# Installation & Setup Guide

Complete guide for installing CocoIndex and setting up project dependencies.

## System Requirements

- **macOS**: 10.12+ on x86_64, 11.0+ on arm64
- **Linux**: x86_64 or arm64, glibc 2.28+ (Debian 10+, Ubuntu 18.10+, Fedora 29+, CentOS/RHEL 8+)
- **Windows**: 10+ on x86_64
- **Python**: 3.11 to 3.13
- **pip** (or uv, poetry, etc.)

## Install CocoIndex

```bash
pip install -U cocoindex
```

### Optional Extras

Install extras based on your needs:

```bash
pip install cocoindex[embeddings]       # SentenceTransformer embeddings
pip install cocoindex[colpali]          # ColPali image/document embeddings
pip install cocoindex[lancedb]          # LanceDB target
pip install cocoindex[embeddings,lancedb]  # Multiple extras
```

## Install Postgres (Required for Internal Storage)

CocoIndex requires a Postgres database with pgvector for internal state management.

### Option 1: Docker (Recommended)

1. Install [Docker Compose](https://docs.docker.com/compose/install/)
2. Start Postgres using CocoIndex's config:

```bash
docker compose -f <(curl -L https://raw.githubusercontent.com/cocoindex-io/cocoindex/refs/heads/main/dev/postgres.yaml) up -d
```

Or create your own `docker-compose.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: cocoindex-postgres
    environment:
      POSTGRES_USER: cocoindex
      POSTGRES_PASSWORD: cocoindex
      POSTGRES_DB: cocoindex
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cocoindex"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

```bash
docker-compose up -d
docker-compose ps  # Verify it's running
```

Connection URL: `postgres://cocoindex:cocoindex@localhost:5432/cocoindex`

### Option 2: Existing PostgreSQL

Enable the pgvector extension on your existing database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT * FROM pg_extension WHERE extname = 'vector';
```

## Environment Configuration

Create a `.env` file in your project directory:

```bash
# Database connection (required - internal storage)
COCOINDEX_DATABASE_URL=postgres://cocoindex:cocoindex@localhost/cocoindex

# Optional: App namespace for organizing flows
COCOINDEX_APP_NAMESPACE=dev

# Optional: Global concurrency limits
COCOINDEX_SOURCE_MAX_INFLIGHT_ROWS=50
COCOINDEX_SOURCE_MAX_INFLIGHT_BYTES=524288000  # 500MB

# No external API keys needed — use Ollama (local) for LLM and SentenceTransformer for embeddings
# Ollama requires no API key (runs locally on port 11434)
```

## Project Setup

### New Project (Minimal)

```python
# main.py
from dotenv import load_dotenv
import cocoindex

@cocoindex.flow_def(name="FlowName")
def my_flow(flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope):
    pass

if __name__ == "__main__":
    load_dotenv()
    cocoindex.init()
    my_flow.update()
```

### With pyproject.toml

```toml
[project]
name = "my-cocoindex-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "cocoindex",
    "python-dotenv",
]

# Add extras as needed:
# "sentence-transformers"  # For local embeddings
# "asyncpg"                # For PostgreSQL source/target
# "qdrant-client"          # For Qdrant target
# "lancedb"                # For LanceDB target
```

### Use-Case Specific Dependencies

**Vector Embedding Pipeline:**
```bash
pip install cocoindex python-dotenv sentence-transformers
```

**LLM Extraction Pipeline:**
```bash
pip install cocoindex python-dotenv openai
# or: pip install cocoindex python-dotenv anthropic
```

**Knowledge Graph Pipeline:**
```bash
pip install cocoindex python-dotenv neo4j
```

**Qdrant Vector Store:**
```bash
pip install cocoindex python-dotenv qdrant-client
```

**LanceDB Vector Store:**
```bash
pip install cocoindex[lancedb] python-dotenv
```

## Additional Target Setup

### Qdrant (Docker)

```yaml
# Add to docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: cocoindex-qdrant
    ports:
      - "6333:6333"  # HTTP API
      - "6334:6334"  # gRPC API
    volumes:
      - qdrant_data:/qdrant/storage
```

```bash
# .env
QDRANT_URL=http://localhost:6333
# QDRANT_API_KEY=your-key  # For Qdrant Cloud
```

### Neo4j (Docker)

```yaml
services:
  neo4j:
    image: neo4j:5
    ports:
      - "7474:7474"  # Browser
      - "7687:7687"  # Bolt
    environment:
      NEO4J_AUTH: neo4j/password
    volumes:
      - neo4j_data:/data
```

### Multi-Database Setup

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: cocoindex-postgres
    environment:
      POSTGRES_USER: cocoindex
      POSTGRES_PASSWORD: cocoindex
      POSTGRES_DB: cocoindex
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  qdrant:
    image: qdrant/qdrant:latest
    container_name: cocoindex-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  postgres_data:
  qdrant_data:
```

## Quick Start Workflow

```bash
# 1. Install
pip install -U cocoindex python-dotenv

# 2. Start Postgres (if needed)
docker compose -f <(curl -L https://raw.githubusercontent.com/cocoindex-io/cocoindex/refs/heads/main/dev/postgres.yaml) up -d

# 3. Create .env
echo 'COCOINDEX_DATABASE_URL=postgres://cocoindex:cocoindex@localhost/cocoindex' > .env

# 4. Write your flow in main.py

# 5. Run
cocoindex update --setup main
```

## Troubleshooting

### PostgreSQL Connection Refused

```bash
docker-compose ps              # Check if running
nc -zv localhost 5432          # Check port accessibility
```

### pgvector Extension Not Found

```bash
psql -U postgres -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';"
# Use pgvector/pgvector Docker image which includes the extension
```

### ModuleNotFoundError

```bash
pip install -e .               # Reinstall project dependencies
pip install cocoindex          # Ensure CocoIndex is installed
```

### Qdrant Connection Issues

```bash
curl http://localhost:6333/    # Check if Qdrant is running
docker logs cocoindex-qdrant   # Check Docker logs
```

## See Also

- **CocoIndex Docs**: <https://cocoindex.io/docs/getting_started/installation>
- **Docker Compose Config**: <https://github.com/cocoindex-io/cocoindex/blob/main/dev/postgres.yaml>
- **pgvector**: <https://github.com/pgvector/pgvector>
