#!/bin/bash
# Regression test: ESM modules must not use require()
# Date: 2026-03-11
# Bug: ReferenceError: require is not defined in setup:installDep and setup:verifyAuth
# Root cause: main.js is ESM (import os from "os") but added require("os").homedir()
# Fix: Use already-imported os module instead of require("os")
# Commit: cf250e3

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Regression: ESM no-require check ==="

# main.js should never use require("os") — os is imported at top
count=$(grep -c 'require("os")' "$REPO_ROOT/ui/electron/main.js" 2>/dev/null || true)
count=${count:-0}
if [[ "$count" -gt 0 ]]; then
    echo "FAIL: Found $count instance(s) of require(\"os\") in main.js — ESM files cannot use require()"
    grep -n 'require("os")' "$REPO_ROOT/ui/electron/main.js"
    exit 1
fi

# Check for any require() calls that reference Node built-ins (fs, path, os, child_process)
for mod in os fs path child_process; do
    count=$(grep -c "require(\"$mod\")" "$REPO_ROOT/ui/electron/main.js" 2>/dev/null || true)
    count=${count:-0}
    count=$(echo "$count" | tr -d '[:space:]')
    if [[ "$count" -gt 0 ]]; then
        echo "FAIL: Found require(\"$mod\") in ESM main.js"
        grep -n "require(\"$mod\")" "$REPO_ROOT/ui/electron/main.js"
        exit 1
    fi
done

echo "PASS: No require() calls for built-in modules in ESM main.js"
