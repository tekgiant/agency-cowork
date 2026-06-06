<#
.SYNOPSIS
    Retrieves, replies to, and forwards emails from the local Outlook desktop
    client via COM automation.  Use as a fallback when the Outlook Mail MCP
    tools fail due to special characters (e.g., '/') in Graph API message IDs.

.DESCRIPTION
    Supports two modes controlled by -Action:

    Search (default) - Searches the Outlook mailbox using subject, sender,
      date range, and/or internet message ID filters.

    Reply / ReplyAll / Forward - Looks up an email by its Outlook EntryID
      (returned from a prior Search), composes a reply or forward with the
      supplied body text, and sends it.

    Returns results as JSON for easy consumption by the agent.

    MailItem API reference:
    https://learn.microsoft.com/en-us/dotnet/api/microsoft.office.interop.outlook.mailitem?view=outlook-pia

.NOTES
    DASL filter gotchas:
    - Date values MUST use 'yyyy-MM-dd HH:mm:ss' format. ISO 8601 with T/Z
      (e.g., '2026-03-01T08:00:00Z') silently breaks the ENTIRE filter,
      causing Restrict() to return all items instead of filtered results.
    - The From filter uses urn:schemas:httpmail:sendername (display name) and
      urn:schemas:httpmail:fromemail (which contains X500 addresses for Exchange
      users, NOT SMTP addresses). Always filter by display name, not SMTP.
    - If any single clause in a combined DASL AND filter is malformed, the
      entire filter silently fails and Restrict() returns all items.

.PARAMETER Action
    Operation to perform: 'Search' (default), 'Reply', 'ReplyAll', 'Forward'.

.PARAMETER EntryId
    Outlook EntryID of the email to reply to or forward.  Required for
    Reply, ReplyAll, and Forward actions.  Obtain from a prior Search result's
    'entryId' field.

.PARAMETER ReplyBody
    Body text to prepend above the quoted thread when replying or forwarding.

.PARAMETER ForwardTo
    Comma-separated list of SMTP email addresses for the Forward action.

.PARAMETER Subject
    (Search) Partial or full subject line to match.

.PARAMETER From
    (Search) Sender email address or display name to filter by.

.PARAMETER ReceivedAfter
    (Search) Only return emails received after this date.

.PARAMETER ReceivedBefore
    (Search) Only return emails received before this date.

.PARAMETER InternetMessageId
    (Search) RFC 2822 Internet Message ID for exact lookup.

.PARAMETER Folder
    (Search) Which folder(s) to search: 'Inbox', 'SentMail', 'All'. Default: 'All'.

.PARAMETER MaxResults
    (Search) Maximum number of results to return. Default: 5.

.PARAMETER BodyPreviewLength
    (Search) Max characters of body text to include. Default: 2000. Set 0 for full body.

.EXAMPLE
    # Search by subject
    .\get-email-com.ps1 -Subject "Introductions Pat" -MaxResults 3

    # Reply-all using EntryID from a prior search
    .\get-email-com.ps1 -Action ReplyAll -EntryId "<id>" -ReplyBody "Thanks for the intro!"

    # Forward an email to two recipients
    .\get-email-com.ps1 -Action Forward -EntryId "<id>" -ReplyBody "FYI" -ForwardTo "alice@contoso.com,bob@contoso.com"
#>

[CmdletBinding()]
param(
    [ValidateSet('Search', 'Reply', 'ReplyAll', 'Forward')]
    [string]$Action = 'Search',

    [string]$EntryId,
    [string]$ReplyBody,
    [string]$ForwardTo,

    [string]$Subject,
    [string]$From,
    [string]$ReceivedAfter,
    [string]$ReceivedBefore,
    [string]$InternetMessageId,
    [ValidateSet('Inbox', 'SentMail', 'All')]
    [string]$Folder = 'All',
    [int]$MaxResults = 5,
    [int]$BodyPreviewLength = 2000
)

$ErrorActionPreference = 'Stop'

function Get-OutlookFolder {
    param($namespace, [string]$folderType)
    switch ($folderType) {
        'Inbox'    { return $namespace.GetDefaultFolder(6) }   # olFolderInbox
        'SentMail' { return $namespace.GetDefaultFolder(5) }   # olFolderSentMail
    }
}

