"""
op_risks — View and manage project risks.

Usage:
    python -m scripts.op_risks list [--format F]         # List all risks
    python -m scripts.op_risks summary [--format F]      # Risk summary stats
    python -m scripts.op_risks add <name> [--severity S] [--likelihood L] [--impact I]
    python -m scripts.op_risks update <name_or_index> [--status S] [...]
    python -m scripts.op_risks link <risk> <task>        # Link risk to task
"""

import argparse
import json
import sys

from ._api import api_get, api_post, api_patch, ensure_loaded, format_output


def _encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_list(args):
    """List all risks."""
    ensure_loaded()
    result = api_get("/risks")
    if not result:
        print("No risks found.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    risks = result if isinstance(result, list) else result.get("risks", [])
    if not risks:
        print("No risks found.")
        return

    headers = ["#", "Name", "Severity", "Likelihood", "Impact", "Status", "Owner"]
    rows = []
    for i, r in enumerate(risks, 1):
        rows.append([
            str(i),
            r.get("name", "?"),
            r.get("severity", ""),
            r.get("likelihood", ""),
            r.get("impact", ""),
            r.get("status", ""),
            r.get("owner", ""),
        ])
    print(format_output(headers, rows, args.format))


def cmd_summary(args):
    """Show risk summary statistics."""
    ensure_loaded()
    result = api_get("/risks")
    if not result:
        print("No risks found.")
        return

    risks = result if isinstance(result, list) else result.get("risks", [])

    # Compute stats
    total = len(risks)
    by_severity = {}
    by_status = {}
    for r in risks:
        sev = r.get("severity", "Unknown")
        sta = r.get("status", "Unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_status[sta] = by_status.get(sta, 0) + 1

    if args.format == "json":
        print(json.dumps({
            "total": total,
            "bySeverity": by_severity,
            "byStatus": by_status,
        }, indent=2))
        return

    print(f"\n=== Risk Summary ===")
    print(f"  Total risks: {total}")

    if by_severity:
        print(f"\n  By severity:")
        for sev, count in sorted(by_severity.items()):
            print(f"    {sev}: {count}")

    if by_status:
        print(f"\n  By status:")
        for sta, count in sorted(by_status.items()):
            print(f"    {sta}: {count}")
    print()


def cmd_add(args):
    """Add a new risk."""
    ensure_loaded()
    body = {"name": args.name}
    if args.severity:
        body["severity"] = args.severity
    if args.likelihood:
        body["likelihood"] = args.likelihood
    if args.impact:
        body["impact"] = args.impact
    if args.owner:
        body["owner"] = args.owner
    if args.description:
        body["description"] = args.description

    # Risks are created as tasks with risk custom fields
    # The server handles the field mapping
    result = api_post("/risks", body=body)
    if result:
        print(f"Created risk: {args.name}")


def cmd_update(args):
    """Update a risk's fields."""
    ensure_loaded()
    body = {}
    if args.name:
        body["name"] = args.name
    if args.severity:
        body["severity"] = args.severity
    if args.likelihood:
        body["likelihood"] = args.likelihood
    if args.impact:
        body["impact"] = args.impact
    if args.status:
        body["status"] = args.status
    if args.owner:
        body["owner"] = args.owner

    if not body:
        print("No fields to update.")
        sys.exit(1)

    result = api_patch(f"/risks/{_encode(args.risk)}", body=body)
    if result:
        print(f"Updated risk: {args.risk}")


def cmd_link(args):
    """Link a risk to a task."""
    ensure_loaded()
    result = api_post(f"/risks/{_encode(args.risk)}/link", body={"task": args.task})
    if result:
        print(f"Linked risk '{args.risk}' to task '{args.task}'.")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_risks",
        description="View and manage OnePlanner project risks.",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List all risks")
    p_list.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_sum = sub.add_parser("summary", help="Risk summary stats")
    p_sum.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_add = sub.add_parser("add", help="Add a new risk")
    p_add.add_argument("name", help="Risk name/title")
    p_add.add_argument("--severity", help="Severity (High, Medium, Low)")
    p_add.add_argument("--likelihood", help="Likelihood (High, Medium, Low)")
    p_add.add_argument("--impact", help="Impact (High, Medium, Low)")
    p_add.add_argument("--owner", help="Risk owner name")
    p_add.add_argument("--description", help="Risk description")

    p_upd = sub.add_parser("update", help="Update a risk")
    p_upd.add_argument("risk", help="Risk name or index")
    p_upd.add_argument("--name", help="New name")
    p_upd.add_argument("--severity", help="Severity")
    p_upd.add_argument("--likelihood", help="Likelihood")
    p_upd.add_argument("--impact", help="Impact")
    p_upd.add_argument("--status", help="Status")
    p_upd.add_argument("--owner", help="Owner")

    p_link = sub.add_parser("link", help="Link risk to task")
    p_link.add_argument("risk", help="Risk name/index")
    p_link.add_argument("task", help="Task name/index")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {"list": cmd_list, "summary": cmd_summary, "add": cmd_add,
                "update": cmd_update, "link": cmd_link}
    commands[args.command](args)


if __name__ == "__main__":
    main()
