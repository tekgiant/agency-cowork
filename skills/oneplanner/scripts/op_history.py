"""
op_history — View task edit history and find stale/recently-modified tasks.

Usage:
    python -m scripts.op_history show <task> [--limit N]       # Full edit history for a task
    python -m scripts.op_history recent [--limit N] [--format F]  # Recently modified tasks
    python -m scripts.op_history stale [--days N] [--format F]    # Tasks not modified in N days
    python -m scripts.op_history batch <task1> [task2 ...] [--limit N]  # History for multiple tasks
"""

import argparse
import json
import sys

from ._api import api_get, api_post, ensure_loaded, format_output


def _encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_show(args):
    """Show edit history for a single task."""
    ensure_loaded()
    params = {}
    if args.limit:
        params["limit"] = str(args.limit)

    result = api_get(f"/tasks/{_encode(args.task)}/history", params=params)
    if not result:
        print(f"No history for '{args.task}'.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    entries = result if isinstance(result, list) else result.get("history", [])
    if not entries:
        print(f"No history entries for '{args.task}'.")
        return

    print(f"\n=== History: {args.task} ===\n")
    for entry in entries:
        ts = entry.get("timestamp", "?")
        user = entry.get("editorName", entry.get("editorAadId", "?"))
        edit_type = entry.get("editType", "?")
        print(f"  [{ts}] {user} — {edit_type}")

        details = entry.get("details", [])
        if isinstance(details, list):
            for d in details:
                field = d.get("field", "?")
                old_val = d.get("oldValue", "")
                new_val = d.get("newValue", "")
                print(f"      {field}: {old_val} → {new_val}")
        elif isinstance(details, dict):
            for field, diff in details.items():
                if isinstance(diff, dict):
                    prev = diff.get("previous", diff.get("from", ""))
                    upd = diff.get("updated", diff.get("to", ""))
                    print(f"      {field}: {prev} → {upd}")
                else:
                    print(f"      {field}: {diff}")
        print()


def cmd_recent(args):
    """Show recently modified tasks across the project."""
    ensure_loaded()
    params = {}
    if args.limit:
        params["limit"] = str(args.limit)

    result = api_get("/tasks/recently-modified", params=params)
    if not result:
        print("No recently modified tasks found.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    tasks = result if isinstance(result, list) else result.get("tasks", [])
    if not tasks:
        print("No recently modified tasks found.")
        return

    headers = ["Task", "Last Modified", "Modified By"]
    rows = []
    for t in tasks:
        rows.append([
            t.get("taskName", t.get("name", "?")),
            t.get("lastModified", "?"),
            t.get("editorName", "?"),
        ])
    print(format_output(headers, rows, args.format))


def cmd_stale(args):
    """Find tasks not modified in the last N days (default: 14)."""
    ensure_loaded()
    days = args.days or 14

    # Get recently-modified tasks (large limit to get all)
    result = api_get("/tasks/recently-modified", params={"limit": "500"})
    all_tasks = api_get("/tasks")

    if not all_tasks:
        print("No tasks loaded.")
        return

    # Build set of recently-modified task names
    recent = result if isinstance(result, list) else (result or {}).get("tasks", [])
    recent_names = set()
    for t in recent:
        name = t.get("taskName", t.get("name", ""))
        if name:
            recent_names.add(name)

    # Tasks with no recent history entry are assumed stale
    task_list = all_tasks if isinstance(all_tasks, list) else all_tasks.get("tasks", [])
    stale = [t for t in task_list
             if t.get("name") not in recent_names
             and not t.get("summary", False)]

    if not stale:
        print(f"No stale tasks (all modified within view window).")
        return

    if args.format == "json":
        print(json.dumps(stale, indent=2, ensure_ascii=False))
        return

    headers = ["#", "Name", "Status", "Assigned", "Finish"]
    rows = []
    for t in stale:
        assigned = t.get("assignedTo", "")
        if isinstance(assigned, list):
            assigned = ", ".join(assigned) if assigned else ""
        rows.append([
            str(t.get("index", "")),
            t.get("name", "?"),
            t.get("status", ""),
            str(assigned),
            t.get("finish", "") or "",
        ])
    print(format_output(headers, rows, args.format))
    print(f"\n{len(stale)} tasks with no recent modifications.")


def cmd_batch(args):
    """Fetch history for multiple tasks at once."""
    ensure_loaded()
    body = {
        "tasks": args.tasks,
    }
    if args.limit:
        body["limit"] = args.limit

    result = api_post("/tasks/history/batch", body=body)
    if not result:
        print("No history data returned.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Display grouped by task — results is a dict keyed by task name
    results_data = result.get("results", result) if isinstance(result, dict) else result
    if isinstance(results_data, dict):
        for task_name, info in results_data.items():
            if isinstance(info, dict) and info.get("error"):
                print(f"\n=== {task_name}: {info['error']} ===")
                continue
            last_mod = info.get("lastModified", "?")
            editor = info.get("editorName", "?")
            edit_type = info.get("editType", "?")
            print(f"\n=== {task_name} ===")
            if last_mod:
                print(f"  Last modified: {last_mod} by {editor} ({edit_type})")
                changes = info.get("changes", [])
                for ch in changes:
                    if isinstance(ch, dict):
                        print(f"    {ch.get('field', '?')}: {ch.get('oldValue', '')} → {ch.get('newValue', '')}")
            else:
                print("  No history recorded.")
    elif isinstance(results_data, list):
        for item in results_data:
            name = item.get("taskName", item.get("name", "?"))
            entries = item.get("history", [])
            print(f"\n=== {name} ({len(entries)} entries) ===")
            for entry in entries[:5]:
                ts = entry.get("timestamp", "?")
                user = entry.get("editorName", "?")
                edit_type = entry.get("editType", "?")
                print(f"  [{ts}] {user} — {edit_type}")
            if len(entries) > 5:
                print(f"  ... and {len(entries) - 5} more")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_history",
        description="View task edit history in OnePlanner.",
    )
    sub = parser.add_subparsers(dest="command")

    p_show = sub.add_parser("show", help="Show edit history for a task")
    p_show.add_argument("task", help="Task name, row number, or outline number")
    p_show.add_argument("--limit", type=int, help="Max entries to show")
    p_show.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_recent = sub.add_parser("recent", help="Recently modified tasks")
    p_recent.add_argument("--limit", type=int, default=20, help="Max tasks to show")
    p_recent.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_stale = sub.add_parser("stale", help="Tasks not recently modified")
    p_stale.add_argument("--days", type=int, default=14, help="Days threshold")
    p_stale.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_batch = sub.add_parser("batch", help="History for multiple tasks")
    p_batch.add_argument("tasks", nargs="+", help="Task names/indices")
    p_batch.add_argument("--limit", type=int, help="Max entries per task")
    p_batch.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {"show": cmd_show, "recent": cmd_recent, "stale": cmd_stale, "batch": cmd_batch}
    commands[args.command](args)


if __name__ == "__main__":
    main()
