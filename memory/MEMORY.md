# Agency Cowork Memory

## Active Programs
- Memory maintenance and QMD index hygiene remain the only active program facts documented in this week's logs (current through 2026-06-04).
- Milestones reached this week: daily maintenance completed, QMD text re-index refreshed, and local SentenceTransformer embeddings were verified/updated.
- The 2026-06-04 maintenance run confirmed the QMD text index is healthy and Azure embeddings remain disabled in this environment.

## Key Contacts
- No new contacts were documented in this week's daily logs.
- Current contact roster remains empty until a named person is added to memory.

## Tooling and Integrations
- QMD memory index with collections for memory-root, knowledgebase, weekly-reports, and skills-docs.
- Local SentenceTransformer/BGE embeddings are the active embedding path; Azure OpenAI embeddings are not configured here.
- Daily maintenance flow uses memory-flush.ps1 and QMD re-index/embedding refresh for upkeep.

## Notes
- This file is intentionally concise and limited to stable, long-lived facts.
- Temporary or episodic details belong in the daily logs under memory/DailyLogs/.
