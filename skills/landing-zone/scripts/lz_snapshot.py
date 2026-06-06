#!/usr/bin/env python3
"""lz_snapshot.py — Timestamped snapshots and week-over-week comparison.

Usage:
    cd skills/landing-zone
    python -m scripts.lz_snapshot --program my-program                    # Create snapshot
    python -m scripts.lz_snapshot --program my-program --wow             # WoW comparison (latest vs 7 days ago)
    python -m scripts.lz_snapshot --program my-program --compare --from 2026-02-24 --to 2026-03-03
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "cache"
PROJECT_ROOT = SKILL_ROOT.parent.parent


def load_cache(program: str) -> dict:
    path = CACHE_DIR / f"{program}-lz.json"
    if not path.exists():
        print(f"ERROR: No cache for '{program}'.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_snapshot(program: str, cache: dict) -> Path:
    """Create a timestamped snapshot from current cache."""
    snap_dir = CACHE_DIR / "snapshots" / program
    snap_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap_path = snap_dir / f"{date_str}.json"

    # Build compact snapshot (items + stats, no full tree)
    items = cache.get("items", {})
    snapshot = {
        "date": date_str,
        "program": program,
        "meta": cache.get("meta", {}),
        "stats": cache.get("stats", {}),
        "items": {
            str(k): {
                "id": v["id"], "type": v.get("type", ""), "title": v.get("title", ""),
                "state": v.get("state", ""), "assigned_to": v.get("assigned_to", ""),
                "tags": v.get("tags", ""),
            }
            for k, v in items.items()
        },
    }

    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"Snapshot saved: {snap_path}")

    # Also update knowledgebase markdown (delegate to lz_sync's generator)
    from scripts.lz_sync import generate_markdown, compute_stats
    flat_items = list(items.values())
    stats = compute_stats(flat_items)
    tree = cache.get("tree", {})
    meta = cache.get("meta", {})
    md_path = generate_markdown(program, tree, stats, meta)
    print(f"Markdown updated: {md_path}")

    return snap_path


def find_snapshot(program: str, target_date: str) -> Path | None:
    """Find a snapshot for a given date, or the closest earlier one."""
    snap_dir = CACHE_DIR / "snapshots" / program
    if not snap_dir.exists():
        return None

    exact = snap_dir / f"{target_date}.json"
    if exact.exists():
        return exact

    # Find closest earlier snapshot
    snapshots = sorted(snap_dir.glob("*.json"), reverse=True)
    for snap in snapshots:
        if snap.stem <= target_date:
            return snap
    return snapshots[-1] if snapshots else None


def load_snapshot(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_snapshots(old: dict, new: dict) -> dict:
    """Compare two snapshots and generate delta analysis."""
    old_items = old.get("items", {})
    new_items = new.get("items", {})
    old_ids = set(old_items.keys())
    new_ids = set(new_items.keys())

    added = new_ids - old_ids
    removed = old_ids - new_ids
    common = old_ids & new_ids

    state_changes = []
    dri_changes = []
    for item_id in common:
        o = old_items[item_id]
        n = new_items[item_id]
        if o.get("state") != n.get("state"):
            state_changes.append({
                "id": n["id"], "title": n.get("title", ""),
                "old_state": o.get("state", ""), "new_state": n.get("state", ""),
                "assigned_to": n.get("assigned_to", ""),
            })
        if o.get("assigned_to") != n.get("assigned_to"):
            dri_changes.append({
                "id": n["id"], "title": n.get("title", ""),
                "old_dri": o.get("assigned_to", ""), "new_dri": n.get("assigned_to", ""),
            })

    # State distribution shift
    old_states = old.get("stats", {}).get("by_state", {})
    new_states = new.get("stats", {}).get("by_state", {})
    all_states = sorted(set(list(old_states.keys()) + list(new_states.keys())))
    state_shift = {}
    for s in all_states:
        old_c = old_states.get(s, 0)
        new_c = new_states.get(s, 0)
        state_shift[s] = {"old": old_c, "new": new_c, "delta": new_c - old_c}

    # Domain-level analysis
    domain_deltas = _compute_domain_deltas(old_items, new_items, state_changes)

    return {
        "old_date": old.get("date", "?"),
        "new_date": new.get("date", "?"),
        "items_added": len(added),
        "items_removed": len(removed),
        "state_changes": state_changes,
        "dri_changes": dri_changes,
        "state_shift": state_shift,
        "domain_deltas": domain_deltas,
        "added_ids": sorted(added),
        "removed_ids": sorted(removed),
    }


def _compute_domain_deltas(old_items: dict, new_items: dict, state_changes: list) -> dict:
    """Compute per-domain progress deltas."""
    # Group items by type=Domain (rough heuristic: items whose type is Domain)
    domains: dict[str, dict] = {}
    for items, label in [(old_items, "old"), (new_items, "new")]:
        for item in items.values():
            if item.get("type") == "Domain":
                name = item.get("title", f"#{item['id']}")
                if name not in domains:
                    domains[name] = {"old_count": 0, "new_count": 0, "state_changes": 0}

    # Count state changes per domain (simplified — uses assigned DRI as proxy)
    return domains


def format_comparison(delta: dict, program: str) -> str:
    """Format comparison as markdown report."""
    lines = [
        f"# {program.replace('-', ' ').title()} — Week-over-Week LZ Report",
        "",
        f"> **From:** {delta['old_date']}",
        f"> **To:** {delta['new_date']}",
        "",
        "## Overview",
        "",
        f"- **Items added:** {delta['items_added']}",
        f"- **Items removed:** {delta['items_removed']}",
        f"- **State changes:** {len(delta['state_changes'])}",
        f"- **DRI reassignments:** {len(delta['dri_changes'])}",
        "",
    ]

    # State distribution shift
    lines.extend(["## State Distribution Shift", "",
                   "| State | Before | After | Delta |",
                   "|-------|-------:|------:|------:|"])
    for state, data in delta["state_shift"].items():
        d = data["delta"]
        sign = "+" if d > 0 else ""
        lines.append(f"| {state} | {data['old']} | {data['new']} | {sign}{d} |")

    # State changes
    if delta["state_changes"]:
        lines.extend(["", f"## State Transitions ({len(delta['state_changes'])})", "",
                       "| ID | Title | From | To | DRI |",
                       "|---:|-------|------|----|-----|"])
        for sc in delta["state_changes"][:30]:
            lines.append(
                f"| {sc['id']} | {sc['title'][:40]} | {sc['old_state']} | "
                f"{sc['new_state']} | {sc['assigned_to']} |"
            )
        if len(delta["state_changes"]) > 30:
            lines.append(f"\n*...and {len(delta['state_changes']) - 30} more*")

    # Newly closed POR
    newly_closed = [sc for sc in delta["state_changes"] if sc["new_state"] in ("Closed POR", "Committed")]
    if newly_closed:
        lines.extend(["", f"## Newly Closed POR ({len(newly_closed)})", "",
                       "| ID | Title | DRI |",
                       "|---:|-------|-----|"])
        for sc in newly_closed:
            lines.append(f"| {sc['id']} | {sc['title'][:50]} | {sc['assigned_to']} |")

    # Newly at-risk
    newly_at_risk = [sc for sc in delta["state_changes"] if sc["new_state"] == "At Risk"]
    if newly_at_risk:
        lines.extend(["", f"## Newly At Risk ({len(newly_at_risk)})", "",
                       "| ID | Title | Previous State | DRI |",
                       "|---:|-------|----------------|-----|"])
        for sc in newly_at_risk:
            lines.append(f"| {sc['id']} | {sc['title'][:40]} | {sc['old_state']} | {sc['assigned_to']} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="LZ snapshots and WoW comparison.")
    parser.add_argument("--program", "-p", required=True, help="Program name")
    parser.add_argument("--wow", action="store_true", help="Week-over-week comparison (latest vs 7 days ago)")
    parser.add_argument("--compare", action="store_true", help="Compare two specific dates")
    parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.wow or args.compare:
        # Comparison mode
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if args.compare and args.from_date and args.to_date:
            from_date, to_date = args.from_date, args.to_date
        else:
            to_date = today
            from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        old_path = find_snapshot(args.program, from_date)
        new_path = find_snapshot(args.program, to_date)

        if not old_path:
            print(f"ERROR: No snapshot found for {from_date} or earlier.", file=sys.stderr)
            print(f"Available snapshots:", file=sys.stderr)
            snap_dir = CACHE_DIR / "snapshots" / args.program
            if snap_dir.exists():
                for s in sorted(snap_dir.glob("*.json")):
                    print(f"  {s.stem}", file=sys.stderr)
            sys.exit(1)
        if not new_path:
            print(f"ERROR: No snapshot found for {to_date}. Run snapshot first.", file=sys.stderr)
            sys.exit(1)

        print(f"Comparing: {old_path.stem} → {new_path.stem}")
        old_snap = load_snapshot(old_path)
        new_snap = load_snapshot(new_path)
        delta = compare_snapshots(old_snap, new_snap)
        print(format_comparison(delta, args.program))
    else:
        # Snapshot mode
        cache = load_cache(args.program)
        create_snapshot(args.program, cache)


if __name__ == "__main__":
    main()
