# qmd-memory

Search and manage the agent's persistent memory using **QMD** — a local hybrid search engine for markdown files. Combines BM25 keyword search, vector semantic search with local SentenceTransformer embeddings (`bge-small-en-v1.5`, 384 dimensions), all running on-device — zero cost, offline-capable, no API keys required. Also supports **local GGUF** and **Azure OpenAI Embeddings** as alternative backends.

## Prerequisites

- **Node.js 22+** and npm
- **~2GB disk space** for QMD's built-in GGUF models (auto-downloaded on first run)
- **Windows** (macOS/Linux also supported)
- *(Optional)* **Python 3.11+** with `sentence-transformers` for local embeddings (recommended), `llama-cpp-python` for GGUF, or `openai` + `python-dotenv` for Azure OpenAI

## Installation

### 1. Install QMD

```bash
npm install -g @tobilu/qmd
```

### 2. Run the setup script

```powershell
powershell -ExecutionPolicy Bypass -File "skills/qmd-memory/scripts/setup-qmd.ps1"
```

This creates 4 collections, adds context descriptions, and runs initial indexing.

### 3. Add QMD MCP server

Add to `C:\Users\<username>\.copilot\mcp-config.json`:

```json
{
  "qmd": {
    "command": "qmd",
    "args": ["mcp"]
  }
}
```

### 4. Register the skill

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"skills/qmd-memory"
```

Restart your Copilot session for the skill to appear in `/skills`.

## Collections

| Collection | What's Indexed |
|-----------|---------------|
| `memory-root` | Daily context logs (`memory/*.md`) |
| `knowledgebase` | Program knowledge, specs, reviews (`memory/Knowledgebase/**/*.md`) |
| `weekly-reports` | Executive weekly reports (`memory/WeeklyReports/**/*.md`) |
| `skills-docs` | Skill definitions (`skills/**/SKILL.md`) |

## Usage

### Search via agent

```
Search my memory for decisions about the project milestone
```

```
What do we know about software readiness?
```

```
Find past weekly reports mentioning supply chain risks
```

### Search via CLI

```powershell
# Keyword search (fast, no API call)
qmd search "project milestone" -n 5

# Hybrid search — BM25 + local vector with RRF merging (recommended)
python skills/qmd-memory/scripts/hybrid-search.py "silicon validation risks" -n 5

# Hybrid search with JSON output
python skills/qmd-memory/scripts/hybrid-search.py "HBM purchase order" --json

# Search within a collection
qmd search "firmware" -c knowledgebase -n 10
python skills/qmd-memory/scripts/hybrid-search.py "firmware" -c knowledgebase
```

### Re-index after adding content

```powershell
# Re-index QMD text index
qmd update

