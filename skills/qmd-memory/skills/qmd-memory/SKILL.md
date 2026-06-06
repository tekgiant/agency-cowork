---
name: qmd-memory
description: |
  Use this skill for ALL access to the agent's memory system — both user-facing requests and internal agent operations. Triggers include: the agent needing to read, search, or write ANY file under the memory/ directory (daily logs, knowledgebase, MEMORY.md, weekly reports); user asks to "search my memory", "find past decisions", "look up knowledgebase content", "what do we know about <topic>", "recall <something>", "search notes for <topic>", "re-index memory", "update memory index"; user asks to "remember this" or "update my profile"; user says "goodbye", "end session", "that's all", "save context", or "flush memory". IMPORTANT: Do NOT grep, glob, or view files in memory/ directly — always go through this skill for search and retrieval. Direct file reads (view tool) are only acceptable when you already have the exact path from a prior skill search result.
---

# QMD Memory Skill

Search and manage the agent's persistent memory using **QMD** (Query Markup Documents) — a local hybrid search engine for markdown files. QMD combines BM25 full-text search and vector semantic search with local embeddings (`bge-small-en-v1.5`, 384 dimensions) via SentenceTransformers. All embedding runs entirely on-device — zero cost, offline-capable, no API keys required.

## Overview

The memory system has two layers:

1. **MEMORY.md** (semantic memory) — Permanent facts about the user, project, and environment. Always loaded at session start. Max ~200 lines.
2. **QMD search** (episodic + knowledge retrieval) — Indexed search across daily logs, knowledgebase, weekly reports, and skill docs.

### Memory Repository

The `memory/` directory is stored in a **separate Git repository** configured via `agentconfig.json` (`memory.repo`). Run `scripts/sync-memory.ps1` to clone or pull the latest memory data. All markdown files in `memory/` are indexed by QMD for fast search and retrieval.

> **First-time setup:** Configure `memory.repo` in `agentconfig.json` and run `powershell -ExecutionPolicy Bypass -File scripts/sync-memory.ps1`. See `installation.md` §2 for details.

### Embedding Strategy

The default embedding provider is **SentenceTransformer** using `BAAI/bge-small-en-v1.5` (384 dimensions). This runs entirely on CPU via `sentence-transformers` — pip-installable, no C++ compiler needed, fast enough for all QMD operations without any cloud API dependency. A **local GGUF** backend (`llama-cpp-python`) is also available for environments where a smaller binary footprint is preferred.

| Component | Use | Notes |
|-----------|-----|-------|
| **Text indexing** | `qmd update` | Fast, local BM25 index |
| **Embedding generation** | `python skills/qmd-memory/scripts/azure-embed.py` | Uses SentenceTransformer by default; `--provider local` for GGUF, `--provider azure_openai` for cloud |
| **Keyword search** | `qmd-query` MCP (lex sub-query) or `qmd search` CLI | BM25, instant |
| **Semantic/conceptual search** | `qmd-query` MCP (lex + vec sub-queries) or `hybrid-search.py` fallback | Combines keyword + semantic |

> **⚠️ Policy: Do NOT use personal Azure subscriptions** to set up embedding services (or any cloud AI endpoints) for work-related content. The SentenceTransformer provider is the recommended default — it runs entirely on-device with no data leaving the machine.

**Configuration file:** `agentconfig.json` (project root)

```json
{
  "memory": {
    "embedding": {
      "provider": "sentence_transformer",
      "sentence_transformer": {
        "model_name": "BAAI/bge-small-en-v1.5",
        "dimensions": 384
      },
      "local": {
        "model_path": "skills/qmd-memory/models/bge-small-en-v1.5-f16.gguf",
        "model_name": "bge-small-en-v1.5-f16",
        "dimensions": 384
      },
      "azure_openai": {
        "endpoint": "",
        "deployment": "text-embedding-3-large",
        "model": "text-embedding-3-large",
        "api_version": "2024-04-01-preview"
      }
    }
  }
}
```

Three providers are available:

| Provider | Config key | Install | Notes |
|----------|-----------|---------|-------|
| **SentenceTransformer** (default) | `sentence_transformer` | `pip install sentence-transformers` | Pure Python, no C++ compiler, auto-downloads model on first use |
| **Local GGUF** | `local` | `pip install llama-cpp-python` + 64MB model download | Lower memory footprint, requires C++ toolchain on some platforms |
| **Azure OpenAI** | `azure_openai` | `pip install openai python-dotenv` | Corporate endpoints only — do NOT use personal subscriptions |

