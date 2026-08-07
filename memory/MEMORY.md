# Agency Cowork Memory

## Active Programs
- Weekly memory maintenance and QMD index hygiene remain active as of 2026-08-07.
- Daily maintenance on 2026-08-07 found no remaining logs dated before the 2026-07-31 cutoff; the archive required no additional entries, and no new milestones or program changes were identified.
- No new permanent milestones were added during this review cycle.

## Key Contacts
- No new contacts or role changes were identified during the 2026-08-07 maintenance review.
- The named-stakeholder contact roster in MEMORY.md remains empty. Team/reviewer identities are maintained separately via the ADO profile refresh workflow (memory/Knowledgebase/ado-profile-data.json).

## Tooling and Integrations
- Default embedding provider remains sentence_transformer with BAAI/bge-small-en-v1.5 (384 dims); QMD text indexing and the configured local embedding cache are refreshed during maintenance.
- Azure OpenAI embedding refresh remains disabled (provider != azure_openai); memory-flush.ps1 refreshes the text index, and the configured SentenceTransformer embeddings are refreshed separately with azure-embed.py.
- ADO profile refresh (scripts/ado_profile_refresh.py) periodically rebuilds the team/reviewer roster from Azure DevOps (MicrosoftIT/OneITVSO, 180-day window) into memory/Knowledgebase/ado-profile-data.json as part of recurring maintenance.
- The current workflow uses the local QMD index refresh process and repository-based memory maintenance.

## Notes
- Stable facts belong here; temporary or episodic details belong in memory/DailyLogs/.
- The latest MEMORY.md review was completed on 2026-08-07; the QMD text index was refreshed during the same maintenance cycle.

