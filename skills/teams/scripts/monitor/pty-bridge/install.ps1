# Install script for the PTY bridge (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1
param(
    [switch]$UsePrebuilts
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "=== Agency PTY Bridge - Install ===" -ForegroundColor Cyan

# Verify node is available
$nodePath = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodePath) {
    Write-Host "ERROR: Node.js not found on PATH." -ForegroundColor Red
    Write-Host "Install Node.js 18+ from https://nodejs.org"
    exit 1
}

$nodeVersion = & node -v
Write-Host "Node.js version: $nodeVersion"

# Install dependencies
Write-Host "Installing dependencies..."
& npm install --production --no-audit --no-fund 2>&1 | Write-Host

# Optionally copy prebuilt node-pty binaries from ui/prebuilds/
# This avoids needing native build tools (Visual Studio, Python, etc.)
$prebuildsDir = Join-Path $ScriptDir ".." ".." ".." ".." "ui" "prebuilds"
if ($UsePrebuilts -or (-not (Test-Path (Join-Path $ScriptDir "node_modules" "@homebridge" "node-pty-prebuilt-multiarch" "build")))) {
    if (Test-Path $prebuildsDir) {
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "win32-arm64" } else { "win32-x64" }
        $srcDir = Join-Path $prebuildsDir $arch
        if (Test-Path $srcDir) {
            $destDir = Join-Path $ScriptDir "node_modules" "@homebridge" "node-pty-prebuilt-multiarch" "build" "Release"
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            Copy-Item (Join-Path $srcDir "pty.node") $destDir -Force
            Copy-Item (Join-Path $srcDir "conpty.node") $destDir -Force
            Copy-Item (Join-Path $srcDir "conpty_console_list.node") $destDir -Force -ErrorAction SilentlyContinue
            Write-Host "Copied prebuilt node-pty binaries from ui/prebuilds/$arch" -ForegroundColor Green
        } else {
            Write-Host "WARNING: Prebuilts for $arch not found at $srcDir" -ForegroundColor Yellow
        }
    } else {
        Write-Host "NOTE: No prebuilds directory found. node-pty will use npm-installed binaries." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "PTY bridge installed successfully." -ForegroundColor Green
Write-Host "  Start with: node bridge.js"
Write-Host "  Or via the Electron UI Monitor panel."
