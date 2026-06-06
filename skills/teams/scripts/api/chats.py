"""Chats API — list chats, get chat details, get members.

Primary endpoint: CSA ``/v3/teams/users/me/updates`` returns chats,
teams, channels, and users in a single call.
"""

from __future__ import annotations

import logging
from typing import Optional

from .client import TeamsApiClient
from .models import Chat, Member

logger = logging.getLogger("teams.api.chats")

# CSA updates query params (from HAR)
_CSA_UPDATES_PARAMS = {
    "isPrefetch": "false",
    "enableMembershipSummary": "true",
    "supportsAdditionalSystemGeneratedFolders": "true",
    "supportsSliceItems": "true",
    "enableEngageCommunities": "true",
}


async def list_chats(
    client: TeamsApiClient,
    topic_filter: Optional[str] = None,
    top: Optional[int] = None,
) -> list[Chat]:
    """List all chats via CSA updates endpoint.

    This returns chats from the CSA ``/v3/teams/users/me/updates``
    endpoint — significantly faster than the MCP ListChats tool.

    Args:
        client: TeamsApiClient instance.
        topic_filter: Case-insensitive substring filter on chat title.
        top: Maximum number of chats to return.

    Returns:
        List of Chat dataclass instances.
    """
    url = client.csa_url("/v3/teams/users/me/updates")
    data = await client.get(url, params=_CSA_UPDATES_PARAMS)

    chats_raw = data.get("chats", [])
    chats = [Chat.from_csa(c) for c in chats_raw]

    # Apply filters
    if topic_filter:
        lower_filter = topic_filter.lower()
        chats = [c for c in chats if lower_filter in (c.title or "").lower()
                 or lower_filter in c.display_name().lower()]

    if top:
        chats = chats[:top]

    logger.info("list_chats: %d chats (filter=%s, top=%s)", len(chats), topic_filter, top)
    return chats


async def get_chat(client: TeamsApiClient, chat_id: str) -> dict:
    """Get details of a specific chat.

    Args:
        client: TeamsApiClient instance.
        chat_id: Conversation thread ID.

    Returns:
        Raw chatsvc conversation JSON.
    """
    encoded = client.encode_conv_id(chat_id)
    url = client.chatsvc_url(f"/users/ME/conversations/{encoded}")
    data = await client.get(url, params={"view": "msnp24Equivalent"})
    logger.info("get_chat: %s", chat_id[:40])
    return data


async def get_chat_members(
    client: TeamsApiClient,
    chat_id: str,
) -> list[Member]:
    """Get members of a chat from the CSA updates data.

    For chats returned by list_chats(), members are already embedded.
    This function is for cases where you need fresh member data.
    """
    # Members are embedded in the CSA response; re-fetch
    chats = await list_chats(client)
    for chat in chats:
        if chat.id == chat_id:
            return chat.members
    # Fallback: try getting the chat directly
    data = await get_chat(client, chat_id)
    members_raw = data.get("members", [])
    return [Member.from_chatsvc(m) for m in members_raw]


async def get_user_properties(client: TeamsApiClient) -> dict:
    """Get the authenticated user's properties (favorites, locale, etc.)."""
    url = client.chatsvc_url("/users/ME/properties")
    return await client.get(url)
