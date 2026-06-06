"""Shared ADO REST helpers for all ADO-based skills."""

import json
import math
import subprocess
import sys
import urllib.request
from .constants import ADO_RESOURCE_ID, API_VERSION, BATCH_SIZE, FIELDS


def get_token() -> str:
    """Get ADO access token via az CLI."""
    try:
        az_cmd = "az.cmd" if sys.platform == "win32" else "az"
        result = subprocess.run(
            [az_cmd, "account", "get-access-token", "--resource", ADO_RESOURCE_ID,
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=30,
        )
        token = result.stdout.strip()
        if not token or result.returncode != 0:
            print(f"ERROR: az CLI failed: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        return token
    except FileNotFoundError:
        print("ERROR: az CLI not found. Install Azure CLI.", file=sys.stderr)
        sys.exit(1)


def ado_get(url: str, token: str) -> dict:
    """Make an authenticated GET request to ADO REST API."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ado_patch(url: str, token: str, body: list[dict]) -> dict:
    """PATCH an ADO work item with JSON Patch operations."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json-patch+json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ado_post(url: str, token: str, body: dict) -> dict:
    """POST to ADO API."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def confirm(msg: str) -> bool:
    """Ask user for confirmation."""
    print(f"\n{msg}")
    resp = input("Proceed? [y/N]: ").strip().lower()
    return resp in ("y", "yes")


def parse_item(wi: dict) -> dict:
    """Parse an ADO work item into a simplified dict."""
    f = wi.get("fields", {})
    assigned = f.get("System.AssignedTo")
    created_by = f.get("System.CreatedBy")
    return {
        "id": wi["id"],
        "type": f.get("System.WorkItemType", ""),
        "title": f.get("System.Title", ""),
        "state": f.get("System.State", ""),
        "assigned_to": assigned.get("displayName", "") if assigned else "",
        "created_by": created_by.get("displayName", "") if created_by else "",
        "tags": f.get("System.Tags", ""),
        "description": f.get("System.Description", ""),
        "iteration_path": f.get("System.IterationPath", ""),
        "changed_date": f.get("System.ChangedDate", ""),
        "created_date": f.get("System.CreatedDate", ""),
    }


def batch_fetch(org: str, project: str, ids: list[int], token: str) -> list[dict]:
    """Fetch work item details in batches of BATCH_SIZE."""
    all_items = []
    fields_param = ",".join(FIELDS)
    total_batches = math.ceil(len(ids) / BATCH_SIZE)

    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        id_str = ",".join(str(x) for x in batch)
        batch_num = i // BATCH_SIZE + 1
        print(f"  Fetching batch {batch_num}/{total_batches} ({len(batch)} items)...")

        url = (f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems"
               f"?ids={id_str}&fields={fields_param}&api-version={API_VERSION}")
        result = ado_get(url, token)
        all_items.extend(result.get("value", []))

    return all_items


def get_work_item(org: str, project: str, item_id: int, token: str) -> dict:
    """Fetch a single work item by ID and return parsed dict."""
    fields_param = ",".join(FIELDS)
    url = (f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{item_id}"
           f"?fields={fields_param}&api-version={API_VERSION}")
    raw = ado_get(url, token)
    return parse_item(raw)


def run_wiql(org: str, project: str, wiql: str, token: str) -> list[dict]:
    """Execute a WIQL query and return the list of work item stubs ({id, url})."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/wiql?api-version={API_VERSION}"
    result = ado_post(url, token, {"query": wiql})
    return result.get("workItems", [])
