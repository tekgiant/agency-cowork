"""
op_tasks — Query, create, update, and delete tasks.

Usage:
    python -m scripts.op_tasks list [--status S] [--bucket B] [--assigned A] [--search Q] [--format F]
    python -m scripts.op_tasks get <name_or_index>
    python -m scripts.op_tasks add <name> [--parent P] [--bucket B] [--assign A] [--start D] [--finish D]
    python -m scripts.op_tasks update <name_or_index> --field value [...]
    python -m scripts.op_tasks complete <name_or_index>
    python -m scripts.op_tasks delete <name_or_index> [--yes]
    python -m scripts.op_tasks indent <name_or_index>
    python -m scripts.op_tasks outdent <name_or_index>
    python -m scripts.op_tasks move <name_or_index> --after <target>
    python -m scripts.op_tasks due <days>
    python -m scripts.op_tasks overdue [--format F]
    python -m scripts.op_tasks undo
"""

import argparse
import json
import sys

from ._api import (
    api_get, api_post, api_patch, api_delete,
    ensure_loaded, confirm, format_output,
)


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_list(args):
    """List tasks with optional filters."""
    ensure_loaded()
    params = {}
    if args.status:
        params["status"] = args.status
    if args.bucket:
        params["bucket"] = args.bucket
    if args.assigned:
        params["assignedTo"] = args.assigned
    if args.sprint:
        params["sprint"] = args.sprint
    if args.search:
        params["search"] = args.search
    if args.critical:
        params["critical"] = "true"

    result = api_get("/tasks", params=params)
    if not result:
        print("No tasks found.")
        return

    tasks = result.get("tasks", []) if isinstance(result, dict) else result

    if args.format == "json":
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
        return

    if not tasks:
        print("No tasks found.")
        return

    headers = ["#", "Outline", "Name", "Status", "% Done", "Start", "Finish", "Assigned"]
    rows = []
    for t in tasks:
        rows.append([
            str(t.get("index", "")),
            t.get("outlineNumber", ""),
            _indent_name(t),
            t.get("status", ""),
            str(t.get("percentComplete", "")),
            t.get("start", "") or "",
            t.get("finish", "") or "",
            _fmt_assigned(t),
        ])
    print(format_output(headers, rows, args.format))


def cmd_get(args):
    """Get details for a single task."""
    ensure_loaded()
    task = api_get(f"/tasks/{_encode(args.name_or_index)}")
    if task:
        print(json.dumps(task, indent=2, ensure_ascii=False))


def cmd_add(args):
    """Create a new task."""
    ensure_loaded()
    body = {"name": args.name}
    if args.parent:
        body["parentTask"] = args.parent
    if args.bucket:
        body["bucketName"] = args.bucket
    if args.assign:
        body["assignTo"] = args.assign
    if args.start:
        body["start"] = args.start
    if args.finish:
        body["finish"] = args.finish
    if args.duration:
        body["duration"] = args.duration

    result = api_post("/tasks", body=body)
    if result:
        print(f"Created task: {args.name}")


def cmd_update(args):
    """Update fields on an existing task."""
    ensure_loaded()
    body = {}
    if args.name:
        body["name"] = args.name
    if args.status:
        body["percentComplete"] = args.status  # Server resolves string like "completed" → 100
    if args.priority:
        body["priority"] = args.priority
    if args.start:
        body["start"] = args.start
    if args.finish:
        body["finish"] = args.finish
    if args.duration:
        body["duration"] = args.duration
    if args.bucket:
        body["bucketName"] = args.bucket
    if args.sprint:
        body["sprintName"] = args.sprint
    if args.percent is not None:
        body["percentComplete"] = args.percent
    if args.notes:
        body["notes"] = args.notes

    if not body:
        print("No fields to update. Use --name, --status, --priority, etc.")
        sys.exit(1)

    result = api_patch(f"/tasks/{_encode(args.task)}", body=body)
    if result:
        print(f"Updated: {result.get('taskName', args.task)}")


def cmd_complete(args):
    """Mark a task as 100% complete."""
    ensure_loaded()
    result = api_patch(f"/tasks/{_encode(args.name_or_index)}", body={"percentComplete": "completed"})
    if result:
        print(f"Completed: {result.get('taskName', args.name_or_index)}")


def cmd_delete(args):
    """Delete a task."""
    ensure_loaded()
    if not args.yes:
        task = api_get(f"/tasks/{_encode(args.name_or_index)}")
        if task and not confirm(f"Delete task '{task.get('name', args.name_or_index)}'?"):
            print("Cancelled.")
            return

    result = api_delete(f"/tasks/{_encode(args.name_or_index)}")
    if result:
        print(f"Deleted: {args.name_or_index}")


def cmd_indent(args):
    """Indent a task (make it a child of the task above)."""
    ensure_loaded()
    result = api_post(f"/tasks/{_encode(args.name_or_index)}/indent")
    if result:
        print(f"Indented: {result.get('taskName', args.name_or_index)}")


def cmd_outdent(args):
    """Outdent a task (move it up one level in hierarchy)."""
    ensure_loaded()
    result = api_post(f"/tasks/{_encode(args.name_or_index)}/outdent")
    if result:
        print(f"Outdented: {result.get('taskName', args.name_or_index)}")


def cmd_move(args):
    """Reorder a task to after another task."""
    ensure_loaded()
    result = api_post("/tasks/reorder", body={
        "task": args.name_or_index,
        "afterTask": args.after,
    })
    if result:
        print(f"Moved: {args.name_or_index} → after {args.after}")


