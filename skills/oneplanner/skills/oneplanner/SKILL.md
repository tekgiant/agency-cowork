---
name: oneplanner
description: Manage Microsoft Project for the Web schedules via the OnePlanner local REST API
version: 1.0.0
category: project-management
requires:
  server: npm run dev:server (port 3100)
  python: ">=3.11"
  workspace: C:\Projects\OnePlanner
---

# OnePlanner Skill

Manage **Microsoft Project for the Web** schedules through a local REST API running on `http://127.0.0.1:3100`. All operations use human-readable names (task names, resource names, bucket names) — GUIDs are resolved internally by the server.

## Quick Start

1. Start the dev server: `npm run dev:server` (from the OnePlanner workspace root)
2. Authenticate: `python -m scripts.op_snapshot save --url <plannerUrl>`
3. Use any of the Python CLI scripts or call the REST API directly.

## Decision Table

| User Intent | Script | Command Example |
|---|---|---|
| See project status | `op_report` | `python -m scripts.op_report status` |
| List all tasks | `op_tasks` | `python -m scripts.op_tasks list` |
| Find overdue tasks | `op_tasks` | `python -m scripts.op_tasks overdue` |
| Tasks due soon | `op_tasks` | `python -m scripts.op_tasks due 7` |
| Create a task | `op_tasks` | `python -m scripts.op_tasks add "Design Review" --bucket "Design" --assign "Jane"` |
| Update a task | `op_tasks` | `python -m scripts.op_tasks update "Design Review" --status "in progress"` |
| Complete a task | `op_tasks` | `python -m scripts.op_tasks complete "Design Review"` |
| Delete a task | `op_tasks` | `python -m scripts.op_tasks delete "Design Review"` |
| Assign a resource | `op_assign` | `python -m scripts.op_assign add "Design Review" "Jane Doe"` |
| Remove assignment | `op_assign` | `python -m scripts.op_assign remove "Design Review" "Jane Doe"` |
| Bulk assign | `op_assign` | `python -m scripts.op_assign bulk "Jane Doe" "Task 1" "Task 2"` |
| List resources | `op_assign` | `python -m scripts.op_assign resources` |
| Add dependency | `op_deps` | `python -m scripts.op_deps add "Task B" "Task A" --type FS` |
| Chain tasks | `op_deps` | `python -m scripts.op_deps chain "Task A" "Task B" "Task C"` |
| Critical path | `op_deps` | `python -m scripts.op_deps critical-path` |
| Save baseline | `op_baseline` | `python -m scripts.op_baseline save --name "Sprint 5"` |
| Compare baseline | `op_baseline` | `python -m scripts.op_baseline compare --baseline "Sprint 5"` |
| View risks | `op_risks` | `python -m scripts.op_risks list` |
| Add a risk | `op_risks` | `python -m scripts.op_risks add "Supply delay" --severity High` |
| Task history | `op_history` | `python -m scripts.op_history show "Design Review"` |
| Recent changes | `op_history` | `python -m scripts.op_history recent` |
| Stale tasks | `op_history` | `python -m scripts.op_history stale --days 14` |
| Weekly report | `op_report` | `python -m scripts.op_report weekly` |
| Workload report | `op_report` | `python -m scripts.op_report workload` |
| Export tasks | `op_bulk` | `python -m scripts.op_bulk export --format csv -o tasks.csv` |
| Import tasks | `op_bulk` | `python -m scripts.op_bulk import tasks.csv` |
| Batch update | `op_bulk` | `python -m scripts.op_bulk update --filter "status=Not Started" --set "priority=high"` |
| Save snapshot | `op_snapshot` | `python -m scripts.op_snapshot save` |
| Refresh data | `op_snapshot` | `python -m scripts.op_snapshot refresh` |
| Diff snapshots | `op_snapshot` | `python -m scripts.op_snapshot diff` |
| Undo last change | `op_tasks` | `python -m scripts.op_tasks undo` |

## Workflow

