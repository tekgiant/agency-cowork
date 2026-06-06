---
name: landing-zone
description: >
  Query, analyze, and manage Azure DevOps Landing Zone requirements. Supports
  syncing ADO saved queries, state machine validation, grading analytics,
  week-over-week progress tracking, and ADO write operations (create, assign,
  grade, reparent, link). Triggers include "landing zone", "LZ", "requirements",
  "grading status", "POR status", "domain status", "LZ sync", "at risk
  requirements", "ungraded items", "week over week", "WoW comparison".
---

# Landing Zone (LZ) Skill

## Overview

The Landing Zone is Azure DevOps-based requirements management. This skill provides structured querying, analysis, and write operations against the LZ database.

**All scripts run from `skills/landing-zone/`:**

```bash
cd skills/landing-zone
python -m scripts.<module> [args]
```

## Known Programs & Queries

Programs are loaded from `programs.json` at runtime. Run `setup.ps1` Phase 5 to configure, or create `programs.json` manually (see `programs.json.example`).

| Program | `--program` flag | ADO Org | ADO Project | ADO Query ID |
|---------|-----------------|---------|-------------|-------------|
| *(configured at setup)* | `my-program` | `MyOrg` | `MyProject` | `<query-guid>` |

Auth: `az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798`.

## Decision Table

| User Intent | Script | Example |
|-------------|--------|---------|
| Sync/refresh LZ data from ADO | `lz_sync` | `python -m scripts.lz_sync --program my-program` |
| Search by keyword (title, description, tags) | `lz_query` | `python -m scripts.lz_query -p my-program --search "CMK encryption"` |
| Query items by state/domain/DRI | `lz_query` | `python -m scripts.lz_query -p my-program --state "New"` |
| Find items by creator | `lz_query` | `python -m scripts.lz_query -p my-program --created-by "Jane Doe"` |
| Find items by iteration path | `lz_query` | `python -m scripts.lz_query -p my-program --iteration "Sprint 5"` |
| Find ungraded/at-risk/stale items | `lz_query` | `python -m scripts.lz_query -p my-program --ungraded` |
| Health report / analytics | `lz_analyze` | `python -m scripts.lz_analyze -p my-program` |
| Create/update/grade ADO items | `lz_update` | `python -m scripts.lz_update -p my-program --action create ...` |
| Take a point-in-time snapshot | `lz_snapshot` | `python -m scripts.lz_snapshot -p my-program` |
| Week-over-week comparison | `lz_snapshot` | `python -m scripts.lz_snapshot -p my-program --wow` |

## ADO Object Model

```
Epic (Product Architecture | System Development)
  └── Domain (Technology Domain — accountability anchor)
       ├── Requirement (atomic LZ unit — graded)
       ├── Feature (grouping — sometimes used instead of Requirement)
       └── Domain (sub-domain grouping)
            └── Requirement
```

## State Machine

### States

| State | Description |
|-------|-------------|
| **New** | Placeholder / early construction |
| **Strawman** | Description developed; Minimum/Target forming |
| **Well defined** | Description + Minimum/Target done; identifying graders |
| **Ready for Architecture Response** | Graders identified; awaiting grades |
| **Graded - POR Pending** | All grades complete; POR pending |
| **At Risk** | Supporting team says Minimum not feasible |
| **Closed POR** | POR set; fully graded; aligned |
| **Closed** | Obsolete or duplicate |

### Gating Rules

| Target State | Gate |
|-------------|------|
| Ready for Arch Response | Minimum set AND Target set AND arch response teams listed |
| Graded - POR Pending | ALL listed teams have provided grades |
| Closed POR | Fully graded AND POR field populated |
| At Risk | Any team indicates Minimum not feasible |

## Requirement Fields

| Field | Description |
|-------|-------------|
| **Owner / DRI** | Directly Responsible Individual |
| **Minimum** | Lower bound of capability range (or "Yes" if no range) |
| **Target** | Upper bound (or "Same as Minimum") |
| **POR** | Plan of Record — what is in-scope after alignment |
| **Architecture Response** | Teams list + notes/constraints |
| **Grade** | Per-team acknowledgement (required for each team) |

