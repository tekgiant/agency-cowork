#!/bin/bash
# Regression guard: bridge.js must handle smart-permission mode
# Date: 2026-03-19
# Bug: Bridge injects /yolo even when smart permission is active
# Root cause: Missing smartPermissionMode guard in /yolo injection path

set -e

FILE="skills/teams/scripts/monitor/pty-bridge/bridge.js"

# Check BRIDGE_SMART_PERMISSION env var is read
if ! grep -q 'BRIDGE_SMART_PERMISSION' "$FILE"; then
    echo "FAIL: bridge.js doesn't read BRIDGE_SMART_PERMISSION env var"
    exit 1
fi

# Check smartPermissionMode variable exists
if ! grep -q 'smartPermissionMode' "$FILE"; then
    echo "FAIL: bridge.js missing smartPermissionMode variable"
    exit 1
fi

# Check /yolo injection has smart permission guard
if ! grep -q '!smartPermissionMode' "$FILE"; then
    echo "FAIL: /yolo injection path missing smartPermissionMode guard"
    exit 1
fi

# Check set_smart_permission pipe command exists
if ! grep -q 'set_smart_permission' "$FILE"; then
    echo "FAIL: bridge.js missing set_smart_permission pipe command"
    exit 1
fi

echo "PASS: bridge.js handles smart-permission mode correctly"
