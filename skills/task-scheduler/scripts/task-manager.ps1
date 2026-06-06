# task-manager.ps1 - CLI for managing scheduled tasks
# Usage: powershell -ExecutionPolicy Bypass -File task-manager.ps1 <command> [options]
#
# Commands:
#   list                                    List all tasks
#   create -Name "..." -Prompt "..." -Schedule "..." [-Timeout <min>]  Create a new task
#   update -Id "..." [-Name "..."] [-Prompt "..."] [-Schedule "..."] [-Timeout <min>]
#   pause  -Id "..."                        Pause a task
#   resume -Id "..."                        Resume a paused task
#   delete -Id "..."                        Delete a task
#   run    -Id "..."                        Immediately run a task
#   logs   -Id "..." [-Tail <n>]            Show execution log
#   status                                  Show scheduler and task summary
#   diagnose                                Run health checks on scheduler components
#   ensure-running                          Check if scheduler is running; start it if not
#   stop                                    Stop the scheduler service
#
# -Timeout <min>  Max execution time in minutes. 0 = no timeout (run to completion).
#                 Defaults to scheduler.default_timeout_minutes from agentconfig.json,
#                 or 30 if not configured.

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("list", "create", "update", "pause", "resume", "delete", "run", "logs", "status", "ensure-running", "stop", "diagnose")]
    [string]$Command,

    [string]$Id,
    [string]$Name,
    [string]$Prompt,
    [string]$Schedule,
    [int]$Timeout = -1,   # -1 means "use global default"; 0 = no timeout
    [int]$Tail = 20,
    [string]$WorkingDirectory
)

# Resolve WorkingDirectory if not provided
if (-not $WorkingDirectory) {
    $base = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { $null }
    if ($base) {
        $WorkingDirectory = (Resolve-Path (Join-Path $base "..\..\..")).Path
    } else {
        $WorkingDirectory = (Get-Location).Path
    }
}

$ErrorActionPreference = "Stop"
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { Join-Path $WorkingDirectory "skills\task-scheduler\scripts" }
$TasksDir = Join-Path (Split-Path -Parent $ScriptRoot) "tasks"
$LogsDir = Join-Path (Split-Path -Parent $ScriptRoot) "logs"

# Prefer pwsh (PS 7+) over powershell.exe (PS 5.1) for broader syntax compatibility
$PwshExe = "powershell.exe"
if (Get-Command pwsh -ErrorAction SilentlyContinue) { $PwshExe = "pwsh.exe" }

# Resolve effective timeout: explicit flag > agentconfig.json global default > 30
if ($Timeout -lt 0) {
    $agentCfgPath = Join-Path $WorkingDirectory "agentconfig.json"
    $defaultTimeout = 30
    if (Test-Path $agentCfgPath) {
        try {
            $agentCfg = Get-Content $agentCfgPath -Raw | ConvertFrom-Json
            if ($null -ne $agentCfg.scheduler -and $null -ne $agentCfg.scheduler.default_timeout_minutes) {
                $defaultTimeout = [int]$agentCfg.scheduler.default_timeout_minutes
            }
        } catch { }
    }
    $Timeout = $defaultTimeout
}

# Ensure directories exist
if (-not (Test-Path $TasksDir)) { New-Item -ItemType Directory -Path $TasksDir -Force | Out-Null }
if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }

# --- Schedule Parsing ---

