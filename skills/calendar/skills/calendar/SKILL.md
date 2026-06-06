---
name: calendar
description: >
  Use this skill when the user asks to "schedule a meeting", "create an event", "book a meeting",
  "find a time", "check availability", "accept a meeting", "decline an invite", "cancel a meeting",
  "update a meeting", "reschedule", "what's on my calendar", "show my meetings", "forward a meeting",
  "find meeting rooms", or any Outlook calendar operation. Triggers include "calendar", "meeting",
  "schedule", "event", "invite", "availability", "free/busy", "meeting room".
---

# Calendar Skill

Manage Outlook calendar events — create, update, accept, decline, cancel, find meeting times, and check availability — powered by the `microsoft-outlook-calendar` MCP server.

## Overview

This skill uses the **microsoft-outlook-calendar MCP** (Microsoft Graph API) to perform calendar operations. All timestamps use ISO 8601 format. Online meetings (Teams) are created by default.

## MCP Capabilities Reference

### Event CRUD

| Tool | Description | Required Parameters | Key Optional Parameters |
|------|-------------|---------------------|------------------------|
| `ListEvents` | List events from user's calendar with optional filters. Returns master event for recurring meetings. | — | `startDateTime`, `endDateTime`, `meetingTitle`, `attendeeEmails`, `top`, `orderby`, `select` |
| `ListCalendarView` | List events with recurring instances expanded in a time range. **Use this for finding specific meeting instances.** | `userIdentifier` | `startDateTime`, `endDateTime`, `subject`, `top`, `orderby`, `select` |
| `CreateEvent` | Create a new calendar event. All events include a Teams meeting link by default. Default duration is 30 minutes. | `subject`, `attendeeEmails`, `startDateTime`, `endDateTime` | `bodyContent`, `location`, `recurrence`, `isOnlineMeeting`, `importance`, `showAs`, `sensitivity`, `timeZone` |
| `UpdateEvent` | Update an existing event — time, subject, body, location, attendees. | `eventId` | `subject`, `startDateTime`, `endDateTime`, `body`, `location`, `attendeesToAdd`, `attendeesToRemove`, `recurrence`, `importance`, `sensitivity`, `showAs` |
| `DeleteEventById` | Delete a calendar event by ID. | `eventId` | — |

### Invitations & Responses

| Tool | Description | Required Parameters | Optional Parameters |
|------|-------------|---------------------|---------------------|
| `AcceptEvent` | Accept a meeting invitation. | `eventId` | `comment`, `sendResponse` |
| `TentativelyAcceptEvent` | Tentatively accept a meeting invitation. | `eventId` | `comment`, `sendResponse` |
| `DeclineEvent` | Decline a meeting invitation. | `eventId` | `comment`, `sendResponse` |
| `CancelEvent` | Cancel a meeting (organizer only). Sends cancellation to all attendees. | `eventId` | `comment` |
| `ForwardEvent` | Forward an event to other recipients. | `eventId`, `recipientEmails` | `comment` |

### Availability & Scheduling

| Tool | Description | Required Parameters | Key Optional Parameters |
|------|-------------|---------------------|------------------------|
| `FindMeetingTimes` | Suggest times that work for all attendees based on availability. | — | `attendeeEmails`, `startDateTime`, `endDateTime`, `meetingDuration`, `maxCandidates`, `isOrganizerOptional`, `returnSuggestionReasons`, `minimumAttendeePercentage`, `timeZone` |
| `GetUserDateAndTimeZoneSettings` | Get user's timezone, date format, working hours, and language preferences. | — | `userIdentifier` |
| `GetRooms` | List all meeting rooms in the tenant. | — | — |

## Key Features

### Online Meetings

- All events include a **Teams meeting link** by default (`isOnlineMeeting: true`)
- Supports Teams for Business, Skype for Business, and Skype for Consumer
- Set `isOnlineMeeting: false` to create an in-person-only event

### Recurring Events

Recurring events use a `recurrence` object with `pattern` and `range`:

**Pattern types:** `daily`, `weekly`, `absoluteMonthly`, `relativeMonthly`, `absoluteYearly`, `relativeYearly`

**Range types:** `endDate` (stop on a date), `numbered` (stop after N occurrences), `noEnd` (no end)

Example — weekly Monday/Wednesday meeting for 10 occurrences:
```json
{
  "recurrence": {
    "pattern": {
      "type": "weekly",
      "interval": 1,
      "daysOfWeek": ["monday", "wednesday"]
    },
    "range": {
      "type": "numbered",
      "startDate": "2026-03-09",
      "numberOfOccurrences": 10
    }
  }
}
```

### Attendee Management

