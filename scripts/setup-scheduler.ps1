# setup-scheduler.ps1 - Create recommended scheduled tasks and start the scheduler service
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup-scheduler.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TasksDir = Join-Path $ProjectRoot "skills\task-scheduler\tasks"
$TaskManager = Join-Path $ProjectRoot "skills\task-scheduler\scripts\task-manager.ps1"
$SchedulerService = Join-Path $ProjectRoot "skills\task-scheduler\scripts\scheduler-service.ps1"
$PidFile = Join-Path $ProjectRoot "skills\task-scheduler\scheduler.pid"

# Prefer pwsh (PS 7+) over powershell.exe (PS 5.1) for broader syntax compatibility
$PwshExe = "powershell.exe"
if (Get-Command pwsh -ErrorAction SilentlyContinue) { $PwshExe = "pwsh.exe" }

Write-Host "`n=== Agency Cowork - Task Scheduler Setup ===" -ForegroundColor Cyan
Write-Host ""

# Ensure tasks directory exists
if (-not (Test-Path $TasksDir)) {
    New-Item -ItemType Directory -Path $TasksDir -Force | Out-Null
}

# --- Helper: Create a task JSON file ---
function New-ScheduledTask {
    param(
        [string]$Id,
        [string]$Name,
        [string]$Prompt,
        [string]$CronExpression,
        [string]$FriendlySchedule,
        [int]$TimeoutMinutes = 15
    )

    $taskFile = Join-Path $TasksDir "task-$Id.json"
    if (Test-Path $taskFile) {
        Write-Host "  [SKIP] $Name - already exists" -ForegroundColor Yellow
        return
    }

    # Calculate next run from cron
    $fields = $CronExpression -split '\s+'
    $cronMin = $fields[0]; $cronHour = $fields[1]; $cronDom = $fields[2]
    $cronMonth = $fields[3]; $cronDow = $fields[4]
    $now = [datetime]::UtcNow
    $candidate = $now.AddMinutes(1)
    $candidate = $candidate.AddSeconds(-$candidate.Second)
    $found = $false
    for ($i = 0; $i -lt 525960; $i++) {  # up to 366 days
        $matchMin = ($cronMin -eq '*') -or ($cronMin -eq $candidate.Minute.ToString())
        $matchHour = ($cronHour -eq '*') -or ($cronHour -eq $candidate.Hour.ToString())
        $matchDom = ($cronDom -eq '*') -or ($cronDom -eq $candidate.Day.ToString())
        $matchMonth = ($cronMonth -eq '*') -or ($cronMonth -eq $candidate.Month.ToString())
        $matchDow = ($cronDow -eq '*') -or ($cronDow -eq ([int]$candidate.DayOfWeek).ToString())
        if ($matchMin -and $matchHour -and $matchDom -and $matchMonth -and $matchDow) {
            $found = $true
            break
        }
        $candidate = $candidate.AddMinutes(1)
    }
    $nextRun = if ($found) { $candidate.ToString("o") } else { $null }

    $task = [ordered]@{
        id                = $Id
        name              = $Name
        prompt            = $Prompt
        schedule_type     = "cron"
        schedule_value    = $CronExpression
        schedule_friendly = $FriendlySchedule
        status            = "active"
        created_at        = $now.ToString("o")
        updated_at        = $now.ToString("o")
        next_run          = $nextRun
        last_run          = $null
        last_result       = $null
        run_count         = 0
        error_count       = 0
        timeout_minutes   = $TimeoutMinutes
        working_directory = $ProjectRoot
    }

    $task | ConvertTo-Json -Depth 5 | Set-Content $taskFile
    $nextFriendly = if ($nextRun) { ([datetime]$nextRun).ToString("yyyy-MM-dd HH:mm UTC") } else { "unknown" }
    Write-Host "  [OK] $Name - next run: $nextFriendly" -ForegroundColor Green
}