function ConvertTo-CronExpression {
    param([string]$ScheduleInput)

    $s = $ScheduleInput.Trim().ToLower()

    # Already a cron expression (5 fields)
    if ($s -match '^\S+\s+\S+\s+\S+\s+\S+\s+\S+$') {
        return @{ cron = $s; friendly = $null; type = "cron" }
    }

    # ISO 8601 datetime -> one-time
    if ($s -match '^\d{4}-\d{2}-\d{2}') {
        $dt = [datetime]::Parse($s).ToUniversalTime()
        return @{ cron = $null; datetime = $dt.ToString("o"); friendly = $dt.ToString("yyyy-MM-dd HH:mm UTC"); type = "once" }
    }

    # Interval: "every Xh", "every Xm", "every X hours", "every X minutes"
    if ($s -match '^every\s+(\d+)\s*(h|hours?|m|minutes?|d|days?)$') {
        $val = [int]$Matches[1]
        $unit = $Matches[2]
        switch -Regex ($unit) {
            '^h'  { return @{ cron = "0 */$val * * *"; friendly = "Every $val hour(s)"; type = "interval" } }
            '^m'  { return @{ cron = "*/$val * * * *"; friendly = "Every $val minute(s)"; type = "interval" } }
            '^d'  { return @{ cron = "0 0 */$val * *"; friendly = "Every $val day(s)"; type = "interval" } }
        }
    }

    # "daily at HH:mm" or "daily at Ham/Hpm"
    if ($s -match '^daily\s+at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?$') {
        $hour = [int]$Matches[1]
        $min = if ($Matches[2]) { [int]$Matches[2] } else { 0 }
        if ($Matches[3] -eq 'pm' -and $hour -lt 12) { $hour += 12 }
        if ($Matches[3] -eq 'am' -and $hour -eq 12) { $hour = 0 }
        return @{ cron = "$min $hour * * *"; friendly = "Daily at $($hour.ToString('00')):$($min.ToString('00'))"; type = "cron" }
    }

    # "weekdays at HH:mm"
    if ($s -match '^weekdays?\s+at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?$') {
        $hour = [int]$Matches[1]
        $min = if ($Matches[2]) { [int]$Matches[2] } else { 0 }
        if ($Matches[3] -eq 'pm' -and $hour -lt 12) { $hour += 12 }
        if ($Matches[3] -eq 'am' -and $hour -eq 12) { $hour = 0 }
        return @{ cron = "$min $hour * * 1-5"; friendly = "Weekdays at $($hour.ToString('00')):$($min.ToString('00'))"; type = "cron" }
    }

    # "weekly on <day>" or "weekly on <day> at HH:mm"
    $dayMap = @{ "sunday"=0; "monday"=1; "tuesday"=2; "wednesday"=3; "thursday"=4; "friday"=5; "saturday"=6;
                 "sun"=0; "mon"=1; "tue"=2; "wed"=3; "thu"=4; "fri"=5; "sat"=6 }
    if ($s -match '^weekly\s+on\s+(\w+)(\s+at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?)?$') {
        $dayName = $Matches[1]
        $dayNum = $dayMap[$dayName]
        if ($null -eq $dayNum) { throw "Unknown day: $dayName" }
        $hour = if ($Matches[3]) { [int]$Matches[3] } else { 9 }
        $min = if ($Matches[4]) { [int]$Matches[4] } else { 0 }
        if ($Matches[5] -eq 'pm' -and $hour -lt 12) { $hour += 12 }
        if ($Matches[5] -eq 'am' -and $hour -eq 12) { $hour = 0 }
        return @{ cron = "$min $hour * * $dayNum"; friendly = "Weekly on $dayName at $($hour.ToString('00')):$($min.ToString('00'))"; type = "cron" }
    }

    # "monthly on the Nth" or "monthly on the Nth at HH:mm"
    if ($s -match '^monthly\s+on\s+the\s+(\d{1,2})\w*(\s+at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?)?$') {
        $day = [int]$Matches[1]
        $hour = if ($Matches[3]) { [int]$Matches[3] } else { 9 }
        $min = if ($Matches[4]) { [int]$Matches[4] } else { 0 }
        if ($Matches[5] -eq 'pm' -and $hour -lt 12) { $hour += 12 }
        if ($Matches[5] -eq 'am' -and $hour -eq 12) { $hour = 0 }
        return @{ cron = "$min $hour $day * *"; friendly = "Monthly on the ${day}th at $($hour.ToString('00')):$($min.ToString('00'))"; type = "cron" }
    }

    throw "Cannot parse schedule: '$ScheduleInput'. Use cron (e.g., '0 9 * * 1'), datetime (e.g., '2026-03-05T14:00:00Z'), or friendly format (e.g., 'daily at 9am', 'weekly on monday', 'every 4 hours')."
}

