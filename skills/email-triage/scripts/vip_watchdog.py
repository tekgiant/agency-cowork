"""VIP watchdog — lightweight check for VIP/urgent sender emails.

Runs frequently (every 5 min) and ONLY checks VIP contacts.
If a new VIP email is found that hasn't been triaged, sends
an immediate Teams alert.

This is the Layer 1 "never-miss" safety net. It's separate from
the main triage engine so it can run on a faster cadence with
minimal API calls.

Usage:
    python -m scripts.vip_watchdog [--profile PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from scripts.mail_client import MailClient, get_sender_email, get_sender_name
from scripts.triage_engine import load_profile, load_processed_ids, CACHE_DIR

VIP_STATE_FILE = CACHE_DIR / "vip-watchdog-state.json"


def _load_vip_state() -> dict:
    if VIP_STATE_FILE.exists():
        with open(VIP_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_check": None, "alerts_sent": []}


def _save_vip_state(state: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(VIP_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def check_vip_emails(profile: dict) -> list[dict]:
    """Check for new VIP emails not yet triaged.

    Returns list of unprocessed VIP messages.
    """
    vip_contacts = profile.get("vip_contacts", [])
    if not vip_contacts:
        return []

    # Build list of VIP email addresses
    vip_emails = []
    for contact in vip_contacts:
        email = contact.get("email", "")
        alias = contact.get("alias", "")
        if email:
            vip_emails.append(email)
        elif alias:
            vip_emails.append(f"{alias}@microsoft.com")

    if not vip_emails:
        return []

    # Check recent emails from VIP senders
    vip_state = _load_vip_state()
    since = vip_state.get("last_check")
    if not since:
        # First run: look back 1 hour
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        since = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    client = MailClient()
    messages = client.list_messages_from_senders(
        sender_emails=vip_emails,
        since=since,
        top=10,
    )

    # Filter out already-processed
    processed = load_processed_ids()
    processed_ids = set(processed.get("ids", {}).keys())

    new_vip = [m for m in messages if m.get("Id") not in processed_ids]

    # Update watchdog state
    vip_state["last_check"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_vip_state(vip_state)

    return new_vip


def format_vip_alert(messages: list[dict]) -> str:
    """Format VIP alert message for Teams."""
    if not messages:
        return ""

    lines = ["🚨 **VIP Email Alert** — Immediate attention required\n"]
    for msg in messages:
        sender = get_sender_name(msg)
        subject = msg.get("Subject", "")
        received = msg.get("ReceivedDateTime", "")[:16]
        lines.append(f"- **{sender}**: {subject} ({received})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VIP Email Watchdog")
    parser.add_argument("--profile", type=str, default=None,
                        help="Path to triage profile JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check but don't update state")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    vip_count = len(profile.get("vip_contacts", []))
    print(f"VIP watchdog: checking {vip_count} VIP contacts...")

    if vip_count == 0:
        print("  No VIP contacts configured — nothing to check.")
        return

    new_msgs = check_vip_emails(profile)

    if new_msgs:
        print(f"\n🚨 {len(new_msgs)} NEW VIP email(s) detected!")
        alert = format_vip_alert(new_msgs)
        print(alert)
        # TODO: Post to Teams via skill
    else:
        print("  ✅ No new VIP emails.")


if __name__ == "__main__":
    main()
