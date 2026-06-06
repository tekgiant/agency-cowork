# scheduler-service.ps1 - Persistent background service that polls for due tasks
# Usage: powershell -ExecutionPolicy Bypass -File scheduler-service.ps1
# Stop:  Read PID from scheduler.pid, then Stop-Process -Id <PID>

param(
    [int]$PollInterval = 60  # seconds between polls
)

$ErrorActionPreference = "Continue"
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { (Get-Location).Path }
$SkillRoot = Split-Path -Parent $ScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $SkillRoot "..\..") -ErrorAction SilentlyContinue).Path
$TasksDir = Join-Path $SkillRoot "tasks"
$LogsDir = Join-Path $SkillRoot "logs"
$PidFile = Join-Path $SkillRoot "scheduler.pid"
$ServiceLog = Join-Path $LogsDir "scheduler-service.log"
$AppSchedulesPath = Join-Path (Join-Path $env:USERPROFILE ".agency-cowork") "schedules.json"

# Read global scheduler config from agentconfig.json each time (re-read so Settings changes
# take effect without restarting the service).
function Get-GlobalSchedulerDefaultTimeout {
    if ($RepoRoot) {
        $agentCfgPath = Join-Path $RepoRoot "agentconfig.json"
        if (Test-Path $agentCfgPath) {
            try {
                $agentCfg = Get-Content $agentCfgPath -Raw | ConvertFrom-Json
                if ($null -ne $agentCfg.scheduler -and $null -ne $agentCfg.scheduler.default_timeout_minutes) {
                    return [int]$agentCfg.scheduler.default_timeout_minutes
                }
            } catch { }
        }
    }
    return 30
}

# Prefer pwsh (PS 7+) over powershell.exe (PS 5.1) for broader syntax compatibility
$PwshExe = "powershell.exe"
if (Get-Command pwsh -ErrorAction SilentlyContinue) { $PwshExe = "pwsh.exe" }

if (-not (Test-Path $TasksDir)) { New-Item -ItemType Directory -Path $TasksDir -Force | Out-Null }
if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }

# --- Service Logging ---

function Write-ServiceLog {
    param([string]$Level, [string]$Message)
    $timestamp = [datetime]::UtcNow.ToString("o")
    $line = "[$timestamp] $Level | $Message"
    Add-Content -Path $ServiceLog -Value $line -Encoding UTF8
    Write-Host $line
}

# --- BOM-safe JSON reader: strip UTF-8 BOM before parsing ---
# StreamWriter with [System.Text.Encoding]::UTF8 writes a BOM (3 bytes: EF BB BF).
# Successive read-modify-write cycles via StreamWriter can accumulate BOMs, causing
# "Unexpected token" JSON parse errors. This function strips BOMs and auto-repairs files.

function Read-TaskJson {
    param([string]$Path)
    $raw = Get-Content $Path -Raw
    if ($raw -and $raw[0] -eq [char]0xFEFF) {
        $raw = $raw.TrimStart([char]0xFEFF)
        # Auto-repair: rewrite without BOM (skip if file is locked by run-task.ps1)
        try {
            [System.IO.File]::WriteAllText($Path, $raw, [System.Text.UTF8Encoding]::new($false))
            Write-ServiceLog "WARN" "Stripped BOM from $Path"
        } catch {
            Write-ServiceLog "WARN" "BOM repair skipped -- file locked: $($_.Exception.Message)"
        }
    }
    return $raw | ConvertFrom-Json
}

# --- Locale-safe date helpers ---
# PowerShell 7 ConvertFrom-Json auto-converts ISO 8601 strings into [datetime] objects.
# Calling [datetime]::Parse() on those triggers a ToString() -> Parse() roundtrip that
# uses the current culture (e.g., DD/MM/YYYY on en-IE), corrupting month/day values.
# These helpers detect pre-converted objects and avoid the string roundtrip entirely.

