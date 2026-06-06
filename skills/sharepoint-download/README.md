# SharePoint File Operations

Download and upload files between local machine and SharePoint/OneDrive via the Microsoft Graph API, with optional Markdown conversion for the Knowledgebase.

The standard SharePoint MCP tools have a **5 MB file-size limit** for reading/writing files. This skill bypasses that limit by transferring directly through the Graph API, authenticated via Azure CLI.

## Prerequisites

- **Azure CLI** (`az`) — [Install Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- **Logged in**: `az login`
- **SharePoint MCP server** connected (used for metadata resolution)
- **MarkItDown** (optional, for document conversion): `pip install 'markitdown[all]'`

## Installation

### 1. Register the skill

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\sharepoint-download"
```

Restart your Copilot session for the skill to appear in `/skills`.

### 2. Verify Azure CLI authentication

```bash
az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
```

If this fails, run `az login` first.

### 3. Install MarkItDown (optional)

For automatic document-to-Markdown conversion:

```bash
pip install 'markitdown[all]'
```

## Usage

Use the `/sharepoint` skill when you want to download or upload files:

```
/sharepoint
```

The agent will:
1. Resolve file metadata from the SharePoint URL
2. Download or upload the file via Graph API (no size limit)
3. Optionally convert to Markdown and store in the Knowledgebase

### Examples

```
Download this SharePoint document: https://microsoft.sharepoint.com/:w:/r/teams/...
```

```
Retrieve this spec from SharePoint, convert to markdown, and add to the Knowledgebase under Specifications/System/ProjectX
```

```
Download all the files from this SharePoint folder and convert them to markdown
```

### Direct Script Usage

You can also use the download script directly:

```powershell
.\scripts\download-from-sharepoint.ps1 `
    -DriveId "b!YPXR4mCsb0KEnHql..." `
    -ItemId "01LANAHGWWDS3ZYQ..." `
    -OutputFile "C:\temp\my-document.docx"
```

## How It Works

```
SharePoint URL
      │
      ▼
┌─────────────────────────┐
│ SharePoint MCP Server   │  Resolve metadata (driveId, itemId, name, size)
│ getFileOrFolderMetadata │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Azure CLI (az)          │  Obtain Graph API access token
│ get-access-token        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Microsoft Graph API     │  Download file content (any size)
│ /drives/{id}/items/{id} │
│ /content                │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ markitdown (optional)   │  Convert to Markdown
└──────────┬──────────────┘
           │
           ▼
     Knowledgebase/
```

## Troubleshooting

### `az` command not found

Install Azure CLI:

```bash
winget install Microsoft.AzureCLI
```

### Token acquisition fails

```bash
az login
```

If using a specific tenant:

```bash
az login --tenant <tenant-id>
```

### SharePoint metadata resolution fails

- Verify the URL is a valid SharePoint sharing link
- Ensure you have at least read access to the file
- Check that the SharePoint MCP server is connected

### Download fails with 403/401

Your Azure CLI session may not have the right permissions. Ensure your account has access to the SharePoint site and try:

```bash
az login --scope https://graph.microsoft.com/.default
```

### Large file download times out

Increase the timeout (default is 600 seconds):

```powershell
.\scripts\download-from-sharepoint.ps1 -DriveId "..." -ItemId "..." -OutputFile "..." -TimeoutSec 1200
```
