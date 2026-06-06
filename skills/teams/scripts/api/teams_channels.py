"""Teams & Channels API — list teams, channels, and channel messages.

Uses CSA ``/v3/teams/users/me/updates`` for team/channel enumeration
and chatsvc for channel messages (channels use the same message API).
"""

from __future__ import annotations

import logging
from typing import Optional

from .client import TeamsApiClient
from .models import Channel, Team, Message
from .messages import list_messages

logger = logging.getLogger("teams.api.teams_channels")

# CSA updates params (shared with chats)
_CSA_UPDATES_PARAMS = {
    "isPrefetch": "false",
    "enableMembershipSummary": "true",
    "supportsAdditionalSystemGeneratedFolders": "true",
    "supportsSliceItems": "true",
    "enableEngageCommunities": "true",
}


async def list_teams_and_channels(
    client: TeamsApiClient,
) -> tuple[list[Team], list[Channel]]:
    """List all teams and channels from CSA updates.

    Returns:
        Tuple of (teams, channels). Teams list may be empty if the
        CSA response only includes channels (common for incremental syncs).
    """
    url = client.csa_url("/v3/teams/users/me/updates")
    data = await client.get(url, params=_CSA_UPDATES_PARAMS)

    # Parse channels
    channels_raw = data.get("channels", [])
    channels = [Channel.from_csa(c) for c in channels_raw]

    # Group channels by parentTeamId into Team objects
    teams_map: dict[str, Team] = {}
    for ch in channels:
        if ch.parent_team_id not in teams_map:
            teams_map[ch.parent_team_id] = Team(
                id=ch.parent_team_id,
                display_name="",  # CSA doesn't always include team names
            )
        teams_map[ch.parent_team_id].channels.append(ch)

    teams = list(teams_map.values())
    logger.info("list_teams_and_channels: %d teams, %d channels", len(teams), len(channels))
    return teams, channels


async def list_channels(
    client: TeamsApiClient,
    team_id: Optional[str] = None,
) -> list[Channel]:
    """List channels, optionally filtered by team ID."""
    _, channels = await list_teams_and_channels(client)
    if team_id:
        channels = [c for c in channels if c.parent_team_id == team_id]
    return channels


async def list_channel_messages(
    client: TeamsApiClient,
    channel_id: str,
    top: int = 50,
) -> list[Message]:
    """List messages in a channel (uses same chatsvc message API)."""
    return await list_messages(client, channel_id, top=top)