function ConvertTo-UtcDateTime {
    param($Value)
    if ($Value -is [datetime]) {
        return $Value.ToUniversalTime()
    }
    if ($Value -is [datetimeoffset]) {
        return $Value.UtcDateTime
    }
    # String path: try ISO 8601 "o" format first, then InvariantCulture fallback
    $dt = [datetime]::MinValue
    if ([datetime]::TryParse($Value, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$dt)) {
        return $dt
    }
    throw "Cannot parse datetime value: $Value"
}

function ConvertTo-UtcDateTimeOffset {
    param($Value)
    if ($Value -is [datetimeoffset]) {
        return $Value.ToUniversalTime()
    }
    if ($Value -is [datetime]) {
        return [datetimeoffset]$Value.ToUniversalTime()
    }
    # String path: InvariantCulture
    $dto = [datetimeoffset]::MinValue
    if ([datetimeoffset]::TryParse($Value, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal, [ref]$dto)) {
        return $dto.ToUniversalTime()
    }
    throw "Cannot parse datetimeoffset value: $Value"
}

# --- Atomic JSON writer: write-to-temp, validate roundtrip, rename ---
# Prevents data corruption if the process crashes mid-write. Keeps a .bak
# file of the previous version so we can roll back if the new write is bad.

function Write-JsonAtomically {
    param([string]$Path, [object]$Object)
    $noBom = [System.Text.UTF8Encoding]::new($false)
    $json = $Object | ConvertTo-Json -Depth 10
    $tmpPath = "$Path.tmp"
    $bakPath = "$Path.bak"

    try {
        # 1. Write to temp file
        [System.IO.File]::WriteAllText($tmpPath, $json, $noBom)

        # 2. Validate the temp file is parseable JSON
        $null = Get-Content $tmpPath -Raw | ConvertFrom-Json

        # 3. Backup current file (if it exists)
        if (Test-Path $Path) {
            Copy-Item -Path $Path -Destination $bakPath -Force
        }

        # 4. Rename temp -> target (near-atomic on same volume)
        Move-Item -Path $tmpPath -Destination $Path -Force

        # 5. Clean up backup on success
        if (Test-Path $bakPath) {
            Remove-Item $bakPath -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # Restore from backup if rename failed
        if ((Test-Path $bakPath) -and -not (Test-Path $Path)) {
            Move-Item -Path $bakPath -Destination $Path -Force
            Write-ServiceLog "ERROR" "Atomic write failed, restored backup: $($_.Exception.Message)"
        } else {
            Write-ServiceLog "ERROR" "Atomic write failed: $($_.Exception.Message)"
        }
        # Clean up temp file
        if (Test-Path $tmpPath) { Remove-Item $tmpPath -Force -ErrorAction SilentlyContinue }
        throw
    }
}

# --- Dispatch audit log: structured JSONL for execution tracing ---

$DispatchLog = Join-Path $LogsDir "dispatch.jsonl"

function Write-DispatchEntry {
    param(
        [string]$TaskId,
        [string]$Status,  # DISPATCHED, COMPLETED, FAILED, TIMEOUT, SKIPPED
        [int]$ExitCode = -1,
        [string]$Duration = "",
        [string]$Details = ""
    )
    $entry = @{
        ts     = [datetime]::UtcNow.ToString("o")
        pid    = $PID
        taskId = $TaskId
        status = $Status
    }
    if ($ExitCode -ge 0)  { $entry.exitCode = $ExitCode }
    if ($Duration)         { $entry.duration = $Duration }
    if ($Details)          { $entry.details  = $Details }
    $line = $entry | ConvertTo-Json -Depth 5 -Compress
    Add-Content -Path $DispatchLog -Value $line -Encoding UTF8
}

# --- Dedup Key: normalize (name, prompt-hash, cron) for duplicate detection ---

function Get-TaskFingerprint {
    param([string]$Name, [string]$Prompt, [string]$Cron)
    if (-not $Name) { $Name = '' }
    if (-not $Prompt) { $Prompt = '' }
    if (-not $Cron) { $Cron = '' }
    $normName = $Name.Trim().ToLower()
    $normCron = $Cron.Trim()
    # Hash the prompt to a short fingerprint (avoids massive string comparisons)
    $promptBytes = [System.Text.Encoding]::UTF8.GetBytes($Prompt.Trim())
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($promptBytes)
    $promptHash = [System.BitConverter]::ToString($hash[0..7]).Replace("-", "").ToLower()
    return "$normName|$promptHash|$normCron"
}

# --- Bi-directional Sync ---

function Sync-TaskStores {
    # Sync between skill tasks/ dir and app schedules.json.
    # Dedup: tasks with same (name, prompt, cron) are considered identical.
    try {
        # Ensure the app schedules directory exists
        $appDir = Split-Path $AppSchedulesPath -Parent
        if (-not (Test-Path $appDir)) { New-Item -ItemType Directory -Path $appDir -Force | Out-Null }

        # Load skill tasks
        $skillTasks = @{}
        $skillFingerprints = @{}
        Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $t = Read-TaskJson $_.FullName
                $skillTasks[$t.id] = $t
                $fp = Get-TaskFingerprint $t.name $t.prompt $t.schedule_value
                $skillFingerprints[$fp] = $t.id
            } catch {}
        }

        # Load app schedules
        $appSchedules = @()
        $appById = @{}
        $appFingerprints = @{}
        if (Test-Path $AppSchedulesPath) {
            try {
                $appSchedules = @(Get-Content $AppSchedulesPath -Raw | ConvertFrom-Json)
                foreach ($s in $appSchedules) {
                    $appById[$s.id] = $s
                    $fp = Get-TaskFingerprint $s.title $s.prompt $s.cronExpression
                    $appFingerprints[$fp] = $s.id
                }
            } catch {}
        }

        $importedToApp = 0
        $importedToSkill = 0

        # Direction 1: Skill tasks -> App schedules.json
        foreach ($id in $skillTasks.Keys) {
            $t = $skillTasks[$id]
            if (-not $t -or -not $t.id) { continue }
            $fp = Get-TaskFingerprint $t.name $t.prompt $t.schedule_value
            # Skip if already in app store (by id or fingerprint)
            if ($appById.ContainsKey($id) -or $appFingerprints.ContainsKey($fp)) { continue }
            # Import into app schedules
            $newSchedule = [ordered]@{
                id             = $t.id
                title          = $t.name
                prompt         = $t.prompt
                cronExpression = $t.schedule_value
                enabled        = ($t.status -eq "active")
                mode           = "auto"
                workingDir     = $t.working_directory
                createdAt      = if ($t.created_at) { (ConvertTo-UtcDateTimeOffset $t.created_at).ToUnixTimeMilliseconds() } else { [datetimeoffset]::UtcNow.ToUnixTimeMilliseconds() }
                lastRunAt      = if ($t.last_run) { (ConvertTo-UtcDateTimeOffset $t.last_run).ToUnixTimeMilliseconds() } else { $null }
                runCount       = [int]($(if ($null -ne $t.run_count) { $t.run_count } else { 0 }))
                errorCount     = [int]($(if ($null -ne $t.error_count) { $t.error_count } else { 0 }))
                lastExitCode   = $null
                lastStatus     = $null
                runHistory     = @()
                _importedFrom  = "skill-task-scheduler"
            }
            $appSchedules += [pscustomobject]$newSchedule
            $appFingerprints[$fp] = $t.id
            $importedToApp++
            Write-ServiceLog "INFO" "Synced skill task to app: $($t.id) ($($t.name))"
        }

        # Direction 2: App schedules -> Skill tasks/
        foreach ($s in $appSchedules) {
            if (-not $s -or -not $s.id) { continue }
            $fp = Get-TaskFingerprint $s.title $s.prompt $s.cronExpression
            # Skip if already in skill store (by id or fingerprint)
            if ($skillTasks.ContainsKey($s.id) -or $skillFingerprints.ContainsKey($fp)) { continue }
            # Skip if no cron expression
            if (-not $s.cronExpression) { continue }
            # Import into skill tasks
            $nextRun = $null
            try { $nextRun = Get-NextRunFromCron $s.cronExpression } catch {}
            $newTask = [ordered]@{
                id                = $s.id
                name              = $s.title
                prompt            = $s.prompt
                schedule_type     = "cron"
                schedule_value    = $s.cronExpression
                schedule_friendly = $s.cronExpression
                status            = if ($s.enabled) { "active" } else { "paused" }
                created_at        = [datetimeoffset]::FromUnixTimeMilliseconds([long]($(if ($null -ne $s.createdAt) { $s.createdAt } else { 0 }))).ToString("o")
                updated_at        = [datetime]::UtcNow.ToString("o")
                next_run          = $nextRun
                last_run          = $null
                last_result       = $null
                run_count         = [int]($(if ($null -ne $s.runCount) { $s.runCount } else { 0 }))
                error_count       = [int]($(if ($null -ne $s.errorCount) { $s.errorCount } else { 0 }))
                timeout_minutes   = if ($null -ne $s.timeoutMinutes -and [int]$s.timeoutMinutes -ge 0) { [int]$s.timeoutMinutes } else { Get-GlobalSchedulerDefaultTimeout }
                working_directory = $s.workingDir
                _importedFrom     = "app-schedules"
            }
            $taskPath = Join-Path $TasksDir "task-$($s.id).json"
            Write-JsonAtomically -Path $taskPath -Object ([pscustomobject]$newTask)
            $skillFingerprints[$fp] = $s.id
            $importedToSkill++
            Write-ServiceLog "INFO" "Synced app schedule to skill: $($s.id) ($($s.title))"
        }

        # Direction 3: Propagate status updates from skill tasks -> app schedules.
        # Fixes tasks stuck in "running" state when the task JSON has a final result.
        $statusUpdated = 0
        foreach ($s in $appSchedules) {
            if (-not $s -or -not $s.id) { continue }
            if (-not $skillTasks.ContainsKey($s.id)) { continue }
            $t = $skillTasks[$s.id]

            $needsUpdate = (($s.lastStatus -eq "running" -or $null -eq $s.lastStatus) -and $t.last_result) -or
                           ($null -ne $s.runCount -and $null -ne $t.run_count -and [int]$s.runCount -ne [int]$t.run_count) -or
                           ($null -ne $s.errorCount -and $null -ne $t.error_count -and [int]$s.errorCount -ne [int]$t.error_count)

            if ($needsUpdate) {
                $s.lastStatus = if ($t.last_result -match '^Error') { "error" } else { "success" }
                $s.lastExitCode = if ($t.last_result -match '^Error') { 1 } else { 0 }
                $s.runCount = [int]($(if ($null -ne $t.run_count) { $t.run_count } else { 0 }))
                $s.errorCount = [int]($(if ($null -ne $t.error_count) { $t.error_count } else { 0 }))
                $s.enabled = ($t.status -eq "active")
                if ($t.last_run) {
                    try { $s.lastRunAt = (ConvertTo-UtcDateTimeOffset $t.last_run).ToUnixTimeMilliseconds() }
                    catch { Write-ServiceLog "WARN" "Failed to parse last_run '$($t.last_run)' for task '$($s.id)': $($_.Exception.Message)" }
                }
                $statusUpdated++
                Write-ServiceLog "INFO" "Synced status for task '$($s.id)': lastStatus=$($s.lastStatus), runCount=$($s.runCount)"
            }
        }

        # Save app schedules if anything was imported or status-updated
        $appDirty = ($importedToApp -gt 0) -or ($statusUpdated -gt 0)
        if ($appDirty) {
            $dir = Split-Path $AppSchedulesPath -Parent
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Write-JsonAtomically -Path $AppSchedulesPath -Object $appSchedules
            if ($importedToApp -gt 0) { Write-ServiceLog "INFO" "Imported $importedToApp task(s) into app schedules.json" }
            if ($statusUpdated -gt 0) { Write-ServiceLog "INFO" "Updated status for $statusUpdated task(s) in schedules.json" }
        }

        if ($importedToSkill -gt 0) {
            Write-ServiceLog "INFO" "Imported $importedToSkill schedule(s) into skill tasks/"
        }

        return ($importedToApp + $importedToSkill)
    } catch {
        Write-ServiceLog "ERROR" "Sync error: $($_.Exception.Message)"
        return 0
    }
}

