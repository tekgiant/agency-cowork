---
name: powerpoint
description: |
  Use this skill when the user asks to "create a PowerPoint", "make a deck", "build a presentation",
  "edit slides", "update this pptx", "redesign this deck", "modify a presentation", "add slides",
  "create a pptx for my meeting", or wants any PowerPoint creation, editing, inspection, or redesign.
  Also triggers on "make me a slide deck about...", "I need a presentation for...", "convert this to slides".
---

# PowerPoint Skill

Two engines, one skill. Pick the right tool for the job:

| Task | Engine | Why |
|------|--------|-----|
| **Create new deck** | pptxGenJS (Node.js) | Rich visuals, charts, icons, design themes, full layout control |
| **Edit existing deck** | python-pptx | Preserves formatting, supports batch edits, handles DRM |
| **Redesign existing deck** | pptxGenJS | Extract content with markitdown → rebuild as new versioned file |

Branding defaults are configured in `agentconfig.json` under `office.powerpoint` and `office.branding`.

---

# Part 1: Creating New Presentations (pptxGenJS)

## Core Philosophy

**pptxGenJS cannot edit files — and that's fine.** Every creation operation produces a new file. When the user wants to redesign an existing deck, extract its content, apply the changes, and write a new versioned file.

| Task | Approach |
|------|----------|
| Create new deck | Write pptxGenJS script → run → output |
| Redesign existing deck | Extract content → full rebuild with new design → output as `_v2` |

### Step 1: Understand the Request

- **New deck**: Go straight to Step 3.
- **Existing deck provided for redesign**: Go to Step 2 first.

### Step 2: Extract Existing Content (redesigns only)

```bash
pip install "markitdown[pptx]" -q
python -m markitdown /path/to/input.pptx
```

Review the extracted markdown to understand content and slide structure.

**Version naming rule:**
- `deck.pptx` → output as `deck_v2.pptx`
- `deck_v2.pptx` → output as `deck_v3.pptx`
- `deck_v2_final.pptx` → output as `deck_v2_final_v2.pptx`

### Step 3: Write the pptxGenJS Script

#### Setup

```powershell
cd skills/powerpoint
npm install   # installs pptxgenjs, react-icons, sharp from local package.json
```

#### Script structure

```javascript
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';

// --- DESIGN CONSTANTS ---
const COLORS = {
  primary: "1E2761",
  secondary: "CADCFC",
  accent: "FFFFFF",
  dark: "111827",
  light: "F9FAFB",
  muted: "6B7280",
};
const FONTS = { heading: "Georgia", body: "Calibri" };

// --- SLIDES ---
// ... build slides here

pres.writeFile({ fileName: "../../output/output_name.pptx" });
```

Save script to the skill directory as `build_presentation.js`, run with:

```powershell
cd skills/powerpoint
node build_presentation.js
```

### pptxGenJS API Quick Reference

#### Layout Dimensions

| Layout | Width | Height |
|--------|-------|--------|
| `LAYOUT_16x9` | 10" | 5.625" |
| `LAYOUT_16x10` | 10" | 6.25" |
| `LAYOUT_4x3` | 10" | 7.5" |
| `LAYOUT_WIDE` | 13.3" | 7.5" |

#### Text

```javascript
// Basic text
slide.addText("Hello", {
  x: 0.5, y: 0.5, w: 8, h: 1,
  fontSize: 24, fontFace: "Arial", color: "363636",
  bold: true, align: "center", valign: "middle"
});

// Rich text array (use breakLine: true between lines)
slide.addText([
  { text: "Bold line", options: { bold: true, breakLine: true } },
  { text: "Normal line", options: { breakLine: true } },
  { text: "Last line" }
], { x: 0.5, y: 0.5, w: 8, h: 2 });

// Bullets (NEVER use unicode "•" — use bullet: true)
slide.addText([
  { text: "First item", options: { bullet: true, breakLine: true } },
  { text: "Second item", options: { bullet: true, breakLine: true } },
  { text: "Sub-item", options: { bullet: true, indentLevel: 1 } }
], { x: 0.5, y: 1, w: 8, h: 3 });
```

#### Shapes

