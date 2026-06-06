#!/bin/bash
# Regression guard: agentconfig.json must have smartPermission section
# Date: 2026-03-19
# Bug: Smart permission config missing from agentconfig
# Root cause: agentconfig.json template not updated with smartPermission section

set -e

FILE="agentconfig.json"

# Check smartPermission top-level section exists
if ! grep -q '"smartPermission"' "$FILE"; then
    echo "FAIL: agentconfig.json missing 'smartPermission' section"
    exit 1
fi

# Check monitor section has smartPermission flag
if ! grep -A10 '"monitor"' "$FILE" | grep -q '"smartPermission"'; then
    echo "FAIL: monitor section missing 'smartPermission' flag"
    exit 1
fi

# Check mcpSafe has at least some MCP tool mappings
if ! grep -q '"mcpSafe":' "$FILE"; then
    echo "FAIL: smartPermission.mcpSafe not defined"
    exit 1
fi

# Check mcpAsk has at least some MCP tool mappings
if ! grep -q '"mcpAsk":' "$FILE"; then
    echo "FAIL: smartPermission.mcpAsk not defined"
    exit 1
fi

echo "PASS: agentconfig.json has smartPermission section with MCP mappings"
