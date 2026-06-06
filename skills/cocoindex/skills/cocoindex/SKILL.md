---
name: cocoindex
description: >
  Comprehensive toolkit for developing with the CocoIndex library. Use when users
  need to create data transformation pipelines (flows), write custom functions,
  or operate flows via CLI or API. Covers building ETL workflows for AI data
  processing, including embedding documents into vector databases, building
  knowledge graphs, creating search indexes, or processing data streams with
  incremental updates. Triggers include "cocoindex", "data pipeline", "indexing flow",
  "embedding pipeline", "vector index", "knowledge graph", "ETL", "data transformation".
---

# CocoIndex

## Overview

CocoIndex is an ultra-performant real-time data transformation framework for AI with incremental processing. This skill enables building **indexing flows** that extract data from sources, apply transformations (chunking, embedding, LLM extraction), and export to targets (vector databases, graph databases, relational databases).

**Core capabilities:**

1. **Write indexing flows** - Define ETL pipelines using Python
2. **Create custom functions** - Build reusable transformation logic
3. **Operate flows** - Run and manage flows using CLI or Python API

**Key features:**

- Incremental processing (only processes changed data)
- Live updates (continuously sync source changes to targets)
- Built-in functions (text chunking, embeddings, LLM extraction)
- Multiple data sources (local files, S3, Azure Blob, Google Drive, Postgres)
- Multiple targets (Postgres+pgvector, Qdrant, LanceDB, Neo4j, Kuzu)

**For detailed documentation:** <https://cocoindex.io/docs/>
**Search documentation:** <https://cocoindex.io/docs/search?q=url%20encoded%20keyword>

## When to Use This Skill

**⚠️ SECURITY POLICY: Local Models Only**

To prevent data exfiltration to third-party services (see CI-1 in `threatmodel.md`), this deployment restricts CocoIndex to **local-only** LLM and embedding providers:

- ✅ **Ollama** — local LLM inference (generation + embeddings), no API key required
- ✅ **SentenceTransformerEmbed** — local embedding models (`all-MiniLM-L6-v2`, etc.)
- ❌ **OpenAI, Anthropic, Gemini, Voyage** — **PROHIBITED** (sends data to external APIs)

**Do NOT** generate flows using `LlmApiType.OPENAI`, `LlmApiType.ANTHROPIC`, `LlmApiType.GEMINI`, or `EmbedText` with external providers. If the user requests an external provider, explain the security policy and offer Ollama or SentenceTransformer as alternatives.

Use when users request:

- "Build a vector search index for my documents"
- "Create an embedding pipeline for code/PDFs/images"
- "Extract structured information using LLMs"
- "Build a knowledge graph from documents"
- "Set up live document indexing"
- "Create custom transformation functions"
- "Run/update my CocoIndex flow"

## Flow Writing Workflow

### Step 1: Understand Requirements

Ask clarifying questions to understand:

**Data source:**

- Where is the data? (local files, S3, database, etc.)
- What file types? (text, PDF, JSON, images, code, etc.)
- How often does it change? (one-time, periodic, continuous)

**Transformations:**

- What processing is needed? (chunking, embedding, extraction, etc.)
- Which embedding model? (SentenceTransformer, OpenAI, custom)
- Any custom logic? (filtering, parsing, enrichment)

**Target:**

- Where should results go? (Postgres, Qdrant, Neo4j, etc.)
- What schema? (fields, primary keys, indexes)
- Vector search needed? (specify similarity metric)

### Step 2: Set Up Dependencies

**For comprehensive installation and database setup, load `references/installation.md`.**

**System requirements:** Python 3.11–3.13 on macOS 10.12+/Linux glibc 2.28+/Windows 10+.

**Install CocoIndex:**

```bash
pip install -U cocoindex
```

**Optional extras (add as needed):**

- `cocoindex[embeddings]` - For SentenceTransformer embeddings (when using `SentenceTransformerEmbed`)
- `cocoindex[colpali]` - For ColPali image/document embeddings (when using `ColPaliEmbedImage` or `ColPaliEmbedQuery`)
- `cocoindex[lancedb]` - For LanceDB target (when exporting to LanceDB)
- `cocoindex[embeddings,lancedb]` - Multiple extras can be combined

