---
name: design-system
description: |
  Use this skill when the user asks to "set up my brand", "design my brand", "create DESIGN.md",
  "update my brand colors", "change my brand fonts", "customize my visual identity", "brand setup",
  "set up my design system", or any request to create or update the project's visual brand identity.
  This is a guided interview that creates DESIGN.md and syncs key values to agentconfig.json.
---

# Design System Skill

A guided interview that creates a `DESIGN.md` brand identity file at the project root. All visual output skills (webpage-builder, visual-explainer, powerpoint, svg-to-ppt) read this file to produce branded, consistent output.

## Overview

This skill follows the same interview pattern as `deep-personalization` — phase-by-phase questions, show-before-write approval, and resume detection. The output is a single `DESIGN.md` file plus a sync of key values to `agentconfig.json > office.branding` for backward compatibility with python-based Office skills.

### What Gets Created

| Target File | What's Written | Phase |
|-------------|---------------|-------|
| `DESIGN.md` | Full brand design system — palette, typography, components, layout, assets | 5 |
| `agentconfig.json` | Synced colors, fonts, and company name under `office.branding` | 5 |

### Prerequisites

- `agentconfig.json` exists in the project root (for branding sync)
- Project root is writable

---

## Interview Protocol

### Rules

1. **Interview one phase at a time.** Complete each phase before moving to the next.
2. **Show the full DESIGN.md before writing.** Present the generated content in a code block and get explicit user approval ("looks good", "approved", "yes") before writing to disk.
3. **If unsure, ask.** Never assume brand preferences.
4. **Seed from agentconfig.json.** If `office.branding` has non-default values, pre-fill company name, colors, and fonts as suggestions.
5. **Allow skipping.** If the user says "skip", use sensible defaults for that phase.
6. **Track progress.** Use the todo list to show which phases are complete, in progress, or remaining.
7. **Don't edit bundled skills.** If the user wants visual behavior beyond what DESIGN.md provides, recommend creating a custom skill (copy + rename) rather than editing bundled skills directly. This ensures their customizations survive skill updates.

### Phase Overview

| Phase | Name | User Interaction |
|-------|------|-----------------|
| 0 | Discovery | Automated — check for existing DESIGN.md, read agentconfig.json |
| 1 | Brand Identity | 3 questions — company name, brand mood, visual density |
| 2 | Color Palette | 1 selection — pick a curated palette or provide custom colors |
| 3 | Typography | 2 questions — Office or web context, font pairing selection |
| 4 | Component Preferences | 2 quick questions — corners, hierarchy style |
| 5 | Write & Sync | Approval — generate DESIGN.md, confirm, write, sync agentconfig |

---

## Phase Details

### Phase 0: Discovery

**Purpose:** Detect existing state and seed values.

**Steps:**

1. Check if `DESIGN.md` already exists at the project root.
   - If yes, read it and ask: "You already have a DESIGN.md. Would you like to update it or start fresh?"
   - If updating, show current values and ask which section to change, then skip to the relevant phase.
2. Read `agentconfig.json` → `office.branding` for seed values:
   - `company` → pre-fill company name (skip question if non-default)
   - `primary_color`, `accent_color`, `dark_color` → suggest as starting palette
   - `font_heading`, `font_body` → suggest as starting fonts
3. If agentconfig has non-default values, present them: "I found these branding values in your config. I'll use them as starting points — you can change any of them."

---

### Phase 1: Brand Identity

**Purpose:** Establish the brand's personality and visual direction.

**Questions:**

1. **"What's your company or program name?"**
   - Pre-fill from `agentconfig.json > office.branding.company` if non-default ("Your Company")
   - Also ask for product/program name and tagline if applicable

2. **"What mood best describes your brand?"**
   Present these options:
   - `A` — **Professional & Trustworthy** — Clean lines, blues and grays, corporate polish
   - `B` — **Bold & Modern** — High contrast, strong accents, forward-looking
   - `C` — **Warm & Approachable** — Earthy tones, rounded shapes, inviting
   - `D` — **Technical & Precise** — Monospace accents, tight spacing, data-driven
   - `E` — **Creative & Expressive** — Rich purples, dynamic layouts, artistic
   - `F` — **Custom** — Describe your brand mood in your own words

