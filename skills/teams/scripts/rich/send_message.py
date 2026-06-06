"""CLI script to send rich messages via Microsoft Teams.

Supplements the MCP ``microsoft-teams`` server (which only supports plain text)
with rich formatting, @mentions, Adaptive Cards, and **file attachments**.

Conversation IDs and user MRIs are provided by the MCP ``microsoft-teams``
server (``ListChats``, ``ListChannels``, etc.) — this script only handles
the send.

Usage examples::

    # Rich text to a chat
    python -m scripts.rich.send_message \\
        --to "19:aaaaaaaa-..._bbbbbbbb-...@unq.gbl.spaces" \\
        --body "**Bold** and *italic* with a [link](https://example.com)"

    # Rich text to a channel (use --channel instead of --to)
    python -m scripts.rich.send_message \\
        --channel "19:KS6nGUz7cs...@thread.tacv2" \\
        --body "Status update" --subject "Weekly Update"

    # Send to a channel via Teams URL (extracts channel ID automatically)
    python -m scripts.rich.send_message \\
        --url "https://teams.microsoft.com/l/channel/19%3A...@thread.tacv2/General?groupId=..." \\
        --body "Hello from a URL!" --subject "Auto-parsed"

    # With an @mention (name + MRI from MCP)
    python -m scripts.rich.send_message \\
        --to "19:abc123@thread.v2" \\
        --body "Hey {mention}, check this" \\
        --mention-name "Alice Johnson" \\
        --mention-mri "8:orgid:aaaaaaaa-1111-2222-3333-444444444444"

    # Multiple @mentions (use {mention0}, {mention1}, ... placeholders)
    python -m scripts.rich.send_message \\
        --to "19:abc123@thread.v2" \\
        --body "{mention0} and {mention1}, please review" \\
        --mention-name "Bob Smith" --mention-mri "8:orgid:bbbbbbbb-1111-2222-3333-..." \\
        --mention-name "Alice Johnson" --mention-mri "8:orgid:aaaaaaaa-1111-2222-3333-..."

    # Adaptive Card from template
    python -m scripts.rich.send_message --to "19:abc@thread.v2" \\
        --card info-card --card-data '{"title":"Status","body":"All systems go"}'

    # Inline Adaptive Card JSON
    python -m scripts.rich.send_message --to "19:abc@thread.v2" \\
        --card-json '{"type":"AdaptiveCard","version":"1.4","body":[...]}'

    # Importance / subject (channels)
    python -m scripts.rich.send_message --channel "19:abc@thread.tacv2" \\
        --body "Release notes" --importance high --subject "v2.1 shipped"

    # File attachment (local file — uploads then sends)
    python -m scripts.rich.send_message \\
        --to "19:abc@thread.v2" \\
        --body "Here's the screenshot" \\
        --attach "C:\\Users\\me\\Pictures\\screenshot.png"

    # Attach an existing SharePoint / OneDrive file (no upload needed)
    python -m scripts.rich.send_message \\
        --to "19:abc@thread.v2" \\
        --body "See attached" \\
        --attach "https://contoso.sharepoint.com/sites/team/Shared%20Documents/report.xlsx"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path as _Path
from urllib.parse import unquote

from .auth import TeamsSession
from .api_client import (
    send_message as api_send_message,
    attach_and_send,
    attach_existing_and_send,
)
from .credential_scanner import scan_for_credentials
from .utils import (
    build_adaptive_card,
    build_card_from_template,
    build_mention_html,
    build_mention_property,
    markdown_to_teams_html,
)

# Shared chunking utility
import sys as _sys
_TEAMS_ROOT = _Path(__file__).resolve().parent.parent.parent
if str(_TEAMS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_TEAMS_ROOT))
from scripts.chunking import chunk_message, INTER_CHUNK_DELAY, DEFAULT_MAX_CHUNK


# ---------------------------------------------------------------------------
# Channel URL parsing
# ---------------------------------------------------------------------------

# Matches Teams channel URLs like:
# https://teams.microsoft.com/l/channel/19%3A...@thread.tacv2/ChannelName?groupId=<guid>&...
_CHANNEL_URL_RE = re.compile(
    r"https://teams\.microsoft\.com/l/channel/"
    r"(?P<channel_id>[^/]+)"          # URL-encoded channel ID
    r"/[^?]*"                          # channel display name slug
    r"\?.*?groupId=(?P<group_id>[0-9a-f-]+)",
    re.IGNORECASE,
)


def parse_channel_url(url: str) -> tuple[str, str]:
    """Extract (channel_id, team_id) from a Teams channel URL.

    Returns:
        Tuple of (decoded channel ID, group/team ID).

    Raises:
        ValueError: If the URL doesn't match the expected Teams channel format.
    """
    m = _CHANNEL_URL_RE.search(url)
    if not m:
        raise ValueError(
            f"Could not parse Teams channel URL: {url}\n"
            "Expected format: https://teams.microsoft.com/l/channel/<id>/Name?groupId=<guid>"
        )
    return unquote(m.group("channel_id")), m.group("group_id")


# ---------------------------------------------------------------------------
# Credential guard logging
# ---------------------------------------------------------------------------

_PLUGIN_ROOT = _Path(__file__).resolve().parent.parent.parent  # scripts/rich -> scripts -> plugin root
_GUARD_LOG = _PLUGIN_ROOT / "logs" / "credential-guard.log"
_BLOCKED_DIR = _PLUGIN_ROOT / "logs" / "blocked-messages"


def _log_credential_block(conversation_id: str, scan_result) -> None:
    """Log a blocked send to the credential guard log file."""
    _GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
    _BLOCKED_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    types = ", ".join(f.type for f in scan_result.findings)
    with open(_GUARD_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] BLOCKED | to={conversation_id} | findings={types}\n")
    # Save redacted content for review
    safe_id = conversation_id.replace(":", "_").replace("/", "_")[:60]
    blocked_file = _BLOCKED_DIR / f"{ts.replace(':', '-')}_{safe_id}.txt"
    blocked_file.write_text(scan_result.redacted_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core send logic
# ---------------------------------------------------------------------------

async def send(
    to: str,
    body: str | None = None,
    *,
    mention_names: list[str] | None = None,
    mention_mris: list[str] | None = None,
    card_template: str | None = None,
    card_data_str: str | None = None,
    card_json_str: str | None = None,
    importance: str = "",
    subject: str = "",
    attach: str | None = None,
) -> dict:
    """Open a Teams browser session, build the rich message, and send it.

    Conversation IDs and user MRIs come from the MCP microsoft-teams server.

    Supports multiple @mentions via paired ``mention_names`` / ``mention_mris``
    lists.  Use ``{mention}`` (single) or ``{mention0}``, ``{mention1}``, etc.
    as placeholders in ``body``.
    """
    async with TeamsSession() as session:
        assert session.user is not None

        conversation_id = to

        # ── Build content HTML ───────────────────────────────────────
        mentions_list: list[dict] = []
        content_html = ""

        if body:
            content_html = markdown_to_teams_html(body)

        # ── Handle @mentions ─────────────────────────────────────────
        names = mention_names or []
        mris = mention_mris or []
        if len(names) != len(mris):
            raise ValueError(
                f"--mention-name and --mention-mri must be provided in equal "
                f"pairs (got {len(names)} names, {len(mris)} MRIs)"
            )

        for idx, (name, mri) in enumerate(zip(names, mris)):
            mention_html = build_mention_html(name, item_id=idx)
            mention_prop = build_mention_property(name, mri, item_id=idx)
            mentions_list.append(mention_prop)

            # Replace numbered placeholder {mention0}, {mention1}, ...
            numbered = f"{{mention{idx}}}"
            if numbered in content_html:
                content_html = content_html.replace(numbered, mention_html)
            elif idx == 0 and "{mention}" in content_html:
                # Legacy single-mention placeholder
                content_html = content_html.replace("{mention}", mention_html)
            elif not any(
                f"{{mention{i}}}" in content_html or (i == 0 and "{mention}" in content_html)
                for i in range(len(names))
            ) and idx == 0:
                # No placeholders at all — prepend all mentions
                all_htmls = " ".join(
                    build_mention_html(n, item_id=j)
                    for j, (n, _) in enumerate(zip(names, mris))
                )
                content_html = f"<p>{all_htmls}&nbsp;</p>" + content_html
                break  # already prepended all mentions

        # ── Handle Adaptive Card ─────────────────────────────────────
        cards_list: list[dict] = []

        if card_template:
            card_data = json.loads(card_data_str) if card_data_str else {}
            cards_list.append(build_card_from_template(card_template, card_data))
            # If no body was provided, use the card title as fallback text
            if not content_html:
                fallback = card_data.get("title", "Adaptive Card")
                content_html = f"<p>{fallback}</p>"

        if card_json_str:
            inline_card = json.loads(card_json_str)
            import uuid
            cards_list.append({"cardId": str(uuid.uuid4()), "card": inline_card})
            if not content_html:
                content_html = "<p>Adaptive Card</p>"

        if not content_html and not attach:
            raise ValueError("No message content: provide --body, --card, --card-json, or --attach")

        # Default fallback body when only attaching a file
        if not content_html and attach:
            if attach.startswith("https://"):
                # URL — extract filename from the URL
                from urllib.parse import unquote, urlparse
                fallback_name = unquote(urlparse(attach).path.rsplit("/", 1)[-1])
            else:
                from pathlib import Path as _P
                fallback_name = _P(attach).name
            content_html = f"<p>{fallback_name}</p>"

        # ── Credential Guard ────────────────────────────────────────
        scan_text = body or ""
        if subject:
            scan_text = f"{subject}\n{scan_text}"
        scan_result = scan_for_credentials(scan_text)
        if not scan_result.is_clean:
            findings_json = [
                {"type": f.type, "description": f.description, "preview": f.match_preview}
                for f in scan_result.findings
            ]
            _log_credential_block(conversation_id, scan_result)
            print(
                json.dumps(
                    {"blocked": True, "reason": "credentials_detected", "findings": findings_json},
                    indent=2,
                ),
                file=sys.stderr,
            )
            raise SystemExit(2)

        # ── Send (with or without attachment) ─────────────────────────
        if attach and attach.startswith("https://"):
            # Existing SharePoint / OneDrive file — reference only, no upload
            result = await attach_existing_and_send(
                session,
                conversation_id,
                content_html,
                attach,
                mentions=mentions_list or None,
                cards=cards_list or None,
                importance=importance.upper() if importance else "",
                subject=subject,
            )
        elif attach:
            result = await attach_and_send(
                session,
                conversation_id,
                content_html,
                attach,
                mentions=mentions_list or None,
                cards=cards_list or None,
                importance=importance.upper() if importance else "",
                subject=subject,
            )
        else:
            # Plain message (no attachment) — chunk if long
            can_chunk = not mentions_list and not cards_list
            if can_chunk and body and len(body) > DEFAULT_MAX_CHUNK:
                # Chunk on raw markdown, convert each chunk to HTML separately
                chunks = chunk_message(body)
                result = {}
                for i, chunk_text in enumerate(chunks):
                    chunk_html = markdown_to_teams_html(chunk_text)
                    result = await api_send_message(
                        session,
                        conversation_id,
                        chunk_html,
                        importance=importance.upper() if importance else "",
                        subject=subject if i == 0 else "",  # subject only on first
                    )
                    if i < len(chunks) - 1:
                        await asyncio.sleep(INTER_CHUNK_DELAY)
            else:
                result = await api_send_message(
                    session,
                    conversation_id,
                    content_html,
                    mentions=mentions_list or None,
                    cards=cards_list or None,
                    importance=importance.upper() if importance else "",
                    subject=subject,
                )
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a rich message via Microsoft Teams",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Destination (pick one):\n"
            "  --to ID          Chat or channel conversation ID\n"
            "  --channel ID     Channel ID (19:...@thread.tacv2)\n"
            "  --url URL        Teams channel URL (auto-extracts IDs)\n\n"
            "This tool supplements the MCP microsoft-teams server with\n"
            "rich formatting, @mentions, and Adaptive Cards."
        ),
    )

    # Destination — mutually exclusive: --to, --channel, or --url
    dest_group = parser.add_mutually_exclusive_group(required=True)
    dest_group.add_argument(
        "--to",
        help="Conversation ID — chat (19:...@unq.gbl.spaces) or channel (19:...@thread.tacv2)",
    )
    dest_group.add_argument(
        "--channel",
        help="Channel ID (19:...@thread.tacv2). Equivalent to --to but explicit for channels.",
    )
    dest_group.add_argument(
        "--url",
        help=(
            "Teams channel URL — channel ID and team ID are extracted automatically."
        ),
    )
    parser.add_argument(
        "--team",
        default="",
        help="Team ID (GUID). Optional metadata paired with --channel; not required for sending.",
    )
    parser.add_argument(
        "--body",
        default=None,
        help=(
            "Message body in Markdown. Converted to Teams HTML. "
            'Use {mention} (single) or {mention0}, {mention1}, ... as '
            'placeholders for @mentions.'
        ),
    )
    parser.add_argument(
        "--mention-name",
        action="append",
        default=None,
        dest="mention_names",
        help=(
            "Display name of a person to @mention. Can be repeated for "
            "multiple mentions (pair each with a --mention-mri)."
        ),
    )
    parser.add_argument(
        "--mention-mri",
        action="append",
        default=None,
        dest="mention_mris",
        help=(
            "MRI of a person to @mention (e.g. 8:orgid:<guid>). "
            "Must be paired with a --mention-name in the same order."
        ),
    )
    parser.add_argument(
        "--card",
        default=None,
        dest="card_template",
        help="Adaptive Card template name (e.g. info-card, action-card, table-card)",
    )
    parser.add_argument(
        "--card-data",
        default=None,
        help='JSON string of template variables, e.g. \'{"title":"Hi","body":"Hello"}\'',
    )
    parser.add_argument(
        "--card-json",
        default=None,
        help="Raw Adaptive Card JSON (inline, instead of using a template)",
    )
    parser.add_argument(
        "--attach",
        default=None,
        help=(
            "File to attach. Pass a local path to upload, or a SharePoint / "
            "OneDrive URL (https://...) to reference an existing file."
        ),
    )
    parser.add_argument(
        "--importance",
        default="",
        choices=["", "normal", "high", "urgent"],
        help="Message importance level (default: normal)",
    )
    parser.add_argument(
        "--subject",
        default="",
        help="Message subject (primarily used in channel posts)",
    )

    args = parser.parse_args()

    # Resolve destination conversation ID
    if args.url:
        channel_id, team_id = parse_channel_url(args.url)
        conversation_id = channel_id
        if not args.team:
            args.team = team_id
    elif args.channel:
        conversation_id = args.channel
    else:
        conversation_id = args.to

    result = asyncio.run(
        send(
            to=conversation_id,
            body=args.body,
            mention_names=args.mention_names,
            mention_mris=args.mention_mris,
            card_template=args.card_template,
            card_data_str=args.card_data,
            card_json_str=args.card_json,
            importance=args.importance,
            subject=args.subject,
            attach=args.attach,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
