---
name: markitdown
description: This skill should be used when the user asks to "convert a document to markdown", "add a file to the knowledgebase", "convert PDF/Word/Excel/PowerPoint to markdown", or wants to convert any supported document format into a .md file for the Knowledgebase. Supports PDF, Word, Excel, PowerPoint, HTML, images, audio, CSV, JSON, XML, ZIP, YouTube URLs, and EPubs.
---

Convert documents to Markdown files using Microsoft MarkItDown, storing results in the organized Knowledgebase.

## Overview

This skill converts documents (PDF, Word, Excel, PowerPoint, HTML, images, and more) into clean Markdown files using the `markitdown` CLI tool. Converted files are stored in the `memory/Knowledgebase/` directory structure, organized by category, so they can be used as reference material by the agent.

## Knowledgebase Structure

Always place converted files into the appropriate category folder:

```
memory/Knowledgebase/
├── Program/                    # Program context, strategy, roadmaps, org docs
├── ExecutiveReviews/           # Monthly exec reviews, notes, readouts
├── ProgramExecutionCouncil/    # Weekly PEC reviews, action items, minutes
├── Workstreams/                # Organized by workstream subfolder
│   ├── <workstream-name>/      # One folder per workstream
│   └── ...
└── Specifications/             # Technical specifications
    ├── SoC/                    # Hardware / component specs
    ├── System/                 # System / integration specs
    ├── Software/               # Software specs
    └── Firmware/               # Firmware / platform specs
```

### Category Selection Guide

When the user doesn't specify a category, determine the best fit:

| Content Type | Target Folder |
|-------------|--------------|
| Program strategy, roadmap, org charts, milestones | `Program/` |
| Monthly executive reviews, exec readouts | `ExecutiveReviews/` |
| Weekly PEC reviews, council minutes, action items | `ProgramExecutionCouncil/` |
| Workstream-specific notes, status, deliverables | `Workstreams/<workstream-name>/` |
| SoC specifications, hardware design docs | `Specifications/SoC/` |
| Hardware/system specs, integration docs | `Specifications/System/` |
| Software specs, SW architecture | `Specifications/Software/` |
| Firmware specs, FW architecture, boot flow | `Specifications/Firmware/` |
| General reference that doesn't fit above | `memory/Knowledgebase/` (root) |

If the content clearly belongs to a workstream but no subfolder exists yet, create it using kebab-case (e.g., `Workstreams/power-management/`).

## Supported Formats

- PDF (.pdf)
- Word (.docx)
- PowerPoint (.pptx)
- Excel (.xlsx, .xls)
- HTML (.html, .htm)
- Images (.jpg, .png — EXIF metadata and OCR)
- Audio (.wav, .mp3 — EXIF metadata and speech transcription)
- Text-based formats (.csv, .json, .xml)
- ZIP files (iterates over contents)
- YouTube URLs
- EPubs (.epub)

## Workflow

### Step 1: Identify the Input and Category

Determine the source file or URL to convert. Ask the user if not provided:
- **Input file path or URL** (required)
- **Knowledgebase category** (ask if not obvious from context — see Category Selection Guide)
- **Output filename** (optional — defaults to original filename with `.md` extension)

### Step 2: Verify markitdown is Installed

Check that `markitdown` is available by running:

```bash
markitdown --help
```

If not installed, inform the user and provide the installation command:

```bash
pip install 'markitdown[all]'
```

### Step 3: Convert the Document

Run the conversion script:

```bash
powershell.exe -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/convert-to-md.ps1" -InputFile "<input_path>" -OutputFile "<output_path>"
```

Or use markitdown directly for simple conversions:

```bash
markitdown "<input_path>" -o "<output_path>"
```

**Example paths by category:**

```bash
# Executive review
markitdown "Feb2026-ExecReview.pptx" -o "memory/Knowledgebase/ExecutiveReviews/feb-2026-exec-review.md"

# SoC specification
markitdown "NPU-Architecture-v2.pdf" -o "memory/Knowledgebase/Specifications/SoC/npu-architecture-v2.md"

# Workstream notes
markitdown "PowerMgmt-Status.docx" -o "memory/Knowledgebase/Workstreams/power-management/status-update.md"

# PEC weekly
markitdown "PEC-Week9.pptx" -o "memory/Knowledgebase/ProgramExecutionCouncil/pec-week-9.md"
```

### Step 4: Verify and Report

After conversion:
1. Confirm the output file was created and report the category it was placed in
2. Show the user a brief preview of the converted content (first ~20 lines)
3. Report the output file path and size

If the user wants to review or edit the converted markdown, offer to open or display it.

## Rules

- Always confirm the input file exists before attempting conversion
- Default output location is the appropriate `memory/Knowledgebase/<category>/` subfolder
- Ask the user which category to use if it's ambiguous — do not guess
- Use kebab-case for output filenames (e.g., `exec-review-feb-2026.md`)
- Create workstream subfolders automatically when needed (kebab-case naming)
- Preserve meaningful names — don't use generic names like `document.md`
- If a file with the same name already exists in the output location, ask the user before overwriting
- For batch conversions (multiple files), convert each file individually and report progress
- Do not delete the original source file after conversion
- If markitdown is not installed, provide clear installation instructions rather than failing silently
