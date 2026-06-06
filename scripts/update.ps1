<#
.SYNOPSIS
    Pull the latest Agency Cowork updates from upstream while preserving local customizations.

.DESCRIPTION
    This script safely updates your forked Agency Cowork repo from the upstream
    template (ahsi-microsoft/agency-cowork) while protecting your personalized files.

    Strategy:
      1. Stash any uncommitted local changes
      2. Fetch the latest from upstream
      3. Merge upstream/main into your current branch
      4. If conflicts arise in personalized files (CLAUDE.md, AGENTS.md, agentconfig.json),
         the script keeps YOUR version and flags the upstream changes for AI-assisted review
      5. Restore stashed changes

    The script recommends using your AI coworker to review and integrate upstream changes
    into your customized files - the agent can read the .example templates, compare with
    your local versions, and surgically apply new features without losing your personalization.

.PARAMETER UpstreamUrl
    The upstream repo URL. Default: https://github.com/ahsi-microsoft/agency-cowork.git

.PARAMETER UpstreamBranch
    The upstream branch to pull from. Default: main

.PARAMETER DryRun
    Show what would happen without making changes.

.PARAMETER Force
    Skip confirmation prompts.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/update.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/update.ps1 -DryRun

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/update.ps1 -UpstreamBranch develop
#>

