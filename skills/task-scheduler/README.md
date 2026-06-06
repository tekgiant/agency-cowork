# task-scheduler

Schedule one-time and recurring tasks that invoke Agency Copilot with stored prompts. Includes a persistent background service, JSON-based task storage, and execution logging.

## Prerequisites

- **Windows** with PowerShell
- **Agency** installed and on PATH

## Registration

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\task-scheduler"
```

Restart your Copilot session for the skill to appear in `/skills`.

## Quick Start

### 1. Start the scheduler service

```powershell
Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -File `"skills/task-scheduler/scripts/scheduler-service.ps1`"" -WindowStyle Hidden
```

### 2. Create a task

```
Schedule a task to generate the program 300 weekly report every Monday at 9am
```

### 3. Check status

```
List my scheduled tasks
```

## Usage Examples

```
Schedule a daily task at 8am to check email for urgent program blockers
```

```
Create a task that runs every Friday at 4pm to draft the weekly status email
```

```
Schedule a one-time task for March 5th at 2pm to summarize the PEC meeting notes
```

```
Pause the weekly report task
```

```
Show me the logs for the weekly-program-300-report task
```

## Task Storage

Tasks are stored as individual JSON files in `tasks/`:

```
tasks/
├── task-weekly-program-300-report.json
├── task-daily-email-check.json
└── task-friday-status-email.json
```

**Manual operations:** Delete a task file to remove it. Edit a task file directly to modify it. The scheduler picks up changes on the next poll (within 60 seconds).

## Schedule Formats

| Format | Example | Description |
|--------|---------|-------------|
| Cron | `0 9 * * 1` | Standard 5-field cron |
| Datetime | `2026-03-05T14:00:00Z` | One-time execution |
| Daily | `daily at 9am` | Every day |
| Weekdays | `weekdays at 8:30am` | Monday–Friday |
| Weekly | `weekly on monday` | Weekly on specific day |
| Monthly | `monthly on the 1st` | Monthly on specific date |
| Interval | `every 4 hours` | Recurring interval |

## Logging

Per-task execution logs in `logs/task-<id>.log`:

```
[2026-03-03T09:00:05Z] RUN_START | task=weekly-program-300-report | trigger=scheduled
[2026-03-03T09:12:34Z] RUN_END   | task=weekly-program-300-report | status=success | duration=754s | result=Report saved
```

Service log in `logs/scheduler-service.log`:

```
[2026-03-01T19:00:00Z] INFO | Scheduler service started (PID 12345, poll interval 60s)
[2026-03-03T09:00:01Z] INFO | Found 1 due task(s)
[2026-03-03T09:00:01Z] INFO | Dispatching task: weekly-program-300-report
```

## CLI Reference

All operations via `task-manager.ps1`:

```powershell
$script = "skills/task-scheduler/scripts/task-manager.ps1"

# List all tasks
powershell -ExecutionPolicy Bypass -File $script list

# Create a task
powershell -ExecutionPolicy Bypass -File $script create -Name "Weekly Report" -Prompt "Generate the program 300 weekly report" -Schedule "weekly on monday"

# Update a task
powershell -ExecutionPolicy Bypass -File $script update -Id "weekly-report" -Schedule "weekly on tuesday at 10am"

# Pause / Resume
powershell -ExecutionPolicy Bypass -File $script pause -Id "weekly-report"
powershell -ExecutionPolicy Bypass -File $script resume -Id "weekly-report"

# Run immediately
powershell -ExecutionPolicy Bypass -File $script run -Id "weekly-report"

# View logs
powershell -ExecutionPolicy Bypass -File $script logs -Id "weekly-report" -Tail 50

# Check scheduler status
powershell -ExecutionPolicy Bypass -File $script status
```

## Troubleshooting

### Scheduler not running tasks

1. Check if the service is running: `task-manager.ps1 status`
2. If stopped, start it (see Quick Start above)
3. Check `logs/scheduler-service.log` for errors

### Task stuck in error_paused

1. View the task logs: `task-manager.ps1 logs -Id "<task-id>"`
2. Fix the underlying issue (prompt, permissions, etc.)
3. Resume: `task-manager.ps1 resume -Id "<task-id>"`

### Task timing seems off

- All times are in UTC. Cron expressions evaluate against UTC.
- The scheduler polls every 60 seconds, so tasks may start up to 60 seconds late.
