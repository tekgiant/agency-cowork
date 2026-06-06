"""Authenticated Teams browser session.

Uses ``playwright.chromium.launch_persistent_context`` with ``channel='msedge'``
to reuse the **real Edge work-profile session**.  The browser is kept alive so
that all API calls can be executed *inside the browser context* via
``page.evaluate(fetch(...))``.  This sidesteps the cookie / session-token
requirements that the ``teams.cloud.microsoft`` proxy enforces — requests made
through the browser carry all the right cookies, headers, and origins automatically.

This module provides:

  - ``UserInfo``      — dataclass with ``user_mri``, ``display_name``, ``user_id``.
  - ``TeamsSession``  — async context-manager wrapping Playwright + Edge.

        async with TeamsSession() as session:
            result = await session.fetch("POST", url, body=payload)

  - ``clear_session()`` — deletes the persistent browser profile.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Playwright,
    Request,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEAMS_URL = "https://teams.cloud.microsoft/"

# Persistent browser profile — uses real Edge User Data directory for M365 auth.
# Requires Edge to be fully closed (no msedge.exe processes) before launching.
# Falls back to a standalone profile if real Edge profile is unavailable.
EDGE_USER_DATA = Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"
BROWSER_PROFILE_DIR = Path.home() / ".teams-agent" / "browser-profile"

# Timeouts
_HEADLESS_READY_TIMEOUT = 30   # seconds — headless Teams page load
_HEADED_READY_TIMEOUT = 120    # seconds — allows time for interactive MFA

# URL fragments that indicate Teams API traffic (used to detect readiness)
_API_URL_PATTERNS = ("chatsvc", "csa/api", "authsvc")

# We capture the chatsvc Bearer token to decode user identity (MRI, display
# name, user_id).  We do NOT use the token directly for httpx calls — all
# real API traffic goes through ``page.evaluate(fetch(...))``.
_CHATSVC_URL_PATTERN = "chatsvc"


# ---------------------------------------------------------------------------
# UserInfo — lightweight identity metadata
# ---------------------------------------------------------------------------

@dataclass
class UserInfo:
    """User identity extracted from the captured Bearer JWT."""

    user_mri: str
    """User's MRI identifier, e.g. ``8:orgid:<guid>``."""

    display_name: str
    """User's display name from the JWT ``name`` claim."""

    user_id: str
    """User's AAD object-id GUID (bare GUID without ``8:orgid:`` prefix)."""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# JWT helpers (used only to extract identity from a captured token)
# ---------------------------------------------------------------------------

