#!/usr/bin/env python3
"""lz_update.py — Write operations to ADO Landing Zone requirements.

All write operations display the proposed change and require user confirmation.

Usage:
    cd skills/landing-zone
    python -m scripts.lz_update --program my-program --action create --parent-id 12968 --title "New requirement"
    python -m scripts.lz_update --program my-program --action assign-dri --id 13246 --dri "Jane Doe"
    python -m scripts.lz_update --program my-program --action find-similar --title "Error handling"
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "cache"

# Import shared ADO helpers from ado_common
sys.path.insert(0, str(SKILL_ROOT.parent))
from ado_common.client import get_token, ado_get, ado_patch, ado_post, confirm
from ado_common.constants import API_VERSION

from scripts.lz_sync import PROGRAM_QUERIES, load_programs


def load_cache(program: str) -> dict:
    path = CACHE_DIR / f"{program}-lz.json"
    if not path.exists():
        print(f"ERROR: No cache for '{program}'.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_org_project(program: str, args) -> tuple[str, str]:
    if not PROGRAM_QUERIES:
        load_programs()
    cfg = PROGRAM_QUERIES.get(program, {})
    return args.org or cfg.get("org", ""), args.project or cfg.get("project", "")


# --- Actions ---

def action_create(args):
    org, project = get_org_project(args.program, args)
    token = get_token()
    wi_type = args.type or "Requirement"

    patches = [
        {"op": "add", "path": "/fields/System.Title", "value": args.title},
    ]
    if args.dri:
        patches.append({"op": "add", "path": "/fields/System.AssignedTo", "value": args.dri})
    if args.parent_id:
        patches.append({
            "op": "add", "path": "/relations/-",
            "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.parent_id}",
            }
        })

    if not confirm(f"CREATE {wi_type} under parent #{args.parent_id or 'none'}\n  Title: {args.title}\n  DRI: {args.dri or '(none)'}"):
        print("Cancelled.")
        return

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/${wi_type}?api-version={API_VERSION}"
    result = ado_patch(url, token, patches)
    print(f"Created work item #{result['id']}: {result['fields']['System.Title']}")


def action_find_similar(args):
    cache = load_cache(args.program)
    items = list(cache.get("items", {}).values())
    titles = {i["id"]: i.get("title", "") for i in items}

    matches = []
    for item_id, title in titles.items():
        ratio = difflib.SequenceMatcher(None, args.title.lower(), title.lower()).ratio()
        if ratio > 0.4:
            matches.append((ratio, item_id, title))

    matches.sort(reverse=True)
    if matches:
        print(f"Found {len(matches)} similar items (threshold > 0.4):\n")
        print(f"{'Score':>6} | {'ID':>6} | Title")
        print("-" * 80)
        for score, item_id, title in matches[:15]:
            print(f"{score:>6.2f} | {item_id:>6} | {title[:60]}")
    else:
        print("No similar items found.")


def action_assign_dri(args):
    org, project = get_org_project(args.program, args)
    token = get_token()

    if not confirm(f"ASSIGN DRI on #{args.id}\n  New DRI: {args.dri}"):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": "/fields/System.AssignedTo", "value": args.dri}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Assigned #{args.id} to {args.dri}")


def action_update_desc(args):
    org, project = get_org_project(args.program, args)
    token = get_token()

    if not confirm(f"UPDATE DESCRIPTION on #{args.id}\n  New description: {args.description[:100]}..."):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": "/fields/System.Description", "value": args.description}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Updated description on #{args.id}")


def action_add_comment(args):
    org, project = get_org_project(args.program, args)
    token = get_token()

    if not confirm(f"ADD COMMENT on #{args.id}\n  Comment: {args.comment[:100]}"):
        print("Cancelled.")
        return

    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workItems/{args.id}/comments?api-version={API_VERSION}-preview.4"
    ado_post(url, token, {"text": args.comment})
    print(f"Comment added to #{args.id}")


def action_set_field(args):
    org, project = get_org_project(args.program, args)
    token = get_token()

    if not confirm(f"SET FIELD on #{args.id}\n  Field: {args.field}\n  Value: {args.value}"):
        print("Cancelled.")
        return

    patches = [{"op": "replace", "path": f"/fields/{args.field}", "value": args.value}]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Set {args.field} = {args.value} on #{args.id}")


def action_reparent(args):
    org, project = get_org_project(args.program, args)
    token = get_token()

    if not confirm(f"REPARENT #{args.id}\n  New parent: #{args.new_parent_id}"):
        print("Cancelled.")
        return

    # Remove existing parent links, add new one
    # First get current relations
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


def action_add_link(args):
    org, project = get_org_project(args.program, args)
    token = get_token()
    link_type = args.link_type or "System.LinkTypes.Related"

    if not confirm(f"ADD LINK on #{args.id}\n  Target: {args.target_url}\n  Type: {link_type}"):
        print("Cancelled.")
        return

    patches = [{
        "op": "add", "path": "/relations/-",
        "value": {"rel": "Hyperlink", "url": args.target_url}
    }]
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{args.id}?api-version={API_VERSION}"
    ado_patch(url, token, patches)
    print(f"Added link to #{args.id}")


ACTIONS = {
    "create": action_create,
    "find-similar": action_find_similar,
    "assign-dri": action_assign_dri,
    "update-desc": action_update_desc,
    "add-comment": action_add_comment,
    "set-field": action_set_field,
    "reparent": action_reparent,
    "add-link": action_add_link,
}


def main():
    parser = argparse.ArgumentParser(description="Write operations for ADO Landing Zone.")
    parser.add_argument("--program", "-p", required=True, help="Program name")
    parser.add_argument("--action", "-a", required=True, choices=list(ACTIONS.keys()))
    parser.add_argument("--id", type=int, help="Work item ID")
    parser.add_argument("--parent-id", type=int, help="Parent work item ID (for create/reparent)")
    parser.add_argument("--new-parent-id", type=int, help="New parent ID (for reparent)")
    parser.add_argument("--title", help="Title (for create/find-similar)")
    parser.add_argument("--type", help="Work item type (for create, default: Requirement)")
    parser.add_argument("--dri", help="DRI name or email")
    parser.add_argument("--description", help="Description text")
    parser.add_argument("--comment", help="Comment text")
    parser.add_argument("--field", help="Field reference name (for set-field)")
    parser.add_argument("--value", help="Field value (for set-field)")
    parser.add_argument("--target-url", help="URL to link (for add-link)")
    parser.add_argument("--link-type", help="Link relation type (for add-link)")
    parser.add_argument("--org", help="ADO organization override")
    parser.add_argument("--project", help="ADO project override")
    args = parser.parse_args()

    ACTIONS[args.action](args)


if __name__ == "__main__":
    main()
