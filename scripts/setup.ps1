<#
.SYNOPSIS
    Interactive setup wizard for Agency Cowork.

.DESCRIPTION
    Guides first-time setup: fork verification, agent customization,
    Microsoft 365 MCP configuration, skill registration, dependencies,
    and security hardening.

    Supports three modes:
      Interactive (default)  - prompts for every decision
      SkipPersonalization    - skips Phase 2 prompts, auto-detects UPN
      Headless               - zero prompts, all values from params/auto-detect/defaults

.PARAMETER Headless
    Run without any interactive prompts. All decisions use parameter values,
    auto-detection, or sensible defaults. Designed for agent-driven setup.
    Implies -SkipForkCheck.

.PARAMETER SkipForkCheck
    Skip the fork verification (for development/testing only).

.PARAMETER SkipPersonalization
    Skip the agent customization prompts. Identity is read from CLAUDE.md
    and memory repo from agentconfig.json.

.PARAMETER AgentName
    Override agent name (headless/personalization). Default: read from CLAUDE.md.

.PARAMETER AgentRole
    Override agent role (headless/personalization). Default: read from CLAUDE.md.

.PARAMETER UserEmail
    User's UPN/email. Default: auto-detected from 'az account show' or 'git config user.email'.

.PARAMETER UserName
    User's full name. Default: derived from UserEmail alias.

.PARAMETER UserOrg
    User's organization. Default: "Microsoft".

.PARAMETER MemoryRepo
    Memory repository URL. Default: read from agentconfig.json.

.PARAMETER TenantId
    Microsoft Entra tenant ID (GUID). Default: auto-detected from Azure CLI.

.PARAMETER InstallDeps
    Comma-separated list of optional dependencies to install.
    Valid values: markitdown, qmd, specify, all, none.
    Default: "all" in headless mode, interactive prompt otherwise.
    Note: QMD includes local SentenceTransformer embedding (pip install, no model download needed).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -SkipPersonalization

.EXAMPLE
    # Agent-driven headless setup
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Headless -UserEmail user@contoso.com

.EXAMPLE
    # Headless with specific deps only
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Headless -InstallDeps "markitdown,qmd"
#>

param(
    [switch]$Headless,
    [switch]$SkipForkCheck,
    [switch]$SkipPersonalization,
    [string]$AgentName,
    [string]$AgentRole,
    [string]$UserEmail,
    [string]$UserName,
    [string]$UserOrg,
    [string]$MemoryRepo,
    [string]$TenantId,
    [string]$InstallDeps
)

# Headless implies SkipForkCheck and SkipPersonalization
if ($Headless) {
    $SkipForkCheck = $true
    $SkipPersonalization = $true
    if (-not $InstallDeps) { $InstallDeps = "all" }
}

$ErrorActionPreference = "Continue"

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ConfigDir = Join-Path $env:USERPROFILE ".copilot"
$CopilotConfig = Join-Path $ConfigDir "config.json"
$VscodeDir = Join-Path $ProjectRoot ".vscode"
$McpConfig = Join-Path $ProjectRoot ".mcp.json"
$LegacyMcpConfig = Join-Path $VscodeDir "mcp.json"
$GlobalMcpConfig = Join-Path $ConfigDir "mcp-config.json"

Set-Location $ProjectRoot

# Track components that were skipped because already installed
$skippedComponents = [System.Collections.Generic.List[string]]::new()

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

function Read-UserInput {
    param(
        [string]$Prompt,
        [string]$Default = "",
        [switch]$Required
    )
    if ($script:Headless) {
        # In headless mode, return the default silently (or empty if none)
        $val = if ($Default) { $Default } else { "" }
        if ($val) { Write-Host "  $Prompt : $val (auto)" -ForegroundColor DarkGray }
        return $val
    }
    $suffix = if ($Default) { " [$Default]" } else { "" }
    do {
        Write-Host "  $Prompt${suffix}: " -NoNewline -ForegroundColor White
        $value = Read-Host
        if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
        if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
            Write-Host "    (required)" -ForegroundColor DarkYellow
        }
    } while ($Required -and [string]::IsNullOrWhiteSpace($value))
    return $value.Trim()
}

function Read-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    if ($script:Headless) {
        # In headless mode, always return the default
        $choice = if ($Default) { "yes" } else { "no" }
        Write-Host "  $Prompt -> $choice (auto)" -ForegroundColor DarkGray
        return $Default
    }
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    Write-Host "  $Prompt $hint " -NoNewline -ForegroundColor White
    $answer = Read-Host
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return ($answer.Trim().ToLower() -match '^y')
}

# Store Headless in script scope so helper functions can access it
$script:Headless = $Headless

# ============================================================
# Phase 0: Welcome
# ============================================================

Write-Host ""
Write-Host "    _                               ____                      _    " -ForegroundColor Magenta
Write-Host "   / \   __ _  ___ _ __   ___ _   _/ ___|___/\    /\___  _ __| | __" -ForegroundColor Magenta
Write-Host "  / _ \ / _`` |/ _ \ '_ \ / __| | | | |   / _ \ /\ / _ \| '__| |/ /" -ForegroundColor Magenta
Write-Host " / ___ \ (_| |  __/ | | | (__| |_| | |__| (_) V  V (_) | |  |   < " -ForegroundColor Magenta
Write-Host "/_/   \_\__, |\___|_| |_|\___|\__, |\____\___/\_/\_/\___/|_|  |_|\_\" -ForegroundColor Magenta
Write-Host "        |___/                 |___/                                 " -ForegroundColor Magenta
Write-Host ""
$modeLabel = if ($Headless) { "Headless Setup (agent-driven)" } elseif ($SkipPersonalization) { "Setup (skip personalization)" } else { "Interactive Setup" }
Write-Host "  Agency for the rest of us -- $modeLabel" -ForegroundColor White
Write-Host ""

# ============================================================
# Phase 0.5: Prerequisites
# ============================================================

Write-Banner "Prerequisites"

# Ensure winget is available
Write-Step "Checking for winget..."
$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    # Try common WindowsApps path (sometimes not on PATH)
    $wingetExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe" -ErrorAction SilentlyContinue
    if ($wingetExe) {
        $env:Path += ";$($wingetExe.DirectoryName)"
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    }
}
if (-not $wingetCmd) {
    Write-Warn "winget not found. Installing Microsoft App Installer..."
    try {
        # Download the latest App Installer MSIX bundle + dependencies from GitHub
        $releases = "https://api.github.com/repos/microsoft/winget-cli/releases/latest"
        $asset = (Invoke-RestMethod -Uri $releases -UseBasicParsing).assets |
            Where-Object { $_.name -match '\.msixbundle$' } | Select-Object -First 1
        $msixPath = Join-Path $env:TEMP $asset.name
        Write-Host "    Downloading $($asset.name)..." -ForegroundColor Gray
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $msixPath -UseBasicParsing

        # Also grab the VCLibs dependency (required on clean installs)
        $vclibsUrl = "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx"
        $vclibsPath = Join-Path $env:TEMP "Microsoft.VCLibs.x64.14.00.Desktop.appx"
        if (-not (Test-Path $vclibsPath)) {
            Write-Host "    Downloading VCLibs dependency..." -ForegroundColor Gray
            Invoke-WebRequest -Uri $vclibsUrl -OutFile $vclibsPath -UseBasicParsing
        }

        # Install VCLibs first, then winget
        Add-AppxPackage -Path $vclibsPath -ErrorAction SilentlyContinue
        Add-AppxPackage -Path $msixPath

        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetCmd) {
            Write-Ok "winget installed successfully"
        } else {
            Write-Warn "winget installed but not on PATH yet. You may need to restart your terminal."
        }

        # Cleanup
        Remove-Item $msixPath -ErrorAction SilentlyContinue
    } catch {
        Write-Err "Failed to install winget: $_"
        Write-Host "    Install manually: https://aka.ms/getwinget" -ForegroundColor Gray
    }
} else {
    $wingetVer = (winget --version 2>$null)
    Write-Ok "winget available ($wingetVer)"
}

# Install core prerequisites via individual winget install commands
if ($wingetCmd) {
    Write-Step "Checking prerequisites..."
    $packages = @(
        @{ Id = "Microsoft.VisualStudioCode"; Name = "VS Code";        Cmd = "code" }
        @{ Id = "Git.Git";                    Name = "Git";             Cmd = "git" }
        @{ Id = "OpenJS.NodeJS.LTS";          Name = "Node.js LTS";    Cmd = "node" }
        @{ Id = "Python.Python.3.12";         Name = "Python 3.12";    Cmd = "python" }
        @{ Id = "Microsoft.AzureCLI";         Name = "Azure CLI";      Cmd = "az" }
        @{ Id = "Microsoft.PowerShell";        Name = "PowerShell 7";   Cmd = "pwsh" }
    )
    foreach ($pkg in $packages) {
        Write-Host "    $($pkg.Name)..." -ForegroundColor Gray -NoNewline
        # Skip if the tool is already on PATH
        if (Get-Command $pkg.Cmd -ErrorAction SilentlyContinue) {
            Write-Host " already installed" -ForegroundColor DarkGray
            $skippedComponents.Add($pkg.Name)
            continue
        }
        $installArgs = @("install", "--id", $pkg.Id, "--source", "winget",
                         "--accept-package-agreements", "--accept-source-agreements")
        if ($Headless) { $installArgs += "--disable-interactivity" }
        $installOutput = & winget @installArgs 2>&1
        $installExit = $LASTEXITCODE
        if ($installExit -eq 0) {
            Write-Host " OK" -ForegroundColor Green
        } elseif ($installOutput | Select-String -Pattern "already installed|No applicable|No newer" -Quiet) {
            Write-Host " already installed" -ForegroundColor DarkGray
            $skippedComponents.Add($pkg.Name)
        } else {
            Write-Host " failed (exit $installExit)" -ForegroundColor Yellow
        }
    }

    # Refresh PATH so newly installed tools are available in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    # Probe well-known install directories for tools that winget just installed
    $probePaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312"
        "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
        "${env:ProgramFiles}\Python312"
        "${env:ProgramFiles}\Python312\Scripts"
        "${env:ProgramFiles}\nodejs"
        "${env:ProgramFiles(x86)}\Microsoft SDKs\Azure\CLI2\wbin"
        "${env:ProgramFiles}\Microsoft SDKs\Azure\CLI2\wbin"
        "${env:ProgramFiles}\Git\cmd"
        "${env:ProgramFiles}\Git\bin"
        "${env:ProgramFiles}\PowerShell\7"
    )
    foreach ($probe in $probePaths) {
        if ((Test-Path $probe) -and ($env:Path -notlike "*$probe*")) {
            $env:Path += ";$probe"
        }
    }
} else {
    Write-Warn "winget not available -- install prerequisites manually: Python 3.12, Node.js LTS, Git, Azure CLI, PowerShell 7"
}

