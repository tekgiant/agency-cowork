When the user asks to customize a dashboard's layout, style, sections, or behavior:

1. Read the target dashboard file. Dashboards live in `memory/Dashboards/`:
   ```
   view memory/Dashboards/<name>.html
   ```
   For the starter template: `view skills/dashboard/templates/dashboard.html`

2. Understand the request — common patterns:
   - **Add a section**: Create a new render function and call it from `render()`
   - **Rearrange layout**: Modify the CSS grid or reorder render calls
   - **Change theme**: Modify CSS custom properties in `:root`
   - **Add AI buttons**: Add `onclick="startTask('your prompt here', 'Chat Title')"` to any element
   - **Add charts/visualizations**: Add inline SVG or Canvas-based rendering
   - **Filter/group files**: Modify `getFilteredCategories()` or add new grouping logic

3. Edit the file directly — each dashboard is a single self-contained HTML file

4. The dashboard auto-refreshes when memory/ files change. For HTML changes, the user can click away and back to reload.

**Data available via postMessage — `renderDashboard(data)` receives:**
```json
{
  "memory": {
    "Knowledgebase": { "name": "Knowledgebase", "count": 12, "newest": "ISO", "files": [
      { "name": "Title", "filename": "title.md", "ext": ".md", "path": "relative",
        "absPath": "absolute", "sizeKB": 4.2, "modifiedAt": "ISO",
        "content": "raw file content (up to 30KB)", "truncated": false }
    ]},
    "DailyLogs": { "name": "DailyLogs", "count": 30, "files": [...] },
    "_root": { "name": "_root", "files": [...] }
  },
  "workDir": "C:/cowork/agency-cowork",
  "generatedAt": "ISO timestamp"
}
```

- Each top-level directory in `memory/` becomes a category key
- Top-level files go into `_root`
- `.json` files are raw strings — parse them client-side with `JSON.parse(f.content)`
- `Dashboards/` is excluded from the scan

**Interactive actions (postMessage to parent):**
- `startTask(prompt, title?)` — launches a new AI session with the given prompt. Optional `title` sets the sidebar chat name (defaults to first 80 chars of prompt).
- `openFile(absPath)` — opens a file in the default external app
- `requestData()` — re-fetches all memory/ data
- `getFile(path)` — fetches full (untruncated) content of a specific file

**Content CRUD (direct file operations, no AI session needed):**
- `await saveFile(path, content)` — Create or overwrite a file in memory/ (max 512KB). Returns `{ ok, path, modifiedAt }` or `{ error }`.
- `await deleteFile(path)` — Delete a file from memory/. Returns `{ ok, path }` or `{ error }`.
- `await patchFrontmatter(path, { key: value })` — Update YAML frontmatter fields without touching the body. Creates frontmatter if none exists. Returns `{ ok, path, modifiedAt }` or `{ error }`.

All CRUD paths must start with `memory/`. Dashboard HTML files (`memory/Dashboards/*.html`) are write-protected. After any write, the file watcher auto-refreshes the dashboard.

**Example patterns:**
```javascript
// "Mark Complete" button
await patchFrontmatter('memory/Projects/alpha.md', { status: 'complete', completed: new Date().toISOString().split('T')[0] });

// Inline content editor
await saveFile('memory/Knowledgebase/notes.md', textarea.value);

// Delete with confirmation
if (confirm('Delete this file?')) await deleteFile('memory/Knowledgebase/old-note.md');
```
