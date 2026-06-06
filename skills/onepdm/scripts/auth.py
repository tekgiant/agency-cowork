"""
OnePDM Browser Session — modeled after the Teams skill CDP auth pattern.

Uses ``playwright.chromium.connect_over_cdp`` with a standalone Edge profile
to reuse cached Azure AD SSO.  The browser stays alive so all API calls run
*inside the browser context* via ``page.evaluate(fetch(...))``.  This
sidesteps httpOnly / SameSite cookie requirements — the browser carries
all the right cookies, headers, and origins automatically.

Connection strategy (in order):
  1. CDP — launch Edge with ``--remote-debugging-port``, connect via
     ``connect_over_cdp``.  Uses standalone profile, never conflicts with
     an already-running Edge instance.
  2. Real Edge User Data profile via ``launch_persistent_context``
     (requires Edge to be fully closed — exclusive profile lock).
  3. Standalone profile, headed (fallback for interactive MFA).

This module provides:
  - ``OnePDMBrowser`` — sync context-manager wrapping Playwright + Edge.
  - ``get_browser()``  — singleton accessor.
  - ``ensure_auth()``  — quick check.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ONEPDM_HOME = "https://onepdm.plm.microsoft.com/onepdm/"
ONEPDM_API = "https://s-onepdm.plm.microsoft.com"

# Persistent browser profile (standalone, never conflicts with running Edge)
EDGE_USER_DATA = Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"
BROWSER_PROFILE_DIR = Path.home() / ".onepdm-agent" / "browser-profile"

# Timeouts
_HEADED_READY_TIMEOUT = 120  # seconds — allows time for interactive MFA

# URL patterns that indicate OnePDM API traffic (used to detect readiness)
_API_URL_PATTERNS = (
    "InnovatorServer.aspx",
    "odata/method",
    "MetaData.asmx",
    "OAuthServerDiscovery.aspx",
    "OAuthToken.aspx",
)


# ---------------------------------------------------------------------------
# Readiness probe — watches requests to detect when OnePDM is authenticated
# ---------------------------------------------------------------------------

class _AuthProbe:
    """Watches outgoing requests for successful ``s-onepdm`` API calls.

    Captures auth-related headers (Authorization, DATABASE, AUTHUSER, etc.)
    from the SPA's requests so we can replay them in our own fetch calls.
    """

    def __init__(self):
        self.ready = False
        self._api_calls = 0
        self.captured_headers: dict[str, str] = {}

    def handler(self, request) -> None:
        url = request.url
        if "s-onepdm" in url:
            headers = request.headers
            # Capture any auth-related headers from the SPA's requests
            for hdr in ("authorization", "database", "authuser",
                        "oauthtoken", "x-innovator-auth"):
                val = headers.get(hdr, "")
                if val and hdr not in self.captured_headers:
                    self.captured_headers[hdr] = val
                    logger.debug(f"AuthProbe captured header: {hdr}={val[:40]}...")

            if any(p in url for p in _API_URL_PATTERNS):
                self._api_calls += 1
                logger.debug(f"AuthProbe: {url} (count={self._api_calls})")
                if self._api_calls >= 1:
                    self.ready = True


# ---------------------------------------------------------------------------
# OnePDMBrowser — the primary public interface
# ---------------------------------------------------------------------------

class OnePDMBrowser:
    """Persistent authenticated browser session for the OnePDM web client.

    Usage::

        browser = get_browser()
        browser.ensure_ready()
        results = browser.global_search("M1345662")
        browser.close()

    The browser stays alive so that every API call runs inside the
    fully-authenticated browser context — cookies are handled by the
    browser automatically.
    """

    _CDP_PORT = 9226  # avoid colliding with Teams (9223) and Confluence (9225)

    def __init__(self):
        self._pw = None
        self._context = None
        self._page = None
        self._edge_proc: Optional[subprocess.Popen] = None
        self._authenticated = False
        self._auth_headers: dict[str, str] = {}  # captured from SPA requests

    # ── lifecycle ─────────────────────────────────────────────────────

    def ensure_ready(self) -> bool:
        """Ensure browser is running and authenticated."""
        if self._page and not self._page.is_closed() and self._authenticated:
            try:
                info = self.validate_user()
                if info.get("user_id"):
                    return True
            except Exception:
                pass
            self._authenticated = False

        return self._connect()

    def close(self):
        """Shut down the browser session and any Edge subprocess."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._pw:
            try:
                self._pw.stop()
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
        self._authenticated = False

    # ── connection strategies ─────────────────────────────────────────

    def _connect(self) -> bool:
        """Launch Edge, navigate to OnePDM, wait until ready."""

        # Strategy 1: CDP — always works, even with Edge open.
        if self._try_connect_cdp(timeout=_HEADED_READY_TIMEOUT):
            return True

        # Strategy 2: Real Edge profile (Edge must be closed).
        if EDGE_USER_DATA.exists():
            check = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"],
                capture_output=True, text=True,
            )
            if "msedge.exe" not in check.stdout:
                if self._try_connect_persistent(
                    profile_dir=EDGE_USER_DATA,
                    extra_args=["--profile-directory=Default"],
                    timeout=_HEADED_READY_TIMEOUT,
                ):
                    return True

        # Strategy 3: Standalone persistent context, headed (interactive MFA).
        print(
            "\n╔══════════════════════════════════════════════════════════╗\n"
            "║  CDP and real profile failed — opening Edge.            ║\n"
            "║  Please sign in to OnePDM if prompted.                  ║\n"
            "║  The window will stay open in the background.           ║\n"
            "╚══════════════════════════════════════════════════════════╝\n",
            flush=True,
        )
        if self._try_connect_persistent(timeout=_HEADED_READY_TIMEOUT):
            return True

        print("ERROR: Could not establish OnePDM session.", file=sys.stderr)
        return False

    # ── Strategy 1: CDP ───────────────────────────────────────────────

    def _try_connect_cdp(self, *, timeout: int) -> bool:
        """Launch Edge with --remote-debugging-port and connect via CDP."""
        self.close()

        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        edge_exe = self._find_edge()
        if not edge_exe:
            return False

        try:
            from playwright.sync_api import sync_playwright

            self._edge_proc = subprocess.Popen([
                edge_exe,
                f"--user-data-dir={BROWSER_PROFILE_DIR}",
                f"--remote-debugging-port={self._CDP_PORT}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ])
            time.sleep(2)

            self._pw = sync_playwright().start()
            browser = self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self._CDP_PORT}",
                timeout=15_000,
            )
            self._context = browser.contexts[0]
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )

            # Set up auth readiness probe
            probe = _AuthProbe()
            self._page.on("request", probe.handler)

            # Navigate to OnePDM
            self._page.goto(
                ONEPDM_HOME, wait_until="domcontentloaded", timeout=60_000
            )

            # Wait for auth to complete
            if self._wait_for_auth(probe, timeout):
                return True

            self.close()
            return False

        except Exception as e:
            logger.debug(f"CDP connect failed: {e}")
            self.close()
            return False

    # ── Strategy 2/3: Persistent context ──────────────────────────────

    def _try_connect_persistent(
        self,
        *,
        timeout: int,
        profile_dir: Path = None,
        extra_args: list[str] = None,
    ) -> bool:
        """Launch Edge via launch_persistent_context."""
        self.close()

        if profile_dir is None:
            profile_dir = BROWSER_PROFILE_DIR
        profile_dir.mkdir(parents=True, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            args = extra_args or []
            self._context = self._pw.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                channel="msedge",
                args=args,
            )
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )

            probe = _AuthProbe()
            self._page.on("request", probe.handler)

            self._page.goto(
                ONEPDM_HOME, wait_until="domcontentloaded", timeout=60_000
            )

            if self._wait_for_auth(probe, timeout):
                return True

            self.close()
            return False

        except Exception as e:
            logger.debug(f"Persistent context failed: {e}")
            self.close()
            return False

    # ── Auth wait loop ────────────────────────────────────────────────

    def _wait_for_auth(self, probe: _AuthProbe, timeout: int) -> bool:
        """Poll until the Aras IOM is initialized and authenticated."""
        deadline = time.monotonic() + timeout
        login_hint_shown = False
        tick = 0

        while time.monotonic() < deadline:
            try:
                current_url = self._page.url

                if tick % 5 == 0:
                    print(f"  [Waiting for auth... page={current_url[:80]}]", flush=True)

                    # Check if the Aras IOM is loaded and authenticated
                    if "onepdm.plm.microsoft.com" in current_url:
                        try:
                            check = self._page.evaluate("""
                                () => {
                                    if (typeof aras === 'undefined') return { ready: false, reason: 'no aras' };
                                    if (!aras.IomInnovator) return { ready: false, reason: 'no IOM' };
                                    try {
                                        const uid = aras.IomInnovator.getUserID();
                                        if (uid) return { ready: true, userId: uid };
                                    } catch(e) {}
                                    return { ready: false, reason: 'getUserID failed' };
                                }
                            """)
                            if check.get("ready"):
                                print(f"  [Aras IOM ready — userId={check['userId']}]", flush=True)
                                self._authenticated = True
                                return True
                            else:
                                logger.debug(f"IOM check: {check.get('reason')}")
                        except Exception as e:
                            logger.debug(f"IOM check error: {e}")

                if "login.microsoftonline.com" in current_url and not login_hint_shown:
                    print(
                        "  [Azure AD login detected — please complete sign-in in Edge]",
                        flush=True,
                    )
                    login_hint_shown = True
            except Exception:
                pass

            tick += 1
            time.sleep(1)

        return False

    # ── IOM API (via Aras JS objects in the browser) ─────────────────

    def _iom_call(self, js_code: str) -> Any:
        """Execute JavaScript using the Aras IOM API in the page context."""
        if not self._page:
            raise RuntimeError(
                "OnePDMBrowser not connected — call ensure_ready() first."
            )
        return self._page.evaluate(js_code)

    def _soap_call(self, body_xml: str, action: str) -> str:
        """Make a SOAP call via the Aras IOM soapSend mechanism.

        Uses the browser's ``aras`` object to get auth headers and makes
        the call through ``XMLHttpRequest`` in the same origin context
        as the SPA — avoiding CORS issues entirely.
        """
        if not self._page:
            raise RuntimeError(
                "OnePDMBrowser not connected — call ensure_ready() first."
            )

        envelope = (
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV='
            '"http://schemas.xmlsoap.org/soap/envelope/">'
            f"<SOAP-ENV:Body>{body_xml}</SOAP-ENV:Body>"
            "</SOAP-ENV:Envelope>"
        )
        js = """
        ([envelope, action]) => {
            const headers = aras.getHttpHeadersForSoapMessage(action);
            const serverUrl = aras.getServerBaseURL();
            const xhr = aras.XmlHttpRequestManager
                ? aras.XmlHttpRequestManager.createRequest()
                : new XMLHttpRequest();
            xhr.open('POST', serverUrl + 'InnovatorServer.aspx', false);
            xhr.setRequestHeader('Content-Type', 'text/xml; charset=UTF-8');
            for (const [k, v] of Object.entries(headers)) {
                xhr.setRequestHeader(k, v);
            }
            xhr.send(envelope);
            if (xhr.status !== 200) {
                throw new Error('SOAP HTTP ' + xhr.status);
            }
            return xhr.responseText;
        }
        """
        return self._page.evaluate(js, [envelope, action])

    def _json_post(self, path: str, payload: dict) -> dict:
        """Make a JSON POST via the Aras browser context (uses IOM auth headers)."""
        js = """
        ([url, body]) => {
            const headers = aras.getHttpHeadersForSoapMessage('ApplyItem');
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url, false);
            xhr.setRequestHeader('Content-Type', 'application/json');
            for (const [k, v] of Object.entries(headers)) {
                xhr.setRequestHeader(k, v);
            }
            xhr.send(JSON.stringify(body));
            if (xhr.status !== 200) throw new Error('HTTP ' + xhr.status);
            return JSON.parse(xhr.responseText);
        }
        """
        return self._page.evaluate(js, [f"{ONEPDM_API}{path}", payload])

    # ── Public API Methods ────────────────────────────────────────────

    def validate_user(self) -> dict:
        """Validate current session, return user info via Aras IOM."""
        result = self._page.evaluate("""
            () => {
                try {
                    const userId = aras.IomInnovator.getUserID();
                    const db = aras.getDatabase();
                    return {
                        login_name: aras.OAuthClient
                            ? (JSON.parse(atob(aras.OAuthClient.getToken().split('.')[1])).username || '')
                            : '',
                        user_id: userId,
                        database: db,
                        server_url: aras.getServerBaseURL()
                    };
                } catch(e) {
                    return { error: e.message };
                }
            }
        """)
        return result

    def global_search(self, query: str) -> list[dict]:
        """Search OnePDM by document number or keyword using IOM."""
        result = self._page.evaluate("""
            (query) => {
                try {
                    // Use IOM ApplyItem for document search by item_number
                    const item = aras.IomInnovator.newItem('Document', 'get');
                    item.setAttribute('select', 'item_number,name,classification,state,id');
                    item.setProperty('item_number', query);
                    const resp = item.apply();
                    if (resp.isError()) {
                        // Try wildcard search
                        const item2 = aras.IomInnovator.newItem('Document', 'get');
                        item2.setAttribute('select', 'item_number,name,classification,state,id');
                        item2.setPropertyCondition('item_number', 'like');
                        item2.setProperty('item_number', '%' + query + '%');
                        const resp2 = item2.apply();
                        if (resp2.isError()) return [];
                        const results = [];
                        for (let i = 0; i < resp2.getItemCount(); i++) {
                            const it = resp2.getItemByIndex(i);
                            results.push({
                                _id: it.getID(),
                                _itemnumber: it.getProperty('item_number', ''),
                                _name: it.getProperty('name', ''),
                                _classification: it.getProperty('classification', ''),
                                _state: it.getProperty('state', '')
                            });
                        }
                        return results;
                    }
                    const results = [];
                    for (let i = 0; i < resp.getItemCount(); i++) {
                        const it = resp.getItemByIndex(i);
                        results.push({
                            _id: it.getID(),
                            _itemnumber: it.getProperty('item_number', ''),
                            _name: it.getProperty('name', ''),
                            _classification: it.getProperty('classification', ''),
                            _state: it.getProperty('state', '')
                        });
                    }
                    return results;
                } catch(e) {
                    return [{ _error: e.message }];
                }
            }
        """, query)
        return result

    def get_document(self, doc_id: str) -> dict:
        """Get full document metadata by OnePDM ID using IOM."""
        result = self._page.evaluate("""
            (docId) => {
                try {
                    const item = aras.IomInnovator.getItemById('Document', docId, 0);
                    if (!item || item.isError()) return {};
                    const props = {};
                    // Extract all properties from the DOM
                    const node = item.node;
                    for (let i = 0; i < node.childNodes.length; i++) {
                        const child = node.childNodes[i];
                        if (child.nodeType === 1) {
                            props[child.nodeName] = child.textContent || '';
                        }
                    }
                    props.id = item.getID();
                    return props;
                } catch(e) {
                    return { error: e.message };
                }
            }
        """, doc_id)
        return result

    def get_document_by_number(self, doc_number: str) -> Optional[dict]:
        """Search for a document by number, return its metadata."""
        results = self.global_search(doc_number)
        for r in results:
            if r.get("_itemnumber", "").upper() == doc_number.upper():
                return self.get_document(r["_id"])
        if results:
            return self.get_document(results[0]["_id"])
        return None

    def list_document_files(self, doc_id: str) -> list[dict]:
        """List file attachments for a document via IOM."""
        result = self._page.evaluate("""
            (docId) => {
                try {
                    const doc = aras.IomInnovator.newItem('Document', 'get');
                    doc.setID(docId);
                    doc.setAttribute('select', 'id');
                    const fileRel = doc.createRelationship('Document File', 'get');
                    fileRel.setAttribute('select', 'related_id');
                    const fileItem = fileRel.createRelatedItem('File', 'get');
                    fileItem.setAttribute('select', 'id,filename,file_size,file_type,located_in');
                    const resp = doc.apply();
                    if (resp.isError()) return [{ _error: resp.getErrorString() }];
                    const rels = resp.getRelationships('Document File');
                    const files = [];
                    for (let i = 0; i < rels.getItemCount(); i++) {
                        const rel = rels.getItemByIndex(i);
                        const related = rel.getRelatedItem();
                        if (related) {
                            files.push({
                                id: related.getID(),
                                filename: related.getProperty('filename', ''),
                                file_size: related.getProperty('file_size', ''),
                                file_type: related.getProperty('file_type', ''),
                                located_in: related.getProperty('located_in', '')
                            });
                        }
                    }
                    return files;
                } catch(e) {
                    return [{ _error: e.message }];
                }
            }
        """, doc_id)
        return result

    def get_file_metadata(self, file_id: str) -> dict:
        """Get file metadata (name, size, vault info) via IOM."""
        result = self._page.evaluate("""
            (fileId) => {
                try {
                    const item = aras.IomInnovator.getItemById('File', fileId, 0);
                    if (!item || item.isError()) return {};
                    const props = {};
                    const node = item.node;
                    for (let i = 0; i < node.childNodes.length; i++) {
                        const child = node.childNodes[i];
                        if (child.nodeType === 1) {
                            props[child.nodeName] = child.textContent || '';
                        }
                    }
                    props.id = item.getID();
                    return props;
                } catch(e) {
                    return { error: e.message };
                }
            }
        """, file_id)
        return result

    def get_download_token(self, file_id: str) -> str:
        """Get file download URL using IOM's getFileUrl."""
        result = self._page.evaluate("""
            (fileId) => {
                try {
                    const url = aras.IomInnovator.getFileUrl(fileId, 0);
                    return url || '';
                } catch(e) {
                    return '';
                }
            }
        """, file_id)
        return result

    def download_file(
        self,
        file_id: str,
        dest_path: str,
        filename: str = None,
        vault_id: str = None,
    ) -> str:
        """Download a file from the vault to a local path.

        Extracts the OAuth Bearer token from the Aras IOM, then uses
        ``requests.get`` with the token to download from the vault server.
        The vault is on a different origin (v-onepdm) so browser fetch/XHR
        is blocked by CORS — Python ``requests`` with the token works.
        """
        import requests as _requests

        if not filename:
            meta = self.get_file_metadata(file_id)
            filename = meta.get("filename", f"{file_id}.bin")

        if not filename:
            filename = f"{file_id}.bin"

        # Get vault URL and auth from the Aras IOM
        vault_info = self._page.evaluate("""
            (fileId) => {
                const url = aras.IomInnovator.getFileUrl(fileId, 0);
                const token = aras.OAuthClient.getToken();
                const db = aras.getDatabase();
                return { url: url || '', token: token || '', db: db || '' };
            }
        """, file_id)

        vault_url = vault_info.get("url", "")
        if not vault_url:
            raise RuntimeError(f"No vault URL for file {file_id}")

        resp = _requests.get(
            vault_url,
            headers={
                "Authorization": f"Bearer {vault_info['token']}",
                "DATABASE": vault_info["db"],
            },
            stream=True,
            timeout=300,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Vault download failed: HTTP {resp.status_code}")

        dest = Path(dest_path)
        if dest.is_dir():
            dest = dest / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        total = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                total += len(chunk)

        print(f"  Downloaded: {dest.name} ({total:,} bytes)", flush=True)
        return str(dest)

    def download_by_doc_number(
        self, doc_number: str, dest_dir: str
    ) -> Optional[str]:
        """Download the latest file for a document number."""
        doc = self.get_document_by_number(doc_number)
        if not doc:
            return None

        doc_id = doc.get("id", "")
        files = self.list_document_files(doc_id)
        if not files:
            return None

        file_info = files[0]
        file_id = file_info.get("id", "")
        filename = file_info.get("filename", f"{doc_number}.bin")

        return self.download_file(file_id, dest_dir, filename=filename)

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_vault_id(file_meta: dict) -> str:
        """Extract vault ID from file metadata."""
        vault_id = file_meta.get("located_in", "")
        if vault_id:
            return vault_id
        return "67BBB9204FE84A8981ED8313049BA06C"

    @staticmethod
    def _find_edge() -> Optional[str]:
        """Find Microsoft Edge executable."""
        for path in [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]:
            if os.path.exists(path):
                return path
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_browser: Optional[OnePDMBrowser] = None


def get_browser() -> OnePDMBrowser:
    """Get the singleton OnePDM browser client."""
    global _browser
    if _browser is None:
        _browser = OnePDMBrowser()
    return _browser


def ensure_auth() -> bool:
    """Ensure OnePDM browser is authenticated."""
    return get_browser().ensure_ready()