# Ensure pip is available (Python may have been just installed by winget)
Write-Step "Checking for pip..."
$pipCmd = Get-Command pip -ErrorAction SilentlyContinue
if (-not $pipCmd) {
    # Python may be on PATH but pip isn't -- try python -m ensurepip
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        # Probe well-known Python install dirs
        foreach ($pyDir in @("$env:LOCALAPPDATA\Programs\Python\Python312", "${env:ProgramFiles}\Python312")) {
            if ((Test-Path "$pyDir\python.exe") -and ($env:Path -notlike "*$pyDir*")) {
                $env:Path += ";$pyDir;$pyDir\Scripts"
            }
        }
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    }
    if ($pythonCmd) {
        Write-Step "pip not on PATH, bootstrapping via ensurepip..."
        python -m ensurepip --upgrade 2>&1 | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
    }
}
if ($pipCmd) {
    $pipVer = (pip --version 2>$null) -replace '^pip (\S+).*', '$1'
    Write-Ok "pip available ($pipVer)"
} else {
    Write-Warn "pip not found. Install Python 3.12 (winget install Python.Python.3.12) and run: python -m ensurepip --upgrade"
}

# Ensure npm is available (Node.js may have been just installed by winget)
Write-Step "Checking for npm..."
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    # Probe well-known Node.js install dir
    $nodeDir = "${env:ProgramFiles}\nodejs"
    if ((Test-Path "$nodeDir\npm.cmd") -and ($env:Path -notlike "*$nodeDir*")) {
        $env:Path += ";$nodeDir"
    }
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
}
if ($npmCmd) {
    $npmVer = (npm --version 2>$null)
    Write-Ok "npm available ($npmVer)"
} else {
    Write-Warn "npm not found. Install Node.js LTS (winget install OpenJS.NodeJS.LTS) and restart your terminal."
}

# Ensure Azure CLI is available (may have been just installed by winget)
Write-Step "Checking for Azure CLI..."
$azCmd = Get-Command az -ErrorAction SilentlyContinue
if (-not $azCmd) {
    # Probe well-known Azure CLI install dirs
    foreach ($azDir in @("${env:ProgramFiles(x86)}\Microsoft SDKs\Azure\CLI2\wbin", "${env:ProgramFiles}\Microsoft SDKs\Azure\CLI2\wbin")) {
        if ((Test-Path "$azDir\az.cmd") -and ($env:Path -notlike "*$azDir*")) {
            $env:Path += ";$azDir"
        }
    }
    $azCmd = Get-Command az -ErrorAction SilentlyContinue
}
if ($azCmd) {
    $azVer = (az version --query '\"azure-cli\"' -o tsv 2>$null)
    Write-Ok "Azure CLI available ($azVer)"
} else {
    Write-Warn "Azure CLI not found. Install with: winget install Microsoft.AzureCLI"
}

# ============================================================
# Phase 1: Fork Verification
# ============================================================

Write-Banner "Phase 1: Fork Verification"

if ($SkipForkCheck) {
    Write-Warn "Fork check skipped (--SkipForkCheck)"
} else {
    $remoteUrl = git remote get-url origin 2>$null
    if (-not $remoteUrl) {
        Write-Err "No git remote 'origin' found. This must be a git repository."
        Write-Host ""
        Write-Host "  To set up:" -ForegroundColor White
        Write-Host "    1. Fork https://github.com/YOUR-ORG/Agency-Cowork on GitHub" -ForegroundColor Gray
        Write-Host "    2. Clone your fork locally" -ForegroundColor Gray
        Write-Host "    3. Run this setup script from the cloned repo" -ForegroundColor Gray
        exit 1
    }

    $baseRepos = @(
        "github.com/YOUR-ORG/Agency-Cowork"
    )

    $isBaseRepo = $false
    foreach ($base in $baseRepos) {
        if ($remoteUrl -match [regex]::Escape($base)) {
            $isBaseRepo = $true
            break
        }
    }

    if ($isBaseRepo) {
        Write-Err "This repo is still pointing at the base Agency-Cowork project."
        Write-Host ""
        Write-Host "  Current remote: $remoteUrl" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  You must fork the repo into your own GitHub account before setup:" -ForegroundColor White
        Write-Host "    1. Go to https://github.com/YOUR-ORG/Agency-Cowork" -ForegroundColor Gray
        Write-Host "    2. Click 'Fork' to create your own copy" -ForegroundColor Gray
        Write-Host "    3. Clone YOUR fork: git clone https://github.com/YOUR-ORG/Agency-Cowork.git" -ForegroundColor Gray
        Write-Host "    4. Run this setup script from your fork" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Or change the remote manually:" -ForegroundColor White
        Write-Host "    git remote set-url origin https://github.com/YOUR-ORG/Agency-Cowork.git" -ForegroundColor Gray
        exit 1
    }

    Write-Ok "Fork verified: $remoteUrl"
}

# ============================================================
# Phase 1.5: Initialize Identity Files from Templates
# ============================================================

Write-Step "Checking identity files..."

if (-not (Test-Path "CLAUDE.md")) {
    if (Test-Path "CLAUDE.md.example") {
        Copy-Item "CLAUDE.md.example" "CLAUDE.md"
        Write-Ok "Created CLAUDE.md from CLAUDE.md.example"
    } else {
        Write-Err "CLAUDE.md.example not found. Cannot create agent identity file."
    }
} else {
    Write-Ok "CLAUDE.md already exists (keeping your customizations)"
}

if (-not (Test-Path "AGENTS.md")) {
    if (Test-Path "AGENTS.md.example") {
        Copy-Item "AGENTS.md.example" "AGENTS.md"
        Write-Ok "Created AGENTS.md from AGENTS.md.example"
    } else {
        Write-Err "AGENTS.md.example not found. Cannot create operational rules file."
    }
} else {
    Write-Ok "AGENTS.md already exists (keeping your customizations)"
}

# ============================================================
# Phase 2: Agent Customization
# ============================================================

Write-Banner "Phase 2: Customize Your Agent"

# Allow skipping interactively if not already set via parameter
if (-not $SkipPersonalization) {
    $SkipPersonalization = -not (Read-YesNo -Prompt "Customize agent name, role, and user profile?")
}

if ($SkipPersonalization) {
    Write-Warn "Personalization skipped"

    # Read identity from CLAUDE.md, allow parameter overrides
    $claudeMd = Get-Content "CLAUDE.md" -Raw
    if ($AgentName) { $agentName = $AgentName }
    elseif ($claudeMd -match '- \*\*Name:\*\* (.+)') { $agentName = $Matches[1].Trim() }
    else { $agentName = "Agency Cowork" }

    if ($AgentRole) { $agentRole = $AgentRole }
    elseif ($claudeMd -match '- \*\*Role:\*\* (.+)') { $agentRole = $Matches[1].Trim() }
    else { $agentRole = "Program Manager & Technical Strategist" }

    Write-Ok "Agent identity: $agentName ($agentRole)"

    # UPN: parameter > az CLI > git config
    if (-not $UserEmail) {
        try { $UserEmail = (az account show --query user.name -o tsv 2>$null) } catch {}
    }
    if (-not $UserEmail) { $UserEmail = (git config user.email 2>$null) }
    $userEmail = $UserEmail
    if ($userEmail) { Write-Ok "UPN: $userEmail" } else { Write-Warn "Could not determine UPN" }

    $userName = if ($UserName) { $UserName } elseif ($userEmail) { $userEmail.Split("@")[0] } else { "" }
    $userOrg = if ($UserOrg) { $UserOrg } else { "Microsoft" }
    $userAlias = if ($userEmail) { $userEmail.Split("@")[0] } else { "" }

} else {
    Write-Host "  These values personalize your agent's identity and memory." -ForegroundColor Gray
    Write-Host "  Press Enter to accept defaults shown in [brackets]." -ForegroundColor Gray
    Write-Host ""

    $agentName = Read-UserInput -Prompt "Agent name" -Default "Agency Cowork"
    $agentRole = Read-UserInput -Prompt "Agent role" -Default "Program Manager & Technical Strategist"

    # Auto-detect UPN, prompt only if detection fails
    $detectedUpn = $null
    try { $detectedUpn = (az account show --query user.name -o tsv 2>$null) } catch {}
    if (-not $detectedUpn) { $detectedUpn = (git config user.email 2>$null) }

    if ($detectedUpn) {
        Write-Ok "Detected UPN: $detectedUpn"
        $useDetected = Read-YesNo -Prompt "Use this as your email/UPN?"
        if ($useDetected) { $userEmail = $detectedUpn }
        else { $userEmail = Read-UserInput -Prompt "Your email (UPN)" -Required }
    } else {
        $userEmail = Read-UserInput -Prompt "Your email (UPN)" -Required
    }

    $userName = Read-UserInput -Prompt "Your full name" -Default ($userEmail.Split("@")[0])
    $userOrg = Read-UserInput -Prompt "Your organization" -Default "Microsoft"
    $userAlias = $userEmail.Split("@")[0]

    Write-Host ""
    Write-Step "Updating CLAUDE.md..."

    $claudeMd = Get-Content "CLAUDE.md" -Raw
    $claudeMd = $claudeMd -replace '- \*\*Name:\*\* Agency Cowork', "- **Name:** $agentName"
    $claudeMd = $claudeMd -replace '- \*\*Role:\*\* Program Manager & Technical Strategist', "- **Role:** $agentRole"
    Set-Content "CLAUDE.md" -Value $claudeMd -NoNewline
    Write-Ok "CLAUDE.md updated (name: $agentName, role: $agentRole)"
}