function Build-DASLFilter {
    param(
        [string]$Subject,
        [string]$From,
        [string]$ReceivedAfter,
        [string]$ReceivedBefore,
        [string]$InternetMessageId
    )

    $clauses = @()

    if ($InternetMessageId) {
        $schemaId = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
        $clauses += """$schemaId"" = '$InternetMessageId'"
        # InternetMessageId is exact, return immediately
        return "@SQL=" + ($clauses -join " AND ")
    }

    if ($Subject) {
        $escaped = $Subject -replace "'", "''"
        $schemaId = "urn:schemas:httpmail:subject"
        $clauses += """$schemaId"" LIKE '%$escaped%'"
    }

    if ($From) {
        $escaped = $From -replace "'", "''"
        $schemaId = "urn:schemas:httpmail:fromemail"
        # Try both fromemail and sendername for flexibility
        $clauses += "(""urn:schemas:httpmail:fromemail"" LIKE '%$escaped%' OR ""urn:schemas:httpmail:sendername"" LIKE '%$escaped%')"
    }

    if ($ReceivedAfter) {
        $dt = [datetime]::Parse($ReceivedAfter).ToUniversalTime()
        # Outlook DASL requires 'yyyy-MM-dd HH:mm:ss' - ISO 8601 with T/Z silently fails
        $dateStr = $dt.ToString("yyyy-MM-dd HH:mm:ss")
        $clauses += """urn:schemas:httpmail:datereceived"" >= '$dateStr'"
    }

    if ($ReceivedBefore) {
        $dt = [datetime]::Parse($ReceivedBefore).ToUniversalTime()
        $dateStr = $dt.ToString("yyyy-MM-dd HH:mm:ss")
        $clauses += """urn:schemas:httpmail:datereceived"" <= '$dateStr'"
    }

    if ($clauses.Count -eq 0) {
        return $null
    }

    return "@SQL=" + ($clauses -join " AND ")
}

function Extract-EmailData {
    param($mailItem, [int]$bodyPreviewLength)

    $toRecipients = @()
    $ccRecipients = @()
    try {
        for ($i = 1; $i -le $mailItem.Recipients.Count; $i++) {
            $r = $mailItem.Recipients.Item($i)
            $entry = @{
                name    = $r.Name
                address = $r.Address
            }
            # Type 1 = To, Type 2 = CC, Type 3 = BCC
            if ($r.Type -eq 1) { $toRecipients += $entry }
            elseif ($r.Type -eq 2) { $ccRecipients += $entry }
        }
    } catch {
        # Fallback: use the To/CC string properties
        $toRecipients = @(@{ name = $mailItem.To; address = "" })
        $ccRecipients = @(@{ name = $mailItem.CC; address = "" })
    }

    $body = $mailItem.Body
    if ($bodyPreviewLength -gt 0 -and $body.Length -gt $bodyPreviewLength) {
        $body = $body.Substring(0, $bodyPreviewLength) + "`n... [truncated at $bodyPreviewLength chars]"
    }

    return [ordered]@{
        subject           = $mailItem.Subject
        from              = $mailItem.SenderEmailAddress
        fromName          = $mailItem.SenderName
        senderEmailType   = $mailItem.SenderEmailType   # 'SMTP' or 'EX' (Exchange)
        toRecipients      = $toRecipients
        ccRecipients      = $ccRecipients
        receivedTime      = $mailItem.ReceivedTime.ToString("yyyy-MM-ddTHH:mm:ssZ")
        sentOn            = $mailItem.SentOn.ToString("yyyy-MM-ddTHH:mm:ssZ")
        conversationTopic = $mailItem.ConversationTopic
        conversationId    = $mailItem.ConversationID
        hasAttachments    = $mailItem.Attachments.Count -gt 0
        importance        = $mailItem.Importance.ToString()
        isRead            = -not $mailItem.UnRead
        body              = $body
        entryId           = $mailItem.EntryID
    }
}

# --- Main ---

function Test-NewOutlook {
    # New Outlook (Monarch/One Outlook) runs as "olk.exe", not "OUTLOOK.EXE"
    $olkProcess = Get-Process -Name "olk" -ErrorAction SilentlyContinue
    if ($olkProcess) { return $true }
    # Also check registry for New Outlook preference
    $regPath = "HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences"
    try {
        $useNewOutlook = Get-ItemPropertyValue -Path $regPath -Name "UseNewOutlook" -ErrorAction SilentlyContinue
        if ($useNewOutlook -eq 1) { return $true }
    } catch {}
    return $false
}

