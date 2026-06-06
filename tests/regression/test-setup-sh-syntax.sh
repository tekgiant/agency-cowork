#!/bin/bash
# Regression test: setup.sh must be syntactically valid
# Date: 2026-03-11
# Bug: Cristian reported unterminated line near "setup complete" banner
# Root cause: Likely Unicode quotes or encoding issues in echo statements
# Fix: Validated and cleaned up end-of-file echo statements
# Reporter: Cristian Velez (Teams, 2026-03-10)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Regression: setup.sh syntax check ==="

# bash -n checks syntax without executing
if ! bash -n "$REPO_ROOT/scripts/setup.sh" 2>/tmp/setup-syntax-err; then
    echo "FAIL: setup.sh has syntax errors:"
    cat /tmp/setup-syntax-err
    exit 1
fi

# Also check setup.ps1 for basic issues (if pwsh is available)
if command -v pwsh &>/dev/null; then
    if ! pwsh -Command "Get-Content '$REPO_ROOT/scripts/setup.ps1' | Out-Null" 2>/dev/null; then
        echo "WARN: setup.ps1 may have encoding issues"
    fi
fi

echo "PASS: setup.sh is syntactically valid"
