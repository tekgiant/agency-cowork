#!/usr/bin/env bash
# Regression test: Scheduler robustness improvements (Phase 2)
# Date: 2026-03-20
# Validates: atomic JSON writes, heartbeat, dispatch timeout, process tree kill,
#            stream read timeout, dispatch audit JSONL, diagnose command, watchdog backoff
# Related: architecture.md lesson #44

set -uo pipefail
PASS=0; FAIL=0
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS: $desc"; ((PASS++)) || true
  else
    echo "  FAIL: $desc"; ((FAIL++)) || true
  fi
}

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCHED="$REPO_ROOT/skills/task-scheduler/scripts/scheduler-service.ps1"
RUN="$REPO_ROOT/skills/task-scheduler/scripts/run-task.ps1"
MGR="$REPO_ROOT/skills/task-scheduler/scripts/task-manager.ps1"
MAIN="$REPO_ROOT/ui/electron/main.js"

echo "=== Scheduler Robustness Regression Tests ==="

# --- T1: Atomic JSON writes ---
echo ""
echo "--- T1: Atomic JSON writes ---"
check "Write-JsonAtomically function exists" grep -q 'function Write-JsonAtomically' "$SCHED"
check "Write-JsonAtomically writes to .tmp" grep -q '\.tmp' "$SCHED"
check "Write-JsonAtomically validates JSON roundtrip" grep -q 'ConvertFrom-Json' "$SCHED"
check "Write-JsonAtomically keeps .bak backup" grep -q '\.bak' "$SCHED"
check "No bare Set-Content for task JSON" bash -c "! grep -P 'ConvertTo-Json.*Set-Content' '$SCHED'"

# --- T2: Heartbeat file ---
echo ""
echo "--- T2: Heartbeat file ---"
check "HeartbeatFile variable defined" grep -q 'scheduler\.heartbeat\.json' "$SCHED"
check "Heartbeat writes PID and timestamp" grep -q 'pid.*=.*\$PID' "$SCHED"
check "Heartbeat writes pollCount" grep -q 'pollCount' "$SCHED"
check "Heartbeat cleanup on exit" grep -q 'HeartbeatFile' "$SCHED"

# --- T3: Service-level dispatch timeout ---
echo ""
echo "--- T3: Service-level dispatch timeout ---"
check "Uses -PassThru without -Wait" grep -q '\-PassThru -NoNewWindow' "$SCHED"
check "No Start-Process -Wait for task dispatch" bash -c "! grep -P 'Start-Process.*-Wait.*run-task' '$SCHED'"
check "WaitForExit with timeout" grep -q 'WaitForExit(' "$SCHED"
check "taskTimeoutSec calculated from timeout_minutes" grep -q 'timeout_minutes.*\+ 10' "$SCHED"

# --- T4: Process tree kill ---
echo ""
echo "--- T4: Process tree kill ---"
check "run-task.ps1 kills child processes via CIM" grep -q 'Get-CimInstance Win32_Process.*ParentProcessId' "$RUN"
check "scheduler-service.ps1 kills child processes on timeout" grep -q 'Get-CimInstance Win32_Process.*ParentProcessId' "$SCHED"

# --- T5: Stream read timeout ---
echo ""
echo "--- T5: Stream read timeout ---"
check "stdoutTask.Wait with timeout" grep -q 'stdoutTask\.Wait(5000)' "$RUN"
check "stderrTask.Wait with timeout" grep -q 'stderrTask\.Wait(5000)' "$RUN"
check "No bare .Result without Wait guard" grep -q 'Wait(5000).*Result' "$RUN"

# --- T6: Dispatch audit log ---
echo ""
echo "--- T6: Dispatch audit log ---"
check "DispatchLog path defined" grep -q 'dispatch\.jsonl' "$SCHED"
check "Write-DispatchEntry function exists" grep -q 'function Write-DispatchEntry' "$SCHED"
check "Dispatch entry written on completion" grep -q "Write-DispatchEntry.*COMPLETED" "$SCHED"
check "Dispatch entry written on failure" grep -q "Write-DispatchEntry.*FAILED" "$SCHED"
check "Dispatch entry written on timeout" grep -q "Write-DispatchEntry.*TIMEOUT" "$SCHED"

# --- T7: Diagnose command ---
echo ""
echo "--- T7: Diagnose command ---"
check "diagnose in ValidateSet" grep -q '"diagnose"' "$MGR"
check "Invoke-Diagnose function exists" grep -q 'function Invoke-Diagnose' "$MGR"
check "Diagnose checks heartbeat" grep -q 'heartbeat' "$MGR"
check "Diagnose checks stale locks" grep -q 'staleLocks\|stale' "$MGR"
check "Diagnose checks dispatch errors" grep -q 'dispatch\.jsonl' "$MGR"
check "Diagnose checks Agency CLI" grep -q 'Agency CLI' "$MGR"

# --- T8: Watchdog exponential backoff ---
echo ""
echo "--- T8: Watchdog exponential backoff ---"
check "Backoff array in main.js" grep -q 'WATCHDOG_BACKOFF_SEC' "$MAIN"
check "Watchdog checks heartbeat file" grep -q 'scheduler\.heartbeat\.json' "$MAIN"
check "lastRestartAt tracked" grep -q 'lastRestartAt' "$MAIN"
check "Backoff delay enforced" grep -q 'timeSinceLastRestart.*backoffSec' "$MAIN"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
