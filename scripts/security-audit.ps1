# security-audit.ps1 -- Check for common security issues in the Agency Cowork workspace
# Usage: powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1
#
# Run periodically to detect:
#   - Secrets in tracked files
#   - Unexpected changes to identity files (CLAUDE.md, MEMORY.md)
#   - Suspicious scheduled tasks
#   - Permission issues

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Issues = @()
$Warnings = @()

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Agency Cowork -- Security Audit" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. Check for secrets in tracked files ---

Write-Host "[1/6] Scanning tracked files for secrets..." -ForegroundColor Yellow

$secretPatterns = @(
    @{ Pattern = 'AZURE_OPENAI_API_KEY=(?!your-api-key-here)'; Desc = "Azure OpenAI API key" },
    @{ Pattern = 'Bearer [A-Za-z0-9\-._~+/]{20,}';            Desc = "Bearer token" },
    @{ Pattern = 'eyJ[A-Za-z0-9\-_]{20,}';                     Desc = "JWT token" },
    @{ Pattern = '-----BEGIN .* KEY-----';                      Desc = "PEM private key" },
    @{ Pattern = 'password\s*[:=]\s*[^\s]{8,}';                 Desc = "Hardcoded password" }
)

$trackedFiles = git -C $ProjectRoot ls-files 2>$null
foreach ($file in $trackedFiles) {
    $fullPath = Join-Path $ProjectRoot $file
    if (-not (Test-Path $fullPath) -or $file -match '\.(gitkeep|png|jpg|gif)$') { continue }

    # Skip .env.example (it has placeholder patterns by design)
    if ($file -eq ".env.example") { continue }
    # Skip docs, security scripts, setup scripts, and test files that contain example patterns by design
    if ($file -match '^scripts[/\\](pre-commit|security-audit|setup)') { continue }
    if ($file -match '^(installation|threatmodel|TESTING-).*\.md$') { continue }
    if ($file -match '^tests[/\\]') { continue }
    if ($file -match '^ui[/\\]build\.md$') { continue }
    if ($file -match '^skills[/\\].*[/\\]README\.md$') { continue }

    try {
        $content = Get-Content $fullPath -Raw -ErrorAction SilentlyContinue
        if (-not $content) { continue }

        foreach ($sp in $secretPatterns) {
            if ($content -match $sp.Pattern) {
                $Issues += "SECRET: $($sp.Desc) found in $file"
            }
        }
    } catch { }
}

if (($Issues | Where-Object { $_ -like "SECRET:*" }).Count -eq 0) {
    Write-Host "  [PASS] No secrets found in tracked files." -ForegroundColor Green
} else {
    foreach ($issue in ($Issues | Where-Object { $_ -like "SECRET:*" })) {
        Write-Host "  [FAIL] $issue" -ForegroundColor Red
    }
}

# --- 2. Check .env file status ---

Write-Host ""
Write-Host "[2/6] Checking environment files..." -ForegroundColor Yellow

$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    $tracked = git -C $ProjectRoot ls-files --error-unmatch ".env" 2>$null
    if ($tracked) {
        $Issues += "CRITICAL: .env file is tracked by git -- it should be gitignored"
        Write-Host "  [FAIL] .env file is tracked by git!" -ForegroundColor Red
    } else {
        Write-Host "  [PASS] .env exists but is gitignored (correct)." -ForegroundColor Green
    }
} else {
    Write-Host "  [PASS] No .env file present." -ForegroundColor Green
}

# --- 3. Check identity file integrity ---

Write-Host ""
Write-Host "[3/6] Checking identity file integrity (CLAUDE.md, MEMORY.md)..." -ForegroundColor Yellow

$identityFiles = @("CLAUDE.md", "memory\MEMORY.md")
foreach ($file in $identityFiles) {
    $fullPath = Join-Path $ProjectRoot $file
    if (-not (Test-Path $fullPath)) {
        $Warnings += "MISSING: $file not found"
        Write-Host "  [WARN] $file not found" -ForegroundColor DarkYellow
        continue
    }

    $diff = git -C $ProjectRoot diff -- $file 2>$null
    if ($diff) {
        $Warnings += "MODIFIED: $file has uncommitted changes -- review for tampering"
        Write-Host "  [WARN] $file has uncommitted changes -- review with: git diff $file" -ForegroundColor DarkYellow
    } else {
        Write-Host "  [PASS] $file matches last commit." -ForegroundColor Green
    }
}

# --- 4. Audit scheduled tasks ---

Write-Host ""
Write-Host "[4/6] Auditing scheduled tasks..." -ForegroundColor Yellow

$tasksDir = Join-Path $ProjectRoot "skills\task-scheduler\tasks"
$taskFiles = Get-ChildItem -Path $tasksDir -Filter "task-*.json" -ErrorAction SilentlyContinue