# Regenerate Azure embeddings
python skills/qmd-memory/scripts/azure-embed.py
```

## GGUF Models

Downloaded automatically on first use (~2GB total):

| Model | Purpose | Size |
|-------|---------|------|
| embeddinggemma-300M | Vector embeddings | ~300MB |
| qwen3-reranker-0.6b | Result re-ranking | ~640MB |
| qmd-query-expansion-1.7B | Query expansion | ~1.1GB |

## Troubleshooting

### QMD not found after install

- Ensure npm global bin directory is on PATH
- Try `npx @tobilu/qmd status` as a test
- Restart terminal after installation

### Search returns no results

1. Check index status: `qmd status`
2. Re-index: `qmd update && qmd embed`
3. Verify collections: `qmd collection list`

### Slow first search

The first search after installation downloads GGUF models (~2GB). Subsequent searches are fast. Pre-warm with: `qmd query "test" -n 1`

## SentenceTransformer Embeddings (Recommended Default)

The default embedding provider uses `BAAI/bge-small-en-v1.5` (384 dimensions) running locally via `sentence-transformers`. Pure Python, no C++ compiler needed, auto-downloads the model on first use (~130MB, cached by HuggingFace). Zero-cost, all data stays on-device.

### Setup

1. **Install sentence-transformers:**
   ```bash
   pip install sentence-transformers
   ```

2. **Verify config** in `agentconfig.json` (default is already `sentence_transformer`):
   ```json
   {
     "memory": {
       "embedding": {
         "provider": "sentence_transformer",
         "sentence_transformer": {
           "model_name": "BAAI/bge-small-en-v1.5",
           "dimensions": 384
         }
       }
     }
   }
   ```

3. **Generate embeddings:**
   ```bash
   python skills/qmd-memory/scripts/azure-embed.py
   ```

   The model downloads automatically on first run.

## Local GGUF Embeddings (Alternative)

For environments where a smaller binary footprint is preferred, the GGUF provider uses `bge-small-en-v1.5-f16` (384 dimensions) via `llama-cpp-python`. Requires C++ toolchain on some platforms.

### Setup

1. **Install llama-cpp-python:**
   ```bash
   pip install llama-cpp-python
   ```

2. **Download the model (~64MB):**
   ```powershell
   New-Item -ItemType Directory -Force skills/qmd-memory/models
   Invoke-WebRequest -Uri "https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-f16.gguf" -OutFile "skills/qmd-memory/models/bge-small-en-v1.5-f16.gguf"
   ```

3. **Switch provider** in `agentconfig.json`:
   ```json
   "provider": "local"
   ```

4. **Generate embeddings:**
   ```bash
   python skills/qmd-memory/scripts/azure-embed.py
   ```

### Benchmark Results

Tested with `bge-small-en-v1.5-f16` (384 dims) on Intel Core Ultra 7 165U:

| Metric | Value |
|--------|-------|
| Single query median | 24.71 ms |
| Single query mean | 29.18 ms |
| Single query best | 17.44 ms |
| P95 latency | 68.32 ms |
| Batch 8 | 98 queries/sec (10.2 ms/query) |
| Batch 32 | 113 queries/sec (8.8 ms/query) |
| Batch 128 | 191 queries/sec (5.2 ms/query) |
| Model RAM | 172 MB |
| Peak process RAM | 575 MB |

**vs Azure OpenAI text-embedding-3-large:** Local bge-small is 2–8× faster (no network latency), zero cost, and runs entirely offline. Trade-off: 384 dims vs 3072 dims — but for QMD local search, 384 dims with bge-small is more than sufficient.

**Verdict:** Very viable for local QMD embedding. At ~25ms/query, re-indexing a 500-doc knowledgebase takes ~12 seconds. Batch mode pushes throughput to 191 docs/sec. The 172 MB RAM footprint is modest.

## Azure OpenAI Embeddings (Optional — Corporate Endpoints Only)

> **⚠️ Policy: Do NOT use personal Azure subscriptions** to set up embedding services for work-related content. The SentenceTransformer provider is the recommended default. If you need Azure OpenAI, use a corporate-provisioned endpoint.

For higher-quality vector search, you can use Azure OpenAI's `text-embedding-3-large` model (3072 dimensions) instead of the local providers.

### Setup

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Set your API key** in `.env`:
   ```
   AZURE_OPENAI_API_KEY=your-actual-key
   ```

3. **Enable Azure embeddings** in `agentconfig.json` (project root):
   ```json
   {
     "memory": {
       "embedding": {
         "provider": "azure_openai",
         "azure_openai": {
           "endpoint": "https://your-corporate-resource.cognitiveservices.azure.com/",
           "deployment": "text-embedding-3-large",
           "model": "text-embedding-3-large",
           "api_version": "2024-04-01-preview"
         }
       }
     }
   }
   ```

4. **Install Python dependencies:**
   ```bash
   pip install openai python-dotenv
   ```

5. **Test connectivity:**
   ```bash
   python skills/qmd-memory/scripts/azure-embed.py --test
   ```

6. **Generate embeddings:**
   ```bash
   python skills/qmd-memory/scripts/azure-embed.py
   ```

### Azure Embedding CLI

```powershell
# Test Azure OpenAI connection
python skills/qmd-memory/scripts/azure-embed.py --test

# Embed all collections
python skills/qmd-memory/scripts/azure-embed.py

# Embed a specific collection
python skills/qmd-memory/scripts/azure-embed.py -c knowledgebase

# Check embedding status
python skills/qmd-memory/scripts/azure-embed.py --status
```

### Configuration Reference

| File | Key | Description |
|------|-----|-------------|
| `agentconfig.json` | `memory.embedding.provider` | `"sentence_transformer"` (default), `"local"` (GGUF), or `"azure_openai"` |
| `agentconfig.json` | `memory.embedding.sentence_transformer.model_name` | HuggingFace model ID (default: `BAAI/bge-small-en-v1.5`) |
| `agentconfig.json` | `memory.embedding.sentence_transformer.dimensions` | Embedding dimensions (384 for bge-small) |
| `agentconfig.json` | `memory.embedding.local.model_path` | Path to GGUF model file |
| `agentconfig.json` | `memory.embedding.local.model_name` | Model name for cache key |
| `agentconfig.json` | `memory.embedding.local.dimensions` | Embedding dimensions (384 for bge-small) |
| `agentconfig.json` | `memory.embedding.azure_openai.endpoint` | Azure OpenAI resource URL (corporate only) |
| `agentconfig.json` | `memory.embedding.azure_openai.deployment` | Deployment name |
| `agentconfig.json` | `memory.embedding.azure_openai.model` | Model name |
| `agentconfig.json` | `memory.embedding.azure_openai.api_version` | API version string |
| `.env` | `AZURE_OPENAI_API_KEY` | API key for Azure (git-ignored) |