# Memory repository: parameter > agentconfig.json > prompt
Write-Step "Configuring memory repository..."
$configJson = Get-Content "agentconfig.json" -Raw | ConvertFrom-Json
if ($MemoryRepo) {
    $memoryRepo = $MemoryRepo
    # Persist the override to agentconfig.json
    $configJson.memory.repo = $memoryRepo
    $configJson | ConvertTo-Json -Depth 10 | Set-Content "agentconfig.json"
    Write-Ok "Memory repo from parameter: $memoryRepo"
} else {
    $memoryRepo = $configJson.memory.repo
}
$memoryBranch = if ($configJson.memory.branch) { $configJson.memory.branch } else { "main" }

if (-not $SkipPersonalization -and -not $Headless -and (-not $memoryRepo -or [string]::IsNullOrWhiteSpace($memoryRepo) -or $memoryRepo -match 'your-org')) {
    Write-Host ""
    Write-Host "  The memory/ directory stores personal context (daily logs, knowledgebase)" -ForegroundColor Gray
    Write-Host "  in a separate private Git repo to keep your data portable and private." -ForegroundColor Gray
    Write-Host ""
    $memoryRepo = Read-UserInput -Prompt "Memory repo URL (or 'skip' to use local memory)" -Default "skip"
    if ($memoryRepo -ne "skip" -and -not [string]::IsNullOrWhiteSpace($memoryRepo)) {
        $memoryBranch = Read-UserInput -Prompt "Memory repo branch" -Default "main"
        $configJson.memory.repo = $memoryRepo
        $configJson.memory.branch = $memoryBranch
        $configJson | ConvertTo-Json -Depth 10 | Set-Content "agentconfig.json"
        Write-Ok "agentconfig.json updated with memory repo: $memoryRepo"
    } else {
        $memoryRepo = $null
    }
}

if ($memoryRepo -and $memoryRepo -ne "skip" -and -not [string]::IsNullOrWhiteSpace($memoryRepo)) {
    Write-Ok "Memory repo: $memoryRepo (branch: $memoryBranch)"
    Write-Step "Syncing memory repository..."
    if (Test-Path "scripts\sync-memory.ps1") {
        & powershell -ExecutionPolicy Bypass -File "scripts\sync-memory.ps1"
    }
} else {
    Write-Warn "No memory repo configured. Memory will be stored locally in memory/"
    if (-not (Test-Path "memory")) { New-Item -ItemType Directory -Path "memory" -Force | Out-Null }
    if (-not (Test-Path "memory\MEMORY.md")) {
        # PS 5.1 requires here-string @" at column 0; use array join instead
        $memoryContent = @(
            "# Semantic Memory",
            "",
            "## User Profile",
            "",
            "- **Name:** $userName",
            "- **Email:** $userEmail",
            "- **Organization:** $userOrg",
            "- **Role:** (your role)",
            "",
            "## Key Contacts",
            "",
            "| Name | Role | Email |",
            "|------|------|-------|",
            "| (add contacts here) | | |",
            "",
            "## Preferences",
            "",
            "- **Communication style:** (formal / casual / concise)",
            "- **Working hours:** (e.g., 9am-5pm PST)",
            "- **Tools:** Agency Cowork, Outlook, Teams, SharePoint"
        ) -join "`r`n"
        $memoryContent | Set-Content "memory\MEMORY.md" -Encoding UTF8
        Write-Ok "Created memory/MEMORY.md with your profile"
    }
    if (-not (Test-Path "memory\Knowledgebase")) {
        New-Item -ItemType Directory -Path "memory\Knowledgebase\Program" -Force | Out-Null
        New-Item -ItemType Directory -Path "memory\Knowledgebase\Specifications" -Force | Out-Null
        Write-Ok "Created memory/Knowledgebase directory structure"
    }
    if (-not (Test-Path "memory/WeeklyReports")) {
        New-Item -ItemType Directory -Path "memory/WeeklyReports" -Force | Out-Null
        Write-Ok "Created memory/WeeklyReports directory"
    }
}

# Migrate daily logs from memory/ root to memory/DailyLogs/ (v0.9.5+)
if (Test-Path "memory") {
    $dailyLogs = Get-ChildItem "memory" -Filter "????-??-??.md" -File -ErrorAction SilentlyContinue
    if ($dailyLogs.Count -gt 0) {
        if (-not (Test-Path "memory\DailyLogs")) {
            New-Item -ItemType Directory -Path "memory\DailyLogs" -Force | Out-Null
        }
        $moved = 0
        foreach ($log in $dailyLogs) {
            $dest = Join-Path "memory\DailyLogs" $log.Name
            if (Test-Path $dest) {
                # Keep newer file, back up older
                $srcTime = $log.LastWriteTime
                $dstTime = (Get-Item $dest).LastWriteTime
                if ($srcTime -gt $dstTime) {
                    Move-Item $log.FullName $dest -Force
                    $moved++
                }
                # else: dest is newer, leave it; source stays (will be cleaned up by archiver)
            } else {
                Move-Item $log.FullName $dest
                $moved++
            }
        }
        if ($moved -gt 0) {
            Write-Ok "Migrated $moved daily log(s) to memory/DailyLogs/"
        }
    }
    # Ensure DailyLogs directory exists for new installs
    if (-not (Test-Path "memory\DailyLogs")) {
        New-Item -ItemType Directory -Path "memory\DailyLogs" -Force | Out-Null
    }
}

# Create global config directory (~/.agency-cowork/)
$globalConfigDir = Join-Path $env:USERPROFILE ".agency-cowork"
if (-not (Test-Path $globalConfigDir)) {
    New-Item -ItemType Directory -Path $globalConfigDir -Force | Out-Null
    Write-Ok "Created global config directory: $globalConfigDir"
}

# Migrate legacy per-repo monitor-config.json to global config
$legacyMonCfg = "skills\teams\monitor\monitor-config.json"
$globalMonCfg = Join-Path $globalConfigDir "monitor-config.json"
if (Test-Path $legacyMonCfg) {
    try {
        $legacy = Get-Content $legacyMonCfg -Raw | ConvertFrom-Json
        $global = @{ enabled = $false; identity = @{}; connection = @{}; workspaces = @{} }
        if (Test-Path $globalMonCfg) {
            $global = Get-Content $globalMonCfg -Raw | ConvertFrom-Json
            # Ensure top-level enabled field exists
            if ($null -eq $global.enabled) {
                $global | Add-Member -NotePropertyName "enabled" -NotePropertyValue $false -Force
            }
        }
        # Migrate identity (only if current is empty/placeholder)
        $currentMri = ""
        if ($global.identity -and $global.identity.mri) { $currentMri = $global.identity.mri }
        $isPlaceholder = (-not $currentMri) -or ($currentMri -match "00000000-0000-0000-0000-000000000000")
        if ($isPlaceholder -and $legacy.authorized_sender -and $legacy.authorized_sender.mri) {
            $global.identity = @{
                mri = $legacy.authorized_sender.mri
                displayName = $legacy.authorized_sender.displayName
                upn = $legacy.authorized_sender.upn
            }
        }
        # Migrate connection (only if legacy has non-default chatsvc_region)
        if ($legacy.connection -and $legacy.connection.chatsvc_region) {
            $global.connection = $legacy.connection
        }
        # Migrate workspace entry -- skip if global already has an enabled entry
        $wsKey = (Resolve-Path ".").Path.ToLower()
        if (-not $global.workspaces) {
            $global | Add-Member -NotePropertyName "workspaces" -NotePropertyValue @{} -Force
        }
        $existingWs = $null
        if ($global.workspaces.PSObject -and $global.workspaces.PSObject.Properties[$wsKey]) {
            $existingWs = $global.workspaces.$wsKey
        }
        $skipMigrate = $false
        if ($existingWs -and $existingWs.enabled) { $skipMigrate = $true }
        if (-not $skipMigrate) {
            # Prefer keyword from agentconfig.json over legacy (legacy may have stale @maia-agent)
            $kwVal = ""
            $agentCfgPath = Join-Path (Resolve-Path ".").Path "agentconfig.json"
            if (Test-Path $agentCfgPath) {
                try {
                    $agentCfg = Get-Content $agentCfgPath -Raw | ConvertFrom-Json
                    if ($agentCfg.monitor -and $agentCfg.monitor.keyword) {
                        $kwVal = $agentCfg.monitor.keyword
                    }
                } catch { }
            }
            if (-not $kwVal) {
                $kwVal = if ($legacy.keyword) { $legacy.keyword } else { "@agent" }
            }
            $rpVal = if ($legacy.reply_prefix) { $legacy.reply_prefix } else { "Agency Cowork: " }
            $mcVal = if ($legacy.monitored_conversations) { $legacy.monitored_conversations } else { @() }
            $dpVal = if ($legacy.dispatch) { $legacy.dispatch } else { @{} }
            $global.workspaces | Add-Member -NotePropertyName $wsKey -NotePropertyValue @{
                enabled = [bool]$legacy.enabled
                keyword = $kwVal
                reply_prefix = $rpVal
                monitored_conversations = $mcVal
                dispatch = $dpVal
            } -Force
        }
        $global | ConvertTo-Json -Depth 10 | Set-Content $globalMonCfg
        Rename-Item $legacyMonCfg "$legacyMonCfg.migrated" -Force
        Write-Ok "Migrated monitor config to global: $globalMonCfg"
    } catch {
        Write-Warn "Could not migrate monitor config: $_"
    }
}

# ============================================================
# Phase 3: Microsoft 365 Configuration
# ============================================================

Write-Banner "Phase 3: Microsoft 365 MCP Servers"