- **Recipients can be names or email addresses** — names are auto-resolved via Microsoft Graph
- Use `attendeesToAdd` and `attendeesToRemove` on `UpdateEvent` to modify attendee lists
- Supports required, optional, and resource (room) attendees

### Free/Busy & Scheduling

- `FindMeetingTimes` analyzes availability of all attendees and suggests optimal slots
- `meetingDuration` uses ISO 8601 duration format: `PT30M` (30 min), `PT1H` (1 hour), `PT1H30M` (90 min)
- Set `isOrganizerOptional: true` to find times when organizer doesn't need to attend
- Use `minimumAttendeePercentage` to accept times when not all attendees are free (e.g., 75 = at least 75% available)

## Workflow

### Scheduling a New Meeting

1. **Gather details** from the user:
   - **Subject** (required)
   - **Date and time** (required) — resolve to ISO 8601 format
   - **Duration** (default: 30 minutes)
   - **Attendees** (required) — names or email addresses
   - **Location** (optional)
   - **Description/body** (optional)
   - **Recurrence** (optional) — ask if it should repeat

2. **Resolve the timezone**:
   - If the user doesn't specify a timezone, call `GetUserDateAndTimeZoneSettings` to get their default
   - Use that timezone for `startDateTime` and `endDateTime`

3. **Check for conflicts** (optional but recommended):
   - Call `ListCalendarView` for the proposed time range to see existing events
   - If conflicts exist, inform the user and offer to find alternative times via `FindMeetingTimes`

4. **Confirm before creating**:
   ```
   Subject: <subject>
   When: <date> <start time> - <end time> (<timezone>)
   Attendees: <list>
   Location: <location or "Teams meeting">
   Recurrence: <pattern or "None">
   ```

5. **Create the event** using `CreateEvent`

6. **Report results** — confirm the meeting was created with all details

### Finding a Meeting Time

1. Collect attendees and preferred time range from the user
2. Call `FindMeetingTimes` with:
   - `attendeeEmails` — list of attendee emails/names
   - `meetingDuration` — e.g., `PT1H`
   - `startDateTime` / `endDateTime` — the window to search
3. **If suggestions are returned**, present them to the user
4. **If no suggestions** (`emptySuggestionsReason` is `OrganizerUnavailable` or `Unknown`):
   - Retry with `isOrganizerOptional: true` if not already set
   - If still empty, inform the user that automated scheduling couldn't find a slot
   - Suggest asking the attendee to propose times (can be included in an outreach email)
   - Optionally scan your own calendar with `ListCalendarView` using `select: "subject,start,end,showAs"` and narrow time windows to manually identify gaps
5. Once the user picks a slot, proceed to create the event

### Viewing Calendar

1. Determine the time range (default: today and next 7 days)
2. Call `ListCalendarView` with `userIdentifier: "me"`, `startDateTime`, `endDateTime`
3. Present events in a clean table or list format:
   ```
   | Time | Subject | Attendees | Location |
   |------|---------|-----------|----------|
   ```

### Responding to Invitations

1. Find the event — use `ListCalendarView` with `subject` filter, or `ListEvents` to locate it
2. Present the event details to the user
3. Based on user's choice:
   - **Accept**: Call `AcceptEvent` with optional comment
   - **Tentative**: Call `TentativelyAcceptEvent` with optional comment
   - **Decline**: Call `DeclineEvent` with optional comment

### Updating/Rescheduling a Meeting

1. **Find the event** — use `ListCalendarView` with `subject` filter to get the `eventId`
   - For recurring meetings, this returns individual instances — confirm which instance to update
2. **Confirm changes** with the user
3. Call `UpdateEvent` with the `eventId` and changed fields:
   - `startDateTime` / `endDateTime` for rescheduling
   - `attendeesToAdd` / `attendeesToRemove` for attendee changes
   - `subject`, `body`, `location` for metadata changes

### Canceling a Meeting

1. Find the event using `ListCalendarView`
2. Confirm with the user — cancellation sends notifications to all attendees
3. Call `CancelEvent` with the `eventId` and optional comment

### Forwarding a Meeting

1. Find the event using `ListCalendarView`
2. Collect recipient emails/names from the user
3. Call `ForwardEvent` with `eventId`, `recipientEmails`, and optional comment

### Finding Meeting Rooms

1. Call `GetRooms` to list all available rooms in the tenant
2. Present the room list with names and email addresses
3. Use the room's email address as the `location` or as an attendee with resource type when creating events

## Time & Timezone Handling

