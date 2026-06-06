"""Workstream action-item tracker.

Manages action-items.json per workstream in the Knowledgebase.

Usage:
    cd skills/workstreams
    python -m scripts.ws_tracker add --workstream my-program/my-workstream \
        --description "Finalize integration spec" --dri "Jane Doe" --due 2026-03-15
    python -m scripts.ws_tracker list [--workstream X] [--overdue] [--dri NAME]
    python -m scripts.ws_tracker update --id ai-001 --status in-progress
    python -m scripts.ws_tracker close --id ai-001 --note "Completed in LZ"
    python -m scripts.ws_tracker summary [--program my-program]
"""

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

KB_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "memory" / "Knowledgebase" / "Workstreams"
REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry.json"

STATUSES = ("open", "in-progress", "done", "cancelled")


def load_registry() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def action_items_path(workstream_slug: str) -> Path:
    """Return path to action-items.json for a workstream slug like 'program/workstream'."""
    return KB_ROOT / workstream_slug / "action-items.json"


def load_items(workstream_slug: str) -> list[dict]:
    p = action_items_path(workstream_slug)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_items(workstream_slug: str, items: list[dict]) -> None:
    p = action_items_path(workstream_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, default=str)


def next_id(items: list[dict]) -> str:
    """Generate next ai-NNN ID."""
    max_n = 0
    for item in items:
        try:
            n = int(item["id"].split("-")[1])
            if n > max_n:
                max_n = n
        except (IndexError, ValueError):
            pass
    return f"ai-{max_n + 1:03d}"


def all_workstream_slugs() -> list[str]:
    """Get all workstream slugs from registry."""
    reg = load_registry()
    return [ws["kb_path"] for ws in reg["workstreams"]]


def cmd_add(args):
    items = load_items(args.workstream)
    new_id = next_id(items)
    today = date.today().isoformat()
    item = {
        "id": new_id,
        "workstream": args.workstream,
        "description": args.description,
        "dri": args.dri or "",
        "due_date": args.due or "",
        "status": "open",
        "source_meeting": args.source or "",
        "lz_req_id": args.lz_req or None,
        "created": today,
        "updated": today,
        "notes": [],
    }
    items.append(item)
    save_items(args.workstream, items)
    print(f"Added {new_id}: {args.description}")
    if args.dri:
        print(f"  DRI: {args.dri}")
    if args.due:
        print(f"  Due: {args.due}")


def cmd_list(args):
    slugs = [args.workstream] if args.workstream else all_workstream_slugs()
    all_items = []
    for slug in slugs:
        for item in load_items(slug):
            if args.dri and args.dri.lower() not in item.get("dri", "").lower():
                continue
            if args.overdue:
                due = item.get("due_date", "")
                if not due or item["status"] in ("done", "cancelled"):
                    continue
                if due >= date.today().isoformat():
                    continue
            elif item["status"] in ("done", "cancelled") and not args.all:
                continue
            all_items.append(item)

    if not all_items:
        print("No action items match the filter.")
        return

    # Print table
    print(f"{'ID':<8} {'Status':<12} {'DRI':<20} {'Due':<12} {'Workstream':<30} Description")
    print("-" * 120)
    for item in sorted(all_items, key=lambda x: x.get("due_date", "9999")):
        overdue_marker = " !" if (item.get("due_date", "") and item["due_date"] < date.today().isoformat() and item["status"] not in ("done", "cancelled")) else ""
        print(f"{item['id']:<8} {item['status']:<12} {item.get('dri', '')[:19]:<20} {item.get('due_date', ''):<12} {item['workstream']:<30} {item['description'][:50]}{overdue_marker}")


def cmd_update(args):
    # Find item across all workstreams
    for slug in all_workstream_slugs():
        items = load_items(slug)
        for item in items:
            if item["id"] == args.id:
                if args.status:
                    item["status"] = args.status
                if args.dri:
                    item["dri"] = args.dri
                if args.due:
                    item["due_date"] = args.due
                if args.note:
                    item["notes"].append({"date": date.today().isoformat(), "text": args.note})
                item["updated"] = date.today().isoformat()
                save_items(slug, items)
                print(f"Updated {args.id} in {slug}")
                return
    print(f"Item {args.id} not found.", file=sys.stderr)
    sys.exit(1)


