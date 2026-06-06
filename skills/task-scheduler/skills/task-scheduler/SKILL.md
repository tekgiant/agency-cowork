---
name: task-scheduler
description: |
  Use this skill when the user asks to "schedule a task", "create a recurring task", "run something on a schedule", "list scheduled tasks", "pause a task", "resume a task", "check task status", "view task logs", "start the scheduler", "stop the scheduler", or any task scheduling operation. This skill manages one-time and recurring tasks that invoke Agency Copilot with stored prompts, powered by a persistent background service.
---

# Task Scheduler Skill

Schedule one-time and recurring tasks that invoke Agency Copilot with stored prompts. Includes a persistent background service, JSON-based task storage, and execution logging.

## Overview

The task scheduler enables automated, unattended execution of routine Agency tasks. Each task is a JSON file containing a prompt and schedule — the scheduler service polls for due tasks and launches Agency to execute them.

### Architecture

```
skills/task-scheduler/
├── scripts/
│   ├── scheduler-service.ps1   # Background polling daemon (always-on)
│   ├── task-manager.ps1        # CLI for task CRUD operations
│   └── run-task.ps1            # Single-task execution (invokes Agency)
├── tasks/                      # One JSON file per task (task-<id>.json)
└── logs/                       # Execution logs per task + service log
```

## Task JSON Schema

Each task is stored as `tasks/task-<id>.json`:

```json
{
  "id": "weekly-program-300-report",
  "name": "Weekly program 300 Status Report",
  "prompt": "Generate the program 300 weekly status report",
  "schedule_type": "cron",
  "schedule_value": "0 9 * * 1",
  "schedule_friendly": "Weekly on monday at 09:00",
  "status": "active",
  "created_at": "2026-03-01T19:00:00Z",
  "updated_at": "2026-03-01T19:00:00Z",
  "next_run": "2026-03-03T09:00:00Z",
  "last_run": null,
  "last_result": null,
  "run_count": 0,
  "error_count": 0,
  "timeout_minutes": 30,
  "working_directory": "C:\\Projects\\Agency-Cowork"
}
```

### Task Status Values

| Status | Description |
|--------|-------------|
| `active` | Task is scheduled and will run when due |
| `paused` | Task is paused by user — will not run until resumed |
| `error_paused` | Auto-paused after 3 consecutive errors — requires manual resume |
| `completed` | One-time task that has finished executing |

### Schedule Types

| Type | schedule_value | Example |
|------|---------------|---------|
| `once` | ISO 8601 datetime | `2026-03-05T14:00:00Z` |
| `cron` | 5-field cron expression | `0 9 * * 1` (Monday 9am) |
| `interval` | Derived from friendly syntax | `0 */4 * * *` (every 4 hours) |

### Friendly Schedule Aliases

These are resolved to cron expressions at task creation time:

| Alias | Cron | Description |
|-------|------|-------------|
| `daily at 9am` | `0 9 * * *` | Every day at 9:00 AM |
| `daily at 8:30am` | `30 8 * * *` | Every day at 8:30 AM |
| `weekdays at 9am` | `0 9 * * 1-5` | Monday–Friday at 9:00 AM |
| `weekly on monday` | `0 9 * * 1` | Every Monday at 9:00 AM |
| `weekly on friday at 4pm` | `0 16 * * 5` | Every Friday at 4:00 PM |
| `monthly on the 1st` | `0 9 1 * *` | 1st of each month at 9:00 AM |
| `every 4 hours` | `0 */4 * * *` | Every 4 hours on the hour |
| `every 30 minutes` | `*/30 * * * *` | Every 30 minutes |

## Workflow

### Creating a Task

1. Collect from the user (ask if not provided):
   - **Name**: Descriptive name for the task (required)
   - **Prompt**: The exact prompt to send to Agency Copilot (required)
   - **Schedule**: When to run — cron, datetime, or friendly alias (required)
   - **Timeout**: Max execution time in minutes (default: 30)

2. Confirm with the user before creating:
   ```
   New Scheduled Task:
     Name:     Weekly program 300 Status Report
     Schedule: Weekly on monday at 09:00 (0 9 * * 1)
     Timeout:  30 minutes
     Prompt:   Generate the program 300 weekly status report

   Create this task?
   ```

3. Run the task manager to create:
   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" create -Name "Weekly program 300 Status Report" -Prompt "Generate the program 300 weekly status report" -Schedule "weekly on monday"
   ```

4. Confirm creation with the task ID and next run time.

### Listing Tasks

Run:
```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" list
```

Present results as a formatted table showing ID, status, next run, last run, and run count.

### Modifying a Task

1. List tasks to find the ID
2. Confirm changes with the user
3. Run:
   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" update -Id "<task-id>" -Schedule "daily at 8am"
   ```

