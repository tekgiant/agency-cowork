#!/usr/bin/env bash
# generate-icns.sh — Convert icon.png to icon.icns for macOS app bundle
#
# Requires: macOS with sips + iconutil (ships with Xcode CLI tools)
# Usage: bash scripts/generate-icns.sh
#
# Input:  ui/assets/icon.png (1000x1000+)
# Output: ui/assets/icon.icns

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_PNG="$PROJECT_ROOT/ui/assets/icon.png"
OUTPUT_ICNS="$PROJECT_ROOT/ui/assets/icon.icns"
ICONSET_DIR="$PROJECT_ROOT/ui/assets/icon.iconset"

if [[ ! -f "$SOURCE_PNG" ]]; then
    echo "Error: Source PNG not found at $SOURCE_PNG"
    exit 1
fi

# Verify we're on macOS (iconutil is macOS-only)
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Error: This script requires macOS (uses iconutil and sips)."
    echo "Run this on your Mac before committing."
    exit 1
fi

echo "Creating iconset from $SOURCE_PNG..."

# Create .iconset directory
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

# Generate all required sizes for macOS .icns
# Format: icon_<size>x<size>.png (1x) and icon_<size>x<size>@2x.png (2x Retina)
sizes=(16 32 128 256 512)
for size in "${sizes[@]}"; do
    sips -z "$size" "$size" "$SOURCE_PNG" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
    retina=$((size * 2))
    if [[ $retina -le 1024 ]]; then
        sips -z "$retina" "$retina" "$SOURCE_PNG" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    fi
done

# iconutil requires icon_512x512@2x.png (1024x1024)
sips -z 1024 1024 "$SOURCE_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null

echo "Generating .icns..."
iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_ICNS"

# Clean up .iconset directory
rm -rf "$ICONSET_DIR"

echo "Done: $OUTPUT_ICNS"
ls -lh "$OUTPUT_ICNS"
