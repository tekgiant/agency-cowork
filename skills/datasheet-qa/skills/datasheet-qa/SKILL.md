---
name: datasheet-qa
description: |
  Use this skill when the user asks to "ingest a datasheet", "add a spec to the knowledge base",
  "what does the datasheet say about X", "look up pinout", "find timing parameters",
  "check power specs", or wants to ask natural language questions about component datasheets,
  SoC specifications, or hardware reference documents. Converts PDF/Word/Excel datasheets to
  searchable markdown, indexes them in QMD, and answers questions with citations.
---

# Datasheet Q&A

Ingest hardware datasheets and specifications into the knowledgebase, then answer natural language questions about them with citations. Designed for electrical engineers who spend hours digging through 200-page PDFs for a single timing parameter.

## Overview

EE teams regularly reference datasheets for ICs, SoCs, memory modules, power regulators, connectors, and board-level components. This skill:

1. **Ingests** — Converts PDF/Word/Excel datasheets to clean markdown via the `markitdown` skill
2. **Indexes** — Stores in the organized knowledgebase (`memory/Knowledgebase/Specifications/`) and indexes via QMD
3. **Answers** — Responds to natural language questions with citations to specific sections

## Workflow

### Ingest a Datasheet

1. **Receive the file** — User provides a local file path, SharePoint link, or email attachment
2. **Convert to markdown:**
   ```
   → Invoke the markitdown skill to convert PDF/Word/Excel → .md
   ```
3. **Classify and store** — Place in the appropriate Knowledgebase subfolder:
   - `memory/Knowledgebase/Specifications/SoC/` — SoC and ASIC datasheets
   - `memory/Knowledgebase/Specifications/System/` — Board, rack, power delivery specs
   - `memory/Knowledgebase/Specifications/Components/` — ICs, memory, connectors, passives
   - `memory/Knowledgebase/Specifications/Firmware/` — Firmware interface specs
4. **Add metadata header** to the markdown file:
   ```markdown
   ---
   type: datasheet
   part_number: <part number>
   manufacturer: <manufacturer>
   revision: <revision>
   ingested: <YYYY-MM-DD>
   source: <original filename or URL>
   ---
   ```
5. **Re-index QMD:**
   ```powershell
   qmd update
   python skills/qmd-memory/scripts/azure-embed.py --collection knowledgebase
   ```
6. **Confirm** — Report the file path, page count, and key sections detected

### Query a Datasheet

1. **Search QMD** for relevant content:
   - Keyword search: `qmd_search` for exact part numbers, signal names, register addresses
   - Semantic search: `hybrid-search.py` for conceptual queries ("what is the maximum junction temperature")
2. **Retrieve** the matching document sections via `qmd_get`
3. **Answer** with citations: include the source file path and section heading
4. **Cross-reference** — If multiple datasheets are indexed, compare specs across parts

### Example Queries

| User asks | Skill does |
|-----------|-----------|
| "Ingest this DDR5 datasheet" | Convert PDF → markdown, store in Specifications/Components/, index |
| "What's the max clock frequency for the SerDes?" | Search QMD → find timing parameters → cite source |
| "Compare power consumption of DDR5 vs DDR4" | Search both datasheets → extract power tables → present comparison |
| "What are the I2C register addresses for the VRM?" | Keyword search for register map → return addresses with descriptions |
| "Show me the pinout for connector J12" | Search for pinout table → render as HTML table via visual-explainer |
| "What thermal limits should I design to?" | Search for thermal specs → extract Tj_max, θ_JA, power dissipation |

## Rendering

For queries that return tabular data (pinouts, register maps, timing parameters, power tables), automatically render as a styled HTML table using the visual-explainer skill. Threshold: 4+ rows or 3+ columns → HTML page.

## Rules

- **ALWAYS** add the metadata header when ingesting a new datasheet
- **ALWAYS** cite the source file and section when answering questions
- **ALWAYS** re-index QMD after ingesting new content
- **NEVER** guess at specifications — if the data isn't in the indexed datasheets, say so explicitly
- **NEVER** confuse specs from different parts/revisions — always confirm which datasheet you're citing
- When a datasheet for the same part already exists, check the revision — update if newer, keep both if different revisions are needed
- Large datasheets (500+ pages) may need to be split into logical sections for better search recall
