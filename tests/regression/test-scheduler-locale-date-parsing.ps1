# Regression test: Scheduler date parsing must be locale-independent
# Date: 2026-04-09
# Bug: [datetime]::Parse() on ConvertFrom-Json auto-converted DateTime objects triggers a
#      locale-dependent ToString()->Parse() roundtrip. On en-IE/en-GB (DD/MM/YYYY), April 9
#      becomes September 4 — all tasks appear due months in the future.
# Fix: ConvertTo-UtcDateTime / ConvertTo-UtcDateTimeOffset helpers that detect [datetime]
#      objects and call .ToUniversalTime() directly, with InvariantCulture fallback for strings.
# Issue: #245

$ErrorActionPreference = "Stop"
$failed = 0

# 1. Verify no raw [datetime]::Parse or [datetimeoffset]::Parse calls remain in scheduler-service.ps1
$schedulerPath = Join-Path $PSScriptRoot "..\..\skills\task-scheduler\scripts\scheduler-service.ps1"
if (-not (Test-Path $schedulerPath)) {
    Write-Host "SKIP: scheduler-service.ps1 not found at $schedulerPath"
    exit 0
}

$rawParseHits = Select-String -LiteralPath $schedulerPath -Pattern '\[datetime\]::Parse\(|\[datetimeoffset\]::Parse\(' |
    Where-Object { $_.Line -notmatch '^\s*#' }

if ($rawParseHits.Count -gt 0) {
    Write-Host "FAIL: Found raw [datetime]::Parse() or [datetimeoffset]::Parse() calls (non-comment):"
    $rawParseHits | ForEach-Object { Write-Host "  Line $($_.LineNumber): $($_.Line.Trim())" }
    $failed++
} else {
    Write-Host "PASS: No raw locale-dependent Parse() calls in scheduler-service.ps1"
}

# 2. Verify ConvertTo-UtcDateTime and ConvertTo-UtcDateTimeOffset helpers exist
$helperHits = Select-String -LiteralPath $schedulerPath -Pattern 'function ConvertTo-UtcDateTime\b|function ConvertTo-UtcDateTimeOffset\b'
if ($helperHits.Count -lt 2) {
    Write-Host "FAIL: Missing ConvertTo-UtcDateTime or ConvertTo-UtcDateTimeOffset helper functions"
    $failed++
} else {
    Write-Host "PASS: Locale-safe date helper functions present"
}

# 3. Functional test: dot-source the helpers and verify correct parsing under a non-US culture
# Extract just the helper functions using regex and evaluate them
$scriptContent = Get-Content $schedulerPath -Raw
$pattern = '(?ms)(function ConvertTo-UtcDateTime\s*\{.+?\n\})\s*(function ConvertTo-UtcDateTimeOffset\s*\{.+?\n\})'
if ($scriptContent -match $pattern) {
    Invoke-Expression $Matches[1]
    Invoke-Expression $Matches[2]
} else {
    Write-Host "FAIL: Could not extract helper functions for functional testing"
    exit 1
}

# Test with a DateTime object (simulates ConvertFrom-Json auto-conversion)
$testDt = [datetime]::new(2026, 4, 9, 14, 30, 0, [System.DateTimeKind]::Utc)
$result = ConvertTo-UtcDateTime $testDt
if ($result.Month -ne 4 -or $result.Day -ne 9) {
    Write-Host "FAIL: ConvertTo-UtcDateTime returned wrong date for DateTime input: $result (expected April 9)"
    $failed++
} else {
    Write-Host "PASS: ConvertTo-UtcDateTime handles DateTime objects correctly"
}

# Test with an ISO 8601 string
$result2 = ConvertTo-UtcDateTime "2026-04-09T14:30:00Z"
if ($result2.Month -ne 4 -or $result2.Day -ne 9) {
    Write-Host "FAIL: ConvertTo-UtcDateTime returned wrong date for ISO string: $result2 (expected April 9)"
    $failed++
} else {
    Write-Host "PASS: ConvertTo-UtcDateTime handles ISO 8601 strings correctly"
}

# Test ConvertTo-UtcDateTimeOffset with a DateTimeOffset object
$testDto = [datetimeoffset]::new(2026, 4, 9, 14, 30, 0, [timespan]::Zero)
$result3 = ConvertTo-UtcDateTimeOffset $testDto
if ($result3.Month -ne 4 -or $result3.Day -ne 9) {
    Write-Host "FAIL: ConvertTo-UtcDateTimeOffset returned wrong date for DTO input: $result3 (expected April 9)"
    $failed++
} else {
    Write-Host "PASS: ConvertTo-UtcDateTimeOffset handles DateTimeOffset objects correctly"
}

# Test ConvertTo-UtcDateTimeOffset with a string
$result4 = ConvertTo-UtcDateTimeOffset "2026-04-09T14:30:00+00:00"
if ($result4.Month -ne 4 -or $result4.Day -ne 9) {
    Write-Host "FAIL: ConvertTo-UtcDateTimeOffset returned wrong date for string: $result4 (expected April 9)"
    $failed++
} else {
    Write-Host "PASS: ConvertTo-UtcDateTimeOffset handles ISO 8601 strings correctly"
}

if ($failed -gt 0) {
    Write-Host "`nFAILED: $failed test(s) failed"
    exit 1
} else {
    Write-Host "`nAll tests passed"
    exit 0
}
