"""Trouter WebSocket client for Teams real-time notifications.

Connects to the Teams Trouter service via WebSocket, authenticates using
Bearer JWT tokens, and receives real-time message push notifications.
Uses a Socket.IO-style frame parser (Trouter protocol subset).

Protocol flow (from HAR trace analysis):
1. Health probe: GET https://go-msit.trouter.teams.microsoft.com/?check=...
2. WebSocket:    wss://df-*.trouter-df.teams.microsoft.com/v4/c?tc=...&epid=...
3. Auth:         Client sends user.authenticate → Server replies trouter.connected
4. Register:     POST registrar/prod/V2/registrations (binds session to Trouter path)
5. Listen:       Server pushes EventMessage payloads via "3:::" frames
6. Heartbeat:    ping/pong events to keep connection alive
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

import aiohttp
import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger("monitor.trouter")


def _ws_is_closed(ws) -> bool:
    """Check if a websocket connection is closed, compatible with websockets 12–16+.

    websockets <13 used ``ws.closed`` (bool property).
    websockets 13+ removed it; use ``ws.protocol.state`` or ``ws.close_code``.
    """
    if hasattr(ws, "closed"):
        return ws.closed
    # websockets 13+ (including 16.0): check close_code or protocol state
    try:
        from websockets.protocol import State
        return ws.protocol.state is State.CLOSED
    except (AttributeError, ImportError):
        pass
    # Fallback: close_code is set once the connection is closed
    return ws.close_code is not None


# Socket.IO frame types used by Trouter
_FRAME_CONNECT = "1::"
_FRAME_EVENT = "5:::"    # Named events: auth, connected, ping
_FRAME_MESSAGE = "3:::"  # Push messages (Trouter message delivery)
_FRAME_ACK = "6:::"      # Acknowledgments (pong responses)


@dataclass
class TrouterSession:
    """Holds state for an active Trouter WebSocket session."""
    ws: Optional[WebSocketClientProtocol] = None
    session_url: str = ""        # surl from trouter.connected
    registrar_url: str = ""      # registrar URL for binding
    registration_id: str = ""    # UUID for this registration
    connect_params: str = ""     # reconnect query params
    connected: bool = False
    last_heartbeat: float = 0.0
    frame_counter: int = 0


@dataclass
class EventMessage:
    """Parsed Trouter EventMessage (incoming Teams message)."""
    message_id: str = ""
    conversation_id: str = ""
    content: str = ""
    sender_mri: str = ""
    sender_name: str = ""
    compose_time: str = ""
    resource_type: str = ""
    raw: dict = field(default_factory=dict)


# Type for message callback
MessageCallback = Callable[[EventMessage], Awaitable[None]]


def _parse_conversation_id(resource: dict) -> str:
    """Extract conversation ID from resource.conversationLink or resource.to."""
    # Try conversationLink first: ".../conversations/48:notes"
    conv_link = resource.get("conversationLink", "")
    if "/conversations/" in conv_link:
        return conv_link.split("/conversations/")[-1]
    # Fall back to "to" field
    return resource.get("to", "")


def _parse_sender_mri(resource: dict) -> str:
    """Extract sender MRI from resource.from."""
    from_field = resource.get("from", "")
    # Format: "https://.../.../contacts/8:orgid:GUID" → extract "8:orgid:GUID"
    if "/contacts/" in from_field:
        return from_field.split("/contacts/")[-1]
    return from_field


def parse_event_message(body_str: str) -> Optional[EventMessage]:
    """Parse an EventMessage from a Trouter "3:::" frame body.

    The body is a JSON string containing the EventMessage. Some bodies are
    double-encoded (JSON string inside JSON) — handle both cases.
    """
    try:
        data = json.loads(body_str) if isinstance(body_str, str) else body_str
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse EventMessage body: %s", body_str[:200])
        return None

    if data.get("type") != "EventMessage":
        return None

    resource_type = data.get("resourceType", "")
    if resource_type != "NewMessage":
        return None

    resource = data.get("resource", {})
    return EventMessage(
        message_id=resource.get("id", ""),
        conversation_id=_parse_conversation_id(resource),
        content=resource.get("content", ""),
        sender_mri=_parse_sender_mri(resource),
        sender_name=resource.get("imdisplayname", ""),
        compose_time=resource.get("composetime", ""),
        resource_type=resource_type,
        raw=data,
    )


def parse_frame(raw: str) -> tuple[str, Optional[dict | str]]:
    """Parse a Socket.IO-style frame from Trouter.

    Frames may include an optional sequence number between the type digit and
    the payload separator, e.g. ``5:1::`` or ``6:::2+["pong"]``.

    Returns (frame_type, payload):
    - "connect", None       for "1::"
    - "event", {name, args} for ``5[:\\d*]::json``
    - "message", {dict}     for "3:::{json}"  (Trouter push)
    - "ack", payload_str    for "6:::..."
    - "unknown", raw_str    for anything else
    """
    if raw.startswith("1::"):
        return "connect", None

    # Event frames: 5:::json  or  5:N::json
    if raw.startswith("5"):
        # Find the payload after the ::  delimiter following the type+optional seq
        m = re.match(r"5(?::[^:]*)?::(.*)", raw, re.DOTALL)
        if m:
            body = m.group(1)
            try:
                payload = json.loads(body)
                return "event", payload
            except json.JSONDecodeError:
                return "event", body

    if raw.startswith("3:::"):
        try:
            payload = json.loads(raw[4:])
            return "message", payload
        except json.JSONDecodeError:
            return "message", raw[4:]

    if raw.startswith("6:::"):
        return "ack", raw[4:]

    return "unknown", raw


class TrouterClient:
    """Async Trouter WebSocket client.

    Usage:
        client = TrouterClient(
            token="Bearer ...",
            on_message=my_handler,
            gateway="go-msit.trouter.teams.microsoft.com",
        )
        await client.connect()
        await client.listen()  # runs until disconnect
    """

    def __init__(
        self,
        token: str,
        on_message: MessageCallback,
        gateway: str = "go-msit.trouter.teams.microsoft.com",
        registrar_url: str = "https://teams.cloud.microsoft/registrar/prod/V2/registrations",
        app_id: str = "AgencyCoworkMonitor",
        heartbeat_interval: int = 30,
    ):
        self.token = token
        self.on_message = on_message
        self.gateway = gateway
        self.registrar_url = registrar_url
        self.app_id = app_id
        self.heartbeat_interval = heartbeat_interval
        self.session = TrouterSession()
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reregistration_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Connect to Trouter WebSocket and authenticate.

        Protocol (from HAR trace):
        1. Open WSS directly to the gateway ``/v4/c`` endpoint
        2. Receive ``1::`` connect frame
        3. Send ``5:::user.authenticate`` with Bearer token in *headers* dict
        4. Receive ``5:N::trouter.connected`` with session URLs
        5. POST Registrar to bind the session path
        """
        import urllib.parse

        epid = str(uuid.uuid4())
        tc = json.dumps({
            "cv": "2026.03.01.1",
            "ua": "TeamsCDL",
            "hr": "",
            "v": "1415/26020101120",
        })
        qs = urllib.parse.urlencode({
            "tc": tc,
            "timeout": "40",
            "epid": epid,
            "ccid": "",
            "dom": "teams.cloud.microsoft",
            "cor_id": str(uuid.uuid4()),
            "con_num": f"{int(time.time() * 1000)}_0",
        })
        ws_url = f"wss://{self.gateway}/v4/c?{qs}"

        # 1. WebSocket connect
        logger.info("Connecting to %s", ws_url[:100])
        self.session.ws = await websockets.connect(
            ws_url,
            additional_headers={
                "Origin": "https://teams.cloud.microsoft",
            },
            ping_interval=None,  # We handle heartbeat ourselves
            max_size=2**22,  # 4MB max frame
        )

        # 2. Wait for connection frame (1::)
        raw = await asyncio.wait_for(self.session.ws.recv(), timeout=10)
        frame_type, _ = parse_frame(str(raw))
        if frame_type != "connect":
            logger.warning("Expected connect frame, got: %s", frame_type)

        # 3. Send auth (matching HAR format exactly)
        auth_payload = json.dumps({
            "name": "user.authenticate",
            "args": [{
                "headers": {
                    "X-Ms-Test-User": "False",
                    "Authorization": f"Bearer {self.token}",
                    "X-MS-Migration": "True",
                },
                "connectparams": {
                    "issuer": "",
                    "scae": "1",
                    "sig": "",
                    "sr": epid,
                    "sp": "",
                    "se": str(int(time.time() + 600) * 1000),
                    "st": str(int(time.time()) * 1000),
                },
            }],
        })
        await self.session.ws.send(f"5:::{auth_payload}")
        logger.info("Sent auth, waiting for trouter.connected...")

        # 4. Wait for trouter.connected (may receive other frames first)
        connected = False
        for _ in range(10):  # up to 10 frames
            raw = await asyncio.wait_for(self.session.ws.recv(), timeout=15)
            frame_type, payload = parse_frame(str(raw))
            if frame_type == "event" and isinstance(payload, dict):
                name = payload.get("name", "")
                if name == "trouter.connected":
                    args = payload.get("args", [{}])
                    if args:
                        info = args[0] if isinstance(args[0], dict) else {}
                        self.session.session_url = info.get("surl", "")
                        self.session.registrar_url = info.get("registrarUrl", self.registrar_url)
                        self.session.connect_params = info.get("connectparams", "")
                    self.session.connected = True
                    self.session.last_heartbeat = time.time()
                    self.session.registration_id = epid
                    connected = True
                    logger.info("Trouter connected, surl=%s", self.session.session_url[:60])
                    break
                elif name == "trouter.message_loss":
                    # Acknowledge message loss (happens on fresh connections)
                    args = payload.get("args", [{}])
                    ack = json.dumps({
                        "name": "trouter.processed_message_loss",
                        "args": args,
                    })
                    await self.session.ws.send(f"5:{self.session.frame_counter}+::{ack}")
                    self.session.frame_counter += 1
                    logger.info("Acknowledged message_loss")

        if not connected:
            raise ConnectionError("Did not receive trouter.connected")

        # 6. Register with Registrar
        await self._register()

    async def _register(self) -> None:
        """Register with the Trouter Registrar service to bind our session.

        Uses ``TeamsCDLWebWorker`` appId and template to receive chat message
        notifications (matching the real Teams web client registration from the
        HAR trace).  Registers with **both** the V3 URL returned by
        ``trouter.connected`` *and* the V2 URL used by the browser client —
        both are needed for reliable message delivery.
        """
        payload = {
            "clientDescription": {
                "appId": "TeamsCDLWebWorker",
                "aesKey": "",
                "languageId": "en-US",
                "platform": "edge",
                "templateKey": "TeamsCDLWebWorker_2.6",
                "platformUIVersion": "1415/26020101120",
            },
            "registrationId": self.session.registration_id,
            "nodeId": "",
            "transports": {
                "TROUTER": [{
                    "context": "",
                    "path": self.session.session_url,
                    "ttl": 3600,
                }]
            },
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Origin": "https://teams.cloud.microsoft",
        }

        # Register with both endpoints for reliable message routing
        reg_urls = []
        server_url = self.session.registrar_url
        if server_url:
            reg_urls.append(server_url)
        # Always include the V2 fallback (used by the browser client)
        v2_url = self.registrar_url
        if v2_url and v2_url != server_url:
            reg_urls.append(v2_url)

        async with aiohttp.ClientSession() as session:
            for reg_url in reg_urls:
                try:
                    async with session.post(reg_url, json=payload, headers=headers) as resp:
                        if resp.status in (200, 202):
                            logger.info("Registered with %s (status=%d)", reg_url[:60], resp.status)
                        else:
                            body = await resp.text()
                            logger.warning("Registrar %s: %d - %s", reg_url[:60], resp.status, body[:200])
                except Exception as e:
                    logger.warning("Registrar %s failed: %s", reg_url[:60], e)

    async def _heartbeat_loop(self) -> None:
        """Send periodic ping to keep the connection alive.

        HAR format: client sends ``5:N+::{"name":"ping"}``
        Server replies with ``6:::N+["pong"]``
        """
        while self._running and self.session.ws and not _ws_is_closed(self.session.ws):
            await asyncio.sleep(self.heartbeat_interval)
            try:
                self.session.frame_counter += 1
                ping = f'5:{self.session.frame_counter}+::{{"name":"ping"}}'
                await self.session.ws.send(ping)
                self.session.last_heartbeat = time.time()
                logger.debug("Sent ping #%d", self.session.frame_counter)
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)
                break

    async def _reregistration_loop(self) -> None:
        """Re-register with the Trouter Registrar before the TTL expires.

        The registration TTL is 3600s (1 hour).  Without proactive renewal,
        messages are silently dropped between TTL expiry and the next
        server-initiated ``trouter.reconnect`` event (up to 20+ minutes).
        Re-registering every 45 minutes keeps the binding alive continuously.
        """
        interval = 45 * 60  # 45 minutes — well within the 1-hour TTL
        while self._running and self.session.ws and not _ws_is_closed(self.session.ws):
            await asyncio.sleep(interval)
            try:
                await self.register()
                logger.info("Proactive re-registration succeeded")
            except Exception as e:
                logger.warning("Proactive re-registration failed: %s — will retry in %ds", e, interval)

    async def listen(self) -> None:
        """Main listen loop. Processes incoming frames until disconnect."""
        if not self.session.ws:
            raise RuntimeError("Not connected — call connect() first")

        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._reregistration_task = asyncio.create_task(self._reregistration_loop())

        try:
            async for raw_msg in self.session.ws:
                if not self._running:
                    break

                raw = str(raw_msg)
                frame_type, payload = parse_frame(raw)
                logger.debug("Frame: type=%s len=%d", frame_type, len(raw))

                if frame_type == "event" and isinstance(payload, dict):
                    name = payload.get("name", "")
                    if name == "ping":
                        # Respond to server ping
                        self.session.frame_counter += 1
                        await self.session.ws.send(
                            f'6:::{self.session.frame_counter}["pong"]'
                        )
                        self.session.last_heartbeat = time.time()
                    elif name == "trouter.message_loss":
                        logger.warning("Message loss detected")
                        args = payload.get("args", [{}])
                        ack = json.dumps({
                            "name": "trouter.processed_message_loss",
                            "args": args,
                        })
                        self.session.frame_counter += 1
                        await self.session.ws.send(
                            f"5:{self.session.frame_counter}+::{ack}"
                        )
                    else:
                        logger.debug("Event: %s", name)

                elif frame_type == "message" and isinstance(payload, dict):
                    # Trouter push message — send ACK, then process
                    msg_id = payload.get("id", "")
                    if msg_id and self.session.ws:
                        ack = json.dumps({
                            "id": msg_id,
                            "status": 200,
                            "headers": {},
                            "body": "",
                        })
                        await self.session.ws.send(f"3:::{ack}")

                    # Extract body and parse EventMessage
                    body = payload.get("body", "")
                    if isinstance(body, str):
                        try:
                            body = json.loads(body)
                        except json.JSONDecodeError:
                            pass

                    if isinstance(body, dict):
                        event_msg = parse_event_message(body)
                    else:
                        event_msg = parse_event_message(body)

                    if event_msg:
                        try:
                            await self.on_message(event_msg)
                        except Exception as e:
                            logger.error("Message handler error: %s", e, exc_info=True)

                elif frame_type == "connect":
                    logger.debug("Received connect frame (reconnect?)")

                elif frame_type == "ack":
                    logger.debug("Received ack: %s", str(payload)[:100])

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("WebSocket closed: code=%s reason=%s", e.code, e.reason)
        except asyncio.CancelledError:
            logger.info("Listen loop cancelled")
        finally:
            self._running = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            if self._reregistration_task:
                self._reregistration_task.cancel()

    async def disconnect(self) -> None:
        """Gracefully disconnect the WebSocket."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._reregistration_task:
            self._reregistration_task.cancel()
        if self.session.ws and not _ws_is_closed(self.session.ws):
            await self.session.ws.close()
            logger.info("Disconnected from Trouter")
        self.session.connected = False

    def update_token(self, new_token: str) -> None:
        """Update the auth token for the next connection/registration."""
        self.token = new_token

    async def register(self) -> None:
        """Public method to trigger re-registration with the Trouter Registrar.

        Called proactively by ``_reregistration_loop()`` and after token refresh
        in ``service.py`` to prevent silent message loss when the registration
        TTL (3600s) expires.
        """
        if not self._running or not self.session.ws or _ws_is_closed(self.session.ws):
            logger.debug("register() called while not connected — skipping")
            return
        await self._register()
