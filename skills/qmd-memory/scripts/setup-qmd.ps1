# setup-qmd.ps1 - Install and configure QMD for Agency Cowork memory search
# Usage: powershell -ExecutionPolicy Bypass -File setup-qmd.ps1
#
# This script:
# 1. Installs QMD globally via npm
# 2. Creates collections for the Agency Cowork memory directories
# 3. Adds context descriptions to each collection
# 4. Runs initial indexing (text + embeddings)
# 5. Verifies with a test search

param(
    [switch]$SkipInstall,
    [switch]$SkipEmbed,
    [switch]$UseAzureEmbed,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.."))
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== QMD Setup for Agency Cowork ===" -ForegroundColor Cyan

# --- Step 1: Install QMD ---

if (-not $SkipInstall) {
    Write-Host "`n[1/5] Installing QMD globally..." -ForegroundColor Yellow
    npm install -g @tobilu/qmd
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install QMD. Ensure Node.js 22+ and npm are available."
        exit 1
    }

    # R1: On Windows, npm generates wrappers that reference /bin/sh (Unix-only).
    # Patch them to invoke Node directly so qmd works from PowerShell and cmd.
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        $npmGlobal = (npm config get prefix).Trim()
        $qmdJs = Join-Path $npmGlobal "node_modules" "@tobilu" "qmd" "dist" "cli" "qmd.js"
        if (Test-Path $qmdJs) {
            $ps1Wrapper = Join-Path $npmGlobal "qmd.ps1"
            @"
#!/usr/bin/env pwsh
`$ret=0
if (`$MyInvocation.ExpectingInput) { `$input | & node "$qmdJs" `$args }
else { & node "$qmdJs" `$args }
`$ret=`$LASTEXITCODE; exit `$ret
"@ | Set-Content $ps1Wrapper -Force -Encoding UTF8

            $cmdWrapper = Join-Path $npmGlobal "qmd.cmd"
            "@ECHO off`r`nnode `"$qmdJs`" %*" | Set-Content $cmdWrapper -Force -Encoding ASCII

            Write-Host "  Patched Windows wrappers (qmd.ps1, qmd.cmd)" -ForegroundColor Green
        } else {
            Write-Warning "Could not find qmd.js at $qmdJs -- wrappers not patched"
        }
    }
}

# Verify qmd is available
$qmdPath = Get-Command qmd -ErrorAction SilentlyContinue
if (-not $qmdPath) {
    Write-Error "qmd not found on PATH. Ensure npm global bin directory is in PATH."
    exit 1
}

Write-Host "  QMD installed: $($qmdPath.Source)" -ForegroundColor Green

# --- Step 2: Create collections ---

Write-Host "`n[2/5] Creating collections..." -ForegroundColor Yellow

$collections = @(
    @{ Name = "memory-root";    Path = "$ProjectRoot\memory";                     Mask = "*.md" },
    @{ Name = "knowledgebase";  Path = "$ProjectRoot\memory\Knowledgebase";       Mask = "**/*.md" },
    @{ Name = "weekly-reports"; Path = "$ProjectRoot\memory\WeeklyReports";       Mask = "**/*.md" },
    @{ Name = "skills-docs";   Path = "$ProjectRoot\skills";                      Mask = "**/SKILL.md" }
)

foreach ($col in $collections) {
    if (Test-Path $col.Path) {
        Write-Host "  Adding collection: $($col.Name) -> $($col.Path)"
        qmd collection add $col.Path --name $col.Name --mask $col.Mask 2>&1 | Out-Null
    } else {
        Write-Host "  Skipping $($col.Name) (path not found: $($col.Path))" -ForegroundColor DarkYellow
    }
}

# --- Step 3: Add context descriptions ---

Write-Host "`n[3/5] Adding context descriptions..." -ForegroundColor Yellow

$contexts = @(
    @{ Path = "qmd://memory-root";    Desc = "Daily context logs for Agency Cowork - decisions, progress, blockers, next steps. Organized by date (YYYY-MM-DD.md)." },
    @{ Path = "qmd://knowledgebase";  Desc = "Long-term your program knowledge - specifications, executive reviews, PEC minutes, workstream notes, converted documents." },
    @{ Path = "qmd://weekly-reports"; Desc = "Executive weekly status reports per your program (program 200, program 300, program 400). 3-5 bullets plus expanded summaries." },
    @{ Path = "qmd://skills-docs";   Desc = "Skill definitions and workflows for Agency Cowork capabilities - send-email, teams, weekly-report, task-scheduler, etc." }
)

foreach ($ctx in $contexts) {
    Write-Host "  Context: $($ctx.Path)"
    qmd context add $ctx.Path $ctx.Desc 2>&1 | Out-Null
}

# --- Step 4: Index ---

Write-Host "`n[4/5] Running initial indexing..." -ForegroundColor Yellow

Write-Host "  Text indexing (qmd update)..."
qmd update
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Text indexing returned non-zero exit code"
}

if (-not $SkipEmbed) {
    # R2: Use Python embedding pipeline (respects agentconfig.json -> memory.embedding.provider)
    # instead of qmd embed (which tries to build llama.cpp with Vulkan/CMake)
    $embedScript = Join-Path $PSScriptRoot "azure-embed.py"
    if (Test-Path $embedScript) {
        Write-Host "  Generating embeddings via Python pipeline (reads provider from agentconfig.json)..."
        python $embedScript --test 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            python $embedScript
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Embedding generation returned non-zero exit code"
            }
        } else {
            Write-Warning "Embedding provider test failed. Falling back to qmd embed..."
            Write-Host "  Generating embeddings (qmd embed) - this may take a few minutes on first run..."
            qmd embed
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Embedding generation returned non-zero exit code"
            }
        }
    } else {
        Write-Host "  azure-embed.py not found, falling back to qmd embed..."
        qmd embed
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Embedding generation returned non-zero exit code"
        }
    }
} else {
    Write-Host "  Skipping embeddings (use -SkipEmbed to skip)"
}