```javascript
slide.addShape(pres.shapes.RECTANGLE, {
  x: 1, y: 1, w: 3, h: 2,
  fill: { color: "FF0000" },
  line: { color: "000000", width: 2 }
});

slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 1, y: 1, w: 3, h: 2,
  fill: { color: "FFFFFF" }, rectRadius: 0.1
});

// Shadow (NEVER use negative offset — corrupts file)
slide.addShape(pres.shapes.RECTANGLE, {
  x: 1, y: 1, w: 3, h: 2,
  fill: { color: "FFFFFF" },
  shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 135, opacity: 0.15 }
});

// Available: RECTANGLE, OVAL, LINE, ROUNDED_RECTANGLE
```

#### Images

```javascript
// From file
slide.addImage({ path: "image.png", x: 1, y: 1, w: 5, h: 3 });

// From base64
slide.addImage({ data: "image/png;base64,iVBOR...", x: 1, y: 1, w: 0.5, h: 0.5 });

// Sizing modes: contain, cover, crop
slide.addImage({ path: "img.png", x: 1, y: 1, w: 5, h: 3,
  sizing: { type: "contain", w: 5, h: 3 } });
```

#### Icons (via react-icons)

```javascript
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const { FaCheckCircle } = require("react-icons/fa");

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

const iconData = await iconToBase64Png(FaCheckCircle, "#4472C4", 256);
slide.addImage({ data: iconData, x: 1, y: 1, w: 0.5, h: 0.5 });
```

#### Charts

```javascript
slide.addChart(pres.charts.BAR, [{
  name: "Sales", labels: ["Q1", "Q2", "Q3"], values: [4500, 5500, 6200]
}], { x: 0.5, y: 1, w: 9, h: 4, barDir: "col", showValue: true });

// Available: BAR, LINE, PIE, DOUGHNUT, SCATTER, BUBBLE, RADAR
```

#### Tables

```javascript
slide.addTable([
  [{ text: "Header", options: { fill: { color: "0078D4" }, color: "FFFFFF", bold: true } }, "Col 2"],
  ["Row 1", "Data"]
], { x: 0.5, y: 1.5, w: 9, colW: [4, 5], border: { pt: 1, color: "CCCCCC" } });
```

#### Slide Backgrounds

```javascript
slide.background = { color: "F1F1F1" };                       // Solid color
slide.background = { path: "https://example.com/bg.jpg" };    // Image
```

### DESIGN.md Integration

If `DESIGN.md` exists at the project root, use it as the primary source for colors and fonts when creating new decks:

**For pptxGenJS (new decks):**
- Read `DESIGN.md` → Color Palette table and Typography Rules
- Map palette to the `COLORS` constant: Primary → `primary`, Accent → `secondary`/`accent`, Dark → `dark`, Background → `light`, Muted → `muted`
- Map fonts to the `FONTS` constant: Heading font → `heading`, Body font → `body`
- Strip `#` prefix from hex values (pptxGenJS requires bare hex like `"0078D4"`)

**For python-pptx (edits):**
- Benefits automatically from the agentconfig.json sync performed by the design-system skill — no changes needed. The `office_common/config.py` → `load_config()` reads `office.branding` values that are kept in sync with DESIGN.md.

**Fallback:** If `DESIGN.md` does not exist, use the 6 hardcoded color themes below and agentconfig.json branding as before.

### Step 4: Design Guidelines

**Don't build boring slides.** Every slide needs a visual element — shape, icon, chart, or image.

#### Pick a bold color palette upfront

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` | `CADCFC` | `FFFFFF` |
| **Coral Energy** | `F96167` | `F9E795` | `2F3C7E` |
| **Warm Terracotta** | `B85042` | `E7E8D1` | `A7BEAE` |
| **Ocean Gradient** | `065A82` | `1C7293` | `21295C` |
| **Charcoal Minimal** | `36454F` | `F2F2F2` | `212121` |
| **Teal Trust** | `028090` | `00A896` | `02C39A` |

#### Layout variety (vary across slides)
- Two-column: text left, visual right
- Icon rows: icon in colored circle + bold header + description
- 2×2 or 2×3 grid cards
- Half-bleed image with content overlay
- Large stat callouts (60–72pt number, small label below)

#### Typography

| Element | Size |
|---------|------|
| Slide title | 36–44pt bold |
| Section header | 20–24pt bold |
| Body text | 14–16pt |
| Captions | 10–12pt muted |

Font pairings: Georgia + Calibri, Arial Black + Arial, Cambria + Calibri

#### Hard rules
- NEVER `#` prefix on hex colors — corrupts the file
- NEVER 8-char hex colors for opacity — use `opacity` property instead
- NEVER unicode bullets — use `bullet: true`
- NEVER reuse option objects across calls — pptxGenJS mutates them
- NEVER accent underlines on titles — hallmark of AI slop
- Use `margin: 0` on text boxes when aligning with shapes
- Use `makeShadow = () => ({...})` factory for reused shadow styles
- Dark/light contrast: dark title/closing slides, light content slides ("sandwich")

