# CocoIndex Plugin

Build data transformation pipelines, custom functions, and operate flows with [CocoIndex](https://cocoindex.io/) — an ultra-performant real-time data transformation framework for AI.

## Features

- **Indexing flows** — Define ETL pipelines in Python that extract, transform, and load data
- **Custom functions** — Build reusable transformation logic (chunking, embedding, LLM extraction)
- **Flow operations** — Run, manage, and monitor flows via CLI or Python API
- **Incremental processing** — Only processes changed data with live update support
- **Multiple targets** — Export to vector databases (Qdrant, Milvus, Pinecone), graph databases (Neo4j), and relational databases (Postgres)

## Prerequisites

- Python 3.12+
- PostgreSQL (local or remote) — used by CocoIndex for internal state management
- `pip install cocoindex`

## Usage

Invoke when you need to build data pipelines for AI workflows — embedding documents into vector stores, building knowledge graphs, creating search indexes, or processing data streams with incremental updates.

Triggers: `cocoindex`, `data pipeline`, `indexing flow`, `embedding pipeline`, `vector index`, `knowledge graph`, `ETL`, `data transformation`.

## License

Apache-2.0 — see [cocoindex-claude](https://github.com/cocoindex-io/cocoindex-claude)
