#!/usr/bin/env python3
"""
hybrid-search.py — Hybrid search combining QMD BM25 + vector similarity.

Uses Reciprocal Rank Fusion (RRF) to merge results from:
  1. QMD BM25 keyword search (via CLI)
  2. Cosine similarity against cached embeddings (SentenceTransformer, local GGUF, or Azure OpenAI)

Usage:
    python hybrid-search.py "query text"
    python hybrid-search.py "query" -c knowledgebase -n 10
    python hybrid-search.py "query" --json
    python hybrid-search.py "query" --bm25-only
    python hybrid-search.py "query" --vector-only
    python hybrid-search.py "query" --provider local

Configuration:
    - agentconfig.json: provider (sentence_transformer, local, or azure_openai), model path / endpoint
    - .env: AZURE_OPENAI_API_KEY (only for Azure provider)
    - Cached embeddings in skills/qmd-memory/cache/embeddings/
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

# --- Paths ---

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_ROOT.parent.parent
AGENT_CONFIG = PROJECT_ROOT / "agentconfig.json"
ENV_FILE = PROJECT_ROOT / ".env"
EMBEDDINGS_DIR = SKILL_ROOT / "cache" / "embeddings"

# RRF constant (standard value from the literature)
RRF_K = 60


# --- BM25 Search via QMD CLI ---

def bm25_search(query: str, collection: str | None, n: int) -> list[dict]:
    """Run QMD BM25 keyword search via CLI."""
    cmd = ["qmd", "search", query, "-n", str(n), "--json"]
    if collection:
        cmd.extend(["-c", collection])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            shell=True  # needed for Windows cmd wrapper
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout) if result.stdout.strip() else []
        # Normalize to [{path, score, snippet}]
        results = []
        for item in data:
            # QMD JSON 'file' is a qmd:// URI like qmd://skills-docs/weekly-report/...
            raw_path = item.get("file", item.get("path", item.get("docid", "")))
            # Parse collection name and relative path from URI
            m = re.match(r"^qmd://([^/]+)/(.+)$", raw_path)
            if m:
                col_name, rel = m.group(1), m.group(2)
                # Map collection name to filesystem base path
                col_bases = {
                    "memory-root": "memory",
                    "knowledgebase": "memory/Knowledgebase",
                    "weekly-reports": "memory/WeeklyReports",
                    "skills-docs": "skills",
                }
                base = col_bases.get(col_name, "")
                path = f"{base}/{rel}" if base else rel
            else:
                path = raw_path
            results.append({
                "path": path,
                "score": item.get("score", 0),
                "snippet": item.get("snippet", item.get("content", "")),
                "collection": item.get("collection", ""),
                "title": item.get("title", ""),
                "source": "bm25",
            })
        return results
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


# --- Vector Search via Azure OpenAI embeddings ---

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_cached_embeddings(collection: str | None) -> list[dict]:
    """Load pre-computed Azure OpenAI embeddings from cache."""
    if not EMBEDDINGS_DIR.exists():
        return []

    docs = []
    for f in EMBEDDINGS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if collection and data.get("collection") != collection:
                continue
            for chunk in data.get("chunks", []):
                docs.append({
                    "path": data.get("path", ""),
                    "collection": data.get("collection", ""),
                    "text": chunk.get("text", ""),
                    "embedding": chunk.get("embedding", []),
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return docs


def vector_search(query: str, collection: str | None, n: int,
                   force_provider: str | None = None) -> list[dict]:
    """Search cached embeddings using query embedding + cosine similarity."""
    from embed_provider import get_provider

    try:
        provider = get_provider(force_provider)
    except Exception as e:
        print(f"  WARNING: Embedding provider failed: {e}", file=sys.stderr)
        return []

    # Generate query embedding
    try:
        query_embeddings = provider.embed([query])
        query_embedding = query_embeddings[0]
    except Exception as e:
        print(f"  WARNING: Embedding failed: {e}", file=sys.stderr)
        provider.close()
        return []

    # Load cached doc embeddings
    cached = load_cached_embeddings(collection)
    if not cached:
        provider.close()
        return []

    # Compute similarities
    scored = []
    for doc in cached:
        if not doc["embedding"]:
            continue
        # Handle dimension mismatch (e.g. old Azure 3072-d cache vs new local 384-d)
        if len(query_embedding) != len(doc["embedding"]):
            continue
        sim = cosine_similarity(query_embedding, doc["embedding"])
        scored.append({
            "path": doc["path"],
            "score": sim,
            "snippet": doc["text"][:500],
            "collection": doc["collection"],
            "source": "vector",
        })

    provider.close()

    # Sort by similarity, return top n
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]

def normalize_path(p: str) -> str:
    """Normalize path for deduplication: forward slashes, lowercase, collapse hyphens/spaces."""
    # Use pathlib to handle OS-specific separators, then normalize
    p = str(Path(p)).replace(os.sep, "/").lower().strip("/")
    # QMD converts spaces to hyphens in URIs — normalize both to spaces for matching
    p = p.replace("-", " ")
    return p


# --- Reciprocal Rank Fusion ---

def reciprocal_rank_fusion(result_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Merge multiple ranked result lists using RRF.

    RRF score = sum(1 / (k + rank_i)) for each list where the doc appears.
    This naturally handles different score scales between BM25 and cosine similarity.
    """
    # Accumulate RRF scores by normalized path
    doc_scores: dict[str, float] = {}
    doc_data: dict[str, dict] = {}

    for results in result_lists:
        for rank, result in enumerate(results):
            key = normalize_path(result["path"])
            rrf_score = 1.0 / (k + rank + 1)  # rank is 0-indexed
            doc_scores[key] = doc_scores.get(key, 0.0) + rrf_score

            # Keep the best metadata for each doc
            if key not in doc_data or result["score"] > doc_data[key].get("original_score", 0):
                existing_sources = doc_data[key]["sources"] if key in doc_data else []
                doc_data[key] = {
                    "path": result["path"],
                    "collection": result.get("collection", ""),
                    "snippet": result.get("snippet", ""),
                    "sources": existing_sources,
                    "original_score": result["score"],
                }

            # Track which search methods found this doc
            source = result.get("source", "unknown")
            if source not in doc_data[key].get("sources", []):
                doc_data[key].setdefault("sources", []).append(source)

    # Build final ranked list
    merged = []
    for key, rrf_score in sorted(doc_scores.items(), key=lambda x: x[1], reverse=True):
        entry = doc_data[key]
        entry["rrf_score"] = rrf_score
        entry["found_by"] = "+".join(entry.pop("sources", []))
        entry.pop("original_score", None)
        merged.append(entry)

    return merged


