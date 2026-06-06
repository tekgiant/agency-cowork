#!/usr/bin/env python3
"""
Cache manager for the Teams skill.
Manages local JSON cache files and recentcontacts.md for chats, teams/channels, and people.

Usage:
    python cache-manager.py status                  # Show cache file ages and contact counts
    python cache-manager.py is-stale <cache_name>   # Exit 0 if stale, 1 if fresh
    python cache-manager.py read <cache_name>        # Print cached data as JSON
    python cache-manager.py write <cache_name>       # Write JSON from stdin
    python cache-manager.py build-teams              # Build teams cache from raw API responses (stdin)
    python cache-manager.py build-chats              # Build chats cache from raw API responses (stdin)
    python cache-manager.py resolve <query>          # Unified search: contacts → JSON cache (person/chat/channel)
    python cache-manager.py lookup-person <name>     # Search people cache by name
    python cache-manager.py lookup-chat <query>        # Find chat by member UPN, name, or topic
    python cache-manager.py lookup-team <name>       # Find team by display name
    python cache-manager.py lookup-channel <team_id> <name>  # Find channel by name in team
    python cache-manager.py read-contacts            # Print recentcontacts.md as JSON
    python cache-manager.py add-person <name> <upn> <user_id>           # Add person to contacts
    python cache-manager.py add-chat <person_or_topic> <chat_id> <type> # Add chat to contacts
    python cache-manager.py add-channel <team> <channel> <team_id> <channel_id>  # Add channel
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
STALE_THRESHOLD_HOURS = 4
RECENT_CONTACTS_FILE = CACHE_DIR / "recentcontacts.md"

CACHE_FILES = {
    "chats": CACHE_DIR / "chats.json",
    "teams": CACHE_DIR / "teams-and-channels.json",
    "people": CACHE_DIR / "people.json",
}

# The self-chat (Notes to Self) uses a special hardcoded ID, not the standard
# 19:...@unq.gbl.spaces (OneOnOne) or 19:...@thread.v2 (Group/Meeting) formats.
SELF_CHAT_ID = "48:notes"
SELF_CHAT_LABEL = "Self (Notes)"
SELF_CHAT_TYPE = "Self"


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# recentcontacts.md management
# ---------------------------------------------------------------------------

CONTACTS_TEMPLATE = """# Recent Contacts

## People
| Name | UPN | User ID |
|------|-----|---------|

## Chats
| Person/Topic | Chat ID | Chat Type |
|--------------|---------|-----------|

