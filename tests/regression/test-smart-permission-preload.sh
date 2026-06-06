#!/bin/bash
# Regression guard: preload.js must expose ensureSmartPermission IPC
# Date: 2026-03-19
# Bug: UI cannot trigger plugin installation
# Root cause: Missing IPC bridge in preload.js

set -e

FILE="ui/electron/preload.js"

# Check ensureSmartPermission is exposed to renderer
if ! grep -q 'ensureSmartPermission' "$FILE"; then
    echo "FAIL: preload.js doesn't expose ensureSmartPermission"
    exit 1
fi

echo "PASS: preload.js exposes smart-permission plugin management"
