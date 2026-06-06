---
name: deep-personalization
description: |
  Use this skill when the user asks to "personalize my agent", "set up my coworker", "configure my identity", "customize my workspace", "deep personalization", "interview me", "get to know me", "build my profile", "set up my preferences", "onboard me", or any request to personalize the agent's identity, communication style, domain knowledge, or working preferences. This is a guided multi-phase interview that writes to CLAUDE.md, AGENTS.md, and memory/MEMORY.md.
---

# Deep Personalization Skill

A guided, multi-phase interview that transforms Agency Cowork from a generic template into a deeply personalized AI coworker. The agent interviews the user, gathers context from Microsoft 365 via WorkIQ, and writes the results to identity, operational, and memory files.

## Overview

This skill replaces the manual "edit CLAUDE.md yourself" approach with an interactive onboarding experience. The agent asks questions, validates answers, uses WorkIQ to fill in gaps, and builds a complete profile — then writes it directly into the configuration files.

### What Gets Personalized

| Target File | What's Written | Phase(s) |
|-------------|---------------|----------|
| `CLAUDE.md` | Agent name, role, personality, communication style, voice rules, domain knowledge, KPIs | 1, 2, 3, 7 |
| `AGENTS.md` | Working preferences, workflow rules, safety boundaries, custom triggers | 3, 7 |
| `memory/MEMORY.md` | User profile, contacts, team members, org structure, glossary, active projects | 1, 4, 5, 6 |

### Prerequisites

- `CLAUDE.md` and `AGENTS.md` exist in the project root (created by `setup.ps1` from `.example` templates)
- `memory/` directory exists (cloned via `agentconfig.json` memory repo, or created locally)
- WorkIQ MCP configured (for artifact gathering — optional but strongly recommended)

---

## Interview Protocol

### Rules

1. **Interview one phase at a time.** Complete each phase before moving to the next.
2. **Show each file update before writing.** Present the proposed content in a code block and get explicit user approval ("looks good", "approved", "yes", etc.) before modifying any file.
3. **If unsure, ask.** Never assume or fabricate user details.
4. **Use WorkIQ before asking the user to repeat themselves.** For discoverable facts (org structure, recent projects, team members, meeting patterns), search M365 first and confirm with the user.
5. **Keep files concise.** MEMORY.md targets ~200 lines. CLAUDE.md stays lean. Move detailed content to `memory/Knowledgebase/` subfolders.
6. **Preserve existing content.** If a file already has personalized sections, merge new content into the existing structure — don't overwrite.
7. **Allow skipping.** If the user says "skip" or "not applicable", move to the next phase without writing.
8. **Track progress.** Use the todo list to show which phases are complete, in progress, or remaining.

### Phase Overview

| Phase | Name | Target File(s) | WorkIQ Queries |
|-------|------|----------------|----------------|
| 0 | Connections Check | — (validation only) | Test MCP availability |
| 1 | About Me | `memory/MEMORY.md` | Emails (sent-from patterns), calendar (meeting titles), org chart |
| 2 | Communication & Voice | `CLAUDE.md` | Sent emails (analyze tone), Teams messages (communication patterns) |
| 3 | Working Preferences | `CLAUDE.md`, `AGENTS.md` | Calendar patterns, email volume, meeting frequency |
| 4 | Domain & Program Knowledge | `CLAUDE.md`, `memory/MEMORY.md` | SharePoint files, recent decks, project plans |
| 5 | Team & Contacts | `memory/MEMORY.md` | Org chart, frequent email recipients, Teams chat participants |
| 6 | Active Projects | `memory/MEMORY.md`, `memory/Knowledgebase/` | Project plans, milestone emails, ADO work items |
| 7 | Synthesis & Wiring | `CLAUDE.md`, `AGENTS.md` | — |

---

## Phase Details

### Phase 0: Connections Check

**Purpose:** Verify tooling before starting the interview.

**Steps:**

