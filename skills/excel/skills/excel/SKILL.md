---
name: excel
description: |
  Use this skill when the user asks to "edit a spreadsheet", "update an Excel file", "modify a workbook",
  "create an xlsx", "inspect a spreadsheet", or wants to create, inspect, edit, or modify Excel workbooks.
  Primary workflow is edit-first: download → inspect → batch edit → upload back.
---

# Excel Skill

Inspect and edit Excel (.xlsx) workbooks using `openpyxl`. Formatting is configured in `agentconfig.json` under `office.excel` and `office.branding`.

## Primary Workflow: Edit Existing Files

Most work involves modifying existing workbooks downloaded from SharePoint:

```
1. Download from SharePoint  →  sharepoint skill
2. Check for DRM (OLE2 header?)  →  office_common/drm_handler.ps1 -Action capture
3. Strip DRM if present      →  office_common/drm_handler.ps1 -Action strip
4. Inspect the workbook      →  xlsx_editor --action inspect
5. Plan edits                →  agent reasons about what to change
6. Apply edits (batch)       →  xlsx_editor --action batch --ops-json '[...]'
7. Re-apply DRM if present   →  office_common/drm_handler.ps1 -Action apply
8. Upload back               →  sharepoint skill
```

> **DRM-protected files:** Many Microsoft files use IRM, which wraps the XLSX in an OLE2 container (`D0 CF` header). `openpyxl` cannot read these directly — strip via COM first using `skills/office_common/drm_handler.ps1`. Always re-apply DRM after editing. See the PowerPoint skill's DRM Workflow section for detailed examples.

### Step 1: Inspect

```powershell
cd skills/excel
python -m scripts.xlsx_editor -i "../../output/workbook.xlsx" --action inspect
python -m scripts.xlsx_editor -i "../../output/workbook.xlsx" --action inspect --sheet "Sheet1"
```

Returns: sheet names, dimensions, headers, sample data (head + tail), formulas, charts, merged cells, filters, column widths.

### Step 2: Edit (Single or Batch)

**Batch edit** (preferred):
```powershell
python -m scripts.xlsx_editor -i workbook.xlsx --action batch --ops-json '[
  {"action": "update-cells", "sheet": "Metrics", "updates": [{"cell": "B2", "value": "1.5x"}, {"cell": "C2", "value": "Complete"}]},
  {"action": "find-replace", "find": "At Risk", "replace": "On Track"},
  {"action": "add-rows", "sheet": "Log", "rows": [["2026-06-15", "Updated status", "user"]]},
  {"action": "insert-rows", "sheet": "Data", "at_row": 5, "rows": [["New", "Row", "Here"]]},
  {"action": "delete-rows", "sheet": "Data", "rows": [8, 9, 10]},
  {"action": "rename-sheet", "sheet": "Old Name", "new_name": "New Name"},
  {"action": "copy-sheet", "sheet": "Template", "new_name": "June 2026"},
  {"action": "delete-sheet", "sheet": "Scratch"}
]'
```

**Single-action edits:**
```powershell
python -m scripts.xlsx_editor -i wb.xlsx --action find-replace --find "OLD" --replace "NEW"
python -m scripts.xlsx_editor -i wb.xlsx --action update-cells --sheet "S1" --updates-json '[{"cell":"B2","value":"Updated"}]'
python -m scripts.xlsx_editor -i wb.xlsx --action add-rows --sheet "S1" --rows-json '[["a","b","c"]]'
python -m scripts.xlsx_editor -i wb.xlsx --action insert-rows --sheet "S1" --at-row 5 --rows-json '[["x","y"]]'
python -m scripts.xlsx_editor -i wb.xlsx --action delete-rows --sheet "S1" --rows "5,6,7"
python -m scripts.xlsx_editor -i wb.xlsx --action extract-data --sheet "S1"
python -m scripts.xlsx_editor -i wb.xlsx --action copy-sheet --sheet "S1" --new-name "Copy"
python -m scripts.xlsx_editor -i wb.xlsx --action rename-sheet --sheet "S1" --new-name "Summary"
python -m scripts.xlsx_editor -i wb.xlsx --action delete-sheet --sheet "Scratch"
```

