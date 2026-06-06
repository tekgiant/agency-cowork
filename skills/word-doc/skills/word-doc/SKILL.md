---
name: word-doc
description: >
  This skill should be used when the user asks to "create a Word document", "edit a Word file",
  "update a docx", "read a Word file", "inspect a document", "get document content",
  "comment on a document", "reply to a comment", or wants to create, read, edit, or collaborate
  on Microsoft Word documents. Supports both cloud (MCP/OneDrive) and local (python-docx) editing.
  Primary workflow is edit-first: download → inspect → batch edit → upload back.
---

# Word Doc Skill

Create, read, inspect, edit, and comment on Microsoft Word documents. Two engines:

| Engine | Best For | How |
|--------|----------|-----|
| **MCP** (cloud) | Create in OneDrive, read via URL, comment/reply | `microsoft-word-*` MCP tools |
| **Local** (python-docx) | Inspect structure, batch edit, find/replace, tables, headers/footers | `scripts/docx_editor.py` |

## Primary Workflow: Edit Existing Files

```
1. Download from SharePoint  →  sharepoint skill (or MCP GetDocumentContent for read-only)
2. Check for DRM (OLE2 header?)  →  office_common/drm_handler.ps1 -Action capture
3. Strip DRM if present      →  office_common/drm_handler.ps1 -Action strip
4. Inspect the document       →  docx_editor --action inspect
5. Plan edits                 →  agent reasons about what to change
6. Apply edits (batch)        →  docx_editor --action batch --ops-json '[...]'
7. Re-apply DRM if present    →  office_common/drm_handler.ps1 -Action apply
8. Upload back                →  sharepoint skill
```

> **DRM-protected files:** Many Microsoft files use IRM, which wraps the DOCX in an OLE2 container (`D0 CF` header). `python-docx` cannot read these directly — strip via COM first using `skills/office_common/drm_handler.ps1`. Always re-apply DRM after editing. See the PowerPoint skill's DRM Workflow section for detailed examples.

### Step 1: Inspect

```powershell
cd skills/word-doc
python -m scripts.docx_editor -i "../../output/doc.docx" --action inspect
```

Returns: paragraph count, table count, section count, styles in use, paragraph details (index, style, text, runs with formatting), table headers + preview rows, headers/footers, page dimensions.

### Step 2: Edit (Single or Batch)

**Batch edit** (preferred):
```powershell
python -m scripts.docx_editor -i doc.docx --action batch --ops-json '[
  {"action": "find-replace", "find": "Q3 2025", "replace": "Q4 2025"},
  {"action": "update-paragraph", "index": 5, "text": "Updated content here"},
  {"action": "insert-paragraph", "index": 3, "text": "New section", "style": "Heading 2"},
  {"action": "delete-paragraph", "index": 12},
  {"action": "update-table-cell", "table": 0, "row": 2, "col": 1, "text": "Complete"},
  {"action": "add-table-row", "table": 0, "values": ["New Item", "Pending", "TBD"]},
  {"action": "update-header", "text": "Program Status — Confidential"},
  {"action": "update-footer", "text": "Confidential"}
]'
```

**Single-action edits:**
```powershell
python -m scripts.docx_editor -i doc.docx --action find-replace --find "OLD" --replace "NEW"
python -m scripts.docx_editor -i doc.docx --action update-paragraph --index 3 --text "New text"
python -m scripts.docx_editor -i doc.docx --action insert-paragraph --index 5 --text "Inserted" --style "Heading 2"
python -m scripts.docx_editor -i doc.docx --action update-table-cell --table 0 --row 1 --col 2 --text "Done"
python -m scripts.docx_editor -i doc.docx --action extract-text
```

### Batch Actions Reference

| Action | Required Fields | Description |
|--------|----------------|-------------|
| `find-replace` | find, replace | Find/replace across paragraphs and tables |
| `update-paragraph` | index, text, style? | Update paragraph text (preserves formatting) |
| `insert-paragraph` | index, text, style? | Insert before index |
| `delete-paragraph` | index | Remove a paragraph |
| `update-table-cell` | table, row, col, text | Update a table cell |
| `add-table-row` | table, values[] | Append row to table |
| `add-table` | headers[], rows[][] | Add new table at end |
| `update-header` | text, section? | Update section header |
| `update-footer` | text, section? | Update section footer |

## Key Features

### Document Creation