3. **"What visual density do you prefer?"**
   - `Spacious` — Generous whitespace, breathing room, fewer elements per section
   - `Balanced` — Standard spacing, good mix of content and whitespace
   - `Information-dense` — Compact layout, more content per viewport, smaller margins

---

### Phase 2: Color Palette

**Purpose:** Select the brand's color system.

**Steps:**

1. Based on the mood selected in Phase 1, read `./references/color-palettes.md` and present the 2 palettes for that mood.
2. Ask: **"Pick a palette, or provide your own colors."**
   - User can pick one of the presented palettes (e.g., "Azure Authority" or "Navy Compass")
   - User can provide their own hex values (e.g., "My primary is #2563EB, accent is #F59E0B")
   - User can provide a partial override (e.g., "I like Navy Compass but change the accent to #E63B2E")
3. If the user provides custom colors, generate semantic names using `./references/brand-vocabulary.md`.
4. Confirm the final 6-color palette with the user before proceeding.

**Palette structure (always 6 roles):**

| Role | Purpose |
|------|---------|
| Primary | Main action color — buttons, links, active states |
| Accent | Highlights, badges, secondary actions, emphasis |
| Dark | Headers, footers, hero backgrounds, dark sections |
| Background | Page canvas, main content areas |
| Surface | Cards, panels, elevated containers |
| Muted | Captions, metadata, disabled states, secondary text |

---

### Phase 3: Typography

**Purpose:** Select font pairings that match the brand and output context.

**Questions:**

1. **"Are your visual outputs primarily for Office documents or web?"**
   - `Office` — Fonts must render in PowerPoint, Word, Excel (Segoe UI, Aptos, Calibri, Arial, Georgia, Cambria, Cascadia Code)
   - `Web` — Google Fonts available (Plus Jakarta Sans, Inter, DM Sans, Sora, Space Grotesk, etc.)
   - `Both` — Use Office-safe fonts as primary, note web alternatives in the accent/display slot

2. Based on context, present 3-4 font pairings:

   **Office-safe pairings:**
   - `1` — **Segoe UI + Georgia** — Modern sans headings, classic serif accents, Cascadia Code for data
   - `2` — **Aptos + Aptos Serif** — Microsoft's latest default, clean and contemporary
   - `3` — **Calibri + Cambria** — Proven Microsoft pairing, universally available
   - `4` — **Arial + Georgia** — Maximum compatibility, strong contrast

   **Web (Google Fonts) pairings:**
   - `1` — **Plus Jakarta Sans + Cormorant Garamond** — Rounded modern + elegant serif
   - `2` — **DM Sans + DM Serif Display** — Matched family, versatile
   - `3` — **Space Grotesk + Instrument Serif** — Technical sans + editorial serif
   - `4` — **Sora + Crimson Pro** — Geometric modern + literary serif

   Ask: **"Pick a pairing, or name your own fonts."**

**Font roles (always 4):**

| Role | Purpose |
|------|---------|
| Heading | Section headers, slide titles, card headings |
| Body | Paragraph text, bullet points, descriptions |
| Accent/Display | Hero titles, pull quotes, editorial moments |
| Monospace | Data labels, code, technical content, captions |

---

### Phase 4: Component Preferences

**Purpose:** Quick visual preference questions for component styling.

**Questions:**

1. **"Rounded or sharp corners?"**
   - `Rounded` — 8-12px border radius, friendly and modern (default)
   - `Sharp` — 0-2px border radius, precise and editorial
   - `Pill` — Fully rounded ends on buttons/badges, large radius on cards

2. **"Subtle or bold hierarchy?"**
   - `Subtle` — Light borders, minimal shadows, understated depth (default)
   - `Bold` — Stronger shadows, vivid accent backgrounds, clear visual layers
   - `Mixed` — Bold for hero/primary sections, subtle for supporting content

---

### Phase 5: Write & Sync

**Purpose:** Generate the final DESIGN.md, get approval, write to disk, sync to agentconfig.json.

**Steps:**

1. **Generate the full DESIGN.md** using all collected answers. Follow this structure:

```markdown
# DESIGN.md — Brand Design System

> All visual skills read this file. Created by the design-system skill.

## Visual Theme & Atmosphere

- **Brand mood:** [from Phase 1]
- **Visual density:** [from Phase 1]
- **Design philosophy:** [generated from mood + density]

## Color Palette & Roles

| Name | Hex | Role |
|------|-----|------|
| [semantic name] | [hex] | [role description] |
(6 rows)

## Typography Rules

- **Heading font:** [font] — [why it fits]
- **Body font:** [font] — [why it fits]
- **Accent font:** [font] — [for hero titles, pull quotes]
- **Monospace font:** [font] — [for data, code, technical labels]
- **Hierarchy:** [heading sizes, body sizes, caption sizes]

## Component Stylings

- **Buttons:** [from Phase 4 + palette]
- **Cards:** [from Phase 4 + palette]
- **Charts:** [series color mapping from palette]

## Layout Principles

- **Content width:** [from density]
- **Spacing scale:** [from density]
- **Alignment:** [default]
- **Responsive:** [default]

## Brand Assets

- **Company name:** [from Phase 1]
- **Program/product name:** [from Phase 1]
- **Logo path:** [null or user-provided]
- **Tagline:** [from Phase 1]
```

2. **Present the full file** in a code block and ask: "Does this look right? Say 'approved' to write it, or tell me what to change."

3. **On approval, write `DESIGN.md`** to the project root.

4. **Sync key values to `agentconfig.json`:**

   Read the current `agentconfig.json`, then update these fields under `office.branding`:

   | DESIGN.md value | agentconfig.json path |
   |-----------------|----------------------|
   | Primary color hex | `office.branding.primary_color` |
   | Accent color hex | `office.branding.accent_color` |
   | Dark color hex | `office.branding.dark_color` |
   | Heading font | `office.branding.font_heading` |
   | Body font | `office.branding.font_body` |
   | Company name | `office.branding.company` |

   This ensures python-based Office skills (powerpoint editor, excel, word-doc) that read `office.branding` via `skills/office_common/config.py` → `load_config()` continue working without code changes.

5. **Confirm sync** by showing the updated `office.branding` values.

---

## Resuming & Updating

### Resume Detection

If the interview gets interrupted, the agent can resume:

1. Check if `DESIGN.md` exists → if yes, read it to detect completed state
2. Ask: "You have an existing DESIGN.md. Would you like to update a specific section or start fresh?"

### Update Flow

When the user says "update my brand colors" or "change my fonts":

1. Read existing `DESIGN.md`
2. Skip to the relevant phase (Phase 2 for colors, Phase 3 for fonts, Phase 1 for identity)
3. Show the current values and ask what to change
4. Regenerate the affected section(s) of DESIGN.md
5. Re-sync to agentconfig.json

**Trigger phrases for partial updates:**
- "Update my brand colors" / "Change my palette" → Phase 2
- "Update my brand fonts" / "Change my typography" → Phase 3
- "Update my brand" / "Refresh my brand" → Phase 1 (full re-interview)
- "Update my brand assets" / "Change company name" → Phase 1, question 1 only

---

## Design Philosophy Generation

Based on mood and density, generate a one-line design philosophy:

| Mood | Density | Example Philosophy |
|------|---------|-------------------|
| Professional | Balanced | "Clarity over decoration — every element earns its place" |
| Professional | Spacious | "Confidence expressed through restraint and breathing room" |
| Bold | Information-dense | "Impact through contrast — bold statements, zero noise" |
| Warm | Spacious | "Inviting spaces that welcome exploration" |
| Technical | Information-dense | "Precision-first — data speaks, design amplifies" |
| Creative | Balanced | "Structured expression — creativity within intentional constraints" |

---

## Usage Examples

**Start brand setup:**
> "Set up my brand" / "Design my brand" / "Create DESIGN.md"

**Update specific aspect:**
> "Change my brand colors to something warmer"
> "Switch my fonts to web-safe Google Fonts"
> "Update my company name in DESIGN.md"

**Start fresh:**
> "Recreate my DESIGN.md from scratch"
