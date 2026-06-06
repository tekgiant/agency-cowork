"""Triage report — Teams summary formatting + Todo sync orchestration.

Generates a Teams-ready summary from triage results and optionally
creates Todo tasks for urgent/needs_response items.

Usage:
    from scripts.triage_report import post_triage_summary
    post_triage_summary(result, profile)
"""

import html
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from scripts.triage_engine import TriageResult, format_summary


def format_teams_html(result: TriageResult) -> str:
    """Format triage results as Teams-compatible HTML.

    Uses ConversationId-based dedup to collapse thread replies into a
    single entry per conversation (keeping the newest or most urgent).
    """
    html_parts = []

    # Build draft link lookup: message_id -> draft deeplink
    draft_links = {}
    for d in (result.draft_results or []):
        if d.get("draft_id") and d.get("message_id") and d.get("type") != "error":
            from scripts.mail_client import build_outlook_deeplink
            draft_links[d["message_id"]] = build_outlook_deeplink(d["draft_id"])

    # Header
    ts = result.timestamp[:16].replace("T", " ")
    html_parts.append(f"<h3>📬 Email Triage -- {ts} UTC</h3>")
    html_parts.append(f"<p>{result.summary_line()}</p>")

    if not result.actionable_items:
        html_parts.append("<p>No urgent or action-required emails.</p>")
        return "\n".join(html_parts)

    # Dedup by conversation thread for display
    deduped = result.deduplicated_results(
        categories=["urgent", "needs_response"]
    )
    urgent_deduped = [r for r in deduped if r["category"] == "urgent"]
    nr_deduped = [r for r in deduped if r["category"] == "needs_response"]

    def _render_item(r):
        contact = f" ({html.escape(r['contact_name'])})" if r.get("contact_name") else ""
        link = f' <a href="{html.escape(r["web_link"])}">Open</a>' if r.get("web_link") else ""
        draft_link = draft_links.get(r.get("message_id"), "")
        draft_html = f' | <a href="{html.escape(draft_link)}">Draft</a>' if draft_link else ""
        return (f"<li><b>{html.escape(r['sender'])}{contact}</b>: "
                f"{html.escape(r['subject'])}{link}{draft_html}</li>")

    if urgent_deduped:
        html_parts.append(f"<h4>Urgent ({len(urgent_deduped)})</h4><ul>")
        for r in urgent_deduped:
            html_parts.append(_render_item(r))
        html_parts.append("</ul>")

    if nr_deduped:
        html_parts.append(f"<h4>Needs Response ({len(nr_deduped)})</h4><ul>")
        for r in nr_deduped:
            html_parts.append(_render_item(r))
        html_parts.append("</ul>")

    # Thread dedup note
    raw_actionable = len(result.urgent_items) + len(result.needs_response_items)
    deduped_actionable = len(urgent_deduped) + len(nr_deduped)
    if deduped_actionable < raw_actionable:
        html_parts.append(
            f"<p><i>{raw_actionable - deduped_actionable} duplicate thread "
            f"replies collapsed</i></p>"
        )

    # Stats footer
    fyi_count = result.stats.get("fyi", 0)
    noise_count = result.stats.get("noise", 0)
    archive_count = result.stats.get("archive", 0)
    draft_count = len(draft_links)
    draft_note = f", {draft_count} draft(s) ready" if draft_count else ""
    html_parts.append(
        f"<p><i>Also: {fyi_count} FYI, {noise_count} noise, "
        f"{archive_count} archived{draft_note}</i></p>"
    )

    # Injection warnings
    if result.injection_flags:
        html_parts.append(
            f"<p><b>{len(result.injection_flags)} email(s) flagged for "
            f"prompt injection</b></p>"
        )

    return "\n".join(html_parts)


def format_teams_text(result: TriageResult) -> str:
    """Format triage results as plain text for Teams."""
    return format_summary(result, verbose=False)


def sync_to_todo(result: TriageResult, profile: dict) -> dict:
    """Create Todo tasks for urgent and needs_response items.

    Returns dict with created/skipped counts.
    """
    prefs = profile.get("preferences", {})
    if not prefs.get("todo_enabled", True):
        return {"created": 0, "skipped": 0, "disabled": True}

    try:
        from scripts.todo_sync import sync_batch
    except ImportError:
        print("  ⚠ todo_sync not available, skipping Todo sync")
        return {"created": 0, "skipped": 0, "error": "import_error"}

    # Build triage items for todo_sync
    items = []
    for r in result.actionable_items:
        items.append({
            "message_id": r["message_id"],
            "subject": r["subject"],
            "sender": r["sender"],
            "sender_email": r["sender_email"],
            "received": r["received"],
            "category": r["category"],
            "web_link": r.get("web_link", ""),
        })

    if not items:
        return {"created": 0, "skipped": 0}

    try:
        stats = sync_batch(items, folder_name=prefs.get("todo_folder", "Email Triage"))
        return stats
    except Exception as e:
        print(f"  ⚠ Todo sync error: {e}")
        return {"created": 0, "skipped": 0, "error": str(e)}


def generate_report(result: TriageResult, profile: dict,
                    output_format: str = "text") -> str:
    """Generate a triage report in the specified format.

    Args:
        result: TriageResult from triage engine
        profile: Triage profile
        output_format: "text", "html", or "json"

    Returns:
        Formatted report string.
    """
    if output_format == "html":
        return format_teams_html(result)
    elif output_format == "json":
        return json.dumps({
            "timestamp": result.timestamp,
            "summary": result.summary_line(),
            "stats": result.stats,
            "urgent": result.urgent_items,
            "needs_response": result.needs_response_items,
            "new_count": result.new_count,
            "skipped": result.skipped_count,
            "errors": result.error_count,
        }, indent=2, default=str)
    else:
        return format_summary(result, verbose=True)
