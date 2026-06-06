# harden-permissions.ps1 - Restrict file system permissions on sensitive agent files
# Usage: powershell -ExecutionPolicy Bypass -File scripts/harden-permissions.ps1
#
# This script ensures only the current user has access to sensitive directories
# and files: memory/, CLAUDE.md, .copilot config, and task scheduler data.

param(
    [switch]$DryRun,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"

# Check for administrator privileges (required for Set-Acl / SeSecurityPrivilege)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin -and -not $DryRun) {
    Write-Host ""
    Write-Host "ERROR: This script requires administrator privileges." -ForegroundColor Red
    Write-Host "Run PowerShell as Administrator, or use -DryRun to preview changes." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Changes = 0
$Errors = 0

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  File Permission Hardening" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  User: $CurrentUser"
Write-Host "  Mode: $(if ($DryRun) { 'DRY RUN' } else { 'APPLY' })"
Write-Host ""

# Paths to harden (relative to project root)
$sensitivePaths = @(
    @{ Path = "memory";                       Desc = "Agent memory and knowledgebase" },
    @{ Path = "CLAUDE.md";                    Desc = "Agent identity file (auto-loaded)" },
    @{ Path = "skills\task-scheduler\tasks";  Desc = "Scheduled task definitions" },
    @{ Path = "skills\task-scheduler\logs";   Desc = "Task execution logs" }
)

# User-level config paths (absolute)
$userConfigPaths = @(
    @{ Path = "$env:USERPROFILE\.copilot\config.json";     Desc = "Copilot config" },
    @{ Path = "$env:USERPROFILE\.copilot\mcp-config.json"; Desc = "MCP server config" }
)

function Set-RestrictedAccess {
    param(
        [string]$TargetPath,
        [string]$Description,
        [switch]$IsFile
    )

    if (-not (Test-Path $TargetPath)) {
        if ($Verbose) { Write-Host "  [SKIP] $Description - path not found: $TargetPath" -ForegroundColor DarkGray }
        return
    }

    try {
        $acl = Get-Acl $TargetPath

        # Check if inheritance is already disabled and only current user has access
        $nonUserRules = $acl.Access | Where-Object {
            $_.IdentityReference.Value -ine $CurrentUser -and
            $_.IdentityReference.Value -ine "BUILTIN\Administrators" -and
            $_.IdentityReference.Value -ine "NT AUTHORITY\SYSTEM"
        }

        if ($nonUserRules.Count -eq 0 -and -not $acl.AreAccessRulesProtected -eq $false) {
            if ($Verbose) { Write-Host "  [OK]   $Description - already restricted" -ForegroundColor Green }
            return
        }

        if ($DryRun) {
            Write-Host "  [WOULD] Restrict $Description ($TargetPath)" -ForegroundColor Yellow
            $script:Changes++
            return
        }

        # Disable inheritance, preserving existing rules
        $acl.SetAccessRuleProtection($true, $true)

        # Remove all non-essential access rules
        $rulesToRemove = $acl.Access | Where-Object {
            $_.IdentityReference.Value -ine $CurrentUser -and
            $_.IdentityReference.Value -ine "BUILTIN\Administrators" -and
            $_.IdentityReference.Value -ine "NT AUTHORITY\SYSTEM"
        }

        foreach ($rule in $rulesToRemove) {
            $acl.RemoveAccessRule($rule) | Out-Null
        }

        # Ensure the current user has explicit FullControl (their access may have
        # come from an inherited group like BUILTIN\Users that we just removed)
        $existingUserRule = $acl.Access | Where-Object { $_.IdentityReference.Value -ieq $CurrentUser }
        if (-not $existingUserRule) {
            if ($IsFile) {
                $userRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                    $CurrentUser, "FullControl", "Allow"
                )
            } else {
                $userRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                    $CurrentUser, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow"
                )
            }
            $acl.AddAccessRule($userRule)
        }

        Set-Acl -Path $TargetPath -AclObject $acl
        Write-Host "  [DONE] Restricted $Description" -ForegroundColor Green
        $script:Changes++
    } catch {
        Write-Host "  [FAIL] $Description - $($_.Exception.Message)" -ForegroundColor Red
        $script:Errors++
    }
}

# Harden project-relative paths
Write-Host "Project files:" -ForegroundColor Yellow
foreach ($item in $sensitivePaths) {
    $fullPath = Join-Path $ProjectRoot $item.Path
    $isFile = -not (Test-Path $fullPath -PathType Container)
    Set-RestrictedAccess -TargetPath $fullPath -Description $item.Desc -IsFile:$isFile
}

# Harden user-level config files
Write-Host ""
Write-Host "User config files:" -ForegroundColor Yellow
foreach ($item in $userConfigPaths) {
    Set-RestrictedAccess -TargetPath $item.Path -Description $item.Desc -IsFile
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  Dry run complete. $Changes path(s) would be changed." -ForegroundColor Yellow
} elseif ($Errors -gt 0) {
    Write-Host "  Done with $Errors error(s). $Changes path(s) hardened." -ForegroundColor DarkYellow
} else {
    Write-Host "  Done. $Changes path(s) hardened. $Errors error(s)." -ForegroundColor Green
}
Write-Host ""
