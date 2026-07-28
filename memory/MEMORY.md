# Agency Cowork Memory

## Active Programs
- Weekly memory maintenance and QMD index hygiene remain active as of 2026-07-28.
- The most recent maintenance activity (2026-07-28 daily maintenance: compacted the 2026-07-14 through 2026-07-17 daily logs and refreshed the QMD text index) completed successfully; no new milestones or program changes were identified.
- No new permanent milestones were added during this review cycle.

## Key Contacts
- No new contacts were documented this week.
- The contact roster remains empty until a named stakeholder or teammate is added to memory.

## Tooling and Integrations
- Default embedding provider remains sentence_transformer with BAAI/bge-small-en-v1.5 (384 dims); the QMD index currently covers 39 documents (39 chunks).
- Azure OpenAI refresh remains available as an override path (skills/qmd-memory/scripts/azure-embed.py) but stays disabled in the current environment (provider != azure_openai), falling back to bge-small-en-v1.5.
- The current workflow uses the local QMD index refresh process and repository-based memory maintenance.

## Notes
- Stable facts belong here; temporary or episodic details belong in memory/DailyLogs/.
- The latest MEMORY.md review was completed on 2026-07-28; the most recent daily maintenance logs were 2026-07-17 (daily maintenance: compacted the 2026-07-09 log + QMD re-index) and 2026-07-28 (daily maintenance: compacted the 2026-07-14 through 2026-07-17 logs + QMD re-index).
