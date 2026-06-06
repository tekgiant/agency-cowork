---
name: workstreams
description: |
  Manage program workstreams — meeting summaries, action item tracking,
  and Landing Zone cross-referencing. Use this skill when the user asks to
  "summarize a workstream meeting", "track action items", "list workstreams",
  "workstream status", "post to workstream channel", "what are the open actions",
  "show overdue items", or any workstream management operation. Triggers include
  "workstream", "action items", "meeting notes for <workstream>", "post summary to channel".
---

# Workstreams Skill

Orchestrate workstream management: meeting summaries, action item tracking, KB storage, and Landing Zone cross-referencing — all mapped to Teams channels.

## Paths

`${PLUGIN_ROOT}` = `C:\Projects\Agency-Cowork\skills\workstreams`

| Alias | Path | Contains |
|-------|------|----------|
| Registry | `${PLUGIN_ROOT}/registry.json` | Workstream → channel + KB folder + LZ domain mapping |
| Tracker | `${PLUGIN_ROOT}/scripts/ws_tracker.py` | Action item CLI |
| KB Root | `C:\Projects\Agency-Cowork\memory\Knowledgebase\Workstreams` | Per-program/workstream folders |

## Registry

The registry (`registry.json`) maps each workstream to:
- `program` — program identifier (e.g., `program-alpha`, `program-beta`)
- `slug` — kebab-case folder name
- `display_name` — human-readable name
- `channel_id` — Teams channel ID (tacv2 format, in the program team)
- `meeting_chat_id` — recurring meeting chat ID (if separate from channel)
- `kb_path` — relative path under Workstreams/ (e.g., `program-alpha/backend-network`)
- `lz_domains` — array of related LZ technology domain names

**Team ID:** Set `team_id` in `registry.json` to your Microsoft Teams team GUID.

Always read `registry.json` first to resolve workstream names to IDs and paths.

## Decision Table

| User Intent | Action | Details |
|-------------|--------|---------|
| List workstreams | Read registry | Show table of workstreams grouped by program |
| Summarize workstream meeting | Meeting Summary Flow (below) | Full workflow: summarize → save → extract actions → LZ check → post |
| View action items | `ws_tracker list` | Optional filters: `--workstream`, `--dri`, `--overdue`, `--all` |
| Add action item | `ws_tracker add` | Requires: `--workstream`, `--description`. Optional: `--dri`, `--due`, `--source`, `--lz-req` |
| Update action item | `ws_tracker update` | `--id` + any of: `--status`, `--dri`, `--due`, `--note` |
| Close action item | `ws_tracker close` | `--id` + optional `--note` |
| Action items summary | `ws_tracker summary` | Markdown report, optional `--program` filter |
| Workstream status | Combined query | Action items + LZ grading % for mapped domains |
| Post to workstream channel | Teams post | Use teams skill rich messaging to post to channel |

## Tracker Commands

All run from `skills/workstreams`:

```bash
cd skills/workstreams

# Add action item
python -m scripts.ws_tracker add -w my-program/my-workstream -d "Finalize spec" --dri "Jane Doe" --due 2026-03-15

# List open items (all workstreams)
python -m scripts.ws_tracker list

# List overdue items
python -m scripts.ws_tracker list --overdue

# List by DRI
python -m scripts.ws_tracker list --dri "Drew"

# List for one workstream
python -m scripts.ws_tracker list -w my-program/my-workstream

# Update status
python -m scripts.ws_tracker update --id ai-001 --status in-progress

# Add a note
python -m scripts.ws_tracker update --id ai-001 --note "Reviewed in weekly sync"

# Close with resolution
python -m scripts.ws_tracker close --id ai-001 --note "Spec finalized and uploaded"

# Markdown summary for exec reporting
python -m scripts.ws_tracker summary

# Summary filtered to one program
python -m scripts.ws_tracker summary -p my-program
```

## Meeting Summary Flow

When the user asks to summarize a workstream meeting:

### Step 1: Identify the Workstream

Match the meeting subject against registry entries:
- Check if subject contains a workstream `display_name` or `slug`
- Check if the meeting chat ID matches a `meeting_chat_id` in registry
- If ambiguous, ask the user which workstream this meeting belongs to

### Step 2: Generate Meeting Summary

Follow the **meeting-summary skill** workflow (Steps 1-6):
1. Find the meeting via calendar
2. Get the Teams meeting chat
3. Get the transcript via WorkIQ
4. Apply transcription corrections
5. Determine program name (from registry, not by inference)
6. Generate structured summary with the standard template

