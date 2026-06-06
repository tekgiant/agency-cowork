#!/usr/bin/env python3
"""lz_sync.py — Fetch ADO Landing Zone saved query and cache locally.

Usage:
    cd skills/landing-zone
    python -m scripts.lz_sync --program my-program
    python -m scripts.lz_sync --program my-program --snapshot
    python -m scripts.lz_sync --org MyOrg --project MyProject --query-id <GUID>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "cache"
PROJECT_ROOT = SKILL_ROOT.parent.parent

# Import shared ADO helpers from ado_common
sys.path.insert(0, str(SKILL_ROOT.parent))
from ado_common.client import get_token, ado_get, batch_fetch, parse_item
from ado_common.constants import API_VERSION

PROGRAM_QUERIES = {}

def load_programs() -> dict:
    """Load program configs from programs.json. Returns dict keyed by program slug."""
    global PROGRAM_QUERIES
    config_path = SKILL_ROOT / "programs.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            PROGRAM_QUERIES = json.load(f)
    return PROGRAM_QUERIES


def run_query(org: str, project: str, query_id: str, token: str) -> dict:
    """Execute an ADO saved query."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/wit/wiql/{query_id}?api-version={API_VERSION}"
    return ado_get(url, token)


def build_tree(relations: list[dict], items_by_id: dict) -> dict:
    """Build parent→children tree from ADO work item relations."""
    children: dict[int, list[int]] = {}
    roots: list[int] = []

    for rel in relations:
        source = rel.get("source")
        target = rel.get("target")
        if not target:
            continue
        tid = target["id"]
        if source:
            sid = source["id"]
            children.setdefault(sid, []).append(tid)
        else:
            roots.append(tid)

    def build_node(item_id: int, depth: int = 0) -> dict | None:
        item = items_by_id.get(item_id)
        if not item:
            return None
        node = dict(item)
        node["depth"] = depth
        node["children"] = []
        for cid in children.get(item_id, []):
            child = build_node(cid, depth + 1)
            if child:
                node["children"].append(child)
        return node

    tree = []
    for rid in roots:
        node = build_node(rid)
        if node:
            tree.append(node)
    return {"roots": tree, "children_map": {str(k): v for k, v in children.items()}}


def compute_stats(items: list[dict]) -> dict:
    """Compute aggregate statistics."""
    states: dict[str, int] = {}
    types: dict[str, int] = {}
    dris: dict[str, int] = {}
    for item in items:
        s = item.get("state", "Unknown")
        states[s] = states.get(s, 0) + 1
        t = item.get("type", "Unknown")
        types[t] = types.get(t, 0) + 1
        d = item.get("assigned_to", "Unassigned") or "Unassigned"
        dris[d] = dris.get(d, 0) + 1
    return {
        "total": len(items),
        "by_state": dict(sorted(states.items(), key=lambda x: -x[1])),
        "by_type": dict(sorted(types.items(), key=lambda x: -x[1])),
        "by_dri": dict(sorted(dris.items(), key=lambda x: -x[1])),
    }