function Get-NextRunFromCron {
    param([string]$Cron)

    $fields = $Cron -split '\s+'
    if ($fields.Count -ne 5) { throw "Invalid cron expression: $Cron" }

    $now = [datetime]::UtcNow
    # Simple next-run calculation: iterate minute-by-minute up to 366 days ahead
    $candidate = $now.AddMinutes(1)
    $candidate = [datetime]::new($candidate.Year, $candidate.Month, $candidate.Day, $candidate.Hour, $candidate.Minute, 0, [System.DateTimeKind]::Utc)
    $limit = $now.AddDays(366)

    while ($candidate -lt $limit) {
        $matchMin = Test-CronField $fields[0] $candidate.Minute 0 59
        $matchHour = Test-CronField $fields[1] $candidate.Hour 0 23
        $matchDom = Test-CronField $fields[2] $candidate.Day 1 31
        $matchMonth = Test-CronField $fields[3] $candidate.Month 1 12
        $matchDow = Test-CronField $fields[4] ([int]$candidate.DayOfWeek) 0 6

        if ($matchMin -and $matchHour -and $matchDom -and $matchMonth -and $matchDow) {
            return $candidate.ToString("o")
        }

        $candidate = $candidate.AddMinutes(1)
    }

    throw "Could not compute next run for cron: $Cron"
}

function Test-CronField {
    param([string]$Field, [int]$Value, [int]$Min, [int]$Max)

    if ($Field -eq '*') { return $true }

    foreach ($part in ($Field -split ',')) {
        # Step: */N or N-M/S
        if ($part -match '^(\*|(\d+)-(\d+))/(\d+)$') {
            $step = [int]$Matches[4]
            $rangeStart = if ($Matches[2]) { [int]$Matches[2] } else { $Min }
            $rangeEnd = if ($Matches[3]) { [int]$Matches[3] } else { $Max }
            for ($i = $rangeStart; $i -le $rangeEnd; $i += $step) {
                if ($Value -eq $i) { return $true }
            }
            continue
        }

        # Range: N-M
        if ($part -match '^(\d+)-(\d+)$') {
            if ($Value -ge [int]$Matches[1] -and $Value -le [int]$Matches[2]) { return $true }
            continue
        }

        # Single value
        if ($part -match '^\d+$') {
            if ($Value -eq [int]$part) { return $true }
            continue
        }
    }

    return $false
}

# --- Task I/O ---

function Get-AllTasks {
    $tasks = @()
    Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $tasks += (Get-Content $_.FullName -Raw | ConvertFrom-Json)
    }
    return $tasks | Sort-Object -Property next_run
}

function Get-Task {
    param([string]$TaskId)
    $path = Join-Path $TasksDir "task-$TaskId.json"
    if (-not (Test-Path $path)) { throw "Task not found: $TaskId" }
    return (Get-Content $path -Raw | ConvertFrom-Json)
}

function Save-Task {
    param([psobject]$Task)
    $path = Join-Path $TasksDir "task-$($Task.id).json"
    $Task | ConvertTo-Json -Depth 10 | Set-Content $path -Encoding UTF8
}

