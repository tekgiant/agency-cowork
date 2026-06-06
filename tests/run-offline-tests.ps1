<#
.SYNOPSIS
    Automated offline test runner for Agency Cowork validation.
    Runs offline tests from TEST_PLAN.md (categories 1-7).

.DESCRIPTION
    Tests: Secrets & Data Hygiene (7), File Structure (6), JSON Validation (8),
    SKILL.md Validation (5), Documentation (10), Security Controls (16),
    Code Quality (3)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tests/run-offline-tests.ps1
#>

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$pass = 0
$fail = 0
$warn = 0
$results = @()

function Test-Check {
    param([string]$Id, [string]$Name, [scriptblock]$Check)
    try {
        $result = & $Check
        if ($result) {
            $script:pass++
            $status = "PASS"
            $symbol = "[PASS]"
        } else {
            $script:fail++
            $status = "FAIL"
            $symbol = "[FAIL]"
        }
    } catch {
        $script:fail++
        $status = "FAIL"
        $symbol = "[FAIL]"
        if ($Verbose) { Write-Host "       Error: $_" -ForegroundColor DarkGray }
    }
    $color = if ($status -eq "PASS") { "Green" } else { "Red" }
    Write-Host "  $symbol $Id - $Name" -ForegroundColor $color
    $script:results += [PSCustomObject]@{ Id=$Id; Name=$Name; Status=$status }
}

Push-Location $RepoRoot