### Batch Actions Reference

| Action | Required Fields | Description |
|--------|----------------|-------------|
| `find-replace` | find, replace, sheet? | Find/replace across sheets |
| `update-cells` | sheet, updates[{cell,value}] | Update specific cells |
| `add-rows` | sheet, rows[[]] | Append rows at end |
| `insert-rows` | sheet, at_row, rows[[]] | Insert at position |
| `delete-rows` | sheet, rows[int] | Delete rows by index |
| `delete-sheet` | sheet | Remove a sheet |
| `copy-sheet` | sheet, new_name | Duplicate a sheet |
| `rename-sheet` | sheet, new_name | Rename a sheet |

## Creating New Workbooks

```powershell
cd skills/excel
python -m scripts.xlsx_builder --sheets-json '[{"name":"Data","headers":["A","B"],"rows":[[1,2],[3,4]]}]' -o "../../output/new.xlsx"
```

Supports: multiple sheets, charts (bar/line/pie), formulas, conditional formatting, auto-filter, freeze panes.

## Configuration

`agentconfig.json` → `office.excel` controls header colors, stripe colors, fonts, auto-filter, and freeze-pane defaults.

## OneDrive Upload

To upload finished workbooks to OneDrive, use the sync folder approach (see CLAUDE.md for details):

```bash
bash skills/shared/upload-to-onedrive.sh "output/workbook.xlsx" "Agency Cowork Outputs"
```

Do NOT use Graph API, MCP upload tools, or PowerShell for OneDrive uploads.

## Gotchas

These failure modes have caused real bugs — do not skip.

### File Handling

- **DRM detection: `D0 CF 11 E0` header = OLE2 (DRM-wrapped).** `openpyxl` throws a cryptic `"not a valid OOXML file"` error — it does NOT tell you the file is DRM-protected. Always check file header bytes before opening.
- **PowerShell `Copy-Item` treats `[` and `]` as glob wildcard delimiters.** Use `-LiteralPath` for any file paths that may contain square brackets (common in user-named files like `[Q3] Budget.xlsx`).
- **Large workbooks (>50MB or >100K rows) can cause openpyxl to consume excessive memory.** For these, consider read-only mode (`load_workbook(read_only=True)`) for inspection, and chunked processing for edits.

### Data Integrity

- **openpyxl does not evaluate formulas.** Cells with formulas show the formula text (e.g., `=SUM(A1:A10)`), not the computed value, in inspect output. The computed value is only available if the file was last saved with cached values by Excel.
- **`find-replace` with no `sheet` parameter searches ALL sheets.** This can silently change data in unexpected sheets if the search term appears in multiple places. Always scope to a specific sheet when possible.
- **Merged cells: editing a cell that's part of a merge group only updates the top-left cell.** Other cells in the merge are read-only — writing to them silently fails.

### Index Conventions

- **Row indices are 1-based (Excel convention)**, unlike PowerPoint shapes which are 0-based. Mixing these up when working across both skills causes off-by-one errors.
- **Column references use cell notation** (A1, B2), not numeric indices. Don't confuse with python-pptx's numeric shape indexing.

### DRM (same as PowerPoint)

- **DRM handler requires Office COM (Windows only).** On macOS, DRM strip/re-apply is not available — warn the user that protected files cannot be edited without a Windows machine.
- **Always re-apply DRM after editing** if the original was protected. Never upload an unprotected version.

## Composes With

- **sharepoint** — Download source workbooks, upload edited versions back
- **powerpoint** — Pull spreadsheet data for chart slides in presentations
- **weekly-report** — Supply data tables and metrics for weekly status reports
- **send-email** — Email finished workbooks as attachments
- **kusto-query** — Export Kusto query results to Excel for further analysis

## Rules

- **ALWAYS inspect first** before editing — understand sheet structure, headers, dimensions
- **Prefer batch edits** — one `--action batch` call with multiple ops
- Row indices are 1-based (Excel convention); column references use cell notation (A1, B2)
- Output defaults to overwriting input; use `--output` to save to a new file