# Validate and repair stale working directories on all task JSONs.
# Imported tasks may reference the source repo path instead of the current one.
# Derives repo root structurally from $ScriptRoot (4 levels up) to avoid
# git PATH dependency in Electron-spawned contexts.
function Repair-WorkingDirectories {
    $repoRoot = (Resolve-Path (Join-Path $ScriptRoot "..\..\.." )).Path
    if (-not (Test-Path $repoRoot)) {
        Write-ServiceLog "WARN" "Cannot determine repo root from '$ScriptRoot' -- skipping working directory validation"
        return
    }
    $repaired = 0
    $taskFiles = Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue
    foreach ($file in $taskFiles) {
        try {
            $task = Read-TaskJson $file.FullName
            $wd = $task.working_directory
            if (-not $wd) { continue }

            if (-not (Test-Path $wd)) {
                # Path doesn't exist -- auto-correct to scheduler's repo root
                Write-ServiceLog "WARN" "Task '$($task.id)' working_directory '$wd' does not exist. Updating to '$repoRoot'."
                $task.working_directory = $repoRoot
            }
            elseif (-not (Test-Path (Join-Path $wd ".git"))) {
                # Path exists but is not a git repo -- auto-correct
                Write-ServiceLog "WARN" "Task '$($task.id)' working_directory '$wd' is not a git repo. Updating to '$repoRoot'."
                $task.working_directory = $repoRoot
            }
            elseif ($wd -ne $repoRoot) {
                # Different valid repo -- warn only (may be intentional)
                Write-ServiceLog "INFO" "Task '$($task.id)' targets different repo '$wd' (scheduler root is '$repoRoot'). Verify intentional."
                continue
            }
            else { continue }

            $task.updated_at = [datetime]::UtcNow.ToString("o")
            Write-JsonAtomically -Path $file.FullName -Object $task
            $repaired++
        } catch {
            Write-ServiceLog "ERROR" "Failed to validate working_directory for $($file.Name): $($_.Exception.Message)"
        }
    }
    if ($repaired -gt 0) {
        Write-ServiceLog "INFO" "Repaired working_directory on $repaired task(s)"
    }
}

