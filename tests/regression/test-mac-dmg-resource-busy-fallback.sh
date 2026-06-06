#!/bin/bash
# Regression test: macOS release helper must fall back cleanly when Electron Builder's dmgbuild leaves a busy mounted image behind
# Date: 2026-03-16
# Bug: macOS release builds signed and notarized the .app successfully, then failed at the DMG step with `Unable to detach device cleanly: hdiutil couldn't unmount diskX - Resource busy`
# Root cause: stock dmgbuild detach was flaky on macOS 15.3, and the helper did not automatically reuse the signed app via the manual DMG path; x64 helper paths also drifted from Electron Builder's real output names
# Commit: pending

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RELEASE_SCRIPT="$REPO_ROOT/ui/scripts/release-mac-manual.sh"
DMG_SCRIPT="$REPO_ROOT/ui/scripts/create-dmg-manual.sh"

echo "=== Regression: macOS DMG resource-busy fallback ==="

if ! grep -q 'Unable to detach device cleanly' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer detects the dmgbuild detach failure signature"
  exit 1
fi

if ! grep -q 'Resource busy' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer detects the busy-device detach failure"
  exit 1
fi

if ! grep -q 'create-dmg-manual.sh' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer falls back to create-dmg-manual.sh"
  exit 1
fi

if ! grep -q 'cleanup_temp_dmgs' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer removes temporary DMG artifacts before fallback"
  exit 1
fi

if ! grep -q 'detach_leftover_volumes' "$RELEASE_SCRIPT"; then
  echo "FAIL: release-mac-manual.sh no longer detaches leftover Agency Cowork volumes before fallback"
  exit 1
fi

if ! grep -q 'APP_DIR="release/mac"' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh no longer maps x64 builds to Electron Builder's release/mac app directory"
  exit 1
fi

if ! grep -q 'DMG_PATH="release/${APP_NAME}-${VERSION}.dmg"' "$DMG_SCRIPT"; then
  echo "FAIL: create-dmg-manual.sh no longer writes the x64 DMG to the stock unsuffixed filename"
  exit 1
fi

echo "PASS: macOS DMG fallback and x64 path safeguards are present"