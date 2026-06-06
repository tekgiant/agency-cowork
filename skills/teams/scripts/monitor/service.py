"""Teams Monitor Service -- main entry point.

Orchestrates the auth lifecycle, Trouter WebSocket connection, message
handler, and reconnection logic. Runs as a long-lived background process.

Usage:
    python -m scripts.monitor.service enable   # Enable with security warning
    python -m scripts.monitor.service start     # Start listening (must be enabled)
    python -m scripts.monitor.service stop      # Stop the running service
    python -m scripts.monitor.service disable   # Disable and stop
    python -m scripts.monitor.service status    # Show service status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Add parent paths for imports
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_TEAMS_ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_TEAMS_ROOT))

from scripts.monitor.config import (
    MonitorConfig, GlobalConfig, WorkspaceConfig,
    load_global_config, load_config, save_global_config,
    set_enabled, assemble_monitor_config, _normalise_workspace_key,
)
from scripts.monitor.trouter_client import TrouterClient
from scripts.monitor.message_handler import MessageHandler, set_chatsvc_token, set_chatsvc_region, set_reply_prefix, _get_cli_binary, _reply_to_chat, matches_keyword, matches_sender, strip_html, probe_chatsvc_region, get_detected_identity
from scripts.api.auth import TokenManager, get_token_manager, _MAX_REFRESH_BUFFER_SECONDS

# Paths
_MONITOR_DIR = _TEAMS_ROOT / "monitor"
_PID_FILE = _MONITOR_DIR / "monitor.pid"
_LOCK_FILE = _MONITOR_DIR / "monitor.lock"
_LOG_DIR = _TEAMS_ROOT / "logs"
_LIFECYCLE_FILE = _LOG_DIR / "monitor-lifecycle.jsonl"
_STARTUP_LOG = _LOG_DIR / "monitor-startup.log"
_LIFECYCLE_MAX_ENTRIES = 500

# Singleton lock state -- held for the lifetime of the foreground process
_lock_fd = None

logger = logging.getLogger("monitor.service")


# ---------------------------------------------------------------------------
# Lifecycle journal -- append-only JSONL for start/stop/crash/stale-pid events
# ---------------------------------------------------------------------------

def _log_lifecycle(event: str, **kwargs) -> None:
    """Append a lifecycle event to monitor-lifecycle.jsonl.

    Each line is a JSON object with ``event``, ``pid``, ``ts``, and any
    additional keyword args (e.g. ``reason``, ``error``, ``traceback``).
    Rotates automatically when the file exceeds _LIFECYCLE_MAX_ENTRIES.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": event,
        "pid": os.getpid(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **kwargs,
    }
    try:
        with open(_LIFECYCLE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _rotate_lifecycle()
    except OSError:
        pass  # best-effort -- don't crash the service over logging


def _rotate_lifecycle() -> None:
    """Keep only the last _LIFECYCLE_MAX_ENTRIES lines (atomic replace)."""
    try:
        lines = _LIFECYCLE_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > _LIFECYCLE_MAX_ENTRIES:
            import tempfile
            tmp = _LIFECYCLE_FILE.with_suffix(".tmp")
            tmp.write_text(
                "\n".join(lines[-_LIFECYCLE_MAX_ENTRIES:]) + "\n",
                encoding="utf-8",
            )
            tmp.replace(_LIFECYCLE_FILE)  # atomic on same filesystem
    except OSError:
        pass


def _setup_logging() -> None:
    """Configure logging to file and stderr."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / "monitor-service.log"

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    fmt.converter = time.gmtime

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def _write_pid() -> None:
    """Write current PID to the PID file."""
    _MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))
    logger.info("PID %d written to %s", os.getpid(), _PID_FILE)


def _read_pid() -> int | None:
    """Read the PID from the PID file, or None if not found."""
    if _PID_FILE.exists():
        try:
            return int(_PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def _is_running(pid: int) -> bool:
    """Check if a process with the given PID is still alive.

    On Windows, OpenProcess can return a valid handle for terminated processes
    that still have outstanding kernel references.  We must call
    GetExitCodeProcess and verify the exit code equals STILL_ACTIVE (259).

    After confirming the PID is alive, we verify its command line contains
    ``monitor.service`` to guard against PID recycling.
    See: https://github.com/ahsi-microsoft/agency-cowork/issues/131
    """
    alive = False
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                alive = exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            pass

    if not alive:
        return False

    # Guard against PID recycling: verify the process is actually our service
    cmdline = _get_process_cmdline(pid)
    if cmdline is not None and "monitor.service" not in cmdline:
        _log_lifecycle("pid-recycled", old_pid=pid, cmdline=cmdline[:200])
        return False
    return True


def _get_process_cmdline(pid: int) -> str | None:
    """Return the command line for *pid*, or None on failure."""
    import subprocess as _sp
    try:
        if sys.platform == "win32":
            out = _sp.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                text=True, timeout=5, stderr=_sp.DEVNULL,
            )
            return out.strip()
        else:
            return _sp.check_output(
                ["ps", "-o", "command=", "-p", str(pid)],
                text=True, timeout=3, stderr=_sp.DEVNULL,
            ).strip()
    except Exception:
        return None  # can't determine -- assume match


def _remove_pid() -> None:
    """Remove the PID file."""
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _acquire_lock() -> bool:
    """Acquire an exclusive file lock for singleton enforcement.

    Uses msvcrt.locking on Windows and fcntl.flock on Unix.  The lock is
    held for the lifetime of the foreground service process -- released
    explicitly by _release_lock() or implicitly when the process exits.

    Returns True on success, False if another instance holds the lock.
    """
    global _lock_fd
    _MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _lock_fd = open(_LOCK_FILE, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write PID into lock file for diagnostics
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except (OSError, IOError):
        if _lock_fd:
            try:
                _lock_fd.close()
            except OSError:
                pass
            _lock_fd = None
        return False


def _release_lock() -> None:
    """Release the singleton file lock."""
    global _lock_fd
    if _lock_fd is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                _lock_fd.seek(0)
                msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, IOError):
                pass
        else:
            import fcntl
            fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
        _lock_fd.close()
    except (OSError, IOError):
        pass
    _lock_fd = None


def _safe_print(*args, **kwargs) -> None:
    """Print with fallback encoding to prevent cp1252 crashes on Windows.

    If the console encoding cannot represent the output, falls back to
    ASCII with replacement characters rather than raising
    UnicodeEncodeError.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        safe = text.encode("ascii", errors="replace").decode("ascii")
        kwargs.pop("file", None)
        print(safe, **kwargs)


async def _acquire_startup_token(token_manager: TokenManager) -> str:
    """Pre-warm token before connecting to Trouter or handling any messages."""
    logger.info("Pre-warming Teams token before connect...")
    token = await token_manager.get_token(force_refresh=True)
    set_chatsvc_token(token)
    logger.info("Token pre-warmed (%d chars)", len(token))
    return token


_PLACEHOLDER_OID = "00000000-0000-0000-0000-000000000000"


def _auto_populate_identity(global_cfg: GlobalConfig) -> bool:
    """Auto-populate config identity from JWT if still at placeholder values.

    Called after the first successful token acquisition.  Extracts oid, upn,
    and displayName from the JWT and persists them to monitor-config.json so
    the user never has to create the file manually.

    Returns True if identity was updated and saved.
    """
    if _PLACEHOLDER_OID not in global_cfg.identity.mri:
        return False  # already configured

    detected = get_detected_identity()
    if not detected.get("mri"):
        logger.debug("No MRI detected from JWT -- cannot auto-populate identity")
        return False

    global_cfg.identity.mri = detected["mri"]
    if detected.get("upn"):
        global_cfg.identity.upn = detected["upn"]
    if detected.get("displayName"):
        global_cfg.identity.displayName = detected["displayName"]

    try:
        save_global_config(global_cfg)
        logger.debug(
            "Auto-populated identity from JWT: %s (...%s) -- saved to monitor-config.json",
            detected.get("displayName") or detected.get("upn") or "unknown",
            detected["mri"][-8:],
        )
        return True
    except Exception as e:
        logger.warning("Failed to save auto-populated identity: %s", e)
        return False


def _compute_refresh_sleep(
    token_manager: TokenManager,
    fallback_refresh_seconds: int,
) -> float:
    """Compute next refresh-loop wakeup.

    If JWT expiry is known we wake close to refresh-at time; otherwise fall back
    to monitor-config token_refresh_minutes with a capped check interval.
    """
    remaining = token_manager.seconds_until_refresh()
    if remaining <= 0:
        return 0.0
    fallback = max(30, fallback_refresh_seconds)
    return min(remaining, float(fallback), float(_MAX_REFRESH_BUFFER_SECONDS))


_CATCHUP_WINDOW_SECONDS = 600  # Look back 10 minutes for missed messages


async def _catchup_poll(
    config: GlobalConfig,
    token: str,
    processed_ids: set,
    route_fn,
) -> None:
    """Poll chatsvc for recent messages missed during offline/startup gap.

    Fetches the last N minutes of messages from each monitored conversation,
    filters to those matching keyword + sender, skips already-processed IDs,
    and feeds them through the normal route_fn.
    """
    import aiohttp
    import urllib.parse
    from datetime import datetime, timezone as tz
    from scripts.monitor.trouter_client import EventMessage

    region = config.connection.chatsvc_region or "amer"
    cutoff = time.time() - _CATCHUP_WINDOW_SECONDS
    total_caught = 0

    # Collect unique conversation IDs from all enabled workspaces
    conv_ids: set[str] = set()
    for ws_key, ws in config.enabled_workspaces().items():
        for mc in ws.monitored_conversations:
            if mc.id != "*":
                conv_ids.add(mc.id)

    if not conv_ids:
        logger.debug("Catch-up: no specific conversation IDs to poll (wildcard only)")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        for conv_id in conv_ids:
            try:
                encoded_conv = urllib.parse.quote(conv_id, safe="")
                url = (
                    f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1/"
                    f"users/ME/conversations/{encoded_conv}/messages"
                    f"?view=msnp24Equivalent&pageSize=30"
                )
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.debug("Catch-up: %s returned %d", conv_id[:30], resp.status)
                        continue
                    data = await resp.json()
                    messages = data.get("messages", []) if isinstance(data, dict) else data if isinstance(data, list) else []

                for msg in messages:
                    msg_id = msg.get("id", "") or msg.get("clientmessageid", "")
                    if not msg_id or msg_id in processed_ids:
                        continue

                    # Parse compose time and skip old messages.
                    # Messages without composetime pass through -- safer to
                    # double-process than to silently drop a missed message.
                    compose_time = msg.get("composetime", "") or msg.get("originalarrivaltime", "")
                    if compose_time:
                        try:
                            ct = datetime.fromisoformat(compose_time.replace("Z", "+00:00"))
                            if ct.timestamp() < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass

                    content = msg.get("content", "")
                    sender_mri = msg.get("from", "") or msg.get("fromUserId", "")
                    sender_name = msg.get("imdisplayname", "")

                    # Build an EventMessage and route it
                    event = EventMessage(
                        message_id=msg_id,
                        conversation_id=conv_id,
                        content=content,
                        sender_mri=sender_mri,
                        sender_name=sender_name,
                        compose_time=compose_time,
                        resource_type="NewMessage",
                        raw=msg,
                    )
                    await route_fn(event)
                    total_caught += 1

            except Exception as e:
                logger.debug("Catch-up poll error for %s: %s", conv_id[:30], e)

    if total_caught:
        logger.info("Catch-up: processed %d missed message(s)", total_caught)
    else:
        logger.debug("Catch-up: no missed messages found")


async def _run_service(global_cfg: GlobalConfig) -> None:
    """Main service loop -- one Trouter connection, multi-workspace dispatch."""
    start_time = time.time()
    config = global_cfg  # alias for connection-level access

    # Install global asyncio exception handler — prevents silent task crashes
    loop = asyncio.get_running_loop()
    _original_handler = loop.get_exception_handler()

    def _global_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "")
        logger.error(
            "Asyncio unhandled exception: %s (exception=%s: %s)",
            msg, type(exc).__name__ if exc else "None", exc,
        )
        if _original_handler:
            _original_handler(loop, context)

    loop.set_exception_handler(_global_exception_handler)

    # Pre-flight: verify CLI binary is available for dispatch
    cli = _get_cli_binary()
    if cli:
        logger.info("CLI binary resolved: %s", cli)
    else:
        logger.warning(
            "[!] CLI binary NOT found -- dispatches will fail. "
            "Install Agency CLI or Claude Code, or set the path in Settings."
        )

    # Apply configured chatsvc region (if set in config or env var)
    if config.connection.chatsvc_region:
        set_chatsvc_region(config.connection.chatsvc_region)

    # -- Build per-workspace handlers ------------------------------------
    enabled_ws = config.enabled_workspaces()
    if not enabled_ws:
        logger.error("No enabled workspaces in global config -- nothing to monitor.")
        return

    # For PTY bridge: use first enabled workspace's dispatch settings
    # (bridge is shared, but session dispatch is per-workspace via handler)
    first_ws_key = next(iter(enabled_ws))
    first_ws = enabled_ws[first_ws_key]

    # -- Initialize PTY bridge + prompt queue (if enabled) ----------------
    prompt_queue = None
    bridge = None
    dispatch_store = None
    if first_ws.dispatch.use_persistent_pty:
        try:
            from scripts.monitor.pty_bridge import PtyBridge
            from scripts.monitor.prompt_queue import PromptQueue, _session_key_for
            from scripts.monitor.dispatch_store import DispatchStore

            # Persistent dispatch store -- survives service restarts
            dispatch_store = DispatchStore()
            dispatch_store.cleanup_old(max_age_hours=72)
            recovered = dispatch_store.mark_interrupted_as_pending()
            if recovered:
                logger.info("Recovered %d interrupted dispatches", recovered)

            bridge = PtyBridge()
            await bridge.start(client_type="monitor", start_bridge=True)

            # Adopt any PTY sessions that survived a previous Python-side crash
            adopted = await bridge.adopt_active_sessions()
            if adopted:
                logger.info("Adopted %d orphaned session(s) on startup", adopted)

            # Inject chatsvc env into bridge sessions
            env_vars: dict[str, str] = {}
            if config.connection.chatsvc_region:
                env_vars["TEAMS_CHATSVC_REGION"] = config.connection.chatsvc_region

            prompt_queue = PromptQueue(
                bridge=bridge,
                dispatch_config=first_ws.dispatch,
                reply_fn=_reply_to_chat,
                dispatch_store=dispatch_store,
            )
            if env_vars:
                prompt_queue.set_session_env(env_vars)
            await prompt_queue.start()

            logger.info("PTY bridge + prompt queue initialized")

            # Pre-warm sessions for all enabled workspaces' warmup conversations
            async def _warm_sessions():
                for ws_key, ws in enabled_ws.items():
                    for conv_id in ws.dispatch.pty_warmup_conversations:
                        try:
                            skey = _session_key_for(conv_id)
                            resume_id = ws.dispatch.persistent_session_id if conv_id == "48:notes" else ""
                            cwd = ws.dispatch.working_directory or ws_key
                            await bridge.spawn_session(
                                session_key=skey,
                                resume_id=resume_id,
                                cwd=cwd,
                                wait_ready=False,
                            )
                            logger.info(
                                "Pre-warming PTY session for %s (key=%s, ws=%s)",
                                conv_id, skey, ws_key[-30:],
                            )
                        except Exception as e:
                            logger.warning("Failed to pre-warm session for %s: %s", conv_id, e)

            await _warm_sessions()
            bridge._on_reconnect = _warm_sessions

        except Exception as e:
            logger.warning(
                "PTY bridge initialization failed -- falling back to subprocess dispatch: %s", e
            )
            prompt_queue = None
            bridge = None

    # Create a MessageHandler per enabled workspace
    ws_handlers: list[tuple[str, MonitorConfig, MessageHandler]] = []
    for ws_key, ws in enabled_ws.items():
        mc = assemble_monitor_config(config, ws_key)
        # Apply reply prefix for outbound messages
        if mc.reply_prefix:
            set_reply_prefix(mc.reply_prefix)
        h = MessageHandler(mc, start_time, prompt_queue=prompt_queue)
        ws_handlers.append((ws_key, mc, h))
        logger.info(
            "Workspace handler: %s (keyword=%s, convs=%d)",
            ws_key[-40:], ws.keyword, len(ws.monitored_conversations),
        )

    # -- Multi-workspace message router ------------------------------------
    _processed_ids: set[str] = set()
    _MAX_DEDUP = 2000

    async def _route_message(event) -> None:
        """Route an incoming message to the correct workspace handler.

        Global checks (dedup, sender) happen here.  Per-workspace checks
        (keyword, conversation) are tested before delegating to the handler.
        First matching workspace wins -- no double-dispatch.
        """
        # 1. Global dedup
        if event.message_id:
            if event.message_id in _processed_ids:
                return
            if len(_processed_ids) >= _MAX_DEDUP:
                to_remove = list(_processed_ids)[:_MAX_DEDUP // 2]
                for mid in to_remove:
                    _processed_ids.discard(mid)
            _processed_ids.add(event.message_id)

        # 2. Strip HTML
        plain_text = strip_html(event.content)
        if not plain_text:
            return

        # 3. Global sender check
        if not matches_sender(event.sender_mri, config.identity.mri):
            logger.debug(
                "Message from unauthorized sender: %s (%s)",
                event.sender_name, event.sender_mri[:40],
            )
            return

        # 4. Per-workspace keyword + conversation match
        for ws_key, mc, handler in ws_handlers:
            # Self-loop prevention
            _loop_prefix = mc.reply_prefix.rstrip() if mc.reply_prefix else "Agency Cowork:"
            if plain_text.lstrip().startswith(_loop_prefix):
                continue

            if not matches_keyword(plain_text, mc.keyword):
                continue
            if not mc.is_monitored(event.conversation_id):
                continue

            # Match found -- delegate to this workspace's handler.
            # The handler's own dedup/sender checks will be redundant but harmless.
            logger.info(
                "Routing to workspace %s (keyword=%s)",
                ws_key[-40:], mc.keyword,
            )
            await handler.handle(event)
            return  # first match wins

        logger.debug("No workspace matched message from %s", event.sender_name)

    reconnect_delay = config.connection.reconnect_delay_seconds
    max_delay = config.connection.max_reconnect_delay_seconds
    fallback_refresh_seconds = config.connection.token_refresh_minutes * 60
    token_manager = get_token_manager()

    _identity_populated = False  # one-shot gate for _auto_populate_identity
    _startup_pending_notified = False  # one-shot gate for pending dispatch notification

    while True:
        try:
            # Always pre-warm a token before accepting/processing messages.
            token = await _acquire_startup_token(token_manager)

            # Auto-populate identity from JWT if config still has placeholder.
            # This handles first-run setups where CLI auth failed (AADSTS530084)
            # but Playwright succeeded -- the user's OID/UPN/name are extracted
            # from the token and persisted so matches_sender() works immediately.
            # One-shot: only attempt once per service lifetime to avoid repeated writes.
            if not _identity_populated:
                _identity_populated = _auto_populate_identity(config) or True

            # Probe chatsvc region if not already configured -- avoids silent
            # message drops when the default "amer" doesn't match the tenant.
            if not config.connection.chatsvc_region:
                discovered = await probe_chatsvc_region(persist=True)
                config.connection.chatsvc_region = discovered
                # Propagate to PTY bridge sessions if already started
                if prompt_queue:
                    prompt_queue.set_session_env({"TEAMS_CHATSVC_REGION": discovered})

            # Connect
            client = TrouterClient(
                token=token,
                on_message=_route_message,
                gateway=config.connection.trouter_gateway,
                registrar_url=config.connection.registrar_url,
                app_id=config.connection.app_id,
                heartbeat_interval=config.connection.heartbeat_interval_seconds,
            )

            await client.connect()
            logger.info("Connected -- entering listen loop")
            reconnect_delay = config.connection.reconnect_delay_seconds  # reset

            # -- Notify about pending dispatches from previous session --
            # One-shot: only fire on first connect, not on every reconnect
            if dispatch_store and not _startup_pending_notified:
                _startup_pending_notified = True
                pending = dispatch_store.get_pending()
                if pending:
                    lines = [
                        "<b>Pending dispatches from previous session:</b><br><br>",
                    ]
                    for i, rec in enumerate(pending, 1):
                        lines.append(rec.to_display(i) + "<br>")
                    lines.append(
                        "<br>Reply with:<br>"
                        "- <code>@agent resume all</code> to re-run all<br>"
                        "- <code>@agent resume 1,3</code> to re-run specific items<br>"
                        "- <code>@agent cancel pending</code> to discard all"
                    )
                    # TODO: route to per-dispatch workspace instead of always first_ws
                    rc = first_ws.dispatch.response_conversation or "48:notes"
                    try:
                        await _reply_to_chat(rc, "\n".join(lines))
                        logger.info(
                            "Posted %d pending dispatch(es) for user review", len(pending)
                        )
                    except Exception as e:
                        logger.warning("Failed to post pending dispatches notice: %s", e)

            # -- Startup catch-up: poll recent messages missed while offline --
            try:
                await _catchup_poll(
                    config=config,
                    token=token,
                    processed_ids=_processed_ids,
                    route_fn=_route_message,
                )
            except Exception as e:
                logger.warning("Startup catch-up poll failed (non-fatal): %s", e)

            # Schedule token refresh as a task
            async def _token_refresh_loop():
                nonlocal token
                while True:
                    await asyncio.sleep(
                        _compute_refresh_sleep(token_manager, fallback_refresh_seconds)
                    )
                    if not token_manager.refresh_due():
                        continue
                    try:
                        logger.info("Refreshing token...")
                        token = await token_manager.get_token(force_refresh=True)
                        client.update_token(token)
                        set_chatsvc_token(token)
                        # Re-register with Trouter after token refresh to prevent
                        # silent message loss when the registration TTL expires
                        # (belt-and-suspenders with _reregistration_loop).
                        try:
                            await client.register()
                            logger.info("Re-registered with Trouter after token refresh")
                        except Exception as reg_err:
                            logger.warning("Re-registration after token refresh failed: %s", reg_err)
                        # Propagate refreshed token to PTY bridge sessions
                        if prompt_queue:
                            prompt_queue.set_session_env({"TEAMS_CHATSVC_TOKEN": token})
                        logger.info(
                            "Token refreshed (next refresh in %ds)",
                            int(token_manager.seconds_until_refresh()),
                        )
                    except Exception as e:
                        if token_manager.is_valid():
                            logger.warning(
                                "Token refresh failed, continuing with cached token (%ds remaining): %s",
                                int(token_manager.expires_in()),
                                e,
                            )
                            continue
                        # Token expired and refresh failed -- retry with backoff
                        # rather than raising (which would silently kill this task).
                        logger.error(
                            "Token expired and refresh failed: %s -- retrying in 30s", e
                        )
                        await asyncio.sleep(min(30, fallback_refresh_seconds))

            refresh_task = asyncio.create_task(_token_refresh_loop())

            try:
                await client.listen()
            finally:
                refresh_task.cancel()
                await client.disconnect()

        except SystemExit:
            logger.info("Service stopped by command")
            break

        except KeyboardInterrupt:
            logger.info("Service interrupted")
            break

        except Exception as e:
            logger.error("Service error: %s -- reconnecting in %ds", e, reconnect_delay)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_delay)

    # -- Clean up PTY bridge on service exit --------------------------------
    if prompt_queue:
        try:
            await prompt_queue.shutdown()
            logger.info("Prompt queue shut down")
        except Exception as e:
            logger.warning("Prompt queue shutdown error: %s", e)
    if bridge:
        try:
            await bridge.shutdown_bridge()
            logger.info("PTY bridge shut down")
        except Exception as e:
            logger.warning("PTY bridge shutdown error: %s", e)


