# Landing Zone (LZ) Skill — Specification

> **Version:** 1.0  
> **Author:** (Your Name)  
> **Date:** 2026-03-03  
> **Status:** Draft

---

## 1. Overview

### 1.1 What a Landing Zone is (and why it exists)

A Landing Zone (LZ) is an Azure DevOps (ADO) database of program requirements that becomes the queryable Single Source of Truth (SSOT) for a program's product definition. The intent is to move requirements out of scattered docs / hallway decisions into a structured, searchable, trackable place—so teams can avoid surprise work, align on scope, and make cross-org commitments explicit.

LZ is an output of the broader Product Definition (ProdDef) process, organized as Technology Domain workstreams. The LZ reduces execution surprises by making "who needs to do what" visible and reviewable across engineering teams and partners.

### 1.2 Problem Statement

The LZ process currently lives entirely in ADO with no agent-assisted tooling. The existing `ado-work-items` marketplace skill provides raw WIQL/API access but has zero LZ domain knowledge: no state machine enforcement, no grading analytics, no tree-aware querying, and no structured caching. The agent needs a dedicated skill that understands the LZ object model, state machine, and grading workflow.

### 1.3 Goals

1. **Cache ADO tree query results** as structured JSON for fast querying
2. **Provide LZ-aware query/filter** operations (by domain, state, DRI, grading status)
3. **Implement the state machine** with deterministic gating rules
4. **Generate analytics** (grading closure %, blockers by domain/team, at-risk items)
5. **Support write operations** (create, update, grade, reparent, link)
6. **Produce timestamped snapshots** with week-over-week comparison for progress analysis
7. **Generate markdown snapshots** to the memory knowledgebase for searchability
8. **Build on existing ADO auth** (`az account get-access-token`) — no new auth mechanisms

---

## 2. Information Architecture in ADO (Object Model)

### 2.1 Top-level structure: two "Epic" sections

The LZ is partitioned into two major sections (Epics):

| Epic | Content |
|------|---------|
| **Product Architecture** | SoC-derived capabilities |
| **System Development** | Non–SoC-derived capabilities (boards, firmware, chassis) |

This split defines "where" the requirement lives and which change-control rules apply later (SoC vs System).

### 2.2 Technology Domains

Inside each Epic, the LZ is organized into **Technology Domains** that map to program workstreams / technology areas / silicon IPs / system components. A Technology Domain is a "folder" or "container" that groups logically related requirements and provides an accountability anchor (Domain owner / DRI).

### 2.3 LZ Requirements (atomic unit)

The building block is a **Landing Zone Requirement** (LZ Req). LZ Reqs appear in several shapes:

| Shape | Description |
|-------|-------------|
| Standalone requirement | Directly under a Technology Domain |
| Sub-domain grouping | Domain-within-a-Domain to group like requirements |
| E2E Feature grouping | Multiple requirements roll up to a critical capability |
| Spec-linked requirement | High-level summary + link to architecture/spec doc; uses LZ process to track review/signoff |

> **Note:** In practice, teams sometimes mix ADO work item types (Requirements vs Features vs Tasks). This causes confusion because grading is designed around "Requirements" with explicit Minimum/Target/POR and grading fields. If a Domain is full of "Features" where others use "Requirements," it's a known hygiene issue.

---

## 3. Roles & Responsibilities

### 3.1 DRI definition

A **DRI** (Directly Responsible Individual) is accountable for their Domain(s) and for moving requirements through definition → grading → POR closure.

### 3.2 DRI core loop

For each Domain, the DRI:

1. Reviews pre-populated requirements (confirm/correct)
2. Adds missing requirements (especially cross-org)
3. Ensures each requirement has clear Title/Description + source context
4. Sets Minimum/Target
5. Identifies required supporting teams in Architecture Response
6. Drives Architecture Response + Grade
7. Advances state per the state machine
8. Ensures POR is captured and visible once aligned

---

## 4. Requirement Fields

### 4.1 Ownership & description hygiene

