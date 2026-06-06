#!/usr/bin/env bash
# ============================================================
# update.sh — Pull the latest Agency Cowork updates from upstream
#              while preserving local customizations.
#
# macOS/Linux equivalent of update.ps1.
#
# Strategy:
#   1. Stash any uncommitted local changes
#   2. Fetch the latest from upstream
#   3. Pre-merge: warn about local-only files at risk of deletion
#   4. Back up personalized files (from .update-preserve manifest)
#   5. Merge upstream/main into your current branch
#   6. Post-merge: regression check on restored files
#   7. Detect upstream template changes & generate diff report
#   8. Stamp agencycowork.json with current version
#   9. Restore stashed changes
#
# Usage:
#   bash scripts/update.sh
#   bash scripts/update.sh --dry-run
#   bash scripts/update.sh --upstream-branch develop
#   bash scripts/update.sh --force
# ============================================================

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────
UPSTREAM_URL="https://github.com/ahsi-microsoft/agency-cowork.git"
UPSTREAM_BRANCH="main"
DRY_RUN=false
FORCE=false

# ── Argument Parsing ────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --upstream-url)     UPSTREAM_URL="$2"; shift 2 ;;
        --upstream-branch)  UPSTREAM_BRANCH="$2"; shift 2 ;;
        --dry-run)          DRY_RUN=true; shift ;;
        --force)            FORCE=true; shift ;;
        -h|--help)
            echo "Usage: bash scripts/update.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --upstream-url URL       Upstream repo URL (default: ahsi-microsoft/agency-cowork)"
            echo "  --upstream-branch BRANCH Upstream branch (default: main)"
            echo "  --dry-run                Show what would happen without making changes"
            echo "  --force                  Skip confirmation prompts"
            echo "  -h, --help               Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage."
            exit 1
            ;;
    esac
done

# ── Resolve paths ───────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Color helpers ───────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
DARKGREEN='\033[0;32m'
NC='\033[0m' # No Color

banner()  { echo -e "\n${CYAN}$(printf '=%.0s' {1..60})\n  $1\n$(printf '=%.0s' {1..60})${NC}\n"; }
step()    { echo -e "  ${YELLOW}>> $1${NC}"; }
ok()      { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "  ${YELLOW}[!!]${NC} $1"; }
err()     { echo -e "  ${RED}[FAIL]${NC} $1"; }
gray()    { echo -e "    ${GRAY}$1${NC}"; }

# ── Default personalized files (fallback if no manifest) ────
DEFAULT_PERSONALIZED_FILES=(
    "CLAUDE.md"
    "AGENTS.md"
    "agentconfig.json"
    ".context-merge.json"
    "CLAUDE.md.example"
    "AGENTS.md.example"
)