# -------------- CLI Commands --------------


def cmd_enable(config: MonitorConfig, workspace_dir: str = "") -> None:
    """Enable the monitor service with security warning."""
    if config.enabled:
        _safe_print("Monitor service is already enabled.")
        _safe_print(f"Monitoring {len(config.monitored_conversations)} conversation(s).")
        return

    warning = """
[!] SECURITY WARNING -- Real-Time Monitor Service

This service creates a persistent WebSocket connection to Teams and
automatically executes Agency Copilot prompts when triggered by
@agent messages. Before enabling, understand these risks:

1. REMOTE PROMPT EXECUTION -- Messages containing {keyword} will
   trigger agent actions. Only messages from the authorized sender
   ({sender}) in monitored conversations are processed.

2. UNATTENDED EXECUTION -- Prompts execute without interactive
   confirmation. The agent will have full tool access. Outbound
   actions are guarded by the Credential Scanner but NOT by
   interactive user confirmation.

3. SESSION PERSISTENCE -- The service maintains a long-lived
   authenticated session to Teams via captured JWT tokens.

4. PROMPT INJECTION RISK -- A compromised sender account could
   inject malicious prompts.

Monitored conversations (default):
{conversations}

To proceed, the service will be enabled but NOT started.
Run 'python -m scripts.monitor.service start' to begin listening.
""".format(
        keyword=config.keyword,
        sender=config.authorized_sender.displayName,
        conversations="\n".join(
            f"  - {c.name} ({c.type})" for c in config.monitored_conversations
        ),
    )
    _safe_print(warning)

    set_enabled(True, workspace_dir=workspace_dir or None)
    _safe_print("[OK] Monitor service ENABLED. Run 'start' to begin listening.")


