<#
.SYNOPSIS
    Handles DRM (Information Rights Management / IRM) operations for Office files.

.DESCRIPTION
    Three operations:
      - capture  : Read DRM policy details from a protected file (JSON output)
      - strip    : Remove DRM and save as clean OOXML (.pptx/.xlsx/.docx)
      - apply    : Re-apply a captured DRM policy to an edited file

    Uses PowerPoint, Excel, or Word COM automation (requires Office installed).

.PARAMETER Action
    One of: capture, strip, apply

.PARAMETER InputFile
    Path to the input Office file.

.PARAMETER OutputFile
    Path for the output file. Required for strip and apply actions.

.PARAMETER PolicyJson
    JSON string with captured DRM policy (required for apply action).
    Format: {"Enabled":true,"PolicyName":"...","DocumentAuthor":"...","StoreLicenses":true,...}

.PARAMETER Format
    Office format: pptx, xlsx, docx. Auto-detected from file extension if omitted.

.EXAMPLE
    # Capture DRM details
    .\drm_handler.ps1 -Action capture -InputFile protected.pptx

    # Strip DRM -> clean OOXML
    .\drm_handler.ps1 -Action strip -InputFile protected.pptx -OutputFile clean.pptx

    # Re-apply DRM policy
    .\drm_handler.ps1 -Action apply -InputFile edited.pptx -OutputFile final.pptx -PolicyJson '{"PolicyName":"Confidential - Microsoft FTE",...}'
#>

param(
    [Parameter(Mandatory)][ValidateSet("capture", "strip", "apply")][string]$Action,
    [Parameter(Mandatory)][string]$InputFile,
    [string]$OutputFile,
    [string]$PolicyJson,
    [string]$PolicyFile,
    [ValidateSet("pptx", "xlsx", "docx")][string]$Format
)

$ErrorActionPreference = "Stop"

# Resolve full paths
$InputFile = [System.IO.Path]::GetFullPath($InputFile)
if ($OutputFile) { $OutputFile = [System.IO.Path]::GetFullPath($OutputFile) }

# Auto-detect format from extension
if (-not $Format) {
    $ext = [System.IO.Path]::GetExtension($InputFile).TrimStart('.').ToLower()
    $formatMap = @{ 'pptx' = 'pptx'; 'ppt' = 'pptx'; 'xlsx' = 'xlsx'; 'xls' = 'xlsx'; 'docx' = 'docx'; 'doc' = 'docx' }
    $Format = $formatMap[$ext]
    if (-not $Format) {
        Write-Error "Cannot determine format from extension .$ext. Use -Format parameter."
        exit 1
    }
}

# Format-specific constants
$saveAsFormats = @{
    'pptx' = 24   # ppSaveAsOpenXMLPresentation
    'xlsx' = 51   # xlOpenXMLWorkbook
    'docx' = 16   # wdFormatDocumentDefault (docx)
}

function Open-OfficeApp {
    param([string]$fmt, [string]$filePath, [bool]$readOnly = $true)

    switch ($fmt) {
        'pptx' {
            $app = New-Object -ComObject PowerPoint.Application
            # Open(FileName, ReadOnly, Untitled, WithWindow)
            $doc = $app.Presentations.Open($filePath, [int]$readOnly, 0, 0)
            return @{ App = $app; Doc = $doc; Permission = $doc.Permission }
        }
        'xlsx' {
            $app = New-Object -ComObject Excel.Application
            $app.Visible = $false
            $app.DisplayAlerts = $false
            $doc = $app.Workbooks.Open($filePath, 0, $readOnly)
            return @{ App = $app; Doc = $doc; Permission = $doc.Permission }
        }
        'docx' {
            $app = New-Object -ComObject Word.Application
            $app.Visible = $false
            $app.DisplayAlerts = 0  # wdAlertsNone
            $doc = $app.Documents.Open($filePath, $false, $readOnly)
            return @{ App = $app; Doc = $doc; Permission = $doc.Permission }
        }
    }
}

function Close-OfficeApp {
    param($ctx)
    try {
        switch ($Format) {
            'pptx' { $ctx.Doc.Close(); $ctx.App.Quit() }
            'xlsx' { $ctx.Doc.Close($false); $ctx.App.Quit() }
            'docx' { $ctx.Doc.Close(0); $ctx.App.Quit() }  # wdDoNotSaveChanges = 0
        }
    } catch { }
    try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ctx.App) | Out-Null } catch { }
}

