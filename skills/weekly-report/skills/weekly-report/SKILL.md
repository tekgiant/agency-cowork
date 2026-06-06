---
name: weekly-report
description: This skill should be used when the user asks to "generate a weekly report", "write weekly status", "create a weekly update", "draft exec bullets", or wants to produce a weekly status report for a program. Also triggers on "status update for executives", "weekly bullets", "program update", "executive status report", or "program status".
---

Generate executive-ready weekly status reports for your programs by gathering live context from M365 via WorkIQ (Microsoft Graph) and synthesizing it with Knowledgebase content.

## Executive Report Mode

This mode enables the agent to generate grounded, executive-ready status reports for a **single program** by leveraging WorkIQ to extract, verify, and summarize key updates from internal M365 sources via Microsoft Graph.

**CRITICAL: One program per run.** Always select exactly one program to report on. Customize the programs table below with your organization's programs.

If the user requests a report covering all programs, run this skill **once per program** and store each in its respective subfolder.

**Output destination:** `memory/WeeklyReports/<Program>/Week of MM-DD-YYYY.md` (using Monday's date)

**When to use:** Executive status reports, program reviews, monthly readouts, leadership summaries, or any request requiring synthesis of internal data for a specific program.

**Key difference from general enterprise research:** This mode is scoped to a single program, queries WorkIQ with program-specific search terms, and outputs to the program's memory/WeeklyReports subfolder. All quality standards (citation tracking, fact verification, anti-hallucination) still apply.

---

## Programs

Customize this table with your organization's programs:

| Program | Codename | Report Folder |
|---------|----------|---------------|
| Program A | (codename) | `memory/WeeklyReports/Program A/` |
| Program B | (codename) | `memory/WeeklyReports/Program B/` |
| Program C | (codename) | `memory/WeeklyReports/Program C/` |

---

### Phase 1: Planning the Search Strategy

**Confirm program scope first:**
1. Identify the target program (exactly one)
2. If user did not specify, ask which program to report on
3. Set output path: `memory/WeeklyReports/<Program>/Week of MM-DD-YYYY.md`

**Load context:**
1. Apply identity and communication principles from `CLAUDE.md` (auto-loaded); read `memory/Knowledgebase/Program/overview.md` for program domain knowledge
2. Read prior reports from `memory/WeeklyReports/<Program>/` for continuity
3. Check `memory/Knowledgebase/` for standing context (program, specs, review history):
   - `Program/` for roadmap and strategy
   - `ExecutiveReviews/` for recent exec readouts
   - `ProgramExecutionCouncil/` for leadership review minutes
   - `Workstreams/` for workstream-specific context
   - `Specifications/` for technical reference

**Identify and prioritize high-value internal sources for the selected program:**
- Program review meeting summaries and decks
- Monthly Executive Review meetings and pre-read decks
- Team channels relevant to the program
- Internal documents and wikis
- Email threads from program leads and executives

**Define search queries by:**
- **Program**: Use program name and codename
- **Topic**: milestones, risks, performance, supply chain, software, platform, cost, volume
- **Time range**: Focus on recency (current week/month) unless historical context requested

**Plan parallel WorkIQ queries** — decompose into 5–10 independent queries before executing.

---

### Phase 2: Executing the Search

Use WorkIQ MCP to retrieve content from Microsoft Graph. **All queries scoped to the selected program. Launch in parallel:**

**If the user's prompt includes specific topics** (e.g., "focus on supply chain and platform"), incorporate those topics into every query below as additional search terms. These user-specified topics take priority and should appear in at least 2 dedicated queries.

**Emails:**
```
What are the latest emails about <Selected Program> <Topic>? Include decisions, milestones, risks, and accomplishments.
```

**Meetings:**
```
What meetings were held <Time Range> about <Selected Program>? Include transcripts, action items, and decisions.
```

**Teams chats:**
```
What are the latest Teams chat messages about <Selected Program> <Topic>?
```

**Files:**
```
What files or documents were shared <Time Range> about <Selected Program> <Topic>?
```

**User-specified topic queries (if provided):**
```
What are the latest updates about <Selected Program> specifically related to <User Topic 1>?
What decisions or accomplishments this week relate to <Selected Program> <User Topic 2>?
```

Replace `<Selected Program>` with the specific program name and codename. Replace `<User Topic N>` with each specific topic from the user's prompt.

**Prioritization rules:**
- Content authored by program leads and executives ranks highest
- Leadership review decks and exec review pre-reads rank above general discussion
- Recent content (this week/month) ranks above older material
- Tag and annotate relevant excerpts for downstream summarization

**Iterative search for coverage gaps (CRITICAL):**
After the initial parallel queries, assess whether each report area has sufficient source material:
- If any area has **fewer than 2 substantive sources**, run **2–3 additional targeted WorkIQ queries** for that area using narrower or alternative search terms
- Example follow-up queries:
  - Engineering gap: "What updates on <Program> milestones, design, validation, testing, or integration this week?"
  - Platform gap: "What updates on <Program> hardware, infrastructure, capacity, power, or deployment this week?"
  - Software gap: "What updates on <Program> software, platform, SDK, tools, or integration testing this week?"
- If follow-up searches still return insufficient results, **note explicitly in that section**: *"Insufficient data from internal sources to provide a detailed status update for this area this week."*
- Do NOT fabricate or pad content to fill gaps

**Discovering additional topics:**
While evaluating sources, watch for areas of **significant progress or discussion that fall outside the core report areas**. Common examples:
- Supply chain (vendor negotiations, lead times, PO decisions, second-sourcing)
- Data center deployment (site selection, permitting, build-out, capacity planning)
- Customer / workload enablement (hand-off, onboarding, integration)
- Cost & finance (OpEx/CapEx decisions, funding gaps, volume economics)
- External communications (press releases, analyst briefings, partner announcements)
- Governance & process (review decisions, org changes, tooling adoption)

If any of these topics have **substantive content from 2+ sources**, add them as **additional sections** in the Expanded Summary after the core report areas.

---

### Phase 3: Evaluating and Curating Sources

Assess each retrieved source for:

| Criterion | Evaluation |
|-----------|-----------|
| **Recency** | When was this authored/shared? Is it current? |
| **Relevance** | Does it directly address the report scope? |
| **Authoritativeness** | Is the author a program lead, exec, or domain owner? |
| **Consistency** | Does it align with other sources, or contradict them? |
| **Signal-to-noise** | Is the content substantive or just administrative? |

**Actions:**
- Discard outdated or unverified content
- Flag assumptions and uncertainties explicitly
- Note conflicting information for the Fact Verification phase
- Cross-reference across sources — claims supported by 2+ sources are stronger

---

### Phase 4: Summarizing Key Information

Extract decision-critical facts, metrics, and insights organized by category:

**Timeline & Milestones:**
- Key milestone dates, release targets, delivery gates
- Schedule changes and their impact

**Performance & Capacity Metrics:**
- Perf/$, Perf/W, rack power, HBM bandwidth
- Unit scale, DC capacity percentages

**Program Status & Achievements:**
- Engineering milestones and deliverables
- Software/platform readiness, spec review completion
- Governance and tooling adoption

**Key Risks & Mitigations:**
- Supply chain (key vendors, long-lead components)
- Schedule compression and critical path items
- Cost and funding gaps
- Each risk paired with its mitigation status

**Options & Trade-offs:**
- Decisions pending with clear pros/cons
- Resource allocation trade-offs

**Structure summaries for the selected program** with consistent subsections (not across multiple generations).

---

### Phase 5: Structuring the Output Document

**Document Structure (Exec Bullets + Expanded Area Summaries):**

```markdown
# <Program> — Weekly Status (Week of MM/DD/YYYY)

**Date:** YYYY-MM-DD
**Scope:** <Program> (e.g., "Program A") — Week of [date range]

## Key Updates

- **<Headline>.** Supporting detail with specific metrics, dates, or decisions. Context on impact or next steps.

- **<Headline>.** Supporting detail with specific metrics, dates, or decisions. Context on impact or next steps.

- **<Headline>.** Supporting detail with specific metrics, dates, or decisions. Context on impact or next steps.

---

## Expanded Summary

### Engineering
Detailed progress on key engineering workstreams and milestones. Include schedule status, risks, and key decisions.

### Platform
Detailed progress on platform, infrastructure, hardware, and deployment readiness. Include vendor status and procurement milestones.

### Software
Detailed progress on software, tools, SDKs, testing, and integration. Include dependency status and resource constraints.

### <Additional Section> (if warranted)
If significant progress or discussion was discovered outside the core areas (e.g., Supply Chain, Deployment, Customer Enablement, Cost & Finance, External Communications), add dedicated sections here with the same level of detail.
```

**Bullet requirements (Key Updates section):**
- Generate **3–5 bullets** focusing on key updates, decisions, or accomplishments this work week
- Keep it **concise and high impact** — each bullet is self-contained and understandable without prior context
- **Lead with the headline** — bold the key takeaway
- **Quantify where possible** — dates, percentages, unit counts, timeline shifts
- No bullet exceeds 3 sentences
- If the user specified topics in their prompt, ensure those topics are prominently covered in the bullets

**Expanded Summary requirements:**
- Provide **2–4 paragraphs per area** (Engineering, Platform, Software) covering the week's progress in detail
- Include specific dates, metrics, owners, and decision outcomes where available
- Call out risks with mitigations and open items with owners
- Each area should stand alone — an exec reading only one section gets a complete picture
- Do not duplicate the Key Updates bullets verbatim; expand with additional context and detail
- If an area has insufficient sources after follow-up searches, state: *"Insufficient data from internal sources to provide a detailed status update for this area this week."*
- If significant topics emerged outside the three core areas, add them as additional sections with the same depth and rigor

**Quality checklist:**
- [ ] 3–5 exec bullets, each self-contained and high-impact
- [ ] Expanded summaries cover Engineering, Platform, and Software with substantive detail (+ additional sections if warranted)
- [ ] Areas with insufficient data are explicitly noted rather than padded
- [ ] Claims are grounded in WorkIQ data or Knowledgebase content
- [ ] Risks are paired with mitigations where available
- [ ] User-specified topics are addressed if provided
- [ ] Consistent with `CLAUDE.md` communication principles

**Output path:** `memory/WeeklyReports/<Program>/Week of MM-DD-YYYY.md`

**Visual Elements (when generating HTML):**
- Timeline of milestones across generations
- Metrics cards (Perf/$, Perf/W, unit scale, rack power)
- Tables for risks, trade-offs, and status comparisons
- RAG status indicators (Red/Amber/Green) where applicable

---

### Phase 6: Fact Verification

Cross-check every key point against source documents:

- Verify all dates, metrics, and claims against the original WorkIQ sources
- Ensure data points are accurate and grounded — no interpolation without labeling
- **Clearly separate:**
  - **Facts** — directly stated in source material, cited with [N]
  - **Assumptions** — inferred or estimated, explicitly labeled as such
  - **Risks** — identified concerns with stated likelihood/impact where available
- Omit unverifiable claims or label them: *"Unverified — requires confirmation from [owner]"*
- Flag contradictions between sources and note which source is more authoritative

---

### Phase 7: Final Editing (Style Conformance)

Align with `CLAUDE.md` communication principles:

- **Analytical, objective, data-driven tone** — no advocacy or optimism bias
- **Formal, concise, structured style** — optimize for senior executive readership
- **Quantify claims** with explicit metrics (Perf/$, Perf/W, dates, unit counts, percentages)
- **Present options neutrally** with clear trade-offs, risks, and constraints
- **Explicitly separate facts, assumptions, and risks** — acknowledge uncertainty
- **Conclude with next steps**, decisions required, and open issues

**Style checklist:**
- [ ] Remove jargon and casual language
- [ ] Use consistent formatting and headings
- [ ] No filler words or hedging ("somewhat", "fairly", "potentially")
- [ ] Every metric has a unit and timeframe
- [ ] Each risk has an owner or escalation path where known
- [ ] Executive Summary is ≤3 sentences of decision-critical facts

**Output delivery:**
1. Save markdown to `memory/WeeklyReports/<Program>/Week of MM-DD-YYYY.md` immediately — do NOT prompt for review before saving
2. Present the saved report inline in chat
3. Offer to email via send-email skill
4. If user needs reports for additional programs, offer to run again for the next program

---

### Executive Report — Quick Reference

| Phase | Action | Tool |
|-------|--------|------|
| 0. Scope | Confirm ONE program; set output path | ask_user |
| 1. Plan | Load CLAUDE.md (auto-loaded), prior reports for this program, KB context; define queries | view, WorkIQ |
| 2. Search | Parallel WorkIQ queries scoped to selected program (emails, meetings, chats, files) | WorkIQ MCP |
| 3. Evaluate | Score sources by recency, authority, consistency | Internal analysis |
| 4. Summarize | Extract metrics, milestones, risks, decisions for this program | Internal analysis |
| 5. Structure | Build single-program report using document template | create/edit |
| 6. Verify | Cross-check all claims against sources | Internal analysis |
| 7. Edit | Apply CLAUDE.md style, remove jargon, save to `memory/WeeklyReports/<Program>/` | edit |

---

## Gotchas

These failure modes have been observed in production — they will bite you if ignored.

### Data Quality

- **WorkIQ queries can time out or return partial results.** If you get fewer than 2 substantive sources for any report area, run 2–3 additional targeted queries with narrower search terms before declaring "insufficient data." Don't give up after one query per area.
- **Hallucination risk is highest in the metrics section.** Every number (dates, percentages, unit counts, timeline shifts) must be traceable to a specific WorkIQ source. Never interpolate, estimate, or round without explicitly labeling it as an estimate.
- **WorkIQ may return very long meeting transcripts.** Extract only decisions, action items, and key outcomes — don't summarize the entire 60-minute discussion or you'll bury the signal.

### Report Continuity

- **Always read the previous week's report before generating.** Without it, the model repeats stale updates ("X milestone hit" when it was already reported last week) or misses ongoing threads. The prior report lives in `memory/WeeklyReports/<Program>/`.
- **One program per run is CRITICAL.** Multi-program reports produce incoherent outputs because WorkIQ sources from different programs blur together. If the user asks for all programs, run separately for each and store independently.

### Source Authority

- **Content from program leads and executives outranks general discussion.** A Teams chat from an IC is less authoritative than a leadership review deck — weight sources accordingly.
- **When sources contradict each other, flag the contradiction** — don't silently pick one. Note which source is more authoritative and surface the disagreement.

### Output

- **Save immediately — do not prompt for feedback before saving.** The user expects the report to be written, not held pending approval. They can edit after.
- **If a report already exists for that week, ask before overwriting** — the user may have manually edited the prior version.

## Composes With

- **qmd-memory** — Search for past reports, decisions, and historical context to ensure continuity
- **email-triage** — Pull recent urgent threads for the "Key Risks" section
- **teams** — Search team channels for blocker discussions and progress updates
- **send-email** — Offer to email the finished report to stakeholders
- **ado** — Pull sprint status, work item counts, and P0/P1 bug status for the report
- **kusto-query** — Pull telemetry metrics for data-driven report sections

## Rules

- Always apply `CLAUDE.md` communication principles (auto-loaded every session)
- Always query WorkIQ for live data — do not rely solely on Knowledgebase content
- Always check the prior week's report for continuity and to avoid repeating stale updates
- Always save the report immediately after generation — do not prompt for feedback before saving
- One report per program per week — if a report already exists for that week, ask before overwriting
- One program per run — never combine multiple programs in a single report
- Use formal, concise, executive-ready language — no filler, no hedging
- Keep content focused on what changed this period — not standing background
- If WorkIQ returns insufficient data for a program, note the gap and ask the user to supplement
