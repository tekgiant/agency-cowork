#!/usr/bin/env bash
# ============================================================
# setup.sh - Interactive setup wizard for Agency Cowork
#
# Cross-platform (macOS & Ubuntu/Debian) equivalent of setup.ps1.
# Guides first-time setup: prerequisites, fork verification, agent
# customization, Microsoft 365 MCP configuration, skill registration,
# dependencies, and security hardening.
#
# Supports three modes:
#   Interactive (default) — prompts for every decision
#   --skip-personalization — skips Phase 2 prompts, auto-detects UPN
#   --headless             — zero prompts, all from args/auto-detect/defaults
#
# Usage:
#   bash scripts/setup.sh
#   bash scripts/setup.sh --headless --user-email user@contoso.com
#   bash scripts/setup.sh --headless --install-deps markitdown,qmd
# ============================================================

set -euo pipefail

# ============================================================
# Argument Parsing
# ============================================================

HEADLESS=false
SKIP_FORK_CHECK=false
SKIP_PERSONALIZATION=false
AGENT_NAME=""
AGENT_ROLE=""
USER_EMAIL=""
USER_NAME=""
USER_ORG=""
MEMORY_REPO=""
TENANT_ID=""
INSTALL_DEPS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --headless)           HEADLESS=true; shift ;;
        --skip-fork-check)    SKIP_FORK_CHECK=true; shift ;;
        --skip-personalization) SKIP_PERSONALIZATION=true; shift ;;
        --agent-name)         AGENT_NAME="$2"; shift 2 ;;
        --agent-role)         AGENT_ROLE="$2"; shift 2 ;;
        --user-email)         USER_EMAIL="$2"; shift 2 ;;
        --user-name)          USER_NAME="$2"; shift 2 ;;
        --user-org)           USER_ORG="$2"; shift 2 ;;
        --memory-repo)        MEMORY_REPO="$2"; shift 2 ;;
        --tenant-id)          TENANT_ID="$2"; shift 2 ;;
        --install-deps)       INSTALL_DEPS="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: bash scripts/setup.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --headless               Zero prompts; uses args/auto-detect/defaults"
            echo "  --skip-fork-check        Skip fork verification"
            echo "  --skip-personalization   Skip agent customization prompts"
            echo "  --agent-name NAME        Override agent name"
            echo "  --agent-role ROLE        Override agent role"
            echo "  --user-email EMAIL       User's UPN/email"
            echo "  --user-name NAME         User's full name"
            echo "  --user-org ORG           User's organization (default: Microsoft)"
            echo "  --memory-repo URL        Memory repository URL"
            echo "  --tenant-id GUID         Microsoft Entra tenant ID"
            echo "  --install-deps LIST      Comma-separated: markitdown,qmd,specify,all,none"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage."
            exit 1
            ;;
    esac
done

# Headless implies skip-fork-check and skip-personalization
if $HEADLESS; then
    SKIP_FORK_CHECK=true
    SKIP_PERSONALIZATION=true
    if [[ -z "$INSTALL_DEPS" ]]; then INSTALL_DEPS="all"; fi
fi

# ============================================================
# Resolve Paths
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$HOME/.copilot"
COPILOT_CONFIG="$CONFIG_DIR/config.json"
VSCODE_DIR="$PROJECT_ROOT/.vscode"
MCP_CONFIG="$PROJECT_ROOT/.mcp.json"
LEGACY_MCP_CONFIG="$VSCODE_DIR/mcp.json"
GLOBAL_MCP_CONFIG="$CONFIG_DIR/mcp-config.json"

cd "$PROJECT_ROOT"

# Track components that were skipped because already installed
SKIPPED_COMPONENTS=()

# ============================================================
# Platform Detection
# ============================================================

PLATFORM="$(uname -s)"
DISTRO=""

case "$PLATFORM" in
    Darwin)
        PLATFORM_LABEL="macOS"
        ;;
    Linux)
        PLATFORM_LABEL="Linux"
        if [[ -f /etc/os-release ]]; then
            # shellcheck disable=SC1091
            . /etc/os-release
            DISTRO="${ID:-unknown}"
        fi
        ;;
    *)
        echo "Unsupported platform: $PLATFORM"
        echo "This script supports macOS and Ubuntu/Debian. For Windows, use setup.ps1."
        exit 1
        ;;
esac

# ============================================================
# Helpers
# ============================================================

# Colors (if terminal supports them)
if [[ -t 1 ]]; then
    CYAN='\033[0;36m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    MAGENTA='\033[0;35m'
    WHITE='\033[1;37m'
    GRAY='\033[0;90m'
    NC='\033[0m'
else
    CYAN='' GREEN='' YELLOW='' RED='' MAGENTA='' WHITE='' GRAY='' NC=''
fi

write_banner() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""
}

write_step() {
    echo -e "${YELLOW}  >> $1${NC}"
}

write_ok() {
    echo -e "${GREEN}  [OK] $1${NC}"
}

write_warn() {
    echo -e "${YELLOW}  [!!] $1${NC}"
}

write_err() {
    echo -e "${RED}  [FAIL] $1${NC}"
}

