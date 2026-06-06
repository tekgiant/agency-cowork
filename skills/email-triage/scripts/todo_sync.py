"""Triage-to-Todo sync — creates Todo tasks from email triage results.

This module bridges the email triage pipeline with Microsoft Todo.
It takes categorized emails and creates corresponding tasks with
email deep links, importance mapping, and due date logic.

Usage (from agent triage prompt):
    python -m scripts.todo_sync --urgent '{"subject":"...", "message_id":"...", "sender":"..."}'
    python -m scripts.todo_sync --needs-response '{"subject":"...", "message_id":"...", "sender":"..."}'
    python -m scripts.todo_sync --batch emails.json
    python -m scripts.todo_sync --summary
"""

import argparse
import html
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from scripts.todo_client import TodoClient

FOLDER_NAME = "Email Triage"

# Priority mapping: triage category → (importance, due_offset_days)
PRIORITY_MAP = {
    "urgent": ("High", 0),
    "needs_response": ("Normal", 2),
}


def _business_day_offset(start: datetime, days: int) -> str:
    """Add business days (skip weekends) and return YYYY-MM-DD."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    if days == 0:
        current = start
    return current.strftime("%Y-%m-%d")


def _build_body(email: dict) -> str:
    """Build task body with email link and metadata.

    ET-8: All dynamic content is HTML-escaped to prevent injection.
    """
    sender = html.escape(email.get("sender", "Unknown"))
    summary = html.escape(email.get("summary", ""))
    message_id = email.get("message_id", "")
    category = html.escape(email.get("category", ""))
    web_link = email.get("web_link", "")

    # Build Outlook deep link if we have a message_id but no web_link
    if not web_link and message_id:
        from urllib.parse import quote
        encoded_id = quote(message_id, safe="")
        web_link = f"https://outlook.office365.com/mail/inbox/id/{encoded_id}"

    parts = []
    if web_link:
        parts.append(f'<a href="{html.escape(web_link)}">Open in Outlook</a>')
    parts.append(f"<br/><b>From:</b> {sender}")
    if summary:
        parts.append(f"<br/><b>Summary:</b> {summary}")
    if category:
        parts.append(f"<br/><b>Category:</b> {category}")

    # Dedup marker (message_id is not user-visible, but still escape)
    if message_id:
        parts.append(f"<!-- msg_id:{html.escape(message_id)} -->")

    return "".join(parts)


def sync_email(client: TodoClient, folder_id: str, email: dict) -> dict | None:
    """Create a Todo task for a single triaged email. Returns task or None if dedup."""
    message_id = email.get("message_id", "")
    category = email.get("category", "urgent")
    subject = email.get("subject", "(no subject)")

    # Dedup check
    if message_id:
        existing = client.find_task_by_message_id(folder_id, message_id)
        if existing:
            return None  # Already exists

    importance, due_offset = PRIORITY_MAP.get(category, ("Normal", 2))
    due_date = _business_day_offset(datetime.now(), due_offset)
    body = _build_body(email)

    # Prefix with category indicator
    prefix = "🔴 " if category == "urgent" else "🟡 "
    task_subject = f"{prefix}{subject}"

    task = client.create_task(
        folder_id=folder_id,
        subject=task_subject,
        body=body,
        importance=importance,
        due_date=due_date,
    )
    return task


def sync_batch(emails: list[dict]) -> dict:
    """Sync a batch of triaged emails to Todo. Returns summary stats."""
    client = TodoClient()
    folder = client.get_or_create_folder(FOLDER_NAME)
    folder_id = folder["Id"]

    stats = {"created": 0, "skipped_dedup": 0, "errors": 0, "tasks": []}

    for email in emails:
        try:
            task = sync_email(client, folder_id, email)
            if task:
                stats["created"] += 1
                stats["tasks"].append({
                    "subject": task["Subject"],
                    "id": task["Id"],
                    "importance": task.get("Importance", "Normal"),
                })
            else:
                stats["skipped_dedup"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"Error syncing '{email.get('subject', '?')}': {e}", file=sys.stderr)

    return stats


def get_summary(client: TodoClient = None) -> dict:
    """Get current Todo summary for Teams posting."""
    if not client:
        client = TodoClient()

    folder = client.get_or_create_folder(FOLDER_NAME)
    stats = client.get_task_stats(folder["Id"])
    tasks = client.list_tasks(folder_id=folder["Id"], top=50)

    urgent = [t for t in tasks if t.get("Importance") == "High" and t.get("Status") != "Completed"]
    needs_resp = [t for t in tasks if t.get("Importance") != "High" and t.get("Status") != "Completed"]
    completed = [t for t in tasks if t.get("Status") == "Completed"]

    return {
        "total_open": len(urgent) + len(needs_resp),
        "urgent_count": len(urgent),
        "needs_response_count": len(needs_resp),
        "completed_count": len(completed),
        "urgent_subjects": [t["Subject"] for t in urgent[:5]],
        "needs_response_subjects": [t["Subject"] for t in needs_resp[:5]],
    }


def format_teams_section(summary: dict) -> str:
    """Format Todo summary as a Teams-ready markdown section."""
    lines = []
    total = summary["total_open"]

    if total == 0:
        lines.append("📋 **Todo:** No open tasks")
        return "\n".join(lines)

    lines.append(f"📋 **Todo Tasks:** {total} open")
    if summary["urgent_count"]:
        lines.append(f"  🔴 {summary['urgent_count']} urgent")
    if summary["needs_response_count"]:
        lines.append(f"  🟡 {summary['needs_response_count']} needs response")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Triage → Todo sync")
    parser.add_argument("--urgent", help="JSON email object to create as urgent task")
    parser.add_argument("--needs-response", dest="needs_response",
                        help="JSON email object to create as needs-response task")
    parser.add_argument("--batch", help="JSON file with array of email objects")
    parser.add_argument("--summary", action="store_true", help="Show current Todo summary")
    parser.add_argument("--teams-section", action="store_true", help="Output Teams-ready summary")

    args = parser.parse_args()

    if args.summary:
        summary = get_summary()
        print(json.dumps(summary, indent=2))
        return

    if args.teams_section:
        summary = get_summary()
        print(format_teams_section(summary))
        return

    emails = []

    if args.urgent:
        email = json.loads(args.urgent)
        email["category"] = "urgent"
        emails.append(email)

    if args.needs_response:
        email = json.loads(args.needs_response)
        email["category"] = "needs_response"
        emails.append(email)

    if args.batch:
        with open(args.batch, "r") as f:
            emails.extend(json.load(f))

    if not emails:
        parser.print_help()
        return

    stats = sync_batch(emails)
    print(f"Synced: {stats['created']} created, {stats['skipped_dedup']} dedup skipped, {stats['errors']} errors")
    for t in stats["tasks"]:
        print(f"  + {t['subject']}")


if __name__ == "__main__":
    main()
