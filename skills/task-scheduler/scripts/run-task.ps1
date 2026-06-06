# run-task.ps1 - Execute a single scheduled task by invoking Agency Copilot
# Usage: powershell -ExecutionPolicy Bypass -File run-task.ps1 -TaskId <id>

param(
    [Parameter(Mandatory=$true)]
    [string]$TaskId
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptRoot
$TasksDir = Join-Path $SkillRoot "tasks"
$LogsDir = Join-Path $SkillRoot "logs"

# Prefer pwsh (PS 7+) over powershell.exe (PS 5.1) for broader syntax compatibility
$PwshExe = "powershell.exe"
if (Get-Command pwsh -ErrorAction SilentlyContinue) { $PwshExe = "pwsh.exe" }

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }

# --- CLI Binary Resolution ---
# Mirrors the Electron app's detectCLI() priority: userOverride → cached resolvedPath
# → well-known install locations → PATH lookup → bare fallback.
# This prevents failures when Windows PATH contains unexpanded %SystemRoot% variables
# (a known Electron registry-read bug that corrupts process.env.PATH).
function Resolve-CliBinary {
    # 1. Check cli-path.json (userOverride first, then resolvedPath)
    $cliCacheFile = Join-Path (Join-Path $env:USERPROFILE ".agency-cowork") "cli-path.json"
    try {
        if (Test-Path -LiteralPath $cliCacheFile -PathType Leaf) {
            $cached = Get-Content -LiteralPath $cliCacheFile -Raw -Encoding UTF8 | ConvertFrom-Json
            # userOverride is an explicit user/admin setting — highest priority
            if ($cached.userOverride) {
                $expanded = [Environment]::ExpandEnvironmentVariables($cached.userOverride)
                if (Test-Path -LiteralPath $expanded -PathType Leaf) { return $expanded }
            }
            $cachedPath = if ($cached.resolvedPath) { $cached.resolvedPath } elseif ($cached.path) { $cached.path } else { $null }
            if ($cachedPath) {
                $expanded = [Environment]::ExpandEnvironmentVariables($cachedPath)
                if (Test-Path -LiteralPath $expanded -PathType Leaf) { return $expanded }
            }
        }
    } catch {
        # Non-fatal: cache read failed (locked, corrupt, encoding) — fall through
    }

    # 2. Well-known Windows install locations
    $wellKnown = @(
        (Join-Path $env:APPDATA "agency\CurrentVersion\agency.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\agency\agency.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\agency.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\agency.exe")
    )
    foreach ($p in $wellKnown) {
        if (Test-Path -LiteralPath $p -PathType Leaf) { return $p }
    }

    # 3. Try PATH lookup (may fail if PATH is corrupted)
    $found = Get-Command agency -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }

    # 4. Bare fallback — let the shell try to find it
    return "agency"
}

# --- Logging ---

