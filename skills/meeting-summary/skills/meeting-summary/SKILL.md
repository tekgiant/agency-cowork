---
name: meeting-summary
description: |
  Generate executive meeting summaries from Teams meeting recaps and transcripts. Use this skill when the user asks to "summarize a meeting", "create meeting notes", "get meeting recap", "write meeting summary", or wants to produce formatted meeting notes from a Teams meeting. Triggers include "meeting summary", "meeting notes", "recap", "summarize the meeting", "what happened in the meeting".
---

# Meeting Summary Skill

Generate executive-quality meeting summaries from Microsoft Teams meeting transcripts. Produces structured markdown with executive summary, action items, and detailed notes.

## Paths

`${PLUGIN_ROOT}` refers to the **plugin root directory** — the parent of `.claude-plugin/` and `skills/`.

The plugin root is the `skills/meeting-summary` directory within your project.

The Knowledgebase root is: `memory/Knowledgebase` (relative to project root)

## Workflow

### Step 1: Identify the Meeting

Determine which meeting the user wants summarized. The user may provide:
- A meeting name/subject (exact or partial)
- A date or time reference ("this morning", "yesterday's standup", "the 2pm meeting")
- Both name and date

**Search strategy (in order):**

1. **Calendar search** — Use `microsoft-outlook-calendar-ListCalendarView` to find the meeting:
   - For "today" or "this morning": search today's date range
   - For "yesterday": search yesterday's date range
   - For "last week": search the past 7 days
   - Use the `subject` parameter to filter by meeting name if provided
   - Use `timeZone: "Pacific Standard Time"` (user's timezone)

2. **If multiple matches**, ask the user to clarify which meeting they mean. Present a numbered list with subject, date, and time.

3. **Extract from the calendar event:**
   - `subject` — Meeting title
   - `id` — Event ID (needed for recap link)
   - `start.dateTime` / `end.dateTime` — Meeting time
   - `onlineMeeting` — Teams meeting join URL
   - `attendees` — Participant list

### Step 2: Find the Meeting Recording & Chat

#### 2a: Find the recording on SharePoint

Search for the meeting recording (.mp4) in SharePoint:

```
microsoft-sharepoint-and-onedrive-findFileOrFolder with searchQuery: "<meeting subject> <YYYYMMDD> Meeting Recording"
```

**Include the date** in the search query (e.g., `<Program> <Meeting Name> 20260305 Meeting Recording`) — this dramatically improves precision for recurring meetings that have many recordings. The date format in recording filenames is `YYYYMMDD_HHmmss` (UTC).

Look for `.mp4` files matching the meeting name. From the result, extract:
- **`driveId`** — from `parentReference.driveId`
- **`itemId`** — the `id` field of the recording DriveItem

Then call `microsoft-sharepoint-and-onedrive-getFileOrFolderMetadata` to get the full metadata, which provides:
- **`siteUrl`** — from `sharepointIds.siteUrl` (e.g., `https://contoso.sharepoint.com/teams/MyTeam`)
- **`parentReference.path`** — Confirms storage location (team site vs. personal OneDrive)

> **Important:** The `siteUrl` MUST come from `sharepointIds.siteUrl` in the metadata response — do NOT try to derive it from `webUrl` or construct it manually.

**Storage location rules:**
- **Channel-scheduled meetings**: Recordings are in the **team site** SharePoint (e.g., `MyTeam/Shared Documents/Recordings/View Only/`)
- **Personal meetings**: Recordings are in the **organizer's OneDrive** (`/personal/<alias>_microsoft_com/Documents/Recordings/`)

If multiple recordings match, filter by date (compare `createdDateTime`) and exact meeting name. **Do not skip recordings based on file size** — small recordings (even <1 MB) can still have full transcripts.

#### 2b: Find the meeting chat (optional, for context)

Use `microsoft-teams-SearchTeamsMessages` to find the meeting chat and recap:

```
microsoft-teams-SearchTeamsMessages with message: "<meeting subject> meeting recap"
```

From the search results, extract:
- **Meeting chat ID** — The `19:meeting_...@thread.v2` chat ID
- **Recap URL** — Look for links containing `meetingrecap` or `meeting/details`
- **Any shared attachments** — PowerPoint, documents shared in the chat

### Step 3: Get the Meeting Transcript

Use a **multi-method fallback chain** — try each method in order until one succeeds:

#### Method A: SharePoint Transcript API (Primary — Recommended)

If a recording was found in Step 2a, download the transcript directly using the cross-platform `get_transcript.py` script:

**Windows:**
```powershell
cd skills/meeting-summary
python -m scripts.get_transcript --site-url "<siteUrl>" --drive-id "<driveId>" --item-id "<itemId>" --format text -o "../../output/<meeting-slug>-transcript.txt"
```

**macOS:**
```bash
cd skills/meeting-summary && python3 -m scripts.get_transcript \
  --site-url '<siteUrl>' \
  --drive-id '<driveId>' \
  --item-id '<itemId>' \
  --format text \
  -o '../../output/<meeting-slug>-transcript.txt'
```

> **macOS prerequisites:** Run the setup script once first: `bash skills/meeting-summary/scripts/setup.sh`

> **macOS CRITICAL:** Use `python3` (not `python`) and **single quotes** for ALL arguments — drive IDs contain `!` which bash silently eats in double quotes. Check the `Args:` debug line in stderr to verify `drive_id` is not `None`.

> **CRITICAL — Parameter order:** The script signature is `fetch_transcript_direct_api(site_url, drive_id, item_id)`. When calling from Python, **always use keyword arguments** to avoid order mistakes:
> ```python
> vtt = await fetch_transcript_direct_api(site_url=site_url, drive_id=drive_id, item_id=item_id)
> ```

**Prerequisites:**
- **Playwright + Edge** — the script uses a CDP (Chrome DevTools Protocol) connection to a standalone Edge browser profile. This works even when Edge is already open for normal use.
- The standalone profile at `~/.teams-agent/browser-profile/` caches M365 auth cookies. First run may require interactive login; subsequent runs reuse the session.
- The script uses CDP port **9224** (unique to meeting-summary; Teams skill uses 9223).
- The script auto-detects the platform (`sys.platform`) and uses the correct Edge paths, process detection, and signal handling for Windows or macOS.

**How to get the parameters:**
1. Use `microsoft-sharepoint-and-onedrive-findFileOrFolder` with the meeting subject + date to find the `.mp4` recording
2. Use `microsoft-sharepoint-and-onedrive-getFileOrFolderMetadata` on the recording to get:
   - `siteUrl` from `sharepointIds.siteUrl` (**required** — this is the SharePoint site base URL)
   - `driveId` from `parentReference.driveId`
   - `itemId` from `id`

**Alternative discovery (especially useful on macOS):** Recordings land in whichever user hit "Record" — not necessarily the organizer. If `findFileOrFolder` fails, use Teams message search instead:
```
microsoft-teams-SearchTeamsMessages with message: "<meeting subject> Recording"
```
Look for a SharePoint URL ending in `-Meeting Recording.mp4` in the results, then call `getFileOrFolderMetadataByUrl` to get the driveId, itemId, and siteUrl.

**MCP auth retry:** If `findFileOrFolder` or `getFileOrFolderMetadata` returns `AADSTS9010010` (token error), wait 30 seconds and retry once — these are transient token refresh failures.

This script:
1. Launches a separate Edge process via CDP with the standalone browser profile
2. Navigates to the SharePoint site to establish auth cookies
3. Calls `/_api/v2.1/drives/{driveId}/items/{itemId}/media/transcripts` to list transcripts
4. Downloads the VTT via `streamContent` endpoint (with 401 retry — up to 3 attempts with re-authentication)
5. Validates the response is actually VTT (not an error page) before saving
6. Parses VTT into clean `[HH:MM:SS] Speaker Name: text` format

**Output formats:**
- `--format text` — Speaker-attributed plain text (default, best for summarization)
- `--format vtt` — Raw WebVTT (for debugging or archival)
- `--format json` — Structured JSON with metadata

**If the script reports "No transcripts found"**: The meeting wasn't transcribed. Fall through to Method B or C.

#### Method B: WorkIQ Transcript (Fallback)

If Method A fails (no recording found, no transcript available, or auth issues):

```
workiq-ask_work_iq with question: "Get the full transcript of the '<meeting subject>' meeting from <date>. Include all speaker names and their statements."
```

WorkIQ has access to Teams meeting transcripts through the Microsoft 365 Copilot API.

**Known limitations:**
- WorkIQ may return transcripts from **the wrong week** for recurring meetings — always verify the date
- WorkIQ may report "not transcribed" for channel-scheduled meetings even when a transcript exists in SharePoint
- If the returned transcript date doesn't match, discard it and try Method C

#### Method C: Manual Transcript (Last Resort)

If both Method A and B fail:
1. Ask the user to download the transcript `.docx` from the Teams meeting recap page
2. Convert using markitdown: `markitdown "<path_to_docx>" -o "output/<slug>-transcript.md"`
3. Read the converted markdown as the transcript source

### Step 4: Apply Transcription Corrections

Apply standard corrections for common transcription errors in your domain. Maintain a corrections table
in your org-specific configuration (e.g., `skills/meeting-summary/transcription-corrections.json`).

Example format:

| Transcription Error | Correct Term |
|---------------------|-------------|
| Common misspelling | Correct product name |
| Phonetic mishearing | Correct acronym |

Apply these replacements to the transcript text before generating the summary. Use case-insensitive matching but preserve the correct casing in the replacement.

> **Enforcement:** Corrections MUST be applied before generating the summary. If using the transcript text directly from `get_transcript.py`, run corrections on the output file or in-memory text. This is frequently missed — double-check by searching the summary for known misheard terms before saving.

> **Tip:** An org-specific setup skill can populate `transcription-corrections.json` with domain-specific terms.

### Step 5: Determine Program and Workstream

#### 5a: Infer the Program Name

Infer the program name from the meeting subject for file organization. Program-to-subject mappings
should be configured per-organization (e.g., in `agentconfig.json` under `programs` or via an
org-specific setup skill).

General approach:

| Subject Contains | Program Name |
|------------------|-------------|
| Known program keyword | Mapped program name |
| Other | Ask the user which program folder to use |

#### 5b: Check for Special Meeting Categories

Some meetings have dedicated KB paths outside the workstream structure:

| Meeting Type | Detection | KB Path |
|-------------|-----------|---------|
| Program Execution Central (PEC) | Subject contains "PEC" or "Program Execution" | `ProgramExecutionCouncil/<program>/` |
| Executive Reviews | Subject contains "Exec Review" or "SLT" | `ExecutiveReviews/<program>/` |

If matched, set `kb_category` to the special path and skip workstream matching (Step 5c).

#### 5c: Match to Workstream (if applicable)

Check if this meeting belongs to a registered workstream by reading `skills/workstreams/registry.json`:

1. **Match by meeting chat ID** — Compare the meeting's Teams chat ID (`19:meeting_...@thread.v2`) against `meeting_chat_id` fields in the registry
2. **Match by subject keywords** — Compare the meeting subject against each workstream's `display_name` and `slug` from the registry. The registry maps subject keywords to workstream paths (e.g., "Design Review" → `<program>/<workstream-slug>`).
3. **If ambiguous**, ask the user which workstream this meeting belongs to (or "none" if it's a general program meeting)

**When a workstream is matched**, extract from the registry:
- `kb_path` — for saving notes (Step 7)
- `channel_id` — for posting summary (Step 9)
- `lz_domains` — for requirement cross-referencing (workstreams skill Step 5)

**When no workstream matches**, this is a general program meeting — use the standard `Program/<PROGRAM>/Meeting Notes/` path.

### Step 6: Generate Meeting Summary

Generate the meeting notes using this structure and voice:

**Voice and Perspective:** Summarize the meeting succinctly and identify action items to follow up. Write in active voice from the perspective of what topics "we" covered. Adapt the formality level to your organization's standards (configured in CLAUDE.md communication principles).

**Document Structure:**

```markdown
# <Meeting Subject>

**Date:** <Full date> | <Time range with timezone>
**Organizer:** <Name>
**Attendees:** <Comma-separated list of all participants>

---

## Executive Summary

<2-3 paragraph summary in active voice. Start with "We convened to..." or "We discussed..." 
Frame from the perspective of what topics were covered. Include key context and framing.>

### Top 3 Takeaways

1. **<Decision/Takeaway label>:** <Description>
2. **<Decision/Takeaway label>:** <Description>
3. **<Decision/Takeaway label>:** <Description>

---

## Action Items

| Area | Action Description | DRI | Due Date |
|------|--------------------|-----|----------|
| <2-3 word area> | <Action description> | <Person name> | <Date or "Ongoing"> |

---

## Detailed Meeting Notes

### 1. <Topic heading>
<Detailed notes for this topic section>

### 2. <Topic heading>
<Detailed notes for this topic section>

...

---

*[Meeting Recap](<recap_url>) | [Recording](<recording_url>)*
```

**Formatting rules:**
- Area column: 2-3 words max (e.g., "Landing Zone", "Retimer Escalation", "Network Ownership")
- Action descriptions: Concise but specific — include what needs to happen and what the outcome should be
- DRI: Full name of the responsible person
- Due dates: Infer reasonable dates (1-2 weeks out for follow-ups, "Ongoing" for persistent items, "As needed" for contingent items)
- Detailed notes: Organize by topic/theme, not chronologically. Use bullet points for individual contributions. Attribute key statements to speakers.
- Include links to the meeting recap and recording at the bottom
- Include links to any attachments or documents referenced in the meeting (ADO work items, SharePoint docs, etc.)

### Step 7: Save to Knowledgebase

Save the meeting notes based on what was matched in Steps 5b and 5c:

**Priority 1 — Special category matched (Step 5b):** Save to the category-specific folder:

```
Path: memory/Knowledgebase/<kb_category>/<YYYY-MM-DD>-<Meeting-Subject-Slug>.md
```

Examples:
- PEC: `ProgramExecutionCouncil/<program>/2026-03-05-Program-Execution-Central.md`
- Exec Review: `ExecutiveReviews/<program>/2026-03-05-Monthly-SLT-Review.md`

**Priority 2 — Workstream matched (Step 5c):** Save to the workstream's KB folder (canonical location):

```
Path: memory/Knowledgebase/Workstreams/<kb_path>/meeting-notes/<YYYY-MM-DD>-<Meeting-Subject-Slug>.md
```

Example: `Workstreams/<program>/<workstream>/meeting-notes/2026-03-05-Weekly-Standup.md`

**Single save only** — do NOT also save to `Program/<PROGRAM>/Meeting Notes/`. The workstream folder is the canonical location for workstream meetings.

**Priority 3 — No match:** Save to the program folder (general meetings):

```
Path: memory/Knowledgebase/Program/<PROGRAM NAME>/Meeting Notes/<YYYY-MM-DD>-<Meeting-Subject-Slug>.md
```

**File naming convention:**
- Date prefix: `YYYY-MM-DD` format
- Subject slug: Kebab-case, remove common program name prefixes to avoid redundancy
- Example: `2026-03-02-Update-Requirements-Alignment.md`

**Directory creation:** If the target directory doesn't exist, create it:
```bash
New-Item -ItemType Directory -Path "<target_dir>" -Force
```

### Step 8: Post to Workstream Channel

**If a workstream with a `channel_id` was matched in Step 5c**, offer to post the summary to the workstream's Teams channel.

**If a special category was matched in Step 5b** (PEC, Exec Review), look up the corresponding channel:
- PEC meetings → Post to the program's "Program Execution Central" channel (use `cache-manager.py resolve "<Program> Program Execution Central"` to find the channel ID)
- Exec Reviews → Usually not posted to channels (skip unless user requests)

**CONFIRMATION GATE (REQUIRED):** Before posting to ANY Teams channel or chat:
1. Show the user: target team name, channel name, channel ID, and a preview of the first 200 chars of the message body.
2. Ask for explicit confirmation: "Post meeting notes to **[Team] > [Channel]**? (yes/no)"
3. Do NOT post if the user declines or does not respond.
4. This gate applies in ALL contexts — interactive, scheduled, and batch.

1. **Prepare a channel-formatted version** of the meeting notes:
   - **ALWAYS** start the message body with `<Agent Name>: Here are the meeting notes from today's <Meeting Subject>.` (use the agent name from CLAUDE.md identity)
   - Convert the full markdown summary (exec summary, takeaways, action items table, ALL detailed notes sections) to HTML
   - Use semantic HTML tags: `<h2>`, `<h3>`, `<h4>`, `<b>`, `<ul>`, `<ol>`, `<table>`, `<a>`, `<em>`
   - Include: exec summary, top 3 takeaways, action items table, **all** detailed notes sections, and recording link
   - Save the HTML body to `output/<slug>-channel-post.html`

2. **Post via Graph MCP** — Use the Teams MCP with `contentType: html`:
   ```
   microsoft-teams-PostChannelMessage with:
     teamId: "<team_id>"
     channelId: "<channel_id>"
     content: "<html_body>"
     contentType: "html"
   ```
   - `team_id` = from the matched workstream registry entry (look up `team_id` field)
   - `channel_id` = from the matched workstream registry entry or cache-manager resolve

   > **Note on HTML support:** The Graph API supports basic HTML in channel messages: headings (h1-h4), bold, italic, links, lists, tables, and line breaks all render correctly. Use `<b>` instead of `<strong>` for widest compatibility. Avoid `<hr>` (use spacing instead) and complex nested HTML.

   > **Playwright sessions:** Both `get_transcript.py` and `send_message.py` use CDP connections to separate Edge processes with the standalone browser profile. They use different ports (9224 and 9223) so there are no conflicts. However, the Graph MCP approach above is simpler and preferred for channel posts.

3. **Fallback — Playwright rich messaging** (only if Graph MCP fails or tables don't render):
   ```powershell
   cd skills/teams
   python -m scripts.rich.send_message --channel "<channel_id>" --body "<html_body>"
   ```
   This launches its own CDP-based Playwright session (port 9223, standalone profile).

4. **Clean up** — Delete the temp HTML file from `output/`

**If no workstream or no channel_id** — skip this step. Optionally ask the user if they'd like to post to a specific channel.

### Step 9: Report to User

After saving and (optionally) posting, report:
- Confirm the file was saved and its path
- Confirm the channel post (if sent) with channel name and message ID
- Show the executive summary and action items table (not the full detailed notes — keep it brief)
- Mention the recap and recording links

## Rules

- **ALWAYS** apply transcription corrections before generating the summary — verify by searching for known misheard terms in the final output
- **ALWAYS** include the recording link at the bottom of the notes (recap link if available)
- **ALWAYS** include links to referenced documents (ADO work items, SharePoint files) in the detailed notes
- **ALWAYS** use active voice in the executive summary ("We discussed...", "The team agreed...")
- **ALWAYS** attribute key decisions and statements to specific speakers in the detailed notes
- **ALWAYS** start channel posts with the agent name prefix (from CLAUDE.md identity)
- **ALWAYS** post the **full** meeting notes to the channel (not just executive summary) — include all detailed note sections
- **ALWAYS** use keyword arguments when calling `fetch_transcript_direct_api(site_url=..., drive_id=..., item_id=...)`
- **ALWAYS** get `siteUrl` from `sharepointIds.siteUrl` via `getFileOrFolderMetadata` — never construct it manually
- **ALWAYS** include the date (YYYYMMDD) in `findFileOrFolder` search queries for recurring meetings
- **NEVER** fabricate transcript content — only summarize what was actually said
- **NEVER** include filler words, tangential chit-chat, or join/leave notifications in the summary
- **NEVER** include the raw transcript in the output file — only the structured summary
- **NEVER** skip a recording based on small file size — small recordings can still have full transcripts
- If MCP tools return `AADSTS9010010`, wait 30 seconds and retry once — this is a transient token refresh failure
- If DRM-protected slide decks can't be converted (BadZipFile / OLE2 error), try `skills/office_common/drm_handler.ps1 -Action strip` first; if COM is unavailable, skip and rely on the transcript alone
- If the transcript is unavailable, clearly state this and generate notes from available chat messages instead
- Keep the executive summary to 2-3 paragraphs max
- Top 3 takeaways should focus on **decisions made** and **key risks identified**
- Action items should be concrete and actionable — avoid vague "continue discussing" items unless no specific next step was identified
- For recurring meetings, focus on what's NEW or CHANGED from previous meetings
- **ALWAYS** check `skills/workstreams/registry.json` to match meetings to workstreams before deciding the save path
- **ALWAYS** offer to post to the workstream channel when a workstream with a `channel_id` is matched
- **NEVER** save workstream meeting notes to both `Workstreams/` and `Program/` — single save to `Workstreams/<kb_path>/meeting-notes/` only
- For PEC meetings, use `cache-manager.py resolve` to find the program-specific PEC channel rather than hardcoding channel IDs

## Automatic Summarization Setup

When the user asks to "auto-summarize" a meeting, "set up automatic meeting notes", or "schedule recurring summaries", use this workflow to create a task-scheduler task that runs the meeting-summary skill automatically after each occurrence.

### Setup Workflow

#### 1. Identify the Meeting

Find the recurring meeting on the calendar:
- Use `microsoft-outlook-calendar-ListCalendarView` to locate the meeting
- Extract: **subject**, **recurrence pattern** (day of week, time), **meeting chat ID** (`19:meeting_...@thread.v2`)
- Confirm the meeting is recurring (not one-time)

#### 2. Match to Workstream

Check `skills/workstreams/registry.json` for a matching workstream (same as Step 5c above). Extract:
- `kb_path` — KB save folder
- `channel_id` — Teams channel for posting (may be null)
- `lz_domains` — for cross-referencing (optional)

If no workstream match, determine the program name for the `Program/<PROGRAM>/Meeting Notes/` fallback path.

#### 3. Calculate Schedule

Set the task to run **30 minutes after the meeting ends**:
- Meeting end time + 30 min → cron expression
- Match the recurrence day (e.g., weekly Wednesday → `30 11 * * 3` for 11:30 AM PT)
- Account for timezone — cron is in local time (PT), `next_run` is in UTC

#### 4. Build the Task Prompt

Construct a self-contained prompt with all identifiers pre-resolved so the scheduled execution skips all lookups:

```
Use the meeting-summary skill to summarize today's <MEETING SUBJECT> meeting.

PRE-RESOLVED IDENTIFIERS (skip all lookups):
- Meeting chat ID: <19:meeting_...@thread.v2>
- Meeting subject: <full subject>
- Program: <PROGRAM_NAME>
- Workstream slug: <program/slug> (or "none" if no workstream)
- KB save path: <memory/Knowledgebase/Workstreams/<kb_path>/meeting-notes/ or Program/<PROGRAM>/Meeting Notes/>
- Teams channel ID: <channel_id> (or "none — skip channel post")
- Team ID: <TEAM_GUID> (from workstream registry)

EXECUTION STEPS:
1. Find the recording: search SharePoint for "<MEETING SUBJECT> <today's YYYYMMDD> Meeting Recording" using findFileOrFolder. Get driveId, itemId from result, then siteUrl from getFileOrFolderMetadata sharepointIds.siteUrl.
2. Get transcript: Run get_transcript.py with --site-url, --drive-id, --item-id (uses CDP, works with Edge open). If Method A fails, fall back to WorkIQ.
3. Apply transcription corrections per meeting-summary skill Step 4.
4. Generate structured meeting summary per meeting-summary skill Step 6 template.
5. Save to KB: <kb_save_path>/YYYY-MM-DD-<Subject-Slug>.md
6. Post full meeting notes to Teams channel via Graph MCP PostChannelMessage with contentType html. Start body with the agent name prefix.
7. Clean up temp files.
```

**Prompt guard notes:**
- Avoid the word "Format" as a standalone verb (triggers shell_injection false positive) — use "Prepare" instead
- Keep quoted text minimal — the guard scans for injection patterns in task prompts
- Test with `python scripts/prompt_guard.py --file <prompt_file> --source task` before creating

#### 5. Create the Scheduled Task

Use the task-scheduler skill to create the task:

```powershell
# Create task JSON directly in skills/task-scheduler/tasks/
# Filename: task-<meeting-slug>.json
```

Task JSON fields:
- `id` — kebab-case slug derived from meeting subject (e.g., `project-alpha-design-review`)
- `name` — human-readable name (e.g., "Project Alpha Design Review Summary")
- `schedule_type` — `cron`
- `schedule_value` — 5-field cron (e.g., `30 11 * * 3`)
- `schedule_friendly` — readable description (e.g., "Weekly on Wednesday at 11:30 AM PT (30 min after meeting)")
- `status` — `active`
- `next_run` — first upcoming occurrence in UTC ISO 8601
- `timeout_minutes` — `30`
- `working_directory` — project root directory

#### 6. Confirm to User

Report:
- Task ID and name
- Schedule (day, time, frequency)
- What it will do: summarize → save to KB → post to channel
- Next scheduled run
- How to pause: `task-manager.ps1 pause -Id "<id>"`

### Example

```
✅ Automatic summarization configured:

  Task:     project-alpha-design-review
  Meeting:  Project Alpha Design Review - Weekly
  Schedule: Every Wednesday at 11:30 AM PT (30 min after meeting)
  Actions:  Summarize → Save to Workstreams/<program>/<workstream>/ → Post to channel
  Next run: March 11, 2026

  Pause:  task-manager.ps1 pause -Id "project-alpha-design-review"
  Delete: task-manager.ps1 delete -Id "project-alpha-design-review"
```

## Troubleshooting

### Common Failures and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `AADSTS9010010` from MCP tools | Transient OAuth token refresh failure | Wait 30 seconds and retry once |
| `get_transcript.py` crashes with "Browser window not found" | CDP connection failed or Edge subprocess crashed | Check port 9224 is free: `Get-NetTCPConnection -LocalPort 9224` (Windows) or `lsof -i :9224` (macOS); kill stale Edge processes on that port |
| `get_transcript.py` fails with CDP timeout | Port 9224 already in use or Edge didn't start | Kill stale Edge processes; script falls back to `launch_persistent_context` (requires Edge closed) |
| `fetch_transcript_direct_api` navigates to wrong URL | Parameter order mismatch — passed `drive_id` as `site_url` | Always use keyword args: `fetch_transcript_direct_api(site_url=..., drive_id=..., item_id=...)` |
| `findFileOrFolder` returns wrong week's recording | Search too generic for recurring meetings | Include date in query: `"<subject> <YYYYMMDD> Meeting Recording"` |
| markitdown fails with "BadZipFile" or "OLE2" on .pptx/.docx | File is DRM/IRM-protected (OLE2 wrapper) | Strip DRM first: `skills/office_common/drm_handler.ps1 -Action strip`; if COM unavailable, skip and rely on transcript |
| Teams channel post shows raw HTML tags | Used `contentType: text` instead of `html` | Use `contentType: "html"` with Graph MCP |
| Teams Playwright session timeout | CDP port conflict or stale Edge process | Teams uses port 9223, meeting-summary uses 9224 — check for zombie Edge processes on those ports |
| "No transcripts found" from `get_transcript.py` | Meeting was not transcribed, or transcript still processing | Wait 30 min after meeting ends; fall back to WorkIQ (Method B) or manual .docx (Method C) |
| Recording found but size is very small (less than 1 MB) | Short meeting or late-start recording | Proceed anyway — small recordings can still have full transcripts |
| `drive_id` is `None` in Args output (macOS) | Used double quotes in bash — `!` in drive IDs gets eaten by history expansion | Use single quotes: `'b!N6uU...'` |
| `python: command not found` (macOS) | macOS doesn't have `python` on PATH | Use `python3` instead |
| "Response is not valid VTT" | API returned an error page instead of VTT | Delete browser profile (`rm -rf ~/.teams-agent/browser-profile/`) and retry |
| 401 on VTT download persists after retries | Auth cookies fully expired | Delete `~/.teams-agent/browser-profile/` — first run after deletion will require interactive login |
| `findFileOrFolder` returns no results for a recording | Recording is in another user's OneDrive (not the organizer's) | Use `SearchTeamsMessages` with `"<subject> Recording"` to find the recording URL from the meeting chat |

### Playwright CDP Architecture

All Playwright-based skills now use **CDP (Chrome DevTools Protocol)** instead of `launch_persistent_context`. This avoids Edge profile lock conflicts:

- A separate Edge process is launched via `subprocess.Popen` with `--remote-debugging-port` and `--user-data-dir=~/.teams-agent/browser-profile/`
- Playwright connects via `chromium.connect_over_cdp("http://127.0.0.1:<port>")`
- Each skill uses a unique port: Teams (9223), meeting-summary (9224), Confluence (9225)
- The standalone profile caches M365 auth cookies — first run may need interactive login
- **Edge can stay open for normal use** — CDP launches a separate process with a different profile