# Cron next-run helper (needed for sync -- imported from task-manager.ps1)
function Get-NextRunFromCron {
    param([string]$Cron)
    $fields = $Cron -split '\s+'
    if ($fields.Count -ne 5) { throw "Invalid cron: $Cron" }
    $now = [datetime]::UtcNow
    $candidate = $now.AddMinutes(1)
    $candidate = [datetime]::new($candidate.Year, $candidate.Month, $candidate.Day, $candidate.Hour, $candidate.Minute, 0, [System.DateTimeKind]::Utc)
    $limit = $now.AddDays(366)
    while ($candidate -lt $limit) {
        if ((Test-CronField $fields[0] $candidate.Minute 0 59) -and
            (Test-CronField $fields[1] $candidate.Hour 0 23) -and
            (Test-CronField $fields[2] $candidate.Day 1 31) -and
            (Test-CronField $fields[3] $candidate.Month 1 12) -and
            (Test-CronField $fields[4] ([int]$candidate.DayOfWeek) 0 6)) {
            return $candidate.ToString("o")
        }
        $candidate = $candidate.AddMinutes(1)
    }
    return $null
}

function Test-CronField {
    param([string]$Field, [int]$Value, [int]$Min, [int]$Max)
    if ($Field -eq '*') { return $true }
    foreach ($part in ($Field -split ',')) {
        if ($part -match '^(\*|(\d+)-(\d+))/(\d+)$') {
            $step = [int]$Matches[4]
            $rangeStart = if ($Matches[2]) { [int]$Matches[2] } else { $Min }
            $rangeEnd = if ($Matches[3]) { [int]$Matches[3] } else { $Max }
            for ($i = $rangeStart; $i -le $rangeEnd; $i += $step) {
                if ($Value -eq $i) { return $true }
            }
            continue
        }
        if ($part -match '^(\d+)-(\d+)$') {
            if ($Value -ge [int]$Matches[1] -and $Value -le [int]$Matches[2]) { return $true }
            continue
        }
        if ($part -match '^\d+$') {
            if ($Value -eq [int]$part) { return $true }
            continue
        }
    }
    return $false
}

