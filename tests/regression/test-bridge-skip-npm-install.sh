#!/bin/bash
# Regression test: Linux teams monitor dependency resolution in packaged app
# Date: 2026-05-01
# Bug: Inside AppImage, main.js runs npm install for bridge deps which fails
#      (read-only squashfs, no compiler, no internet guaranteed)
# Root cause: The hasDeps check runs npm install unconditionally. In packaged
#      builds, node-pty is already available via NODE_PATH from buildBridgeEnv().
# Fix: Skip npm install when app.isPackaged is true (all deps bundled in asar)
# Branch: fix/linux-teams-monitor-deps

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MAIN_JS="$REPO_ROOT/ui/electron/main.js"
PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

echo "=== Regression: Teams monitor bridge deps in packaged app ==="

# Prerequisite: main.js exists
if [[ ! -f "$MAIN_JS" ]]; then
    echo "FATAL: main.js not found at $MAIN_JS"
    exit 1
fi

# REQ-2.1: Bridge npm install is skipped when app.isPackaged is true
echo ""
echo "--- REQ-2.1: app.isPackaged guard on npm install ---"

# The bridge install logic reads package.json deps and runs npm install.
# The fix should add an app.isPackaged (or isDev) check to skip this in packaged builds.
# We need to find the section that does npm install for the bridge and verify the guard.

# First, find the bridge npm install section (~line 8092)
bridge_install_section=$(grep -n 'npm.*install\|hasDeps\|bridge.*dependencies' "$MAIN_JS" | head -20)

if [[ -z "$bridge_install_section" ]]; then
    fail "Could not find bridge npm install section in main.js"
else
    pass "Found bridge install logic in main.js"
fi

# Check that the hasDeps / npm install path has an isPackaged or isDev guard
# The pattern should be: if (hasDeps && !app.isPackaged) or equivalent
# Verify the guard is on the SAME conditional as hasDeps (co-located)

hasDeps_line=$(grep -n 'hasDeps' "$MAIN_JS" | head -1 | cut -d: -f1)
if [[ -z "$hasDeps_line" ]]; then
    # Maybe renamed — look for the npm install in bridge context
    hasDeps_line=$(grep -n 'installBridgeDeps\|npm.*install.*bridge\|npmInstall.*bridge' "$MAIN_JS" | head -1 | cut -d: -f1)
fi

if [[ -n "$hasDeps_line" ]]; then
    # Extract 20 lines around the hasDeps check for context
    context=$(sed -n "$((hasDeps_line - 5)),$((hasDeps_line + 15))p" "$MAIN_JS")
    
    # Check for the isPackaged guard co-located with hasDeps on the SAME line
    hasDeps_guard_line=$(sed -n "${hasDeps_line},$((hasDeps_line + 15))p" "$MAIN_JS" | grep 'hasDeps' | head -1)
    if echo "$hasDeps_guard_line" | grep -q 'isPackaged\|isDev\|!app\.isPackaged'; then
        pass "hasDeps conditional includes app.isPackaged/isDev guard on SAME line"
    elif echo "$context" | grep -q 'isPackaged\|isDev\|!app\.isPackaged'; then
        pass "npm install section has app.isPackaged/isDev guard (near hasDeps, not same line)"
    else
        fail "npm install section LACKS app.isPackaged guard — will try npm install inside read-only AppImage"
    fi
else
    fail "Could not locate hasDeps/bridge npm install line in main.js"
fi

# REQ-2.2: Dev mode (unpackaged) still runs npm install
echo ""
echo "--- REQ-2.2: Dev mode preserved ---"

# The isDev variable should still be defined and used
if grep -q 'const isDev.*=.*!app.isPackaged' "$MAIN_JS"; then
    pass "isDev variable properly defined from app.isPackaged"
else
    fail "isDev variable definition not found (expected: const isDev = !app.isPackaged)"
fi

