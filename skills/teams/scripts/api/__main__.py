"""CLI entry point for the Teams direct API client.

Usage:
    cd skills/teams
    python -m scripts.api list-chats [--filter TOPIC] [--top N]
    python -m scripts.api list-messages --chat CHAT_ID [--top N]
    python -m scripts.api send-message --chat CHAT_ID --body "message" [--body-file FILE] [--markdown]
    python -m scripts.api post-channel --team TEAM_ID --channel CHANNEL_ID --body "message" [--body-file FILE] [--markdown]
    python -m scripts.api reply-channel --team TEAM_ID --channel CHANNEL_ID --message MSG_ID --body "reply" [--body-file FILE] [--markdown]
    python -m scripts.api channel-members --team TEAM_ID --channel CHANNEL_ID
    python -m scripts.api send-rich --chat CHAT_ID --body-file body.md
    python -m scripts.api send-rich --team TEAM_ID --channel CHANNEL_ID --body-file body.md
    python -m scripts.api send-rich --team TEAM_ID --channel CHANNEL_ID --message MSG_ID --body-file body.md
    python -m scripts.api list-teams
    python -m scripts.api list-channels [--team TEAM_ID]
    python -m scripts.api get-chat --chat CHAT_ID
    python -m scripts.api get-members --chat CHAT_ID
    python -m scripts.api sync-cache [--chats] [--teams] [--enrich-upns]

All output is JSON for easy parsing by the agent.
Chat operations use chatsvc REST API. Channel operations use Microsoft Graph API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from .client import TeamsApiClient
from .chats import list_chats, get_chat, get_chat_members, get_user_properties
from .messages import (
    list_messages, send_message, _load_markdown_body,
    post_channel_message, reply_to_channel_message, get_channel_members,
    list_thread_replies,
)
from .teams_channels import list_teams_and_channels, list_channels, list_channel_messages
from .sync_cache import (
    sync_all_from_api, sync_chats_from_api, sync_teams_from_api,
    sync_chats_from_json, sync_teams_from_json, enrich_upns,
)


def _json_out(data) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


async def _cmd_list_chats(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        chats = await list_chats(client, topic_filter=args.filter, top=args.top)
        _json_out({"count": len(chats), "chats": [c.to_dict() for c in chats]})


async def _cmd_list_messages(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        msgs = await list_messages(client, args.chat, top=args.top)
        _json_out({"count": len(msgs), "messages": [m.to_dict() for m in msgs]})


async def _cmd_send_message(args: argparse.Namespace) -> None:
    body = _load_markdown_body(args.body, args.body_file, args.markdown)
    async with TeamsApiClient() as client:
        result = await send_message(client, args.chat, body, html=not args.plain)
        _json_out({"status": "sent", "response": result})


async def _cmd_list_teams(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        teams, channels = await list_teams_and_channels(client)
        _json_out({
            "teamCount": len(teams),
            "channelCount": len(channels),
            "teams": [t.to_dict() for t in teams],
        })


async def _cmd_list_channels(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        channels = await list_channels(client, team_id=args.team)
        _json_out({"count": len(channels), "channels": [c.to_dict() for c in channels]})


async def _cmd_get_chat(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        data = await get_chat(client, args.chat)
        _json_out(data)


async def _cmd_get_members(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        members = await get_chat_members(client, args.chat)
        _json_out({
            "count": len(members),
            "members": [
                {"mri": m.mri, "displayName": m.display_name, "role": m.role}
                for m in members
            ],
        })


async def _cmd_user_props(args: argparse.Namespace) -> None:
    async with TeamsApiClient() as client:
        props = await get_user_properties(client)
        _json_out(props)


async def _cmd_sync_cache(args: argparse.Namespace) -> None:
    if args.from_stdin:
        # MCP fallback: read raw JSON from stdin and write to cache
        import sys as _sys
        raw = _sys.stdin.read()
        if args.chats and not args.teams:
            summary = sync_chats_from_json(raw)
        elif args.teams and not args.chats:
            summary = sync_teams_from_json(raw)
        else:
            # Auto-detect: if it has "chats" key, process as chats; if "channels", as teams
            data = json.loads(raw)
            summary = {}
            if "chats" in data:
                summary.update(sync_chats_from_json(raw))
            if "channels" in data:
                summary.update(sync_teams_from_json(raw))
            if not summary:
                summary = {"error": "No 'chats' or 'channels' key found in input"}
        _json_out({"status": "synced", "mode": "stdin", **summary})
    else:
        # Browser mode: connect via Playwright and fetch
        async with TeamsApiClient() as client:
            if args.chats and not args.teams:
                summary = await sync_chats_from_api(client)
            elif args.teams and not args.chats:
                summary = await sync_teams_from_api(client)
            else:
                summary = await sync_all_from_api(client)

            if args.enrich_upns:
                upn_summary = await enrich_upns(client)
                summary["upnEnrichment"] = upn_summary

            _json_out({"status": "synced", "mode": "browser", **summary})


async def _cmd_post_channel(args: argparse.Namespace) -> None:
    body = _load_markdown_body(args.body, args.body_file, args.markdown)
    # Graph API calls don't need the Playwright browser session
    client = TeamsApiClient()
    try:
        result = await post_channel_message(
            client, args.team, args.channel, body, html=not args.plain)
        _json_out({"status": "sent", "messageId": result.get("id"),
                    "channelId": args.channel})
    finally:
        await client.close()


async def _cmd_reply_channel(args: argparse.Namespace) -> None:
    body = _load_markdown_body(args.body, args.body_file, args.markdown)
    client = TeamsApiClient()
    try:
        result = await reply_to_channel_message(
            client, args.team, args.channel, args.message, body, html=not args.plain)
        _json_out({"status": "sent", "replyId": result.get("id"),
                    "parentMessageId": args.message, "channelId": args.channel})
    finally:
        await client.close()


async def _cmd_channel_members(args: argparse.Namespace) -> None:
    client = TeamsApiClient()
    try:
        members = await get_channel_members(client, args.team, args.channel)
        _json_out({"count": len(members), "members": members})
    finally:
        await client.close()


async def _cmd_get_thread(args: argparse.Namespace) -> None:
    """Retrieve all messages from a channel thread via chatsvc API."""
    client = TeamsApiClient()
    try:
        msgs = await list_thread_replies(
            client, args.channel, args.message, top=args.top)
        _json_out({
            "count": len(msgs),
            "channelId": args.channel,
            "threadMessageId": args.message,
            "messages": [m.to_dict() for m in msgs],
        })
    finally:
        await client.close()


async def _cmd_send_rich(args: argparse.Namespace) -> None:
    """High-level send: markdown file → Teams HTML → validate → send."""
    from pathlib import Path as _Path
    _teams_root = _Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_teams_root))
    from scripts.rich.utils import markdown_to_teams_html

    # Load markdown
    if args.body_file:
        md_text = _Path(args.body_file).read_text(encoding="utf-8").strip()
    elif args.body:
        md_text = args.body
    else:
        print(json.dumps({"error": "Either --body or --body-file required"}))
        sys.exit(1)

    # Convert to HTML
    html = markdown_to_teams_html(md_text)

    # Validate (optional but recommended)
    if not args.skip_validate:
        from scripts.rich.validate_message import validate_markdown
        vresult = validate_markdown(md_text)
        if not vresult.ok:
            print(json.dumps({"error": "Validation failed",
                              "issues": vresult.to_dict()["issues"]}))
            sys.exit(1)

    # Send based on target
    if args.chat:
        # Chat message via chatsvc
        from .auth import get_token_manager
        tm = get_token_manager()
        token = await tm.get_token()

        import httpx, urllib.parse, uuid
        from datetime import datetime, timezone
        from .client import CHATSVC_BASE, USER_MRI

        encoded = urllib.parse.quote(args.chat, safe="")
        url = f"{CHATSVC_BASE}/users/ME/conversations/{encoded}/messages"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        payload = {
            "id": "-1", "type": "Message", "conversationid": args.chat,
            "conversationLink": f"{CHATSVC_BASE}/users/ME/conversations/{encoded}",
            "from": USER_MRI, "composetime": now, "originalarrivaltime": now,
            "messagetype": "RichText/Html", "contenttype": "text", "content": html,
            "clientmessageid": str(uuid.uuid4().int)[:19],
            "imdisplayname": os.environ.get("TEAMS_DISPLAY_NAME", "Agent"),
            "properties": {"importance": "", "subject": "", "formatVariant": "TEAMS"},
        }
        headers = {"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                _json_out({"status": "sent", "target": args.chat,
                            "type": "chat", "httpStatus": resp.status_code})
            else:
                _json_out({"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]})
                sys.exit(1)

    elif args.channel and args.team:
        # Channel message or reply via Graph API
        client = TeamsApiClient()
        try:
            if args.message:
                result = await reply_to_channel_message(
                    client, args.team, args.channel, args.message, html)
                _json_out({"status": "sent", "target": args.channel,
                            "type": "channel_reply", "replyId": result.get("id"),
                            "parentMessageId": args.message})
            else:
                result = await post_channel_message(
                    client, args.team, args.channel, html)
                _json_out({"status": "sent", "target": args.channel,
                            "type": "channel_post", "messageId": result.get("id")})
        finally:
            await client.close()
    else:
        print(json.dumps({"error": "Specify --chat OR (--team + --channel)"}))
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.api",
        description="Direct Teams API client — fast alternative to MCP tools",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    # list-chats
    p = sub.add_parser("list-chats", help="List chats (via CSA updates)")
    p.add_argument("--filter", help="Filter by title/topic (case-insensitive)")
    p.add_argument("--top", type=int, help="Max results")
    p.set_defaults(func=_cmd_list_chats)

    # list-messages
    p = sub.add_parser("list-messages", help="List messages in a chat")
    p.add_argument("--chat", required=True, help="Chat/conversation ID")
    p.add_argument("--top", type=int, default=50, help="Max messages (default 50)")
    p.set_defaults(func=_cmd_list_messages)

    # send-message
    p = sub.add_parser("send-message", help="Send a message to a chat")
    p.add_argument("--chat", required=True, help="Chat/conversation ID")
    p.add_argument("--body", help="Message body (HTML or text)")
    p.add_argument("--body-file", help="Read message body from a file")
    p.add_argument("--markdown", action="store_true",
                   help="Convert body from markdown to Teams HTML")
    p.add_argument("--plain", action="store_true", help="Send as plain text")
    p.set_defaults(func=_cmd_send_message)

    # list-teams
    p = sub.add_parser("list-teams", help="List teams and channels")
    p.set_defaults(func=_cmd_list_teams)

    # list-channels
    p = sub.add_parser("list-channels", help="List channels (optionally by team)")
    p.add_argument("--team", help="Filter by team ID")
    p.set_defaults(func=_cmd_list_channels)

    # get-chat
    p = sub.add_parser("get-chat", help="Get chat details")
    p.add_argument("--chat", required=True, help="Chat/conversation ID")
    p.set_defaults(func=_cmd_get_chat)

    # get-members
    p = sub.add_parser("get-members", help="Get chat members")
    p.add_argument("--chat", required=True, help="Chat/conversation ID")
    p.set_defaults(func=_cmd_get_members)

    # user-properties
    p = sub.add_parser("user-properties", help="Get user properties")
    p.set_defaults(func=_cmd_user_props)

    # sync-cache — the key new command
    p = sub.add_parser("sync-cache",
                       help="Fetch Teams data and write directly to cache files")
    p.add_argument("--chats", action="store_true",
                   help="Sync only chats cache")
    p.add_argument("--teams", action="store_true",
                   help="Sync only teams/channels cache")
    p.add_argument("--enrich-upns", action="store_true",
                   help="Also enrich cached people with UPNs (slower, browser only)")
    p.add_argument("--from-stdin", action="store_true",
                   help="Read raw CSA JSON from stdin instead of connecting to browser")
    p.set_defaults(func=_cmd_sync_cache)

    # post-channel — new message to a channel (via Graph API)
    p = sub.add_parser("post-channel",
                       help="Post a message to a Teams channel (Graph API)")
    p.add_argument("--team", required=True, help="Team GUID")
    p.add_argument("--channel", required=True, help="Channel ID (19:...@thread.tacv2)")
    p.add_argument("--body", help="Message body")
    p.add_argument("--body-file", help="Read message body from a file")
    p.add_argument("--markdown", action="store_true",
                   help="Convert body from markdown to Teams HTML")
    p.add_argument("--plain", action="store_true", help="Send as plain text")
    p.set_defaults(func=_cmd_post_channel)

    # reply-channel — reply to a channel thread (via Graph API)
    p = sub.add_parser("reply-channel",
                       help="Reply to a channel message thread (Graph API)")
    p.add_argument("--team", required=True, help="Team GUID")
    p.add_argument("--channel", required=True, help="Channel ID (19:...@thread.tacv2)")
    p.add_argument("--message", required=True, help="Parent message ID to reply to")
    p.add_argument("--body", help="Reply body")
    p.add_argument("--body-file", help="Read reply body from a file")
    p.add_argument("--markdown", action="store_true",
                   help="Convert body from markdown to Teams HTML")
    p.add_argument("--plain", action="store_true", help="Send as plain text")
    p.set_defaults(func=_cmd_reply_channel)

    # get-thread — retrieve all messages in a channel thread (via chatsvc)
    p = sub.add_parser("get-thread",
                       help="Get all messages in a channel thread (chatsvc API)")
    p.add_argument("--channel", required=True,
                   help="Channel ID (19:...@thread.tacv2)")
    p.add_argument("--message", required=True,
                   help="Root message ID of the thread")
    p.add_argument("--top", type=int, default=200,
                   help="Max messages to return (default 200)")
    p.set_defaults(func=_cmd_get_thread)

    # channel-members — get channel members (via Graph API)
    p = sub.add_parser("channel-members",
                       help="Get channel members (Graph API)")
    p.add_argument("--team", required=True, help="Team GUID")
    p.add_argument("--channel", required=True, help="Channel ID")
    p.set_defaults(func=_cmd_channel_members)

    # send-rich — high-level: markdown → HTML → validate → send
    p = sub.add_parser("send-rich",
                       help="Send rich message: markdown → Teams HTML → validate → send")
    p.add_argument("--chat", help="Chat/conversation ID (for chat messages)")
    p.add_argument("--team", help="Team GUID (for channel messages)")
    p.add_argument("--channel", help="Channel ID (for channel messages)")
    p.add_argument("--message", help="Parent message ID (for channel replies)")
    p.add_argument("--body", help="Markdown body text")
    p.add_argument("--body-file", help="Read markdown body from a file")
    p.add_argument("--skip-validate", action="store_true",
                   help="Skip emoji/link validation")
    p.set_defaults(func=_cmd_send_rich)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
