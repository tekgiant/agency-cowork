# CLI Operations Reference

Complete guide for operating CocoIndex flows using the CLI.

## Environment Setup

### Environment Variables

Create a `.env` file in the project directory:

```bash
# Database connection (required)
COCOINDEX_DATABASE_URL=postgresql://user:password@localhost/cocoindex_db

# Optional: App namespace for organizing flows
COCOINDEX_APP_NAMESPACE=dev

# Optional: Global concurrency limits
COCOINDEX_SOURCE_MAX_INFLIGHT_ROWS=50
COCOINDEX_SOURCE_MAX_INFLIGHT_BYTES=524288000  # 500MB

# Optional: LLM — use Ollama (local, no API key needed)
# External LLM API keys (OpenAI, Anthropic, Voyage) are PROHIBITED by security policy (CI-1)
```

### Loading Environment Files

```bash
cocoindex <command> ...                        # Default: loads .env from cwd
cocoindex --env-file path/to/.env <command>    # Custom env file
cocoindex --app-dir /path/to/project <command> # Specify app directory
```

## APP_TARGET Format

```bash
cocoindex update main              # Python module
cocoindex update main.py           # Python file
cocoindex update main:MyFlowName   # Specific flow in module
cocoindex update path/to/flows.py:MyFlowName  # Specific flow in file
```

## Core Commands

### setup - Initialize Flow Resources

```bash
cocoindex setup main.py            # Setup all flows
cocoindex setup main.py:MyFlow     # Setup specific flow
```

Creates internal storage tables, target resources (tables, collections, graphs), updates schemas.

### update - Build/Update Target Data

```bash
cocoindex update main.py           # One-time update
cocoindex update --setup main.py   # Update with auto-setup
cocoindex update main.py:TextEmbedding  # Update specific flow
cocoindex update --reexport main.py     # Force reexport all data
```

### update -L - Live Update Mode

```bash
cocoindex update main.py -L            # Live update
cocoindex update --setup main.py -L    # Live update with auto-setup
cocoindex update --reexport main.py -L # Live update with reexport on initial
```

Requires at least one source with `refresh_interval` or source-specific change capture.

### drop - Remove Flow Resources

```bash
cocoindex drop main.py             # Drop all flows
cocoindex drop main.py:MyFlow      # Drop specific flow
```

**Warning:** Destructive and cannot be undone.

### show - Inspect Flow Definition

```bash
cocoindex show main.py:MyFlow      # Show specific flow
cocoindex show main.py             # Show all flows
```

### evaluate - Test Without Updating

```bash
cocoindex evaluate main.py:MyFlow                          # Evaluate flow
cocoindex evaluate main.py:MyFlow --output-dir ./eval_results  # Custom output dir
cocoindex evaluate main.py:MyFlow --no-cache               # Disable cache
```

## Complete Workflow Examples

### First-Time Setup

```bash
cocoindex setup main.py     # Setup resources
cocoindex update main.py    # Run initial indexing
cocoindex show main.py      # Verify results
```

### Development Workflow

```bash
cocoindex evaluate main.py:MyFlow --output-dir ./test_output  # Test first
cocoindex update --setup main.py:MyFlow                        # Then update
cocoindex show main.py:MyFlow                                  # Check results
```

### Production Live Updates

```bash
cocoindex update --setup main.py -L
```

### Rebuild After Changes

```bash
cocoindex drop main.py              # Drop old resources
cocoindex setup main.py             # Setup with new definition
cocoindex update --reexport main.py # Reindex everything
```

## Common Issues

| Issue | Solution |
|-------|----------|
| "Flow not found" | Check APP_TARGET format; use `--app-dir` |
| "Database connection failed" | Check `.env` has `COCOINDEX_DATABASE_URL` |
| "Schema mismatch" | Re-run `cocoindex setup main.py` |
| "Live update exits" | Add `refresh_interval` to source |

## Global Options

```bash
cocoindex --version                # Show version
cocoindex --help                   # Show help
cocoindex --app-dir /custom/path update main  # Custom app directory
cocoindex --env-file prod.env update main     # Custom env file
```
