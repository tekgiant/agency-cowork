# upload-to-sharepoint.ps1: Upload a local file to SharePoint/OneDrive via Microsoft Graph API
# Companion to download-from-sharepoint.ps1
#
# Uses Azure CLI (az) to obtain a Graph API access token, then uploads the file.
# - Files <=4MB: simple PUT upload
# - Files >4MB: resumable upload session with chunked PUT (3.75MB chunks)
#
# Supports personal OneDrive via -DriveId "me"

param(
    [Parameter(Mandatory=$true)]
    [string]$InputFile,

    [Parameter(Mandatory=$true)]
    [string]$DriveId,

    [Parameter(Mandatory=$false)]
    [string]$ParentFolderId = "root",

    [Parameter(Mandatory=$false)]
    [string]$FileName,

    [Parameter(Mandatory=$false)]
    [ValidateSet("rename", "replace", "fail")]
    [string]$ConflictBehavior = "rename",

    [Parameter(Mandatory=$false)]
    [int]$TimeoutSec = 600
)

$ErrorActionPreference = "Stop"

# Constants
$SIMPLE_UPLOAD_MAX = 4 * 1MB          # 4 MB -- Graph API simple upload limit
$CHUNK_SIZE        = 3932160           # 3.75 MB (3840 KiB) -- must be multiple of 320 KiB