def cmd_due(args):
    """List tasks due in the next N days."""
    ensure_loaded()
    result = api_get(f"/tasks/due", params={"days": str(args.days)})
    if not result:
        print(f"No tasks due in the next {args.days} days.")
        return

    tasks = result.get("tasks", []) if isinstance(result, dict) else result

    if args.format == "json":
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
        return

    if not tasks:
        print(f"No tasks due in the next {args.days} days.")
        return

    headers = ["#", "Name", "Finish", "Status", "Assigned"]
    rows = []
    for t in tasks:
        rows.append([
            str(t.get("index", "")),
            t.get("name", ""),
            t.get("finish", "") or "",
            t.get("status", ""),
            _fmt_assigned(t),
        ])
    print(format_output(headers, rows, args.format))


def cmd_overdue(args):
    """List overdue tasks."""
    ensure_loaded()
    result = api_get("/tasks/overdue")
    if not result:
        print("No overdue tasks — nice!")
        return

    tasks = result.get("tasks", []) if isinstance(result, dict) else result

    if args.format == "json":
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
        return

    if not tasks:
        print("No overdue tasks — nice!")
        return

    headers = ["#", "Name", "Finish", "Status", "Assigned"]
    rows = []
    for t in tasks:
        rows.append([
            str(t.get("index", "")),
            t.get("name", ""),
            t.get("finish", "") or "",
            t.get("status", ""),
            _fmt_assigned(t),
        ])
    print(format_output(headers, rows, args.format))


def cmd_undo(args):
    """Undo the last mutation."""
    ensure_loaded()
    result = api_post("/undo")
    if result:
        print("Undo successful.")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _encode(name_or_index: str) -> str:
    """URL-encode a task name/index for path segments."""
    import urllib.parse
    return urllib.parse.quote(str(name_or_index), safe="")


def _indent_name(task: dict) -> str:
    """Indent task name by outline level."""
    level = task.get("outlineLevel", 1)
    prefix = "  " * max(0, level - 1)
    is_summary = task.get("summary", False)
    marker = "▸ " if is_summary else "  "
    return f"{prefix}{marker}{task.get('name', '?')}"


def _fmt_assigned(task: dict) -> str:
    """Format the assignedTo field (may be a list or string)."""
    assigned = task.get("assignedTo", "")
    if isinstance(assigned, list):
        return ", ".join(assigned) if assigned else ""
    return str(assigned) if assigned else ""


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_tasks",
        description="Query, create, update, and delete OnePlanner tasks.",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="List tasks with optional filters")
    p_list.add_argument("--status", help="Filter by status (e.g., 'In Progress')")
    p_list.add_argument("--bucket", help="Filter by bucket name")
    p_list.add_argument("--assigned", help="Filter by assignee name")
    p_list.add_argument("--sprint", help="Filter by sprint name")
    p_list.add_argument("--search", help="Free text search")
    p_list.add_argument("--critical", action="store_true", help="Only critical path tasks")
    p_list.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    # get
    p_get = sub.add_parser("get", help="Get details for a single task")
    p_get.add_argument("name_or_index", help="Task name, row number, or outline number")

    # add
    p_add = sub.add_parser("add", help="Create a new task")
    p_add.add_argument("name", help="Task name")
    p_add.add_argument("--parent", help="Parent task name for indentation")
    p_add.add_argument("--bucket", help="Bucket name")
    p_add.add_argument("--assign", help="Resource name to assign")
    p_add.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_add.add_argument("--finish", help="Finish date (YYYY-MM-DD)")
    p_add.add_argument("--duration", help="Duration (e.g., '5d', '4h')")

    # update
    p_upd = sub.add_parser("update", help="Update task fields")
    p_upd.add_argument("task", help="Task name, row number, or outline number")
    p_upd.add_argument("--name", help="New task name")
    p_upd.add_argument("--status", help="Status (not started, in progress, completed)")
    p_upd.add_argument("--priority", help="Priority (urgent, high, medium, low)")
    p_upd.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_upd.add_argument("--finish", help="Finish date (YYYY-MM-DD)")
    p_upd.add_argument("--duration", help="Duration (e.g., '5d')")
    p_upd.add_argument("--bucket", help="Bucket name")
    p_upd.add_argument("--sprint", help="Sprint name")
    p_upd.add_argument("--percent", type=int, help="Percent complete (0-100)")
    p_upd.add_argument("--notes", help="Task notes (plain text)")

    # complete
    p_comp = sub.add_parser("complete", help="Mark a task as complete")
    p_comp.add_argument("name_or_index", help="Task name, row number, or outline number")

    # delete
    p_del = sub.add_parser("delete", help="Delete a task")
    p_del.add_argument("name_or_index", help="Task name, row number, or outline number")
    p_del.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    # indent / outdent
    p_indent = sub.add_parser("indent", help="Indent a task")
    p_indent.add_argument("name_or_index")
    p_outdent = sub.add_parser("outdent", help="Outdent a task")
    p_outdent.add_argument("name_or_index")

    # move
    p_move = sub.add_parser("move", help="Reorder task position")
    p_move.add_argument("name_or_index", help="Task to move")
    p_move.add_argument("--after", required=True, help="Place after this task")

    # due / overdue
    p_due = sub.add_parser("due", help="Tasks due in N days")
    p_due.add_argument("days", type=int, help="Number of days")
    p_due.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_over = sub.add_parser("overdue", help="List overdue tasks")
    p_over.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    # undo
    sub.add_parser("undo", help="Undo the last mutation")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "list": cmd_list, "get": cmd_get, "add": cmd_add, "update": cmd_update,
        "complete": cmd_complete, "delete": cmd_delete,
        "indent": cmd_indent, "outdent": cmd_outdent, "move": cmd_move,
        "due": cmd_due, "overdue": cmd_overdue, "undo": cmd_undo,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
