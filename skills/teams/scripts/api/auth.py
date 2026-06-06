"""Token manager for Teams API — Azure CLI primary, Playwright fallback.

Acquires Bearer tokens for ic3.teams.office.com (chatsvc + CSA endpoints)
and graph.microsoft.com (Graph API for channel operations).
Tokens are cached in-memory and on disk (~/.teams-agent/token-cache.json)
for cross-process reuse, and auto-refreshed before expiry.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("teams.api.auth")

# Token resources
RESOURCE_TEAMS = "https://ic3.teams.office.com"
RESOURCE_GRAPH = "https://graph.microsoft.com"

# Default token lifetime assumption (~50 min) when expiry unknown
_DEFAULT_LIFETIME_SECONDS = 3000
_MAX_REFRESH_BUFFER_SECONDS = 300
_MIN_REFRESH_BUFFER_SECONDS = 60
_REFRESH_BUFFER_RATIO = 0.10
_MIN_VALIDITY_REUSE_SECONDS = 30

# ── Persistent token cache ──────────────────────────────────────────────
# Stores tokens on disk so subprocesses (send_message.py, agency copilot)
# can reuse them without launching a fresh Playwright browser session.
_TOKEN_CACHE_FILE = Path.home() / ".teams-agent" / "token-cache.json"


def _load_token_cache() -> dict:
    """Load the on-disk token cache (best-effort)."""
    try:
        if _TOKEN_CACHE_FILE.exists():
            return json.loads(_TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Failed to load token cache: %s", e)
    return {}


def _save_token_cache(resource: str, token: str, expires_at: float) -> None:
    """Persist a token to disk for cross-process reuse."""
    try:
        cache = _load_token_cache()
        cache[resource] = {"token": token, "expires_at": expires_at}
        _TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        logger.debug("Token cached to disk for %s (expires in %ds)",
                      resource.split("//")[-1], int(expires_at - time.time()))
    except Exception as e:
        logger.debug("Failed to save token cache: %s", e)


def _load_cached_token(resource: str, min_validity: float = _MIN_VALIDITY_REUSE_SECONDS) -> Optional[str]:
    """Load a still-valid token from the disk cache."""
    cache = _load_token_cache()
    entry = cache.get(resource)
    if entry:
        token = entry.get("token", "")
        expires_at = entry.get("expires_at", 0)
        remaining = expires_at - time.time()
        if token and remaining > min_validity:
            logger.debug("Loaded cached token for %s (%ds remaining)",
                          resource.split("//")[-1], int(remaining))
            return token
    return None


class TokenManager:
    """Manages Bearer token acquisition and caching for a specific resource."""

    def __init__(self, resource: str = RESOURCE_TEAMS) -> None:
        self._resource = resource
        self._token: str = ""
        self._expires_at: float = 0.0
        self._refresh_at: float = 0.0
        self._lock = asyncio.Lock()
        # Hydrate from disk cache if a valid token exists
        cached = _load_cached_token(resource)
        if cached:
            self._set_token(cached)
            logger.info("TokenManager hydrated from disk cache for %s", resource.split("//")[-1])

    @property
    def token(self) -> str:
        return self._token

    @property
    def resource(self) -> str:
        return self._resource

    def expires_in(self) -> float:
        """Seconds remaining until token expires (0.0 if no token)."""
        if not self._token:
            return 0.0
        return max(0.0, self._expires_at - time.time())

    def seconds_until_refresh(self) -> float:
        """Seconds remaining until proactive refresh is due (0.0 if no token)."""
        if not self._token:
            return 0.0
        return max(0.0, self._refresh_at - time.time())

    def is_valid(self, min_validity_seconds: float = 0.0) -> bool:
        if not self._token:
            return False
        return self.expires_in() > max(0.0, min_validity_seconds)

    def refresh_due(self) -> bool:
        if not self._token:
            return True
        return time.time() >= self._refresh_at

    def _set_token(self, token: str) -> None:
        now = time.time()
        expires_at = _parse_token_expiry(token)
        if not expires_at or expires_at <= now:
            expires_at = now + _DEFAULT_LIFETIME_SECONDS
            logger.debug("Token expiry unknown; using default %ds", _DEFAULT_LIFETIME_SECONDS)

        lifetime = max(1.0, expires_at - now)
        refresh_buffer = max(
            _MIN_REFRESH_BUFFER_SECONDS,
            min(_MAX_REFRESH_BUFFER_SECONDS, lifetime * _REFRESH_BUFFER_RATIO),
        )

        self._token = token
        self._expires_at = expires_at
        self._refresh_at = max(now, expires_at - refresh_buffer)
        logger.info(
            "Token acquired for %s (%d chars, expires in %ds, refresh in %ds)",
            self._resource.split("//")[-1],
            len(token),
            int(self.expires_in()),
            int(self.seconds_until_refresh()),
        )
        # Persist to disk for cross-process reuse
        _save_token_cache(self._resource, token, expires_at)

    async def get_token(
        self, *, force_refresh: bool = False, min_validity_seconds: float = _MIN_VALIDITY_REUSE_SECONDS
    ) -> str:
        """Get a valid token, refreshing if needed."""
        if not force_refresh and not self.refresh_due() and self.is_valid(min_validity_seconds):
            return self._token

        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh and not self.refresh_due() and self.is_valid(min_validity_seconds):
                return self._token

            try:
                token = await _acquire_token(self._resource, skip_cache=force_refresh)
                self._set_token(token)
                return self._token
            except Exception:
                # Graceful degradation: if old token is still valid, keep using it.
                if self.is_valid():
                    logger.warning(
                        "Token refresh failed for %s; reusing existing token (%ds remaining)",
                        self._resource.split("//")[-1],
                        int(self.expires_in()),
                    )
                    return self._token
                raise

    def invalidate(self) -> None:
        """Force token refresh on next call."""
        self._token = ""
        self._expires_at = 0.0
        self._refresh_at = 0.0


def _parse_token_expiry(token: str) -> Optional[float]:
    """Parse JWT exp claim from a Bearer token. Returns unix timestamp or None.

    Note: This performs claim extraction only — no signature verification.
    The token is already trusted (acquired from Azure CLI / Playwright);
    we only need the exp claim to schedule proactive refresh.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + ("=" * (-len(parts[1]) % 4))
        payload = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        claims = json.loads(payload)
        exp = claims.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp)
    except Exception as e:
        logger.debug("Failed to parse token expiry: %s", e)
    return None


