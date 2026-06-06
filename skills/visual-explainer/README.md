# Visual Explainer Plugin

Generate beautiful, self-contained HTML pages that visually explain systems, code changes, plans, and data. Replaces ASCII tables and text-based diagrams with browser-rendered visualizations.

## Features

- **Web diagrams** — Architecture overviews, flowcharts, system diagrams using Mermaid.js
- **Diff reviews** — Visual code change analysis with architecture comparison
- **Plan reviews** — Compare implementation plans against codebase with risk assessment
- **Slide decks** — Magazine-quality HTML slide presentations
- **Project recaps** — Mental model snapshots for context-switching
- **Data tables** — Styled, sortable HTML tables (auto-triggered for 4+ rows or 3+ columns)

## Usage

Invoke when the user asks for a diagram, architecture overview, diff review, plan review, comparison table, or any visual explanation of technical concepts.

Triggers: `diagram`, `visual`, `architecture overview`, `diff review`, `plan review`, `comparison table`, `visual explanation`.

## Output

All outputs are self-contained HTML files saved to the `output/` directory and automatically opened in the default browser. No external dependencies required at runtime.

## Design System

If a `DESIGN.md` file exists in the project root, visual-explainer applies its design tokens (colors, fonts, spacing) for branded output. Otherwise, built-in presets are used.

## License

MIT — see [visual-explainer](https://github.com/nicobailon/visual-explainer)