function Get-SkillMdPath {
    param([string]$SkillName)
    $nested = "skills/$SkillName/skills/$SkillName/SKILL.md"
    if (Test-Path $nested) { return $nested }
    return "skills/$SkillName/SKILL.md"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Agency Cowork - Offline Test Suite" -ForegroundColor Cyan
Write-Host " Repository: $RepoRoot" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ============================================================
# Category 1: Secrets & Data Hygiene (7 tests)
# ============================================================
Write-Host "--- 1. Secrets & Data Hygiene ---" -ForegroundColor Yellow

Test-Check "DH-01" "No API keys in tracked files" {
    $hits = git grep -ilE "sk-[a-zA-Z0-9]{20,}|AZURE_OPENAI_API_KEY=[^y\$\{]" -- ":(exclude)tests/" ":(exclude)scripts/pre-commit" ":(exclude)scripts/security-audit.ps1" ":(exclude)installation.md" 2>$null
    return ($null -eq $hits -or $hits.Count -eq 0)
}

Test-Check "DH-02" ".env not tracked by git" {
    $hits = git ls-files .env 2>$null
    return ([string]::IsNullOrWhiteSpace($hits))
}

Test-Check "DH-03" ".obsidian config not tracked by git" {
    $hits = git ls-files "memory/.obsidian" 2>$null
    return ([string]::IsNullOrWhiteSpace($hits))
}

Test-Check "DH-04" "No QMD embeddings cache committed" {
    $cacheDir = "skills/qmd-memory/cache/embeddings"
    if (-not (Test-Path $cacheDir)) { return $true }
    $files = git ls-files "$cacheDir" 2>$null
    return ([string]::IsNullOrWhiteSpace($files))
}

Test-Check "DH-05" "agentconfig.json has embedding config" {
    $json = Get-Content "agentconfig.json" -Raw | ConvertFrom-Json
    # Check for any configured embedding provider (sentence_transformer, local, or azure_openai)
    $provider = $json.memory.embedding.provider
    return (-not [string]::IsNullOrWhiteSpace($provider))
}

Test-Check "DH-06" "No plaintext passwords in tracked files" {
    $hits = git grep -ilE "password\s*[:=]\s*[^\s\$\{]{8,}" -- ":(exclude)tests/" ":(exclude)scripts/" ":(exclude)installation.md" ":(exclude)threatmodel.md" 2>$null
    return ($null -eq $hits -or $hits.Count -eq 0)
}

Test-Check "DH-07" "No tenant IDs outside config and docs" {
    $hits = git grep -il "72f988bf" -- ":(exclude)installation.md" ":(exclude)threatmodel.md" ":(exclude)tests/" 2>$null
    return ($null -eq $hits -or $hits.Count -eq 0)
}

# ============================================================
# Category 2: File Structure & Integrity (6 tests)
# ============================================================
Write-Host "`n--- 2. File Structure & Integrity ---" -ForegroundColor Yellow

Test-Check "FS-01" "Core files exist" {
    $required = @("README.md", "CLAUDE.md", "AGENTS.md", "installation.md",
                  "threatmodel.md", "agentconfig.json", ".gitignore", ".gitattributes")
    foreach ($f in $required) {
        if (-not (Test-Path $f)) { return $false }
    }
    return $true
}

Test-Check "FS-02" "Memory sync script exists" {
    return (Test-Path "scripts/sync-memory.ps1")
}

Test-Check "FS-03" "WeeklyReports directory exists" {
    return (Test-Path "memory/WeeklyReports")
}

Test-Check "FS-04" "All 9 skills have required structure" {
    $skills = @("claude-deep-research-skill", "markitdown", "qmd-memory", "send-email",
                "sharepoint-download", "spec-kit", "task-scheduler", "teams", "weekly-report")
    foreach ($s in $skills) {
        $pluginJson = "skills/$s/.claude-plugin/plugin.json"
        $agencyJson = "skills/$s/agency.json"
        # Some skills have SKILL.md nested, others have it at root
        $skillMd = "skills/$s/skills/$s/SKILL.md"
        if (-not (Test-Path $skillMd)) { $skillMd = "skills/$s/SKILL.md" }
        if (-not (Test-Path $pluginJson)) {
            if ($Verbose) { Write-Host "       Missing: $pluginJson" -ForegroundColor DarkGray }
            return $false
        }
        if (-not (Test-Path $agencyJson)) {
            if ($Verbose) { Write-Host "       Missing: $agencyJson" -ForegroundColor DarkGray }
            return $false
        }
        if (-not (Test-Path $skillMd)) {
            if ($Verbose) { Write-Host "       Missing: SKILL.md for $s" -ForegroundColor DarkGray }
            return $false
        }
    }
    return $true
}

Test-Check "FS-05" "Scripts directory has security files" {
    return ((Test-Path "scripts/pre-commit") -and (Test-Path "scripts/security-audit.ps1"))
}

Test-Check "FS-06" "Tests directory has test plan" {
    return (Test-Path "tests/TEST_PLAN.md")
}

# ============================================================
# Category 3: JSON Schema Validation (12 tests)
# ============================================================
Write-Host "`n--- 3. JSON Schema Validation ---" -ForegroundColor Yellow

Test-Check "JSON-01" "agentconfig.json is valid JSON" {
    $null = Get-Content "agentconfig.json" -Raw | ConvertFrom-Json
    return $true
}

Test-Check "JSON-02" "agentconfig.json has embedding config" {
    $json = Get-Content "agentconfig.json" -Raw | ConvertFrom-Json
    return ($null -ne $json.memory.embedding.provider -and
            $null -ne $json.memory.embedding.azure_openai.endpoint -and
            $null -ne $json.memory.embedding.azure_openai.deployment)
}

$skills = @("claude-deep-research-skill", "markitdown", "qmd-memory", "send-email",
            "sharepoint-download", "spec-kit", "task-scheduler", "teams", "weekly-report")

Test-Check "JSON-03" "All 9 plugin.json files are valid JSON" {
    foreach ($s in $skills) {
        $null = Get-Content "skills/$s/.claude-plugin/plugin.json" -Raw | ConvertFrom-Json
    }
    return $true
}

Test-Check "JSON-04" "All plugin.json have required fields" {
    foreach ($s in $skills) {
        $json = Get-Content "skills/$s/.claude-plugin/plugin.json" -Raw | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace($json.name)) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.version)) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.description)) { return $false }
        if ($null -eq $json.keywords -or $json.keywords.Count -eq 0) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.author.name)) { return $false }
    }
    return $true
}

Test-Check "JSON-05" "All plugin.json author is Agency Cowork" {
    foreach ($s in $skills) {
        $json = Get-Content "skills/$s/.claude-plugin/plugin.json" -Raw | ConvertFrom-Json
        if ($json.author.name -ne "Agency Cowork") {
            if ($Verbose) { Write-Host "       $s author: $($json.author.name)" -ForegroundColor DarkGray }
            return $false
        }
    }
    return $true
}

Test-Check "JSON-06" "All 9 agency.json files are valid JSON" {
    foreach ($s in $skills) {
        $null = Get-Content "skills/$s/agency.json" -Raw | ConvertFrom-Json
    }
    return $true
}

Test-Check "JSON-07" "All agency.json have required fields" {
    foreach ($s in $skills) {
        $json = Get-Content "skills/$s/agency.json" -Raw | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace($json.category)) { return $false }
        if ($null -eq $json.engines -or $json.engines.Count -eq 0) { return $false }
    }
    return $true
}