function Start-ClassicOutlook {
    # Find Outlook.exe path
    $pf = $env:ProgramFiles
    $pf86 = ${env:ProgramFiles(x86)}
    $outlookPaths = @(
        "$pf\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "$pf86\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "$pf\Microsoft Office\Office16\OUTLOOK.EXE"
    )
    $outlookExe = $outlookPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $outlookExe) {
        $outlookExe = (Get-Command OUTLOOK.EXE -ErrorAction SilentlyContinue).Source
    }
    if ($outlookExe) {
        Write-Host "Launching classic Outlook: $outlookExe" -ForegroundColor Yellow
        Start-Process $outlookExe
        Write-Host "Waiting for Outlook to initialize..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10
        return $true
    }
    return $false
}

$outlook = $null
try {
    $outlook = New-Object -ComObject Outlook.Application
    # Verify COM is functional by accessing the namespace
    $testNs = $outlook.GetNamespace("MAPI")
    $null = $testNs.GetDefaultFolder(6)  # olFolderInbox
} catch {
    $comError = $_
    $outlook = $null

    if (Test-NewOutlook) {
        Write-Host ""
        Write-Host "========================================================" -ForegroundColor Red
        Write-Host "  NEW OUTLOOK DETECTED - COM automation not supported"   -ForegroundColor Red
        Write-Host "========================================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "The 'New Outlook' (olk.exe) does not support COM automation." -ForegroundColor Yellow
        Write-Host "To use this script, please switch back to Classic Outlook:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  1. Open Outlook" -ForegroundColor Cyan
        Write-Host "  2. Toggle OFF the 'New Outlook' switch (top-right corner)" -ForegroundColor Cyan
        Write-Host "  3. Wait for Classic Outlook to restart" -ForegroundColor Cyan
        Write-Host "  4. Re-run this script" -ForegroundColor Cyan
        Write-Host ""

        # Attempt to launch classic Outlook directly
        $classicRunning = Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue
        if (-not $classicRunning) {
            Write-Host "Attempting to launch Classic Outlook..." -ForegroundColor Yellow
            if (Start-ClassicOutlook) {
                try {
                    $outlook = New-Object -ComObject Outlook.Application
                    $testNs = $outlook.GetNamespace("MAPI")
                    $null = $testNs.GetDefaultFolder(6)
                    Write-Host "Classic Outlook launched successfully!" -ForegroundColor Green
                } catch {
                    Write-Error "Classic Outlook launched but COM still failed. Please manually toggle off 'New Outlook' mode and re-run."
                    exit 1
                }
            } else {
                Write-Error "Could not find OUTLOOK.EXE. Please open Classic Outlook manually and re-run."
                exit 1
            }
        } else {
            Write-Error "Classic Outlook process found but COM failed. Try restarting Outlook in classic mode."
            exit 1
        }
    } else {
        # Not New Outlook - maybe Outlook isn't running at all
        $outlookRunning = Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue
        if (-not $outlookRunning) {
            Write-Host "Outlook is not running. Attempting to launch..." -ForegroundColor Yellow
            if (Start-ClassicOutlook) {
                try {
                    $outlook = New-Object -ComObject Outlook.Application
                } catch {
                    Write-Error "Launched Outlook but COM creation failed: $_"
                    exit 1
                }
            } else {
                Write-Error "Outlook is not installed or not found. Error: $comError"
                exit 1
            }
        } else {
            Write-Error "Outlook is running but COM object creation failed: $comError"
            exit 1
        }
    }
}

if (-not $outlook) {
    Write-Error "Failed to establish Outlook COM connection."
    exit 1
}

$namespace = $outlook.GetNamespace("MAPI")

