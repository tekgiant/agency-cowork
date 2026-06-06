#!/bin/bash
# Regression test: MCP config merge must never overwrite existing servers
# Date: 2026-03-11
# Bug: Cristian Velez's mcp-config.json was blown away by setup.sh
# Root cause: Initial setup.sh overwrote the file instead of merging
# Fix: Python merge script: "if key not in existing['mcpServers']"
# Reporter: Cristian Velez (Teams, 2026-03-10)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Regression: MCP config merge (not replace) ==="

# setup.sh must contain merge logic (if key not in existing)
if ! grep -q "if key not in existing" "$REPO_ROOT/scripts/setup.sh"; then
    echo "FAIL: setup.sh missing merge guard — could overwrite existing MCP config"
    exit 1
fi

# setup.sh must NOT have bare 'cat > $MCP_CONFIG' without checking if file exists first
# (the pattern should be: write to /tmp first, then merge)
if grep -q "cat > \"\$MCP_CONFIG\"" "$REPO_ROOT/scripts/setup.sh"; then
    echo "FAIL: setup.sh writes directly to MCP_CONFIG — should write to /tmp and merge"
    exit 1
fi

echo "PASS: MCP config uses merge-not-replace pattern"
