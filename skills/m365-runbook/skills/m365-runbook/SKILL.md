---
name: m365-runbook
description: |
  Use this skill when an M365 integration is failing, broken, or producing errors. Triggers on:
  "Teams isn't working", "email send failed", "SharePoint download broken", "MCP auth failed",
  "cache is stale", "Playwright session expired", "Graph API error", "COM script failed",
  "can't access SharePoint", "Teams monitor stopped", "DRM error", or any M365 connectivity issue.
  This is the troubleshooting playbook — follow it before escalating to the user.
---

# M365 Integration Runbook

Systematic troubleshooting for common M365 integration failures. Follow these runbooks before escalating to the user or declaring a feature broken.

## When to Use

- Any MCP tool returns an error
- A skill fails silently (no output, unexpected results)
- The user reports that an integration "isn't working"
- Scheduled tasks fail with M365 errors
- After infrastructure changes (OS update, Outlook update, Teams update)

---

## Runbook 1: MCP Authentication Failures

**Symptoms:** MCP tools return 401/403, "access denied", "token expired", or similar auth errors.

**Diagnostic steps:**
1. Check if the MCP server process is running:
   ```bash
   ps aux | grep -i "mcp"
   ```
2. Check MCP server logs for auth errors
3. Verify the user's Azure AD session is active — try a simple WorkIQ query
4. If using delegated auth, the refresh token may have expired (typically 90 days)

**Resolution:**
- Restart the MCP server process
- Have the user re-authenticate via browser (the MCP will prompt)
- If persistent, check if Conditional Access policies have changed

**Escalation:** If re-auth doesn't fix it, check Azure AD admin portal for revoked app permissions.

---

## Runbook 2: Graph API Message ID Encoding Failures

**Symptoms:** `"Resource not found for the segment 'AAA='"` error on GetMessage, ReplyToMessage, ForwardMessage, or any tool that takes a messageId.

**Root cause:** Base64-encoded message IDs contain `/` characters that the Graph API misinterprets as URL path separators.

**Resolution:**
1. This affects ALL MCP tools that route a message ID through the URL path
2. Fall back to the Outlook COM script (`skills/send-email/scripts/get-email-com.ps1`)
3. Search by subject/sender to get the `entryId`, then use `-Action Reply|Forward`
4. COM requires Classic Outlook (not New Outlook) — see Runbook 6

**This is a known Microsoft Graph limitation, not a bug in our code.**

---

## Runbook 3: Teams Cache Staleness

**Symptoms:** Can't find a chat/channel that exists, wrong person resolved, "chat not found" errors.

**Diagnostic steps:**
1. Check cache age:
   ```bash
   python3 skills/teams/scripts/cache-manager.py status
   ```
2. If `lastRefreshed` is older than 4 hours, cache is stale

**Resolution:**
1. Force refresh: `python3 skills/teams/scripts/cache-manager.py refresh all`
2. If a specific chat was just created, it won't be in cache — use `ListChats` with `userUpns` filter
3. After resolving, add to cache: `python3 skills/teams/scripts/cache-manager.py add-chat ...`

---

## Runbook 4: SharePoint Download Failures

**Symptoms:** SharePoint file download fails, returns 403, or downloads a corrupted/empty file.

**Diagnostic steps:**
1. Verify the user has access to the SharePoint site (not just the file)
2. Check if the file URL is a sharing link vs. a direct path — they use different Graph API endpoints
3. Check if the file is on a personal OneDrive vs. a SharePoint team site

**Resolution:**
- **Sharing links:** Use the Graph API `/shares/` endpoint with base64-encoded sharing URL
- **Personal OneDrive:** Requires different permissions than SharePoint team sites
- **Encrypted/DRM files:** File may download successfully but be OLE2 wrapped — check header bytes
- **Large files (>4MB):** May need chunked download via Graph API
- If all else fails, have the user copy the file to their personal OneDrive or download manually

**Common mistake:** Using `az account get-access-token` for Graph API calls — this uses the CLI's app registration which may not have the right scopes. Use the MCP's delegated auth instead.

---

## Runbook 5: DRM / Encrypted File Handling

**Symptoms:** File opens as garbled content, `python-pptx`/`openpyxl` throws "not a valid OOXML file", file header is `D0 CF 11 E0`.

