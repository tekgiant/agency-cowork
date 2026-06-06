"""
op_report — Generate summary reports for OnePlanner projects.

Usage:
    python -m scripts.op_report status [--format F]       # Overall project status report
    python -m scripts.op_report workload [--format F]     # Resource workload breakdown
    python -m scripts.op_report overdue [--format F]      # Overdue task report with assignees
    python -m scripts.op_report milestones [--format F]   # Upcoming milestones
    python -m scripts.op_report weekly [--format F]       # Weekly status summary
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from ._api import (
    api_get, ensure_loaded, format_output, save_cache,
    format_markdown_table,
)


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_status(args):
    """Generate an overall project status report."""
    ensure_loaded()
    summary = api_get("/project/summary")
    tasks = api_get("/tasks")
    overdue = api_get("/tasks/overdue")

    if args.format == "json":
        print(json.dumps({
            "summary": summary,
            "overdueCount": len(overdue) if overdue else 0,
            "overdue": overdue,
        }, indent=2, ensure_ascii=False))
        return

    task_list = tasks if isinstance(tasks, list) else (tasks or {}).get("tasks", [])
    overdue_list = overdue if isinstance(overdue, list) else (overdue or {}).get("tasks", [])

    # Status breakdown
    by_status = {}
    for t in task_list:
        if not t.get("summary", False):
            s = t.get("status", "Unknown")
            by_status[s] = by_status.get(s, 0) + 1

    total = len([t for t in task_list if not t.get("summary", False)])

    report = []
    report.append("# Project Status Report")
    report.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    report.append(f"Project: {summary.get('projectName', '?')}" if summary else "")
    report.append("")
    report.append("## Summary")
    report.append(f"- Total tasks: {total}")
    for s, count in sorted(by_status.items()):
        pct = round(count / total * 100) if total else 0
        report.append(f"- {s}: {count} ({pct}%)")
    report.append(f"- Overdue: {len(overdue_list)}")

    if overdue_list:
        report.append("")
        report.append("## Overdue Tasks")
        headers = ["Task", "Due", "Assigned"]
        rows = [[
            t.get("name", "?"),
            t.get("finish", "?") or "",
            ", ".join(t["assignedTo"]) if isinstance(t.get("assignedTo"), list) else str(t.get("assignedTo", "")),
        ] for t in overdue_list]
        report.append(format_markdown_table(headers, rows))

    output = "\n".join(report)
    print(output)

    # Cache the report
    save_cache("report_status", {"report": output, "summary": summary})


def cmd_workload(args):
    """Show resource workload breakdown."""
    ensure_loaded()
    tasks = api_get("/tasks")
    resources = api_get("/resources")

    if not tasks:
        print("No tasks loaded.")
        return

    task_list = tasks if isinstance(tasks, list) else tasks.get("tasks", [])

    # Build workload map
    workload = {}  # name → {total, notStarted, inProgress, completed}
    for t in task_list:
        if t.get("summary", False):
            continue
        assigned = t.get("assignedTo", "")
        if isinstance(assigned, list):
            names = [n.strip() for n in assigned if n.strip()]
        elif isinstance(assigned, str) and assigned:
            names = [n.strip() for n in assigned.split(",") if n.strip()]
        else:
            names = []
        if not names:
            names = ["(Unassigned)"]
        status = t.get("status", "Not Started")
        for name in names:
            if name not in workload:
                workload[name] = {"total": 0, "Not Started": 0, "In Progress": 0, "Completed": 0}
            workload[name]["total"] += 1
            if status in workload[name]:
                workload[name][status] += 1

    if args.format == "json":
        print(json.dumps(workload, indent=2, ensure_ascii=False))
        return

    headers = ["Resource", "Total", "Not Started", "In Progress", "Completed", "% Done"]
    rows = []
    for name in sorted(workload.keys()):
        w = workload[name]
        pct = round(w["Completed"] / w["total"] * 100) if w["total"] else 0
        rows.append([
            name,
            str(w["total"]),
            str(w["Not Started"]),
            str(w["In Progress"]),
            str(w["Completed"]),
            f"{pct}%",
        ])
    print(format_output(headers, rows, args.format))


def cmd_overdue(args):
    """Generate a detailed overdue report with assignment info."""
    ensure_loaded()
    overdue = api_get("/tasks/overdue")
    if not overdue:
        print("No overdue tasks!")
        return

    overdue_list = overdue if isinstance(overdue, list) else overdue.get("tasks", [])

    if args.format == "json":
        print(json.dumps(overdue_list, indent=2, ensure_ascii=False))
        return

    # Group by assignee
    by_owner = {}
    for t in overdue_list:
        assigned = t.get("assignedTo", "")
        if isinstance(assigned, list):
            owner = ", ".join(assigned) if assigned else "(Unassigned)"
        else:
            owner = str(assigned) if assigned else "(Unassigned)"
        if owner not in by_owner:
            by_owner[owner] = []
        by_owner[owner].append(t)

    print(f"\n=== Overdue Report ({len(overdue_list)} tasks) ===\n")
    for owner, items in sorted(by_owner.items()):
        print(f"  {owner} ({len(items)} tasks):")
        for t in items:
            print(f"    - {t.get('name', '?')} (due: {t.get('finish', '?') or '?'})")
        print()


def cmd_milestones(args):
    """Show upcoming milestones."""
    ensure_loaded()
    tasks = api_get("/tasks")
    if not tasks:
        print("No tasks loaded.")
        return

    task_list = tasks if isinstance(tasks, list) else tasks.get("tasks", [])

    # Filter to milestones (flagged or zero duration)
    milestones = [t for t in task_list
                  if t.get("milestone", False)
                  or t.get("durationDays", None) == 0]

    if not milestones:
        print("No milestones found.")
        return

    if args.format == "json":
        print(json.dumps(milestones, indent=2, ensure_ascii=False))
        return

    headers = ["#", "Name", "Date", "Status", "Assigned"]
    rows = []
    for t in milestones:
        assigned = t.get("assignedTo", "")
        if isinstance(assigned, list):
            assigned = ", ".join(assigned) if assigned else ""
        rows.append([
            str(t.get("index", "")),
            t.get("name", "?"),
            t.get("finish", t.get("start", "?")) or "",
            t.get("status", ""),
            str(assigned),
        ])
    print(format_output(headers, rows, args.format))


def cmd_weekly(args):
    """Generate a weekly status summary (markdown)."""
    ensure_loaded()
    summary = api_get("/project/summary")
    tasks = api_get("/tasks")
    overdue = api_get("/tasks/overdue")
    recent = api_get("/tasks/recently-modified", params={"limit": "10"})

    task_list = tasks if isinstance(tasks, list) else (tasks or {}).get("tasks", [])
    overdue_list = overdue if isinstance(overdue, list) else (overdue or {}).get("tasks", [])
    recent_list = recent if isinstance(recent, list) else (recent or {}).get("tasks", [])

    total_leaf = len([t for t in task_list if not t.get("summary", False)])
    completed = len([t for t in task_list
                     if not t.get("summary", False)
                     and t.get("status") == "Completed"])
    pct = round(completed / total_leaf * 100) if total_leaf else 0

    report = []
    report.append(f"# Weekly Status — {summary.get('projectName', 'Project') if summary else 'Project'}")
    report.append(f"_Week of {datetime.now(timezone.utc).strftime('%B %d, %Y')}_\n")

    report.append(f"## Overall Progress: {pct}%")
    report.append(f"- **{completed}** / **{total_leaf}** tasks completed")
    report.append(f"- **{len(overdue_list)}** overdue tasks\n")

    if recent_list:
        report.append("## Recent Activity")
        for t in recent_list:
            report.append(f"- **{t.get('taskName', t.get('name', '?'))}** — "
                          f"{t.get('editType', '?')} "
                          f"by {t.get('editorName', '?')} ({t.get('lastModified', '?')})")
        report.append("")

    if overdue_list:
        report.append("## Action Required (Overdue)")
        for t in overdue_list[:5]:
            assigned = t.get("assignedTo", "")
            if isinstance(assigned, list):
                assigned = ", ".join(assigned) if assigned else "unassigned"
            report.append(f"- **{t.get('name', '?')}** — due: {t.get('finish', '?') or '?'} "
                          f"({assigned or 'unassigned'})")
        if len(overdue_list) > 5:
            report.append(f"- ... and {len(overdue_list) - 5} more")

    output = "\n".join(report)
    print(output)

    # Save to cache
    save_cache("report_weekly", {"report": output})


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_report",
        description="Generate OnePlanner project reports.",
    )
    sub = parser.add_subparsers(dest="command")

    for name, help_text in [
        ("status", "Overall project status"),
        ("workload", "Resource workload breakdown"),
        ("overdue", "Overdue task report"),
        ("milestones", "Upcoming milestones"),
        ("weekly", "Weekly status summary (markdown)"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "status": cmd_status, "workload": cmd_workload, "overdue": cmd_overdue,
        "milestones": cmd_milestones, "weekly": cmd_weekly,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