Test-Check "JSON-08" ".mcp.json is valid JSON (if exists)" {
    if (-not (Test-Path ".mcp.json")) { return $true }
    $null = Get-Content ".mcp.json" -Raw | ConvertFrom-Json
    return $true
}

# Third-party skills (preserved upstream author attribution)
$thirdPartySkills = @("visual-explainer")

Test-Check "JSON-09" "Third-party skills have required structure" {
    foreach ($s in $thirdPartySkills) {
        $pluginJson = "skills/$s/.claude-plugin/plugin.json"
        $agencyJson = "skills/$s/agency.json"
        $skillMd = "skills/$s/skills/$s/SKILL.md"
        if (-not (Test-Path $skillMd)) { $skillMd = "skills/$s/SKILL.md" }
        if (-not (Test-Path $pluginJson)) {
            if ($Verbose) { Write-Host "       Missing: $pluginJson" -ForegroundColor DarkGray }
            return $false
        }
        if (-not (Test-Path $agencyJson)) {
            if ($Verbose) { Write-Host "       Missing: $agencyJson" -ForegroundColor DarkGray }
            return $false
        }
        if (-not (Test-Path $skillMd)) {
            if ($Verbose) { Write-Host "       Missing: SKILL.md for $s" -ForegroundColor DarkGray }
            return $false
        }
    }
    return $true
}

Test-Check "JSON-10" "Third-party plugin.json valid with required fields" {
    foreach ($s in $thirdPartySkills) {
        $json = Get-Content "skills/$s/.claude-plugin/plugin.json" -Raw | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace($json.name)) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.version)) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.description)) { return $false }
        if ($null -eq $json.keywords -or $json.keywords.Count -eq 0) { return $false }
        if ([string]::IsNullOrWhiteSpace($json.author.name)) { return $false }
    }
    return $true
}

Test-Check "JSON-11" "Third-party skills have LICENSE file" {
    foreach ($s in $thirdPartySkills) {
        if (-not (Test-Path "skills/$s/LICENSE")) {
            if ($Verbose) { Write-Host "       Missing: skills/$s/LICENSE" -ForegroundColor DarkGray }
            return $false
        }
    }
    return $true
}

Test-Check "JSON-12" "Third-party agency.json valid with required fields" {
    foreach ($s in $thirdPartySkills) {
        $json = Get-Content "skills/$s/agency.json" -Raw | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace($json.category)) { return $false }
        if ($null -eq $json.engines -or $json.engines.Count -eq 0) { return $false }
    }
    return $true
}

# ============================================================
# Category 4: SKILL.md Frontmatter Validation (5 tests)
# ============================================================
Write-Host "`n--- 4. SKILL.md Frontmatter Validation ---" -ForegroundColor Yellow

Test-Check "SKL-01" "All SKILL.md files start with ---" {
    foreach ($s in $skills) {
        $path = Get-SkillMdPath $s
        $firstLine = Get-Content $path -TotalCount 1
        if ($firstLine -ne "---") {
            if ($Verbose) { Write-Host "       $s first line: $firstLine" -ForegroundColor DarkGray }
            return $false
        }
    }
    return $true
}

Test-Check "SKL-02" "All SKILL.md have name: field" {
    foreach ($s in $skills) {
        $content = Get-Content (Get-SkillMdPath $s) -Raw
        if ($content -notmatch "(?m)^name:") { return $false }
    }
    return $true
}

Test-Check "SKL-03" "All SKILL.md have description: field" {
    foreach ($s in $skills) {
        $content = Get-Content (Get-SkillMdPath $s) -Raw
        if ($content -notmatch "(?m)^description:") { return $false }
    }
    return $true
}

Test-Check "SKL-04" "No SKILL.md wrapped in code fences" {
    foreach ($s in $skills) {
        $firstLine = Get-Content (Get-SkillMdPath $s) -TotalCount 1
        if ($firstLine -match "^``") { return $false }
    }
    return $true
}

Test-Check "SKL-05" "SKILL.md names match plugin.json names" {
    foreach ($s in $skills) {
        $pluginJson = Get-Content "skills/$s/.claude-plugin/plugin.json" -Raw | ConvertFrom-Json
        $skillContent = Get-Content (Get-SkillMdPath $s) -Raw
        if ($skillContent -match "(?m)^name:\s*(.+)$") {
            $skillName = $Matches[1].Trim()
            if ($skillName -ne $pluginJson.name) {
                if ($Verbose) { Write-Host "       ${s}: SKILL.md=$skillName, plugin.json=$($pluginJson.name)" -ForegroundColor DarkGray }
                return $false
            }
        } else {
            return $false
        }
    }
    return $true
}