**Install Postgres (required for internal storage):**

If user doesn't already have Postgres with pgvector, guide them to start one via Docker:

```bash
docker compose -f <(curl -L https://raw.githubusercontent.com/cocoindex-io/cocoindex/refs/heads/main/dev/postgres.yaml) up -d
```

Default connection URL: `postgres://cocoindex:cocoindex@localhost:5432/cocoindex`

**For full installation details:** <https://cocoindex.io/docs/getting_started/installation>

### Step 3: Set Up Environment

**Check existing environment first:**

1. Check if `COCOINDEX_DATABASE_URL` exists in environment variables
   - If not found, use default: `postgres://cocoindex:cocoindex@localhost/cocoindex`

2. **For flows requiring LLM/embeddings** (extraction, semantic search):
   - Use **Ollama** for LLM generation (local, no API key): `ollama pull llama3.2`
   - Use **SentenceTransformerEmbed** for embeddings (local, no API key): install `cocoindex[embeddings]`
   - **Do NOT use external providers** (OpenAI, Anthropic, Gemini, Voyage) — this is prohibited by security policy (CI-1)
   - Check if Ollama is running: `ollama list`

**Guide user to create `.env` file:**

```bash
# Database connection (required - internal storage)
COCOINDEX_DATABASE_URL=postgres://cocoindex:cocoindex@localhost/cocoindex

# No external API keys needed — use Ollama (local) for LLM and SentenceTransformer for embeddings
# Ollama requires no API key (runs locally on port 11434)
```

**For more LLM options:** <https://cocoindex.io/docs/ai/llm>

Create basic project structure:

```python
# main.py
from dotenv import load_dotenv
import cocoindex

@cocoindex.flow_def(name="FlowName")
def my_flow(flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope):
    # Flow definition here
    pass

if __name__ == "__main__":
    load_dotenv()
    cocoindex.init()
    my_flow.update()
```

### Step 4: Write the Flow

Follow this structure:

```python
@cocoindex.flow_def(name="DescriptiveName")
def flow_name(flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope):
    # 1. Import source data
    data_scope["source_name"] = flow_builder.add_source(
        cocoindex.sources.SourceType(...)
    )

    # 2. Create collector(s) for outputs
    collector = data_scope.add_collector()

    # 3. Transform data (iterate through rows)
    with data_scope["source_name"].row() as item:
        # Apply transformations
        item["new_field"] = item["existing_field"].transform(
            cocoindex.functions.FunctionName(...)
        )

        # Nested iteration (e.g., chunks within documents)
        with item["nested_table"].row() as nested_item:
            nested_item["embedding"] = nested_item["text"].transform(...)

            # Collect data for export
            collector.collect(
                field1=nested_item["field1"],
                field2=item["field2"],
                generated_id=cocoindex.GeneratedField.UUID
            )

    # 4. Export to target
    collector.export(
        "target_name",
        cocoindex.targets.TargetType(...),
        primary_key_fields=["field1"],
        vector_indexes=[...]  # If needed
    )
```

**Key principles:**

- Each source creates a field in the top-level data scope
- Use `.row()` to iterate through table data
- **CRITICAL: Always assign transformed data to row fields** - Use `item["new_field"] = item["existing_field"].transform(...)`, NOT local variables like `new_field = item["existing_field"].transform(...)`
- Transformations create new fields without mutating existing data
- Collectors gather data from any scope level
- Export must happen at top level (not within row iterations)

**Common mistakes to avoid:**

❌ **Wrong:** Using local variables for transformations

```python
with data_scope["files"].row() as file:
    summary = file["content"].transform(...)  # ❌ Local variable
    summaries_collector.collect(filename=file["filename"], summary=summary)
```

✅ **Correct:** Assigning to row fields

```python
with data_scope["files"].row() as file:
    file["summary"] = file["content"].transform(...)  # ✅ Field assignment
    summaries_collector.collect(filename=file["filename"], summary=file["summary"])
```

