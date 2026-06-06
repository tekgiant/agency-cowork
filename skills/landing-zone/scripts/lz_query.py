#!/usr/bin/env python3
"""lz_query.py — Query and filter cached Landing Zone data.

Usage:
    cd skills/landing-zone
    python -m scripts.lz_query --program my-program --search "CMK encryption"
    python -m scripts.lz_query --program my-program --not-ready
    python -m scripts.lz_query --program my-program --domain "System-level RAS"
    python -m scripts.lz_query --program my-program --state "New" --output json
"""

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "cache"

sys.path.insert(0, str(SKILL_ROOT))
from models.state_machine import parse_state, GRADED_STATES, TERMINAL_STATES


def load_cache(program: str) -> dict:
    """Load cached LZ data."""
    path = CACHE_DIR / f"{program}-lz.json"
    if not path.exists():
        print(f"ERROR: No cache for '{program}'. Run: python -m scripts.lz_sync --program {program}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_flat_items(cache: dict) -> list[dict]:
    """Get all items as a flat list from cache."""
    items = cache.get("items", {})
    return list(items.values())


def get_domain_path(cache: dict, item_id: int) -> str:
    """Trace the domain ancestry path for an item."""
    items = cache.get("items", {})
    children_map = cache.get("tree", {}).get("children_map", {})
    # Build reverse parent map
    parent_map: dict[int, int] = {}
    for pid_str, child_ids in children_map.items():
        pid = int(pid_str)
        for cid in child_ids:
            parent_map[cid] = pid

    path_parts = []
    current = item_id
    while current in parent_map:
        parent = parent_map[current]
        parent_item = items.get(str(parent), {})
        if parent_item.get("type") in ("Domain", "Epic"):
            path_parts.insert(0, parent_item.get("title", f"#{parent}"))
        current = parent
    return " > ".join(path_parts) if path_parts else "(root)"


def _strip_html(text: str) -> str:
    """Strip HTML tags for plain-text search."""
    return re.sub(r"<[^>]+>", " ", text)


def filter_items(items: list[dict], cache: dict, args) -> list[dict]:
    """Apply filters to items."""
    result = items

    # Free-text search across title, description, and tags
    if args.search:
        keywords = args.search.lower().split()
        def matches(item):
            blob = " ".join([
                item.get("title", ""),
                _strip_html(item.get("description", "") or ""),
                item.get("tags", ""),
            ]).lower()
            return all(kw in blob for kw in keywords)
        result = [i for i in result if matches(i)]

    if args.state:
        target = args.state.lower()
        result = [i for i in result if i.get("state", "").lower() == target]

    if args.type:
        target = args.type.lower()
        result = [i for i in result if i.get("type", "").lower() == target]

    if args.dri:
        target = args.dri.lower()
        result = [i for i in result if target in (i.get("assigned_to", "") or "").lower()]

    if args.created_by:
        target = args.created_by.lower()
        result = [i for i in result if target in (i.get("created_by", "") or "").lower()]

    if args.iteration:
        target = args.iteration.lower()
        result = [i for i in result if target in (i.get("iteration_path", "") or "").lower()]

    if args.domain:
        target = args.domain.lower()
        result = [i for i in result if target in get_domain_path(cache, i["id"]).lower()]

    if args.not_ready:
        result = [i for i in result
                  if not i.get("minimum") or not i.get("target")
                  or parse_state(i.get("state", "")) not in GRADED_STATES | TERMINAL_STATES]

    if args.at_risk:
        result = [i for i in result if parse_state(i.get("state", "")) is not None
                  and i.get("state", "").lower() in ("at risk",)]

    if args.ungraded:
        result = [i for i in result
                  if i.get("state", "") == "Ready for Architecture Response"]

    if args.stale:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.stale)
        cutoff_str = cutoff.isoformat()
        result = [i for i in result
                  if (i.get("changed_date", "") or "9999") < cutoff_str]

    return result


def format_table(items: list[dict], cache: dict) -> str:
    """Format items as a text table."""
    if not items:
        return "No items match the filter."
    lines = [
        f"{'ID':>6} | {'Type':<12} | {'State':<30} | {'DRI':<25} | Title",
        "-" * 120,
    ]
    for item in items:
        lines.append(
            f"{item['id']:>6} | {item.get('type', ''):<12} | {item.get('state', ''):<30} | "
            f"{(item.get('assigned_to', '') or ''):<25} | {item.get('title', '')[:50]}"
        )
    lines.append(f"\n{len(items)} items")
    return "\n".join(lines)


def format_markdown(items: list[dict], cache: dict) -> str:
    """Format items as markdown."""
    if not items:
        return "No items match the filter."
    lines = [
        "| ID | Type | State | DRI | Title |",
        "|---:|------|-------|-----|-------|",
    ]
    for item in items:
        lines.append(
            f"| {item['id']} | {item.get('type', '')} | {item.get('state', '')} | "
            f"{item.get('assigned_to', '')} | {item.get('title', '')} |"
        )
    lines.append(f"\n*{len(items)} items*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Query cached Landing Zone data.")
    parser.add_argument("--program", "-p", required=True, help="Program name (e.g., my-program)")
    parser.add_argument("--search", "-s", help="Free-text search across title, description, and tags (all keywords must match)")
    parser.add_argument("--state", help="Filter by state")
    parser.add_argument("--type", help="Filter by work item type")
    parser.add_argument("--dri", help="Filter by DRI/assigned-to name (substring)")
    parser.add_argument("--created-by", help="Filter by creator name (substring)")
    parser.add_argument("--iteration", help="Filter by iteration path (substring)")
    parser.add_argument("--domain", help="Filter by technology domain (substring)")
    parser.add_argument("--not-ready", action="store_true", help="Items not ready for grading")
    parser.add_argument("--at-risk", action="store_true", help="Items in At Risk state")
    parser.add_argument("--ungraded", action="store_true", help="Items awaiting architecture response grades")
    parser.add_argument("--stale", type=int, metavar="DAYS", help="Items unchanged for N days")
    parser.add_argument("--output", "-o", choices=["table", "json", "markdown"], default="table",
                        help="Output format (default: table)")
    args = parser.parse_args()

    cache = load_cache(args.program)
    items = get_flat_items(cache)
    filtered = filter_items(items, cache, args)

    if args.output == "json":
        print(json.dumps(filtered, indent=2, ensure_ascii=False))
    elif args.output == "markdown":
        print(format_markdown(filtered, cache))
    else:
        print(format_table(filtered, cache))


if __name__ == "__main__":
    main()
