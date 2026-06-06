#!/usr/bin/env bash
# security-audit.sh — Check for common security issues in the Agency Cowork workspace
#
# Bash equivalent of security-audit.ps1 for macOS & Linux.
#
# Usage: bash scripts/security-audit.sh
#
# Checks:
#   1. Secrets in tracked files
#   2. .env file status
#   3. Identity file integrity (CLAUDE.md, MEMORY.md)
#   4. Scheduled task audit
#   5. MCP config review
#   6. Unexpected executables

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ISSUES=0
WARNINGS=0

# Colors
if [[ -t 1 ]]; then
    CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; GRAY='\033[0;90m'; NC='\033[0m'
else
    CYAN='' GREEN='' YELLOW='' RED='' GRAY='' NC=''
fi

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Agency Cowork -- Security Audit${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# --- 1. Check for secrets in tracked files ---
echo -e "${YELLOW}[1/6] Scanning tracked files for secrets...${NC}"

secret_patterns=(
    'AZURE_OPENAI_API_KEY=[^y]'
    'Bearer [A-Za-z0-9._~+/]{20,}'
    'eyJ[A-Za-z0-9_]{20,}'
    'BEGIN .* KEY'
    'password[[:space:]]*[:=][[:space:]]*[^[:space:]]{8,}'
)
secret_descs=(
    "Azure OpenAI API key"
    "Bearer token"
    "JWT token"
    "PEM private key"
    "Hardcoded password"
)

found_secrets=false
tracked_files="$(git -C "$PROJECT_ROOT" ls-files 2>/dev/null || true)"

if [[ -n "$tracked_files" ]]; then
    while IFS= read -r file; do
        full_path="$PROJECT_ROOT/$file"
        # Skip binary and example files
        [[ "$file" =~ \.(gitkeep|png|jpg|gif|ico|icns)$ ]] && continue
        [[ "$file" == ".env.example" ]] && continue
        [[ ! -f "$full_path" ]] && continue
        # Skip docs, security scripts, and test files that contain example patterns by design
        [[ "$file" =~ ^scripts/(pre-commit|security-audit|setup) ]] && continue
        [[ "$file" =~ ^(installation|threatmodel|TESTING-).*\.md$ ]] && continue
        [[ "$file" =~ ^tests/ ]] && continue
        [[ "$file" =~ ^ui/build\.md$ ]] && continue
        [[ "$file" =~ ^skills/.*/README\.md$ ]] && continue

        for i in "${!secret_patterns[@]}"; do
            if grep -qE -- "${secret_patterns[$i]}" "$full_path" 2>/dev/null; then
                echo -e "${RED}  [FAIL] SECRET: ${secret_descs[$i]} found in $file${NC}"
                found_secrets=true
                ISSUES=$((ISSUES + 1))
            fi
        done
    done <<< "$tracked_files"
fi

if ! $found_secrets; then
    echo -e "${GREEN}  [PASS] No secrets found in tracked files.${NC}"
fi

# --- 2. Check .env file status ---
echo ""
echo -e "${YELLOW}[2/6] Checking environment files...${NC}"

env_file="$PROJECT_ROOT/.env"
if [[ -f "$env_file" ]]; then
    if git -C "$PROJECT_ROOT" ls-files --error-unmatch ".env" &>/dev/null; then
        echo -e "${RED}  [FAIL] .env file is tracked by git!${NC}"
        ISSUES=$((ISSUES + 1))
    else
        echo -e "${GREEN}  [PASS] .env exists but is gitignored (correct).${NC}"
    fi
else
    echo -e "${GREEN}  [PASS] No .env file present.${NC}"
fi

# --- 3. Check identity file integrity ---
echo ""
echo -e "${YELLOW}[3/6] Checking identity file integrity (CLAUDE.md, MEMORY.md)...${NC}"

identity_files=("CLAUDE.md" "memory/MEMORY.md")
for file in "${identity_files[@]}"; do
    full_path="$PROJECT_ROOT/$file"
    if [[ ! -f "$full_path" ]]; then
        echo -e "${YELLOW}  [WARN] $file not found${NC}"
        WARNINGS=$((WARNINGS + 1))
        continue
    fi

    diff_output="$(git -C "$PROJECT_ROOT" diff -- "$file" 2>/dev/null || true)"
    if [[ -n "$diff_output" ]]; then
        echo -e "${YELLOW}  [WARN] $file has uncommitted changes -- review with: git diff $file${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${GREEN}  [PASS] $file matches last commit.${NC}"
    fi
done

# --- 4. Audit scheduled tasks ---
echo ""
echo -e "${YELLOW}[4/6] Auditing scheduled tasks...${NC}"

tasks_dir="$PROJECT_ROOT/skills/task-scheduler/tasks"
if [[ -d "$tasks_dir" ]]; then
    task_files=("$tasks_dir"/task-*.json)
    if [[ -f "${task_files[0]:-}" ]]; then
        echo "  Found ${#task_files[@]} task(s):"
        for tf in "${task_files[@]}"; do
            # Basic check for risky patterns in task prompts
            if grep -qiE '(forward.*email|send.*email.*to|delete|share.*file|post.*channel|download.*from)' "$tf" 2>/dev/null; then
                echo -e "${YELLOW}  [WARN] Potentially risky prompt in $(basename "$tf")${NC}"
                WARNINGS=$((WARNINGS + 1))
            fi
        done
    else
        echo -e "${GREEN}  [PASS] No scheduled tasks found.${NC}"
    fi
else
    echo -e "${GREEN}  [PASS] No scheduled tasks directory.${NC}"
fi

# --- 5. Check MCP config ---
echo ""
echo -e "${YELLOW}[5/6] Checking MCP configuration...${NC}"

# Check .mcp.json (primary) then .vscode/mcp.json (legacy) then global mcp-config.json (fallback)
ws_mcp_config=".mcp.json"
legacy_mcp_config=".vscode/mcp.json"
global_mcp_config="$HOME/.copilot/mcp-config.json"
if [[ -f "$ws_mcp_config" ]]; then
    mcp_config="$ws_mcp_config"
elif [[ -f "$legacy_mcp_config" ]]; then
    mcp_config="$legacy_mcp_config"
elif [[ -f "$global_mcp_config" ]]; then
    mcp_config="$global_mcp_config"
else
    mcp_config=""
fi

if [[ -n "$mcp_config" ]]; then
    # Check for non-Microsoft URLs — support both "servers" and "mcpServers" keys
    if python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
servers = cfg.get('servers', cfg.get('mcpServers', {}))
for name, srv in servers.items():
    url = srv.get('url', '')
    cmd = srv.get('command', '')
    if url:
        if 'agent365.svc.cloud.microsoft' in url:
            print(f'PASS|{name}: Official Microsoft endpoint')
        else:
            print(f'WARN|{name}: Non-standard URL: {url}')
    elif cmd:
        print(f'PASS|{name}: Local command ({cmd})')
" "$mcp_config" 2>/dev/null; then
        : # output printed by python
    else
        echo -e "${YELLOW}  [WARN] Failed to parse $(basename "$mcp_config")${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi | while IFS='|' read -r level msg; do
        if [[ "$level" == "PASS" ]]; then
            echo -e "${GREEN}  [PASS] $msg${NC}"
        else
            echo -e "${YELLOW}  [WARN] $msg${NC}"
            # Can't increment WARNINGS in subshell, but the warning is printed
        fi
    done
else
    echo -e "${GRAY}  [INFO] No MCP config found (checked .mcp.json, .vscode/mcp.json, and ~/.copilot/mcp-config.json)${NC}"
fi

# --- 6. Check file system ---
echo ""
echo -e "${YELLOW}[6/6] Checking file system...${NC}"

# Look for unexpected executables (skip node_modules, .git, .venv)
suspicious="$(find "$PROJECT_ROOT" \( -name "*.exe" -o -name "*.dll" -o -name "*.bat" -o -name "*.cmd" -o -name "*.vbs" \) \
    -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/.venv/*" 2>/dev/null || true)"

if [[ -z "$suspicious" ]]; then
    echo -e "${GREEN}  [PASS] No unexpected executable files found.${NC}"
else
    while IFS= read -r sf; do
        echo -e "${YELLOW}  [WARN] Unexpected executable: $sf${NC}"
        WARNINGS=$((WARNINGS + 1))
    done <<< "$suspicious"
fi

# --- Summary ---
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Audit Summary${NC}"
echo -e "${CYAN}========================================${NC}"

if [[ $ISSUES -eq 0 && $WARNINGS -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}  [PASS] All checks passed. No issues found.${NC}"
    echo ""
else
    if [[ $ISSUES -gt 0 ]]; then
        echo ""
        echo -e "${RED}  $ISSUES critical issue(s) found.${NC}"
    fi
    if [[ $WARNINGS -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}  $WARNINGS warning(s) found.${NC}"
    fi
    echo ""
fi

if [[ $ISSUES -gt 0 ]]; then exit 1; else exit 0; fi
