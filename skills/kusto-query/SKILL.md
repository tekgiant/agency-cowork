# Kusto / Azure Data Explorer Query Skill

> Query Azure Data Explorer (Kusto) tables using natural language. The user provides a Kusto link or cluster/database/table details, asks a data question, and the agent generates and executes KQL.

## Prerequisites

- **Azure CLI** authenticated (`az login` completed)
- **Python 3.9+** with `requests` (stdlib-compatible; no extra pip packages)
- User must have at least **Reader** access on the target ADX cluster/database

## Quick Start

```bash
# 1. Parse a Kusto link and discover schema
python3 skills/kusto-query/scripts/kusto_query.py \
  --link "https://dataexplorer.azure.com/clusters/mycluster.westus2/databases/MyDB" \
  --table "MyTable" \
  --action schema

# 2. Run a KQL query
python3 skills/kusto-query/scripts/kusto_query.py \
  --link "https://dataexplorer.azure.com/clusters/mycluster.westus2/databases/MyDB" \
  --table "MyTable" \
  --action query \
  --kql "MyTable | summarize count() by bin(Timestamp, 1h) | order by Timestamp desc | take 24"

# 3. Run a query and output CSV
python3 skills/kusto-query/scripts/kusto_query.py \
  --cluster "mycluster.westus2" \
  --database "MyDB" \
  --action query \
  --kql "MyTable | take 10" \
  --format csv
```

## Workflow — How the Agent Should Use This Skill

### Step 1: Parse the User's Kusto Link

Users will paste links in various formats. Extract cluster, database, and optionally table:

| Link Format | Example |
|---|---|
| Data Explorer web | `https://dataexplorer.azure.com/clusters/mycluster.westus2/databases/MyDB` |
| Cluster URI | `https://mycluster.westus2.kusto.windows.net` |
| Azure portal ADX | `https://portal.azure.com/#@.../resource/subscriptions/.../providers/Microsoft.Kusto/clusters/mycluster` |

The script's `--link` flag handles all these formats automatically.

### Step 2: Discover Schema

**Always run schema discovery first** before writing any KQL. This gives you column names and types:

```bash
python3 skills/kusto-query/scripts/kusto_query.py \
  --link "<pasted_link>" \
  --table "<table_name>" \
  --action schema
```

Output is JSON with column names, types, and a sample of table names if `--table` is omitted.

If the user didn't specify a table, first list tables:
```bash
python3 skills/kusto-query/scripts/kusto_query.py \
  --link "<pasted_link>" \
  --action list-tables
```

### Step 3: Generate KQL

Using the schema from Step 2 and the user's natural language question, write KQL. Follow these guidelines:

- **Always include a time filter** if a `Timestamp`/`datetime` column exists (default: last 7 days)
- **Use `take` or `limit`** for exploratory queries (default: 100 rows)
- **Use `summarize`** for aggregation questions ("how many", "average", "trend")
- **Use `project`** to select only relevant columns (don't return 50-column rows)
- **Use `render`** hints if the user wants a chart (e.g., `| render timechart`)

### Step 4: Execute and Analyze

```bash
python3 skills/kusto-query/scripts/kusto_query.py \
  --link "<pasted_link>" \
  --table "<table>" \
  --action query \
  --kql "<generated_kql>" \
  --format json
```

- For small results (< 50 rows): analyze inline, present as formatted table or summary
- For large results: save to CSV (`--format csv --output results.csv`), then analyze

### Step 5: Iterate

If the query returns unexpected results or errors:
1. Check the error message (common: column name typos, type mismatches)
2. Re-examine schema
3. Adjust KQL and re-run

## Performance — Speed Optimization Guidelines

**Goal:** Minimize turn count and total execution time without sacrificing output quality.

### Query Strategy (cut iteration cycles)

1. **Pre-filter in the first query.** Don't run a broad query then refine — include ALL known exclusions upfront. For Chaos Studio data, always exclude synthetics (`!endswith "-SYNTHETICS-CP"`), E2E tests, and known 1P internal patterns in the FIRST query.
2. **Batch lookups into a single query.** Don't resolve customer names one-by-one. Use `summarize make_set()` or `join` to get all enrichment data in one KQL call.
3. **Use `let` statements for complex queries.** Combine multiple analysis steps into a single KQL execution using `let` bindings, reducing round-trips:
   ```kql
   let raw = experimentstart | where EventInfo_Time >= ago(30d) | where ExperimentName !endswith "-SYNTHETICS-CP" | ...;
   let topN = raw | summarize count() by AccountId | top 10 by count_;
   let enriched = topN | join kind=inner (raw | summarize ... by AccountId) on AccountId;
   enriched | project-away AccountId1
   ```
4. **Target ≤ 3 query round-trips total:** (1) schema discovery, (2) main analytical query with all filters, (3) optional enrichment/drill-down. If you need more, combine steps.

### Follow-up Questions (CRITICAL — avoid runaway iterations)

When the user asks a follow-up after the initial report (e.g., "now show me only 3P customers" or "who are the top customers by name?"):

1. **DO NOT write long Python scripts for entity resolution.** Never write 50+ line scripts that make N serial HTTP calls to resolve tenant IDs, subscription names, or customer identities one-by-one. This takes 20+ minutes and is the #1 cause of slow follow-ups.
2. **Prefer KQL-side enrichment.** If the data source has a mapping table (e.g., `subscriptioninfo`, `tenantmapping`), join against it in KQL. One query, all results.
3. **If external resolution is needed, batch it.** Write a SHORT Python script (< 30 lines) that:
   - Takes ALL IDs as input (not one-by-one)
   - Uses `asyncio.gather()` or `concurrent.futures.ThreadPoolExecutor` for parallel HTTP calls
   - Has a hard timeout of 30 seconds total (not per-call)
   - Falls back to showing raw IDs if resolution fails
4. **For Azure subscription → tenant → company resolution specifically:**
   - Use `az graph query` to batch-resolve subscriptions if available
   - Or query the ARM `subscriptions` API once to get all sub metadata in one call
   - NEVER call Graph/ARM per-subscription in a serial loop
5. **Cap follow-up to 2 additional tool calls max.** If you can't answer the follow-up in 2 tool calls (1 query + 1 report generation), simplify the approach — show raw IDs with a note that names couldn't be resolved quickly.
6. **Reuse data from the previous query.** If the initial query returned subscription/tenant IDs, filter and re-aggregate in Python from the saved JSON — don't re-query Kusto.

### Report Generation (cut generation time)

1. **Use a single-pass HTML template.** Don't build the report section-by-section across many tool calls. Write the COMPLETE HTML file in ONE `Write` tool call with all data, charts, and styling inline.
2. **Embed data as JSON in a `<script>` block** at the top of the HTML, then reference it from Chart.js configs and table renderers. This avoids duplicating data across HTML elements.
3. **Use Chart.js from CDN** (`https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js`) for all visualization.
4. **Standard dashboard layout:**
   - Header: title + filter badges + date range
   - Stats grid: 3-4 KPI cards
   - Charts: horizontal bar (primary ranking), bubble/scatter (correlation), doughnut (distribution)
   - Data table: sortable, with rank, name, key metrics, volume bar
   - Methodology/caveats section
   - Footer: data source, query timestamp
5. **Dark theme CSS variables** (matches the user's environment):
   ```css
   :root { --bg:#0d1117; --surface:#161b22; --border:#30363d; --text:#e6edf3;
           --muted:#8b949e; --accent:#58a6ff; --green:#3fb950; --orange:#d29922; --red:#f85149; }
   ```
6. **Always save to `output/` folder** with a descriptive filename.

### HTML Rendering Notes

- Use `grid-template-columns: 1fr 1fr` for chart rows, with `@media(max-width:900px)` fallback to `1fr`
- Set `max-height` on `<canvas>` elements to prevent chart overflow
- For the legend on doughnut/pie charts, use `position:'right'` with small font to avoid overflow on narrow viewports — **but test that the legend doesn't clip on the right side.** If > 6 legend items, use `position:'bottom'` instead.
- Ensure the region doughnut chart container has `min-height: 280px` and `overflow: visible` to prevent legend clipping

## Auth Details

Authentication uses Azure CLI tokens:
```
az account get-access-token --resource https://<cluster>.kusto.windows.net --query accessToken -o tsv
```

Tokens are cached at `~/.agency-cowork/kusto-token-cache.json` for 30 minutes.

If auth fails:
1. Check `az account show` — user may need `az login`
2. Check cluster access — user needs at least Viewer role on the ADX database
3. The cluster URI must be correct (including region suffix like `.westus2`)

## Limitations

- **No cross-cluster queries** — each query targets one cluster/database
- **Result size** — REST API returns max 500K rows or 64 MB per query
- **No streaming** — full result set is returned at once
- **No materialized views** — use regular tables or functions
