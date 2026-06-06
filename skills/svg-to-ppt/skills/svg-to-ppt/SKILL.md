---
name: svg-to-ppt
description: >
  Use this skill when the user asks to "create a diagram for PowerPoint", "make an SVG slide",
  "convert SVG to PPT", "build an architecture diagram", "generate editable PowerPoint shapes",
  or needs SVG diagrams that convert cleanly to editable PowerPoint shapes. Triggers include
  "svg", "diagram to ppt", "editable shapes", "architecture diagram", "process diagram".
---

# SVG-to-PPT Skill Pack

Generalizable workflow for creating SVG diagrams that convert cleanly to editable PowerPoint shapes.

## When to Use
- You need architecture/process diagrams in PPT with post-conversion editability.
- You need predictable shape conversion across Office environments.
- You want reusable standards (grouping, arrows, text wrap, validation).

## Inputs
- Business logic summary (what the diagram must communicate)
- Diagram structure (lanes, sections, or phases)
- Content blocks (titles + pre-wrapped text lines)
- Styling constraints (minimal palette, no decorative complexity)

## Outputs
- PPT-compatible SVG (primitive shapes only)
- Prompt package for LLM-based diagram generation
- Validation checklist for conversion quality

## Workflow
1. **Define logic map**
   - List lanes/phases and required nodes.
   - Identify key branches and convergence points.
2. **Lay out with absolute coordinates**
   - Create lane containers and block boxes first.
   - Add text as pre-wrapped lines (`<text>` per line).
3. **Connect with atomic arrows**
   - Each arrow is a `<g>` with one `line` + one `polygon`.
   - Line endpoint penetrates polygon by 2–4 px.
   - Validator note: the tool prefers atomic `Arrow_*` groups but will accept a single `layer-connectors` group as a documented fallback when atomic grouping isn't feasible. Prefer atomic grouping when possible.
4. **Apply compatibility constraints**
   - No `<marker>`, no path-based arrow tips.
   - Prefer inline element styling over CSS dependencies.
5. **Validate in toolchain**
   - Open SVG in VS Code.
   - Insert into PPT and `Convert to Shape`.
   - Ungroup and inspect long text blocks + arrows.

## DESIGN.md Integration

- If `DESIGN.md` exists at the project root, use its Primary and Accent colors for shape fills and borders.
- Use the heading font from DESIGN.md only if it is Office-safe (Segoe UI, Aptos, Arial, Calibri, Georgia, Cambria); otherwise fall back to Aptos.
- If `DESIGN.md` does not exist, use the default palette and Office-safe fonts as specified below.

## Mandatory Constraints
- Use only `rect`, `line`, `polygon`, `text` unless a strong reason exists.
- Use hierarchical groups: `Main_Group > layer_* > Block_* / Arrow_*`.
- Use absolute coordinates (avoid transform-heavy composition).
- Use Office-safe fonts: `Aptos`, `Segoe UI`, `Arial`.
- Keep typography proportional to box width (for ~1600px canvas: heading ~16–20px, body ~12–15px for dense content).
- Use inline styling on elements (`fill`, `stroke`, `stroke-width`); avoid external CSS or `<style>` blocks.
- Layout order: place major blocks first, connectors/arrows second, legend last.
- Avoid unnecessary line crossings; use clear top-down or left-right flow.
- Output only valid SVG content.

## Files in this Skill
- `../../CHECKLIST.md` — authoring and conversion QA checklist
- `../../templates/ppt_shape_starter.svg` — copy/paste starter
- `../../examples/api_profile_filtering_flow.svg` — worked reference example
 - `../../Makefile` — provides `make validate` to run the full validation suite locally (recommended before publishing)
 - `Makefile` guardrails: `MAX_FONT_SIZE` and `MAX_TEXT_CHARS` catch common overflow-prone outputs (`STRICT_TEXT_FIT=1` to enforce as hard failure)
 - Note: Avoid embedding `<defs>` with markers or external font/image references in shared diagrams; these commonly cause rendering failures in PPT and some SVG viewers. Prefer primitives and inline styling.

### Header box sizing

