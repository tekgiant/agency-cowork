#!/usr/bin/env python3
"""
azure-embed.py — Generate embeddings for QMD memory collections.

Supports local GGUF, SentenceTransformer (default), and Azure OpenAI, controlled by
``agentconfig.json`` → ``memory.embedding.provider``.

Usage:
    python azure-embed.py                    # Embed all collections
    python azure-embed.py --collection knowledgebase  # Embed one collection
    python azure-embed.py --status           # Show embedding status
    python azure-embed.py --test             # Test embedding connectivity
    python azure-embed.py --provider sentence_transformer  # Force SentenceTransformer (default)
    python azure-embed.py --provider local   # Force local GGUF
    python azure-embed.py --provider azure_openai  # Force Azure OpenAI

Configuration:
    - agentconfig.json (project root): provider, model path / Azure endpoint
    - .env (project root): AZURE_OPENAI_API_KEY (only for Azure provider)

Requires:
    - Local:  llama-cpp-python
    - Azure:  openai, python-dotenv, tiktoken
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

# --- Paths ---

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_ROOT.parent.parent
AGENT_CONFIG = PROJECT_ROOT / "agentconfig.json"
ENV_FILE = PROJECT_ROOT / ".env"
EMBEDDINGS_DIR = SKILL_ROOT / "cache" / "embeddings"


def load_config() -> dict:
    """Load embedding config from agentconfig.json."""
    if not AGENT_CONFIG.exists():
        print(f"ERROR: {AGENT_CONFIG} not found.", file=sys.stderr)
        sys.exit(1)

    with open(AGENT_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config.get("memory", {}).get("embedding", {})


def get_collection_docs(collection: str | None) -> list[dict]:
    """Get documents from QMD collections via CLI, with filesystem fallback."""
    try:
        cmd = ["qmd", "status", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print("  WARNING: qmd status failed, using filesystem fallback.", file=sys.stderr)
            return get_docs_from_filesystem(collection)

        # Use qmd to list documents in the collection
        list_cmd = ["qmd", "list"]
        if collection:
            list_cmd.extend(["-c", collection])
        list_cmd.append("--json")

        result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return get_docs_from_filesystem(collection)
        return json.loads(result.stdout) if result.stdout.strip() else []
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        print("  QMD CLI not available, using filesystem fallback.", file=sys.stderr)
        return get_docs_from_filesystem(collection)


COLLECTION_PATHS = {
    "memory-root": ("memory", "*.md"),
    "knowledgebase": ("memory/Knowledgebase", "**/*.md"),
    "weekly-reports": ("memory/WeeklyReports", "**/*.md"),
    "skills-docs": ("skills", "**/SKILL.md"),
}


def get_docs_from_filesystem(collection: str | None) -> list[dict]:
    """Fallback: read documents directly from filesystem."""
    docs = []
    collections = {collection: COLLECTION_PATHS[collection]} if collection and collection in COLLECTION_PATHS else COLLECTION_PATHS

    for col_name, (rel_path, glob_pattern) in collections.items():
        base = PROJECT_ROOT / rel_path
        if not base.exists():
            continue
        for filepath in base.glob(glob_pattern):
            if filepath.is_file():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    docs.append({
                        "collection": col_name,
                        "path": str(filepath.relative_to(PROJECT_ROOT)),
                        "content": content,
                    })
                except Exception as e:
                    print(f"  WARNING: Could not read {filepath}: {e}", file=sys.stderr)
    return docs


def _get_tokenizer():
    """Get tiktoken encoder for text-embedding-3-large (cl100k_base)."""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None


def chunk_text(text: str, max_tokens: int = 8000, overlap: int = 200) -> list[str]:
    """Split text into chunks suitable for embedding.

    Uses tiktoken (cl100k_base) for accurate token counting.
    Falls back to a conservative word-based estimate if tiktoken is unavailable.
    """
    enc = _get_tokenizer()

    if enc is not None:
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return [text]

        chunks = []
        start = 0
        while start < len(tokens):
            end = min(start + max_tokens, len(tokens))
            chunk = enc.decode(tokens[start:end])
            chunks.append(chunk)
            start = end - overlap
            if start >= len(tokens) - overlap:
                break
        return chunks

    # Fallback: conservative word-based approximation (~1.3 tokens per word)
    max_words = int(max_tokens / 1.3)
    overlap_words = int(overlap / 1.3)
    words = text.split()

    if len(words) <= max_words:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap_words
        if start >= len(words) - overlap_words:
            break

    return chunks


def generate_embeddings(provider, texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts using the configured provider."""
    all_embeddings = []
    batch_size = 16

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embeddings = provider.embed(batch)
        all_embeddings.extend(embeddings)

        if len(texts) > batch_size:
            done = min(i + batch_size, len(texts))
            print(f"    Embedded {done}/{len(texts)} chunks...")

    return all_embeddings


