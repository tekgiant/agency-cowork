# Agency Cowork Memory

## Active Programs
- Weekly memory maintenance and QMD index hygiene remain active as of 2026-07-28.
- The most recent completed maintenance activity was the 2026-07-17 daily maintenance (compacted the 2026-07-09 log and refreshed the QMD text index); no new milestones or program changes have been identified since.
- No new permanent milestones were reached or added during this review cycle.

## Key Contacts
- No new contacts or role changes were documented in this week's daily logs (2026-07-14 through 2026-07-17).
- The named-stakeholder contact roster in MEMORY.md remains empty. Team/reviewer identities are maintained separately via the ADO profile refresh workflow (memory/Knowledgebase/ado-profile-data.json).

## Tooling and Integrations
- Default embedding provider remains sentence_transformer with BAAI/bge-small-en-v1.5 (384 dims); the QMD index currently covers 39 documents (41 chunks).
- Azure OpenAI refresh remains available as an override path (skills/qmd-memory/scripts/azure-embed.py) and was last exercised on 2026-07-14 (41/41 chunks regenerated); scheduled maintenance keeps it disabled (provider != azure_openai), falling back to bge-small-en-v1.5.
- ADO profile refresh (scripts/ado_profile_refresh.py) periodically rebuilds the team/reviewer roster from Azure DevOps (MicrosoftIT/OneITVSO, 180-day window) into memory/Knowledgebase/ado-profile-data.json as part of recurring maintenance.
- The current workflow uses the local QMD index refresh process and repository-based memory maintenance.

## Notes
- Stable facts belong here; temporary or episodic details belong in memory/DailyLogs/.
- The latest MEMORY.md review was completed on 2026-07-28; the most recent daily maintenance logs were 2026-07-16 and 2026-07-17 (no daily logs exist between 2026-07-18 and 2026-07-28).
