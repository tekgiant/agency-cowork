#!/bin/bash
# Regression guard: main.js must forward smart-permission env vars
# Date: 2026-03-19
# Bug: Smart permission env vars not reaching bridge/hook subprocess
# Root cause: buildBridgeEnv() not forwarding BRIDGE_SMART_PERMISSION

set -e

FILE="ui/electron/main.js"

# Check monitorSmartPermission module variable exists
if ! grep -q 'monitorSmartPermission' "$FILE"; then
    echo "FAIL: main.js missing monitorSmartPermission variable"
    exit 1
fi

# Check buildBridgeEnv forwards BRIDGE_SMART_PERMISSION
if ! grep -q 'BRIDGE_SMART_PERMISSION' "$FILE"; then
    echo "FAIL: buildBridgeEnv doesn't set BRIDGE_SMART_PERMISSION"
    exit 1
fi

# Check smart-permission env vars are forwarded (SMART_PERMISSION_MODEL etc.)
if ! grep -q 'SMART_PERMISSION_MODEL' "$FILE"; then
    echo "FAIL: buildBridgeEnv doesn't forward SMART_PERMISSION_MODEL"
    exit 1
fi

# Check CLAUDE_MCP_SAFE forwarded
if ! grep -q 'CLAUDE_MCP_SAFE' "$FILE"; then
    echo "FAIL: buildBridgeEnv doesn't forward CLAUDE_MCP_SAFE"
    exit 1
fi

# Check plugin:ensureSmartPermission IPC handler exists
if ! grep -q 'plugin:ensureSmartPermission' "$FILE"; then
    echo "FAIL: main.js missing plugin:ensureSmartPermission IPC handler"
    exit 1
fi

echo "PASS: main.js properly forwards smart-permission configuration"