## Channels
| Team | Channel | Team ID | Channel ID |
|------|---------|---------|------------|
""".lstrip()


def _parse_md_table(lines: list[str]) -> list[list[str]]:
    """Parse markdown table rows (skipping header and separator) into lists of cell values."""
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # Skip separator rows (e.g., |------|-----|---------|)
        if all(re.fullmatch(r"-+", c) or c == "" for c in cells):
            continue
        rows.append(cells)
    return rows


def read_recent_contacts() -> dict:
    """Read recentcontacts.md and return structured data.

    Returns dict with keys: people, chats, channels — each a list of dicts.
    """
    if not RECENT_CONTACTS_FILE.exists():
        return {"people": [], "chats": [], "channels": []}

    text = RECENT_CONTACTS_FILE.read_text(encoding="utf-8")

    # Split into sections by ## headers
    sections: dict[str, list[str]] = {}
    current_section = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            sections[current_section] = []
        elif current_section is not None:
            sections[current_section].append(line)

    result: dict[str, list[dict]] = {"people": [], "chats": [], "channels": []}

    # Parse People table
    if "people" in sections:
        rows = _parse_md_table(sections["people"])
        # Skip header row
        for row in rows[1:] if rows else []:
            if len(row) >= 3:
                result["people"].append({
                    "name": row[0], "upn": row[1], "userId": row[2],
                })

    # Parse Chats table
    if "chats" in sections:
        rows = _parse_md_table(sections["chats"])
        for row in rows[1:] if rows else []:
            if len(row) >= 3:
                result["chats"].append({
                    "personOrTopic": row[0], "chatId": row[1], "chatType": row[2],
                })

    # Parse Channels table
    if "channels" in sections:
        rows = _parse_md_table(sections["channels"])
        for row in rows[1:] if rows else []:
            if len(row) >= 4:
                result["channels"].append({
                    "team": row[0], "channel": row[1],
                    "teamId": row[2], "channelId": row[3],
                })

    return result


def write_recent_contacts(data: dict) -> None:
    """Write structured data back to recentcontacts.md."""
    ensure_cache_dir()
    lines = ["# Recent Contacts", ""]

    # People
    lines.append("## People")
    lines.append("| Name | UPN | User ID |")
    lines.append("|------|-----|---------|")
    for p in data.get("people", []):
        lines.append(f"| {p['name']} | {p['upn']} | {p['userId']} |")
    lines.append("")

    # Chats
    lines.append("## Chats")
    lines.append("| Person/Topic | Chat ID | Chat Type |")
    lines.append("|--------------|---------|-----------|")
    for c in data.get("chats", []):
        lines.append(f"| {c['personOrTopic']} | {c['chatId']} | {c['chatType']} |")
    lines.append("")

    # Channels
    lines.append("## Channels")
    lines.append("| Team | Channel | Team ID | Channel ID |")
    lines.append("|------|---------|---------|------------|")
    for ch in data.get("channels", []):
        lines.append(f"| {ch['team']} | {ch['channel']} | {ch['teamId']} | {ch['channelId']} |")
    lines.append("")

    RECENT_CONTACTS_FILE.write_text("\n".join(lines), encoding="utf-8")


def add_person_contact(name: str, upn: str, user_id: str) -> None:
    """Add a person to recentcontacts.md (deduped by UPN)."""
    data = read_recent_contacts()
    for p in data["people"]:
        if normalize(p["upn"]) == normalize(upn):
            # Update existing entry
            p["name"] = name
            p["userId"] = user_id
            write_recent_contacts(data)
            print(f"Updated person: {name} ({upn})")
            return
    data["people"].append({"name": name, "upn": upn, "userId": user_id})
    write_recent_contacts(data)
    print(f"Added person: {name} ({upn})")


def add_chat_contact(person_or_topic: str, chat_id: str, chat_type: str) -> None:
    """Add a chat to recentcontacts.md (deduped by chat ID)."""
    data = read_recent_contacts()
    for c in data["chats"]:
        if c["chatId"] == chat_id:
            c["personOrTopic"] = person_or_topic
            c["chatType"] = chat_type
            write_recent_contacts(data)
            print(f"Updated chat: {person_or_topic}")
            return
    data["chats"].append({
        "personOrTopic": person_or_topic, "chatId": chat_id, "chatType": chat_type,
    })
    write_recent_contacts(data)
    print(f"Added chat: {person_or_topic}")


def add_channel_contact(team: str, channel: str, team_id: str, channel_id: str) -> None:
    """Add a channel to recentcontacts.md (deduped by channel ID)."""
    data = read_recent_contacts()
    for ch in data["channels"]:
        if ch["channelId"] == channel_id:
            ch["team"] = team
            ch["channel"] = channel
            ch["teamId"] = team_id
            write_recent_contacts(data)
            print(f"Updated channel: {team} / {channel}")
            return
    data["channels"].append({
        "team": team, "channel": channel, "teamId": team_id, "channelId": channel_id,
    })
    write_recent_contacts(data)
    print(f"Added channel: {team} / {channel}")


def read_cache(name: str) -> dict | None:
    path = CACHE_FILES.get(name)
    if not path or not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_cache(name: str, data: list | dict) -> None:
    ensure_cache_dir()
    path = CACHE_FILES.get(name)
    if not path:
        print(f"Unknown cache: {name}", file=sys.stderr)
        sys.exit(1)
    payload = {
        "lastRefreshed": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Cache '{name}' written ({len(data) if isinstance(data, list) else 1} entries)")


def is_stale(name: str) -> bool:
    cache = read_cache(name)
    if not cache or "lastRefreshed" not in cache:
        return True
    last = datetime.fromisoformat(cache["lastRefreshed"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last > timedelta(hours=STALE_THRESHOLD_HOURS)


def cache_age_str(name: str) -> str:
    cache = read_cache(name)
    if not cache or "lastRefreshed" not in cache:
        return "not cached"
    last = datetime.fromisoformat(cache["lastRefreshed"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() / 60)}m ago"
    return f"{hours:.1f}h ago"


def count_entries(name: str) -> int:
    cache = read_cache(name)
    if not cache or "data" not in cache:
        return 0
    data = cache["data"]
    return len(data) if isinstance(data, list) else 1


def cmd_status() -> None:
    print("Teams Cache Status")
    print("=" * 50)
    for name in CACHE_FILES:
        age = cache_age_str(name)
        count = count_entries(name)
        stale = is_stale(name)
        status = "STALE" if stale else "fresh"
        extra = ""
        # Report member coverage for chats
        if name == "chats":
            cache = read_cache("chats")
            if cache and cache.get("data"):
                with_members = sum(1 for c in cache["data"] if c.get("members"))
                total = len(cache["data"])
                extra = f"  ({with_members}/{total} have members)"
        print(f"  {name:10s}  {count:4d} entries  {age:>12s}  [{status}]{extra}")
    # Recent contacts summary
    contacts = read_recent_contacts()
    p_count = len(contacts["people"])
    c_count = len(contacts["chats"])
    ch_count = len(contacts["channels"])
    exists = RECENT_CONTACTS_FILE.exists()
    print(f"  {'contacts':10s}  {p_count} people, {c_count} chats, {ch_count} channels  "
          f"[{'exists' if exists else 'missing'}]")


def cmd_is_stale(name: str) -> None:
    if name not in CACHE_FILES:
        print(f"Unknown cache: {name}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if is_stale(name) else 1)


def cmd_read(name: str) -> None:
    cache = read_cache(name)
    if not cache:
        print(json.dumps({"lastRefreshed": None, "data": []}))
    else:
        print(json.dumps(cache, indent=2, ensure_ascii=False))


def cmd_write(name: str) -> None:
    raw = sys.stdin.read()
    data = json.loads(raw)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    write_cache(name, data)

    # Auto-populate derived caches and recentcontacts after writing
    if name == "chats":
        _auto_populate_from_chats(data)
    elif name == "teams":
        _auto_populate_from_teams(data)


def _auto_populate_from_chats(chats: list) -> None:
    """After writing chats cache, auto-derive people cache and update recentcontacts.

    - Validates that chat entries include members
    - Extracts unique people from all member lists → writes people.json
    - Adds each chat to recentcontacts.md (OneOnOne by counterparty name, others by topic)
    - Adds each person to recentcontacts.md
    """
    all_people: dict[str, dict] = {}  # keyed by lowercase UPN for dedup
    missing_members = 0

    for chat in chats:
        chat_id = chat.get("id", "")
        chat_type = chat.get("chatType", "")
        topic = chat.get("topic", "")
        members = chat.get("members", [])

        # Detect self-chat (Notes to Self) by its special ID
        if chat_id == SELF_CHAT_ID:
            add_chat_contact(SELF_CHAT_LABEL, SELF_CHAT_ID, SELF_CHAT_TYPE)
            continue

        if not members:
            missing_members += 1
            # Still add to recentcontacts if it has a topic
            if topic:
                add_chat_contact(topic, chat_id, chat_type)
            continue

        # Collect people from members
        for m in members:
            upn = m.get("upn", "") or m.get("email", "")
            if upn:
                key = upn.lower().strip()
                if key not in all_people:
                    all_people[key] = {
                        "displayName": m.get("displayName", ""),
                        "upn": upn,
                        "userId": m.get("userId", ""),
                    }

        # Add chat to recentcontacts
        if chat_type == "OneOnOne" and len(members) >= 2:
            # Use the counterparty name (member who is NOT the current user)
            # Heuristic: pick the member whose UPN differs from the owner
            # Since we don't know the owner UPN here, add both and let dedup handle it
            # Better heuristic: use the first member by default; the SKILL.md instructs
            # the agent to call add-chat with the correct counterparty name
            counterparty = _find_counterparty(members)
            label = counterparty.get("displayName", "") if counterparty else topic or chat_id[:30]
            add_chat_contact(label, chat_id, chat_type)
        elif topic:
            add_chat_contact(topic, chat_id, chat_type)

        # Add each member to recentcontacts
        for m in members:
            upn = m.get("upn", "") or m.get("email", "")
            name = m.get("displayName", "")
            user_id = m.get("userId", "")
            if upn and name:
                add_person_contact(name, upn, user_id)

    # Write derived people cache
    if all_people:
        write_cache("people", list(all_people.values()))

    if missing_members > 0:
        print(f"WARNING: {missing_members}/{len(chats)} chats have no members. "
              f"Run ListChatMembers for each chat and include members in cache entries.",
              file=sys.stderr)


def _find_counterparty(members: list[dict]) -> dict | None:
    """From a OneOnOne chat's member list, find the counterparty (non-owner).

    Reads recentcontacts.md to find the current user's UPN and exclude them.
    Returns the other member, or the first member if the owner can't be determined.
    Returns None for self-chats (single member).
    """
    if len(members) < 2:
        return members[0] if members else None
    contacts = read_recent_contacts()
    owner_upns = set()
    # The first person in recentcontacts is typically the owner
    for p in contacts.get("people", []):
        owner_upns.add(p["upn"].lower().strip())

    # If we have exactly 2 members and one matches a known person, pick the other
    if len(members) == 2:
        m0_upn = (members[0].get("upn", "") or members[0].get("email", "")).lower().strip()
        m1_upn = (members[1].get("upn", "") or members[1].get("email", "")).lower().strip()
        # Prefer the member that is NOT in our contacts (likely the counterparty)
        # But actually, both may be in contacts. Use a simpler heuristic:
        # check if one matches a well-known owner pattern
        if m0_upn in owner_upns and m1_upn not in owner_upns:
            return members[1]
        if m1_upn in owner_upns and m0_upn not in owner_upns:
            return members[0]

    # Fallback: return first member
    return members[0] if members else None


def _auto_populate_from_teams(teams: list) -> None:
    """After writing teams cache, auto-update recentcontacts with channels."""
    for team in teams:
        team_name = team.get("displayName", "")
        team_id = team.get("id", "")
        for channel in team.get("channels", []):
            channel_name = channel.get("displayName", "")
            channel_id = channel.get("id", "")
            if team_name and channel_name and team_id and channel_id:
                add_channel_contact(team_name, channel_name, team_id, channel_id)


def normalize(s: str) -> str:
    return s.lower().strip()


def _token_match(query: str, text: str) -> bool:
    """Check if *query* matches *text* at word boundaries.

    Prevents false positives like "self" matching "Vendor Self-Service".
    The query must match the full text, or appear as a complete word/token
    (delimited by spaces, punctuation other than hyphens, or string edges).
    Hyphens are treated as word-internal characters to prevent "self" from
    matching in "self-service" (a hyphenated compound word).
    """
    if not query or not text:
        return False
    q = normalize(query)
    t = normalize(text)
    if q == t:
        return True
    # Word-boundary match: query must be surrounded by non-word characters.
    # Include hyphen in the word-character class so "self" won't match
    # "self-service" (the hyphen connects them into one token).
    return bool(re.search(r'(?<![a-z0-9-])' + re.escape(q) + r'(?![a-z0-9-])', t))


def cmd_lookup_person(query: str) -> None:
    cache = read_cache("people")
    if not cache or not cache.get("data"):
        print(json.dumps([]))
        return
    results = [
        p for p in cache["data"]
        if _token_match(query, p.get("displayName", ""))
        or _token_match(query, p.get("upn", ""))
    ]
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_lookup_chat(query: str) -> None:
    """Find chats by member UPN, member display name, or chat topic.

    Searches:
    0. Self-chat (Notes to Self) if query matches "self", "notes", etc.
    1. OneOnOne/Group/Meeting chats for members matching the query (UPN or display name)
    2. Group/Meeting chats for topic matching the query
    """
    q = normalize(query)

    # Check for self-chat queries first (fast path, no cache needed)
    self_keywords = {"self", "notes", "self-chat", "self chat", "notes to self", "48:notes"}
    if q in self_keywords:
        # Check recentcontacts for the cached self-chat entry
        contacts = read_recent_contacts()
        for c in contacts.get("chats", []):
            if c["chatId"] == SELF_CHAT_ID:
                print(json.dumps([{
                    "chatId": SELF_CHAT_ID,
                    "chatType": SELF_CHAT_TYPE,
                    "topic": SELF_CHAT_LABEL,
                    "matchedMember": None,
                    "matchedUpn": None,
                    "memberCount": 1,
                }], indent=2))
                return
        # Not cached yet — return the well-known ID anyway
        print(json.dumps([{
            "chatId": SELF_CHAT_ID,
            "chatType": SELF_CHAT_TYPE,
            "topic": SELF_CHAT_LABEL,
            "matchedMember": None,
            "matchedUpn": None,
            "memberCount": 1,
        }], indent=2))
        return

    cache = read_cache("chats")
    if not cache or not cache.get("data"):
        print(json.dumps([]))
        return
    q = normalize(query)
    results = []
    seen_ids: set[str] = set()
    for chat in cache["data"]:
        chat_id = chat.get("id", "")
        if chat_id in seen_ids:
            continue

        # Search members by UPN or display name (word-boundary match)
        members = chat.get("members", [])
        for m in members:
            member_upn = m.get("upn", "") or m.get("email", "")
            member_name = m.get("displayName", "")
            if _token_match(query, member_upn) or _token_match(query, member_name):
                results.append({
                    "chatId": chat_id,
                    "chatType": chat.get("chatType"),
                    "topic": chat.get("topic", ""),
                    "matchedMember": m.get("displayName"),
                    "matchedUpn": m.get("upn") or m.get("email"),
                    "memberCount": len(members),
                })
                seen_ids.add(chat_id)
                break

        # Also search by topic for Group/Meeting chats (word-boundary match)
        if chat_id not in seen_ids:
            topic = chat.get("topic", "")
            if topic and _token_match(query, topic):
                results.append({
                    "chatId": chat_id,
                    "chatType": chat.get("chatType"),
                    "topic": topic,
                    "matchedMember": None,
                    "matchedUpn": None,
                    "memberCount": len(members),
                })
                seen_ids.add(chat_id)

    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_lookup_team(query: str) -> None:
    cache = read_cache("teams")
    if not cache or not cache.get("data"):
        print(json.dumps([]))
        return
    results = [
        t for t in cache["data"]
        if _token_match(query, t.get("displayName", ""))
    ]
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_lookup_channel(team_id: str, query: str) -> None:
    cache = read_cache("teams")
    if not cache or not cache.get("data"):
        print(json.dumps([]))
        return
    for team in cache["data"]:
        if team.get("id") == team_id:
            channels = team.get("channels", [])
            results = [
                c for c in channels
                if _token_match(query, c.get("displayName", ""))
            ]
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return
    print(json.dumps([]))


def cmd_resolve(query: str) -> None:
    """Unified resolver — searches recentcontacts.md first, then JSON caches.

    Returns a JSON object with the best match across all tiers:
    {
      "found": true/false,
      "tier": "contacts" | "cache" | null,
      "person": { "name", "upn", "userId" } | null,
      "chat": { "chatId", "chatType", "personOrTopic" } | null,
      "channel": { "team", "channel", "teamId", "channelId" } | null,
      "allMatches": { "people": [...], "chats": [...], "channels": [...] }
    }
    """
    q = normalize(query)

    # Self-chat fast path
    self_keywords = {"self", "notes", "self-chat", "self chat", "notes to self", "48:notes"}
    if q in self_keywords:
        print(json.dumps({
            "found": True, "tier": "builtin",
            "person": None,
            "chat": {"chatId": SELF_CHAT_ID, "chatType": SELF_CHAT_TYPE,
                     "personOrTopic": SELF_CHAT_LABEL},
            "channel": None,
            "allMatches": {"people": [], "chats": [{
                "chatId": SELF_CHAT_ID, "chatType": SELF_CHAT_TYPE,
                "personOrTopic": SELF_CHAT_LABEL}], "channels": []},
        }, indent=2))
        return

    result = {
        "found": False, "tier": None,
        "person": None, "chat": None, "channel": None,
        "allMatches": {"people": [], "chats": [], "channels": []},
    }

    # -- Tier 1: recentcontacts.md (word-boundary matching) --
    contacts = read_recent_contacts()

    matched_people = [
        p for p in contacts.get("people", [])
        if _token_match(query, p.get("name", "")) or _token_match(query, p.get("upn", ""))
    ]
    matched_chats = [
        c for c in contacts.get("chats", [])
        # chatId is an opaque identifier (e.g. "19:abc@thread.v2") --
        # exact match only; word-boundary matching is not applicable.
        if _token_match(query, c.get("personOrTopic", "")) or c.get("chatId", "") == query
    ]
    matched_channels = [
        ch for ch in contacts.get("channels", [])
        if _token_match(query, ch.get("channel", "")) or _token_match(query, ch.get("team", ""))
    ]

    if matched_people or matched_chats or matched_channels:
        result["found"] = True
        result["tier"] = "contacts"
        if matched_people:
            result["person"] = matched_people[0]
        if matched_chats:
            result["chat"] = matched_chats[0]
        if matched_channels:
            result["channel"] = matched_channels[0]
        result["allMatches"] = {
            "people": matched_people,
            "chats": matched_chats,
            "channels": matched_channels,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # -- Tier 2: JSON caches (word-boundary matching) --
    # People
    people_cache = read_cache("people")
    if people_cache and people_cache.get("data"):
        matched_people = [
            {"name": p.get("displayName", ""), "upn": p.get("upn", ""),
             "userId": p.get("userId", "")}
            for p in people_cache["data"]
            if _token_match(query, p.get("displayName", ""))
            or _token_match(query, p.get("upn", ""))
        ]

    # Chats
    chats_cache = read_cache("chats")
    if chats_cache and chats_cache.get("data"):
        seen_ids: set[str] = set()
        for chat in chats_cache["data"]:
            chat_id = chat.get("id", "")
            if chat_id in seen_ids:
                continue
            topic = chat.get("topic", "")
            # Match by topic (word-boundary)
            if topic and _token_match(query, topic):
                matched_chats.append({
                    "chatId": chat_id, "chatType": chat.get("chatType", ""),
                    "personOrTopic": topic})
                seen_ids.add(chat_id)
                continue
            # Match by member name or UPN (word-boundary)
            for m in chat.get("members", []):
                mname = m.get("displayName", "")
                mupn = m.get("upn", "") or m.get("email", "")
                if _token_match(query, mname) or (mupn and _token_match(query, mupn)):
                    label = m.get("displayName", "") if chat.get("chatType") == "OneOnOne" else topic or chat_id[:30]
                    matched_chats.append({
                        "chatId": chat_id, "chatType": chat.get("chatType", ""),
                        "personOrTopic": label})
                    seen_ids.add(chat_id)
                    break

    # Teams/channels
    teams_cache = read_cache("teams")
    if teams_cache and teams_cache.get("data"):
        for team in teams_cache["data"]:
            team_name = team.get("displayName", "")
            team_id = team.get("id", "")
            if _token_match(query, team_name):
                for ch in team.get("channels", []):
                    matched_channels.append({
                        "team": team_name, "channel": ch.get("displayName", ""),
                        "teamId": team_id, "channelId": ch.get("id", "")})
            else:
                for ch in team.get("channels", []):
                    if _token_match(query, ch.get("displayName", "")):
                        matched_channels.append({
                            "team": team_name, "channel": ch.get("displayName", ""),
                            "teamId": team_id, "channelId": ch.get("id", "")})

    if matched_people or matched_chats or matched_channels:
        result["found"] = True
        result["tier"] = "cache"
        if matched_people:
            result["person"] = matched_people[0]
        if matched_chats:
            result["chat"] = matched_chats[0]
        if matched_channels:
            result["channel"] = matched_channels[0]
        result["allMatches"] = {
            "people": matched_people,
            "chats": matched_chats,
            "channels": matched_channels,
        }

    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_build_teams() -> None:
    """Build teams cache from raw MCP API responses.

    Reads JSON from stdin:
    {
      "teams": [<items from ListTeams response>],
      "channels": {"<teamId>": [<items from ListChannels response>], ...}
    }

    Transforms into cache format and writes teams cache + populates recentcontacts.
    """
    raw = json.loads(sys.stdin.read())
    teams_raw = raw.get("teams", [])
    channels_map = raw.get("channels", {})

    teams_data = []
    for team in teams_raw:
        team_id = team.get("id", "")
        display_name = team.get("displayName", "")
        team_channels = []
        for ch in channels_map.get(team_id, []):
            team_channels.append({
                "id": ch.get("id", ""),
                "displayName": ch.get("displayName", ""),
            })
        teams_data.append({
            "id": team_id,
            "displayName": display_name,
            "channels": team_channels,
        })

    write_cache("teams", teams_data)
    _auto_populate_from_teams(teams_data)
    print(f"Built teams cache: {len(teams_data)} teams, "
          f"{sum(len(t['channels']) for t in teams_data)} channels")


def cmd_build_chats() -> None:
    """Build chats cache from raw MCP API responses.

    Reads JSON from stdin:
    {
      "chats": [<items from ListChats response>],
      "members": {"<chatId>": [<items from ListChatMembers response>], ...}
    }

    Merges members into each chat entry, writes chats cache, derives people cache,
    and populates recentcontacts.
    """
    raw = json.loads(sys.stdin.read())
    chats_raw = raw.get("chats", [])
    members_map = raw.get("members", {})

    chats_data = []
    for chat in chats_raw:
        chat_id = chat.get("id", "")
        raw_members = members_map.get(chat_id, [])
        members = []
        for m in raw_members:
            upn = m.get("email", "") or m.get("upn", "")
            members.append({
                "displayName": m.get("displayName", ""),
                "upn": upn,
                "userId": m.get("userId", ""),
            })
        chats_data.append({
            "id": chat_id,
            "topic": chat.get("topic", ""),
            "chatType": chat.get("chatType", ""),
            "members": members,
        })

    write_cache("chats", chats_data)
    _auto_populate_from_chats(chats_data)
    with_members = sum(1 for c in chats_data if c.get("members"))
    print(f"Built chats cache: {len(chats_data)} chats ({with_members} with members)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        cmd_status()
    elif cmd == "is-stale":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py is-stale <chats|teams|people>", file=sys.stderr)
            sys.exit(2)
        cmd_is_stale(sys.argv[2])
    elif cmd == "read":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py read <chats|teams|people>", file=sys.stderr)
            sys.exit(2)
        cmd_read(sys.argv[2])
    elif cmd == "write":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py write <chats|teams|people>", file=sys.stderr)
            sys.exit(2)
        cmd_write(sys.argv[2])
    elif cmd == "lookup-person":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py lookup-person <name>", file=sys.stderr)
            sys.exit(2)
        cmd_lookup_person(" ".join(sys.argv[2:]))
    elif cmd == "lookup-chat":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py lookup-chat <upn>", file=sys.stderr)
            sys.exit(2)
        cmd_lookup_chat(sys.argv[2])
    elif cmd == "lookup-team":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py lookup-team <name>", file=sys.stderr)
            sys.exit(2)
        cmd_lookup_team(" ".join(sys.argv[2:]))
    elif cmd == "lookup-channel":
        if len(sys.argv) < 4:
            print("Usage: cache-manager.py lookup-channel <team_id> <name>", file=sys.stderr)
            sys.exit(2)
        cmd_lookup_channel(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "read-contacts":
        contacts = read_recent_contacts()
        print(json.dumps(contacts, indent=2, ensure_ascii=False))
    elif cmd == "add-person":
        if len(sys.argv) < 5:
            print("Usage: cache-manager.py add-person <name> <upn> <user_id>", file=sys.stderr)
            sys.exit(2)
        add_person_contact(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "add-chat":
        if len(sys.argv) < 5:
            print("Usage: cache-manager.py add-chat <person_or_topic> <chat_id> <chat_type>",
                  file=sys.stderr)
            sys.exit(2)
        add_chat_contact(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "add-channel":
        if len(sys.argv) < 6:
            print("Usage: cache-manager.py add-channel <team> <channel> <team_id> <channel_id>",
                  file=sys.stderr)
            sys.exit(2)
        add_channel_contact(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "build-teams":
        cmd_build_teams()
    elif cmd == "build-chats":
        cmd_build_chats()
    elif cmd == "resolve":
        if len(sys.argv) < 3:
            print("Usage: cache-manager.py resolve <query>", file=sys.stderr)
            sys.exit(2)
        cmd_resolve(" ".join(sys.argv[2:]))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
