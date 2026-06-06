"""Outlook REST API v2.0 mail client — deterministic email fetching.

Uses the same OWA bearer token as todo_auth.py (Mail.ReadWrite scope).
Provides deterministic inbox queries via OData filters, unlike the
AI-powered mail-SearchMessages MCP which can miss emails.

Usage:
    from scripts.mail_client import MailClient
    client = MailClient()
    emails = client.list_messages(since="2026-03-16T00:00:00Z")
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

sys.path.insert(0, ".")
from scripts.todo_auth import get_token, ensure_token

API_BASE = "https://outlook.office365.com/api/v2.0/me"

# Fields to fetch (minimize payload)
DEFAULT_SELECT = (
    "Id,Subject,Sender,ToRecipients,CcRecipients,"
    "Importance,IsRead,ReceivedDateTime,BodyPreview,"
    "ConversationId,HasAttachments,WebLink,Categories,"
    "Flag,IsDraft"
)

# Full body select (for content analysis)
FULL_SELECT = DEFAULT_SELECT + ",Body"


class MailClient:
    """Deterministic Outlook REST API v2.0 mail client."""

    # ET-7: Email address validation for OData filter safety
    _EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

    @staticmethod
    def _validate_email(email: str) -> str:
        """Validate email address format to prevent OData filter injection."""
        if not MailClient._EMAIL_PATTERN.match(email):
            raise ValueError(f"Invalid email address format: {email!r}")
        # Extra safety: reject any OData/SQL metacharacters
        if any(c in email for c in ("'", '"', ";", "(", ")", "$")):
            raise ValueError(f"Email contains disallowed characters: {email!r}")
        return email

    def __init__(self, max_retries: int = 3):
        self._token: str | None = None
        self._max_retries = max_retries

    def _headers(self) -> dict:
        if not self._token:
            self._token = get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        json_body: dict | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Make an API request with retry and token refresh."""
        last_err = None
        backoff = [5, 15, 45]

        for attempt in range(self._max_retries):
            try:
                resp = requests.request(
                    method, url, headers=self._headers(),
                    json=json_body, timeout=timeout,
                )

                if resp.status_code == 401:
                    # Token expired — refresh and retry
                    ensure_token()
                    self._token = get_token()
                    continue

                if resp.status_code == 429:
                    # Throttled — back off
                    retry_after = int(resp.headers.get("Retry-After", backoff[min(attempt, 2)]))
                    time.sleep(retry_after)
                    continue

                if resp.status_code >= 500:
                    # Server error — retry with backoff
                    time.sleep(backoff[min(attempt, 2)])
                    continue

                resp.raise_for_status()
                return resp

            except requests.exceptions.Timeout:
                last_err = f"Timeout after {timeout}s"
                time.sleep(backoff[min(attempt, 2)])
            except requests.exceptions.ConnectionError as e:
                last_err = str(e)
                time.sleep(backoff[min(attempt, 2)])

        raise RuntimeError(f"Failed after {self._max_retries} attempts: {last_err}")

    def list_messages(
        self,
        since: str | None = None,
        top: int = 50,
        folder: str = "inbox",
        select: str = DEFAULT_SELECT,
        filter_expr: str | None = None,
        include_body: bool = False,
        max_pages: int = 10,
    ) -> list[dict]:
        """Fetch messages from a folder with deterministic OData filtering.

        Args:
            since: ISO 8601 datetime — fetch emails received after this time
            top: Max results per page (max 50)
            folder: Mail folder (inbox, sentitems, drafts, etc.)
            select: OData $select fields
            filter_expr: Custom OData $filter (overrides `since`)
            include_body: Include full Body field
            max_pages: Max pages to follow (safety limit)

        Returns:
            List of message objects, newest first.
        """
        if include_body:
            select = FULL_SELECT

        params = {
            "$orderby": "ReceivedDateTime desc",
            "$top": min(top, 50),
            "$select": select,
        }

        if filter_expr:
            params["$filter"] = filter_expr
        elif since:
            # Normalize timestamp to OData-compatible format (no microseconds)
            ts = since.replace("+00:00", "Z")
            if "." in ts:
                ts = ts.split(".")[0] + "Z"
            if not ts.endswith("Z"):
                ts = ts + "Z"
            params["$filter"] = f"ReceivedDateTime ge {ts}"

        url = f"{API_BASE}/mailfolders/{folder}/messages"
        all_messages = []
        page = 0

        while url and page < max_pages:
            resp = self._request("GET", url + "?" + "&".join(
                f"{k}={v}" for k, v in params.items()
            ) if page == 0 else url)

            data = resp.json()
            messages = data.get("value", [])
            all_messages.extend(messages)

            # Follow pagination
            url = data.get("@odata.nextLink")
            params = {}  # nextLink includes params
            page += 1

        return all_messages

    def get_message(self, message_id: str, include_body: bool = True) -> dict:
        """Get a single message by ID."""
        select = FULL_SELECT if include_body else DEFAULT_SELECT
        url = f"{API_BASE}/messages('{message_id}')?$select={select}"
        resp = self._request("GET", url)
        return resp.json()

    def update_categories(self, message_id: str, categories: list[str]) -> dict:
        """Set categories on a message (for triage labeling)."""
        url = f"{API_BASE}/messages('{message_id}')"
        resp = self._request("PATCH", url, json_body={"Categories": categories})
        return resp.json()

    def set_importance(self, message_id: str, importance: str = "High") -> dict:
        """Set importance on a message (Normal, Low, High)."""
        url = f"{API_BASE}/messages('{message_id}')"
        resp = self._request("PATCH", url, json_body={"Importance": importance})
        return resp.json()

    def flag_message(self, message_id: str, flag_status: str = "Flagged") -> dict:
        """Set flag on a message (NotFlagged, Flagged, Complete)."""
        url = f"{API_BASE}/messages('{message_id}')"
        resp = self._request("PATCH", url, json_body={
            "Flag": {"FlagStatus": flag_status}
        })
        return resp.json()

    def update_message(self, message_id: str, patches: dict) -> dict:
        """Apply arbitrary PATCH fields to a message (categories, importance, flag, etc.)."""
        url = f"{API_BASE}/messages('{message_id}')"
        resp = self._request("PATCH", url, json_body=patches)
        return resp.json()

    def list_messages_from_senders(
        self,
        sender_emails: list[str],
        since: str | None = None,
        top: int = 10,
    ) -> list[dict]:
        """Fetch messages from specific senders (for VIP watchdog).

        Uses OData $filter with OR conditions on Sender/EmailAddress/Address.
        ET-7: Email addresses are validated before OData filter interpolation.
        """
        if not sender_emails:
            return []

        # ET-7: Validate all email addresses before building OData filter
        validated = []
        for email in sender_emails:
            try:
                validated.append(self._validate_email(email))
            except ValueError as e:
                print(f"  ⚠️ Skipping invalid sender: {e}", file=sys.stderr)

        if not validated:
            return []

        conditions = [
            f"Sender/EmailAddress/Address eq '{email}'"
            for email in validated
        ]
        filter_expr = " or ".join(conditions)

        if since:
            filter_expr = f"ReceivedDateTime ge {since} and ({filter_expr})"

        return self.list_messages(
            filter_expr=filter_expr,
            top=top,
            select=DEFAULT_SELECT,
        )


