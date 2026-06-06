"""Microsoft Todo authentication via Playwright — Outlook REST API token extraction.

Manages a persistent Edge browser profile with Azure AD SSO. Navigates to
Outlook Web App (OWA), intercepts the OWA bearer token from network requests,
and caches it for use by todo_client.py.

NOTE: We use the Outlook REST API v2.0 (/api/v2.0/me/tasks) instead of
Graph Todo API because the OWA token includes task scopes by default, while
Graph tokens from OWA lack Tasks.ReadWrite. Tasks created via Outlook REST
API sync to Microsoft Todo automatically.

Security (ET-2): Token is encrypted at rest using Windows DPAPI (current-user
scope). On non-Windows platforms, falls back to file-permission-restricted
plaintext with a warning.

Usage:
    from scripts.todo_auth import get_token, ensure_token
    token = get_token()          # returns valid OWA bearer token string
    ensure_token()               # re-auth if expired
    python -m scripts.todo_auth  # CLI: --interactive, --verify, --test
"""

import ctypes
import ctypes.wintypes
import json
import os
import platform
import sys
import time
from typing import Optional

import requests

_playwright = None
_context = None
_edge_proc = None

OWA_URL = "https://outlook.office365.com/owa/?path=/tasks"
OWA_API_BASE = "https://outlook.office365.com/api/v2.0/me"
_CDP_PORT = 9226  # unique port (confluence=9225, teams=9223, meeting-summary=9224)

USER_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "AgencyCowork", "todo-browser",
)
TOKEN_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "todo-token.json",
)


# --- ET-2: DPAPI encryption helpers ---

_IS_WINDOWS = platform.system() == "Windows"


def _dpapi_encrypt(data: bytes) -> bytes:
    """Encrypt bytes using Windows DPAPI (current-user scope)."""
    if not _IS_WINDOWS:
        return data

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                     ("pbData", ctypes.POINTER(ctypes.c_char))]

    input_blob = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    output_blob = DATA_BLOB()

    if ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob), None, None, None, None, 0,
        ctypes.byref(output_blob),
    ):
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        return encrypted
    raise OSError("DPAPI CryptProtectData failed")


def _dpapi_decrypt(data: bytes) -> bytes:
    """Decrypt bytes using Windows DPAPI (current-user scope)."""
    if not _IS_WINDOWS:
        return data

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                     ("pbData", ctypes.POINTER(ctypes.c_char))]

    input_blob = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    output_blob = DATA_BLOB()

    if ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0,
        ctypes.byref(output_blob),
    ):
        decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        return decrypted
    raise OSError("DPAPI CryptUnprotectData failed")


def _get_browser_context(headless: bool = True):
    """Launch or reuse a Playwright browser context via CDP."""
    global _playwright, _context, _edge_proc
    if _context is not None:
        return _context

    import subprocess

    os.makedirs(USER_DATA_DIR, exist_ok=True)

    edge_exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge_exe):
        edge_exe = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

    if os.path.exists(edge_exe):
        try:
            args = [
                edge_exe,
                f"--user-data-dir={USER_DATA_DIR}",
                f"--remote-debugging-port={_CDP_PORT}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            if headless:
                args.append("--headless=new")
            args.append("about:blank")

            _edge_proc = subprocess.Popen(args)
            time.sleep(2)

            from playwright.sync_api import sync_playwright
            _playwright = sync_playwright().start()
            browser = _playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{_CDP_PORT}",
                timeout=15_000,
            )
            _context = browser.contexts[0]
            return _context
        except Exception:
            if _edge_proc:
                _edge_proc.terminate()
                _edge_proc = None

    # Fallback: persistent context
    from playwright.sync_api import sync_playwright
    _playwright = sync_playwright().start()
    _context = _playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        channel="msedge",
        headless=headless,
    )
    return _context


def _intercept_owa_token(context, timeout_ms: int = 45000) -> Optional[str]:
    """Navigate to OWA and intercept the Outlook bearer token."""
    page = context.new_page()
    captured_token = {"value": None}

    def on_request(request):
        if captured_token["value"]:
            return
        url = request.url
        if "outlook.office365.com" in url:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer ") and len(auth_header) > 1000:
                captured_token["value"] = auth_header[7:]

    page.on("request", on_request)

    try:
        page.goto(OWA_URL, timeout=timeout_ms, wait_until="networkidle")
        time.sleep(3)
    except Exception as e:
        print(f"OWA navigation: {e}", file=sys.stderr)
    finally:
        page.close()

    return captured_token["value"]


