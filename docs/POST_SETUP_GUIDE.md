# Post-Setup & Post-Upgrade Guide

> **This file is referenced by the automated post-setup and post-upgrade prompts.**
> Read it fully before taking any setup/configuration actions.

## Guiding Principles

1. **Local-first, zero cloud.** All embedding, indexing, and memory operations run entirely on-device. Never suggest, configure, or attempt cloud-based embedding services (Azure OpenAI, Hugging Face Inference API, OpenAI API, Cohere, etc.) unless the user explicitly requests it.
2. **Follow the scripts.** Use the existing setup scripts and Python pipelines — do not improvise alternatives or install additional services.
3. **Don't ask unnecessary questions.** The defaults in `agentconfig.json` are correct. Don't present the user with provider choices, API key prompts, or subscription options for embeddings.

---

## Embedding Setup (QMD Memory)

The embedding provider is configured in `agentconfig.json` → `memory.embedding.provider`. The default is `"sentence_transformer"` which uses `BAAI/bge-small-en-v1.5` — a local model that runs on CPU via the `sentence-transformers` Python package. **This is the correct and only recommended configuration.**

### Setup Steps

```powershell
# 1. Install the Python dependency (if not already installed)
pip install sentence-transformers

# 2. Update the QMD text index
qmd update

# 3. Generate embeddings using the local provider
python skills/qmd-memory/scripts/azure-embed.py
```

> **Note:** Despite the filename `azure-embed.py`, this script reads the provider setting from `agentconfig.json` and uses whatever is configured — by default, that's `sentence_transformer` (fully local, no Azure involved).

### What NOT to do