def save_embeddings(collection: str, doc_path: str, chunks: list[str],
                    embeddings: list[list[float]], model_name: str) -> None:
    """Save embeddings to the local cache."""
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # Create a safe filename from the doc path
    safe_name = doc_path.replace("/", "__").replace("\\", "__").replace(".md", "")
    output_file = EMBEDDINGS_DIR / f"{safe_name}.json"

    data = {
        "collection": collection,
        "path": doc_path,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "chunks": [
            {
                "text": chunk,
                "embedding": emb,
            }
            for chunk, emb in zip(chunks, embeddings)
        ],
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def cmd_embed(collection: str | None, force_provider: str | None = None) -> None:
    """Generate embeddings for QMD documents using the configured provider."""
    from embed_provider import get_provider

    try:
        provider = get_provider(force_provider)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Embedding Provider: {provider.name}")
    print(f"  Dimensions: {provider.dimensions}")
    if collection:
        print(f"  Collection: {collection}")
    print()

    docs = get_collection_docs(collection)
    if not docs:
        print("No documents found to embed.")
        return

    print(f"Found {len(docs)} documents to embed.")
    total_chunks = 0
    total_embedded = 0

    for doc in docs:
        path = doc.get("path", "unknown")
        content = doc.get("content", "")
        col = doc.get("collection", "unknown")

        if not content.strip():
            continue

        chunks = chunk_text(content)
        total_chunks += len(chunks)

        print(f"  [{col}] {path} ({len(chunks)} chunk{'s' if len(chunks) != 1 else ''})")

        try:
            embeddings = generate_embeddings(provider, chunks)
            save_embeddings(col, path, chunks, embeddings, provider.name)
            total_embedded += len(chunks)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)

    provider.close()
    print(f"\nDone. Embedded {total_embedded}/{total_chunks} chunks from {len(docs)} documents.")
    print(f"Embeddings saved to: {EMBEDDINGS_DIR}")


def cmd_status() -> None:
    """Show embedding status."""
    if not EMBEDDINGS_DIR.exists():
        print("No embeddings found.")
        print("Run: python azure-embed.py")
        return

    files = list(EMBEDDINGS_DIR.glob("*.json"))
    if not files:
        print("No embeddings found.")
        return

    print(f"Embeddings ({len(files)} documents)")
    print("=" * 60)

    total_chunks = 0
    models_seen = set()
    for f in sorted(files):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            n_chunks = len(data.get("chunks", []))
            total_chunks += n_chunks
            generated = data.get("generated_at", "unknown")
            col = data.get("collection", "?")
            path = data.get("path", f.stem)
            model = data.get("model", "unknown")
            models_seen.add(model)
            print(f"  [{col}] {path} — {n_chunks} chunks ({model}, {generated})")
        except Exception:
            print(f"  {f.name} — error reading")

    print(f"\nTotal: {total_chunks} chunks across {len(files)} documents")
    print(f"Models: {', '.join(sorted(models_seen))}")


def cmd_test(force_provider: str | None = None) -> None:
    """Test embedding provider connectivity."""
    from embed_provider import get_provider

    try:
        provider = get_provider(force_provider)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Testing Embedding Provider: {provider.name}")
    print(f"  Dimensions: {provider.dimensions}")
    print()

    test_inputs = ["Hello world", "project alpha release readiness", "Embedding test"]

    try:
        import time
        t0 = time.perf_counter()
        embeddings = provider.embed(test_inputs)
        elapsed = time.perf_counter() - t0

        print(f"SUCCESS — Generated {len(embeddings)} embeddings in {elapsed*1000:.0f}ms")
        for i, emb in enumerate(embeddings):
            dim = len(emb)
            preview = f"[{emb[0]:.6f}, {emb[1]:.6f}, ..., {emb[-1]:.6f}]"
            print(f"  [{i}]: dim={dim}  {preview}")

        print(f"\n  Throughput: {len(test_inputs)/elapsed:.0f} texts/sec")
        provider.close()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate embeddings for QMD memory collections (local GGUF or Azure OpenAI)."
    )
    parser.add_argument(
        "--collection", "-c",
        choices=["memory-root", "knowledgebase", "weekly-reports", "skills-docs"],
        help="Embed only a specific collection (default: all)",
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["local", "sentence_transformer", "azure_openai"],
        help="Override the embedding provider from agentconfig.json",
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show embedding status",
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Test embedding provider connectivity",
    )

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.test:
        cmd_test(args.provider)
    else:
        cmd_embed(args.collection, args.provider)


if __name__ == "__main__":
    main()