def save_cache(program: str, data: dict) -> Path:
    """Save structured JSON cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{program}-lz.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def generate_markdown(program: str, tree_data: dict, stats: dict, meta: dict) -> Path:
    """Generate markdown snapshot for knowledgebase."""
    lines = [
        f"# {program.replace('-', ' ').title()} Landing Zone Requirements",
        "",
        f"> **Source:** [ADO Query]({meta['query_url']})",
        f"> **Cached:** {meta['timestamp']}",
        f"> **Total items:** {stats['total']}",
        "",
        "## Summary",
        "",
        "| State | Count |",
        "|-------|-------|",
    ]
    for state, count in stats["by_state"].items():
        lines.append(f"| {state} | {count} |")
    lines.append("")

    def render_node(node: dict, depth: int = 0):
        indent = "  " * depth
        state = node.get("state", "")
        icon = "[x]" if state in ("Closed", "Closed POR", "Resolved") else "[ ]" if state in ("New", "Active") else "[-]"
        dri = f" *({node['assigned_to']})*" if node.get("assigned_to") else ""
        lines.append(f"{indent}- {icon} **{node['id']}** [{node['type']}] {node['title']}{dri} -- *{state}*")
        for child in node.get("children", []):
            render_node(child, depth + 1)

    lines.extend(["## Requirements Tree", ""])
    for root in tree_data.get("roots", []):
        render_node(root)
        lines.append("")

    # Save to knowledgebase
    kb_dir = PROJECT_ROOT / "memory" / "Knowledgebase" / "Workstreams"
    kb_dir.mkdir(parents=True, exist_ok=True)
    md_path = kb_dir / f"{program}-landing-zone-requirements.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def sync(org: str, project: str, query_id: str, program: str, snapshot: bool = False) -> dict:
    """Main sync workflow."""
    print(f"Syncing {program} Landing Zone from {org}/{project}...")
    print(f"  Query ID: {query_id}")

    token = get_token()

    # Execute query
    print("  Running saved query...")
    result = run_query(org, project, query_id, token)
    relations = result.get("workItemRelations", [])
    print(f"  Found {len(relations)} relations")

    # Collect unique IDs
    all_ids = set()
    for rel in relations:
        if rel.get("source"):
            all_ids.add(rel["source"]["id"])
        if rel.get("target"):
            all_ids.add(rel["target"]["id"])
    unique_ids = sorted(all_ids)
    print(f"  {len(unique_ids)} unique work items")

    # Batch fetch
    raw_items = batch_fetch(org, project, unique_ids, token)
    items = [parse_item(wi) for wi in raw_items]
    items_by_id = {item["id"]: item for item in items}

    # Build tree
    tree_data = build_tree(relations, items_by_id)

    # Compute stats
    stats = compute_stats(items)
    print(f"  Stats: {stats['total']} items across {len(stats['by_state'])} states")

    # Metadata
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    query_url = f"https://dev.azure.com/{org}/{project}/_queries/query/{query_id}/"
    meta = {
        "program": program,
        "org": org,
        "project": project,
        "query_id": query_id,
        "query_url": query_url,
        "timestamp": timestamp,
        "item_count": len(items),
        "relation_count": len(relations),
    }

    # Build cache data
    cache_data = {
        "meta": meta,
        "stats": stats,
        "items": items_by_id,
        "tree": tree_data,
    }

    # Save
    cache_path = save_cache(program, cache_data)
    print(f"  Cache saved: {cache_path}")

    md_path = generate_markdown(program, tree_data, stats, meta)
    print(f"  Markdown saved: {md_path}")

    if snapshot:
        snap_dir = CACHE_DIR / "snapshots" / program
        snap_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap_path = snap_dir / f"{date_str}.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"  Snapshot saved: {snap_path}")

    print(f"\nSync complete: {stats['total']} items cached for {program}")
    return cache_data


def main():
    load_programs()
    parser = argparse.ArgumentParser(description="Sync ADO Landing Zone to local cache.")
    if PROGRAM_QUERIES:
        parser.add_argument("--program", "-p", choices=list(PROGRAM_QUERIES.keys()),
                            help="Program shortcut (resolves to known query ID)")
    else:
        parser.add_argument("--program", "-p",
                            help="Program shortcut (configure in programs.json)")
    parser.add_argument("--org", help="ADO organization")
    parser.add_argument("--project", help="ADO project")
    parser.add_argument("--query-id", help="ADO saved query GUID")
    parser.add_argument("--snapshot", "-s", action="store_true",
                        help="Also create a timestamped snapshot")
    args = parser.parse_args()

    if args.program:
        if args.program not in PROGRAM_QUERIES:
            parser.error(f"Unknown program '{args.program}'. Configure it in programs.json or use --org/--project/--query-id.")
        cfg = PROGRAM_QUERIES[args.program]
        org = args.org or cfg["org"]
        project = args.project or cfg["project"]
        query_id = args.query_id or cfg["query_id"]
        program = args.program
    elif args.org and args.project and args.query_id:
        org, project, query_id = args.org, args.project, args.query_id
        program = args.org.lower()
    else:
        parser.error("Provide --program or --org/--project/--query-id")

    sync(org, project, query_id, program, args.snapshot)


if __name__ == "__main__":
    main()
