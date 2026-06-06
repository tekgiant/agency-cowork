"""Draft composer — creates safe reply drafts for triaged emails.

Safety-first design:
  - Drafts are created as NEW messages (not via Reply API) to prevent accidental sends
  - To/CC fields are left BLANK — recipients are listed in the body header for copy/paste
  - Subject is prefixed with "Re: " and includes [DRAFT] tag

Two draft modes:
  1. Confident reply: Full draft body when enough context exists (clear ask, known topic)
  2. Structured scaffold: TODOs + open questions when context is insufficient

Usage (from triage engine or agent):
    from scripts.draft_composer import DraftComposer
    composer = DraftComposer(mail_client)
    draft = composer.create_reply_draft(original_msg, body_html="<p>Thanks...</p>")
    draft = composer.create_scaffold_draft(original_msg, todos=["Review attachment"], questions=["Timeline?"])
"""

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, ".")

from scripts.mail_client import MailClient, get_sender_email, get_sender_name, build_outlook_deeplink


# --- Recipient Formatting ---

def _format_recipients_html(msg: dict) -> str:
    """Format original To/CC recipients as an HTML block for the draft body header."""
    lines = []

    # To recipients
    to_recips = msg.get("ToRecipients", [])
    if to_recips:
        to_parts = []
        for r in to_recips:
            name = r.get("EmailAddress", {}).get("Name", "")
            email = r.get("EmailAddress", {}).get("Address", "")
            display = f"{html.escape(name)} &lt;{html.escape(email)}&gt;" if name else html.escape(email)
            to_parts.append(display)
        lines.append(f"<b>To:</b> {'; '.join(to_parts)}")

    # CC recipients
    cc_recips = msg.get("CcRecipients", [])
    if cc_recips:
        cc_parts = []
        for r in cc_recips:
            name = r.get("EmailAddress", {}).get("Name", "")
            email = r.get("EmailAddress", {}).get("Address", "")
            display = f"{html.escape(name)} &lt;{html.escape(email)}&gt;" if name else html.escape(email)
            cc_parts.append(display)
        lines.append(f"<b>CC:</b> {'; '.join(cc_parts)}")

    return "<br/>".join(lines)


def _format_original_quote(msg: dict) -> str:
    """Format the original email as a quoted block for the draft."""
    sender = get_sender_name(msg) or get_sender_email(msg)
    received = msg.get("ReceivedDateTime", "")[:16].replace("T", " ")
    subject = html.escape(msg.get("Subject", ""))

    # Use full body if available, otherwise body preview
    body_content = ""
    body = msg.get("Body", {})
    if body.get("Content"):
        body_content = body["Content"]
    else:
        body_content = f"<p>{html.escape(msg.get('BodyPreview', ''))}</p>"

    return (
        f'<div style="border-left: 2px solid #ccc; padding-left: 12px; margin-top: 16px; color: #555;">'
        f'<p><b>From:</b> {html.escape(sender)}<br/>'
        f'<b>Sent:</b> {received} UTC<br/>'
        f'<b>Subject:</b> {subject}</p>'
        f'{body_content}'
        f'</div>'
    )


# --- Draft Builder ---

