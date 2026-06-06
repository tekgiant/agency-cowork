#!/bin/bash
# Date: 2026-03-17
# Bug: PR review found file:read allowed reads under ~/ and macOS release scripts accepted arbitrary ARCH values.
# Root cause: Electron file preview scoped reads to home directory, and DMG helper scripts trusted positional ARCH input.
# Reference: PR #62

set -euo pipefail

cd "$(dirname "$0")/../.."

if ! grep -nE 'path outside working directory' ui/electron/main.js >/dev/null; then
  echo "FAIL: file:read is not restricted to working directory"
  exit 1
fi

if grep -nE 'resolved.startsWith\(homeDir' ui/electron/main.js >/dev/null; then
  echo "FAIL: file:read still allows home directory reads"
  exit 1
fi

for file in ui/scripts/release-mac-manual.sh ui/scripts/create-dmg-manual.sh; do
  if ! grep -nE 'case "\$\{ARCH\}" in' "$file" >/dev/null; then
    echo "FAIL: missing ARCH allowlist in $file"
    exit 1
  fi
done

echo "PASS: file reads restricted to workdir and macOS scripts validate ARCH"
