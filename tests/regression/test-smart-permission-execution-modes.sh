#!/bin/bash
# Regression guard: EXECUTION_MODES must include "smart" entry
# Date: 2026-03-19
# Bug: Smart permission mode missing from execution mode selector
# Root cause: EXECUTION_MODES array in App.jsx not updated

set -e

FILE="ui/src/App.jsx"

# Check that EXECUTION_MODES contains "smart" id
if ! grep -q 'id: "smart"' "$FILE"; then
    echo "FAIL: EXECUTION_MODES missing 'smart' entry in $FILE"
    exit 1
fi

# Check that ShieldCheck icon exists (used by smart mode)
if ! grep -q 'ShieldCheck:' "$FILE"; then
    echo "FAIL: ShieldCheck icon not defined in $FILE"
    exit 1
fi

# Check smart mode is between autopilot and yolo (ordering matters for UX)
SMART_LINE=$(grep -n 'id: "smart"' "$FILE" | head -1 | cut -d: -f1)
YOLO_LINE=$(grep -n 'id: "yolo"' "$FILE" | head -1 | cut -d: -f1)
if [ "$SMART_LINE" -ge "$YOLO_LINE" ]; then
    echo "FAIL: Smart mode should appear before YOLO mode in EXECUTION_MODES"
    exit 1
fi

echo "PASS: EXECUTION_MODES includes smart mode in correct position"