function New-TaskId {
    param([string]$Name)
    $slug = ($Name.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')
    if ($slug.Length -gt 40) { $slug = $slug.Substring(0, 40).TrimEnd('-') }
    $existing = Get-ChildItem -Path $TasksDir -Filter "task-$slug*.json" -ErrorAction SilentlyContinue
    if ($existing.Count -eq 0) { return $slug }
    return "$slug-$([guid]::NewGuid().ToString().Substring(0,4))"
}

# --- Commands ---

function Invoke-List {
    $tasks = Get-AllTasks
    if ($tasks.Count -eq 0) {
        Write-Host "No scheduled tasks found."
        return
    }

    Write-Host "`nScheduled Tasks"
    Write-Host ("=" * 100)
    Write-Host ("{0,-30} {1,-10} {2,-22} {3,-22} {4,5}" -f "ID", "Status", "Next Run", "Last Run", "Runs")
    Write-Host ("-" * 100)
    foreach ($t in $tasks) {
        $nextRun = if ($t.next_run) { ([datetime]$t.next_run).ToString("yyyy-MM-dd HH:mm UTC") } else { "-" }
        $lastRun = if ($t.last_run) { ([datetime]$t.last_run).ToString("yyyy-MM-dd HH:mm UTC") } else { "-" }
        Write-Host ("{0,-30} {1,-10} {2,-22} {3,-22} {4,5}" -f $t.id, $t.status, $nextRun, $lastRun, $t.run_count)
    }
    Write-Host ""
}

function Invoke-Create {
    if (-not $Name) { throw "Name is required. Use -Name `"...`"" }
    if (-not $Prompt) { throw "Prompt is required. Use -Prompt `"...`"" }
    if (-not $Schedule) { throw "Schedule is required. Use -Schedule `"...`"" }

    # Prompt injection guard
    $guardScript = Join-Path (Split-Path (Split-Path (Split-Path $ScriptRoot -Parent) -Parent) -Parent) "scripts\prompt_guard.py"
    if (Test-Path $guardScript) {
        $guardResult = & python $guardScript --text $Prompt --source task --json 2>&1
        if ($LASTEXITCODE -eq 1) {
            $parsed_guard = $guardResult | ConvertFrom-Json
            Write-Host "BLOCKED: Prompt injection detected (severity: $($parsed_guard.max_severity))" -ForegroundColor Red
            foreach ($f in $parsed_guard.findings) {
                Write-Host "  [$($f.severity)] $($f.pattern_name): $($f.description)" -ForegroundColor Yellow
            }
            throw "Task creation rejected - prompt failed injection scan."
        }
    }

    $parsed = ConvertTo-CronExpression $Schedule
    $taskId = New-TaskId $Name

    $nextRun = $null
    if ($parsed.type -eq "once") {
        $nextRun = $parsed.datetime
    } else {
        $nextRun = Get-NextRunFromCron $parsed.cron
    }

    $task = [ordered]@{
        id                = $taskId
        name              = $Name
        prompt            = $Prompt
        schedule_type     = $parsed.type
        schedule_value    = if ($parsed.cron) { $parsed.cron } else { $parsed.datetime }
        schedule_friendly = if ($parsed.friendly) { $parsed.friendly } else { $Schedule }
        status            = "active"
        created_at        = [datetime]::UtcNow.ToString("o")
        updated_at        = [datetime]::UtcNow.ToString("o")
        next_run          = $nextRun
        last_run          = $null
        last_result       = $null
        run_count         = 0
        error_count       = 0
        timeout_minutes   = $Timeout
        working_directory = $WorkingDirectory
    }

    $taskObj = [pscustomobject]$task
    Save-Task $taskObj

    Write-Host "Task created: $taskId"
    Write-Host "  Name:     $Name"
    Write-Host "  Schedule: $($task.schedule_friendly) ($($task.schedule_value))"
    Write-Host "  Next run: $nextRun"
    Write-Host "  Prompt:   $Prompt"
}

function Invoke-Update {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $task = Get-Task $Id

    $changed = $false
    if ($Name) { $task.name = $Name; $changed = $true }
    if ($Prompt) {
        # Prompt injection guard
        $guardScript = Join-Path (Split-Path (Split-Path (Split-Path $ScriptRoot -Parent) -Parent) -Parent) "scripts\prompt_guard.py"
        if (Test-Path $guardScript) {
            $guardResult = & python $guardScript --text $Prompt --source task --json 2>&1
            if ($LASTEXITCODE -eq 1) {
                $parsed_guard = $guardResult | ConvertFrom-Json
                Write-Host "BLOCKED: Prompt injection detected (severity: $($parsed_guard.max_severity))" -ForegroundColor Red
                foreach ($f in $parsed_guard.findings) {
                    Write-Host "  [$($f.severity)] $($f.pattern_name): $($f.description)" -ForegroundColor Yellow
                }
                throw "Task update rejected - prompt failed injection scan."
            }
        }
        $task.prompt = $Prompt; $changed = $true
    }
    if ($Schedule) {
        $parsed = ConvertTo-CronExpression $Schedule
        $task.schedule_type = $parsed.type
        $task.schedule_value = if ($parsed.cron) { $parsed.cron } else { $parsed.datetime }
        $task.schedule_friendly = if ($parsed.friendly) { $parsed.friendly } else { $Schedule }
        if ($parsed.type -eq "once") {
            $task.next_run = $parsed.datetime
        } else {
            $task.next_run = Get-NextRunFromCron $parsed.cron
        }
        $changed = $true
    }
    if ($PSBoundParameters.ContainsKey('Timeout')) { $task.timeout_minutes = $Timeout; $changed = $true }

    if (-not $changed) { Write-Host "Nothing to update."; return }

    $task.updated_at = [datetime]::UtcNow.ToString("o")
    Save-Task $task

    Write-Host "Task updated: $Id"
}

function Invoke-Pause {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $task = Get-Task $Id
    $task.status = "paused"
    $task.updated_at = [datetime]::UtcNow.ToString("o")
    Save-Task $task
    Write-Host "Task paused: $Id"
}

function Invoke-Resume {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $task = Get-Task $Id
    $task.status = "active"
    $task.error_count = 0
    $task.updated_at = [datetime]::UtcNow.ToString("o")

    # Recalculate next run
    if ($task.schedule_type -ne "once") {
        $task.next_run = Get-NextRunFromCron $task.schedule_value
    }

    Save-Task $task
    Write-Host "Task resumed: $Id (next run: $($task.next_run))"
}

function Invoke-Delete {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $path = Join-Path $TasksDir "task-$Id.json"
    if (-not (Test-Path $path)) { throw "Task not found: $Id" }
    Remove-Item $path -Force
    Write-Host "Task deleted: $Id"
}

function Invoke-Run {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $task = Get-Task $Id
    $runScript = Join-Path $ScriptRoot "run-task.ps1"
    Write-Host "Running task: $Id"
    & $PwshExe -ExecutionPolicy Bypass -File $runScript -TaskId $Id
}

function Invoke-Logs {
    if (-not $Id) { throw "Id is required. Use -Id `"...`"" }
    $logPath = Join-Path $LogsDir "task-$Id.log"
    if (-not (Test-Path $logPath)) {
        Write-Host "No logs found for task: $Id"
        return
    }
    Get-Content $logPath -Tail $Tail
}

function Invoke-Status {
    $tasks = Get-AllTasks
    $active = ($tasks | Where-Object { $_.status -eq "active" }).Count
    $paused = ($tasks | Where-Object { $_.status -eq "paused" }).Count
    $errorPaused = ($tasks | Where-Object { $_.status -eq "error_paused" }).Count
    $completed = ($tasks | Where-Object { $_.status -eq "completed" }).Count

    # Check if scheduler service is running
    $schedulerRunning = $false
    $pidFile = Join-Path (Split-Path -Parent $ScriptRoot) "scheduler.pid"
    if (Test-Path $pidFile) {
        $svcPid = (Get-Content $pidFile -Raw).Trim()
        $proc = Get-Process -Id $svcPid -ErrorAction SilentlyContinue
        if ($proc) { $schedulerRunning = $true }
    }

    Write-Host "`nTask Scheduler Status"
    Write-Host ("=" * 50)
    Write-Host "  Service:       $(if ($schedulerRunning) { 'RUNNING' } else { 'STOPPED' })"
    Write-Host "  Total tasks:   $($tasks.Count)"
    Write-Host "  Active:        $active"
    Write-Host "  Paused:        $paused"
    Write-Host "  Error paused:  $errorPaused"
    Write-Host "  Completed:     $completed"

    $nextDue = $tasks | Where-Object { $_.status -eq "active" -and $_.next_run } | Select-Object -First 1
    if ($nextDue) {
        Write-Host "  Next due:      $($nextDue.id) at $($nextDue.next_run)"
    }
    Write-Host ""
}

# --- ensure-running: idempotent start ---

function Invoke-EnsureRunning {
    $pidFile = Join-Path (Split-Path -Parent $ScriptRoot) "scheduler.pid"
    $servicePath = Join-Path $ScriptRoot "scheduler-service.ps1"

    # Check if already running via PID file
    if (Test-Path $pidFile) {
        $svcPid = (Get-Content $pidFile -Raw).Trim()
        $proc = $null
        try { $proc = Get-Process -Id $svcPid -ErrorAction SilentlyContinue } catch {}
        if ($null -ne $proc) {
            $result = @{ action = "already_running"; pid = [int]$svcPid }
            $result | ConvertTo-Json | Write-Output
            return
        }
        # Stale PID file -- remove it
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    # Start the scheduler as a detached hidden process
    $procObj = Start-Process -FilePath $PwshExe `
        -ArgumentList "-ExecutionPolicy Bypass -File `"$servicePath`"" `
        -WindowStyle Hidden -PassThru
    
    # Wait briefly for PID file to be written
    $waited = 0
    while ($waited -lt 5000 -and -not (Test-Path $pidFile)) {
        Start-Sleep -Milliseconds 500
        $waited += 500
    }

    $newPid = if (Test-Path $pidFile) { [int](Get-Content $pidFile -Raw).Trim() } else { $procObj.Id }
    $result = @{ action = "started"; pid = $newPid }
    $result | ConvertTo-Json | Write-Output
}

# --- stop: kill the scheduler service ---

function Invoke-Stop {
    $pidFile = Join-Path (Split-Path -Parent $ScriptRoot) "scheduler.pid"

    if (-not (Test-Path $pidFile)) {
        $result = @{ action = "not_running" }
        $result | ConvertTo-Json | Write-Output
        return
    }

    $svcPid = (Get-Content $pidFile -Raw).Trim()
    $proc = $null
    try { $proc = Get-Process -Id $svcPid -ErrorAction SilentlyContinue } catch {}

    if ($null -ne $proc) {
        try { Stop-Process -Id $svcPid -Force } catch {}
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    $result = @{ action = "stopped"; pid = [int]$svcPid }
    $result | ConvertTo-Json | Write-Output
}

# --- Diagnose: comprehensive health check ---

function Invoke-Diagnose {
    $checks = @()

    # 1. Scheduler process alive
    $pidFile = Join-Path $SkillRoot "scheduler.pid"
    $schedulerAlive = $false
    $schedulerPid = $null
    if (Test-Path $pidFile) {
        $schedulerPid = (Get-Content $pidFile -Raw).Trim()
        try {
            $proc = Get-Process -Id $schedulerPid -ErrorAction SilentlyContinue
            $schedulerAlive = ($null -ne $proc)
        } catch {}
    }
    $checks += @{
        check   = "Scheduler Process"
        status  = if ($schedulerAlive) { "PASS" } else { "FAIL" }
        detail  = if ($schedulerAlive) { "PID $schedulerPid alive" }
                  elseif ($schedulerPid) { "PID $schedulerPid not running" }
                  else { "No PID file found" }
    }

    # 2. Heartbeat freshness
    $heartbeatFile = Join-Path $LogsDir "scheduler.heartbeat.json"
    $heartbeatAge = -1
    if (Test-Path $heartbeatFile) {
        try {
            $hb = Get-Content $heartbeatFile -Raw | ConvertFrom-Json
            $heartbeatAge = ([datetime]::UtcNow - [datetime]::Parse($hb.timestamp)).TotalSeconds
            $hbStatus = if ($heartbeatAge -le 180) { "PASS" }
                        elseif ($heartbeatAge -le 600) { "WARN" }
                        else { "FAIL" }
            $checks += @{
                check  = "Heartbeat Freshness"
                status = $hbStatus
                detail = "{0:N0}s ago | polls=$($hb.pollCount) | tasks=$($hb.totalTasks) | locks=$($hb.activeLocks)" -f $heartbeatAge
            }
        } catch {
            $checks += @{ check = "Heartbeat Freshness"; status = "FAIL"; detail = "Parse error: $($_.Exception.Message)" }
        }
    } else {
        $checks += @{ check = "Heartbeat Freshness"; status = "WARN"; detail = "No heartbeat file (scheduler may not have run yet)" }
    }

    # 3. Task files
    $taskFiles = @(Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue)
    $corruptCount = 0
    foreach ($f in $taskFiles) {
        try { $null = Get-Content $f.FullName -Raw | ConvertFrom-Json }
        catch { $corruptCount++ }
    }
    $checks += @{
        check  = "Task Files"
        status = if ($corruptCount -eq 0) { "PASS" } else { "FAIL" }
        detail = "$($taskFiles.Count) files, $corruptCount corrupted"
    }

    # 4. Stale lock files
    $lockFiles = @(Get-ChildItem -Path $TasksDir -Filter "*.lock" -ErrorAction SilentlyContinue)
    $staleLocks = @($lockFiles | Where-Object {
        ([datetime]::UtcNow - $_.LastWriteTimeUtc).TotalMinutes -gt 30
    })
    $checks += @{
        check  = "Lock Files"
        status = if ($staleLocks.Count -gt 0) { "WARN" } elseif ($lockFiles.Count -gt 0) { "INFO" } else { "PASS" }
        detail = "$($lockFiles.Count) active, $($staleLocks.Count) stale (>30min)"
    }

    # 5. Recent dispatch errors
    $dispatchLog = Join-Path $LogsDir "dispatch.jsonl"
    $recentErrors = 0
    if (Test-Path $dispatchLog) {
        $recentLines = Get-Content $dispatchLog -Tail 50 -ErrorAction SilentlyContinue
        foreach ($line in $recentLines) {
            try {
                $entry = $line | ConvertFrom-Json
                if ($entry.status -in @("FAILED", "TIMEOUT")) { $recentErrors++ }
            } catch {}
        }
    }
    $checks += @{
        check  = "Recent Dispatches"
        status = if ($recentErrors -eq 0) { "PASS" } elseif ($recentErrors -le 3) { "WARN" } else { "FAIL" }
        detail = "$recentErrors errors in last 50 dispatches"
    }

    # 6. Agency CLI available
    $agencyAvail = $false
    try {
        $agencyCmd = Get-Command "agency" -ErrorAction SilentlyContinue
        $agencyAvail = ($null -ne $agencyCmd)
    } catch {}
    $checks += @{
        check  = "Agency CLI"
        status = if ($agencyAvail) { "PASS" } else { "FAIL" }
        detail = if ($agencyAvail) { "Found: $($agencyCmd.Source)" } else { "Not found in PATH" }
    }

    # 7. Log directory writable
    $logWritable = $false
    $testFile = Join-Path $LogsDir ".write-test-$(Get-Random)"
    try {
        Set-Content $testFile -Value "test" -ErrorAction Stop
        Remove-Item $testFile -Force
        $logWritable = $true
    } catch {}
    $checks += @{
        check  = "Logs Writable"
        status = if ($logWritable) { "PASS" } else { "FAIL" }
        detail = if ($logWritable) { $LogsDir } else { "Cannot write to $LogsDir" }
    }

    # 8. Log directory size
    $logSize = 0
    Get-ChildItem -Path $LogsDir -Recurse -ErrorAction SilentlyContinue | ForEach-Object { $logSize += $_.Length }
    $logSizeMB = [Math]::Round($logSize / 1MB, 1)
    $checks += @{
        check  = "Log Size"
        status = if ($logSizeMB -lt 50) { "PASS" } elseif ($logSizeMB -lt 200) { "WARN" } else { "FAIL" }
        detail = "${logSizeMB}MB"
    }

    # Output as JSON
    @{
        timestamp = [datetime]::UtcNow.ToString("o")
        checks    = $checks
        summary   = @{
            pass = @($checks | Where-Object { $_.status -eq "PASS" }).Count
            warn = @($checks | Where-Object { $_.status -eq "WARN" }).Count
            fail = @($checks | Where-Object { $_.status -eq "FAIL" }).Count
        }
    } | ConvertTo-Json -Depth 5 | Write-Output
}

# --- Main ---

switch ($Command) {
    "list"   { Invoke-List }
    "create" { Invoke-Create }
    "update" { Invoke-Update }
    "pause"  { Invoke-Pause }
    "resume" { Invoke-Resume }
    "delete" { Invoke-Delete }
    "run"    { Invoke-Run }
    "logs"   { Invoke-Logs }
    "status" { Invoke-Status }
    "diagnose" { Invoke-Diagnose }
    "ensure-running" { Invoke-EnsureRunning }
    "stop" { Invoke-Stop }
}
