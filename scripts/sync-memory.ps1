<#
.SYNOPSIS
    Syncs the memory/ directory from a configured Git repository.
.DESCRIPTION
    Clones or pulls the memory repo configured in agentconfig.json into the memory/ directory.
    This separates personal data (MEMORY.md, daily logs, knowledgebase) from the framework.
.PARAMETER Force
    If set, deletes and re-clones the memory directory even if it already exists.
.EXAMPLE
    .\scripts\sync-memory.ps1
    .\scripts\sync-memory.ps1 -Force
#>
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Resolve project root
if ($PSCommandPath) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
} else {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ConfigFile = Join-Path $ProjectRoot "agentconfig.json"
$MemoryDir  = Join-Path $ProjectRoot "memory"
$GitDir     = Join-Path $MemoryDir ".git"

# Load config
if (-not (Test-Path $ConfigFile)) {
    Write-Error "agentconfig.json not found at $ConfigFile"
    exit 1
}

$config  = Get-Content $ConfigFile -Raw | ConvertFrom-Json
$repoUrl = $config.memory.repo
$branch  = if ($config.memory.branch) { $config.memory.branch } else { "main" }

if (-not $repoUrl) {
    Write-Error "memory.repo is not configured in agentconfig.json"
    exit 1
}

Write-Host "Memory repo : $repoUrl"
Write-Host "Branch      : $branch"
Write-Host "Local path  : $MemoryDir"

# Force re-clone
if ($Force -and (Test-Path $MemoryDir)) {
    Write-Host "Force: removing existing memory directory..."
    Remove-Item -Recurse -Force $MemoryDir
}

# Clone or pull
$ErrorActionPreference = "Continue"

if (Test-Path $GitDir) {
    Write-Host "Pulling latest..."
    Push-Location $MemoryDir
    try {
        $pullOutput = git pull origin $branch 2>&1
        $pullOutput | Where-Object { $_ -is [string] } | Out-Host
        if ($LASTEXITCODE -ne 0) {
            $ErrorActionPreference = "Stop"
            throw "git pull failed"
        }
        Write-Host "Memory synced (pull)."
    } finally {
        Pop-Location
    }
} elseif (Test-Path $MemoryDir) {
    $ErrorActionPreference = "Stop"
    Write-Warning "memory/ exists but is not a git repo. Use -Force to replace it."
    exit 1
} else {
    Write-Host "Cloning memory repo..."
    $cloneOutput = git clone --branch $branch $repoUrl $MemoryDir 2>&1
    $cloneOutput | Where-Object { $_ -is [string] } | Out-Host
    if ($LASTEXITCODE -ne 0) {
        $ErrorActionPreference = "Stop"
        throw "git clone failed"
    }
    Write-Host "Memory synced (clone)."
}

$ErrorActionPreference = "Stop"

# Summary
$fileCount = (Get-ChildItem -Path $MemoryDir -Recurse -File -Exclude ".git*" | Measure-Object).Count
Write-Host "Files in memory/: $fileCount"
