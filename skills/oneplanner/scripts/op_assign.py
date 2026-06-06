"""
op_assign — Manage resource assignments on tasks.

Usage:
    python -m scripts.op_assign list <task>                 # Show who is assigned
    python -m scripts.op_assign add <task> <resource>       # Assign a person
    python -m scripts.op_assign remove <task> <resource>    # Unassign a person
    python -m scripts.op_assign replace <task> <old> <new>  # Swap one assignee
    python -m scripts.op_assign bulk <resource> <task1> [task2 ...]  # Assign one person to many tasks
    python -m scripts.op_assign resources                   # List available resources
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
    """Show assignments for a specific task."""
    ensure_loaded()
    result = api_get(f"/tasks/{_encode(args.task)}/assignments")
    if not result:
        print(f"No assignments for '{args.task}'.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    assignments = result if isinstance(result, list) else result.get("assignments", [])
    if not assignments:
        print(f"No assignments for '{args.task}'.")
        return

    headers = ["Resource", "Units"]
    rows = [[a.get("resourceName", "?"), str(a.get("units", "100%"))] for a in assignments]
    print(format_output(headers, rows, args.format))


def cmd_add(args):
    """Assign a resource to a task."""
    ensure_loaded()
    result = api_post(f"/tasks/{_encode(args.task)}/assign", body={"resourceName": args.resource})
    if result:
        print(f"Assigned '{args.resource}' to '{args.task}'.")


def cmd_remove(args):
    """Remove a resource assignment from a task."""
    ensure_loaded()
    result = api_delete(f"/tasks/{_encode(args.task)}/assign/{_encode(args.resource)}")
    if result:
        print(f"Removed '{args.resource}' from '{args.task}'.")


def cmd_replace(args):
    """Replace one assignee with another."""
    ensure_loaded()
    # Remove old, then add new
    api_delete(f"/tasks/{_encode(args.task)}/assign/{_encode(args.old)}")
    result = api_post(f"/tasks/{_encode(args.task)}/assign", body={"resourceName": args.new})
    if result:
        print(f"Replaced '{args.old}' with '{args.new}' on '{args.task}'.")


def cmd_bulk(args):
    """Assign one resource to multiple tasks."""
    ensure_loaded()
    successes = 0
    errors = 0
    for task in args.tasks:
        try:
            api_post(f"/tasks/{_encode(task)}/assign", body={"resourceName": args.resource})
            print(f"  ✓ Assigned to '{task}'")
            successes += 1
        except SystemExit:
            print(f"  ✗ Failed for '{task}'")
            errors += 1
    print(f"\nBulk assign complete: {successes} succeeded, {errors} failed.")


def cmd_resources(args):
    """List all available resources in the project."""
    ensure_loaded()
    resources = api_get("/resources")
    if not resources:
        print("No resources found.")
        return

    if args.format == "json":
        print(json.dumps(resources, indent=2, ensure_ascii=False))
        return

    items = resources if isinstance(resources, list) else resources.get("resources", [])
    headers = ["Name", "Type", "Assignments"]
    rows = []
    for r in items:
        rows.append([
            r.get("name", "?"),
            r.get("type", "?"),
            str(r.get("assignmentCount", "")),
        ])
    print(format_output(headers, rows, args.format))


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_assign",
        description="Manage resource assignments on OnePlanner tasks.",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Show assignments for a task")
    p_list.add_argument("task", help="Task name, row number, or outline number")
    p_list.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_add = sub.add_parser("add", help="Assign a resource to a task")
    p_add.add_argument("task", help="Task name/index")
    p_add.add_argument("resource", help="Resource name")

    p_rm = sub.add_parser("remove", help="Remove assignment from task")
    p_rm.add_argument("task", help="Task name/index")
    p_rm.add_argument("resource", help="Resource name")

    p_rep = sub.add_parser("replace", help="Swap one assignee for another")
    p_rep.add_argument("task", help="Task name/index")
    p_rep.add_argument("old", help="Current assignee name")
    p_rep.add_argument("new", help="New assignee name")

    p_bulk = sub.add_parser("bulk", help="Assign one resource to many tasks")
    p_bulk.add_argument("resource", help="Resource name")
    p_bulk.add_argument("tasks", nargs="+", help="Task names/indices")

    p_res = sub.add_parser("resources", help="List available resources")
    p_res.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "list": cmd_list, "add": cmd_add, "remove": cmd_remove,
        "replace": cmd_replace, "bulk": cmd_bulk, "resources": cmd_resources,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