# --- Singleton Check (system-wide) ---
# Check for ANY scheduler-service.ps1 process, regardless of working directory.
# The old PID-file approach only prevented duplicates within the same directory,
# allowing multiple clones to each run their own scheduler and race on task JSON.

$existingSchedulers = @()
try {
    $existingSchedulers = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'scheduler-service\.ps1' })
} catch {
    # CIM not available -- fall back to PID file check only
    Write-ServiceLog "WARN" "CIM query failed, falling back to PID-file singleton check: $($_.Exception.Message)"
}

if ($existingSchedulers.Count -gt 0) {
    $pids = ($existingSchedulers | ForEach-Object { $_.ProcessId }) -join ', '
    Write-ServiceLog "WARN" "Scheduler already running (PID(s): $pids). Exiting to prevent race condition."
    # Self-heal: if PID file is missing, regenerate it so health checks work correctly.
    if (-not (Test-Path $PidFile) -and $existingSchedulers.Count -eq 1) {
        $existingSchedulers[0].ProcessId | Set-Content $PidFile -Encoding UTF8
        Write-ServiceLog "INFO" "Regenerated missing PID file for scheduler PID $($existingSchedulers[0].ProcessId)"
    }
    exit 0
}

# Secondary check: PID file (catches cases where CIM query missed something)
if (Test-Path $PidFile) {
    $existingPid = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
    if ($existingPid) {
        $existingPid = $existingPid.Trim()
        $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-ServiceLog "WARN" "Scheduler already running (PID $existingPid from PID file). Exiting."
            exit 0
        }
    }
}

