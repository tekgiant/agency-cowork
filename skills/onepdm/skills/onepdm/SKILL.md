---
name: onepdm
description: |
  Search, browse, and download specifications from OnePDM (Aras Innovator PLM).
  Use when the user asks to "download a spec", "search OnePDM", "find specification M1345662",
  "list specs", "check spec freshness", "import SOW exhibits", "update specs", or any
  operation involving OnePDM document retrieval. Triggers: "onepdm", "specification",
  "spec download", "plm", "document number", "M1", "download spec", "list specs",
  "check freshness", "import sow".
---

# OnePDM Skill

Download and manage hardware specifications from [OnePDM](https://onepdm.plm.microsoft.com/onepdm/) — Microsoft's PLM (Product Lifecycle Management) system powered by Aras Innovator.

## Overview

OnePDM stores all MAIA program specifications (design, test, firmware, compliance). This skill provides:

1. **Search** — Find documents by number (M#######) or keyword
2. **Download** — Retrieve the latest file for a specification
3. **Tracking** — Registry of all tracked specs with last-retrieval dates
4. **Freshness** — Detect when OnePDM has newer revisions than local copies
5. **Batch ops** — Import spec lists from SOW/PRD exhibits, bulk download/update

## Authentication

OnePDM uses Azure AD SSO (OpenID Connect). The skill authenticates via Playwright browser automation:

1. First run: Opens Edge with Azure AD login — user signs in once
2. Subsequent runs: Reuses cached cookies (stored in `%LOCALAPPDATA%/AgencyCowork/onepdm-browser/`)
3. If cookies expire: Automatically re-launches browser for SSO

**Test auth:** `python skills/onepdm/scripts/onepdm_cli.py test-auth`

## CLI Commands

```powershell
$cli = "python skills/onepdm/scripts/onepdm_cli.py"

# Search OnePDM
& $cli search "M1345662"
& $cli search "Everglades Platform"

# Show document metadata
& $cli info M1345662

# List file attachments
& $cli list-files M1345662

# Download a spec
& $cli download M1345662
& $cli download M1345662 --dest "C:\temp"

# Import SOW exhibits to tracking registry
& $cli import-sow "memory\Knowledgebase\Specifications\System\maia300-sow-prd-exhibits-a-b.md"

# List tracked specs (numbered, filterable)
& $cli list
& $cli list --filter "thermal"
& $cli list --program maia-300
& $cli list --stale

# Update specs by selection number from list
& $cli update 1,3,5
& $cli update 1-10
& $cli update --stale
& $cli update --all

# Check for newer versions on OnePDM
& $cli check-freshness
```

## Configuration

### Spec Registry (`config/onepdm-specs.json`)
Auto-maintained JSON tracking each specification:
```json
{
  "M1345662": {
    "doc_number": "M1345662",
    "onepdm_id": "F16D88AFE6B840E68F258107C8059703",
    "name": "Everglades Platform Hardware Specification",
    "revision": "A",
    "state": "Released",
    "last_retrieved": "2026-03-14T17:36:00Z",
    "local_path": "memory/Knowledgebase/Specifications/System/M1345662.docx",
    "onepdm_modified": "2026-03-04T14:47:56"
  }
}
```

### Program Config (`config/onepdm-programs.json`)
Program-sensitive data sourced from org repo (`.gitignore`d from public fork):
```json
{
  "programs": {
    "maia-300": {
      "sow_exhibits": ["M1345662", "M1391136", "M1389728"],
      "exhibit_source": "MAIA300 SOW_PRD Exhibits A_B.xlsx"
    }
  }
}
```

## Workflow

### Download a specification
1. User asks: "download spec M1345662"
2. Run: `python skills/onepdm/scripts/onepdm_cli.py download M1345662`
3. Optionally convert to markdown: `markitdown <downloaded_file> -o <dest.md>`
4. Registry auto-updated with retrieval timestamp

### Import and batch download SOW exhibits
1. Run: `python skills/onepdm/scripts/onepdm_cli.py import-sow <exhibits.md>`
2. Run: `python skills/onepdm/scripts/onepdm_cli.py list` — review numbered list
3. Run: `python skills/onepdm/scripts/onepdm_cli.py update --all` — download all
4. Optionally convert each to markdown via markitdown

### Check for updates
1. Run: `python skills/onepdm/scripts/onepdm_cli.py check-freshness`
2. Review stale specs
3. Run: `python skills/onepdm/scripts/onepdm_cli.py update --stale` — refresh only changed specs

## API Architecture

OnePDM is Aras Innovator with:
- **SOAP/XML API** at `s-onepdm.plm.microsoft.com/onepdm/InnovatorServer.aspx`
- **Vault file storage** at `v-onepdm.plm.microsoft.com/onepdm/vaultserver.aspx`
- **Download tokens** via `AuthenticationBroker.asmx/GetFileDownloadToken`

Flow: Search → Get Document → List Files → Get Token → Download from Vault

## Dependencies
- `playwright` (browser SSO authentication)
- `requests` (SOAP API calls)
- `markitdown` (optional, post-download conversion)

## Rules
- **ALWAYS** test auth before first use in a session: `test-auth` command
- **ALWAYS** update the registry after downloads (CLI does this automatically)
- **NEVER** store OnePDM credentials or tokens in source code
- **NEVER** share downloaded specifications outside authorized channels
- After downloading DRM-protected files, use `skills/office_common/drm_handler.ps1 -Action strip` before markitdown conversion
- Program-specific spec lists go in `config/onepdm-programs.json`, not in skill code
