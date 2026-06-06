"""
voice_extract.py — Extract writer's voice profile from sent emails.

Run during onboarding Phase 2.5 (after identity, before VIP contacts).
Fetches 90 days of sent emails, classifies by audience, and extracts
voice patterns per class. Outputs voice-profile.json to ~/.agency-cowork/.

Usage:
    python voice_extract.py --fetch          # Fetch + classify emails
    python voice_extract.py --analyze        # Analyze cached emails
    python voice_extract.py --all            # Fetch + analyze + save
    python voice_extract.py --dry-run        # Print stats, don't save
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add scripts/ to path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))

# ---------- configuration ----------

PROFILE_DIR = Path.home() / ".agency-cowork"
VOICE_PROFILE_PATH = PROFILE_DIR / "voice-profile.json"
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_FILE = CACHE_DIR / "_voice_emails.json"
CACHE_MAX_AGE_DAYS = 7  # ET-4: Auto-delete cache after this many days

DEFAULTS_DIR = Path(__file__).parent.parent / "defaults"
TEMPLATE_PATH = DEFAULTS_DIR / "voice-profile-template.json"

# Noise senders to exclude
NOISE_SUBJECTS = re.compile(
    r"(canceled|cancelled):\s|accepted:|declined:|tentative:|"
    r"automatic reply|out of office|meeting notes:",
    re.IGNORECASE,
)

NOISE_SENDERS = {
    "noreply@email.teams.microsoft.com",
    "no-reply@sharepointonline.com",
    "notifications@github.com",
    "noreply@aka.ms",
}

# Body extraction: cut at first reply chain indicator
REPLY_CHAIN_MARKERS = [
    "\nFrom:",
    "\n________________________________",
    "Get Outlook for iOS",
    "\n-----Original Message-----",
    "\nOn ",  # "On Mon, Jan..." reply marker
]


def _cleanup_stale_cache() -> None:
    """ET-4: Auto-delete voice email cache if older than CACHE_MAX_AGE_DAYS."""
    if not CACHE_FILE.exists():
        return
    try:
        age_days = (time.time() - CACHE_FILE.stat().st_mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            CACHE_FILE.unlink()
            print(f"  🧹 Deleted stale voice cache ({age_days:.0f} days old)")
    except OSError:
        pass


def extract_authored_body(raw_body: str) -> str:
    """Extract only the authored portion of an email, cutting reply chains."""
    body = raw_body.strip()
    if not body:
        return ""

    # Find the earliest reply-chain marker after the first 30 chars
    earliest = len(body)
    for marker in REPLY_CHAIN_MARKERS:
        idx = body.find(marker, 30)
        if idx != -1 and idx < earliest:
            earliest = idx

    return body[:earliest].strip()


# ---------- audience classification ----------

def load_triage_profile() -> dict | None:
    """Load triage profile for contact lists."""
    profile_path = PROFILE_DIR / "triage-profile.json"
    if profile_path.exists():
        with open(profile_path, encoding="utf-8") as f:
            return json.load(f)
    return None


def classify_audience(
    to_addrs: list[str],
    cc_addrs: list[str],
    n_total: int,
    directs: set[str],
    peers: set[str],
    management: set[str],
    external_domains: set[str],
) -> str:
    """Classify a sent email into an audience class."""
    all_recip = set(to_addrs + cc_addrs)
    all_aliases = {a.split("@")[0].lower() for a in all_recip}
    all_domains = {a.split("@")[1].lower() for a in all_recip if "@" in a}

    # External if any non-microsoft domain
    ext = all_domains - {"microsoft.com"}
    if ext:
        return "external"

    # Check if mgmt in recipients
    has_mgmt = bool(all_aliases & management)

    # Large group with mgmt
    if n_total > 6 and has_mgmt:
        return "broad_with_mgmt"

    # Large group without mgmt
    if n_total > 8:
        return "broad_group"

    # Direct reports
    to_aliases = {a.split("@")[0].lower() for a in to_addrs}
    if to_aliases & directs and not (to_aliases & management) and not (to_aliases & peers):
        return "directs"

    # Management
    if to_aliases & management:
        return "management"

    # Peers
    if to_aliases & peers:
        return "peers"

    return "other"


# ---------- email fetching ----------

def fetch_sent_emails(days: int = 90, max_count: int = 300) -> list[dict]:
    """Fetch sent emails via Outlook REST API using OWA token from todo_auth."""
    try:
        from todo_auth import get_token
    except ImportError:
        print("ERROR: todo_auth.py not found. Run from skills/email-triage/scripts/")
        sys.exit(1)

    import urllib.request
    import urllib.error

    token = get_token()
    if not token:
        print("ERROR: Could not get OWA token. Ensure browser is running on CDP port.")
        sys.exit(1)

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = "https://outlook.office.com/api/v2.0/me/mailfolders/sentitems/messages"
    filt = f"SentDateTime ge {since}"
    select = "Subject,ToRecipients,CcRecipients,BccRecipients,Body,SentDateTime,From,Importance"
    url = f"{base}?$filter={filt}&$select={select}&$top={max_count}&$orderby=SentDateTime desc"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR fetching sent emails: {e.code} {e.reason}")
        sys.exit(1)

    messages = data.get("value", [])
    print(f"Fetched {len(messages)} sent emails from past {days} days")
    return messages


def process_emails(raw_messages: list[dict]) -> list[dict]:
    """Process raw API messages into simplified format, filtering noise."""
    processed = []
    for msg in raw_messages:
        subj = msg.get("Subject", "")

        # Skip noise
        if NOISE_SUBJECTS.search(subj):
            continue
        from_addr = msg.get("From", {}).get("EmailAddress", {}).get("Address", "")
        if from_addr.lower() in NOISE_SENDERS:
            continue

        to_addrs = [r["EmailAddress"]["Address"].lower()
                     for r in msg.get("ToRecipients", [])
                     if r.get("EmailAddress", {}).get("Address")]
        cc_addrs = [r["EmailAddress"]["Address"].lower()
                     for r in msg.get("CcRecipients", [])
                     if r.get("EmailAddress", {}).get("Address")]
        bcc_addrs = [r["EmailAddress"]["Address"].lower()
                      for r in msg.get("BccRecipients", [])
                      if r.get("EmailAddress", {}).get("Address")]

        body_raw = msg.get("Body", {}).get("Content", "")
        # Strip HTML tags for plain text extraction
        body_text = re.sub(r"<[^>]+>", " ", body_raw)
        body_text = re.sub(r"\s+", " ", body_text).strip()
        authored = extract_authored_body(body_text)

        if not authored or len(authored) < 10:
            continue

        processed.append({
            "date": msg.get("SentDateTime", "")[:16],
            "subject": subj,
            "to": to_addrs,
            "cc": cc_addrs,
            "bcc": bcc_addrs,
            "n_recip": len(to_addrs) + len(cc_addrs) + len(bcc_addrs),
            "body": authored,
            "importance": msg.get("Importance", "Normal"),
        })

    print(f"Processed {len(processed)} authored emails (excluded noise/auto)")
    return processed


def classify_all(
    emails: list[dict],
    directs: set[str],
    peers: set[str],
    management: set[str],
    external_domains: set[str],
) -> dict[str, list[dict]]:
    """Classify all emails into audience buckets."""
    buckets: dict[str, list[dict]] = {
        "directs": [], "peers": [], "management": [],
        "broad_group": [], "broad_with_mgmt": [],
        "external": [], "other": [],
    }

    for email in emails:
        audience = classify_audience(
            email["to"], email["cc"], email["n_recip"],
            directs, peers, management, external_domains,
        )
        buckets[audience].append(email)

    for aud, msgs in buckets.items():
        if msgs:
            print(f"  {aud}: {len(msgs)} emails")

    return buckets


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser(description="Extract writer's voice profile from sent emails")
    parser.add_argument("--fetch", action="store_true", help="Fetch and cache sent emails")
    parser.add_argument("--analyze", action="store_true", help="Analyze cached emails (requires prior --fetch)")
    parser.add_argument("--all", action="store_true", help="Fetch + analyze + save profile")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without saving")
    parser.add_argument("--days", type=int, default=90, help="Days of history to fetch (default: 90)")
    parser.add_argument("--max", type=int, default=300, help="Max emails to fetch (default: 300)")
    args = parser.parse_args()

    if not any([args.fetch, args.analyze, args.all, args.dry_run]):
        parser.print_help()
        return

    # ET-4: Clean up stale cache before any operation
    _cleanup_stale_cache()

    if args.fetch or args.all:
        print(f"\n📬 Fetching sent emails (past {args.days} days, max {args.max})...")
        raw = fetch_sent_emails(days=args.days, max_count=args.max)
        processed = process_emails(raw)

        # Get contact lists from triage profile
        profile = load_triage_profile()
        directs = set()
        peers_set = set()
        mgmt = set()
        ext_domains = set()

        if profile:
            for c in profile.get("vip_contacts", []):
                alias = c.get("alias", "").lower()
                if alias:
                    mgmt.add(alias)
            for c in profile.get("tier1_contacts", []):
                alias = c.get("alias", "").lower()
                role = c.get("role", "").lower()
                if alias:
                    if "direct" in role:
                        directs.add(alias)
                    elif "manager" in role or "lead" in role or "director" in role:
                        mgmt.add(alias)
                    else:
                        peers_set.add(alias)

        # Classify
        print("\n📊 Classifying by audience...")
        buckets = classify_all(processed, directs, peers_set, mgmt, ext_domains)

        # Cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(buckets, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Cached to {CACHE_FILE}")

    if args.analyze or args.all:
        if not CACHE_FILE.exists():
            print("ERROR: No cached emails. Run with --fetch first.")
            sys.exit(1)

        with open(CACHE_FILE, encoding="utf-8") as f:
            buckets = json.load(f)

        print("\n🔍 Voice Analysis Summary:")
        print("=" * 60)
        for audience, msgs in buckets.items():
            if audience == "other" or not msgs:
                continue
            bodies = [m["body"] for m in msgs]
            avg_len = sum(len(b.split()) for b in bodies) / max(len(bodies), 1)
            print(f"\n  {audience.upper()} ({len(msgs)} emails, avg {avg_len:.0f} words)")
            for m in msgs[:3]:
                preview = m["body"][:80].replace("\n", " ")
                print(f"    • [{m['date'][:10]}] {preview}...")

        if not args.dry_run and args.all:
            # Copy template as starting point
            if TEMPLATE_PATH.exists():
                PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                if not VOICE_PROFILE_PATH.exists():
                    shutil.copy(TEMPLATE_PATH, VOICE_PROFILE_PATH)
                    print(f"\n📝 Created voice profile template at {VOICE_PROFILE_PATH}")
                    print("   → Edit this file with extracted voice patterns, or use the")
                    print("     pre-built voice profile from defaults/")
                else:
                    print(f"\n✅ Voice profile already exists at {VOICE_PROFILE_PATH}")

            # ET-4: Delete cache after successful analysis (contains email bodies)
            if CACHE_FILE.exists():
                try:
                    CACHE_FILE.unlink()
                    print("  🧹 Deleted voice email cache (sensitive data cleaned)")
                except OSError:
                    pass

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
