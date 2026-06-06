#!/usr/bin/env python3
"""lz_analyze.py — Health analytics for Landing Zone data.

Usage:
    cd skills/landing-zone
    python -m scripts.lz_analyze --program my-program --report summary
    python -m scripts.lz_analyze --program my-program --report json
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "cache"


def load_cache(program: str) -> dict:
    """Load cached LZ data."""
    path = CACHE_DIR / f"{program}-lz.json"
    if not path.exists():
        print(f"ERROR: No cache for '{program}'. Run: python -m scripts.lz_sync --program {program}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_domain_items(cache: dict) -> dict[str, list[dict]]:
    """Group items by their parent domain."""
    items = cache.get("items", {})
    children_map = cache.get("tree", {}).get("children_map", {})

    # Build parent map
    parent_of: dict[int, int] = {}
    for pid_str, child_ids in children_map.items():
        for cid in child_ids:
            parent_of[cid] = int(pid_str)

    # Find domain-level items and their descendants
    domains: dict[str, list[dict]] = {}
    for item_id_str, item in items.items():
        item_id = int(item_id_str)
        # Walk up to find domain ancestor
        current = item_id
        domain_name = "(root)"
        while current in parent_of:
            parent = parent_of[current]
            parent_item = items.get(str(parent), {})
            if parent_item.get("type") == "Domain":
                domain_name = parent_item.get("title", f"Domain #{parent}")
            current = parent
        domains.setdefault(domain_name, []).append(item)

    return domains


def analyze(cache: dict) -> dict:
    """Run full health analysis."""
    items = list(cache.get("items", {}).values())
    stats = cache.get("stats", {})
    meta = cache.get("meta", {})
    domain_items = get_domain_items(cache)

    # State analysis
    state_dist = stats.get("by_state", {})

    # Grading progress by domain
    grading_by_domain = {}
    for domain, ditems in domain_items.items():
        reqs = [i for i in ditems if i.get("type") in ("Requirement", "Feature")]
        total = len(reqs)
        graded = sum(1 for i in reqs if i.get("state", "") in
                     ("Graded - POR Pending", "Closed POR", "Committed"))
        closed = sum(1 for i in reqs if i.get("state", "") in ("Closed", "Removed"))
        grading_by_domain[domain] = {
            "total": total,
            "graded": graded,
            "closed": closed,
            "active": total - graded - closed,
            "percent_graded": round(graded / total * 100) if total > 0 else 0,
        }

    # DRI workload
    dri_workload: dict[str, dict] = {}
    for item in items:
        dri = item.get("assigned_to", "Unassigned") or "Unassigned"
        if dri not in dri_workload:
            dri_workload[dri] = {"total": 0, "states": {}}
        dri_workload[dri]["total"] += 1
        s = item.get("state", "Unknown")
        dri_workload[dri]["states"][s] = dri_workload[dri]["states"].get(s, 0) + 1

    # At-risk items
    at_risk = [i for i in items if i.get("state", "").lower() == "at risk"]

    # Items in "Ready for Architecture Response" (awaiting grading)
    awaiting_grade = [i for i in items if i.get("state", "") == "Ready for Architecture Response"]

    return {
        "meta": meta,
        "state_distribution": state_dist,
        "grading_by_domain": grading_by_domain,
        "dri_workload": dict(sorted(dri_workload.items(), key=lambda x: -x[1]["total"])),
        "at_risk": at_risk,
        "awaiting_grade": awaiting_grade,
        "total_items": len(items),
    }


def format_summary(analysis: dict) -> str:
    """Generate markdown summary report."""
    meta = analysis["meta"]
    lines = [
        f"# {meta.get('program', '').replace('-', ' ').title()} — LZ Health Report",
        "",
        f"> **Generated:** {meta.get('timestamp', 'unknown')}",
        f"> **Total items:** {analysis['total_items']}",
        "",
        "## State Distribution",
        "",
        "| State | Count | Bar |",
        "|-------|------:|-----|",
    ]
    max_count = max(analysis["state_distribution"].values()) if analysis["state_distribution"] else 1
    for state, count in analysis["state_distribution"].items():
        bar_len = round(count / max_count * 20)
        bar = "#" * bar_len
        lines.append(f"| {state} | {count} | {bar} |")

    lines.extend(["", "## Grading Progress by Domain", "",
                   "| Domain | Total | Graded | Active | % Graded |",
                   "|--------|------:|-------:|-------:|---------:|"])
    for domain, data in sorted(analysis["grading_by_domain"].items(), key=lambda x: -x[1]["total"]):
        if data["total"] == 0:
            continue
        lines.append(
            f"| {domain[:40]} | {data['total']} | {data['graded']} | "
            f"{data['active']} | {data['percent_graded']}% |"
        )

    if analysis["at_risk"]:
        lines.extend(["", "## At-Risk Items", "",
                       "| ID | Title | DRI |",
                       "|---:|-------|-----|"])
        for item in analysis["at_risk"]:
            lines.append(f"| {item['id']} | {item.get('title', '')[:50]} | {item.get('assigned_to', '')} |")

    if analysis["awaiting_grade"]:
        lines.extend(["", f"## Awaiting Grading ({len(analysis['awaiting_grade'])} items)", "",
                       "| ID | Title | DRI |",
                       "|---:|-------|-----|"])
        for item in analysis["awaiting_grade"][:20]:
            lines.append(f"| {item['id']} | {item.get('title', '')[:50]} | {item.get('assigned_to', '')} |")
        if len(analysis["awaiting_grade"]) > 20:
            lines.append(f"\n*...and {len(analysis['awaiting_grade']) - 20} more*")

    lines.extend(["", "## Top DRIs by Workload", "",
                   "| DRI | Items |",
                   "|-----|------:|"])
    for dri, data in list(analysis["dri_workload"].items())[:15]:
        lines.append(f"| {dri} | {data['total']} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Landing Zone health analytics.")
    parser.add_argument("--program", "-p", required=True, help="Program name")
    parser.add_argument("--report", "-r", choices=["summary", "json"], default="summary",
                        help="Report format (default: summary)")
    args = parser.parse_args()

    cache = load_cache(args.program)
    analysis = analyze(cache)

    if args.report == "json":
        # Remove large lists for JSON output
        output = {k: v for k, v in analysis.items() if k not in ("at_risk", "awaiting_grade")}
        output["at_risk_count"] = len(analysis["at_risk"])
        output["awaiting_grade_count"] = len(analysis["awaiting_grade"])
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_summary(analysis))


if __name__ == "__main__":
    main()
