---
name: lab-notebook
description: |
  Use this skill when the user asks to "log a measurement", "record test results",
  "create a lab entry", "document characterization data", "track bench measurements",
  "start a test session", "what did we measure for X", or wants to maintain a structured
  engineering lab notebook with timestamped entries, test configurations, and searchable
  measurement data.
---

# Lab Notebook

Structured, searchable engineering lab notebook for hardware teams. Replaces scattered OneNote pages, Excel files, and email threads with a consistent, version-controlled, QMD-indexed record of lab measurements, test results, and characterization data.

## Overview

Hardware engineers take measurements constantly — bench characterization, silicon bring-up, power rail measurements, signal integrity scans, thermal profiling. This data often lives in:
- Random Excel files on someone's desktop
- OneNote notebooks nobody else can find
- Email attachments with no search
- Sticky notes on the bench

This skill provides a structured, searchable alternative that integrates with the agent's memory system.

## Storage

Lab entries are stored as dated markdown files in a dedicated Knowledgebase subfolder:

```
memory/Knowledgebase/Lab/
├── sessions/
│   ├── 2026-03-12-ddr-characterization.md
│   ├── 2026-03-11-power-rail-sweep.md
│   └── 2026-03-10-serdes-eye-diagram.md
├── equipment/
│   └── bench-inventory.md
└── templates/
    ├── measurement-session.md
    └── silicon-bring-up.md
```

## Workflow

### Start a Lab Session

When the user says "start a lab session" or "log measurements":

1. **Create a session file** with the naming convention:
   ```
   memory/Knowledgebase/Lab/sessions/YYYY-MM-DD-<short-description>.md
   ```

2. **Apply the session template:**
   ```markdown
   ---
   type: lab-session
   date: YYYY-MM-DD
   engineer: <name>
   dut: <device under test>
   station: <bench/station ID>
   tags: [<relevant tags>]
   ---

   # Lab Session: <Title>

   ## Objective
   <What are we trying to measure/verify?>

   ## Setup
   - **DUT:** <Device under test, serial number, silicon rev>
   - **Station:** <Bench ID, equipment list>
   - **Firmware:** <Version, build>
   - **Conditions:** <Temperature, voltage, clock frequency>

   ## Measurements

   | # | Timestamp | Parameter | Value | Unit | Pass/Fail | Notes |
   |---|-----------|-----------|-------|------|-----------|-------|
   | 1 | HH:MM | | | | | |

   ## Observations
   <Anomalies, unexpected behavior, visual observations>

   ## Conclusions
   <Summary of findings, next steps>

   ## Action Items
   - [ ] <follow-up action>
   ```

3. **Index the session** — QMD auto-indexes on next update cycle

### Log a Measurement

When the user says "log: <parameter> = <value>":

1. Find the active lab session for today (most recent session file with today's date)
2. Append a new row to the Measurements table with auto-generated timestamp
3. Confirm the entry

### Query Lab Data

Search across all lab sessions using QMD:

| User asks | Skill does |
|-----------|-----------|
| "What was the VDD measurement on the dev board?" | Search sessions → find power rail entries → return with dates |
| "Show all thermal measurements from last week" | Date-filtered search → aggregate results → render table |
| "When did we first see the SerDes eye closure issue?" | Search for SerDes + eye → return earliest session |
| "Compare power readings across silicon revisions" | Search sessions by DUT tag → extract power data → compare |

### Render as HTML

When measurement data spans 4+ rows, automatically generate an HTML table via visual-explainer. For time-series data, consider Chart.js line/scatter plots.

## Integration Points

- **Teams**: Post session summaries to lab channels after each session
- **ADO**: Link lab findings to work items (bugs, tasks) when issues are discovered
- **Calendar**: Reference the meeting/event that prompted the lab session
- **SharePoint**: Upload raw data files (scope captures, CSV exports) alongside the markdown summary

## Rules

- **ALWAYS** use ISO timestamps (YYYY-MM-DD HH:MM) for consistency
- **ALWAYS** include the DUT identifier and firmware version — measurements without context are useless
- **ALWAYS** note environmental conditions (temperature, voltage) that affect measurements
- **NEVER** overwrite previous session files — append or create new sessions
- **NEVER** store raw binary data (scope captures, images) in markdown — reference the file path/SharePoint link instead
- Tag sessions with component names, silicon revisions, and test types for better search recall
- When the user says "close the session", add Conclusions and Action Items sections if missing