class DraftComposer:
    """Creates safe email drafts via the Outlook REST API."""

    def __init__(self, client: Optional[MailClient] = None):
        self.client = client or MailClient()

    def _create_draft(self, subject: str, body_html: str) -> dict:
        """Create a draft message with blank recipients via OWA REST API.

        POST /api/v2.0/me/messages creates a draft in the Drafts folder.
        """
        from scripts.mail_client import API_BASE

        payload = {
            "Subject": subject,
            "Body": {
                "ContentType": "HTML",
                "Content": body_html,
            },
            "ToRecipients": [],
            "CcRecipients": [],
            "Importance": "Normal",
        }

        url = f"{API_BASE}/messages"
        resp = self.client._request("POST", url, json_body=payload)
        return resp.json()

    def create_reply_draft(
        self,
        original_msg: dict,
        body_html: str,
        include_original: bool = True,
    ) -> dict:
        """Create a confident reply draft with full response body.

        Args:
            original_msg: The original email message (with full Body if available)
            body_html: The HTML reply body content
            include_original: Whether to include the original email as a quote

        Returns:
            Created draft message dict from API.
        """
        subject = original_msg.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build the full draft body
        parts = []

        # Recipients header (for copy/paste)
        recip_block = _format_recipients_html(original_msg)
        if recip_block:
            parts.append(
                f'<div style="background: #f0f4f8; padding: 10px 14px; border-radius: 6px; '
                f'margin-bottom: 16px; font-size: 13px; font-family: Segoe UI, sans-serif;">'
                f'<b>📋 Copy recipients before sending:</b><br/>{recip_block}'
                f'</div>'
            )

        # Reply body
        parts.append(body_html)

        # Original email quote
        if include_original:
            parts.append("<hr/>")
            parts.append(_format_original_quote(original_msg))

        full_body = "\n".join(parts)
        draft = self._create_draft(subject, full_body)

        print(f"  📝 Draft created: {subject[:60]}")
        return draft

    def create_scaffold_draft(
        self,
        original_msg: dict,
        todos: Optional[list[str]] = None,
        questions: Optional[list[str]] = None,
        context_notes: Optional[str] = None,
        include_original: bool = True,
    ) -> dict:
        """Create a structured scaffold draft with TODOs and open questions.

        Used when there isn't enough context for a confident reply.

        Args:
            original_msg: The original email message
            todos: Action items to address before replying
            questions: Open questions that need answers
            context_notes: Brief notes about what's known / needed
            include_original: Whether to include the original email as a quote

        Returns:
            Created draft message dict from API.
        """
        subject = original_msg.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        sender = get_sender_name(original_msg) or get_sender_email(original_msg)

        parts = []

        # Recipients header
        recip_block = _format_recipients_html(original_msg)
        if recip_block:
            parts.append(
                f'<div style="background: #f0f4f8; padding: 10px 14px; border-radius: 6px; '
                f'margin-bottom: 16px; font-size: 13px; font-family: Segoe UI, sans-serif;">'
                f'<b>📋 Copy recipients before sending:</b><br/>{recip_block}'
                f'</div>'
            )

        # Scaffold body
        parts.append(
            f'<div style="font-family: Segoe UI, sans-serif; font-size: 14px;">'
            f'<p style="color: #888;">⚠️ <i>Draft scaffold — review and complete before sending</i></p>'
        )

        # Greeting placeholder
        parts.append(f"<p>Hi {html.escape(sender.split()[0] if sender else '')},</p>")
        parts.append("<p>[Your reply here]</p>")

        # TODOs
        if todos:
            parts.append('<p><b>📌 TODOs before sending:</b></p><ul>')
            for t in todos:
                parts.append(f"<li>☐ {html.escape(t)}</li>")
            parts.append("</ul>")

        # Open questions
        if questions:
            parts.append('<p><b>❓ Open questions to resolve:</b></p><ul>')
            for q in questions:
                parts.append(f"<li>{html.escape(q)}</li>")
            parts.append("</ul>")

        # Context notes
        if context_notes:
            parts.append(
                f'<p><b>📝 Context:</b><br/>'
                f'<span style="color: #555;">{html.escape(context_notes)}</span></p>'
            )

        parts.append("</div>")

        # Original email quote
        if include_original:
            parts.append("<hr/>")
            parts.append(_format_original_quote(original_msg))

        full_body = "\n".join(parts)
        draft = self._create_draft(subject, full_body)

        print(f"  📝 Scaffold draft created: {subject[:60]}")
        return draft


def create_drafts_for_results(
    results: list[dict],
    client: Optional[MailClient] = None,
    profile: Optional[dict] = None,
    dry_run: bool = False,
    drafted_ids: Optional[dict] = None,
) -> list[dict]:
    """Create drafts for actionable triage results.

    Called by the triage engine after classification. For each urgent/needs_response
    item, fetches the full email body and creates an appropriate draft.

    Args:
        results: List of triage result dicts (from TriageResult.actionable_items)
        client: MailClient instance (creates one if None)
        profile: Triage profile (for voice/preference settings)
        dry_run: If True, log but don't create drafts
        drafted_ids: Dict of message_id → draft info for already-drafted emails

    Returns:
        List of dicts with draft creation results.
    """
    if not client:
        client = MailClient()
    if drafted_ids is None:
        drafted_ids = {}

    composer = DraftComposer(client)
    prefs = (profile or {}).get("preferences", {})
    draft_mode = prefs.get("draft_mode", "tier1_only")

    drafts_created = []

    for item in results:
        msg_id = item.get("message_id", "")
        category = item.get("category", "")
        tier = item.get("tier", 99)

        # Respect draft_mode preference
        if draft_mode == "never":
            continue
        if draft_mode == "tier1_only" and tier > 1:
            continue
        # draft_mode == "all" → draft for everything actionable

        if not msg_id:
            continue

        # Skip if draft already created for this message
        if msg_id in drafted_ids:
            print(f"  \u23ed\ufe0f Draft already exists for: {item.get('subject', '')[:50]}")
            drafts_created.append({
                "message_id": msg_id,
                "conversation_id": item.get("conversation_id", ""),
                "subject": item.get("subject", ""),
                "type": "already_drafted",
                "draft_id": drafted_ids[msg_id].get("draft_id", "") if isinstance(drafted_ids[msg_id], dict) else "",
            })
            continue

        # Skip if another message in the same conversation already has a draft
        conv_id = item.get("conversation_id", "")
        if conv_id and drafted_ids:
            existing_conv_draft = None
            for did, dinfo in drafted_ids.items():
                if isinstance(dinfo, dict) and dinfo.get("conversation_id") == conv_id:
                    existing_conv_draft = dinfo
                    break
            if existing_conv_draft:
                print(f"  \u23ed\ufe0f Thread already has draft: {item.get('subject', '')[:50]}")
                drafts_created.append({
                    "message_id": msg_id,
                    "conversation_id": conv_id,
                    "subject": item.get("subject", ""),
                    "type": "already_drafted",
                    "draft_id": existing_conv_draft.get("draft_id", ""),
                })
                continue

        try:
            # Fetch full message body for context
            full_msg = client.get_message(msg_id, include_body=True)

            subject = full_msg.get("Subject", "")
            body_preview = full_msg.get("BodyPreview", "")
            signals = item.get("signals", [])

            if dry_run:
                print(f"  [dry-run] Would create draft for: {subject[:50]}")
                drafts_created.append({
                    "message_id": msg_id,
                    "subject": subject,
                    "type": "dry_run",
                })
                continue

            # Determine draft type based on available context signals
            has_clear_ask = any(s in signals for s in [
                "response_keywords", "urgent_keywords", "deadline",
                "mention", "urgent_subject_tag",
            ])

            if has_clear_ask and category == "needs_response":
                # Scaffold with contextual hints extracted from the email
                todos = _extract_todos(full_msg, signals)
                questions = _extract_questions(full_msg)
                draft = composer.create_scaffold_draft(
                    full_msg,
                    todos=todos,
                    questions=questions,
                    context_notes=f"Category: {category} | Tier: {tier} | Signals: {', '.join(signals or [])}",
                )
                draft_type = "scaffold"
            else:
                # Minimal scaffold for urgent or low-context items
                draft = composer.create_scaffold_draft(
                    full_msg,
                    todos=["Review email and determine appropriate response"],
                    questions=_extract_questions(full_msg),
                    context_notes=f"Category: {category} | Tier: {tier} | Signals: {', '.join(signals or [])}",
                )
                draft_type = "scaffold"

            drafts_created.append({
                "message_id": msg_id,
                "conversation_id": item.get("conversation_id", ""),
                "draft_id": draft.get("Id", ""),
                "subject": subject,
                "type": draft_type,
            })

            # Tag original email with "📝 Response Drafted" category
            try:
                existing_cats = list(full_msg.get("Categories") or [])
                drafted_label = "📝 Response Drafted"
                if drafted_label not in existing_cats:
                    existing_cats.append(drafted_label)
                    client.update_message(msg_id, {"Categories": existing_cats})
            except Exception as tag_err:
                print(f"  ⚠️ Failed to tag '{subject[:40]}' with draft category: {tag_err}")

        except Exception as e:
            print(f"  ❌ Failed to create draft for {msg_id[:20]}...: {e}")
            drafts_created.append({
                "message_id": msg_id,
                "subject": item.get("subject", ""),
                "type": "error",
                "error": str(e),
            })

    return drafts_created


