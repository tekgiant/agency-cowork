# teams

Interact with Microsoft Teams directly from the agent — send messages, read chats and channels, manage teams/channels/members, and search conversations. Includes a **local cache layer** for fast lookups of conversations, channels, and people.

## Prerequisites

- **Microsoft Teams MCP** configured in `~/.copilot/mcp-config.json` (the `microsoft-teams` server)
- **WorkIQ MCP** for user/UPN lookups
- **Python 3.11+** for the cache manager script

## Registration

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\teams"
```

Restart your Copilot session for the skill to appear in `/skills`.

## Usage

The skill activates automatically when you interact with Teams:

```
Send Adam a Teams message saying "meeting pushed to 3pm"
```

```
What are the latest messages in the Project Alpha General?
```

```
Refresh my Teams cache
```

### Cache Management

The skill maintains a local cache of your chats, teams/channels, and people for fast ID resolution:

| Cache | Contents | Auto-refresh |
|-------|----------|-------------|
| `chats.json` | All chats with member details | Every 4 hours |
| `teams-and-channels.json` | Teams and their channels | Every 4 hours |
| `people.json` | Known people (name, UPN, ID) | Every 4 hours |

**Manual refresh:**
- `"Refresh Teams cache"` — Rebuild all caches
- `"Refresh Teams chats"` — Rebuild chats only
- `"Refresh Teams teams"` — Rebuild teams/channels only

### Cache Manager Script

```powershell
# Check cache status
python skills/teams/scripts/cache-manager.py status

# Look up a person
python skills/teams/scripts/cache-manager.py lookup-person "Adam Smith"

# Find 1:1 chat by UPN
python skills/teams/scripts/cache-manager.py lookup-chat "adam@contoso.com"

# Find a team by name
python skills/teams/scripts/cache-manager.py lookup-team "your-team"
```

## Capabilities

- **Send messages** to chats and channels
- **Read messages** from chats and channels
- **Search** across all Teams conversations
- **Create** chats (1:1 and group), channels (standard and private)
- **Manage members** — add to chats/channels, update roles
- **Update/delete** chats, channels, and messages
- **Reply** to channel messages

## Limitations

- Cache is local to the machine — not shared across devices
- Channel member enumeration requires team membership
- Meeting chats are read-only (cannot post to meeting chats via MCP in some cases)
