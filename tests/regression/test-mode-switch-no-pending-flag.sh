#!/bin/bash
# Regression guard: _pendingModeSwitch must not be set during mode switch loop
# Date: 2026-04-06
# Bug: Setting _pendingModeSwitch=true during task:setMode loop caused PTY text detection
#      to read mode keywords from LLM output ("...plan for...", "...in autopilot mode...")
#      and corrupt meta.ptyMode mid-switch, causing spurious extra tabs.
# Root cause: PTY text detection scans ALL output — mode keywords appear in agent responses,
#             not just in the TUI status bar. JSONL events are the only reliable mode signal.
# Fix: Never set _pendingModeSwitch inside the setMode for-loop. Rely on JSONL only.
# Reference: architecture.md Lesson #47

set -e

FILE="ui/electron/main.js"

# Extract the task:setMode ipcMain handler body (from the handle registration to the slash fallback)
HANDLER_BODY=$(awk '/ipcMain\.handle\("task:setMode"/, /Slash fallback/' "$FILE")

# 1. _pendingModeSwitch must not be set to true inside the setMode loop
if echo "$HANDLER_BODY" | grep -q '_pendingModeSwitch = true'; then
    echo "FAIL: _pendingModeSwitch = true found inside task:setMode handler body in $FILE"
    echo "      This causes false positives when LLM output contains mode keywords."
    echo "      Rely on JSONL session.mode_changed events instead."
    exit 1
fi

# 2. The comment explaining WHY must exist (documents the invariant)
if ! grep -q '_pendingModeSwitch.*false positives\|false positives.*_pendingModeSwitch\|Do NOT set _pendingModeSwitch' "$FILE"; then
    echo "WARN: No comment explaining why _pendingModeSwitch is not used in task:setMode"
    echo "      Add a comment to prevent future re-introduction of the bug."
fi

# 3. PTY text detection guard: _pendingModeSwitch usage in onData should still exist
#    (it's valid elsewhere, just not in the mode switch loop)
if ! grep -q '_pendingModeSwitch' "$FILE"; then
    echo "FAIL: _pendingModeSwitch removed entirely from $FILE — it is needed for other paths"
    exit 1
fi

echo "PASS: _pendingModeSwitch not set in task:setMode loop; PTY text detection guard preserved elsewhere"