- For small header boxes used to label subsections (like `SKILL.md`, `PROMPT.md`, `CHECKLIST.md`) prefer calculating and setting an explicit `height` based on number of lines and chosen line-height. Example:

   ```text
   box_height = (n_lines * line_height) + (2 * padding)
   ```

- Recommended defaults: `line_height` 18px, `padding` 8–12px. That yields `box_height` ~72–90px for 2–3 lines.
- Always emit absolute `y` positions for each `<tspan>` within these header boxes to avoid renderer-relative spacing issues.

Additional safeguard guidance:
- When authoring blocks, add a small safety margin to the computed box height: `box_height = (n_lines * line_height) + (2 * padding) + safety_margin` where `safety_margin` = 10–20 px.
- Break long lines into explicit `<tspan>` lines and use absolute `y` coordinates; avoid `dy` stacking.
- Reserve an explicit right-side padding of 12–16px inside blocks to absorb font fallback width differences after conversion.

## Known Convert-to-Shape Issue & Workaround

- Problem: In some Office builds, `Convert to Shape` can produce overlapping or poorly-wrapped text inside converted rectangles. This is often caused by renderer differences in interpreting relative `dy` values on `<tspan>` elements or by insufficient box padding for the chosen font size.

- Root cause: Using cumulative `dy` offsets (for example many `<tspan dy="20">` lines) creates relative positioning that some renderers mis-handle, producing collapsed line spacing or placement that overlaps other nearby text elements.

- Recommended solution:
   - Author text blocks as a single `<text>` element containing multiple `<tspan>` children where each `<tspan>` uses explicit absolute `y` coordinates (and `x` as needed). Absolute `y` is more robust across viewers and PPT's Convert-to-Shape implementation.
   - Keep consecutive `<tspan>` lines separated by at least ~18 px (`MinLineGap`) to avoid 1–2 px overlap caused by font metric differences during conversion.
   - Increase per-block vertical padding and box `height` by a small margin (e.g., +10–20 px) to provide breathing room for line-height differences.
   - Prefer slightly smaller body fonts over aggressive wrapping; aim for conservative line lengths and pre-wrapped lines. Keep segments under `MAX_TEXT_CHARS` (default 90) unless the container is widened.
   - If overlap persists after the above changes, reduce font-size by 1–2 pts or increase the block width/padding for the affected block, then re-run validation.

- Validation step: After making these changes, run `make validate-ps` (line-gap + right-edge fit checks), then run `make validate`, and test `Convert to Shape` in PowerPoint. If overlapping still occurs, attach a screenshot of the converted slide and the corresponding SVG so an author can map the problematic shape back to the SVG lines and iterate.

### Reference Example

A properly authored 3-line block (18px line height, top text y at 100):

```xml
<rect x="40" y="88" width="320" height="74" rx="6" fill="#fff" stroke="#333" />
<text x="56" y="100" font-family="Segoe UI" font-size="12" fill="#111">
   <tspan x="56" y="100">First line of title or heading</tspan>
   <tspan x="56" y="118">Second line — body, shorter length</tspan>
   <tspan x="56" y="136">Third line — final detail</tspan>
</text>
```

### Pre-Output Self-Check

Before finalizing any SVG, verify:
- No `<marker>` usage
- No `<path>` arrow tips
- Arrows grouped atomically
- Text lines do not touch block borders
- Layer and block IDs are unique and meaningful

Quick rule-of-thumb to avoid bottom/right overflow:
- Prefer moving a block left or increasing width instead of reducing font-size when a block sits near the canvas edge.
- If a block contains many small lines (notes, tips), increase its height by at least 20 px over the theoretical computed height as a conservative buffer.

## Input Format (Recommended)

When requesting a diagram, provide:
- Diagram title
- Lanes/phases
- Blocks per lane
- Connections
- Color intent (optional)
- Orientation: `LR` or `TD`

## Output Contract

- Return a single complete SVG file.
- Include grouped layers and named block/arrow groups.
- Include a small legend/note block if requested.

## Adoption Pattern for Teams
- Keep this as the canonical source for PPT-compatible SVG standards.
- Require checklist pass before publishing SVG to stakeholders.
- Version templates and examples as patterns evolve.
