---
name: design-review
description: |
  Use this skill when the user asks to "prepare a design review", "create a review checklist",
  "document review outcomes", "track review action items", "schedule a design review",
  "generate review package", or wants to manage the end-to-end design review process —
  from preparation through execution to follow-up. Supports schematic reviews, layout reviews,
  firmware reviews, and system-level architecture reviews.
---

# Design Review

End-to-end design review management for hardware teams. Automates the ceremony around reviews — preparation, checklists, documentation, action item tracking, and follow-up — so engineers focus on the actual technical review.

## Overview

Design reviews are critical gates in hardware development, but the process around them is pure toil:
- Manually assembling review packages from scattered documents
- Creating checklists from scratch each time
- Taking notes in real-time while trying to participate technically
- Chasing action items via email after the review
- Documenting outcomes in Word/Confluence days later

This skill automates all of that.

## Review Types

| Type | Trigger Phrases | Key Checklist Areas |
|------|----------------|-------------------|
| **Schematic Review** | "schematic review", "SCH review" | Net naming, decoupling, ERC clean, power sequencing, testability |
| **Layout Review** | "layout review", "PCB review" | Stackup, impedance, thermal relief, DFM/DFA, keepouts |
| **Firmware Review** | "FW review", "firmware review" | Register map, boot sequence, error handling, update mechanism |
| **System Architecture** | "architecture review", "system review" | Block diagram, interfaces, power budget, thermal envelope, BOM risk |
| **Signal Integrity** | "SI review", "signal integrity review" | Eye diagrams, crosstalk, impedance matching, return paths |
| **Power Delivery** | "PDN review", "power review" | Load map, transient response, efficiency, sequencing, protection |

## Workflow

### 1. Prepare Review Package

When the user says "prepare a design review for <topic>":

1. **Determine review type** from the topic description
2. **Generate checklist** from the appropriate template (see Checklists below)
3. **Gather documents** — Search QMD, SharePoint, and email for relevant specs, schematics, simulations:
   ```
   → Search knowledgebase for related specs
   → Search SharePoint for design files
   → Search email for latest design discussions
   ```
4. **Create the review package** as a markdown file:
   ```
   memory/Knowledgebase/Reviews/YYYY-MM-DD-<review-title>.md
   ```
5. **Schedule the meeting** (if requested) using the calendar skill
6. **Post to Teams** (if requested) — Share the review package link and agenda

### Review Package Template

```markdown
---
type: design-review
review_type: <schematic|layout|firmware|system|si|pdn>
date: YYYY-MM-DD
owner: <design owner>
reviewers: [<list of reviewers>]
status: scheduled | in-progress | completed
---

# Design Review: <Title>

## Scope
<What is being reviewed — block, subsystem, full board?>

## Design Documents
| Document | Location | Version |
|----------|----------|---------|
| <doc name> | <path or URL> | <rev> |

## Pre-Review Checklist
- [ ] <checklist item 1>
- [ ] <checklist item 2>
...

## Review Notes
<Captured during the review — findings, concerns, approvals>

## Action Items
| # | Action | Owner | Due | Status |
|---|--------|-------|-----|--------|
| 1 | | | | Open |

## Decision
- [ ] Approved — proceed to next phase
- [ ] Approved with conditions — must close action items before proceeding
- [ ] Not approved — requires redesign (see notes)
```

### 2. Capture Review Notes

During or after the review:

- **From Teams meeting transcript**: Use meeting-summary skill to extract key discussions, then merge into the review document
- **Manual entry**: User dictates findings → skill formats and appends to Review Notes
- **Action items**: Extract action items with owners and due dates

### 3. Track Action Items

After the review:

1. **Parse action items** from the review document
2. **Create ADO work items** (if requested) via the landing-zone or ado-work-items skill
3. **Send follow-up email** (if requested) with action item summary to all reviewers
4. **Schedule follow-up** (if action items have a common due date)

### 4. Close the Review

When all action items are resolved:

1. Update review status to `completed`
2. Record final decision (approved / approved with conditions / not approved)
3. Archive in Knowledgebase for future reference

## Checklists

### Schematic Review Checklist
- [ ] All nets named consistently (no auto-generated names)
- [ ] Decoupling capacitors placed per IC vendor recommendations
- [ ] Power sequencing meets all IC requirements
- [ ] ERC clean — no errors, warnings reviewed and waived with rationale
- [ ] Test points on critical signals (clock, reset, power rails, high-speed data)
- [ ] Pull-up/pull-down resistors on all open-drain/open-collector outputs
- [ ] Voltage level translation where needed between domains
- [ ] Reset circuitry covers all power domains and sequencing scenarios
- [ ] Thermal shutdown and overcurrent protection on all power regulators
- [ ] Mechanical connectors match board outline and enclosure constraints

### Layout Review Checklist
- [ ] PCB stackup matches impedance targets (document stackup in design file)
- [ ] Controlled impedance traces verified against SI simulation
- [ ] No trace stubs on high-speed signals (length-matched if differential)
- [ ] Thermal relief pads on all power components
- [ ] Via stitching on ground plane splits
- [ ] DFM rules checked (minimum trace/space, annular ring, drill aspect ratio)
- [ ] DFA rules checked (component spacing, orientation, pick-and-place clearance)
- [ ] Keepout zones respected (antenna, thermal, mechanical)
- [ ] Silkscreen readable at 1:1 scale (reference designators, polarity marks)
- [ ] Fiducials, tooling holes, and panel frame present

### System Architecture Checklist
- [ ] Block diagram covers all functional blocks and interfaces
- [ ] Interface protocols defined (PCIe gen/lanes, Ethernet speed, I2C/SPI addressing)
- [ ] Power budget calculated (worst-case, typical, sleep states)
- [ ] Thermal budget fits within system cooling solution
- [ ] BOM has second-source options for all critical components
- [ ] Compliance requirements identified (FCC, UL, RoHS, REACH)
- [ ] Testability plan — how will each subsystem be validated?
- [ ] Manufacturing plan — who builds it, what are the critical process steps?

## Integration Points

- **calendar**: Schedule review meetings with attendees
- **teams**: Post review packages and outcomes to team channels
- **meeting-summary**: Extract notes from Teams meeting transcripts
- **confluence**: Publish review outcomes to the wiki
- **landing-zone / ado-work-items**: Create ADO work items for action items
- **send-email**: Send review invitations and follow-up summaries

## Rules

- **ALWAYS** include the review type and status in the metadata header
- **ALWAYS** generate the appropriate checklist based on review type
- **ALWAYS** track action items with owners and due dates
- **NEVER** mark a review as "completed" if there are open action items
- **NEVER** skip the checklist — even experienced engineers miss things
- When merging meeting transcript notes, preserve the original speaker attributions
- Cross-reference action items with ADO work items when available