Write-Host "  MCP servers connect your agent to Outlook, Teams, SharePoint," -ForegroundColor Gray
Write-Host "  Calendar, Word, and WorkIQ (AI-powered M365 search)." -ForegroundColor Gray
Write-Host ""

# Ensure Azure CLI is logged in (skip gracefully if az not installed)
Write-Step "Checking Azure CLI authentication..."
$azAccount = $null
if (-not $azCmd) {
    Write-Warn "Azure CLI is not installed. Skipping Azure authentication."
    Write-Host "    Install later with: winget install Microsoft.AzureCLI" -ForegroundColor Gray
    Write-Host "    Then re-run setup to complete Phase 3 configuration." -ForegroundColor Gray
} else {
    try { $azAccount = (az account show --query user.name -o tsv 2>$null) } catch {}
    if (-not $azAccount) {
        Write-Warn "Azure CLI not logged in. Running 'az login'..."
        az login --output none 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Azure CLI login failed. Some features (tenant auto-detect, SharePoint, Landing Zone) will not work."
        } else {
            $azAccount = (az account show --query user.name -o tsv 2>$null)
            Write-Ok "Logged in as: $azAccount"
        }
    } else {
        Write-Ok "Azure CLI authenticated: $azAccount"
    }
}

# Tenant ID: parameter > auto-detect > prompt
$resolvedTenantId = $null
if ($TenantId) {
    $resolvedTenantId = $TenantId
    Write-Ok "Tenant ID from parameter: $resolvedTenantId"
} elseif ($azCmd) {
    Write-Step "Attempting to auto-detect tenant ID via Azure CLI..."
    try {
        $resolvedTenantId = (az account show --query tenantId -o tsv 2>$null)
        if ($resolvedTenantId -and $resolvedTenantId -match '^[0-9a-f]{8}-') {
            Write-Ok "Detected tenant ID: $resolvedTenantId"
            $useTenant = Read-YesNo -Prompt "Use this tenant ID?"
            if (-not $useTenant) { $resolvedTenantId = $null }
        } else {
            $resolvedTenantId = $null
        }
    } catch {
        $resolvedTenantId = $null
    }
}

if (-not $resolvedTenantId) {
    if ($Headless) {
        Write-Warn "Tenant ID could not be auto-detected and no -TenantId provided."
        Write-Host "    Re-run with: -TenantId <GUID>" -ForegroundColor Gray
        Write-Host "    Continuing setup -- MCP servers will use placeholder tenant ID." -ForegroundColor Gray
        $resolvedTenantId = "REPLACE-WITH-YOUR-TENANT-ID"
    } else {
        Write-Host ""
        Write-Host "  To find your tenant ID:" -ForegroundColor Gray
        Write-Host "    - Azure Portal: https://portal.azure.com > Microsoft Entra ID > Overview" -ForegroundColor Gray
        Write-Host "    - Azure CLI: az account show --query tenantId -o tsv" -ForegroundColor Gray
        Write-Host "    - Entra Portal: https://entra.microsoft.com/#view/Microsoft_AAD_IAM/TenantOverview.ReactView" -ForegroundColor Gray
        Write-Host ""
        $resolvedTenantId = Read-UserInput -Prompt "Enter your Microsoft Entra tenant ID (GUID), or press Enter to skip" -Default "REPLACE-WITH-YOUR-TENANT-ID"
        if ($resolvedTenantId -eq "REPLACE-WITH-YOUR-TENANT-ID") {
            Write-Warn "Skipped tenant ID. You can set it later in your MCP config file."
        }
    }
}

$tenantId = $resolvedTenantId

# Validate format (skip validation for placeholder)
if ($tenantId -ne "REPLACE-WITH-YOUR-TENANT-ID" -and $tenantId -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
    Write-Err "Invalid tenant ID format. Expected a GUID like: 12345678-1234-1234-1234-123456789abc"
    Write-Host "  You entered: $tenantId" -ForegroundColor Gray
    Write-Host "  You can fix this later in: $McpConfig" -ForegroundColor Gray
}

# Detect Git for Windows bash (needed by QMD's npm wrapper on Windows)
$gitBashBinDir = $null
$gitBashCandidates = @(
    "C:\Program Files\Git\bin",
    "C:\Program Files (x86)\Git\bin",
    "$env:LOCALAPPDATA\Programs\Git\bin"
)
foreach ($candidate in $gitBashCandidates) {
    if (Test-Path (Join-Path $candidate "bash.exe")) {
        $gitBashBinDir = $candidate
        break
    }
}
if (-not $gitBashBinDir) {
    # Try to find bash.exe from git.exe location (e.g., Git\cmd\git.exe -> Git\bin\bash.exe)
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) {
        $gitBinDir = Join-Path (Split-Path (Split-Path $gitCmd.Source)) "bin"
        if (Test-Path (Join-Path $gitBinDir "bash.exe")) {
            $gitBashBinDir = $gitBinDir
        }
    }
}
if ($gitBashBinDir) {
    Write-Ok "Git for Windows bash found: $gitBashBinDir\bash.exe"
} else {
    Write-Warn "Git for Windows bash.exe not found. QMD requires bash.exe on PATH."
    Write-Host "    Install Git for Windows: winget install Git.Git" -ForegroundColor Gray
    Write-Host "    Or ensure 'C:\Program Files\Git\bin' is in your system PATH." -ForegroundColor Gray
}
$hasWsl = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)

# Generate MCP config
Write-Step "Writing MCP configuration..."

# Verify agency CLI is available (required for agency mcp servers)
$agencyCmd = Get-Command agency -ErrorAction SilentlyContinue
if (-not $agencyCmd) {
    # Also check well-known install location before attempting install
    $wellKnownAgency = Join-Path $env:APPDATA "agency\CurrentVersion\agency.exe"
    if (Test-Path $wellKnownAgency) {
        $agencyDir = Split-Path $wellKnownAgency
        $env:Path += ";$agencyDir"
        $agencyCmd = Get-Command agency -ErrorAction SilentlyContinue
    }
}

if (-not $agencyCmd) {
    Write-Step "Installing Agency CLI..."
    try {
        # Step 1: Detect architecture
        $agencyArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }

        # Step 2: Download PathInstaller
        $installerFolder = Join-Path $env:TEMP ("AgencyInstall_" + (Get-Date).Ticks)
        $installerZip = "$installerFolder.zip"
        $installerUrl = "https://aka.ms/PathInstaller-win-$agencyArch"
        Write-Host "    Downloading installer ($agencyArch)..." -ForegroundColor Gray
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerZip -UseBasicParsing

        # Step 3: Extract and run PathInstaller
        Expand-Archive -Path $installerZip -DestinationPath $installerFolder -Force
        $pathInstaller = Join-Path $installerFolder "Pathinstaller.exe"
        Write-Host "    Running PathInstaller..." -ForegroundColor Gray
        & $pathInstaller Install agency 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }

        # Step 4: Cleanup installer
        Remove-Item $installerFolder -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $installerZip -Force -ErrorAction SilentlyContinue

        # Step 5: Refresh PATH from registry so current session sees the new install
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

        # Step 6: Also probe the well-known install directory in case PATH wasn't updated yet
        $wellKnownAgency = Join-Path $env:APPDATA "agency\CurrentVersion\agency.exe"
        if ((Test-Path $wellKnownAgency) -and ($env:Path -notlike "*agency\CurrentVersion*")) {
            $env:Path += ";" + (Split-Path $wellKnownAgency)
        }

        # Step 7: Verify installation
        $agencyCmd = Get-Command agency -ErrorAction SilentlyContinue
        if ($agencyCmd) {
            $agencyVer = (agency --version 2>$null) -replace '\s+$',''
            Write-Ok "Agency CLI installed: $agencyVer"
        } else {
            Write-Warn "Agency CLI install completed but 'agency' not yet on PATH."
            Write-Host "    You may need to restart your terminal for PATH changes to take effect." -ForegroundColor Gray
            Write-Host "    Expected location: $wellKnownAgency" -ForegroundColor Gray
        }
    } catch {
        Write-Warn "Agency CLI installation failed: $_"
        Write-Host '    Manual install: iex "& { $(irm aka.ms/InstallTool.ps1)} agency"' -ForegroundColor Gray
        Write-Host "    After install, restart your terminal and re-run this script." -ForegroundColor Gray
    }
} else {
    $agencyVer = (agency --version 2>$null) -replace '\s+$',''
    Write-Ok "Agency CLI available: $agencyVer"
}