# --- Helper functions for extracting email metadata ---

def get_sender_email(msg: dict) -> str:
    """Extract sender email address from message object."""
    sender = msg.get("Sender", {})
    return (sender.get("EmailAddress", {}).get("Address", "") or "").lower()


def get_sender_name(msg: dict) -> str:
    """Extract sender display name."""
    sender = msg.get("Sender", {})
    return sender.get("EmailAddress", {}).get("Name", "")


def get_sender_alias(msg: dict) -> str:
    """Extract alias from sender email (part before @)."""
    email = get_sender_email(msg)
    return email.split("@")[0] if "@" in email else ""


def get_to_emails(msg: dict) -> list[str]:
    """Extract To recipient emails."""
    return [
        (r.get("EmailAddress", {}).get("Address", "") or "").lower()
        for r in msg.get("ToRecipients", [])
    ]


def get_cc_emails(msg: dict) -> list[str]:
    """Extract CC recipient emails."""
    return [
        (r.get("EmailAddress", {}).get("Address", "") or "").lower()
        for r in msg.get("CcRecipients", [])
    ]


def is_user_in_to(msg: dict, user_email: str) -> bool:
    """Check if user is in the To line (not just CC)."""
    return user_email.lower() in get_to_emails(msg)


def is_user_in_cc_only(msg: dict, user_email: str) -> bool:
    """Check if user is in CC but not To."""
    email = user_email.lower()
    return email in get_cc_emails(msg) and email not in get_to_emails(msg)


def get_recipient_count(msg: dict) -> int:
    """Total number of recipients (To + CC)."""
    return len(msg.get("ToRecipients", [])) + len(msg.get("CcRecipients", []))


def build_outlook_deeplink(message_id: str) -> str:
    """Build an Outlook deep link URL from a REST API message ID.

    Uses the OWA inbox path format which works without a pre-existing
    session cookie (unlike deeplink/read/ which returns 401).
    """
    if not message_id:
        return ""
    from urllib.parse import quote
    encoded_id = quote(message_id, safe="")
    return f"https://outlook.office365.com/mail/inbox/id/{encoded_id}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Outlook REST API mail client")
    parser.add_argument("--since", help="Fetch emails since (ISO 8601)")
    parser.add_argument("--top", type=int, default=10, help="Max results")
    parser.add_argument("--sender", help="Filter by sender email")
    parser.add_argument("--vip", nargs="+", help="VIP sender emails to check")
    args = parser.parse_args()

    client = MailClient()

    if args.vip:
        print(f"Checking VIP emails from: {', '.join(args.vip)}")
        msgs = client.list_messages_from_senders(args.vip, since=args.since)
    else:
        msgs = client.list_messages(since=args.since, top=args.top)

    print(f"\n{len(msgs)} message(s):")
    for m in msgs:
        sender = get_sender_name(m) or get_sender_email(m)
        subj = m.get("Subject", "(no subject)")[:60]
        dt = m.get("ReceivedDateTime", "")[:19]
        imp = m.get("Importance", "Normal")
        imp_icon = "🔴" if imp == "High" else ""
        print(f"  {imp_icon} {dt}  {sender:30s}  {subj}")