- **Always use ISO 8601 format**: `2026-03-09T09:00:00`
- **Always specify timezone** via the `timeZone` parameter (e.g., `Pacific Standard Time`)
- If the user says "tomorrow at 2pm", resolve it relative to their timezone
- Call `GetUserDateAndTimeZoneSettings` to determine the user's default timezone if not known
- **Be consistent** — use the same timezone for both start and end times

## Known Issues & Limitations

| Issue | Details | Workaround |
|-------|---------|------------|
| **`FindMeetingTimes` returns empty / `OrganizerUnavailable`** | When the organizer's calendar is heavily booked, `FindMeetingTimes` may return `emptySuggestionsReason: "OrganizerUnavailable"` with zero suggestions — even for time ranges that appear to have gaps. | Set `isOrganizerOptional: true` to search only attendee availability. If that still returns empty (`emptySuggestionsReason: "Unknown"`), fall back to manual scheduling: ask the other person to propose times, or use `ListCalendarView` with narrow date ranges and `select` to scan for gaps. |
| **`FindMeetingTimes` empty with `isOrganizerOptional`** | Even with `isOrganizerOptional: true`, the API may return zero suggestions with `emptySuggestionsReason: "Unknown"`. This can happen when the attendee's free/busy data is unavailable or when both calendars are too packed. | Ask the attendee directly (via email or Teams) to propose times that work for them. Include this as part of the outreach message. |
| **`ListCalendarView` cross-user access failure** | Calling `ListCalendarView` with another user's email as `userIdentifier` may fail with `"The specified object was not found in the store"` if you lack permissions to view their calendar. | You can only reliably view your own calendar. For other users, use `FindMeetingTimes` (which reads free/busy data, not full calendar details) or ask them to share availability. |
| **Large calendar output** | `ListCalendarView` for busy users can return very large output that exceeds context limits, even for a single day. | Always use `select` to limit returned fields (e.g., `select: "subject,start,end,showAs"`). Use narrow time windows (1–2 days). If output is still too large, scan day-by-day. |
| **Recurring event instances** | `ListEvents` returns only the master recurring event, not individual instances. | Always use `ListCalendarView` when looking for a specific instance of a recurring meeting — it expands recurrences into individual events within the time range. |
| **`showAs` returns integers, not strings** | The MCP Calendar C# SDK serializes the `FreeBusyStatus` enum as integer ordinals instead of the string names used by the Graph API. Mapping: `0`=free, `1`=tentative, `2`=busy, `3`=oof, `4`=workingElsewhere, `5`=unknown. Regular busy meetings (e.g., standups, 1:1s) may return `showAs: 3` and be misidentified as OOF. See [#238](https://github.com/ahsi-microsoft/agency-cowork/issues/238). | **Never rely on `showAs` alone for OOF detection.** Normalize integers to strings using the mapping above. For OOF detection, use subject-based heuristics: `isAllDay == true` AND subject contains "Out of Office", "OOF", or "PTO". Treat `showAs: 2` and `showAs: 3` as equivalent to "busy" for non-all-day meetings. |

## `showAs` Integer Normalization

The MCP Calendar server returns `showAs` as integers. Always normalize before interpreting:

```
0 → "free"        3 → "oof"
1 → "tentative"   4 → "workingElsewhere"
2 → "busy"        5 → "unknown"
```

**OOF detection** — do NOT trust `showAs == 3` alone. Use this pattern:
- `isAllDay == true` AND subject matches `/out of office|ooo|oof|pto|vacation/i` → **OOF**
- `showAs == 3` AND `isAllDay == false` → treat as **busy** (not OOF)
- OR check if the user has Automatic Replies enabled (separate API)

## Rules

- **ALWAYS** confirm with the user before creating, updating, canceling, or deleting events — never modify the calendar without explicit approval
- **ALWAYS** use `ListCalendarView` (not `ListEvents`) when looking for a specific meeting instance of a recurring event — `ListEvents` returns only the master series
- **ALWAYS** include a Teams meeting link by default — set `isOnlineMeeting: false` only if the user explicitly requests no online meeting
- **ALWAYS** resolve timezone before creating events — use `GetUserDateAndTimeZoneSettings` if the user doesn't specify
- **ALWAYS** present event details clearly before any modification
- **NEVER** fabricate or guess event IDs — always resolve from `ListCalendarView` or `ListEvents` responses
- **NEVER** create, cancel, or delete events without explicit user confirmation
- Default meeting duration is 30 minutes if the user doesn't specify
- When the user says "schedule" or "book", create an event; when they say "find a time" or "when are we free", use `FindMeetingTimes`
- For recurring events, always confirm the recurrence pattern and end condition with the user
- Recipient names are auto-resolved by the MCP — use WorkIQ as a fallback if resolution fails