def cmd_disable(config: MonitorConfig, workspace_dir: str = "") -> None:
    """Disable the monitor service and stop if running."""
    pid = _read_pid()
    if pid and _is_running(pid):
        _safe_print(f"Stopping running service (PID {pid})...")
        if sys.platform == "win32":
            os.system(f"taskkill /F /PID {pid} >nul 2>&1")
        else:
            os.kill(pid, signal.SIGTERM)
        _remove_pid()

    set_enabled(False, workspace_dir=workspace_dir or None)
    _safe_print("[OK] Monitor service DISABLED.")


def cmd_start(global_cfg: GlobalConfig, foreground: bool = False) -> None:
    """Start the monitor service.

    By default, launches as a detached background process (survives shell
    closure).  Use ``--foreground`` for debugging.
    """
    enabled = global_cfg.enabled_workspaces()
    if not enabled:
        _safe_print("[ERROR] No enabled workspaces in global config.")
        _safe_print("Run 'python -m scripts.monitor.service enable' first.")
        return

    # Check for existing instance
    pid = _read_pid()
    if pid and _is_running(pid):
        _safe_print(f"Monitor service is already running (PID {pid}).")
        return
    if pid:
        # Stale PID file -- process is dead, clean up before restarting
        _safe_print(f"[!] Stale PID file (PID {pid} is dead) -- cleaning up and restarting...")
        _log_lifecycle("stale-pid-cleanup", old_pid=pid, reason="dead process on start")
        _remove_pid()

    if not foreground:
        # Launch a detached child that runs in foreground mode
        import subprocess
        cmd = [
            sys.executable, "-m", "scripts.monitor.service",
            "start", "--foreground",
        ]
        # Redirect stderr to a startup crash log so pre-logging errors
        # (import failures, syntax errors) are captured.
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        startup_log = open(_STARTUP_LOG, "w", encoding="utf-8")
        kwargs: dict = dict(
            cwd=str(_TEAMS_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=startup_log,
            stdin=subprocess.DEVNULL,
        )
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
            kwargs["creationflags"] = 0x00000200 | 0x00000008
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        startup_log.close()  # parent releases handle; child owns it
        # Wait briefly to confirm it started
        import time
        time.sleep(2)
        if proc.poll() is not None:
            _safe_print(f"[ERROR] Service exited immediately (rc={proc.returncode}). Run with --foreground to debug.")
            return
        _safe_print(f"[OK] Monitor service started (PID {proc.pid}) -- detached background process.")
        _safe_print(f"  Stop with: python -m scripts.monitor.service stop")
        return

    # Foreground mode -- run inline (for debugging or when called by detached child)
    # Acquire exclusive file lock BEFORE writing PID to prevent races
    if not _acquire_lock():
        # Try to identify the lock holder from the lock file content
        lock_pid = None
        try:
            lock_pid = int(_LOCK_FILE.read_text().strip())
        except (OSError, ValueError):
            pass
        if lock_pid and _is_running(lock_pid):
            _safe_print(f"[ERROR] Another monitor instance (PID {lock_pid}) holds the lock.")
            # Recover missing PID file so status/stop work correctly
            if not _PID_FILE.exists():
                _PID_FILE.write_text(str(lock_pid))
                _safe_print(f"  Restored missing PID file for PID {lock_pid}.")
                _safe_print(f"  Use 'stop' command to stop the existing instance first.")
            _log_lifecycle("lock-conflict", lock_holder=lock_pid)
        else:
            _safe_print("[ERROR] A stale lock file exists but the holder appears dead.")
            _safe_print("  Delete the lock file manually and retry:")
            _safe_print(f"  {_LOCK_FILE}")
            _log_lifecycle("lock-conflict-stale", lock_pid=lock_pid)
        return

    _safe_print(f"Starting monitor service (foreground) -- {len(enabled)} workspace(s)...")
    for ws_key in enabled:
        _safe_print(f"  - {ws_key}")
    _setup_logging()
    _write_pid()
    _log_lifecycle("start", workspaces=len(enabled),
                   python=sys.version.split()[0])

    try:
        asyncio.run(_run_service(global_cfg))
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
        _log_lifecycle("stop", reason="KeyboardInterrupt")
    except SystemExit as e:
        logger.info("Service stopped by SystemExit (code=%s)", e.code)
    except BaseException as e:
        # Catch EVERYTHING to log the actual cause of death
        logger.critical(
            "SERVICE CRASHED with unhandled %s: %s",
            type(e).__name__, e,
            exc_info=True,
        )
    finally:
        _release_lock()
        _remove_pid()
        logger.info("Monitor service PID file removed, shutting down")
        _safe_print("Monitor service stopped.")


def cmd_stop() -> None:
    """Stop the running monitor service."""
    pid = _read_pid()
    if not pid:
        _safe_print("No PID file found -- service may not be running.")
        return

    if not _is_running(pid):
        _safe_print(f"PID {pid} is not running. Cleaning up PID file.")
        _remove_pid()
        return

    _safe_print(f"Stopping monitor service (PID {pid})...")
    _log_lifecycle("stop", reason="cmd_stop", target_pid=pid)
    if sys.platform == "win32":
        rc = os.system(f"taskkill /F /PID {pid} >nul 2>&1")
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            rc = 0
        except OSError:
            rc = 1

    # Wait briefly then verify the process actually died before removing PID
    if rc == 0:
        import time as _t
        for _ in range(10):
            _t.sleep(0.5)
            if not _is_running(pid):
                break
    if _is_running(pid):
        _safe_print(f"[ERROR] Failed to kill PID {pid} -- process still running.")
        _safe_print("Try running as administrator, or manually kill the process.")
        _log_lifecycle("stop-failed", target_pid=pid, reason="process survived kill")
        return
    _remove_pid()
    _safe_print("[OK] Monitor service stopped.")


def cmd_status(global_cfg: GlobalConfig) -> None:
    """Show the current status of the monitor service."""
    pid = _read_pid()
    running = pid and _is_running(pid)

    ws_status = []
    for ws_key, ws in global_cfg.workspaces.items():
        ws_status.append({
            "workspace": ws_key,
            "enabled": ws.enabled,
            "keyword": ws.keyword,
            "conversations": len(ws.monitored_conversations),
        })

    status = {
        "running": bool(running),
        "pid": pid if running else None,
        "identity": global_cfg.identity.displayName,
        "identity_mri": global_cfg.identity.mri[:40],
        "identity_configured": _PLACEHOLDER_OID not in global_cfg.identity.mri,
        "workspaces": ws_status,
    }
    print(json.dumps(status, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Teams Monitor Service")
    parser.add_argument(
        "command",
        choices=["enable", "disable", "start", "stop", "status"],
        help="Service command",
    )
    parser.add_argument(
        "--foreground", action="store_true",
        help="Run in foreground (default: detached background process)",
    )
    parser.add_argument(
        "--workspace", type=str, default="",
        help="Workspace directory (for enable/disable targeting a specific workspace)",
    )
    args = parser.parse_args()

    global_cfg = load_global_config()

    if args.command == "enable":
        # For enable/disable, assemble a MonitorConfig for display purposes
        ws_dir = args.workspace or str(Path(__file__).resolve().parent.parent.parent.parent.parent)
        config = assemble_monitor_config(global_cfg, ws_dir)
        cmd_enable(config, workspace_dir=ws_dir)
    elif args.command == "disable":
        ws_dir = args.workspace or str(Path(__file__).resolve().parent.parent.parent.parent.parent)
        config = assemble_monitor_config(global_cfg, ws_dir)
        cmd_disable(config, workspace_dir=ws_dir)
    elif args.command == "start":
        cmd_start(global_cfg, foreground=args.foreground)
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status(global_cfg)


if __name__ == "__main__":
    main()