The DRI (or delegated owner) ensures: Owner is correct, Title is descriptive, Description includes source references and context (what, why, what's expected).

### 4.2 Minimum / Target semantics

| Scenario | Minimum | Target |
|----------|---------|--------|
| No real range | "Yes" | "Same as Minimum" |
| Range exists | Lower bound | Upper bound |
| Optional | "No" | "Yes" (or equivalent) |

Especially useful for "range" requirements (capacity, bandwidth, ratios).

### 4.3 POR field

Once alignment is reached, the DRI populates **POR (Plan of Record)** to document what is in-scope and what is explicitly not-POR to prevent ambiguity.

### 4.4 Architecture Response + Grade

The Architecture Response tab lists the teams that must provide support. Each team provides:

| Field | Required | Description |
|-------|----------|-------------|
| Architecture Response | Optional | Notes/assumptions/constraints |
| Grade | **Required** | Acknowledgement of understanding + feasibility |

The goal is cross-org clarity and commitment, not "work tracking" inside the LZ.

### 4.5 "Fully graded" definition

A requirement is **fully graded** when all identified supporting teams have provided their grade (and any needed response), indicating shared understanding and acknowledgement of support expected.

---

## 5. State Machine

### 5.1 Canonical state flow

```
New → Strawman → Well defined → Ready for Architecture Response → Graded POR Pending → Closed POR
                                                                ↘ At Risk (scope review) ↗
                                                                                         → Closed (Obsolete/Duplicate)
```

| State | Description |
|-------|-------------|
| **New** | Placeholder / early construction |
| **Strawman** | Description developed; Minimum/Target forming |
| **Well defined** | Description + Minimum/Target done; still identifying graders |
| **Ready for Architecture Response** | Graders identified; awaiting responses/grades |
| **Graded POR Pending** | All responses/grades complete; POR pending review/costing/schedule |
| **At Risk** | A supporting team indicates Minimum not deliverable; triggers scope review |
| **Closed POR** | POR set; fully graded; costing/schedule aligned |
| **Closed** | Obsolete or duplicate; requirement retired |

### 5.2 State transition gating rules

| Transition Target | Gate |
|-------------------|------|
| Ready for Architecture Response | Minimum/Target set AND all supporting teams listed in Architecture Response |
| Graded POR Pending | All listed teams have grades AND responses where needed |
| At Risk | Any supporting team indicates Minimum not feasible |
| Closed POR | Fully graded AND POR filled AND costing/schedule alignment acknowledged |

---

## 6. Relationship to Team ADOs

Every team tracks execution in their own ADO system (RTL, DV, firmware, platform, driver, OS, etc.). The LZ is the program-level contract that:

- Clarifies what work is required
- Makes cross-team dependencies explicit
- Supports formal dependency filing for planning cycles

**Best practice:** When an LZ Req is graded and a team needs to do work, that team creates a work item in their ADO and links it back to the LZ Req for traceability.

---

## 7. Change Control

A recurring risk is requirements getting "snuck in" late. The governance model:

| Scope Type | Lock Milestone | Change Route |
|-----------|----------------|-------------|
| SoC-derived | SoC milestone | SoC change board |
| System-derived | System/platform milestone | System change board |

Even before lock, LZ grading is used as an early warning system to surface scope churn and force explicit review.

---

## 8. Known ADO Saved Queries

Programs and their ADO saved query IDs are configured in `skills/landing-zone/programs.json` during first-time setup (see `setup.ps1` Phase 5). Example format:

| Program | Query ID | URL |
|---------|----------|-----|
| program-a | `<query-guid>` | `https://dev.azure.com/<org>/<project>/_queries/query/<guid>` |
| program-b | `<query-guid>` | `https://dev.azure.com/<org>/<project>/_queries/query/<guid>` |

All queries should be ADO tree queries that return the full LZ hierarchy.

---

## 9. Skill Architecture

### 9.1 File Structure

```
skills/landing-zone/
├── .claude-plugin/
│   └── plugin.json
├── agency.json
├── README.md
├── skills/
│   └── landing-zone/
│       └── SKILL.md              # Full skill definition with LZ domain knowledge
├── scripts/
│   ├── __init__.py
│   ├── lz_sync.py                # Fetch ADO saved query → structured JSON cache
│   ├── lz_query.py               # Query/filter cached LZ data (CLI tool)
│   ├── lz_analyze.py             # Health analytics, grading progress, reports
│   ├── lz_update.py              # Write operations to ADO (create, update, grade, link)
│   └── lz_snapshot.py            # Timestamped snapshots + WoW comparison
├── models/
│   ├── __init__.py
│   └── state_machine.py          # State transition rules + gating validation
├── cache/                        # Gitignored — cached ADO data
│   ├── .gitkeep
│   └── snapshots/                # Timestamped snapshot history
│       └── {program}/
│           └── {YYYY-MM-DD}.json
└── .gitignore                    # cache/*.json, cache/snapshots/
```

### 9.2 Technology choices

| Choice | Rationale |
|--------|-----------|
| Python | Consistent with teams rich messaging, azure-embed; better for tree/analytics than PS |
| `az` CLI for auth | Already installed; `az account get-access-token --resource 499b84ac-...` |
| Local JSON cache | ADO API is slow (800+ items = 5 batches); cache enables instant queries |
| Separate skill | Encodes LZ domain knowledge; doesn't belong in generic ADO plugin |
| No new pip deps | Uses stdlib only (`json`, `urllib`, `subprocess`, `enum`, `difflib`) |

---

## 10. Supported Operations

### 10.1 Read Operations

| Operation | Script | CLI Example |
|-----------|--------|-------------|
| **Sync from ADO** | `lz_sync.py` | `python -m scripts.lz_sync --program my-program` |
| **Query/filter** | `lz_query.py` | `python -m scripts.lz_query --program my-program --not-ready` |
| **Health analytics** | `lz_analyze.py` | `python -m scripts.lz_analyze --program my-program --report summary` |
| **Snapshot** | `lz_snapshot.py` | `python -m scripts.lz_snapshot --program my-program` |
| **WoW comparison** | `lz_snapshot.py` | `python -m scripts.lz_snapshot --program my-program --wow` |

### 10.2 Write Operations (all require user confirmation)

| Operation | Script | CLI Example |
|-----------|--------|-------------|
| **Create requirement** | `lz_update.py` | `--action create --parent-id <ID> --title "..."` |
| **Find similar** | `lz_update.py` | `--action find-similar --title "..." --program my-program` |
| **Assign DRI** | `lz_update.py` | `--action assign-dri --id <ID> --dri "Jane Doe"` |
| **Update description** | `lz_update.py` | `--action update-desc --id <ID> --description "..."` |
| **Add comment** | `lz_update.py` | `--action add-comment --id <ID> --comment "..."` |
| **Assign grader** | `lz_update.py` | `--action assign-grader --id <ID> --team "Team" --rep "Jane Doe"` |
| **Assign grade** | `lz_update.py` | `--action assign-grade --id <ID> --team "Team" --grade "Acknowledged"` |
| **Set Minimum/Target/POR** | `lz_update.py` | `--action set-field --id <ID> --field minimum --value "..."` |
| **Change parent** | `lz_update.py` | `--action reparent --id <ID> --new-parent-id <ID>` |
| **Add external link** | `lz_update.py` | `--action add-link --id <ID> --target-url "https://..." --link-type "Related"` |

### 10.3 Query Filters

| Filter | Flag | Description |
|--------|------|-------------|
| By state | `--state "New"` | Items in specified state |
| By domain | `--domain "System-level RAS"` | Items under specified technology domain |
| By DRI | `--dri "Jane Doe"` | Items assigned to specified DRI |
| By type | `--type Requirement` | Items of specified work item type |
| Not ready | `--not-ready` | Missing Minimum/Target or arch response list |
| At risk | `--at-risk` | Items in At Risk state |
| One grade away | `--one-grade-away` | All-but-one team has graded |
| Ungraded | `--ungraded` | In Ready for Arch Response with missing grades |
| Stale | `--stale 14` | Unchanged for N days |

---

## 11. Sync (`lz_sync.py`)

### 11.1 Behavior

1. Accept `--program` shortcut (resolves to query ID from built-in lookup) or explicit `--query-id`
2. Get auth token via `az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798`
3. Execute tree query via `GET _apis/wit/wiql/{queryId}?api-version=7.1`
4. Collect all unique work item IDs from `workItemRelations` (both `source` and `target`)
5. Batch-fetch work item details (200/batch) via `GET _apis/wit/workitems?ids={batch}&fields=...`
6. Extract fields: Id, WorkItemType, Title, State, AssignedTo, Tags, Description, custom fields (Minimum, Target, POR, Architecture Response)
7. Build parent→child tree structure from relations
8. Save structured JSON to `cache/{program}-lz.json` with metadata (timestamp, query ID, item counts, state summary)
9. If `--snapshot` flag: also create timestamped snapshot

### 11.2 Built-in query lookup

Programs are loaded from `programs.json` at runtime:

```python
def load_programs() -> dict:
    config_path = SKILL_ROOT / "programs.json"
    if not config_path.exists():
        print("ERROR: programs.json not found. Run setup.ps1 or create it manually.", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)
```

See `programs.json.example` for the expected format.

---

## 12. State Machine (`state_machine.py`)

### 12.1 States enum

```python
class LZState(Enum):
    NEW = "New"
    STRAWMAN = "Strawman"
    WELL_DEFINED = "Well defined"
    READY_FOR_ARCH_RESPONSE = "Ready for Architecture Response"
    GRADED_POR_PENDING = "Graded - POR Pending"
    AT_RISK = "At Risk"
    CLOSED_POR = "Closed POR"
    CLOSED = "Closed"
    # Aliases for ADO variations
    COMMITTED = "Committed"
    REMOVED = "Removed"
    ACTIVE = "Active"
```

### 12.2 Gating functions

| Function | Gate Logic |
|----------|-----------|
| `can_move_to_ready(item)` | `minimum` set AND `target` set AND `arch_response_teams` is non-empty |
| `can_move_to_graded(item)` | All teams in `arch_response_teams` have `grade` value |
| `can_move_to_closed_por(item)` | Fully graded AND `por` field is non-empty |
| `is_at_risk(item)` | Any team's grade indicates Minimum not feasible |
| `validate_transition(item, target_state)` | Check current state → target state is allowed AND gating rules pass; return `(ok: bool, reason: str)` |

---

## 13. Snapshots & Week-over-Week (`lz_snapshot.py`)

### 13.1 Snapshot creation

- Point-in-time snapshot from cached JSON
- Saved to `cache/snapshots/{program}/{YYYY-MM-DD}.json`
- Captures per-item: id, state, DRI, type, domain path, grading status
- Aggregate stats: state counts, grading % by domain, DRI workload
- Also generates markdown at `memory/Knowledgebase/Workstreams/{program}-landing-zone-requirements.md`

### 13.2 Week-over-week comparison

Compare two snapshots (default: latest vs 7 days ago, or explicit dates).

**Per-domain delta report:**
- Items added / removed / state changed
- Grading progress (% change, new grades received)
- New at-risk items
- Newly closed POR items

**Overall program delta:**
- State distribution shift (visual bar in markdown)
- Top movers (domains with most progress / regression)
- DRI workload changes

**CLI:**
```bash
# Auto: latest vs 7 days ago
python -m scripts.lz_snapshot --program my-program --wow

# Explicit dates
python -m scripts.lz_snapshot --program my-program --compare --from 2026-02-24 --to 2026-03-03
```

**Output:** Markdown report suitable for weekly status emails, executive reviews, or knowledgebase archival.

---

## 14. ADO Field Mapping

Custom fields like "Minimum", "Target", "POR", "Architecture Response" may use different internal field names depending on the ADO process template. The sync script discovers and maps these dynamically from the query's column definitions, with a fallback config stored in the cache JSON.

---

## 15. Dependencies

| Dependency | Status | Purpose |
|-----------|--------|---------|
| `az` CLI | Already installed | ADO auth tokens |
| Python 3.10+ | Already required | All scripts |
| Python stdlib | Built-in | `json`, `urllib`, `subprocess`, `enum`, `difflib`, `argparse` |

No new pip packages required.

---

## 16. Out of Scope (v1)

- Change control routing automation
- Real-time ADO webhook integration
- Bulk import/export of requirements from external sources
- ADO process template creation/modification

---

## 17. Implementation Todos

| # | ID | Title | Depends On |
|---|-----|-------|------------|
| 1 | `lz-scaffold` | Scaffold skill directory structure | — |
| 2 | `lz-skillmd` | Write SKILL.md with full LZ domain knowledge | 1 |
| 3 | `lz-sync` | Implement `lz_sync.py` — ADO → local cache | 1 |
| 4 | `lz-state-machine` | Implement `state_machine.py` — transitions + gating | 1 |
| 5 | `lz-query` | Implement `lz_query.py` — query/filter cached data | 3, 4 |
| 6 | `lz-analyze` | Implement `lz_analyze.py` — health analytics | 5 |
| 7 | `lz-update` | Implement `lz_update.py` — ADO write operations | 3, 4 |
| 8 | `lz-snapshot` | Implement `lz_snapshot.py` — snapshots + WoW comparison | 3 |
| 9 | `lz-register` | Register skill and update docs | 2 |
