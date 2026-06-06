# markitdown

Convert documents (PDF, Word, Excel, PowerPoint, and more) to Markdown files for the Knowledgebase using Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) tool.

## Prerequisites

- **Python 3.10+** installed
- **pip** package manager

## Installation

### 1. Register the skill

Add this skill's path to the `skill_directories` array in `~/.copilot/config.json`:

```json
"C:\\Projects\\Agency-Cowork\\skills\\markitdown"
```

Restart your Copilot session for the skill to appear in `/skills`.

### 2. Install MarkItDown

Install with all optional dependencies (recommended):

```bash
pip install 'markitdown[all]'
```

Or install only the converters you need:

```bash
# Individual format support
pip install 'markitdown[pdf]'       # PDF files
pip install 'markitdown[docx]'      # Word documents
pip install 'markitdown[pptx]'      # PowerPoint presentations
pip install 'markitdown[xlsx]'      # Excel spreadsheets
pip install 'markitdown[xls]'       # Older Excel files (.xls)
pip install 'markitdown[outlook]'   # Outlook messages
pip install 'markitdown[pdf, docx, pptx, xlsx]'  # Multiple formats
```

### 3. Verify installation

```bash
markitdown --help
```

## Usage

Use the `/markitdown` skill when you want to convert a document to Markdown:

```
/markitdown
```

The agent will ask for:
- **Input file** path (required)
- **Output location** (optional — defaults to `Knowledgebase/`)

### Examples

```
Convert the quarterly report PDF to markdown for the knowledgebase
```

```
Add the project specs document to the knowledgebase
```

```
Convert all the PowerPoint slides in the docs folder to markdown
```

### Direct CLI Usage

You can also use `markitdown` directly from the command line:

```bash
# Convert a single file
markitdown report.pdf -o Knowledgebase/report.md

# Pipe content
cat document.docx | markitdown > output.md

# Convert and print to stdout
markitdown presentation.pptx
```

## Supported Formats

| Format | Extensions | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Text extraction with structure preservation |
| Word | `.docx` | Headings, lists, tables, links |
| PowerPoint | `.pptx` | Slide content and speaker notes |
| Excel | `.xlsx`, `.xls` | Tables and cell data |
| HTML | `.html`, `.htm` | Converted with structure intact |
| Images | `.jpg`, `.png` | EXIF metadata and OCR |
| Audio | `.wav`, `.mp3` | EXIF metadata and transcription |
| Text | `.csv`, `.json`, `.xml` | Structured text formats |
| Archives | `.zip` | Iterates over contents |
| Video | YouTube URLs | Fetches transcript |
| Books | `.epub` | Chapter and content extraction |

## Troubleshooting

### markitdown not found

```
pip install 'markitdown[all]'
```

If using a virtual environment, make sure it's activated before installing.

### Conversion produces empty output

Some PDFs are image-based (scanned documents). Try using Azure Document Intelligence for better results:

```bash
markitdown document.pdf -o output.md -d -e "<your_azure_doc_intel_endpoint>"
```

### Permission errors

Ensure you have read access to the input file and write access to the output directory.
