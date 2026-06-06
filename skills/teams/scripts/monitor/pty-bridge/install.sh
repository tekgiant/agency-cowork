#!/usr/bin/env bash
# Install script for the PTY bridge (macOS/Linux)
# Usage: bash install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Agency PTY Bridge — Install ==="

# Verify node is available
if ! command -v node &>/dev/null; then
  echo "ERROR: Node.js not found on PATH."
  echo "Install Node.js 18+ from https://nodejs.org or via your package manager."
  exit 1
fi

NODE_VERSION=$(node -v)
echo "Node.js version: $NODE_VERSION"

# Install dependencies
echo "Installing dependencies..."
npm install --production --no-audit --no-fund 2>&1

echo ""
echo "✓ PTY bridge installed successfully."
echo "  Start with: node bridge.js"
echo "  Or via the Electron UI Monitor panel."
