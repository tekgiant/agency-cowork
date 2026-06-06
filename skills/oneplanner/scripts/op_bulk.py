"""
op_bulk — Bulk import, export, and batch-update tasks.

Usage:
    python -m scripts.op_bulk export [--format csv|json] [--output FILE]
    python -m scripts.op_bulk import <file> [--dry-run]
    python -m scripts.op_bulk update --filter <key=value> --set <key=value> [--dry-run]
    python -m scripts.op_bulk delete --filter <key=value> [--dry-run] [--yes]
"""

import argparse
import csv
import io
import json
import sys

from ._api import api_get, api_post, api_patch, api_delete, ensure_loaded, confirm


def _encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_export(args):
    """Export all tasks to CSV or JSON."""
    ensure_loaded()
    tasks = api_get("/tasks")
    if not tasks:
        print("No tasks to export.")
        return

    task_list = tasks if isinstance(tasks, list) else tasks.get("tasks", [])

    if args.format == "json":
        output = json.dumps(task_list, indent=2, ensure_ascii=False)
    else:
        # CSV export
        fields = ["index", "outlineNumber", "name", "status", "percentComplete",
                   "priority", "start", "finish", "durationDays", "assignedTo",
                   "bucketName", "sprintName", "summary", "milestone"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in task_list:
            row = {f: t.get(f, "") for f in fields}
            # Convert assignedTo list to comma-separated string for CSV
            if isinstance(row.get("assignedTo"), list):
                row["assignedTo"] = ", ".join(row["assignedTo"])
            writer.writerow(row)
        output = buf.getvalue()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Exported {len(task_list)} tasks to {args.output}")
    else:
        print(output)


def cmd_import(args):
    """Import tasks from a CSV or JSON file."""
    ensure_loaded()

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"ERROR: Cannot read {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    # Detect format
    tasks_to_add = []
    if args.file.endswith(".json"):
        data = json.loads(content)
        tasks_to_add = data if isinstance(data, list) else data.get("tasks", [])
    else:
        # CSV
        reader = csv.DictReader(io.StringIO(content))
        tasks_to_add = [row for row in reader]

    if not tasks_to_add:
        print("No tasks found in file.")
        return

    print(f"Found {len(tasks_to_add)} tasks to import.")

    if args.dry_run:
        print("\n[DRY RUN] Would create:")
        for t in tasks_to_add:
            print(f"  + {t.get('name', '?')}")
        return

    if not confirm(f"Create {len(tasks_to_add)} tasks?"):
        print("Cancelled.")
        return

    created = 0
    errors = 0
    for t in tasks_to_add:
        body = {"name": t.get("name", "Unnamed")}

        # Map optional fields
        if t.get("bucket"):
            body["bucket"] = t["bucket"]
        if t.get("start"):
            body["start"] = t["start"]
        if t.get("finish"):
            body["finish"] = t["finish"]
        if t.get("duration"):
            body["duration"] = t["duration"]
        if t.get("assignedTo"):
            body["assignTo"] = t["assignedTo"]
        if t.get("parent"):
            body["parent"] = t["parent"]

        try:
            api_post("/tasks", body=body)
            print(f"  ✓ {body['name']}")
            created += 1
        except SystemExit:
            print(f"  ✗ {body['name']}")
            errors += 1

    print(f"\nImport complete: {created} created, {errors} failed.")

    # Refresh to pick up new tasks
    if created > 0:
        print("Refreshing project data...")
        api_post("/project/refresh")


def cmd_update(args):
    """Batch-update tasks matching a filter."""
    ensure_loaded()
    tasks = api_get("/tasks")
    if not tasks:
        print("No tasks loaded.")
        return

    task_list = tasks if isinstance(tasks, list) else tasks.get("tasks", [])

    # Parse filter (e.g., "status=In Progress")
    filter_key, filter_val = _parse_kv(args.filter)
    set_key, set_val = _parse_kv(args.set)

    # Find matching tasks
    matches = []
    for t in task_list:
        val = str(t.get(filter_key, ""))
        if val.lower() == filter_val.lower():
            matches.append(t)

    if not matches:
        print(f"No tasks match filter: {filter_key}={filter_val}")
        return

    print(f"Found {len(matches)} tasks matching '{filter_key}={filter_val}'.")
    print(f"Will set: {set_key}={set_val}")

    if args.dry_run:
        print("\n[DRY RUN] Would update:")
        for t in matches:
            print(f"  ~ {t.get('name', '?')}")
        return

    if not confirm(f"Update {len(matches)} tasks?"):
        print("Cancelled.")
        return

    updated = 0
    errors = 0
    for t in matches:
        name = t.get("name", "")
        if not name:
            continue
        try:
            api_patch(f"/tasks/{_encode(name)}", body={set_key: set_val})
            print(f"  ✓ {name}")
            updated += 1
        except SystemExit:
            print(f"  ✗ {name}")
            errors += 1

    print(f"\nBatch update complete: {updated} updated, {errors} failed.")
    if updated > 0:
        api_post("/project/refresh")


def cmd_delete(args):
    """Batch-delete tasks matching a filter."""
    ensure_loaded()
    tasks = api_get("/tasks")
    if not tasks:
        print("No tasks loaded.")
        return

    task_list = tasks if isinstance(tasks, list) else tasks.get("tasks", [])

    filter_key, filter_val = _parse_kv(args.filter)
    matches = [t for t in task_list
               if str(t.get(filter_key, "")).lower() == filter_val.lower()
               and not t.get("summary", False)]

    if not matches:
        print(f"No tasks match filter: {filter_key}={filter_val}")
        return

    print(f"Found {len(matches)} tasks matching '{filter_key}={filter_val}'.")

    if args.dry_run:
        print("\n[DRY RUN] Would delete:")
        for t in matches:
            print(f"  - {t.get('name', '?')}")
        return

    if not args.yes and not confirm(f"DELETE {len(matches)} tasks? This cannot be undone!"):
        print("Cancelled.")
        return

    deleted = 0
    errors = 0
    for t in matches:
        name = t.get("name", "")
        if not name:
            continue
        try:
            api_delete(f"/tasks/{_encode(name)}")
            print(f"  ✓ {name}")
            deleted += 1
        except SystemExit:
            print(f"  ✗ {name}")
            errors += 1

    print(f"\nBatch delete complete: {deleted} deleted, {errors} failed.")
    if deleted > 0:
        api_post("/project/refresh")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _parse_kv(s: str) -> tuple[str, str]:
    """Parse 'key=value' string."""
    if "=" not in s:
        print(f"ERROR: Expected 'key=value' format, got '{s}'", file=sys.stderr)
        sys.exit(1)
    key, val = s.split("=", 1)
    return key.strip(), val.strip()


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_bulk",
        description="Bulk import, export, and batch operations for OnePlanner tasks.",
    )
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export", help="Export tasks to CSV or JSON")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.add_argument("--output", "-o", help="Output file path")

    p_import = sub.add_parser("import", help="Import tasks from CSV or JSON")
    p_import.add_argument("file", help="Path to CSV or JSON file")
    p_import.add_argument("--dry-run", action="store_true", help="Preview without creating")

    p_update = sub.add_parser("update", help="Batch-update tasks matching a filter")
    p_update.add_argument("--filter", required=True, help="Filter: key=value")
    p_update.add_argument("--set", required=True, help="Update: key=value")
    p_update.add_argument("--dry-run", action="store_true")

    p_delete = sub.add_parser("delete", help="Batch-delete tasks matching a filter")
    p_delete.add_argument("--filter", required=True, help="Filter: key=value")
    p_delete.add_argument("--dry-run", action="store_true")
    p_delete.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {"export": cmd_export, "import": cmd_import,
                "update": cmd_update, "delete": cmd_delete}
    commands[args.command](args)


if __name__ == "__main__":
    main()
