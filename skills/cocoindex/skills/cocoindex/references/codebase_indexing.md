# Codebase Indexing Example

Complete end-to-end example for building a real-time codebase index with semantic search.
Based on the official [realtime-codebase-indexing](https://github.com/cocoindex-io/realtime-codebase-indexing) example.

## Overview

This example:
1. **Ingests** code files from a local codebase
2. **Detects** the programming language via file extension
3. **Chunks** code using Tree-sitter for syntax-aware splitting (functions, classes, modules)
4. **Embeds** each chunk using SentenceTransformers
5. **Stores** embeddings in Postgres with pgvector for cosine similarity search
6. **Queries** the index with natural language using the same embedding model

**Key advantage:** CocoIndex uses incremental processing — only changed files are reprocessed, enabling near real-time index updates.

## Use Cases

- Semantic code context for AI coding agents (Claude, Codex, Gemini CLI)
- MCP for code editors (Cursor, Windsurf, VSCode)
- Context-aware code search — natural language code retrieval
- Code review agents — AI code review, automated code analysis, PR summarization
- Automated code refactoring and large-scale code migration
- SRE workflows — root cause analysis, incident response, change impact assessment
- Auto-generated design documentation from code

## Prerequisites

```bash
pip install "cocoindex[embeddings]" python-dotenv pgvector "psycopg[binary,pool]"
```

Or via `pyproject.toml`:

```toml
[project]
name = "code-embedding"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "cocoindex[embeddings]>=0.3.9",
    "python-dotenv>=1.0.1",
    "pgvector>=0.4.1",
    "psycopg[binary,pool]",
]

[tool.setuptools]
packages = []
```

Postgres with pgvector must be running. See `references/installation.md` for setup.

## Complete Example (main.py)

```python
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector
import functools
import cocoindex
import os
from numpy.typing import NDArray
import numpy as np


# --- Shared embedding logic (used for both indexing and querying) ---

@cocoindex.transform_flow()
def code_to_embedding(
    text: cocoindex.DataSlice[str],
) -> cocoindex.DataSlice[NDArray[np.float32]]:
    """Embed text using a SentenceTransformer model."""
    return text.transform(
        cocoindex.functions.SentenceTransformerEmbed(
            model="sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    # Alternative: use Ollama for embeddings (local, no API key):
    # return text.transform(
    #     cocoindex.functions.EmbedText(
    #         api_type=cocoindex.LlmApiType.OLLAMA,
    #         model="nomic-embed-text",
    #     )
    # )


# --- Indexing Flow ---

@cocoindex.flow_def(name="CodeEmbedding")
def code_embedding_flow(
    flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope
) -> None:
    """Index codebase files into a vector database."""

    # 1. Ingest code files
    data_scope["files"] = flow_builder.add_source(
        cocoindex.sources.LocalFile(
            path="../..",  # codebase root — adjust to your project
            included_patterns=["*.py", "*.rs", "*.toml", "*.md", "*.mdx"],
            excluded_patterns=["**/.*", "target", "**/node_modules"],
        )
    )
    code_embeddings = data_scope.add_collector()

    with data_scope["files"].row() as file:
        # 2. Detect programming language from filename
        file["language"] = file["filename"].transform(
            cocoindex.functions.DetectProgrammingLanguage()
        )

        # 3. Chunk code using Tree-sitter (syntax-aware splitting)
        file["chunks"] = file["content"].transform(
            cocoindex.functions.SplitRecursively(),
            language=file["language"],
            chunk_size=1000,
            min_chunk_size=300,
            chunk_overlap=300,
        )

        with file["chunks"].row() as chunk:
            # 4. Embed each chunk
            chunk["embedding"] = chunk["text"].call(code_to_embedding)

            # 5. Collect for export
            code_embeddings.collect(
                filename=file["filename"],
                location=chunk["location"],
                code=chunk["text"],
                embedding=chunk["embedding"],
                start=chunk["start"],
                end=chunk["end"],
            )

    # 6. Export to Postgres with vector index
    code_embeddings.export(
        "code_embeddings",
        cocoindex.targets.Postgres(),
        primary_key_fields=["filename", "location"],
        vector_indexes=[
            cocoindex.VectorIndexDef(
                field_name="embedding",
                metric=cocoindex.VectorSimilarityMetric.COSINE_SIMILARITY,
            )
        ],
    )


# --- Query Handler ---

@functools.cache
def connection_pool() -> ConnectionPool:
    return ConnectionPool(os.environ["COCOINDEX_DATABASE_URL"])


TOP_K = 5


@code_embedding_flow.query_handler(
    result_fields=cocoindex.QueryHandlerResultFields(
        embedding=["embedding"], score="score"
    )
)
def search(query: str) -> cocoindex.QueryOutput:
    """Search the codebase index with a natural language query."""
    table_name = cocoindex.utils.get_target_default_name(
        code_embedding_flow, "code_embeddings"
    )
    query_vector = code_to_embedding.eval(query)

    with connection_pool().connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT filename, code, embedding,
                       embedding <=> %s AS distance,
                       start, "end"
                FROM {table_name}
                ORDER BY distance LIMIT %s
                """,
                (query_vector, TOP_K),
            )
            return cocoindex.QueryOutput(
                query_info=cocoindex.QueryInfo(
                    embedding=query_vector,
                    similarity_metric=cocoindex.VectorSimilarityMetric.COSINE_SIMILARITY,
                ),
                results=[
                    {
                        "filename": row[0],
                        "code": row[1],
                        "embedding": row[2],
                        "score": 1.0 - row[3],
                        "start": row[4],
                        "end": row[5],
                    }
                    for row in cur.fetchall()
                ],
            )


# --- Main ---

def _main() -> None:
    stats = code_embedding_flow.update()
    print("Updated index:", stats)

    while True:
        query = input("Enter search query (or Enter to quit): ")
        if query == "":
            break
        query_output = search(query)
        print("\nSearch results:")
        for result in query_output.results:
            print(
                f"[{result['score']:.3f}] {result['filename']}"
                f" (L{result['start']['line']}-L{result['end']['line']})"
            )
            print(f"    {result['code']}")
            print("---")
        print()


if __name__ == "__main__":
    load_dotenv()
    cocoindex.init()
    _main()
```

## How It Works

### Tree-sitter Integration

Unlike naive line-based chunking, CocoIndex uses [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) (Rust implementation) to parse code by syntax structure. Chunks align with functions, classes, and modules — preserving semantic integrity for better retrieval.

Supported languages include Python, Rust, JavaScript, TypeScript, Java, C++, Go, and many more. If a language isn't recognized, it falls back to plain text splitting.

### Incremental Processing

CocoIndex tracks file changes automatically. On subsequent runs, only modified files are reprocessed:

```bash
# First run: indexes everything
cocoindex update main

# Later runs: only reprocesses changed files
cocoindex update main
```

### Live Updates

For continuous monitoring (e.g., during development):

```bash
cocoindex update main -L
```

This requires adding `refresh_interval` to the source:

```python
import datetime

data_scope["files"] = flow_builder.add_source(
    cocoindex.sources.LocalFile(path="../.."),
    refresh_interval=datetime.timedelta(seconds=30)
)
```

## Running

```bash
# 1. Create .env file
echo 'COCOINDEX_DATABASE_URL=postgres://cocoindex:cocoindex@localhost/cocoindex' > .env

# 2. Install dependencies
pip install -e .

# 3. Setup and update the index
cocoindex update --setup main

# 4. Run interactive search
python main.py

# 5. (Optional) Start CocoInsight for pipeline visualization
cocoindex server -ci main
# Then open https://cocoindex.io/cocoinsight
```

## Customization

### Different Embedding Model

Replace `SentenceTransformerEmbed` with Ollama embeddings (local, no API key):

```python
@cocoindex.transform_flow()
def code_to_embedding(text: cocoindex.DataSlice[str]) -> cocoindex.DataSlice[NDArray[np.float32]]:
    return text.transform(
        cocoindex.functions.EmbedText(
            api_type=cocoindex.LlmApiType.OLLAMA,
            model="nomic-embed-text",
        )
    )
```

> **Security policy:** External LLM APIs (OpenAI, Anthropic, Gemini, Voyage) are prohibited. Use Ollama or SentenceTransformer only. See CI-1 in `threatmodel.md`.

### Different File Types

Adjust `included_patterns` and `excluded_patterns`:

```python
cocoindex.sources.LocalFile(
    path=".",
    included_patterns=["*.py", "*.js", "*.ts", "*.tsx", "*.java", "*.go", "*.cpp", "*.h"],
    excluded_patterns=["**/.*", "**/node_modules", "**/dist", "**/build", "**/__pycache__"],
)
```

### Different Vector Store

Replace `cocoindex.targets.Postgres()` with Qdrant:

```python
code_embeddings.export(
    "code_embeddings",
    cocoindex.targets.Qdrant(collection_name="codebase"),
    primary_key_fields=["filename", "location"],
)
```

## References

- **GitHub repo**: <https://github.com/cocoindex-io/realtime-codebase-indexing>
- **Tutorial**: <https://dev.to/cocoindex/build-real-time-codebase-indexing-for-ai-coding-agents-5eb2>
- **Video**: <https://www.youtube.com/watch?v=G3WstvhHO24>
- **CocoIndex docs**: <https://cocoindex.io/docs/>
- **CocoInsight**: <https://cocoindex.io/cocoinsight>
