#!/usr/bin/env python3
"""ado_update.py — General-purpose ADO work item write operations.

All write operations display the proposed change and require user confirmation.

Usage:
    cd skills/ado
    python -m scripts.ado_update --action create --type Bug --title "Fix login"
    python -m scripts.ado_update --action assign --id 12345 --dri "Jane Doe"
    python -m scripts.ado_update --action add-comment --id 12345 --comment "Reviewed"
    python -m scripts.ado_update --action set-field --id 12345 --field System.State --value Active
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Import shared ADO helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ado_common.client import get_token, ado_get, ado_patch, ado_post, confirm
from ado_common.constants import API_VERSION

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


# --- Actions ---

def action_create(args, config):
    org, project = get_org_project(args, config)
    token = get_token()
    wi_type = args.type or "Task"

    patches = [
        {"op": "add", "path": "/fields/System.Title", "value": args.title},
    ]
    if args.dri:
        patches.append({"op": "add", "path": "/fields/System.AssignedTo", "value": args.dri})
    if args.description:
        patches.append({"op": "add", "path": "/fields/System.Description", "value": args.description})
    if args.parent_id:
        patches.append({
            "op": "add", "path": "/relations/-",
            "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.parent_id}",
            }
        })

    if not confirm(f"CREATE {wi_type} under parent #{args.parent_id or 'none'}\n"
                   f"  Title: {args.title}\n  DRI: {args.dri or '(none)'}"):
        print("Cancelled.")
        return

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/${wi_type}?api-version={API_VERSION}"
    result = ado_patch(url, token, patches)
    print(f"Created work item #{result['id']}: {result['fields']['System.Title']}")


def action_assign(args, config):
    org, project = get_org_project(args, config)
    token = get_token()

    if not confirm(f"ASSIGN #{args.id}\n  New assignee: {args.dri}"):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": "/fields/System.AssignedTo", "value": args.dri}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Assigned #{args.id} to {args.dri}")


def action_update_desc(args, config):
    org, project = get_org_project(args, config)
    token = get_token()

    if not confirm(f"UPDATE DESCRIPTION on #{args.id}\n  New description: {args.description[:100]}..."):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": "/fields/System.Description", "value": args.description}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Updated description on #{args.id}")


def action_add_comment(args, config):
    org, project = get_org_project(args, config)
    token = get_token()

    if not confirm(f"ADD COMMENT on #{args.id}\n  Comment: {args.comment[:100]}"):
        print("Cancelled.")
        return

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workItems/{args.id}/comments?api-version={API_VERSION}-preview.4"
    ado_post(url, token, {"text": args.comment})
    print(f"Comment added to #{args.id}")


def action_set_field(args, config):
    org, project = get_org_project(args, config)
    token = get_token()

    if not confirm(f"SET FIELD on #{args.id}\n  Field: {args.field}\n  Value: {args.value}"):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": f"/fields/{args.field}", "value": args.value}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Set {args.field} = {args.value} on #{args.id}")


def action_reparent(args, config):
    org, project = get_org_project(args, config)
    token = get_token()

    if not confirm(f"REPARENT #{args.id}\n  New parent: #{args.new_parent_id}"):
        print("Cancelled.")
        return

    # Get current relations to find existing parent
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?$expand=relations&api-version={API_VERSION}"
    wi = ado_get(url, token)

    patches = []
    for i, rel in enumerate(wi.get("relations", [])):
        if rel.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
            patches.append({"op": "remove", "path": f"/relations/{i}"})

    patches.append({
        "op": "add", "path": "/relations/-",
        "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.new_parent_id}",
        }
    })

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Reparented #{args.id} under #{args.new_parent_id}")


def action_add_link(args, config):
    org, project = get_org_project(args, config)
    token = get_token()
    link_type = args.link_type or "Hyperlink"

    if not confirm(f"ADD LINK on #{args.id}\n  Target: {args.target_url}\n  Type: {link_type}"):
        print("Cancelled.")
        return

    patches = [{
        "op": "add", "path": "/relations/-",
        "value": {"rel": link_type, "url": args.target_url}
    }]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Added {link_type} link to #{args.id}")


ACTIONS = {
    "create": action_create,
    "assign": action_assign,
    "update-desc": action_update_desc,
    "add-comment": action_add_comment,
    "set-field": action_set_field,
    "reparent": action_reparent,
    "add-link": action_add_link,
}


def main():
    config = load_config()

    parser = argparse.ArgumentParser(description="Write operations for ADO work items.")
    parser.add_argument("--action", "-a", required=True, choices=list(ACTIONS.keys()))
    parser.add_argument("--id", type=int, help="Work item ID")
    parser.add_argument("--parent-id", type=int, help="Parent work item ID (for create)")
    parser.add_argument("--new-parent-id", type=int, help="New parent ID (for reparent)")
    parser.add_argument("--title", help="Title (for create)")
    parser.add_argument("--type", help="Work item type (for create, default: Task)")
    parser.add_argument("--dri", help="Assignee name or email")
    parser.add_argument("--description", help="Description text")
    parser.add_argument("--comment", help="Comment text")
    parser.add_argument("--field", help="Field reference name (for set-field)")
    parser.add_argument("--value", help="Field value (for set-field)")
    parser.add_argument("--target-url", help="URL to link (for add-link)")
    parser.add_argument("--link-type", help="Link relation type (for add-link, default: Hyperlink)")
    parser.add_argument("--org", help="ADO organization (overrides ado.json)")
    parser.add_argument("--project", help="ADO project (overrides ado.json)")
    args = parser.parse_args()

    ACTIONS[args.action](args, config)


if __name__ == "__main__":
    main()
