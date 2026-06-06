# Installation Guide — Agency Cowork

First-time setup instructions for the Agency Cowork workspace, including Agency tooling, MCP servers, and all skills.

## Desktop App Installer (Recommended)

The easiest way to get started is with the desktop app installer, which bundles a graphical setup wizard:

| Platform | Download | Notes |
|----------|----------|-------|
| Windows | [Agency Cowork Setup 0.9.0.exe](https://github.com/ahsi-microsoft/agency-cowork/releases/latest) | Unsigned — click **More info → Run anyway** at SmartScreen prompt |
| macOS (Apple Silicon) | [Agency Cowork-0.9.0-arm64.dmg](https://github.com/ahsi-microsoft/agency-cowork/releases/latest) | Unsigned — see macOS note below |
| macOS (Intel) | [Agency Cowork-0.9.0.dmg](https://github.com/ahsi-microsoft/agency-cowork/releases/latest) | Unsigned — see macOS note below |

> **Windows:** The installer is unsigned — Windows SmartScreen will prompt on first run. Click **More info → Run anyway** to proceed.
>
> **macOS:** The DMG is unsigned. After mounting and dragging to Applications, run: `xattr -d com.apple.quarantine /Applications/Agency\ Cowork.app` to bypass Gatekeeper.

The setup wizard walks you through:
1. Choosing a working directory for your project files
2. Extracting the bundled Agency Cowork template
3. Running the setup script (agent identity, MCP config, skill registration, security)
4. Optionally applying org-specific config from a private repo
5. Verifying the Agency CLI is installed

### Updating an Existing Installation

When a new version of the installer is run over an existing setup, the wizard automatically detects the previous installation and switches to a streamlined **update flow**:

- Creates a timestamped backup before making changes
- **Preserves:** `CLAUDE.md`, `AGENTS.md`, `memory/`, `agentconfig.json` (monitor config auto-preserved at `~/.agency-cowork/monitor-config.json`)
- **Updates:** `scripts/`, `skills/` (merged — user-created skills are preserved), `.config/`, `tests/`, docs
- Optionally re-syncs org-specific config

All releases are available at [github.com/ahsi-microsoft/agency-cowork/releases](https://github.com/ahsi-microsoft/agency-cowork/releases).

---

## CLI Setup (Alternative)

If you prefer a command-line setup or are on macOS/Linux, use the interactive setup script:

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

**macOS / Ubuntu (Bash):**
```bash
bash scripts/setup.sh
```

The wizard will:
1. Verify you've forked the repo (blocks setup on the base project)
2. Customize your agent identity (name, role) and user profile
3. Auto-detect your Microsoft 365 tenant ID and configure MCP servers
4. Register all 12 local skills
5. Install git hooks and harden file permissions
6. Optionally install MarkItDown, QMD, Handy (speech-to-text), and Specify CLI
7. Run the security audit and offline test suite

**After running the wizard**, come back to this document for:
- [Marketplace plugins](#marketplace-plugins) (ADO Explorer)
- [Obsidian setup](#8-install-obsidian) (optional)
- [Troubleshooting](#troubleshooting)

---

## Manual Setup Reference

The sections below document each setup step individually. Use these if you prefer manual configuration or need to re-run a specific step.

### Headless (agent-driven, zero prompts)

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Headless -TenantId "<your-tenant-id>"
```

**macOS / Ubuntu:**
```bash
bash scripts/setup.sh --headless --tenant-id "<your-tenant-id>"
```

The script auto-detects your UPN from Azure CLI (`az account show`) or `git config user.email`, reads agent identity from `CLAUDE.md`, and syncs the memory repo from `agentconfig.json`. All optional dependencies are installed by default.

**Common options:**

| Parameter (PS1 / sh) | Default | Description |
|-----------|---------|-------------|
| `-Headless` / `--headless` | — | Zero interactive prompts; all values from params/auto-detect/defaults |
| `-TenantId` / `--tenant-id` | Auto-detect via `az` | Microsoft Entra tenant ID (GUID) |
| `-UserEmail` / `--user-email` | Auto-detect | Your UPN/email |
| `-MemoryRepo` / `--memory-repo` | From `agentconfig.json` | Memory repository URL |
| `-InstallDeps` / `--install-deps` | `"all"` | Comma-separated: `markitdown`, `qmd`, `specify`, `all`, `none` |
| `-SkipPersonalization` / `--skip-personalization` | — | Skip Phase 2 prompts but keep other phases interactive |
| `-SkipForkCheck` / `--skip-fork-check` | — | Skip fork verification |
| `-AgentName` / `--agent-name` | From `CLAUDE.md` | Override agent name |
| `-AgentRole` / `--agent-role` | From `CLAUDE.md` | Override agent role |

**Examples:**

```powershell
# Windows — Full headless with Microsoft corporate tenant
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Headless -TenantId "72f988bf-86f1-41af-91ab-2d7cd011db47"

# Windows — Headless, skip optional dependencies
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Headless -TenantId "72f988bf-86f1-41af-91ab-2d7cd011db47" -InstallDeps none

# Windows — Interactive wizard (prompts for every decision)
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

```bash
# macOS / Ubuntu — Full headless with Microsoft corporate tenant
bash scripts/setup.sh --headless --tenant-id "72f988bf-86f1-41af-91ab-2d7cd011db47"

# macOS / Ubuntu — Headless, skip optional dependencies
bash scripts/setup.sh --headless --tenant-id "72f988bf-86f1-41af-91ab-2d7cd011db47" --install-deps none

# macOS / Ubuntu — Interactive wizard
bash scripts/setup.sh
```

### What the script does

| Phase | Description |
|-------|-------------|
| **Prerequisites** | Installs packages via `winget` (Windows), `brew` (macOS), or `apt` (Ubuntu) |
| **Phase 1** | Fork verification (skipped in headless) |
| **Phase 1.5** | Creates `CLAUDE.md` and `AGENTS.md` from `.example` templates if they don't already exist |
| **Phase 2** | Agent identity & memory sync — reads `CLAUDE.md` + `agentconfig.json`, auto-detects UPN, clones/pulls memory repo |
| **Phase 3** | Azure CLI login + MCP server config — writes `~/.copilot/mcp-config.json` with WorkIQ, Teams, Outlook, Calendar, Word, SharePoint, QMD |
| **Phase 4** | Registers all 19 local skills in `~/.copilot/config.json` |
| **Phase 5** | Installs pre-commit hook, hardens file permissions, runs security audit |
| **Phase 6** | Optional dependencies — MarkItDown, QMD, Handy, Specify CLI, Teams monitor |
| **Phase 7** | Runs offline test suite |

After setup completes, start a new Copilot session and run `/skills` to verify all skills are loaded.

> **Note:** If you prefer manual step-by-step setup or need to troubleshoot individual components, see the detailed sections below.

### Organization-Specific Configuration

The desktop app setup wizard includes an optional org config step that clones a private repo and overlays org-specific files (ADO queries, Confluence spaces, report structures) onto your project. The repo URL is saved for automatic re-sync on future updates.

If using CLI setup instead, clone the org skill manually after running the main setup:

```bash
cd skills/
git clone https://github.com/your-org/your-setup.git
cd your-setup
pwsh apply.ps1
```

This applies org-specific configuration (ADO queries, Confluence spaces, report structures) on top of the generic template. The skill directory is gitignored so org data stays out of the public repo. See the [README](README.md#organization-specific-setup-skills) for the full pattern.

---

## Updating from Upstream

Your fork receives new features, skills, and fixes from the upstream template. The update script pulls these changes while preserving your customizations:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/update.ps1
```

### How it works

| Step | What happens |
|------|-------------|
| **Stash** | Saves any uncommitted local changes |
| **Fetch** | Downloads new commits from `upstream/main` |
| **Merge** | Merges upstream into your branch; auto-resolves conflicts in personalized files by keeping **your** version |
| **Protect** | Backs up and restores `CLAUDE.md`, `AGENTS.md`, and `agentconfig.json` so your identity and settings are never overwritten |
| **Review** | If `.example` templates changed upstream, saves a diff summary and recommends AI-assisted integration |
| **Restore** | Pops stashed changes back |

**Options:**

| Parameter | Description |
|-----------|-------------|
| `-DryRun` | Show what would happen without making changes |
| `-Force` | Skip confirmation prompts |
| `-UpstreamBranch <name>` | Pull from a branch other than `main` |

### Template Pattern

Agent identity and operational rules use a **template pattern** to separate upstream updates from your customizations:

| File | Tracked in Git | Purpose |
|------|----------------|---------|
| `CLAUDE.md.example` | Yes | Upstream template — updated by the project maintainers |
| `AGENTS.md.example` | Yes | Upstream template — updated by the project maintainers |
| `CLAUDE.md` | No (gitignored) | **Your** personalized agent identity |
| `AGENTS.md` | No (gitignored) | **Your** personalized operational rules |

On first run, `setup.ps1` copies the `.example` files to create your local versions. After that, your `CLAUDE.md` and `AGENTS.md` are yours to customize freely — they will never be overwritten by `git pull` or the update script.

### Integrating Upstream Template Changes

When the upstream `.example` templates gain new features (new skills, updated security rules, etc.), the update script flags this and recommends using your AI coworker to merge them:

1. Run `scripts/update.ps1`
2. If templates changed, the script saves a diff to `.update-backup/template-changes.md`
3. Start a new Copilot session and ask:

> "Read `.update-backup/template-changes.md` and integrate the upstream changes into my `CLAUDE.md` and `AGENTS.md` while preserving my customizations."

The AI agent will read both files, identify what's new in the template, and surgically add new features without overwriting your identity, domain knowledge, or communication preferences.

---

## Table of Contents (Manual Setup)

- [Prerequisites](#prerequisites)
- [1. Install Agency](#1-install-agency)
- [2. Configure Memory Repository](#2-configure-memory-repository)
- [3. Configure MCP Servers](#3-configure-mcp-servers)
- [4. Register Local Skills](#4-register-local-skills)
  - [Marketplace Plugins](#marketplace-plugins)
- [5. Install Git Hooks](#5-install-git-hooks)
- [6. Harden File Permissions](#6-harden-file-permissions)
- [7. Install Skill Dependencies](#7-install-skill-dependencies)
  - [Deep Research](#deep-research)
  - [Send Email](#send-email)
  - [MarkItDown](#markitdown)
  - [Spec Kit](#spec-kit)
  - [Weekly Report](#weekly-report)
  - [Task Scheduler](#task-scheduler)
  - [Teams Rich Messaging & Monitor Service](#teams-rich-messaging--monitor-service)
  - [SharePoint](#sharepoint)
  - [OnePlanner](#oneplanner)
  - [QMD Memory](#qmd-memory)
- [8. Install Obsidian](#8-install-obsidian)
- [9. Run Security Audit](#9-run-security-audit)
- [10. Verify Installation](#10-verify-installation)

---

## Manual Setup

The sections below document each step individually for reference and troubleshooting.

---

## Prerequisites

- **Windows 10/11**, **macOS**, or **Linux**
- **Python 3.10+** installed
- **Microsoft Outlook** MCP configured (required for send-email skill — see [Configure MCP Servers](#3-configure-mcp-servers))
- **Git** installed

---

## 1. Install Agency

Agency is the environment that powers the AI agent tooling. Full documentation is available at [https://aka.ms/Agency](https://aka.ms/Agency) (VPN required).

### Windows

Open PowerShell and run:

```powershell
iex "& { $(irm aka.ms/InstallTool.ps1)} agency"
```

### macOS / Linux

Open a terminal and run:

```bash
curl -sSfL https://aka.ms/InstallTool.sh | sh -s agency && exec $SHELL -l
```

After installation, restart your terminal to ensure all PATH changes take effect.

---

## 2. Configure Memory Repository

The `memory/` directory (MEMORY.md, daily logs, knowledgebase) is stored in a **separate Git repository** to keep personal data private and portable. Each user configures their own memory repo.

### Create your memory repo

1. Create a new **private** GitHub repository (e.g., `your-org/agent-memory`)
2. Push your initial memory contents there (see the [agent-memory template](https://github.com/YOUR-ORG/agent-memory) for the expected structure)

### Configure the memory repo URL

Edit `agentconfig.json` in the project root and set `memory.repo` to your repo URL:

```json
{
  "memory": {
    "repo": "https://github.com/your-org/agent-memory.git",
    "branch": "main",
    ...
  }
}
```

### Sync memory

Run the sync script to clone (or pull) the memory repo into `memory/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-memory.ps1
```

This clones the configured repo into `memory/`. On subsequent runs, it pulls the latest changes.

To force a fresh re-clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-memory.ps1 -Force
```

### Verify

```powershell
Test-Path memory/MEMORY.md   # Should return True
```

> **Note:** The `memory/` directory is git-ignored in the framework repo. All memory data lives exclusively in your configured memory repo. Changes to memory (daily logs, knowledgebase updates) should be committed and pushed from `memory/` directly.

---

## 3. Configure MCP Servers

MCP (Model Context Protocol) servers give the agent access to Microsoft 365 data and services. Configure them in your user-level MCP config file:

**Config file location:** `C:\Users\<username>\.copilot\mcp-config.json`

Create or update the file with the following standard MCP servers:

```json
{
  "mcpServers": {
    "workiq": {
      "command": "agency",
      "args": ["mcp", "workiq"]
    },
    "microsoft-teams": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/{your-tenant-id}/servers/mcp_TeamsServer",
      "type": "http"
    },
    "microsoft-outlook-mail": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/{your-tenant-id}/servers/mcp_MailTools",
      "type": "http"
    },
    "microsoft-sharepoint-and-onedrive": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/{your-tenant-id}/servers/mcp_ODSPRemoteServer",
      "type": "http"
    },
    "microsoft-outlook-calendar": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/{your-tenant-id}/servers/mcp_CalendarTools",
      "type": "http"
    },
    "microsoft-word": {
      "url": "https://agent365.svc.cloud.microsoft/agents/tenants/{your-tenant-id}/servers/mcp_WordServer",
      "type": "http"
    },
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
```

> **Note:** The `env.PATH` entry for the QMD server ensures Git for Windows' `bash.exe` is available. QMD's npm wrapper requires `bash.exe` to run. Without this, Windows may resolve `bash.exe` to WSL, which fails if no Linux distribution is installed.
>
> **If WSL has no distros installed**, the setup script automatically detects this and rewrites the QMD config to call Git bash directly:
> ```json
> "qmd": {
>   "command": "C:\\Program Files\\Git\\bin\\bash.exe",
>   "args": ["C:/ProgramData/global-npm/node_modules/@tobilu/qmd/qmd", "mcp"]
> }
> ```
> This bypasses the npm shim entirely. Re-run `setup.ps1` if you install/remove WSL later.

### Finding Your Tenant ID

The Microsoft 365 MCP servers require your **Microsoft Entra (Azure AD) tenant ID** — a GUID that identifies your organization. There are several ways to find it:

#### Option 1: Azure Portal

1. Go to [https://portal.azure.com](https://portal.azure.com)
2. Navigate to **Microsoft Entra ID** (formerly Azure Active Directory)
3. The **Tenant ID** is displayed on the Overview page

#### Option 2: Azure CLI

```bash
az account show --query tenantId -o tsv
```

#### Option 3: PowerShell (Microsoft Graph)

```powershell
Connect-MgGraph -Scopes "Organization.Read.All"
(Get-MgOrganization).Id
```

> Requires the `Microsoft.Graph` PowerShell module: `Install-Module Microsoft.Graph -Scope CurrentUser`

#### Option 4: Microsoft Entra Portal

Visit [https://entra.microsoft.com/#view/Microsoft_AAD_IAM/TenantOverview.ReactView](https://entra.microsoft.com/#view/Microsoft_AAD_IAM/TenantOverview.ReactView) — the **Tenant ID** is shown on the Overview page.

Once you have your tenant ID, replace all instances of `{your-tenant-id}` in the MCP config above.

### Standard MCP Servers

| Server | Type | Purpose |
|--------|------|---------|
| **workiq** | Local (npx) | AI-powered search across Microsoft 365 — emails, meetings, files, and Teams data. Natural language queries powered by M365 Copilot. |
| **microsoft-teams** | Remote (HTTP) | Full Microsoft Teams operations — send/read messages, manage chats, channels, members, and search conversations via Microsoft Graph. |
| **microsoft-outlook-mail** | Remote (HTTP) | Full Outlook Mail operations — send, reply, forward, draft, search, flag, and manage email messages and attachments via Microsoft Graph. |
| **microsoft-sharepoint-and-onedrive** | Remote (HTTP) | SharePoint and OneDrive operations — browse document libraries, read/write files, manage folders, search files, and share documents via Microsoft Graph. |
| **microsoft-outlook-calendar** | Remote (HTTP) | Outlook Calendar operations — create, read, update, and delete calendar events, manage meeting invitations, and query availability via Microsoft Graph. |
| **microsoft-word** | Remote (HTTP) | Microsoft Word operations — create, read, and edit Word documents via Microsoft Graph. |
| **qmd** | Local (CLI) | Local hybrid search engine for markdown files. Indexes memory/, Knowledgebase/, memory/WeeklyReports/. BM25 + vector + LLM re-ranking. Requires `npm install -g @tobilu/qmd`. |

### Setup Notes

- **WorkIQ** runs locally via `npx` and requires Node.js installed. On first use, you will be prompted to accept the EULA at [https://github.com/microsoft/work-iq-mcp](https://github.com/microsoft/work-iq-mcp).
- **Microsoft Teams**, **Microsoft Outlook Mail**, **Microsoft Outlook Calendar**, **Microsoft Word**, and **Microsoft SharePoint and OneDrive** are remote HTTP servers hosted on `agent365.svc.cloud.microsoft`. They authenticate using your Microsoft 365 credentials.
- Replace `{your-tenant-id}` with your organization's Microsoft Entra (Azure AD) tenant ID. See [Finding Your Tenant ID](#finding-your-tenant-id) above.
- **QMD** runs locally and requires Node.js 22+ and ~2GB disk for built-in GGUF models. Install with `npm install -g @tobilu/qmd`. On Windows, QMD's npm wrapper uses `bash.exe` (a shell script), so **Git for Windows** must be installed (`winget install Git.Git`). The MCP config uses `cmd /c` to launch QMD and includes an `env.PATH` entry pointing to Git's `bin/` directory so that `bash.exe` is found. Run the setup script: `powershell -ExecutionPolicy Bypass -File "skills/qmd-memory/scripts/setup-qmd.ps1"`

> **Recommended: SentenceTransformer Embeddings.** QMD now defaults to local embeddings using `BAAI/bge-small-en-v1.5` (384 dimensions) via `sentence-transformers` — pip-installable, no C++ compiler needed, model auto-downloads on first use. A local GGUF backend (`llama-cpp-python`) is also available. Azure OpenAI (`text-embedding-3-large`, 3072 dimensions) is available as an optional fallback for corporate endpoints only — do **not** use personal Azure subscriptions for work content. See the [QMD Memory](#qmd-memory) section below for full setup.

### Verify

Ask the agent questions that exercise each MCP:

```
What meetings do I have this week?              # WorkIQ
Search my emails for messages about the project     # Outlook Mail MCP
What's on my calendar for tomorrow?              # Outlook Calendar MCP
What are the latest messages in the General channel?  # Teams MCP
Find the Everglades hardware spec on SharePoint  # SharePoint & OneDrive MCP
Search my memory for the project milestone decisions  # QMD
```

---

## 4. Register Local Skills

All skills in this project are local (not from a marketplace). Register them as `installed_plugins` entries in your Copilot config file, the same way marketplace plugins are tracked. The `skill_directories` config key does **not** work for Copilot CLI skill loading.

**Config file location:** `C:\Users\<username>\.copilot\config.json`

Each plugin directory already has the correct structure (`.claude-plugin/plugin.json` + `skills/<name>/SKILL.md`), so they load the same way marketplace plugins do — the only difference is `marketplace` is set to `"local"` and `cache_path` points directly to the skill directory in your repo.

Add the following to the `installed_plugins` array in `config.json` (adjust the base path if your repo is cloned elsewhere):

```json
{
  "installed_plugins": [
    {
      "name": "markitdown",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\markitdown"
    },
    {
      "name": "qmd-memory",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\qmd-memory"
    },
    {
      "name": "send-email",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\send-email"
    },
    {
      "name": "sharepoint",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\sharepoint-download"
    },
    {
      "name": "spec-kit",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\spec-kit"
    },
    {
      "name": "task-scheduler",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\task-scheduler"
    },
    {
      "name": "teams",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\teams"
    },
    {
      "name": "weekly-report",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\weekly-report"
    },
    {
      "name": "oneplanner",
      "marketplace": "local",
      "version": "1.0.0",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\oneplanner"
    },
    {
      "name": "visual-explainer",
      "marketplace": "local",
      "version": "0.6.2",
      "installed_at": "2026-03-02T00:00:00Z",
      "enabled": true,
      "cache_path": "C:\\Projects\\agency-cowork\\skills\\visual-explainer"
    }
  ]
}
```

> **Note:** Marketplace plugins (installed via `/plugin install <name>@agency`) also appear in `installed_plugins` but use `"marketplace": "agency"` and are stored in `~/.copilot/installed-plugins/agency/`. For local skills, use `"marketplace": "local"` with `cache_path` pointing to the plugin root in your repo.

### Plugin directory structure

Each skill directory must contain:

```
skills/<name>/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest (name, description, version)
├── skills/
│   └── <name>/
│       └── SKILL.md          # Skill definition with YAML frontmatter
└── agency.json               # Agency plugin metadata
```

After updating `config.json`, restart your Copilot session and verify with `/skills` — all registered skills should appear in the list.

### Marketplace Plugins

Some plugins are installed from the Agency marketplace rather than registered locally. Run these commands in the Copilot CLI:

#### Add the Agency Playground marketplace

```
/plugin marketplace add agency-microsoft/playground
```

#### Install ADO Explorer

```
/plugin install ado-explorer@agency-playground
```

This installs the Azure DevOps explorer plugin, which provides tools for browsing ADO repositories, inspecting pull requests, and querying work items.

---

## 5. Install Git Hooks

The pre-commit hook blocks accidental commits of secrets, API keys, tokens, and large files.

### Automatic (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-hooks.ps1
```

### Manual

```powershell
# Windows
copy scripts\pre-commit .git\hooks\pre-commit
```

```bash
# macOS / Linux
cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

### Verify

```powershell
# This should block the commit with a "BLOCKED: Potential secret" message
git stash
echo "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" > test-secret.txt
git add test-secret.txt
git commit -m "test"
git checkout -- test-secret.txt
Remove-Item test-secret.txt
git stash pop
```

### What It Blocks

| Pattern | Example |
|---------|---------|
| API keys | `AZURE_OPENAI_API_KEY=sk-...` |
| Bearer tokens | `Bearer eyJ...` |
| JWT tokens | `eyJhbGciOi...` |
| PEM private keys | `-----BEGIN RSA PRIVATE KEY-----` |
| Hardcoded passwords | `password = hunter2` |
| `.env` files | `.env`, `.env.local`, `.env.production` |
| Large files | Any file > 1MB |

---

## 6. Harden File Permissions

Restrict access to sensitive files so only your user account (and Administrators/SYSTEM) can read them. This mitigates threats T3 (Memory Poisoning) and T9 (File System Access) from the threat model.

### Run the hardening script

Preview changes first:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harden-permissions.ps1 -DryRun
```

Apply:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harden-permissions.ps1
```

### What It Hardens

| Path | Content |
|------|---------|
| `memory/` | Agent memory, daily logs (`DailyLogs/`), knowledgebase |
| `~/.agency-cowork/` | Global monitor config (identity, per-workspace settings) |
| `CLAUDE.md` | Agent identity file (auto-loaded every session) |
| `skills/task-scheduler/tasks/` | Scheduled task definitions |
| `skills/task-scheduler/logs/` | Task execution logs |
| `~/.copilot/config.json` | Copilot configuration (skill registration) |
| `~/.copilot/mcp-config.json` | MCP server endpoints |

---

## 7. Install Skill Dependencies

Skills are registered in Step 3. Some skills have external dependencies that need to be installed separately.

### Deep Research

A comprehensive research engine with multi-source synthesis, citation tracking, and verification. No additional dependencies required — the skill is self-contained.

**Usage:**

```
Use deep research to analyze the state of quantum computing in 2025
```

See [`skills/claude-deep-research-skill/README.md`](skills/claude-deep-research-skill/README.md) for full documentation.

---

### Send Email

Send, reply, forward, draft, and search Outlook email via the **microsoft-outlook-mail MCP**. No local Outlook installation required.

**Requirements:** microsoft-outlook-mail MCP configured (see [Configure MCP Servers](#3-configure-mcp-servers)).

**Usage:**

```
Send an email to alice@contoso.com summarizing today's code changes
```

See [`skills/send-email/README.md`](skills/send-email/README.md) for full documentation.

---

### MarkItDown

Convert documents (PDF, Word, Excel, PowerPoint, and more) to Markdown for the Knowledgebase using Microsoft's [MarkItDown](https://github.com/microsoft/markitdown).

#### Install MarkItDown

Using `uv` (recommended if available):

```bash
uv tool install "markitdown[all]"
```

Using `pip`:

```bash
pip install "markitdown[all]"
```

Or install only specific format support:

```bash
pip install "markitdown[pdf, docx, pptx, xlsx]"
```

#### Verify

```bash
markitdown --help
```

**Usage:**

```
Convert the quarterly report PDF to markdown for the knowledgebase
```

See [`skills/markitdown/README.md`](skills/markitdown/README.md) for full documentation.

---

### Handy (Speech-to-Text)

[Handy](https://github.com/cjpais/handy) is a free, open-source, offline speech-to-text application. It uses Whisper models to transcribe speech locally — no cloud, fully private.

#### Install Handy

**Windows** (via winget):

```powershell
winget install cjpais.Handy
```

**macOS** (via Homebrew):

```bash
brew install --cask handy
```

**Linux**: Download from the [releases page](https://github.com/cjpais/handy/releases).

#### Usage in Agency Cowork

Click the **mic button** in the chat input to enter voice mode. Press **Space** to toggle push-to-talk (when not focused on a text input). Press **Escape** to exit voice mode. Handy transcribes locally and pastes text into the active field.

See [architecture.md](architecture.md#handy-speech-to-text-integration) for integration details.

---

### Spec Kit

Spec-driven development toolkit from GitHub. Define specifications first, then systematically plan and implement features instead of vibe coding. Source: [github.com/github/spec-kit](https://github.com/github/spec-kit).

#### Install the Specify CLI

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

#### Initialize in a project

```bash
specify init . --ai claude
```

#### Verify

```bash
specify check
```

**Available commands after init:**

| Command | Purpose |
|---------|---------|
| `/speckit.constitution` | Define project principles and standards |
| `/speckit.specify` | Write a feature specification |
| `/speckit.plan` | Generate implementation plan from spec |
| `/speckit.tasks` | Break plan into ordered, actionable tasks |
| `/speckit.implement` | Execute the task plan |
| `/speckit.analyze` | Analyze existing codebase |
| `/speckit.clarify` | Clarify ambiguous requirements |
| `/speckit.checklist` | Generate pre-implementation checklist |
| `/speckit.taskstoissues` | Convert tasks to GitHub Issues |

See [`skills/spec-kit/README.md`](skills/spec-kit/README.md) for full documentation.

---

### Weekly Report

Generate executive-ready weekly status reports. Gathers live context from M365 via WorkIQ, cross-references with the Knowledgebase, and produces 3–5 bullet updates per program.

**Requirements:** WorkIQ MCP configured and `CLAUDE.md` present in project root.

> **Note:** Agent identity lives in `CLAUDE.md`, which GitHub Copilot and Claude Code auto-load every session — no manual load step needed.

**Usage:**

```
Generate the the project weekly status report
```

See [`skills/weekly-report/README.md`](skills/weekly-report/README.md) for full documentation.

---

### Task Scheduler

Schedule one-time and recurring tasks that invoke Agency Copilot with stored prompts. Includes a persistent background service, JSON-based task storage, and execution logging.

**Requirements:** Agency installed and on PATH.

#### Quick Setup (Recommended)

Run the setup script to create recommended memory management tasks and start the scheduler:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts/setup-scheduler.ps1
```

This creates 4 tasks:

| Task | Schedule | Purpose |
|------|----------|---------|
| daily-memory-maintenance | Daily 11 PM PT | Compact logs, review MEMORY.md, re-index QMD |
| weekly-memory-review | Friday 5 PM PT | Deep MEMORY.md accuracy review |
| weekly-log-archive | Saturday 10 PM PT | Archive daily logs older than 14 days |
| weekly-qmd-reindex | Sunday 8 PM PT | Full QMD + Azure embedding refresh |

The script skips tasks that already exist and starts the scheduler service if not running.

#### Manual Setup

Start the scheduler service directly:

```powershell
Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -File `"skills/task-scheduler/scripts/scheduler-service.ps1`"" -WindowStyle Hidden
```

Create tasks interactively:

```
Schedule a task to generate the the project weekly report every Monday at 9am
```

#### Managing Tasks

```powershell
# List all tasks
powershell.exe -ExecutionPolicy Bypass -File skills/task-scheduler/scripts/task-manager.ps1 list

# Check scheduler status
powershell.exe -ExecutionPolicy Bypass -File skills/task-scheduler/scripts/task-manager.ps1 status

# View task logs
powershell.exe -ExecutionPolicy Bypass -File skills/task-scheduler/scripts/task-manager.ps1 logs -Id "daily-memory-maintenance" -Tail 20
```

See [`skills/task-scheduler/README.md`](skills/task-scheduler/README.md) for full documentation.

---

### Teams Rich Messaging & Monitor Service

The Teams skill provides three messaging tiers and a real-time monitor service:

| Tier | Transport | Use Case |
|------|-----------|----------|
| **chatsvc API** (preferred) | Direct HTTP + Azure CLI token | Rich HTML messages — tables, emojis, bold, links. No browser needed. |
| **MCP PostMessage** | Microsoft Graph MCP | Simple plain-text messages. Fast, no dependencies. |
| **Playwright send_message.py** (fallback) | Browser automation | @mentions, Adaptive Cards, file attachments, message importance. Requires Edge. |

#### Prerequisites

- **Python 3.10+** (already required by other skills)
- **Azure CLI** (`az`) logged in — provides tokens for the chatsvc API
- **Microsoft Edge** browser installed (only needed for Playwright fallback features)
- **`aiohttp`** Python package (for async HTTP in the monitor service)

#### Install

```powershell
# Install Python dependencies
pip install -r skills/teams/requirements.txt

# Install Playwright Edge browser driver (optional — for @mentions, cards, file attachments)
python -m playwright install msedge
```

#### Sending Messages via chatsvc API (Preferred)

The chatsvc direct API is the fastest and most reliable way to send rich HTML messages. It uses an Azure CLI token and bypasses Playwright entirely:

```python
# Get token
az account get-access-token --resource "https://ic3.teams.office.com" --query accessToken -o tsv

# The Teams skill handles this automatically — just tell the agent:
# "Send a formatted message to <person> about <topic>"
```

The `markdown_to_teams_html()` converter in `skills/teams/scripts/rich/utils.py` handles:
- Markdown → Teams HTML conversion (bold, italic, headers, lists, tables, links)
- Emoji shortcodes → CDN image URLs (150+ mapped emojis)
- Proper Teams message payload formatting

#### First-run authentication (Playwright)

Only needed if you use features that require Playwright (@mentions, Adaptive Cards, file attachments). The Playwright browser session uses a persistent Edge profile at `~/.teams-agent/browser-profile/`. On first run, it opens Edge to `teams.cloud.microsoft.com` for authentication (may require interactive MFA).

```powershell
# Test rich messaging (sends to self-chat)
cd skills/teams
python -m scripts.rich.send_message --to "48:notes" --body "**Rich test** from Agency Cowork"
```

#### Monitor Service (Real-Time Channel & Chat Monitoring)

The monitor service listens for `@agent` mentions in Teams conversations via WebSocket (Trouter), dispatches the prompt to the AI agent, and delivers the response back to the conversation.

> **Security Warning:** The monitor service executes prompts unattended. See the [Security](#monitor-service-security) section below and [`threatmodel.md`](threatmodel.md) (T11, T12) before enabling.

##### Configuration

Edit `agentconfig.json` in the project root:

```json
{
  "monitor": {
    "enabled": true,
    "keyword": "@agent"
  }
}
```

The monitor config file at `~/.agency-cowork/monitor-config.json` controls per-workspace settings including which conversations to watch:

```json
{
  "identity": {
    "mri": "8:orgid:<your-guid>",
    "displayName": "Your Name",
    "upn": "you@microsoft.com"
  },
  "connection": { "trouter_gateway": "go-msit.trouter.teams.microsoft.com", "..." : "..." },
  "workspaces": {
    "c:\\projects\\agency-cowork": {
      "enabled": true,
      "keyword": "@agent",
      "reply_prefix": "Agency Cowork: ",
      "monitored_conversations": [
        { "id": "48:notes", "name": "Self (Notes)", "type": "Self" },
        { "id": "19:meeting_...", "name": "Team Standup", "type": "channel" }
      ],
      "dispatch": { "command": "agency copilot -p", "timeout_minutes": 15 }
    }
  }
}
```

##### Starting the Monitor

```powershell
cd skills/teams
python -m scripts.monitor.service start
```

The service:
1. Authenticates via Azure CLI token to the Teams Trouter WebSocket
2. Loads global config from `~/.agency-cowork/monitor-config.json`
3. Creates a message handler per enabled workspace
4. Routes incoming messages: global dedup → sender check (identity MRI) → per-workspace keyword + conversation match → first-match dispatch
5. Scans the prompt through the **Prompt Guard** for injection attacks
6. Dispatches to Agency Copilot via file-based output (avoids stdout pollution)
7. Reads the agent's response from the output file
8. Prefixes with the workspace's reply prefix and sends back to the source conversation via chatsvc API
9. Scans the outbound response through the **Credential Guard**

##### Monitor Service Security {#monitor-service-security}

| Control | Description |
|---------|-------------|
| **Off by default** | Requires `"enabled": true` in `agentconfig.json` and a workspace entry in `~/.agency-cowork/monitor-config.json` |
| **Sender allowlist** | Only messages from the authorized user's MRI are processed |
| **Conversation allowlist** | Only messages in explicitly configured conversations are processed |
| **Prompt Guard** | All extracted prompts scanned for injection before Agency dispatch |
| **Credential Guard** | All outbound responses scanned for secrets before sending |
| **File-based dispatch** | Agent writes response to temp file — prevents execution trace leakage |
| **Agent prefix** | All outbound messages prefixed with per-workspace reply prefix for clear attribution |
| **Audit logging** | All prompts and responses logged to `skills/teams/logs/` |

##### Stopping the Monitor

```powershell
cd skills/teams
python -m scripts.monitor.service stop
```

Or use the PID file: `Stop-Process -Id (Get-Content skills/teams/monitor/monitor.pid)`

#### Verify

After installation, confirm messaging works:

```powershell
# Test chatsvc API (preferred — rich HTML, no browser)
cd skills/teams
python -c "from scripts.rich.utils import markdown_to_teams_html; print(markdown_to_teams_html('**test**'))"

# Test Playwright (optional — for @mentions, cards, attachments)
python -m scripts.rich.send_message --to "48:notes" --body "**Rich test** from Agency Cowork"

# Test monitor service
python -m scripts.monitor.service status
```

---

### SharePoint

Download and upload files between local machine and SharePoint/OneDrive via the Microsoft Graph API, with optional Markdown conversion for the Knowledgebase. Bypasses the 5 MB limit of the SharePoint MCP read/write tools.

**Requirements:** Azure CLI (`az`) logged in, SharePoint MCP configured (see [Configure MCP Servers](#3-configure-mcp-servers)).

#### Verify Azure CLI authentication

```bash
az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
```

If this fails, run `az login` first.

**Usage:**

```
Download this SharePoint document and add it to the knowledgebase: https://microsoft.sharepoint.com/:w:/r/teams/...
```

See [`skills/sharepoint-download/README.md`](skills/sharepoint-download/README.md) for full documentation.

---

### OnePlanner

Manage Microsoft Project for the Web schedules through a local REST API. Query tasks, manage assignments, track dependencies, view risks, compare baselines, and generate project reports. Source: [github.com/ahsi-microsoft/OnePlanner](https://github.com/ahsi-microsoft/OnePlanner).

#### Prerequisites

- **Node.js 18+** with npm
- **Python 3.11+** (for CLI scripts)
- **Git** access to the [OnePlanner repository](https://github.com/ahsi-microsoft/OnePlanner)

#### Clone the OnePlanner repo

```powershell
# Clone into C:\Projects (or your preferred location)
cd C:\Projects
git clone https://github.com/ahsi-microsoft/OnePlanner.git
cd OnePlanner
```

#### Install Node.js dependencies

```powershell
npm install
```

#### Start the dev server

The OnePlanner REST API runs on `http://127.0.0.1:3100`. Start it before using the skill:

```powershell
cd C:\Projects\OnePlanner
npm run dev:server
```

> **Tip:** You can also run `npm run dev` to start both the Vite frontend and the API server concurrently.

#### Authenticate

On first use, authenticate against a Project for the Web plan URL:

```powershell
cd C:\Projects\agency-cowork\skills\oneplanner
python -m scripts.op_snapshot save --url <plannerUrl>
```

Replace `<plannerUrl>` with the URL of your Project for the Web plan (e.g., `https://project.microsoft.com/...`).

#### Verify

```powershell
# Check server health
curl http://127.0.0.1:3100/health

# List tasks via CLI
cd C:\Projects\agency-cowork\skills\oneplanner
python -m scripts.op_tasks list

# Project summary
python -m scripts.op_report status
```

**Usage:**

```
Show the OnePlanner project status
List all overdue tasks in OnePlanner
Add a task "Design Review" to the Design bucket and assign to Jane
```

See [`skills/oneplanner/skills/oneplanner/SKILL.md`](skills/oneplanner/skills/oneplanner/SKILL.md) for the full decision table and REST API reference.

---

### Landing Zone

Query, analyze, and manage Azure DevOps Landing Zone requirements. Provides ADO sync, state machine validation, grading analytics, week-over-week progress tracking, and write operations.

**Requirements:** Azure CLI (`az`) logged in, access to your ADO project.

#### Verify Azure CLI authentication

```bash
az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv
```

If this fails, run `az login` first.

#### First sync

```bash
cd skills/landing-zone
python -m scripts.lz_sync --program your-program
```

**Usage:**

```
Sync the landing zone and show grading progress
```

See [`skills/landing-zone/SPEC.md`](skills/landing-zone/SPEC.md) for the full specification.

---

### Workstreams

Manage program workstreams — meeting summaries, action item tracking, KB storage per workstream, and Landing Zone cross-referencing. Maps Teams channels to Knowledgebase folders.

#### No additional setup required

The workstreams skill uses the existing Teams MCP, meeting-summary skill, and landing-zone skill. The workstream registry (`skills/workstreams/registry.json`) maps your program workstream channels.

KB folders are pre-created at `memory/Knowledgebase/Workstreams/{program}/{slug}/`.

#### Usage

```bash
cd skills/workstreams

# List all open action items
python -m scripts.ws_tracker list

# Add an action item
python -m scripts.ws_tracker add -w <program>/<workstream> -d "Finalize integration spec" --dri "Jane Doe" --due 2026-03-15

# Executive summary of all open items
python -m scripts.ws_tracker summary -p <program>
```

For meeting summary workflow, tell the agent: "Summarize the Backend Network workstream meeting from today."

---

### Confluence Wiki

Browse, search, create, and edit Confluence wiki pages on your organization's Confluence instance.

#### Prerequisites

- Python 3.10+ (already required)
- `playwright` pip package with Chromium: `pip install playwright && python -m playwright install chromium`
- `requests` pip package (already installed)
- Network access to your Confluence instance

#### First-time Setup

```bash
cd skills/confluence

# Interactive login — browser opens for Azure AD SAML SSO
python -m scripts.auth --interactive
# Press Enter after login completes

# Verify session
python -m scripts.auth --verify
```

#### Quick Test

```bash
cd skills/confluence

# List accessible spaces
python -m scripts.wiki_cli spaces

# Search for pages
python -m scripts.wiki_cli search --query "Your Topic" --space YOURSPACE

# Read a page
python -m scripts.wiki_cli read --id 230290071
```

**Note:** PATs are disabled on this Confluence instance. SAML cookie auth via Playwright is the only working authentication method. If your session expires, re-run `python -m scripts.auth --interactive`.

---

### Webpage Builder

Cinematic landing page builder that generates high-fidelity React + GSAP + Tailwind sites from 4 simple questions. Ships with 4 aesthetic presets (Organic Tech, Midnight Luxe, Brutalist Signal, Vapor Clinic), each with a complete design system.

#### Prerequisites

- Node.js 18+ with npm
- A target directory for the generated site

#### Usage

Tell the agent: "Build me a landing page" or invoke the `webpage-builder` skill. The agent will:
1. Ask 4 questions (brand, aesthetic preset, value props, CTA)
2. Scaffold a Vite + React project
3. Generate the full site with GSAP animations, ScrollTrigger, noise texture, and interactive components

#### Templates

Design token presets and CSS templates are in `skills/webpage-builder/templates/`:
- `presets.json` — color palettes, fonts, image URLs per preset
- `index.css` — noise overlay, magnetic buttons, typewriter cursor, pulse dots
- `tailwind.config.js.template` — Tailwind theme extension template

---

### Deep Personalization

Guided multi-phase interview that transforms the agent from a generic template into a deeply personalized AI coworker. The agent interviews you, gathers context from Microsoft 365 via WorkIQ, and writes to `CLAUDE.md`, `AGENTS.md`, and `memory/MEMORY.md`.

#### Prerequisites

- `CLAUDE.md` and `AGENTS.md` in project root (created by `setup.ps1`)
- `memory/` directory (from memory repo or created locally)
- WorkIQ MCP configured (optional but recommended — enables automatic M365 artifact gathering)

#### Usage

Start a Copilot session and say:

```
Personalize my agent
```

The skill runs 8 phases: Connections Check → About Me → Communication & Voice → Working Preferences → Domain Knowledge → Team & Contacts → Active Projects → Synthesis. Each phase shows proposed file changes and waits for approval before writing.

You can also run individual phases:

```
Update my domain knowledge
Update my contacts
Refresh my active projects
```

See [`skills/deep-personalization/SKILL.md`](skills/deep-personalization/skills/deep-personalization/SKILL.md) for the full interview protocol.

---

### QMD Memory

Local hybrid search engine for the agent's memory system. Indexes daily logs, knowledgebase, weekly reports, and skill documentation. Provides BM25 keyword search and vector semantic search with local SentenceTransformer embeddings (`bge-small-en-v1.5`, 384 dimensions). All embedding runs on-device — zero cost, offline-capable.

#### Prerequisites

- Node.js 22+ installed
- ~2GB free disk space for QMD's built-in GGUF models (downloaded on first use)
- Python 3.11+ with `sentence-transformers` for local embeddings

#### Install QMD

```bash
npm install -g @tobilu/qmd
```

#### Set up collections

Run the setup script to create QMD collections and initial index:

```powershell
powershell -ExecutionPolicy Bypass -File "skills/qmd-memory/scripts/setup-qmd.ps1"
```

This creates 4 collections:

| Collection | Path | Content |
|-----------|------|---------|
| `memory-root` | `memory/DailyLogs/*.md`, `memory/MEMORY.md` | Daily context logs, MEMORY.md |
| `knowledgebase` | `memory/Knowledgebase/**/*.md` | Program specs, reviews, workstream notes |
| `weekly-reports` | `memory/WeeklyReports/**/*.md` | Executive weekly status reports |
| `skills-docs` | `skills/**/SKILL.md` | Skill definitions and workflows |

#### Verify

```bash
qmd status         # Shows collections and document counts
qmd search "test"  # Returns matching documents
```

#### Re-indexing

QMD auto-reindexes text every 5 minutes when running as MCP server. Manual reindex:

```bash
qmd update
python skills/qmd-memory/scripts/azure-embed.py
```

#### SentenceTransformer Embeddings (Default)

The default embedding provider uses `BAAI/bge-small-en-v1.5` (384 dimensions) via `sentence-transformers`. Pure Python, no C++ compiler needed, model auto-downloads on first use.

**Step 1: Install sentence-transformers**

```bash
pip install sentence-transformers
```

**Step 2: Test the provider**

```bash
python skills/qmd-memory/scripts/azure-embed.py --test
```

Expected output: confirms SentenceTransformer model loaded and returns embedding vectors.

**Step 3: Generate embeddings**

```bash
python skills/qmd-memory/scripts/azure-embed.py
```

> The `setup.ps1` script automates these steps when you choose to install QMD during setup.

#### Local GGUF Embeddings (Alternative)

For environments where a smaller binary footprint is preferred, use the GGUF provider:

```bash
pip install llama-cpp-python
New-Item -ItemType Directory -Force skills/qmd-memory/models
Invoke-WebRequest -Uri "https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-f16.gguf" -OutFile "skills/qmd-memory/models/bge-small-en-v1.5-f16.gguf"
```

Then set `"provider": "local"` in `agentconfig.json`.

#### Azure OpenAI Embeddings (Optional Fallback)

> **⚠️ Policy: Do NOT use personal Azure subscriptions** to set up embedding services for work content. The SentenceTransformer provider is the recommended default. If you need Azure OpenAI, use a corporate-provisioned endpoint only.

Azure OpenAI `text-embedding-3-large` (3072 dimensions) is available as a fallback for higher-dimensional embeddings:

**Step 1: Install Python dependencies**

```bash
pip install openai python-dotenv tiktoken
```

**Step 2: Configure credentials**

- Set `memory.embedding.provider` to `"azure_openai"` in `agentconfig.json`
- Set the `endpoint` to your corporate Azure OpenAI resource URL
- Store your API key in `.env` (git-ignored): `AZURE_OPENAI_API_KEY=your-key-here`

**Step 3: Test and generate**

```bash
python skills/qmd-memory/scripts/azure-embed.py --provider azure_openai --test
python skills/qmd-memory/scripts/azure-embed.py --provider azure_openai
```

See [`skills/qmd-memory/README.md`](skills/qmd-memory/README.md) for full documentation.

---

## 8. Install Obsidian

[Obsidian](https://obsidian.md/) is recommended for browsing and editing the `memory/` directory, including daily context logs and the Knowledgebase. It provides graph views, full-text search, and linked references across all markdown files.

### Download

- **All platforms**: [https://obsidian.md/download](https://obsidian.md/download)
- **GitHub releases**: [https://github.com/obsidianmd/obsidian-releases/releases/](https://github.com/obsidianmd/obsidian-releases/releases/)

### Windows

```powershell
winget install Obsidian.Obsidian
```

### macOS

```bash
brew install --cask obsidian
```

### Setup

1. Open Obsidian
2. Choose **"Open folder as vault"**
3. Select the `memory/` directory (`C:\Projects\agency-cowork\memory`)
4. Obsidian will detect the existing `.obsidian` configuration in the folder

The vault gives you a navigable view of:

```
memory/
├── Daily logs (YYYY-MM-DD.md)
└── Knowledgebase/
    ├── Program/
    ├── ExecutiveReviews/
    ├── ProgramExecutionCouncil/
    ├── Workstreams/
    └── Specifications/ (SoC, System, Software, Firmware)
```

---

## 9. Run Security Audit

Run the security audit after setup to establish a clean baseline, and periodically thereafter. See [`threatmodel.md`](threatmodel.md) for the full threat model.

### One-time audit

```powershell
powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1
```

The audit checks 6 areas:

| Check | What It Detects |
|-------|----------------|
| Secrets scan | API keys, tokens, passwords in tracked files |
| .env status | Whether `.env` is accidentally tracked by git |
| Identity integrity | Uncommitted changes to `CLAUDE.md` and `MEMORY.md` |
| Scheduled tasks | Dangerous patterns in task prompts (forwarding, deleting, sharing) |
| MCP configuration | Non-Microsoft server URLs in `mcp-config.json` |
| File system | Unexpected executables (`.exe`, `.dll`, `.bat`, etc.) |

### Schedule recurring audits

Use the task scheduler to run the security audit weekly:

```
Schedule a task called "Weekly Security Audit" to run "Run the security audit: powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1 and report any issues found" every Monday at 8am
```

### Dependency audit

Run periodically to check for known vulnerabilities in installed packages:

```bash
# Node.js packages (QMD, WorkIQ)
npm audit

# Python packages (markitdown, specify-cli)
pip audit          # Requires: pip install pip-audit
```

---

## 10. Verify Installation

Run through this checklist to confirm everything is working:

| Component | Verification Command | Expected Result |
|-----------|---------------------|-----------------|
| Agency | Open a new terminal session | Agent tooling is available |
| Memory Repo | `Test-Path memory\MEMORY.md` | Returns `True` (run `scripts\sync-memory.ps1` if not) |
| MCP Config | Check `C:\Users\<username>\.copilot\mcp-config.json` exists | Contains workiq, teams, outlook-mail, outlook-calendar, word, sharepoint, and qmd servers |
| Pre-commit hook | `Test-Path .git\hooks\pre-commit` | Returns `True` |
| File permissions | `scripts/harden-permissions.ps1 -DryRun` | Shows 0 paths to change |
| Security audit | `scripts/security-audit.ps1` | All checks pass |
| WorkIQ MCP | Ask "What meetings do I have today?" | Returns M365 data |
| Teams MCP | Ask "What are the latest messages in General?" | Returns Teams messages |
| Teams chatsvc | `az account get-access-token --resource "https://ic3.teams.office.com" --query accessToken -o tsv` | Returns a Bearer token |
| Teams Rich | `cd skills/teams && python -m scripts.rich.send_message --to "48:notes" --body "test"` | Sends message to self-chat |
| Teams Monitor | `cd skills/teams && python -m scripts.monitor.service status` | Shows service status (off by default) |
| Outlook Mail MCP | Ask "Search my recent emails" | Returns email results |
| SharePoint MCP | Ask "Find the hardware spec on SharePoint" | Returns file metadata |
| QMD MCP | Ask "Search my memory for program status" | Returns indexed memory results |
| Deep Research | `/deep-research` | Skill is recognized |
| Send Email | `/send-email` | Skill is recognized |
| Task Scheduler | `/task-scheduler` then "List my scheduled tasks" | Skill is recognized, shows task list |
| QMD Memory | `qmd status` | Shows collections and index health |
| MarkItDown | `markitdown --help` | Shows CLI help text |
| Spec Kit | `specify check` | Shows all prerequisites as met |
| SharePoint | `/sharepoint` | Skill is recognized |
| ADO Explorer | `/ado-explorer` | Skill is recognized, can browse ADO repos |
| Landing Zone | `cd skills/landing-zone && python -m scripts.lz_sync --program your-program` | Syncs LZ data from ADO |
| OnePlanner | `curl http://127.0.0.1:3100/health` | Returns server health + session status |
| Workstreams | `cd skills/workstreams && python -m scripts.ws_tracker list` | Shows action items tracker |
| Confluence | `cd skills/confluence && python -m scripts.auth --verify` | Shows authenticated user |
| Webpage Builder | `Test-Path skills/webpage-builder/templates/presets.json` | Returns `True` |
| Deep Personalization | \"Personalize my agent\" in Copilot session | Skill is recognized, starts Phase 0 interview |
| Obsidian | Open Obsidian → memory vault | Knowledgebase folders visible |

---

## 11. Smart Permission Plugin (Optional)

The **smart-permission** plugin provides intelligent 4-tier permission decisions as an alternative to YOLO mode. It auto-approves safe operations, blocks dangerous commands, uses AI for edge cases, and defers unknown tools to the built-in system.

### Prerequisites

- **Perl 5.14+** — On Windows, Git Bash ships Perl at `C:\Program Files\Git\usr\bin\perl.exe`. Verify: `perl -v`
- **Copilot CLI** — Must support `copilot plugin` commands (2026.3.14+)

### Installation

The plugin auto-installs when you enable Smart Permission mode in Settings. To install manually:

```powershell
# 1. Register the plugin marketplace
agency copilot -- plugin marketplace add agency-microsoft/playground

# 2. Install the smart-permission plugin
agency copilot -- plugin install smart-permission@agency-playground
```

### Verification

```powershell
# Confirm plugin is installed
agency copilot -- plugin list
# Should show: smart-permission@agency-playground (v3.3.1)

# Test with debug logging
$env:SMART_PERMISSION_DEBUG = "1"
# Start a Copilot session and run a command — check %TEMP%\smart_permission_debug.log
```

### Configuration

Smart Permission settings are in `agentconfig.json` → `smartPermission` section:
- `model`: AI model for edge-case classification (default: `claude-haiku-4.5`)
- `debug`: Enable debug logging to `%TEMP%\smart_permission_debug.log`
- `timeout`: Timeout in seconds for AI classification (default: 30)
- `mcpSafe`: Space-separated MCP tool names to auto-approve (pre-populated with read-only M365 tools)
- `mcpAsk`: Space-separated MCP tool names requiring confirmation (pre-populated with write M365 tools)

---

## Troubleshooting

### Agency install fails

- **Windows**: Ensure PowerShell execution policy allows scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- **macOS/Linux**: Ensure `curl` is installed and you have internet access
- **VPN**: The install scripts and documentation at `aka.ms` may require VPN access

### markitdown not found after install

- If installed with `uv tool install`, ensure `~/.local/bin` (Linux/macOS) or `%APPDATA%\uv\tools` (Windows) is on your PATH
- If installed with `pip`, ensure your Python Scripts directory is on your PATH
- Restart your terminal after installation

### WorkIQ not responding

- Ensure you have accepted the EULA
- Check your Microsoft 365 authentication is valid
- Verify VPN connectivity if required by your organization
- Ensure Node.js and `npx` are installed and on your PATH

### Teams, Outlook Mail, Outlook Calendar, or Word MCP not responding

- Verify `mcp-config.json` exists at `C:\Users\<username>\.copilot\mcp-config.json`
- Check that the server URLs are correct and the tenant ID matches your organization
- Ensure your Microsoft 365 credentials are valid
- These are remote HTTP servers — verify network connectivity to `agent365.svc.cloud.microsoft`

### QMD MCP not responding / WSL error

If QMD fails with `Windows Subsystem for Linux has no installed distributions`, the system is resolving `bash.exe` to WSL instead of Git for Windows:

1. **Verify Git for Windows is installed:** `where.exe git` should show `C:\Program Files\Git\cmd\git.exe`
2. **Verify Git bash exists:** `Test-Path "C:\Program Files\Git\bin\bash.exe"` should return `True`
3. **Fix the MCP config** — ensure the QMD server entry in `~/.copilot/mcp-config.json` includes the `env` block:

```json
"qmd": {
  "command": "qmd",
  "args": ["mcp"]
}
```

4. **For CLI usage** (outside MCP), add Git's `bin/` to your system PATH:

```powershell
# Temporary (current session only)
$env:PATH = "C:\Program Files\Git\bin;$env:PATH"

# Permanent (requires restart)
[Environment]::SetEnvironmentVariable("PATH", "C:\Program Files\Git\bin;" + [Environment]::GetEnvironmentVariable("PATH", "User"), "User")
```

5. **Re-run setup** to regenerate the MCP config with bash detection: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`

### OnePlanner server not responding

- Ensure the dev server is running: `cd C:\Projects\OnePlanner && npm run dev:server`
- Check port 3100 is not in use: `netstat -ano | findstr :3100`
- Verify Node.js dependencies are installed: `cd C:\Projects\OnePlanner && npm install`
- If authentication fails, re-authenticate: `cd skills/oneplanner && python -m scripts.op_snapshot save --url <plannerUrl>`