# --- Output formatting ---

def format_results(results: list[dict], output_format: str, n: int) -> str:
    """Format merged results for output."""
    results = results[:n]

    if output_format == "json":
        return json.dumps(results, indent=2, ensure_ascii=False)

    if output_format == "md":
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r['path']}")
            lines.append(f"**Collection:** {r['collection']} | **Found by:** {r['found_by']} | **RRF:** {r['rrf_score']:.4f}")
            lines.append("")
            snippet = r.get("snippet", "").strip()
            if snippet:
                # Truncate long snippets
                if len(snippet) > 500:
                    snippet = snippet[:500] + "..."
                lines.append(snippet)
            lines.append("")
        return "\n".join(lines)

    # Default: compact text
    lines = []
    for i, r in enumerate(results, 1):
        found = r["found_by"]
        rrf = r["rrf_score"]
        snippet = r.get("snippet", "").strip().replace("\n", " ")[:200]
        lines.append(f"{i}. [{found}] {r['path']}  (RRF: {rrf:.4f})")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid search: QMD BM25 + vector similarity with RRF merging."
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("-c", "--collection", help="Filter to a specific collection")
    parser.add_argument("-n", "--num-results", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--md", action="store_true", help="Markdown output")
    parser.add_argument("--bm25-only", action="store_true", help="Only run BM25 keyword search")
    parser.add_argument("--vector-only", action="store_true", help="Only run vector search")
    parser.add_argument("--provider", "-p", choices=["local", "sentence_transformer", "azure_openai"],
                        help="Override embedding provider from agentconfig.json")
    parser.add_argument("--rrf-k", type=int, default=RRF_K, help=f"RRF constant (default: {RRF_K})")

    args = parser.parse_args()

    output_format = "json" if args.json else "md" if args.md else "text"
    candidate_n = args.num_results * 3  # fetch more candidates for RRF

    result_lists = []

    # BM25 search
    if not args.vector_only:
        if output_format == "text":
            print(f"[BM25] Searching: {args.query}", file=sys.stderr)
        bm25_results = bm25_search(args.query, args.collection, candidate_n)
        if bm25_results:
            result_lists.append(bm25_results)
            if output_format == "text":
                print(f"[BM25] Found {len(bm25_results)} results", file=sys.stderr)
        else:
            if output_format == "text":
                print("[BM25] No results", file=sys.stderr)

    # Vector search
    if not args.bm25_only:
        if output_format == "text":
            print(f"[Vector] Searching: {args.query}", file=sys.stderr)
        vec_results = vector_search(args.query, args.collection, candidate_n, args.provider)
        if vec_results:
            result_lists.append(vec_results)
            if output_format == "text":
                print(f"[Vector] Found {len(vec_results)} results", file=sys.stderr)
        else:
            if output_format == "text":
                print("[Vector] No results", file=sys.stderr)

    if not result_lists:
        print("No results found.", file=sys.stderr)
        sys.exit(0)

    # Merge with RRF (or just return the single list if only one source)
    if len(result_lists) == 1:
        merged = result_lists[0]
        for r in merged:
            r["rrf_score"] = r.get("score", 0)
            r["found_by"] = r.get("source", "unknown")
    else:
        merged = reciprocal_rank_fusion(result_lists, k=args.rrf_k)

    if output_format == "text":
        print("", file=sys.stderr)

    print(format_results(merged, output_format, args.num_results))


if __name__ == "__main__":
    main()
