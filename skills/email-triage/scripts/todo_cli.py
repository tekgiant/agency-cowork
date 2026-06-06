"""Todo CLI — interactive task management for email triage.

Commands:
    list [--folder NAME] [--all]  Show tasks (numbered)
    add SUBJECT [--folder NAME]   Create a task
    complete NUMBER               Mark task done by list number
    open NUMBER                   Open linked email in browser
    sync                          Run triage → Todo sync
    stats                         Show task statistics
    folders                       List all task folders
    cleanup [--days N]            Remove completed tasks older than N days

Usage:
    python -m scripts.todo_cli list
    python -m scripts.todo_cli add "Follow up on Maia 300 PO" --folder "Email Triage"
    python -m scripts.todo_cli complete 3
"""

import argparse
import re
import sys
import webbrowser

# Ensure parent dir is on path for imports
sys.path.insert(0, ".")

from scripts.todo_client import TodoClient

DEFAULT_FOLDER = "Email Triage"

# Cache for numbered task listing (used by complete/open commands)
_last_listed_tasks = []


def _get_client() -> TodoClient:
    return TodoClient()


def _find_folder(client: TodoClient, name: str):
    folders = client.list_folders()
    for f in folders:
        if f["Name"].lower() == name.lower():
            return f
    return None


def cmd_folders(args):
    """List all task folders."""
    client = _get_client()
    folders = client.list_folders()
    print(f"Task Folders ({len(folders)}):")
    for i, f in enumerate(folders, 1):
        print(f"  {i}. {f['Name']}")


def cmd_list(args):
    """List tasks in a folder."""
    client = _get_client()

    if args.all:
        tasks = client.list_tasks(top=args.top or 30)
        header = "All Tasks"
    else:
        folder_name = args.folder or DEFAULT_FOLDER
        folder = _find_folder(client, folder_name)
        if not folder:
            print(f"Folder '{folder_name}' not found. Available folders:")
            for f in client.list_folders():
                print(f"  - {f['Name']}")
            return
        tasks = client.list_tasks(folder_id=folder["Id"], top=args.top or 30)
        header = f"Tasks in '{folder_name}'"

    if not tasks:
        print(f"{header}: (empty)")
        return

    # Status indicators
    status_icons = {
        "NotStarted": "○",
        "InProgress": "◐",
        "Completed": "●",
        "WaitingOnOthers": "◑",
        "Deferred": "◌",
    }
    importance_icons = {"High": "🔴", "Normal": "", "Low": "🔵"}

    print(f"\n{header} ({len(tasks)}):")
    print(f"{'#':>3}  {'':2} {'':4} {'Subject':<60} {'Due':<12}")
    print(f"{'---':>3}  {'--':2} {'----':4} {'-'*60} {'-'*12}")

    for i, t in enumerate(tasks, 1):
        status_icon = status_icons.get(t.get("Status", "NotStarted"), "?")
        imp_icon = importance_icons.get(t.get("Importance", "Normal"), "")
        subject = t.get("Subject", "(no subject)")[:60]
        due = ""
        due_dt = t.get("DueDateTime", {})
        if due_dt and due_dt.get("DateTime"):
            due = due_dt["DateTime"][:10]

        print(f"{i:>3}  {status_icon:2} {imp_icon:4} {subject:<60} {due:<12}")

    # Save for use by complete/open
    global _last_listed_tasks
    _last_listed_tasks = tasks


def cmd_add(args):
    """Create a new task."""
    client = _get_client()
    folder_name = args.folder or DEFAULT_FOLDER
    folder = client.get_or_create_folder(folder_name)

    task = client.create_task(
        folder_id=folder["Id"],
        subject=args.subject,
        body=args.body,
        importance=args.importance or "Normal",
        due_date=args.due,
    )
    print(f"Created: {task['Subject']}")
    if args.due:
        print(f"  Due: {args.due}")


def cmd_complete(args):
    """Mark a task as completed by number from last list output."""
    client = _get_client()

    # Need to re-list to get task IDs
    folder_name = args.folder or DEFAULT_FOLDER
    folder = _find_folder(client, folder_name)
    if not folder:
        print(f"Folder '{folder_name}' not found.")
        return

    tasks = client.list_tasks(folder_id=folder["Id"], top=50)
    numbers = _parse_numbers(args.numbers, len(tasks))

    completed = 0
    for n in numbers:
        if 1 <= n <= len(tasks):
            task = tasks[n - 1]
            if task.get("Status") != "Completed":
                client.complete_task(task["Id"])
                print(f"  ● {task['Subject']}")
                completed += 1
            else:
                print(f"  (already completed) {task['Subject']}")

    print(f"\n{completed} task(s) completed.")