To switch providers, change `"provider"` in `agentconfig.json` and install the corresponding dependency.

**Dependencies (default):** `pip install sentence-transformers` — the model (`BAAI/bge-small-en-v1.5`) downloads automatically on first use (~130MB, cached by HuggingFace).

## QMD Collections

| Collection | Path | What's Indexed |
|-----------|------|---------------|
| `memory-root` | `memory/*.md` | Daily context logs, MEMORY.md |
| `knowledgebase` | `memory/Knowledgebase/**/*.md` | Program knowledge, specs, exec reviews, PEC minutes, workstream notes |
| `weekly-reports` | `memory/WeeklyReports/**/*.md` | Executive weekly status reports per program |
| `skills-docs` | `skills/**/SKILL.md` | Skill definitions and workflows |

## MCP Tools (Primary Access)

QMD 2.0 exposes these tools via the `qmd` MCP server:

| Tool | Description | Speed | Use When |
|------|-------------|-------|----------|
| `qmd-query` | Unified search — BM25 + vector + reranking via typed sub-queries | Varies | **Primary search tool.** Supports `lex` (keyword), `vec` (semantic), and `hyde` (hypothetical document) sub-queries combined via RRF |
| `qmd-get` | Retrieve full document by path or docid | Fast | Read a specific file after finding it via search |
| `qmd-multi_get` | Retrieve multiple documents by glob/list | Fast | Read several related files at once |
| `qmd-status` | Index health, collection info, model status | Fast | Verify QMD is running and indexed |

> **Note:** In QMD 2.0, the old `search`, `vector_search`, and `deep_search` tools were replaced by a single unified `query` tool. Use typed sub-queries to control which search backends are used.

### MCP Tool Parameters

**`qmd-query`** (unified search):
- `searches` (required) — Array of typed sub-queries. Each has `type` (`lex`, `vec`, or `hyde`) and `query` string. First sub-query gets 2× weight — put your strongest signal first.
- `intent` (optional) — Background context to disambiguate the query (e.g., `"web page load times"` when query is `"performance"`). Steers expansion, reranking, and snippet extraction without searching on its own.
- `collections` (optional) — Array of collection names to restrict search (e.g., `["knowledgebase", "weekly-reports"]`). Omit to search all.
- `limit` (optional) — Max results (default: 10)
- `minScore` (optional) — Minimum relevance score 0–1 (default: 0)
- `candidateLimit` (optional) — Max candidates to rerank (default: 40, lower = faster)

**Sub-query types:**

| Type | Method | Input | When to use |
|------|--------|-------|-------------|
| `lex` | BM25 | Keywords — exact terms, names, code | Known terms, IDs, error strings |
| `vec` | Vector | Natural language question | Conceptual queries, don't know exact vocabulary |
| `hyde` | Vector | Hypothetical answer (50–100 words) | Complex/nuanced topics — most powerful for recall |

**Writing good queries:**

- **lex:** 2–5 terms, no filler words. Exact phrase: `"connection pool"` (quoted). Exclude: `performance -sports` (minus prefix). Code identifiers work: `handleError async`.
- **vec:** Full natural language question. Be specific: `"how does the rate limiter handle burst traffic"`. Include context: `"in the payment service, how are refunds processed"`.
- **hyde:** Write 50–100 words of what the *answer* looks like. Use the vocabulary you expect in the result.

**Lex query syntax:**

| Syntax | Meaning | Example |
|--------|---------|---------|
| `term` | Prefix match | `perf` matches "performance" |
| `"phrase"` | Exact phrase | `"rate limiter"` |
| `-term` | Exclude | `performance -sports` |

Note: `-term` only works in lex queries, not vec/hyde.

**Combining types:**

| Goal | Approach |
|------|----------|
| Know exact terms | `lex` only |
| Don't know vocabulary | Use a single-line query (implicit `expand:`) or `vec` |
| Best recall | `lex` + `vec` |
| Complex topic | `lex` + `vec` + `hyde` |
| Ambiguous query | Add `intent` to any combination above |

First sub-query gets 2× weight in fusion — put your strongest signal first.

**Query strategy examples:**

