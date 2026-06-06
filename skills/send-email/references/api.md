# Send Email — MCP API Reference

Detailed parameter reference for the microsoft-outlook-mail MCP tools. This file is for reference when you need exact parameter names — the model already has tool schemas at runtime.

## Sending & Composing

| Tool | Description | Optional Parameters |
|------|-------------|---------------------|
| `SendEmailWithAttachments` | Create and send an email with optional attachments (file URIs or base64). Recipients can be names or email addresses — names are auto-resolved via Microsoft Graph. | `cc`, `bcc`, `attachmentUris`, `directAttachmentFilePaths`, `directAttachments` |
| `CreateDraftMessage` | Create a draft email without sending it. Returns a draft message ID for further editing. | `to`, `cc`, `bcc`, `contentType` (`"Text"` or `"HTML"`) |
| `UpdateDraft` | Update a draft's recipients, subject, body, and attachments before sending. | `to`, `cc`, `bcc`, `subject`, `body`, `attachmentUris`, `directAttachmentFilePaths`, `directAttachments` |
| `SendDraftMessage` | Send an existing draft message by its ID. | — |

## Replying & Forwarding

| Tool | Description | Optional Parameters |
|------|-------------|---------------------|
| `ReplyToMessage` | Reply to a single sender on an existing message. | `comment`, `toRecipients`, `ccRecipients`, `bccRecipients`, `preferHtml` |
| `ReplyAllToMessage` | Reply-all to an existing message. | `comment`, `toRecipients`, `ccRecipients`, `bccRecipients`, `preferHtml` |
| `ReplyWithFullThread` | Reply preserving the full quoted thread, with option to add recipients and re-attach files. | `introComment`, `additionalTo`, `additionalCc`, `additionalBcc`, `includeOriginalNonInlineAttachments`, `replyAll`, `preferHtml` |
| `ReplyAllWithFullThread` | Reply-all preserving the full quoted thread. | `introComment`, `additionalTo`, `additionalCc`, `additionalBcc`, `includeOriginalNonInlineAttachments`, `preferHtml` |
| `ForwardMessage` | Forward a message with optional comment and new attachments. | `introComment`, `additionalTo`, `additionalCc`, `additionalBcc`, `attachmentUris`, `directAttachmentFilePaths`, `directAttachments`, `preferHtml` |
| `ForwardMessageWithFullThread` | Forward preserving the full quoted thread; returns sensitivity label. | `introComment`, `additionalTo`, `additionalCc`, `additionalBcc`, `includeOriginalNonInlineAttachments`, `preferHtml` |

## Searching & Reading

| Tool | Description | Optional Parameters |
|------|-------------|---------------------|
| `SearchMessages` | AI-powered natural language search across the mailbox. Also supports KQL-style queries (e.g., `from:sarah subject:budget hasattachment:true`). | `conversationId` |
| `GetMessage` | Get a specific message by ID, with full body or preview only. | `preferHtml`, `bodyPreviewOnly` |
| `GetAttachments` | List all attachments on a message (metadata: ID, name, size, type). | — |
| `DownloadAttachment` | Download attachment content as base64. | — |

## Managing Messages

| Tool | Description | Optional Parameters |
|------|-------------|---------------------|
| `UpdateMessage` | Update a message's subject, body, categories, or importance. | `subject`, `body`, `contentType`, `categories`, `importance` |
| `DeleteMessage` | Delete a message from the mailbox. | — |
| `FlagEmail` | Set flag status on an email: `Flagged`, `Complete`, or `NotFlagged`. | `mailboxAddress` |

## Managing Attachments

| Tool | Description | Optional Parameters |
|------|-------------|---------------------|
| `AddDraftAttachments` | Add file URI attachments to an existing draft. | — |
| `UploadAttachment` | Upload a small file attachment (<3 MB, base64-encoded) to a message. | `contentType` |
| `UploadLargeAttachment` | Upload a large file attachment (3–150 MB, chunked) to a message. | `contentType` |
| `DeleteAttachment` | Remove an attachment from a message. | — |

## COM Fallback Script Parameters

| Parameter | Type | Applies to | Description |
|-----------|------|------------|-------------|
| `-Action` | string | All | `Search` (default), `Reply`, `ReplyAll`, `Forward` |
| `-EntryId` | string | Reply/ReplyAll/Forward | Outlook EntryID from a prior Search result |
| `-ReplyBody` | string | Reply/ReplyAll/Forward | Body text (plain or HTML) to prepend above the quoted thread |
| `-ForwardTo` | string | Forward | Comma-separated SMTP email addresses |
| `-Subject` | string | Search | Partial or full subject match |
| `-From` | string | Search | Sender **display name** (not SMTP address) |
| `-ReceivedAfter` | string | Search | ISO 8601 date |
| `-ReceivedBefore` | string | Search | ISO 8601 date |
| `-InternetMessageId` | string | Search | RFC 2822 message ID for exact lookup |
| `-Folder` | string | Search | `Inbox`, `SentMail`, or `All` (default) |
| `-MaxResults` | int | Search | Max results (default: 5) |
| `-BodyPreviewLength` | int | Search | Max body chars (default: 2000; 0 = full) |