def cmd_open(args):
    """Open the email linked to a task in the default browser."""
    client = _get_client()

    folder_name = args.folder or DEFAULT_FOLDER
    folder = _find_folder(client, folder_name)
    if not folder:
        print(f"Folder '{folder_name}' not found.")
        return

    tasks = client.list_tasks(folder_id=folder["Id"], top=50)
    n = args.number
    if n < 1 or n > len(tasks):
        print(f"Invalid task number {n}. Range: 1-{len(tasks)}")
        return

    task = tasks[n - 1]
    body = task.get("Body", {}).get("Content", "")

    # Extract Outlook link from body
    url_match = re.search(r"https://outlook\.office365\.com/mail/deeplink/read/[^\s)]+", body)
    if url_match:
        url = url_match.group(0)
        print(f"Opening: {task['Subject']}")
        webbrowser.open(url)
    else:
        print(f"No email link found in task: {task['Subject']}")
        print(f"Body preview: {body[:200]}")


def cmd_stats(args):
    """Show task statistics for a folder."""
    client = _get_client()

    folder_name = args.folder or DEFAULT_FOLDER
    folder = _find_folder(client, folder_name)
    if not folder:
        # Show stats for all folders
        folders = client.list_folders()
        print("Task Statistics:")
        for f in folders:
            stats = client.get_task_stats(f["Id"])
            if stats["total"] > 0:
                print(f"  {f['Name']}: {stats['total']} total "
                      f"({stats['not_started']} pending, {stats['completed']} done)")
        return

    stats = client.get_task_stats(folder["Id"])
    print(f"'{folder_name}' Statistics:")
    print(f"  Total:       {stats['total']}")
    print(f"  Not Started: {stats['not_started']}")
    print(f"  In Progress: {stats['in_progress']}")
    print(f"  Completed:   {stats['completed']}")


def cmd_cleanup(args):
    """Remove completed tasks older than N days."""
    client = _get_client()
    folder_name = args.folder or DEFAULT_FOLDER
    folder = _find_folder(client, folder_name)
    if not folder:
        print(f"Folder '{folder_name}' not found.")
        return

    days = args.days or 7
    deleted = client.cleanup_completed(folder["Id"], older_than_days=days)
    print(f"Deleted {deleted} completed task(s) older than {days} days.")


def _parse_numbers(spec: str, max_n: int) -> list:
    """Parse number specification: '1,3,5' or '1-5' or 'all'."""
    if spec.lower() == "all":
        return list(range(1, max_n + 1))

    numbers = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            numbers.extend(range(int(start), int(end) + 1))
        else:
            numbers.append(int(part))
    return numbers


def main():
    parser = argparse.ArgumentParser(
        description="Todo CLI — email triage task management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # folders
    sub.add_parser("folders", help="List all task folders")

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--folder", "-f", default=None, help="Folder name")
    p_list.add_argument("--all", "-a", action="store_true", help="All folders")
    p_list.add_argument("--top", "-n", type=int, default=30, help="Max results")

    # add
    p_add = sub.add_parser("add", help="Create a task")
    p_add.add_argument("subject", help="Task title")
    p_add.add_argument("--folder", "-f", default=None, help="Folder name")
    p_add.add_argument("--body", "-b", default=None, help="Task body")
    p_add.add_argument("--importance", "-i", choices=["Low", "Normal", "High"])
    p_add.add_argument("--due", "-d", default=None, help="Due date (YYYY-MM-DD)")

    # complete
    p_complete = sub.add_parser("complete", help="Mark task(s) done")
    p_complete.add_argument("numbers", help="Task number(s): 1,3,5 or 1-5 or all")
    p_complete.add_argument("--folder", "-f", default=None, help="Folder name")

    # open
    p_open = sub.add_parser("open", help="Open email linked to a task")
    p_open.add_argument("number", type=int, help="Task number from list")
    p_open.add_argument("--folder", "-f", default=None, help="Folder name")

    # stats
    p_stats = sub.add_parser("stats", help="Show task statistics")
    p_stats.add_argument("--folder", "-f", default=None, help="Folder name")

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Remove old completed tasks")
    p_cleanup.add_argument("--days", type=int, default=7, help="Days threshold")
    p_cleanup.add_argument("--folder", "-f", default=None, help="Folder name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "folders": cmd_folders,
        "list": cmd_list,
        "add": cmd_add,
        "complete": cmd_complete,
        "open": cmd_open,
        "stats": cmd_stats,
        "cleanup": cmd_cleanup,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
