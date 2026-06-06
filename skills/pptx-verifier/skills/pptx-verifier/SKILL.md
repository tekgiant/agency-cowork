---
name: pptx-verifier
description: |
  Use this skill after creating or editing a PowerPoint presentation to verify output quality before
  delivering to the user. Triggers on: "verify this deck", "check my presentation", "QA this pptx",
  or automatically after any powerpoint skill run. Also use when the user says "does this deck look right",
  "check for issues", or "validate the slides".
---

# PowerPoint Verifier Skill

Automated quality verification for generated or edited PowerPoint files. Run this after every deck creation or edit to catch issues before delivery.

## When to Use

- **Always** after the `powerpoint` skill creates or edits a deck
- When the user asks to verify, check, or QA a presentation
- Before uploading a deck to SharePoint or emailing it

## Verification Pipeline

### Step 1: Structural Verification

Run the verification script to check for common issues:

```bash
cd skills/pptx-verifier
python3 scripts/verify_pptx.py "../../output/<filename>.pptx"
```

The script checks:
- **Slide count** — matches the requested number of slides
- **Empty text placeholders** — shapes with no text content (likely forgotten placeholders)
- **Minimum content** — each slide has at least one text element
- **File integrity** — valid OOXML ZIP structure

### Step 2: Content Verification

Extract content and review for completeness:

```bash
pip install "markitdown[pptx]" -q
python -m markitdown "../../output/<filename>.pptx"
```

Check for:
- All requested topics/sections are present
- No placeholder text left behind ("Lorem ipsum", "Title here", "[INSERT]")
- Bullet points are substantive, not one-word stubs
- Data/metrics match what was provided or pulled from sources
- Speaker notes are present if requested

### Step 3: Visual Verification

Convert to images and inspect visually:

```bash
# macOS
libreoffice --headless --convert-to pdf "../../output/<filename>.pptx" --outdir /tmp/
pdftoppm -jpeg -r 150 "/tmp/<filename>.pdf" "/tmp/slide"
ls -1 /tmp/slide-*.jpg
```

Then read each slide image and check for:
- **Overlapping elements** — text boxes or shapes stacked on each other
- **Text overflow** — content cut off at shape boundaries
- **Low contrast** — light text on light backgrounds or dark on dark
- **Uneven spacing** — inconsistent margins or crowded content
- **Edge violations** — elements within 0.3" of slide edges
- **Font consistency** — mixed fonts that weren't intentional

### Step 4: Report

Present findings to the user as a checklist:

```
## Deck Verification: <filename>.pptx

### Structural
- [x] Slide count: 5 (matches request)
- [x] No empty placeholders found
- [x] File integrity: valid OOXML
- [ ] ⚠ Slide 3: text box has no content

### Content
- [x] All 5 requested topics covered
- [x] No placeholder text found
- [ ] ⚠ Slide 4: metric "1.5x improvement" not found in source data

### Visual
- [x] No overlapping elements
- [ ] ⚠ Slide 2: title text appears cut off at right edge
- [x] Contrast ratios acceptable

### Actions Needed
1. Add content to empty text box on slide 3
2. Verify "1.5x improvement" metric source
3. Extend title text box width on slide 2
```

## Gotchas

- **LibreOffice renders fonts differently than PowerPoint** — visual check catches layout issues but font rendering won't match exactly. For pixel-perfect verification, the user must open in actual PowerPoint.
- **markitdown loses formatting** — it can tell you WHAT text is on each slide but not HOW it looks (no color, size, or position info). Always do the visual check too.
- **DRM-wrapped files can't be verified** — if the file has an OLE2 header (`D0 CF 11 E0`), it must be stripped before verification. Re-apply DRM after.
- **pptxGenJS corruption from bad hex colors is silent** — the file opens but renders incorrectly. The structural check catches invalid OOXML but not all color corruption.

## Composes With

- **powerpoint** — This skill runs after powerpoint creates or edits a deck
- **sharepoint** — Verify before uploading to SharePoint
- **send-email** — Verify before emailing as attachment

## Rules

- Never skip verification after creating a deck — the first render is almost never correct
- Present findings as a checklist, not a wall of text
- If critical issues are found, fix them and re-verify — don't deliver a deck with known problems
- Visual verification requires LibreOffice installed — if not available, note in the report that visual check was skipped