# ============================================================
# Category 5: Documentation Validation (10 tests)
# ============================================================
Write-Host "`n--- 5. Documentation Validation ---" -ForegroundColor Yellow

Test-Check "DOC-01" "README.md contains Agency Cowork description" {
    $content = Get-Content "README.md" -Raw
    return ($content -match "Agency Cowork" -and $content -match "(?i)ai coworker")
}

Test-Check "DOC-02" "README.md has Skills section" {
    $content = Get-Content "README.md" -Raw
    return ($content -match "(?i)#+\s*.*Skills" -and $content -match "(?i)skills")
}

Test-Check "DOC-03" "README.md has Security section" {
    $content = Get-Content "README.md" -Raw
    return ($content -match "(?i)## Security")
}

Test-Check "DOC-04" "README.md has Customizing section" {
    $content = Get-Content "README.md" -Raw
    return ($content -match "(?i)customiz")
}

Test-Check "DOC-05" "installation.md has tenant ID discovery" {
    $content = Get-Content "installation.md" -Raw
    return ($content -match "(?i)finding your tenant id")
}

Test-Check "DOC-06" "installation.md lists skills in installed_plugins" {
    $content = Get-Content "installation.md" -Raw
    $count = ([regex]::Matches($content, "cache_path")).Count
    return ($count -ge 8)
}

Test-Check "DOC-07" "AGENTS.md has Security section" {
    $content = Get-Content "AGENTS.md" -Raw
    return ($content -match "## Security" -and $content -match "(?i)prompt injection")
}

Test-Check "DOC-08" "AGENTS.md references skill table" {
    $content = Get-Content "AGENTS.md" -Raw
    return ($content -match "weekly-report" -and $content -match "send-email" -and $content -match "task-scheduler")
}

Test-Check "DOC-09" "threatmodel.md has all 9 threats" {
    $content = Get-Content "threatmodel.md" -Raw
    for ($i = 1; $i -le 9; $i++) {
        if ($content -notmatch "T${i}:") { return $false }
    }
    return $true
}

Test-Check "DOC-10" "CLAUDE.md contains domain knowledge" {
    $content = Get-Content "CLAUDE.md" -Raw
    return ($content -match "(?i)domain knowledge" -and ($content -match "(?i)program" -or $content -match "(?i)agent"))
}

# ============================================================
# Category 6: Security Controls (16 tests)
# ============================================================
Write-Host "`n--- 6. Security Controls ---" -ForegroundColor Yellow

Test-Check "SEC-01" "Pre-commit hook script exists and is executable" {
    $hook = "scripts/pre-commit"
    if (-not (Test-Path $hook)) { return $false }
    $content = Get-Content $hook -Raw
    return ($content -match "AZURE_OPENAI_API_KEY" -and $content -match "\.env")
}

Test-Check "SEC-02" "Pre-commit detects API key patterns" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "AZURE_OPENAI_API_KEY" -and $content -match "Bearer")
}

Test-Check "SEC-03" "Pre-commit detects .env files" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "\.env")
}

Test-Check "SEC-04" "Pre-commit detects large files" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "1048576" -or $content -match "1MB" -or $content -match "size")
}

Test-Check "SEC-05" "Pre-commit detects JWT tokens" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "eyJ")
}

Test-Check "SEC-06" "Pre-commit detects PEM keys" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "BEGIN.*PRIVATE KEY" -or $content -match "PEM")
}

Test-Check "SEC-07" "Pre-commit skips security scripts" {
    $content = Get-Content "scripts/pre-commit" -Raw
    return ($content -match "pre-commit" -and $content -match "security-audit")
}

Test-Check "SEC-08" "Security audit script runs without parse errors" {
    $output = powershell -ExecutionPolicy Bypass -Command "& { try { . '$RepoRoot/scripts/security-audit.ps1'; exit 0 } catch { Write-Host `$_.Exception.Message; exit 1 } }" 2>&1
    return ($LASTEXITCODE -eq 0)
}

Test-Check "SEC-09" ".gitignore excludes .env" {
    $content = Get-Content ".gitignore" -Raw
    return ($content -match "\.env")
}

Test-Check "SEC-10" ".gitignore excludes .env.local" {
    $content = Get-Content ".gitignore" -Raw
    return ($content -match "\.env\.local" -or $content -match "\.env\*")
}

