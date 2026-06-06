# Code Review Guidelines

Standards and checks for all contributions to Agency Cowork. Reviewers and CI should enforce these before merge.

---

## 1. PowerShell Scripts (.ps1)

### Encoding & Portability

| Rule | Rationale |
|------|-----------|
| **No Unicode em-dashes (U+2014), en-dashes (U+2013), or smart quotes (U+201C-201D)** in string literals or comments | Windows PowerShell 5.1 reads UTF-8-without-BOM as ANSI, corrupting multi-byte codepoints and causing parse failures (see Issue #19) |
| **UTF-8 with BOM** required for any `.ps1` file containing non-ASCII characters (e.g., `✓`, `⚠`, `→`, box-drawing) | PowerShell 5.1 only recognizes UTF-8 when BOM is present |
| **ASCII-only preferred** in executable code paths; restrict non-ASCII to `Write-Host` display strings | Minimizes encoding-related breakage across locales |
| All `.ps1` files must **parse cleanly** under both `pwsh` (7.x) and `powershell` (5.1) | CI test `CQ-02` validates this automatically |

### Error Handling & Privileges

| Rule | Rationale |
|------|-----------|
| Scripts requiring elevated privileges must **check at startup** and exit with a clear message | `Set-Acl`, registry writes, and service management fail silently or cryptically without admin |
| Use `$ErrorActionPreference = "Stop"` at script top | Fail-fast prevents cascading silent failures |
| Use `try/catch` around external tool invocations (`az`, `git`, `qmd`) | External tools return non-terminating errors that `$ErrorActionPreference` doesn't catch |
| Never use bare `throw` or `raise` inside `asyncio.create_task()` coroutines | Exception kills the task silently — use retry-with-backoff pattern instead |

### Style

| Rule | Rationale |
|------|-----------|
| Use full cmdlet names in scripts (`Get-ChildItem` not `ls`, `ForEach-Object` not `%`) | Readability, cross-platform compatibility |
| Prefer named parameters over positional | Clarity and maintainability |
| Named constants over magic numbers (`$_MAX_REFRESH_BUFFER_SECONDS` not `300.0`) | Self-documenting, single point of change |

---

## 2. Python Scripts (.py)

### Encoding & Imports

| Rule | Rationale |
|------|-----------|
| UTF-8 source files (Python 3 default — no action needed) | Universal compatibility |
| Do not use `import *`; use explicit imports | Namespace clarity, IDE support |
| Group imports: stdlib, third-party, local — separated by blank lines | PEP 8 |

### Security

| Rule | Rationale |
|------|-----------|
| Never log or print tokens, secrets, or credentials | Credentials in logs are a persistent exfiltration vector |
| JWT parsing must **not** verify signatures unless specifically required | Agent tokens are for expiry inspection, not trust validation — use `options={"verify_signature": False}` |
| Scan external content with `prompt_guard.py` before using in tool calls | Prompt injection defense (see AGENTS.md § Security) |

### Async Code

| Rule | Rationale |
|------|-----------|
| Never use bare `raise` inside `asyncio.create_task()` coroutines | Exception kills the task silently; parent never sees it |
| Use retry-with-backoff for recoverable failures in long-running tasks | Graceful degradation over hard crash |
| Log errors before re-raising or retrying | Observability — silent failures are undebuggable |

---

## 3. SKILL.md Files

| Rule | Rationale |
|------|-----------|
| Must start with `---` YAML frontmatter (not wrapped in code fences) | Copilot / Claude skill loader requires raw YAML at line 1 |
| Required frontmatter fields: `name`, `description` | Skill registry and discovery |
| `name` in frontmatter must match `name` in `plugin.json` | Consistency across registration systems |
| Keep the Workflow section ordered and numbered | Agent follows steps sequentially |
| Decision tables must have clear, mutually exclusive conditions | Prevents agent ambiguity on which tool to use |

---

## 4. Markdown & Documentation

| Rule | Rationale |
|------|-----------|
| Use ASCII hyphens (`-`), not em-dashes (`—`) in all `.md` files referenced by scripts | Prevents encoding issues when scripts read markdown |
| Internal links must resolve to existing files | CI test `DOC-12` validates this |
| No domain-specific references in public-facing docs | Sanitization — CI tests `SAN-01` through `SAN-05` validate this |
| Tables must use consistent column counts across all rows | Markdown renderers silently drop malformed rows |

---

## 5. Security & Secrets

| Rule | Rationale |
|------|-----------|
| No API keys, tokens, passwords, or PEM keys in tracked files | Pre-commit hook blocks these patterns (SEC-01 through SEC-06) |
| `.env` files must be gitignored, never committed | Contains runtime secrets |
| `agentconfig.json` must use placeholder values in the public repo | Real endpoints are configured per-deployment |
| Outbound actions (email, Teams, SharePoint) require explicit user confirmation | AGENTS.md § Outbound Action Confirmation |
| `monitor_all`-style flags that bypass conversation filtering are **prohibited** | Grants access to all tenant conversations — unacceptable security scope |

---

## 6. Git & PR Standards

### Branch Naming

| Pattern | Use |
|---------|-----|
| `fix/<issue-or-description>` | Bug fixes |
| `feat/<feature-name>` | New features |
| `integrate-<topic>` | Cherry-picks / integration branches |
| `docs/<topic>` | Documentation-only changes |

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description

Optional body with context, rationale, and what changed.

Fixes #<issue>
Co-authored-by: Name <email>
```

Types: `fix`, `feat`, `docs`, `refactor`, `test`, `chore`

### Pull Requests

| Requirement | Detail |
|-------------|--------|
| **Title** follows conventional commit format | `fix(scripts): replace em-dashes in PS1 files` |
| **Body** explains what, why, and how | Not just "fixes bug" |
| **Base branch** is current `main` | PRs against stale bases create merge conflicts and miss architectural changes |
| **No personalization leaks** | No real names, aliases, org-specific terms in public repo content |
| **Co-authored-by credit** when cherry-picking or building on others' work | Attribution in commit trailer |
| **CI tests pass** | All offline tests (categories 1-7) must be green |
| **Self-review before requesting review** | Check diff for debug prints, TODOs, commented-out code |

---

## 7. Architecture Alignment

| Rule | Rationale |
|------|-----------|
| New messaging tiers must respect the established priority order (see Teams SKILL.md) | `scripts.api` → MCP HTML → MCP plain → Playwright |
| Token management uses shared `TokenManager` singleton, not per-module instances | Prevents token refresh storms and inconsistent state |
| Multi-resource token architecture (`RESOURCE_TEAMS`, `RESOURCE_GRAPH`) must be preserved | Teams Substrate API and Microsoft Graph require different tokens |
| Config changes must not expand security scope without explicit review | Adding fields like `monitor_all` requires security assessment |

---

## Automated Enforcement

The following checks run automatically:

| Check | Trigger | Test IDs |
|-------|---------|----------|
| Em-dash scan | `run-offline-tests.ps1` | CQ-01 |
| PS1 parse validation (5.1 + 7.x) | `run-offline-tests.ps1` | CQ-02 |
| Secret detection | Pre-commit hook | SEC-01 through SEC-06 |
| Sanitization scan | `run-offline-tests.ps1` | SAN-01 through SAN-13 |
| SKILL.md frontmatter | `run-offline-tests.ps1` | SKL-01 through SKL-05 |
| JSON schema validation | `run-offline-tests.ps1` | JSON-01 through JSON-08 |

Run the full offline suite before pushing:

```powershell
pwsh tests/run-offline-tests.ps1 -Verbose
```
