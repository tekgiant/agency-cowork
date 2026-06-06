#!/usr/bin/env python3
"""ado_query.py — General-purpose ADO work item query and search.

Usage:
    cd skills/ado
    python -m scripts.ado_query --action get --id 12345
    python -m scripts.ado_query --action search --keywords "encryption key"
    python -m scripts.ado_query --action wiql --wiql "SELECT [System.Id] FROM WorkItems WHERE ..."
    python -m scripts.ado_query --action saved-query --query-id <GUID>
    python -m scripts.ado_query --action list --state Active --type Bug
"""

import argparse
import json
import sys
from pathlib import Path

# Import shared ADO helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ado_common.client import get_token, ado_get, batch_fetch, parse_item, get_work_item, run_wiql
from ado_common.constants import API_VERSION, FIELDS

SKILL_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """Load default org/project from ado.json."""
    config_path = SKILL_ROOT / "ado.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_org_project(args, config: dict) -> tuple[str, str]:
    """Resolve org and project from args or config."""
    org = args.org or config.get("org", "")
    project = args.project or config.get("project", "")
    if not org or not project:
        print("ERROR: --org and --project are required (or set in ado.json).", file=sys.stderr)
        sys.exit(1)
    return org, project


def format_table(items: list[dict]) -> str:
    """Format work items as a text table."""
    if not items:
        return "No items found."
    lines = [f"{'ID':>7} | {'Type':<20} | {'State':<20} | {'Assigned To':<25} | Title"]
    lines.append("-" * 110)
    for item in items:
        lines.append(
            f"{item['id']:>7} | {item['type']:<20} | {item['state']:<20} | "
            f"{item['assigned_to'][:25]:<25} | {item['title'][:60]}"
        )
    lines.append(f"\n{len(items)} item(s)")
    return "\n".join(lines)


def format_output(items: list[dict], fmt: str) -> str:
    """Format output in the requested format."""
    if fmt == "json":
        return json.dumps(items, indent=2, ensure_ascii=False)
    elif fmt == "markdown":
        if not items:
            return "No items found."
        lines = ["| ID | Type | State | Assigned To | Title |",
                 "|---:|------|-------|-------------|-------|"]
        for item in items:
            lines.append(f"| {item['id']} | {item['type']} | {item['state']} | "
                         f"{item['assigned_to']} | {item['title']} |")
        return "\n".join(lines)
    else:
        return format_table(items)


# --- Actions ---

def action_get(args, config):
    """Get a single work item by ID."""
    org, project = get_org_project(args, config)
    token = get_token()
    item = get_work_item(org, project, args.id, token)
    if args.output == "json":
        print(json.dumps(item, indent=2, ensure_ascii=False))
    else:
        print(f"ID:          {item['id']}")
        print(f"Type:        {item['type']}")
        print(f"Title:       {item['title']}")
        print(f"State:       {item['state']}")
        print(f"Assigned To: {item['assigned_to']}")
        print(f"Created By:  {item['created_by']}")
        print(f"Created:     {item['created_date']}")
        print(f"Changed:     {item['changed_date']}")
        print(f"Iteration:   {item['iteration_path']}")
        print(f"Tags:        {item['tags']}")
        if item.get("description"):
            print(f"\nDescription:\n{item['description'][:500]}")


def action_search(args, config):
    """Keyword search via WIQL."""
    org, project = get_org_project(args, config)
    token = get_token()

    keywords = args.keywords
    # Build WIQL WHERE clause — all keywords must appear in title or description
    conditions = []
    for kw in keywords.split():
        conditions.append(
            f"([System.Title] CONTAINS '{kw}' OR [System.Description] CONTAINS '{kw}' "
            f"OR [System.Tags] CONTAINS '{kw}')"
        )
    where = " AND ".join(conditions)
    wiql = f"SELECT [System.Id] FROM WorkItems WHERE {where} ORDER BY [System.ChangedDate] DESC"

    print(f"Searching for: {keywords}")
    stubs = run_wiql(org, project, wiql, token)
    if not stubs:
        print("No items found.")
        return

    ids = [s["id"] for s in stubs[:200]]
    print(f"Found {len(stubs)} items, fetching details for {len(ids)}...")
    raw_items = batch_fetch(org, project, ids, token)
    items = [parse_item(wi) for wi in raw_items]
    print(format_output(items, args.output))


