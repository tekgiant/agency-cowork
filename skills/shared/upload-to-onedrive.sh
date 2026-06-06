#!/usr/bin/env bash
# upload-to-onedrive.sh — Copy a local file to OneDrive via sync folder
#
# Usage: upload-to-onedrive.sh <source-file> [target-folder-name]
#
# Strategy: Detect the OneDrive sync folder on the local filesystem and cp.
# This avoids all Graph API auth issues — OneDrive client handles the sync.
#
# If OneDrive sync folder is not found, prints setup instructions and exits 1.

set -euo pipefail

SOURCE_FILE="${1:-}"
# Sanitize target folder name to prevent path traversal (e.g., "../../.ssh")
TARGET_FOLDER="$(basename "${2:-Agency Cowork Outputs}")"
if [[ "$TARGET_FOLDER" == "." || "$TARGET_FOLDER" == ".." ]]; then
    echo "ERROR: Invalid target folder name: $TARGET_FOLDER"
    exit 1
fi

if [[ -z "$SOURCE_FILE" ]]; then
    echo "Usage: upload-to-onedrive.sh <source-file> [target-folder-name]"
    echo "  source-file:       Path to the file to upload"
    echo "  target-folder-name: Folder name inside OneDrive (default: 'Agency Cowork Outputs')"
    exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "ERROR: File not found: $SOURCE_FILE"
    exit 1
fi

# --- Detect OneDrive sync folder ---
# Priority order: CloudStorage (modern macOS), home dir, Windows paths
ONEDRIVE_PATH=""

detect_onedrive() {
    local candidates=()

    case "$(uname -s)" in
        Darwin)
            # macOS: CloudStorage is the modern location (Monterey+)
            candidates=(
                "$HOME/Library/CloudStorage/OneDrive-Microsoft"
                "$HOME/Library/CloudStorage/OneDrive-SharedLibraries-Microsoft"
                "$HOME/OneDrive - Microsoft"
                "$HOME/OneDrive"
            )
            # Also glob for any OneDrive variant in CloudStorage
            for d in "$HOME/Library/CloudStorage"/OneDrive*; do
                [[ -d "$d" ]] && candidates+=("$d")
            done
            ;;
        Linux)
            candidates=(
                "$HOME/OneDrive - Microsoft"
                "$HOME/OneDrive"
            )
            ;;
        MINGW*|MSYS*|CYGWIN*)
            # Git Bash / WSL on Windows
            candidates=(
                "$USERPROFILE/OneDrive - Microsoft"
                "$HOME/OneDrive - Microsoft"
                "$HOME/OneDrive"
            )
            ;;
    esac

    for candidate in "${candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            ONEDRIVE_PATH="$candidate"
            return 0
        fi
    done
    return 1
}

if ! detect_onedrive; then
    echo "ERROR: OneDrive sync folder not found on this machine."
    echo ""
    echo "To fix this:"
    echo "  1. Install Microsoft OneDrive from https://onedrive.com/download"
    echo "  2. Sign in with your Microsoft work account"
    echo "  3. Let OneDrive finish initial sync"
    echo "  4. Re-run this command"
    echo ""
    echo "Looked for:"
    echo "  ~/Library/CloudStorage/OneDrive-Microsoft  (macOS)"
    echo "  ~/OneDrive - Microsoft                     (all platforms)"
    echo "  ~/OneDrive                                 (fallback)"
    exit 1
fi

echo "OneDrive sync folder: $ONEDRIVE_PATH"

# --- Create target folder if needed ---
DEST_DIR="$ONEDRIVE_PATH/$TARGET_FOLDER"
if [[ ! -d "$DEST_DIR" ]]; then
    echo "Creating folder: $TARGET_FOLDER"
    mkdir -p "$DEST_DIR"
fi

# --- Copy file ---
FILENAME="$(basename "$SOURCE_FILE")"
DEST_FILE="$DEST_DIR/$FILENAME"

# Handle conflict: add timestamp suffix if file exists
if [[ -f "$DEST_FILE" ]]; then
    TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
    EXT="${FILENAME##*.}"
    BASE="${FILENAME%.*}"
    DEST_FILE="$DEST_DIR/${BASE}_${TIMESTAMP}.${EXT}"
    FILENAME="$(basename "$DEST_FILE")"
fi

cp "$SOURCE_FILE" "$DEST_FILE"

echo "Uploaded: $FILENAME"
echo "Location: $DEST_FILE"
echo "OneDrive will sync this file automatically."

# --- Output structured result for script consumers ---
echo "---RESULT---"
echo "status=ok"
echo "filename=$FILENAME"
echo "local_path=$DEST_FILE"
echo "onedrive_folder=$TARGET_FOLDER"
