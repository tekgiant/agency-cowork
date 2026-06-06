#!/bin/bash
# Regression test: Task JSON readers must handle UTF-8 BOM
# Date: 2026-03-20
# Bug: StreamWriter with [System.Text.Encoding]::UTF8 writes a 3-byte BOM (EF BB BF).
#      Successive read-modify-write cycles in run-task.ps1 accumulated BOMs, causing
#      "Unexpected token" JSON parse errors in both main.js and scheduler-service.ps1.
# Fix: (1) UTF8Encoding($false) for no-BOM writes, (2) readTaskJson/Read-TaskJson
#      helpers that strip BOM on read and auto-repair files.
# Commit: a55f6d4

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Regression: Task JSON BOM resilience ==="

MAIN="$REPO_ROOT/ui/electron/main.js"
SCHED="$REPO_ROOT/skills/task-scheduler/scripts/scheduler-service.ps1"
RUNTASK="$REPO_ROOT/skills/task-scheduler/scripts/run-task.ps1"

# 1. main.js must have readTaskJson helper
echo -n "  main.js has readTaskJson helper... "
if grep -q 'function readTaskJson' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — readTaskJson helper missing"
  exit 1
fi

# 2. readTaskJson must strip BOM (charCodeAt 0xFEFF)
echo -n "  readTaskJson strips BOM... "
if grep -q '0xFEFF' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — BOM detection missing in readTaskJson"
  exit 1
fi

# 3. scheduler-service.ps1 must have Read-TaskJson helper
echo -n "  scheduler-service.ps1 has Read-TaskJson helper... "
if grep -q 'function Read-TaskJson' "$SCHED"; then
  echo "PASS"
else
  echo "FAIL — Read-TaskJson helper missing"
  exit 1
fi

# 4. Read-TaskJson must strip BOM (0xFEFF)
echo -n "  Read-TaskJson strips BOM... "
if grep -q '0xFEFF' "$SCHED"; then
  echo "PASS"
else
  echo "FAIL — BOM detection missing in Read-TaskJson"
  exit 1
fi

# 5. No raw Get-Content ... | ConvertFrom-Json for task files (all should use Read-TaskJson)
echo -n "  No raw Get-Content|ConvertFrom-Json for task files in scheduler-service... "
# Allowed: appSchedules (schedules.json) uses raw — only task-*.json must use helper
# Allowed: Write-JsonAtomically validation reads tmpPath to verify JSON roundtrip
RAW_READS=$(grep -n 'Get-Content.*Raw.*ConvertFrom-Json' "$SCHED" | grep -v 'AppSchedules' | grep -v 'tmpPath' | wc -l)
if [ "$RAW_READS" -eq 0 ]; then
  echo "PASS"
else
  echo "FAIL — $RAW_READS raw reads remain (should use Read-TaskJson)"
  grep -n 'Get-Content.*Raw.*ConvertFrom-Json' "$SCHED" | grep -v 'AppSchedules'
  exit 1
fi

# 6. run-task.ps1 must use UTF8Encoding($false) for no-BOM writes
echo -n "  run-task.ps1 uses UTF8Encoding(false) for writes... "
if grep -q 'UTF8Encoding.*\$false' "$RUNTASK"; then
  echo "PASS"
else
  echo "FAIL — run-task.ps1 still using BOM-producing encoding"
  exit 1
fi

# 7. run-task.ps1 StreamReader must use leaveOpen
echo -n "  run-task.ps1 StreamReader uses leaveOpen... "
if grep -q 'StreamReader.*leaveOpen\|StreamReader.*\$true' "$RUNTASK"; then
  echo "PASS"
else
  echo "FAIL — StreamReader not using leaveOpen"
  exit 1
fi

echo "=== All task JSON BOM resilience checks passed ==="