async def _acquire_token(resource: str, *, skip_cache: bool = False) -> str:
    """Acquire token: env var → disk cache → Azure CLI → Playwright (Teams only).

    Resolution order:
    1. ``TEAMS_CHATSVC_TOKEN`` env var — set by monitor dispatch to pass
       the already-acquired token to child processes without Playwright.
    2. Disk cache (``~/.teams-agent/token-cache.json``) — cross-process reuse.
    3. Azure CLI (``az account get-access-token``).
    4. Playwright browser session (Teams resource only) — last resort.
    """
    # 0. Environment variable (injected by monitor dispatch subprocess)
    if resource == RESOURCE_TEAMS and not skip_cache:
        env_token = os.environ.get("TEAMS_CHATSVC_TOKEN", "")
        if env_token:
            exp = _parse_token_expiry(env_token)
            if exp and (exp - time.time()) > _MIN_VALIDITY_REUSE_SECONDS:
                logger.info("Using token from TEAMS_CHATSVC_TOKEN env var")
                return env_token
            else:
                logger.debug("TEAMS_CHATSVC_TOKEN expired or invalid, skipping")

    # 1. Check disk cache (enables cross-process token reuse)
    if not skip_cache:
        cached = _load_cached_token(resource)
        if cached:
            logger.info("Using cached token from disk for %s", resource.split("//")[-1])
            return cached

    # 2. Azure CLI
    token = await _acquire_via_cli(resource)
    if token:
        return token

    # 3. Playwright fallback only works for Teams resource
    if resource == RESOURCE_TEAMS:
        logger.info("Azure CLI failed, trying Playwright fallback...")
        token = await _acquire_via_playwright()
        if token:
            return token

    raise RuntimeError(f"Failed to acquire token for {resource}")


_cli_blocked_by_token_protection = False  # Cached: skip CLI if CA Token Protection detected


async def _acquire_via_cli(resource: str) -> Optional[str]:
    """Acquire token using ``az account get-access-token``.

    Detects AADSTS530084 (Conditional Access Token Protection) and permanently
    skips CLI for the rest of this process lifetime — the CLI cannot issue
    proof-of-possession tokens, so retrying is pointless.
    """
    global _cli_blocked_by_token_protection
    if _cli_blocked_by_token_protection:
        logger.debug("Skipping Azure CLI — previously blocked by Token Protection (AADSTS530084)")
        return None

    az_cmd = "az.cmd" if sys.platform == "win32" else "az"
    try:
        proc = await asyncio.create_subprocess_exec(
            az_cmd, "account", "get-access-token",
            "--resource", resource,
            "--query", "accessToken", "-o", "tsv",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        token = stdout.decode().strip()
        if token and proc.returncode == 0:
            logger.debug("Token acquired via Azure CLI for %s", resource)
            return token
        if stderr:
            stderr_text = stderr.decode()[:300]
            logger.debug("Azure CLI stderr: %s", stderr_text)
            # AADSTS530084: Conditional Access Token Protection — CLI can't issue PoP tokens.
            # Cache this so we skip CLI on every future token refresh (avoids repeated failures
            # and potential blocking dialog popups on Windows).
            if "AADSTS530084" in stderr_text:
                _cli_blocked_by_token_protection = True
                logger.warning(
                    "Azure CLI blocked by Conditional Access Token Protection (AADSTS530084). "
                    "Skipping CLI for all future token requests — will use Playwright fallback."
                )
    except Exception as e:
        logger.debug("Azure CLI token failed: %s", e)
    return None


async def _acquire_via_playwright() -> Optional[str]:
    """Acquire token via Playwright Teams browser session."""
    try:
        _teams_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(_teams_root))
        from scripts.rich.auth import TeamsSession

        async with TeamsSession() as session:
            token = session._tokens.get("chatsvc", "")
            if token:
                logger.debug("Token acquired via Playwright")
                return token
    except Exception as e:
        logger.debug("Playwright token failed: %s", e)
    return None


# Module-level singletons keyed by resource
_managers: dict[str, TokenManager] = {}


def get_token_manager(resource: str = RESOURCE_TEAMS) -> TokenManager:
    """Get or create a TokenManager singleton for the given resource."""
    if resource not in _managers:
        _managers[resource] = TokenManager(resource)
    return _managers[resource]


def get_graph_token_manager() -> TokenManager:
    """Shorthand for get_token_manager(RESOURCE_GRAPH)."""
    return get_token_manager(RESOURCE_GRAPH)
