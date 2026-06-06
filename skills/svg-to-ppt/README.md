# SVG-to-PPT Skill Pack

Create SVG diagrams that convert cleanly into editable PowerPoint shapes using **Convert to Shape**.

This README is the quick entry point for the `svg-to-ppt` workflow. For full standards and detailed rules, use the linked files below.

---

## Start Here

1. Define the diagram logic first (lanes/phases, blocks, connections).
2. Author using PPT-safe SVG primitives.
3. Validate structure and conversion-readiness.
4. Insert into PowerPoint and run **Convert to Shape**.

---

## Core Files

- [`SKILL.md`](./skills/svg-to-ppt/SKILL.md) — complete workflow, constraints, and team adoption guidance (includes agent generation prompt).
- [`CHECKLIST.md`](./CHECKLIST.md) — preflight checks before conversion and publishing.

Supporting assets:
- [`templates/ppt_shape_starter.svg`](./templates/ppt_shape_starter.svg) — starter scaffold.
- [`examples/api_profile_filtering_flow.svg`](./examples/api_profile_filtering_flow.svg) — generic API investigation reference example.

---

## Non-Negotiable Rules (Summary)

- Use primitive geometry: `rect`, `line`, `polygon`, `text`.
- Avoid `<marker>`, path-based arrowheads, and external dependencies.
- Keep arrows simple and grouped (`Arrow_N`), with one `line` + one `polygon` when possible.
- Prefer absolute coordinates and minimal transforms.
- Use Office-safe fonts: `Aptos`, `Segoe UI`, `Arial`.
- Pre-wrap multiline text and use explicit `x`/`y` positioning for stable conversion.

For the full authoritative rule set, see [`SKILL.md`](./skills/svg-to-ppt/SKILL.md).

---

## Recommended Authoring Flow

1. Start from [`templates/ppt_shape_starter.svg`](./templates/ppt_shape_starter.svg).
2. Add blocks and labels with conservative line lengths.
3. Add connectors/arrows after layout is stable.
4. Run checklist validation using [`CHECKLIST.md`](./CHECKLIST.md).
5. Validate locally:
   - `make validate` (full local skill validation)
   - `powershell -ExecutionPolicy Bypass -File scripts/validate-svg.ps1` (Windows-friendly validation)
   - `make validate-svg SVG=templates/ppt_shape_starter.svg` (single SVG)
6. Test in PowerPoint with **Convert to Shape** and inspect text/arrow behavior.

### Makefile Commands

- `make help` — list available validation targets.
- `make validate` — run required file checks + SVG safety checks.
- `make validate-ps` — run the PowerShell validator from Make.
- `make check-files` — ensure `SKILL.md`, `CHECKLIST.md`, `README.md`, and bundled SVGs exist.
- `make check-svg-safety` — validate bundled SVG files against safety rules.
- `make validate-svg SVG=path/to/file.svg` — validate one SVG file.
- `MAX_FONT_SIZE=28` / `MAX_TEXT_CHARS=90` — guardrails used by validators to catch likely overflow risks.
- `STRICT_TEXT_FIT=1` — default strict mode; long text and fit violations fail validation.
- `MIN_LINE_GAP=18` — enforces minimum `tspan` line spacing to reduce post-conversion overlap.

On Windows, run Make targets from Git Bash/WSL, or use the PowerShell validator directly.

---

## Common Conversion Pitfalls

- Overlapping text from cumulative `dy` usage.
- Right-edge clipping due to tight block width/padding.
- Arrowheads detached from connector lines.
- Hidden complexity from markers/defs unsupported by PPT.
- Overhanging text from oversized font choices relative to box width.

Mitigations are documented in [`CHECKLIST.md`](./CHECKLIST.md) and [`SKILL.md`](./skills/svg-to-ppt/SKILL.md).

Practical default for this skill: keep headings near `16–20px`, body text near `12–15px`, and split long lines before conversion.

---

## When to Use This Skill

Use this pack when the output must be editable in PowerPoint after SVG import and conversion.

If you only need visual rendering (not PPT editability), standard Mermaid/HTML rendering may be sufficient.
