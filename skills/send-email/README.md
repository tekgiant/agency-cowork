# send-email

Send, reply, forward, draft, and search Outlook email via the **microsoft-outlook-mail MCP**. No local Outlook installation required — all operations go through Microsoft Graph.

## Prerequisites

- **microsoft-outlook-mail MCP** connected and authenticated

## Registration

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\send-email"
```

Restart your Copilot session for the skill to appear in `/skills`.

## Usage

Use the `/send-email` skill when you want to send, reply, forward, or search emails:

```
/send-email
```

The agent will ask for (or use from context):
- **Recipient** email address(es) or name(s) — names are auto-resolved
- **Subject** line
- **Body** content
- **Cc / Bcc** recipients (optional)
- **Attachments** — file URIs or local paths (optional)

The agent will always confirm the composed email with you before sending.

### Examples

```
Send an email to alice@contoso.com summarizing today's code changes
```

```
Reply to the latest email from Bob about the deployment
```

```
Forward the budget email to carol@contoso.com with a note
```

```
Search my emails for messages about the Q3 deliverables
```

## Email Format

**To**: `alice@contoso.com`
**Subject**: `Summary of authentication refactor`

**Body**:
```
Refactored the authentication module to use token-based auth instead of
session cookies. Updated 12 files across the auth and middleware packages.

—
Sent by Agency Cowork
```

## Capabilities

| Operation | MCP Tool |
|-----------|----------|
| Send email (with attachments) | `SendEmailWithAttachments` |
| Create/update/send drafts | `CreateDraftMessage`, `UpdateDraft`, `SendDraftMessage` |
| Reply / Reply-all | `ReplyToMessage`, `ReplyAllToMessage`, `ReplyWithFullThread` |
| Forward | `ForwardMessage`, `ForwardMessageWithFullThread` |
| Search emails | `SearchMessages` |
| Read email | `GetMessage` |
| Manage attachments | `GetAttachments`, `DownloadAttachment`, `UploadAttachment` |
| Flag / unflag | `FlagEmail` |
| Delete | `DeleteMessage` |

See `SKILL.md` for the full MCP capabilities reference.