def action_wiql(args, config):
    """Run arbitrary WIQL query."""
    org, project = get_org_project(args, config)
    token = get_token()

    stubs = run_wiql(org, project, args.wiql, token)
    if not stubs:
        print("No items found.")
        return

    ids = [s["id"] for s in stubs[:200]]
    print(f"Query returned {len(stubs)} items, fetching details for {len(ids)}...")
    raw_items = batch_fetch(org, project, ids, token)
    items = [parse_item(wi) for wi in raw_items]
    print(format_output(items, args.output))


def action_saved_query(args, config):
    """Execute an ADO saved query by GUID."""
    org, project = get_org_project(args, config)
    token = get_token()

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/wiql/{args.query_id}?api-version={API_VERSION}"
    result = ado_get(url, token)

    # Handle both flat and tree queries
    if "workItems" in result:
        ids = [wi["id"] for wi in result["workItems"][:200]]
    elif "workItemRelations" in result:
        id_set = set()
        for rel in result["workItemRelations"]:
            if rel.get("source"):
                id_set.add(rel["source"]["id"])
            if rel.get("target"):
                id_set.add(rel["target"]["id"])
        ids = sorted(id_set)[:200]
    else:
        print("No items found.")
        return

    print(f"Saved query returned {len(ids)} items, fetching details...")
    raw_items = batch_fetch(org, project, ids, token)
    items = [parse_item(wi) for wi in raw_items]
    print(format_output(items, args.output))


def action_list(args, config):
    """List work items with filters via WIQL WHERE clauses."""
    org, project = get_org_project(args, config)
    token = get_token()

    conditions = []
    if args.state:
        conditions.append(f"[System.State] = '{args.state}'")
    if args.type:
        conditions.append(f"[System.WorkItemType] = '{args.type}'")
    if args.dri:
        conditions.append(f"[System.AssignedTo] CONTAINS '{args.dri}'")
    if args.creator:
        conditions.append(f"[System.CreatedBy] CONTAINS '{args.creator}'")
    if args.iteration:
        conditions.append(f"[System.IterationPath] UNDER '{args.iteration}'")
    if args.area:
        conditions.append(f"[System.AreaPath] UNDER '{args.area}'")
    if args.tag:
        conditions.append(f"[System.Tags] CONTAINS '{args.tag}'")

    if not conditions:
        print("ERROR: Provide at least one filter (--state, --type, --dri, --creator, --iteration, --area, --tag).",
              file=sys.stderr)
        sys.exit(1)

    where = " AND ".join(conditions)
    wiql = f"SELECT [System.Id] FROM WorkItems WHERE {where} ORDER BY [System.ChangedDate] DESC"

    stubs = run_wiql(org, project, wiql, token)
    if not stubs:
        print("No items found.")
        return

    ids = [s["id"] for s in stubs[:200]]
    print(f"Found {len(stubs)} items, fetching details for {len(ids)}...")
    raw_items = batch_fetch(org, project, ids, token)
    items = [parse_item(wi) for wi in raw_items]
    print(format_output(items, args.output))


ACTIONS = {
    "get": action_get,
    "search": action_search,
    "wiql": action_wiql,
    "saved-query": action_saved_query,
    "list": action_list,
}


def main():
    config = load_config()

    parser = argparse.ArgumentParser(description="Query ADO work items.")
    parser.add_argument("--action", "-a", required=True, choices=list(ACTIONS.keys()),
                        help="Query action to perform")
    parser.add_argument("--id", type=int, help="Work item ID (for get)")
    parser.add_argument("--keywords", "-k", help="Search keywords (for search)")
    parser.add_argument("--wiql", help="WIQL query string (for wiql)")
    parser.add_argument("--query-id", help="Saved query GUID (for saved-query)")
    parser.add_argument("--state", help="Filter by state (for list)")
    parser.add_argument("--type", help="Filter by work item type (for list)")
    parser.add_argument("--dri", help="Filter by assigned-to (for list)")
    parser.add_argument("--creator", help="Filter by created-by (for list)")
    parser.add_argument("--iteration", help="Filter by iteration path (for list)")
    parser.add_argument("--area", help="Filter by area path (for list)")
    parser.add_argument("--tag", help="Filter by tag (for list)")
    parser.add_argument("--org", help="ADO organization (overrides ado.json)")
    parser.add_argument("--project", help="ADO project (overrides ado.json)")
    parser.add_argument("--output", "-o", choices=["table", "json", "markdown"],
                        default="table", help="Output format (default: table)")
    args = parser.parse_args()

    ACTIONS[args.action](args, config)


if __name__ == "__main__":
    main()
