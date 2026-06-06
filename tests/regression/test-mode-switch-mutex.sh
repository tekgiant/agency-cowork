#!/bin/bash
# Regression guard: task:setMode must be serialized with a per-task mutex
# Date: 2026-04-06
# Bug: Concurrent setMode calls interleaved Shift+Tab writes and meta.ptyMode reads,
#      causing chaotic cycling — PTY received 6+ tabs in <1s and landed on wrong mode.
# Root cause: No mutex on the async mode-switch loop; re-entrant calls shared meta.ptyMode.
# Fix: meta._modeSwitchChain promise chain serializes all setMode calls per task.
# Reference: architecture.md Lesson #46

set -e

FILE="ui/electron/main.js"

# 1. Mutex pattern must exist: _modeSwitchChain
if ! grep -q '_modeSwitchChain' "$FILE"; then
    echo "FAIL: task:setMode missing _modeSwitchChain mutex in $FILE"
    exit 1
fi

# 2. The chain must be initialized defensively (|| Promise.resolve())
if ! grep -q '_modeSwitchChain.*Promise\.resolve' "$FILE"; then
    echo "FAIL: _modeSwitchChain not initialized with Promise.resolve() fallback in $FILE"
    exit 1
fi

# 3. MODE_STEP_DELAY_MS must be >= 2000ms to allow JSONL to arrive
DELAY=$(grep -o 'MODE_STEP_DELAY_MS = [0-9]*' "$FILE" | grep -o '[0-9]*')
if [ -z "$DELAY" ]; then
    echo "FAIL: MODE_STEP_DELAY_MS constant not found in $FILE"
    exit 1
fi
if [ "$DELAY" -lt 2000 ]; then
    echo "FAIL: MODE_STEP_DELAY_MS=$DELAY is too low (must be >= 2000ms to give JSONL time to arrive)"
    exit 1
fi

# 4. _pendingModeSwitch must NOT be set inside the setMode for-loop
# (it causes false positives from LLM output containing mode keywords)
# Check: no line sets _pendingModeSwitch=true within a block that also sends shift tabs
PENDING_IN_LOOP=$(awk '/ipcMain\.handle\("task:setMode"/, /Slash fallback/' "$FILE" | grep '_pendingModeSwitch = true' | wc -l)
if [ "$PENDING_IN_LOOP" -gt 0 ]; then
    echo "FAIL: _pendingModeSwitch = true found inside task:setMode loop — causes false positives from LLM output"
    exit 1
fi

echo "PASS: task:setMode has mutex (_modeSwitchChain), delay >= 2000ms, no _pendingModeSwitch in loop"