```
1. Check server health     → GET /health  (or `python -m scripts.op_snapshot summary`)
2. If not authenticated    → `python -m scripts.op_snapshot save --url <url>`
3. If data not loaded      → `python -m scripts.op_snapshot refresh`
4. Perform operations      → Use op_*.py scripts or REST API
5. After mutations         → Server auto-refreshes; manual: `python -m scripts.op_snapshot refresh`
```

## Rules

1. **Always run from the `skills/oneplanner/` directory** (or the repo root, using `-m scripts.op_*` module syntax).
2. **The dev server must be running** on port 3100 (`npm run dev:server`).
3. **Use task names** (not GUIDs) for all operations. The server resolves names to IDs.
4. **Row numbers** and **outline numbers** also work as task identifiers.
5. **Dates** are in `YYYY-MM-DD` format (Pacific timezone is handled automatically).
6. **Durations** use "5d" (days) or "4h" (hours) shorthand.
7. **Status** values: "not started", "in progress", "completed" (case-insensitive).
8. **Priority** values: "urgent", "high", "medium", "low" (case-insensitive).
9. **All scripts** support `--format json` for machine-readable output.
10. **Destructive operations** (delete, bulk delete) require `--yes` flag or interactive confirmation.
11. **After bulk operations**, the server automatically refreshes data. No manual refresh needed.
12. **Undo** only works for the last mutation and requires the revision token chain to be intact.

## REST API Reference

The server at `http://127.0.0.1:3100` exposes these endpoints:

### Auth
- `GET /health` — Server health + session status
- `POST /auth/login` — Browser-based token extraction (`{ plannerUrl }`)
- `POST /auth/token` — Manual token paste (`{ token, projectId [, graphToken] }`)
- `GET /auth/status` — Session details
- `POST /auth/renew` — Renew token via browser
- `POST /auth/logout` — Clear session

### Project
- `POST /project/load` — Load project data (parallel fetch all endpoints)
- `POST /project/refresh` — Refresh data from API
- `GET /project/summary` — Project statistics
- `GET /project/snapshot` — Full snapshot (all data)

### Tasks
- `GET /tasks` — List tasks (query: `status`, `bucket`, `assignedTo`, `sprint`, `search`, `critical`, `fields`)
- `GET /tasks/due?days=N` — Tasks due within N days
- `GET /tasks/overdue` — Overdue tasks
- `GET /tasks/:nameOrIndex` — Single task detail
- `POST /tasks` — Create task (`{ name, parent?, bucket?, assignTo?, start?, finish?, duration? }`)
- `PATCH /tasks/:nameOrIndex` — Update task (`{ name?, status?, priority?, start?, finish?, ... }`)
- `DELETE /tasks/:nameOrIndex` — Delete task
- `POST /tasks/:nameOrIndex/indent` — Indent task
- `POST /tasks/:nameOrIndex/outdent` — Outdent task
- `POST /tasks/reorder` — Reorder (`{ task, afterTask }`)
- `POST /undo` — Undo last mutation

### Assignments
- `POST /tasks/:nameOrIndex/assign` — Assign (`{ resource }`)
- `DELETE /tasks/:nameOrIndex/assign/:resourceName` — Unassign
- `GET /tasks/:nameOrIndex/assignments` — List assignments
- `GET /resources` — List all resources

### Links
- `POST /tasks/:nameOrIndex/link` — Add link (`{ predecessor, type?, lag? }`)
- `DELETE /tasks/:nameOrIndex/link/:predecessorName` — Remove link
- `GET /tasks/:nameOrIndex/links` — List dependencies

### History
- `GET /tasks/:nameOrIndex/history?limit=N` — Task edit history
- `POST /tasks/history/batch` — Batch history (`{ tasks: [...], limit? }`)
- `GET /tasks/recently-modified?limit=N` — Recently modified tasks

### Backup & Baseline
- `POST /backup/create` — Create full backup
- `POST /baseline/save` — Save baseline (`{ name? }`)
- `POST /baseline/compare` — Compare vs baseline (`{ baseline? }`)
- `GET /baselines` — List baselines
- `GET /risks` — List risks
- `GET /critical-path` — Critical path analysis