# Write PID file
$PID | Set-Content $PidFile -Encoding UTF8

# Cleanup on exit
$HeartbeatFile = Join-Path $LogsDir "scheduler.heartbeat.json"
$cleanupScript = {
    if (Test-Path $using:PidFile) {
        Remove-Item $using:PidFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $using:HeartbeatFile) {
        Remove-Item $using:HeartbeatFile -Force -ErrorAction SilentlyContinue
    }
}

try {
    Register-EngineEvent PowerShell.Exiting -Action $cleanupScript | Out-Null
} catch { }

Write-ServiceLog "INFO" "Scheduler service started (PID $PID, poll interval ${PollInterval}s)"

# Initial sync between skill tasks/ and app schedules.json
Sync-TaskStores

# Validate working directories on all tasks (fixes stale paths from imports)
Repair-WorkingDirectories

# --- Main Poll Loop ---

$pollCount = 0
$syncEveryN = 5  # sync every 5 polls (~5 minutes at default 60s interval)

while ($true) {
    try {
        $now = [datetime]::UtcNow
        $pollCount++

        # Periodic bi-directional sync
        if ($pollCount % $syncEveryN -eq 0) {
            $syncResult = Sync-TaskStores
            if ($syncResult -gt 0) {
                Repair-WorkingDirectories
            }
        }

        # Scan for due tasks
        $taskFiles = Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue
        $dueTasks = @()

        foreach ($file in $taskFiles) {
            try {
                $task = Read-TaskJson $file.FullName
                if ($task.status -ne "active") { continue }

                # Check if due
                if (-not $task.next_run) { continue }
                $nextRun = ConvertTo-UtcDateTime $task.next_run
                if ($nextRun -le $now) {
                    $dueTasks += $task
                }
            } catch {
                Write-ServiceLog "ERROR" "Failed to read task file $($file.Name): $($_.Exception.Message)"
            }
        }

        if ($dueTasks.Count -gt 0) {
            Write-ServiceLog "INFO" "Found $($dueTasks.Count) due task(s)"

            # Execute tasks sequentially
            foreach ($task in ($dueTasks | Sort-Object -Property next_run)) {
                # Re-check status (might have been paused while queued)
                $taskPath = Join-Path $TasksDir "task-$($task.id).json"
                if (-not (Test-Path $taskPath)) {
                    Write-ServiceLog "WARN" "Task file disappeared: $($task.id)"
                    continue
                }

                $freshTask = Read-TaskJson $taskPath
                if ($freshTask.status -ne "active") {
                    Write-ServiceLog "INFO" "Skipping task $($task.id) (status: $($freshTask.status))"
                    continue
                }

                # Re-check next_run — Electron's advanceWorkspaceTaskNextRun() may have
                # advanced it since our initial scan (issue #193 double-execution race).
                if ($freshTask.next_run) {
                    try {
                        $freshNextRun = ConvertTo-UtcDateTime $freshTask.next_run
                        if ($freshNextRun -gt [datetime]::UtcNow) {
                            Write-ServiceLog "INFO" "Skipping task $($task.id) -- next_run advanced to future ($($freshTask.next_run)), likely by Electron PTY runner"
                            continue
                        }
                    } catch {}
                }

                Write-ServiceLog "INFO" "Dispatching task: $($task.id)"

                # Dispatch lock: prevent multiple schedulers from dispatching the same task.
                # Write a .lock file atomically -- if it already exists, another scheduler won.
                $lockFile = Join-Path $TasksDir "task-$($task.id).lock"
                $lockAcquired = $false
                try {
                    # CreateNew fails if file exists -- atomic check-and-create
                    $lockStream = [System.IO.File]::Open($lockFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
                    $lockWriter = [System.IO.StreamWriter]::new($lockStream)
                    $lockWriter.Write("$PID|$([datetime]::UtcNow.ToString('o'))")
                    $lockWriter.Close()
                    $lockStream.Close()
                    $lockAcquired = $true
                } catch [System.IO.IOException] {
                    # Lock file exists -- check if it's stale (>30 minutes old)
                    if (Test-Path $lockFile) {
                        $lockAge = ([datetime]::UtcNow - (Get-Item $lockFile).LastWriteTimeUtc).TotalMinutes
                        if ($lockAge -gt 30) {
                            Write-ServiceLog "WARN" "Stale lock for $($task.id) (${lockAge}min old) -- removing and retrying"
                            Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
                            # Don't retry this poll -- let the next cycle pick it up
                        } else {
                            Write-ServiceLog "INFO" "Task $($task.id) already dispatched by another process -- skipping"
                        }
                    }
                }

                if (-not $lockAcquired) { continue }

                $runScript = Join-Path $ScriptRoot "run-task.ps1"
                $dispatchStart = [datetime]::UtcNow
                Write-DispatchEntry -TaskId $task.id -Status "DISPATCHED"
                try {
                    # Use -PassThru without -Wait so we can enforce a service-level
                    # timeout. The task itself has timeout_minutes, but if run-task.ps1
                    # hangs (crash after Kill(), stream deadlock, etc.), -Wait blocks
                    # the entire scheduler forever. The 10-minute buffer accounts for
                    # Agency CLI startup time.
                    # null timeout_minutes means "use global default" (scheduler:update writes null for blank).
                    # 0 = explicit no-timeout: apply a 24-hour service-level ceiling so a hung
                    # task cannot block the scheduler loop indefinitely; run-task.ps1 still waits
                    # to completion internally for the actual copilot.exe child.
                    $effectiveTimeout = if ($null -ne $task.timeout_minutes) { [int]$task.timeout_minutes } else { Get-GlobalSchedulerDefaultTimeout }
                    $noTaskTimeout = ($effectiveTimeout -le 0)
                    $rawTimeoutSec = if ($noTaskTimeout) { 86400 } else { [Math]::Max(($effectiveTimeout + 10) * 60, 1200) }
                    # Clamp to avoid Int32 overflow in WaitForExit(ms): 2,147,483 * 1000 < Int32.MaxValue
                    $taskTimeoutSec = if ([long]$rawTimeoutSec -gt 2147483) { 2147483 } else { [int]$rawTimeoutSec }
                    $taskProcess = Start-Process -FilePath $PwshExe `
                        -ArgumentList "-ExecutionPolicy Bypass -File `"$runScript`" -TaskId `"$($task.id)`"" `
                        -PassThru -NoNewWindow

                    $exited = $taskProcess.WaitForExit([int]($taskTimeoutSec * 1000))
                    $dispatchDuration = ([datetime]::UtcNow - $dispatchStart).ToString("hh\:mm\:ss")

                    if (-not $exited) {
                        # Service-level timeout -- kill the runner process tree
                        Write-ServiceLog "ERROR" "Task runner timed out after ${taskTimeoutSec}s: $($task.id)"
                        try {
                            $childProcs = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskProcess.Id)" -ErrorAction SilentlyContinue)
                            foreach ($cp in $childProcs) {
                                try { Stop-Process -Id $cp.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
                            }
                            $taskProcess.Kill()
                        } catch {}
                        Write-DispatchEntry -TaskId $task.id -Status "TIMEOUT" -ExitCode 124 -Duration $dispatchDuration -Details "Service-level timeout (${taskTimeoutSec}s)"
                    } elseif ($taskProcess.ExitCode -eq 0) {
                        Write-ServiceLog "INFO" "Task completed successfully: $($task.id)"
                        Write-DispatchEntry -TaskId $task.id -Status "COMPLETED" -ExitCode 0 -Duration $dispatchDuration
                    } else {
                        Write-ServiceLog "WARN" "Task finished with exit code $($taskProcess.ExitCode): $($task.id)"
                        Write-DispatchEntry -TaskId $task.id -Status "FAILED" -ExitCode $taskProcess.ExitCode -Duration $dispatchDuration
                    }
                } catch {
                    $dispatchDuration = ([datetime]::UtcNow - $dispatchStart).ToString("hh\:mm\:ss")
                    Write-ServiceLog "ERROR" "Failed to run task $($task.id): $($_.Exception.Message)"
                    Write-DispatchEntry -TaskId $task.id -Status "FAILED" -Details $_.Exception.Message -Duration $dispatchDuration
                } finally {
                    # Always release the dispatch lock
                    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        Write-ServiceLog "ERROR" "Poll loop error: $($_.Exception.Message)"
    }

    # --- Heartbeat: write health status after each poll cycle ---
    try {
        $taskCount = @(Get-ChildItem -Path $TasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue).Count
        $lockCount = @(Get-ChildItem -Path $TasksDir -Filter "*.lock" -ErrorAction SilentlyContinue).Count
        $hb = @{
            pid         = $PID
            timestamp   = [datetime]::UtcNow.ToString("o")
            pollCount   = $pollCount
            totalTasks  = $taskCount
            activeLocks = $lockCount
            dueTasks    = $dueTasks.Count
            status      = "healthy"
        }
        $noBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($HeartbeatFile, ($hb | ConvertTo-Json -Depth 5), $noBom)
    } catch {
        # Heartbeat write failure is non-fatal
    }

    Start-Sleep -Seconds $PollInterval
}
