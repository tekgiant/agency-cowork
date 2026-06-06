---
name: ado
description: >
  General-purpose Azure DevOps work item operations. Query by ID, keyword search
  via WIQL, run saved queries, filter by state/type/DRI/iteration/area/tag, and
  write operations (create, assign, comment, set-field, reparent, link).
  Triggers: "ADO", "work item", "query ADO", "search ADO", "create work item",
  "assign work item", "ADO comment", "WIQL".
---

# ADO Skill

## Overview

General-purpose Azure DevOps work item query and update operations. Uses `ado_common` shared library for auth and REST helpers.

**For Landing Zone-specific tasks** (LZ sync, grading, WoW comparison, state machine), use the `landing-zone` skill instead.

**All scripts run from `skills/ado/`:**

```bash
cd skills/ado
python -m scripts.ado_query [args]
python -m scripts.ado_update [args]
```

## Configuration

Create `ado.json` (see `ado.json.example`) with default org/project:

```json
{ "org": "MyOrg", "project": "MyProject" }
```

Or pass `--org` and `--project` on every command.

Auth: `az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798`.

## Decision Table

| User Intent | Script | Action | Example |
|-------------|--------|--------|---------|
| Get work item by ID | `ado_query` | `get` | `--action get --id 12345` |
| Keyword search (title/desc/tags) | `ado_query` | `search` | `--action search --keywords "encryption"` |
| Run arbitrary WIQL | `ado_query` | `wiql` | `--action wiql --wiql "SELECT ..."` |
| Execute saved query | `ado_query` | `saved-query` | `--action saved-query --query-id <GUID>` |
| List with filters | `ado_query` | `list` | `--action list --state Active --type Bug` |
| Create work item | `ado_update` | `create` | `--action create --type Task --title "..."` |
| Assign work item | `ado_update` | `assign` | `--action assign --id 12345 --dri "Jane"` |
| Update description | `ado_update` | `update-desc` | `--action update-desc --id 12345 --description "..."` |
| Add comment | `ado_update` | `add-comment` | `--action add-comment --id 12345 --comment "..."` |
| Set any field | `ado_update` | `set-field` | `--action set-field --id 12345 --field System.State --value Active` |
| Change parent | `ado_update` | `reparent` | `--action reparent --id 12345 --new-parent-id 67890` |
| Add link | `ado_update` | `add-link` | `--action add-link --id 12345 --target-url "https://..."` |

## Query Operations (ado_query.py)

```bash
# Get single work item
python -m scripts.ado_query --action get --id 12345

# Keyword search (matches title, description, tags — all keywords must match)
python -m scripts.ado_query --action search --keywords "encryption key management"

# Arbitrary WIQL
python -m scripts.ado_query --action wiql --wiql "SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'Active' AND [System.WorkItemType] = 'Bug'"

# Execute saved query by GUID
python -m scripts.ado_query --action saved-query --query-id a1b2c3d4-...

# List with filters (combine any)
python -m scripts.ado_query --action list --state Active
python -m scripts.ado_query --action list --type Bug --dri "Jane Doe"
python -m scripts.ado_query --action list --iteration "Sprint 5" --tag "security"
python -m scripts.ado_query --action list --area "MyProject\\Backend" --creator "John"

# Output formats
python -m scripts.ado_query --action list --state Active --output json
python -m scripts.ado_query --action list --state Active --output markdown
```

## Update Operations (ado_update.py)

**All writes require user confirmation before executing.**

```bash
# Create work item
python -m scripts.ado_update --action create --type Bug --title "Login fails" --dri "Jane Doe"
python -m scripts.ado_update --action create --type Task --title "Review PR" --parent-id 12345

# Assign
python -m scripts.ado_update --action assign --id 12345 --dri "Jane Doe"

# Update description
python -m scripts.ado_update --action update-desc --id 12345 --description "Updated description"

# Add comment
python -m scripts.ado_update --action add-comment --id 12345 --comment "Reviewed and approved"

# Set any field
python -m scripts.ado_update --action set-field --id 12345 --field System.State --value Resolved

# Reparent
python -m scripts.ado_update --action reparent --id 12345 --new-parent-id 67890

# Add link
python -m scripts.ado_update --action add-link --id 12345 --target-url "https://dev.azure.com/..."
```

## Rules

1. **Write operations require confirmation** — never bypass the confirmation prompt.
2. **Use `ado.json` for defaults** — avoids repeating `--org`/`--project` on every call.
3. **For LZ-specific operations** — use the `landing-zone` skill, not this one.
4. **Output format** — default is `table`; use `--output json` for structured data, `--output markdown` for reports.
