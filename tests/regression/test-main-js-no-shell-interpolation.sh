#!/bin/bash
# Date: 2026-03-17
# Bug: Security review found shell interpolation in Electron helpers and unauthenticated debug write access.
# Root cause: main.js used execSync template literals for taskkill/Azure CLI/monitor service stop, and debug HTTP routes had no token gate.
# Reference: PR #62

set -euo pipefail

cd "$(dirname "$0")/../.."

MAIN_JS="ui/electron/main.js"

if grep -nE 'execSync\(`.*\$\{' "$MAIN_JS"; then
  echo "FAIL: main.js still contains interpolated execSync template literals"
  exit 1
fi

if ! grep -nE 'function hasValidDebugToken' "$MAIN_JS" >/dev/null; then
  echo "FAIL: debug token guard missing"
  exit 1
fi

if ! grep -nE 'error: "unauthorized"' "$MAIN_JS" >/dev/null; then
  echo "FAIL: debug API unauthorized response missing"
  exit 1
fi

echo "PASS: no interpolated execSync calls and debug API requires auth token"
