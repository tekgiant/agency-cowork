<#
.SYNOPSIS
    Install prerequisites for Teams Rich Messaging (Playwright + Edge).
.DESCRIPTION
    Installs the Python dependencies for the Teams rich messaging engine
    and the Playwright Edge browser driver.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File skills\teams\scripts\setup-rich-messaging.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "=== Teams Rich Messaging Setup ===" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found. Install Python 3.10+ first." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python found: $($python.Source)" -ForegroundColor Green

# Install requirements
$reqFile = Join-Path $PSScriptRoot "..\requirements.txt"
if (Test-Path $reqFile) {
    Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
    & python -m pip install -r $reqFile --quiet
    Write-Host "[OK] Python dependencies installed" -ForegroundColor Green
} else {
    Write-Host "WARNING: requirements.txt not found at $reqFile" -ForegroundColor Yellow
    Write-Host "Installing playwright and python-dotenv directly..." -ForegroundColor Yellow
    & python -m pip install "playwright>=1.40" "python-dotenv>=1.0" --quiet
    Write-Host "[OK] Python dependencies installed" -ForegroundColor Green
}

# Install Playwright Edge browser
Write-Host "Installing Playwright Edge browser driver..." -ForegroundColor Yellow
& python -m playwright install msedge
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Playwright Edge installation failed." -ForegroundColor Red
    Write-Host "Make sure Microsoft Edge is installed on this machine." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Playwright Edge driver installed" -ForegroundColor Green

# Create browser profile directory
$profileDir = Join-Path $env:USERPROFILE ".teams-agent\browser-profile"
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    Write-Host "[OK] Created browser profile directory: $profileDir" -ForegroundColor Green
} else {
    Write-Host "[OK] Browser profile directory exists: $profileDir" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host "Test with: python skills/teams/scripts/rich/send_message.py --to `"48:notes`" --body `"**Test** message`"" -ForegroundColor White
Write-Host "First run may require interactive MFA in the Edge browser window." -ForegroundColor Yellow
