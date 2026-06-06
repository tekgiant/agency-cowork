#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Ensures all skills with .claude-plugin/plugin.json in the working directory
    are registered in ~/.copilot/config.json as installed_plugins.

.DESCRIPTION
    Scans the skills/ directory for subdirectories containing .claude-plugin/plugin.json,
    reads the plugin name and version, then merges them into the Copilot CLI config.
    Existing plugins (marketplace or local from other directories) are preserved.
    Runs idempotently -- safe to call on every app startup.

.PARAMETER WorkDir
    The project working directory containing the skills/ folder.
    Defaults to current directory.

.PARAMETER Quiet
    Suppress non-error output.
#>
param(
    [string]$WorkDir = (Get-Location).Path,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$skillsDir = Join-Path $WorkDir "skills"
if (-not (Test-Path $skillsDir)) {
    if (-not $Quiet) { Write-Host "[skill-sync] No skills/ directory found in $WorkDir" }
    exit 0
}

$copilotConfig = Join-Path $env:USERPROFILE ".copilot" "config.json"
if (-not (Test-Path $copilotConfig)) {
    if (-not $Quiet) { Write-Host "[skill-sync] Copilot config not found at $copilotConfig -- skipping" }
    exit 0
}

# Discover all registrable skills (have .claude-plugin/plugin.json)
$discovered = @()
$skillDirs = Get-ChildItem $skillsDir -Directory
foreach ($dir in $skillDirs) {
    $pluginJson = Join-Path $dir.FullName ".claude-plugin" "plugin.json"
    if (Test-Path $pluginJson) {
        $skillName = $dir.Name
        $skillVersion = "1.0.0"
        try {
            $meta = Get-Content $pluginJson -Raw | ConvertFrom-Json
            if ($meta.name) { $skillName = $meta.name }
            if ($meta.version) { $skillVersion = $meta.version }
        } catch { }
        $discovered += @{
            name = $skillName
            version = $skillVersion
            path = $dir.FullName
        }
    }
}

if ($discovered.Count -eq 0) {
    if (-not $Quiet) { Write-Host "[skill-sync] No skills with plugin.json found" }
    exit 0
}

# Load current config
$config = Get-Content $copilotConfig -Raw | ConvertFrom-Json

# Get existing installed_plugins
$existingPlugins = @()
if ($config.PSObject.Properties['installed_plugins']) {
    $existingPlugins = @($config.installed_plugins)
}

# Build a lookup of currently registered local plugins by cache_path
$registeredPaths = @{}
$existingPlugins | Where-Object { $_.marketplace -eq "local" } | ForEach-Object {
    $normPath = ($_.cache_path -replace '\\\\', '\') -replace '/$', ''
    $registeredPaths[$normPath] = $true
}

# Find skills that need to be registered
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$newEntries = @()
$discoveredNames = @()

foreach ($skill in $discovered) {
    $discoveredNames += $skill.name
    $normPath = $skill.path -replace '/$', ''
    
    # Check if already registered (by path or name)
    $alreadyByPath = $registeredPaths.ContainsKey($normPath)
    $alreadyByName = $existingPlugins | Where-Object { $_.name -eq $skill.name -and $_.marketplace -eq "local" }
    
    if (-not $alreadyByPath -and -not $alreadyByName) {
        $escapedPath = $skill.path -replace '\\', '\\\\'
        $newEntries += @{
            name = $skill.name
            marketplace = "local"
            version = $skill.version
            installed_at = $timestamp
            enabled = $true
            cache_path = $escapedPath
        }
    }
}

if ($newEntries.Count -eq 0) {
    if (-not $Quiet) { Write-Host "[skill-sync] All $($discovered.Count) skills already registered" }
    exit 0
}

# Merge: keep all existing plugins, add new ones
$allPlugins = $existingPlugins + $newEntries
$config | Add-Member -NotePropertyName "installed_plugins" -NotePropertyValue $allPlugins -Force
$config | ConvertTo-Json -Depth 10 | Set-Content $copilotConfig

if (-not $Quiet) {
    $newCount = $newEntries.Count
    $totalCount = $discovered.Count
    $msg = "[skill-sync] Registered $newCount new skills, $totalCount total discovered:"
    Write-Host $msg
    foreach ($entry in $newEntries) {
        $eName = $entry.name
        Write-Host "    + $eName"
    }
}
