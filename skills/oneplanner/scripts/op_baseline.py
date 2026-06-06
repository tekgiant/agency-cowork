"""
op_baseline — Save, list, and compare project baselines.

Usage:
    python -m scripts.op_baseline save [--name NAME]      # Save current snapshot as named baseline
    python -m scripts.op_baseline list                     # List available baselines
    python -m scripts.op_baseline compare [--baseline B]   # Compare current vs baseline
"""

import argparse
import json
import sys

from ._api import api_get, api_post, ensure_loaded, format_output, save_cache_raw, CACHE_DIR


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_save(args):
    """Save a baseline snapshot."""
    ensure_loaded()
    body = {}
    if args.name:
        body["name"] = args.name

    result = api_post("/baseline/save", body=body)
    if result:
        path = result.get("path", "")
        name = result.get("name", args.name or "baseline")
        print(f"Baseline saved: {name}")
        if path:
            print(f"  File: {path}")


def cmd_list(args):
    """List available baselines."""
    ensure_loaded()
    result = api_get("/baselines")
    if not result:
        print("No baselines found.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    baselines = result if isinstance(result, list) else result.get("files", result.get("baselines", []))
    if not baselines:
        print("No baselines found.")
        return

    headers = ["File", "Type", "Date", "Size"]
    rows = []
    for b in baselines:
        size_kb = b.get("sizeBytes", 0) // 1024
        rows.append([
            b.get("fileName", b.get("name", "?")),
            b.get("type", "?"),
            b.get("createdAt", b.get("date", "?"))[:19] if b.get("createdAt", b.get("date")) else "?",
            f"{size_kb} KB" if size_kb else str(b.get("taskCount", "?")),
        ])
    print(format_output(headers, rows, args.format))


def cmd_compare(args):
    """Compare current project state with a saved baseline."""
    ensure_loaded()
    body = {}
    if args.baseline:
        body["baseline"] = args.baseline

    result = api_post("/baseline/compare", body=body)
    if not result:
        print("No comparison data available. Save a baseline first.")
        return

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    summary = result.get("summary", {})
    print(f"\n=== Baseline Comparison ===")
    print(f"  Baseline: {result.get('baselineFile', '?')}")
    print(f"  Delayed:  {summary.get('delayed', 0)} tasks")
    print(f"  On Track: {summary.get('onTrackOrAhead', 0)} tasks")
    if summary.get("maxSlipDays"):
        print(f"  Max Slip: {summary['maxSlipDays']} days")

    # Show comparisons (schedule variances)
    comparisons = result.get("comparisons", [])
    if comparisons:
        # Filter to only tasks with actual variances
        delayed = [c for c in comparisons
                   if (c.get("startVarianceDays") or 0) != 0
                   or (c.get("finishVarianceDays") or 0) != 0]

        if delayed:
            print(f"\n--- Schedule Variances ---")
            headers = ["Task", "Start Variance", "Finish Variance", "% Done"]
            rows = []
            for c in delayed[:20]:
                rows.append([
                    c.get("taskName", "?"),
                    c.get("startVariance", ""),
                    c.get("finishVariance", ""),
                    str(c.get("percentComplete", "")),
                ])
            print(format_output(headers, rows, args.format))
            if len(delayed) > 20:
                print(f"  ... and {len(delayed) - 20} more")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.op_baseline",
        description="Save, list, and compare OnePlanner baselines.",
    )
    sub = parser.add_subparsers(dest="command")

    p_save = sub.add_parser("save", help="Save current state as baseline")
    p_save.add_argument("--name", help="Baseline name")

    p_list = sub.add_parser("list", help="List available baselines")
    p_list.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    p_comp = sub.add_parser("compare", help="Compare current vs baseline")
    p_comp.add_argument("--baseline", help="Baseline name to compare against")
    p_comp.add_argument("--format", choices=["table", "json", "markdown"], default="table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {"save": cmd_save, "list": cmd_list, "compare": cmd_compare}
    commands[args.command](args)


if __name__ == "__main__":
    main()
