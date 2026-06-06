"""D365 Finance & Operations Expense Report automation via Playwright.

Opens the D365 expense workspace in Edge, navigates the UI, and guides
the user through creating/submitting an expense report. Always pauses
for user confirmation before final submission.

Usage (from agent):
    python skills/d365-expense/scripts/expense.py --interactive
    python skills/d365-expense/scripts/expense.py --action navigate
    python skills/d365-expense/scripts/expense.py --action screenshot
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_URL = (
    "https://myexpense.operations.dynamics.com/?cmp=1010&mi=ExpenseWorkspace"
)
_CDP_PORT = 9227  # unique to this skill
BROWSER_PROFILE_DIR = str(
    Path.home() / ".d365-expense-agent" / "browser-profile"
)
SCREENSHOT_DIR = str(
    Path.home() / ".d365-expense-agent" / "screenshots"
)

# Defaults (can be overridden via CLI args)
DEFAULTS = {
    "interim_approver": "Maila Lee",
    "final_approver": "Tarri Edmonson",
    "cost_center": "10217334",
}

# ---------------------------------------------------------------------------
# Browser connection (mirrors confluence/teams pattern)
# ---------------------------------------------------------------------------

_playwright = None
_context = None
_page = None
_edge_proc = None


def _find_edge():
    """Locate the Edge executable across platforms."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    else:
        candidates = [
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def connect_browser(headless=False):
    """Launch or connect to Edge. Returns (context, page).

    Strategy 1: CDP — launch Edge with --remote-debugging-port, connect via CDP.
    Strategy 2: Persistent context — launch_persistent_context with Edge channel.
    Strategy 3: Headed fallback — for interactive MFA.
    """
    global _playwright, _context, _page, _edge_proc
    if _page is not None:
        return _context, _page

    from playwright.sync_api import sync_playwright

    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    edge_exe = _find_edge()

    # Strategy 1: CDP
    if edge_exe:
        try:
            headless_flag = "--headless=new" if headless else ""
            cmd = [
                edge_exe,
                f"--user-data-dir={BROWSER_PROFILE_DIR}",
                f"--remote-debugging-port={_CDP_PORT}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--window-size=1440,900",
            ]
            if headless_flag:
                cmd.append(headless_flag)
            cmd.append("about:blank")
            _edge_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(3)
            _playwright = sync_playwright().start()
            browser = _playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{_CDP_PORT}",
                timeout=15_000,
            )
            _context = browser.contexts[0]
            _page = _context.new_page()
            _page.set_viewport_size({"width": 1440, "height": 900})
            print(f"✅ Connected via CDP on port {_CDP_PORT}", file=sys.stderr)
            return _context, _page
        except Exception as e:
            print(f"⚠️  CDP failed ({e}), trying persistent context...", file=sys.stderr)
            if _edge_proc:
                _edge_proc.terminate()
                _edge_proc = None
            if _playwright:
                _playwright.stop()
                _playwright = None

    # Strategy 2: Persistent context
    try:
        _playwright = sync_playwright().start()
        _context = _playwright.chromium.launch_persistent_context(
            BROWSER_PROFILE_DIR,
            channel="msedge",
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
            ],
        )
        _page = _context.new_page()
        print("✅ Connected via persistent context", file=sys.stderr)
        return _context, _page
    except Exception as e:
        print(f"⚠️  Persistent context failed ({e}), trying headed...", file=sys.stderr)
        if _context:
            _context.close()
            _context = None
        if _playwright:
            _playwright.stop()
            _playwright = None

    # Strategy 3: Headed fallback (for MFA)
    _playwright = sync_playwright().start()
    _context = _playwright.chromium.launch_persistent_context(
        BROWSER_PROFILE_DIR,
        channel="msedge",
        headless=False,
        viewport={"width": 1440, "height": 900},
    )
    _page = _context.new_page()
    print("✅ Connected via headed fallback (MFA may be required)", file=sys.stderr)
    return _context, _page


def take_screenshot(label="step"):
    """Save a screenshot and return the path."""
    global _page
    if not _page:
        return None
    ts = int(time.time())
    path = os.path.join(SCREENSHOT_DIR, f"{label}_{ts}.png")
    _page.screenshot(path=path, full_page=False)
    print(f"📸 Screenshot saved: {path}", file=sys.stderr)
    return path


def close_browser():
    """Clean shutdown of browser resources."""
    global _playwright, _context, _page, _edge_proc
    if _page:
        try:
            _page.close()
        except Exception:
            pass
        _page = None
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
            _edge_proc.wait(timeout=5)
        except Exception:
            try:
                _edge_proc.kill()
            except Exception:
                pass
        _edge_proc = None


# ---------------------------------------------------------------------------
# D365 Navigation & Interaction
# ---------------------------------------------------------------------------