try {
    # --- Validate input file ---
    if (-not (Test-Path $InputFile -PathType Leaf)) {
        Write-Warning "Input file not found: $InputFile"
        exit 1
    }
    $fileInfo = Get-Item $InputFile
    $fileSize = $fileInfo.Length
    $sizeMB = [math]::Round($fileSize / 1MB, 2)

    # Use provided filename or fall back to input filename
    if (-not $FileName) {
        $FileName = $fileInfo.Name
    }

    # --- Get Graph API token ---
    $azPath = Get-Command az -ErrorAction SilentlyContinue
    if (-not $azPath) {
        Write-Warning "Azure CLI (az) is not installed or not on PATH."
        Write-Warning "Install it from: https://learn.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    }

    Write-Host "Obtaining Graph API access token..."
    $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to obtain access token. Run 'az login' first."
        Write-Warning $token
        exit 1
    }
    $authHeaders = @{ "Authorization" = "Bearer $token" }

    # --- Build base URL ---
    if ($DriveId -eq "me") {
        $driveBase = "https://graph.microsoft.com/v1.0/me/drive"
    } else {
        $driveBase = "https://graph.microsoft.com/v1.0/drives/$DriveId"
    }

    # Build the item path segment
    if ($ParentFolderId -eq "root") {
        $itemPath = "$driveBase/root:/${FileName}:"
    } else {
        $itemPath = "$driveBase/items/${ParentFolderId}:/${FileName}:"
    }

    Write-Host "Uploading to Graph API..."
    Write-Host "  File:     $InputFile ($sizeMB MB)"
    Write-Host "  Drive:    $DriveId"
    Write-Host "  Folder:   $ParentFolderId"
    Write-Host "  Filename: $FileName"
    Write-Host "  Conflict: $ConflictBehavior"

    # --- Simple upload (<=4MB) ---
    if ($fileSize -le $SIMPLE_UPLOAD_MAX) {
        Write-Host "  Method:   Simple PUT upload"

        $uploadUrl = "${itemPath}/content?@microsoft.graph.conflictBehavior=$ConflictBehavior"
        $contentType = "application/octet-stream"
        $fileBytes = [System.IO.File]::ReadAllBytes($fileInfo.FullName)

        $response = Invoke-RestMethod -Uri $uploadUrl -Method PUT -Headers $authHeaders `
            -ContentType $contentType -Body $fileBytes -TimeoutSec $TimeoutSec

        Write-Host ""
        Write-Host "Upload complete!"
        Write-Host "  Name:    $($response.name)"
        Write-Host "  Size:    $([math]::Round($response.size / 1MB, 2)) MB"
        Write-Host "  WebUrl:  $($response.webUrl)"
        Write-Host "  DriveId: $($response.parentReference.driveId)"
        Write-Host "  ItemId:  $($response.id)"

        # Output structured data for script consumers
        $result = @{
            name    = $response.name
            size    = $response.size
            webUrl  = $response.webUrl
            driveId = $response.parentReference.driveId
            itemId  = $response.id
        }
        $result | ConvertTo-Json -Compress
        exit 0
    }

    # --- Resumable upload session (>4MB) ---
    Write-Host "  Method:   Resumable upload session (chunked)"

    # Create upload session
    $sessionUrl = "${itemPath}/createUploadSession"
    $sessionBody = @{
        item = @{
            "@microsoft.graph.conflictBehavior" = $ConflictBehavior
            name = $FileName
        }
    } | ConvertTo-Json -Depth 3

    $session = Invoke-RestMethod -Uri $sessionUrl -Method POST -Headers $authHeaders `
        -ContentType "application/json" -Body $sessionBody -TimeoutSec $TimeoutSec

    $uploadUrl = $session.uploadUrl
    if (-not $uploadUrl) {
        Write-Warning "Failed to create upload session -- no uploadUrl returned."
        exit 1
    }

    Write-Host "  Upload session created. Uploading in chunks..."

    # Upload file in chunks
    $stream = [System.IO.File]::OpenRead($fileInfo.FullName)
    try {
        $offset = 0
        $chunkNumber = 0
        $totalChunks = [math]::Ceiling($fileSize / $CHUNK_SIZE)
        $buffer = New-Object byte[] $CHUNK_SIZE

        while ($offset -lt $fileSize) {
            $chunkNumber++
            $bytesToRead = [math]::Min($CHUNK_SIZE, $fileSize - $offset)
            $bytesRead = $stream.Read($buffer, 0, $bytesToRead)

            $rangeEnd = $offset + $bytesRead - 1
            $contentRange = "bytes $offset-$rangeEnd/$fileSize"

            Write-Host "  Chunk $chunkNumber/$totalChunks : $contentRange"

            # Extract exact chunk bytes
            $chunkBytes = New-Object byte[] $bytesRead
            [Array]::Copy($buffer, $chunkBytes, $bytesRead)

            # Upload chunk -- note: upload URL has its own auth, no Bearer needed
            $chunkResponse = Invoke-RestMethod -Uri $uploadUrl -Method PUT `
                -ContentType "application/octet-stream" `
                -Headers @{ "Content-Range" = $contentRange } `
                -Body $chunkBytes -TimeoutSec $TimeoutSec

            $offset += $bytesRead

            # The final chunk returns the completed DriveItem
            if ($offset -ge $fileSize -and $chunkResponse.id) {
                Write-Host ""
                Write-Host "Upload complete!"
                Write-Host "  Name:    $($chunkResponse.name)"
                Write-Host "  Size:    $([math]::Round($chunkResponse.size / 1MB, 2)) MB"
                Write-Host "  WebUrl:  $($chunkResponse.webUrl)"
                Write-Host "  DriveId: $($chunkResponse.parentReference.driveId)"
                Write-Host "  ItemId:  $($chunkResponse.id)"

                $result = @{
                    name    = $chunkResponse.name
                    size    = $chunkResponse.size
                    webUrl  = $chunkResponse.webUrl
                    driveId = $chunkResponse.parentReference.driveId
                    itemId  = $chunkResponse.id
                }
                $result | ConvertTo-Json -Compress
            }
        }
    } finally {
        $stream.Close()
        $stream.Dispose()
    }

    exit 0

} catch {
    Write-Warning "Upload failed: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $errorBody = $reader.ReadToEnd()
            Write-Warning "Response: $errorBody"
        } catch { }
    }
    exit 1
}
