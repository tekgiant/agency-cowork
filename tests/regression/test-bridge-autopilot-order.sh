#!/bin/bash
# Regression test: applyMonitorYoloMode() must be called BEFORE startMonitorBridge()
# Date: 2026-03-29
# Bug: Bridge spawned with BRIDGE_AUTOPILOT=0 despite agentconfig.json having autopilotMode: true
# Root cause: autoStartMonitorService() called startMonitorBridge() before applyMonitorYoloMode(),
#   so module-level vars were still at defaults when buildBridgeEnv() read them for env vars.
#   Settings only arrived ~17min later via pipe commands — too late, sessions already stuck.
# Fix: Move applyMonitorYoloMode() call to before the bridge spawn in autoStartMonitorService()
# PR: #166

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MAIN_JS="$REPO_ROOT/ui/electron/main.js"

echo "=== Regression: Bridge autopilot ordering check ==="

# Test 1: In autoStartMonitorService(), applyMonitorYoloMode must appear BEFORE startMonitorBridge
# Extract the function body and check line ordering
apply_line=$(grep -n "applyMonitorYoloMode" "$MAIN_JS" | grep -v "function\|setTimeout\|//\|async function" | head -1 | cut -d: -f1)
bridge_line=$(grep -n "startMonitorBridge" "$MAIN_JS" | grep -v "function\|//\|return " | head -1 | cut -d: -f1)

if [[ -z "$apply_line" || -z "$bridge_line" ]]; then
    echo "FAIL: Could not find applyMonitorYoloMode or startMonitorBridge calls in main.js"
    exit 1
fi

if [[ "$apply_line" -gt "$bridge_line" ]]; then
    echo "FAIL: applyMonitorYoloMode() (line $apply_line) is called AFTER startMonitorBridge() (line $bridge_line)"
    echo "  applyMonitorYoloMode MUST be called first so BRIDGE_AUTOPILOT env vars are set at spawn time"
    exit 1
fi

echo "  PASS: applyMonitorYoloMode (line $apply_line) is before startMonitorBridge (line $bridge_line)"

# Test 2: buildBridgeEnv must reference the module-level autopilot/yolo/approve variables
for var in "monitorYoloMode" "monitorAutopilotMode" "monitorAutoApprove"; do
    if ! grep -q "$var" "$MAIN_JS"; then
        echo "FAIL: buildBridgeEnv does not reference $var"
        exit 1
    fi
done
echo "  PASS: buildBridgeEnv references all three module-level autonomy variables"

# Test 3: BRIDGE_AUTOPILOT, BRIDGE_YOLO, BRIDGE_AUTO_APPROVE must be set in buildBridgeEnv
for envvar in "BRIDGE_YOLO" "BRIDGE_AUTOPILOT" "BRIDGE_AUTO_APPROVE"; do
    if ! grep -q "$envvar" "$MAIN_JS"; then
        echo "FAIL: $envvar not found in main.js (must be set in buildBridgeEnv)"
        exit 1
    fi
done
echo "  PASS: All three BRIDGE_* env vars are set in buildBridgeEnv"

# Test 4: There should be no code path where startMonitorBridge is called without
# applyMonitorYoloMode being called first. Check all call sites.
all_bridge_calls=$(grep -n "startMonitorBridge(" "$MAIN_JS" | grep -v "function\|//\|return " | cut -d: -f1)
all_apply_calls=$(grep -n "applyMonitorYoloMode()" "$MAIN_JS" | grep -v "function\|setTimeout\|//\|async function" | cut -d: -f1)

fail=0
for bl in $all_bridge_calls; do
    # Find the nearest applyMonitorYoloMode call before this bridge call
    found_before=0
    for al in $all_apply_calls; do
        if [[ "$al" -lt "$bl" ]]; then
            found_before=1
        fi
    done
    if [[ "$found_before" -eq 0 ]]; then
        echo "FAIL: startMonitorBridge at line $bl has no preceding applyMonitorYoloMode call"
        fail=1
    fi
done

if [[ "$fail" -eq 1 ]]; then
    exit 1
fi
echo "  PASS: All startMonitorBridge calls have a preceding applyMonitorYoloMode call"

echo ""
echo "All bridge autopilot ordering checks passed."
