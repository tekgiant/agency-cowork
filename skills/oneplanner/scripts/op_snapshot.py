"""
op_snapshot — Save, refresh, and browse project snapshots.

Usage:
    python -m scripts.op_snapshot save [--url URL]    # Authenticate + load + cache
    python -m scripts.op_snapshot refresh              # Reload from API
    python -m scripts.op_snapshot summary              # Print project stats
    python -m scripts.op_snapshot show [--format json|table]  # Show all tasks
    python -m scripts.op_snapshot diff [FILE]          # Compare current vs cached snapshot
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from ._api import (
    api_get, api_post, ensure_session, ensure_loaded,
    load_cache, save_cache, save_cache_raw,
    format_output, CACHE_DIR,
)


def cmd_save(args):
    """Authenticate, load project data, and save a snapshot to cache."""
    ensure_session(args.url)
    print("Loading project data...")
    result = api_post("/project/load")
    if result:
        print(f"Loaded: {result.get('taskCount', '?')} tasks, "
              f"{result.get('resourceCount', '?')} resources")

    # Fetch snapshot and cache it
    snapshot = api_get("/project/snapshot")
    if snapshot:
        p = save_cache_raw("snapshot", snapshot)
        print(f"Snapshot saved to {p}")

    # Also save a brief summary
    summary = api_get("/project/summary")
    if summary:
        save_cache("summary", summary)
        _print_summary(summary)


def cmd_refresh(args):
    """Reload project data from API and update cached snapshot."""
    ensure_loaded()
    print("Refreshing project data...")
    result = api_post("/project/refresh")
    if result:
        print(f"Refreshed: {result.get('taskCount', '?')} tasks")

    snapshot = api_get("/project/snapshot")
    if snapshot:
        p = save_cache_raw("snapshot", snapshot)
        print(f"Snapshot updated at {p}")

    summary = api_get("/project/summary")
    if summary:
        save_cache("summary", summary)
        _print_summary(summary)


def cmd_summary(args):
    """Print project summary stats."""
    ensure_loaded()
    summary = api_get("/project/summary")
    if summary:
        save_cache("summary", summary)
        _print_summary(summary)


def cmd_show(args):
    """Show all tasks in the current snapshot."""
    ensure_loaded()
    params = {}
    if hasattr(args, 'fields') and args.fields:
        params["fields"] = args.fields

    result = api_get("/tasks", params=params if params else None)
    if not result:
        print("No tasks loaded.")
        return

    tasks = result.get("tasks", []) if isinstance(result, dict) else result

    if args.format == "json":
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
        return

    if not tasks:
        print("No tasks loaded.")
        return

    headers = ["#", "Outline", "Name", "Status", "% Done", "Start", "Finish", "Assigned"]
    rows = []
    for t in tasks:
        assigned = t.get("assignedTo", "")
        if isinstance(assigned, list):
            assigned = ", ".join(assigned) if assigned else ""
        rows.append([
            str(t.get("index", "")),
            t.get("outlineNumber", ""),
            t.get("name", ""),
            t.get("status", ""),
            str(t.get("percentComplete", "")),
            t.get("start", "") or "",
            t.get("finish", "") or "",
            str(assigned),
        ])
    print(format_output(headers, rows, args.format))


def cmd_diff(args):
    """Compare the current project state with a cached snapshot."""
    ensure_loaded()

    # Load the reference snapshot
    ref_path = args.file
    if ref_path:
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                ref = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: Cannot read {ref_path}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        ref = load_cache("snapshot")
        if not ref:
            print("No cached snapshot found. Run 'save' first.", file=sys.stderr)
            sys.exit(1)

    # Get current snapshot from server
    current = api_get("/project/snapshot")
    if not current:
        print("ERROR: Could not fetch current snapshot.", file=sys.stderr)
        sys.exit(1)

    # Extract task lists (handle wrapped/raw formats)
    ref_tasks = ref.get("tasks", ref.get("data", {}).get("tasks", []))
    cur_tasks = current.get("tasks", [])

    ref_by_id = {t["id"]: t for t in ref_tasks if "id" in t}
    cur_by_id = {t["id"]: t for t in cur_tasks if "id" in t}

    added = [cur_by_id[tid] for tid in cur_by_id if tid not in ref_by_id]
    removed = [ref_by_id[tid] for tid in ref_by_id if tid not in cur_by_id]
    modified = []

    compare_fields = ["name", "percentComplete", "status", "start", "finish",
                       "priority", "duration", "bucketId", "parentId"]

    for tid in cur_by_id:
        if tid in ref_by_id:
            changes = {}
            for fld in compare_fields:
                old = ref_by_id[tid].get(fld)
                new = cur_by_id[tid].get(fld)
                if str(old) != str(new):
                    changes[fld] = {"from": old, "to": new}
            if changes:
                modified.append({
                    "name": cur_by_id[tid].get("name", tid),
                    "changes": changes,
                })

    print(f"\n=== Snapshot Diff ===")
    print(f"Added:    {len(added)} tasks")
    print(f"Removed:  {len(removed)} tasks")
    print(f"Modified: {len(modified)} tasks\n")

    if added:
        print("--- Added ---")
        for t in added:
            print(f"  + {t.get('name', '?')}")

    if removed:
        print("--- Removed ---")
        for t in removed:
            print(f"  - {t.get('name', '?')}")

    if modified:
        print("--- Modified ---")
        for m in modified:
            print(f"  ~ {m['name']}:")
            for fld, ch in m["changes"].items():
                print(f"      {fld}: {ch['from']} → {ch['to']}")


def _print_summary(summary: dict):
    """Display project summary."""
    tasks_info = summary.get("tasks", {})
    print(f"\n{'─' * 50}")
    print(f"  Project:    {summary.get('projectName', '?')}")
    print(f"  Tasks:      {tasks_info.get('total', summary.get('totalTasks', '?'))}  "
          f"(summary: {tasks_info.get('summaryTasks', summary.get('summaryTasks', '?'))}, "
          f"milestones: {tasks_info.get('milestones', summary.get('milestones', '?'))})")
    print(f"  Resources:  {summary.get('resources', '?')}")
    print(f"  Buckets:    {summary.get('buckets', '?')}")

    # Status breakdown may be nested under tasks or flat
    status = summary.get("statusBreakdown", {})
    if not status and tasks_info:
        parts = []
        for key in ("notStarted", "inProgress", "completed"):
            if key in tasks_info:
                parts.append(f"{key}: {tasks_info[key]}")
        if parts:
            status = True  # signal we printed
            print(f"  Status:     {', '.join(parts)}")
    if isinstance(status, dict) and status:
        parts = [f"{k}: {v}" for k, v in status.items()]
        print(f"  Status:     {', '.join(parts)}")

    overdue = tasks_info.get("overdue", summary.get("overdue"))
    if overdue:
        print(f"  Overdue:    {overdue} tasks")
    risk_count = summary.get("risks", summary.get("riskCount"))
    if risk_count:
        print(f"  Risks:      {risk_count}")
    if summary.get("lastRefreshed") or summary.get("loadedAt"):
        print(f"  Refreshed:  {summary.get('lastRefreshed', summary.get('loadedAt'))}")
    print(f"{'─' * 50}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_snapshot",
        description="Save, refresh, and browse OnePlanner project snapshots.",
    )
    sub = parser.add_subparsers(dest="command")

    p_save = sub.add_parser("save", help="Authenticate, load, and cache a snapshot")
    p_save.add_argument("--url", help="Planner URL to open")

    sub.add_parser("refresh", help="Reload data from API")
    sub.add_parser("summary", help="Print project stats")

    p_show = sub.add_parser("show", help="Show all tasks")
    p_show.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    p_show.add_argument("--fields", help="Comma-separated field list")

    p_diff = sub.add_parser("diff", help="Compare current vs cached snapshot")
    p_diff.add_argument("file", nargs="?", help="Path to reference snapshot JSON")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "save": cmd_save,
        "refresh": cmd_refresh,
        "summary": cmd_summary,
        "show": cmd_show,
        "diff": cmd_diff,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