def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload of a JWT without verifying the signature."""
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _token_to_user_info(token: str) -> UserInfo:
    """Parse a JWT to extract user identity."""
    claims = _decode_jwt_payload(token)
    oid = claims.get("oid", "")
    user_mri = f"8:orgid:{oid}" if oid else ""
    display_name = claims.get("name") or claims.get("preferred_username") or ""
    return UserInfo(user_mri=user_mri, display_name=display_name, user_id=oid)


# ---------------------------------------------------------------------------
# Readiness detection — wait until Teams fires its first API request
# ---------------------------------------------------------------------------

class _TokenProbe:
    """Watches outgoing requests and captures Bearer tokens per service.

    Different Teams API endpoints use different tokens (different audiences).
    We capture tokens keyed by URL pattern so the session can inject the
    right ``Authorization`` header for each ``fetch()`` call.
    """

    # URL fragment → service key
    # Note: "api/mt/" matches all regions (amer, noam-pilot2, emea, etc.)
    _SERVICE_PATTERNS = {
        "chatsvc": "chatsvc",
        "api/mt/": "mt",
        "csa/api": "csa",
        "authsvc": "authsvc",
    }

    def __init__(self) -> None:
        self.ready = False
        self.tokens: dict[str, str] = {}  # service_key → bearer token

    def handler(self, request: Request) -> None:
        url = request.url

        if not self.ready and any(p in url for p in self._SERVICE_PATTERNS):
            self.ready = True

        # Capture skypetoken from x-skypetoken header (used for AMS auth)
        skype_tok = request.headers.get("x-skypetoken", "")
        if skype_tok and "skype" not in self.tokens:
            self.tokens["skype"] = skype_tok

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return

        token = auth.split(" ", 1)[1]
        for fragment, key in self._SERVICE_PATTERNS.items():
            if fragment in url and key not in self.tokens:
                self.tokens[key] = token

    @property
    def chatsvc_token(self) -> str | None:
        """The token captured from chatsvc requests (used for identity)."""
        return self.tokens.get("chatsvc")


# ---------------------------------------------------------------------------
# TeamsSession — the primary public interface
# ---------------------------------------------------------------------------

class TeamsSession:
    """Persistent authenticated browser session for the Teams web client.

    Usage::

        async with TeamsSession() as session:
            print(session.user)  # UserInfo(…)
            data = await session.fetch("POST", url, body={"key": "value"})

    The browser is kept alive for the lifetime of the context manager so that
    every ``fetch()`` call runs inside the fully-authenticated browser context
    — cookies, tokens, and headers are handled by the browser automatically.
    """

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._tokens: dict[str, str] = {}  # service_key → Bearer token
        self.user: UserInfo | None = None

    # ── async context manager ────────────────────────────────────────

    async def __aenter__(self) -> "TeamsSession":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── connect / close ──────────────────────────────────────────────

    async def connect(self) -> UserInfo:
        """Launch Edge, navigate to Teams, wait until ready.

        Strategy (in order):
          0. Token-only — if ``TEAMS_CHATSVC_TOKEN`` env var or disk cache
             contains a valid token, skip the browser entirely. The session
             won't have a live browser page but ``_tokens`` will be populated
             for direct API calls. Use this when running as a dispatch child.
          1. CDP — launch a separate Edge process with ``--remote-debugging-port``
             using the standalone browser-profile, then ``connect_over_cdp``.
             Works regardless of whether Edge is already running.
          2. Real Edge User Data profile via ``launch_persistent_context``
             (requires Edge to be fully closed — exclusive profile lock).
          3. Standalone profile, ``launch_persistent_context``, headed
             (fallback for interactive MFA if CDP fails).

        The browser stays open after this call.

        Returns the ``UserInfo`` for the logged-in user.
        Raises ``TimeoutError`` if no session can be established.
        """
        import os as _os, time as _time

        # Strategy 0: Token-only — reuse a pre-acquired token (no browser).
        # This is set by the monitor dispatch to avoid opening Edge windows.
        env_token = _os.environ.get("TEAMS_CHATSVC_TOKEN", "")
        if env_token:
            exp = _decode_jwt_payload(env_token).get("exp")
            if exp and (float(exp) - _time.time()) > 30:
                self._tokens = {"chatsvc": env_token}
                user = _token_to_user_info(env_token)
                if user.user_mri:
                    self.user = user
                    return user

        # Also check disk cache (~/.teams-agent/token-cache.json)
        try:
            _cache_file = Path.home() / ".teams-agent" / "token-cache.json"
            if _cache_file.exists():
                _cache = json.loads(_cache_file.read_text(encoding="utf-8"))
                _entry = _cache.get("https://ic3.teams.office.com", {})
                _tok = _entry.get("token", "")
                _exp = _entry.get("expires_at", 0)
                if _tok and (_exp - _time.time()) > 30:
                    self._tokens = {"chatsvc": _tok}
                    user = _token_to_user_info(_tok)
                    if user.user_mri:
                        self.user = user
                        return user
        except Exception:
            pass

        # Strategy 1: CDP — always works, even with Edge open.
        user = await self._try_connect_cdp(timeout=_HEADED_READY_TIMEOUT)
        if user:
            self.user = user
            return user

        # Strategy 2: Real Edge profile via persistent context (Edge must be closed).
        if EDGE_USER_DATA.exists():
            import subprocess as _sp
            check = _sp.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"],
                capture_output=True, text=True,
            )
            if "msedge.exe" not in check.stdout:
                user = await self._try_connect(
                    headless=False,
                    timeout=_HEADED_READY_TIMEOUT,
                    profile_dir=EDGE_USER_DATA,
                    extra_args=["--profile-directory=Default"],
                )
                if user:
                    self.user = user
                    return user

        # Strategy 3: Standalone persistent context, headed (interactive MFA).
        print(
            "\n╔══════════════════════════════════════════════════════════╗\n"
            "║  CDP and real profile failed — opening Edge.            ║\n"
            "║  Please sign in if prompted.  The window will stay open ║\n"
            "║  in the background while the session is active.         ║\n"
            "╚══════════════════════════════════════════════════════════╝\n",
            flush=True,
        )
        user = await self._try_connect(headless=False, timeout=_HEADED_READY_TIMEOUT)
        if user:
            self.user = user
            return user

        raise TimeoutError(
            "Could not establish a Teams session. "
            "Make sure you can reach teams.cloud.microsoft/ in Edge and try again."
        )

    # ── CDP connect strategy ─────────────────────────────────────────

    _CDP_PORT = 9223  # avoid colliding with user's own debug port on 9222
    _edge_proc: "subprocess.Popen[bytes] | None" = None

    async def _try_connect_cdp(self, *, timeout: int) -> UserInfo | None:
        """Launch Edge manually with ``--remote-debugging-port`` and connect
        via CDP.  Uses the standalone browser-profile so it never conflicts
        with an already-running Edge instance.

        Returns ``UserInfo`` on success, ``None`` on failure.
        """
        import subprocess, time

        await self.close()

        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        edge_exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        if not Path(edge_exe).exists():
            edge_exe = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        if not Path(edge_exe).exists():
            return None  # Edge not installed

        try:
            self._edge_proc = subprocess.Popen([
                edge_exe,
                f"--user-data-dir={BROWSER_PROFILE_DIR}",
                f"--remote-debugging-port={self._CDP_PORT}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ])
            # Give Edge a moment to open the debug port
            time.sleep(2)

            self._pw = await async_playwright().start()
            browser = await self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self._CDP_PORT}",
                timeout=15_000,
            )
            self._context = browser.contexts[0]
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else await self._context.new_page()
            )
            probe = _TokenProbe()
            self._page.on("request", probe.handler)

            await self._page.goto(
                TEAMS_URL, wait_until="domcontentloaded", timeout=60_000
            )

            # Wait for chatsvc Bearer token
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                if probe.chatsvc_token:
                    break
                if "login.microsoftonline.com" in self._page.url:
                    # Redirect to login — session not cached, wait for user
                    pass
                await asyncio.sleep(0.5)

            if probe.chatsvc_token:
                # Collect remaining service tokens
                extra_deadline = asyncio.get_event_loop().time() + 5
                while asyncio.get_event_loop().time() < extra_deadline:
                    if len(probe.tokens) >= len(_TokenProbe._SERVICE_PATTERNS):
                        break
                    await asyncio.sleep(0.3)

                self._tokens = dict(probe.tokens)
                return _token_to_user_info(probe.chatsvc_token)

            # No token captured — clean up
            await self.close()
            return None

        except Exception:
            await self.close()
            return None

    async def close(self) -> None:
        """Shut down the browser session and any Edge subprocess."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        if self._edge_proc is not None:
            try:
                self._edge_proc.terminate()
                self._edge_proc.wait(timeout=5)
            except Exception:
                try:
                    self._edge_proc.kill()
                except Exception:
                    pass
            self._edge_proc = None

    # ── fetch — execute an API call through the browser ──────────────

    async def fetch(
        self,
        method: str,
        url: str,
        *,
        body: dict | list | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """Execute an HTTP request *inside* the browser via ``page.evaluate``.

        The browser automatically attaches cookies.  The ``Authorization``
        header is injected from the captured per-service Bearer tokens so
        that the Teams proxy authenticates the request.

        Args:
            method: HTTP method (``"GET"``, ``"POST"``, etc.).
            url: Full URL to call.
            body: Optional JSON-serialisable body (for POST/PUT/PATCH).
            extra_headers: Optional additional headers to merge.

        Returns:
            Parsed JSON response body.

        Raises:
            RuntimeError: If the session is not connected or the request fails.
        """
        if not self._page:
            raise RuntimeError("TeamsSession is not connected — call connect() first.")

        headers = {
            "Content-Type": "application/json",
            "BehaviorOverride": "redirectAs404",
            "x-ms-client-type": "web",
            "x-ms-test-user": "False",
            "x-ms-migration": "True",
        }

        # Inject the correct auth header based on URL
        token = self._resolve_token_for_url(url)
        if token:
            if "asyncgw.teams" in url:
                headers["Authorization"] = f"skype_token {token}"
            else:
                headers["Authorization"] = f"Bearer {token}"

        if extra_headers:
            headers.update(extra_headers)

        # Remove headers explicitly set to None (allows callers to suppress defaults)
        headers = {k: v for k, v in headers.items() if v is not None}

        # Build the fetch() options
        fetch_opts: dict[str, Any] = {
            "method": method.upper(),
            "headers": headers,
            "credentials": "include",
        }
        if body is not None:
            fetch_opts["body"] = json.dumps(body)

        js = """
        async ([url, opts]) => {
            const resp = await fetch(url, opts);
            const text = await resp.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch {}
            return {
                status: resp.status,
                statusText: resp.statusText,
                body: parsed,
                raw: text.substring(0, 2000),
                locationHeader: resp.headers.get('Location') || '',
            };
        }
        """

        result = await self._page.evaluate(js, [url, fetch_opts])
        status = result.get("status", 0)

        # ── Auto-discover chatsvc region from 404 "different cloud" ──
        # Teams returns 404 + Location header pointing to the correct
        # regional endpoint (e.g. noam-pilot2 instead of amer).  Retry
        # once with the corrected URL and update the module-level region.
        if (
            status == 404
            and "different cloud" in result.get("raw", "").lower()
            and "/api/chatsvc/" in url
        ):
            import re as _re
            location = result.get("locationHeader", "")
            raw_body = result.get("raw", "")
            # Try Location header first, then scan the response body
            source = location or raw_body
            m = _re.search(r"/api/chatsvc/([a-z0-9_-]+)/v\d", source, _re.IGNORECASE)
            if m:
                new_region = m.group(1)
                import scripts.rich.api_client as _rac
                _rac._CHATSVC_REGION = new_region
                _rac.CHATSVC_BASE = (
                    f"https://teams.cloud.microsoft/api/chatsvc/"
                    f"{new_region}/v1/users/ME"
                )
                os.environ["TEAMS_CHATSVC_REGION"] = new_region

                # Rewrite the URL with the correct region and retry
                retry_url = _re.sub(
                    r"/api/chatsvc/[a-z0-9_-]+/",
                    f"/api/chatsvc/{new_region}/",
                    url,
                    flags=_re.IGNORECASE,
                )
                # Also fix conversationLink inside the body if present
                if body is not None:
                    import json as _json
                    body_str = _json.dumps(body)
                    body_str = _re.sub(
                        r"/api/chatsvc/[a-z0-9_-]+/",
                        f"/api/chatsvc/{new_region}/",
                        body_str,
                        flags=_re.IGNORECASE,
                    )
                    fetch_opts["body"] = body_str

                result = await self._page.evaluate(js, [retry_url, fetch_opts])
                status = result.get("status", 0)

        if status >= 400:
            raise RuntimeError(
                f"Teams API returned {status} {result.get('statusText', '')}: "
                f"{result.get('raw', '')}"
            )

        return result.get("body") or {}

    async def fetch_upload(
        self,
        method: str,
        url: str,
        file_path: str,
        *,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """Upload a local file *through* the browser via ``page.evaluate``.

        Reads the file on the Python side, Base64-encodes it, then uses
        ``page.evaluate`` to decode it back into an ``ArrayBuffer`` and
        ``fetch()`` with the binary body.

        For cross-origin uploads (SharePoint, AMS), a temporary page is
        opened on the target origin so the browser sends same-origin cookies
        automatically — no CORS issues.

        Args:
            method: HTTP method (``"PUT"`` or ``"POST"``).
            url: Full upload URL.
            file_path: Absolute local path to the file to upload.
            content_type: MIME type for the ``Content-Type`` header
                (default: ``application/octet-stream``).
            extra_headers: Optional additional headers to merge.

        Returns:
            Parsed JSON response body (or empty dict).

        Raises:
            RuntimeError: If the session is not connected or the request fails.
            FileNotFoundError: If the local file does not exist.
        """
        if not self._context:
            raise RuntimeError("TeamsSession is not connected — call connect() first.")

        import base64 as b64mod
        from pathlib import Path as _P
        from urllib.parse import urlparse

        fp = _P(file_path)
        if not fp.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_bytes = fp.read_bytes()
        b64_data = b64mod.b64encode(raw_bytes).decode("ascii")

        headers: dict[str, str] = {"Content-Type": content_type}
        if extra_headers:
            headers.update(extra_headers)

        # Inject auth token for AMS uploads
        token = self._resolve_token_for_url(url)
        if token and "asyncgw.teams" in url:
            headers["Authorization"] = f"skype_token {token}"

        # Remove headers explicitly set to None
        headers = {k: v for k, v in headers.items() if v is not None}

        # Determine if the target URL is cross-origin from the main page
        target_origin = urlparse(url).scheme + "://" + urlparse(url).netloc
        main_origin = ""
        if self._page:
            main_origin = urlparse(self._page.url).scheme + "://" + urlparse(self._page.url).netloc

        cross_origin = target_origin != main_origin

        js = """
        async ([url, method, b64, headers]) => {
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

            const resp = await fetch(url, {
                method: method,
                headers: headers,
                body: bytes.buffer,
            });
            const text = await resp.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch {}
            return { status: resp.status, statusText: resp.statusText, body: parsed, raw: text.substring(0, 2000) };
        }
        """

        if cross_origin:
            # Open a temporary page on the target origin so fetch is same-origin
            # and the browser's SSO cookies are sent automatically.
            upload_page = await self._context.new_page()
            try:
                await upload_page.goto(
                    target_origin, wait_until="domcontentloaded", timeout=30_000
                )
                # Small wait to let SSO cookies settle
                await asyncio.sleep(1)
                result = await upload_page.evaluate(js, [url, method.upper(), b64_data, headers])
            finally:
                await upload_page.close()
        else:
            result = await self._page.evaluate(js, [url, method.upper(), b64_data, headers])

        status = result.get("status", 0)
        if status >= 400:
            raise RuntimeError(
                f"Upload returned {status} {result.get('statusText', '')}: "
                f"{result.get('raw', '')}"
            )

        return result.get("body") or {}

    # ── internals ────────────────────────────────────────────────────

    def _resolve_token_for_url(self, url: str) -> str | None:
        """Pick the right Bearer token for a given URL.

        Returns:
            A token string to use as ``Authorization: Bearer <token>``,
            or ``None`` if no token is needed.

        Note:
            For AMS URLs the returned string is already prefixed with
            ``skype_token`` so the caller must use it as
            ``Authorization: skype_token <token>``.
        """
        # AMS (asyncgw) uses skype_token auth, not Bearer
        if "asyncgw.teams" in url:
            return self._tokens.get("skype")
        for fragment, key in _TokenProbe._SERVICE_PATTERNS.items():
            if fragment in url:
                return self._tokens.get(key)
        # Fallback: try chatsvc token (most common)
        return self._tokens.get("chatsvc")

    async def _try_connect(
        self,
        *,
        headless: bool,
        timeout: int,
        profile_dir: Path | None = None,
        extra_args: list[str] | None = None,
    ) -> UserInfo | None:
        """Attempt to launch the browser and wait for readiness.

        Args:
            headless: Whether to run headless.
            timeout: Max seconds to wait for a chatsvc Bearer token.
            profile_dir: Browser profile directory. Defaults to
                ``BROWSER_PROFILE_DIR`` (standalone profile).
            extra_args: Additional Chromium args (e.g.
                ``["--profile-directory=Default"]`` for the real Edge profile).

        On failure returns ``None`` and cleans up.
        """
        # Clean up any prior state
        await self.close()

        use_dir = profile_dir or BROWSER_PROFILE_DIR
        use_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()

        launch_args = []
        if extra_args:
            launch_args.extend(extra_args)

        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                str(use_dir),
                headless=headless,
                channel="msedge",
                args=launch_args,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                ),
            )

            self._page = (
                self._context.pages[0]
                if self._context.pages
                else await self._context.new_page()
            )
            probe = _TokenProbe()
            self._page.on("request", probe.handler)

            await self._page.goto(
                TEAMS_URL, wait_until="domcontentloaded", timeout=60_000
            )

            # Wait for the probe to capture a Bearer token
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                if probe.chatsvc_token:
                    break
                if headless and "login.microsoftonline.com" in self._page.url:
                    break
                await asyncio.sleep(0.5)

            if probe.chatsvc_token:
                # Wait a few more seconds to collect tokens from other services
                extra_deadline = asyncio.get_event_loop().time() + 5
                while asyncio.get_event_loop().time() < extra_deadline:
                    if len(probe.tokens) >= len(_TokenProbe._SERVICE_PATTERNS):
                        break
                    await asyncio.sleep(0.3)

                self._tokens = dict(probe.tokens)
                return _token_to_user_info(probe.chatsvc_token)

            # Fallback: try sessionStorage
            if probe.ready:
                try:
                    token_str = await self._page.evaluate(
                        """() => {
                            for (let i = 0; i < sessionStorage.length; i++) {
                                const key = sessionStorage.key(i);
                                if (key && key.includes('token')) {
                                    const val = sessionStorage.getItem(key);
                                    if (val && val.split('.').length === 3) return val;
                                }
                            }
                            return null;
                        }"""
                    )
                    if token_str:
                        self._tokens = {"chatsvc": token_str}
                        return _token_to_user_info(token_str)
                except Exception:
                    pass

            # Failed — clean up
            await self.close()
            return None

        except Exception:
            await self.close()
            return None


# ---------------------------------------------------------------------------
# Utility: clear the persistent browser profile
# ---------------------------------------------------------------------------

def clear_session() -> None:
    """Delete the persistent browser profile, forcing a fresh login next time."""
    import shutil

    if BROWSER_PROFILE_DIR.exists():
        shutil.rmtree(BROWSER_PROFILE_DIR, ignore_errors=True)
        print("Browser profile cleared.", flush=True)
    else:
        print("No saved browser profile found.", flush=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear_session()
        return

    print("Connecting to Teams...", flush=True)
    async with TeamsSession() as session:
        assert session.user is not None
        print(json.dumps(session.user.to_dict(), indent=2))
        print("\nSession is live.  Press Ctrl+C to close.")
        try:
            await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    asyncio.run(_main())
