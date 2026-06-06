**Feature Specification** [[Feature Requests]]

Obsidian Vault Integration for Agency Cowork

|                  |                                      |
| ---------------- | ------------------------------------ |
| **Author**       | Nikhil Kaul                          |
| **Date**         | March 16, 2026                       |
| **Status**       | Draft                                |
| **Version**      | 0.1                                  |
| **Stakeholders** | Yang You, Kyle Rader, Imran Siddique |

# 1. Overview

Agency Cowork generates a rich graph of interconnected markdown files: daily logs, knowledgebase entries, weekly reports, skill docs, and identity files. Today these are navigable only via terminal or Finder. Obsidian transforms this same file tree into a browsable, searchable, linked knowledge graph with zero data duplication.

This spec defines a lightweight integration that registers the Agency Cowork project directory as an Obsidian vault, enabling human-side navigation of agent-generated content. The key insight: Obsidian is a read layer, not a write layer. The agent produces the files; Obsidian makes them useful to humans.

# 2. Strategic Framing

Obsidian is a complement to Agency Cowork, not a platform dependency. The integration should live at the pointer level: we tell Obsidian where the files are, set sane defaults, and get out of the way. We do not build Obsidian plugins, add Obsidian-specific metadata to agent output, or create bidirectional sync. The agent’s markdown output stays format-agnostic so that VS Code, GitHub, or any other .md viewer works equally well.

The analogy: this is like configuring a Git GUI to point at an existing repo. You don’t change the repo to accommodate the GUI.

# 3. Scope

## 3.1 In Scope

•       Setup wizard integration: detect Obsidian, offer vault registration

•       Desktop app “Open in Obsidian” launch button

•       .obsidian/ config generation with sane defaults

•       Gitignore management for vault config

•       Cross-platform support (Windows, macOS, Linux)

## 3.2 Out of Scope

•       Custom Obsidian plugin development

•       Bidirectional sync (Obsidian edits flowing back to agent)

•       Obsidian-specific frontmatter or wiki-link formatting in agent output

•       Obsidian Publish or Sync integration

•       Obsidian as a required dependency (always optional)

# 4. Design Decision: Vault Root

The critical product question is whether the vault root should be memory/ or the project root.

|   |   |   |
|---|---|---|
|**Option**|**Pros**|**Cons**|
|**memory/ only**|Clean scope. Matches OneDrive sync boundary. Fewer excluded folders needed.|Misses outputs/, CLAUDE.md, skill READMEs. Graph view is incomplete.|
|**Project root**|Full graph view across all .md files. Human can browse everything. Best Obsidian experience.|Requires exclude rules for node_modules/, ui/, .git/, scripts/. Larger index.|

**Recommendation:** Project root. The value of Obsidian is the graph view and cross-file linking. A vault scoped to memory/ misses half the interesting content. The exclude list is a one-time config cost.

# 5. Feature Detail

## 5.1 Setup Wizard Step

A new optional step in the OOBE setup wizard, positioned after memory configuration and before service setup.

**Detection logic:** Check for Obsidian installation by testing the obsidian:// URI scheme handler on macOS/Windows, and checking standard install paths (/Applications/Obsidian.app, %LOCALAPPDATA%\Obsidian, /usr/bin/obsidian).

**If Obsidian is detected:** Show toggle: “Register project as Obsidian vault” with a green Recommended badge (same pattern as OneDrive memory). Default: on.

**If Obsidian is not detected:** Skip the step entirely. Do not prompt installation.

**Action on confirm:** Create .obsidian/ directory at project root with default config. Add .obsidian/ to .gitignore if not already present.

## 5.2 Default Vault Configuration

The generated .obsidian/ directory includes the following config files:

|   |   |
|---|---|
|**File**|**Purpose**|
|**app.json**|Excluded folders: node_modules, ui/node_modules, .git, ui/release, ui/dist. Attachment folder: outputs/. Default view: reading.|
|**appearance.json**|Theme: system default. No custom CSS. Minimal opinionation.|
|**core-plugins.json**|Enable: graph view, search, backlinks, outgoing links, tags, daily notes. Disable: templates (agent handles this), publish, sync.|
|**daily-notes.json**|Folder: memory/DailyLogs. Date format: YYYY-MM-DD. Matches existing agent convention.|
|**graph.json**|Default graph filters: hide node_modules, ui/, scripts/. Show orphans. Color groups by folder.|

