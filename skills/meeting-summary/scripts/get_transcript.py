"""
Meeting transcript downloader — fetches VTT transcript from SharePoint
for Teams meeting recordings.

Cross-platform: works on both Windows and macOS. Platform-specific browser
launch/detection is handled automatically via sys.platform.

Usage:
    # Windows:
    python -m scripts.get_transcript --site-url "<siteUrl>" --drive-id "<driveId>" --item-id "<itemId>" --format text -o "output/transcript.txt"

    # macOS (use python3 and single quotes — drive IDs contain ! which bash eats in double quotes):
    python3 -m scripts.get_transcript --site-url '<siteUrl>' --drive-id '<driveId>' --item-id '<itemId>' --format text -o 'output/transcript.txt'

    # With recording web URL (either platform):
    python -m scripts.get_transcript --recording-url "https://microsoft.sharepoint.com/teams/.../Recording.mp4" -o output/transcript.txt

Flow:
    1. Construct the stream.aspx URL for the recording
    2. Use Playwright (browser auth via CDP) to load the page
    3. Intercept the VTT transcript network request
    4. Parse VTT into speaker-attributed plain text
"""

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

_IS_MACOS = sys.platform == "darwin"
_IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# Dependency check — fail fast with actionable message
# ---------------------------------------------------------------------------

