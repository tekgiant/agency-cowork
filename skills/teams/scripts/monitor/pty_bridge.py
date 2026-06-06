"""Async Python client for the Agency PTY Bridge (named pipe).

Connects to the Node.js PTY bridge via named pipe and provides an async
interface for spawning sessions, injecting prompts, and receiving structured
events (assistant messages, turn ends, errors).

Usage:
    bridge = PtyBridge()
    await bridge.start()
    await bridge.spawn_session("conv-123", resume_id="abc-uuid")
    response = await bridge.write_prompt("conv-123", "What is 2+2?")
    await bridge.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("monitor.pty_bridge")

IS_WIN = sys.platform == "win32"
PIPE_PATH = r"\\.\pipe\agency-pty-bridge" if IS_WIN else "/tmp/agency-pty-bridge.sock"
DISCOVERY_FILE = Path.home() / ".agency-cowork" / "pty-bridge.json"
BRIDGE_SCRIPT = Path(__file__).resolve().parent / "pty-bridge" / "bridge.js"

# How long to wait for events after writing a prompt
DEFAULT_TURN_TIMEOUT = 900  # 15 minutes


class StaleSessionError(Exception):
    """Raised when a session shows no activity within the activity timeout.

    This typically indicates session contention — another client is using
    the same PTY session, so the bridge's prompt was consumed by the
    interactive terminal instead of the agent.
    """
    pass


@dataclass
class SessionInfo:
    """Tracks local state for a PTY session."""
    session_key: str
    resume_id: str = ""
    ready: bool = False
    busy: bool = False
    # Queue for turn_end events — write_prompt awaits this
    turn_end_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # Queue for all events (for consumers that want raw event stream)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # Accumulated assistant messages for current turn
    message_accumulator: list[str] = field(default_factory=list)


class PtyBridge:
    """Async client for the PTY bridge named pipe."""

    def __init__(self, pipe_path: str = PIPE_PATH):
        self._pipe_path = pipe_path
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._sessions: dict[str, SessionInfo] = {}
        self._connected = False
        self._read_task: Optional[asyncio.Task] = None
        self._bridge_proc: Optional[subprocess.Popen] = None
        self._health_task: Optional[asyncio.Task] = None
        self._global_event_queue: asyncio.Queue = asyncio.Queue()
        self._client_type: str = "monitor"
        self._shutting_down = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._on_reconnect: Optional[callable] = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def sessions(self) -> dict[str, SessionInfo]:
        return dict(self._sessions)

    async def start(self, client_type: str = "monitor", start_bridge: bool = True) -> None:
        """Connect to the PTY bridge. Optionally start the bridge if not running."""
        self._client_type = client_type
        self._shutting_down = False
        # Try connecting to existing bridge first
        connected = await self._try_connect()
        if not connected and start_bridge:
            logger.info("Bridge not running — starting it")
            await self._start_bridge_process()
            # Wait for bridge to be ready (up to 10s)
            for _ in range(20):
                await asyncio.sleep(0.5)
                connected = await self._try_connect()
                if connected:
                    break
            if not connected:
                raise RuntimeError("Failed to connect to PTY bridge after starting it")

        if not connected:
            raise RuntimeError(f"Cannot connect to PTY bridge at {self._pipe_path}")

        # Identify ourselves
        await self._send({"type": client_type})
        logger.info("Connected to PTY bridge as %s", client_type)

        # Start background reader
        self._read_task = asyncio.create_task(self._read_loop())

        # Start health check
        self._health_task = asyncio.create_task(self._health_loop())

    async def _try_connect(self) -> bool:
        """Attempt to connect to the named pipe. Returns True on success."""
        try:
            if IS_WIN:
                reader, writer = await self._connect_windows_pipe()
            else:
                reader, writer = await asyncio.open_unix_connection(self._pipe_path)

            self._reader = reader
            self._writer = writer
            self._connected = True
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            logger.debug("Connection attempt failed: %s", e)
            return False

    async def _connect_windows_pipe(self):
        """Connect to a Windows named pipe using ProactorEventLoop."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2**16)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.create_pipe_connection(
            lambda: protocol, self._pipe_path
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer

    async def _start_bridge_process(self) -> None:
        """Start the Node.js bridge as a subprocess."""
        node_path = os.environ.get("AGENCY_BRIDGE_NODE") or shutil.which("node")
        if not node_path:
            raise RuntimeError("Node.js not found on PATH — required for PTY bridge")

        bridge_script = Path(os.environ.get("AGENCY_BRIDGE_SCRIPT", str(BRIDGE_SCRIPT)))
        if not bridge_script.exists():
            raise RuntimeError(f"Bridge script not found: {bridge_script}")

        child_env = dict(os.environ)
        node_path_override = os.environ.get("AGENCY_BRIDGE_NODE_PATH")
        if node_path_override:
            child_env["NODE_PATH"] = node_path_override
        if os.environ.get("AGENCY_BRIDGE_ELECTRON_RUN_AS_NODE") == "1":
            child_env["ELECTRON_RUN_AS_NODE"] = "1"

        logger.info("Starting PTY bridge: %s %s", node_path, bridge_script)
        self._bridge_proc = subprocess.Popen(
            [node_path, str(bridge_script)],
            cwd=str(bridge_script.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0,
        )
        logger.info("Bridge process started (PID %d)", self._bridge_proc.pid)

    async def _read_loop(self) -> None:
        """Continuously read NDJSON events from the bridge."""
        assert self._reader is not None
        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    logger.warning("Bridge connection closed")
                    self._connected = False
                    break
                try:
                    evt = json.loads(line.decode("utf-8").strip())
                    await self._handle_event(evt)
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Read loop error: %s", e)
            self._connected = False

        # Unblock any sessions waiting on turn_end (they'll get None → RuntimeError)
        for session in self._sessions.values():
            try:
                session.turn_end_queue.put_nowait(None)
            except Exception:
                pass

        # Auto-reconnect unless we're shutting down
        if not self._shutting_down:
            self._schedule_reconnect()

    async def _handle_event(self, evt: dict[str, Any]) -> None:
        """Route an event from the bridge to the appropriate session."""
        event_type = evt.get("event", "")
        session_key = evt.get("sessionKey", "")

        # Global events
        if event_type == "pong":
            return
        if event_type == "status":
            await self._global_event_queue.put(evt)
            return

        # Session-specific events
        session = self._sessions.get(session_key)

        if event_type == "spawned":
            if session:
                logger.info("Session %s spawned", session_key)
                await session.event_queue.put(evt)
            return

        if event_type == "ready":
            if session:
                session.ready = True
                await session.event_queue.put(evt)
            logger.info("Session %s ready", session_key)
            return

        if event_type == "assistant_message":
            if session:
                content = evt.get("content", "")
                session.message_accumulator.append(content)
                await session.event_queue.put(evt)
            return

        if event_type == "turn_end":
            if session:
                session.busy = False
                response = evt.get("response", "")
                await session.turn_end_queue.put(response)
                await session.event_queue.put(evt)
            logger.info("Session %s turn_end (%d chars)", session_key,
                        len(evt.get("response", "")))
            return

        if event_type == "error":
            if session:
                await session.event_queue.put(evt)
            logger.warning("Session %s error: %s", session_key, evt.get("message", ""))
            return

        if event_type == "exit":
            if session:
                session.ready = False
                session.busy = False
                await session.event_queue.put(evt)
                # Unblock anyone waiting on turn_end
                await session.turn_end_queue.put(None)
            logger.info("Session %s exited (code=%s)", session_key, evt.get("exitCode"))
            return

        # Forward anything else to global queue
        await self._global_event_queue.put(evt)

    async def _health_loop(self) -> None:
        """Periodic health check via ping/pong. Triggers reconnect on failure."""
        try:
            while not self._shutting_down:
                await asyncio.sleep(30)
                if self._connected:
                    try:
                        await self._send({"cmd": "ping"})
                    except Exception as e:
                        logger.warning("Health ping failed: %s — triggering reconnect", e)
                        self._connected = False
                        self._schedule_reconnect()
                        return
        except asyncio.CancelledError:
            pass

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt if not already reconnecting."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    # After this many consecutive failed connection attempts, restart the
    # bridge process instead of just retrying the pipe connection.
    _RESTART_AFTER_ATTEMPTS = 5
    # Maximum number of bridge restarts before giving up.
    _MAX_RESTARTS = 10

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect to the bridge with exponential backoff.

        This loop MUST be bulletproof — any unhandled exception here would
        leave the service alive but unable to process dispatches.  Wrap the
        entire body in try/except BaseException to catch even asyncio
        internals and ProactorEventLoop errors on Windows.
        """
        _BACKOFF = [2, 5, 10, 20, 30, 60]  # seconds
        attempt = 0
        while not self._shutting_down:
            try:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                logger.info("Bridge reconnect attempt %d in %ds...", attempt + 1, delay)
                await asyncio.sleep(delay)

                if self._shutting_down:
                    return

                # Clean up stale connection — protect against ProactorEventLoop errors
                self._safe_close_writer()
                self._reader = None
                self._writer = None

                try:
                    connected = await self._try_connect()
                    if connected:
                        await self._send({"type": self._client_type})
                        # Clear stale sessions — prompt_queue will re-spawn on demand
                        self._sessions.clear()
                        # Restart read and health loops
                        if self._read_task and not self._read_task.done():
                            self._read_task.cancel()
                        self._read_task = asyncio.create_task(self._read_loop())
                        if self._health_task and not self._health_task.done():
                            self._health_task.cancel()
                        self._health_task = asyncio.create_task(self._health_loop())
                        logger.info("Reconnected to PTY bridge (attempt %d)", attempt + 1)
                        # Fire reconnect callback (e.g., re-warm sessions)
                        if self._on_reconnect:
                            try:
                                result = self._on_reconnect()
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                logger.warning("Reconnect callback failed: %s", e)
                        return
                except Exception as e:
                    logger.info("Reconnect attempt %d failed: %s", attempt + 1, e)

                attempt += 1

            except asyncio.CancelledError:
                logger.info("Reconnect loop cancelled")
                return
            except BaseException as e:
                # Catch EVERYTHING — including OSError from ProactorEventLoop,
                # RuntimeError from closed event loops, etc.
                logger.error("Reconnect loop unexpected error (attempt %d): %s: %s",
                             attempt + 1, type(e).__name__, e)
                attempt += 1
                # Sleep a bit before retrying (can't use asyncio.sleep if loop is broken)
                try:
                    await asyncio.sleep(5)
                except Exception:
                    import time
                    time.sleep(5)

        logger.warning("Reconnect loop stopped (shutting down)")

    def _safe_close_writer(self) -> None:
        """Close the writer transport without risking ProactorEventLoop crashes."""
        if not self._writer:
            return
        try:
            transport = self._writer.transport
            if transport and not transport.is_closing():
                transport.close()
        except Exception:
            pass
        self._writer = None

    async def _restart_bridge_process(self) -> None:
        """Kill a stale bridge process (if any) and start a fresh one."""
        # Terminate existing bridge process if we spawned one
        if self._bridge_proc:
            try:
                self._bridge_proc.terminate()
                self._bridge_proc.wait(timeout=5)
                logger.info("Terminated stale bridge process (PID %d)", self._bridge_proc.pid)
            except Exception as e:
                logger.debug("Stale bridge cleanup: %s", e)
            self._bridge_proc = None

        # Also check the discovery file for an externally-started bridge
        if DISCOVERY_FILE.exists():
            try:
                info = json.loads(DISCOVERY_FILE.read_text())
                old_pid = info.get("pid")
                if old_pid:
                    # On Windows os.kill() calls TerminateProcess for any
                    # signal other than CTRL_C/CTRL_BREAK, so SIGTERM works.
                    os.kill(old_pid, signal.SIGTERM)
                    logger.info("Killed stale bridge from discovery file (PID %d)", old_pid)
            except (ProcessLookupError, PermissionError, OSError):
                pass  # already dead
            except Exception as e:
                logger.debug("Discovery file cleanup: %s", e)

        try:
            await self._start_bridge_process()
        except Exception as e:
            logger.error("Failed to restart bridge process: %s", e)

    async def _send(self, obj: dict) -> None:
        """Send a JSON command to the bridge."""
        if not self._writer:
            raise RuntimeError("Not connected to bridge")
        line = json.dumps(obj) + "\n"
        try:
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            self._connected = False
            raise RuntimeError(f"Bridge send failed (pipe broken): {e}") from e

    # ── Public API ───────────────────────────────────────────────────────────

    async def spawn_session(
        self,
        session_key: str,
        resume_id: str = "",
        cwd: str = "",
        env: Optional[dict[str, str]] = None,
        wait_ready: bool = True,
        ready_timeout: float = 120,
    ) -> SessionInfo:
        """Spawn a new PTY session in the bridge.

        Args:
            session_key: Unique key for this session (e.g., conversation ID hash).
            resume_id: Copilot session ID to resume (optional).
            cwd: Working directory for the CLI process.
            env: Additional environment variables.
            wait_ready: If True, wait until the TUI is ready for input.
            ready_timeout: Seconds to wait for ready signal.

        Returns:
            SessionInfo for the new session.
        """
        # Create local session tracking
        info = SessionInfo(session_key=session_key, resume_id=resume_id)
        self._sessions[session_key] = info

        # Send spawn command
        cmd = {"cmd": "spawn", "sessionKey": session_key}
        if resume_id:
            cmd["resumeId"] = resume_id
        if cwd:
            cmd["cwd"] = cwd
        if env:
            cmd["env"] = env
        await self._send(cmd)

        if wait_ready:
            # Wait for the ready event
            deadline = time.monotonic() + ready_timeout
            while time.monotonic() < deadline:
                try:
                    evt = await asyncio.wait_for(
                        info.event_queue.get(), timeout=min(5, deadline - time.monotonic())
                    )
                    if evt.get("event") == "ready":
                        break
                    if evt.get("event") == "exit":
                        raise RuntimeError(
                            f"Session {session_key} exited during startup "
                            f"(code={evt.get('exitCode')})"
                        )
                    if evt.get("event") == "error":
                        raise RuntimeError(
                            f"Session {session_key} error during startup: "
                            f"{evt.get('message')}"
                        )
                except asyncio.TimeoutError:
                    continue
            else:
                raise TimeoutError(
                    f"Session {session_key} did not become ready within {ready_timeout}s"
                )

        logger.info("Session %s spawned (resume=%s, ready=%s)",
                     session_key, resume_id or "new", info.ready)
        return info

    async def write_prompt(
        self,
        session_key: str,
        prompt: str,
        timeout: float = DEFAULT_TURN_TIMEOUT,
        activity_timeout: float = 0,
    ) -> str:
        """Write a prompt to a session and wait for the turn to complete.

        Args:
            session_key: The session to write to.
            prompt: The prompt text to inject.
            timeout: Seconds to wait for turn_end (total).
            activity_timeout: If > 0, require at least one assistant_message
                within this many seconds.  If no activity is detected, raise
                StaleSessionError (likely session contention).

        Returns:
            The accumulated assistant response text.

        Raises:
            KeyError: If session_key doesn't exist.
            TimeoutError: If the turn doesn't complete within timeout.
            StaleSessionError: If no activity within activity_timeout (contention).
            RuntimeError: If the session exits mid-turn.
        """
        info = self._sessions.get(session_key)
        if not info:
            raise KeyError(f"Session {session_key} not found")

        if not info.ready:
            raise RuntimeError(f"Session {session_key} not ready for input")

        # Clear any stale turn_end events
        while not info.turn_end_queue.empty():
            try:
                info.turn_end_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Reset accumulator
        info.message_accumulator = []
        info.busy = True

        # Send write command
        await self._send({"cmd": "write", "sessionKey": session_key, "prompt": prompt})

        # ── Dual-timeout: activity detection + full turn timeout ─────────
        use_activity_check = 0 < activity_timeout < timeout

        if use_activity_check:
            # Phase 1: Wait up to activity_timeout for any sign of life.
            # If turn_end arrives quickly, great — return immediately.
            # If nothing comes, check whether assistant messages arrived.
            try:
                response = await asyncio.wait_for(
                    info.turn_end_queue.get(), timeout=activity_timeout,
                )
            except asyncio.TimeoutError:
                if not info.message_accumulator:
                    # No activity at all — session is likely contended
                    info.busy = False
                    raise StaleSessionError(
                        f"Session {session_key}: no activity within "
                        f"{activity_timeout:.0f}s — possible session contention "
                        f"(another client may be using this session)"
                    )
                # Activity detected — extend to full remaining timeout
                logger.info(
                    "Session %s: activity detected (%d messages) during "
                    "stale-check window, extending to full timeout",
                    session_key, len(info.message_accumulator),
                )
                remaining = timeout - activity_timeout
                try:
                    response = await asyncio.wait_for(
                        info.turn_end_queue.get(), timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    info.busy = False
                    raise TimeoutError(
                        f"Session {session_key}: prompt timed out after {timeout}s"
                    )
        else:
            # Original single-timeout path
            try:
                response = await asyncio.wait_for(
                    info.turn_end_queue.get(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                info.busy = False
                raise TimeoutError(
                    f"Session {session_key}: prompt timed out after {timeout}s"
                )

        if response is None:
            # Session exited
            raise RuntimeError(f"Session {session_key} exited while processing prompt")

        # If bridge returned empty response, fall back to Python-side accumulator
        # (bridge accumulator can miss content from tool-call turns)
        if not response.strip() and info.message_accumulator:
            response = "".join(info.message_accumulator)
            logger.info(
                "Session %s: using Python-side accumulator (%d chars) — bridge response was empty",
                session_key, len(response),
            )

        info.busy = False
        return response

    async def kill_session(self, session_key: str) -> None:
        """Kill a specific PTY session."""
        await self._send({"cmd": "kill", "sessionKey": session_key})
        self._sessions.pop(session_key, None)

    async def get_status(self) -> dict:
        """Request status from the bridge."""
        # Clear queue
        while not self._global_event_queue.empty():
            try:
                self._global_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        await self._send({"cmd": "status"})
        try:
            evt = await asyncio.wait_for(self._global_event_queue.get(), timeout=5)
            return evt
        except asyncio.TimeoutError:
            return {"sessions": []}

    async def adopt_active_sessions(self) -> int:
        """Query the bridge for active sessions and register any not already tracked.

        Used on startup/reconnect when the bridge may have sessions that
        survived a Python-side crash.  Returns the number of sessions adopted.
        """
        if not self._connected:
            return 0
        try:
            status = await self.get_status()
        except Exception as e:
            logger.warning("adopt_active_sessions: failed to query bridge: %s", e)
            return 0

        bridge_sessions = status.get("sessions", [])
        adopted = 0
        for s in bridge_sessions:
            skey = s.get("sessionKey", "")
            if not skey or skey in self._sessions:
                continue
            info = SessionInfo(session_key=skey)
            info.ready = bool(s.get("ready", False))
            info.busy = bool(s.get("busy", False))
            self._sessions[skey] = info
            adopted += 1
            logger.info(
                "Adopted orphaned session %s (ready=%s, busy=%s, pid=%s)",
                skey, info.ready, info.busy, s.get("pid"),
            )
        if adopted:
            logger.info("Adopted %d active session(s) from bridge", adopted)
        return adopted

    async def shutdown(self) -> None:
        """Disconnect from the bridge and optionally stop it."""
        self._shutting_down = True
        self._connected = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        self._sessions.clear()
        logger.info("PTY bridge client shut down")

    async def shutdown_bridge(self) -> None:
        """Send shutdown command to the bridge process, then disconnect."""
        try:
            await self._send({"cmd": "shutdown"})
        except Exception:
            pass
        await self.shutdown()
        if self._bridge_proc:
            try:
                self._bridge_proc.terminate()
                self._bridge_proc.wait(timeout=5)
            except Exception:
                pass
        logger.info("Bridge process stopped")
