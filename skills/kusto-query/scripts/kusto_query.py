#!/usr/bin/env python3
"""
Kusto Query CLI — parse Kusto links, discover schema, execute KQL.

Usage:
    # List tables
    python3 kusto_query.py --link "https://dataexplorer.azure.com/clusters/mycluster.westus2/databases/MyDB" --action list-tables

    # Get table schema
    python3 kusto_query.py --link "..." --table "MyTable" --action schema

    # Run a KQL query
    python3 kusto_query.py --link "..." --action query --kql "MyTable | take 10"

    # Run query, output CSV
    python3 kusto_query.py --cluster "mycluster.westus2" --database "MyDB" --action query --kql "..." --format csv --output results.csv
"""

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

# Add scripts dir to path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))
from kusto_client import KustoClient, KustoAuthError, KustoQueryError


def parse_kusto_link(link: str) -> dict:
    """
    Parse various Kusto/ADX link formats into {cluster, database, table?}.

    Supported formats:
    - https://dataexplorer.azure.com/clusters/<cluster>/databases/<db>
    - https://<cluster>.kusto.windows.net/<db>
    - https://<cluster>.<region>.kusto.windows.net
    - Azure portal resource URLs (extract cluster name)
    - Plain cluster name: "mycluster" or "mycluster.westus2"
    """
    result = {"cluster": None, "database": None, "table": None}

    if not link:
        return result

    link = link.strip()

    # Format 1: Data Explorer web UI
    # https://dataexplorer.azure.com/clusters/mycluster.westus2/databases/MyDB
    m = re.match(r"https?://dataexplorer\.azure\.com/clusters/([^/]+)/databases/([^/?#]+)", link)
    if m:
        cluster_part = m.group(1)
        result["cluster"] = f"https://{cluster_part}.kusto.windows.net"
        result["database"] = m.group(2)
        # Check for table in fragment or query params
        table_m = re.search(r"[?&#]table=([^&#]+)", link)
        if table_m:
            result["table"] = table_m.group(1)
        return result

    # Format 2: Direct cluster URI
    # https://mycluster.westus2.kusto.windows.net/MyDB
    m = re.match(r"(https?://[^/]+\.kusto\.windows\.net)(?:/([^/?#]+))?", link)
    if m:
        result["cluster"] = m.group(1)
        if m.group(2):
            result["database"] = m.group(2)
        return result

    # Format 3: Azure portal resource URL
    # .../Microsoft.Kusto/clusters/mycluster...
    m = re.search(r"Microsoft\.Kusto/clusters/([^/?#]+)", link)
    if m:
        cluster_name = m.group(1)
        result["cluster"] = f"https://{cluster_name}.kusto.windows.net"
        return result

    # Format 4: Plain cluster name (e.g., "mycluster" or "mycluster.westus2")
    if not link.startswith("http"):
        result["cluster"] = f"https://{link}.kusto.windows.net"
        return result

    # Fallback: treat as cluster URI
    result["cluster"] = link if link.startswith("https://") else f"https://{link}"
    return result


def format_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2, default=str)


def format_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def format_table(rows: list[dict], max_col_width: int = 40) -> str:
    """Simple ASCII table for terminal output."""
    if not rows:
        return "(no results)"

    cols = list(rows[0].keys())
    # Compute column widths
    widths = {c: min(max(len(c), max(len(str(r.get(c, ""))[:max_col_width]) for r in rows)), max_col_width) for c in cols}

    # Header
    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    lines = [header, sep]

    # Rows
    for r in rows:
        line = " | ".join(str(r.get(c, ""))[:max_col_width].ljust(widths[c]) for c in cols)
        lines.append(line)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Kusto/ADX query CLI")
    parser.add_argument("--link", help="Kusto link (Data Explorer URL, cluster URI, or portal URL)")
    parser.add_argument("--cluster", help="Cluster URI (alternative to --link)")
    parser.add_argument("--database", help="Database name (alternative to or override from --link)")
    parser.add_argument("--table", help="Table name (for schema action)")
    parser.add_argument("--action", required=True, choices=["schema", "query", "list-tables"],
                        help="Action to perform")
    parser.add_argument("--kql", help="KQL query string (required for 'query' action)")
    parser.add_argument("--format", choices=["json", "csv", "table"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--output", help="Write output to file instead of stdout")
    parser.add_argument("--timeout", type=int, default=120, help="Query timeout in seconds")

    args = parser.parse_args()

    # Resolve cluster + database
    parsed = parse_kusto_link(args.link) if args.link else {"cluster": None, "database": None, "table": None}
    cluster = args.cluster or parsed["cluster"]
    database = args.database or parsed["database"]
    table = args.table or parsed["table"]

    if not cluster:
        print("ERROR: No cluster specified. Use --link or --cluster.", file=sys.stderr)
        sys.exit(1)

    if args.action != "list-tables" and not database:
        print("ERROR: No database specified. Use --link (with /databases/...) or --database.", file=sys.stderr)
        sys.exit(1)

    # For list-tables and schema, we need a database
    if args.action in ("list-tables", "schema") and not database:
        print("ERROR: --database is required for this action.", file=sys.stderr)
        sys.exit(1)

    try:
        client = KustoClient(cluster_uri=cluster, database=database or "")
    except Exception as e:
        print(f"ERROR: Failed to initialize client: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.action == "list-tables":
            tables = client.list_tables()
            output = json.dumps({"tables": tables}, indent=2)
            print(f"Found {len(tables)} table(s) in database '{database}':", file=sys.stderr)

        elif args.action == "schema":
            if not table:
                print("ERROR: --table is required for schema action.", file=sys.stderr)
                sys.exit(1)
            schema = client.get_schema(table)
            output = json.dumps({"table": table, "columns": schema}, indent=2)
            print(f"Schema for '{table}' ({len(schema)} columns):", file=sys.stderr)

        elif args.action == "query":
            if not args.kql:
                print("ERROR: --kql is required for query action.", file=sys.stderr)
                sys.exit(1)
            rows = client.execute(args.kql, timeout=args.timeout)
            print(f"Query returned {len(rows)} row(s).", file=sys.stderr)

            if args.format == "csv":
                output = format_csv(rows)
            elif args.format == "table":
                output = format_table(rows)
            else:
                output = format_json(rows)
        else:
            print(f"ERROR: Unknown action '{args.action}'", file=sys.stderr)
            sys.exit(1)

    except KustoAuthError as e:
        print(f"AUTH ERROR: {e}", file=sys.stderr)
        print("\nTroubleshooting:", file=sys.stderr)
        print("  1. Run 'az login' to authenticate", file=sys.stderr)
        print("  2. Verify you have access to the cluster: 'az account show'", file=sys.stderr)
        print(f"  3. Check cluster URI: {cluster}", file=sys.stderr)
        sys.exit(2)
    except KustoQueryError as e:
        print(f"QUERY ERROR: {e}", file=sys.stderr)
        sys.exit(3)

    # Output
    if args.output:
        Path(args.output).write_text(output)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
