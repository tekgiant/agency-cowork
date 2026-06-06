# Workstreams Skill

Orchestrates program workstream management: meeting summaries, action item tracking, and Landing Zone cross-referencing across Teams channels and the Knowledgebase.

## Features

- **Registry-driven** workstream-to-channel mapping (`registry.json`)
- **Meeting summary** workflow: summarize → save to KB → extract actions → detect LZ changes → post to channel
- **Action item tracker** (`ws_tracker.py`): add, list, update, close, summary with DRI/due dates
- **LZ cross-reference**: detect requirement changes during meeting minutes, propose LZ updates
- **Per-workstream KB folders**: organized by program with meeting notes and action items

## Quick Start

```bash
cd skills/workstreams

# List open action items across all workstreams
python -m scripts.ws_tracker list

# Add an action item
python -m scripts.ws_tracker add --workstream my-program/my-workstream --description "Finalize spec" --dri "Jane Doe" --due 2026-03-15

# Summary for exec reporting
python -m scripts.ws_tracker summary
```

See `skills/workstreams/SKILL.md` for the full workflow and decision table.
