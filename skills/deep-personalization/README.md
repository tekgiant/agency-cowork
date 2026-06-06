# Deep Personalization

Guided multi-phase interview that transforms Agency Cowork from a generic template into a deeply personalized AI coworker.

## What It Does

Instead of manually editing CLAUDE.md, AGENTS.md, and MEMORY.md, this skill runs an interactive onboarding flow:

1. **Connections Check** — verifies MCP availability and creates MEMORY.md if missing
2. **About Me** — builds your professional profile (WorkIQ gathers org data first)
3. **Communication & Voice** — defines how the agent writes on your behalf (analyzes your sent emails for patterns)
4. **Working Preferences** — configures daily workflow, output formats, safety rules
5. **Domain & Program Knowledge** — loads project context, timelines, acronyms
6. **Team & Contacts** — builds a contacts directory from M365 interaction patterns
7. **Active Projects** — captures current priorities and deadlines
8. **Synthesis** — reviews everything, verifies accuracy, offers follow-up automations

## How to Use

Start a Copilot session and say:

```
Personalize my agent
```

Or for a specific phase:

```
Update my domain knowledge
Update my contacts
Refresh my active projects
```

## Files Modified

| File | What's Written |
|------|---------------|
| `CLAUDE.md` | Agent name, role, personality, voice rules, domain knowledge, KPIs |
| `AGENTS.md` | Working preferences, workflow rules, custom safety boundaries |
| `memory/MEMORY.md` | User profile, contacts, team, glossary, active projects |

## WorkIQ Integration

When WorkIQ MCP is available, the skill queries Microsoft 365 **before** asking interview questions:

- **Emails** — sent-from patterns (signature, tone analysis), frequent recipients
- **Calendar** — meeting patterns, working hours, recurring meetings
- **Teams** — communication style, active chats
- **SharePoint** — project documents, strategy decks
- **Graph** — org chart, display name, title

This means less typing — the agent proposes answers from your M365 data and you confirm or correct.

## Prerequisites

- `CLAUDE.md` and `AGENTS.md` in project root (created by `setup.ps1`)
- `memory/` directory (from memory repo or created locally)
- WorkIQ MCP configured (optional but recommended for artifact gathering)
