# spec-kit

Spec-driven development toolkit from GitHub. Build high-quality software by defining specifications first, then systematically planning and implementing — instead of vibe coding.

Source: [github.com/github/spec-kit](https://github.com/github/spec-kit)

## Prerequisites

- **Python 3.11+**
- **uv** package manager ([install uv](https://docs.astral.sh/uv/getting-started/installation/))
- **Git**
- **GitHub CLI** (optional, for `/speckit.taskstoissues`)

## Installation

### 1. Install the Specify CLI

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

Verify installation:

```bash
specify check
```

### 2. Register the skill

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\spec-kit"
```

Restart your Copilot session for the skill to appear in `/skills`.

### 3. Initialize a project

Navigate to your project directory and run:

```bash
specify init . --ai claude
```

Or for a new project:

```bash
specify init my-project
```

This creates a `.speckit/` directory with slash commands, templates, and configuration.

## Upgrading

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git
```

## Usage

Spec Kit provides a pipeline of slash commands that guide you from idea to implementation:

### Full Pipeline

```
/speckit.constitution  →  Define project principles and standards
/speckit.specify       →  Write the feature specification
/speckit.plan          →  Generate implementation plan from spec
/speckit.tasks         →  Break plan into ordered, actionable tasks
/speckit.implement     →  Execute the task plan
```

### Utility Commands

```
/speckit.analyze         →  Analyze existing codebase
/speckit.clarify         →  Clarify ambiguous requirements
/speckit.checklist       →  Generate pre-implementation checklist
/speckit.taskstoissues   →  Convert tasks to GitHub Issues
```

### Examples

```
/speckit.constitution Create principles for a Python microservice with strict type safety and 90% test coverage

/speckit.specify Build a notification system that sends real-time alerts via WebSocket and email digests on a configurable schedule

/speckit.plan

/speckit.tasks

/speckit.implement
```

## Project Structure

After initialization, your project will have:

```
.speckit/
├── memory/
│   └── constitution.md      # Project principles and standards
├── features/
│   └── <feature-name>/
│       ├── spec.md           # Feature specification
│       ├── plan.md           # Implementation plan
│       └── tasks.md          # Task breakdown
└── commands/                 # Slash command definitions
    ├── analyze.md
    ├── checklist.md
    ├── clarify.md
    ├── constitution.md
    ├── implement.md
    ├── plan.md
    ├── specify.md
    ├── tasks.md
    └── taskstoissues.md
```

## Supported AI Agents

Spec Kit works with multiple AI coding assistants:

- **GitHub Copilot** (Claude in Agent Mode)
- **Claude Code**
- **Cursor**
- **Windsurf**

Use `specify init . --ai <agent>` to configure for your preferred agent.

## Troubleshooting

### `specify` command not found

Ensure `uv` tools directory is on your PATH:

- **Windows**: `%APPDATA%\uv\tools` or `%USERPROFILE%\.local\bin`
- **macOS/Linux**: `~/.local/bin`

Restart your terminal after installation.

### `specify check` reports missing tools

Install the missing prerequisites listed in the check output. Common ones:

```bash
# Git (if missing)
winget install Git.Git

# GitHub CLI (optional, for taskstoissues)
winget install GitHub.cli
```

### Slash commands not available

Ensure `specify init .` has been run in the project directory. The slash commands are created inside `.speckit/commands/`.

### Git authentication issues on Linux

Install Git Credential Manager:

```bash
wget https://github.com/git-ecosystem/git-credential-manager/releases/download/v2.6.1/gcm-linux_amd64.2.6.1.deb
sudo dpkg -i gcm-linux_amd64.2.6.1.deb
git config --global credential.helper manager
```
