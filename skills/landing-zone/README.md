# Landing Zone (LZ) Skill

Query, analyze, and manage Azure DevOps Landing Zone requirements.

See [SPEC.md](SPEC.md) for the full specification and [SKILL.md](skills/landing-zone/SKILL.md) for the agent skill definition.

## Quick Start

```bash
cd skills/landing-zone

# Sync your program's LZ from ADO
python -m scripts.lz_sync --program my-program

# Query ungraded items
python -m scripts.lz_query --program my-program --ungraded

# Health analytics
python -m scripts.lz_analyze --program my-program --report summary

# Week-over-week comparison
python -m scripts.lz_snapshot --program my-program --wow
```

## Prerequisites

- Azure CLI (`az`) logged in
- Python 3.10+
- Access to your ADO org/project (configured in `programs.json`)
- Run `setup.ps1` Phase 5 to configure programs, or create `programs.json` manually (see `programs.json.example`)