# Verify azureauth installation (required for MCP auth tokens)
# PathInstaller sometimes extracts zips incompletely, leaving MSALWrapper.dll missing
# which causes 0xe0434352 (CLR unhandled exception) at runtime.
$azureAuthDir = Join-Path $env:LOCALAPPDATA "Programs" "AzureAuth"
$azureAuthHealthy = $false
if (Test-Path $azureAuthDir) {
    # Find the active version directory (highest version number)
    $versionDirs = Get-ChildItem $azureAuthDir -Directory | Where-Object { $_.Name -match '^\d+\.\d+' } | Sort-Object { [version]($_.Name -replace '[^\d.]','') } -Descending
    if ($versionDirs.Count -gt 0) {
        $activeDir = $versionDirs[0].FullName
        $azureAuthExe = Join-Path $activeDir "azureauth.exe"
        $msalDll = Join-Path $activeDir "MSALWrapper.dll"

        if ((Test-Path $azureAuthExe) -and (Test-Path $msalDll)) {
            # Quick verification -- run azureauth --version
            try {
                $azVer = & $azureAuthExe --version 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $azureAuthHealthy = $true
                    Write-Ok "AzureAuth verified: v$($azVer.Trim()) (MSALWrapper.dll present)"
                }
            } catch { }
        }

        if (-not $azureAuthHealthy) {
            Write-Warn "AzureAuth installation incomplete -- attempting repair..."
            # Look for the source zip to re-extract missing files
            $zipPattern = Join-Path $azureAuthDir "azureauth-*-win-*.zip"
            $sourceZips = Get-ChildItem $zipPattern -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
            $repaired = $false
            if ($sourceZips.Count -gt 0) {
                try {
                    Add-Type -AssemblyName System.IO.Compression.FileSystem
                    $zip = [System.IO.Compression.ZipFile]::OpenRead($sourceZips[0].FullName)
                    $restoredCount = 0
                    foreach ($entry in $zip.Entries) {
                        if ($entry.Name -eq '') { continue }
                        $destPath = Join-Path $activeDir $entry.FullName
                        $dir = Split-Path $destPath -Parent
                        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
                        if (-not (Test-Path $destPath)) {
                            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destPath, $false)
                            $restoredCount++
                        }
                    }
                    $zip.Dispose()
                    if ($restoredCount -gt 0) {
                        Write-Ok "Restored $restoredCount missing file(s) from $($sourceZips[0].Name)"
                    }
                    # Re-verify
                    $azVer = & $azureAuthExe --version 2>$null
                    if ($LASTEXITCODE -eq 0) {
                        $azureAuthHealthy = $true
                        Write-Ok "AzureAuth repaired: v$($azVer.Trim())"
                    } else {
                        Write-Err "AzureAuth still broken after repair -- exit code $LASTEXITCODE"
                    }
                    $repaired = $true
                } catch {
                    Write-Err "AzureAuth repair failed: $_"
                }
            }
            if (-not $repaired) {
                Write-Warn "No source zip found for repair. MSALWrapper.dll may be missing."
                Write-Host "    To fix manually:" -ForegroundColor Gray
                Write-Host "    1. Re-download azureauth from the Agency CLI installer" -ForegroundColor Gray
                Write-Host "    2. Or re-run: agency auth login" -ForegroundColor Gray
            }
        }
    }
} else {
    Write-Host "    AzureAuth not installed yet (will be provisioned by Agency CLI on first auth)" -ForegroundColor Gray
}

if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}
if (-not (Test-Path $VscodeDir)) {
    New-Item -ItemType Directory -Path $VscodeDir -Force | Out-Null
}

