---
name: dashboard
description: >
  Interactive, live-updating dashboards embedded in the Electron app.
  Each dashboard is a self-contained HTML page rendered in an iframe,
  receiving all memory/ content via postMessage. Dashboards auto-refresh
  when files change and include interactive controls that launch AI sessions.
---

# Dashboard Skill

A multi-dashboard system embedded in the Agency Cowork app. Each dashboard is a standalone HTML page that receives the **entire `memory/` directory** as structured data and renders it however it wants. Dashboards auto-refresh when any file in `memory/` changes and can include interactive controls that launch AI sessions.

**Dashboards can render anything stored in memory/** — knowledgebase articles, daily logs, weekly reports, JSON data files, CSV exports, YAML configs, and any other text content. If you want to visualize, browse, or interact with your data, a dashboard can do it.

**Triggers:** "open dashboard", "show dashboard", "customize dashboard", "create a new dashboard"

## Keeping Content Fresh

Dashboards automatically re-render when files in `memory/` change, but the **content itself** needs to be kept up to date. If a dashboard visualizes data that should be refreshed on a schedule (e.g., project status pulled from ADO, meeting notes from Teams, weekly metrics), create a **scheduled task** to update the underlying files:

```
Schedule a recurring task to update memory/Knowledgebase/project-status.md
with the latest information from ADO every morning at 9am
```

The task-scheduler skill can run AI sessions on a cron schedule that write updated content to `memory/`. The dashboard will auto-refresh when those files change — no dashboard rebuild needed.

**Pattern:** Scheduled task writes data → file lands in `memory/` → file watcher fires → dashboard re-renders with fresh data.

## Creating New Dashboards

Create new dashboards by writing a self-contained HTML file directly to `memory/Dashboards/<name>.html`. The file must include the postMessage bridge code below to receive data from the Electron host. Use the starter template at `skills/dashboard/templates/dashboard.html` as a reference.

**IMPORTANT:** Dashboards render inside an iframe in the Electron app — do NOT open them in a browser with `Start-Process` or `open`. Save the HTML file to `memory/Dashboards/` and it will appear in the sidebar automatically.

### Required postMessage Bridge

Every dashboard HTML file must include this bridge code to receive data from the Electron host:

```javascript
// Request data on load
window.addEventListener("message", (e) => {
  if (!e.data || e.data.channel !== "dashboard-data") return;
  if (e.data.type === "data-payload") renderDashboard(e.data.payload);
  if (e.data.type === "data-changed") requestData(); // re-request on file change
  if (e.data.type === "file-content") onFileContent(e.data.requestPath, e.data.payload);
});

function requestData() {
  parent.postMessage({ channel: "dashboard-action", type: "request-data" }, "*");
}

// Fetch full (untruncated) content of a specific file
function getFile(filePath) {
  parent.postMessage({ channel: "dashboard-action", type: "get-file", payload: { path: filePath } }, "*");
}

// Launch an AI task (title is optional — sets the chat name in the sidebar)
function startTask(prompt, title) {
  parent.postMessage({ channel: "dashboard-action", type: "start-task", payload: { prompt, title } }, "*");
}

// Open a file externally
function openFile(absPath) {
  parent.postMessage({ channel: "dashboard-action", type: "open-file", payload: { path: absPath } }, "*");
}

// ── Content CRUD (create, update, delete files in memory/) ──
const _pendingSave = {}, _pendingDelete = {}, _pendingPatch = {};

function saveFile(filePath, content) {
  return new Promise((resolve) => {
    _pendingSave[filePath] = resolve;
    parent.postMessage({ channel: "dashboard-action", type: "save-file", payload: { path: filePath, content } }, "*");
    setTimeout(() => { if (_pendingSave[filePath]) { delete _pendingSave[filePath]; resolve({ error: "Timeout" }); } }, 10000);
  });
}

function deleteFile(filePath) {
  return new Promise((resolve) => {
    _pendingDelete[filePath] = resolve;
    parent.postMessage({ channel: "dashboard-action", type: "delete-file", payload: { path: filePath } }, "*");
    setTimeout(() => { if (_pendingDelete[filePath]) { delete _pendingDelete[filePath]; resolve({ error: "Timeout" }); } }, 10000);
  });
}

function patchFrontmatter(filePath, fields) {
  return new Promise((resolve) => {
    _pendingPatch[filePath] = resolve;
    parent.postMessage({ channel: "dashboard-action", type: "patch-frontmatter", payload: { path: filePath, fields } }, "*");
    setTimeout(() => { if (_pendingPatch[filePath]) { delete _pendingPatch[filePath]; resolve({ error: "Timeout" }); } }, 10000);
  });
}

// Listen for CRUD results
window.addEventListener("message", (e) => {
  if (!e.data || e.data.channel !== "dashboard-data") return;
  const { type, payload, requestPath } = e.data;
  if (type === "save-result" && _pendingSave[requestPath]) {
    _pendingSave[requestPath](payload); delete _pendingSave[requestPath];
  } else if (type === "delete-result" && _pendingDelete[requestPath]) {
    _pendingDelete[requestPath](payload); delete _pendingDelete[requestPath];
  } else if (type === "patch-result" && _pendingPatch[requestPath]) {
    _pendingPatch[requestPath](payload); delete _pendingPatch[requestPath];
  }
});

// Handle full file content response
function onFileContent(requestPath, result) {
  if (result.error) return console.warn("File fetch failed:", result.error);
  // result = { content, sizeKB, modifiedAt, path, absPath }
}

// Request initial data
if (window.parent !== window) requestData();
```

### Workflow

1. Read the starter template at `skills/dashboard/templates/dashboard.html` to understand the structure
2. Create a new HTML file with the postMessage bridge code, a `renderDashboard(data)` function, and your layout/styling
3. Save to `memory/Dashboards/<name>.html`
4. The dashboard appears in the sidebar automatically — no browser launch needed

## Architecture

### Multi-Dashboard Structure
- **`templates/dashboard.html`** — Starter template (reference implementation)
- **`memory/Dashboards/*.html`** — Active dashboards (syncs via OneDrive)
- Sidebar shows a collapsible list of all dashboards
- Each dashboard is independently customizable

### Data Flow

```
Electron main.js                  DashboardView (React)             dashboard.html (iframe)
    │                                    │                                  │
    │  scans memory/ recursively         │                                  │
    │  ◄── dashboard:getData ──          │                                  │
    │  ──► { memory: {...} } ──►         │  ──► postMessage(data) ──►       │
    │                                    │                                  │  renders
    │  fs.watch(memory/) fires           │                                  │
    │  ──► dashboard:dataChanged ──►     │  ──► postMessage(changed) ──►    │
    │                                    │                                  │  re-requests
```

### Interactive Actions

Dashboards can include controls that launch AI sessions:

| Action Type | postMessage | Effect |
|-------------|-------------|--------|
| `start-task` | `{ channel: 'dashboard-action', type: 'start-task', payload: { prompt, title? } }` | Creates new AI task with the prompt. Optional `title` sets the chat name in the sidebar (defaults to first 80 chars of prompt). |
| `request-data` | `{ channel: 'dashboard-action', type: 'request-data' }` | Fetches fresh data from memory/ |
| `get-file` | `{ channel: 'dashboard-action', type: 'get-file', payload: { path } }` | Fetches full (untruncated) file content; response arrives as `file-content` message |
| `open-file` | `{ channel: 'dashboard-action', type: 'open-file', payload: { path } }` | Opens file in default app |
| `save-file` | `{ channel: 'dashboard-action', type: 'save-file', payload: { path, content } }` | Create/overwrite a file in memory/ (max 512KB, no `.html` in Dashboards/) |
| `delete-file` | `{ channel: 'dashboard-action', type: 'delete-file', payload: { path } }` | Delete a file from memory/ (no `.html` in Dashboards/) |
| `patch-frontmatter` | `{ channel: 'dashboard-action', type: 'patch-frontmatter', payload: { path, fields } }` | Update YAML frontmatter fields without rewriting the file body |

### Content CRUD — Write Operations

Dashboards can create, update, and delete files directly in `memory/` without spawning an AI session. This enables interactive buttons like "Mark Complete", inline editing, and "New Entry" forms.

**Security constraints:**
- Paths must be within `memory/` (no `..` traversal)
- Cannot overwrite dashboard HTML files in `memory/Dashboards/*.html`
- `saveFile` content limited to 512KB
- All paths are relative to the workspace root (e.g., `memory/Knowledgebase/my-file.md`)

**JavaScript helpers** (included in the starter template):

```javascript
// Create or overwrite a file
const result = await saveFile('memory/Knowledgebase/new-article.md', '# Title\n\nContent here');
// → { ok: true, path: '...', modifiedAt: '...' } or { error: 'message' }

// Delete a file
const result = await deleteFile('memory/Knowledgebase/old-article.md');
// → { ok: true, path: '...' } or { error: 'message' }

// Update specific frontmatter fields (preserves the rest of the file)
const result = await patchFrontmatter('memory/Projects/my-project.md', {
  status: 'complete',
  completed_date: '2026-03-24'
});
// → { ok: true, path: '...', modifiedAt: '...' } or { error: 'message' }
```

**Auto-refresh:** After any CRUD operation, the file watcher detects the change and the dashboard auto-refreshes — no manual reload needed.

**Response messages** sent back from the host:

| Response Type | Payload |
|---------------|---------|
| `save-result` | `{ ok: true, path, modifiedAt }` or `{ error: 'message' }` |
| `delete-result` | `{ ok: true, path }` or `{ error: 'message' }` |
| `patch-result` | `{ ok: true, path, modifiedAt }` or `{ error: 'message' }` |

## Data Schema

The Electron main process scans the **entire `memory/` directory** and returns all text content. Dashboards interpret the data however they need — no hardcoded schema assumptions.

### Scanned File Types
`.md`, `.json`, `.txt`, `.csv`, `.yaml`, `.yml`, `.toml`, `.xml`, `.html`

### Payload Structure

```json
{
  "memory": {
    "Knowledgebase": {
      "name": "Knowledgebase",
      "count": 12,
      "newest": "2026-03-24T20:00:00Z",
      "files": [
        {
          "name": "article title",
          "filename": "article-title.md",
          "ext": ".md",
          "path": "article-title.md",
          "absPath": "C:/cowork/agency-cowork/memory/Knowledgebase/article-title.md",
          "sizeKB": 4.2,
          "modifiedAt": "2026-03-24T20:00:00Z",
          "content": "# Full file content (capped at 30KB)...",
          "truncated": false
        },
        {
          "name": "security review",
          "filename": "security-review.md",
          "ext": ".md",
          "path": "Workstreams/security-review.md",
          "absPath": "C:/cowork/agency-cowork/memory/Knowledgebase/Workstreams/security-review.md",
          "sizeKB": 1.8,
          "modifiedAt": "2026-03-20T10:00:00Z",
          "content": "...",
          "truncated": false
        }
      ]
    },
    "DailyLogs": { "name": "DailyLogs", "count": 30, "files": [...] },
    "_root": { "name": "_root", "files": [...] }
  },
  "workDir": "C:/cowork/agency-cowork",
  "generatedAt": "2026-03-24T20:00:00Z"
}
```

**Key points:**
- **Only top-level directories** in `memory/` become category keys (e.g., `Knowledgebase`, `DailyLogs`)
- **Subdirectories are NOT promoted** to their own category — they stay nested under the parent. Files in `memory/Knowledgebase/Workstreams/` appear in the `Knowledgebase` category with `path: "Workstreams/security-review.md"`
- The `path` field is **relative to the category directory**, not to `memory/`. To build the full memory-relative path for AI prompts, use `memory/{category}/{path}` (e.g., `memory/Knowledgebase/Workstreams/security-review.md`)
- Top-level files in `memory/` go into `_root`
- `.json` files are delivered as raw string content — the dashboard parses them client-side
- Content capped at 30KB per file; `truncated: true` if exceeded. Use the `get-file` action to fetch full content on demand
- `Dashboards/` directory is excluded from the scan (avoid recursion)

## Customization

Each dashboard is an independent HTML file in `memory/Dashboards/`. To customize:

1. Read `memory/Dashboards/<name>.html` to understand the current structure
2. Edit the HTML/CSS/JS directly
3. Changes take effect immediately (the file watcher detects changes and hot-reloads)

### Tips
- **Any file in `memory/` is available** — markdown, JSON, CSV, YAML, XML, TOML, plain text
- Parse `.json` files client-side: `const data = JSON.parse(file.content)`
- Filter by category: `data.memory.Knowledgebase` for KB articles, `data.memory.DailyLogs` for logs, etc.
- Add interactive buttons that call `startTask("your prompt here")`
- The same data payload goes to all dashboards — each renders it differently
- Use visual-explainer aesthetics (Paper/Ink, Blueprint, Editorial) for consistent design
- **To keep dashboard data fresh**, create scheduled tasks that write updated content to `memory/`. The dashboard auto-refreshes when files change — you never need to rebuild the dashboard itself.

### Example Use Cases

| Dashboard | Data Source | Scheduled Task |
|-----------|------------|----------------|
| Knowledge Base browser | `memory/Knowledgebase/*.md` | None needed — updated by AI sessions |
| Project status tracker | `memory/Knowledgebase/project-status.json` | Daily: pull latest from ADO |
| Weekly metrics | `memory/WeeklyReports/*.md` | Weekly: generate report from M365 data |
| Meeting notes viewer | `memory/Knowledgebase/Meetings/*.md` | After each meeting: summarize transcript |
| Team directory | `memory/Knowledgebase/team-roster.json` | Weekly: refresh from org chart |

## Debugging

Three debug tools help AI sessions diagnose dashboard issues:

### 1. Data Dump

The `dashboard:dumpData` IPC writes a JSON snapshot of the data payload to `memory/Dashboards/.debug-data.json`. File contents are replaced with `contentLength` and a 200-char `contentPreview` to keep the file readable.

To trigger: ask the AI to run `window.electronAPI.dumpDashboardData()` or read `memory/Dashboards/.debug-data.json` after a dashboard load. The file shows exactly what categories, files, and paths the dashboard receives.

### 2. Console Capture

Dashboard errors and warnings are automatically sent from the iframe to the Electron host via postMessage, which appends them to `memory/Dashboards/.debug-log.txt` with timestamps and severity levels.

The starter template includes this capture automatically. For custom dashboards, add this bridge code:

```javascript
function logToParent(level, ...args) {
  const message = args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ');
  parent.postMessage({ channel: "dashboard-action", type: "console-log", payload: { level, message } }, "*");
}
console.error = (...args) => { logToParent('error', ...args); };
console.warn = (...args) => { logToParent('warn', ...args); };
window.addEventListener('error', (e) => {
  logToParent('error', `Unhandled: ${e.message} at ${e.filename}:${e.lineno}:${e.colno}`);
});
```

### 3. Error Boundary

The starter template wraps `render()` in a try/catch. If rendering fails, the error and stack trace are displayed visibly in the dashboard content area (red box with monospace text) AND logged to the console capture above.

### Debug Workflow for AI

When debugging a dashboard that isn't rendering correctly:

1. Read `memory/Dashboards/.debug-log.txt` for JavaScript errors
2. Read `memory/Dashboards/.debug-data.json` to inspect the data payload structure
3. Read the dashboard HTML source at `memory/Dashboards/<name>.html`
4. Fix the issue and save — the dashboard hot-reloads automatically

## Files

```
skills/dashboard/
├── .claude-plugin/plugin.json        — Skill registration
├── skill.json                        — Skill metadata
├── skills/dashboard/SKILL.md         — This file
├── templates/
│   └── dashboard.html                — Starter template (reference implementation)
└── commands/
    └── customize.md                  — AI command for dashboard customization

memory/Dashboards/
└── *.html                            — User dashboards (created from template or AI)
```