if (-not $taskFiles -or $taskFiles.Count -eq 0) {
    Write-Host "  [PASS] No scheduled tasks found." -ForegroundColor Green
} else {
    Write-Host "  Found $($taskFiles.Count) task(s):" -ForegroundColor White

    $dangerousPatterns = @(
        @{ Pattern = 'forward.*email';     Desc = "Email forwarding" },
        @{ Pattern = 'send.*email.*to';    Desc = "Sending email to specific recipient" },
        @{ Pattern = 'delete';             Desc = "Deletion operation" },
        @{ Pattern = 'share.*file';        Desc = "File sharing" },
        @{ Pattern = 'post.*channel';      Desc = "Channel posting" },
        @{ Pattern = 'download.*from';     Desc = "File download" }
    )

    foreach ($file in $taskFiles) {
        try {
            $task = Get-Content $file.FullName -Raw | ConvertFrom-Json
            $statusColor = if ($task.status -eq "active") { "White" } else { "DarkGray" }
            Write-Host "    [$($task.status)] $($task.id): $($task.prompt)" -ForegroundColor $statusColor

            if ($task.status -eq "active") {
                foreach ($dp in $dangerousPatterns) {
                    if ($task.prompt -match $dp.Pattern) {
                        $Warnings += "TASK: '$($task.id)' contains potentially risky prompt ($($dp.Desc))"
                        Write-Host "      [WARN] Potentially risky: $($dp.Desc)" -ForegroundColor DarkYellow
                    }
                }
            }
        } catch {
            $Warnings += "TASK: Failed to parse $($file.Name)"
            Write-Host "    [FAIL] Failed to parse: $($file.Name)" -ForegroundColor Red
        }
    }
}

# --- 5. Check MCP config ---

Write-Host ""
Write-Host "[5/6] Checking MCP configuration..." -ForegroundColor Yellow

# Check .mcp.json (primary) then global mcp-config.json (fallback)
$wsConfigPath = Join-Path (Get-Location) ".mcp.json"
$legacyConfigPath = Join-Path (Get-Location) ".vscode\mcp.json"
$globalConfigPath = Join-Path $env:USERPROFILE ".copilot\mcp-config.json"
$mcpConfigPath = if (Test-Path $wsConfigPath) { $wsConfigPath } elseif (Test-Path $legacyConfigPath) { $legacyConfigPath } elseif (Test-Path $globalConfigPath) { $globalConfigPath } else { $null }

if ($mcpConfigPath) {
    try {
        $mcpContent = Get-Content $mcpConfigPath -Raw | ConvertFrom-Json
        # Support both "mcpServers" (.mcp.json) and "servers" (legacy .vscode/mcp.json)
        $sObj = if ($mcpContent.PSObject.Properties["mcpServers"]) { $mcpContent.mcpServers } elseif ($mcpContent.PSObject.Properties["servers"]) { $mcpContent.servers } else { $null }
        if ($sObj) {
            $servers = $sObj.PSObject.Properties
            foreach ($server in $servers) {
                $url = $server.Value.url
                if ($url) {
                    if ($url -match 'agent365\.svc\.cloud\.microsoft') {
                        Write-Host "  [PASS] $($server.Name): Official Microsoft endpoint" -ForegroundColor Green
                    } else {
                        $Warnings += "MCP: $($server.Name) points to non-Microsoft URL: $url"
                        Write-Host "  [WARN] $($server.Name): Non-standard URL: $url" -ForegroundColor DarkYellow
                    }
                } elseif ($server.Value.command) {
                    Write-Host "  [PASS] $($server.Name): Local command ($($server.Value.command))" -ForegroundColor Green
                }
            }
        } else {
            Write-Host "  [INFO] MCP config has no servers section" -ForegroundColor DarkGray
        }
    } catch {
        $Warnings += "MCP: Failed to parse $(Split-Path -Leaf $mcpConfigPath)"
        Write-Host "  [FAIL] Failed to parse $(Split-Path -Leaf $mcpConfigPath)" -ForegroundColor Red
    }
} else {
    Write-Host "  [INFO] No MCP config found (checked .mcp.json, .vscode/mcp.json, and ~/.copilot/mcp-config.json)" -ForegroundColor DarkGray
}

# --- 6. Check file system ---

Write-Host ""
Write-Host "[6/6] Checking file system..." -ForegroundColor Yellow

$unexpectedExts = @("*.exe", "*.dll", "*.bat", "*.cmd", "*.vbs")
$suspiciousFiles = @()
foreach ($ext in $unexpectedExts) {
    $found = Get-ChildItem -Path $ProjectRoot -Filter $ext -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\node_modules\\|\\\.git\\|\\\.venv\\' }
    $suspiciousFiles += $found
}

if ($suspiciousFiles.Count -eq 0) {
    Write-Host "  [PASS] No unexpected executable files found." -ForegroundColor Green
} else {
    foreach ($sf in $suspiciousFiles) {
        $Warnings += "FILE: Unexpected executable: $($sf.FullName)"
        Write-Host "  [WARN] Unexpected executable: $($sf.FullName)" -ForegroundColor DarkYellow
    }
}

# --- Summary ---

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Audit Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$issueCount = $Issues.Count
$warnCount = $Warnings.Count

if ($issueCount -eq 0 -and $warnCount -eq 0) {
    Write-Host ""
    Write-Host "  [PASS] All checks passed. No issues found." -ForegroundColor Green
    Write-Host ""
} else {
    if ($issueCount -gt 0) {
        Write-Host ""
        Write-Host "  $issueCount critical issue(s):" -ForegroundColor Red
        foreach ($i in $Issues) { Write-Host "     - $i" -ForegroundColor Red }
    }
    if ($warnCount -gt 0) {
        Write-Host ""
        Write-Host "  $warnCount warning(s):" -ForegroundColor DarkYellow
        foreach ($w in $Warnings) { Write-Host "     - $w" -ForegroundColor DarkYellow }
    }
    Write-Host ""
}

if ($issueCount -gt 0) { exit 1 } else { exit 0 }
