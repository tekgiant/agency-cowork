"""Confluence SAML SSO authentication via Playwright persistent browser context.

Manages a persistent Edge browser profile that caches Azure AD SAML session
cookies. Provides cookie extraction for the `requests` library.

Usage:
    from scripts.auth import get_session, ensure_session
    session = get_session()  # returns requests.Session with cookies
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests

# Lazy import Playwright — only needed for auth
_playwright = None
_context = None

BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://wiki.example.com")
USER_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "AgencyCowork", "confluence-browser",
)
COOKIE_CACHE = os.path.join(USER_DATA_DIR, "cookies.json")

_CDP_PORT = 9225  # unique port for confluence (teams=9223, meeting-summary=9224)
_edge_proc = None


def _get_browser_context():
    """Launch or reuse a Playwright browser context.

    Strategy:
      1. CDP — launch Edge subprocess with ``--remote-debugging-port`` using
         the confluence browser profile, then ``connect_over_cdp``.
         Works even when Edge is already running.
      2. Fallback to ``launch_persistent_context`` (may fail if Edge is open).
    """
    global _playwright, _context, _edge_proc
    if _context is not None:
        return _context

    import subprocess
    import time

    os.makedirs(USER_DATA_DIR, exist_ok=True)

    # Strategy 1: CDP
    edge_exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge_exe):
        edge_exe = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

    if os.path.exists(edge_exe):
        try:
            _edge_proc = subprocess.Popen([
                edge_exe,
                f"--user-data-dir={USER_DATA_DIR}",
                f"--remote-debugging-port={_CDP_PORT}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "about:blank",
            ])
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

    # Strategy 2: Fallback to persistent context
    from playwright.sync_api import sync_playwright
    _playwright = sync_playwright().start()
    _context = _playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        channel="msedge",
        headless=True,
    )
    return _context


def _extract_cookies(context) -> dict:
    """Extract wiki cookies from browser context."""
    all_cookies = context.cookies()
    wiki_cookies = {}
    for c in all_cookies:
        domain = c.get("domain", "")
        if "ahsiwiki" in domain or domain == "":
            wiki_cookies[c["name"]] = c["value"]
    return wiki_cookies


def _save_cookies(cookies: dict) -> None:
    """Cache cookies to disk for fast reuse."""
    os.makedirs(os.path.dirname(COOKIE_CACHE), exist_ok=True)
    with open(COOKIE_CACHE, "w", encoding="utf-8") as f:
        json.dump(cookies, f)


def _load_cached_cookies() -> Optional[dict]:
    """Load cookies from disk cache."""
    if not os.path.exists(COOKIE_CACHE):
        return None
    try:
        with open(COOKIE_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _test_cookies(cookies: dict) -> bool:
    """Test if cookies are valid by checking current user."""
    session = requests.Session()
    for name, val in cookies.items():
        session.cookies.set(name, val, domain="ahsiwiki.corp.microsoft.com")
    try:
        r = session.get(f"{BASE_URL}/rest/api/user/current", timeout=10)
        if r.status_code == 200:
            user = r.json()
            return user.get("type") != "anonymous" and user.get("username", "") != ""
    except requests.RequestException:
        pass
    return False


def _authenticate_browser() -> dict:
    """Perform SAML SSO authentication via Playwright and return cookies."""
    context = _get_browser_context()
    page = context.new_page()

    # Navigate to trigger SAML auth
    page.goto(f"{BASE_URL}/login.action", timeout=60000, wait_until="networkidle")

    # Wait for redirect back to Confluence after SAML
    try:
        page.wait_for_url(f"**/{BASE_URL.split('//')[1]}/**", timeout=60000)
    except Exception:
        pass

    # Verify authentication
    page.goto(f"{BASE_URL}/rest/api/user/current", wait_until="networkidle", timeout=30000)
    body = page.text_content("body") or "{}"
    user = json.loads(body)

    if user.get("type") == "anonymous":
        print("WARNING: SAML SSO did not complete. You may need to run with headless=False.", file=sys.stderr)
        print("Try: python -m scripts.auth --interactive", file=sys.stderr)

    cookies = _extract_cookies(context)
    page.close()
    return cookies


def ensure_session() -> dict:
    """Ensure valid session cookies exist. Re-authenticates if needed."""
    # Try cached cookies first
    cookies = _load_cached_cookies()
    if cookies and _test_cookies(cookies):
        return cookies

    # Authenticate via browser
    cookies = _authenticate_browser()
    if _test_cookies(cookies):
        _save_cookies(cookies)
        return cookies

    # Return whatever we got
    _save_cookies(cookies)
    return cookies


def get_session() -> requests.Session:
    """Get a requests.Session with valid Confluence cookies."""
    cookies = ensure_session()
    session = requests.Session()
    session.headers.update({
        "X-Atlassian-Token": "no-check",
        "Content-Type": "application/json",
    })
    for name, val in cookies.items():
        session.cookies.set(name, val, domain="ahsiwiki.corp.microsoft.com")
    return session


def close():
    """Close the browser context if open."""
    global _playwright, _context
    if _context:
        _context.close()
        _context = None
    if _playwright:
        _playwright.stop()
        _playwright = None


def main():
    """CLI: authenticate interactively or verify session."""
    import argparse
    parser = argparse.ArgumentParser(description="Confluence authentication")
    parser.add_argument("--interactive", action="store_true", help="Force interactive login (headless=False)")
    parser.add_argument("--verify", action="store_true", help="Verify current session")
    args = parser.parse_args()

    if args.interactive:
        # Force interactive auth
        global _playwright, _context
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        _context = _playwright.chromium.launch_persistent_context(
            USER_DATA_DIR, channel="msedge", headless=False,
        )
        page = _context.new_page()
        page.goto(f"{BASE_URL}/login.action", timeout=120000)
        input("Press Enter after login completes in the browser...")
        page.goto(f"{BASE_URL}/rest/api/user/current", wait_until="networkidle")
        body = page.text_content("body") or "{}"
        user = json.loads(body)
        print(f"Authenticated as: {user.get('displayName', '?')} ({user.get('username', '?')})")
        cookies = _extract_cookies(_context)
        _save_cookies(cookies)
        close()
        return

    if args.verify:
        cookies = _load_cached_cookies()
        if cookies and _test_cookies(cookies):
            session = requests.Session()
            for n, v in cookies.items():
                session.cookies.set(n, v, domain="ahsiwiki.corp.microsoft.com")
            r = session.get(f"{BASE_URL}/rest/api/user/current")
            user = r.json()
            print(f"Session valid: {user.get('displayName', '?')} ({user.get('username', '?')})")
        else:
            print("Session expired or not found. Run: python -m scripts.auth --interactive")
            sys.exit(1)
        return

    # Default: ensure session
    cookies = ensure_session()
    if _test_cookies(cookies):
        session = requests.Session()
        for n, v in cookies.items():
            session.cookies.set(n, v, domain="ahsiwiki.corp.microsoft.com")
        r = session.get(f"{BASE_URL}/rest/api/user/current")
        user = r.json()
        print(f"Authenticated as: {user.get('displayName', '?')} ({user.get('username', '?')})")
    else:
        print("Authentication failed. Run: python -m scripts.auth --interactive")
        sys.exit(1)
    close()


if __name__ == "__main__":
    main()
