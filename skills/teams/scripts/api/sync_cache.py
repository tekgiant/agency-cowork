"""Sync Teams data directly into local cache files.

Connects via Playwright browser session, fetches chats/teams/channels
from the CSA+chatsvc endpoints, and writes directly to the JSON caches
and recentcontacts.md — no intermediate processing needed.

Supports two modes:
1. **Browser mode** (default): Uses Playwright TeamsSession for auth
2. **MCP mode** (--from-mcp): Takes raw MCP API output on stdin and writes to cache

Usage (from skills/teams/):
    python -m scripts.api sync-cache           # Sync all via browser
    python -m scripts.api sync-cache --chats   # Sync only chats via browser
    python -m scripts.api sync-cache --teams   # Sync only teams via browser
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("teams.api.sync_cache")

# Resolve cache-manager module for direct function imports
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))


def _get_cache_manager():
    """Import cache-manager functions (it's a hyphenated filename)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cache_manager", _SCRIPTS_DIR / "cache-manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def sync_chats_from_api(client) -> dict:
    """Fetch all chats via browser session and write directly to cache.

    Returns:
        Summary dict with chat count and member stats.
    """
    from .chats import list_chats
    cm = _get_cache_manager()

    logger.info("Fetching chats via CSA updates...")
    chats = await list_chats(client)
    logger.info("Got %d chats from CSA", len(chats))

    chats_data = _transform_chats(chats)

    # Write to cache using cache-manager functions
    cm.write_cache("chats", chats_data)
    cm._auto_populate_from_chats(chats_data)

    with_members = sum(1 for c in chats_data if c.get("members"))
    summary = {
        "totalChats": len(chats_data),
        "withMembers": with_members,
        "withoutMembers": len(chats_data) - with_members,
    }
    logger.info("Chats cache written: %s", summary)
    return summary


async def sync_teams_from_api(client) -> dict:
    """Fetch all teams/channels via browser session and write directly to cache.

    Returns:
        Summary dict with team and channel counts.
    """
    from .teams_channels import list_teams_and_channels
    cm = _get_cache_manager()

    logger.info("Fetching teams and channels via CSA updates...")
    teams, channels = await list_teams_and_channels(client)
    logger.info("Got %d teams, %d channels from CSA", len(teams), len(channels))

    teams_data = _transform_teams(teams)

    # Write to cache using cache-manager functions
    cm.write_cache("teams", teams_data)
    cm._auto_populate_from_teams(teams_data)

    total_channels = sum(len(t["channels"]) for t in teams_data)
    summary = {
        "totalTeams": len(teams_data),
        "totalChannels": total_channels,
    }
    logger.info("Teams cache written: %s", summary)
    return summary


async def sync_all_from_api(client) -> dict:
    """Sync all caches (chats + teams) via browser session."""
    chats_summary = await sync_chats_from_api(client)
    teams_summary = await sync_teams_from_api(client)
    return {**chats_summary, **teams_summary}


def sync_chats_from_json(raw_json: str) -> dict:
    """Build chats cache from raw CSA JSON response (no browser needed).

    Args:
        raw_json: JSON string — either the full CSA updates response
                  or a {"chats": [...]} wrapper.

    Returns:
        Summary dict.
    """
    from .models import Chat, Member
    cm = _get_cache_manager()

    data = json.loads(raw_json)

    # Support both full CSA response and just the chats array
    if "chats" in data and isinstance(data["chats"], list):
        chats_raw = data["chats"]
    elif isinstance(data, list):
        chats_raw = data
    else:
        chats_raw = data.get("chats", [])

    chats = [Chat.from_csa(c) for c in chats_raw]
    chats_data = _transform_chats(chats)

    cm.write_cache("chats", chats_data)
    cm._auto_populate_from_chats(chats_data)

    with_members = sum(1 for c in chats_data if c.get("members"))
    return {"totalChats": len(chats_data), "withMembers": with_members}


def sync_teams_from_json(raw_json: str) -> dict:
    """Build teams cache from raw CSA JSON response (no browser needed).

    Args:
        raw_json: JSON string — either the full CSA updates response
                  or a {"teams": [...], "channels": [...]} wrapper.

    Returns:
        Summary dict.
    """
    from .models import Team, Channel
    cm = _get_cache_manager()

    data = json.loads(raw_json)

    # Support full CSA response (has channels at top level)
    channels_raw = data.get("channels", [])
    channels = [Channel.from_csa(c) for c in channels_raw]

    # Group channels by parentTeamId into Team objects
    teams_map: dict[str, list] = {}
    for ch in channels:
        teams_map.setdefault(ch.parent_team_id, []).append(ch)

    teams = []
    for team_id, team_channels in teams_map.items():
        teams.append(Team(
            id=team_id,
            display_name="",
            channels=team_channels,
        ))

    teams_data = _transform_teams(teams)

    cm.write_cache("teams", teams_data)
    cm._auto_populate_from_teams(teams_data)

    total_channels = sum(len(t["channels"]) for t in teams_data)
    return {"totalTeams": len(teams_data), "totalChannels": total_channels}


def _transform_chats(chats) -> list[dict]:
    """Transform Chat dataclass list → cache format."""
    chats_data = []
    for chat in chats:
        members = []
        for m in chat.members:
            user_id = m.object_id or ""
            if not user_id and m.mri.startswith("8:orgid:"):
                user_id = m.mri.replace("8:orgid:", "")

            members.append({
                "displayName": m.display_name,
                "upn": "",  # CSA doesn't include UPN — enrich later
                "userId": user_id,
            })

        # Map CSA chatType to cache format
        chat_type = chat.chat_type
        if chat.is_one_on_one:
            chat_type = "OneOnOne"
        elif chat.thread_type == "meeting":
            chat_type = "Meeting"
        elif chat.chat_type in ("chat", ""):
            chat_type = "Group" if len(chat.members) > 2 else "OneOnOne"

        chats_data.append({
            "id": chat.id,
            "topic": chat.title or "",
            "chatType": chat_type,
            "members": members,
        })
    return chats_data


def _transform_teams(teams) -> list[dict]:
    """Transform Team dataclass list → cache format."""
    teams_data = []
    for team in teams:
        team_channels = []
        for ch in team.channels:
            team_channels.append({
                "id": ch.id,
                "displayName": ch.display_name,
            })
        teams_data.append({
            "id": team.id,
            "displayName": team.display_name,
            "channels": team_channels,
        })
    return teams_data


async def enrich_upns(client) -> dict:
    """Enrich cached people with UPNs by querying user profiles.

    CSA member data includes MRIs and display names but NOT UPNs.
    This fetches UPNs for people that lack them.

    Returns:
        Summary dict with enrichment stats.
    """
    cm = _get_cache_manager()
    people_cache = cm.read_cache("people")
    if not people_cache or not people_cache.get("data"):
        return {"enriched": 0, "total": 0}

    people = people_cache["data"]
    to_enrich = [p for p in people if not p.get("upn") and p.get("userId")]

    if not to_enrich:
        return {"enriched": 0, "total": len(people), "alreadyComplete": True}

    logger.info("Enriching UPNs for %d/%d people", len(to_enrich), len(people))

    enriched = 0
    for person in to_enrich:
        try:
            user_id = person["userId"]
            url = f"https://teams.cloud.microsoft/api/mt/part/msft/beta/users/8:orgid:{user_id}/properties"
            data = await client.get(url)
            upn = data.get("userPrincipalName", "") or data.get("email", "")
            if upn:
                person["upn"] = upn
                enriched += 1
                cm.add_person_contact(person["displayName"], upn, user_id)
        except Exception as e:
            logger.debug("Failed to enrich %s: %s", person.get("displayName"), e)

    if enriched:
        cm.write_cache("people", people)

    return {"enriched": enriched, "total": len(people), "lacking_upn": len(to_enrich)}
