"""Messages API — list messages, send to chats, post/reply to channels.

Uses chatsvc REST API for chat operations (fast) and Microsoft Graph API
for channel operations (reliable, MCP-free).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .client import TeamsApiClient, USER_MRI
from .models import Message

# Shared chunking utility
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT.parent))
from scripts.chunking import chunk_message, INTER_CHUNK_DELAY

logger = logging.getLogger("teams.api.messages")

# Default view params (from HAR)
_MSG_VIEW = "msnp24Equivalent|supportsMessageProperties"

# Reply prefix — loaded once from agentconfig.json → monitor.replyPrefix
_AGENT_CONFIG = Path(__file__).resolve().parent.parent.parent.parent.parent / "agentconfig.json"


def _get_reply_prefix() -> str:
    """Read the configurable reply prefix from agentconfig.json."""
    try:
        if _AGENT_CONFIG.exists():
            data = json.loads(_AGENT_CONFIG.read_text(encoding="utf-8"))
            return data.get("monitor", {}).get("replyPrefix", "Agency Cowork: ")
    except (json.JSONDecodeError, OSError):
        pass
    return "Agency Cowork: "


def _load_markdown_body(body: Optional[str], body_file: Optional[str],
                        markdown: bool) -> str:
    """Resolve message body from inline text or file, with optional markdown conversion.

    Args:
        body: Inline body text.
        body_file: Path to a file containing the body.
        markdown: If True, convert markdown to Teams HTML.

    Returns:
        Final body string (HTML if markdown=True, raw otherwise).
    """
    if body_file:
        text = Path(body_file).read_text(encoding="utf-8").strip()
    elif body:
        text = body
    else:
        raise ValueError("Either --body or --body-file must be provided")

    if markdown:
        # Import the converter from rich utils
        _teams_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(_teams_root))
        from scripts.rich.utils import markdown_to_teams_html
        return markdown_to_teams_html(text)

    return text


async def list_messages(
    client: TeamsApiClient,
    chat_id: str,
    top: int = 50,
    start_time: Optional[int] = None,
) -> list[Message]:
    """List messages in a chat/channel.

    Args:
        client: TeamsApiClient instance.
        chat_id: Conversation thread ID.
        top: Max messages to return (pageSize).
        start_time: Unix timestamp (ms) to start from. Default 1 = all history.

    Returns:
        List of Message dataclass instances, newest first.
    """
    encoded = client.encode_conv_id(chat_id)
    url = client.chatsvc_url(f"/users/ME/conversations/{encoded}/messages")
    params = {
        "view": _MSG_VIEW,
        "pageSize": str(top),
        "startTime": str(start_time if start_time is not None else 1),
    }
    data = await client.get(url, params=params)

    messages_raw = data.get("messages", [])
    messages = [Message.from_chatsvc(m) for m in messages_raw]

    # Filter out system messages (ThreadActivity/*, Event/Call, etc.)
    user_messages = [
        m for m in messages
        if m.message_type in ("Text", "RichText/Html", "RichText", "")
    ]

    logger.info("list_messages: %d messages from %s", len(user_messages), chat_id[:40])
    return user_messages


async def send_message(
    client: TeamsApiClient,
    chat_id: str,
    body: str,
    html: bool = True,
) -> dict:
    """Send a message to a chat/channel.

    Args:
        client: TeamsApiClient instance.
        chat_id: Conversation thread ID.
        body: Message content (HTML or plain text).
        html: If True, sends as RichText/Html. If False, sends as Text.

    Returns:
        API response dict.
    """
    # Apply configurable reply prefix from agentconfig.json
    reply_prefix = _get_reply_prefix()
    if reply_prefix and not body.startswith(reply_prefix):
        body = reply_prefix + body
    display_name = reply_prefix.rstrip(": ") if reply_prefix else os.environ.get("TEAMS_DISPLAY_NAME", "Agent")

    encoded = client.encode_conv_id(chat_id)
    url = client.chatsvc_url(f"/users/ME/conversations/{encoded}/messages")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Ensure HTML wrapping
    content = body
    if html and not content.strip().startswith("<"):
        content = f"<p>{content}</p>"

    message_type = "RichText/Html" if html else "Text"

    payload = {
        "id": "-1",
        "type": "Message",
        "conversationid": chat_id,
        "conversationLink": (
            f"{client.chatsvc_url('/users/ME/conversations/')}{encoded}"
        ),
        "from": USER_MRI,
        "fromUserId": USER_MRI,
        "composetime": now,
        "originalarrivaltime": now,
        "content": content,
        "messagetype": message_type,
        "contenttype": "Text",
        "imdisplayname": display_name,
        "clientmessageid": str(uuid.uuid4().int)[:19],
        "callId": "",
        "state": 0,
        "version": "0",
        "amsreferences": [],
        "properties": {
            "importance": "",
            "subject": "",
            "title": "",
            "cards": "[]",
            "links": "[]",
            "mentions": "[]",
            "onbehalfof": None,
            "files": "[]",
            "policyViolation": None,
            "formatVariant": "TEAMS",
        },
        "crossPostChannels": [],
    }

    result = await client.post(url, body=payload)
    logger.info("send_message: sent to %s", chat_id[:40])
    return result


# ── Channel operations (via Microsoft Graph API) ──


async def list_channel_messages(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
    top: int = 50,
) -> list[Message]:
    """List messages in a Teams channel via Graph API.

    Args:
        client: TeamsApiClient instance (used for graph_get).
        team_id: Team GUID.
        channel_id: Channel thread ID (19:...@thread.tacv2).
        top: Max messages to return.

    Returns:
        List of Message dataclass instances (user messages only), newest first.
    """
    path = f"/teams/{team_id}/channels/{channel_id}/messages"
    params = {"$top": str(top)}
    data = await client.graph_get(path, params=params)

    messages_raw = data.get("value", [])
    messages = [Message.from_graph(m) for m in messages_raw]

    # Filter to user messages only (exclude system events)
    user_messages = [
        m for m in messages
        if m.message_type in ("Text", "RichText/Html", "RichText", "")
    ]

    logger.info(
        "list_channel_messages: %d messages from channel %s",
        len(user_messages), channel_id[:30],
    )
    return user_messages


async def list_channel_message_replies(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
    message_id: str,
    top: int = 50,
) -> list[Message]:
    """List replies to a channel message via Graph API.

    Args:
        client: TeamsApiClient instance.
        team_id: Team GUID.
        channel_id: Channel thread ID.
        message_id: Parent message ID.
        top: Max replies to return.

    Returns:
        List of Message dataclass instances.
    """
    path = f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    params = {"$top": str(top)}
    data = await client.graph_get(path, params=params)

    replies_raw = data.get("value", [])
    replies = [Message.from_graph(r) for r in replies_raw]

    user_replies = [
        r for r in replies
        if r.message_type in ("Text", "RichText/Html", "RichText", "")
    ]

    logger.info(
        "list_channel_message_replies: %d replies to %s in %s",
        len(user_replies), message_id, channel_id[:30],
    )
    return user_replies


async def list_thread_replies(
    client: TeamsApiClient,
    channel_id: str,
    message_id: str,
    top: int = 200,
) -> list[Message]:
    """List all messages in a channel thread via chatsvc API.

    Uses the Teams Chat Service v2 (chatsvc) API which reliably returns
    thread replies.  The standard Graph API ``/replies`` endpoint requires
    ``ChannelMessage.Read.All`` app permission which is typically
    unavailable via Azure CLI tokens.

    Args:
        client: TeamsApiClient instance.
        channel_id: Channel thread ID (``19:...@thread.tacv2``).
        message_id: Root message ID of the thread (numeric timestamp).
        top: Max messages to return (default 200).

    Returns:
        List of Message instances (user messages only), oldest first.
    """
    # Thread-scoped conversation: channelId;messageid=rootMessageId
    thread_conv_id = f"{channel_id};messageid={message_id}"
    encoded = client.encode_conv_id(thread_conv_id)
    path = f"/users/ME/conversations/{encoded}/messages"
    params = {
        "view": _MSG_VIEW,
        "pageSize": str(top),
        "startTime": "1",
    }

    data = await client.chatsvc_get_direct(path, params=params)
    messages_raw = data.get("messages", [])
    messages = [Message.from_chatsvc(m) for m in messages_raw]

    # Keep only user-generated messages (skip system/control messages)
    user_messages = [
        m for m in messages
        if m.message_type in ("Text", "RichText/Html", "RichText", "")
    ]

    logger.info(
        "list_thread_replies: %d messages in thread %s of %s",
        len(user_messages), message_id, channel_id[:30],
    )
    return user_messages


async def post_channel_message(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
    body: str,
    html: bool = True,
) -> dict:
    """Post a new message to a Teams channel via Graph API.

    Long messages are automatically split into sequential chunks.

    Args:
        client: TeamsApiClient instance (used for graph_post).
        team_id: Team GUID.
        channel_id: Channel thread ID (19:...@thread.tacv2).
        body: Message content.
        html: If True, send as HTML. If False, send as plain text.

    Returns:
        Graph API response dict (includes message id).
    """
    reply_prefix = _get_reply_prefix()
    if reply_prefix and not body.startswith(reply_prefix):
        body = reply_prefix + body

    # Skip chunking for pre-rendered HTML — splitting inside tags produces
    # invalid markup.  Chunk the source text before HTML conversion instead.
    if html:
        return await _post_single_channel_message(client, team_id, channel_id, body, html)

    chunks = chunk_message(body)

    if len(chunks) == 1:
        return await _post_single_channel_message(client, team_id, channel_id, chunks[0], html)

    logger.info("Chunking channel message into %d parts for %s", len(chunks), channel_id[:30])
    last_result: dict = {}
    for i, chunk in enumerate(chunks):
        last_result = await _post_single_channel_message(client, team_id, channel_id, chunk, html)
        if i < len(chunks) - 1:
            await asyncio.sleep(INTER_CHUNK_DELAY)
    return last_result


async def _post_single_channel_message(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
    body: str,
    html: bool = True,
) -> dict:
    """Post a single message to a channel (no chunking)."""
    path = f"/teams/{team_id}/channels/{channel_id}/messages"
    payload = {
        "body": {
            "contentType": "html" if html else "text",
            "content": body,
        }
    }
    result = await client.graph_post(path, payload)
    msg_id = result.get("id", "unknown")
    logger.info("post_channel_message: posted to channel %s (id=%s)",
                channel_id[:30], msg_id)
    return result


async def reply_to_channel_message(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
    message_id: str,
    body: str,
    html: bool = True,
) -> dict:
    """Reply to a message thread in a Teams channel via Graph API.

    Long messages are automatically split into sequential chunks.

    Args:
        client: TeamsApiClient instance (used for graph_post).
        team_id: Team GUID.
        channel_id: Channel thread ID (19:...@thread.tacv2).
        message_id: Parent message ID to reply to.
        body: Reply content.
        html: If True, send as HTML. If False, send as plain text.

    Returns:
        Graph API response dict (includes reply id).
    """
    reply_prefix = _get_reply_prefix()
    if reply_prefix and not body.startswith(reply_prefix):
        body = reply_prefix + body

    # Skip chunking for pre-rendered HTML — splitting inside tags produces
    # invalid markup.  Chunk the source text before HTML conversion instead.
    path = f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    if html:
        return await _post_single_reply(client, path, body, html, channel_id, message_id)

    chunks = chunk_message(body)

    if len(chunks) == 1:
        return await _post_single_reply(client, path, chunks[0], html, channel_id, message_id)

    logger.info("Chunking channel reply into %d parts for %s", len(chunks), channel_id[:30])
    last_result: dict = {}
    for i, chunk in enumerate(chunks):
        last_result = await _post_single_reply(client, path, chunk, html, channel_id, message_id)
        if i < len(chunks) - 1:
            await asyncio.sleep(INTER_CHUNK_DELAY)
    return last_result


async def _post_single_reply(
    client: TeamsApiClient,
    path: str,
    body: str,
    html: bool,
    channel_id: str,
    message_id: str,
) -> dict:
    """Post a single reply to a channel thread (no chunking)."""
    payload = {
        "body": {
            "contentType": "html" if html else "text",
            "content": body,
        }
    }
    result = await client.graph_post(path, payload)
    reply_id = result.get("id", "unknown")
    logger.info("reply_to_channel_message: replied to %s in %s (id=%s)",
                message_id, channel_id[:30], reply_id)
    return result


async def get_channel_members(
    client: TeamsApiClient,
    team_id: str,
    channel_id: str,
) -> list[dict]:
    """Get members of a Teams channel via Graph API.

    Args:
        client: TeamsApiClient instance (used for graph_get).
        team_id: Team GUID.
        channel_id: Channel thread ID.

    Returns:
        List of member dicts with displayName, email, userId.
    """
    path = f"/teams/{team_id}/channels/{channel_id}/members"
    result = await client.graph_get(path)
    members = []
    for m in result.get("value", []):
        members.append({
            "displayName": m.get("displayName", ""),
            "email": m.get("email", ""),
            "userId": m.get("userId", ""),
            "roles": m.get("roles", []),
        })
    logger.info("get_channel_members: %d members in %s", len(members), channel_id[:30])
    return members
