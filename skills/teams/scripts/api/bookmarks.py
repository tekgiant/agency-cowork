"""Saved messages (bookmarks) — save, unsave, and list saved Teams messages.

Uses the chatsvc rcmetadata API to bookmark messages and the virtual
``48:saved`` conversation to list all saved messages.

API endpoints:
    PUT  /users/ME/conversations/{channelId}/rcmetadata/{messageId}
         Body: {"s": 1, "mid": <int>}   → save
         Body: {"s": 0, "mid": <int>}   → unsave
    GET  /users/ME/conversations/48%3Asaved/messages
         ?view=msnp24Equivalent|supportsMessageProperties&pageSize=200
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .client import TeamsApiClient

logger = logging.getLogger("teams.api.bookmarks")

# Virtual conversation ID for saved messages
_SAVED_CONV_ID = "48:saved"

# Default view params (same as messages.py _MSG_VIEW)
_MSG_VIEW = "msnp24Equivalent|supportsMessageProperties"


@dataclass
class SavedMessage:
    """A saved (bookmarked) Teams message."""

    message_id: str
    channel_id: str
    content: str = ""
    sender_name: str = ""
    sender_id: str = ""
    saved_at: Optional[datetime] = None
    timestamp: Optional[datetime] = None
    rc_metadata: dict = field(default_factory=dict, repr=False)
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict (excludes raw payload)."""
        return {
            "messageId": self.message_id,
            "channelId": self.channel_id,
            "content": self.content,
            "senderName": self.sender_name,
            "senderId": self.sender_id,
            "savedAt": self.saved_at.isoformat() if self.saved_at else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_chatsvc(cls, data: dict) -> "SavedMessage":
        """Parse a saved message from the ``48:saved`` conversation response.

        Args:
            data: Raw message dict from the ``48:saved`` messages endpoint.

        Returns:
            SavedMessage instance.
        """
        ts = None
        arrival = data.get("originalarrivaltime") or data.get("composetime")
        if arrival:
            try:
                ts = datetime.fromisoformat(arrival.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Extract saved_at from rcMetadata if available
        saved_at = None
        rc_meta = data.get("rcMetadata") or data.get("rcmetadata") or {}
        if isinstance(rc_meta, str):
            try:
                rc_meta = json.loads(rc_meta)
            except (json.JSONDecodeError, TypeError):
                rc_meta = {}
        lu = rc_meta.get("lu") or rc_meta.get("ch")
        if lu:
            try:
                saved_at = datetime.fromtimestamp(lu / 1000, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        return cls(
            message_id=str(data.get("id", data.get("clientmessageid", ""))),
            channel_id=data.get("conversationid", ""),
            content=data.get("content", ""),
            sender_name=data.get("imdisplayname", ""),
            sender_id=data.get("from", ""),
            saved_at=saved_at,
            timestamp=ts,
            rc_metadata=rc_meta,
            raw=data,
        )


async def save_message(
    client: TeamsApiClient,
    channel_id: str,
    message_id: str,
) -> dict:
    """Save (bookmark) a message via the chatsvc rcmetadata API.

    Args:
        client: TeamsApiClient instance.
        channel_id: Conversation/channel ID containing the message.
        message_id: Numeric message ID to save.

    Returns:
        API response dict with rcMetadata confirmation.
    """
    encoded_channel = client.encode_conv_id(channel_id)
    path = f"/users/ME/conversations/{encoded_channel}/rcmetadata/{message_id}"
    body = {"s": 1, "mid": int(message_id)}

    result = await client.chatsvc_put_direct(path, body)
    logger.info("save_message: saved %s in %s", message_id, channel_id[:40])
    return result


async def unsave_message(
    client: TeamsApiClient,
    channel_id: str,
    message_id: str,
) -> dict:
    """Unsave (remove bookmark from) a message via the chatsvc rcmetadata API.

    Args:
        client: TeamsApiClient instance.
        channel_id: Conversation/channel ID containing the message.
        message_id: Numeric message ID to unsave.

    Returns:
        API response dict.
    """
    encoded_channel = client.encode_conv_id(channel_id)
    path = f"/users/ME/conversations/{encoded_channel}/rcmetadata/{message_id}"
    body = {"s": 0, "mid": int(message_id)}

    result = await client.chatsvc_put_direct(path, body)
    logger.info("unsave_message: unsaved %s in %s", message_id, channel_id[:40])
    return result


async def list_saved_messages(
    client: TeamsApiClient,
    sync_state: Optional[str] = None,
    start_time: Optional[int] = None,
    page_size: int = 200,
) -> tuple[list[SavedMessage], Optional[str]]:
    """List all saved messages from the virtual ``48:saved`` conversation.

    Args:
        client: TeamsApiClient instance.
        sync_state: Opaque hex token for incremental sync (from previous call).
        start_time: Unix timestamp (ms) — only return messages saved after this.
        page_size: Max messages per page (default 200).

    Returns:
        Tuple of (list of SavedMessage instances, new syncState token or None).
    """
    encoded = client.encode_conv_id(_SAVED_CONV_ID)
    path = f"/users/ME/conversations/{encoded}/messages"
    params: dict[str, str] = {
        "view": _MSG_VIEW,
        "pageSize": str(page_size),
    }
    if sync_state:
        params["syncState"] = sync_state
    if start_time is not None:
        params["startTime"] = str(start_time)
    else:
        params["startTime"] = "1"

    data = await client.chatsvc_get_direct(path, params=params)

    messages_raw = data.get("messages", [])
    messages = [SavedMessage.from_chatsvc(m) for m in messages_raw]

    # Extract new syncState for incremental polling
    new_sync_state = data.get("_metadata", {}).get("syncState")

    logger.info("list_saved_messages: %d saved messages", len(messages))
    return messages, new_sync_state