# ---------------------------------------------------------------
# Action: Reply / ReplyAll / Forward
# ---------------------------------------------------------------
if ($Action -in @('Reply', 'ReplyAll', 'Forward')) {
    if (-not $EntryId) {
        Write-Error "The -EntryId parameter is required for $Action. Obtain it from a prior Search result's 'entryId' field."
        exit 1
    }
    if ($Action -eq 'Forward' -and -not $ForwardTo) {
        Write-Error "The -ForwardTo parameter is required for Forward action. Provide comma-separated SMTP addresses."
        exit 1
    }

    try {
        $msg = $namespace.GetItemFromID($EntryId)
    } catch {
        Write-Error "Failed to look up email by EntryID. The ID may be invalid or the email may have been moved/deleted. Error: $_"
        exit 1
    }

    switch ($Action) {
        'Reply'    { $outgoing = $msg.Reply() }
        'ReplyAll' { $outgoing = $msg.ReplyAll() }
        'Forward'  { $outgoing = $msg.Forward() }
    }

    # Prepend reply body above the quoted thread
    if ($ReplyBody) {
        if ($ReplyBody -match '<[a-zA-Z][\s\S]*>') {
            # HTML content - inject into HTMLBody before the quoted thread
            $outgoing.HTMLBody = $ReplyBody + "<br/>" + $outgoing.HTMLBody
        } else {
            $outgoing.Body = $ReplyBody + "`r`n`r`n" + $outgoing.Body
        }
    }

    # Add forward recipients
    if ($Action -eq 'Forward' -and $ForwardTo) {
        foreach ($addr in ($ForwardTo -split ',')) {
            $addr = $addr.Trim()
            if ($addr) {
                $recip = $outgoing.Recipients.Add($addr)
                $recip.Type = 1  # olTo
            }
        }
        $outgoing.Recipients.ResolveAll() | Out-Null
    }

    $outgoing.Send()

    # Build recipient list for output
    $toList = @()
    for ($i = 1; $i -le $outgoing.Recipients.Count; $i++) {
        $r = $outgoing.Recipients.Item($i)
        $toList += @{ name = $r.Name; address = $r.Address; type = $r.Type }
    }

    $result = [ordered]@{
        action     = $Action
        subject    = $outgoing.Subject
        recipients = $toList
        status     = "sent"
    }
    $result | ConvertTo-Json -Depth 5
    exit 0
}

# ---------------------------------------------------------------
# Action: Search (default)
# ---------------------------------------------------------------
$filter = Build-DASLFilter -Subject $Subject -From $From `
    -ReceivedAfter $ReceivedAfter -ReceivedBefore $ReceivedBefore `
    -InternetMessageId $InternetMessageId

if (-not $filter) {
    Write-Error "At least one search parameter is required: -Subject, -From, -ReceivedAfter, -ReceivedBefore, or -InternetMessageId"
    exit 1
}

Write-Verbose "DASL filter: $filter"

$foldersToSearch = @()
if ($Folder -eq 'All') {
    $foldersToSearch += Get-OutlookFolder $namespace 'Inbox'
    $foldersToSearch += Get-OutlookFolder $namespace 'SentMail'
} else {
    $foldersToSearch += Get-OutlookFolder $namespace $Folder
}

$allResults = @()

foreach ($f in $foldersToSearch) {
    Write-Verbose "Searching folder: $($f.Name)"
    $items = $f.Items
    $items.Sort("[ReceivedTime]", $true)  # newest first

    try {
        $filtered = $items.Restrict($filter)
        Write-Verbose "  Found $($filtered.Count) items matching filter"

        $count = 0
        $item = $filtered.GetFirst()
        while ($item -ne $null -and $count -lt $MaxResults) {
            if ($item.Class -eq 43) {  # olMail = 43
                $allResults += Extract-EmailData $item $BodyPreviewLength
                $count++
            }
            $item = $filtered.GetNext()
        }
    } catch {
        Write-Verbose "  Error searching folder $($f.Name): $_"
    }
}

# Sort all results by receivedTime descending and limit
$allResults = $allResults | Sort-Object { [datetime]$_.receivedTime } -Descending | Select-Object -First $MaxResults

$output = [ordered]@{
    query   = [ordered]@{
        subject          = $Subject
        from             = $From
        receivedAfter    = $ReceivedAfter
        receivedBefore   = $ReceivedBefore
        internetMessageId = $InternetMessageId
        folder           = $Folder
    }
    count   = $allResults.Count
    results = $allResults
}

$output | ConvertTo-Json -Depth 5
