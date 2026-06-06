# Agency Cowork

Build your own AI coworker. Agency Cowork wraps [Agency](https://aka.ms/Agency) in a desktop app with persistent identity, memory, 25+ skills, and Microsoft 365 integrations -- so you can go from install to working coworker in minutes.

<div align="center">

[![Watch the Demo](docs/images/demo-thumbnail.png)](https://microsoft-my.sharepoint.com/:v:/p/nikhilkaul/IQBm3K5EnjNIQbZDUwwvCB0CAV_hkuSXOcRAHxU1_3iggBc?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJPbmVEcml2ZUZvckJ1c2luZXNzIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXciLCJyZWZlcnJhbFZpZXciOiJNeUZpbGVzTGlua0NvcHkifX0&e=U5imd7)

*Click the image to watch the demo*

</div>

## Get Started

1. **Download** the installer from the [latest release](https://github.com/ahsi-microsoft/agency-cowork/releases/latest) (Windows x64, ARM64, or macOS)
2. **Run the setup wizard** -- pick a working directory, configure memory & M365 integrations
3. **Ask your coworker anything** -- type in the prompt bar and go

That's it. The setup wizard handles agent identity, MCP servers, skills, and security automatically.

> **Updating?** Install the new version over the old one. The wizard detects your existing setup and runs a streamlined update that preserves your customizations.

## What It Does

| Category | Examples |
|----------|----------|
| **Meetings** | Transcripts, summaries, prep, scheduling |
| **Documents** | Specs, slide decks, spreadsheets, Word docs |
| **Communication** | Draft & send emails, Teams messages, weekly reports |
| **ADO & Data** | Work items, dependencies, landing zone requirements |
| **Research** | Multi-source analysis, action items, visual explainers |
| **Scheduling** | Recurring tasks (email triage, meeting digests) run automatically |
| **Voice Input** | Offline speech-to-text via [Handy](https://github.com/cjpais/handy) — push-to-talk in the chat |

### 25+ Skills

Agency Cowork ships with modular skills for Teams, Outlook, Calendar, SharePoint, Word, Excel, PowerPoint, ADO, Confluence, OnePDM, Project for the Web, and more. Each skill is a self-contained markdown file -- easy to read, modify, or create your own.

See the full list in [AGENTS.md](AGENTS.md.example) or ask your coworker: *"What skills do you have?"*

## Customize

The quickest way to personalize your coworker:

> "Personalize my agent"

This runs a guided interview that configures your agent's identity, communication style, and domain knowledge automatically.

**Or edit manually:**

| File | What it controls |
|------|-----------------|
| `CLAUDE.md` | Agent identity, persona, domain knowledge |
| `AGENTS.md` | Operational rules, skill routing, security policies |
| `memory/MEMORY.md` | Your profile, contacts, working context |
| `memory/Knowledgebase/` | Long-term reference material |
| `agentconfig.json` | Monitor, scheduler, and runtime settings |

All personalization files are gitignored -- your customizations stay local.

## Create Custom Skills

Ask your coworker to build one:

> "Create a skill called daily-standup that summarizes my calendar and yesterday's Teams messages"

The agent scaffolds the directory, writes the SKILL.md, and registers it. Every skill follows this layout:

```
skills/<name>/
├── agency.json           # Metadata
├── scripts/              # Supporting code (optional)
└── skills/<name>/
    └── SKILL.md          # Instructions the agent follows
```

> **Tip: Rename when customizing.** If you modify a bundled skill, copy it to a new name (e.g. `weekly-report` → `my-weekly-report`) so upgrades don't overwrite your changes. User-created skills are always preserved during upgrades.

Each bundled skill includes a `skill.json` manifest with version metadata. During upgrades, only skills with a newer bundled version are replaced — your customizations are safe if the skill has been renamed.

## Build from Source

```bash
cd ui
npm install
npm run dev:electron      # Dev mode with hot-reload
npm run build:win         # Windows installer (x64 + ARM64)
npm run build:mac         # macOS DMG
```

Or run headless (no desktop app):

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

# macOS / Linux
bash scripts/setup.sh
```

See [installation.md](installation.md) for manual setup and [ui/build.md](ui/build.md) for build details.

## Architecture

```
Agency Cowork
├── CLAUDE.md          Identity & persona (auto-loaded every session)
├── AGENTS.md          Operational rules & security (auto-loaded)
├── memory/            Daily logs, knowledgebase, user profile
├── skills/            25+ modular capabilities
├── scripts/           Setup, security, utilities
└── ui/                Electron desktop app
    ├── electron/      Main process (IPC, PTY, scheduler, monitor)
    └── src/           React UI (terminal, settings, task runner)
```

The agent connects to Microsoft 365 via MCP servers (Outlook, Teams, Calendar, SharePoint, Word) and can monitor Teams conversations in real time for `@agent` mentions.

For full architecture details, see [architecture.md](architecture.md).

## Security

> **This agent operates with your identity.** It can access your email, Teams, calendar, and files. Treat it with the same care as your own credentials.

> **AI Governance:** Usage must comply with [AI at Microsoft Guidance](https://eng.ms/docs/initiatives/ai-guidance-for-microsoft-developers/governance). Review the governance policies before using this tool with any Microsoft data.

**Key controls:**
- All outbound emails and Teams messages require your approval before sending
- Prompt Guard scans external content for injection attacks
- Credential Guard blocks outbound messages containing secrets
- Monitor service is off by default and requires explicit opt-in
- Pre-commit hook blocks secrets from being committed

See [threatmodel.md](threatmodel.md) for the full STRIDE analysis.

## Platform Support

| Platform | Status |
|----------|--------|
| Windows x64 | Primary |
| Windows ARM64 | Tested |
| Windows DevBox | Tested |
| macOS (Intel & Apple Silicon) | Tested |
| Ubuntu / Debian Linux | Tested |

## License

MIT

## Credits

| Contributor | Contribution |
|-------------|-------------|
| **Yang You** | Terminal UI architecture -- PTY sessions, JSONL pipeline, slash command system |
| **Nikhil Kaul** | Desktop app UX -- home screen, setup wizard, visual polish |
| **Nico Bailon** | [visual-explainer](https://github.com/nicobailon/visual-explainer) skill (MIT) |