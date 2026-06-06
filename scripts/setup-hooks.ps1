# setup-hooks.ps1 - Install git hooks for the Agency-Cowork repository
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup-hooks.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$HooksDir = Join-Path $ProjectRoot ".git\hooks"
$SourceHook = Join-Path $ProjectRoot "scripts\pre-commit"
$DestHook = Join-Path $HooksDir "pre-commit"

if (-not (Test-Path $HooksDir)) {
    Write-Host "Error: .git/hooks directory not found. Is this a git repository?" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $SourceHook)) {
    Write-Host "Error: scripts/pre-commit not found." -ForegroundColor Red
    exit 1
}

Copy-Item -Path $SourceHook -Destination $DestHook -Force
Write-Host "Installed pre-commit hook to .git/hooks/pre-commit" -ForegroundColor Green

# Verify the hook is in place
if (Test-Path $DestHook) {
    Write-Host "Hook installed successfully." -ForegroundColor Green
} else {
    Write-Host "Error: Hook installation failed." -ForegroundColor Red
    exit 1
}
