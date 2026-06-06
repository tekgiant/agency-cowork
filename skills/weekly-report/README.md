# weekly-report

Generate executive-ready weekly status reports for your programs (program 200, program 300, program 400) by gathering live context from M365 via WorkIQ and synthesizing with Knowledgebase content.

## Prerequisites

- **WorkIQ MCP** configured and authenticated (see [installation.md](../../installation.md))
- **`CLAUDE.md`** present in the project root (agent identity — auto-loaded every session)

## Registration

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\weekly-report"
```

Restart your Copilot session for the skill to appear in `/skills`.

## Usage

```
/weekly-report
```

Or describe what you need:

```
Generate the program 300 weekly status report
```

```
Write weekly bullets for all three programs
```

```
Draft exec update for program 200 this week
```

The skill will:
1. Ask which program (if not specified)
2. Query WorkIQ for emails, meetings, and files from the week
3. Cross-reference with Knowledgebase and prior week's report
4. Draft 3–5 executive-ready bullets
5. Present for your review before saving

## Report Structure

Each report contains 3–5 bullets covering:

- **Engineering progress** — milestones, deliverables, validation
- **Software / platform readiness** — builds, testing, spec reviews
- **Supply chain / vendor status** — key vendors, long-lead items
- **Schedule / milestone changes** — date shifts, critical path updates
- **Risk mitigations or escalations** — new risks, active mitigations

## Output

Reports are saved to:

```
memory/WeeklyReports/
├── program 200/
│   └── Week of MM-DD-YYYY.md
├── program 300/
│   └── Week of MM-DD-YYYY.md
└── program 400/
    └── Week of MM-DD-YYYY.md
```

## Example Output

```markdown
# Program A — Weekly Status (Week of 02/24/2026)

## Key Updates

- **Engineering milestones on track across key workstreams.** Focus shifting to
  integration testing, platform readiness, and deployment planning. Four architecture
  spec reviews completed this week with Wave 1 sign-offs targeting Feb 28.

- **Volume decision advanced to 10K units.** Cross-functional alignment
  reached on scaling from 5K→10K, with infrastructure builds pulled in to
  enable earlier lab readiness and drive significant cost avoidance.

- **Software release milestone moved to March 23; validation now late April.**
  Integration dependencies remain a gating factor — new tracker stood up to manage
  follow-ups against release readiness.
```

## Integration with Other Skills

- **send-email**: After generating a report, email it to stakeholders
- **markitdown**: Convert meeting decks or docs to markdown for the Knowledgebase before report generation