```json
// Simple keyword lookup
[{ "type": "lex", "query": "project alpha milestone" }]

// Conceptual search
[{ "type": "vec", "query": "what was decided about the firmware timeline?" }]

// Best recall — combine lex + vec + hyde
[
  { "type": "lex", "query": "\"firmware readiness\" timeline -test" },
  { "type": "vec", "query": "when is the firmware delivery date?" },
  { "type": "hyde", "query": "The firmware team committed to delivering the final build by March 15. This was discussed in the PEC review and depends on the silicon validation completing by March 1." }
]

// Disambiguate with intent
{
  "searches": [{ "type": "lex", "query": "performance" }],
  "intent": "firmware execution benchmarks and cycle counts"
}
```

**`qmd-get`**:
- `file` (required) — File path or docid (e.g., `memory/DailyLogs/2026-03-01.md` or `#abc123`)
- `fromLine` (optional) — Start from this line number
- `maxLines` (optional) — Maximum lines to return

**`qmd-multi_get`**:
- `pattern` (required) — Glob pattern or comma-separated list (e.g., `memory/DailyLogs/2026-03-*.md`)

## CLI Fallback

If the QMD MCP server is unavailable, use CLI commands via PowerShell:

```powershell
# Keyword search (fast, BM25 only) — preferred for exact terms
qmd search "project alpha release timeline" -n 5

# Search within a specific collection
qmd search "firmware readiness" -c knowledgebase -n 10

# Hybrid query with auto-expansion + reranking (best quality, uses LLM)
qmd query "quarterly planning process"

# Structured query document (lex + vec, no LLM expansion)
qmd query "lex: `"firmware readiness`" timeline
vec: when is firmware delivery?"

# Show score traces for debugging
qmd query --json --explain "firmware timeline"

# Get a specific document
qmd get "memory/Knowledgebase/Program/roadmap.md"

# Get document by docid (from search results)
qmd get "#abc123"

# Get multiple documents by glob
qmd multi-get "memory/DailyLogs/2026-03-*.md"

# Batch pull by comma-separated list
qmd multi-get notes/foo.md,notes/bar.md

# Check index status
qmd status

# Re-index text (fast, no GPU needed)
qmd update
```

> **Note:** `qmd query` uses QMD's built-in GGUF models for expansion and reranking. For faster semantic search without LLM overhead, prefer `hybrid-search.py` which uses the configured embedding provider (SentenceTransformer by default). `qmd search` (BM25 only) is always fast.

### Hybrid Search (Recommended for Conceptual Queries)

Combines QMD BM25 keyword search with local vector similarity using Reciprocal Rank Fusion (RRF). BM25 catches exact keyword matches while vector embeddings catch conceptual/semantic matches.

```powershell
# Hybrid search (BM25 + local vector, RRF merged)
python skills/qmd-memory/scripts/hybrid-search.py "project alpha release decisions" -n 5

# JSON output for programmatic use
python skills/qmd-memory/scripts/hybrid-search.py "HBM purchase order" --json

# Markdown output
python skills/qmd-memory/scripts/hybrid-search.py "power efficiency" --md

# BM25 only (fast, no embedding call)
python skills/qmd-memory/scripts/hybrid-search.py "firmware" --bm25-only

# Vector only (local GGUF)
python skills/qmd-memory/scripts/hybrid-search.py "infrastructure decisions" --vector-only

# Override provider (e.g., use Azure OpenAI instead of local)
python skills/qmd-memory/scripts/hybrid-search.py "decisions" --provider azure_openai

# Filter by collection
python skills/qmd-memory/scripts/hybrid-search.py "supply chain" -c weekly-reports -n 10
```

Results show `found_by: bm25+vector` when both engines match, boosting documents with cross-signal agreement. The RRF algorithm merges rankings without needing score calibration between the two backends.

### Embedding CLI

Generate and refresh vector embeddings for all indexed documents. By default uses the local GGUF model configured in `agentconfig.json`:

```powershell
# Test embedding connectivity (local or Azure, based on config)
python skills/qmd-memory/scripts/azure-embed.py --test

# Generate embeddings for all collections (default: local GGUF, ~25ms/doc, 191 docs/sec batch)
python skills/qmd-memory/scripts/azure-embed.py

# Generate embeddings for a specific collection
python skills/qmd-memory/scripts/azure-embed.py --collection knowledgebase

# Override provider for this run only
python skills/qmd-memory/scripts/azure-embed.py --provider azure_openai

