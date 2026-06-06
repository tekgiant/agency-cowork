"""Base Teams API HTTP client.

Provides ``TeamsApiClient`` — wraps ``TeamsSession`` (Playwright-based browser
auth) for read operations and direct ``aiohttp`` + Bearer token for writes.

Read operations (list chats, list messages, etc.) go through the browser
context because the ``teams.cloud.microsoft`` proxy requires per-service
Bearer tokens that are only captured during browser page load.

Write operations (send message) can use the direct chatsvc Bearer token
acquired via Azure CLI, which is faster (~200ms vs ~5s browser startup).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("teams.api.client")

# Add parent for rich.auth import
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))

from scripts.rich.auth import TeamsSession
from scripts.chunking import chunk_message, INTER_CHUNK_DELAY

# Base URLs (from HAR traces)
# Region is dynamic — set via TEAMS_CHATSVC_REGION env var or auto-discovered
# from the monitor's 404 Location header. Common values: amer, noam-pilot2, emea.
_CHATSVC_REGION = os.environ.get("TEAMS_CHATSVC_REGION", "amer")
CHATSVC_BASE = f"https://teams.cloud.microsoft/api/chatsvc/{_CHATSVC_REGION}/v1"


def update_chatsvc_region(region: str) -> None:
    """Update the chatsvc base URL with a new region slug."""
    global CHATSVC_BASE, _CHATSVC_REGION
    _CHATSVC_REGION = region
    CHATSVC_BASE = f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1"
    logger.info("CHATSVC_BASE updated to %s", CHATSVC_BASE)

CSA_BASE = "https://teams.cloud.microsoft/api/csa-msft/api"
MT_BASE = "https://teams.cloud.microsoft/api/mt/part/msft/beta"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# User MRI (owner — matches monitor config)
USER_MRI = os.environ.get("TEAMS_USER_MRI", "8:orgid:YOUR_USER_GUID_HERE")

# Send-message headers (for direct aiohttp path)
_SEND_HEADERS = {
    "X-MS-Migration": "True",
    "X-Ms-Test-User": "False",
    "behavioroverride": "redirectAs404",
    "clientinfo": (
        "os=windows; osVer=NT 10.0; proc=x86; lcid=en-us; "
        "deviceType=1; country=us; clientName=skypeteams; "
        "clientVer=1415/26020101120; utcOffset=-08:00; "
        "timezone=America/Los_Angeles"
    ),
}


class TeamsApiClient:
    """Async Teams API client — Playwright for reads, direct HTTP for writes."""

    def __init__(self) -> None:
        self._session: Optional[TeamsSession] = None

    async def connect(self) -> None:
        """Start the browser session (required for read operations)."""
        if self._session is None:
            self._session = TeamsSession()
            await self._session.connect()
            logger.info("TeamsSession connected as %s", self._session.user)

    async def close(self) -> None:
        """Close the browser session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "TeamsApiClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── Read operations (via Playwright browser) ──

    async def get(self, url: str, params: Optional[dict] = None) -> Any:
        """GET request via browser session."""
        if not self._session:
            raise RuntimeError("Not connected — call connect() first")
        full_url = url
        if params:
            qs = urllib.parse.urlencode(params, safe="|")
            full_url = f"{url}?{qs}"
        return await self._session.fetch("GET", full_url)

    async def post(self, url: str, body: Any = None) -> Any:
        """POST request via browser session."""
        if not self._session:
            raise RuntimeError("Not connected — call connect() first")
        return await self._session.fetch("POST", url, body=body)

    # ── Fast send (direct HTTP, no browser needed) ──

    async def send_direct(self, chat_id: str, content: str, html: bool = True) -> dict:
        """Send a message via direct chatsvc HTTP (no browser needed).

        Long messages are automatically split into sequential chunks.
        Uses Azure CLI token — fastest path for sending messages.
        Falls back to browser session if CLI token unavailable.
        """
        chunks = chunk_message(content)

        if len(chunks) == 1:
            return await self._send_one(chat_id, chunks[0], html)

        logger.info("Chunking message into %d parts for %s", len(chunks), chat_id[:30])
        last_result: dict = {}
        for i, chunk in enumerate(chunks):
            last_result = await self._send_one(chat_id, chunk, html)
            if i < len(chunks) - 1:
                await asyncio.sleep(INTER_CHUNK_DELAY)
        return last_result

    async def _send_one(self, chat_id: str, content: str, html: bool = True) -> dict:
        """Send a single message (no chunking)."""
        from .auth import get_token_manager

        tm = get_token_manager()
        try:
            token = await tm.get_token()
        except RuntimeError:
            logger.info("CLI token unavailable, using browser session for send")
            return await self._send_via_session(chat_id, content, html)

        return await self._send_via_http(chat_id, content, html, token)

    async def _send_via_http(
        self, chat_id: str, content: str, html: bool, token: str
    ) -> dict:
        """Direct aiohttp POST to chatsvc (same as monitor's _reply_to_chat)."""
        import aiohttp

        encoded = urllib.parse.quote(chat_id, safe="")
        url = f"{CHATSVC_BASE}/users/ME/conversations/{encoded}/messages"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        if html and not content.strip().startswith("<"):
            content = content.replace("\n", "<br/>")
            content = f"<p>{content}</p>"

        payload = {
            "id": "-1",
            "type": "Message",
            "conversationid": chat_id,
            "conversationLink": f"{CHATSVC_BASE}/users/ME/conversations/{encoded}",
            "from": USER_MRI,
            "fromUserId": USER_MRI,
            "composetime": now,
            "originalarrivaltime": now,
            "content": content,
            "messagetype": "RichText/Html" if html else "Text",
            "contenttype": "Text",
            "imdisplayname": os.environ.get("TEAMS_DISPLAY_NAME", "Agent"),
            "clientmessageid": str(uuid.uuid4().int)[:19],
            "callId": "",
            "state": 0,
            "version": "0",
            "amsreferences": [],
            "properties": {
                "importance": "", "subject": "", "title": "",
                "cards": "[]", "links": "[]", "mentions": "[]",
                "onbehalfof": None, "files": "[]",
                "policyViolation": None, "formatVariant": "TEAMS",
            },
            "crossPostChannels": [],
        }

        headers = {**_SEND_HEADERS, "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status in (200, 201, 202):
                    logger.info("Message sent to %s via direct HTTP", chat_id[:30])
                    return {"status": "sent", "code": resp.status}
                text = await resp.text()

                # ── Auto-discover region from 404 "different cloud" ──
                if resp.status == 404 and "different cloud" in text.lower():
                    import re as _re
                    location = resp.headers.get("Location", "")
                    source = location or text
                    m = _re.search(r"/api/chatsvc/([a-z0-9_-]+)/v\d", source, _re.IGNORECASE)
                    if m:
                        new_region = m.group(1)
                        update_chatsvc_region(new_region)
                        os.environ["TEAMS_CHATSVC_REGION"] = new_region
                        logger.info("Auto-discovered chatsvc region: %s — retrying", new_region)

                        # Rebuild URL and conversationLink with correct region
                        retry_url = f"{CHATSVC_BASE}/users/ME/conversations/{encoded}/messages"
                        payload["conversationLink"] = f"{CHATSVC_BASE}/users/ME/conversations/{encoded}"
                        async with session.post(retry_url, json=payload, headers=headers) as retry_resp:
                            if retry_resp.status in (200, 201, 202):
                                logger.info("Message sent to %s via direct HTTP (region=%s)", chat_id[:30], new_region)
                                return {"status": "sent", "code": retry_resp.status}
                            retry_text = await retry_resp.text()
                            raise ApiError(retry_resp.status, retry_text[:500])

                raise ApiError(resp.status, text[:500])

    async def _send_via_session(
        self, chat_id: str, content: str, html: bool
    ) -> dict:
        """Send via browser session (slower but guaranteed auth)."""
        encoded = urllib.parse.quote(chat_id, safe="")
        url = f"{CHATSVC_BASE}/users/ME/conversations/{encoded}/messages"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        if html and not content.strip().startswith("<"):
            content = content.replace("\n", "<br/>")
            content = f"<p>{content}</p>"

        payload = {
            "id": "-1", "type": "Message",
            "conversationid": chat_id,
            "composetime": now, "originalarrivaltime": now,
            "content": content,
            "messagetype": "RichText/Html" if html else "Text",
            "contenttype": "Text",
            "imdisplayname": os.environ.get("TEAMS_DISPLAY_NAME", "Agent"),
            "clientmessageid": str(uuid.uuid4().int)[:19],
            "properties": {"formatVariant": "TEAMS", "cards": "[]",
                           "links": "[]", "mentions": "[]", "files": "[]"},
        }

        if not self._session:
            await self.connect()
        return await self._session.fetch("POST", url, body=payload)

    # ── URL builders ──

    @staticmethod
    def chatsvc_url(path: str) -> str:
        return CHATSVC_BASE + path

    @staticmethod
    def csa_url(path: str) -> str:
        return CSA_BASE + path

    @staticmethod
    def graph_url(path: str) -> str:
        return GRAPH_BASE + path

    @staticmethod
    def encode_conv_id(conv_id: str) -> str:
        return urllib.parse.quote(conv_id, safe="")

    # ── Graph API operations (direct HTTP, no browser needed) ──

    async def graph_post(self, path: str, body: Any) -> dict:
        """POST to Microsoft Graph API using az CLI token.

        Args:
            path: Graph API path (e.g., /teams/{id}/channels/{id}/messages).
            body: JSON-serializable payload.

        Returns:
            API response dict.
        """
        import httpx
        from .auth import get_graph_token_manager

        tm = get_graph_token_manager()
        token = await tm.get_token()
        url = self.graph_url(path)
        headers = {"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code in (200, 201, 202):
                return resp.json()
            raise ApiError(resp.status_code, resp.text[:500])

    async def graph_get(self, path: str, params: Optional[dict] = None) -> Any:
        """GET from Microsoft Graph API using az CLI token.

        Args:
            path: Graph API path.
            params: Optional query parameters.

        Returns:
            API response (parsed JSON).
        """
        import httpx
        from .auth import get_graph_token_manager

        tm = get_graph_token_manager()
        token = await tm.get_token()
        url = self.graph_url(path)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise ApiError(resp.status_code, resp.text[:500])


    async def chatsvc_get_direct(
        self, path: str, params: Optional[dict] = None,
    ) -> Any:
        """GET from chatsvc API using Azure CLI token (no browser needed).

        Uses the Teams Chat Service v2 (chatsvc) API with a token for
        ``https://ic3.teams.office.com``.  Designed for operations that
        only require read-access to channel/thread messages.

        Args:
            path: chatsvc API path (appended to CHATSVC_BASE).
            params: Optional query parameters.

        Returns:
            Parsed JSON response.
        """
        import httpx
        from .auth import get_token_manager

        tm = get_token_manager()
        token = await tm.get_token()
        url = self.chatsvc_url(path)
        if params:
            qs = urllib.parse.urlencode(params, safe="|")
            url = f"{url}?{qs}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise ApiError(resp.status_code, resp.text[:500])


class ApiError(Exception):
    def __init__(self, status: int, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail[:200]}")
