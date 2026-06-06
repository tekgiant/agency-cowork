#!/bin/bash
# Regression test: packaged monitor PTY must reuse Electron main runtime, and macOS release helpers must stay on the stock DMG + notarization path
# Date: 2026-03-15
# Bug: Packaged Teams monitor PTY failed with posix_spawnp, first monitor prompt shifted behind startup, and the release flow drifted away from the stock electron-builder DMG path the app ships with
# Root cause: Monitor bridge used a separate packaged Electron-as-Node runtime instead of the working Electron main PTY runtime; prompt queue ignored pre-warmed ready sessions; release helpers and regressions drifted out of sync while iterating on DMG experiments
# Commit: pending

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

MAIN="$REPO_ROOT/ui/electron/main.js"
BRIDGE="$REPO_ROOT/skills/teams/scripts/monitor/pty-bridge/bridge.js"
QUEUE="$REPO_ROOT/skills/teams/scripts/monitor/prompt_queue.py"
DMG_SCRIPT="$REPO_ROOT/ui/scripts/create-dmg-manual.sh"
RELEASE_SCRIPT="$REPO_ROOT/ui/scripts/release-mac-manual.sh"
DMG_NOTARIZE="$REPO_ROOT/ui/scripts/notarize-dmg.sh"

echo "=== Regression: packaged monitor + macOS DMG path ==="

if ! grep -q 'function useInProcessMonitorBridge()' "$MAIN"; then
  echo "FAIL: main.js no longer selects an in-process monitor bridge for packaged macOS builds"
  exit 1
fi

if ! grep -q 'function hasResidentBackgroundActivity()' "$MAIN"; then
  echo "FAIL: main.js no longer separates resident background work from passive scheduler state"
  exit 1
fi

if ! grep -q 'return monitorConnected;' "$MAIN"; then
  echo "FAIL: main.js no longer limits macOS keep-alive behavior to the live Teams monitor"
  exit 1
fi

if ! grep -q 'globalThis.__AGENCY_SHARED_PTY = pty' "$MAIN"; then
  echo "FAIL: main.js no longer shares the Electron main PTY instance with the monitor bridge"
  exit 1
fi

if ! grep -q 'const BRIDGE_DISCOVERY_FILE = path.join(os.homedir(), ".agency-cowork", "pty-bridge.json")' "$MAIN"; then
  echo "FAIL: main.js no longer tracks bridge ownership through the discovery file"
  exit 1
fi

if grep -q 'mainWindow.?\.webContents\.send("monitor:' "$MAIN"; then
  echo "FAIL: main.js reintroduced unsafe direct renderer sends for monitor IPC events"
  exit 1
fi

if ! grep -q 'PTY bridge owner mismatch' "$MAIN"; then
  echo "FAIL: main.js no longer rejects attaching to a stale bridge owner"
  exit 1
fi

if ! grep -q 'path.join(teamsDir, "monitor", "monitor.pid")' "$MAIN"; then
  echo "FAIL: main.js no longer checks the Python monitor PID file in skills/teams/monitor/monitor.pid"
  exit 1
fi

if ! grep -q 'globalThis.__AGENCY_SHARED_PTY' "$BRIDGE"; then
  echo "FAIL: bridge.js no longer accepts the shared PTY instance from Electron main"
  exit 1
fi

if ! grep -q 'READY_FOOTER_RE' "$BRIDGE"; then
  echo "FAIL: bridge.js no longer recognizes resumed-session footer output as a ready signal"
  exit 1
fi

if ! grep -q 'elapsedMs >= 5000 && hasPromptHint' "$BRIDGE"; then
  echo "FAIL: bridge.js no longer allows resumed sessions to become ready from prompt/footer output"
  exit 1
fi

if ! grep -q 'Adopting pre-warmed ready session' "$QUEUE"; then
  echo "FAIL: prompt_queue.py no longer adopts pre-warmed ready sessions"
  exit 1
fi

if ! grep -q 'startup_grace_until = 0.0' "$QUEUE"; then
  echo "FAIL: prompt_queue.py no longer clears startup grace for adopted ready sessions"
  exit 1
fi

if grep -q 'set background picture' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh reintroduced a custom Finder background"
  exit 1
fi

if ! grep -q 'system-default window appearance' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh no longer resets Finder metadata for default styling"
  exit 1
fi

if ! grep -q 'ICON_ROW_Y=190' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh no longer keeps the DMG icons vertically centered"
  exit 1
fi

if ! grep -q 'APPLICATIONS_ICON_X=390' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh no longer uses the centered Applications icon position"
  exit 1
fi

if ! grep -q 'xcrun notarytool submit' "$DMG_NOTARIZE"; then
  echo "FAIL: notarize-dmg.sh no longer submits the DMG container for notarization"
  exit 1
fi

if ! grep -q 'codesign --force --sign' "$DMG_NOTARIZE"; then
  echo "FAIL: notarize-dmg.sh no longer signs the DMG container before notarization"
  exit 1
fi

if ! grep -q 'electron-builder --mac dmg' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer uses the stock electron-builder DMG path"
  exit 1
fi

if grep -q 'background.*dmg-background' "$REPO_ROOT/ui/package.json"; then
  echo "FAIL: package.json reintroduced a custom DMG background"
  exit 1
fi

echo "PASS: Packaged monitor runtime and macOS DMG release safeguards are present"