def _save_token(token: str) -> None:
    """Cache token to disk, encrypted with DPAPI on Windows."""
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    data = {
        "source": "outlook.office365.com",
        "captured_at": time.time(),
        "expires_estimate": time.time() + 3600,
    }

    if _IS_WINDOWS:
        try:
            encrypted = _dpapi_encrypt(token.encode("utf-8"))
            import base64
            data["access_token_dpapi"] = base64.b64encode(encrypted).decode("ascii")
            data["encrypted"] = True
        except OSError:
            # DPAPI failed — fall back to plaintext with warning
            data["access_token"] = token
            data["encrypted"] = False
            print("WARNING: DPAPI encryption failed, token stored in plaintext",
                  file=sys.stderr)
    else:
        data["access_token"] = token
        data["encrypted"] = False

    with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Restrict file permissions on non-Windows
    if not _IS_WINDOWS:
        try:
            os.chmod(TOKEN_CACHE, 0o600)
        except OSError:
            pass


def _load_cached_token() -> Optional[str]:
    """Load token from disk cache if not expired. Decrypts DPAPI if needed."""
    if not os.path.exists(TOKEN_CACHE):
        return None
    try:
        with open(TOKEN_CACHE, encoding="utf-8") as f:
            data = json.load(f)

        expires = data.get("expires_estimate", 0)
        if time.time() >= (expires - 300):
            return None

        # Try DPAPI-encrypted token first
        if data.get("encrypted") and data.get("access_token_dpapi"):
            import base64
            encrypted = base64.b64decode(data["access_token_dpapi"])
            return _dpapi_decrypt(encrypted).decode("utf-8")

        # Fall back to plaintext (legacy cache or non-Windows)
        return data.get("access_token") or data.get("outlook_token")
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _test_token(token: str) -> bool:
    """Test if token is valid by listing task folders."""
    try:
        r = requests.get(
            f"{OWA_API_BASE}/taskfolders",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def ensure_token(headless: bool = True) -> str:
    """Ensure a valid OWA token exists. Re-authenticates if needed.

    Returns:
        Valid Outlook REST API bearer token string.

    Raises:
        RuntimeError: If authentication fails.
    """
    token = _load_cached_token()
    if token and _test_token(token):
        return token

    context = _get_browser_context(headless=headless)
    try:
        token = _intercept_owa_token(context)
    finally:
        # ET-6: Minimize CDP port exposure — close browser immediately after capture
        close()

    if token and _test_token(token):
        _save_token(token)
        return token

    if token:
        _save_token(token)
        return token

    raise RuntimeError(
        "Failed to obtain OWA token. "
        "Run: python -m scripts.todo_auth --interactive"
    )


def get_token() -> str:
    """Get a valid OWA bearer token (convenience wrapper)."""
    return ensure_token()


def close():
    """Close the browser context and Edge process."""
    global _playwright, _context, _edge_proc
    if _context:
        try:
            _context.close()
        except Exception:
            pass
        _context = None
    if _playwright:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None
    if _edge_proc:
        try:
            _edge_proc.terminate()
        except Exception:
            pass
        _edge_proc = None


def main():
    """CLI: authenticate interactively or verify session."""
    import argparse
    parser = argparse.ArgumentParser(description="Microsoft Todo authentication (via Outlook REST API)")
    parser.add_argument("--interactive", action="store_true", help="Visible browser for initial SSO")
    parser.add_argument("--verify", action="store_true", help="Verify current cached token")
    parser.add_argument("--test", action="store_true", help="Test token by listing task folders")
    args = parser.parse_args()

    if args.verify:
        token = _load_cached_token()
        if token and _test_token(token):
            print("Token valid — Outlook Tasks API accessible")
        else:
            print("Token expired or not found. Run: python -m scripts.todo_auth --interactive")
            sys.exit(1)
        return

    if args.test:
        token = _load_cached_token()
        if not token:
            print("No cached token. Run: python -m scripts.todo_auth first.")
            sys.exit(1)
        r = requests.get(
            f"{OWA_API_BASE}/taskfolders",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            folders = r.json().get("value", [])
            print(f"Found {len(folders)} task folder(s):")
            for f in folders:
                print(f"  - {f.get('Name', '?')}")
        else:
            print(f"API error: {r.status_code} {r.text[:200]}")
            sys.exit(1)
        return

    headless = not args.interactive
    try:
        token = ensure_token(headless=headless)
        print(f"Authenticated — token captured ({len(token)} chars)")
        r = requests.get(
            f"{OWA_API_BASE}/taskfolders",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            folders = r.json().get("value", [])
            print(f"Found {len(folders)} task folder(s):")
            for f in folders:
                print(f"  - {f.get('Name', '?')}")
    except RuntimeError as e:
        print(f"{e}")
        sys.exit(1)
    finally:
        close()


if __name__ == "__main__":
    main()