def _extract_todos(msg: dict, signals: list[str]) -> list[str]:
    """Extract action items from the email content and signals."""
    todos = []
    body_preview = msg.get("BodyPreview", "").lower()

    if "deadline" in signals:
        todos.append("Check and confirm deadline")
    if "response_keywords" in signals:
        todos.append("Address the direct ask / question")
    if msg.get("HasAttachments"):
        todos.append("Review attachment(s)")
    if "please review" in body_preview:
        todos.append("Review the referenced document or proposal")
    if "approve" in body_preview or "approval" in body_preview:
        todos.append("Provide approval or feedback")
    if "schedule" in body_preview or "meeting" in body_preview:
        todos.append("Check calendar availability")

    if not todos:
        todos.append("Review and respond to sender's request")

    return todos


def _extract_questions(msg: dict) -> list[str]:
    """Extract open questions that need answers before replying."""
    questions = []
    body_preview = msg.get("BodyPreview", "")

    # Look for question marks in the preview
    sentences = body_preview.replace("?", "?\n").split("\n")
    for s in sentences:
        s = s.strip()
        if s.endswith("?") and len(s) > 15 and len(s) < 200:
            questions.append(s)

    if not questions:
        questions.append("What is the expected response / next step?")

    return questions[:5]  # Cap at 5 questions


# --- CLI ---

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Draft Composer — create safe reply drafts")
    parser.add_argument("--message-id", required=True, help="Graph message ID to draft a reply for")
    parser.add_argument("--mode", choices=["reply", "scaffold"], default="scaffold",
                        help="Draft mode: 'reply' (full body) or 'scaffold' (TODOs + questions)")
    parser.add_argument("--body", help="HTML body content (for reply mode)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created")
    args = parser.parse_args()

    client = MailClient()
    composer = DraftComposer(client)

    msg = client.get_message(args.message_id, include_body=True)
    subject = msg.get("Subject", "")
    print(f"Original: {subject}")
    print(f"From: {get_sender_name(msg)} <{get_sender_email(msg)}>")

    if args.dry_run:
        print(f"\n[dry-run] Would create {args.mode} draft for: {subject}")
        print(f"Recipients block:\n{_format_recipients_html(msg)}")
        sys.exit(0)

    if args.mode == "reply" and args.body:
        draft = composer.create_reply_draft(msg, body_html=args.body)
    else:
        todos = _extract_todos(msg, [])
        questions = _extract_questions(msg)
        draft = composer.create_scaffold_draft(msg, todos=todos, questions=questions)

    print(f"\n✅ Draft created: {draft.get('Id', '')[:30]}...")