def _dismiss_idle_dialog():
    """Handle D365 'Are you still there?' timeout dialog."""
    global _page
    try:
        still_here = _page.locator("button:has-text('I\\'m here'), button:has-text('Continue')")
        if still_here.count() > 0:
            still_here.first.click()
            print("🔄 Dismissed idle dialog", file=sys.stderr)
            time.sleep(1)
    except Exception:
        pass


def _dismiss_reconnect_dialog():
    """Handle network connectivity lost dialog."""
    global _page
    try:
        reconnect = _page.locator("button:has-text('Reconnect'), button:has-text('Retry')")
        if reconnect.count() > 0:
            reconnect.first.click()
            print("🔄 Clicked Reconnect", file=sys.stderr)
            time.sleep(3)
    except Exception:
        pass


def _wait_for_d365_ready(timeout=60):
    """Wait until D365 page is loaded and interactive."""
    global _page
    start = time.time()
    while time.time() - start < timeout:
        _dismiss_idle_dialog()
        _dismiss_reconnect_dialog()
        # Check if the main workspace shell is loaded
        try:
            ready = _page.evaluate("""
                () => {
                    const loading = document.querySelector('.loading-indicator, .splash-screen');
                    if (loading && getComputedStyle(loading).display !== 'none') return false;
                    // Check if the main content area exists
                    const content = document.querySelector(
                        '[data-dyn-controlname], .workspace-wrapper, #MainContent, .modulesFlyout-mainArea'
                    );
                    return content !== null;
                }
            """)
            if ready:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def navigate_to_workspace():
    """Navigate to the D365 Expense Management workspace."""
    global _page
    print(f"🌐 Navigating to: {WORKSPACE_URL}", file=sys.stderr)
    _page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=60000)

    # Wait for D365 to finish loading
    loaded = _wait_for_d365_ready(timeout=60)
    if loaded:
        print("✅ D365 Expense workspace loaded", file=sys.stderr)
    else:
        print("⚠️  D365 may still be loading — check screenshot", file=sys.stderr)

    return take_screenshot("workspace")


