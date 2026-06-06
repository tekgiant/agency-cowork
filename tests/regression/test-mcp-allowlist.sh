#!/bin/bash
# Regression test: MCP refresh ALLOWED_COMMANDS must include all server command types
# Date: 2026-03-11
# Bug: MCP reload went from 4/4 to 0/4 — agency command was blocked by allowlist
# Root cause: ALLOWED_COMMANDS Set didn't include "agency" or "qmd"
# Fix: Added agency, qmd to the Set. bash handled separately with path validation.
# Commit: 2bbdd6a

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MAIN="$REPO_ROOT/ui/electron/main.js"

echo "=== Regression: MCP allowlist check ==="

# Every command used in mcp-config templates must be in ALLOWED_COMMANDS
# Note: bash is NOT in ALLOWED_COMMANDS — it's handled by a separate path-validation check
# that restricts bash to scripts under ~/.agency-cowork/ only
required_commands=("agency" "qmd" "node" "npx" "python" "python3")

for cmd in "${required_commands[@]}"; do
    if ! grep -q "ALLOWED_COMMANDS.*\"$cmd\"" "$MAIN"; then
        echo "FAIL: \"$cmd\" not found in ALLOWED_COMMANDS in main.js"
        grep -n "ALLOWED_COMMANDS" "$MAIN"
        exit 1
    fi
done

# Verify bash is NOT in the allowlist (security: handled by path validation instead)
if grep -q 'ALLOWED_COMMANDS.*"bash"' "$MAIN"; then
    echo "FAIL: \"bash\" should NOT be in ALLOWED_COMMANDS — use path-restricted validation instead"
    exit 1
fi

echo "PASS: All required commands are in ALLOWED_COMMANDS, bash properly restricted"