param(
    [string]$UpstreamUrl = "https://github.com/ahsi-microsoft/agency-cowork.git",
    [string]$UpstreamBranch = "main",
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Continue"

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# ============================================================
# Helpers
# ============================================================

function Write-Banner {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host "  >> $Text" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [!!] $Text" -ForegroundColor DarkYellow
}

function Write-Err {
    param([string]$Text)
    Write-Host "  [FAIL] $Text" -ForegroundColor Red
}

function Detect-OneDrivePath {
    <#
    .SYNOPSIS
        Detect the OneDrive sync folder using documented priority order.
    .DESCRIPTION
        Windows: %OneDriveCommercial% -> %OneDrive% -> ~/OneDrive - Microsoft -> ~/OneDrive
        Returns $null if no valid OneDrive path is found.
    #>
    $candidates = @(
        $env:OneDriveCommercial,
        $env:OneDrive,
        (Join-Path $HOME "OneDrive - Microsoft"),
        (Join-Path $HOME "OneDrive")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    return $null
}

function Test-InsideOneDrive {
    <#
    .SYNOPSIS
        Check if a directory is already inside a OneDrive sync folder.
    #>
    param([string]$DirPath, [string]$OneDrivePath)
    if (-not $OneDrivePath) { return $false }
    $normalDir = $DirPath.TrimEnd('\', '/').ToLower()
    $normalOD  = $OneDrivePath.TrimEnd('\', '/').ToLower()
    return $normalDir.StartsWith($normalOD + '\') -or ($normalDir -eq $normalOD)
}

function Invoke-OneDriveMigration {
    <#
    .SYNOPSIS
        Migrate memory/ from local directory to OneDrive cloud-synced junction.
    .DESCRIPTION
        1. Creates <OneDrive>/Agency Cowork/<FolderName>/memory/
        2. Smart-merges existing memory contents (newer file wins by mtime)
        3. Replaces local memory/ with an NTFS junction to the OneDrive target
        4. Updates agentconfig.json -- sets "onedrive+git" if .git exists, else "onedrive"
    #>
    param(
        [string]$ProjectRoot,
        [string]$OneDrivePath,
        [string]$FolderName
    )

    $agencyCoworkDir = Join-Path $OneDrivePath "Agency Cowork"
    $targetBase = Join-Path $agencyCoworkDir $FolderName

    $targetMemory = Join-Path $targetBase "memory"
    $localMemory  = Join-Path $ProjectRoot "memory"

    # Pre-flight checks (postmortem 2026-03-17: fail fast before any destructive ops)
    if (-not (Test-Path $localMemory)) {
        Write-Warn "No memory/ directory found -- nothing to migrate"
        return $false
    }
    # Check if memory/ is already a junction/reparse point (already migrated or broken)
    $memItem = Get-Item $localMemory -Force -ErrorAction SilentlyContinue
    if ($memItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $jTarget = $memItem.Target
        if ($jTarget -and (Test-Path $jTarget)) {
            Write-Ok "memory/ is already a junction -> $jTarget (already migrated)"
            return $true
        } else {
            Write-Err "memory/ is a broken junction -> $jTarget"
            Write-Warn "Remove the stale junction manually: Remove-Item '$localMemory' -Force"
            return $false
        }
    }
    $localFileCount = (Get-ChildItem $localMemory -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($localFileCount -eq 0) {
        Write-Warn "memory/ is empty -- nothing to migrate"
        return $false
    }

    # If target folder already exists, merge into it instead of creating a new one.
    # Postmortem 2026-04-10: dedup logic was creating a new folder (e.g. maia-agent-2),
    # orphaning existing OneDrive files. The smart-merge (newer-wins) handles conflicts
    # correctly, so merging into the existing folder is safe and preserves cloud files.
    $existingDestFileCount = 0
    if (Test-Path $targetMemory) {
        $existingDestFileCount = (Get-ChildItem $targetMemory -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($existingDestFileCount -gt 0) {
            Write-Host "  Found existing OneDrive folder with $existingDestFileCount file(s): $targetMemory" -ForegroundColor Yellow
            Write-Host "  Will merge local files into existing folder (newer file wins)." -ForegroundColor Yellow
            Write-Host "  Existing OneDrive files that are not in local will be preserved." -ForegroundColor Yellow
        }
    }

    # Verify OneDrive target parent is writable
    $testFile = Join-Path $targetBase ".write-test-$(Get-Random)"
    try {
        New-Item -ItemType Directory -Path $targetBase -Force | Out-Null
        Set-Content $testFile "test" -ErrorAction Stop
        Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Err "OneDrive target is not writable: $targetBase"
        Write-Warn "Check OneDrive sync status and disk space."
        return $false
    }
    Write-Ok "Pre-flight checks passed ($localFileCount local files to merge)"

    # Create the OneDrive target directory (no-op if it already exists)
    New-Item -ItemType Directory -Path $targetMemory -Force | Out-Null
    if ($existingDestFileCount -eq 0) {
        Write-Ok "Created OneDrive target: $targetMemory"
    }

    # Back up existing OneDrive files before merge (if any exist).
    # Postmortem 2026-04-10: previous version had no backup of OneDrive-side files,
    # so overwritten or orphaned cloud files were unrecoverable.
    $cloudBackupDir = $null
    if ($existingDestFileCount -gt 0) {
        $cloudBackupDir = Join-Path $ProjectRoot ".onedrive-pre-merge-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        try {
            New-Item -ItemType Directory -Path $cloudBackupDir -Force | Out-Null
            Copy-Item -LiteralPath $targetMemory -Destination (Join-Path $cloudBackupDir "memory") -Recurse -Force
            Write-Ok "Backed up $existingDestFileCount existing OneDrive file(s) to $cloudBackupDir"
        } catch {
            Write-Warn "Could not back up existing OneDrive files: $_. Proceeding with merge anyway."
        }
    }

    # Smart-merge: copy files from local memory/ to OneDrive target
    # Source newer -> overwrite (back up dest first); dest newer -> keep; same mtime -> skip
    $backupDir = Join-Path $ProjectRoot "memory-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $backedUpCount = 0
    $copiedCount = 0
    $skippedCount = 0

    if (Test-Path $localMemory) {
        $localFiles = Get-ChildItem $localMemory -Recurse -File -ErrorAction SilentlyContinue
        foreach ($file in $localFiles) {
            $relativePath = $file.FullName.Substring($localMemory.Length + 1)
            $destFile = Join-Path $targetMemory $relativePath

            $destDir = Split-Path $destFile -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }

            if (Test-Path $destFile) {
                $destInfo = Get-Item $destFile
                if ($file.LastWriteTimeUtc -gt $destInfo.LastWriteTimeUtc) {
                    # Source is newer -- back up dest (only if no full pre-merge backup), copy source
                    if (-not $cloudBackupDir) {
                        $backupFile = Join-Path $backupDir $relativePath
                        $backupFileDir = Split-Path $backupFile -Parent
                        if (-not (Test-Path $backupFileDir)) {
                            New-Item -ItemType Directory -Path $backupFileDir -Force | Out-Null
                        }
                        Copy-Item -LiteralPath $destFile -Destination $backupFile -Force
                        $backedUpCount++
                    }
                    Copy-Item -LiteralPath $file.FullName -Destination $destFile -Force
                    $copiedCount++
                } else {
                    $skippedCount++
                }
                # Dest newer or same mtime -- skip (OneDrive version preserved)
            } else {
                Copy-Item -LiteralPath $file.FullName -Destination $destFile -Force
                $copiedCount++
            }
        }
    }

    if ($copiedCount -gt 0) {
        Write-Ok "Merged $copiedCount file(s) to OneDrive"
    }
    if ($skippedCount -gt 0) {
        Write-Ok "Kept $skippedCount existing OneDrive file(s) (newer or same)"
    }
    if ($backedUpCount -gt 0) {
        Write-Warn "Overwrote $backedUpCount file(s) (local was newer). Originals backed up to $backupDir"
    } elseif ($cloudBackupDir -and $copiedCount -gt 0) {
        Write-Ok "Overwritten OneDrive files recoverable from pre-merge backup: $cloudBackupDir"
    }

    # Validate file counts before proceeding with destructive operations.
    # Postmortem 2026-03-17: silent failure during copy left OneDrive empty while
    # source was deleted. Always verify dest has at least as many files as source.
    # With merge-into-existing, dest should have at least: pre-existing files + newly copied files.
    $destCount = (Get-ChildItem $targetMemory -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    $expectedMin = $existingDestFileCount + $copiedCount
    if ($expectedMin -gt 0 -and $destCount -lt $expectedMin) {
        Write-Err "File count mismatch: expected at least $expectedMin (existing=$existingDestFileCount + copied=$copiedCount), found $destCount. Aborting migration."
        Write-Warn "Source files preserved in: $localMemory"
        Write-Warn "Partial copy in: $targetMemory"
        return $false
    }

    # Create a full pre-flight backup before any destructive operations.
    # This is the safety net -- if anything below fails, we restore from here.
    $migrationBackup = Join-Path $ProjectRoot ".onedrive-migration-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    try {
        New-Item -ItemType Directory -Path $migrationBackup -Force | Out-Null
        Copy-Item -LiteralPath $localMemory -Destination (Join-Path $migrationBackup "memory") -Recurse -Force
        Write-Ok "Pre-flight backup: $migrationBackup"
    } catch {
        Write-Err "Failed to create pre-flight backup: $_. Aborting migration."
        return $false
    }

    # Remove local memory/ and create NTFS junction
    $junctionCreated = $false
    try {
        Remove-Item -LiteralPath $localMemory -Recurse -Force -ErrorAction Stop
        New-Item -ItemType Junction -Path $localMemory -Target $targetMemory | Out-Null
        $junctionCreated = $true
        Write-Ok "Created junction: memory/ -> $targetMemory"
    } catch {
        Write-Err "Failed to create junction: $_"
        # Restore from backup since source was deleted
        if (-not (Test-Path $localMemory)) {
            Write-Warn "Restoring memory/ from backup..."
            try {
                Copy-Item -LiteralPath (Join-Path $migrationBackup "memory") -Destination $localMemory -Recurse -Force
                Write-Ok "Restored memory/ from backup"
            } catch {
                Write-Err "Restore failed: $_. Manual recovery from: $migrationBackup"
            }
        }
        return $false
    }

    # Verify the junction works by listing files through it
    $junctionFileCount = (Get-ChildItem $localMemory -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($junctionFileCount -eq 0 -and $sourceCount -gt 0) {
        Write-Err "Junction verification failed: 0 files visible through junction (expected $sourceCount)"
        Write-Warn "Restoring memory/ from backup..."
        try {
            Remove-Item -LiteralPath $localMemory -Force -ErrorAction SilentlyContinue  # remove broken junction
            Copy-Item -LiteralPath (Join-Path $migrationBackup "memory") -Destination $localMemory -Recurse -Force
            Write-Ok "Restored memory/ from backup"
        } catch {
            Write-Err "Restore failed: $_. Manual recovery from: $migrationBackup"
        }
        return $false
    }

    # R10: Fix git submodule pointer -- NTFS junctions resolve to real OneDrive path,
    # so relative gitdir (../.git/modules/memory) breaks. Rewrite to absolute path.
    $gitFile = Join-Path $targetMemory ".git"
    if (Test-Path $gitFile) {
        $gitContent = Get-Content $gitFile -Raw
        if ($gitContent -match "^gitdir:\s*(\.\..*)") {
            try {
                $relPath = $Matches[1].Trim()
                $absPath = (Resolve-Path (Join-Path $localMemory $relPath) -ErrorAction Stop).Path -replace '\\', '/'
                Set-Content $gitFile "gitdir: $absPath" -NoNewline -Encoding UTF8
                Write-Ok "Rewrote .git pointer to absolute path (junction-safe)"
            } catch {
                Write-Warn "Could not resolve git pointer -- manual fix may be needed: $_"
            }
        }
    }

    # R11: Also migrate outputs/ directory (user-generated content, benefits from cloud sync)
    # Same backup-validate-delete-junction-verify pattern as memory/ above.
    $localOutputs = Join-Path $ProjectRoot "outputs"
    $outputsMigrated = $false
    if ((Test-Path $localOutputs) -and -not (Get-Item $localOutputs).Attributes.ToString().Contains("ReparsePoint")) {
        $targetOutputs = Join-Path $targetBase "outputs"
        try {
            New-Item -ItemType Directory -Path $targetOutputs -Force | Out-Null
            $outputFiles = Get-ChildItem $localOutputs -Recurse -File -ErrorAction SilentlyContinue
            foreach ($file in $outputFiles) {
                $relativePath = $file.FullName.Substring($localOutputs.Length + 1)
                $destFile = Join-Path $targetOutputs $relativePath
                $destDir = Split-Path $destFile -Parent
                if (-not (Test-Path $destDir)) {
                    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
                }
                Copy-Item -LiteralPath $file.FullName -Destination $destFile -Force
            }

            # Validate file counts before deletion
            $outSourceCount = ($outputFiles | Measure-Object).Count
            $outDestCount = (Get-ChildItem $targetOutputs -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
            if ($outSourceCount -gt 0 -and $outDestCount -lt $outSourceCount) {
                Write-Warn "outputs/ file count mismatch: source=$outSourceCount, dest=$outDestCount. Skipping."
            } else {
                # Back up outputs/ before deletion
                Copy-Item -LiteralPath $localOutputs -Destination (Join-Path $migrationBackup "outputs") -Recurse -Force
                Remove-Item -LiteralPath $localOutputs -Recurse -Force -ErrorAction Stop
                New-Item -ItemType Junction -Path $localOutputs -Target $targetOutputs | Out-Null

                # Verify junction
                $outJunctionCount = (Get-ChildItem $localOutputs -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
                if ($outJunctionCount -eq 0 -and $outSourceCount -gt 0) {
                    Write-Warn "outputs/ junction verification failed. Restoring from backup..."
                    try {
                        Remove-Item -LiteralPath $localOutputs -Force -ErrorAction SilentlyContinue
                        Copy-Item -LiteralPath (Join-Path $migrationBackup "outputs") -Destination $localOutputs -Recurse -Force -ErrorAction Stop
                        Write-Warn "Restored outputs/ from backup"
                    } catch {
                        Write-Err "outputs/ restore FAILED: $_. Manual recovery from: $migrationBackup"
                    }
                } else {
                    Write-Ok "Migrated outputs/ -> $targetOutputs ($outSourceCount files)"
                    $outputsMigrated = $true
                }
            }
        } catch {
            Write-Warn "Could not migrate outputs/: $_"
            # Restore from backup if source was deleted
            if (-not (Test-Path $localOutputs) -and (Test-Path (Join-Path $migrationBackup "outputs"))) {
                try {
                    Copy-Item -LiteralPath (Join-Path $migrationBackup "outputs") -Destination $localOutputs -Recurse -Force -ErrorAction Stop
                    Write-Warn "Restored outputs/ from backup"
                } catch {
                    Write-Err "outputs/ restore FAILED: $_. Manual recovery from: $migrationBackup"
                }
            }
        }
    }

    # Clean up migration backup only after ALL migrations succeeded:
    #   - memory/ junction was created and verified, AND
    #   - outputs/ either: (a) doesn't exist, (b) migrated OK, or (c) wasn't backed up (migration never attempted)
    $allMigrationsOk = $junctionCreated -and (-not (Test-Path $localOutputs) -or $outputsMigrated -or -not (Test-Path (Join-Path $migrationBackup "outputs")))
    if ($allMigrationsOk -and (Test-Path $migrationBackup)) {
        try {
            Remove-Item -LiteralPath $migrationBackup -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok "Cleaned up migration backup"
        } catch {
            Write-Warn "Could not remove backup at $migrationBackup -- safe to delete manually"
        }
    } elseif (Test-Path $migrationBackup) {
        Write-Warn "Keeping migration backup (not all migrations verified): $migrationBackup"
    }

    # Update agentconfig.json
    $configPath = Join-Path $ProjectRoot "agentconfig.json"
    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        # Preserve git -- if .git exists in the migrated memory, mark as dual-sync
        $hasGit = Test-Path (Join-Path $targetMemory ".git")
        if ($hasGit) {
            $config.memory.location = "onedrive+git"
            Write-Ok "Git repo preserved -- memory uses both OneDrive + Git sync"
        } else {
            $config.memory.location = "onedrive"
        }
        $config.memory.onedrivePath = $targetMemory
        $config | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8
        Write-Ok "Updated agentconfig.json (memory.location = $($config.memory.location))"
    } catch {
        Write-Err "Failed to update agentconfig.json: $_"
        Write-Warn "Manually set memory.location to 'onedrive' and onedrivePath to '$targetMemory'"
        return $false
    }

    # Clean up empty backup directory
    if ((Test-Path $backupDir) -and -not (Get-ChildItem $backupDir -Recurse -File)) {
        Remove-Item $backupDir -Recurse -ErrorAction SilentlyContinue
    }

    # R12: Re-index QMD collections -- junction targets resolve to real OneDrive paths,
    # so stale collections pointing to old local paths will return zero results.
    $qmdCmd = Get-Command qmd -ErrorAction SilentlyContinue
    if ($qmdCmd) {
        Write-Step "Re-indexing QMD collections for new paths..."
        try {
            $collections = @("memory-root", "knowledgebase", "weekly-reports", "skills-docs")
            foreach ($col in $collections) {
                qmd collection remove $col 2>&1 | Out-Null
            }
            # Re-add collections pointing through the junction (resolves to OneDrive)
            qmd collection add memory-root (Join-Path $localMemory "") --mask "*.md" 2>&1 | Out-Null
            qmd collection add knowledgebase (Join-Path $localMemory "Knowledgebase") --mask "**/*.md" 2>&1 | Out-Null
            qmd collection add weekly-reports (Join-Path $ProjectRoot "memory/WeeklyReports") --mask "**/*.md" 2>&1 | Out-Null
            qmd collection add skills-docs (Join-Path $ProjectRoot "skills") --mask "**/SKILL.md" 2>&1 | Out-Null
            qmd update 2>&1 | Out-Null
            Write-Ok "QMD collections re-indexed through junction"

            # Re-embed using Python pipeline (respects agentconfig.json provider)
            $embedScript = Join-Path $ProjectRoot "skills" "qmd-memory" "scripts" "azure-embed.py"
            if (Test-Path $embedScript) {
                python $embedScript 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "QMD embeddings regenerated"
                }
            }
        } catch {
            Write-Warn "QMD re-index failed: $_ -- run 'qmd status' to check manually"
        }
    }

    return $true
}

# Files that contain user customizations and should never be overwritten by upstream.
# Read from .update-preserve manifest if it exists; fall back to hardcoded defaults.
$DefaultPersonalizedFiles = @(
    "CLAUDE.md",
    "AGENTS.md",
    "agentconfig.json",
    ".env",
    "skills/teams/monitor/monitor-config.json",
    ".context-merge.json",
    "CLAUDE.md.example",
    "AGENTS.md.example"
)

function Resolve-PreserveManifest {
    <#
    .SYNOPSIS
        Reads .update-preserve and resolves glob patterns to actual file paths.
    #>
    param([string]$Root)

    $manifestPath = Join-Path $Root ".update-preserve"
    if (-not (Test-Path $manifestPath)) {
        return $null
    }

    $patterns = Get-Content $manifestPath |
        Where-Object { $_ -and $_ -notmatch '^\s*#' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -ne '' }

    $resolved = @()

    foreach ($pattern in $patterns) {
        # Directory patterns (ending with /)
        if ($pattern.EndsWith('/')) {
            $dirPath = Join-Path $Root ($pattern.TrimEnd('/'))
            if (Test-Path $dirPath) {
                $children = Get-ChildItem -Path $dirPath -Recurse -File -ErrorAction SilentlyContinue
                foreach ($child in $children) {
                    $rel = $child.FullName.Substring($Root.Length).TrimStart('\', '/')
                    $resolved += $rel
                }
            }
            continue
        }

        # If pattern contains wildcards, resolve via Get-ChildItem
        if ($pattern -match '[\*\?\[\]]') {
            # Split into directory and filename parts for proper glob resolution
            $patternDir = Split-Path $pattern -Parent
            $patternLeaf = Split-Path $pattern -Leaf
            $searchRoot = if ($patternDir) { Join-Path $Root $patternDir } else { $Root }

            if (Test-Path $searchRoot) {
                $matches = Get-ChildItem -Path $searchRoot -Filter $patternLeaf -File -ErrorAction SilentlyContinue
                foreach ($m in $matches) {
                    $rel = $m.FullName.Substring($Root.Length).TrimStart('\', '/')
                    $resolved += $rel
                }
            }
        } else {
            # Literal file path
            $fullPath = Join-Path $Root $pattern
            if (Test-Path $fullPath -PathType Leaf) {
                $resolved += $pattern
            } elseif (Test-Path $fullPath -PathType Container) {
                # Treat bare directory name as recursive protect
                $children = Get-ChildItem -Path $fullPath -Recurse -File -ErrorAction SilentlyContinue
                foreach ($child in $children) {
                    $rel = $child.FullName.Substring($Root.Length).TrimStart('\', '/')
                    $resolved += $rel
                }
            }
        }
    }

    return ($resolved | Sort-Object -Unique)
}

# Resolve personalized files from manifest or fall back to defaults
$manifestFiles = Resolve-PreserveManifest -Root $ProjectRoot
if ($manifestFiles) {
    $PersonalizedFiles = $manifestFiles
    $usingManifest = $true
} else {
    $PersonalizedFiles = $DefaultPersonalizedFiles
    $usingManifest = $false
}

# Auto-protect skill defaults/ directories (user customization layer).
# These contain voice profiles, triage rules, and other per-user configs
# that must survive upstream merges regardless of manifest presence.
$skillsRoot = Join-Path $ProjectRoot "skills"
if (Test-Path $skillsRoot) {
    $defaultsDirs = Get-ChildItem -Path $skillsRoot -Filter "defaults" -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue
    foreach ($dd in $defaultsDirs) {
        $ddFiles = Get-ChildItem -Path $dd.FullName -File -ErrorAction SilentlyContinue
        foreach ($f in $ddFiles) {
            $rel = $f.FullName.Substring($ProjectRoot.Length + 1) -replace '\\', '/'
            if ($PersonalizedFiles -notcontains $rel) {
                $PersonalizedFiles += $rel
            }
        }
    }
}

# Auto-protect task-scheduler task definitions (user-created, never shipped by upstream).
# Without this, upgrades silently delete all scheduled tasks. Fixes #218.
$tasksDir = Join-Path $skillsRoot "task-scheduler" "tasks"
if (Test-Path $tasksDir) {
    $taskFiles = Get-ChildItem -Path $tasksDir -Filter "*.json" -File -ErrorAction SilentlyContinue
    foreach ($f in $taskFiles) {
        $rel = $f.FullName.Substring($ProjectRoot.Length + 1) -replace '\\', '/'
        if ($PersonalizedFiles -notcontains $rel) {
            $PersonalizedFiles += $rel
        }
    }
}

# ============================================================
# Pre-flight checks
# ============================================================

Write-Banner "Agency Cowork - Update from Upstream"

if ($DryRun) {
    Write-Warn "DRY RUN - no changes will be made"
    Write-Host ""
}

# Verify we're in a git repo
if (-not (Test-Path ".git")) {
    Write-Err "Not a git repository. Run this script from your Agency Cowork project root."
    exit 1
}

# Check current branch
$currentBranch = git rev-parse --abbrev-ref HEAD 2>$null
Write-Ok "Current branch: $currentBranch"

# Report preserve source
if ($usingManifest) {
    Write-Ok "Preserve manifest: .update-preserve ($($PersonalizedFiles.Count) file(s) resolved)"
} else {
    Write-Warn "No .update-preserve found - using default protect list (3 files)"
    Write-Host "    Create .update-preserve to protect org-specific files. See README." -ForegroundColor Gray
}

# ============================================================
# Step 0: Self-Update & Pre-Upgrade Cleanup
# ============================================================

Write-Banner "Step 0: Pre-Upgrade Checks"

# R5: Self-update -- if upstream has a newer update.ps1, re-exec with it.
# This solves the chicken-and-egg bug where new features (like OneDrive migration)
# only exist in the NEW script, but the OLD script is what runs during the upgrade.
if (-not $DryRun -and -not $env:AGENCY_UPDATE_SELF_UPDATED) {
    try {
        # Ensure upstream remote exists and is fetched
        $hasUpstream = git remote get-url upstream 2>$null
        if (-not $hasUpstream) {
            git remote add upstream $UpstreamUrl 2>$null
        }
        git fetch upstream --quiet 2>$null

        $upstreamScript = git show "upstream/$($UpstreamBranch):scripts/update.ps1" 2>$null
        if ($upstreamScript) {
            $tempScript = Join-Path $env:TEMP "agency-cowork-update-$(Get-Random).ps1"
            $upstreamScript | Set-Content $tempScript -Encoding UTF8
            $selfHash = (Get-FileHash $MyInvocation.MyCommand.Path -Algorithm SHA256).Hash
            $newHash  = (Get-FileHash $tempScript -Algorithm SHA256).Hash
            if ($selfHash -ne $newHash) {
                Write-Step "Newer update.ps1 found upstream -- re-executing..."
                $env:AGENCY_UPDATE_SELF_UPDATED = "1"
                $reExecArgs = @("-ExecutionPolicy", "Bypass", "-File", $tempScript)
                if ($UpstreamUrl -ne "https://github.com/ahsi-microsoft/agency-cowork.git") {
                    $reExecArgs += @("-UpstreamUrl", $UpstreamUrl)
                }
                if ($UpstreamBranch -ne "main") { $reExecArgs += @("-UpstreamBranch", $UpstreamBranch) }
                if ($Force) { $reExecArgs += "-Force" }
                if ($DryRun) { $reExecArgs += "-DryRun" }
                # Use the same PS host that's running us (pwsh or powershell.exe)
                $psExe = (Get-Process -Id $PID).MainModule.FileName
                & $psExe @reExecArgs
                $exitCode = $LASTEXITCODE
                Remove-Item $tempScript -ErrorAction SilentlyContinue
                $env:AGENCY_UPDATE_SELF_UPDATED = $null
                exit $exitCode
            }
            Remove-Item $tempScript -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warn "Self-update check failed (non-fatal): $_"
    }
}

# R6: Kill stale task runners and zombie processes before merge
if (-not $DryRun) {
    $killedCount = 0
    # Kill stale pwsh/powershell task runners (run-task.ps1, scheduler-service.ps1)
    try {
        Get-CimInstance Win32_Process -Filter "Name='pwsh.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.CommandLine -and ($_.CommandLine -like "*run-task.ps1*" -or $_.CommandLine -like "*scheduler-service.ps1*")) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $killedCount++
            }
        }
    } catch { <# CimInstance may fail on some systems #> }

    if ($killedCount -gt 0) {
        Write-Ok "Cleaned up $killedCount stale task runner(s)"
    }
}

# ============================================================
# Step 1: Stash local changes
# ============================================================

Write-Banner "Step 1: Stash Local Changes"

$hasChanges = (git status --porcelain 2>$null) -ne $null
if ($hasChanges) {
    $stashName = "agency-cowork-update-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Step "Uncommitted changes detected. Stashing as: $stashName"
    if (-not $DryRun) {
        git stash push -m $stashName --include-untracked 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to stash changes. Aborting."
            exit 1
        }
        Write-Ok "Changes stashed"
    } else {
        Write-Host "    Would stash uncommitted changes" -ForegroundColor Gray
    }
    $didStash = $true
} else {
    Write-Ok "Working tree is clean"
    $didStash = $false
}

# ============================================================
# Step 2: Configure upstream remote
# ============================================================

Write-Banner "Step 2: Configure Upstream Remote"

$existingUpstream = git remote get-url upstream 2>$null
if ($existingUpstream) {
    if ($existingUpstream -ne $UpstreamUrl) {
        Write-Warn "Upstream remote exists but points to: $existingUpstream"
        Write-Step "Updating to: $UpstreamUrl"
        if (-not $DryRun) {
            git remote set-url upstream $UpstreamUrl 2>&1 | Out-Null
        }
    }
    Write-Ok "Upstream remote: $UpstreamUrl"
} else {
    Write-Step "Adding upstream remote: $UpstreamUrl"
    if (-not $DryRun) {
        git remote add upstream $UpstreamUrl 2>&1 | Out-Null
    }
    Write-Ok "Upstream remote added"
}

# ============================================================
# Step 3: Fetch upstream
# ============================================================

Write-Banner "Step 3: Fetch Upstream Changes"

Write-Step "Fetching upstream/$UpstreamBranch..."
if (-not $DryRun) {
    git fetch upstream $UpstreamBranch 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to fetch from upstream. Check your network and repo access."
        if ($didStash) {
            Write-Step "Restoring stashed changes..."
            git stash pop 2>&1 | Out-Null
        }
        exit 1
    }
    Write-Ok "Fetched upstream/$UpstreamBranch"
} else {
    Write-Host "    Would fetch upstream/$UpstreamBranch" -ForegroundColor Gray
}

# Show what's new
Write-Step "Changes since last update:"
$logOutput = git log --oneline "$currentBranch..upstream/$UpstreamBranch" 2>$null
if ($logOutput) {
    $logOutput | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    $totalCommits = ($logOutput | Measure-Object).Count
    if ($totalCommits -gt 20) {
        Write-Host "    ... and $($totalCommits - 20) more commits" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  $totalCommits new commit(s) from upstream" -ForegroundColor White
} else {
    Write-Ok "Already up to date with upstream/$UpstreamBranch"
    if ($didStash) {
        Write-Step "Restoring stashed changes..."
        if (-not $DryRun) { git stash pop 2>&1 | Out-Null }
    }
    exit 0
}

# Confirm before merging
if (-not $Force -and -not $DryRun) {
    Write-Host ""
    Write-Host "  This will merge $totalCommits commit(s) into your $currentBranch branch." -ForegroundColor White
    Write-Host "  $($PersonalizedFiles.Count) personalized file(s) will be protected via $(if ($usingManifest) { '.update-preserve manifest' } else { 'default list' })." -ForegroundColor White
    Write-Host ""
    $confirm = Read-Host "  Continue? [Y/n]"
    if ($confirm -and $confirm.Trim().ToLower() -eq 'n') {
        Write-Warn "Update cancelled by user"
        if ($didStash) {
            Write-Step "Restoring stashed changes..."
            git stash pop 2>&1 | Out-Null
        }
        exit 0
    }
}

# ============================================================
# Step 3.5: Pre-merge deletion warning
# ============================================================

Write-Banner "Step 3.5: Check for Local-Only Files at Risk"

# Find files that exist locally but not in upstream -- these will be deleted by merge
# unless they are in .gitignore or .update-preserve
$upstreamFiles = git ls-tree -r --name-only "upstream/$UpstreamBranch" 2>$null
$localTrackedFiles = git ls-files 2>$null

if ($upstreamFiles -and $localTrackedFiles) {
    $upstreamSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$upstreamFiles, [System.StringComparer]::OrdinalIgnoreCase)
    $localOnlyFiles = @()

    foreach ($lf in $localTrackedFiles) {
        if (-not $upstreamSet.Contains($lf)) {
            $localOnlyFiles += $lf
        }
    }

    # Filter out files already protected by .update-preserve
    $preserveSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$PersonalizedFiles, [System.StringComparer]::OrdinalIgnoreCase)
    $atRiskFiles = $localOnlyFiles | Where-Object { -not $preserveSet.Contains($_) }

    if ($atRiskFiles.Count -gt 0) {
        Write-Warn "$($atRiskFiles.Count) local-only file(s) not in upstream and not protected:"
        foreach ($rf in $atRiskFiles) {
            Write-Host "    $rf" -ForegroundColor DarkYellow
        }
        Write-Host ""
        Write-Host "  These files may be deleted during merge." -ForegroundColor Yellow
        Write-Host "  Add them to .update-preserve to protect them, or press Enter to continue." -ForegroundColor Yellow
        Write-Host ""

        if (-not $Force -and -not $DryRun) {
            # Auto-backup at-risk files regardless of user choice
            $atRiskBackupDir = Join-Path $ProjectRoot ".update-backup-atrisk"
            New-Item -ItemType Directory -Path $atRiskBackupDir -Force | Out-Null
            foreach ($rf in $atRiskFiles) {
                $rfFull = Join-Path $ProjectRoot $rf
                if (Test-Path $rfFull) {
                    $destDir = Join-Path $atRiskBackupDir (Split-Path $rf -Parent)
                    if ($destDir -and -not (Test-Path $destDir)) {
                        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
                    }
                    Copy-Item $rfFull (Join-Path $atRiskBackupDir $rf) -Force
                }
            }
            Write-Ok "Safety backup created at .update-backup-atrisk/ (just in case)"
        }
    } else {
        Write-Ok "No unprotected local-only files at risk"
    }
} else {
    Write-Ok "Could not compare trees - skipping local-only file check"
}

# ============================================================
# Step 3.7: Back up untracked runtime directories in skills/
# ============================================================

$runtimeBackupDir = Join-Path $ProjectRoot ".update-backup-runtime"
# NOTE: Backup dirs (.update-backup, .update-backup-runtime) may contain
# secrets from .env, agentconfig.json, or skills/ config files. They are
# cleaned up after restore (see Step 7.7), but if the script exits early,
# manual cleanup is required. These dirs are also listed in .gitignore.
$untrackedRuntimeDirs = @()

if (-not $DryRun) {
    # Scan skills/ for non-empty untracked directories (caches, logs, PID files)
    $skillsDir = Join-Path $ProjectRoot "skills"
    if (Test-Path $skillsDir) {
        $untrackedPaths = git ls-files --others --directory -- "skills/" 2>$null
        if ($untrackedPaths) {
            foreach ($uPath in $untrackedPaths) {
                # Skip Python bytecode caches and other non-essential noise
                if ($uPath -match '__pycache__|\.pyc$|node_modules|\.venv|\.egg-info|/dist/|/build/') { continue }
                $fullPath = Join-Path $ProjectRoot $uPath.TrimEnd('/')
                if ((Test-Path $fullPath -PathType Container) -and (Get-ChildItem $fullPath -Recurse -File -ErrorAction SilentlyContinue)) {
                    $untrackedRuntimeDirs += $uPath.TrimEnd('/')
                }
            }
        }
    }

    if ($untrackedRuntimeDirs.Count -gt 0) {
        Write-Step "Backing up $($untrackedRuntimeDirs.Count) untracked runtime dir(s) in skills/..."
        New-Item -ItemType Directory -Path $runtimeBackupDir -Force | Out-Null
        foreach ($rtDir in $untrackedRuntimeDirs) {
            $src = Join-Path $ProjectRoot $rtDir
            $dest = Join-Path $runtimeBackupDir $rtDir
            $destParent = Split-Path $dest -Parent
            if (-not (Test-Path $destParent)) {
                New-Item -ItemType Directory -Path $destParent -Force | Out-Null
            }
            Copy-Item $src $dest -Recurse -Force
            Write-Host "    + $rtDir" -ForegroundColor DarkGreen
        }
        Write-Ok "Runtime state backed up to .update-backup-runtime/"
    } else {
        Write-Ok "No untracked runtime directories found"
    }
} else {
    Write-Host "    Would scan skills/ for untracked runtime dirs" -ForegroundColor Gray
}

# ============================================================
# Step 3.8: Stop background services before merge
# ============================================================

$schedulerWasRunning = $false
$monitorWasRunning = $false

if (-not $DryRun) {
    # Stop task scheduler if running.
    # Primary: check PID file. Fallback: process scan for orphans when PID file is missing.
    $schedulerPidFile = Join-Path $ProjectRoot "skills" "task-scheduler" "scheduler.pid"
    if (Test-Path $schedulerPidFile) {
        $schedulerWasRunning = $true
        $schedulerPid = (Get-Content $schedulerPidFile -Raw).Trim()
        if ($schedulerPid -match '^\d+$') {
            $proc = Get-Process -Id ([int]$schedulerPid) -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Step "Stopping task scheduler (PID $schedulerPid)..."
                try {
                    Stop-Process -Id ([int]$schedulerPid) -Force -ErrorAction Stop
                    Write-Ok "Task scheduler stopped"
                    Remove-Item $schedulerPidFile -Force -ErrorAction SilentlyContinue
                } catch {
                    Write-Warn "Could not stop scheduler (PID $schedulerPid): $_"
                }
            } else {
                Write-Step "Task scheduler PID $schedulerPid is stale (process not running) -- will restart after upgrade"
                Remove-Item $schedulerPidFile -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        # PID file missing — scan for orphaned scheduler processes (e.g. after crash or git clean)
        try {
            $orphans = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'scheduler-service\.ps1' })
            if ($orphans.Count -gt 0) {
                $schedulerWasRunning = $true
                foreach ($orphan in $orphans) {
                    Write-Step "Stopping orphaned scheduler (PID $($orphan.ProcessId), no PID file)..."
                    try {
                        Stop-Process -Id ([int]$orphan.ProcessId) -Force -ErrorAction Stop
                        Write-Ok "Orphaned scheduler stopped (PID $($orphan.ProcessId))"
                    } catch {
                        Write-Warn "Could not stop orphaned scheduler (PID $($orphan.ProcessId)): $_"
                    }
                }
            }
        } catch {
            Write-Warn "Process scan for orphaned scheduler failed: $_"
        }
    }

    # Stop Teams monitor service if running
    $monitorPidFile = Join-Path $ProjectRoot "skills" "teams" "monitor" "monitor.pid"
    if (-not (Test-Path $monitorPidFile)) {
        # Also check legacy locations
        $monitorPidFile = Join-Path $ProjectRoot "skills" "teams" "monitor.pid"
    }
    if (-not (Test-Path $monitorPidFile)) {
        $monitorPidFile = Join-Path $ProjectRoot "skills" "teams" "scripts" "monitor" "monitor.pid"
    }
    if (Test-Path $monitorPidFile) {
        $monitorWasRunning = $true
        $monitorPid = (Get-Content $monitorPidFile -Raw).Trim()
        if ($monitorPid -match '^\d+$') {
            $proc = Get-Process -Id ([int]$monitorPid) -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Step "Stopping Teams monitor (PID $monitorPid)..."
                try {
                    Stop-Process -Id ([int]$monitorPid) -Force -ErrorAction Stop
                    Write-Ok "Teams monitor stopped"
                    Remove-Item $monitorPidFile -Force -ErrorAction SilentlyContinue
                    # Also clean lock file to prevent singleton conflict on restart
                    $lockFile = Join-Path (Split-Path $monitorPidFile) "monitor.lock"
                    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
                } catch {
                    Write-Warn "Could not stop monitor (PID $monitorPid): $_"
                }
            } else {
                Write-Step "Teams monitor PID $monitorPid is stale (process not running) -- will restart after upgrade"
                Remove-Item $monitorPidFile -Force -ErrorAction SilentlyContinue
                $lockFile = Join-Path (Split-Path $monitorPidFile) "monitor.lock"
                Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        # PID file missing — scan for orphaned monitor processes (e.g. after crash or git clean)
        try {
            $orphans = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'scripts\.monitor\.service' })
            if ($orphans.Count -gt 0) {
                $monitorWasRunning = $true
                foreach ($orphan in $orphans) {
                    Write-Step "Stopping orphaned Teams monitor (PID $($orphan.ProcessId), no PID file)..."
                    try {
                        Stop-Process -Id ([int]$orphan.ProcessId) -Force -ErrorAction Stop
                        Write-Ok "Orphaned Teams monitor stopped (PID $($orphan.ProcessId))"
                    } catch {
                        Write-Warn "Could not stop orphaned Teams monitor (PID $($orphan.ProcessId)): $_"
                    }
                }
            }
        } catch {
            Write-Warn "Process scan for orphaned Teams monitor failed: $_"
        }
    }

    if (-not $schedulerWasRunning -and -not $monitorWasRunning) {
        Write-Ok "No background services running"
    }
} else {
    Write-Host "    Would stop background services (scheduler, Teams monitor)" -ForegroundColor Gray
}

# ============================================================
# Step 4: Back up personalized files
# ============================================================

Write-Banner "Step 4: Protect Personalized Files"

$backupDir = Join-Path $ProjectRoot ".update-backup"
if (-not $DryRun) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

$backedUp = @()
foreach ($file in $PersonalizedFiles) {
    $fullPath = Join-Path $ProjectRoot $file
    if (Test-Path $fullPath) {
        Write-Step "Backing up: $file"
        if (-not $DryRun) {
            # Ensure subdirectory structure exists in backup
            $backupTarget = Join-Path $backupDir $file
            $backupTargetDir = Split-Path $backupTarget -Parent
            if ($backupTargetDir -and -not (Test-Path $backupTargetDir)) {
                New-Item -ItemType Directory -Path $backupTargetDir -Force | Out-Null
            }
            Copy-Item $fullPath $backupTarget -Force
        }
        $backedUp += $file
    }
}

if ($backedUp.Count -gt 0) {
    Write-Ok "Backed up $($backedUp.Count) personalized file(s) to .update-backup/"
} else {
    Write-Ok "No personalized files to protect"
}

# ============================================================
# Step 4.5: OneDrive cloud backup of customizations
# ============================================================

Write-Banner "Step 4.5: OneDrive Cloud Backup"

if (-not $DryRun) {
    $configPath45 = Join-Path $ProjectRoot "agentconfig.json"
    $memLocation45 = $null
    $onedrivePath45 = $null

    if (Test-Path $configPath45) {
        try {
            $agentConfig45 = Get-Content $configPath45 -Raw | ConvertFrom-Json
            $memLocation45 = $agentConfig45.memory.location
            $onedrivePath45 = $agentConfig45.memory.onedrivePath
        } catch { }
    }

    if ($memLocation45 -and $memLocation45 -match "onedrive") {
        # Resolve the workspace OneDrive folder (parent of memory/)
        $onedriveWorkspaceDir = $null
        if ($onedrivePath45 -and (Test-Path $onedrivePath45)) {
            # onedrivePath points to .../Agency Cowork/<workspace>/memory
            $onedriveWorkspaceDir = Split-Path $onedrivePath45 -Parent
        } else {
            # Fall back: detect OneDrive and construct the path
            $odPath = Detect-OneDrivePath
            if ($odPath) {
                $folderName45 = Split-Path $ProjectRoot -Leaf
                $onedriveWorkspaceDir = Join-Path (Join-Path $odPath "Agency Cowork") $folderName45
            }
        }

        if ($onedriveWorkspaceDir -and (Test-Path $onedriveWorkspaceDir)) {
            $backupTimestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $cloudBackupDir = Join-Path $onedriveWorkspaceDir "backups\pre-upgrade-$backupTimestamp"

            Write-Step "Backing up customizations to OneDrive..."
            try {
                New-Item -ItemType Directory -Path $cloudBackupDir -Force | Out-Null

                # Back up CLAUDE.md and AGENTS.md
                foreach ($customFile in @("CLAUDE.md", "AGENTS.md")) {
                    $srcFile = Join-Path $ProjectRoot $customFile
                    if (Test-Path $srcFile) {
                        Copy-Item $srcFile (Join-Path $cloudBackupDir $customFile) -Force
                    }
                }

                # Back up agentconfig.json
                $srcConfig = Join-Path $ProjectRoot "agentconfig.json"
                if (Test-Path $srcConfig) {
                    Copy-Item $srcConfig (Join-Path $cloudBackupDir "agentconfig.json") -Force
                }

                # Back up skills/ directory (excluding caches, __pycache__, node_modules)
                $srcSkills = Join-Path $ProjectRoot "skills"
                if (Test-Path $srcSkills) {
                    $destSkills = Join-Path $cloudBackupDir "skills"
                    New-Item -ItemType Directory -Path $destSkills -Force | Out-Null
                    $skillFiles = Get-ChildItem $srcSkills -Recurse -File -ErrorAction SilentlyContinue |
                        Where-Object {
                            $_.FullName -notmatch '__pycache__|node_modules|\.pyc$|\.egg-info|/\.venv/|\\\.venv\\|/cache/|\\cache\\'
                        }
                    $cloudCopied = 0
                    foreach ($sf in $skillFiles) {
                        $relPath = $sf.FullName.Substring($srcSkills.Length + 1)
                        $destFile = Join-Path $destSkills $relPath
                        $destDir = Split-Path $destFile -Parent
                        if (-not (Test-Path $destDir)) {
                            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
                        }
                        Copy-Item $sf.FullName $destFile -Force
                        $cloudCopied++
                    }
                    Write-Ok "Backed up skills/ ($cloudCopied files) to OneDrive"
                }

                Write-Ok "Cloud backup: $cloudBackupDir"

                # Prune old backups -- keep only the 5 most recent pre-upgrade backups
                $backupsRoot = Join-Path $onedriveWorkspaceDir "backups"
                if (Test-Path $backupsRoot) {
                    $oldBackups = Get-ChildItem $backupsRoot -Directory -Filter "pre-upgrade-*" -ErrorAction SilentlyContinue |
                        Sort-Object Name -Descending |
                        Select-Object -Skip 5
                    foreach ($old in $oldBackups) {
                        Remove-Item $old.FullName -Recurse -Force -ErrorAction SilentlyContinue
                        Write-Host "    Pruned old backup: $($old.Name)" -ForegroundColor Gray
                    }
                }
            } catch {
                Write-Warn "OneDrive cloud backup failed (non-fatal): $_"
                Write-Warn "Local backup in .update-backup/ is still intact."
            }
        } else {
            Write-Host "    OneDrive workspace folder not found -- skipping cloud backup" -ForegroundColor Gray
        }
    } else {
        Write-Host "    OneDrive not configured for memory -- skipping cloud backup" -ForegroundColor Gray
        Write-Host "    (Run setup or edit agentconfig.json to enable OneDrive sync)" -ForegroundColor Gray
    }
} else {
    # DryRun
    $configPath45 = Join-Path $ProjectRoot "agentconfig.json"
    if (Test-Path $configPath45) {
        try {
            $ac45 = Get-Content $configPath45 -Raw | ConvertFrom-Json
            if ($ac45.memory.location -match "onedrive") {
                Write-Host "    Would back up CLAUDE.md, AGENTS.md, skills/ to OneDrive" -ForegroundColor Gray
            }
        } catch { }
    }
}

# ============================================================
# Step 5: Merge upstream
# ============================================================

Write-Banner "Step 5: Merge Upstream Changes"

if ($DryRun) {
    Write-Host "    Would merge upstream/$UpstreamBranch into $currentBranch" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Files that would be updated:" -ForegroundColor White
    git diff --name-only "$currentBranch..upstream/$UpstreamBranch" 2>$null | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
} else {
    Write-Step "Merging upstream/$UpstreamBranch into $currentBranch..."

    # Use a merge strategy that favors ours for personalized files
    git merge "upstream/$UpstreamBranch" --no-edit 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }

    if ($LASTEXITCODE -ne 0) {
        # Merge conflict - check if it's only in personalized files
        $conflictFiles = git diff --name-only --diff-filter=U 2>$null
        $personalConflicts = @()
        $otherConflicts = @()

        foreach ($cf in $conflictFiles) {
            if ($PersonalizedFiles -contains $cf) {
                $personalConflicts += $cf
            } else {
                $otherConflicts += $cf
            }
        }

        # Auto-resolve personalized file conflicts by keeping ours
        foreach ($pf in $personalConflicts) {
            Write-Step "Resolving conflict in $pf - keeping YOUR version"
            git checkout --ours $pf 2>&1 | Out-Null
            git add $pf 2>&1 | Out-Null
        }

        if ($otherConflicts.Count -gt 0) {
            Write-Err "Merge conflicts in non-personalized files:"
            foreach ($oc in $otherConflicts) {
                Write-Host "    $oc" -ForegroundColor Red
            }
            Write-Host ""
            Write-Host "  Resolve these conflicts manually, then run:" -ForegroundColor White
            Write-Host '    git add <resolved-files>' -ForegroundColor Gray
            Write-Host "    git merge --continue" -ForegroundColor Gray
            Write-Host ""
            Write-Host "  Or abort the merge:" -ForegroundColor White
            Write-Host "    git merge --abort" -ForegroundColor Gray

            if ($didStash) {
                Write-Warn "Your stashed changes will be restored after you resolve conflicts."
                Write-Host "    Run: git stash pop" -ForegroundColor Gray
            }
            exit 1
        }

        # All conflicts were in personalized files and auto-resolved
        if ($personalConflicts.Count -gt 0) {
            git commit --no-edit 2>&1 | Out-Null
            Write-Ok "Merge completed (personalized file conflicts auto-resolved)"
        }
    } else {
        Write-Ok "Merge completed cleanly"
    }

    # Restore personalized files from backup (in case merge overwrote them)
    foreach ($file in $backedUp) {
        $backupPath = Join-Path $backupDir $file
        $restorePath = Join-Path $ProjectRoot $file
        if (Test-Path $backupPath) {
            # Ensure directory exists (file may have been deleted by merge)
            $restoreDir = Split-Path $restorePath -Parent
            if ($restoreDir -and -not (Test-Path $restoreDir)) {
                New-Item -ItemType Directory -Path $restoreDir -Force | Out-Null
            }
            Copy-Item $backupPath $restorePath -Force
            Write-Ok "Restored your customized: $file"
        }
    }

    # Smart-merge agentconfig.json: preserve local values but add new upstream keys
    # Since agentconfig.json is tracked in git, we compare the user's backup against
    # the upstream version to find new keys added by the update.
    $agentConfigPath = Join-Path $ProjectRoot "agentconfig.json"
    $agentConfigBackup = Join-Path $backupDir "agentconfig.json"
    if ((Test-Path $agentConfigPath) -and (Test-Path $agentConfigBackup)) {
        try {
            $localConfig = Get-Content $agentConfigBackup -Raw | ConvertFrom-Json -AsHashtable
            # Get the upstream version (what the merge brought in) by reading from git
            $upstreamJson = git show "HEAD:agentconfig.json" 2>$null
            if ($upstreamJson) {
                $upstreamConfig = $upstreamJson | ConvertFrom-Json -AsHashtable
                $addedKeys = 0

                # Recursively add missing keys from upstream into local config
                function Merge-MissingKeys {
                    param([hashtable]$Local, [hashtable]$Upstream, [string]$Path = "")
                    $added = 0
                    foreach ($key in $Upstream.Keys) {
                        $keyPath = if ($Path) { "$Path.$key" } else { $key }
                        if (-not $Local.ContainsKey($key)) {
                            $Local[$key] = $Upstream[$key]
                            Write-Host "    + Added new config key: $keyPath" -ForegroundColor Green
                            $added++
                        } elseif ($Upstream[$key] -is [hashtable] -and $Local[$key] -is [hashtable]) {
                            $added += Merge-MissingKeys -Local $Local[$key] -Upstream $Upstream[$key] -Path $keyPath
                        }
                    }
                    return $added
                }

                $addedKeys = Merge-MissingKeys -Local $localConfig -Upstream $upstreamConfig
                if ($addedKeys -gt 0) {
                    $localConfig | ConvertTo-Json -Depth 10 | Set-Content $agentConfigPath -Encoding utf8
                    Write-Ok "Merged $addedKeys new key(s) from upstream into agentconfig.json (your values preserved)"
                }
            }
        } catch {
            Write-Warn "Could not smart-merge agentconfig.json: $($_.Exception.Message)"
        }
    }
}

# ============================================================
# Step 5.5: Post-merge regression check
# ============================================================

Write-Banner "Step 5.5: Post-Merge Regression Check"

if (-not $DryRun) {
    $regressions = @()

    # Check every backed-up file was restored correctly
    foreach ($file in $backedUp) {
        $restorePath = Join-Path $ProjectRoot $file
        $backupPath = Join-Path $backupDir $file
        if (-not (Test-Path $restorePath)) {
            $regressions += "$file [DELETED - restore failed]"
        } elseif (Test-Path $backupPath) {
            $currentHash = (Get-FileHash $restorePath -Algorithm SHA256).Hash
            $backupHash  = (Get-FileHash $backupPath  -Algorithm SHA256).Hash
            if ($currentHash -ne $backupHash) {
                $regressions += "$file [CONTENT CHANGED - backup/restore mismatch]"
            }
        }
    }

    # Check for any preserved-manifest files that no longer exist (merge may have deleted parent dirs)
    foreach ($file in $PersonalizedFiles) {
        $fullPath = Join-Path $ProjectRoot $file
        if ($backedUp -notcontains $file) {
            # This file didn't exist pre-merge either - skip
            continue
        }
        if (-not (Test-Path $fullPath)) {
            if ($regressions -notcontains "$file [DELETED - restore failed]") {
                $regressions += "$file [MISSING after merge]"
            }
        }
    }

    if ($regressions.Count -gt 0) {
        Write-Err "REGRESSION DETECTED - $($regressions.Count) protected file(s) may have been affected:"
        foreach ($r in $regressions) {
            Write-Host "    $r" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "  Backups are available in .update-backup/ for manual recovery." -ForegroundColor Yellow
    } else {
        Write-Ok "All $($backedUp.Count) protected file(s) verified - no regressions"
    }

    # Additional runtime state validation
    $warnings = @()

    # Check embedding cache survived (if it existed before)
    $embeddingDir = Join-Path $ProjectRoot "skills" "qmd-memory" "cache" "embeddings"
    $embeddingBackup = Join-Path $runtimeBackupDir "skills" "qmd-memory" "cache" "embeddings"
    if ((Test-Path $embeddingBackup) -and -not (Test-Path $embeddingDir)) {
        $warnings += "QMD embedding cache was not restored -- vector search may be non-functional"
    } elseif ((Test-Path $embeddingDir) -and -not (Get-ChildItem $embeddingDir -File -ErrorAction SilentlyContinue)) {
        $warnings += "QMD embedding cache is empty -- vector search may be non-functional"
    }

    # Migrate QMD MCP config from legacy bash/shim approach to node-direct + adapter
    $qmdInstalled = Get-Command qmd -ErrorAction SilentlyContinue
    if ($qmdInstalled) {
        $qmdNodeExe = $null
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) { $qmdNodeExe = $nodeCmd.Source }
        $qmdEntryScript = $null
        $qmdNpmPrefix = $null
        try { $qmdNpmPrefix = (npm config get prefix 2>$null).Trim() } catch {}
        if ($qmdNpmPrefix) {
            $candidate = Join-Path $qmdNpmPrefix "node_modules\@tobilu\qmd\dist\cli\qmd.js"
            if (Test-Path $candidate) { $qmdEntryScript = $candidate }
        }
        if (-not $qmdEntryScript) {
            foreach ($loc in @(
                (Join-Path $env:APPDATA "npm\node_modules\@tobilu\qmd\dist\cli\qmd.js"),
                (Join-Path $HOME ".npm-global\node_modules\@tobilu\qmd\dist\cli\qmd.js")
            )) { if ((Test-Path $loc) -and -not $qmdEntryScript) { $qmdEntryScript = $loc } }
        }
        $adapterScript = Join-Path $ScriptDir "qmd-mcp-adapter.js"
        $wsMcpPath = Join-Path $ProjectRoot ".mcp.json"
        $legacyMcpPath = Join-Path $ProjectRoot ".vscode" "mcp.json"
        $globalMcpPath = Join-Path $env:USERPROFILE ".copilot" "mcp-config.json"
        # Migrate legacy .vscode/mcp.json to .mcp.json if needed
        if ((Test-Path $legacyMcpPath) -and -not (Test-Path $wsMcpPath)) {
            try {
                $legCfg = Get-Content $legacyMcpPath -Raw | ConvertFrom-Json
                $legServers = if ($legCfg.PSObject.Properties["servers"]) { $legCfg.servers } elseif ($legCfg.PSObject.Properties["mcpServers"]) { $legCfg.mcpServers } else { @{} }
                $migCfg = [PSCustomObject]@{ mcpServers = $legServers }
                $migCfg | ConvertTo-Json -Depth 10 | Set-Content $wsMcpPath
                Remove-Item -LiteralPath $legacyMcpPath -Force
                Write-Ok "Migrated .vscode/mcp.json -> .mcp.json"
            } catch {
                $warnings += "Could not auto-migrate .vscode/mcp.json: $($_.Exception.Message)"
            }
        } elseif ((Test-Path $legacyMcpPath) -and (Test-Path $wsMcpPath)) {
            Remove-Item -LiteralPath $legacyMcpPath -Force -ErrorAction SilentlyContinue
            Write-Ok "Removed stale .vscode/mcp.json (using .mcp.json)"
        }
        foreach ($cfgPath in @($wsMcpPath, $globalMcpPath)) {
            if (-not (Test-Path $cfgPath)) { continue }
            try {
                $mcpCfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
                $sKey = if ($mcpCfg.PSObject.Properties["mcpServers"]) { "mcpServers" } else { "servers" }
                $qmdEntry = if ($mcpCfg.$sKey) { $mcpCfg.$sKey.PSObject.Properties["qmd"] } else { $null }
                if (-not $qmdEntry) { continue }
                $q = $qmdEntry.Value
                $isLegacy = ($q.command -eq "qmd") -or
                            ($q.env -and $q.env.PATH) -or
                            ($q.command -like "*node*" -and ($q.args -notcontains $adapterScript))
                if ($isLegacy -and $qmdNodeExe -and $qmdEntryScript -and (Test-Path $adapterScript)) {
                    $q.command = $qmdNodeExe
                    $q.args = @($adapterScript, "--", $qmdNodeExe, $qmdEntryScript, "mcp")
                    if ($q.PSObject.Properties["env"]) { $q.PSObject.Properties.Remove("env") }
                    Set-Content $cfgPath -Value ($mcpCfg | ConvertTo-Json -Depth 10)
                    Write-Ok "QMD MCP: migrated to node-direct + adapter in $(Split-Path -Leaf $cfgPath)"
                }
            } catch {
                $warnings += "Could not migrate QMD MCP config in $(Split-Path -Leaf $cfgPath): $($_.Exception.Message)"
            }
        }
        if (-not $qmdNodeExe) {
            $warnings += "Could not resolve node.exe -- QMD MCP migration skipped (run setup.ps1 after installing Node)"
        } elseif (-not $qmdEntryScript) {
            $warnings += "Could not find qmd.js entry point -- QMD MCP migration skipped (run: npm install -g @tobilu/qmd)"
        }
    }

    # Check scheduler PID file references a valid process
    $schedPidFile = Join-Path $ProjectRoot "skills" "task-scheduler" "scheduler.pid"
    if (Test-Path $schedPidFile) {
        $schedPid = (Get-Content $schedPidFile -Raw).Trim()
        if ($schedPid -match '^\d+$') {
            $schedProc = Get-Process -Id ([int]$schedPid) -ErrorAction SilentlyContinue
            if (-not $schedProc -and -not $schedulerWasRunning) {
                $warnings += "scheduler.pid ($schedPid) references a process that is not running"
            }
        }
    }

    # Verify azureauth installation (incomplete extraction causes 0xe0434352)
    $azureAuthDir = Join-Path $env:LOCALAPPDATA "Programs" "AzureAuth"
    if (Test-Path $azureAuthDir) {
        $versionDirs = Get-ChildItem $azureAuthDir -Directory | Where-Object { $_.Name -match '^\d+\.\d+' } | Sort-Object { [version]($_.Name -replace '[^\d.]','') } -Descending
        if ($versionDirs.Count -gt 0) {
            $msalDll = Join-Path $versionDirs[0].FullName "MSALWrapper.dll"
            $azExe = Join-Path $versionDirs[0].FullName "azureauth.exe"
            if ((Test-Path $azExe) -and -not (Test-Path $msalDll)) {
                $warnings += "AzureAuth incomplete: MSALWrapper.dll missing from $($versionDirs[0].Name) -- MCP auth will fail (0xe0434352). Re-run setup.ps1 to auto-repair."
            } elseif (Test-Path $azExe) {
                try {
                    $azVer = & $azExe --version 2>$null
                    if ($LASTEXITCODE -ne 0) {
                        $warnings += "AzureAuth $($versionDirs[0].Name) exits with error -- MCP auth may fail"
                    }
                } catch { }
            }
        }
    }

    if ($warnings.Count -gt 0) {
        Write-Warn "Runtime state warnings ($($warnings.Count)):"
        foreach ($w in $warnings) {
            Write-Host "    - $w" -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "    Would run post-merge regression check" -ForegroundColor Gray
}

# ============================================================
# Step 6: Detect upstream template changes
# ============================================================

Write-Banner "Step 6: Review Template Changes"

$templateFiles = @("CLAUDE.md.example", "AGENTS.md.example")
$templatesChanged = @()

foreach ($tf in $templateFiles) {
    $diff = git diff "HEAD~1..HEAD" -- $tf 2>$null
    if ($diff) {
        $templatesChanged += $tf
    }
}

if ($templatesChanged.Count -gt 0 -and -not $DryRun) {
    Write-Warn "The following templates were updated upstream:"
    foreach ($tc in $templatesChanged) {
        Write-Host "    $tc" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  ----------------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  RECOMMENDED: Ask your AI coworker to integrate the changes." -ForegroundColor Cyan
    Write-Host "  ----------------------------------------------------------------" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Your personalized CLAUDE.md and AGENTS.md were preserved, but the" -ForegroundColor White
    Write-Host "  upstream .example templates have new content. To safely integrate:" -ForegroundColor White
    Write-Host ""
    Write-Host "  Start a Copilot session and ask:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host '    "Compare CLAUDE.md.example with my CLAUDE.md and integrate any' -ForegroundColor White
    Write-Host '     new sections or changes while keeping my customizations."' -ForegroundColor White
    Write-Host ""
    Write-Host '    "Compare AGENTS.md.example with my AGENTS.md and integrate any' -ForegroundColor White
    Write-Host '     new skills, rules, or sections while keeping my customizations."' -ForegroundColor White
    Write-Host ""
    Write-Host "  The AI agent can read both files, identify what's new in the template," -ForegroundColor Gray
    Write-Host "  and surgically add new features without overwriting your identity," -ForegroundColor Gray
    Write-Host "  domain knowledge, or communication preferences." -ForegroundColor Gray
    Write-Host ""

    # Save a diff summary for the agent to review
    $diffReport = Join-Path $ProjectRoot ".update-backup\template-changes.md"
    $diffContent = "# Upstream Template Changes`n`n"
    $diffContent += "Generated by ``scripts/update.ps1`` on $(Get-Date -Format 'yyyy-MM-dd HH:mm')`n`n"
    $diffContent += "Review these changes and integrate relevant ones into your personalized files.`n`n"

    foreach ($tc in $templatesChanged) {
        $localFile = $tc -replace '\.example$', ''
        $diffContent += "## $tc`n`n"
        $diffContent += "Corresponding personalized file: ``$localFile```n`n"
        $diffContent += "``````diff`n"
        $diffContent += (git diff "HEAD~1..HEAD" -- $tc 2>$null) -join "`n"
        $diffContent += "`n```````n`n"
    }

    Set-Content $diffReport $diffContent
    Write-Ok "Diff summary saved to: .update-backup/template-changes.md"
    Write-Host "    Share this file with your AI coworker for context." -ForegroundColor Gray
} elseif (-not $DryRun) {
    Write-Ok "No template changes to review"
}

# ============================================================
# Step 7: Restore stashed changes
# ============================================================

Write-Banner "Step 7: Restore Local Changes"

if ($didStash -and -not $DryRun) {
    Write-Step "Restoring stashed changes..."
    git stash pop 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Stash pop had conflicts. Resolve manually, then run: git stash drop"
    } else {
        Write-Ok "Stashed changes restored"
    }
} elseif ($didStash) {
    Write-Host "    Would restore stashed changes" -ForegroundColor Gray
} else {
    Write-Ok "No stashed changes to restore"
}

# ============================================================
# Step 7.5: Offer OneDrive migration for local/git memory configs
# ============================================================

$didMigrateOneDrive = $false

if (-not $DryRun) {
    $configPath = Join-Path $ProjectRoot "agentconfig.json"
    $memoryLocation = $null
    if (Test-Path $configPath) {
        try {
            $agentConfig = Get-Content $configPath -Raw | ConvertFrom-Json
            $memoryLocation = $agentConfig.memory.location
        } catch {
            Write-Warn "Could not parse agentconfig.json: $_"
        }
    }

    # Treat missing/null/empty memory.location as "local" (the Electron default)
    $effectiveLocation = if ([string]::IsNullOrWhiteSpace($memoryLocation)) { "local" } else { $memoryLocation }

    if ($effectiveLocation -eq "local" -or $effectiveLocation -eq "git") {
        $oneDrivePath = Detect-OneDrivePath
        $memoryDir = Join-Path $ProjectRoot "memory"
        $alreadyInside = Test-InsideOneDrive -DirPath $ProjectRoot -OneDrivePath $oneDrivePath

        if ($oneDrivePath -and -not $alreadyInside) {
            Write-Banner "OneDrive Memory Migration"

            if ($effectiveLocation -eq "git") {
                Write-Host "  Your memory is currently synced via Git (memory.location = `"git`")." -ForegroundColor White
                Write-Host "  OneDrive detected at: $oneDrivePath" -ForegroundColor White
                Write-Host ""
                Write-Host "  Adding OneDrive sync gives you both:" -ForegroundColor White
                Write-Host "    - Git version control (commit history, branching, PRs)" -ForegroundColor Gray
                Write-Host "    - OneDrive cloud backup (automatic, cross-device, version history)" -ForegroundColor Gray
                Write-Host "    - Seamless junction -- memory/ path stays the same" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  Your Git repo stays intact. OneDrive syncs the same folder," -ForegroundColor Yellow
                Write-Host "  so you get both Git + cloud backup working together." -ForegroundColor Yellow
            } else {
                Write-Host "  Your memory is currently stored locally (memory.location = `"$memoryLocation`")." -ForegroundColor White
                Write-Host "  OneDrive detected at: $oneDrivePath" -ForegroundColor White
                Write-Host ""
                Write-Host "  Migrating to OneDrive gives you:" -ForegroundColor White
                Write-Host "    - Cross-device sync (access memory from any machine)" -ForegroundColor Gray
                Write-Host "    - Automatic cloud backup" -ForegroundColor Gray
                Write-Host "    - Seamless junction -- memory/ path stays the same" -ForegroundColor Gray
            }
            Write-Host ""

            $folderName = Split-Path $ProjectRoot -Leaf
            $targetPreview = Join-Path (Join-Path (Join-Path $oneDrivePath "Agency Cowork") $folderName) "memory"
            Write-Host "  Target: $targetPreview" -ForegroundColor DarkCyan
            Write-Host ""

            if ($Force) {
                # Force mode: auto-yes for local, skip for git (git users chose deliberately)
                $migrate = if ($effectiveLocation -eq "git") { "n" } else { "y" }
            } else {
                $defaultChoice = if ($effectiveLocation -eq "git") { "n" } else { "y" }
                $promptSuffix = if ($effectiveLocation -eq "git") { "[y/N]" } else { "[Y/n]" }
                $migrate = Read-Host "  Migrate memory to OneDrive? $promptSuffix"
                if ([string]::IsNullOrWhiteSpace($migrate)) { $migrate = $defaultChoice }
            }

            if ($migrate.ToLower() -eq "y") {
                Write-Step "Migrating memory to OneDrive..."
                $didMigrateOneDrive = Invoke-OneDriveMigration `
                    -ProjectRoot $ProjectRoot `
                    -OneDrivePath $oneDrivePath `
                    -FolderName $folderName
                if ($didMigrateOneDrive) {
                    Write-Ok "Memory successfully migrated to OneDrive"
                }
            } else {
                Write-Host "    Skipped. You can migrate later by editing agentconfig.json" -ForegroundColor Gray
                Write-Host "    or running setup.ps1 again." -ForegroundColor Gray
            }
        } elseif ($alreadyInside) {
            Write-Host "  [INFO] Project is already inside OneDrive -- no junction needed." -ForegroundColor Gray
        }
    }
} else {
    # DryRun: just report what would happen
    $configPath = Join-Path $ProjectRoot "agentconfig.json"
    if (Test-Path $configPath) {
        try {
            $agentConfig = Get-Content $configPath -Raw | ConvertFrom-Json
            $memLoc = $agentConfig.memory.location
            $effLoc = if ([string]::IsNullOrWhiteSpace($memLoc)) { "local" } else { $memLoc }
            if ($effLoc -eq "local" -or $effLoc -eq "git") {
                $oneDrivePath = Detect-OneDrivePath
                if ($oneDrivePath) {
                    Write-Host "    Would offer OneDrive memory migration ($effLoc -> onedrive, OneDrive at: $oneDrivePath)" -ForegroundColor Gray
                }
            }
        } catch { }
    }
}

# ============================================================
# Step 7.7: Restore untracked runtime directories
# ============================================================

if (-not $DryRun -and (Test-Path $runtimeBackupDir)) {
    $restoredCount = 0
    foreach ($rtDir in $untrackedRuntimeDirs) {
        $src = Join-Path $runtimeBackupDir $rtDir
        $dest = Join-Path $ProjectRoot $rtDir
        if (-not (Test-Path $src)) { continue }
        # Merge strategy: copy files from backup that don't exist at dest
        $destParent = Split-Path $dest -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }
        if (-not (Test-Path $dest)) {
            # Dest missing entirely -- restore whole dir
            Copy-Item $src $dest -Recurse -Force
            $restoredCount++
        } else {
            # Dest exists -- merge: copy missing files from backup
            $srcFiles = Get-ChildItem $src -Recurse -File -ErrorAction SilentlyContinue
            $merged = 0
            foreach ($f in $srcFiles) {
                $rel = $f.FullName.Substring($src.Length)
                $destFile = Join-Path $dest $rel
                if (-not (Test-Path $destFile)) {
                    $destFileDir = Split-Path $destFile -Parent
                    if (-not (Test-Path $destFileDir)) { New-Item -ItemType Directory -Path $destFileDir -Force | Out-Null }
                    Copy-Item $f.FullName $destFile -Force
                    $merged++
                }
            }
            if ($merged -gt 0) { $restoredCount++ }
        }
    }
    if ($restoredCount -gt 0) {
        Write-Ok "Restored $restoredCount runtime dir(s) from backup"
    }
    # Clean up runtime backup
    Remove-Item $runtimeBackupDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ============================================================
# Step 7.8: Restart background services
# ============================================================

if (-not $DryRun) {
    # Migrate task prompts -- fix paths like "todays daily log" -> explicit memory/DailyLogs/ path
    $tasksDir = Join-Path $ProjectRoot "skills" "task-scheduler" "tasks"
    if (Test-Path $tasksDir) {
        $promptFixes = @{
            "daily-memory-maintenance" = @{
                old = "Write a brief entry in todays daily log noting the maintenance"
                new = "Write a brief entry in todays daily log at memory/DailyLogs/YYYY-MM-DD.md (where YYYY-MM-DD is todays date) noting the maintenance"
            }
            "weekly-qmd-reindex" = @{
                old = "Write a brief entry in todays daily log noting the re-index"
                new = "Write a brief entry in todays daily log at memory/DailyLogs/YYYY-MM-DD.md (where YYYY-MM-DD is todays date) noting the re-index"
            }
        }
        foreach ($taskId in $promptFixes.Keys) {
            $taskFile = Join-Path $tasksDir "task-$taskId.json"
            if (Test-Path $taskFile) {
                try {
                    $task = Get-Content $taskFile -Raw | ConvertFrom-Json
                    $fix = $promptFixes[$taskId]
                    if ($task.prompt -and $task.prompt.Contains($fix.old)) {
                        $task.prompt = $task.prompt.Replace($fix.old, $fix.new)
                        $task.updated_at = (Get-Date).ToUniversalTime().ToString("o")
                        $task | ConvertTo-Json -Depth 5 | Set-Content $taskFile
                        Write-Ok "Migrated task prompt: $taskId (daily log path fix)"
                    }
                } catch { }
            }
        }
    }

    # Recalculate stale next_run timestamps in task definitions
    $tasksDir = Join-Path $ProjectRoot "skills" "task-scheduler" "tasks"
    if (Test-Path $tasksDir) {
        $now = Get-Date
        $taskFiles = Get-ChildItem $tasksDir -Filter "*.json" -ErrorAction SilentlyContinue
        foreach ($tf in $taskFiles) {
            try {
                $task = Get-Content $tf.FullName -Raw | ConvertFrom-Json
                if ($task.next_run) {
                    $nextRun = [DateTime]::Parse($task.next_run)
                    if ($nextRun -lt $now) {
                        Write-Warn "Task '$($task.name)' has stale next_run ($($task.next_run)) -- scheduler will recalculate on restart"
                    }
                }
            } catch { }
        }
    }

    # Warn about tasks stuck in error_paused state
    if (Test-Path $tasksDir) {
        $errorTasks = @()
        foreach ($tf in (Get-ChildItem $tasksDir -Filter "*.json" -ErrorAction SilentlyContinue)) {
            try {
                $task = Get-Content $tf.FullName -Raw | ConvertFrom-Json
                if ($task.status -eq "error_paused") {
                    $errorTasks += [PSCustomObject]@{ Name = $task.name; ErrorCount = $task.error_count; File = $tf.Name }
                }
            } catch { }
        }
        if ($errorTasks.Count -gt 0) {
            Write-Warn "$($errorTasks.Count) scheduled task(s) in error_paused state:"
            foreach ($et in $errorTasks) {
                Write-Host "    - $($et.Name) (error_count: $($et.ErrorCount)) -- edit $($et.File) to set status=active and error_count=0" -ForegroundColor Yellow
            }
        }
    }

    # Restart task scheduler if it was running before upgrade
    if ($schedulerWasRunning) {
        $setupScheduler = Join-Path $ProjectRoot "scripts" "setup-scheduler.ps1"
        if (Test-Path $setupScheduler) {
            Write-Step "Restarting task scheduler..."
            try {
                $schedulerOutput = & $setupScheduler 2>&1
                if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
                    Write-Warn "Scheduler setup exited with code $LASTEXITCODE`n$schedulerOutput"
                } else {
                    Write-Ok "Task scheduler restarted"
                }
            } catch {
                Write-Warn "Could not restart scheduler: $_`nRun manually: powershell scripts/setup-scheduler.ps1"
            }
        }
    }

    # Verify task scheduler is actually running after restart
    if ($schedulerWasRunning) {
        Start-Sleep -Seconds 2
        $schedulerPidFile = Join-Path $ProjectRoot "skills" "task-scheduler" "scheduler.pid"
        if (Test-Path $schedulerPidFile) {
            $newPid = (Get-Content $schedulerPidFile -Raw).Trim()
            if ($newPid -match '^\d+$') {
                $proc = Get-Process -Id ([int]$newPid) -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Ok "Task scheduler verified running (PID $newPid)"
                } else {
                    Write-Warn "Task scheduler PID $newPid is not alive -- scheduler may have failed to start"
                }
            }
        } else {
            Write-Warn "scheduler.pid not found after restart -- scheduler may have failed to start"
        }
    }

    # Ensure Teams Python dependencies are installed (fixes #183)
    $teamsReqs = Join-Path $ProjectRoot "skills" "teams" "requirements.txt"
    if (Test-Path $teamsReqs) {
        $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
        if ($pipCmd) {
            Write-Step "Verifying Teams Python dependencies..."
            try {
                $pipCheck = pip install --disable-pip-version-check --dry-run -r $teamsReqs 2>&1
                $needsInstall = ($pipCheck | Select-String "Would install" -Quiet) -eq $true
                if ($needsInstall) {
                    pip install --disable-pip-version-check -r $teamsReqs 2>&1 | Out-Host
                    if ($LASTEXITCODE -eq 0) { Write-Ok "Teams Python dependencies installed" }
                    else { Write-Warn "Teams pip install had issues -- check output above" }
                } else {
                    Write-Ok "Teams Python dependencies up to date"
                }
            } catch {
                Write-Warn "Could not verify Teams Python dependencies: $_"
            }
        } else {
            Write-Warn "pip not available -- skipping Teams Python dependency check"
        }
    }

    # Restart Teams monitor if it was running before upgrade
    if ($monitorWasRunning) {
        $teamsDir = Join-Path $ProjectRoot "skills" "teams"
        $serviceScript = Join-Path $teamsDir "scripts" "monitor" "service.py"
        if (Test-Path $serviceScript) {
            Write-Step "Restarting Teams monitor..."
            try {
                $startArgs = @("-m", "scripts.monitor.service", "start")
                Start-Process -FilePath "python" -ArgumentList $startArgs -WorkingDirectory $teamsDir -WindowStyle Hidden
                Start-Sleep -Seconds 2
                $newPidFile = Join-Path $teamsDir "monitor" "monitor.pid"
                if (-not (Test-Path $newPidFile)) {
                    $newPidFile = Join-Path $teamsDir "monitor.pid"
                }
                if (-not (Test-Path $newPidFile)) {
                    $newPidFile = Join-Path $teamsDir "scripts" "monitor" "monitor.pid"
                }
                if (Test-Path $newPidFile) {
                    Write-Ok "Teams monitor restarted"
                } else {
                    Write-Warn "Teams monitor may not have started -- check manually"
                }
            } catch {
                Write-Warn "Could not restart Teams monitor: $_"
            }
        }
    }

    if (-not $schedulerWasRunning -and -not $monitorWasRunning) {
        Write-Ok "No services to restart"
    }
}

# ============================================================
# Optional tools -- offer to install if missing
# ============================================================

if (-not $DryRun) {
    # PowerShell 7 (pwsh) -- required by task scheduler since v1.0.7
    $pwshInstalled = $null -ne (Get-Command pwsh -ErrorAction SilentlyContinue)
    if ($pwshInstalled) {
        Write-Ok "PowerShell 7 (pwsh) already installed"
    } elseif ($Force) {
        Write-Step "PowerShell 7 not found -- installing via winget..."
        $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
        if ($wingetAvailable) {
            winget install Microsoft.PowerShell --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
            # Add to PATH for this session
            $pwsh7Path = "${env:ProgramFiles}\PowerShell\7"
            if ((Test-Path $pwsh7Path) -and ($env:Path -notlike "*$pwsh7Path*")) {
                $env:Path += ";$pwsh7Path"
            }
            if (Get-Command pwsh -ErrorAction SilentlyContinue) { Write-Ok "PowerShell 7 installed" }
            else { Write-Warn "PowerShell 7 install may have had issues -- check output above" }
        } else {
            Write-Warn "winget not found -- install PowerShell 7 manually: https://aka.ms/install-powershell"
        }
    } else {
        Write-Warn "PowerShell 7 (pwsh) not found. The task scheduler requires pwsh for best compatibility."
        $installPwsh = Read-Host "  Install PowerShell 7? [Y/n]"
        if ($installPwsh -notmatch '^[Nn]') {
            $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
            if ($wingetAvailable) {
                Write-Step "Installing PowerShell 7..."
                winget install Microsoft.PowerShell --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
                $pwsh7Path = "${env:ProgramFiles}\PowerShell\7"
                if ((Test-Path $pwsh7Path) -and ($env:Path -notlike "*$pwsh7Path*")) {
                    $env:Path += ";$pwsh7Path"
                }
                if (Get-Command pwsh -ErrorAction SilentlyContinue) { Write-Ok "PowerShell 7 installed" }
                else { Write-Warn "PowerShell 7 install may have had issues -- check output above" }
            } else {
                Write-Warn "winget not found -- install PowerShell 7 manually: https://aka.ms/install-powershell"
            }
        } else {
            Write-Step "Skipping PowerShell 7 (run 'winget install Microsoft.PowerShell' later)"
        }
    }

    # Handy (offline speech-to-text via Whisper) -- added in v1.0.4
    $handyInstalled = $null -ne (Get-Command handy -ErrorAction SilentlyContinue)
    if (-not $handyInstalled) {
        $handyPaths = @(
            "$env:LOCALAPPDATA\Programs\Handy\Handy.exe",
            "$env:LOCALAPPDATA\Handy\handy.exe",
            "$env:ProgramFiles\Handy\Handy.exe"
        )
        foreach ($hp in $handyPaths) {
            if (Test-Path $hp) { $handyInstalled = $true; break }
        }
    }
    if ($handyInstalled) {
        Write-Ok "Handy (speech-to-text) already installed"
    } elseif ($Force) {
        Write-Step "Skipping Handy in -Force mode (run 'winget install cjpais.Handy' later if desired)"
    } else {
        $installHandy = Read-Host "  Install Handy? (offline speech-to-text, uses Whisper) [y/N]"
        if ($installHandy -match '^[Yy]') {
            $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
            if ($wingetAvailable) {
                Write-Step "Installing Handy..."
                winget install cjpais.Handy --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
                if ($LASTEXITCODE -eq 0) { Write-Ok "Handy installed" }
                else { Write-Warn "Handy install may have had issues -- check output above" }
            } else {
                Write-Warn "winget not found -- download Handy manually from https://github.com/cjpais/handy/releases"
            }
        } else {
            Write-Step "Skipping Handy (run 'winget install cjpais.Handy' later if desired)"
        }
    }
}

# ============================================================
# Cleanup & summary
# ============================================================

if (-not $DryRun) {
    # Clean up backup directory (keep template-changes.md if it exists)
    foreach ($file in $backedUp) {
        $backupPath = Join-Path $backupDir $file
        Remove-Item $backupPath -ErrorAction SilentlyContinue
    }
    # Remove backup dir if empty (but keep if template-changes.md exists)
    $remaining = Get-ChildItem $backupDir -ErrorAction SilentlyContinue
    if (-not $remaining) {
        Remove-Item $backupDir -ErrorAction SilentlyContinue
    }

    # Stamp agencycowork.json with current version
    $versionFile = Join-Path $ProjectRoot "agencycowork.json"
    $stampVersion = "unknown"
    # Try to read version from ui/package.json (matches desktop app versioning)
    $uiPkgPath = Join-Path $ProjectRoot "ui" "package.json"
    if (Test-Path $uiPkgPath) {
        try {
            $pkgJson = Get-Content $uiPkgPath -Raw | ConvertFrom-Json
            if ($pkgJson.version) { $stampVersion = $pkgJson.version }
        } catch { }
    }
    $stamp = @{
        version   = $stampVersion
        updatedAt = (Get-Date -Format "o")
        installedVia = "update.ps1"
    }
    # Merge with existing agencycowork.json if present
    if (Test-Path $versionFile) {
        try {
            $existing = Get-Content $versionFile -Raw | ConvertFrom-Json
            if ($existing.createdAt) { $stamp["createdAt"] = $existing.createdAt }
            if ($existing.orgRepoUrl) { $stamp["orgRepoUrl"] = $existing.orgRepoUrl }
        } catch { }
    }
    if (-not $stamp.ContainsKey("createdAt")) { $stamp["createdAt"] = $stamp["updatedAt"] }
    $stamp | ConvertTo-Json -Depth 4 | Set-Content $versionFile -Encoding UTF8
    Write-Ok "Stamped agencycowork.json (v$stampVersion)"
}

Write-Banner "Update Complete"

# R4: Post-install verification -- catch common breakage immediately
if (-not $DryRun) {
    Write-Step "Running post-install verification..."
    $verifyFails = @()

    # Check QMD CLI
    $qmdCheck = Get-Command qmd -ErrorAction SilentlyContinue
    if ($qmdCheck) {
        try {
            $qmdVer = qmd --version 2>&1
            Write-Ok "QMD CLI: $qmdVer"
        } catch {
            $verifyFails += "QMD CLI failed: $_"
        }
    }

    # Check embedding provider
    $embedScript = Join-Path $ProjectRoot "skills" "qmd-memory" "scripts" "azure-embed.py"
    if (Test-Path $embedScript) {
        try {
            python $embedScript --test 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Embedding provider: connected"
            } else {
                $verifyFails += "Embedding provider test failed (exit code $LASTEXITCODE)"
            }
        } catch {
            $verifyFails += "Embedding provider test error: $_"
        }
    }

    if ($verifyFails.Count -gt 0) {
        Write-Warn "Post-install verification found $($verifyFails.Count) issue(s):"
        foreach ($f in $verifyFails) {
            Write-Host "    - $f" -ForegroundColor DarkYellow
        }
        Write-Host ""
    }
}

Write-Host "  Protected files ($($PersonalizedFiles.Count) via $(if ($usingManifest) { '.update-preserve manifest' } else { 'default list' })):" -ForegroundColor Green
foreach ($file in $PersonalizedFiles) {
    $fullPath = Join-Path $ProjectRoot $file
    if (Test-Path $fullPath) {
        Write-Host "    + $file" -ForegroundColor DarkGreen
    } else {
        Write-Host "    - $file [not found]" -ForegroundColor DarkYellow
    }
}
Write-Host ""

if (-not $usingManifest) {
    Write-Warn "TIP: Create .update-preserve in your project root to protect org-specific files."
    Write-Host "    See the template in the upstream repo or run: agency copilot" -ForegroundColor Gray
    Write-Host '    and ask "Help me set up .update-preserve for my org-specific files"' -ForegroundColor Gray
    Write-Host ""
}

if ($templatesChanged.Count -gt 0) {
    Write-Host "  ACTION NEEDED: Review upstream template changes." -ForegroundColor Yellow
    Write-Host "  See: .update-backup/template-changes.md" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Ask your AI coworker:" -ForegroundColor White
    Write-Host '    "Read .update-backup/template-changes.md and integrate the' -ForegroundColor White
    Write-Host '     upstream changes into my CLAUDE.md and AGENTS.md while' -ForegroundColor White
    Write-Host '     preserving my customizations."' -ForegroundColor White
    Write-Host ""
}

if ($didMigrateOneDrive) {
    Write-Host "  OneDrive migration: " -ForegroundColor Green -NoNewline
    Write-Host "COMPLETE" -ForegroundColor Cyan
    Write-Host "    memory/ is now cloud-synced via NTFS junction" -ForegroundColor DarkGreen
    Write-Host ""
}

if ($schedulerWasRunning -or $monitorWasRunning) {
    Write-Host "  Background services:" -ForegroundColor Green
    if ($schedulerWasRunning) { Write-Host "    Task scheduler: restarted" -ForegroundColor DarkGreen }
    if ($monitorWasRunning)   { Write-Host "    Teams monitor:  restarted" -ForegroundColor DarkGreen }
    Write-Host ""
}

Write-Host "  Next steps:" -ForegroundColor Gray
Write-Host "    1. Start a new Copilot session to pick up any new features" -ForegroundColor White
Write-Host "    2. Run /skills to verify all skills are loaded" -ForegroundColor White
if ($templatesChanged.Count -gt 0) {
    Write-Host "    3. Ask the agent to integrate template changes (see above)" -ForegroundColor White
}
Write-Host ""