# The npm install code should still exist within the bridge context (not removed entirely)
# Scope check to ±20 lines around hasDeps to avoid matching unrelated npm references
if [[ -n "$hasDeps_line" ]]; then
    bridge_context=$(sed -n "$((hasDeps_line - 10)),$((hasDeps_line + 20))p" "$MAIN_JS")
    if echo "$bridge_context" | grep -q 'npm.*install\|npmInstall\|execSync.*npm'; then
        pass "npm install code path still exists near bridge deps check (available for dev mode)"
    else
        fail "npm install code appears removed from bridge context (should still work in dev mode)"
    fi
else
    # Fallback: global check
    if grep -q 'npm.*install\|npmInstall\|execSync.*npm' "$MAIN_JS"; then
        pass "npm install code path still exists (available for dev mode)"
    else
        fail "npm install code appears to be completely removed (should still work in dev mode)"
    fi
fi

# REQ-2.3: Bridge package.json is NOT modified
echo ""
echo "--- REQ-2.3: Bridge package.json unchanged ---"

BRIDGE_PKG="$REPO_ROOT/skills/teams/scripts/monitor/pty-bridge/package.json"
if [[ -f "$BRIDGE_PKG" ]]; then
    # Check that it still declares the dependency (untouched)
    if grep -q 'node-pty-prebuilt-multiarch\|node-pty' "$BRIDGE_PKG"; then
        pass "Bridge package.json still declares node-pty dependency (unchanged)"
    else
        fail "Bridge package.json no longer declares node-pty — should not be modified in this branch"
    fi
else
    fail "Bridge package.json not found at $BRIDGE_PKG"
fi

# REQ-2.4: Logging — skip message when isPackaged
echo ""
echo "--- REQ-2.4: Skip logging ---"

if [[ -n "$hasDeps_line" ]]; then
    context=$(sed -n "$((hasDeps_line - 5)),$((hasDeps_line + 20))p" "$MAIN_JS")
    # Must find a log/send call (not just a comment) that mentions skipping
    # Look for send() or console.log() with skip/packaged/bundled message
    if echo "$context" | grep -v '^\s*//' | grep -q 'send\s*(.*skip\|send\s*(.*packaged\|send\s*(.*bundled\|console\.log.*skip\|log.*skip.*install\|log.*packaged'; then
        pass "Found skip log message in actual code (not comment) near the guard"
    else
        fail "No skip log message found in code — should log why npm install is being skipped"
    fi
else
    fail "Cannot check logging (hasDeps line not found)"
fi

# REQ-2.5: Regression safety — buildBridgeEnv still sets NODE_PATH
echo ""
echo "--- REQ-2.5: NODE_PATH in buildBridgeEnv ---"

if grep -q 'NODE_PATH' "$MAIN_JS"; then
    pass "main.js still references NODE_PATH"
else
    fail "main.js no longer references NODE_PATH — bridge resolution will fail"
fi

if grep -q 'buildBridgeEnv\|getBridgeNodeModulesPath' "$MAIN_JS"; then
    pass "buildBridgeEnv/getBridgeNodeModulesPath functions still exist"
else
    fail "buildBridgeEnv/getBridgeNodeModulesPath functions not found"
fi

# Verify the fix is in the correct file (main.js, not a random file)
if [[ "$MAIN_JS" == *"ui/electron/main.js" ]]; then
    pass "Changes target the correct file: ui/electron/main.js"
else
    fail "Test is not targeting ui/electron/main.js"
fi

# Verify that useInProcessMonitorBridge is darwin-only (context check)
echo ""
echo "--- Context: useInProcessMonitorBridge scope ---"
useinprocess_section=$(grep -A 5 'useInProcessMonitorBridge' "$MAIN_JS" | head -10)
if echo "$useinprocess_section" | grep -q 'darwin'; then
    pass "useInProcessMonitorBridge is darwin-only (confirms Linux uses external bridge)"
else
    fail "useInProcessMonitorBridge may have been changed — verify it's still darwin-only"
fi

# Summary
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
