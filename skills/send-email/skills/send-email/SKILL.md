---
name: send-email
description: This skill should be used when the user asks to "send an email to someone", "email this to <person>", "send a message to <email>", "reply to an email", "forward this email", "draft an email", "search my emails", "find emails about <topic>", or wants to compose, send, reply, forward, search, or manage emails via Outlook. Unlike notify-me which sends to yourself, this skill sends to any specified recipient(s). Powered by the microsoft-outlook-mail MCP.
---

Manage Outlook email via the **microsoft-outlook-mail** MCP — send, reply, forward, draft, search, and manage messages and attachments.

## Overview

This skill uses the **microsoft-outlook-mail MCP** (Microsoft Graph API) to perform email operations. No local Outlook installation or PowerShell scripts are needed — all operations go through the MCP tools directly.

## MCP Tools

This skill uses the **microsoft-outlook-mail MCP**. The model already has tool schemas at runtime — refer to MCP tool definitions directly for parameter details. Key tools:

- **Send:** `SendEmailWithAttachments`, `CreateDraftMessage`, `UpdateDraft`, `SendDraftMessage`
- **Reply/Forward:** `ReplyToMessage`, `ReplyAllToMessage`, `ReplyWithFullThread`, `ReplyAllWithFullThread`, `ForwardMessage`, `ForwardMessageWithFullThread`
- **Search/Read:** `SearchMessages`, `GetMessage`, `GetAttachments`, `DownloadAttachment`
- **Manage:** `UpdateMessage`, `DeleteMessage`, `FlagEmail`
- **Attachments:** `AddDraftAttachments`, `UploadAttachment`, `UploadLargeAttachment`, `DeleteAttachment`

**Recipients:** All tools accept both email addresses and display names (auto-resolved via Graph). Use WorkIQ if resolution fails.

**Attachments:** Three methods — file URIs (OneDrive/SharePoint/Graph links), local file paths (`directAttachmentFilePaths`), or base64 (`directAttachments`).

**HTML:** Always use HTML for email bodies. Set `contentType: "HTML"` for drafts, `preferHtml: true` for replies/forwards/reads.

**Thread preservation:** Prefer `WithFullThread` variants for replies and forwards to keep the quoted thread intact.

## Workflow

### Step 1: Gather Email Details

Collect the following from the user (ask if not provided):
- **Recipients**: One or more email addresses or names (required). Names are auto-resolved by the MCP. Use WorkIQ to look up addresses if only partial names are provided.
- **Subject**: The email subject line (required)
- **Body**: The email body content (required)
- **Cc / Bcc**: Optional additional recipients
- **Attachments**: Optional file URIs or local file paths

If the user provides a description of what they want to send rather than exact text, compose appropriate subject and body content and confirm with the user before sending.

### Step 2: Confirm Before Sending

Always present the composed email to the user for confirmation before sending:

```
To: <recipient1>; <recipient2>
Cc: <cc-recipient> (if any)
Subject: <subject>

<body>

—
Sent by Agency Cowork
```

Ask: "Does this look good to send?"

Do NOT send the email until the user explicitly confirms.

### Step 3: Send the Email

Use the `SendEmailWithAttachments` MCP tool:

- **to**: Array of recipient email addresses or names
- **cc** / **bcc**: Optional arrays of Cc/Bcc recipients
- **subject**: The subject line
- **body**: The full body in **HTML**, always ending with the signature block:

```html
<body content in HTML>

—
Sent by Agency Cowork
```

- **attachmentUris** / **directAttachmentFilePaths** / **directAttachments**: Optional attachments

**IMPORTANT:** Always send ONE email with all recipients — never send separate emails to each person.

### Step 4: Confirm

Inform the user that the email was sent successfully, listing all recipients.

## Other Operations

### Replying to an Email
1. Use `SearchMessages` to find the message if the user doesn't provide an ID
2. Use `GetMessage` to read the original message
3. Compose the reply and confirm with the user
4. Use `ReplyToMessage` or `ReplyAllToMessage` (or the `WithFullThread` variants to preserve the quoted thread)
5. **If any MCP reply tool fails** with "Resource not found for the segment" error, fall back to the COM script:
   - Search via COM to get `entryId` (if not already obtained)
   - Use `-Action Reply` or `-Action ReplyAll` with the `entryId` and `-ReplyBody`