### Step 3: Save to Workstream KB

Save the meeting notes to the workstream's KB folder:

```
memory/Knowledgebase/Workstreams/{kb_path}/meeting-notes/{YYYY-MM-DD}-{subject-slug}.md
```

**Single save only** — do NOT also save to `Program/{PROGRAM}/Meeting Notes/`. The workstream folder is the canonical location.

If the meeting is NOT associated with any workstream, fall back to the existing meeting-summary path: `memory/Knowledgebase/Program/{PROGRAM}/Meeting Notes/`.

### Step 4: Extract Action Items

Scan the generated meeting notes for action items:
1. Parse the `## Action Items` table from the meeting summary
2. For each action item, use `ws_tracker add`:
   - `--workstream` = the identified workstream slug
   - `--description` = action description
   - `--dri` = DRI column value
   - `--due` = due date (infer from notes or set to 2 weeks out)
   - `--source` = meeting note filename slug

Present the extracted items to the user and ask for confirmation before adding.

### Step 5: Requirement Detection & LZ Cross-Reference

After generating the summary, scan the detailed meeting notes for requirement-related signals:

**Trigger keywords** (case-insensitive):
- "requirement", "requirements", "landing zone", "LZ"
- "minimum", "target", "POR", "plan of record"
- "grading", "grade", "architecture response"
- "spec", "specification"
- Domain-specific terms matching the workstream's `lz_domains` from registry

**When requirement signals are detected:**

1. **Identify related LZ requirements:**
   - Use `lz_query -p {program} --domain "{domain}"` for each domain in the workstream's `lz_domains`
   - If a specific requirement ID is mentioned, fetch it directly

2. **Show context to user:**
   - Quote the relevant meeting discussion
   - Show the matching LZ requirement(s) with current state/description

3. **Propose an update — ask user to choose:**
   - **Update description** (`lz_update --action update-desc`): if the requirement definition changed
   - **Add comment** (`lz_update --action add-comment`): if it's a status update, decision, or note
   - **Create new requirement** (`lz_update --action create`): if a new requirement was identified
   - **Skip**: no LZ update needed

4. **Execute only after explicit user confirmation.**

### Step 6: Post to Workstream Channel

After saving notes and processing action items, ask the user if they want to post the summary to the workstream's Teams channel.

If yes, use the teams skill rich messaging to post:
- Post to `channel_id` from registry (using `team_id` from `registry.json`)
- Format as rich HTML with the executive summary + action items table
- Include a link to the full meeting notes (if a recording/recap URL is available)

Use `microsoft-teams-PostChannelMessage` with `contentType: "html"`.

## Workstream Status Query

When the user asks for workstream status, combine:

1. **Action items**: Run `ws_tracker list -w {slug}` to get open items count + overdue count
2. **LZ grading** (if domains mapped): Run `lz_query -p {program} --domain "{domain}"` for each `lz_domains` entry to get grading progress
3. **Recent meeting notes**: List files in `{kb_path}/meeting-notes/` sorted by date, show the latest 3

Present as a concise status card:
```
## {Display Name} Workstream — {Program}
- **Open actions:** 5 (2 overdue)
- **LZ grading:** Networking 50%, Data Transfers 28%
- **Last meeting:** 2026-03-01 (Weekly Backend Network Sync)
```

## Known Workstreams

No workstreams are pre-configured. Populate `registry.json` with your program's workstream definitions following this structure:

```json
{
  "program": "program-alpha",
  "slug": "backend-network",
  "display_name": "Backend Network",
  "channel_id": "19:your-channel-id@thread.tacv2",
  "meeting_chat_id": null,
  "kb_path": "program-alpha/backend-network",
  "lz_domains": ["Networking", "Data Transfers"]
}
```

## Rules

1. **Always read `registry.json`** before any workstream operation — do not hardcode channel IDs.
2. **Single save for workstream meetings** — save to `Workstreams/{kb_path}/meeting-notes/` only. Fall back to `Program/` path only for non-workstream meetings.
3. **Confirm before adding action items** — show extracted items to user before writing to action-items.json.
4. **Confirm before LZ updates** — always show the proposed change and get explicit approval.
5. **Confirm before posting to channel** — always show the content and channel name before posting.
6. **Sync LZ before cross-referencing** — if LZ cache is >24h old, run `lz_sync` first.
7. **Use `python -m scripts.ws_tracker`** — always invoke from `skills/workstreams/` directory.