def get_page_state():
    """Extract current page state — title, URL, visible text, form fields."""
    global _page
    state = {
        "url": _page.url,
        "title": _page.title(),
    }

    try:
        state["visible_text"] = _page.evaluate("""
            () => {
                const el = document.querySelector(
                    '.workspace-wrapper, #MainContent, [data-dyn-controlname="ExpenseWorkspace"], body'
                );
                const text = el ? el.innerText : document.body.innerText;
                return text.substring(0, 5000);
            }
        """)
    except Exception:
        state["visible_text"] = ""

    try:
        state["buttons"] = _page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll(
                    'button:not([style*="display: none"]), [role="button"], .button-container a'
                ));
                return btns.slice(0, 30).map(b => ({
                    text: (b.innerText || b.getAttribute('aria-label') || '').trim().substring(0, 80),
                    id: b.id || '',
                    name: b.getAttribute('data-dyn-controlname') || '',
                })).filter(b => b.text.length > 0);
            }
        """)
    except Exception:
        state["buttons"] = []

    try:
        state["inputs"] = _page.evaluate("""
            () => {
                const inputs = Array.from(document.querySelectorAll(
                    'input:not([type="hidden"]), select, textarea, [contenteditable="true"]'
                ));
                return inputs.slice(0, 30).map(inp => ({
                    type: inp.tagName.toLowerCase() + (inp.type ? ':' + inp.type : ''),
                    id: inp.id || '',
                    name: inp.name || inp.getAttribute('data-dyn-controlname') || '',
                    label: inp.getAttribute('aria-label') || '',
                    value: (inp.value || '').substring(0, 100),
                    placeholder: inp.placeholder || '',
                }));
            }
        """)
    except Exception:
        state["inputs"] = []

    return state


def click_element(selector=None, text=None, control_name=None):
    """Click an element by selector, visible text, or D365 control name."""
    global _page
    _dismiss_idle_dialog()

    target = None
    if selector:
        target = _page.locator(selector)
    elif text:
        # Try button/link with matching text
        target = _page.locator(
            f"button:has-text('{text}'), a:has-text('{text}'), "
            f"[role='button']:has-text('{text}'), span:has-text('{text}')"
        )
    elif control_name:
        target = _page.locator(f"[data-dyn-controlname='{control_name}']")

    if target and target.count() > 0:
        target.first.scroll_into_view_if_needed()
        target.first.click()
        time.sleep(2)
        _dismiss_idle_dialog()
        print(f"✅ Clicked: {selector or text or control_name}", file=sys.stderr)
        return True

    print(f"❌ Element not found: {selector or text or control_name}", file=sys.stderr)
    return False


def fill_field(selector=None, label=None, control_name=None, value=""):
    """Fill a form field by selector, aria-label, or D365 control name."""
    global _page
    _dismiss_idle_dialog()

    target = None
    if selector:
        target = _page.locator(selector)
    elif label:
        target = _page.locator(f"[aria-label='{label}'], input[placeholder*='{label}']")
    elif control_name:
        target = _page.locator(
            f"[data-dyn-controlname='{control_name}'] input, "
            f"[data-dyn-controlname='{control_name}'] textarea"
        )

    if target and target.count() > 0:
        target.first.scroll_into_view_if_needed()
        target.first.click()
        target.first.fill(value)
        time.sleep(1)
        print(f"✅ Filled '{selector or label or control_name}' with '{value}'", file=sys.stderr)
        return True

    print(f"❌ Field not found: {selector or label or control_name}", file=sys.stderr)
    return False


def select_dropdown(control_name=None, label=None, option_text=""):
    """Select an option from a D365 dropdown/lookup field."""
    global _page
    _dismiss_idle_dialog()

    # D365 dropdowns often require clicking the field, then selecting from a list
    locator = None
    if control_name:
        locator = _page.locator(f"[data-dyn-controlname='{control_name}']")
    elif label:
        locator = _page.locator(f"[aria-label='{label}']")

    if locator and locator.count() > 0:
        locator.first.click()
        time.sleep(1)
        # Type to filter and select
        active = _page.locator("input:focus, [contenteditable]:focus")
        if active.count() > 0:
            active.first.fill(option_text)
            time.sleep(1)
            # Press Enter or click the matching dropdown item
            _page.keyboard.press("Enter")
            time.sleep(1)
            print(f"✅ Selected '{option_text}' in dropdown", file=sys.stderr)
            return True

    print(f"❌ Dropdown not found or option not selected", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="D365 Expense Report Automation")
    parser.add_argument("--action", choices=[
        "navigate", "screenshot", "state", "click", "fill", "select",
        "create_report", "interactive",
    ], default="navigate")
    parser.add_argument("--headless", action="store_true", default=False)
    parser.add_argument("--selector", help="CSS selector for click/fill")
    parser.add_argument("--text", help="Visible text for click")
    parser.add_argument("--control-name", help="D365 data-dyn-controlname")
    parser.add_argument("--label", help="aria-label for fill/select")
    parser.add_argument("--value", help="Value for fill", default="")
    parser.add_argument("--title", help="Expense report title")
    parser.add_argument("--expenses", help="JSON array of expense objects")
    args = parser.parse_args()

    try:
        connect_browser(headless=args.headless)

        if args.action == "navigate":
            ss = navigate_to_workspace()
            state = get_page_state()
            print(json.dumps({"screenshot": ss, "state": state}, indent=2))

        elif args.action == "screenshot":
            ss = take_screenshot("manual")
            print(json.dumps({"screenshot": ss}))

        elif args.action == "state":
            state = get_page_state()
            print(json.dumps(state, indent=2))

        elif args.action == "click":
            ok = click_element(
                selector=args.selector, text=args.text,
                control_name=args.control_name,
            )
            ss = take_screenshot("after_click")
            state = get_page_state()
            print(json.dumps({"clicked": ok, "screenshot": ss, "state": state}, indent=2))

        elif args.action == "fill":
            ok = fill_field(
                selector=args.selector, label=args.label,
                control_name=args.control_name, value=args.value,
            )
            ss = take_screenshot("after_fill")
            print(json.dumps({"filled": ok, "screenshot": ss}))

        elif args.action == "select":
            ok = select_dropdown(
                control_name=args.control_name, label=args.label,
                option_text=args.value,
            )
            ss = take_screenshot("after_select")
            print(json.dumps({"selected": ok, "screenshot": ss}))

        elif args.action == "create_report":
            # Full workflow: navigate → inspect → report results
            ss = navigate_to_workspace()
            state = get_page_state()
            result = {
                "screenshot": ss,
                "state": state,
                "title": args.title,
                "expenses": json.loads(args.expenses) if args.expenses else [],
                "defaults": DEFAULTS,
                "status": "workspace_loaded",
                "next_step": "Inspect the workspace and proceed with report creation",
            }
            print(json.dumps(result, indent=2))

        elif args.action == "interactive":
            ss = navigate_to_workspace()
            state = get_page_state()
            print(json.dumps({
                "screenshot": ss,
                "state": state,
                "message": "Workspace loaded. Ready for interactive commands.",
            }, indent=2))
            # Keep browser open for subsequent CLI calls
            print("\n⏳ Browser session active. Run additional commands with --action.", file=sys.stderr)
            print("   Press Ctrl+C to close.", file=sys.stderr)
            try:
                while True:
                    time.sleep(5)
                    _dismiss_idle_dialog()
            except KeyboardInterrupt:
                pass

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    finally:
        if args.action != "interactive":
            close_browser()


if __name__ == "__main__":
    main()