function Write-TaskLog {
    param(
        [string]$TaskId,
        [string]$Event,
        [string]$Status = "",
        [string]$Duration = "",
        [string]$Message = ""
    )
    $logPath = Join-Path $LogsDir "task-$TaskId.log"
    $timestamp = [datetime]::UtcNow.ToString("o")
    $parts = @("[${timestamp}]", $Event, "| task=$TaskId")
    if ($Status) { $parts += "| status=$Status" }
    if ($Duration) { $parts += "| duration=$Duration" }
    if ($Message) { $parts += "| $Message" }
    $line = $parts -join " "
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

# --- Main ---

$taskPath = Join-Path $TasksDir "task-$TaskId.json"
if (-not (Test-Path $taskPath)) {
    Write-Error "Task file not found: $taskPath"
    exit 1
}

# BOM-safe read: strip UTF-8 BOM if present (see architecture.md lesson #43)
$taskRaw = Get-Content $taskPath -Raw
if ($taskRaw -and $taskRaw[0] -eq [char]0xFEFF) {
    $taskRaw = $taskRaw.TrimStart([char]0xFEFF)
    [System.IO.File]::WriteAllText($taskPath, $taskRaw, [System.Text.UTF8Encoding]::new($false))
    Write-TaskLog -TaskId $TaskId -Event "WARN" -Message "Stripped BOM from task file"
}
$task = $taskRaw | ConvertFrom-Json
$startTime = [datetime]::UtcNow

# Generate a correlation ID for log tracing. This is NOT passed to
# copilot.exe (there is no --session-id flag). Each `agency copilot`
# invocation without --resume automatically starts a fresh session,
# which provides the isolation we need (#215).
$sessionId = [guid]::NewGuid().ToString()

Write-TaskLog -TaskId $TaskId -Event "RUN_START" -Message "trigger=scheduled | session=$sessionId | prompt=$($task.prompt.Substring(0, [Math]::Min(100, $task.prompt.Length)))"

$exitCode = 0
$output = ""
$errorMsg = ""

try {
    $workDir = if ($task.working_directory) { $task.working_directory } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path }
    if (-not (Test-Path $workDir)) {
        throw "Working directory '$workDir' does not exist. Task may have a stale path from a previous workspace import."
    }
    # null timeout_minutes means "use global default" (scheduler:update writes null for blank field).
    # 0 = explicit no-timeout: wait indefinitely for the task to finish.
    $timeoutVal = if ($null -ne $task.timeout_minutes) { [int]$task.timeout_minutes } else { 30 }
    $noTimeout = ($timeoutVal -eq 0)
    # Clamp to avoid Int32 overflow in WaitForExit(ms): 2,147,483 * 1000 < Int32.MaxValue
    $timeoutSec = if ($noTimeout) { 0 } else { if ([long]$timeoutVal * 60 -gt 2147483) { 2147483 } else { [int]$timeoutVal * 60 } }

    # Build the Agency command.
    # NOTE: $sessionId is for log correlation only — not passed to copilot.exe.
    # copilot.exe has no --session-id flag; -s means --silent (#215).
    # A new copilot process with no --resume flag always starts a fresh session,
    # which is sufficient isolation for scheduled task runs.
    $escapedPrompt = $task.prompt -replace '"', '\"'
    # Redirect output to files instead of pipes to avoid PTY requirement and
    # handle leaks from child processes inheriting pipe handles (issue #193).
    $runLogFile = Join-Path $LogsDir "task-$TaskId-run.log"
    $runErrFile = Join-Path $LogsDir "task-$TaskId-run.err"
    $cliBinary = Resolve-CliBinary
    # Use & operator with quoted path so paths containing spaces resolve correctly
    $fullCommand = "Set-Location '$workDir'; & '$cliBinary' copilot -p `"$escapedPrompt`" > '$runLogFile' 2> '$runErrFile'"

    # Use -EncodedCommand so prompt text (parentheses, quotes, pipes) is
    # never parsed as PowerShell code.
    $encodedBytes = [System.Text.Encoding]::Unicode.GetBytes($fullCommand)
    $encodedCommand = [Convert]::ToBase64String($encodedBytes)

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $PwshExe
    $processInfo.Arguments = "-ExecutionPolicy Bypass -NonInteractive -EncodedCommand $encodedCommand"
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.WorkingDirectory = $workDir

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processInfo

    $process.Start() | Out-Null

    $exited = if ($noTimeout) {
        # No timeout — wait indefinitely for the process to finish.
        $process.WaitForExit()
        $true
    } else {
        $process.WaitForExit($timeoutSec * 1000)
    }

    if (-not $exited) {
        # Timeout -- kill the process tree (parent + children) to avoid orphans
        $errorMsg = "Task timed out after $($task.timeout_minutes) minutes"
        $exitCode = 124
        try {
            # Kill child processes first (e.g. Agency CLI, copilot.exe)
            $childProcs = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($process.Id)" -ErrorAction SilentlyContinue)
            foreach ($cp in $childProcs) {
                try { Stop-Process -Id $cp.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
            }
            $process.Kill()
        } catch {}
        Write-TaskLog -TaskId $TaskId -Event "TIMEOUT" -Message "$errorMsg (killed process tree: $($childProcs.Count) children)"
    } else {
        $exitCode = $process.ExitCode
    }

    # Kill orphaned child processes that may hold output file handles open.
    # agency.exe spawns children that inherit handles; waiting for them to
    # exit naturally can block or produce stale file locks (issue #193).
    try {
        $childProcs = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($process.Id)" -ErrorAction SilentlyContinue)
        foreach ($cp in $childProcs) {
            try { Stop-Process -Id $cp.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
    } catch {}

    # Read output from files — no pipe handle leaks possible (issue #193).
    $output = ""
    $stderrOutput = ""
    if (Test-Path $runLogFile) { $output = Get-Content $runLogFile -Raw -ErrorAction SilentlyContinue }
    if (Test-Path $runErrFile) { $stderrOutput = Get-Content $runErrFile -Raw -ErrorAction SilentlyContinue }
    if (-not $output) { $output = "" }
    if (-not $stderrOutput) { $stderrOutput = "" }

    # Cleanup run output files
    Remove-Item $runLogFile -Force -ErrorAction SilentlyContinue
    Remove-Item $runErrFile -Force -ErrorAction SilentlyContinue

    if ($exitCode -ne 0 -and -not $errorMsg) {
        $errorMsg = if ($stderrOutput.Trim()) { $stderrOutput.Trim() } else { "Exit code: $exitCode" }
    }

    $process.Dispose()

} catch {
    $errorMsg = $_.Exception.Message
    $exitCode = 1
}

$endTime = [datetime]::UtcNow
$duration = $endTime - $startTime
$durationStr = "{0:N0}s" -f $duration.TotalSeconds

# Determine result summary
$status = if ($exitCode -eq 0 -and -not $errorMsg) { "success" } else { "error" }
$resultSummary = if ($status -eq "error") {
    "Error: $($errorMsg.Substring(0, [Math]::Min(200, $errorMsg.Length)))"
} elseif ($output) {
    $output.Trim().Substring(0, [Math]::Min(200, $output.Trim().Length))
} else {
    "Completed"
}

Write-TaskLog -TaskId $TaskId -Event "RUN_END" -Status $status -Duration $durationStr -Message "session=$sessionId | result=$resultSummary"

# --- Update Task JSON (with retry and file locking) ---

$maxRetries = 3
$retryDelay = 1  # seconds
for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
    try {
        # Acquire exclusive file lock to prevent concurrent read-modify-write
        $lockStream = [System.IO.File]::Open($taskPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        try {
            $reader = [System.IO.StreamReader]::new($lockStream, [System.Text.Encoding]::UTF8, $true, 4096, $true)  # leaveOpen
            $jsonText = $reader.ReadToEnd()
            $reader.Dispose()
            $task = $jsonText | ConvertFrom-Json

            $task.last_run = $endTime.ToString("o")
            $task.last_result = $resultSummary
            $task.run_count = [int]$task.run_count + 1
            $task.updated_at = $endTime.ToString("o")

            if ($status -eq "error") {
                $task.error_count = [int]$task.error_count + 1
                # Auto-pause after 3 consecutive errors
                if ([int]$task.error_count -ge 3) {
                    $task.status = "error_paused"
                    Write-TaskLog -TaskId $TaskId -Event "AUTO_PAUSED" -Message "Paused after $($task.error_count) consecutive errors"
                }
            } else {
                # Reset error count on success
                $task.error_count = 0
            }

            # Calculate next run
            if ($task.schedule_type -eq "once") {
                $task.status = "completed"
                $task.next_run = $null
            } elseif ($task.schedule_type -eq "cron" -or $task.schedule_type -eq "interval") {
                if ($task.status -eq "active") {
                    try {
                        $fields = ($task.schedule_value) -split '\s+'
                        $candidate = [datetime]::UtcNow.AddMinutes(1)
                        $candidate = [datetime]::new($candidate.Year, $candidate.Month, $candidate.Day, $candidate.Hour, $candidate.Minute, 0, [System.DateTimeKind]::Utc)
                        $limit = [datetime]::UtcNow.AddDays(366)
                        $found = $false
                        while ($candidate -lt $limit -and -not $found) {
                            $matchMin = ($fields[0] -eq '*') -or (($fields[0] -split ',') -contains $candidate.Minute.ToString())
                            $matchHour = ($fields[1] -eq '*') -or (($fields[1] -split ',') -contains $candidate.Hour.ToString())
                            $matchDom = ($fields[2] -eq '*') -or (($fields[2] -split ',') -contains $candidate.Day.ToString())
                            $matchMonth = ($fields[3] -eq '*') -or (($fields[3] -split ',') -contains $candidate.Month.ToString())
                            $matchDow = ($fields[4] -eq '*') -or (($fields[4] -split ',') -contains ([int]$candidate.DayOfWeek).ToString())

                            if ($fields[0] -match '^\*/(\d+)$') { $matchMin = ($candidate.Minute % [int]$Matches[1]) -eq 0 }
                            if ($fields[1] -match '^\*/(\d+)$') { $matchHour = ($candidate.Hour % [int]$Matches[1]) -eq 0 }
                            if ($fields[2] -match '^\*/(\d+)$') { $matchDom = (($candidate.Day - 1) % [int]$Matches[1]) -eq 0 }
                            if ($fields[1] -match '^(\d+)-(\d+)$') { $matchHour = ([int]$candidate.Hour -ge [int]$Matches[1]) -and ([int]$candidate.Hour -le [int]$Matches[2]) }
                            if ($fields[4] -match '^(\d+)-(\d+)$') { $matchDow = ([int]$candidate.DayOfWeek -ge [int]$Matches[1]) -and ([int]$candidate.DayOfWeek -le [int]$Matches[2]) }

                            if ($matchMin -and $matchHour -and $matchDom -and $matchMonth -and $matchDow) {
                                $task.next_run = $candidate.ToString("o")
                                $found = $true
                            } else {
                                $candidate = $candidate.AddMinutes(1)
                            }
                        }
                    } catch {
                        Write-TaskLog -TaskId $TaskId -Event "WARN" -Message "Could not calculate next run: $($_.Exception.Message)"
                    }
                }
            }

            # Truncate and rewrite under the same lock
            $lockStream.SetLength(0)
            $lockStream.Position = 0
            $noBom = [System.Text.UTF8Encoding]::new($false)
            $writer = [System.IO.StreamWriter]::new($lockStream, $noBom, 4096, $true)  # leaveOpen, no BOM
            $writer.Write(($task | ConvertTo-Json -Depth 10))
            $writer.Flush()
            $writer.Dispose()
        } finally {
            $lockStream.Close()
        }
        break  # Success -- exit retry loop
    } catch {
        if ($attempt -lt $maxRetries) {
            Write-TaskLog -TaskId $TaskId -Event "WARN" -Message "JSON update attempt $attempt failed (retrying in ${retryDelay}s): $($_.Exception.Message)"
            Start-Sleep -Seconds $retryDelay
            $retryDelay = $retryDelay * 2  # Exponential backoff
        } else {
            Write-TaskLog -TaskId $TaskId -Event "ERROR" -Message "JSON update failed after $maxRetries attempts: $($_.Exception.Message)"
        }
    }
}

exit $exitCode