# --- Helper: Update prompt in existing task (preserves runtime state) ---
function Update-TaskPrompt {
    param(
        [string]$Id,
        [string]$NewPrompt
    )
    $taskFile = Join-Path $TasksDir "task-$Id.json"
    if (-not (Test-Path $taskFile)) { return }
    try {
        $task = Get-Content $taskFile -Raw | ConvertFrom-Json
        if ($task.prompt -ne $NewPrompt) {
            $task.prompt = $NewPrompt
            $task.updated_at = [datetime]::UtcNow.ToString("o")
            $task | ConvertTo-Json -Depth 5 | Set-Content $taskFile
            Write-Host "  [UPDATED] $($task.name) - prompt refreshed" -ForegroundColor Cyan
        }
    } catch {
        Write-Host "  [WARN] Could not update task $Id - $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# --- Create recommended tasks ---

Write-Host "`nCreating memory management tasks..." -ForegroundColor White

# Store prompts in variables (single-quoted to avoid PS interpretation)
$prompt1 = 'Run daily memory maintenance. Steps: Step 1 - Compact daily logs older than 7 days by appending a 2-3 line summary to memory/Knowledgebase/Program/daily-log-archive.md. Step 2 - Review memory/MEMORY.md and update stale facts such as outdated dates, completed milestones, or contacts who may have changed roles. Step 3 - Re-index QMD and refresh Azure embeddings by running: powershell -ExecutionPolicy Bypass -File skills/qmd-memory/scripts/memory-flush.ps1. Step 4 - Write a brief entry in todays daily log at memory/DailyLogs/YYYY-MM-DD.md (where YYYY-MM-DD is todays date) noting the maintenance was performed. Step 5 - Git add, commit, and push any changes.'

$prompt2 = 'Review and update memory/MEMORY.md. Step 1 - Read the file. Step 2 - Check Active Programs section: are dates still current, have milestones been reached. Step 3 - Check Key Contacts: any role changes or new contacts from this weeks daily logs. Step 4 - Check Tooling and Integrations: any new tools or workflow changes from recent sessions. Step 5 - Update any stale facts and keep MEMORY.md under 200 lines. Step 6 - If changes were made, git add memory/MEMORY.md, commit with message Weekly MEMORY.md review, and push.'

$prompt3 = 'Archive old daily logs to keep the memory directory clean. Step 1 - List all daily log files in the memory/DailyLogs/ directory matching YYYY-MM-DD.md pattern. Step 2 - Read each log older than 14 days that has not been archived and append a 2-3 line summary to memory/Knowledgebase/Program/daily-log-archive.md with the date as a heading. Step 3 - After archiving, delete the original log file and keep only the last 14 days of logs. Step 4 - Git add, commit with Weekly log archive, and push.'

$prompt4 = 'Run a full QMD re-index and Azure embedding refresh. Step 1 - Run cmd /c qmd update to refresh the text index. Step 2 - Run python skills/qmd-memory/scripts/azure-embed.py to regenerate Azure OpenAI embeddings. Step 3 - Verify by running a test search: cmd /c qmd search program status. Step 4 - Write a brief entry in todays daily log at memory/DailyLogs/YYYY-MM-DD.md (where YYYY-MM-DD is todays date) noting the re-index was performed.'

# 1. Daily Memory Maintenance (11 PM Pacific = 7 AM UTC next day)
New-ScheduledTask `
    -Id "daily-memory-maintenance" `
    -Name "Daily Memory Maintenance" `
    -Prompt $prompt1 `
    -CronExpression "0 7 * * *" `
    -FriendlySchedule "Daily at 11:00 PM Pacific (07:00 UTC)" `
    -TimeoutMinutes 15

# 2. Weekly MEMORY.md Review (Friday 5 PM Pacific = Saturday 1 AM UTC)
New-ScheduledTask `
    -Id "weekly-memory-review" `
    -Name "Weekly MEMORY.md Review" `
    -Prompt $prompt2 `
    -CronExpression "0 1 * * 6" `
    -FriendlySchedule "Weekly on Friday at 5:00 PM Pacific (01:00 UTC Saturday)" `
    -TimeoutMinutes 15

# 3. Weekly Log Archive (Saturday 10 PM Pacific = Sunday 6 AM UTC)
New-ScheduledTask `
    -Id "weekly-log-archive" `
    -Name "Weekly Log Archive" `
    -Prompt $prompt3 `
    -CronExpression "0 6 * * 0" `
    -FriendlySchedule "Weekly on Saturday at 10:00 PM Pacific (06:00 UTC Sunday)" `
    -TimeoutMinutes 15

# 4. Weekly QMD Re-index (Sunday 8 PM Pacific = Monday 4 AM UTC)
New-ScheduledTask `
    -Id "weekly-qmd-reindex" `
    -Name "Weekly QMD Re-index" `
    -Prompt $prompt4 `
    -CronExpression "0 4 * * 1" `
    -FriendlySchedule "Weekly on Sunday at 8:00 PM Pacific (04:00 UTC Monday)" `
    -TimeoutMinutes 20

# --- Migrate: update prompts in existing tasks (upgrade path) ---
# New-ScheduledTask skips if file exists, so this ensures stale prompts get refreshed
Update-TaskPrompt -Id "daily-memory-maintenance" -NewPrompt $prompt1
Update-TaskPrompt -Id "weekly-memory-review" -NewPrompt $prompt2
Update-TaskPrompt -Id "weekly-log-archive" -NewPrompt $prompt3
Update-TaskPrompt -Id "weekly-qmd-reindex" -NewPrompt $prompt4

# --- Start the scheduler service ---

Write-Host "`nStarting scheduler service..." -ForegroundColor White

# Check if already running
$alreadyRunning = $false
if (Test-Path $PidFile) {
    $svcPid = (Get-Content $PidFile -Raw).Trim()
    $proc = Get-Process -Id $svcPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  [SKIP] Scheduler already running (PID $svcPid)" -ForegroundColor Yellow
        $alreadyRunning = $true
    }
}

if (-not $alreadyRunning) {
    # Clean up stale PID file (process dead but file remains)
    if (Test-Path $PidFile) {
        $stalePid = (Get-Content $PidFile -Raw).Trim()
        if ($stalePid -match '^\d+$') {
            $staleProc = Get-Process -Id ([int]$stalePid) -ErrorAction SilentlyContinue
            if ($staleProc) {
                Write-Host "  [CLEAN] Stopping old scheduler (PID $stalePid)..." -ForegroundColor Yellow
                Stop-Process -Id ([int]$stalePid) -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    Start-Process -FilePath $PwshExe `
        -ArgumentList "-ExecutionPolicy Bypass -File `"$SchedulerService`"" `
        -WindowStyle Hidden
    Start-Sleep -Seconds 3

    if (Test-Path $PidFile) {
        $svcPid = (Get-Content $PidFile -Raw).Trim()
        $proc = Get-Process -Id $svcPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  [OK] Scheduler started (PID $svcPid)" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] Scheduler may not have started. Check logs." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [WARN] PID file not found after 3s. Check logs at skills/task-scheduler/logs/" -ForegroundColor Yellow
    }
}

# --- Show status ---

Write-Host ""
& $PwshExe -ExecutionPolicy Bypass -File $TaskManager list
& $PwshExe -ExecutionPolicy Bypass -File $TaskManager status

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "Tasks will run automatically on their schedules."
Write-Host "Use 'powershell -File skills/task-scheduler/scripts/task-manager.ps1 list' to manage tasks."
Write-Host ""
