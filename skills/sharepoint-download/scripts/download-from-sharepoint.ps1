# download-from-sharepoint: Download a file from SharePoint via Microsoft Graph API
# Invoked via /sharepoint skill
#
# Uses Azure CLI (az) to obtain a Graph API access token, then downloads the file
# by driveId + itemId. This bypasses the 5 MB limit of the SharePoint MCP read tools.

param(
    [Parameter(Mandatory=$true)]
    [string]$DriveId,

    [Parameter(Mandatory=$true)]
    [string]$ItemId,

    [Parameter(Mandatory=$true)]
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [int]$TimeoutSec = 600
)

$ErrorActionPreference = "Stop"

try {
    # Verify Azure CLI is available
    $azPath = Get-Command az -ErrorAction SilentlyContinue
    if (-not $azPath) {
        Write-Warning "Azure CLI (az) is not installed or not on PATH."
        Write-Warning "Install it from: https://learn.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    }

    # Obtain a Graph API access token via Azure CLI
    Write-Host "Obtaining Graph API access token..."
    $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to obtain access token. Run 'az login' first."
        Write-Warning $token
        exit 1
    }

    # Ensure output directory exists
    $outputDir = Split-Path -Parent $OutputFile
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }

    # Download via Graph API
    $graphUrl = "https://graph.microsoft.com/v1.0/drives/$DriveId/items/$ItemId/content"
    $headers = @{ "Authorization" = "Bearer $token" }

    Write-Host "Downloading from Graph API..."
    Write-Host "  Drive:  $DriveId"
    Write-Host "  Item:   $ItemId"
    Write-Host "  Output: $OutputFile"

    Invoke-WebRequest -Uri $graphUrl -Headers $headers -OutFile $OutputFile -TimeoutSec $TimeoutSec

    # Verify download
    if (Test-Path $OutputFile) {
        $fileSize = (Get-Item $OutputFile).Length
        $sizeMB = [math]::Round($fileSize / 1MB, 1)
        Write-Host "Download complete: $OutputFile ($sizeMB MB)"
        exit 0
    } else {
        Write-Warning "Download failed - output file was not created."
        exit 1
    }

} catch {
    Write-Warning "Download failed: $($_.Exception.Message)"
    exit 1
}