- ❌ Do NOT suggest Azure OpenAI embeddings or attempt to create Azure resources
- ❌ Do NOT suggest Hugging Face Inference API or any remote embedding API
- ❌ Do NOT change the `provider` field in `agentconfig.json` without explicit user request
- ❌ Do NOT prompt the user to choose between embedding providers
- ❌ Do NOT attempt to set up API keys, endpoints, or subscriptions for embeddings
- ❌ Do NOT use `qmd embed` directly (it tries to build llama.cpp with Vulkan/CMake)

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: sentence_transformers` | Run `pip install sentence-transformers` |
| Model download slow on first run | Normal — `BAAI/bge-small-en-v1.5` is ~130MB, cached after first download |
| `azure-embed.py --test` fails | Check that `pip install sentence-transformers` succeeded; verify `agentconfig.json` has `"provider": "sentence_transformer"` |
| Embeddings stale after knowledgebase changes | Run `qmd update` then `python skills/qmd-memory/scripts/azure-embed.py` |

---

## Post-Upgrade Checklist

After an upgrade, follow these steps **in order**:

### 1. Context File Sync
> **Note:** This step is performed by the AI coworker (Copilot agent), not the upgrade script. The upgrade script detects template changes and saves a diff to `.update-backup/template-changes.md` — this checklist tells the agent how to merge them.

Upgrade may have added new framework content (security rules, skills, warnings) to `.example` files. Merge these into the user's working files while preserving their customizations:

1. Read `.context-merge.json` for section classifications (`framework` vs `user`)
2. For each file (`CLAUDE.md`, `AGENTS.md`):
   - Read the user's current file and the corresponding `.example` file
   - For sections classified as `framework`: compare content — if the `.example` version is different or the section is missing from the user's file, update/add it from `.example`
   - For sections classified as `user`: **keep the user's version unchanged** (these contain personalized content)
   - For sections in the user's file not listed in the manifest (e.g., "Working Preferences"): **preserve them** — these are user-added sections
   - Maintain section ordering: framework sections in `.example` order, user-only sections appended at end
3. Show the user a summary of what was added/updated (e.g., "Added new 'Critical Warnings' section, updated 'Skills' table with 3 new skills")
4. If `.context-merge.json` is missing (older install), skip this step — the user can run `deep-personalization` to rebuild

### 2. Restore Personalization
- Read the backup directory (`.update-backup-*/ `) for preserved files
- Restore `memory/MEMORY.md` from backup if it was overwritten
- Restore scheduled tasks from backup `scripts/tasks/` directory
- Restore `skills/*/defaults/` files (voice profiles, triage config, etc.)
- Note: `CLAUDE.md` and `AGENTS.md` are handled by Context File Sync (step 1) — do NOT wholesale restore them from backup

### 3. Check OneDrive Migration
- Check if `memory/` is stored inside OneDrive (via junction or direct path)
- Check if the Agency Cowork Outputs folder is inside OneDrive
- If neither is in OneDrive, ask the user if they'd like to migrate (use `scripts/update.ps1` `Invoke-OneDriveMigration`)

### 4. QMD Memory & Embeddings
Follow the [Embedding Setup](#embedding-setup-qmd-memory) section above. Key commands:
```powershell
pip install sentence-transformers   # ensure dependency
qmd update                          # rebuild text index
python skills/qmd-memory/scripts/azure-embed.py  # generate local embeddings
```

### 5. Teams Monitor Dependencies
Ensure the Teams monitor Python dependencies are installed:
```powershell
pip install -r skills/teams/requirements.txt   # aiohttp, websockets, playwright, etc.
```
If the monitor fails to start with `ModuleNotFoundError: No module named 'aiohttp'`, this step was missed.

### 6. Fix Recent Tasks Missing Session IDs

Newer versions of Agency CLI (2026.4.5.2+) create "stub" sessions — a minimal `events.jsonl` file without `workspace.yaml`. Older versions of the app couldn't detect these stubs, so tasks started on those versions will have `sessionId: null` in the task index and cannot be resumed.

To backfill session IDs for recent tasks:

1. Open the task index file at `~/.agency-cowork/store/index.json`
2. For each task with `"sessionId": null`, check `~/.copilot/session-state/` for a session directory that:
   - Was created within a few seconds of the task's `createdAt` timestamp
   - Has an `events.jsonl` file (check the first line — it should contain the task's working directory in `data.workDir`)
   - Does **not** have a `checkpoints/` subfolder (those are meta-sessions, not user tasks)
3. If a match is found, update the task entry: `"sessionId": "<uuid>"`
4. Alternatively, start any affected tasks fresh — the current version now auto-detects stub sessions within ~5 seconds of spawn and persists the session ID immediately

> **Note:** This step is only needed if you were running Agency CLI 2026.4.5.2+ while using an older version of Agency Cowork. New installs and upgrades to the current version detect stub sessions automatically.

### 7. Health Check
- Verify skills are loaded and MCP servers connect
- Confirm working directory is accessible
- Check that `qmd update` and embedding generation succeeded
- **Verify task scheduler is running** (if enabled in Settings):
  - Check `skills/task-scheduler/scheduler.pid` — if PID is alive, scheduler is running
  - Report count of active/paused/total scheduled tasks
  - If any tasks show `error_paused` status, review the task log (`task-<name>.log`) and reset via the task-scheduler skill or by editing the task JSON to set `"status": "active"` and `"error_count": 0`
  - If scheduler should be running but isn't, start it via the task-scheduler skill

---

## Fresh Install Checklist

### 1. Health Check
- Verify skills are loaded and MCP servers connect
- Confirm working directory is accessible
- Report status with checkmarks (✓) for working items and warnings for issues
- **Verify task scheduler is running** if enabled during setup

### 2. QMD Memory Setup
Follow the [Embedding Setup](#embedding-setup-qmd-memory) section above.

### 3. Introduction
- Introduce yourself with your name and capabilities
- Give 3 specific examples of tasks the user can try
- Keep it short, friendly, and visual

---

## Available Embedding Providers (Reference Only)

These exist in the codebase but should only be configured if the user explicitly requests them:

| Provider | Config key | When to use |
|----------|-----------|-------------|
| **SentenceTransformer** (default ✓) | `sentence_transformer` | Always — local, free, no API keys |
| Local GGUF | `local` | Only if user wants lower memory footprint and has C++ toolchain |
| Azure OpenAI | `azure_openai` | Only if user explicitly provides endpoint + API key |

**Policy:** Do NOT use personal Azure subscriptions to set up embedding services for work-related content. The SentenceTransformer provider is the recommended default.