### Step 5: Design the Flow Solution

**IMPORTANT:** The patterns listed below are common starting points, but **you cannot exhaustively enumerate all possible scenarios**. When user requirements don't match existing patterns:

1. **Combine elements from multiple patterns** - Mix and match sources, transformations, and targets
2. **Review additional examples** - See <https://github.com/cocoindex-io/cocoindex?tab=readme-ov-file#-examples-and-demo>
3. **Think from first principles** - Use the core APIs (sources, transforms, collectors, exports)
4. **Be creative** - CocoIndex is flexible; unique combinations of components can solve unique problems

**Common starting patterns (use references for detailed examples):**

- **For text embedding:** Load `references/flow_patterns.md` → "Pattern 1: Simple Text Embedding"
- **For code embedding:** Load `references/flow_patterns.md` → "Pattern 2: Code Embedding with Language Detection"
- **For LLM extraction + knowledge graph:** Load `references/flow_patterns.md` → "Pattern 3: LLM-based Extraction to Knowledge Graph"
- **For live updates:** Load `references/flow_patterns.md` → "Pattern 4: Live Updates with Refresh Interval"
- **For custom functions:** Load `references/flow_patterns.md` → "Pattern 5: Custom Transform Function"
- **For reusable query logic:** Load `references/flow_patterns.md` → "Pattern 6: Transform Flow for Reusable Logic"
- **For concurrency control:** Load `references/flow_patterns.md` → "Pattern 7: Concurrency Control"

### Step 6: Test and Run

Guide user through testing:

```bash
# 1. Run with setup
cocoindex update --setup -f main   # -f force setup without confirmation prompts

# 2. Start a server and redirect users to CocoInsight
cocoindex server -ci main
# Then open CocoInsight at https://cocoindex.io/cocoinsight
```

## Data Types

CocoIndex has a type system independent of programming languages. All data types are determined at flow definition time.

**When to define types:**

- **Custom functions**: Type annotations are **required** for return values (source of truth for type inference)
- **Flow fields**: Type annotations are **NOT needed** - CocoIndex automatically infers types
- **Dataclasses/Pydantic models**: Only create when **actually used** (as function params/returns or ExtractByLlm output_type)

**Common type categories:**

1. **Primitive types**: `str`, `int`, `float`, `bool`, `bytes`, `datetime.date`, `datetime.datetime`, `uuid.UUID`
2. **Vector types**: `cocoindex.Vector[cocoindex.Float32, typing.Literal[768]]` - 768-dim float32 vector
3. **Struct types**: Dataclass, NamedTuple, or Pydantic model
4. **Table types**: KTable (`dict[K, V]`), LTable (`list[R]`)
5. **Json type**: `cocoindex.Json` for unstructured/dynamic data
6. **Optional types**: `T | None` for nullable values

**For comprehensive data types documentation:** <https://cocoindex.io/docs/core/data_types>

## Custom Functions

When users need custom transformation logic, create custom functions.

### Standalone Functions

```python
@cocoindex.op.function(behavior_version=1)
def my_function(input_arg: str, optional_arg: int | None = None) -> dict:
    # Transformation logic
    return {"result": f"processed-{input_arg}"}
```

### Spec+Executor Functions (for config/setup needs)

```python
class MyFunction(cocoindex.op.FunctionSpec):
    model_name: str
    threshold: float = 0.5

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class MyFunctionExecutor:
    spec: MyFunction
    model = None

    def prepare(self) -> None:
        self.model = load_model(self.spec.model_name)

    def __call__(self, text: str) -> dict:
        result = self.model.process(text)
        return {"result": result}
```

For detailed examples, load `references/custom_functions.md`.

**For more on custom functions:** <https://cocoindex.io/docs/custom_ops/custom_functions>

## Built-in Functions

### Text Processing

