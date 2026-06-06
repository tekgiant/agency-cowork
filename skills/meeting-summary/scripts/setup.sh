#!/usr/bin/env bash
# Setup script for meeting-summary skill on macOS.
# Installs Playwright and its browser dependencies.
#
# Usage:
#   bash skills/meeting-summary/scripts/setup.sh

set -euo pipefail

echo "=== Meeting Summary Skill — macOS Setup ==="
echo ""

# Check for Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ via Homebrew:"
    echo "  brew install python@3.12"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python: $PYTHON_VERSION"

# Check for pip
if ! python3 -m pip --version &>/dev/null; then
    echo "ERROR: pip not found. Install it with:"
    echo "  python3 -m ensurepip --upgrade"
    exit 1
fi

# Install Playwright
echo ""
echo "Installing Playwright..."
python3 -m pip install playwright --break-system-packages --quiet 2>/dev/null \
    || python3 -m pip install playwright --quiet

# Install Chromium browser for Playwright (needed for CDP with Edge)
echo ""
echo "Installing Playwright Chromium browser..."
python3 -m playwright install chromium

# Verify Edge is installed
EDGE_APP="/Applications/Microsoft Edge.app"
if [ ! -d "$EDGE_APP" ]; then
    echo ""
    echo "WARNING: Microsoft Edge not found at $EDGE_APP"
    echo "Install Edge from: https://www.microsoft.com/edge"
    echo "The script will still work if Edge is installed elsewhere."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Usage:"
echo "  cd skills/meeting-summary"
echo "  python3 -m scripts.get_transcript --site-url '<siteUrl>' --drive-id '<driveId>' --item-id '<itemId>' --format text -o '../../output/transcript.txt'"
echo ""
echo "NOTE: On macOS, always use single quotes for arguments (drive IDs contain ! which bash eats in double quotes)."
