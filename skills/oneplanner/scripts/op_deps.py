"""
op_deps — Manage task dependencies (predecessor/successor links).

Usage:
    python -m scripts.op_deps list <task>                      # Show deps for a task
    python -m scripts.op_deps add <task> <predecessor> [--type FS|FF|SS|SF] [--lag 2d]
    python -m scripts.op_deps remove <task> <predecessor>
    python -m scripts.op_deps chain <task1> <task2> [task3 ...] [--type FS]
    python -m scripts.op_deps critical-path [--format F]
"""

import argparse
import json
import sys

from ._api import api_get, api_post, api_delete, ensure_loaded, format_output


def _encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_list(args):
    """Show dependencies for a task."""
    ensure_loaded()
    result = api_get(f"/tasks/{_encode(args.task)}/links")
    if not result:
        print(f"No dependencies for '{args.task}'.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    preds = result.get("predecessors", [])
    succs = result.get("successors", [])

    if preds:
        print(f"\nPredecessors of '{args.task}':")
        headers = ["Task", "Type", "Delay (days)"]
        rows = [[p.get("predecessorName", p.get("name", "?")),
                 p.get("linkType", p.get("type", "FS")),
                 str(p.get("delay", 0))] for p in preds]
        print(format_output(headers, rows, args.format))

    if succs:
        print(f"\nSuccessors of '{args.task}':")
        headers = ["Task", "Type", "Delay (days)"]
        rows = [[s.get("successorName", s.get("name", "?")),
                 s.get("linkType", s.get("type", "FS")),
                 str(s.get("delay", 0))] for s in succs]
        print(format_output(headers, rows, args.format))

    if not preds and not succs:
        print(f"No dependencies for '{args.task}'.")


def cmd_add(args):
    """Add a dependency link."""
    ensure_loaded()
    body = {
        "predecessorName": args.predecessor,
        "linkType": args.type,
    }
    if args.lag:
        body["delay"] = args.lag

    result = api_post(f"/tasks/{_encode(args.task)}/link", body=body)
    if result:
        print(f"Added link: {args.predecessor} → {args.task} ({args.type})")


def cmd_remove(args):
    """Remove a dependency link."""
    ensure_loaded()
    result = api_delete(f"/tasks/{_encode(args.task)}/link/{_encode(args.predecessor)}")
    if result:
        print(f"Removed link: {args.predecessor} → {args.task}")


def cmd_chain(args):
    """Create a chain of FS links: task1 → task2 → task3 → ..."""
    ensure_loaded()
    tasks = args.tasks
    if len(tasks) < 2:
        print("Need at least 2 tasks to create a chain.", file=sys.stderr)
        sys.exit(1)

    created = 0
    for i in range(len(tasks) - 1):
        pred = tasks[i]
        succ = tasks[i + 1]
        try:
            api_post(f"/tasks/{_encode(succ)}/link", body={
                "predecessorName": pred,
                "linkType": args.type,
            })
            print(f"  ✓ {pred} → {succ} ({args.type})")
            created += 1
        except SystemExit:
            print(f"  ✗ Failed: {pred} → {succ}")

    print(f"\nChain complete: {created}/{len(tasks) - 1} links created.")


def cmd_critical_path(args):
    """Show the critical path analysis."""
    ensure_loaded()
    result = api_get("/critical-path")
    if not result:
        print("Critical path analysis not available.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    tasks = result.get("tasks", result) if isinstance(result, dict) else result
    if isinstance(tasks, list):
        headers = ["#", "Name", "Start", "Finish", "% Done", "Assigned"]
        rows = []
        for t in tasks:
            assigned = t.get("assignedTo", "")
            if isinstance(assigned, list):
                assigned = ", ".join(assigned) if assigned else ""
            rows.append([
                str(t.get("outlineNumber", "")),
                t.get("name", ""),
                t.get("start", "") or "",
                t.get("finish", "") or "",
                str(t.get("percentComplete", "")),
                str(assigned),
            ])
        print(format_output(headers, rows, args.format))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_deps",
        description="Manage task dependencies in OnePlanner.",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Show dependencies for a task")
    p_list.add_argument("task", help="Task name, row number, or outline number")
    p_list.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_add = sub.add_parser("add", help="Add a dependency link")
    p_add.add_argument("task", help="Successor task")
    p_add.add_argument("predecessor", help="Predecessor task")
    p_add.add_argument("--type", choices=["FS", "FF", "SS", "SF"], default="FS")
    p_add.add_argument("--lag", help="Lag duration (e.g., '2d', '4h')")

    p_rm = sub.add_parser("remove", help="Remove a dependency link")
    p_rm.add_argument("task", help="Successor task")
    p_rm.add_argument("predecessor", help="Predecessor task")

    p_chain = sub.add_parser("chain", help="Chain tasks in FS sequence")
    p_chain.add_argument("tasks", nargs="+", help="Tasks in order")
    p_chain.add_argument("--type", choices=["FS", "FF", "SS", "SF"], default="FS")

    p_cp = sub.add_parser("critical-path", help="Show critical path")
    p_cp.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "list": cmd_list, "add": cmd_add, "remove": cmd_remove,
        "chain": cmd_chain, "critical-path": cmd_critical_path,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