# Portable sed -i (macOS requires '' arg, GNU does not)
sed_i() {
    if [[ "$PLATFORM" == "Darwin" ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# Read user input with optional default; returns default in headless mode
read_input() {
    local prompt="$1"
    local default="${2:-}"
    local required="${3:-false}"
    local value=""

    if $HEADLESS; then
        value="$default"
        if [[ -n "$value" ]]; then
            echo -e "${GRAY}  $prompt : $value (auto)${NC}" >&2
        fi
        echo "$value"
        return
    fi

    local suffix=""
    if [[ -n "$default" ]]; then suffix=" [$default]"; fi

    while true; do
        echo -ne "${WHITE}  ${prompt}${suffix}: ${NC}" >&2
        read -r value
        if [[ -z "$value" ]]; then value="$default"; fi
        if [[ "$required" == "true" && -z "$value" ]]; then
            echo -e "${YELLOW}    (required)${NC}" >&2
            continue
        fi
        break
    done
    echo "$value"
}

# Yes/No prompt; returns 0 for yes, 1 for no. Default: true (yes)
read_yesno() {
    local prompt="$1"
    local default="${2:-true}"

    if $HEADLESS; then
        local choice
        if [[ "$default" == "true" ]]; then choice="yes"; else choice="no"; fi
        echo -e "${GRAY}  $prompt -> $choice (auto)${NC}" >&2
        [[ "$default" == "true" ]]
        return
    fi

    local hint
    if [[ "$default" == "true" ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
    echo -ne "${WHITE}  $prompt $hint ${NC}" >&2
    local answer
    read -r answer
    if [[ -z "$answer" ]]; then
        [[ "$default" == "true" ]]
        return
    fi
    [[ "$answer" =~ ^[Yy] ]]
    return
}

# Check if a command exists
has_cmd() {
    command -v "$1" &>/dev/null
}

# ============================================================
# Phase 0: Welcome
# ============================================================

echo ""
echo -e "${MAGENTA}    _                               ____                      _    ${NC}"
echo -e "${MAGENTA}   / \\   __ _  ___ _ __   ___ _   _/ ___|___/\\    /\\___  _ __| | __${NC}"
echo -e "${MAGENTA}  / _ \\ / _\` |/ _ \\ '_ \\ / __| | | | |   / _ \\ /\\ / _ \\| '__| |/ /${NC}"
echo -e "${MAGENTA} / ___ \\ (_| |  __/ | | | (__| |_| | |__| (_) V  V (_) | |  |   < ${NC}"
echo -e "${MAGENTA}/_/   \\_\\__, |\\___|_| |_|\\___|\\___, |\\____\\___/\\_/\\_/\\___/|_|  |_|\\_\\${NC}"
echo -e "${MAGENTA}        |___/                 |___/                                 ${NC}"
echo ""

mode_label="Interactive Setup"
if $HEADLESS; then
    mode_label="Headless Setup (agent-driven)"
elif $SKIP_PERSONALIZATION; then
    mode_label="Setup (skip personalization)"
fi
echo -e "${WHITE}  Agency for the rest of us -- $mode_label ($PLATFORM_LABEL)${NC}"
echo ""

# ============================================================
# Phase 0.5: Prerequisites
# ============================================================

write_banner "Prerequisites"

# Prerequisites are best-effort — don't abort if a package manager fails
set +e

if [[ "$PLATFORM" == "Darwin" ]]; then
    # --- macOS: Homebrew ---
    write_step "Checking for Homebrew..."

    # Apple Silicon: Homebrew may be installed but not in PATH for non-login shells
    if ! has_cmd brew && [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    # Intel Mac: check /usr/local/bin/brew
    if ! has_cmd brew && [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi

    if has_cmd brew; then
        brew_ver="$(brew --version 2>/dev/null | head -1)"
        write_ok "Homebrew available ($brew_ver)"
    else
        write_warn "Homebrew not found."
        # In headless mode (e.g. launched from Electron), Homebrew's installer
        # requires an interactive TTY for sudo — skip and let user install manually.
        if $HEADLESS || ! [[ -t 0 ]]; then
            write_warn "Non-interactive session detected. Install Homebrew manually first:"
            echo -e "${GRAY}    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${NC}"
            write_warn "Then re-run this setup script."
        elif read_yesno "Install Homebrew now?" "true"; then
            write_step "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add Homebrew to PATH for Apple Silicon
            if [[ -f /opt/homebrew/bin/brew ]]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            write_ok "Homebrew installed"
        else
            write_warn "Skipping Homebrew. Install packages manually."
        fi
    fi

    if has_cmd brew; then
        write_step "Installing core packages via Homebrew..."
        # Install packages (brew won't error if already installed)
        local_packages=("python@3.12" "node@22" "git" "azure-cli")
        for pkg in "${local_packages[@]}"; do
            if brew list "$pkg" &>/dev/null; then
                write_ok "$pkg already installed"
                SKIPPED_COMPONENTS+=("$pkg")
            else
                write_step "Installing $pkg..."
                brew install "$pkg" 2>&1 || write_warn "Failed to install $pkg"
            fi
        done
    fi

elif [[ "$PLATFORM" == "Linux" ]]; then
    # --- Ubuntu/Debian: apt ---
    if [[ "$DISTRO" == "ubuntu" || "$DISTRO" == "debian" ]]; then
        write_step "Updating package lists..."
        sudo apt-get update -qq 2>/dev/null || write_warn "apt-get update failed"

        write_step "Installing core packages via apt..."
        apt_packages=("python3" "python3-pip" "python3-venv" "nodejs" "npm" "git" "curl" "jq")
        for pkg in "${apt_packages[@]}"; do
            if dpkg -s "$pkg" &>/dev/null; then
                write_ok "$pkg already installed"
                SKIPPED_COMPONENTS+=("$pkg")
            else
                write_step "Installing $pkg..."
                sudo apt-get install -y "$pkg" 2>&1 || write_warn "Failed to install $pkg"
            fi
        done

        # Azure CLI via Microsoft's apt repo
        write_step "Checking for Azure CLI..."
        if has_cmd az; then
            az_ver="$(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo "unknown")"
            write_ok "Azure CLI available ($az_ver)"
        else
            write_step "Installing Azure CLI..."
            curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash 2>&1 || write_warn "Azure CLI install failed"
        fi
    else
        write_warn "Unsupported Linux distro: $DISTRO. Install Python 3, Node.js, Git, and Azure CLI manually."
    fi
fi

# Verify core tools
write_step "Verifying installed tools..."
for tool in python3 node npm git; do
    if has_cmd "$tool"; then
        ver="$("$tool" --version 2>/dev/null | head -1)"
        write_ok "$tool available ($ver)"
    else
        write_warn "$tool not found. Some features may not work."
    fi
done

# pip check
write_step "Checking for pip..."
if has_cmd pip3; then
    pip_ver="$(pip3 --version 2>/dev/null | head -1)"
    write_ok "pip3 available ($pip_ver)"
elif has_cmd pip; then
    pip_ver="$(pip --version 2>/dev/null | head -1)"
    write_ok "pip available ($pip_ver)"
else
    write_step "Bootstrapping pip..."
    python3 -m ensurepip --upgrade 2>/dev/null || write_warn "pip bootstrap failed"
fi

# Azure CLI check
write_step "Checking for Azure CLI..."
if has_cmd az; then
    az_ver="$(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo "unknown")"
    write_ok "Azure CLI available ($az_ver)"
else
    write_warn "Azure CLI not found."
    if [[ "$PLATFORM" == "Darwin" ]]; then
        echo -e "${GRAY}    Install with: brew install azure-cli${NC}"
    else
        echo -e "${GRAY}    Install with: curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash${NC}"
    fi
fi

# Determine pip command
# Add --break-system-packages for PEP 668 / Homebrew-managed Python (3.12+)
PIP_CMD=""
PIP_EXTRA=""
if has_cmd pip3; then PIP_CMD="pip3"
elif has_cmd pip; then PIP_CMD="pip"
fi
if [[ -n "$PIP_CMD" ]]; then
    # Detect externally-managed Python (PEP 668) via the marker file
    py_stdlib="$(python3 -c 'import sysconfig; print(sysconfig.get_path("stdlib"))' 2>/dev/null || true)"
    if [[ -n "$py_stdlib" && -f "$py_stdlib/EXTERNALLY-MANAGED" ]]; then
        PIP_EXTRA="--break-system-packages"
    fi
fi

# Re-enable strict mode after best-effort prerequisites
set -euo pipefail

# ============================================================
# Phase 1: Fork Verification
# ============================================================

write_banner "Phase 1: Fork Verification"

if $SKIP_FORK_CHECK; then
    write_warn "Fork check skipped (--skip-fork-check)"
else
    remote_url="$(git remote get-url origin 2>/dev/null || true)"
    if [[ -z "$remote_url" ]]; then
        write_err "No git remote 'origin' found. This must be a git repository."
        echo ""
        echo -e "${WHITE}  To set up:${NC}"
        echo -e "${GRAY}    1. Fork the Agency-Cowork repo on GitHub${NC}"
        echo -e "${GRAY}    2. Clone your fork locally${NC}"
        echo -e "${GRAY}    3. Run this setup script from the cloned repo${NC}"
        exit 1
    fi

    is_base_repo=false
    if [[ "$remote_url" == *"YOUR-ORG/Agency-Cowork"* ]]; then
        is_base_repo=true
    fi

    if $is_base_repo; then
        write_err "This repo is still pointing at the base Agency-Cowork project."
        echo ""
        echo -e "${GRAY}  Current remote: $remote_url${NC}"
        echo ""
        echo -e "${WHITE}  You must fork the repo into your own GitHub account before setup.${NC}"
        echo -e "${GRAY}    1. Go to the Agency-Cowork repo on GitHub${NC}"
        echo -e "${GRAY}    2. Click 'Fork' to create your own copy${NC}"
        echo -e "${GRAY}    3. Clone YOUR fork and run this setup script${NC}"
        exit 1
    fi

    write_ok "Fork verified: $remote_url"
fi

# ============================================================
# Phase 1.5: Initialize Identity Files from Templates
# ============================================================

write_step "Checking identity files..."

if [[ ! -f "CLAUDE.md" ]]; then
    if [[ -f "CLAUDE.md.example" ]]; then
        cp "CLAUDE.md.example" "CLAUDE.md"
        write_ok "Created CLAUDE.md from CLAUDE.md.example"
    else
        write_err "CLAUDE.md.example not found. Cannot create agent identity file."
    fi
else
    write_ok "CLAUDE.md already exists (keeping your customizations)"
fi

if [[ ! -f "AGENTS.md" ]]; then
    if [[ -f "AGENTS.md.example" ]]; then
        cp "AGENTS.md.example" "AGENTS.md"
        write_ok "Created AGENTS.md from AGENTS.md.example"
    else
        write_err "AGENTS.md.example not found. Cannot create operational rules file."
    fi
else
    write_ok "AGENTS.md already exists (keeping your customizations)"
fi

# ============================================================
# Phase 2: Agent Customization
# ============================================================

write_banner "Phase 2: Customize Your Agent"

agentName=""
agentRole=""
userEmail=""
userName=""
userOrg=""
userAlias=""

if ! $SKIP_PERSONALIZATION; then
    if ! read_yesno "Customize agent name, role, and user profile?" "true"; then
        SKIP_PERSONALIZATION=true
    fi
fi

if $SKIP_PERSONALIZATION; then
    write_warn "Personalization skipped"

    # Read identity from CLAUDE.md, allow parameter overrides
    if [[ -n "$AGENT_NAME" ]]; then
        agentName="$AGENT_NAME"
    elif [[ -f "CLAUDE.md" ]]; then
        agentName="$(grep '\*\*Name:\*\*' CLAUDE.md | head -1 | sed 's/.*\*\*Name:\*\* //' | xargs)" || agentName="Agency Cowork"
    fi
    if [[ -z "$agentName" ]]; then agentName="Agency Cowork"; fi

    if [[ -n "$AGENT_ROLE" ]]; then
        agentRole="$AGENT_ROLE"
    elif [[ -f "CLAUDE.md" ]]; then
        agentRole="$(grep '\*\*Role:\*\*' CLAUDE.md | head -1 | sed 's/.*\*\*Role:\*\* //' | xargs)" || agentRole="AI Coworker"
    fi
    if [[ -z "$agentRole" ]]; then agentRole="AI Coworker"; fi

    write_ok "Agent identity: $agentName ($agentRole)"

    # UPN: parameter > az CLI > git config
    if [[ -z "$USER_EMAIL" ]]; then
        USER_EMAIL="$(az account show --query user.name -o tsv 2>/dev/null || true)"
    fi
    if [[ -z "$USER_EMAIL" ]]; then
        USER_EMAIL="$(git config user.email 2>/dev/null || true)"
    fi
    userEmail="$USER_EMAIL"
    if [[ -n "$userEmail" ]]; then
        write_ok "UPN: $userEmail"
    else
        write_warn "Could not determine UPN"
    fi

    userName="${USER_NAME:-${userEmail%%@*}}"
    userOrg="${USER_ORG:-Microsoft}"
    userAlias="${userEmail%%@*}"

else
    echo -e "${GRAY}  These values personalize your agent's identity and memory.${NC}"
    echo -e "${GRAY}  Press Enter to accept defaults shown in [brackets].${NC}"
    echo ""

    agentName="$(read_input "Agent name" "Agency Cowork")"
    agentRole="$(read_input "Agent role" "AI Coworker")"

    # Auto-detect UPN
    detected_upn="$(az account show --query user.name -o tsv 2>/dev/null || true)"
    if [[ -z "$detected_upn" ]]; then
        detected_upn="$(git config user.email 2>/dev/null || true)"
    fi

    if [[ -n "$detected_upn" ]]; then
        write_ok "Detected UPN: $detected_upn"
        if read_yesno "Use this as your email/UPN?" "true"; then
            userEmail="$detected_upn"
        else
            userEmail="$(read_input "Your email (UPN)" "" "true")"
        fi
    else
        userEmail="$(read_input "Your email (UPN)" "" "true")"
    fi

    userName="$(read_input "Your full name" "${userEmail%%@*}")"
    userOrg="$(read_input "Your organization" "Microsoft")"
    userAlias="${userEmail%%@*}"

    echo ""
    write_step "Updating CLAUDE.md..."
    sed_i "s/- \*\*Name:\*\* Agency Cowork/- **Name:** $agentName/" CLAUDE.md
    sed_i "s/- \*\*Role:\*\* AI Coworker/- **Role:** $agentRole/" CLAUDE.md
    write_ok "CLAUDE.md updated (name: $agentName, role: $agentRole)"
fi

# Memory repository: parameter > agentconfig.json > prompt
write_step "Configuring memory repository..."
memoryRepo=""
memoryBranch="main"

if [[ -n "$MEMORY_REPO" ]]; then
    memoryRepo="$MEMORY_REPO"
    # Update agentconfig.json
    python3 -c "
import json
with open('agentconfig.json', 'r') as f:
    cfg = json.load(f)
cfg['memory']['repo'] = '$memoryRepo'
with open('agentconfig.json', 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>/dev/null || write_warn "Could not update agentconfig.json"
    write_ok "Memory repo from parameter: $memoryRepo"
else
    memoryRepo="$(python3 -c "import json; cfg=json.load(open('agentconfig.json')); print(cfg.get('memory',{}).get('repo',''))" 2>/dev/null || true)"
    memoryBranch="$(python3 -c "import json; cfg=json.load(open('agentconfig.json')); print(cfg.get('memory',{}).get('branch','main'))" 2>/dev/null || true)"
fi

if ! $SKIP_PERSONALIZATION && ! $HEADLESS; then
    if [[ -z "$memoryRepo" || "$memoryRepo" == *"your-org"* ]]; then
        echo ""
        echo -e "${GRAY}  The memory/ directory stores personal context (daily logs, knowledgebase)${NC}"
        echo -e "${GRAY}  in a separate private Git repo to keep your data portable and private.${NC}"
        echo ""
        memoryRepo="$(read_input "Memory repo URL (or 'skip' to use local memory)" "skip")"
        if [[ "$memoryRepo" != "skip" && -n "$memoryRepo" ]]; then
            memoryBranch="$(read_input "Memory repo branch" "main")"
            python3 -c "
import json
with open('agentconfig.json', 'r') as f:
    cfg = json.load(f)
cfg['memory']['repo'] = '$memoryRepo'
cfg['memory']['branch'] = '$memoryBranch'
with open('agentconfig.json', 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>/dev/null || write_warn "Could not update agentconfig.json"
            write_ok "agentconfig.json updated with memory repo: $memoryRepo"
        else
            memoryRepo=""
        fi
    fi
fi

# Normalize placeholder URLs to empty (YOUR-ORG is the default in agentconfig.json)
if [[ "$memoryRepo" == *"YOUR-ORG"* || "$memoryRepo" == *"your-org"* || "$memoryRepo" == *"YOUR_ORG"* ]]; then
    memoryRepo=""
fi

if [[ -n "$memoryRepo" && "$memoryRepo" != "skip" ]]; then
    write_ok "Memory repo: $memoryRepo (branch: $memoryBranch)"
    write_step "Syncing memory repository..."
    if [[ -f "scripts/sync-memory.sh" ]]; then
        bash "scripts/sync-memory.sh" || write_warn "Memory sync had issues"
    elif [[ -f "scripts/sync-memory.ps1" ]] && has_cmd pwsh; then
        pwsh -File "scripts/sync-memory.ps1" || write_warn "Memory sync had issues"
    else
        write_warn "No memory sync script found. Clone your memory repo into memory/ manually."
    fi
else
    write_ok "Using local memory (no remote repo configured)"
    write_ok "You can add a remote memory repo later in Settings for cloud sync"
    mkdir -p "memory/Knowledgebase/Program" "memory/Knowledgebase/Specifications"

    if [[ ! -f "memory/MEMORY.md" ]]; then
        cat > "memory/MEMORY.md" << MEMEOF
# Semantic Memory

## User Profile

- **Name:** $userName
- **Email:** $userEmail
- **Organization:** $userOrg
- **Role:** (your role)

## Key Contacts

| Name | Role | Email |
|------|------|-------|
| (add contacts here) | | |

## Preferences

- **Communication style:** (formal / casual / concise)
- **Working hours:** (e.g., 9am-5pm PST)
- **Tools:** Agency Cowork, Outlook, Teams, SharePoint
MEMEOF
        write_ok "Created memory/MEMORY.md with your profile"
    fi
    write_ok "Created memory/Knowledgebase directory structure"
fi

if [[ ! -d "memory/WeeklyReports" ]]; then
    mkdir -p "memory/WeeklyReports"
    write_ok "Created memory/WeeklyReports directory"
fi

# Migrate daily logs from memory/ root to memory/DailyLogs/ (v0.9.5+)
if [[ -d "memory" ]]; then
    shopt -s nullglob
    daily_logs=(memory/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md)
    shopt -u nullglob
    if [[ ${#daily_logs[@]} -gt 0 ]]; then
        mkdir -p "memory/DailyLogs"
        moved=0
        for log in "${daily_logs[@]}"; do
            base="$(basename "$log")"
            dest="memory/DailyLogs/$base"
            if [[ -f "$dest" ]]; then
                # Keep newer file
                if [[ "$log" -nt "$dest" ]]; then
                    mv -f "$log" "$dest"
                    ((moved++))
                fi
            else
                mv "$log" "$dest"
                ((moved++))
            fi
        done
        if [[ $moved -gt 0 ]]; then
            write_ok "Migrated $moved daily log(s) to memory/DailyLogs/"
        fi
    fi
    # Ensure DailyLogs directory exists for new installs
    mkdir -p "memory/DailyLogs"
fi

# Create global config directory (~/.agency-cowork/)
GLOBAL_CONFIG_DIR="$HOME/.agency-cowork"
mkdir -p "$GLOBAL_CONFIG_DIR"

# Migrate legacy per-repo monitor-config.json to global config
LEGACY_MON_CFG="skills/teams/monitor/monitor-config.json"
GLOBAL_MON_CFG="$GLOBAL_CONFIG_DIR/monitor-config.json"
if [ -f "$LEGACY_MON_CFG" ]; then
    if command -v python3 &>/dev/null; then
        python3 -c "
import json, os, sys
legacy_path = '$LEGACY_MON_CFG'
global_path = '$GLOBAL_MON_CFG'
ws_key = os.path.abspath('.')

with open(legacy_path) as f:
    legacy = json.load(f)

gcfg = {'identity': {}, 'connection': {}, 'workspaces': {}}
if os.path.exists(global_path):
    with open(global_path) as f:
        gcfg = json.load(f)

# Migrate identity
sender = legacy.get('authorized_sender', {})
if sender.get('mri'):
    gcfg['identity'] = {
        'mri': sender['mri'],
        'displayName': sender.get('displayName', ''),
        'upn': sender.get('upn', '')
    }

# Migrate connection
if legacy.get('connection'):
    gcfg['connection'] = legacy['connection']

# Migrate workspace entry
if 'workspaces' not in gcfg:
    gcfg['workspaces'] = {}
gcfg['workspaces'][ws_key] = {
    'enabled': legacy.get('enabled', False),
    'keyword': legacy.get('keyword', '@agent'),
    'reply_prefix': legacy.get('reply_prefix', 'Agency Cowork: '),
    'monitored_conversations': legacy.get('monitored_conversations', []),
    'dispatch': legacy.get('dispatch', {})
}

with open(global_path, 'w') as f:
    json.dump(gcfg, f, indent=2)

os.rename(legacy_path, legacy_path + '.migrated')
print('OK')
" && write_ok "Migrated monitor config to global: $GLOBAL_MON_CFG" \
        || write_warn "Could not migrate monitor config"
    else
        write_warn "python3 not found — skipping monitor config migration"
    fi
fi

# ============================================================
# Phase 3: Microsoft 365 Configuration
# ============================================================

write_banner "Phase 3: Microsoft 365 MCP Servers"

echo -e "${GRAY}  MCP servers connect your agent to Outlook, Teams, SharePoint,${NC}"
echo -e "${GRAY}  Calendar, Word, and WorkIQ (AI-powered M365 search).${NC}"
echo ""

# Ensure Azure CLI is logged in
write_step "Checking Azure CLI authentication..."
azAccount=""
azAccount="$(az account show --query user.name -o tsv 2>/dev/null || true)"
if [[ -z "$azAccount" ]]; then
    write_warn "Azure CLI not logged in. Running 'az login'..."
    az login --output none 2>&1 || write_err "Azure CLI login failed. Some features will not work."
    azAccount="$(az account show --query user.name -o tsv 2>/dev/null || true)"
    if [[ -n "$azAccount" ]]; then
        write_ok "Logged in as: $azAccount"
    fi
else
    write_ok "Azure CLI authenticated: $azAccount"
fi

# Tenant ID: parameter > auto-detect > prompt
resolvedTenantId=""
if [[ -n "$TENANT_ID" ]]; then
    resolvedTenantId="$TENANT_ID"
    write_ok "Tenant ID from parameter: $resolvedTenantId"
else
    write_step "Attempting to auto-detect tenant ID via Azure CLI..."
    resolvedTenantId="$(az account show --query tenantId -o tsv 2>/dev/null || true)"
    if [[ "$resolvedTenantId" =~ ^[0-9a-f]{8}- ]]; then
        write_ok "Detected tenant ID: $resolvedTenantId"
        if ! read_yesno "Use this tenant ID?" "true"; then
            resolvedTenantId=""
        fi
    else
        resolvedTenantId=""
    fi
fi

if [[ -z "$resolvedTenantId" ]]; then
    if $HEADLESS; then
        write_err "Tenant ID could not be auto-detected and no --tenant-id provided."
        echo -e "${GRAY}  Re-run with: --tenant-id <GUID>${NC}"
        exit 1
    fi
    echo ""
    echo -e "${GRAY}  To find your tenant ID:${NC}"
    echo -e "${GRAY}    - Azure Portal: https://portal.azure.com > Microsoft Entra ID > Overview${NC}"
    echo -e "${GRAY}    - Azure CLI: az account show --query tenantId -o tsv${NC}"
    echo ""
    resolvedTenantId="$(read_input "Enter your Microsoft Entra tenant ID (GUID)" "" "true")"
fi

tenantId="$resolvedTenantId"

# Validate format
if [[ ! "$tenantId" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    write_err "Invalid tenant ID format. Expected a GUID like: 12345678-1234-1234-1234-123456789abc"
    echo -e "${GRAY}  You entered: $tenantId${NC}"
    echo -e "${GRAY}  You can fix this later in: $MCP_CONFIG${NC}"
fi

# Generate MCP config
write_step "Writing MCP configuration..."

# Verify agency CLI is available (required for agency mcp servers)
if ! command -v agency &>/dev/null; then
    write_warn "Agency CLI not found. MCP servers require 'agency' on PATH."
    echo -e "${GRAY}    Install: curl -sSfL https://aka.ms/InstallTool.sh | sh -s agency${NC}"
    echo -e "${GRAY}    After install, restart your terminal and re-run this script.${NC}"
fi

mkdir -p "$CONFIG_DIR"
mkdir -p "$VSCODE_DIR"

# Use Agency built-in MCP servers — handles EntraID auth automatically, no tenant ID needed
# Word still uses HTTP endpoint (no agency builtin yet) — requires tenant ID
# Wrap through /usr/bin/env so the "command" field is a system binary, not "agency".
# Some GitHub orgs enforce Copilot CLI MCP server policies that block unrecognized
# command names. See: https://github.com/ahsi-microsoft/agency-cowork/issues/277
cat > /tmp/mcp-config-setup.json << MCPEOF
{
  "mcpServers": {
    "workiq": {
      "command": "/usr/bin/env",
      "args": ["agency", "mcp", "workiq"]
    },
    "teams": {
      "command": "/usr/bin/env",
      "args": ["agency", "mcp", "teams"]
    },
    "mail": {
      "command": "/usr/bin/env",
      "args": ["agency", "mcp", "mail"]
    },
    "calendar": {
      "command": "/usr/bin/env",
      "args": ["agency", "mcp", "calendar"]
    },
    "sharepoint": {
      "command": "/usr/bin/env",
      "args": ["agency", "mcp", "sharepoint"]
    },
    "microsoft-word": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/${tenantId}/servers/mcp_WordServer",
      "type": "http"
    }
  }
}
MCPEOF

# Migrate legacy .vscode/mcp.json to .mcp.json if it exists
if [[ -f "$LEGACY_MCP_CONFIG" ]] && [[ ! -f "$MCP_CONFIG" ]]; then
    python3 -c "
import json, sys
legacy_path, new_path = sys.argv[1], sys.argv[2]
with open(legacy_path) as f:
    cfg = json.load(f)
servers = cfg.get('servers', cfg.get('mcpServers', {}))
with open(new_path, 'w') as f:
    json.dump({'mcpServers': servers}, f, indent=2)
    f.write('\n')
" "$LEGACY_MCP_CONFIG" "$MCP_CONFIG" 2>/dev/null && {
        rm -f "$LEGACY_MCP_CONFIG"
        write_ok "Migrated .vscode/mcp.json -> .mcp.json"
    } || write_warn "Could not auto-migrate .vscode/mcp.json"
fi

if [[ -f "$MCP_CONFIG" ]]; then
    # Merge: add new servers, replace old HTTP servers with STDIO builtins
    # Pass MCP_CONFIG as a CLI argument (sys.argv[1]) instead of shell-interpolating into Python code
    # to prevent injection if the path contains single quotes
    python3 -c "
import json, sys, os
mcp_path = sys.argv[1]
with open(mcp_path) as f:
    existing = json.load(f)
with open('/tmp/mcp-config-setup.json') as f:
    new = json.load(f)
# Support both 'mcpServers' (.mcp.json) and 'servers' (legacy)
s_key = 'mcpServers' if 'mcpServers' in existing else 'servers' if 'servers' in existing else 'mcpServers'
if s_key not in existing:
    existing['mcpServers'] = {}
    s_key = 'mcpServers'
# Remove old HTTP servers replaced by STDIO builtins
old_http = ['microsoft-teams', 'microsoft-outlook-mail', 'microsoft-outlook-calendar', 'microsoft-sharepoint-and-onedrive']
removed = []
for old in old_http:
    srv = existing[s_key].get(old, {})
    if 'url' in srv or srv.get('type') == 'http':
        del existing[s_key][old]
        removed.append(old)
# Migrate workiq from old npx wrapper to agency builtin
wiq = existing[s_key].get('workiq', {})
if wiq.get('command') and os.path.basename(wiq['command']) == 'npx':
    del existing[s_key]['workiq']
    removed.append('workiq (npx)')
# Add new servers
added = []
for key, val in new.get('mcpServers', {}).items():
    if key not in existing[s_key]:
        existing[s_key][key] = val
        added.append(key)
# Migrate legacy 'servers' key to 'mcpServers'
if s_key == 'servers':
    existing['mcpServers'] = existing.pop('servers')
    added.append('(migrated key servers -> mcpServers)')
if added or removed:
    with open(mcp_path, 'w') as f:
        json.dump(existing, f, indent=2)
if removed:
    print(f'removed {len(removed)} legacy HTTP server(s): {chr(44).join(removed)}')
if added:
    print(f'added {len(added)} STDIO server(s): {chr(44).join(added)}')
if not added and not removed:
    print('all servers already configured')
" "$MCP_CONFIG" 2>/dev/null
    if [[ $? -eq 0 ]]; then
        write_ok "MCP config: $(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
skey = 'mcpServers' if 'mcpServers' in cfg else 'servers'
print(f\"{len(cfg.get(skey, {}))} server(s) configured\")
" "$MCP_CONFIG" 2>/dev/null || echo 'updated')"
    else
        write_warn "Could not merge MCP config. Keeping existing file."
    fi
else
    cp /tmp/mcp-config-setup.json "$MCP_CONFIG"
    write_ok "MCP config written to: $MCP_CONFIG"
fi
rm -f /tmp/mcp-config-setup.json

# Clean up legacy configs
if [[ -f "$LEGACY_MCP_CONFIG" ]] && [[ -f "$MCP_CONFIG" ]]; then
    rm -f "$LEGACY_MCP_CONFIG"
    write_ok "Removed legacy .vscode/mcp.json (migrated to .mcp.json)"
fi
if [[ -f "$GLOBAL_MCP_CONFIG" ]]; then
    echo "  [INFO] MCP config active at .mcp.json"
    echo "         Global config at $GLOBAL_MCP_CONFIG can be removed if no other projects use it."
fi

# ============================================================
# Phase 4: Skill Registration
# ============================================================

write_banner "Phase 4: Register Skills"

echo -e "${GRAY}  Registering all 24 local skills as installed_plugins.${NC}"
echo ""

skills=(
    "calendar" "claude-deep-research-skill" "cocoindex" "confluence" "deep-personalization"
    "email-triage" "excel" "landing-zone" "markitdown" "meeting-summary"
    "onepdm" "oneplanner" "powerpoint" "qmd-memory"
    "send-email" "sharepoint-download" "spec-kit" "svg-to-ppt" "task-scheduler"
    "teams" "visual-explainer" "webpage-builder" "weekly-report" "word-doc" "workstreams"
)

# Generate config.json via python3
python3 << PYEOF
import json, os
from datetime import datetime, timezone

project_root = "$PROJECT_ROOT"
config_path = "$COPILOT_CONFIG"
skills = $(printf '%s\n' "${skills[@]}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin]))")
timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Load existing config or create new
config = {}
if os.path.exists(config_path):
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception:
        pass

# Build plugin entries
new_plugins = []
for skill in skills:
    skill_path = os.path.join(project_root, "skills", skill)
    new_plugins.append({
        "name": skill,
        "marketplace": "local",
        "version": "1.0.0",
        "installed_at": timestamp,
        "enabled": True,
        "cache_path": skill_path
    })

# Merge: keep non-local plugins, replace local ones
existing = config.get("installed_plugins", [])
kept = [p for p in existing if not (p.get("marketplace") == "local" and p.get("name") in skills)]
config["installed_plugins"] = kept + new_plugins

os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
PYEOF

write_ok "Registered ${#skills[@]} skills in: $COPILOT_CONFIG"
for skill in "${skills[@]}"; do
    echo -e "${GREEN}    + $skill${NC}"
done

# ============================================================
# Phase 5: Landing Zone Configuration (Optional)
# ============================================================

write_banner "Phase 5: Landing Zone Programs (Optional)"

echo -e "${GRAY}  The Landing Zone skill queries ADO saved queries for program requirements.${NC}"
echo -e "${GRAY}  If you use Landing Zone, configure your programs now.${NC}"
echo -e "${GRAY}  You can skip this and configure later by editing skills/landing-zone/programs.json${NC}"
echo ""

lzConfigPath="$PROJECT_ROOT/skills/landing-zone/programs.json"

if read_yesno "Configure Landing Zone programs?" "false"; then
    programs="{"
    add_more=true
    count=0

    while $add_more; do
        echo ""
        write_step "Add a Landing Zone program"
        echo -ne "${WHITE}  Program slug (e.g., my-program): ${NC}"
        read -r prog_slug
        if [[ -z "$prog_slug" ]]; then break; fi

        echo -ne "${WHITE}  ADO Organization name: ${NC}"
        read -r ado_org
        if [[ -z "$ado_org" ]]; then break; fi

        echo -ne "${WHITE}  ADO Project name: ${NC}"
        read -r ado_project
        if [[ -z "$ado_project" ]]; then break; fi

        echo -ne "${WHITE}  ADO Saved Query GUID: ${NC}"
        read -r query_id
        if [[ -z "$query_id" ]]; then break; fi

        if [[ $count -gt 0 ]]; then programs="$programs,"; fi
        programs="$programs \"$prog_slug\": {\"org\": \"$ado_org\", \"project\": \"$ado_project\", \"query_id\": \"$query_id\"}"
        count=$((count + 1))
        write_ok "Added: $prog_slug -> $ado_org/$ado_project ($query_id)"

        if ! read_yesno "Add another program?" "false"; then
            add_more=false
        fi
    done

    programs="$programs }"
    if [[ $count -gt 0 ]]; then
        echo "$programs" | python3 -c "import sys,json; print(json.dumps(json.loads(sys.stdin.read()), indent=2))" > "$lzConfigPath"
        write_ok "Landing Zone config written to: skills/landing-zone/programs.json ($count programs)"
    else
        write_warn "No programs configured. You can add them later to skills/landing-zone/programs.json"
    fi
else
    echo -e "${GRAY}  Skipped. See skills/landing-zone/programs.json.example for the format.${NC}"
fi

# ============================================================
# Phase 6: Git Hooks & Security
# ============================================================

write_banner "Phase 6: Security Hardening"

# Install pre-commit hook
write_step "Installing pre-commit hook..."
hook_source="$PROJECT_ROOT/scripts/pre-commit"
hook_dest="$PROJECT_ROOT/.git/hooks/pre-commit"
if [[ -f "$hook_source" ]]; then
    cp "$hook_source" "$hook_dest"
    chmod +x "$hook_dest"
    write_ok "Pre-commit hook installed"
else
    write_warn "scripts/pre-commit not found, skipping"
fi

# Security scripts (gracefully skip if PS1-only)
write_step "Running security checks..."
if [[ -f "scripts/security-audit.sh" ]]; then
    bash "scripts/security-audit.sh" || write_warn "Security audit had issues"
elif has_cmd pwsh && [[ -f "scripts/security-audit.ps1" ]]; then
    pwsh -File "scripts/security-audit.ps1" || write_warn "Security audit had issues"
else
    write_warn "No security audit script for this platform (scripts/security-audit.sh not found)"
fi

# ============================================================
# Phase 7: Optional Dependencies
# ============================================================

write_banner "Phase 7: Optional Dependencies"

echo -e "${GRAY}  These tools enhance specific skills. You can install them now${NC}"
echo -e "${GRAY}  or later. The agent works without them but some skills will${NC}"
echo -e "${GRAY}  be limited.${NC}"
echo ""

# Parse INSTALL_DEPS into flags
install_markitdown=false
install_qmd=false
install_specify=false
install_handy=false

if [[ -n "$INSTALL_DEPS" ]]; then
    deps_lower="$(echo "$INSTALL_DEPS" | tr '[:upper:]' '[:lower:]')"
    case "$deps_lower" in
        *all*)
            install_markitdown=true
            install_qmd=true
            ;;
        *none*) ;;
        *)
            [[ "$deps_lower" == *markitdown* ]] && install_markitdown=true
            [[ "$deps_lower" == *qmd* ]] && install_qmd=true
            [[ "$deps_lower" == *specify* ]] && install_specify=true
            [[ "$deps_lower" == *handy* ]] && install_handy=true
            ;;
    esac
fi

# Helper: install a Python package using the best available method
# Usage: install_python_pkg <package-spec> <command-to-check> <friendly-name>
# Tries: (1) check if already installed, (2) uv tool, (3) pipx, (4) brew, (5) pip
install_python_pkg() {
    local pkg_spec="$1"       # e.g. "markitdown[all]"
    local check_cmd="$2"      # e.g. "markitdown"  — command name to test
    local friendly="$3"       # e.g. "MarkItDown"
    local brew_name="${4:-}"   # optional brew formula name

    # 1. Already installed?
    if has_cmd "$check_cmd"; then
        write_ok "$friendly already installed ($(command -v $check_cmd))"
        SKIPPED_COMPONENTS+=("$friendly")
        return 0
    fi

    # 2. uv tool install (best: manages its own venv, no system pollution)
    if has_cmd uv; then
        write_step "Installing $friendly via uv..."
        if uv tool install "$pkg_spec" 2>&1; then
            write_ok "$friendly installed via uv"
            return 0
        fi
        write_warn "uv install failed, trying next method..."
    fi

    # 3. pipx (same isolation as uv, just older)
    if has_cmd pipx; then
        write_step "Installing $friendly via pipx..."
        if pipx install "$pkg_spec" 2>&1; then
            write_ok "$friendly installed via pipx"
            return 0
        fi
        write_warn "pipx install failed, trying next method..."
    fi

    # 4. brew (if a formula exists)
    if [[ -n "$brew_name" ]] && has_cmd brew; then
        write_step "Installing $friendly via Homebrew..."
        if brew install "$brew_name" 2>&1; then
            write_ok "$friendly installed via Homebrew"
            return 0
        fi
        write_warn "brew install failed, trying next method..."
    fi

    # 5. pip (last resort — may need --break-system-packages)
    if [[ -n "$PIP_CMD" ]]; then
        write_step "Installing $friendly via pip..."
        if $PIP_CMD install $PIP_EXTRA "$pkg_spec" 2>&1; then
            write_ok "$friendly installed via pip"
            return 0
        fi
        write_warn "pip install failed"
    fi

    write_warn "Could not install $friendly. Install manually: pip3 install $pkg_spec"
    return 1
}

# Helper: install a pip library (not a CLI tool — no command to check)
# Usage: install_pip_lib <package-spec> <import-name> [<friendly-name>]
install_pip_lib() {
    local pkg_spec="$1"
    local import_name="$2"      # Python import name to test (e.g. "dotenv" for python-dotenv)
    local friendly="${3:-$1}"    # defaults to package spec

    # Check if already importable
    if python3 -c "import $import_name" 2>/dev/null; then
        write_ok "$friendly already installed"
        SKIPPED_COMPONENTS+=("$friendly")
        return 0
    fi

    # Try uv pip > pip
    if has_cmd uv; then
        if uv pip install --system "$pkg_spec" 2>&1; then
            write_ok "$friendly installed via uv pip"
            return 0
        fi
    fi
    if [[ -n "$PIP_CMD" ]]; then
        if $PIP_CMD install $PIP_EXTRA "$pkg_spec" 2>&1; then
            write_ok "$friendly installed via pip"
            return 0
        fi
    fi

    write_warn "Could not install $friendly. Install manually: pip3 install $pkg_spec"
    return 1
}

# MarkItDown
if [[ -z "$INSTALL_DEPS" ]]; then
    if read_yesno "Install MarkItDown? (converts PDF/Word/Excel to markdown)" "true"; then
        install_markitdown=true
    fi
fi
if $install_markitdown; then
    install_python_pkg "markitdown[all]" "markitdown" "MarkItDown" || true
fi

# Handy (speech-to-text)
if [[ -z "$INSTALL_DEPS" ]]; then
    if read_yesno "Install Handy? (offline speech-to-text, uses Whisper)" "false"; then
        install_handy=true
    fi
fi
if $install_handy; then
    if command -v handy &>/dev/null || [[ -d "/Applications/Handy.app" ]]; then
        write_ok "Handy already installed"
    else
        write_step "Installing Handy (speech-to-text)..."
        if [[ "$OSTYPE" == darwin* ]] && command -v brew &>/dev/null; then
            brew install --cask handy 2>&1 || true
            if [[ -d "/Applications/Handy.app" ]]; then
                write_ok "Handy installed"
            else
                write_warn "Handy install may have had issues -- check output above"
            fi
        elif [[ "$OSTYPE" == linux* ]]; then
            write_warn "Handy on Linux: download from https://github.com/cjpais/handy/releases"
        else
            write_warn "Install Handy manually from https://github.com/cjpais/handy/releases"
        fi
    fi
fi

# QMD
if [[ -z "$INSTALL_DEPS" ]]; then
    if read_yesno "Install QMD? (local hybrid search for memory, requires Node.js 22 LTS)" "true"; then
        install_qmd=true
    fi
fi
if $install_qmd; then
    # Check Node version — QMD requires Node 22 LTS (better-sqlite3 has no prebuilds for 24+)
    node_major="$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1)"
    if [[ -z "$node_major" || "$node_major" -lt 22 ]]; then
        write_warn "QMD requires Node.js 22 LTS. Current: $(node --version 2>/dev/null || echo 'not found')"
        write_warn "Skipping QMD install. Install Node.js 22 LTS and re-run setup to enable memory search."
        install_qmd=false
    elif [[ "$node_major" -gt 22 ]]; then
        write_warn "Node.js $node_major detected — better-sqlite3 may lack prebuilds for this version."
        write_warn "Recommended: use Node.js 22 LTS. If QMD install fails, switch to Node 22 and re-run."
    fi
fi
if $install_qmd; then
    # Check if already installed
    if has_cmd qmd; then
        write_ok "QMD already installed ($(command -v qmd))"
        SKIPPED_COMPONENTS+=("QMD")
        # Verify native modules match current Node version
        # Cache the Node ABI version after a successful rebuild to avoid expensive rebuilds on every run
        node_abi="$(node -e 'console.log(process.versions.modules)' 2>/dev/null || echo unknown)"
        abi_cache="$HOME/.agency-cowork/qmd-node-abi"
        cached_abi=""
        [[ -f "$abi_cache" ]] && cached_abi="$(cat "$abi_cache" 2>/dev/null)"
        if [[ "$node_abi" == "$cached_abi" ]]; then
            write_ok "QMD native modules up to date (Node ABI $node_abi)"
        elif ! qmd status >/dev/null 2>&1; then
            write_warn "QMD installed but native modules need rebuild for Node ABI $node_abi..."
            qmd_dir="$(npm root -g 2>/dev/null)/@tobilu/qmd"
            if [[ -d "$qmd_dir" ]]; then
                if (cd "$qmd_dir" && npm rebuild better-sqlite3 2>&1); then
                    echo "$node_abi" > "$abi_cache"
                    write_ok "Rebuild successful — cached ABI $node_abi"
                else
                    write_warn "Rebuild failed"
                fi
            fi
        else
            # qmd status works — cache the current ABI
            echo "$node_abi" > "$abi_cache"
        fi
    else
        write_step "Installing QMD..."
        npm install -g --prefix "$HOME/.npm-global" @tobilu/qmd 2>&1 || write_warn "QMD install had issues"
        # Ensure user-level npm bin is on PATH
        if [ -d "$HOME/.npm-global/bin" ] && ! echo "$PATH" | grep -q "$HOME/.npm-global/bin"; then
            export PATH="$HOME/.npm-global/bin:$PATH"
        fi
    fi
    if has_cmd qmd; then
        write_ok "QMD installed"

        # Create a QMD launcher script that auto-rebuilds native modules if needed
        qmd_launcher="$HOME/.agency-cowork/qmd-launcher.sh"
        cat > "$qmd_launcher" << 'LAUNCHER'
#!/bin/bash
# Auto-rebuild better-sqlite3 if Node ABI changed, then start QMD MCP
if ! qmd status >/dev/null 2>&1; then
    qmd_dir="$(npm root -g 2>/dev/null)/@tobilu/qmd"
    if [[ -d "$qmd_dir" ]]; then
        (cd "$qmd_dir" && npm rebuild better-sqlite3 2>/dev/null)
    fi
fi
exec qmd mcp "$@"
LAUNCHER
        chmod +x "$qmd_launcher"

        # Add QMD to MCP config using the launcher (auto-rebuilds on Node version change)
        # Check .mcp.json first, then global mcp-config.json
        if [[ -f "$MCP_CONFIG" ]]; then
            python3 -c "
import json, sys
try:
    mcp_path, launcher = sys.argv[1], sys.argv[2]
    with open(mcp_path, 'r') as f:
        cfg = json.load(f)
    # Support both 'mcpServers' (.mcp.json) and 'servers' (legacy)
    s_key = 'mcpServers' if 'mcpServers' in cfg else 'servers' if 'servers' in cfg else 'mcpServers'
    servers = cfg.setdefault(s_key, {})
    servers['qmd'] = {'command': 'bash', 'args': [launcher]}
    with open(mcp_path, 'w') as f:
        json.dump(cfg, f, indent=2)
        f.write('\n')
    print('  [OK] QMD MCP config set (with auto-rebuild launcher)')
except Exception as e:
    print(f'  [!!] Could not update MCP config: {e}', file=sys.stderr)
" "$MCP_CONFIG" "$qmd_launcher" 2>&1
        fi

        # Install sentence-transformers
        install_pip_lib "sentence-transformers" "sentence_transformers" "sentence-transformers" || true

        # Test embedding provider
        write_step "Testing SentenceTransformer embedding provider..."
        if python3 skills/qmd-memory/scripts/azure-embed.py --test 2>&1; then
            write_ok "SentenceTransformer embedding provider working"
        else
            write_warn "SentenceTransformer test failed (QMD keyword search still works without embeddings)"
        fi

        # QMD collection setup — register project directories for memory search
        if read_yesno "Run QMD collection setup now?" "true"; then
            write_step "Registering QMD collections for $PROJECT_ROOT..."
            # Define collections as simple lists (avoids declare -A + set -u issues)
            col_names=("memory-root" "knowledgebase" "weekly-reports" "skills-docs")
            col_paths=("$PROJECT_ROOT/memory" "$PROJECT_ROOT/memory/Knowledgebase" "$PROJECT_ROOT/memory/WeeklyReports" "$PROJECT_ROOT/skills")
            col_masks=("*.md" "**/*.md" "**/*.md" "**/SKILL.md")
            for i in "${!col_names[@]}"; do
                col_name="${col_names[$i]}"
                col_path="${col_paths[$i]}"
                col_mask="${col_masks[$i]}"
                if [[ -d "$col_path" ]]; then
                    # Remove existing collection (may point to old path), then re-add
                    qmd collection remove "$col_name" 2>/dev/null || true
                    qmd collection add "$col_path" --name "$col_name" --mask "$col_mask" 2>&1 || \
                        write_warn "Failed to add QMD collection: $col_name"
                    write_ok "QMD collection: $col_name → $col_path"
                else
                    write_warn "Skipping QMD collection $col_name (path not found: $col_path)"
                    mkdir -p "$col_path" 2>/dev/null && \
                        qmd collection add "$col_path" --name "$col_name" --mask "$col_mask" 2>/dev/null && \
                        write_ok "QMD collection: $col_name → $col_path (created)" || true
                fi
            done

            # Run initial indexing
            write_step "Running QMD text indexing..."
            qmd update 2>&1 || write_warn "QMD text indexing had issues"
            write_ok "QMD collections registered and indexed"
        fi
    else
        write_warn "QMD install may have had issues -- check output above"
    fi
fi

# Specify CLI
if [[ -z "$INSTALL_DEPS" ]]; then
    if read_yesno "Install Specify CLI? (spec-driven development from GitHub)" "false"; then
        install_specify=true
    fi
fi
if $install_specify; then
    if has_cmd specify; then
        write_ok "Specify CLI already installed ($(command -v specify))"
        SKIPPED_COMPONENTS+=("Specify CLI")
    else
        write_step "Installing specify-cli..."
        if has_cmd uv; then
            uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git" 2>&1 || \
                write_warn "Specify CLI install had issues"
        elif has_cmd pipx; then
            pipx install "git+https://github.com/github/spec-kit.git" 2>&1 || \
                write_warn "Specify CLI install had issues"
        elif [[ -n "$PIP_CMD" ]]; then
            $PIP_CMD install $PIP_EXTRA "git+https://github.com/github/spec-kit.git" 2>&1 || \
                write_warn "Specify CLI install had issues"
        else
            write_warn "No pip/uv/pipx available. Install specify-cli manually."
        fi
        has_cmd specify && write_ok "Specify CLI installed" || write_warn "Specify CLI may not be on PATH"
    fi
fi

# Teams Rich Messaging & Monitor
echo ""
write_step "Setting up Teams skill dependencies..."
teams_reqs="$PROJECT_ROOT/skills/teams/requirements.txt"
if [[ -f "$teams_reqs" ]]; then
    # Check if all requirements are already satisfied
    if has_cmd uv; then
        check_output=$(uv pip install --system --dry-run -r "$teams_reqs" 2>&1 || true)
    elif [[ -n "$PIP_CMD" ]]; then
        check_output=$($PIP_CMD install $PIP_EXTRA --dry-run -r "$teams_reqs" 2>&1 || true)
    else
        check_output="no-pip"
    fi
    if echo "$check_output" | grep -q "Would install"; then
        write_step "Installing Teams Python dependencies..."
        if has_cmd uv; then
            uv pip install --system -r "$teams_reqs" 2>&1 || write_warn "Teams uv install had issues"
            write_ok "Teams Python dependencies installed via uv"
        elif [[ -n "$PIP_CMD" ]]; then
            $PIP_CMD install $PIP_EXTRA -r "$teams_reqs" 2>&1 || write_warn "Teams pip install had issues"
            write_ok "Teams Python dependencies installed via pip"
        fi
    elif [[ "$check_output" == "no-pip" ]]; then
        write_warn "No pip or uv available. Install Teams deps manually: pip3 install -r $teams_reqs"
    else
        write_ok "Teams Python dependencies already installed"
        SKIPPED_COMPONENTS+=("Teams Python deps")
    fi
else
    write_warn "skills/teams/requirements.txt not found, skipping"
fi

# Playwright browser
playwright_browser=""
if [[ "$PLATFORM" == "Darwin" ]]; then
    playwright_browser="msedge"
else
    playwright_browser="chromium"
fi

if [[ -z "$INSTALL_DEPS" ]]; then
    install_playwright=false
    if read_yesno "Install Playwright $playwright_browser driver? (needed for @mentions, Adaptive Cards)" "true"; then
        install_playwright=true
    fi
else
    install_playwright=true
fi

if $install_playwright; then
    # For msedge, Playwright uses the system browser -- check if it's already available
    browser_found=false
    if [[ "$playwright_browser" == "msedge" ]]; then
        # macOS: check for Edge in Applications
        if [[ -d "/Applications/Microsoft Edge.app" ]]; then
            # Also verify playwright Python package is installed
            if python3 -c "import playwright" 2>/dev/null; then
                browser_found=true
            fi
        fi
    else
        # chromium: check Playwright cache directory
        pw_browsers_dir="$HOME/.cache/ms-playwright"
        if [[ -d "$pw_browsers_dir" ]] && ls "$pw_browsers_dir" | grep -q "$playwright_browser" 2>/dev/null; then
            if python3 -c "import playwright" 2>/dev/null; then
                browser_found=true
            fi
        fi
    fi

    if $browser_found; then
        write_ok "Playwright $playwright_browser driver already installed"
        SKIPPED_COMPONENTS+=("Playwright $playwright_browser")
    else
        write_step "Installing Playwright $playwright_browser driver..."
        python3 -m playwright install "$playwright_browser" 2>&1 || write_warn "Playwright install had issues"
        # On Ubuntu, also install system dependencies
        if [[ "$PLATFORM" == "Linux" ]]; then
            write_step "Installing Playwright system dependencies..."
            python3 -m playwright install-deps 2>&1 || write_warn "Playwright system deps install had issues"
        fi
        write_ok "Playwright $playwright_browser driver installed"
    fi
fi

# Monitor service notice
echo ""
echo -e "${GRAY}  Teams Monitor Service (real-time channel/chat monitoring):${NC}"
echo -e "${GRAY}    The monitor service listens for @agent mentions in Teams${NC}"
echo -e "${GRAY}    and dispatches prompts to the AI agent. It is OFF by default.${NC}"
echo ""
echo -e "${YELLOW}    To enable:${NC}"
echo -e "${WHITE}      1. Set monitor.enabled=true in agentconfig.json${NC}"
echo -e "${WHITE}      2. Configure monitor settings in the Settings panel or ~/.agency-cowork/monitor-config.json${NC}"
echo -e "${WHITE}      3. Start: cd skills/teams && python3 -m scripts.monitor.service start${NC}"
echo ""
echo -e "${RED}    SECURITY: Review threatmodel.md (T11, T12) before enabling.${NC}"
echo -e "${RED}    The service executes prompts unattended with your M365 identity.${NC}"
echo ""

# ============================================================
# Phase 8: Verification
# ============================================================

write_banner "Phase 8: Verification"

write_step "Running offline test suite..."
if [[ -f "tests/run-offline-tests.sh" ]]; then
    bash "tests/run-offline-tests.sh" || write_warn "Some tests failed"
elif has_cmd pwsh && [[ -f "tests/run-offline-tests.ps1" ]]; then
    pwsh -File "tests/run-offline-tests.ps1" || write_warn "Some tests failed"
else
    write_warn "No test suite found for this platform, skipping verification"
fi

# ============================================================
# Summary
# ============================================================

write_banner "Setup Complete!"

echo -e "${WHITE}  Agent:  $agentName ($agentRole)${NC}"
if [[ -n "$userName" ]]; then echo -e "${WHITE}  User:   $userName <$userEmail>${NC}"; fi
if [[ -n "$userOrg" ]]; then echo -e "${WHITE}  Org:    $userOrg${NC}"; fi
echo -e "${WHITE}  Memory: ${memoryRepo:-local}${NC}"
echo -e "${WHITE}  Tenant: $tenantId${NC}"
echo ""
echo -e "${GRAY}  Files configured:${NC}"
echo -e "${GRAY}    CLAUDE.md              Agent identity${NC}"
if [[ -f "memory/MEMORY.md" ]]; then
    echo -e "${GRAY}    memory/MEMORY.md       User profile & contacts${NC}"
fi
echo -e "${GRAY}    $MCP_CONFIG${NC}"
echo -e "${GRAY}    $COPILOT_CONFIG${NC}"
echo ""

# Skipped components summary
if [[ ${#SKIPPED_COMPONENTS[@]} -gt 0 ]]; then
    # Deduplicate the list (no declare -A — macOS ships Bash 3.2)
    unique_skipped=()
    for comp in "${SKIPPED_COMPONENTS[@]}"; do
        local dup=0
        for existing in "${unique_skipped[@]}"; do
            [[ "$existing" == "$comp" ]] && dup=1 && break
        done
        [[ $dup -eq 0 ]] && unique_skipped+=("$comp")
    done
    echo -e "${GRAY}  Pre-existing tools (kept as-is):${NC}"
    for comp in "${unique_skipped[@]}"; do
        echo -e "${GRAY}    - $comp${NC}"
    done
    echo ""
    echo -e "${YELLOW}  To upgrade these, re-run setup interactively:${NC}"
    echo -e "${CYAN}    bash scripts/setup.sh${NC}"
    echo -e "${GRAY}  Or update individually with brew/pip/npm.${NC}"
    echo ""
fi

echo -e "${YELLOW}  Get started:${NC}"
echo ""
echo -e "${CYAN}    cd $PROJECT_ROOT${NC}"
echo -e "${CYAN}    copilot${NC}"
echo ""
echo -e "${WHITE}  This launches Agency Cowork — your AI coworker. Once running,${NC}"
echo -e "${WHITE}  say ${CYAN}\"Personalize my agent\"${WHITE} to run the deep-personalization skill.${NC}"
echo -e "${WHITE}  It will interview you and configure domain knowledge, contacts,${NC}"
echo -e "${WHITE}  communication style, and working preferences automatically.${NC}"
echo ""
echo -e "${GRAY}  After that, you can:${NC}"
echo -e "${GRAY}    - Populate memory/Knowledgebase/ with your reference docs${NC}"
echo -e "${GRAY}    - Run: /skills  -- to verify all skills are loaded${NC}"
echo -e "${GRAY}    - (Optional) Enable Teams monitor -- see installation.md${NC}"
echo ""
echo -e "${GRAY}  Documentation:${NC}"
echo -e "${GRAY}    README.md          Project overview${NC}"
echo -e "${GRAY}    installation.md    Detailed manual setup reference${NC}"
echo -e "${GRAY}    threatmodel.md     Security threat model${NC}"
echo ""