def cmd_close(args):
    for slug in all_workstream_slugs():
        items = load_items(slug)
        for item in items:
            if item["id"] == args.id:
                item["status"] = "done"
                item["updated"] = date.today().isoformat()
                if args.note:
                    item["notes"].append({"date": date.today().isoformat(), "text": f"Closed: {args.note}"})
                save_items(slug, items)
                print(f"Closed {args.id}: {item['description']}")
                return
    print(f"Item {args.id} not found.", file=sys.stderr)
    sys.exit(1)


def cmd_summary(args):
    """Markdown summary of all open items, grouped by workstream."""
    reg = load_registry()
    ws_map = {ws["kb_path"]: ws["display_name"] for ws in reg["workstreams"]}
    slugs = [s for s in all_workstream_slugs() if not args.program or s.startswith(args.program)]

    now = datetime.now(tz=None).astimezone().strftime('%Y-%m-%d %H:%M %Z')
    lines = [f"# Action Items Summary\n", f"> Generated: {now}\n"]
    total_open = 0
    total_overdue = 0

    for slug in sorted(slugs):
        items = [i for i in load_items(slug) if i["status"] in ("open", "in-progress")]
        if not items:
            continue
        display = ws_map.get(slug, slug)
        lines.append(f"\n## {display} ({slug})\n")
        lines.append(f"| ID | Status | DRI | Due | Description |")
        lines.append(f"|---:|--------|-----|-----|-------------|")
        for item in sorted(items, key=lambda x: x.get("due_date", "9999")):
            overdue = ""
            if item.get("due_date") and item["due_date"] < date.today().isoformat():
                overdue = " **OVERDUE**"
                total_overdue += 1
            total_open += 1
            lines.append(f"| {item['id']} | {item['status']} | {item.get('dri', '')} | {item.get('due_date', '')}{overdue} | {item['description']} |")

    lines.insert(2, f"> **Open:** {total_open} | **Overdue:** {total_overdue}\n")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Workstream action-item tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add an action item")
    p_add.add_argument("--workstream", "-w", required=True, help="Workstream slug (e.g., my-program/my-workstream)")
    p_add.add_argument("--description", "-d", required=True, help="Action description")
    p_add.add_argument("--dri", help="Directly responsible individual")
    p_add.add_argument("--due", help="Due date (YYYY-MM-DD)")
    p_add.add_argument("--source", help="Source meeting slug")
    p_add.add_argument("--lz-req", type=int, help="Related LZ requirement ID")
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", help="List action items")
    p_list.add_argument("--workstream", "-w", help="Filter by workstream slug")
    p_list.add_argument("--dri", help="Filter by DRI name (substring match)")
    p_list.add_argument("--overdue", action="store_true", help="Show only overdue items")
    p_list.add_argument("--all", action="store_true", help="Include done/cancelled items")
    p_list.set_defaults(func=cmd_list)

    # update
    p_upd = sub.add_parser("update", help="Update an action item")
    p_upd.add_argument("--id", required=True, help="Action item ID (e.g., ai-001)")
    p_upd.add_argument("--status", choices=STATUSES, help="New status")
    p_upd.add_argument("--dri", help="New DRI")
    p_upd.add_argument("--due", help="New due date")
    p_upd.add_argument("--note", help="Add a note")
    p_upd.set_defaults(func=cmd_update)

    # close
    p_close = sub.add_parser("close", help="Close an action item")
    p_close.add_argument("--id", required=True, help="Action item ID")
    p_close.add_argument("--note", help="Closing note")
    p_close.set_defaults(func=cmd_close)

    # summary
    p_sum = sub.add_parser("summary", help="Markdown summary of open items")
    p_sum.add_argument("--program", "-p", help="Filter by program (e.g., my-program)")
    p_sum.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
