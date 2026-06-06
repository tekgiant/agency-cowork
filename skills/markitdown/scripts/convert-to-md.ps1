# convert-to-md: Convert a document to Markdown using MarkItDown
# Invoked via /markitdown skill
#
# Handles old .doc (OLE2) files that have a .docx extension by
# converting them to HTML via Word COM automation first, then
# running markitdown on the HTML.

param(
    [Parameter(Mandatory=$true)]
    [string]$InputFile,

    [Parameter(Mandatory=$false)]
    [string]$OutputFile
)

$ErrorActionPreference = "Stop"

function Test-OLE2Format([string]$FilePath) {
    # OLE2 Compound Document magic bytes: D0 CF 11 E0 A1 B1 1A E1
    $fs = $null
    try {
        $fs = [System.IO.FileStream]::new($FilePath, [System.IO.FileMode]::Open,
              [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $bytes = New-Object byte[] 8
        $read = $fs.Read($bytes, 0, 8)
        if ($read -lt 4) { return $false }
        return ($bytes[0] -eq 0xD0 -and $bytes[1] -eq 0xCF -and
                $bytes[2] -eq 0x11 -and $bytes[3] -eq 0xE0)
    } finally {
        if ($fs) { $fs.Dispose() }
    }
}

function Convert-OLE2ToHTML([string]$FilePath) {
    # Use Word COM automation to export OLE2 .doc files as filtered HTML.
    # Copies the source file to temp first to avoid lock conflicts.
    $word = $null
    $doc = $null
    $tempCopy = Join-Path $env:TEMP "markitdown_src_$(Get-Random).doc"
    $htmlPath = Join-Path $env:TEMP "markitdown_ole2_$(Get-Random).html"
    try {
        Copy-Item -Path $FilePath -Destination $tempCopy -Force
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0  # wdAlertsNone
        $word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        # Open with explicit params: ConfirmConversions=false, ReadOnly=true, AddToRecentFiles=false
        $doc = $word.Documents.Open($tempCopy, $false, $true, $false)
        # wdFormatFilteredHTML = 10 (clean HTML without Office XML)
        $doc.SaveAs2($htmlPath, 10)
        $doc.Close(0)  # wdDoNotSaveChanges
        $word.Quit(0)
        Write-Host "OLE2 file exported to HTML via Word COM"
        return $htmlPath
    } catch {
        throw "Word COM conversion failed: $($_.Exception.Message). Ensure Microsoft Word is installed."
    } finally {
        if ($doc) { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) | Out-Null } catch {} }
        if ($word) { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null } catch {} }
        Remove-Item $tempCopy -Force -ErrorAction SilentlyContinue
    }
}

try {
    # Verify input file exists
    if (-not (Test-Path $InputFile)) {
        Write-Warning "Input file not found: $InputFile"
        exit 1
    }

    $resolvedInput = (Resolve-Path $InputFile).Path

    # Determine output file path
    if (-not $OutputFile) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedInput)
        $OutputFile = Join-Path "memory\Knowledgebase" "$baseName.md"
    }

    # Verify markitdown is installed
    $markitdownPath = (Get-Command markitdown -ErrorAction SilentlyContinue)
    if (-not $markitdownPath) {
        Write-Warning "markitdown is not installed. Install it with: pip install 'markitdown[all]'"
        exit 1
    }

    $convertInput = $resolvedInput
    $tempHtml = $null

    # Detect OLE2 .doc files masquerading as .docx
    $ext = [System.IO.Path]::GetExtension($resolvedInput).ToLower()
    if ($ext -in @('.docx', '.doc') -and (Test-OLE2Format $resolvedInput)) {
        Write-Host "Detected OLE2 (legacy .doc) format - converting via Word COM first..."
        $tempHtml = Convert-OLE2ToHTML $resolvedInput
        $convertInput = $tempHtml
    }

    # Run markitdown conversion
    Write-Host "Converting: $convertInput"
    markitdown $convertInput -o $OutputFile
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "markitdown conversion failed with exit code $LASTEXITCODE"
        exit 1
    }

    # Verify output was created
    if (Test-Path $OutputFile) {
        $fileSize = (Get-Item $OutputFile).Length
        Write-Host "Converted successfully: $OutputFile ($fileSize bytes)"
    } else {
        Write-Warning "Output file was not created: $OutputFile"
        exit 1
    }

    exit 0

} catch {
    Write-Warning "Conversion failed: $($_.Exception.Message)"
    exit 1
} finally {
    # Clean up temp HTML and its companion files folder
    if ($tempHtml -and (Test-Path $tempHtml)) {
        Remove-Item $tempHtml -Force -ErrorAction SilentlyContinue
        $filesDir = [System.IO.Path]::ChangeExtension($tempHtml, $null).TrimEnd('.') + "_files"
        if (Test-Path $filesDir) {
            Remove-Item $filesDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
