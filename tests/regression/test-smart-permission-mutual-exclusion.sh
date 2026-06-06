#!/bin/bash
# Regression guard: Smart permission and YOLO must be mutually exclusive
# Date: 2026-03-19
# Bug: Both smart permission and yolo enabled simultaneously
# Root cause: Missing mutual exclusion logic in save handlers

set -e

APP="ui/src/App.jsx"
MAIN="ui/electron/main.js"
BRIDGE="skills/teams/scripts/monitor/pty-bridge/bridge.js"

# Check App.jsx has mutual exclusion in save handler
if ! grep -q 'smartPermission ? false : yoloMode' "$APP"; then
    echo "FAIL: App.jsx save handler missing smartPermission/yolo mutual exclusion"
    exit 1
fi

# Check main.js saveConfig enforces mutual exclusion
if ! grep -A3 'smartPermission && monitorYoloMode' "$MAIN" | grep -q 'monitorYoloMode = false'; then
    echo "FAIL: main.js saveConfig missing smartPermission/yolo mutual exclusion"
    exit 1
fi

# Check bridge.js set_smart_permission disables yolo
if ! grep -A3 'smartPermissionMode && yoloMode' "$BRIDGE" | grep -q 'yoloMode = false'; then
    echo "FAIL: bridge.js set_smart_permission missing yolo mutual exclusion"
    exit 1
fi

# Check bridge.js set_yolo disables smart permission
if ! grep -A3 'yoloMode && smartPermissionMode' "$BRIDGE" | grep -q 'smartPermissionMode = false'; then
    echo "FAIL: bridge.js set_yolo missing smart permission mutual exclusion"
    exit 1
fi

echo "PASS: Smart permission and YOLO are mutually exclusive across all layers"