# Check embedding status
python skills/qmd-memory/scripts/azure-embed.py --status
```

Embeddings are cached locally in `skills/qmd-memory/cache/embeddings/` and do not require re-generation unless source documents change.

## Workflow

### Memory Search (Primary Use Case)

**When to search:** Before answering questions about:
- Past decisions, discussions, or context from previous sessions
- Program knowledge, specifications, or technical details
- Historical weekly reports or status updates
- Any topic where the `memory/` directory might have relevant content

**Search workflow:**

1. **Determine search type:**
   - Known exact terms (names, IDs, dates) → Use `qmd-query` with `lex` sub-query — fast BM25 keyword search
   - Conceptual/fuzzy queries → Use `qmd-query` with `lex` + `vec` sub-queries for best recall
   - Complex topics needing deep recall → Use `qmd-query` with `lex` + `vec` + `hyde` sub-queries
   - Ambiguous terms → Add `intent` to disambiguate (e.g., `"intent": "firmware execution benchmarks"` when searching for "performance")
   - Fallback if MCP unavailable → `python skills/qmd-memory/scripts/hybrid-search.py "query"` (BM25 + local vector with RRF merging)

2. **Scope the search:**
   - Daily logs → collection: `dailylogs`
   - Program knowledge → collection: `knowledgebase`
   - Weekly reports → collection: `weekly-reports`
   - Skill workflows → collection: `skills-docs`
   - Cross-cutting topics → omit collection (searches all)

3. **Inject results as context:**
   - Include the top search results in your reasoning
   - Cite the source file path when referencing retrieved content
   - If results are insufficient, try a different search mode or broader query

4. **Proceed with the response** using the retrieved context alongside MEMORY.md and CLAUDE.md

### Memory Maintenance

#### Updating MEMORY.md (Semantic Memory)

When the user shares permanent facts (preferences, contacts, project changes), update `memory/MEMORY.md`:

1. Read current MEMORY.md
2. Classify the new information:
   - **Profile/preference** → Update the relevant section
   - **New contact** → Add to Key Contacts
   - **Tool/workflow change** → Update Tooling & Integrations
   - **Program update** → Update Active Programs
3. Check for contradictions — new info replaces old
4. Ensure file stays under ~200 lines
5. Write the updated file

**When to update MEMORY.md:**
- User explicitly says "remember this" or "update my profile"
- A significant permanent fact is learned (e.g., new team member, tool change)
- Do NOT store temporary/episodic facts here — those go in daily logs

#### Daily Context Logs (`memory/DailyLogs/YYYY-MM-DD.md`)

Store daily summaries, decisions, and working context as dated markdown files. These serve as a running log of what happened each day.

- **Auto-load**: Today's log and yesterday's log are loaded automatically at session start for continuity
- **Older logs**: Searchable via QMD — no need to manually retrieve; search by topic instead
- **Content**: Key decisions, blockers, progress notes, conversation summaries, action items

**Creating a daily log:**
- At the start of each session, check if today's log exists; create it if not
- Append notable context throughout the session (decisions made, problems solved, next steps)
- At session end, update with a summary of what was accomplished

**Format:**

```markdown
# YYYY-MM-DD

## Summary
Brief overview of the day's work.

## Decisions
- Decision made and rationale

## Progress
- What was accomplished

## Blockers
- Any open issues

## Next Steps
- What to pick up next
```

These are automatically indexed by QMD and searchable in future sessions.

#### Knowledgebase (`memory/Knowledgebase/`)

Store long-term artifacts, curated project knowledge, reports, and reference material as markdown files. These are **not** auto-loaded — retrieve them when needed for specific tasks.

Organized by category:

- **`Program/`** — Program context, strategy, roadmaps, org docs
- **`ExecutiveReviews/`** — Monthly exec reviews, notes, readouts
- **`ProgramExecutionCouncil/`** — Weekly PEC reviews, action items, minutes
- **`Workstreams/<name>/`** — One subfolder per workstream (kebab-case), containing status, deliverables, notes
- **`Specifications/SoC/`** — System-on-Chip specs
- **`Specifications/System/`** — System / hardware specs
- **`Specifications/Software/`** — Software specs
- **`Specifications/Firmware/`** — Firmware specs
- **Converted documents**: Output from the markitdown skill (PDF/Word/Excel → markdown)

**Naming convention:** Use descriptive kebab-case filenames (e.g., `project-architecture.md`, `deployment-notes.md`, `troubleshooting-guide.md`).

**Directory structure:**

```
memory/
├── DailyLogs/
│   ├── 2026-03-01.md                    # Older daily log (retrieve on demand)
│   └── 2026-03-02.md                    # Today's log (auto-load)
├── MEMORY.md
└── Knowledgebase/
    ├── Program/                         # Program context, roadmaps
    ├── ExecutiveReviews/                # Monthly exec reviews
    ├── ProgramExecutionCouncil/         # Weekly PEC reviews
    ├── Workstreams/
    │   ├── <workstream-name>/           # Per-workstream folder
    │   └── ...
    └── Specifications/
        ├── SoC/                         # System-on-Chip specs
        ├── System/                      # Hardware / system specs
        ├── Software/                    # Software specs
        └── Firmware/                    # Firmware specs
