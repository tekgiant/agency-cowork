# memory-flush.ps1 - Re-index QMD text and refresh Azure OpenAI embeddings
# Usage: powershell -ExecutionPolicy Bypass -File skills/qmd-memory/scripts/memory-flush.ps1
#
# This script runs the deterministic re-indexing steps of a memory flush:
# 1. qmd update (fast text re-index)
# 2. azure-embed.py (Azure OpenAI embeddings, if configured)
#
# The context-aware part (reviewing session, writing daily logs, updating MEMORY.md)
# is handled by the agent before calling this script. See qmd-memory SKILL.md
# "Memory Flush" section for the full workflow.

param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")),
    [switch]$SkipEmbeddings,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Message, [string]$Color = "White")
    if (-not $Quiet) {
        Write-Host "[$timestamp] $Message" -ForegroundColor $Color
    }
}

# --- Step 1: QMD text re-index ---

Write-Log "Memory Flush - starting re-index" "Cyan"

$qmdCliCandidates = @(
    (Join-Path $ProjectRoot "node_modules\@tobilu\qmd\dist\cli\qmd.js"),
    "C:\ProgramData\global-npm\node_modules\@tobilu\qmd\dist\cli\qmd.js"
)
$qmdPath = Get-Command qmd -ErrorAction SilentlyContinue
$qmdCliScript = $qmdCliCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$textIndexExitCode = 0

if ($qmdCliScript) {
    Write-Log "Running qmd update via CLI script..." "Yellow"
    node $qmdCliScript update 2>&1 | ForEach-Object {
        if (-not $Quiet) { Write-Host "  $_" }
    }
    $textIndexExitCode = $LASTEXITCODE
} elseif ($qmdPath) {
    Write-Log "Running qmd update (text re-index)..." "Yellow"
    qmd update 2>&1 | ForEach-Object {
        if (-not $Quiet) { Write-Host "  $_" }
    }
    $textIndexExitCode = $LASTEXITCODE
} else {
    Write-Log "ERROR: qmd not found on PATH and local CLI script is missing. Skipping text re-index." "Red"
}

if ($textIndexExitCode -eq 0) {
    Write-Log "Text re-index complete." "Green"
} elseif ($qmdPath -or $qmdCliScript) {
    Write-Log "WARNING: qmd update returned exit code $textIndexExitCode" "DarkYellow"
}

# --- Step 2: Azure OpenAI embeddings ---

if (-not $SkipEmbeddings) {
    $configFile = Join-Path $ProjectRoot "agentconfig.json"
    $azureEmbedScript = Join-Path $ScriptDir "azure-embed.py"

    $useAzure = $false
    if (Test-Path $configFile) {
        try {
            $config = Get-Content $configFile -Raw | ConvertFrom-Json
            $provider = $config.memory.embedding.provider
            if ($provider -eq "azure_openai") {
                $useAzure = $true
            }
        } catch {
            Write-Log "WARNING: Could not parse agentconfig.json - skipping Azure embeddings" "DarkYellow"
        }
    }

    if ($useAzure -and (Test-Path $azureEmbedScript)) {
        Write-Log "Running Azure OpenAI embedding generation..." "Yellow"
        python $azureEmbedScript 2>&1 | ForEach-Object {
            if (-not $Quiet) { Write-Host "  $_" }
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Azure embeddings complete." "Green"
        } else {
            Write-Log "WARNING: azure-embed.py returned exit code $LASTEXITCODE" "DarkYellow"
        }
    } elseif (-not $useAzure) {
        Write-Log "Azure embeddings not enabled (provider != azure_openai). Skipping." "Gray"
    } else {
        Write-Log "WARNING: azure-embed.py not found at $azureEmbedScript" "DarkYellow"
    }
} else {
    Write-Log "Skipping embeddings (--SkipEmbeddings flag)" "Gray"
}

# --- Done ---

Write-Log "Memory flush complete." "Cyan"