$mcpConfigContent = @"
{
  "mcpServers": {
    "workiq": {
      "command": "cmd.exe",
      "args": ["/c", "agency", "mcp", "workiq"]
    },
    "teams": {
      "command": "cmd.exe",
      "args": ["/c", "agency", "mcp", "teams"]
    },
    "mail": {
      "command": "cmd.exe",
      "args": ["/c", "agency", "mcp", "mail"]
    },
    "calendar": {
      "command": "cmd.exe",
      "args": ["/c", "agency", "mcp", "calendar"]
    },
    "sharepoint": {
      "command": "cmd.exe",
      "args": ["/c", "agency", "mcp", "sharepoint"]
    },
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
"@

# Write node-direct QMD config into the template if we can resolve paths now.
# This avoids the bash shim entirely. The second-pass patch below refines this
# with the protocol adapter; this handles the case where setup runs non-interactively.
$qmdNpmPrefixEarly = $null
try { $qmdNpmPrefixEarly = (npm config get prefix 2>$null).Trim() } catch {}
$qmdJsEarly = $null
if ($qmdNpmPrefixEarly) {
    $candidate = Join-Path $qmdNpmPrefixEarly "node_modules\@tobilu\qmd\dist\cli\qmd.js"
    if (Test-Path $candidate) { $qmdJsEarly = $candidate }
}
if (-not $qmdJsEarly) {
    foreach ($loc in @(
        (Join-Path $env:APPDATA "npm\node_modules\@tobilu\qmd\dist\cli\qmd.js"),
        (Join-Path $HOME ".npm-global\node_modules\@tobilu\qmd\dist\cli\qmd.js")
    )) { if ((Test-Path $loc) -and -not $qmdJsEarly) { $qmdJsEarly = $loc } }
}
$qmdNodeExeEarly = $null
$nodeExeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeExeCmd) { $qmdNodeExeEarly = $nodeExeCmd.Source }

if ($qmdNodeExeEarly -and $qmdJsEarly) {
    # Rewrite the qmd entry to use node directly (no bash dependency)
    $mcpObj = $mcpConfigContent | ConvertFrom-Json
    $mcpObj.mcpServers.qmd.command = $qmdNodeExeEarly
    $mcpObj.mcpServers.qmd.args = @($qmdJsEarly, "mcp")
    $mcpConfigContent = $mcpObj | ConvertTo-Json -Depth 10
    Write-Ok "QMD MCP: using node-direct invocation (node: $qmdNodeExeEarly)"
}

# Test agency mcp auth health before migrating away from old HTTP servers
$agencyMcpHealthy = $false
if ($agencyCmd) {
    Write-Step "Testing agency MCP authentication..."
    try {
        $testOutput = & agency mcp calendar --health-check 2>&1
        if ($LASTEXITCODE -eq 0) {
            $agencyMcpHealthy = $true
            Write-Ok "Agency MCP auth: healthy"
        } else {
            # Health check flag may not exist -- try a quick spawn + immediate kill
            $testProc = Start-Process -FilePath "agency" -ArgumentList "mcp","calendar" -PassThru -NoNewWindow -RedirectStandardError (Join-Path $env:TEMP "agency-mcp-test-err.txt") -RedirectStandardOutput (Join-Path $env:TEMP "agency-mcp-test-out.txt")
            Start-Sleep -Seconds 5
            if (-not $testProc.HasExited) {
                # Process is alive after 5s -- auth likely succeeded
                Stop-Process -Id $testProc.Id -Force -ErrorAction SilentlyContinue
                $agencyMcpHealthy = $true
                Write-Ok "Agency MCP auth: healthy (server started successfully)"
            } else {
                $errContent = Get-Content (Join-Path $env:TEMP "agency-mcp-test-err.txt") -Raw -ErrorAction SilentlyContinue
                if ($errContent -match "azureauth|access.token|EntraID|0xe0434352") {
                    Write-Warn "Agency MCP auth failed: azureauth not working on this machine"
                    Write-Host "    Error: $($errContent.Substring(0, [Math]::Min(200, $errContent.Length)))" -ForegroundColor Gray
                } else {
                    Write-Warn "Agency MCP server exited unexpectedly (exit code: $($testProc.ExitCode))"
                }
            }
            Remove-Item (Join-Path $env:TEMP "agency-mcp-test-err.txt") -Force -ErrorAction SilentlyContinue
            Remove-Item (Join-Path $env:TEMP "agency-mcp-test-out.txt") -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warn "Agency MCP health check failed: $_"
    }
}

# Migrate legacy .vscode/mcp.json to .mcp.json if it exists
if ((Test-Path $LegacyMcpConfig) -and -not (Test-Path $McpConfig)) {
    try {
        $legacyCfg = Get-Content $LegacyMcpConfig -Raw | ConvertFrom-Json
        $migratedCfg = [PSCustomObject]@{}
        # Convert "servers" key to "mcpServers"
        $legacyServers = if ($legacyCfg.PSObject.Properties["servers"]) { $legacyCfg.servers } elseif ($legacyCfg.PSObject.Properties["mcpServers"]) { $legacyCfg.mcpServers } else { $null }
        if ($legacyServers) {
            $migratedCfg | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue $legacyServers
        } else {
            $migratedCfg | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{}
        }
        $migratedCfg | ConvertTo-Json -Depth 10 | Set-Content $McpConfig
        Remove-Item -LiteralPath $LegacyMcpConfig -Force
        Write-Ok "Migrated .vscode/mcp.json -> .mcp.json"
    } catch {
        Write-Warn "Could not auto-migrate .vscode/mcp.json: $($_.Exception.Message)"
    }
}

if (Test-Path $McpConfig) {
    # Merge: add new servers, replace old HTTP servers with STDIO builtins (only if auth works)
    try {
        $existing = Get-Content $McpConfig -Raw | ConvertFrom-Json
        $new = $mcpConfigContent | ConvertFrom-Json
        # Support both "mcpServers" (.mcp.json) and "servers" (legacy)
        $sKey = if ($existing.PSObject.Properties["mcpServers"]) { "mcpServers" } else { "servers" }
        if (-not $existing.$sKey) { $existing | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{}; $sKey = "mcpServers" }

        $removed = @()
        if ($agencyMcpHealthy) {
            # Auth works -- safe to remove old HTTP servers
            $oldHttpServers = @("microsoft-teams", "microsoft-outlook-mail", "microsoft-outlook-calendar", "microsoft-sharepoint-and-onedrive")
            foreach ($old in $oldHttpServers) {
                if ($existing.$sKey.PSObject.Properties[$old]) {
                    $srv = $existing.$sKey.$old
                    if ($srv.url -or $srv.type -eq "http") {
                        $existing.$sKey.PSObject.Properties.Remove($old)
                        $removed += $old
                    }
                }
            }
            # Also migrate workiq from old npx wrapper to agency builtin
            if ($existing.$sKey.PSObject.Properties["workiq"]) {
                $wiq = $existing.$sKey.workiq
                if ($wiq.command -and (Split-Path $wiq.command -Leaf) -eq "npx") {
                    $existing.$sKey.PSObject.Properties.Remove("workiq")
                    $removed += "workiq (npx)"
                }
            }
        } else {
            # Auth broken -- keep old HTTP servers, skip STDIO servers that need auth
            $authServers = @("teams", "mail", "calendar", "sharepoint", "workiq")
            Write-Warn "Keeping existing MCP servers (agency auth not available)"
            Write-Host "    The new STDIO servers (teams, mail, calendar) require working azureauth." -ForegroundColor Gray
            Write-Host "    Fix: run 'agency auth login' then re-run setup, or keep using HTTP servers." -ForegroundColor Gray
            # Remove auth-dependent servers from the new config so we don't add broken ones
            foreach ($authSrv in $authServers) {
                if ($new.mcpServers.PSObject.Properties[$authSrv]) {
                    $new.mcpServers.PSObject.Properties.Remove($authSrv)
                }
            }
        }

        $added = @()
        foreach ($key in $new.mcpServers.PSObject.Properties.Name) {
            if (-not $existing.$sKey.PSObject.Properties[$key]) {
                $existing.$sKey | Add-Member -NotePropertyName $key -NotePropertyValue $new.mcpServers.$key
                $added += $key
            }
        }
        # If existing file used legacy "servers" key, migrate to "mcpServers"
        if ($sKey -eq "servers") {
            $migrated = $existing.servers
            $existing.PSObject.Properties.Remove("servers")
            $existing | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue $migrated
        }
        $changed = ($added.Count -gt 0) -or ($removed.Count -gt 0) -or ($sKey -eq "servers")
        if ($changed) {
            $existing | ConvertTo-Json -Depth 10 | Set-Content $McpConfig
        }
        if ($removed.Count -gt 0) {
            Write-Ok "MCP config: removed $($removed.Count) legacy HTTP server(s) ($($removed -join ', '))"
        }
        if ($added.Count -gt 0) {
            Write-Ok "MCP config: added $($added.Count) STDIO server(s) ($($added -join ', '))"
        }
        if (-not $changed) {
            Write-Ok "MCP config: all servers already configured (no changes)"
        }
    } catch {
        Write-Warn "Could not merge MCP config: $($_.Exception.Message). Run setup again or edit $McpConfig manually."
    }
} else {
    if (-not $agencyMcpHealthy) {
        Write-Warn "Writing MCP config without auth-dependent servers (azureauth not available)"
        Write-Host "    Only QMD server will be configured. Run 'agency auth login' then re-run setup." -ForegroundColor Gray
        # Strip auth-dependent servers from the fresh config
        $mcpObj = $mcpConfigContent | ConvertFrom-Json
        foreach ($authSrv in @("teams", "mail", "calendar", "workiq")) {
            if ($mcpObj.mcpServers.PSObject.Properties[$authSrv]) {
                $mcpObj.mcpServers.PSObject.Properties.Remove($authSrv)
            }
        }
        $mcpConfigContent = $mcpObj | ConvertTo-Json -Depth 10
    }
    Set-Content $McpConfig -Value $mcpConfigContent
    Write-Ok "MCP config written to: $McpConfig"
}

# Clean up legacy configs
if ((Test-Path $McpConfig) -and (Test-Path $LegacyMcpConfig)) {
    Remove-Item -LiteralPath $LegacyMcpConfig -Force -ErrorAction SilentlyContinue
    Write-Ok "Removed legacy .vscode/mcp.json (migrated to .mcp.json)"
}
if ((Test-Path $McpConfig) -and (Test-Path $GlobalMcpConfig)) {
    Write-Host "  [INFO] MCP config active at .mcp.json" -ForegroundColor Gray
    Write-Host "         Global config at $GlobalMcpConfig can be removed if no other projects use it." -ForegroundColor Gray
}

# ============================================================
# Phase 4: Skill Registration
# ============================================================

Write-Banner "Phase 4: Register Skills"

Write-Host "  Registering all 24 local skills as installed_plugins." -ForegroundColor Gray
Write-Host ""

$skills = @(
    "calendar", "claude-deep-research-skill", "cocoindex", "confluence", "deep-personalization",
    "email-triage", "excel", "landing-zone", "markitdown", "meeting-summary",
    "onepdm", "oneplanner", "powerpoint", "qmd-memory",
    "send-email", "sharepoint-download", "spec-kit", "svg-to-ppt", "task-scheduler",
    "teams", "visual-explainer", "webpage-builder", "weekly-report", "word-doc", "workstreams"
)

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$pluginEntries = @()
foreach ($skill in $skills) {
    $skillPath = (Join-Path $ProjectRoot "skills\$skill") -replace '\\', '\\'
    $pluginEntries += @{
        name = $skill
        marketplace = "local"
        version = "1.0.0"
        installed_at = $timestamp
        enabled = $true
        cache_path = $skillPath
    }
}

# Load or create config.json
if (Test-Path $CopilotConfig) {
    try {
        $config = Get-Content $CopilotConfig -Raw | ConvertFrom-Json
    } catch {
        Write-Warn "Could not parse existing config.json, creating new one"
        $config = [PSCustomObject]@{}
    }
} else {
    $config = [PSCustomObject]@{}
}

# Merge: remove any existing local plugins with the same names, then add ours
$existingPlugins = @()
if ($config.PSObject.Properties['installed_plugins']) {
    $existingPlugins = @($config.installed_plugins | Where-Object {
        -not ($_.marketplace -eq "local" -and $skills -contains $_.name)
    })
}

$allPlugins = $existingPlugins + $pluginEntries
$config | Add-Member -NotePropertyName "installed_plugins" -NotePropertyValue $allPlugins -Force
$config | ConvertTo-Json -Depth 10 | Set-Content $CopilotConfig
Write-Ok "Registered $($skills.Count) skills in: $CopilotConfig"

foreach ($skill in $skills) {
    Write-Host "    + $skill" -ForegroundColor DarkGreen
}

# ============================================================
# Phase 4b: Task Scheduler Setup
# ============================================================

Write-Host ""
Write-Step "Setting up Task Scheduler service..."
$schedulerSetup = Join-Path $ProjectRoot "scripts\setup-scheduler.ps1"
if (Test-Path $schedulerSetup) {
    $schedulerShell = "powershell"
    if (Get-Command pwsh -ErrorAction SilentlyContinue) { $schedulerShell = "pwsh" }
    & $schedulerShell -ExecutionPolicy Bypass -File $schedulerSetup
} else {
    Write-Warn "scripts/setup-scheduler.ps1 not found, skipping scheduler setup"
}

# ============================================================
# Phase 5: Landing Zone Configuration (Optional)
# ============================================================

Write-Banner "Phase 5: Landing Zone Programs (Optional)"

Write-Host "  The Landing Zone skill queries ADO saved queries for program requirements." -ForegroundColor Gray
Write-Host "  If you use Landing Zone, configure your programs now." -ForegroundColor Gray
Write-Host "  You can skip this and configure later by editing skills/landing-zone/programs.json" -ForegroundColor Gray
Write-Host ""

$lzConfigPath = Join-Path $ProjectRoot "skills\landing-zone\programs.json"
$configureLz = Read-YesNo -Prompt "Configure Landing Zone programs?"

if ($configureLz) {
    $programs = @{}
    $addMore = $true

    while ($addMore) {
        Write-Host ""
        Write-Step "Add a Landing Zone program"
        $progSlug = Read-Host "  Program slug (e.g., my-program)"
        if (-not $progSlug) { break }

        $adoOrg = Read-Host "  ADO Organization name"
        if (-not $adoOrg) { break }

        $adoProject = Read-Host "  ADO Project name"
        if (-not $adoProject) { break }

        $queryId = Read-Host "  ADO Saved Query GUID"
        if (-not $queryId) { break }

        $programs[$progSlug] = @{
            org = $adoOrg
            project = $adoProject
            query_id = $queryId
        }

        Write-Ok "Added: $progSlug -> $adoOrg/$adoProject ($queryId)"
        $addMore = Read-YesNo -Prompt "Add another program?"
    }

    if ($programs.Count -gt 0) {
        $programs | ConvertTo-Json -Depth 5 | Set-Content $lzConfigPath
        Write-Ok "Landing Zone config written to: skills/landing-zone/programs.json ($($programs.Count) programs)"
    } else {
        Write-Warn "No programs configured. You can add them later to skills/landing-zone/programs.json"
    }
} else {
    Write-Host "  Skipped. See skills/landing-zone/programs.json.example for the format." -ForegroundColor Gray
}

# ============================================================
# Phase 6: Git Hooks & Security
# ============================================================

Write-Banner "Phase 6: Security Hardening"

# Install pre-commit hook
Write-Step "Installing pre-commit hook..."
$hookSource = Join-Path $ProjectRoot "scripts\pre-commit"
$hookDest = Join-Path $ProjectRoot ".git\hooks\pre-commit"
if (Test-Path $hookSource) {
    Copy-Item -Path $hookSource -Destination $hookDest -Force
    Write-Ok "Pre-commit hook installed"
} else {
    Write-Warn "scripts/pre-commit not found, skipping"
}

# Harden file permissions
Write-Step "Hardening file permissions..."
$hardenScript = Join-Path $ProjectRoot "scripts\harden-permissions.ps1"
if (Test-Path $hardenScript) {
    & powershell -ExecutionPolicy Bypass -File $hardenScript
} else {
    Write-Warn "scripts/harden-permissions.ps1 not found, skipping"
}

# Run security audit
Write-Step "Running security audit..."
$auditScript = Join-Path $ProjectRoot "scripts\security-audit.ps1"
if (Test-Path $auditScript) {
    & powershell -ExecutionPolicy Bypass -File $auditScript
} else {
    Write-Warn "scripts/security-audit.ps1 not found, skipping"
}

# ============================================================
# Phase 7: Optional Dependencies
# ============================================================

Write-Banner "Phase 7: Optional Dependencies"

Write-Host "  These tools enhance specific skills. You can install them now" -ForegroundColor Gray
Write-Host "  or later. The agent works without them but some skills will" -ForegroundColor Gray
Write-Host "  be limited." -ForegroundColor Gray
Write-Host ""

# Parse InstallDeps into a set for headless control
$depsToInstall = @{}
if ($InstallDeps) {
    $depsList = $InstallDeps.ToLower() -split '[,;\s]+'
    if ($depsList -contains 'all') {
        $depsToInstall = @{ markitdown = $true; qmd = $true; specify = $false }  # specify still opt-in
    } elseif ($depsList -contains 'none') {
        $depsToInstall = @{ markitdown = $false; qmd = $false; specify = $false }
    } else {
        $depsToInstall['markitdown'] = $depsList -contains 'markitdown'
        $depsToInstall['qmd'] = $depsList -contains 'qmd'
        $depsToInstall['specify'] = $depsList -contains 'specify'
    }
}

# MarkItDown
$installMid = if ($depsToInstall.Count -gt 0) { $depsToInstall['markitdown'] } else { Read-YesNo -Prompt "Install MarkItDown? (converts PDF/Word/Excel to markdown)" }
if ($installMid) {
    # Check if markitdown is already installed (PATH check + pip show + python import fallback)
    $midInstalled = $null -ne (Get-Command markitdown -ErrorAction SilentlyContinue)
    if (-not $midInstalled) {
        try { $midInstalled = (pip show markitdown 2>&1 | Out-String) -match 'Name:\s*markitdown' } catch {}
    }
    if (-not $midInstalled) {
        try { python -c "import markitdown" 2>$null; if ($LASTEXITCODE -eq 0) { $midInstalled = $true } } catch {}
    }
    if ($midInstalled) {
        Write-Ok "MarkItDown already installed"
        $skippedComponents.Add("MarkItDown")
    } else {
        Write-Step "Installing markitdown..."
        $uvAvailable = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)
        if ($uvAvailable) {
            uv tool install "markitdown[all]" 2>&1 | Out-Host
        } elseif ($pipCmd) {
            pip install --disable-pip-version-check "markitdown[all]" 2>&1 | Out-Host
        } else {
            Write-Warn "Neither uv nor pip found -- skipping MarkItDown."
            Write-Host "    Install Python 3.12 first: winget install Python.Python.3.12" -ForegroundColor Gray
        }
        if ($LASTEXITCODE -eq 0 -and ($uvAvailable -or $pipCmd)) { Write-Ok "MarkItDown installed" }
        elseif ($uvAvailable -or $pipCmd) { Write-Warn "MarkItDown install may have had issues -- check output above" }
    }
}

# Handy (speech-to-text)
$installHandy = if ($depsToInstall.Count -gt 0) { $depsToInstall['handy'] } else { Read-YesNo -Prompt "Install Handy? (offline speech-to-text, uses Whisper)" }
if ($installHandy) {
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
        Write-Ok "Handy already installed"
        $skippedComponents.Add("Handy")
    } else {
        Write-Step "Installing Handy (speech-to-text)..."
        $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
        if ($wingetAvailable) {
            winget install cjpais.Handy --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) { Write-Ok "Handy installed" }
            else { Write-Warn "Handy install may have had issues -- check output above" }
        } else {
            Write-Warn "winget not found -- download Handy manually from https://github.com/cjpais/handy/releases"
        }
    }
}

