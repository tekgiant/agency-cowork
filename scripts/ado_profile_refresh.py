#!/usr/bin/env python3
"""Refresh ADO profile dashboard data."""

import subprocess
import json
import sys
import urllib.request
import math
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path

ORG = "MicrosoftIT"
PROJECT = "OneITVSO"
USER_EMAIL = "mibir@microsoft.com"
USER_ID = "9d6096ca-c31a-469a-b0b6-e202daf4f972"
TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
DAYS_BACK = 180
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "memory" / "Knowledgebase" / "ado-profile-data.json"


def get_token():
    az_cmd = "az.cmd" if sys.platform == "win32" else "az"
    result = subprocess.run(
        [az_cmd, "account", "get-access-token", "--resource", "499b84ac-1321-427f-aa17-267ca6975798",
         "--tenant", TENANT, "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=30
    )
    token = result.stdout.strip()
    if not token or result.returncode != 0:
        print(f"ERROR: az CLI failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return token


def ado_request(url, token, method="GET", body=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_wiql(token, wiql):
    url = f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/wit/wiql?api-version=7.1"
    result = ado_request(url, token, "POST", {"query": wiql})
    return result.get("workItems", [])


def batch_fetch_items(token, ids):
    fields = "System.Id,System.WorkItemType,System.Title,System.State,System.ChangedDate,System.CreatedDate,System.AreaPath,System.IterationPath,System.AssignedTo,System.Tags"
    all_items = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i+200]
        id_str = ",".join(str(x) for x in batch)
        url = f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/wit/workitems?ids={id_str}&fields={fields}&api-version=7.1"
        result = ado_request(url, token)
        all_items.extend(result.get("value", []))
    return all_items


def parse_work_item(wi):
    f = wi.get("fields", {})
    assigned = f.get("System.AssignedTo")
    return {
        "id": wi["id"],
        "type": f.get("System.WorkItemType", ""),
        "title": f.get("System.Title", ""),
        "state": f.get("System.State", ""),
        "assignedTo": assigned.get("displayName", "") if assigned else "",
        "areaPath": f.get("System.AreaPath", ""),
        "iterationPath": f.get("System.IterationPath", ""),
        "changedDate": f.get("System.ChangedDate", ""),
        "createdDate": f.get("System.CreatedDate", ""),
        "tags": f.get("System.Tags", ""),
    }


def parse_pr(pr):
    return {
        "pullRequestId": pr.get("pullRequestId"),
        "title": pr.get("title", ""),
        "status": pr.get("status", ""),
        "creationDate": pr.get("creationDate", ""),
        "closedDate": pr.get("closedDate", ""),
        "repository": pr.get("repository", {}).get("name", ""),
        "targetBranch": pr.get("targetRefName", "").replace("refs/heads/", ""),
        "sourceBranch": pr.get("sourceRefName", "").replace("refs/heads/", ""),
    }


def main():
    print("Getting token...")
    token = get_token()
    print("Token acquired.")

    since_date = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    # 1. Completed work items - try multiple queries
    print(f"\n--- Querying completed work items (since {since_date}) ---")

    # Primary: assigned to user
    wiql1 = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.AssignedTo] = '{USER_EMAIL}' "
        f"AND [System.State] IN ('Closed', 'Resolved', 'Done', 'Completed') "
        f"AND [System.ChangedDate] >= '{since_date}' "
        f"ORDER BY [System.ChangedDate] DESC"
    )
    stubs1 = run_wiql(token, wiql1)
    print(f"  Assigned to (current): {len(stubs1)}")

    # Also: EVER assigned
    wiql2 = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.AssignedTo] EVER '{USER_EMAIL}' "
        f"AND [System.State] IN ('Closed', 'Resolved', 'Done', 'Completed') "
        f"AND [System.ChangedDate] >= '{since_date}' "
        f"ORDER BY [System.ChangedDate] DESC"
    )
    stubs2 = run_wiql(token, wiql2)
    print(f"  Assigned to (ever): {len(stubs2)}")

    # Also: resolved by
    wiql3 = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [Microsoft.VSTS.Common.ResolvedBy] = '{USER_EMAIL}' "
        f"AND [System.ChangedDate] >= '{since_date}' "
        f"ORDER BY [System.ChangedDate] DESC"
    )
    try:
        stubs3 = run_wiql(token, wiql3)
        print(f"  Resolved by: {len(stubs3)}")
    except Exception as e:
        stubs3 = []
        print(f"  Resolved by query failed: {e}")

    # Also: closed by
    wiql4 = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [Microsoft.VSTS.Common.ClosedBy] = '{USER_EMAIL}' "
        f"AND [System.ChangedDate] >= '{since_date}' "
        f"ORDER BY [System.ChangedDate] DESC"
    )
    try:
        stubs4 = run_wiql(token, wiql4)
        print(f"  Closed by: {len(stubs4)}")
    except Exception as e:
        stubs4 = []
        print(f"  Closed by query failed: {e}")

    # Merge all IDs
    all_wi_ids = set()
    for stubs in [stubs1, stubs2, stubs3, stubs4]:
        for s in stubs:
            all_wi_ids.add(s["id"])
    print(f"  Total unique IDs: {len(all_wi_ids)}")

    # Fetch details
    work_items = []
    if all_wi_ids:
        work_items = batch_fetch_items(token, sorted(all_wi_ids))
    parsed_items = [parse_work_item(wi) for wi in work_items]
    print(f"  Fetched details: {len(parsed_items)}")

    # 2. PRs created (top 200)
    print(f"\n--- Querying PRs created by user {USER_ID} ---")
    pr_url = (
        f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/git/pullrequests"
        f"?searchCriteria.creatorId={USER_ID}&searchCriteria.status=all&$top=200&api-version=7.1"
    )
    pr_result = ado_request(pr_url, token)
    pr_count = pr_result.get("count", 0)
    pr_values = pr_result.get("value", [])
    print(f"  PR API count: {pr_count}, accessible values: {len(pr_values)}")

    # Also try org-wide
    pr_url_org = (
        f"https://dev.azure.com/{ORG}/_apis/git/pullrequests"
        f"?searchCriteria.creatorId={USER_ID}&searchCriteria.status=all&$top=200&api-version=7.1"
    )
    pr_result_org = ado_request(pr_url_org, token)
    pr_count_org = pr_result_org.get("count", 0)
    pr_values_org = pr_result_org.get("value", [])
    print(f"  Org-wide PR count: {pr_count_org}, accessible values: {len(pr_values_org)}")

    # Merge PRs (dedupe by ID)
    all_prs = {}
    for pr in pr_values + pr_values_org:
        pid = pr.get("pullRequestId")
        if pid and pid not in all_prs:
            all_prs[pid] = pr
    parsed_prs = [parse_pr(pr) for pr in all_prs.values()]
    print(f"  Total unique PRs: {len(parsed_prs)}")

    # 3. Daily activity heatmap
    print("\n--- Computing daily activity heatmap ---")
    daily_counts = defaultdict(int)

    # Count work item ChangedDate
    for item in parsed_items:
        if item["changedDate"]:
            day = item["changedDate"][:10]
            daily_counts[day] += 1

    # Count PR creationDate
    for pr in parsed_prs:
        if pr["creationDate"]:
            day = pr["creationDate"][:10]
            daily_counts[day] += 1

    # Sort by date
    heatmap = [{"date": k, "count": v} for k, v in sorted(daily_counts.items())]
    print(f"  Days with activity: {len(heatmap)}")

    # 4. Summary stats
    wi_by_type = defaultdict(int)
    wi_by_state = defaultdict(int)
    for item in parsed_items:
        wi_by_type[item["type"]] += 1
        wi_by_state[item["state"]] += 1

    pr_by_status = defaultdict(int)
    for pr in parsed_prs:
        pr_by_status[pr["status"]] += 1

    # Build output JSON
    output = {
        "lastUpdated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "queryParams": {
            "org": ORG,
            "project": PROJECT,
            "userEmail": USER_EMAIL,
            "userId": USER_ID,
            "daysBack": DAYS_BACK,
            "sinceDate": since_date,
        },
        "summary": {
            "completedWorkItems": len(parsed_items),
            "pullRequestsCreated": len(parsed_prs),
            "prApiReportedCount": max(pr_count, pr_count_org),
            "daysWithActivity": len(heatmap),
            "workItemsByType": dict(wi_by_type),
            "workItemsByState": dict(wi_by_state),
            "prsByStatus": dict(pr_by_status),
        },
        "completedWorkItems": parsed_items,
        "pullRequests": parsed_prs,
        "dailyActivity": heatmap,
    }

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Written to {OUTPUT_PATH}")
    print(f"  Work items: {len(parsed_items)}, PRs: {len(parsed_prs)}, Heatmap days: {len(heatmap)}")


if __name__ == "__main__":
    main()