### Step 5: QA (Required — Assume There Are Bugs)

Your first render is almost never correct. Don't skip this.

#### Content check

```powershell
pip install "markitdown[pptx]" -q
python -m markitdown output.pptx
```

#### Visual check — convert to PDF and render as images

**Windows (preferred — PowerPoint COM, pixel-perfect):**
```powershell
# 1. Export PPTX → PDF via PowerPoint COM (ppSaveAsPDF = 32)
$pptx = Resolve-Path "output.pptx"
$pdf  = "output.pdf"
$ppt  = New-Object -ComObject PowerPoint.Application
$deck = $ppt.Presentations.Open($pptx.Path, 1, $null, 0)  # ReadOnly, no window
$deck.SaveAs($pdf, 32)
$deck.Close()
$ppt.Quit()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($deck) | Out-Null
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
[GC]::Collect()

# 2. Render PDF pages to PNG via PyMuPDF (pip install PyMuPDF)
python -c "
import fitz
doc = fitz.open('output.pdf')
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=200)
    pix.save(f'slide_{i+1}.png')
    print(f'Slide {i+1}: {pix.width}x{pix.height}')
doc.close()
"
```

**macOS/Linux (fallback — LibreOffice, fonts may differ):**
```bash
libreoffice --headless --convert-to pdf output.pptx
python -c "
import fitz
doc = fitz.open('output.pdf')
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=200)
    pix.save(f'slide_{i+1}.png')
doc.close()
"
```