# QMD
$installQmd = if ($depsToInstall.Count -gt 0) { $depsToInstall['qmd'] } else { Read-YesNo -Prompt "Install QMD? (local hybrid search for memory, requires Node.js)" }
if ($installQmd) {
    # Check Node version -- QMD requires Node 22 LTS (better-sqlite3 has no prebuilds for 24+)
    $nodeMajor = 0
    try { $nodeMajor = [int]((node --version 2>$null) -replace '^v(\d+).*', '$1') } catch {}
    if ($nodeMajor -eq 0) {
        Write-Warn "Node.js not found. QMD requires Node.js 22 LTS."
        Write-Warn "Install Node.js 22 LTS (winget install OpenJS.NodeJS.LTS) and re-run setup."
        $installQmd = $false
    } elseif ($nodeMajor -lt 22) {
        Write-Warn "QMD requires Node.js 22 LTS. Current: $(node --version 2>$null)"
        Write-Warn "Skipping QMD install. Install Node.js 22 LTS and re-run setup."
        $installQmd = $false
    } elseif ($nodeMajor -gt 22) {
        Write-Warn "Node.js $nodeMajor detected -- better-sqlite3 may lack prebuilds for this version."
        # Check if C++ build tools are available for source compilation
        $hasVCTools = $null -ne (Get-Command cl.exe -ErrorAction SilentlyContinue) -or
            (Test-Path "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC")
        if (-not $hasVCTools) {
            Write-Warn "C++ build tools not found. QMD needs to compile better-sqlite3 from source for Node $nodeMajor."
            Write-Host "    Installing Visual Studio Build Tools (C++ workload)..." -ForegroundColor Gray
            $installBuildTools = Read-YesNo -Prompt "Install C++ build tools for native compilation?" -Default $true
            if ($installBuildTools) {
                Write-Step "Installing Visual Studio Build Tools..."
                winget install Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --passive" 2>&1 | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "Build tools install may have failed. If QMD install fails, try:"
                    Write-Host "    winget install Microsoft.VisualStudio.2022.BuildTools" -ForegroundColor Gray
                    Write-Host "    Or install Node.js 22 LTS: winget install OpenJS.NodeJS.LTS" -ForegroundColor Gray
                } else {
                    Write-Ok "Visual Studio Build Tools installed"
                }
            } else {
                Write-Warn "Skipping build tools. If QMD fails, either install build tools or Node.js 22 LTS."
            }
        }
    }
}
if ($installQmd) {
    # Check if QMD is already installed (PATH + npm global prefix + common filesystem locations)
    $qmdInstalled = $null -ne (Get-Command qmd -ErrorAction SilentlyContinue)
    if (-not $qmdInstalled) {
        # Check npm global prefix directory for the package
        $npmPrefix = $null
        try { $npmPrefix = (npm config get prefix 2>$null).Trim() } catch {}
        if ($npmPrefix -and (Test-Path (Join-Path $npmPrefix "node_modules\@tobilu\qmd"))) {
            $qmdInstalled = $true
        }
    }
    if (-not $qmdInstalled) {
        # Check well-known npm global locations
        @(
            (Join-Path $env:APPDATA "npm\node_modules\@tobilu\qmd"),
            (Join-Path $HOME ".npm-global\node_modules\@tobilu\qmd")
        ) | ForEach-Object { if (Test-Path $_) { $qmdInstalled = $true } }
    }
    if ($qmdInstalled) {
        Write-Ok "QMD already installed"
        $skippedComponents.Add("QMD")
    } else {
        Write-Step "Installing QMD..."
        npm install -g @tobilu/qmd 2>&1 | Out-Host
    }
    if ($qmdInstalled -or $LASTEXITCODE -eq 0) {
        if (-not $qmdInstalled) { Write-Ok "QMD installed" }

        # Verify node + qmd.js are resolvable (adapter approach requires both; no bash needed)
        Write-Step "Verifying node + qmd.js for QMD MCP..."
        $nodeCheck = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCheck) {
            Write-Ok "node found: $($nodeCheck.Source)"
        } else {
            Write-Warn "node not found on PATH -- QMD MCP will fall back to bare 'qmd' shim"
        }

        # Patch QMD MCP config to use absolute paths (avoids Node.js version mismatch)
        # When multiple Node versions exist, the qmd.cmd shim calls bare "node" which may
        # resolve to the wrong version, causing native module crashes (issue #120).
        Write-Step "Patching QMD MCP config with absolute paths..."
        $qmdNodeExe = $null
        $qmdEntryScript = $null
        # Find the node.exe that npm is using (same tree where QMD was installed)
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) { $qmdNodeExe = $nodeCmd.Source }
        # Find the qmd.js entry point in the npm global prefix
        $qmdNpmPrefix = $null
        try { $qmdNpmPrefix = (npm config get prefix 2>$null).Trim() } catch {}
        if ($qmdNpmPrefix) {
            $qmdJs = Join-Path $qmdNpmPrefix "node_modules\@tobilu\qmd\dist\cli\qmd.js"
            if (Test-Path $qmdJs) { $qmdEntryScript = $qmdJs }
        }
        # Also check well-known locations if prefix didn't work
        if (-not $qmdEntryScript) {
            @(
                (Join-Path $env:APPDATA "npm\node_modules\@tobilu\qmd\dist\cli\qmd.js"),
                (Join-Path $HOME ".npm-global\node_modules\@tobilu\qmd\dist\cli\qmd.js")
            ) | ForEach-Object { if ((Test-Path $_) -and -not $qmdEntryScript) { $qmdEntryScript = $_ } }
        }
        if ($qmdNodeExe -and $qmdEntryScript) {
            $adapterScript = Join-Path $PSScriptRoot "qmd-mcp-adapter.js"
            # Apply adapter patch to workspace config and global config (if it exists)
            foreach ($cfgPath in @($McpConfig, $GlobalMcpConfig)) {
                if (-not (Test-Path $cfgPath)) { continue }
                try {
                    $mcpCfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
                    $sKey = if ($mcpCfg.PSObject.Properties["servers"]) { "servers" } else { "mcpServers" }
                    if ($mcpCfg.$sKey -and $mcpCfg.$sKey.PSObject.Properties["qmd"]) {
                        # Route through the protocol adapter (Content-Length ↔ NDJSON translation).
                        # Copilot CLI uses Content-Length framing; MCP SDK v1.25+ uses NDJSON.
                        $mcpCfg.$sKey.qmd.command = $qmdNodeExe
                        $mcpCfg.$sKey.qmd.args = @($adapterScript, "--", $qmdNodeExe, $qmdEntryScript, "mcp")
                        # Remove env.PATH if present -- no longer needed with absolute paths
                        if ($mcpCfg.$sKey.qmd.PSObject.Properties["env"]) {
                            $mcpCfg.$sKey.qmd.PSObject.Properties.Remove("env")
                        }
                        Set-Content $cfgPath -Value ($mcpCfg | ConvertTo-Json -Depth 10)
                        Write-Ok "QMD MCP: adapter + absolute paths in $(Split-Path -Leaf $cfgPath)"
                    }
                } catch {
                    Write-Warn "Could not patch QMD MCP config in $(Split-Path -Leaf $cfgPath): $_"
                }
            }
        } elseif (-not $qmdNodeExe) {
            Write-Warn "Could not resolve node.exe path -- QMD MCP will use shim"
        } elseif (-not $qmdEntryScript) {
            Write-Warn "Could not find qmd.js entry point -- QMD MCP will use shim"
        }

        # Install Python dependency for SentenceTransformer embeddings (default provider)
        $stInstalled = $false
        try { $stInstalled = (pip show sentence-transformers 2>&1 | Out-String) -match 'Name:\s*sentence-transformers' } catch {}
        if (-not $stInstalled) {
            try { python -c "import sentence_transformers" 2>$null; if ($LASTEXITCODE -eq 0) { $stInstalled = $true } } catch {}
        }
        if ($stInstalled) {
            Write-Ok "sentence-transformers already installed"
            $skippedComponents.Add("sentence-transformers")
        } else {
            Write-Step "Installing sentence-transformers for local embeddings..."
            $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
            if ($pipCmd) {
                pip install --disable-pip-version-check sentence-transformers 2>&1 | Out-Host
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "sentence-transformers installed (default SentenceTransformer embedding provider)"
                } else {
                    Write-Warn "sentence-transformers install had issues -- check output above"
                    Write-Host "    You can install manually: pip install sentence-transformers" -ForegroundColor Gray
                }
            } else {
                Write-Warn "pip not found. Install manually: pip install sentence-transformers"
            }
        }

        # Test SentenceTransformer embedding provider
        $pythonAvailable = $pythonCmd -or (Get-Command python -ErrorAction SilentlyContinue)
        if ($pythonAvailable) {
            Write-Step "Testing SentenceTransformer embedding provider..."
            $testResult = python skills/qmd-memory/scripts/azure-embed.py --test 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "SentenceTransformer embedding provider working"
                $testResult | Select-String "SUCCESS|Throughput|dim=" | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
            } else {
                Write-Warn "SentenceTransformer test failed (QMD keyword search still works without embeddings)"
                Write-Host "    You can re-test later: python skills/qmd-memory/scripts/azure-embed.py --test" -ForegroundColor Gray
            }
        } else {
            Write-Warn "Python not available -- skipping SentenceTransformer test."
        }

        $setupQmd = Read-YesNo -Prompt "Run QMD collection setup now?"
        if ($setupQmd -and (Test-Path "skills\qmd-memory\scripts\setup-qmd.ps1")) {
            & powershell -ExecutionPolicy Bypass -File "skills\qmd-memory\scripts\setup-qmd.ps1"
        }
    } else {
        Write-Warn "QMD install may have had issues -- check output above"
    }
}