- Create Word documents directly in OneDrive root
- Support for **HTML content** for rich formatting (headings, tables, lists, bold/italic, links)
- Support for **plain text** content
- Auto-generated file names with timestamp when `fileName` is empty
- Optionally share the document immediately with a colleague via `shareWith`
- Returns full Microsoft Graph DriveItem metadata (id, webUrl, size, etc.)

### Document Retrieval

- Fetch content from **SharePoint** or **OneDrive** sharing URLs
- Returns plain text extraction of the document body
- Returns all **comments** in the document (with IDs for replying)
- Returns document metadata: filename, size, driveId, documentId

### Comment Collaboration

- Add new comments to documents for review/feedback
- Reply to existing comment threads
- Full comment thread support — use `commentId` from `GetDocumentContent` results
- Requires `driveId` and `documentId` from a prior `GetDocumentContent` call

## Workflow

### Creating a New Document

1. **Gather details** from the user:
   - **File name** (optional — leave empty for auto-generated name)
   - **Content** — the document body as HTML or plain text
   - **Share with** (optional) — email address to share the new document with

2. **Compose the content**:
   - If the user provides raw text, use it directly
   - If the user describes what they want, compose HTML content with appropriate formatting
   - Use HTML tags for structure: `<h1>`, `<h2>`, `<p>`, `<ul>`, `<ol>`, `<table>`, `<b>`, `<i>`, `<a>`
   - Ensure all HTML tags and URLs are valid

3. **Confirm before creating** — present a summary of the document to be created:
   ```
   File name: <name>.docx (or auto-generated)
   Content preview: <first ~200 chars>
   Share with: <email> (if specified)
   ```

4. **Create the document** using `microsoft-word-CreateDocument`

5. **Report results** — share the document URL with the user

### Reading a Document

1. User provides a **SharePoint or OneDrive URL**
2. Call `microsoft-word-GetDocumentContent` with the URL
3. Present the document content, metadata, and any existing comments
4. Store `driveId` and `documentId` for subsequent comment operations

### Adding Comments

1. **Read the document first** using `GetDocumentContent` to obtain `driveId` and `documentId`
2. Compose the comment text
3. Call `microsoft-word-AddComment` with `driveId`, `documentId`, and `newComment`
4. Confirm to the user that the comment was added

### Replying to Comments

1. **Read the document first** using `GetDocumentContent` to obtain existing comments with their IDs
2. Identify the target comment by presenting the list of comments to the user
3. Compose the reply text
4. Call `microsoft-word-ReplyToComment` with `commentId`, `driveId`, `documentId`, and `newComment`
5. Confirm to the user that the reply was posted

## HTML Content Tips

When creating documents with rich formatting, use standard HTML:

```html
<h1>Document Title</h1>
<p>Introduction paragraph with <b>bold</b> and <i>italic</i> text.</p>

<h2>Section Heading</h2>
<ul>
  <li>Bullet point one</li>
  <li>Bullet point two</li>
</ul>

<table>
  <tr><th>Header 1</th><th>Header 2</th></tr>
  <tr><td>Cell 1</td><td>Cell 2</td></tr>
</table>
```

## OneDrive Upload

To upload finished documents to OneDrive, use the sync folder approach (see CLAUDE.md for details):

```bash
bash skills/shared/upload-to-onedrive.sh "output/document.docx" "Agency Cowork Outputs"
```

Do NOT use Graph API, MCP upload tools, or PowerShell for OneDrive uploads.

## Rules

- **ALWAYS** confirm with the user before creating a document — never create without explicit approval
- **ALWAYS** ensure HTML tags are valid and properly closed when using HTML content
- **ALWAYS** read the document first (via `GetDocumentContent`) before attempting comment operations — you need the `driveId` and `documentId`
- **ALWAYS** share the document URL with the user after creation
- **NEVER** include sensitive information (passwords, keys, secrets) in document content
- **NEVER** guess or fabricate `driveId`, `documentId`, or `commentId` — always obtain from MCP responses
- If the user provides a SharePoint/OneDrive URL, use `GetDocumentContent`; if they want to create from scratch, use `CreateDocument`
- For document content that the user describes rather than dictates, compose appropriate formatted content and confirm before creating
- When the user asks to "share" a document, use the `shareWith` parameter on `CreateDocument` or use SharePoint MCP's `shareFileOrFolder` for existing documents
