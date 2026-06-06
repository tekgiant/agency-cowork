# SVG-to-PPT Conversion Checklist

## A) Authoring Checks
- [ ] Business logic is captured before styling work starts.
- [ ] Diagram uses a simple flow direction (LR or TD).
- [ ] Colors are minimal and consistent across functional sections.
- [ ] Geometry uses primitive elements (`rect`, `line`, `polygon`, `text`).
- [ ] No `<marker>` references are used.
- [ ] No path-based arrow tips are used.
- [ ] Arrows are grouped atomically (`Arrow_N`: one line + one polygon) OR placed in a single `layer-connectors` group (validator accepts either; atomic preferred).
- [ ] Arrow line endpoints penetrate arrow polygons by ~2–4 px when atomic groups are used.
- [ ] No `<defs>` entries containing external references or markers are present (remove `<marker>` and avoid external fonts/images).
- [ ] All major modules are grouped (`Block_*`, `layer-*`, `Main_Group`).
- [ ] Coordinates are absolute; transforms are minimized.

## B) Text Robustness Checks
- [ ] Text is pre-wrapped into multiple `<text>` lines for long content.
- [ ] Body lines are reasonably short (avoid overlong tokens per line).
- [ ] Heading/body font sizes are proportional to box width (typical: heading 16–20px, body 12–15px on ~1600px canvas).
- [ ] Font stack uses Office-safe defaults (`Aptos, Segoe UI, Arial`).
- [ ] Container width has enough redundancy (target ~1.3x for body blocks).
- [ ] Side and vertical padding are preserved in every text block.
- [ ] Longest 2–3 text blocks are checked for clipping risk.
- [ ] Use absolute `y` positions for `<tspan>` lines inside a single `<text>` element (avoid cumulative `dy` offsets). If you used relative `dy`, convert to absolute `y` values to improve robustness across viewers.
- [ ] Use a minimum `y` gap of ~18px between consecutive `<tspan>` lines to avoid post-conversion overlap in PPT.
- [ ] If overlaps occur after conversion: increase block `height` by ~10–20 px, or reduce font-size by 1–2 pts, then revalidate.
- [ ] Verify longest body lines are <= ~50 characters; if longer, split into multiple tspans.
- [ ] Verify no single inline text run is excessively long (use `MAX_TEXT_CHARS` guardrail in Makefile validation).
- [ ] Confirm per-line vertical spacing ~18–20 px; measure `box_height = (n_lines * line_height) + (2 * padding)` and ensure rectangle `height` meets or exceeds that value.
- [ ] Confirm fonts: headings 13–14, body 11–12; if using larger fonts, increase padding accordingly.

## C) Conversion Checks (VS Code + PPT)
- [ ] Connector lines (vertical or between boxes) do not overlap text: start vertical connectors below the header rect bottom and end them above the top of the destination rect. Verify visually after conversion.
- [ ] Run `make validate-ps` (or `powershell -ExecutionPolicy Bypass -File scripts/validate-svg.ps1`) to enforce line-gap and right-edge fit heuristics before committing.
- [ ] Run `make validate` (or `viztool validate-skill`) and resolve any reported issues before committing or publishing.
- [ ] If you intend to commit diagram changes, ensure your working directory is a git repository and include a short commit message referencing validation (e.g., "docs(svg): add diagram - validation passed").
- [ ] For large or complex diagrams, try removing `<style>` blocks and inline critical styles to reduce renderer load; prefer simple inline `fill`/`stroke` attributes.

## D) Publish/Security Checks
- [ ] Sensitive values are replaced with placeholders (e.g., `[AUTH_TOKEN]`).
- [ ] File naming is clear and versioned when needed.
- [ ] Example source logic is documented for reuse.

## E) Right-edge & Overflow Safeguards
- [ ] Reserve an explicit right margin inside any box: prefer at least 12–16px horizontal padding on the right side to account for font fallback and PPT renderer differences.
- [ ] Enforce a conservative max characters-per-line (recommended 40). If a line exceeds this, split it into multiple `<tspan>` lines.
- [ ] Keep each text segment under the `MAX_TEXT_CHARS` validator threshold (default `90`) unless the containing rectangle is explicitly widened.
- [ ] Use explicit `x` and absolute `y` attributes on every `<tspan>`; do not rely on cumulative `dy` offsets.
- [ ] Add a safety vertical margin to every box's `height`: compute `box_height = (n_lines * line_height) + (2 * padding) + safety_margin` where `safety_margin` = 10–20 px.
- [ ] For blocks near the canvas edge, prefer widening the box or moving the box left instead of shrinking fonts.