def _check_dependencies():
    """Verify prerequisites are installed before doing any real work."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        if _IS_MACOS:
            print(
                "Error: Playwright is not installed.\n"
                "Run the setup script first:\n"
                "  bash skills/meeting-summary/scripts/setup.sh\n"
                "\n"
                "Or install manually:\n"
                "  pip3 install playwright --break-system-packages\n"
                "  python3 -m playwright install chromium",
                file=sys.stderr,
            )
        else:
            print(
                "Error: Playwright is not installed.\n"
                "Install with:\n"
                "  pip install playwright\n"
                "  python -m playwright install chromium",
                file=sys.stderr,
            )
        sys.exit(1)

_check_dependencies()

# ---------------------------------------------------------------------------
# Platform-specific Edge paths and process detection
# ---------------------------------------------------------------------------

if _IS_MACOS:
    EDGE_USER_DATA = Path.home() / "Library" / "Application Support" / "Microsoft Edge"
    _USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
    )
else:
    EDGE_USER_DATA = Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
    )

_STANDALONE_PROFILE = Path.home() / ".teams-agent" / "browser-profile"
_CDP_PORT = 9224  # unique port for meeting-summary (teams skill uses 9223)
_MAX_AUTH_RETRY = 3

# Track subprocess so we can clean it up
_edge_proc = None


def _edge_executable():
    """Return the path to the Edge binary, or None if not found."""
    if _IS_MACOS:
        candidates = [
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path.home() / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge",
        ]
    else:
        candidates = [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _is_edge_running():
    """Check if Edge is currently running."""
    try:
        if _IS_MACOS:
            result = subprocess.run(
                ["pgrep", "-x", "Microsoft Edge"],
                capture_output=True, text=True,
            )
            return result.returncode == 0
        else:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"],
                capture_output=True, text=True,
            )
            return "msedge.exe" in result.stdout
    except FileNotFoundError:
        return False


def _launch_args():
    """Common Playwright launch kwargs for Edge."""
    return dict(
        channel="msedge",
        args=[
            "--profile-directory=Default",
            "--window-position=-2400,-2400",  # Off-screen so the browser isn't visible
        ],
        viewport={"width": 1280, "height": 900},
        user_agent=_USER_AGENT,
    )


def _cleanup_edge():
    """Terminate the CDP Edge subprocess and clean up temp profile if we created one."""
    global _edge_proc
    if _edge_proc:
        try:
            _edge_proc.terminate()
            _edge_proc.wait(timeout=5)
        except Exception:
            try:
                _edge_proc.kill()
            except Exception:
                pass
        _edge_proc = None
    _cleanup_temp_profile()


# Register signal-based cleanup on macOS (SIGTERM not reliable on Windows)
if _IS_MACOS:
    import signal

    def _signal_handler(signum, frame):
        _cleanup_edge()
        sys.exit(1)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


_temp_profile_dir = None  # Track temp profile for cleanup


def _copy_edge_profile():
    """Copy essential Edge profile files to a temp dir.

    Copies cookies, login data, local/session storage, and IndexedDB
    but skips caches and GPU data to keep it fast (~2-5s).
    Returns the temp dir path.
    """
    global _temp_profile_dir
    source = EDGE_USER_DATA / "Default"
    if not source.exists():
        return None

    _temp_profile_dir = tempfile.mkdtemp(prefix="edge-profile-copy-")
    dest = Path(_temp_profile_dir) / "Default"
    dest.mkdir(parents=True, exist_ok=True)

    # Essential files for auth state
    essential_files = [
        "Cookies", "Cookies-journal",
        "Login Data", "Login Data-journal",
        "Web Data", "Web Data-journal",
        "Preferences", "Secure Preferences",
        "TransportSecurity",
    ]
    for fname in essential_files:
        src = source / fname
        if src.exists():
            shutil.copy2(str(src), str(dest / fname))

    # Essential dirs for session state
    essential_dirs = [
        "Local Storage",
        "Session Storage",
        "IndexedDB",
        "databases",
    ]
    for dname in essential_dirs:
        src = source / dname
        if src.exists():
            shutil.copytree(str(src), str(dest / dname), dirs_exist_ok=True)

    # Copy parent-level files needed by Chromium
    for fname in ["Local State"]:
        src = EDGE_USER_DATA / fname
        if src.exists():
            shutil.copy2(str(src), str(Path(_temp_profile_dir) / fname))

    print(f"  Copied Edge profile to temp dir ({dest})", file=sys.stderr)
    return _temp_profile_dir


def _cleanup_temp_profile():
    """Remove the temporary profile copy."""
    global _temp_profile_dir
    if _temp_profile_dir:
        try:
            shutil.rmtree(_temp_profile_dir, ignore_errors=True)
        except Exception:
            pass
        _temp_profile_dir = None


async def _launch_edge_context(playwright):
    """Launch Playwright with an Edge browser session.

    Strategy (tried in order):
      0. Profile copy (macOS) — copy Edge profile to temp dir, launch
         persistent context on the copy.  Works even when Edge is running.
         No CDP, no profile lock.
      1. CDP — launch Edge subprocess with --remote-debugging-port using
         the standalone profile, then connect_over_cdp.  Works even when
         Edge is already running (Windows preferred).
      2. Real Edge User Data profile via launch_persistent_context
         (only if Edge is not running — needs exclusive profile lock).

    Returns a BrowserContext.
    """
    global _edge_proc

    edge_exe = _edge_executable()

    # --- Strategy 0: Profile copy (macOS preferred) ---
    # Copies auth cookies/session to a temp dir, avoids profile lock AND CDP issues
    if _IS_MACOS and EDGE_USER_DATA.exists():
        try:
            temp_profile = _copy_edge_profile()
            if temp_profile:
                context = await playwright.chromium.launch_persistent_context(
                    temp_profile,
                    headless=False,
                    **_launch_args(),
                )
                print("  Browser launched (profile copy, no lock conflict)", file=sys.stderr)
                return context
        except Exception as e:
            print(f"  Profile copy strategy failed: {e}", file=sys.stderr)
            _cleanup_temp_profile()

    # --- Strategy 1: CDP with standalone profile ---
    if edge_exe:
        _STANDALONE_PROFILE.mkdir(parents=True, exist_ok=True)
        try:
            popen_kwargs = {}
            if _IS_MACOS:
                popen_kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            _edge_proc = subprocess.Popen(
                [
                    edge_exe,
                    f"--user-data-dir={_STANDALONE_PROFILE}",
                    f"--remote-debugging-port={_CDP_PORT}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-position=-2400,-2400",
                    "about:blank",
                ],
                **popen_kwargs,
            )
            time.sleep(3 if _IS_MACOS else 2)
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{_CDP_PORT}",
                timeout=15_000,
            )
            context = browser.contexts[0]
            print("  Browser launched (CDP, standalone profile)", file=sys.stderr)
            return context
        except Exception as e:
            print(f"  CDP strategy failed: {e}", file=sys.stderr)
            if _edge_proc:
                _edge_proc.terminate()
                _edge_proc = None

    # --- Strategy 2: Real Edge profile (Edge must be closed) ---
    if _is_edge_running():
        print(
            "  WARNING: Edge is running. CDP failed and real profile is locked.\n"
            "  Close Edge or ensure the standalone profile works.",
            file=sys.stderr,
        )

    if not EDGE_USER_DATA.exists():
        print(
            f"  Edge User Data not found at {EDGE_USER_DATA}.\n"
            "  Install Microsoft Edge or check the path.",
            file=sys.stderr,
        )
        sys.exit(1)

    context = await playwright.chromium.launch_persistent_context(
        str(EDGE_USER_DATA),
        headless=False,
        **_launch_args(),
    )
    print("  Browser launched (headed, real Edge profile)", file=sys.stderr)
    return context


# ---------------------------------------------------------------------------
# Transcript fetching (platform-agnostic API layer)
# ---------------------------------------------------------------------------

async def fetch_transcript_direct_api(
    site_url: str, drive_id: str, item_id: str, timeout_ms: int = 60000
) -> str | None:
    """Fetch transcript via direct SharePoint REST API calls using browser auth.

    Navigates to the SharePoint site root (to establish auth cookies) then
    makes direct API calls via page.request.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await _launch_edge_context(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()

            # Navigate to the site to establish auth cookies
            print(f"  Authenticating to {site_url}...", file=sys.stderr)
            try:
                await page.goto(site_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:
                print(f"  Site load warning: {e}", file=sys.stderr)

            if "login.microsoftonline.com" in page.url:
                print(
                    "\n  ╔══════════════════════════════════════════════════╗\n"
                    "  ║  SIGN IN REQUIRED                                ║\n"
                    "  ║  An Edge window has opened for authentication.   ║\n"
                    "  ║  Please sign in with your Microsoft account.     ║\n"
                    "  ║  Waiting up to 2 minutes...                      ║\n"
                    "  ╚══════════════════════════════════════════════════╝\n",
                    file=sys.stderr,
                )
                for i in range(120):
                    await asyncio.sleep(1)
                    if "login.microsoftonline.com" not in page.url:
                        print("  ✓ Authentication successful!", file=sys.stderr)
                        break
                    if i > 0 and i % 30 == 0:
                        print(f"  Still waiting for login... ({120 - i}s remaining)", file=sys.stderr)
                else:
                    print("  ✗ Login timed out after 2 minutes.", file=sys.stderr)

            await asyncio.sleep(2)  # Let cookies settle

            # Step 1: List transcripts for this recording
            base = f"{site_url}/_api/v2.1/drives/{drive_id}/items/{item_id}"
            transcript_id = None

            print("  Listing transcripts...", file=sys.stderr)
            list_resp = await page.request.get(f"{base}/media/transcripts")
            if list_resp.ok:
                data = await list_resp.json()
                items = data.get("value", [])
                if items:
                    transcript_id = items[0]["id"]
                    t_name = items[0].get("displayName", "unknown")
                    print(f"  Found transcript: {t_name} (ID: {transcript_id})",
                          file=sys.stderr)

            # Fallback: get item metadata with ?$select=media
            if not transcript_id:
                print("  Trying item metadata...", file=sys.stderr)
                meta_resp = await page.request.get(f"{base}?$select=id,name,media")
                if meta_resp.ok:
                    metadata = await meta_resp.json()
                    transcripts = metadata.get("media", {}).get("transcripts", [])
                    if transcripts:
                        transcript_id = transcripts[0]["id"]
                        print(f"  Found transcript ID in metadata: {transcript_id}",
                              file=sys.stderr)

            if not transcript_id:
                print("  No transcripts found for this recording.", file=sys.stderr)
                return None

            # Step 2: Download VTT (with retry on 401)
            vtt_url = (
                f"{base}/media/transcripts/{transcript_id}/streamContent"
                "?is=1&applymediaedits=false"
            )

            vtt_content = None
            for attempt in range(1, _MAX_AUTH_RETRY + 1):
                print(f"  Downloading VTT (attempt {attempt}/{_MAX_AUTH_RETRY})...",
                      file=sys.stderr)
                vtt_resp = await page.request.get(vtt_url)

                if vtt_resp.ok:
                    vtt_content = await vtt_resp.text()
                    break

                if vtt_resp.status == 401 and attempt < _MAX_AUTH_RETRY:
                    print(
                        f"  VTT download got 401 — re-authenticating (attempt {attempt})...",
                        file=sys.stderr,
                    )
                    try:
                        await page.goto(
                            site_url,
                            wait_until="domcontentloaded",
                            timeout=timeout_ms,
                        )
                    except Exception:
                        pass
                    if "login.microsoftonline.com" in page.url:
                        print("  Auth cookies expired — waiting for interactive login...",
                              file=sys.stderr)
                        for _ in range(120):
                            await asyncio.sleep(1)
                            if "login.microsoftonline.com" not in page.url:
                                break
                    await asyncio.sleep(3)
                    continue

                print(f"  VTT download failed: {vtt_resp.status}", file=sys.stderr)
                return None

            if not vtt_content:
                print(f"  VTT download failed after {_MAX_AUTH_RETRY} attempts.",
                      file=sys.stderr)
                return None

            # Validate the response is actually VTT, not an error page
            if not vtt_content.lstrip("\ufeff").strip().startswith("WEBVTT"):
                print(
                    f"  ERROR: Response is not valid VTT ({len(vtt_content)} chars).\n"
                    f"  First 200 chars: {vtt_content[:200]!r}",
                    file=sys.stderr,
                )
                return None

            print(f"  Got VTT: {len(vtt_content)} chars", file=sys.stderr)
            return vtt_content

        finally:
            await context.close()
            _cleanup_edge()


async def fetch_transcript_via_browser(stream_url: str, timeout_ms: int = 60000) -> str | None:
    """Load stream.aspx in Playwright, intercept the VTT transcript download.

    Fallback method — uses Edge in headed mode.
    """
    from playwright.async_api import async_playwright

    vtt_content = None
    vtt_event = asyncio.Event()

    async def handle_response(response):
        nonlocal vtt_content
        url = response.url
        if "media/transcripts/" in url and "streamContent" in url:
            try:
                body = await response.text()
                if body.startswith("WEBVTT"):
                    vtt_content = body
                    vtt_event.set()
                    print(f"  Captured VTT: {len(body)} chars", file=sys.stderr)
            except Exception as e:
                print(f"  Warning: could not read VTT response: {e}", file=sys.stderr)

    async with async_playwright() as p:
        context = await _launch_edge_context(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("response", handle_response)

            print(f"  Loading: {stream_url[:100]}...", file=sys.stderr)
            try:
                await page.goto(stream_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:
                print(f"  Page load warning: {e}", file=sys.stderr)

            # Wait for VTT to be captured (the page auto-loads the transcript)
            try:
                await asyncio.wait_for(vtt_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                print("  VTT not auto-loaded, trying transcript tab...", file=sys.stderr)
                try:
                    transcript_btn = page.locator("button:has-text('Transcript')")
                    if await transcript_btn.count() > 0:
                        await transcript_btn.first.click()
                        await asyncio.wait_for(vtt_event.wait(), timeout=15)
                except Exception:
                    pass

            if not vtt_content:
                print("  Trying to extract from page state...", file=sys.stderr)
                try:
                    page_content = await page.content()
                    tid_match = re.search(
                        r'"transcripts":\s*\[\s*\{[^}]*"id"\s*:\s*"([a-f0-9-]{36})"',
                        page_content,
                    )
                    if tid_match:
                        transcript_id = tid_match.group(1)
                        print(f"  Found transcript ID in page: {transcript_id}",
                              file=sys.stderr)
                        api_match = re.search(
                            r'(https://[^"]+/_api/v2\.1/drives/[^"]+/items/[^"?]+)',
                            page_content,
                        )
                        if api_match:
                            base_url = api_match.group(1)
                            vtt_url = (
                                f"{base_url}/media/transcripts/{transcript_id}"
                                "/streamContent?is=1&applymediaedits=false"
                            )
                            resp = await page.request.get(vtt_url)
                            if resp.ok:
                                vtt_content = await resp.text()
                                print(f"  Fetched VTT: {len(vtt_content)} chars",
                                      file=sys.stderr)
                except Exception as e:
                    print(f"  Page state extraction failed: {e}", file=sys.stderr)

        finally:
            await context.close()
            _cleanup_edge()

    return vtt_content


# ---------------------------------------------------------------------------
# URL builders (platform-agnostic)
# ---------------------------------------------------------------------------

_ALLOWED_SHAREPOINT_SUFFIXES = (".sharepoint.com", ".sharepoint-df.com")


def build_stream_url(recording_web_url: str) -> str:
    """Convert a recording's webUrl to the stream.aspx viewer URL."""
    parsed = urllib.parse.urlparse(recording_web_url)

    # Validate the URL is a SharePoint HTTPS URL
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS URLs are allowed, got: {parsed.scheme}")
    if not any(parsed.netloc.endswith(s) for s in _ALLOWED_SHAREPOINT_SUFFIXES):
        raise ValueError(
            f"URL must be a SharePoint domain (*{' or *'.join(_ALLOWED_SHAREPOINT_SUFFIXES)}), "
            f"got: {parsed.netloc}"
        )

    decoded_path = urllib.parse.unquote(parsed.path)
    path_parts = decoded_path.split("/")
    if len(path_parts) >= 3 and path_parts[1] in ("teams", "sites"):
        site_prefix = "/" + "/".join(path_parts[1:3])
    else:
        site_prefix = ""

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    stream_path = f"{site_prefix}/_layouts/15/stream.aspx"
    query = urllib.parse.urlencode({"id": decoded_path})
    return f"{base_url}/{stream_path.lstrip('/')}?{query}"


def build_stream_url_from_ids(site_url: str, drive_id: str, item_id: str) -> str:
    """Build stream.aspx URL from site URL and IDs (when webUrl not available).

    Constructs the stream.aspx viewer URL using the SharePoint embed endpoint.
    This lets Method B (browser interception) work even when only IDs are provided.
    """
    parsed = urllib.parse.urlparse(site_url)
    # stream.aspx accepts a driveId + itemId combo via the 'id' query param
    # Format: /_layouts/15/stream.aspx?id=/drives/{driveId}/items/{itemId}
    # But the more reliable approach uses the embed endpoint:
    embed_path = f"/_api/v2.1/drives/{drive_id}/items/{item_id}"
    stream_path = "/_layouts/15/stream.aspx"
    query = urllib.parse.urlencode({"id": embed_path, "referrer": "Teams"})
    return f"{parsed.scheme}://{parsed.netloc}{stream_path}?{query}"


# ---------------------------------------------------------------------------
# VTT parser (platform-agnostic)
# ---------------------------------------------------------------------------

def parse_vtt_to_text(vtt_content: str) -> str:
    """Parse VTT into clean speaker-attributed text.

    Input:
        WEBVTT

        uuid/segment
        00:01:01.526 --> 00:01:03.486
        <v Jane Doe>Good, how are you?</v>

    Output:
        [00:01:01] Jane Doe: Good, how are you?
    """
    lines = []
    current_speaker = None
    current_text_parts = []
    current_time = None

    def flush():
        nonlocal current_text_parts
        if current_speaker and current_text_parts:
            text = " ".join(current_text_parts)
            lines.append(f"[{current_time}] {current_speaker}: {text}")
            current_text_parts = []

    for raw_line in vtt_content.split("\n"):
        line = raw_line.strip().lstrip("\ufeff")  # Strip BOM

        if line == "WEBVTT" or not line:
            flush()
            continue

        # Timestamp
        time_match = re.match(r"(\d{2}:\d{2}:\d{2})\.\d+ --> ", line)
        if time_match:
            flush()
            current_time = time_match.group(1)
            continue

        # Segment ID (UUID-like)
        if re.match(r"^[a-f0-9]{8}-", line):
            continue

        # Speaker-attributed: <v Speaker Name>text</v>
        speaker_match = re.match(r"<v ([^>]+)>(.*?)(?:</v>)?$", line)
        if speaker_match:
            new_speaker = speaker_match.group(1)
            text = re.sub(r"</?v[^>]*>", "", speaker_match.group(2)).strip()

            if new_speaker != current_speaker:
                flush()
                current_speaker = new_speaker

            if text:
                current_text_parts.append(text)
            continue

        # Plain text continuation
        text = re.sub(r"</?v[^>]*>", "", line).strip()
        if text:
            current_text_parts.append(text)

    flush()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output path validation
# ---------------------------------------------------------------------------

# Resolve from the skill's expected working directory (project root)
_ALLOWED_OUTPUT_BASES = ("output", "memory")


def _validate_output_path(output_path_str: str) -> Path:
    """Validate that the output path is within allowed directories."""
    output_path = Path(output_path_str).resolve()
    cwd = Path.cwd().resolve()

    # Allow paths within the current working directory tree
    if output_path.is_relative_to(cwd):
        return output_path

    # Block writes outside the working directory
    raise ValueError(
        f"Output path must be within the working directory ({cwd}).\n"
        f"Got: {output_path}"
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download meeting transcript from SharePoint"
    )
    parser.add_argument(
        "--recording-url",
        help="WebUrl of the .mp4 recording (from MCP getFileOrFolderMetadata)",
    )
    parser.add_argument(
        "--drive-id",
        help="SharePoint drive ID (used with --item-id and --site-url)",
    )
    parser.add_argument(
        "--item-id",
        help="DriveItem ID of the .mp4 recording",
    )
    parser.add_argument(
        "--site-url",
        help="SharePoint site URL",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format",
        choices=["vtt", "text", "json"],
        default="text",
        help="Output format: vtt (raw), text (speaker-attributed), json (structured)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Page load timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Debug: log parsed arguments so failures are diagnosable
    print(
        f"  Args: site_url={args.site_url!r}, drive_id={args.drive_id!r}, "
        f"item_id={args.item_id!r}, recording_url={args.recording_url!r}, "
        f"format={args.format!r}, output={args.output!r}",
        file=sys.stderr,
    )

    # Determine fetch method
    vtt = None
    has_ids = bool(args.drive_id and args.item_id and args.site_url)
    has_url = bool(args.recording_url)

    if has_ids:
        print("Fetching transcript via direct API...", file=sys.stderr)
        vtt = asyncio.run(
            fetch_transcript_direct_api(
                site_url=args.site_url,
                drive_id=args.drive_id,
                item_id=args.item_id,
                timeout_ms=args.timeout * 1000,
            )
        )

    if not vtt and has_url:
        stream_url = build_stream_url(args.recording_url)
        print("Fetching transcript via stream.aspx (from recording URL)...", file=sys.stderr)
        vtt = asyncio.run(
            fetch_transcript_via_browser(
                stream_url, timeout_ms=args.timeout * 1000
            )
        )

    # Auto-fallback: if Method A returned no transcripts but we have IDs,
    # construct the stream.aspx URL from IDs and try Method B (browser interception).
    # This handles personal OneDrive recordings where the transcript API endpoint
    # doesn't expose transcripts but stream.aspx loads them client-side.
    if not vtt and has_ids and not has_url:
        try:
            stream_url = build_stream_url_from_ids(args.site_url, args.drive_id, args.item_id)
            print("Fetching transcript via stream.aspx (constructed from IDs)...", file=sys.stderr)
            vtt = asyncio.run(
                fetch_transcript_via_browser(
                    stream_url, timeout_ms=args.timeout * 1000
                )
            )
        except Exception as e:
            print(f"  stream.aspx fallback failed: {e}", file=sys.stderr)

    if not vtt:
        if not (has_url or has_ids):
            missing = []
            if not args.drive_id:
                missing.append("--drive-id")
            if not args.item_id:
                missing.append("--item-id")
            if not args.site_url:
                missing.append("--site-url")
            if not args.recording_url:
                missing.append("--recording-url")
            print(
                f"Error: missing required arguments: {', '.join(missing)}.\n"
                "Provide --recording-url OR all of --drive-id, --item-id, --site-url.",
                file=sys.stderr,
            )
        else:
            print(
                "Error: Could not retrieve transcript. The meeting may not have "
                "transcription enabled, or the SharePoint API returned no transcript entries.\n"
                f"  site_url: {args.site_url}\n"
                f"  drive_id: {args.drive_id}\n"
                f"  item_id:  {args.item_id}",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"Retrieved VTT: {len(vtt)} chars", file=sys.stderr)

    # Prepare output
    if args.format == "vtt":
        output = vtt
    elif args.format == "text":
        output = parse_vtt_to_text(vtt)
    elif args.format == "json":
        output = json.dumps(
            {
                "driveId": args.drive_id,
                "itemId": args.item_id,
                "siteUrl": args.site_url,
                "recordingUrl": args.recording_url,
                "format": "speaker_attributed_text",
                "content": parse_vtt_to_text(vtt),
            },
            indent=2,
        )

    # Write output
    if args.output:
        out_path = _validate_output_path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Saved to: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