# ════════════════════════════════════════════════════════════
# Resolve .update-preserve manifest
# ════════════════════════════════════════════════════════════
resolve_preserve_manifest() {
    local manifest="$PROJECT_ROOT/.update-preserve"
    if [[ ! -f "$manifest" ]]; then
        return 1
    fi

    local resolved=()
    while IFS= read -r line; do
        # Skip comments and blank lines
        line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "$line" || "$line" == \#* ]] && continue

        # Directory patterns (ending with /)
        if [[ "$line" == */ ]]; then
            local dir_path="$PROJECT_ROOT/${line%/}"
            if [[ -d "$dir_path" ]]; then
                while IFS= read -r -d '' child; do
                    local rel="${child#$PROJECT_ROOT/}"
                    resolved+=("$rel")
                done < <(find "$dir_path" -type f -print0 2>/dev/null)
            fi
            continue
        fi

        # Glob patterns (contain *, ?, or [)
        if [[ "$line" == *[\*\?\[]* ]]; then
            # Use bash glob expansion from project root
            local matches
            matches=( $PROJECT_ROOT/$line )
            for m in "${matches[@]}"; do
                if [[ -f "$m" ]]; then
                    local rel="${m#$PROJECT_ROOT/}"
                    resolved+=("$rel")
                fi
            done
            continue
        fi

        # Literal path
        local full_path="$PROJECT_ROOT/$line"
        if [[ -f "$full_path" ]]; then
            resolved+=("$line")
        elif [[ -d "$full_path" ]]; then
            # Bare directory name — protect all contents recursively
            while IFS= read -r -d '' child; do
                local rel="${child#$PROJECT_ROOT/}"
                resolved+=("$rel")
            done < <(find "$full_path" -type f -print0 2>/dev/null)
        fi
    done < "$manifest"

    # Deduplicate and sort
    if [[ ${#resolved[@]} -gt 0 ]]; then
        printf '%s\n' "${resolved[@]}" | sort -u
        return 0
    fi
    return 1
}

# Resolve personalized files
PERSONALIZED_FILES=()
USING_MANIFEST=false

manifest_output="$(resolve_preserve_manifest)" && {
    while IFS= read -r f; do
        PERSONALIZED_FILES+=("$f")
    done <<< "$manifest_output"
    USING_MANIFEST=true
}

if [[ ${#PERSONALIZED_FILES[@]} -eq 0 ]]; then
    PERSONALIZED_FILES=("${DEFAULT_PERSONALIZED_FILES[@]}")
    USING_MANIFEST=false
fi

# Auto-protect task-scheduler task definitions (user-created, never shipped by upstream).
# Without this, upgrades silently delete all scheduled tasks. Fixes #218.
TASKS_PROTECT_DIR="$PROJECT_ROOT/skills/task-scheduler/tasks"
if [[ -d "$TASKS_PROTECT_DIR" ]]; then
    while IFS= read -r -d '' f; do
        rel="${f#$PROJECT_ROOT/}"
        PERSONALIZED_FILES+=("$rel")
    done < <(find "$TASKS_PROTECT_DIR" -maxdepth 1 -name "*.json" -type f -print0 2>/dev/null)
fi

# ════════════════════════════════════════════════════════════
# Pre-flight checks
# ════════════════════════════════════════════════════════════
banner "Agency Cowork - Update from Upstream"

if $DRY_RUN; then
    warn "DRY RUN - no changes will be made"
    echo ""
fi

# Verify git repo
if [[ ! -d ".git" ]]; then
    err "Not a git repository. Run this script from your Agency Cowork project root."
    exit 1
fi

# Current branch
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
ok "Current branch: $CURRENT_BRANCH"

# Report preserve source
if $USING_MANIFEST; then
    ok "Preserve manifest: .update-preserve (${#PERSONALIZED_FILES[@]} file(s) resolved)"
else
    warn "No .update-preserve found - using default protect list (3 files)"
    gray "Create .update-preserve to protect org-specific files. See README."
fi

# ════════════════════════════════════════════════════════════
# Step 1: Stash local changes
# ════════════════════════════════════════════════════════════
banner "Step 1: Stash Local Changes"

DID_STASH=false
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    STASH_NAME="agency-cowork-update-$(date +%Y%m%d-%H%M%S)"
    step "Uncommitted changes detected. Stashing as: $STASH_NAME"
    if ! $DRY_RUN; then
        if ! git stash push -m "$STASH_NAME" --include-untracked 2>&1 | while IFS= read -r l; do gray "$l"; done; then
            err "Failed to stash changes. Aborting."
            exit 1
        fi
        ok "Changes stashed"
    else
        gray "Would stash uncommitted changes"
    fi
    DID_STASH=true
else
    ok "Working tree is clean"
fi

# ════════════════════════════════════════════════════════════
# Step 2: Configure upstream remote
# ════════════════════════════════════════════════════════════
banner "Step 2: Configure Upstream Remote"

EXISTING_UPSTREAM="$(git remote get-url upstream 2>/dev/null || true)"
if [[ -n "$EXISTING_UPSTREAM" ]]; then
    if [[ "$EXISTING_UPSTREAM" != "$UPSTREAM_URL" ]]; then
        warn "Upstream remote exists but points to: $EXISTING_UPSTREAM"
        step "Updating to: $UPSTREAM_URL"
        if ! $DRY_RUN; then
            git remote set-url upstream "$UPSTREAM_URL" 2>/dev/null
        fi
    fi
    ok "Upstream remote: $UPSTREAM_URL"
else
    step "Adding upstream remote: $UPSTREAM_URL"
    if ! $DRY_RUN; then
        git remote add upstream "$UPSTREAM_URL" 2>/dev/null
    fi
    ok "Upstream remote added"
fi

# ════════════════════════════════════════════════════════════
# Step 3: Fetch upstream
# ════════════════════════════════════════════════════════════
banner "Step 3: Fetch Upstream Changes"

step "Fetching upstream/$UPSTREAM_BRANCH..."
if ! $DRY_RUN; then
    if ! git fetch upstream "$UPSTREAM_BRANCH" 2>&1 | while IFS= read -r l; do gray "$l"; done; then
        err "Failed to fetch from upstream. Check your network and repo access."
        if $DID_STASH; then
            step "Restoring stashed changes..."
            git stash pop 2>/dev/null || true
        fi
        exit 1
    fi
    ok "Fetched upstream/$UPSTREAM_BRANCH"
else
    gray "Would fetch upstream/$UPSTREAM_BRANCH"
fi

# Show what's new
step "Changes since last update:"
LOG_OUTPUT="$(git log --oneline "$CURRENT_BRANCH..upstream/$UPSTREAM_BRANCH" 2>/dev/null || true)"
if [[ -n "$LOG_OUTPUT" ]]; then
    echo "$LOG_OUTPUT" | head -20 | while IFS= read -r l; do gray "$l"; done
    TOTAL_COMMITS="$(echo "$LOG_OUTPUT" | wc -l | tr -d ' ')"
    if [[ "$TOTAL_COMMITS" -gt 20 ]]; then
        gray "... and $((TOTAL_COMMITS - 20)) more commits"
    fi
    echo ""
    echo -e "  ${NC}$TOTAL_COMMITS new commit(s) from upstream"
else
    ok "Already up to date with upstream/$UPSTREAM_BRANCH"
    if $DID_STASH; then
        step "Restoring stashed changes..."
        if ! $DRY_RUN; then git stash pop 2>/dev/null || true; fi
    fi
    exit 0
fi

# Confirm before merging
if ! $FORCE && ! $DRY_RUN; then
    echo ""
    echo -e "  This will merge $TOTAL_COMMITS commit(s) into your $CURRENT_BRANCH branch."
    PRESERVE_SOURCE="default list"
    $USING_MANIFEST && PRESERVE_SOURCE=".update-preserve manifest"
    echo -e "  ${#PERSONALIZED_FILES[@]} personalized file(s) will be protected via $PRESERVE_SOURCE."
    echo ""
    read -r -p "  Continue? [Y/n] " confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        warn "Update cancelled by user"
        if $DID_STASH; then
            step "Restoring stashed changes..."
            git stash pop 2>/dev/null || true
        fi
        exit 0
    fi
fi

# ════════════════════════════════════════════════════════════
# Step 3.5: Pre-merge deletion warning
# ════════════════════════════════════════════════════════════
banner "Step 3.5: Check for Local-Only Files at Risk"

UPSTREAM_FILES="$(git ls-tree -r --name-only "upstream/$UPSTREAM_BRANCH" 2>/dev/null || true)"
LOCAL_TRACKED_FILES="$(git ls-files 2>/dev/null || true)"

if [[ -n "$UPSTREAM_FILES" && -n "$LOCAL_TRACKED_FILES" ]]; then
    # Build a set of upstream files (one per line in a temp file for fast lookup)
    UPSTREAM_TMP="$(mktemp)"
    echo "$UPSTREAM_FILES" | sort > "$UPSTREAM_TMP"

    # Find local-only files not in upstream
    LOCAL_ONLY="$(echo "$LOCAL_TRACKED_FILES" | sort | comm -23 - "$UPSTREAM_TMP")"
    rm -f "$UPSTREAM_TMP"

    # Filter out files already protected by .update-preserve
    AT_RISK=()
    if [[ -n "$LOCAL_ONLY" ]]; then
        while IFS= read -r lf; do
            protected=false
            for pf in "${PERSONALIZED_FILES[@]}"; do
                if [[ "$lf" == "$pf" ]]; then
                    protected=true
                    break
                fi
            done
            if ! $protected; then
                AT_RISK+=("$lf")
            fi
        done <<< "$LOCAL_ONLY"
    fi

    if [[ ${#AT_RISK[@]} -gt 0 ]]; then
        warn "${#AT_RISK[@]} local-only file(s) not in upstream and not protected:"
        for rf in "${AT_RISK[@]}"; do
            echo -e "    ${YELLOW}$rf${NC}"
        done
        echo ""
        echo -e "  ${YELLOW}These files may be deleted during merge.${NC}"
        echo -e "  ${YELLOW}Add them to .update-preserve to protect them, or press Enter to continue.${NC}"
        echo ""

        if ! $FORCE && ! $DRY_RUN; then
            # Auto-backup at-risk files
            AT_RISK_BACKUP="$PROJECT_ROOT/.update-backup-atrisk"
            mkdir -p "$AT_RISK_BACKUP"
            for rf in "${AT_RISK[@]}"; do
                rf_full="$PROJECT_ROOT/$rf"
                if [[ -f "$rf_full" ]]; then
                    dest_dir="$AT_RISK_BACKUP/$(dirname "$rf")"
                    mkdir -p "$dest_dir"
                    cp "$rf_full" "$AT_RISK_BACKUP/$rf"
                fi
            done
            ok "Safety backup created at .update-backup-atrisk/ (just in case)"
        fi
    else
        ok "No unprotected local-only files at risk"
    fi
else
    ok "Could not compare trees - skipping local-only file check"
fi

# ════════════════════════════════════════════════════════════
# Step 3.8: Stop background services (scheduler, monitor)
# ════════════════════════════════════════════════════════════
banner "Step 3.8: Stop Background Services"

SCHEDULER_WAS_RUNNING=false
SCHEDULER_PID_FILE="$PROJECT_ROOT/skills/task-scheduler/scheduler.pid"

if ! $DRY_RUN; then
    if [[ -f "$SCHEDULER_PID_FILE" ]]; then
        scheduler_pid="$(cat "$SCHEDULER_PID_FILE" | tr -d '[:space:]')"
        if [[ "$scheduler_pid" =~ ^[0-9]+$ ]] && kill -0 "$scheduler_pid" 2>/dev/null; then
            step "Stopping task scheduler (PID $scheduler_pid)..."
            kill -15 "$scheduler_pid" 2>/dev/null || kill -9 "$scheduler_pid" 2>/dev/null || true
            sleep 1
            ok "Task scheduler stopped"
            SCHEDULER_WAS_RUNNING=true
            rm -f "$SCHEDULER_PID_FILE"
        else
            step "Task scheduler PID $scheduler_pid is stale -- will restart after upgrade"
            rm -f "$SCHEDULER_PID_FILE"
            SCHEDULER_WAS_RUNNING=true
        fi
    else
        # PID file missing — scan for orphaned scheduler processes
        orphan_pids="$(pgrep -f 'scheduler-service\.ps1' 2>/dev/null || true)"
        if [[ -n "$orphan_pids" ]]; then
            step "Stopping orphaned scheduler (no PID file, PID(s): $(echo "$orphan_pids" | tr '\n' ' '))..."
            echo "$orphan_pids" | xargs -r kill -15 2>/dev/null || true
            sleep 1
            # Force-kill any survivors
            echo "$orphan_pids" | xargs -r kill -9 2>/dev/null || true
            ok "Orphaned scheduler stopped"
            SCHEDULER_WAS_RUNNING=true
        else
            ok "Task scheduler not running"
        fi
    fi
else
    gray "Would stop task scheduler if running"
fi


banner "Step 4: Protect Personalized Files"

BACKUP_DIR="$PROJECT_ROOT/.update-backup"
if ! $DRY_RUN; then
    mkdir -p "$BACKUP_DIR"
fi

BACKED_UP=()
for file in "${PERSONALIZED_FILES[@]}"; do
    full_path="$PROJECT_ROOT/$file"
    if [[ -f "$full_path" ]]; then
        step "Backing up: $file"
        if ! $DRY_RUN; then
            backup_target="$BACKUP_DIR/$file"
            mkdir -p "$(dirname "$backup_target")"
            cp "$full_path" "$backup_target"
        fi
        BACKED_UP+=("$file")
    fi
done

if [[ ${#BACKED_UP[@]} -gt 0 ]]; then
    ok "Backed up ${#BACKED_UP[@]} personalized file(s) to .update-backup/"
else
    ok "No personalized files to protect"
fi

# ════════════════════════════════════════════════════════════
# Step 5: Merge upstream
# ════════════════════════════════════════════════════════════
banner "Step 5: Merge Upstream Changes"

if $DRY_RUN; then
    gray "Would merge upstream/$UPSTREAM_BRANCH into $CURRENT_BRANCH"
    echo ""
    echo -e "  Files that would be updated:"
    git diff --name-only "$CURRENT_BRANCH..upstream/$UPSTREAM_BRANCH" 2>/dev/null | while IFS= read -r l; do gray "$l"; done
else
    step "Merging upstream/$UPSTREAM_BRANCH into $CURRENT_BRANCH..."

    MERGE_OUTPUT="$(git merge "upstream/$UPSTREAM_BRANCH" --no-edit 2>&1)" || MERGE_FAILED=true
    echo "$MERGE_OUTPUT" | while IFS= read -r l; do gray "$l"; done
    MERGE_FAILED="${MERGE_FAILED:-false}"

    if $MERGE_FAILED; then
        # Check if conflicts are only in personalized files
        CONFLICT_FILES="$(git diff --name-only --diff-filter=U 2>/dev/null || true)"
        PERSONAL_CONFLICTS=()
        OTHER_CONFLICTS=()

        if [[ -n "$CONFLICT_FILES" ]]; then
            while IFS= read -r cf; do
                is_personal=false
                for pf in "${PERSONALIZED_FILES[@]}"; do
                    if [[ "$cf" == "$pf" ]]; then
                        is_personal=true
                        break
                    fi
                done
                if $is_personal; then
                    PERSONAL_CONFLICTS+=("$cf")
                else
                    OTHER_CONFLICTS+=("$cf")
                fi
            done <<< "$CONFLICT_FILES"
        fi

        # Auto-resolve personalized file conflicts by keeping ours
        for pf in "${PERSONAL_CONFLICTS[@]}"; do
            step "Resolving conflict in $pf - keeping YOUR version"
            git checkout --ours "$pf" 2>/dev/null
            git add "$pf" 2>/dev/null
        done

        if [[ ${#OTHER_CONFLICTS[@]} -gt 0 ]]; then
            err "Merge conflicts in non-personalized files:"
            for oc in "${OTHER_CONFLICTS[@]}"; do
                echo -e "    ${RED}$oc${NC}"
            done
            echo ""
            echo -e "  Resolve these conflicts manually, then run:"
            gray "git add <resolved-files>"
            gray "git merge --continue"
            echo ""
            echo -e "  Or abort the merge:"
            gray "git merge --abort"

            if $DID_STASH; then
                warn "Your stashed changes will be restored after you resolve conflicts."
                gray "Run: git stash pop"
            fi
            exit 1
        fi

        # All conflicts were in personalized files and auto-resolved
        if [[ ${#PERSONAL_CONFLICTS[@]} -gt 0 ]]; then
            git commit --no-edit 2>/dev/null
            ok "Merge completed (personalized file conflicts auto-resolved)"
        fi
    else
        ok "Merge completed cleanly"
    fi

    # Restore personalized files from backup (in case merge overwrote them)
    for file in "${BACKED_UP[@]}"; do
        backup_path="$BACKUP_DIR/$file"
        restore_path="$PROJECT_ROOT/$file"
        if [[ -f "$backup_path" ]]; then
            # Ensure directory exists (file may have been deleted by merge)
            mkdir -p "$(dirname "$restore_path")"
            cp "$backup_path" "$restore_path"
            ok "Restored your customized: $file"
        fi
    done

    # Auto-protect and restore skills/*/defaults/ directories
    SKILLS_ROOT="$PROJECT_ROOT/skills"
    if [[ -d "$SKILLS_ROOT" ]]; then
        while IFS= read -r -d '' defaults_file; do
            rel="${defaults_file#$PROJECT_ROOT/}"
            backup_path="$BACKUP_DIR/$rel"
            if [[ -f "$backup_path" ]] && [[ ! -f "$defaults_file" ]]; then
                mkdir -p "$(dirname "$defaults_file")"
                cp "$backup_path" "$defaults_file"
                ok "Restored skill default: $rel"
            fi
        done < <(find "$SKILLS_ROOT" -maxdepth 3 -path "*/defaults/*" -type f -print0 2>/dev/null)
    fi
fi

# ════════════════════════════════════════════════════════════
# Step 5.5: Post-merge regression check
# ════════════════════════════════════════════════════════════
banner "Step 5.5: Post-Merge Regression Check"

if ! $DRY_RUN; then
    REGRESSIONS=()

    for file in "${BACKED_UP[@]}"; do
        restore_path="$PROJECT_ROOT/$file"
        backup_path="$BACKUP_DIR/$file"
        if [[ ! -f "$restore_path" ]]; then
            REGRESSIONS+=("$file [DELETED - restore failed]")
        elif [[ -f "$backup_path" ]]; then
            current_hash="$(shasum -a 256 "$restore_path" 2>/dev/null | cut -d' ' -f1)"
            backup_hash="$(shasum -a 256 "$backup_path" 2>/dev/null | cut -d' ' -f1)"
            if [[ "$current_hash" != "$backup_hash" ]]; then
                REGRESSIONS+=("$file [CONTENT CHANGED - backup/restore mismatch]")
            fi
        fi
    done

    # Check preserved files still exist
    for file in "${PERSONALIZED_FILES[@]}"; do
        full_path="$PROJECT_ROOT/$file"
        # Skip if file wasn't backed up (didn't exist pre-merge)
        was_backed=false
        for bf in "${BACKED_UP[@]}"; do
            [[ "$bf" == "$file" ]] && { was_backed=true; break; }
        done
        $was_backed || continue

        if [[ ! -f "$full_path" ]]; then
            already_reported=false
            for r in "${REGRESSIONS[@]}"; do
                [[ "$r" == "$file [DELETED - restore failed]" ]] && { already_reported=true; break; }
            done
            $already_reported || REGRESSIONS+=("$file [MISSING after merge]")
        fi
    done

    if [[ ${#REGRESSIONS[@]} -gt 0 ]]; then
        err "REGRESSION DETECTED - ${#REGRESSIONS[@]} protected file(s) may have been affected:"
        for r in "${REGRESSIONS[@]}"; do
            echo -e "    ${RED}$r${NC}"
        done
        echo ""
        echo -e "  ${YELLOW}Backups are available in .update-backup/ for manual recovery.${NC}"
    else
        ok "All ${#BACKED_UP[@]} protected file(s) verified - no regressions"
    fi
else
    gray "Would run post-merge regression check"
fi

# ════════════════════════════════════════════════════════════
# Step 6: Detect upstream template changes
# ════════════════════════════════════════════════════════════
banner "Step 6: Review Template Changes"

TEMPLATE_FILES=("CLAUDE.md.example" "AGENTS.md.example")
TEMPLATES_CHANGED=()

for tf in "${TEMPLATE_FILES[@]}"; do
    diff_output="$(git diff "HEAD~1..HEAD" -- "$tf" 2>/dev/null || true)"
    if [[ -n "$diff_output" ]]; then
        TEMPLATES_CHANGED+=("$tf")
    fi
done

if [[ ${#TEMPLATES_CHANGED[@]} -gt 0 ]] && ! $DRY_RUN; then
    warn "The following templates were updated upstream:"
    for tc in "${TEMPLATES_CHANGED[@]}"; do
        echo -e "    ${YELLOW}$tc${NC}"
    done
    echo ""
    echo -e "  ${CYAN}----------------------------------------------------------------${NC}"
    echo -e "  ${CYAN}RECOMMENDED: Ask your AI coworker to integrate the changes.${NC}"
    echo -e "  ${CYAN}----------------------------------------------------------------${NC}"
    echo ""
    echo -e "  Your personalized CLAUDE.md and AGENTS.md were preserved, but the"
    echo -e "  upstream .example templates have new content. To safely integrate:"
    echo ""
    echo -e "  ${YELLOW}Start a Copilot session and ask:${NC}"
    echo ""
    echo -e '    "Compare CLAUDE.md.example with my CLAUDE.md and integrate any'
    echo -e '     new sections or changes while keeping my customizations."'
    echo ""
    echo -e '    "Compare AGENTS.md.example with my AGENTS.md and integrate any'
    echo -e '     new skills, rules, or sections while keeping my customizations."'
    echo ""
    gray "The AI agent can read both files, identify what's new in the template,"
    gray "and surgically add new features without overwriting your identity,"
    gray "domain knowledge, or communication preferences."
    echo ""

    # Save a diff summary for the agent to review
    DIFF_REPORT="$PROJECT_ROOT/.update-backup/template-changes.md"
    mkdir -p "$(dirname "$DIFF_REPORT")"
    {
        echo "# Upstream Template Changes"
        echo ""
        echo "Generated by \`scripts/update.sh\` on $(date '+%Y-%m-%d %H:%M')"
        echo ""
        echo "Review these changes and integrate relevant ones into your personalized files."
        echo ""
        for tc in "${TEMPLATES_CHANGED[@]}"; do
            local_file="${tc%.example}"
            echo "## $tc"
            echo ""
            echo "Corresponding personalized file: \`$local_file\`"
            echo ""
            echo '```diff'
            git diff "HEAD~1..HEAD" -- "$tc" 2>/dev/null || true
            echo '```'
            echo ""
        done
    } > "$DIFF_REPORT"
    ok "Diff summary saved to: .update-backup/template-changes.md"
    gray "Share this file with your AI coworker for context."
elif ! $DRY_RUN; then
    ok "No template changes to review"
fi

# ════════════════════════════════════════════════════════════
# Step 7: Restore stashed changes
# ════════════════════════════════════════════════════════════
banner "Step 7: Restore Local Changes"

if $DID_STASH && ! $DRY_RUN; then
    step "Restoring stashed changes..."
    if git stash pop 2>&1 | while IFS= read -r l; do gray "$l"; done; then
        ok "Stashed changes restored"
    else
        warn "Stash pop had conflicts. Resolve manually, then run: git stash drop"
    fi
elif $DID_STASH; then
    gray "Would restore stashed changes"
else
    ok "No stashed changes to restore"
fi

# ════════════════════════════════════════════════════════════
# Cleanup & summary
# ════════════════════════════════════════════════════════════

if ! $DRY_RUN; then
    # Clean up individual backup files (keep template-changes.md if it exists)
    for file in "${BACKED_UP[@]}"; do
        backup_path="$BACKUP_DIR/$file"
        rm -f "$backup_path" 2>/dev/null
    done
    # Remove empty subdirectories in backup
    find "$BACKUP_DIR" -type d -empty -delete 2>/dev/null || true
    # Remove backup dir if empty (but keep if template-changes.md exists)
    if [[ -d "$BACKUP_DIR" ]] && [[ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]]; then
        rmdir "$BACKUP_DIR" 2>/dev/null || true
    fi

    # Stamp agencycowork.json with current version
    VERSION_FILE="$PROJECT_ROOT/agencycowork.json"
    STAMP_VERSION="unknown"
    # Try to read version from ui/package.json (matches desktop app versioning)
    UI_PKG="$PROJECT_ROOT/ui/package.json"
    if [[ -f "$UI_PKG" ]]; then
        STAMP_VERSION="$(python3 -c "import json; print(json.load(open('$UI_PKG'))['version'])" 2>/dev/null || \
                         node -e "console.log(require('$UI_PKG').version)" 2>/dev/null || \
                         echo "unknown")"
    fi

    # Read existing agencycowork.json for merge (preserve createdAt, orgRepoUrl)
    EXISTING_CREATED=""
    EXISTING_ORG=""
    if [[ -f "$VERSION_FILE" ]]; then
        EXISTING_CREATED="$(python3 -c "import json; d=json.load(open('$VERSION_FILE')); print(d.get('createdAt',''))" 2>/dev/null || true)"
        EXISTING_ORG="$(python3 -c "import json; d=json.load(open('$VERSION_FILE')); print(d.get('orgRepoUrl',''))" 2>/dev/null || true)"
    fi

    NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    CREATED="${EXISTING_CREATED:-$NOW}"

    # Write using python for reliable JSON (or fallback to cat)
    if command -v python3 &>/dev/null; then
        python3 -c "
import json, sys
stamp = {
    'version': '$STAMP_VERSION',
    'createdAt': '$CREATED',
    'updatedAt': '$NOW',
    'installedVia': 'update.sh',
}
org = '$EXISTING_ORG'
if org:
    stamp['orgRepoUrl'] = org
with open('$VERSION_FILE', 'w') as f:
    json.dump(stamp, f, indent=2)
    f.write('\n')
" 2>/dev/null
    else
        cat > "$VERSION_FILE" <<STAMP
{
  "version": "$STAMP_VERSION",
  "createdAt": "$CREATED",
  "updatedAt": "$NOW",
  "installedVia": "update.sh"
}
STAMP
    fi
    ok "Stamped agencycowork.json (v$STAMP_VERSION)"
fi

# Restart task scheduler if it was running before upgrade
if $SCHEDULER_WAS_RUNNING && ! $DRY_RUN; then
    SETUP_SCHEDULER="$PROJECT_ROOT/scripts/setup-scheduler.ps1"
    if command -v pwsh &>/dev/null && [[ -f "$SETUP_SCHEDULER" ]]; then
        step "Restarting task scheduler..."
        pwsh -ExecutionPolicy Bypass -File "$SETUP_SCHEDULER" &>/dev/null &
        sleep 3
        if [[ -f "$SCHEDULER_PID_FILE" ]]; then
            restart_pid="$(cat "$SCHEDULER_PID_FILE" | tr -d '[:space:]')"
            ok "Task scheduler restarted (PID $restart_pid)"
        else
            warn "Scheduler restart initiated but PID file not yet written (may still be starting)"
        fi
    else
        warn "Cannot restart scheduler: pwsh not found or setup-scheduler.ps1 missing"
        gray "    Run manually: pwsh -ExecutionPolicy Bypass -File scripts/setup-scheduler.ps1"
    fi
fi

# Warn about tasks stuck in error_paused state
TASKS_DIR="$PROJECT_ROOT/skills/task-scheduler/tasks"
if [[ -d "$TASKS_DIR" ]] && command -v python3 &>/dev/null; then
    ERROR_TASKS=$(python3 -c "
import json, glob, os
tasks_dir = '$TASKS_DIR'
errors = []
for f in glob.glob(os.path.join(tasks_dir, '*.json')):
    try:
        t = json.load(open(f))
        if t.get('status') == 'error_paused':
            errors.append(f\"{t.get('name','?')} (error_count: {t.get('error_count',0)}) -- {os.path.basename(f)}\")
    except: pass
for e in errors:
    print(e)
" 2>/dev/null)
    if [[ -n "$ERROR_TASKS" ]]; then
        warn "Scheduled task(s) in error_paused state:"
        while IFS= read -r line; do
            echo -e "    ${YELLOW}- $line${NC}"
        done <<< "$ERROR_TASKS"
    fi
fi

banner "Update Complete"

PRESERVE_SOURCE="default list"
$USING_MANIFEST && PRESERVE_SOURCE=".update-preserve manifest"
echo -e "  ${GREEN}Protected files (${#PERSONALIZED_FILES[@]} via $PRESERVE_SOURCE):${NC}"
for file in "${PERSONALIZED_FILES[@]}"; do
    full_path="$PROJECT_ROOT/$file"
    if [[ -f "$full_path" ]]; then
        echo -e "    ${DARKGREEN}+ $file${NC}"
    else
        echo -e "    ${YELLOW}- $file [not found]${NC}"
    fi
done
echo ""

if ! $USING_MANIFEST; then
    warn "TIP: Create .update-preserve in your project root to protect org-specific files."
    gray "See the template in the upstream repo or run: agency copilot"
    gray 'and ask "Help me set up .update-preserve for my org-specific files"'
    echo ""
fi

if [[ ${#TEMPLATES_CHANGED[@]} -gt 0 ]]; then
    echo -e "  ${YELLOW}ACTION NEEDED: Review upstream template changes.${NC}"
    echo -e "  ${YELLOW}See: .update-backup/template-changes.md${NC}"
    echo ""
    echo -e "  Ask your AI coworker:"
    echo -e '    "Read .update-backup/template-changes.md and integrate the'
    echo -e '     upstream changes into my CLAUDE.md and AGENTS.md while'
    echo -e '     preserving my customizations."'
    echo ""
fi

echo -e "  ${GRAY}Next steps:${NC}"
echo -e "    1. Start a new Copilot session to pick up any new features"
echo -e "    2. Run /skills to verify all skills are loaded"
if [[ ${#TEMPLATES_CHANGED[@]} -gt 0 ]]; then
    echo -e "    3. Ask the agent to integrate template changes (see above)"
fi
echo ""
