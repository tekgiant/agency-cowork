"""Refresh the ADO team profiles directory from PR authors/reviewers in shared repos."""
import json, os, sys, time, re, subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone


def get_token():
    az_cmd = "az.cmd" if sys.platform == "win32" else "az"
    result = subprocess.run(
        [az_cmd, "account", "get-access-token", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=60,
    )
    token = result.stdout.strip()
    if not token or result.returncode != 0:
        print(f"ERROR: az CLI failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return token


TOKEN = get_token()

ORG = "https://dev.azure.com/MicrosoftIT"
PROJECT = "OneITVSO"
SEED_USER = "9d6096ca-c31a-469a-b0b6-e202daf4f972"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api_get(url, retries=5):
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After", "5"))
                print(f"  HTTP {e.code}, retrying in {wait}s (attempt {attempt + 1}/{retries + 1})...")
                time.sleep(wait)
                continue
            if e.code in (404, 403) and attempt == retries:
                print(f"  WARN: {e.code} for {url[:120]}")
                return None
            raise
        except (URLError, ConnectionResetError, TimeoutError, OSError) as e:
            if attempt < retries:
                wait = 2 ** attempt
                print(f"  Transient request error: {e!r}, retrying in {wait}s (attempt {attempt + 1}/{retries + 1})...")
                time.sleep(wait)
                continue
            raise

users = {}  # email_lower -> {id, displayName, email}

def add_user(identity):
    """Extract and add a user from an ADO identity object."""
    if not identity or not isinstance(identity, dict):
        return
    name = identity.get("displayName", "") or ""
    email = identity.get("uniqueName", "") or identity.get("mailAddress", "") or ""
    uid = identity.get("id", "") or ""
    if not email:
        return
    email_lower = email.strip().lower()
    if not email_lower.endswith("@microsoft.com"):
        return
    # Filter service accounts and team identities
    if "\\" in name or "[" in name or "]" in name:
        return
    if "\\" in email or "[" in email or "]" in email:
        return
    if "[Default]" in name or "[Default]" in email:
        return
    # Skip entries that look like service accounts
    if re.search(r'\\|vstfs|:/', email_lower):
        return
    if email_lower not in users:
        users[email_lower] = {"id": uid, "displayName": name.strip(), "email": email.strip()}
    elif uid and not users[email_lower]["id"]:
        users[email_lower]["id"] = uid

# ============================================================
# SOURCE 1: PR authors and reviewers
# ============================================================
print("=== Source 1: PR authors and reviewers ===")

# Find repos from seed user's PRs
print(f"  Finding repos from seed user {SEED_USER}...")
seed_url = f"{ORG}/{PROJECT}/_apis/git/pullrequests?searchCriteria.creatorId={SEED_USER}&$top=100&api-version=7.0"
seed_data = api_get(seed_url)
repo_ids = set()
if seed_data and "value" in seed_data:
    for pr in seed_data["value"]:
        repo = pr.get("repository", {})
        rid = repo.get("id")
        if rid:
            repo_ids.add(rid)
    print(f"  Found {len(repo_ids)} repos from {len(seed_data['value'])} seed PRs")

# For each repo, get recent PRs
pr_count = 0
for i, repo_id in enumerate(repo_ids):
    print(f"  Fetching PRs for repo {i+1}/{len(repo_ids)} ({repo_id[:8]}...)...")
    pr_url = f"{ORG}/{PROJECT}/_apis/git/repositories/{repo_id}/pullRequests?$top=100&searchCriteria.status=all&api-version=7.0"
    pr_data = api_get(pr_url)
    if not pr_data or "value" not in pr_data:
        continue
    for pr in pr_data["value"]:
        pr_count += 1
        add_user(pr.get("createdBy"))
        for reviewer in pr.get("reviewers", []):
            add_user(reviewer)

print(f"  Processed {pr_count} PRs, unique users so far: {len(users)}")


# ============================================================
# Build and save output
# ============================================================
print("\n=== Building output ===")

user_list = sorted(users.values(), key=lambda u: u["displayName"].lower())
output = {
    "users": user_list,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "source": "PR authors and reviewers from shared repos identified from recent PRs by user 9d6096ca-c31a-469a-b0b6-e202daf4f972"
}

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "Knowledgebase", "ado-profiles")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "_directory.json")

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nDone! Saved {len(user_list)} users to {out_path}")