# Specify CLI
$installSpecify = if ($depsToInstall.Count -gt 0) { $depsToInstall['specify'] } else { Read-YesNo -Prompt "Install Specify CLI? (spec-driven development from GitHub)" -Default $false }
if ($installSpecify) {
    # Check if specify is already installed
    $specifyInstalled = (Get-Command specify -ErrorAction SilentlyContinue) -or
        ((pip show specify-cli 2>$null) -match 'Name: specify-cli')
    if ($specifyInstalled) {
        Write-Ok "Specify CLI already installed"
        $skippedComponents.Add("Specify CLI")
    } else {
        Write-Step "Installing specify-cli..."
        $uvAvailable = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)
        if ($uvAvailable) {
            uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git" 2>&1 | Out-Host
        } elseif ($pipCmd) {
            pip install --disable-pip-version-check "git+https://github.com/github/spec-kit.git" 2>&1 | Out-Host
        } else {
            Write-Warn "Neither uv nor pip found -- skipping Specify CLI."
            Write-Host "    Install Python 3.12 first: winget install Python.Python.3.12" -ForegroundColor Gray
        }
        if ($LASTEXITCODE -eq 0 -and ($uvAvailable -or $pipCmd)) { Write-Ok "Specify CLI installed" }
        elseif ($uvAvailable -or $pipCmd) { Write-Warn "Specify CLI install may have had issues -- check output above" }
    }
}

# Teams Rich Messaging & Monitor
Write-Host ""
Write-Step "Setting up Teams skill dependencies..."
$teamsReqs = Join-Path $ProjectRoot "skills\teams\requirements.txt"
if (Test-Path $teamsReqs) {
    if ($pipCmd) {
        # Check if all requirements are already satisfied
        $checkOutput = pip install --disable-pip-version-check --dry-run -r $teamsReqs 2>&1
        $alreadySatisfied = ($checkOutput | Select-String "Would install" -Quiet) -ne $true
        if ($alreadySatisfied) {
            Write-Ok "Teams Python dependencies already installed"
            $skippedComponents.Add("Teams Python deps")
        } else {
            pip install --disable-pip-version-check -r $teamsReqs 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) { Write-Ok "Teams Python dependencies installed" }
            else { Write-Warn "Teams pip install had issues -- check output above" }
        }
    } else {
        Write-Warn "pip not available -- skipping Teams Python dependencies."
        Write-Host "    Install Python 3.12 first: winget install Python.Python.3.12" -ForegroundColor Gray
    }
} else {
    Write-Warn "skills/teams/requirements.txt not found, skipping"
}

# Playwright Edge (optional)
$installPlaywright = if ($depsToInstall.Count -gt 0) { $true } else { Read-YesNo -Prompt "Install Playwright Edge driver? (needed for @mentions, Adaptive Cards, file attachments)" }
if ($installPlaywright) {
    if ($pythonCmd -or (Get-Command python -ErrorAction SilentlyContinue)) {
        # For msedge, Playwright uses the system Edge binary -- check if Edge is installed
        $edgePaths = @(
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
        )
        $edgeInstalled = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        # Also check that the playwright Python package is installed
        $pwInstalled = python -c "import playwright; print('ok')" 2>$null
        if ($edgeInstalled -and $pwInstalled -eq "ok") {
            Write-Ok "Playwright Edge driver already installed (system Edge detected)"
            $skippedComponents.Add("Playwright Edge")
        } else {
            Write-Step "Installing Playwright Edge driver..."
            python -m playwright install msedge 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) { Write-Ok "Playwright Edge driver installed" }
            else { Write-Warn "Playwright install had issues -- check output above" }
        }
    } else {
        Write-Warn "Python not available -- skipping Playwright install."
        Write-Host "    Install Python 3.12 first: winget install Python.Python.3.12" -ForegroundColor Gray
    }
}

# Monitor service notice
Write-Host ""
Write-Host "  Teams Monitor Service (real-time channel/chat monitoring):" -ForegroundColor Gray
Write-Host "    The monitor service listens for @agent mentions in Teams" -ForegroundColor Gray
Write-Host "    and dispatches prompts to the AI agent. It is OFF by default." -ForegroundColor Gray
Write-Host "" -ForegroundColor Gray
Write-Host "    To enable:" -ForegroundColor Yellow
Write-Host "      1. Set monitor.enabled=true in agentconfig.json" -ForegroundColor White
Write-Host "      2. Configure monitor settings in the Settings panel or ~/.agency-cowork/monitor-config.json" -ForegroundColor White
Write-Host "      3. Start: cd skills/teams && python -m scripts.monitor.service start" -ForegroundColor White
Write-Host "" -ForegroundColor Gray
Write-Host "    SECURITY: Review threatmodel.md (T11, T12) before enabling." -ForegroundColor Red
Write-Host "    The service executes prompts unattended with your M365 identity." -ForegroundColor Red
Write-Host ""

# ============================================================
# Phase 8: Verification
# ============================================================

Write-Banner "Phase 8: Verification"

Write-Step "Running offline test suite..."
$testScript = Join-Path $ProjectRoot "tests\run-offline-tests.ps1"
if (Test-Path $testScript) {
    & powershell -ExecutionPolicy Bypass -File $testScript
} else {
    Write-Warn "tests/run-offline-tests.ps1 not found, skipping verification"
}

# ============================================================
# Summary
# ============================================================

Write-Banner "Setup Complete!"

Write-Host "  Agent:  $agentName ($agentRole)" -ForegroundColor White
if ($userName) { Write-Host "  User:   $userName <$userEmail>" -ForegroundColor White }
if ($userOrg) { Write-Host "  Org:    $userOrg" -ForegroundColor White }
Write-Host "  Memory: $memoryRepo" -ForegroundColor White
Write-Host "  Tenant: $tenantId" -ForegroundColor White
Write-Host ""
Write-Host "  Files configured:" -ForegroundColor Gray
Write-Host "    CLAUDE.md              Agent identity" -ForegroundColor Gray
if (Test-Path "memory\MEMORY.md") {
    Write-Host "    memory/MEMORY.md       User profile & contacts" -ForegroundColor Gray
}
Write-Host "    $McpConfig" -ForegroundColor Gray
Write-Host "    $CopilotConfig" -ForegroundColor Gray
Write-Host ""

# Skipped components summary
if ($skippedComponents.Count -gt 0) {
    Write-Host "  Pre-existing tools (kept as-is):" -ForegroundColor Gray
    foreach ($comp in $skippedComponents) {
        Write-Host "    - $comp" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  To upgrade these, re-run setup interactively:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1" -ForegroundColor Cyan
    Write-Host "  Or update individually with winget/pip/npm." -ForegroundColor Gray
    Write-Host ""
}

Write-Host "  Get started:" -ForegroundColor Yellow
Write-Host ""
Write-Host "    cd $ProjectRoot" -ForegroundColor Cyan
Write-Host "    copilot" -ForegroundColor Cyan
Write-Host ""
Write-Host "  This launches Agency Cowork -- your AI coworker. Once running," -ForegroundColor White
Write-Host "  say `"Personalize my agent`" to run the deep-personalization skill." -ForegroundColor White
Write-Host "  It will interview you and configure domain knowledge, contacts," -ForegroundColor White
Write-Host "  communication style, and working preferences automatically." -ForegroundColor White
Write-Host ""
Write-Host "  After that, you can:" -ForegroundColor Gray
Write-Host "    - Populate memory/Knowledgebase/ with your reference docs" -ForegroundColor Gray
Write-Host "    - Run: /skills  -- to verify all skills are loaded" -ForegroundColor Gray
Write-Host "    - (Optional) Enable Teams monitor -- see installation.md" -ForegroundColor Gray
Write-Host ""
Write-Host "  Documentation:" -ForegroundColor Gray
Write-Host "    README.md          Project overview" -ForegroundColor Gray
Write-Host "    installation.md    Detailed manual setup reference" -ForegroundColor Gray
Write-Host "    threatmodel.md     Security threat model" -ForegroundColor Gray
Write-Host ""