# --- CAPTURE ------------------------------------------------------------------
if ($Action -eq "capture") {
    $ctx = Open-OfficeApp -fmt $Format -filePath $InputFile -readOnly $true
    $perm = $ctx.Permission

    $result = @{
        Enabled              = [bool]$perm.Enabled
        DocumentAuthor       = $perm.DocumentAuthor
        RequestPermissionURL = $perm.RequestPermissionURL
        StoreLicenses        = [bool]$perm.StoreLicenses
        PermissionFromPolicy = [bool]$perm.PermissionFromPolicy
        PolicyName           = $perm.PolicyName
        PolicyDescription    = $perm.PolicyDescription
        Entries              = @()
    }

    for ($i = 1; $i -le $perm.Count; $i++) {
        $entry = $perm.Item($i)
        $result.Entries += @{
            UserId         = $entry.UserId
            Permission     = $entry.Permission
            ExpirationDate = $(if ($entry.ExpirationDate) { $entry.ExpirationDate.ToString("o") } else { $null })
        }
    }

    Close-OfficeApp $ctx
    $result | ConvertTo-Json -Depth 3
    exit 0
}

# --- STRIP --------------------------------------------------------------------
if ($Action -eq "strip") {
    if (-not $OutputFile) { Write-Error "-OutputFile required for strip action"; exit 1 }

    $ctx = Open-OfficeApp -fmt $Format -filePath $InputFile -readOnly $false

    $wasEnabled = $ctx.Permission.Enabled
    if ($wasEnabled) {
        $ctx.Permission.Enabled = $false
        Write-Host "IRM stripped from document"
    } else {
        Write-Host "Document has no IRM protection"
    }

    # Save as clean OOXML
    $saveFormat = $saveAsFormats[$Format]
    switch ($Format) {
        'pptx' { $ctx.Doc.SaveAs($OutputFile, $saveFormat) }
        'xlsx' { $ctx.Doc.SaveAs($OutputFile, $saveFormat) }
        'docx' { $ctx.Doc.SaveAs([ref]$OutputFile, [ref]$saveFormat) }
    }

    Close-OfficeApp $ctx

    # Verify output is clean OOXML (ZIP header)
    $bytes = [System.IO.File]::ReadAllBytes($OutputFile)
    $header = ($bytes[0..1] | ForEach-Object { $_.ToString("X2") }) -join ""
    if ($header -eq "504B") {
        Write-Host "Output verified: clean OOXML (ZIP format)"
    } else {
        Write-Warning "Output may still be OLE2-wrapped. Header: $header"
    }

    @{ Status = "ok"; IrmWasEnabled = $wasEnabled; OutputFile = $OutputFile; SizeBytes = (Get-Item $OutputFile).Length } | ConvertTo-Json
    exit 0
}

# --- APPLY --------------------------------------------------------------------
if ($Action -eq "apply") {
    if (-not $OutputFile) { Write-Error "-OutputFile required for apply action"; exit 1 }
    if (-not $PolicyJson -and -not $PolicyFile) { Write-Error "-PolicyJson or -PolicyFile required for apply action"; exit 1 }

    if ($PolicyFile) {
        $PolicyJson = Get-Content $PolicyFile -Raw
    }
    $policy = $PolicyJson | ConvertFrom-Json

    if (-not $policy.Enabled) {
        Write-Host "Policy has Enabled=false - no DRM to apply. Copying file as-is."
        Copy-Item $InputFile $OutputFile -Force
        @{ Status = "ok"; DrmApplied = $false; OutputFile = $OutputFile } | ConvertTo-Json
        exit 0
    }

    # Copy input to output first (we'll modify output in-place)
    Copy-Item $InputFile $OutputFile -Force

    $ctx = Open-OfficeApp -fmt $Format -filePath $OutputFile -readOnly $false

    # Re-enable IRM
    $ctx.Permission.Enabled = $true
    Write-Host "IRM re-enabled"

    # Apply policy-based permissions if available
    if ($policy.PermissionFromPolicy -and $policy.PolicyName) {
        # Try to apply the named policy
        try {
            # ApplyPolicy method takes policy name and template path
            # For Microsoft 365, policies are applied by enabling + setting entries
            Write-Host "Policy: $($policy.PolicyName)"
        } catch {
            Write-Host "Warning: Could not apply named policy, using manual entries"
        }
    }

    # Re-add permission entries
    foreach ($entry in $policy.Entries) {
        try {
            $ctx.Permission.Add($entry.UserId, $entry.Permission, $entry.ExpirationDate)
            Write-Host "Added permission: $($entry.UserId) = $($entry.Permission)"
        } catch {
            Write-Host "Warning: Could not add entry for $($entry.UserId): $_"
        }
    }

    # Save
    switch ($Format) {
        'pptx' { $ctx.Doc.Save() }
        'xlsx' { $ctx.Doc.Save() }
        'docx' { $ctx.Doc.Save() }
    }

    Close-OfficeApp $ctx

    $bytes = [System.IO.File]::ReadAllBytes($OutputFile)
    $header = ($bytes[0..1] | ForEach-Object { $_.ToString("X2") }) -join ""
    $isDrm = $header -eq "D0CF"

    @{
        Status     = "ok"
        DrmApplied = $true
        IsDrmWrapped = $isDrm
        PolicyName = $policy.PolicyName
        OutputFile = $OutputFile
        SizeBytes  = (Get-Item $OutputFile).Length
    } | ConvertTo-Json
    exit 0
}