**Diagnostic steps:**
1. Check file header:
   ```bash
   python3 -c "print(open('file.pptx','rb').read(4).hex())"
   ```
   - `d0cf11e0` = OLE2 (DRM-wrapped or encrypted)
   - `504b0304` = Clean OOXML

**Resolution (Windows only):**
1. Capture DRM policy: `drm_handler.ps1 -Action capture -InputFile file.pptx`
2. Strip DRM: `drm_handler.ps1 -Action strip -InputFile file.pptx -OutputFile clean.pptx`
3. Edit the clean file
4. Re-apply DRM: `drm_handler.ps1 -Action apply -InputFile clean.pptx -OutputFile final.pptx -PolicyJson $policy`

**macOS limitation:** DRM handling requires Office COM automation (Windows only). On macOS, inform the user that DRM-protected files cannot be edited locally. Options:
- Open the file in Office Online (browser) for editing
- Transfer to a Windows machine for COM-based processing
- Ask the document owner to share an unprotected version

---

## Runbook 6: Classic Outlook vs. New Outlook

**Symptoms:** COM fallback scripts fail with "cannot create Outlook.Application object" or launch the wrong Outlook version.

**Diagnostic steps (Windows):**
1. Check which Outlook is running:
   ```powershell
   Get-Process outlook -ErrorAction SilentlyContinue | Select-Object ProcessName, Path
   Get-Process olk -ErrorAction SilentlyContinue | Select-Object ProcessName, Path
   ```
2. If `olk.exe` is running, New Outlook is active

**Resolution:**
- COM automation only works with Classic Outlook (`OUTLOOK.EXE`)
- Ask the user to toggle off "New Outlook" (top-right toggle in Outlook app)
- Wait for Classic Outlook to fully start before retrying
- On macOS, COM is not available — use MCP tools only

---

## Runbook 7: Playwright Session Issues

**Symptoms:** Rich Teams messages fail silently, Playwright browser doesn't launch, "browser context expired" errors.

**Diagnostic steps:**
1. Check if chromium is installed: `python3 -m playwright install --dry-run chromium`
2. Check for stale browser processes: `ps aux | grep chromium`
3. Look for session storage issues in the Playwright persistent context directory

**Resolution:**
1. Kill stale browser processes
2. Reinstall browser: `python3 -m playwright install chromium`
3. Clear persistent context (session cookies) and re-authenticate
4. If on macOS, ensure the terminal has screen recording / accessibility permissions for Playwright

---

## Runbook 8: Teams Monitor PTY Failures (macOS)

**Symptoms:** Teams Monitor stops polling, shows "disconnected", or PTY process crashes.

**Root cause (documented in architecture.md):** Three root causes have been identified:
1. Electron `ELECTRON_RUN_AS_NODE=1` child process doesn't inherit correct PATH
2. PTY ready detection fails if the session resumes (no "Environment loaded:" output)
3. IPC routing uses direct `webContents.send()` which crashes if renderer is not ready

**Resolution:**
1. Run bridge in-process (Electron main thread), not as a separate child process
2. Accept bootstrap + prompt/footer readiness signals, not just "Environment loaded:"
3. Route all monitor events through `sendToRenderer()` guard
4. Restart the monitor service from the app's settings panel

---

## Gotchas

- **Don't assume all errors are auth errors.** A 403 from SharePoint might be a missing site permission, not a token issue. A 200 from Teams might not mean success (see Runbook 2's note about wrong-region 200s).
- **MCP server crashes are silent.** If all MCP tools suddenly fail, check if the server process is still running before debugging individual tools.
- **Rate limiting is real.** Graph API has throttling limits. If multiple parallel requests fail with 429, back off and retry with smaller batches.
- **New Outlook is actively rolling out.** Microsoft is pushing users to New Outlook, which breaks COM automation. This will be an increasingly common issue.

## Composes With

- **teams** — Troubleshoot Teams-specific failures (cache, Playwright, rich messaging)
- **send-email** — Troubleshoot email failures (Graph API, COM fallback, DASL filters)
- **sharepoint** — Troubleshoot SharePoint download/upload failures
- **powerpoint** / **excel** / **word-doc** — Troubleshoot DRM and file handling issues
