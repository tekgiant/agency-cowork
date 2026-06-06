# test-ps1-no-non-ascii.ps1
# Date: 2026-03-27
# Bug: #162 - Scheduler crashes on PS 5.1 due to em-dash encoding mismatch
# Root cause: Em-dash (U+2014) byte 0x94 maps to right double quote in Windows-1252,
#   injecting phantom quotes that break PS 5.1 string parsing.
# Fix: Replace all non-ASCII characters in .ps1 files with ASCII equivalents.
#   Files with UTF-8 BOM are exempt (PS 5.1 reads them as UTF-8 correctly).
#
# This test scans ALL .ps1 files in the repo for non-ASCII bytes (>127).
# Files with UTF-8 BOM (EF BB BF) are excluded since PS 5.1 handles them correctly.
# Also verifies all .ps1 files parse without errors under the current PowerShell.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$failed = $false
$scanned = 0
$bomExempt = 0

Write-Host "=== Test: No non-ASCII bytes in .ps1 files (issue #162) ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host ""

# --- Part 1: Scan for non-ASCII bytes ---

$ps1Files = Get-ChildItem -Path $RepoRoot -Recurse -Filter "*.ps1" |
    Where-Object { $_.FullName -notlike "*\node_modules\*" -and
                   $_.FullName -notlike "*\release\*" -and
                   $_.FullName -notlike "*\builds\*" -and
                   $_.FullName -notlike "*\.git\*" }

foreach ($file in $ps1Files) {
    $scanned++
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)

    # Check for UTF-8 BOM (EF BB BF) -- exempt these files
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bomExempt++
        continue
    }

    # Scan for non-ASCII bytes
    $violations = @()
    $lineNum = 1
    $lineStart = 0
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -eq 10) {
            $lineNum++
            $lineStart = $i + 1
        }
        elseif ($bytes[$i] -gt 127) {
            $col = $i - $lineStart + 1
            $violations += [PSCustomObject]@{
                Line = $lineNum
                Col  = $col
                Byte = "0x{0:X2}" -f $bytes[$i]
            }
        }
    }

    if ($violations.Count -gt 0) {
        $failed = $true
        $relPath = $file.FullName.Substring($RepoRoot.Length + 1)
        Write-Host "  FAIL  $relPath ($($violations.Count) non-ASCII bytes)" -ForegroundColor Red
        $violations | Select-Object -First 5 | ForEach-Object {
            Write-Host "         Line $($_.Line), Col $($_.Col): byte $($_.Byte)" -ForegroundColor Yellow
        }
        if ($violations.Count -gt 5) {
            Write-Host "         ... and $($violations.Count - 5) more" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Scanned: $scanned files ($bomExempt BOM-exempt)" -ForegroundColor Gray

# --- Part 2: Parse validation ---

Write-Host ""
Write-Host "=== Test: All .ps1 files parse without errors ===" -ForegroundColor Cyan

$parseFailures = 0
foreach ($file in $ps1Files) {
    $errors = $null
    $tokens = $null
    try {
        [System.Management.Automation.Language.Parser]::ParseFile(
            $file.FullName, [ref]$tokens, [ref]$errors
        ) | Out-Null
    } catch {
        $errors = @($_)
    }
    if ($errors -and $errors.Count -gt 0) {
        $failed = $true
        $parseFailures++
        $relPath = $file.FullName.Substring($RepoRoot.Length + 1)
        Write-Host "  FAIL  $relPath ($($errors.Count) parse errors)" -ForegroundColor Red
        $errors | Select-Object -First 3 | ForEach-Object {
            $msg = if ($_.Extent) { "Line $($_.Extent.StartLineNumber): $($_.Message)" } else { "$_" }
            Write-Host "         $msg" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
if ($failed) {
    Write-Host "FAILED: Non-ASCII bytes or parse errors found in .ps1 files." -ForegroundColor Red
    Write-Host "Fix: Replace non-ASCII chars with ASCII equivalents, or add UTF-8 BOM." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "PASSED: All $scanned .ps1 files are ASCII-clean and parse without errors." -ForegroundColor Green
    exit 0
}