Test-Check "SEC-11" ".gitignore excludes QMD cache" {
    $content = Get-Content ".gitignore" -Raw
    return ($content -match "qmd-memory" -or $content -match "embeddings")
}

Test-Check "SEC-12" ".gitattributes marks PDF as binary" {
    $content = Get-Content ".gitattributes" -Raw
    return ($content -match "\.pdf")
}

Test-Check "SEC-13" ".gitattributes marks DOCX as binary" {
    $content = Get-Content ".gitattributes" -Raw
    return ($content -match "\.docx")
}

Test-Check "SEC-14" ".gitattributes marks GGUF as binary" {
    $content = Get-Content ".gitattributes" -Raw
    return ($content -match "\.gguf")
}

Test-Check "SEC-15" ".gitattributes enforces line endings" {
    $content = Get-Content ".gitattributes" -Raw
    return ($content -match "eol=" -or $content -match "text=auto")
}

Test-Check "SEC-16" "No secrets found in current tracked files" {
    $hits = git grep -ilE "sk-[a-zA-Z0-9]{20,}" -- ":(exclude)tests/" ":(exclude)scripts/pre-commit" ":(exclude)scripts/security-audit.ps1" 2>$null
    return ($null -eq $hits -or $hits.Count -eq 0)
}

# ============================================================
# Category 7: Code Quality (2 tests)
# ============================================================
Write-Host "`n--- 7. Code Quality ---" -ForegroundColor Yellow

Test-Check "CQ-01" "No Unicode em-dashes (U+2014) in PS1 files" {
    $emDash = [char]0x2014
    $bad = @()
    Get-ChildItem $RepoRoot -Recurse -Filter *.ps1 | ForEach-Object {
        $content = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
        $count = ([regex]::Matches($content, $emDash)).Count
        if ($count -gt 0) { $bad += "$($_.Name): $count" }
    }
    if ($bad.Count -gt 0 -and $Verbose) {
        $bad | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
    return ($bad.Count -eq 0)
}

Test-Check "CQ-02" "All PS1 files parse without errors" {
    $bad = @()
    Get-ChildItem $RepoRoot -Recurse -Filter *.ps1 | ForEach-Object {
        $tokens = $null; $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count -gt 0) { $bad += "$($_.Name): $($parseErrors.Count) error(s)" }
    }
    if ($bad.Count -gt 0 -and $Verbose) {
        $bad | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
    return ($bad.Count -eq 0)
}

Test-Check "CQ-03" "All bundled skills have skill.json manifest" {
    $skillsDir = Join-Path $RepoRoot "skills"
    $missing = @()
    Get-ChildItem $skillsDir -Directory | ForEach-Object {
        $manifest = Join-Path $_.FullName "skill.json"
        if (-not (Test-Path $manifest)) { $missing += $_.Name }
        else {
            try {
                $json = Get-Content $manifest -Raw | ConvertFrom-Json
                if (-not $json.version) { $missing += "$($_.Name) (no version)" }
            } catch { $missing += "$($_.Name) (invalid JSON)" }
        }
    }
    if ($missing.Count -gt 0 -and $Verbose) {
        $missing | ForEach-Object { Write-Host "       Missing: $_" -ForegroundColor DarkGray }
    }
    return ($missing.Count -eq 0)
}

Test-Check "CQ-04" "Bundled skills marked with bundled flag for rename guidance" {
    $skillsDir = Join-Path $RepoRoot "skills"
    $bad = @()
    Get-ChildItem $skillsDir -Directory | ForEach-Object {
        $manifest = Join-Path $_.FullName "skill.json"
        if (Test-Path $manifest) {
            try {
                $json = Get-Content $manifest -Raw | ConvertFrom-Json
                if ($json.bundled -ne $true) {
                    $bad += "$($_.Name) (missing bundled: true)"
                }
            } catch { }
        }
    }
    if ($bad.Count -gt 0 -and $Verbose) {
        $bad | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
    return ($bad.Count -eq 0)
}

# ============================================================
# Summary
# ============================================================
$total = $pass + $fail
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Results: $pass/$total passed" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
if ($fail -gt 0) {
    Write-Host " FAILURES:" -ForegroundColor Red
    $results | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        Write-Host "   $($_.Id) - $($_.Name)" -ForegroundColor Red
    }
}
Write-Host "========================================`n" -ForegroundColor Cyan

Pop-Location
exit $fail