6. Always append the signature: "Sent by Agency Cowork"

### Forwarding an Email
1. Locate the message via `SearchMessages` or `GetMessage`
2. Confirm the forward recipients and any intro comment with the user
3. Use `ForwardMessage` or `ForwardMessageWithFullThread`
4. **If any MCP forward tool fails** with "Resource not found for the segment" error, fall back to the COM script:
   - Search via COM to get `entryId` (if not already obtained)
   - Use `-Action Forward` with the `entryId`, `-ReplyBody`, and `-ForwardTo`
5. Always append the signature: "Sent by Agency Cowork"

### Drafting an Email
1. Use `CreateDraftMessage` to create the draft
2. Use `UpdateDraft` to refine recipients, body, or attachments
3. Use `AddDraftAttachments` for file URI attachments
4. Present the draft to the user for review
5. Use `SendDraftMessage` when the user approves

### Searching Emails
1. Use `SearchMessages` with a natural language query (e.g., "emails from John about the project")
2. Present results to the user in a concise summary
3. Use `GetMessage` to retrieve full details of a specific result
4. **If `GetMessage` fails** with a "Resource not found for the segment" error, this indicates the message ID contains a `/` character that breaks Graph API URL routing. Fall back to the Outlook COM script (see below). Note: the same error will occur with **all** MCP tools that take a messageId (reply, forward, etc.).

### Fallback: Outlook COM Retrieval & Reply

When Graph API MCP tools fail due to special characters (`/`, `+`) in message IDs, use the local Outlook COM script as a fallback. **This affects ALL tools that take a messageId** — not just `GetMessage` but also `ReplyToMessage`, `ReplyAllToMessage`, `ReplyWithFullThread`, `ForwardMessage`, `ForwardMessageWithFullThread`, and any other tool that routes a message ID through the Graph API URL path.

**Script:** `scripts/get-email-com.ps1`