# --- Step 4b: Optional Azure OpenAI Embeddings ---

if ($UseAzureEmbed) {
    Write-Host "`n[4b] Installing Azure embedding dependencies..." -ForegroundColor Yellow
    pip install openai python-dotenv tiktoken --quiet 2>&1 | Out-Null
    Write-Host "  Installed: openai, python-dotenv, tiktoken"

    Write-Host "  Generating Azure OpenAI embeddings..." -ForegroundColor Yellow
    $azureScript = Join-Path $PSScriptRoot "azure-embed.py"
    if (Test-Path $azureScript) {
        Write-Host "  Testing Azure OpenAI connectivity..."
        python $azureScript --test
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Running Azure OpenAI embedding for all collections..."
            python $azureScript
        } else {
            Write-Warning "Azure OpenAI test failed. Check .env (AZURE_OPENAI_API_KEY) and agentconfig.json."
        }
    } else {
        Write-Warning "azure-embed.py not found at $azureScript"
    }
}

# --- Step 5: Verify ---

Write-Host "`n[5/5] Verifying installation..." -ForegroundColor Yellow

Write-Host "  Index status:"
qmd status

Write-Host "`n  Test search: 'your program status'"
qmd search "your program status" -n 3

Write-Host "`n=== QMD Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Get started:" -ForegroundColor Yellow
Write-Host ""
Write-Host "    cd $ProjectRoot" -ForegroundColor Cyan
Write-Host "    copilot" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Once running, say " -ForegroundColor White -NoNewline
Write-Host '"Personalize my agent"' -ForegroundColor Cyan -NoNewline
Write-Host " to run the deep-personalization" -ForegroundColor White
Write-Host "  skill, which will configure domain knowledge, contacts, and preferences." -ForegroundColor White
Write-Host ""
Write-Host "  Additional setup:" -ForegroundColor Gray
Write-Host "    - Add QMD MCP server to mcp-config.json (use full path):" -ForegroundColor Gray
Write-Host "      `"qmd`": { `"command`": `"$($qmdPath.Source)`", `"args`": [`"mcp`"] }" -ForegroundColor Gray
Write-Host "    - Try: " -ForegroundColor Gray -NoNewline
Write-Host '"Search my memory for decisions about the project milestone"' -ForegroundColor Gray
Write-Host ""
Write-Host "  Optional - Azure OpenAI Embeddings:" -ForegroundColor Gray
Write-Host "    pip install openai python-dotenv tiktoken" -ForegroundColor Gray
Write-Host "    Copy .env.example to .env and set AZURE_OPENAI_API_KEY" -ForegroundColor Gray
Write-Host "    In agentconfig.json, set memory.embedding.provider to `"azure_openai`"" -ForegroundColor Gray
Write-Host "    Run: python skills/qmd-memory/scripts/azure-embed.py --test" -ForegroundColor Gray
Write-Host ""
