"""Outlook rules sync — push triage profile to Exchange server-side rules.

Creates and manages Outlook Inbox Rules that provide Layer 0 (always-on,
zero-latency) email triage. Rules are prefixed with '[Triage]' for
identification and management.

Server rules handle:
    - VIP sender → categorize "🔴 Urgent" + flag + mark High importance
    - Tier 1 sender → categorize "🟡 Tier 1"
    - Noise sender → move to "Noise" folder + mark read
    - Calendar auto-replies → move to archive

The Python engine (Layer 1+) then reads these pre-set categories
for enrichment (Todo tasks, Teams summaries, audit trail).

Usage:
    python -m scripts.rules_sync [--profile PATH] [--dry-run] [--clean]
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

import requests

sys.path.insert(0, ".")

from scripts.todo_auth import get_token, ensure_token
from scripts.triage_engine import load_profile

API_BASE = "https://outlook.office365.com/api/v2.0/me"
RULES_URL = f"{API_BASE}/mailfolders/inbox/messagerules"
FOLDERS_URL = f"{API_BASE}/mailfolders"

# Prefix for all triage-managed rules (for identification)
RULE_PREFIX = "[Triage] "


@dataclass
class RulePlan:
    """Plan for a single Outlook rule."""
    name: str
    sequence: int
    conditions: dict
    actions: dict
    enabled: bool = True
    existing_id: Optional[str] = None  # Set if rule already exists


class RulesSync:
    """Sync triage profile contacts to Outlook server-side rules."""

    def __init__(self):
        self._token: str | None = None

    def _headers(self) -> dict:
        if not self._token:
            self._token = get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, json_body: dict | None = None,
                 timeout: int = 30) -> requests.Response:
        """API request with token refresh on 401."""
        resp = requests.request(method, url, headers=self._headers(),
                                json=json_body, timeout=timeout)
        if resp.status_code == 401:
            ensure_token()
            self._token = get_token()
            resp = requests.request(method, url, headers=self._headers(),
                                    json=json_body, timeout=timeout)
        return resp

    # --- Read existing rules ---

    def list_rules(self) -> list[dict]:
        """Get all inbox rules."""
        resp = self._request("GET", RULES_URL)
        resp.raise_for_status()
        return resp.json().get("value", [])

    def list_triage_rules(self) -> list[dict]:
        """Get only [Triage]-prefixed rules."""
        return [r for r in self.list_rules()
                if r.get("DisplayName", "").startswith(RULE_PREFIX)]

    # --- CRUD ---

    def create_rule(self, plan: RulePlan) -> dict:
        """Create a new inbox rule."""
        body = {
            "DisplayName": plan.name,
            "Sequence": plan.sequence,
            "IsEnabled": plan.enabled,
            "Conditions": plan.conditions,
            "Actions": plan.actions,
        }
        resp = self._request("POST", RULES_URL, json_body=body)
        resp.raise_for_status()
        return resp.json()

    def update_rule(self, rule_id: str, plan: RulePlan) -> dict:
        """Update an existing rule."""
        body = {
            "DisplayName": plan.name,
            "Sequence": plan.sequence,
            "IsEnabled": plan.enabled,
            "Conditions": plan.conditions,
            "Actions": plan.actions,
        }
        url = f"{RULES_URL}/{rule_id}"
        resp = self._request("PATCH", url, json_body=body)
        resp.raise_for_status()
        return resp.json()

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule by ID."""
        url = f"{RULES_URL}/{rule_id}"
        resp = self._request("DELETE", url)
        return resp.status_code == 204

    # --- Folder helpers ---

    def get_or_create_folder(self, name: str) -> str:
        """Get folder ID by name, create if missing."""
        resp = self._request("GET", FOLDERS_URL)
        resp.raise_for_status()
        folders = resp.json().get("value", [])

        for f in folders:
            if f.get("DisplayName", "").lower() == name.lower():
                return f["Id"]

        # Create folder
        resp = self._request("POST", FOLDERS_URL,
                             json_body={"DisplayName": name})
        resp.raise_for_status()
        return resp.json()["Id"]

    # --- Plan generation ---

    def build_plan(self, profile: dict) -> list[RulePlan]:
        """Generate rule plans from a triage profile.

        Rule priority (lower sequence = higher priority):
            1-10:  VIP rules
            11-30: Tier 1 contact rules
            31-40: Noise sender rules
            41-50: Auto-archive rules (calendar responses)
        """
        plans: list[RulePlan] = []
        seq = 1

        # --- VIP rules ---
        vip_contacts = profile.get("vip_contacts", [])
        if vip_contacts:
            vip_addrs = self._resolve_addresses(vip_contacts)
            if vip_addrs:
                plans.append(RulePlan(
                    name=f"{RULE_PREFIX}VIP — Urgent + Flag",
                    sequence=seq,
                    conditions={
                        "FromAddresses": vip_addrs,
                    },
                    actions={
                        "AssignCategories": ["🔴 Urgent"],
                        "MarkImportance": "High",
                        "StopProcessingRules": True,
                    },
                ))
                seq += 1

        # --- Tier 1 rules ---
        # Group into batches of ~10 to stay within reasonable rule sizes
        tier1_contacts = profile.get("tier1_contacts", [])
        if tier1_contacts:
            batch_size = 10
            for i in range(0, len(tier1_contacts), batch_size):
                batch = tier1_contacts[i:i + batch_size]
                addrs = self._resolve_addresses(batch)
                if addrs:
                    batch_num = (i // batch_size) + 1
                    names = ", ".join(c.get("name", "?")[:15] for c in batch[:3])
                    suffix = f" +{len(batch) - 3}" if len(batch) > 3 else ""
                    plans.append(RulePlan(
                        name=f"{RULE_PREFIX}Tier 1 #{batch_num} — {names}{suffix}",
                        sequence=10 + batch_num,
                        conditions={
                            "FromAddresses": addrs,
                        },
                        actions={
                            "AssignCategories": ["🟡 Tier 1"],
                            "StopProcessingRules": False,
                        },
                    ))
                    seq += 1

        # --- Noise rules ---
        noise = profile.get("noise_filters", {})
        noise_senders = noise.get("senders", [])
        noise_domains = noise.get("domains", [])

        if noise_senders:
            noise_addrs = [
                {"EmailAddress": {"Address": s}} for s in noise_senders
            ]
            plans.append(RulePlan(
                name=f"{RULE_PREFIX}Noise — Auto-archive senders",
                sequence=31,
                conditions={
                    "FromAddresses": noise_addrs,
                },
                actions={
                    "MarkAsRead": True,
                    "StopProcessingRules": True,
                },
            ))

        # SenderContains for domain filtering (partial match)
        if noise_domains:
            plans.append(RulePlan(
                name=f"{RULE_PREFIX}Noise — Domain filter",
                sequence=32,
                conditions={
                    "SenderContains": noise_domains,
                },
                actions={
                    "MarkAsRead": True,
                    "StopProcessingRules": True,
                },
            ))

        # --- Calendar auto-archive ---
        plans.append(RulePlan(
            name=f"{RULE_PREFIX}Auto-archive — Calendar responses",
            sequence=41,
            conditions={
                "SubjectContains": ["Accepted:", "Declined:", "Tentative:"],
            },
            actions={
                "MarkAsRead": True,
                "StopProcessingRules": True,
            },
        ))

        plans.append(RulePlan(
            name=f"{RULE_PREFIX}Auto-archive — Cancellations",
            sequence=42,
            conditions={
                "SubjectContains": ["Canceled:"],
            },
            actions={
                "MarkAsRead": True,
                "StopProcessingRules": True,
            },
        ))

        return plans

    def _resolve_addresses(self, contacts: list[dict]) -> list[dict]:
        """Convert contact entries to Outlook FromAddresses format."""
        addrs = []
        for c in contacts:
            email = c.get("email", "")
            alias = c.get("alias", "")
            name = c.get("name", "")

            if email:
                addr = email
            elif alias:
                # Assume microsoft.com domain for aliases
                addr = f"{alias}@microsoft.com"
            else:
                continue

            addrs.append({
                "EmailAddress": {
                    "Name": name,
                    "Address": addr,
                }
            })
        return addrs

    # --- Sync orchestration ---

    def sync(self, profile: dict, dry_run: bool = False,
             auto_confirm: bool = False) -> dict:
        """Sync profile rules to Outlook. Idempotent.

        Strategy:
        1. Build plan from profile
        2. List existing [Triage] rules
        3. Match by DisplayName (update if exists, create if new)
        4. Delete orphaned [Triage] rules not in plan

        Args:
            profile: Triage profile with contacts and preferences
            dry_run: If True, show changes without applying
            auto_confirm: If True, skip interactive confirmation (ET-3: --yes flag)

        Returns:
            dict with created, updated, deleted, unchanged counts
        """
        plans = self.build_plan(profile)
        existing = self.list_triage_rules()

        # Index existing by name
        existing_by_name = {r["DisplayName"]: r for r in existing}
        plan_names = {p.name for p in plans}

        stats = {"created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                 "errors": 0, "total_planned": len(plans)}

        # ET-3: Preview changes and require confirmation
        changes_preview = []
        for plan in plans:
            existing_rule = existing_by_name.get(plan.name)
            if existing_rule:
                if not self._rule_matches(existing_rule, plan):
                    changes_preview.append(f"  ~ Update: {plan.name}")
            else:
                changes_preview.append(f"  + Create: {plan.name}")
        for name in existing_by_name:
            if name not in plan_names:
                changes_preview.append(f"  - Delete: {name}")

        if changes_preview and not dry_run and not auto_confirm:
            print("\nPlanned Exchange rule changes:")
            for line in changes_preview:
                print(line)
            print()
            try:
                answer = input("Apply these changes? [y/N] ").strip().lower()
                if answer != "y":
                    print("Aborted — no changes applied.")
                    return stats
            except (EOFError, KeyboardInterrupt):
                print("\nAborted — no changes applied.")
                return stats

        # Create or update
        for plan in plans:
            existing_rule = existing_by_name.get(plan.name)

            if existing_rule:
                # Check if update needed
                if self._rule_matches(existing_rule, plan):
                    print(f"  = Unchanged: {plan.name}")
                    stats["unchanged"] += 1
                    continue

                if dry_run:
                    print(f"  ~ Would update: {plan.name}")
                    stats["updated"] += 1
                    continue

                try:
                    self.update_rule(existing_rule["Id"], plan)
                    print(f"  ^ Updated: {plan.name}")
                    stats["updated"] += 1
                except Exception as e:
                    print(f"  X Failed to update {plan.name}: {e}")
                    stats["errors"] += 1
            else:
                if dry_run:
                    print(f"  + Would create: {plan.name}")
                    stats["created"] += 1
                    continue

                try:
                    self.create_rule(plan)
                    print(f"  + Created: {plan.name}")
                    stats["created"] += 1
                except Exception as e:
                    print(f"  X Failed to create {plan.name}: {e}")
                    stats["errors"] += 1

        # Delete orphaned triage rules
        for name, rule in existing_by_name.items():
            if name not in plan_names:
                if dry_run:
                    print(f"  - Would delete orphan: {name}")
                    stats["deleted"] += 1
                    continue

                try:
                    self.delete_rule(rule["Id"])
                    print(f"  - Deleted orphan: {name}")
                    stats["deleted"] += 1
                except Exception as e:
                    print(f"  X Failed to delete {name}: {e}")
                    stats["errors"] += 1

        return stats

    def clean(self, dry_run: bool = False) -> int:
        """Remove all [Triage] rules."""
        rules = self.list_triage_rules()
        count = 0
        for rule in rules:
            name = rule.get("DisplayName", "?")
            if dry_run:
                print(f"  - Would delete: {name}")
            else:
                try:
                    self.delete_rule(rule["Id"])
                    print(f"  - Deleted: {name}")
                except Exception as e:
                    print(f"  ❌ Failed to delete {name}: {e}")
            count += 1
        return count

    def _rule_matches(self, existing: dict, plan: RulePlan) -> bool:
        """Check if an existing rule matches the plan (no update needed)."""
        if existing.get("Sequence") != plan.sequence:
            return False
        if existing.get("IsEnabled") != plan.enabled:
            return False
        # Deep comparison of conditions and actions is complex;
        # for now, compare JSON serialization
        ex_conds = json.dumps(existing.get("Conditions", {}), sort_keys=True)
        pl_conds = json.dumps(plan.conditions, sort_keys=True)
        ex_acts = json.dumps(existing.get("Actions", {}), sort_keys=True)
        pl_acts = json.dumps(plan.actions, sort_keys=True)
        return ex_conds == pl_conds and ex_acts == pl_acts


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Sync triage rules to Outlook")
    parser.add_argument("--profile", type=str, default=None,
                        help="Path to triage profile JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without modifying rules")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip interactive confirmation (for unattended execution)")
    parser.add_argument("--clean", action="store_true",
                        help="Remove all [Triage] rules")
    parser.add_argument("--list", action="store_true",
                        help="List all inbox rules")

    args = parser.parse_args()
    sync = RulesSync()

    if args.list:
        import io, sys as _sys
        _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace')
        rules = sync.list_rules()
        print(f"Found {len(rules)} inbox rules:")
        for r in rules:
            name = r.get("DisplayName", "?")
            enabled = "Y" if r.get("IsEnabled") else "N"
            seq = r.get("Sequence", "?")
            tag = "*" if name.startswith(RULE_PREFIX) else " "
            print(f"  {tag} [{enabled}] seq={seq:>3}  {name}")
        return

    if args.clean:
        print("Removing all [Triage] rules...")
        count = sync.clean(dry_run=args.dry_run)
        action = "would remove" if args.dry_run else "removed"
        print(f"\n{action.title()} {count} rule(s)")
        return

    profile = load_profile(args.profile)
    vip_count = len(profile.get("vip_contacts", []))
    t1_count = len(profile.get("tier1_contacts", []))
    noise_count = len(profile.get("noise_filters", {}).get("senders", []))
    print(f"Profile: {vip_count} VIPs, {t1_count} Tier 1, {noise_count} noise senders")

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\nSyncing rules to Outlook ({mode})...")
    stats = sync.sync(profile, dry_run=args.dry_run, auto_confirm=args.yes)

    err_msg = f", {stats['errors']} errors" if stats.get('errors') else ""
    print(f"\nSync complete: "
          f"{stats['created']} created, {stats['updated']} updated, "
          f"{stats['deleted']} deleted, {stats['unchanged']} unchanged"
          f"{err_msg}")


if __name__ == "__main__":
    main()