**API Reference:** [MailItem Properties](https://learn.microsoft.com/en-us/dotnet/api/microsoft.office.interop.outlook.mailitem?view=outlook-pia#properties_)

**When to use:**
- Any MCP tool returns an error like `"Resource not found for the segment 'AAA='"` — this means the message ID contains a `/` that the Graph API misinterprets as a URL path separator.
- The email is confirmed to exist (e.g., appears in `SearchMessages` citations) but cannot be read, replied to, or forwarded via MCP tools.
- You need to reply to or forward an email and `ReplyToMessage` / `ReplyAllToMessage` / `ForwardMessage` all fail with the same segment error.

**Parameters:**

| Parameter | Type | Applies to | Description |
|-----------|------|------------|-------------|
| `-Action` | string | All | `Search` (default), `Reply`, `ReplyAll`, `Forward` |
| `-EntryId` | string | Reply/ReplyAll/Forward | Outlook EntryID from a prior Search result |
| `-ReplyBody` | string | Reply/ReplyAll/Forward | Body text (plain or HTML) to prepend above the quoted thread. HTML is auto-detected and injected into HTMLBody. |
| `-ForwardTo` | string | Forward | Comma-separated SMTP email addresses |
| `-Subject` | string | Search | Partial or full subject match |
| `-From` | string | Search | Sender **display name** (not SMTP address — see Known Issues) |
| `-ReceivedAfter` | string | Search | ISO 8601 date — only emails after this date |
| `-ReceivedBefore` | string | Search | ISO 8601 date — only emails before this date |
| `-InternetMessageId` | string | Search | RFC 2822 message ID for exact lookup |
| `-Folder` | string | Search | `Inbox`, `SentMail`, or `All` (default: `All`) |
| `-MaxResults` | int | Search | Max results to return (default: 5) |
| `-BodyPreviewLength` | int | Search | Max body chars (default: 2000; 0 = full) |

**Search output fields:** `subject`, `from` (X500 or SMTP address), `fromName` (display name), `senderEmailType` (`SMTP` or `EX`), `toRecipients`, `ccRecipients`, `receivedTime`, `sentOn`, `conversationTopic`, `conversationId`, `hasAttachments`, `importance`, `isRead`, `body`, `entryId`

**Reply/Forward output fields:** `action`, `subject`, `recipients`, `status` (`"sent"`)

**Usage:**
```powershell
# Search by subject
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/get-email-com.ps1 -Subject "Introductions Pat" -MaxResults 3

# Search by sender display name + date range
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/get-email-com.ps1 -From "Jane Doe" -ReceivedAfter "2026-03-01"

# Reply-all using EntryID from a prior search
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/get-email-com.ps1 -Action ReplyAll -EntryId "<entryId>" -ReplyBody "Thanks for the intro!`r`n`r`n-Your Name`r`n`r`n—`r`nSent by Agency Cowork"

# Forward an email
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/get-email-com.ps1 -Action Forward -EntryId "<entryId>" -ReplyBody "FYI — see thread below." -ForwardTo "alice@contoso.com,bob@contoso.com"
```

**Requirements:** Outlook desktop must be installed on the local machine. The script uses COM automation which is only supported by **Classic Outlook** (OUTLOOK.EXE), not the New Outlook (olk.exe). If New Outlook is detected, the script will:
1. Display a message asking the user to toggle off "New Outlook" mode (top-right toggle in Outlook)
2. Attempt to launch Classic Outlook automatically
3. If Classic Outlook launches successfully, proceed with the operation
4. If it fails, instruct the user to manually switch to Classic Outlook and re-run

**Workflow when GetMessage fails (read-only):**
1. Identify the subject and sender from the `SearchMessages` citation attributes
2. Run the COM script with `-Subject` and optionally `-From` or date filters
3. Present the retrieved email content to the user

**Workflow when Reply/Forward MCP tools fail:**
1. First, search for the email via COM to get the `entryId`:
   ```powershell
   scripts/get-email-com.ps1 -Subject "..." -From "..." -MaxResults 1
   ```
2. Extract the `entryId` from the search result
3. Compose the reply body (include the signature block)
4. **Confirm with the user** before sending
5. Send via COM:
   ```powershell
   scripts/get-email-com.ps1 -Action ReplyAll -EntryId "<entryId>" -ReplyBody "<body>"
   ```
6. The script preserves the full quoted thread automatically (Outlook appends original below)

### Known Issues & DASL Filter Gotchas

| Issue | Details | Workaround |
|-------|---------|------------|
| **Graph API `/` in message IDs** | Message IDs are base64-encoded and may contain `+`, `/`, `=`. The `/` is misinterpreted as a URL path separator, causing **all MCP tools that take a messageId** to fail — including `GetMessage`, `ReplyToMessage`, `ReplyAllToMessage`, `ReplyWithFullThread`, `ReplyAllWithFullThread`, `ForwardMessage`, and `ForwardMessageWithFullThread`. The error is `"Resource not found for the segment 'AAA='"`. | Use the COM fallback script for both retrieval and reply/forward. Search first to get the `entryId`, then use `-Action Reply|ReplyAll|Forward`. |
| **DASL date format** | DASL `Restrict()` requires date values in `'yyyy-MM-dd HH:mm:ss'` format. ISO 8601 with `T`/`Z` (e.g., `'2026-03-01T08:00:00Z'`) **silently breaks the entire filter**, causing `Restrict()` to return all items. | The script handles this automatically. If writing custom DASL filters, always use space-separated format without timezone suffix. |
| **From filter uses X500 addresses** | Exchange stores sender addresses internally as X500 (e.g., `/O=EXCHANGELABS/.../CN=JANE DOE`), not SMTP. The `urn:schemas:httpmail:fromemail` property contains these X500 addresses. | Always use **display names** (e.g., "Jane Doe") for the `-From` parameter, not SMTP addresses (e.g., "janedoe@contoso.com"). The script searches both `fromemail` and `sendername`. |
| **Silent DASL filter failure** | If ANY clause in a combined DASL `AND` filter is malformed, the entire filter silently fails and `Restrict()` returns all items instead of an error. | Use `-Verbose` flag to inspect the generated DASL filter string and verify `Restrict()` result count matches expectations. |
| **WorkIQ citation-only results** | `SearchMessages` may find an email and return it in citations (with `attributionSource: "grounding"`) but refuse to display the body — likely hitting the same Graph API URL encoding issue internally. | Extract the subject from the citation's `providerDisplayName` and use the COM fallback to retrieve the full content. |

## Gotchas

These are real failure modes that have caused bugs in production — read carefully.

### Graph API Message ID Encoding

- **Message IDs containing `/` break ALL MCP tools**, not just `GetMessage` — Reply, Forward, Update, Delete all fail with `"Resource not found for the segment 'AAA='"`. The IDs are base64-encoded and may contain `/`, `+`, `=`. When this happens, fall back to the COM script (`scripts/get-email-com.ps1`).
- **WorkIQ `SearchMessages` may find an email (returned in citations) but refuse to display the body** — this is the same Graph URL encoding issue. Extract the subject from the citation's `providerDisplayName` and use the COM fallback.

### DASL Filter Gotchas (COM Fallback)

- **DASL date filters require `'yyyy-MM-dd HH:mm:ss'` format.** ISO 8601 with `T`/`Z` (e.g., `'2026-03-01T08:00:00Z'`) **silently breaks the entire filter** — `Restrict()` returns ALL items, not an error. The script handles this automatically, but if writing custom DASL filters, always use space-separated format.
- **If ANY clause in a combined DASL `AND` filter is malformed, the entire filter silently succeeds** — returns all items instead of erroring. Use `-Verbose` to debug.
- **`-From` must use display names** (e.g., "Jane Doe"), not SMTP addresses. Exchange stores sender addresses as X500 internally.

### COM Fallback Requirements

- **COM fallback requires Classic Outlook (OUTLOOK.EXE)**, not New Outlook (olk.exe). If New Outlook is active, the script will attempt to launch Classic Outlook, but the user may need to toggle manually.

### Formatting

- **Always send HTML, never plain text.** Plain text emails lose all formatting and look unprofessional. Use `<p>` tags for paragraphs (bare newlines are ignored in HTML rendering), `<ul>`/`<ol>` for lists, `<strong>` for emphasis.
- **Always append the signature block:** `— Sent by Agency Cowork`

## Composes With

- **email-triage** — Triage identifies emails needing responses; this skill drafts and sends those responses
- **weekly-report** — Offer to email generated reports after saving
- **teams** — Cross-reference Teams discussions when composing follow-up emails
- **sharepoint** — Attach SharePoint documents to emails via file URIs
- **calendar** — Reference meeting context when composing follow-up emails

## Rules

- ALWAYS confirm with the user before sending — never send without explicit approval
- ALWAYS consolidate multiple recipients into a single email — do not send separate emails
- ALWAYS use **HTML formatting** for email bodies — never send plain text walls of text. Use `contentType: "HTML"` for drafts and `preferHtml: true` for replies/forwards. Structure content with:
  - `<p>` tags for paragraphs (never rely on bare newlines)
  - `<ul>`/`<ol>` with `<li>` for lists and bullet points
  - `<strong>` for emphasis on key terms, statuses, and decisions
  - `<a href="...">` for clickable links (ADO work items, SharePoint docs, etc.)
  - `<table>` for tabular data when comparing items or listing statuses
  - Proper whitespace between sections for scannability
- ALWAYS append the signature block to every outgoing email body (send, reply, forward):
  ```
  —
  Sent by Agency Cowork
  ```
- Keep subject under 100 characters
- Do not include sensitive information (passwords, keys, secrets) in the email
- Do not include large code blocks in the email body — summarize instead
- If the user asks to email themselves, suggest using the `/notify-me` skill instead
- All recipient addresses must be valid email format (or resolvable names)
- For replies and forwards, prefer the `WithFullThread` variants to preserve conversation context
