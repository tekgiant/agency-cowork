"""Message handler for the Teams monitor service.

Filters incoming EventMessages against the configured rules (keyword, sender,
conversation), extracts prompts, dispatches to Agency Copilot, and handles
join/leave/list/status commands.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import MonitorConfig, save_config
from .trouter_client import EventMessage

# Shared chunking utility for long-message delivery
_TEAMS_ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent.parent
if str(_TEAMS_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_TEAMS_ROOT_FOR_IMPORT))
from scripts.chunking import chunk_message, INTER_CHUNK_DELAY

# Import prompt guard from repo root scripts/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from scripts.prompt_guard import scan_for_injections, log_injection_event

logger = logging.getLogger("monitor.handler")

# Paths
_TEAMS_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _TEAMS_ROOT / "logs"
_MEMORY_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "memory"
_DAILY_LOGS_DIR = _MEMORY_DIR / "DailyLogs"

# CLI binary cache (shared with Electron UI)
_CLI_CACHE_FILE = Path.home() / ".agency-cowork" / "cli-path.json"
# Startup timeout: if the subprocess hasn't produced any output within this
# window, it's likely hung (auth prompt, missing config, etc.).
_DISPATCH_STARTUP_TIMEOUT = 90  # seconds

# HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Module-level chatsvc Bearer token — set by the service when token is acquired/refreshed.
# Used by _reply_to_chat() for direct API replies (no Playwright needed).
_chatsvc_token: str = ""
_user_mri: str = ""  # User MRI from token JWT (e.g. "8:orgid:<guid>")
_user_upn: str = ""  # UPN from token JWT (e.g. "user@contoso.com")
_user_display_name: str = ""  # Display name from token JWT

# Dynamic chatsvc region — auto-discovered from 404 Location header or config.
# Defaults to "amer" but will be updated on first 752 error.
_chatsvc_region: str = os.environ.get("TEAMS_CHATSVC_REGION", "amer")

# Configurable reply prefix — prepended to all outbound messages.
# Set from agentconfig.json → monitor.replyPrefix via set_reply_prefix().
_reply_prefix: str = "Agency Cowork: "


def set_reply_prefix(prefix: str) -> None:
    """Update the reply prefix prepended to all outbound messages."""
    global _reply_prefix
    _reply_prefix = prefix
    logger.info("Reply prefix set to: %r", prefix)


def set_chatsvc_token(token: str) -> None:
    """Update the chatsvc Bearer token used for replying to chats.

    Also extracts the user MRI, UPN, and display name from JWT claims
    so that _reply_to_chat can set the correct ``from`` field and
    identity can be auto-populated on first run.
    """
    global _chatsvc_token, _user_mri, _user_upn, _user_display_name
    _chatsvc_token = token
    # Extract identity fields from JWT claims
    try:
        import base64 as _b64
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + ("=" * (-len(parts[1]) % 4))
            claims = json.loads(_b64.urlsafe_b64decode(payload_b64.encode("ascii")))
            oid = claims.get("oid", "")
            if oid:
                _user_mri = f"8:orgid:{oid}"
                logger.debug("User MRI set: %s", _user_mri)
            upn = claims.get("upn", "") or claims.get("preferred_username", "")
            if upn:
                _user_upn = upn
            name = claims.get("name", "")
            if name:
                _user_display_name = name
    except Exception as e:
        logger.debug("Failed to extract identity from token: %s", e)


def get_detected_identity() -> dict:
    """Return identity fields extracted from the last JWT token.

    Returns a dict with ``mri``, ``upn``, ``displayName`` — any or all
    may be empty strings if not yet detected.
    """
    return {"mri": _user_mri, "upn": _user_upn, "displayName": _user_display_name}


def set_chatsvc_region(region: str) -> None:
    """Update the chatsvc region slug everywhere (e.g. 'amer', 'noam-pilot2', 'emea').

    Propagates to all modules that build chatsvc/mt URLs:
      - monitor/message_handler (this module)
      - api/client.CHATSVC_BASE
      - rich/api_client.CHATSVC_BASE + _CHATSVC_REGION
      - os.environ so rich/utils.py picks it up per-call
    """
    global _chatsvc_region
    _chatsvc_region = region
    os.environ["TEAMS_CHATSVC_REGION"] = region
    logger.info("chatsvc region set to: %s", region)

    # Propagate to api/client module
    try:
        from scripts.api.client import update_chatsvc_region as _update_api
        _update_api(region)
    except Exception:
        pass

    # Propagate to rich/api_client module
    try:
        import scripts.rich.api_client as _rac
        _rac._CHATSVC_REGION = region
        _rac.CHATSVC_BASE = f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1/users/ME"
    except Exception:
        pass


def get_chatsvc_region() -> str:
    """Return the current chatsvc region slug."""
    return _chatsvc_region


async def probe_chatsvc_region(persist: bool = True) -> str:
    """Discover the correct chatsvc region by probing the API.

    Makes a lightweight GET to ``48:notes`` (self-chat) using the current
    token and default region.  If the API returns a redirect (301/302) or
    404 with a Location header pointing to a different region, we extract
    and adopt the correct region.

    Args:
        persist: If True, save the discovered region to monitor-config.json.

    Returns:
        The discovered (or confirmed) region slug.
    """
    global _chatsvc_region
    if not _chatsvc_token:
        logger.debug("probe_chatsvc_region: no token available, skipping")
        return _chatsvc_region

    region = _chatsvc_region
    probe_conv = "48%3Anotes"  # URL-encoded 48:notes
    url = (
        f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1/"
        f"users/ME/conversations/{probe_conv}/messages?pageSize=1"
    )
    headers = {
        "Authorization": f"Bearer {_chatsvc_token}",
        "Accept": "application/json",
    }

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # allow_redirects=False so we can inspect Location header
            async with session.get(url, headers=headers, allow_redirects=False) as resp:
                if resp.status in (200, 201):
                    logger.info("Region probe: '%s' confirmed (status %d)", region, resp.status)
                    # Check response headers for region hints even on 200
                    # Some deployments embed the canonical region in headers
                    canon = resp.headers.get("X-MS-Region", "")
                    if canon and canon.lower() != region.lower():
                        logger.info("Region probe: header suggests '%s' instead of '%s'", canon, region)
                        set_chatsvc_region(canon.lower())
                        region = canon.lower()
                    if persist and region != _chatsvc_region:
                        _persist_region(region)
                    return region

                # Redirect or 404 with Location → different region
                location = resp.headers.get("Location", "")
                resp_body = ""
                try:
                    resp_body = await resp.text()
                except Exception:
                    pass

                if resp.status in (301, 302, 307, 404) and (
                    location or "different cloud" in resp_body.lower()
                ):
                    new_region = _extract_region_from_url(location or resp_body)
                    if new_region and new_region != region:
                        logger.info(
                            "Region probe: discovered '%s' (was '%s', status %d)",
                            new_region, region, resp.status,
                        )
                        set_chatsvc_region(new_region)
                        if persist:
                            _persist_region(new_region)
                        return new_region

                logger.info(
                    "Region probe: status %d with no redirect hint — keeping '%s'",
                    resp.status, region,
                )
    except Exception as e:
        logger.warning("Region probe failed: %s — keeping '%s'", e, region)

    return region


def _persist_region(region: str) -> None:
    """Write the discovered region back to monitor-config.json."""
    try:
        from .config import load_global_config, save_global_config
        gcfg = load_global_config()
        if gcfg.connection.chatsvc_region != region:
            gcfg.connection.chatsvc_region = region
            save_global_config(gcfg)
            logger.info("Persisted chatsvc_region='%s' to monitor-config.json", region)
    except Exception as e:
        logger.debug("Failed to persist region: %s", e)


def _extract_region_from_url(url_or_body: str) -> Optional[str]:
    """Extract the chatsvc region slug from a URL or error body.

    Matches patterns like:
      https://teams.cloud.microsoft/api/chatsvc/noam-pilot2/v1/...
      https://teams.cloud.microsoft/api/chatsvc/emea/v1/...
    """
    m = re.search(r"/api/chatsvc/([a-z0-9_-]+)/v\d", url_or_body, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _resolve_cli_binary() -> Optional[str]:
    """Resolve the Agency/Claude CLI binary path.

    Resolution order (mirrors Electron's detectCLI()):
    1. Electron's cached path (~/.agency-cowork/cli-path.json)
    2. System PATH lookup: ``agency`` then ``claude``
    3. Common install locations (Windows npm global, macOS homebrew)

    Returns the resolved binary path, or None if not found.
    """
    # 1. Check Electron's CLI cache
    try:
        if _CLI_CACHE_FILE.exists():
            cache = json.loads(_CLI_CACHE_FILE.read_text(encoding="utf-8"))
            # User override takes priority
            for key in ("userOverride", "resolvedPath"):
                p = cache.get(key, "")
                if p and Path(p).exists():
                    logger.info("CLI resolved from cache (%s): %s", key, p)
                    return p
    except Exception as e:
        logger.debug("CLI cache read failed: %s", e)

    # 2. System PATH lookup
    which_cmd = "where" if sys.platform == "win32" else "which"
    for binary in ("agency", "claude"):
        try:
            result = subprocess.run(
                [which_cmd, binary],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                resolved = result.stdout.strip().split("\n")[0].strip()
                if resolved and Path(resolved).exists():
                    logger.info("CLI resolved via %s: %s", which_cmd, resolved)
                    return resolved
        except Exception:
            pass

    # 3. Common install locations
    common_paths = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            common_paths.extend([
                Path(appdata) / "npm" / "agency.cmd",
                Path(appdata) / "npm" / "claude.cmd",
            ])
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            common_paths.extend([
                Path(localappdata) / "Programs" / "agency" / "agency.exe",
            ])
    else:
        common_paths.extend([
            Path.home() / ".npm-global" / "bin" / "agency",
            Path("/usr/local/bin/agency"),
            Path.home() / ".npm-global" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
        ])

    for p in common_paths:
        if p.exists():
            logger.info("CLI resolved from common path: %s", p)
            return str(p)

    return None


# Cached CLI binary path (resolved once per service lifetime)
_cached_cli_path: Optional[str] = None


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its descendants (cross-platform)."""
    import signal
    if sys.platform == "win32":
        # taskkill /T /F kills the entire tree on Windows
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            logger.warning("taskkill tree for PID %d failed: %s", pid, e)
    else:
        # On Unix, kill the process group
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as e:
            logger.warning("killpg for PID %d failed: %s", pid, e)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _get_cli_binary() -> Optional[str]:
    """Get CLI binary path, caching the result for the service lifetime."""
    global _cached_cli_path
    if _cached_cli_path is None:
        _cached_cli_path = _resolve_cli_binary() or ""
    return _cached_cli_path or None


# Dedup buffer: message IDs we've already processed
_processed_ids: set[str] = set()
_MAX_DEDUP_SIZE = 10000


def _log_prompt_to_memory(
    prompt: str,
    event: EventMessage,
    kind: str,
    result: str = "",
    output_summary: str = "",
) -> None:
    """Log a triggered prompt (and optionally its result) to structured JSON log
    and to today's daily memory log for searchability.

    Args:
        prompt: The extracted prompt text.
        event: The source EventMessage.
        kind: "dispatch" | "command" | "rejected".
        result: "success" | "failed" | "timeout" | "error" | "" (for pre-dispatch).
        output_summary: First ~500 chars of the Agency output (for dispatch results).
    """
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = ts.strftime("%Y-%m-%d")

    entry = {
        "timestamp": ts_str,
        "kind": kind,
        "prompt": prompt,
        "sender": event.sender_name,
        "sender_mri": event.sender_mri,
        "conversation": event.conversation_id,
        "message_id": event.message_id,
        "result": result,
        "output_summary": output_summary[:500] if output_summary else "",
    }

    # 1. Append to JSON log: logs/monitor-prompts.jsonl (one JSON object per line)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        jsonl_path = _LOG_DIR / "monitor-prompts.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("Failed to write prompt JSONL log: %s", e)

    # 2. Append to today's daily memory log: memory/DailyLogs/YYYY-MM-DD.md
    try:
        _DAILY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        daily_log = _DAILY_LOGS_DIR / f"{date_str}.md"
        # Build markdown snippet
        if kind == "dispatch" and result:
            # Post-dispatch result entry
            md = (
                f"\n### Monitor Dispatch Result [{ts.strftime('%H:%M')}]\n"
                f"- **Prompt:** {prompt}\n"
                f"- **Result:** {result}\n"
            )
            if output_summary:
                md += f"- **Output:** {output_summary[:300]}\n"
        elif kind == "dispatch":
            # Pre-dispatch trigger entry
            md = (
                f"\n### Monitor Triggered [{ts.strftime('%H:%M')}]\n"
                f"- **Prompt:** {prompt}\n"
                f"- **Sender:** {event.sender_name}\n"
                f"- **Conversation:** {event.conversation_id[:40]}\n"
            )
        elif kind == "command":
            md = (
                f"\n### Monitor Command [{ts.strftime('%H:%M')}]\n"
                f"- **Command:** {prompt}\n"
            )
        else:
            md = ""

        if md:
            with open(daily_log, "a", encoding="utf-8") as f:
                f.write(md)
    except Exception as e:
        logger.warning("Failed to write daily memory log: %s", e)


async def _notify_injection(
    result,  # InjectionScanResult
    prompt: str,
    event: EventMessage,
) -> None:
    """Send injection alert to owner via Teams self-chat (best-effort).

    Reads agentconfig.json for prompt_guard.notify_teams / notify_email settings.
    """
    try:
        # Read notification settings from agentconfig.json
        agent_config_path = _TEAMS_ROOT.parent.parent / "agentconfig.json"
        notify_teams = True
        notify_email = False
        if agent_config_path.exists():
            with open(agent_config_path, "r", encoding="utf-8") as f:
                ac = json.load(f)
            pg = ac.get("prompt_guard", {})
            notify_teams = pg.get("notify_teams", True)
            notify_email = pg.get("notify_email", False)

        patterns = ", ".join(f.pattern_name for f in result.findings)
        alert_body = (
            f"⚠️ **Prompt Injection Blocked**\n\n"
            f"**Severity:** {result.max_severity}\n"
            f"**Source:** {result.source}\n"
            f"**Sender:** {event.sender_name}\n"
            f"**Conversation:** {event.conversation_id[:40]}\n"
            f"**Patterns:** {patterns}\n"
            f"**Prompt preview:** {prompt[:100]}"
        )

        if notify_teams:
            send_msg = _TEAMS_ROOT / "scripts" / "rich" / "send_message.py"
            proc = await asyncio.create_subprocess_exec(
                "python", "-m", "scripts.rich.send_message",
                "--to", "48:notes",
                "--body", alert_body,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_TEAMS_ROOT),
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
            logger.info("Injection alert sent to Teams self-chat")

    except Exception as e:
        logger.warning("Failed to send injection notification: %s", e)


async def _reply_to_chat(conversation_id: str, body: str, token: str = "") -> bool:
    """Send a reply message back to the source conversation.

    Long messages are automatically split into sequential chunks using
    paragraph/line/sentence boundaries.  Each chunk is sent as a separate
    message with (1/N) … (N/N) suffixes so the reader knows more is coming.

    Uses the Teams chatsvc REST API directly (no Playwright needed).
    Falls back to send_message.py subprocess if no token is available.
    Returns True on success (all chunks delivered).
    """
    # Apply reply prefix once before chunking so it only appears on the
    # first chunk (instead of _send_single_message adding it to each chunk).
    prefixed_body = body
    if _reply_prefix and not body.startswith(_reply_prefix):
        prefixed_body = _reply_prefix + body

    chunks = chunk_message(prefixed_body)

    if len(chunks) == 1:
        return await _send_single_message(conversation_id, chunks[0], token, skip_prefix=True)

    # Sequential delivery with inter-chunk delay to preserve ordering
    logger.info(
        "Chunking reply into %d parts for %s (%d chars total)",
        len(chunks), conversation_id[:30], len(body),
    )
    all_ok = True
    for i, chunk in enumerate(chunks):
        ok = await _send_single_message(conversation_id, chunk, token, skip_prefix=True)
        if not ok:
            logger.warning("Chunk %d/%d failed for %s", i + 1, len(chunks), conversation_id[:30])
            all_ok = False
            break  # don't send remaining chunks if one fails
        if i < len(chunks) - 1:
            await asyncio.sleep(INTER_CHUNK_DELAY)
    return all_ok


async def _send_single_message(conversation_id: str, body: str, token: str = "", skip_prefix: bool = False) -> bool:
    """Send a single message to the conversation (no chunking).

    This is the low-level send function called by _reply_to_chat() for each
    chunk.  External callers should use _reply_to_chat() instead.
    """
    import urllib.parse
    import uuid

    # Prefix all outbound messages with configurable agent identity
    if not skip_prefix and _reply_prefix and not body.startswith(_reply_prefix):
        body = _reply_prefix + body

    # Use module-level token if none supplied
    effective_token = token or _chatsvc_token

    # ── Primary: direct chatsvc HTTP POST ────────────────────────────
    if effective_token:
        try:
            import aiohttp

            encoded_conv = urllib.parse.quote(conversation_id, safe="")
            user_mri = _user_mri or "8:orgid:00000000-0000-0000-0000-000000000000"
            region = _chatsvc_region
            url = (
                f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1/"
                f"users/ME/conversations/{encoded_conv}/messages"
            )

            # Convert markdown-ish body to simple HTML
            content_html = body.replace("\n", "<br/>")
            if not content_html.startswith("<"):
                content_html = f"<p>{content_html}</p>"

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            payload = {
                "id": "-1",
                "type": "Message",
                "conversationid": conversation_id,
                "conversationLink": f"https://teams.cloud.microsoft/api/chatsvc/{region}/v1/users/ME/conversations/{encoded_conv}",
                "from": user_mri,
                "fromUserId": user_mri,
                "composetime": now,
                "originalarrivaltime": now,
                "content": content_html,
                "messagetype": "RichText/Html",
                "contenttype": "Text",
                "imdisplayname": _reply_prefix.rstrip(": ") if _reply_prefix else "Agency Cowork",
                "clientmessageid": str(uuid.uuid4().int)[:19],
                "callId": "",
                "state": 0,
                "version": "0",
                "amsreferences": [],
                "properties": {
                    "importance": "",
                    "subject": "",
                    "title": "",
                    "cards": "[]",
                    "links": "[]",
                    "mentions": "[]",
                    "onbehalfof": None,
                    "files": "[]",
                    "policyViolation": None,
                    "formatVariant": "TEAMS",
                },
                "crossPostChannels": [],
            }

            headers = {
                "Authorization": f"Bearer {effective_token}",
                "Content-Type": "application/json",
                "X-MS-Migration": "True",
                "X-Ms-Test-User": "False",
                "clientinfo": (
                    "os=windows; osVer=NT 10.0; proc=x86; lcid=en-us; "
                    "deviceType=1; country=us; clientName=skypeteams; "
                    "clientVer=1415/26020101120; utcOffset=-08:00; "
                    "timezone=America/Los_Angeles"
                ),
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status in (201, 202):
                        # 201/202 = confirmed delivery
                        try:
                            resp_ok_body = await resp.text()
                            resp_ok_json = json.loads(resp_ok_body) if resp_ok_body.strip() else {}
                            msg_id = resp_ok_json.get("OriginalArrivalTime") or resp_ok_json.get("id", "")
                            logger.info(
                                "Reply delivered to %s via chatsvc API (status=%d, msgId=%s)",
                                conversation_id[:30], resp.status, str(msg_id)[:40],
                            )
                        except Exception as log_err:
                            logger.info("Reply delivered to %s via chatsvc API (status=%d, body parse error: %s)",
                                       conversation_id[:30], resp.status, log_err)
                        return True

                    if resp.status == 200:
                        # 200 from wrong region returns a "messages" echo (conversation
                        # history) instead of delivering.  Detect and auto-correct.
                        resp_ok_body = await resp.text()
                        try:
                            resp_ok_json = json.loads(resp_ok_body) if resp_ok_body.strip() else {}
                        except Exception:
                            resp_ok_json = {}

                        is_echo = (
                            isinstance(resp_ok_json, dict) and "messages" in resp_ok_json
                        ) or (
                            isinstance(resp_ok_json, list)
                        )

                        if is_echo:
                            # Extract correct region from conversationLink in echoed messages
                            echo_region = _extract_region_from_url(resp_ok_body)
                            if echo_region and echo_region != region:
                                logger.warning(
                                    "chatsvc region mismatch: sent to '%s' but conversation lives in '%s' — retrying",
                                    region, echo_region,
                                )
                                set_chatsvc_region(echo_region)
                                # Persist discovered region to config
                                _persist_region(echo_region)
                                retry_url = (
                                    f"https://teams.cloud.microsoft/api/chatsvc/{echo_region}/v1/"
                                    f"users/ME/conversations/{encoded_conv}/messages"
                                )
                                payload["conversationLink"] = (
                                    f"https://teams.cloud.microsoft/api/chatsvc/{echo_region}/v1/"
                                    f"users/ME/conversations/{encoded_conv}"
                                )
                                async with session.post(retry_url, json=payload, headers=headers) as retry_resp:
                                    retry_body = await retry_resp.text()
                                    if retry_resp.status in (201, 202):
                                        logger.info("Reply delivered to %s via chatsvc API (region=%s)",
                                                   conversation_id[:30], echo_region)
                                        return True
                                    # Retry also returned 200 — may still be wrong region
                                    logger.warning("chatsvc retry returned %d (region=%s): %s",
                                                  retry_resp.status, echo_region, retry_body[:200])
                                    return False
                            else:
                                logger.warning(
                                    "chatsvc returned 200 with messages echo but no alternate region found — "
                                    "message likely NOT delivered (region=%s, bodyLen=%d)",
                                    region, len(resp_ok_body),
                                )
                                return False
                        else:
                            # 200 without messages echo — treat as success (some endpoints do this)
                            msg_id = resp_ok_json.get("OriginalArrivalTime") or resp_ok_json.get("id", "") if isinstance(resp_ok_json, dict) else ""
                            logger.info(
                                "Reply sent to %s via chatsvc API (status=200, msgId=%s, bodyLen=%d)",
                                conversation_id[:30], str(msg_id)[:40], len(resp_ok_body),
                            )
                            return True

                    resp_body = await resp.text()
                    logger.warning("chatsvc reply failed (%d): %s",
                                  resp.status, resp_body[:200])

                    # Auto-discover region from redirect or 404 "different cloud"
                    location = resp.headers.get("Location", "")
                    if resp.status in (301, 302, 404) and (
                        location or "different cloud" in resp_body.lower()
                    ):
                        new_region = _extract_region_from_url(location or resp_body)
                        if new_region and new_region != region:
                            set_chatsvc_region(new_region)
                            _persist_region(new_region)
                            logger.info("Auto-discovered region '%s' — retrying", new_region)
                            # Retry with correct region
                            retry_url = (
                                f"https://teams.cloud.microsoft/api/chatsvc/{new_region}/v1/"
                                f"users/ME/conversations/{encoded_conv}/messages"
                            )
                            payload["conversationLink"] = (
                                f"https://teams.cloud.microsoft/api/chatsvc/{new_region}/v1/"
                                f"users/ME/conversations/{encoded_conv}"
                            )
                            async with session.post(retry_url, json=payload, headers=headers) as retry_resp:
                                if retry_resp.status in (201, 202):
                                    logger.info("Reply delivered to %s via chatsvc API (region=%s)",
                                               conversation_id[:30], new_region)
                                    return True
                                retry_body = await retry_resp.text()
                                logger.warning("chatsvc retry failed (%d): %s",
                                              retry_resp.status, retry_body[:200])
        except Exception as e:
            logger.warning("chatsvc reply error: %s", e)

    # ── Fallback: send_message.py subprocess ─────────────────────────
    try:
        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "scripts.rich.send_message",
            "--to", conversation_id,
            "--body", body,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_TEAMS_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            logger.info("Reply sent to %s via send_message", conversation_id[:30])
            return True
        else:
            logger.warning("Reply failed (rc=%d): %s",
                          proc.returncode, stderr.decode(errors="replace")[:200])
            return False
    except Exception as e:
        logger.warning("Reply send error: %s", e)
        return False


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = _HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


_SUMMARY_DELIMITER = "---SUMMARY---"


def _split_reply_summary(stdout: str, prompt: str) -> tuple[str, str]:
    """Parse Agency stdout into (reply_body, summary_body).

    Protocol:
    - If stdout contains ``---SUMMARY---``, text before is the reply and
      text after is the summary.
    - Otherwise the full stdout is the reply, and a truncated version
      (first 300 chars) is used as the summary.

    Both parts are capped for safety: reply at 30 000 chars (chunked at send
    time), summary at 1000 chars (single message).
    """
    MAX_REPLY = 30_000  # chunking handles splitting; this is the absolute cap
    MAX_SUMMARY = 1000

    if _SUMMARY_DELIMITER in stdout:
        parts = stdout.split(_SUMMARY_DELIMITER, 1)
        reply = parts[0].strip()
        summary = parts[1].strip()
    else:
        reply = stdout.strip()
        # Auto-generate summary: first 300 chars of the reply
        summary = reply[:300]
        if len(reply) > 300:
            summary += "…"

    # Guard against empty reply
    if not reply:
        reply = f"(No output for: {prompt[:100]})"
    if not summary:
        summary = reply[:300]

    # Truncate for Teams safety
    if len(reply) > MAX_REPLY:
        reply = reply[:MAX_REPLY - 3] + "..."
    if len(summary) > MAX_SUMMARY:
        summary = summary[:MAX_SUMMARY - 3] + "..."

    return reply, summary


def _keyword_boundary_match(text: str, keyword: str) -> Optional[re.Match]:
    """Word-boundary match for a keyword inside text (case-insensitive).

    Returns the first re.Match or None.  Treats '@' as a word boundary so
    both '@tai' and 'tai' are matched as whole words, preventing false
    positives like 'details' or 'contain' when the keyword is short.
    """
    escaped = re.escape(keyword)
    pattern = rf"(?<!\w){escaped}(?!\w)"
    return re.search(pattern, text, re.IGNORECASE)


def matches_keyword(text: str, keyword: str, raw_html: str = "") -> bool:
    """Check if the text contains the keyword as a whole word (case-insensitive).

    Teams wraps @mentions in <at> tags — after HTML stripping, the leading
    '@' is lost (e.g. '@agent' becomes 'agent').  The bare-word fallback
    (without '@') is ONLY used when the raw HTML actually contains an
    ``<at>`` tag wrapping the keyword, preventing false positives on plain
    uses of the word (e.g. 'agents', 'agent-based').

    Uses word-boundary regex to avoid substring false positives (e.g.
    keyword '@tai' must NOT match 'details' or 'maintain').
    """
    # Direct match (e.g. text literally contains '@agent')
    if _keyword_boundary_match(text, keyword):
        return True
    # Fallback: only if keyword starts with '@' AND raw HTML proves it was
    # an actual @mention (Teams <at> tag), not just the bare word.
    if keyword.startswith("@") and raw_html:
        bare = keyword[1:]
        at_tag_re = re.compile(rf"<at\b[^>]*>\s*{re.escape(bare)}\s*</at>", re.IGNORECASE)
        if at_tag_re.search(raw_html) and _keyword_boundary_match(text, bare):
            return True
    return False


def matches_sender(sender_mri: str, authorized_mri: str) -> bool:
    """Check if the sender MRI matches the authorized sender or runtime-detected MRI.

    Falls back to the MRI extracted from the JWT token at runtime ONLY when
    authorized_mri is not configured (placeholder/empty), which handles the
    first-run auto-detect scenario before identity is persisted to config.
    """
    # Prefer explicitly configured authorized_mri when it is set.
    if authorized_mri and "00000000-0000-0000-0000-000000000000" not in authorized_mri and authorized_mri == sender_mri:
        return True
    # Fallback: only use runtime-detected MRI when authorized_mri is not configured.
    if (not authorized_mri or "00000000-0000-0000-0000-000000000000" in authorized_mri) and _user_mri and _user_mri == sender_mri:
        return True
    return False


def is_duplicate(message_id: str) -> bool:
    """Check if we've already processed this message ID."""
    if message_id in _processed_ids:
        return True
    # Trim dedup buffer if too large
    if len(_processed_ids) >= _MAX_DEDUP_SIZE:
        # Remove oldest half (approximation — sets are unordered, but effective enough)
        to_remove = list(_processed_ids)[: _MAX_DEDUP_SIZE // 2]
        for mid in to_remove:
            _processed_ids.discard(mid)
    _processed_ids.add(message_id)
    return False


def extract_prompt(text: str, keyword: str, raw_html: str = "") -> str:
    """Extract the prompt text after the keyword.

    Handles both plain-text keywords ('@agent ...') and HTML-stripped
    @mentions where the raw HTML proves an ``<at>`` tag was present.

    Uses word-boundary regex to find the keyword position, avoiding
    false substring matches (e.g. 'tai' inside 'details').

    Examples:
        "@agent search emails about project status" → "search emails about project status"
        "agent search emails about project status"  → "search emails about project status"
          (only when raw_html contains <at>agent</at>)
        "@agent join General" → "join General"
    """
    m = _keyword_boundary_match(text, keyword)
    if m is None and keyword.startswith("@") and raw_html:
        bare = keyword[1:]
        at_tag_re = re.compile(rf"<at\b[^>]*>\s*{re.escape(bare)}\s*</at>", re.IGNORECASE)
        if at_tag_re.search(raw_html):
            m = _keyword_boundary_match(text, bare)
    if m is None:
        return text.strip()
    return text[m.end():].strip()


def is_command(prompt: str) -> Optional[tuple[str, str]]:
    """Check if the prompt is a built-in command.

    Returns (command, argument) or None if not a command.
    Commands: join, leave, list, status, stop, resume, cancel, dispatches
    """
    prompt_lower = prompt.lower().strip()
    for cmd in ("join", "leave", "list", "status", "stop",
                "resume", "cancel", "dispatches"):
        if prompt_lower == cmd:
            return cmd, ""
        if prompt_lower.startswith(cmd + " "):
            return cmd, prompt[len(cmd):].strip()
    return None


class MessageHandler:
    """Processes incoming EventMessages based on filter rules."""

    def __init__(self, config: MonitorConfig, start_time: float,
                 prompt_queue=None):
        self.config = config
        self.start_time = start_time
        self._dispatch_count = 0
        self._command_count = 0
        self._rejected_count = 0
        self._prompt_queue = prompt_queue  # Optional PromptQueue for PTY bridge

    def _reply_target(self, event: EventMessage) -> str:
        """Resolve where to send summaries/status messages.

        Uses dispatch.response_conversation if set, otherwise falls back
        to the self-chat (48:notes) so summaries don't pollute group chats.
        """
        rc = self.config.dispatch.response_conversation
        return rc if rc else "48:notes"

    def _is_self_chat(self, conversation_id: str) -> bool:
        """Check if a conversation is the self-chat (48:notes) or typed 'Self'."""
        if conversation_id == "48:notes":
            return True
        for conv in self.config.monitored_conversations:
            if conv.id == conversation_id and conv.type == "Self":
                return True
        return False

    async def handle(self, event: EventMessage) -> None:
        """Main entry point — called by TrouterClient for each EventMessage."""
        # --- Filter pipeline ---

        # 1. Dedup
        if event.message_id and is_duplicate(event.message_id):
            logger.debug("Duplicate message: %s", event.message_id[:20])
            return

        # 2. Strip HTML for text matching
        plain_text = strip_html(event.content)
        if not plain_text:
            return

        # 2b. Self-loop prevention — skip messages sent by the agent
        _loop_prefix = self.config.reply_prefix.rstrip() if self.config.reply_prefix else "Agency Cowork:"
        if plain_text.lstrip().startswith(_loop_prefix):
            logger.debug("Skipping agent-sent message (self-loop prevention)")
            return

        # 3. Keyword match (pass raw HTML so @mention detection works)
        raw_html = event.content or ""
        if not matches_keyword(plain_text, self.config.keyword, raw_html):
            return  # Not for us

        # 4. Sender verification
        if not matches_sender(event.sender_mri, self.config.authorized_sender.mri):
            logger.warning(
                "Keyword match from unauthorized sender: %s (%s)",
                event.sender_name, event.sender_mri,
            )
            self._rejected_count += 1
            return

        # 5. Conversation check
        if not self.config.is_monitored(event.conversation_id):
            logger.info(
                "Keyword match in unmonitored conversation: %s",
                event.conversation_id[:40],
            )
            self._rejected_count += 1
            return

        # --- Passed all filters ---
        prompt = extract_prompt(plain_text, self.config.keyword, raw_html)
        logger.info(
            "Accepted message from %s in %s: %s",
            event.sender_name, event.conversation_id[:30], prompt[:100],
        )

        # Check for built-in commands
        cmd_result = is_command(prompt)
        if cmd_result:
            _log_prompt_to_memory(prompt, event, kind="command")
            await self._handle_command(cmd_result[0], cmd_result[1], event)
            return

        # Log the triggered prompt to memory before dispatch
        _log_prompt_to_memory(prompt, event, kind="dispatch")

        # Prompt injection guard — scan before dispatch.
        # Self-chat (48:notes / type=Self) is inherently trusted — the user is
        # talking directly to themselves.  Log the match but proceed with dispatch.
        # External/group conversations remain fully guarded (block + notify).
        injection_result = scan_for_injections(prompt, source="monitor")
        if not injection_result.clean:
            is_self = self._is_self_chat(event.conversation_id)
            matched_patterns = ", ".join(f.pattern_name for f in injection_result.findings)
            log_injection_event(injection_result, text_preview=prompt[:200])
            _log_prompt_to_memory(
                prompt, event, kind="dispatch",
                result="injection_warning" if is_self else "blocked_injection",
                output_summary=f"Injection detected: {injection_result.max_severity} — {matched_patterns}",
            )
            if is_self:
                logger.info(
                    "Prompt guard match in SELF-CHAT (%s) — proceeding: %s",
                    injection_result.max_severity, matched_patterns,
                )
                # Informational reply so user sees what triggered
                try:
                    info_body = (
                        f"ℹ️ **Prompt Guard Notice** (self-chat — not blocked)\n\n"
                        f"**Severity:** {injection_result.max_severity}\n"
                        f"**Patterns:** {matched_patterns}\n"
                        f"Proceeding with dispatch. This would be blocked in external chats."
                    )
                    await _reply_to_chat(event.conversation_id, info_body)
                except Exception:
                    pass  # best-effort
            else:
                logger.warning(
                    "BLOCKED prompt injection (%s) from %s: %s",
                    injection_result.max_severity, event.sender_name, prompt[:100],
                )
                await _notify_injection(injection_result, prompt, event)
                self._rejected_count += 1
                return

        # Dispatch to Agency Copilot
        await self._dispatch_prompt(prompt, event)

    async def _handle_command(self, cmd: str, arg: str, event: EventMessage) -> None:
        """Handle built-in commands (join, leave, list, status, stop, resume, cancel, dispatches)."""
        self._command_count += 1

        if cmd == "join":
            await self._cmd_join(arg, event)
        elif cmd == "leave":
            await self._cmd_leave(arg, event)
        elif cmd == "list":
            await self._cmd_list(event)
        elif cmd == "status":
            await self._cmd_status(event)
        elif cmd == "stop":
            await self._cmd_stop(event)
        elif cmd == "resume":
            await self._cmd_resume(arg, event)
        elif cmd == "cancel":
            await self._cmd_cancel(arg, event)
        elif cmd == "dispatches":
            await self._cmd_dispatches(arg, event)

    async def _cmd_join(self, name: str, event: EventMessage) -> None:
        """Join a channel/group chat for monitoring."""
        if not name:
            await _reply_to_chat(event.conversation_id, "Usage: `@agent join <channel or chat name>`")
            return

        # Try to resolve via cache-manager
        cache_mgr = Path(__file__).resolve().parent.parent / "cache-manager.py"
        result = None

        # Try channel lookup first, then chat
        for lookup_type in ("channel", "chat"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python", str(cache_mgr), f"lookup-{lookup_type}", name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(cache_mgr.parent.parent),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0 and stdout:
                    result = json.loads(stdout.decode())
                    break
            except Exception as e:
                logger.debug("Lookup %s for '%s' failed: %s", lookup_type, name, e)

        if result and isinstance(result, dict):
            conv_id = result.get("id", "")
            conv_name = result.get("displayName", result.get("topic", name))
            conv_type = "Channel" if "thread.tacv2" in conv_id else "Group"

            if self.config.add_conversation(conv_id, conv_name, conv_type):
                save_config(self.config)
                logger.info("Joined: %s (%s)", conv_name, conv_id[:30])
                await _reply_to_chat(event.conversation_id, f"✅ Now monitoring **{conv_name}** ({conv_type})")
            else:
                logger.info("Already monitoring: %s", conv_name)
                await _reply_to_chat(event.conversation_id, f"Already monitoring **{conv_name}**")
        else:
            logger.warning("Could not resolve '%s' from cache", name)
            await _reply_to_chat(event.conversation_id, f"❌ Could not find '{name}' in cache")

    async def _cmd_leave(self, name: str, event: EventMessage) -> None:
        """Leave (stop monitoring) a conversation."""
        # Find by name or ID
        target = None
        for conv in self.config.monitored_conversations:
            if name.lower() in conv.name.lower() or name == conv.id:
                target = conv
                break

        if target:
            if target.id == "48:notes":
                await _reply_to_chat(event.conversation_id, "Cannot leave self-chat (48:notes)")
                return
            self.config.remove_conversation(target.id)
            save_config(self.config)
            logger.info("Left: %s (%s)", target.name, target.id[:30])
            await _reply_to_chat(event.conversation_id, f"✅ Stopped monitoring **{target.name}**")
        else:
            logger.warning("Not monitoring anything matching '%s'", name)
            await _reply_to_chat(event.conversation_id, f"Not monitoring anything matching '{name}'")

    async def _cmd_list(self, event: EventMessage) -> None:
        """List all monitored conversations."""
        lines = ["**Monitored conversations:**"]
        for conv in self.config.monitored_conversations:
            lines.append(f"- {conv.name} ({conv.type})")
        reply = "\n".join(lines)
        logger.info(reply)
        await _reply_to_chat(event.conversation_id, reply)

    async def _cmd_status(self, event: EventMessage) -> None:
        """Report service status."""
        uptime = time.time() - self.start_time
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        status_msg = (
            f"**Monitor Service Status**\n\n"
            f"- **Uptime:** {hours}h {minutes}m {seconds}s\n"
            f"- **Monitored:** {len(self.config.monitored_conversations)} conversations\n"
            f"- **Dispatched:** {self._dispatch_count} prompts\n"
            f"- **Commands:** {self._command_count}\n"
            f"- **Rejected:** {self._rejected_count}"
        )
        logger.info(status_msg)
        await _reply_to_chat(event.conversation_id, status_msg)

    async def _cmd_stop(self, event: EventMessage) -> None:
        """Signal the service to stop."""
        logger.info("Stop command received -- shutting down")
        # The service.py main loop checks a stop flag
        raise SystemExit(0)

    # ── Dispatch management commands ─────────────────────────────────

    async def _cmd_resume(self, arg: str, event: EventMessage) -> None:
        """Resume pending dispatches from a previous session."""
        if not self._prompt_queue or not self._prompt_queue.dispatch_store:
            await _reply_to_chat(event.conversation_id, "No dispatch store available.")
            return

        store = self._prompt_queue.dispatch_store
        pending = store.get_pending()
        if not pending:
            await _reply_to_chat(event.conversation_id, "No pending dispatches to resume.")
            return

        arg_lower = arg.lower().strip()
        if arg_lower == "all" or not arg_lower:
            to_resume = pending
        else:
            try:
                indices = {int(x.strip()) for x in arg_lower.split(",")}
                to_resume = [
                    rec for i, rec in enumerate(pending, 1) if i in indices
                ]
            except ValueError:
                await _reply_to_chat(
                    event.conversation_id,
                    "Usage: <code>resume all</code> or <code>resume 1,3,5</code>",
                )
                return

        if not to_resume:
            await _reply_to_chat(event.conversation_id, "No matching dispatches found.")
            return

        resumed = 0
        for rec in to_resume:
            fake_event = EventMessage(
                conversation_id=rec.conversation_id,
                message_id="",
                sender_name=rec.sender_name,
                sender_mri=rec.sender_mri,
                content=rec.prompt,
                compose_time="",
            )
            # Cancel the old record before re-enqueue (prevents phantom duplicates)
            store.cancel(rec.id)
            try:
                await self._prompt_queue.enqueue(
                    conversation_id=rec.conversation_id,
                    prompt=rec.prompt,
                    event=fake_event,
                    response_conversation=self._reply_target(event),
                )
                resumed += 1
            except Exception as e:
                logger.error("Failed to resume dispatch %s: %s", rec.id, e)

        await _reply_to_chat(
            event.conversation_id,
            f"<b>Resumed {resumed} dispatch(es).</b>",
        )

    async def _cmd_cancel(self, arg: str, event: EventMessage) -> None:
        """Cancel pending dispatches."""
        if not self._prompt_queue or not self._prompt_queue.dispatch_store:
            await _reply_to_chat(event.conversation_id, "No dispatch store available.")
            return

        store = self._prompt_queue.dispatch_store
        arg_lower = arg.lower().strip()

        if arg_lower in ("pending", "all", ""):
            pending = store.get_pending()
            for rec in pending:
                store.cancel(rec.id)
            await _reply_to_chat(
                event.conversation_id,
                f"<b>Cancelled {len(pending)} pending dispatch(es).</b>",
            )
        else:
            pending = store.get_pending()
            try:
                indices = {int(x.strip()) for x in arg_lower.split(",")}
                cancelled = 0
                for i, rec in enumerate(pending, 1):
                    if i in indices:
                        store.cancel(rec.id)
                        cancelled += 1
                await _reply_to_chat(
                    event.conversation_id,
                    f"<b>Cancelled {cancelled} dispatch(es).</b>",
                )
            except ValueError:
                await _reply_to_chat(
                    event.conversation_id,
                    "Usage: <code>cancel pending</code> or <code>cancel 1,3</code>",
                )

    async def _cmd_dispatches(self, arg: str, event: EventMessage) -> None:
        """Show dispatch history and status."""
        if not self._prompt_queue or not self._prompt_queue.dispatch_store:
            await _reply_to_chat(event.conversation_id, "No dispatch store available.")
            return

        store = self._prompt_queue.dispatch_store
        arg_lower = arg.lower().strip()

        if arg_lower == "pending":
            records = store.get_pending()
            title = "Pending dispatches"
        elif arg_lower == "incomplete":
            records = store.get_incomplete()
            title = "Incomplete dispatches"
        else:
            records = store.get_recent(limit=15)
            title = "Recent dispatches (last 15)"

        if not records:
            await _reply_to_chat(event.conversation_id, f"No {title.lower()} found.")
            return

        lines = [f"<b>{title}:</b><br>"]
        for i, rec in enumerate(records, 1):
            lines.append(rec.to_display(i) + "<br>")

        await _reply_to_chat(event.conversation_id, "\n".join(lines))

    async def _dispatch_prompt(self, prompt: str, event: EventMessage) -> None:
        """Dispatch a prompt to Agency Copilot.

        Tries the persistent PTY bridge first (via PromptQueue) for near-instant
        follow-up dispatch.  Falls back to subprocess spawn if the bridge is
        unavailable or ``use_persistent_pty`` is disabled.
        """
        self._dispatch_count += 1
        reply_to = self._reply_target(event)
        source_conv = event.conversation_id
        is_same = source_conv == reply_to
        is_self_chat = self._is_self_chat(event.conversation_id)

        # Send receipt to source conversation (immediate feedback to sender)
        # Skip receipt here when using PTY bridge — prompt_queue sends its own
        # when the item is actually dequeued for processing.
        if self.config.dispatch.send_receipt and not (
            self._prompt_queue and self.config.dispatch.use_persistent_pty
        ):
            await _reply_to_chat(
                source_conv,
                f"\u23f3 **Processing:** {prompt[:200]}"
            )

        # ── Try PTY bridge path ──────────────────────────────────────────
        if self._prompt_queue and self.config.dispatch.use_persistent_pty:
            try:
                logger.info(
                    "Dispatch #%d via PTY bridge: %s",
                    self._dispatch_count, prompt[:150],
                )
                await self._prompt_queue.enqueue(
                    conversation_id=source_conv,
                    prompt=prompt,
                    event=event,
                    response_conversation=reply_to,
                    is_self_chat=is_self_chat,
                )
                return
            except Exception as e:
                logger.warning(
                    "Dispatch #%d PTY bridge failed, falling back to subprocess: %s",
                    self._dispatch_count, e,
                )
                # Fall through to subprocess path

        # ── Subprocess fallback path ─────────────────────────────────────
        await self._dispatch_prompt_subprocess(
            prompt, event, reply_to, source_conv, is_same, is_self_chat,
        )

    async def _dispatch_prompt_subprocess(
        self,
        prompt: str,
        event: EventMessage,
        reply_to: str,
        source_conv: str,
        is_same: bool,
        is_self_chat: bool,
    ) -> None:
        """Dispatch via subprocess spawn (original path / fallback).

        Agency writes its response to a designated file (avoiding stdout
        pollution from execution trace markers). The monitor reads the file
        and sends:
        - The reply → source conversation (event.conversation_id)
        - A summary → response_conversation (self-chat)
        """
        import uuid as _uuid

        # ── Resolve CLI binary before anything else ──────────────────────
        cli_path = _get_cli_binary()
        if not cli_path:
            err_msg = (
                "CLI binary not found. Install Agency CLI or Claude Code, "
                "or set the path in the Electron UI Settings."
            )
            logger.error("Dispatch #%d: %s", self._dispatch_count, err_msg)
            await _reply_to_chat(
                source_conv,
                f"\u274c **Dispatch failed:** {err_msg}"
            )
            return

        logger.info(
            "Dispatching prompt #%d via subprocess (cli=%s): %s",
            self._dispatch_count, cli_path, prompt[:150],
        )

        cwd = self.config.dispatch.working_directory or str(_TEAMS_ROOT.parent.parent)
        timeout = self.config.dispatch.timeout_minutes * 60

        # ── Ensure AGENTS.md/CLAUDE.md/GEMINI.md are accessible in the CWD ──
        # When dispatch CWD differs from the agency-cowork root, the CLI can't
        # find these files (it only auto-loads from CWD).  Symlink them into the
        # dispatch CWD so the agent has its full identity and skill definitions.
        agency_root = Path(_TEAMS_ROOT.parent.parent).resolve()
        dispatch_path = Path(cwd).resolve()
        _linked_files: list[Path] = []
        if dispatch_path != agency_root:
            for fname in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                src = agency_root / fname
                dst = dispatch_path / fname
                if src.exists() and not dst.exists():
                    try:
                        dst.symlink_to(src)
                        _linked_files.append(dst)
                        logger.debug("Symlinked %s → %s", dst, src)
                    except OSError:
                        # Symlinks may fail on Windows without admin; copy instead
                        try:
                            import shutil
                            shutil.copy2(str(src), str(dst))
                            _linked_files.append(dst)
                            logger.debug("Copied %s → %s", dst, src)
                        except OSError as copy_err:
                            logger.warning("Could not link/copy %s to %s: %s", fname, cwd, copy_err)
            # Add symlinked files to .gitignore in the target repo
            if _linked_files and (dispatch_path / ".git").exists():
                try:
                    gitignore = dispatch_path / ".gitignore"
                    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
                    additions = [f.name for f in _linked_files if f.name not in existing]
                    if additions:
                        with open(gitignore, "a", encoding="utf-8") as gi:
                            gi.write("\n# Agency Cowork agent identity (auto-linked by monitor)\n")
                            for name in additions:
                                gi.write(f"{name}\n")
                except OSError as gi_err:
                    logger.warning("Could not update .gitignore in %s: %s", cwd, gi_err)

        # Use persistent session for self-chat conversations so the agent
        # maintains conversational context across dispatches.
        session_id = self.config.dispatch.persistent_session_id if is_self_chat else ""

        # Create response file for Agency to write into
        dispatch_dir = _TEAMS_ROOT / "logs" / "dispatch"
        dispatch_dir.mkdir(parents=True, exist_ok=True)
        response_file = dispatch_dir / f"response-{_uuid.uuid4().hex[:12]}.md"

        wrapped_prompt = (
            f"You received the following request from {event.sender_name} "
            f"in a Teams chat (conversation ID: {event.conversation_id}).\n\n"
            f"REQUEST: {prompt}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Execute the request above. Use the skills in AGENTS.md "
            f"whenever a matching skill exists — read the skill's SKILL.md "
            f"for usage. For general ADO tasks (query, search, create, "
            f"update, comment), use the ado skill (cd skills/ado && "
            f"python -m scripts.ado_query / ado_update). For Landing "
            f"Zone-specific tasks (LZ sync, grading, WoW, state machine), "
            f"use the landing-zone skill (cd skills/landing-zone && "
            f"python -m scripts.lz_update / lz_query / lz_sync / "
            f"lz_analyze). Do NOT write ad-hoc scripts or raw REST API "
            f"calls when a skill already handles the operation.\n"
            f"2. Write your COMPLETE response into the file:\n"
            f"   {response_file}\n"
            f"   This file will be delivered to the chat automatically.\n"
            f"3. CRITICAL: Do NOT use the Teams skill, do NOT send messages, "
            f"do NOT open browsers, do NOT call any Teams API scripts. The "
            f"monitor service handles all Teams communication. Just write "
            f"your response to the file above.\n"
            f"4. Use Teams-compatible HTML for rich formatting (bold, lists, "
            f"links). Keep the response concise and conversational.\n"
            f"5. Do NOT include execution trace, tool output, or debugging "
            f"artifacts in the response file \u2014 only the final message the "
            f"recipient should see.\n"
            f"6. MANDATORY: After the main reply, add a line containing only "
            f"'---SUMMARY---' followed by a structured completion summary "
            f"including:\n"
            f"   - What actions you took (1-2 sentences)\n"
            f"   - Any files generated, modified, or sent (list paths/names)\n"
            f"   - Any errors or issues encountered\n"
            f"   - Status: success / partial / failed\n"
            f"   This summary is required even if the task seems trivial. "
            f"It will be logged for the operator.\n"
            f"7. IMPORTANT: Create the file using the create tool or by writing "
            f"to it. The monitor will read it after you exit."
        )

        # Build command: use resolved CLI path instead of config string.
        # Config command is "agency copilot" (or "agency copilot -p") → take
        # subcommands after the binary name and prepend the resolved path.
        # Strip -p/--prompt from config — we add it explicitly before the
        # prompt to guarantee correct position (fixes #97, #98).
        cfg_parts = self.config.dispatch.command.split()
        # cfg_parts[0] is "agency" or "claude" — replace with resolved path
        if len(cfg_parts) > 1:
            sub_args = [a for a in cfg_parts[1:] if a not in ("-p", "--prompt")]
        else:
            sub_args = ["copilot"]
        cmd_parts = [cli_path] + sub_args

        # Append --resume for persistent session (self-chat thread).
        # Use equals syntax: copilot.exe 1.0.8 declares --resume[=sessionId]
        # and space-separated form treats the value as a positional arg (#97).
        if session_id:
            cmd_parts.append(f"--resume={session_id}")
            logger.info(
                "Dispatch #%d using persistent session %s",
                self._dispatch_count, session_id[:12],
            )
        # Always add -p immediately before the prompt so it isn't treated as
        # a bare positional argument (#97) and never duplicated (#98).
        cmd_parts.append("-p")
        cmd_parts.append(wrapped_prompt)

        logger.info(
            "Dispatch #%d command: %s %s [prompt len=%d] cwd=%s",
            self._dispatch_count, cmd_parts[0],
            " ".join(cmd_parts[1:-1]),  # log args but not the full prompt
            len(wrapped_prompt), cwd,
        )

        # Build subprocess environment: inherit parent env + inject cached
        # Teams token so the child process NEVER opens a browser for auth.
        dispatch_env = dict(os.environ)
        if _chatsvc_token:
            dispatch_env["TEAMS_CHATSVC_TOKEN"] = _chatsvc_token
            logger.info(
                "Dispatch #%d: injecting TEAMS_CHATSVC_TOKEN (%d chars)",
                self._dispatch_count, len(_chatsvc_token),
            )
        if _chatsvc_region:
            dispatch_env["TEAMS_CHATSVC_REGION"] = _chatsvc_region

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=dispatch_env,
                start_new_session=True,  # own process group so killpg doesn't hit the monitor
            )
            logger.info(
                "Dispatch #%d subprocess started (PID %d)",
                self._dispatch_count, proc.pid,
            )

            # ── Stream stderr to log in a background task ─────────────
            stderr_lines: list[str] = []

            async def _stream_stderr():
                assert proc.stderr is not None
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace").rstrip()
                    stderr_lines.append(text)
                    # Log first 20 lines at INFO for visibility, rest at DEBUG
                    if len(stderr_lines) <= 20:
                        logger.info("Dispatch #%d stderr: %s",
                                    self._dispatch_count, text[:200])
                    else:
                        logger.debug("Dispatch #%d stderr: %s",
                                     self._dispatch_count, text[:200])

            stderr_task = asyncio.create_task(_stream_stderr())

            try:
                # Wait for completion with timeout
                stdout_bytes = await asyncio.wait_for(
                    proc.stdout.read() if proc.stdout else asyncio.sleep(0),
                    timeout=timeout,
                )
                await proc.wait()
                await stderr_task  # drain remaining stderr

                if isinstance(stdout_bytes, bytes):
                    stdout_text = stdout_bytes.decode(errors="replace").strip()
                else:
                    stdout_text = ""

                logger.info(
                    "Dispatch #%d finished (PID %d, rc=%s, stdout=%d bytes, stderr=%d lines)",
                    self._dispatch_count, proc.pid, proc.returncode,
                    len(stdout_text), len(stderr_lines),
                )

                if proc.returncode == 0:
                    # Primary: read the response file Agency wrote
                    result = ""
                    if response_file.exists():
                        result = response_file.read_text(encoding="utf-8").strip()
                        logger.info(
                            "Dispatch #%d completed \u2014 read %d bytes from %s",
                            self._dispatch_count, len(result), response_file.name,
                        )
                    else:
                        logger.warning(
                            "Dispatch #%d: response file not found (%s), "
                            "falling back to stdout (%d bytes)",
                            self._dispatch_count, response_file.name,
                            len(stdout_text),
                        )
                        result = stdout_text

                    reply_body, summary_body = _split_reply_summary(
                        result, prompt,
                    )

                    _log_prompt_to_memory(
                        prompt, event, kind="dispatch",
                        result="success", output_summary=summary_body[:500],
                    )

                    # Send reply to source; always send summary to response conv
                    tasks = [_reply_to_chat(event.conversation_id, reply_body)]
                    if reply_to:
                        if is_same:
                            # Self-chat: append summary as separate follow-up
                            if summary_body and summary_body != reply_body[:300]:
                                tasks.append(_reply_to_chat(
                                    reply_to,
                                    f"📋 **Summary:** {summary_body}",
                                ))
                        else:
                            tasks.append(_reply_to_chat(
                                reply_to,
                                f"✅ **Done:** {prompt[:100]}\n\n{summary_body}",
                            ))
                    await asyncio.gather(*tasks)
                else:
                    err_text = "\n".join(stderr_lines[-10:]) or f"Exit code {proc.returncode}"
                    logger.warning("Dispatch #%d failed (rc=%d): %s",
                                    self._dispatch_count, proc.returncode, err_text[:500])
                    _log_prompt_to_memory(
                        prompt, event, kind="dispatch",
                        result="failed", output_summary=err_text[:500],
                    )
                    # Include actionable info in the Teams reply
                    rc = proc.returncode
                    hint = ""
                    if rc == 3221225786:
                        hint = " (STATUS_STACK_BUFFER_OVERRUN — try restarting or reinstalling the CLI)"
                    elif rc == 1:
                        hint = " (check CLI auth: run 'agency copilot' then '/login')"
                    error_msg = (
                        f"❌ **Failed:** {prompt[:100]}\n\n"
                        f"Exit code {rc}{hint}\n"
                        f"Last stderr: {err_text[-200:]}"
                    )
                    await _reply_to_chat(source_conv, error_msg)
                    if reply_to and not is_same:
                        await _reply_to_chat(reply_to, error_msg)
            except asyncio.TimeoutError:
                # Kill the entire process tree — copilot.exe child processes
                # can outlive the agency.exe wrapper (zombie accumulation).
                _kill_process_tree(proc.pid)
                # Reap the zombie so it doesn't linger in the process table
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                stderr_task.cancel()
                logger.error("Dispatch #%d timed out after %ds (PID %d)",
                              self._dispatch_count, timeout, proc.pid)
                _log_prompt_to_memory(
                    prompt, event, kind="dispatch",
                    result="timeout", output_summary=f"Timed out after {timeout}s",
                )
                timeout_msg = f"⏰ **Timed out:** {prompt[:100]} (after {timeout // 60}min)"
                await _reply_to_chat(source_conv, timeout_msg)
                if reply_to and not is_same:
                    await _reply_to_chat(reply_to, timeout_msg)
            finally:
                # Clean up response file
                if response_file.exists():
                    try:
                        response_file.unlink()
                    except OSError:
                        pass
                # Clean up symlinked/copied agent identity files
                for lf in _linked_files:
                    try:
                        lf.unlink()
                    except OSError:
                        pass

        except FileNotFoundError:
            # CLI binary exists on disk but isn't executable, or disappeared
            global _cached_cli_path
            _cached_cli_path = None  # force re-resolve next time
            err_msg = f"CLI binary not executable: {cli_path}"
            logger.error("Dispatch #%d: %s", self._dispatch_count, err_msg)
            _log_prompt_to_memory(
                prompt, event, kind="dispatch",
                result="error", output_summary=err_msg,
            )
            await _reply_to_chat(
                reply_to,
                f"\u274c **Error:** {err_msg}"
            )

        except Exception as e:
            logger.error("Dispatch #%d error: %s", self._dispatch_count, e)
            _log_prompt_to_memory(
                prompt, event, kind="dispatch",
                result="error", output_summary=str(e)[:500],
            )
            await _reply_to_chat(
                reply_to,
                f"\u274c **Error:** {prompt[:100]}\n\n{str(e)[:200]}"
            )