## 5.3 Desktop App: Open in Obsidian

Add an “Open in Obsidian” button to the desktop app home screen sidebar, next to the existing terminal and file browser launchers.

**Implementation:** Use the obsidian:// URI scheme. Specifically obsidian://open?vault=<vault-name> where vault-name is the project directory name (e.g., agency-cowork).

**Visibility:** Only show the button when .obsidian/ exists in the project root. If the user hasn’t set up the vault, show a subtle link: “Set up Obsidian vault” that triggers the vault creation flow.

**Deep links:** When the user clicks a .md file reference in the terminal output or transcript view, offer “Open in Obsidian” as an option alongside “Open in default editor.” URI: obsidian://open?vault=<name>&file=<relative-path>.

## 5.4 Gitignore Management

The .obsidian/ directory contains user-specific vault config (workspace layout, plugin state, hotkeys). This must not be committed to the shared repo.

•       Setup wizard appends .obsidian/ to .gitignore if not already present

•       update.ps1 preserves .obsidian/ during upstream merges (same pattern as CLAUDE.md)

## 5.5 Upgrade Path

When upgrading Agency Cowork to a new version:

•       Preserve .obsidian/ entirely (it’s gitignored and user-owned)

•       If new excluded folders are needed (e.g., a new build output directory), append them via a migration script rather than overwriting app.json

•       Never modify user’s installed Obsidian plugins or hotkeys

# 6. Implementation

## 6.1 Effort Estimate

|   |   |   |
|---|---|---|
|**Component**|**Owner**|**Estimate**|
|Obsidian detection + vault config generation|Setup scripts (PS1/Bash)|0.5 day|
|Setup wizard UI step|Electron app|0.5 day|
|Open in Obsidian button + deep links|Electron app|0.5 day|
|Gitignore + upgrade path handling|Setup + update scripts|0.25 day|
|Testing (Windows, macOS, Linux)|All|0.5 day|
|**Total**||**2.25 days**|

## 6.2 Platform Notes

•       **Windows:** Obsidian install path is %LOCALAPPDATA%\Obsidian. URI scheme registration is automatic on install. Junction/symlink handling for OneDrive memory is already tested.

•       **macOS:** Obsidian.app in /Applications. URI scheme works via Launch Services. Gatekeeper may prompt on first open if vault references unsigned scripts (not expected since Obsidian only reads .md files).

•       **Linux:** Check /usr/bin/obsidian or snap/flatpak paths. URI scheme support varies by desktop environment; fall back to xdg-open.

# 7. Non-Goals and Future Considerations

These are explicitly deferred. They may become relevant if Obsidian adoption is high enough to justify further investment.

•       **Wiki-link formatting:** The agent could emit [[wiki-links]] in daily logs to cross-reference knowledgebase entries. This would improve Obsidian graph density but couples agent output to Obsidian conventions. Evaluate post-launch based on user feedback.

•       **Obsidian plugin:** A custom plugin could surface agent status, trigger prompts, or show task scheduler state inside Obsidian. High effort, unclear incremental value over the desktop app.

•       **Bidirectional editing:** Allowing humans to edit .md files in Obsidian and have the agent pick up changes. Risk: conflicting edits, no merge strategy. The agent’s memory/Knowledgebase is designed as agent-owned.

•       **Obsidian Canvas:** Using Obsidian’s canvas feature to visualize agent architecture or task flows. Cool but niche.

# 8. Success Criteria

•       Setup wizard correctly detects Obsidian on all three platforms

•       One-click vault registration with no manual config required

•       Open in Obsidian button launches directly to vault

•       Deep links open specific .md files in Obsidian from the desktop app

•       .obsidian/ survives upgrades without data loss

•       Zero impact on users who don’t have Obsidian installed

# 9. Open Questions

|   |   |   |
|---|---|---|
|**#**|**Question**|**Owner**|
|1|Should we ship a recommended community plugin list (e.g., Dataview for querying daily logs)?|Nikhil|
|2|Should the daily-notes plugin point at memory/DailyLogs even though agents create those files, not humans?|Yang|
|3|Do we want an Obsidian section in the desktop app settings pane for post-setup configuration?|Kyle|