1. Check that `CLAUDE.md` and `AGENTS.md` exist. If not, copy from `.example` templates.
2. Check that `memory/` directory exists. If not, offer to create it locally.
3. If `memory/MEMORY.md` doesn't exist, create it from the template below.
4. Test WorkIQ MCP availability by running a simple query (e.g., search for the user's recent emails). If WorkIQ is unavailable, warn that artifact gathering will be skipped and all info must come from the interview.
5. List which MCPs are available (Outlook, Calendar, Teams, SharePoint, Word) so the user knows what data the agent can access.

**MEMORY.md template** (create if missing):

```markdown
# MEMORY.md — Permanent Semantic Memory

> Loaded automatically at the start of every session. Keep this file under ~200 lines.
> For detailed context, use `memory/Knowledgebase/` subfolders.

## User Profile

- **Name:**
- **Role/Title:**
- **Organization:**
- **Email:**
- **Key responsibilities:**

## Communication Preferences

- **Preferred style:**
- **Formality level:**
- **Response length preference:**

## Contacts & Team

(Key people the user works with regularly)

## Glossary

(Acronyms, internal terms, and project codenames)

## Active Context

(Current priorities, active projects, upcoming deadlines)

## Working Preferences

(How the user wants the agent to behave — output format, safety rules, workflow patterns)
```

---

### Phase 1: About Me

**Purpose:** Build the user's professional profile in MEMORY.md.

**WorkIQ Gathering (before asking questions):**
- Search sent emails for the user's email signature (title, org, contact info)
- Search calendar for recurring meetings (reveals team structure, responsibilities)
- Search for the user's display name and org info via Graph

**Interview Questions:**

1. What's your name and job title?
2. What organization/team are you in? What does your team do?
3. What are your key responsibilities? (Top 3-5 areas you own)
4. What's your professional background in 1-2 sentences?
5. Is there anything else people should know about your role — scope, authority level, reporting chain?

**Cross-reference:** Compare interview answers with WorkIQ findings. If there are discrepancies, ask the user to clarify.

**Output:** Update `memory/MEMORY.md` → `## User Profile` section.

---

### Phase 2: Communication & Voice

**Purpose:** Define how the agent should communicate on the user's behalf.

**WorkIQ Gathering (before asking questions):**
- Pull 5-10 recent sent emails and analyze tone, structure, sign-off patterns
- Pull recent Teams messages to detect formality patterns
- Note: DO NOT show email content to user unless asked — just extract patterns

**Interview Questions:**

1. When I write emails/messages on your behalf, how should they sound? (formal, casual, direct, diplomatic, etc.)
2. Are there phrases or patterns you always use? (greetings, sign-offs, recurring phrases)
3. Are there phrases you'd never use? (buzzwords, clichés, etc.)
4. Does your tone shift by context? (e.g., formal with leadership, casual with team, technical with engineers)
5. Is there a writer, leader, or communicator whose style you admire?
6. Any absolute rules? (e.g., "never use exclamation marks", "always bullet-point key asks")

**Output:** Update `CLAUDE.md` → `## Communication Principles` section. Merge new voice rules into existing principles (don't overwrite the structural framework — add user-specific nuance).

Example additions to CLAUDE.md:

```markdown
### Voice & Tone (Personalized)

- **Default tone:** [from interview]
- **With leadership:** [from interview]
- **With direct team:** [from interview]
- **Sign-off:** [from interview]
- **Never say:** [from interview]
- **Always include:** [from interview]
```

---

### Phase 3: Working Preferences

**Purpose:** Define how the agent should work day-to-day.

**WorkIQ Gathering:**
- Calendar: typical meeting load, free time patterns, working hours
- Email: volume patterns, response time norms

**Interview Questions:**

1. What do you want this agent to help with most? (Top 3 daily use cases)
2. What are your biggest workflow pain points today?
3. How should I communicate with you? (Bullet points vs. prose? Short vs. detailed? Proactive vs. on-demand?)
4. What output formats do you prefer? (Markdown tables, bullet lists, executive summaries, etc.)
5. What should I never do without asking first? (Beyond the existing security rules)
6. What hours do you work? Any time zones or schedule patterns I should be aware of?
7. Are there recurring tasks you'd like me to handle? (Weekly reports, meeting prep, email triage, etc.)

**Output:**
- Update `CLAUDE.md` → `## Metrics & Integrity` — add user-defined KPIs
- Update `AGENTS.md` — add custom rules under a new `## Working Preferences` section (before Skills)
- Update `memory/MEMORY.md` → `## Working Preferences` section

Example AGENTS.md addition:

```markdown
## Working Preferences

- **Primary use cases:** [from interview]
- **Communication format:** [from interview]
- **Working hours:** [from interview]
- **Recurring tasks:** [from interview]
- **Additional safety rules:** [from interview]
```

---

### Phase 4: Domain & Program Knowledge

**Purpose:** Give the agent deep expertise in the user's domain.

**WorkIQ Gathering:**
- SharePoint: search for recent strategy decks, roadmaps, program plans
- Emails: search for milestone announcements, program reviews
- Teams: search for program-related channel conversations

**Interview Questions:**

1. What program, product, or initiative are you currently working on?
2. What's the timeline? (Key dates, phases, milestones)
3. What are the key objectives and success metrics?
4. What's the current status? (On track, at risk, any blockers?)
5. Are there codenames, acronyms, or internal terms I should know?
6. What technical context matters? (Architecture, platform, dependencies)
7. Who are the key stakeholders?

**Output:**
- Update `CLAUDE.md` → `## Domain Knowledge` — replace the placeholder with real content
- Update `memory/MEMORY.md` → `## Glossary` with acronyms and terms
- If detailed, create `memory/Knowledgebase/Program/overview.md` with the full picture

---

### Phase 5: Team & Contacts

**Purpose:** Build a contacts directory so the agent knows who's who.

**WorkIQ Gathering:**
- Frequent email recipients (top 10-15 by volume)
- Calendar: recurring 1:1s and meeting attendees
- Teams: active chat participants

**Interview Questions:**

Present the WorkIQ-gathered list and ask:
1. Here are the people you interact with most [list]. Are these correct? Anyone missing?
2. For each key person: what's their role, and what do you work with them on?
3. Are there people outside your org you work with regularly? (Vendors, partners, customers)
4. Any communication preferences for specific people? (e.g., "always CC person X on emails to Y")

**Output:** Update `memory/MEMORY.md` → `## Contacts & Team` section.

Format:

```markdown
## Contacts & Team

| Name | Role | Context | Notes |
|------|------|---------|-------|
| Jane Smith | Engineering Lead | Owns firmware delivery | Prefers Teams over email |
| Bob Chen | Program Manager | Weekly sync Tuesdays | CC on all milestone updates |
```

---

### Phase 6: Active Projects

**Purpose:** Load the agent with current project context.

**WorkIQ Gathering:**
- Search for project plans, status reports, milestone emails
- ADO work items if landing-zone skill is configured
- OnePlanner if configured

**Interview Questions:**

1. What are your top 1-3 active projects right now?
2. For each project: status, next milestone, blockers, key decisions pending
3. Are there any deadlines in the next 2 weeks I should know about?
4. Where does project documentation live? (SharePoint, Confluence, ADO, etc.)

**Output:**
- Update `memory/MEMORY.md` → `## Active Context` section
- For substantial projects, create individual files in `memory/Knowledgebase/Program/`

---

### Phase 7: Synthesis & Wiring

**Purpose:** Review everything, wire it together, and verify.

**Steps:**

1. **Present a summary** of all the personalization that was done across files
2. **Verify CLAUDE.md** — read back the Identity, Communication Principles, Domain Knowledge, and Metrics sections. Ask "Does this represent you accurately?"
3. **Verify AGENTS.md** — read back any new Working Preferences or custom rules. Ask "Are these rules correct?"
4. **Verify MEMORY.md** — read back the full file. Ask "Anything missing or wrong?"
5. **Offer follow-ups:**
   - "Would you like me to create a scheduled daily briefing task?"
   - "Would you like me to set up a weekly report for your program?"
   - "Are there any other recurring workflows I should configure?"
6. **Save everything** — commit the changes and summarize what was built

---

## Resuming Interrupted Sessions

If the interview gets interrupted, the agent can resume:

1. Read MEMORY.md, CLAUDE.md, AGENTS.md to detect what's already been filled in
2. Check which sections still have placeholder content
3. Ask the user: "It looks like we completed phases 1-3 last time. Ready to continue with Phase 4 (Domain Knowledge)?"

Detection heuristics:
- `CLAUDE.md` → Identity section has non-default name/role → Phase 1 done
- `CLAUDE.md` → Communication Principles has personalized voice rules → Phase 2 done
- `AGENTS.md` → Has `## Working Preferences` section → Phase 3 done
- `CLAUDE.md` → Domain Knowledge has real content (not placeholder) → Phase 4 done
- `memory/MEMORY.md` → Contacts table has entries → Phase 5 done
- `memory/MEMORY.md` → Active Context has entries → Phase 6 done

---

## Usage Examples

**Start full personalization:**
> "Set up my coworker" / "Personalize my agent" / "Deep personalization"

**Resume interrupted personalization:**
> "Continue personalizing" / "Pick up where we left off on personalization"

**Update specific section:**
> "Update my domain knowledge" (runs Phase 4 only)
> "Update my contacts" (runs Phase 5 only)
> "Refresh my active projects" (runs Phase 6 only)

**Re-run with WorkIQ refresh:**
> "Re-scan my M365 data and update my profile"