### Pausing a Task

```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" pause -Id "<task-id>"
```

### Resuming a Task

```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" resume -Id "<task-id>"
```

Resuming recalculates `next_run` and resets the error counter.

### Deleting a Task

```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" delete -Id "<task-id>"
```

**Manual fallback:** Users can also delete a task by removing the JSON file directly from `tasks/task-<id>.json`.

### Running a Task Immediately

```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" run -Id "<task-id>"
```

### Viewing Task Logs

```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" logs -Id "<task-id>" -Tail 20
```

Log entries follow this format:
```
[2026-03-03T09:00:05Z] RUN_START | task=weekly-program-300-report | trigger=scheduled
[2026-03-03T09:12:34Z] RUN_END   | task=weekly-program-300-report | status=success | duration=754s | result=Report saved to memory/WeeklyReports/program 300/...
```

### Starting the Scheduler Service

The scheduler runs as a persistent background process:

```powershell
Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -File `"${SKILL_ROOT}/scripts/scheduler-service.ps1`"" -WindowStyle Hidden
```

Verify it's running:
```powershell
powershell.exe -ExecutionPolicy Bypass -File "${SKILL_ROOT}/scripts/task-manager.ps1" status
```

### Stopping the Scheduler Service

Read the PID and stop the process:
```powershell
$pid = Get-Content "${SKILL_ROOT}/scheduler.pid"
Stop-Process -Id $pid
```

## Execution Details

### How Tasks Execute

1. Scheduler polls `tasks/*.json` every 60 seconds
2. Finds tasks where `status == "active"` and `next_run <= now`
3. Launches `run-task.ps1` for each due task (sequential — one at a time)
4. `run-task.ps1` invokes Agency Copilot as a subprocess with the stored prompt
5. Captures output, logs results, updates the task JSON
6. Calculates the next run time based on the schedule

### Error Handling

- Failed tasks increment `error_count` on the task JSON
- After **3 consecutive errors**, the task is auto-paused with `status: "error_paused"`
- Successful execution resets `error_count` to 0
- Timeouts (default 30 min) kill the subprocess and log a timeout error
- One-time tasks (`schedule_type: "once"`) are marked `completed` after execution

### Logging

- **Per-task logs**: `logs/task-<id>.log` — every run start/end with timestamps, status, duration, result
- **Service log**: `logs/scheduler-service.log` — daemon lifecycle, poll events, dispatch records

## Rules

- **ALWAYS** confirm with the user before creating, modifying, or deleting tasks
- **ALWAYS** list tasks when the user asks about existing schedules
- **NEVER** create tasks without explicit user approval
- **NEVER** run tasks containing prompts with sensitive data (passwords, keys, secrets)
- **ALWAYS** validate that the scheduler service is running before telling the user tasks will execute on schedule
- When resuming error-paused tasks, review the logs first and explain the errors to the user
- Prompt content should be self-contained — the scheduled task runs in a fresh Agency session without conversational context
- Task IDs are auto-generated from the name (kebab-case, max 40 chars)
- If a task file is manually deleted, the scheduler silently skips it on the next poll

### Outbound Action Safety

Scheduled tasks run **unattended** — there is no interactive user to approve outbound actions. Apply these additional rules:

- **FLAG outbound prompts at creation time.** If a task prompt contains outbound actions (send email, post Teams message, forward, share files), warn the user that this will execute without interactive confirmation and require explicit acknowledgment.
- **Restrict outbound scope.** Scheduled task prompts that send email or post messages should specify exact recipients/channels — never use open-ended instructions like "send to relevant people" or "forward to the team."
- **Audit regularly.** Remind the user to periodically review tasks and logs: `powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1`
- **No external recipient escalation.** Scheduled tasks should never be configured to send to external (non-organization) email addresses. Flag this as a security risk if requested.

### Dangerous Prompt Patterns

The following patterns in scheduled task prompts are flagged by the security audit and should trigger a warning at creation time:

| Pattern | Risk |
|---------|------|
| `forward.*email` | Email forwarding (potential data exfiltration) |
| `send.*email.*to` | Email sending to specific recipient |
| `delete` | Destructive operation |
| `share.*file` | File sharing (potential data exposure) |
| `post.*channel` | Channel posting (message sent without review) |
| `download.*from` | File download (potential malware vector) |