## Operations Reference

### Sync (lz_sync.py)

```bash
# Sync using program shortcut
python -m scripts.lz_sync --program my-program

# Sync with snapshot
python -m scripts.lz_sync --program my-program --snapshot

# Sync with explicit query
python -m scripts.lz_sync --org MyOrg --project MyProject --query-id <GUID>
```

Fetches the ADO tree query, batch-fetches all work items, caches as JSON + markdown.

### Query (lz_query.py)

```bash
# Free-text search (matches title, description, tags — all keywords must match)
python -m scripts.lz_query -p my-program --search "CMK encryption"
python -m scripts.lz_query -p my-program --search "key protection library"

# By state
python -m scripts.lz_query -p my-program --state "New"

# By DRI
python -m scripts.lz_query -p my-program --dri "Jane Doe"

# By creator
python -m scripts.lz_query -p my-program --created-by "John Smith"

# By iteration path
python -m scripts.lz_query -p my-program --iteration "Sprint 5"

# By domain
python -m scripts.lz_query -p my-program --domain "System-level RAS"

# Combine filters (e.g., search + state + type)
python -m scripts.lz_query -p my-program --search "encryption" --state "New" --type "Requirement"

# Special filters
python -m scripts.lz_query -p my-program --not-ready
python -m scripts.lz_query -p my-program --at-risk
python -m scripts.lz_query -p my-program --ungraded
python -m scripts.lz_query -p my-program --stale 14

# Output formats
python -m scripts.lz_query -p my-program --state "New" --output json
python -m scripts.lz_query -p my-program --state "New" --output markdown
```

### Analyze (lz_analyze.py)

```bash
# Markdown summary report
python -m scripts.lz_analyze -p my-program --report summary

# JSON analytics
python -m scripts.lz_analyze -p my-program --report json
```

### Update (lz_update.py) — Write Operations

**All writes require user confirmation before executing.**

```bash
# Create requirement
python -m scripts.lz_update -p my-program --action create --parent-id 12968 --title "New requirement"

# Find similar (duplicate check)
python -m scripts.lz_update -p my-program --action find-similar --title "Error handling"

# Assign DRI
python -m scripts.lz_update -p my-program --action assign-dri --id 13246 --dri "Jane Doe"

# Update description
python -m scripts.lz_update -p my-program --action update-desc --id 13246 --description "Updated description"

# Add comment
python -m scripts.lz_update -p my-program --action add-comment --id 13246 --comment "Review needed"

# Set field (Minimum, Target, POR, or any ADO field reference name)
python -m scripts.lz_update -p my-program --action set-field --id 13246 --field "Custom.Minimum" --value "Yes"

# Change parent
python -m scripts.lz_update -p my-program --action reparent --id 13246 --new-parent-id 13030

# Add external link
python -m scripts.lz_update -p my-program --action add-link --id 13246 --target-url "https://dev.azure.com/..."
```

### Snapshot & WoW (lz_snapshot.py)

```bash
# Create snapshot
python -m scripts.lz_snapshot -p my-program

# Week-over-week (latest vs 7 days ago)
python -m scripts.lz_snapshot -p my-program --wow

# Compare specific dates
python -m scripts.lz_snapshot -p my-program --compare --from 2026-02-24 --to 2026-03-03
```

## Rules

1. **Always sync before first use** — run `lz_sync` to populate the cache.
2. **Sync before analysis** if cache is >24h old — check `meta.timestamp` in cache JSON.
3. **Write operations require confirmation** — never bypass the confirmation prompt.
4. **Find-similar before create** — always check for duplicates before creating new requirements.
5. **Take snapshots weekly** — enables WoW comparison for executive reporting.
6. **Use `--program` shortcut** — avoids typos in query IDs.

## Limitations

- Custom fields (Minimum, Target, POR, Architecture Response) may vary by ADO process template — field reference names may need manual mapping.
- Grading status requires Architecture Response tab data which may not be available via standard REST API fields.
- Cache is a point-in-time snapshot — always sync for the latest data before making decisions.
- WoW comparison requires at least 2 snapshots on different dates.