Look for:
- Overlapping elements or text overflow
- Text cut off at box boundaries
- Low-contrast text or icons
- Uneven spacing or crowded content
- Leftover placeholder text
- Elements too close to slide edges (< 0.5" margin)

#### Fix loop
1. Find issues → fix in script → `node build_presentation.js`
2. Regenerate PDF → re-inspect
3. Repeat until a full pass finds no new issues

**Do not declare success until you've completed at least one fix-and-verify cycle.**

---

# Part 2: Editing Existing Presentations (python-pptx)

Most work involves modifying existing presentations downloaded from SharePoint:

```
1. Download from SharePoint       →  sharepoint skill
2. Check for DRM (OLE2 header?)   →  office_common/drm_handler.ps1 -Action capture
3. Strip DRM if present           →  office_common/drm_handler.ps1 -Action strip
4. Inspect the deck               →  pptx_editor --action inspect
5. Plan edits                     →  agent reasons about what to change
6. Apply edits (batch)            →  pptx_editor --action batch --ops-json '[...]'
7. Re-apply DRM if it was present →  office_common/drm_handler.ps1 -Action apply
8. Upload back                    →  sharepoint skill
```

## DRM-Protected Files

Many Microsoft files use Information Rights Management (IRM), which wraps the PPTX in an OLE2 container. `python-pptx` cannot read these files directly — they must be stripped via COM first.

### Detecting DRM

Check the file header: `D0 CF 11 E0` = OLE2 (likely DRM-wrapped). `50 4B 03 04` = clean ZIP (standard OOXML).

```powershell
$bytes = [System.IO.File]::ReadAllBytes("deck.pptx")
$header = ($bytes[0..3] | ForEach-Object { $_.ToString("X2") }) -join " "
# "D0 CF 11 E0" = DRM-protected, "50 4B 03 04" = clean PPTX
```

### DRM Workflow

```powershell
# DRM handler lives in skills/office_common/ (shared across pptx/xlsx/docx skills)

# 1. Capture the DRM policy (save JSON for later re-application)
$policy = powershell.exe -ExecutionPolicy Bypass -File skills/office_common/drm_handler.ps1 `
    -Action capture -InputFile "output/deck.pptx"

# 2. Strip DRM → clean PPTX that python-pptx can read
powershell.exe -ExecutionPolicy Bypass -File skills/office_common/drm_handler.ps1 `
    -Action strip -InputFile "output/deck.pptx" -OutputFile "output/deck_clean.pptx"

# 3. Edit with python-pptx (inspect, batch, etc.)
python -m skills.powerpoint.scripts.pptx_editor -i "output/deck_clean.pptx" --action inspect
python -m skills.powerpoint.scripts.pptx_editor -i "output/deck_clean.pptx" --action batch --ops-json '[...]'

# 4. Re-apply DRM to the edited file
powershell.exe -ExecutionPolicy Bypass -File skills/office_common/drm_handler.ps1 `
    -Action apply -InputFile "output/deck_clean.pptx" `
    -OutputFile "output/deck_final.pptx" -PolicyJson $policy
```

**CRITICAL: Always re-apply DRM after editing.** If the original file was DRM-protected, the output must be DRM-protected. Never upload an unprotected version of a protected file.

The `drm_handler.ps1` script lives in `skills/office_common/` and supports all Office formats: `-Format pptx`, `-Format xlsx`, `-Format docx` (auto-detected from extension).

### Step 1: Inspect

```powershell
cd skills/powerpoint
python -m scripts.pptx_editor -i "../../output/deck.pptx" --action inspect
python -m scripts.pptx_editor -i "../../output/deck.pptx" --action inspect --slide 3  # single slide detail
```

Returns: slide count, dimensions, and for each slide — layout, all shapes with indices, text content, table data, image metadata, placeholder info, speaker notes.

### Step 2: Edit (Single or Batch)

**Batch edit** (preferred — multiple edits in one call):
```powershell
python -m scripts.pptx_editor -i deck.pptx --action batch --ops-json '[
  {"action": "replace-text", "find": "Q3 2025", "replace": "Q4 2025"},
  {"action": "update-text", "slide": 2, "shape": 1, "text": "New bullet content"},
  {"action": "update-table", "slide": 4, "shape": 0, "row": 1, "col": 2, "text": "Complete"},
  {"action": "update-notes", "slide": 0, "text": "Updated speaker notes"},
  {"action": "delete-slide", "index": 8},
  {"action": "move-slide", "from": 5, "to": 2},
  {"action": "duplicate-slide", "index": 3}
]'
```

**Single-action edits:**
```powershell
python -m scripts.pptx_editor -i deck.pptx --action replace-text --find "OLD" --replace "NEW"
python -m scripts.pptx_editor -i deck.pptx --action update-text --slide 2 --shape 1 --text "New text"
python -m scripts.pptx_editor -i deck.pptx --action update-table --slide 3 --shape 0 --row 1 --col 2 --text "Updated"
python -m scripts.pptx_editor -i deck.pptx --action delete-slide --index 5
python -m scripts.pptx_editor -i deck.pptx --action move-slide --from-index 4 --to-index 1
python -m scripts.pptx_editor -i deck.pptx --action duplicate-slide --index 2
python -m scripts.pptx_editor -i deck.pptx --action update-notes --slide 0 --text "Notes here"
python -m scripts.pptx_editor -i deck.pptx --action extract-text
```

### Batch Actions Reference

| Action | Required Fields | Description |
|--------|----------------|-------------|
| `replace-text` | find, replace, slide? | Find/replace text (optionally scoped to one slide) |
| `update-text` | slide, shape, text, para? | Update text in a specific shape |
| `update-table` | slide, shape, row, col, text | Update a table cell |
| `update-notes` | slide, text | Update speaker notes |
| `delete-slide` | index | Remove a slide |
| `move-slide` | from, to | Reorder a slide |
| `duplicate-slide` | index | Copy a slide (appended at end) |

## Configuration

`agentconfig.json` → `office.powerpoint` and `office.branding` control colors, fonts, slide dimensions, footer text, and template paths.

## Dependencies

**pptxGenJS creation engine** (install once):
```powershell
cd skills/powerpoint
npm install
```

**python-pptx editing engine:**
```powershell
pip install python-pptx
```

**markitdown** (for content extraction and QA):
```powershell
pip install "markitdown[pptx]"
```

**PyMuPDF** (for rendering PDF pages to PNG during visual QA):
```powershell
pip install PyMuPDF
```

## OneDrive Upload

To upload finished presentations to OneDrive, use the sync folder approach (see CLAUDE.md for details):

```bash
bash skills/shared/upload-to-onedrive.sh "output/presentation.pptx" "Agency Cowork Outputs"
```

Do NOT use Graph API, MCP upload tools, or PowerShell for OneDrive uploads.

## Gotchas

These are hard-won failure modes — if you skip this section, you will hit them.

### pptxGenJS Creation

- **`#` prefix on hex colors silently corrupts the .pptx file.** Use bare hex like `"1E2761"`, never `"#1E2761"`. The file will open but render garbled colors or crash older PowerPoint versions.
- **8-char hex codes for opacity (e.g., `"1E276180"`) also corrupt.** Use the `opacity` property instead.
- **Unicode bullet characters (`•`, `▸`) render inconsistently across platforms.** Always use `bullet: true` in text options — never hardcode unicode bullets.
- **pptxGenJS mutates option objects** passed to `addText()`, `addShape()`, etc. If you reuse the same object across multiple calls, later slides inherit corrupted state. Use a factory function: `makeShadow = () => ({...})`.
- **Negative shadow offsets corrupt the file silently.** Always use positive `offset` values.
- **`writeFile()` resolves paths relative to CWD, not the script location.** Always run from `skills/powerpoint/` and use explicit relative paths like `../../output/`.
- **Accent underlines on titles are a hallmark of AI-generated slides.** Avoid them — they signal "a robot made this."

### Content Extraction & Redesign

- **markitdown extraction loses most formatting** — bold, colors, images, and complex layouts are discarded. Only reliable for extracting raw text content and basic slide structure.
- **Table data from markitdown may be mangled** — column alignment and merged cells often break. Always inspect tables manually before rebuilding.

### DRM-Protected Files

- **DRM detection relies on file header bytes**, not file extension. `D0 CF 11 E0` = OLE2 (DRM-wrapped), `50 4B 03 04` = clean OOXML. Attempting to open a DRM file with python-pptx throws a cryptic `PackageNotFoundError`, not a clear "DRM detected" message.
- **Always re-apply DRM after editing.** If you forget, you've just stripped confidentiality protections from a protected document and uploaded it unprotected.
- **DRM handler requires Office COM (Windows only).** On macOS, DRM strip/re-apply is not available — skip those steps and warn the user that the file cannot be edited without a Windows machine.

### QA & Verification

- **On Windows, use PowerPoint COM for PDF export** — pixel-perfect rendering, no font substitution issues. Use `New-Object -ComObject PowerPoint.Application` → `SaveAs($pdf, 32)`. Requires PowerPoint installed (available on this machine as v16.0).
- **Use PyMuPDF (`pip install PyMuPDF`) to render PDF pages to PNG** for visual inspection. `fitz.open(pdf)` → `page.get_pixmap(dpi=200)` → `pix.save(png)`.
- **LibreOffice is a fallback for macOS/Linux** where PowerPoint COM is not available. Font rendering will differ from actual PowerPoint.
- **Your first render is almost never correct.** Don't skip the QA cycle — overlapping elements, cut-off text, and low-contrast issues are the norm, not the exception.
- **Clean up QA artifacts** (PDF, PNG files) after verification is complete.

## Composes With

- **sharepoint** — Download source decks for editing, upload finished presentations
- **markitdown** — Extract content from existing decks for redesign workflows
- **svg-to-ppt** — Create SVG diagrams that convert to editable PowerPoint shapes via Convert to Shape
- **send-email** — Email finished presentations as attachments
- **excel** — Pull data from spreadsheets for chart slides
- **visual-explainer** — Generate HTML diagrams that can inform slide layouts

## Rules

### Creation (pptxGenJS)
- **Use pptxGenJS for all new decks** — superior visuals, charts, icons vs. python-pptx builder
- **Run QA on every deck** — content check + visual check before delivering
- **Version, don't overwrite** — existing files get `_v2`, `_v3` suffixes
- NEVER `#` prefix on hex colors, NEVER unicode bullets, NEVER reuse option objects

### Editing (python-pptx)
- **ALWAYS inspect first** before editing — use shape/slide indices from inspect output
- **ALWAYS capture and re-apply DRM** if the original file is DRM-protected (OLE2 header `D0 CF 11 E0`)
- **NEVER upload an unprotected version** of a DRM-protected file to SharePoint
- **Prefer batch edits** — one `--action batch` call with multiple ops vs. many single calls
- **Preserve formatting** — edit operations update text while keeping fonts, sizes, colors intact
- All indices are 0-based (slides, shapes, paragraphs, rows, cols)
- Output defaults to overwriting input; use `--output` to save to a new file
- DRM handler requires Office COM (PowerPoint/Excel/Word installed locally on Windows)