- **SplitRecursively** - Chunk text: `doc["chunks"] = doc["content"].transform(cocoindex.functions.SplitRecursively(), language="markdown", chunk_size=2000, chunk_overlap=500)`
- **ParseJson** - Parse JSON strings: `data = json_string.transform(cocoindex.functions.ParseJson())`
- **DetectProgrammingLanguage** - Detect language: `file["language"] = file["filename"].transform(cocoindex.functions.DetectProgrammingLanguage())`

### Embeddings

- **SentenceTransformerEmbed** (recommended — local, no API key): `chunk["embedding"] = chunk["text"].transform(cocoindex.functions.SentenceTransformerEmbed(model="sentence-transformers/all-MiniLM-L6-v2"))`
- **ColPaliEmbedImage** (requires `cocoindex[colpali]`): Multimodal image embeddings
- ~~EmbedText with external APIs~~ — **PROHIBITED** by security policy (CI-1). Use SentenceTransformerEmbed or Ollama instead.

### LLM Extraction

- **ExtractByLlm** - Extract structured data or text with LLM (**Ollama only**):

```python
item["product_info"] = item["text"].transform(
    cocoindex.functions.ExtractByLlm(
        llm_spec=cocoindex.LlmSpec(api_type=cocoindex.LlmApiType.OLLAMA, model="llama3.2"),
        output_type=ProductInfo,
        instruction="Extract product information"
    )
)
```

## Common Sources and Targets

**Browse all sources:** <https://cocoindex.io/docs/sources/>
**Browse all targets:** <https://cocoindex.io/docs/targets/>

### Sources

- **LocalFile**: `cocoindex.sources.LocalFile(path="documents", included_patterns=["*.md", "*.txt"])`
- **AmazonS3**: `cocoindex.sources.AmazonS3(bucket="my-bucket", prefix="documents/")`
- **Postgres**: `cocoindex.sources.Postgres(connection=..., query="SELECT id, content FROM documents")`

### Targets

- **Postgres** (with pgvector): `collector.export("target", cocoindex.targets.Postgres(), primary_key_fields=["id"], vector_indexes=[...])`
- **Qdrant**: `collector.export("target", cocoindex.targets.Qdrant(collection_name="my_collection"), primary_key_fields=["id"])`
- **LanceDB**: `collector.export("target", cocoindex.targets.LanceDB(uri="lancedb_data", table_name="my_table"), primary_key_fields=["id"])`
- **Neo4j**: Nodes and Relationships exports for knowledge graphs

## Operating Flows

### CLI Operations

```bash
cocoindex setup main.py           # Create resources
cocoindex update --setup main      # Update with auto-setup
cocoindex update main.py -L        # Live update (continuous)
cocoindex drop main.py             # Remove all resources
cocoindex show main.py:FlowName    # Inspect flow
cocoindex evaluate main.py:FlowName --output-dir ./test_output  # Test without side effects
```

For complete CLI reference, load `references/cli_operations.md`.

### API Operations

```python
from dotenv import load_dotenv
import cocoindex

load_dotenv()
cocoindex.init()

stats = my_flow.update()           # One-time update
stats = await my_flow.update_async()  # Async update

# Live update
with cocoindex.FlowLiveUpdater(my_flow) as updater:
    pass  # Updater runs in background
```

For complete API reference, load `references/api_operations.md`.

## Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| "Flow not found" | Check APP_TARGET format; use `--app-dir` if not in project root |
| "Database connection failed" | Check `.env` has `COCOINDEX_DATABASE_URL`; test with `psql` |
| "Schema mismatch" | Re-run `cocoindex setup main.py` |
| "Live update exits immediately" | Add `refresh_interval` to source |
| "Out of memory" | Add `max_inflight_rows` / `max_inflight_bytes` concurrency limits |

## Reference Documentation

- **references/installation.md** - Installation, database setup, and project configuration
- **references/codebase_indexing.md** - Complete end-to-end codebase indexing example with Tree-sitter chunking and semantic search
- **references/flow_patterns.md** - Complete flow pattern examples
- **references/custom_functions.md** - Custom function creation guide
- **references/cli_operations.md** - Complete CLI reference
- **references/api_operations.md** - Python API reference

**For comprehensive documentation:** <https://cocoindex.io/docs/>