```

#### Re-indexing After Content Changes

After adding significant new content (bulk knowledgebase ingestion, multiple weekly reports):

```powershell
# Step 1: Update QMD text index (fast, local)
qmd update

# Step 2: Generate embeddings (fast, local GGUF by default)
python skills/qmd-memory/scripts/azure-embed.py
```

QMD also auto-reindexes text every 5 minutes when running as an MCP server (but does not auto-refresh embeddings).

## Memory Flush (Pre-Session-End)

**Before ending a session or when context is getting long**, proactively save important context to prevent memory loss. This can also be triggered by running `memory-flush.ps1`.

1. **Check for unsaved context** — Review the session for:
   - Decisions made but not yet written to daily log
   - New permanent facts not yet in MEMORY.md (contacts, preferences, tool changes)
   - Action items or next steps discussed but not recorded
   - Important context that would be lost if the session resets

2. **Write to daily log** (`memory/DailyLogs/YYYY-MM-DD.md`):
   - Append a `## Session Summary` section with key decisions, outcomes, and next steps
   - Include any action items with owners and deadlines
   - Note any blockers or risks identified

3. **Update MEMORY.md** if permanent facts changed:
   - New contacts learned → add to Key Contacts
   - Workflow/tool changes → update Tooling & Integrations
   - Project status changes → update Active Programs

4. **Trigger re-index** if significant content was added:
   ```powershell
   powershell -File skills/qmd-memory/scripts/memory-flush.ps1
   ```
   Or manually: `qmd update` then `python skills/qmd-memory/scripts/azure-embed.py`

**When to flush:**
- When the user says "goodbye", "end session", "that's all", or similar
- When context window is approaching limits (long sessions with many tool calls)
- When switching to a significantly different topic area
- At natural breakpoints after completing a major task

## Rules

### Search Rules
- **ALWAYS** search QMD before answering questions about past context or program knowledge — do not rely on memory alone
- **ALWAYS** cite the source file path when using retrieved content in responses
- **ALWAYS** prefer MCP `qmd-query` tool over CLI commands when the QMD MCP server is available
- **ALWAYS** use `azure-embed.py` for batch embedding generation (uses local SentenceTransformer by default)
- **ALWAYS** prefer `hybrid-search.py` as fallback when MCP is unavailable — it uses the optimized local embedding provider
- **NEVER** use personal Azure subscriptions to set up embedding services or any cloud AI endpoints for work-related content — use the local SentenceTransformer provider instead
- For search, start with `qmd-query` using `lex` sub-query (fast BM25 keyword) and add `vec`/`hyde` if initial results are insufficient
- Use `intent` to disambiguate ambiguous queries (e.g., "performance" → add intent: "firmware benchmarks")
- When contradictions are found between memory sources, prefer more recent content

### Memory Maintenance Rules
- **ALWAYS** load MEMORY.md at session start. Update when permanent facts change. Keep under ~200 lines.
- **ALWAYS** create/update today's daily log. Auto-load today + yesterday only.
- **ALWAYS** flush memory before ending a session (see Memory Flush above)
- **NEVER** store secrets, credentials, or sensitive data in MEMORY.md or daily logs
- **NEVER** store temporary/episodic facts in MEMORY.md — use daily logs instead
- Knowledgebase files are searchable via QMD. Do not auto-load all files — search by topic, then retrieve what's relevant.
- Daily logs should be scannable, not exhaustive transcripts.
- If a knowledgebase article already exists for a topic, update it rather than creating a new one.
- After significant knowledgebase changes, run `qmd update` then `python skills/qmd-memory/scripts/azure-embed.py`
- The local GGUF model file (`skills/qmd-memory/models/bge-small-en-v1.5-f16.gguf`) is git-ignored — see Model download section for first-time setup
