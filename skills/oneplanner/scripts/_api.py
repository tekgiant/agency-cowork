"""
OnePlanner REST API client — shared helper for all op_*.py scripts.

Communicates with the local Fastify server at http://127.0.0.1:3100.
Uses only Python stdlib (urllib.request, json, pathlib).

Usage (internal — imported by other scripts):
    from scripts._api import api_get, api_post, api_patch, api_delete
    from scripts._api import ensure_session, load_cache, save_cache
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 encoding errors with Unicode chars
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── Constants ────────────────────────────────────────────────────────────────

SKILL_ROOT = Path(__file__).resolve().parent.parent  # skills/oneplanner/
CACHE_DIR = SKILL_ROOT / "cache"
PROJECT_ROOT = SKILL_ROOT.parent.parent               # repo root
API_BASE = "http://127.0.0.1:3100"

# ─── REST Client ──────────────────────────────────────────────────────────────


def api_request(method: str, path: str, body: dict | list | None = None,
                params: dict | None = None) -> dict | list | None:
    """Make an HTTP request to the local OnePlanner API server."""
    url = f"{API_BASE}{path}"
    if params:
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if qs:
            url += f"?{qs}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8")
            err = json.loads(body_text)
            msg = err.get("error", body_text)
        except Exception:
            msg = body_text or str(e)
        print(f"ERROR ({e.code}): {msg}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot connect to OnePlanner API at {API_BASE}. "
              f"Is the dev server running? (npm run dev)\n  {e.reason}", file=sys.stderr)
        sys.exit(1)


# Convenience wrappers
import urllib.parse  # noqa: E402


def api_get(path: str, params: dict | None = None):
    return api_request("GET", path, params=params)


def api_post(path: str, body: dict | None = None):
    return api_request("POST", path, body=body or {})


def api_patch(path: str, body: dict):
    return api_request("PATCH", path, body=body)


def api_delete(path: str):
    return api_request("DELETE", path)


# ─── Session Management ──────────────────────────────────────────────────────


def check_health() -> dict:
    """Check if the API server is running and return health status."""
    return api_get("/health")


def ensure_session(planner_url: str | None = None) -> dict:
    """
    Ensure the API has an active authenticated session.
    If not authenticated, either uses the provided plannerUrl or prompts for one.
    Returns the health status.
    """
    health = check_health()
    if health.get("authenticated"):
        return health

    if not planner_url:
        # Check if there's a saved planner URL in cache
        cached = load_cache("session")
        if cached and cached.get("data", {}).get("plannerUrl"):
            planner_url = cached["data"]["plannerUrl"]
            print(f"Using saved Planner URL: {planner_url}")
        else:
            planner_url = input("Enter Planner URL: ").strip()
            if not planner_url:
                print("ERROR: No Planner URL provided.", file=sys.stderr)
                sys.exit(1)

    print(f"Authenticating via browser... (URL: {planner_url})")
    result = api_post("/auth/login", {"plannerUrl": planner_url})
    if result and result.get("ok"):
        # Cache the planner URL for future use
        save_cache("session", {"plannerUrl": planner_url, "projectId": result.get("projectId")})
        print(f"Authenticated! Project ID: {result.get('projectId')}")
    return check_health()


def ensure_loaded() -> dict:
    """Ensure project data is loaded. Loads if needed. Returns health."""
    health = check_health()
    if not health.get("authenticated"):
        print("ERROR: Not authenticated. Run: python -m scripts.op_snapshot save", file=sys.stderr)
        sys.exit(1)
    if not health.get("hasSnapshot"):
        print("Loading project data...")
        api_post("/project/load")
    return check_health()


# ─── Cache Helpers ────────────────────────────────────────────────────────────


def load_cache(name: str) -> dict | None:
    """Read a cached JSON file from skills/oneplanner/cache/."""
    path = CACHE_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(name: str, data) -> Path:
    """Write data to a cached JSON file with metadata wrapper."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    payload = {
        "lastRefreshed": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def save_cache_raw(name: str, data) -> Path:
    """Write data directly (no metadata wrapper)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ─── Display Helpers ──────────────────────────────────────────────────────────


def confirm(msg: str) -> bool:
    """Prompt user for confirmation before destructive actions."""
    print(f"\n{msg}")
    resp = input("Proceed? [y/N]: ").strip().lower()
    return resp in ("y", "yes")


def format_table(headers: list[str], rows: list[list[str]], max_width: int = 120) -> str:
    """Format data as a fixed-width text table."""
    if not rows:
        return "(no data)"

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))

    # Cap widths
    total = sum(widths) + (len(widths) - 1) * 3
    if total > max_width and widths:
        # Shrink the widest column
        widths[-1] = max(10, widths[-1] - (total - max_width))

    # Format
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    sep = "-+-".join("-" * w for w in widths)

    lines = [fmt.format(*[str(h)[:w] for h, w in zip(headers, widths)]), sep]
    for row in rows:
        cells = [str(c)[:w] for c, w in zip(row, widths)]
        # Pad if fewer cells than headers
        while len(cells) < len(widths):
            cells.append("")
        lines.append(fmt.format(*cells))

    return "\n".join(lines)


def format_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format data as a Markdown table."""
    if not rows:
        return "(no data)"
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        cells = [str(c) for c in row]
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def format_output(headers: list[str], rows: list[list[str]], fmt: str = "table") -> str:
    """Format data in the requested output format."""
    if fmt == "json":
        items = []
        for row in rows:
            item = {}
            for i, h in enumerate(headers):
                item[h] = row[i] if i < len(row) else ""
            items.append(item)
        return json.dumps(items, indent=2, ensure_ascii=False)
    elif fmt == "markdown":
        return format_markdown_table(headers, rows)
    else:
        return format_table(headers, rows)
