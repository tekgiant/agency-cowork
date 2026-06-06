#!/usr/bin/env bash
# sync-memory.sh — Clone or pull the memory repo configured in agentconfig.json
#
# Bash equivalent of sync-memory.ps1 for macOS & Linux.
#
# Usage:
#   bash scripts/sync-memory.sh           # Clone or pull
#   bash scripts/sync-memory.sh --force   # Delete and re-clone

set -euo pipefail

FORCE=false
if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]]; then
    FORCE=true
fi

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/agentconfig.json"
MEMORY_DIR="$PROJECT_ROOT/memory"
GIT_DIR="$MEMORY_DIR/.git"

# Colors
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' NC=''
fi

# Load config
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${RED}Error: agentconfig.json not found at $CONFIG_FILE${NC}"
    exit 1
fi

REPO_URL="$(python3 -c "import json; cfg=json.load(open('$CONFIG_FILE')); print(cfg.get('memory',{}).get('repo',''))" 2>/dev/null || true)"
BRANCH="$(python3 -c "import json; cfg=json.load(open('$CONFIG_FILE')); print(cfg.get('memory',{}).get('branch','main'))" 2>/dev/null || true)"

if [[ -z "$BRANCH" ]]; then BRANCH="main"; fi

if [[ -z "$REPO_URL" ]]; then
    echo -e "${RED}Error: memory.repo is not configured in agentconfig.json${NC}"
    exit 1
fi

echo "Memory repo : $REPO_URL"
echo "Branch      : $BRANCH"
echo "Local path  : $MEMORY_DIR"

# Force re-clone
if $FORCE && [[ -d "$MEMORY_DIR" ]]; then
    echo "Force: removing existing memory directory..."
    rm -rf "$MEMORY_DIR"
fi

# Clone or pull
if [[ -d "$GIT_DIR" ]]; then
    echo "Pulling latest..."
    cd "$MEMORY_DIR"
    if git pull origin "$BRANCH"; then
        echo -e "${GREEN}Memory synced (pull).${NC}"
    else
        echo -e "${RED}git pull failed${NC}"
        exit 1
    fi
elif [[ -d "$MEMORY_DIR" ]]; then
    echo -e "${YELLOW}Warning: memory/ exists but is not a git repo. Use --force to replace it.${NC}"
    exit 1
else
    echo "Cloning memory repo..."
    if git clone --branch "$BRANCH" "$REPO_URL" "$MEMORY_DIR"; then
        echo -e "${GREEN}Memory synced (clone).${NC}"
    else
        echo -e "${RED}git clone failed${NC}"
        exit 1
    fi
fi

# Summary
FILE_COUNT=$(find "$MEMORY_DIR" -type f -not -path '*/.git/*' | wc -l | tr -d ' ')
echo "Files in memory/: $FILE_COUNT"
