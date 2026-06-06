# Test Plan — Agency Cowork

Comprehensive test plan for validating the Agency Cowork baseline before distribution. Tests are organized by category and tagged with execution requirements.

**Legend:**
- **[OFFLINE]** — Can run without external services
- **[LOCAL-DEP]** — Requires locally installed tools (markitdown, QMD, specify, etc.)
- **[LIVE-M365]** — Requires live Microsoft 365 + MCP servers
- **[MANUAL]** — Requires human judgment or interactive verification

---

## 1. Sanitization Verification

Confirm all domain-specific references, personal data, and credentials have been removed.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| SAN-01 | No domain-specific references in any tracked file | `git grep -i` for domain terms returns 0 results | [OFFLINE] |
| SAN-02 | No personal email addresses | `git grep -iE 'personal-email-patterns'` returns 0 | [OFFLINE] |
| SAN-03 | No personal UPN or User IDs | `git grep -iE 'personal-guid-patterns'` returns 0 | [OFFLINE] |
| SAN-04 | No real Azure endpoints | `git grep -i personal-azure-names` returns 0 | [OFFLINE] |
| SAN-05 | No real tenant IDs (72f988bf) | `git grep 72f988bf` returns 0 | [OFFLINE] |
| SAN-06 | No real API keys in tracked files | `security-audit.ps1` check 1 passes | [OFFLINE] |
| SAN-07 | `.env` file does not exist or is gitignored | `git ls-files .env` returns empty | [OFFLINE] |
| SAN-08 | `.env.example` contains only placeholder values | Manual: verify `your-api-key-here` | [OFFLINE] |
| SAN-09 | `agentconfig.json` uses placeholder endpoint | Verify `your-resource.cognitiveservices.azure.com` | [OFFLINE] |
| SAN-10 | `recentcontacts.md` has no real contacts | Tables exist but contain no real data or only example/contoso data | [OFFLINE] |
| SAN-11 | No weekly report content exists | `memory/WeeklyReports/` contains only `.gitkeep` | [OFFLINE] |
| SAN-12 | No knowledgebase specs from original project | `memory/Knowledgebase/Specifications/System/Everglades/` does not exist | [OFFLINE] |
| SAN-13 | No QMD embeddings cache committed | `skills/qmd-memory/cache/embeddings/` is empty or gitignored | [OFFLINE] |

---

## 2. File Structure & Integrity

Verify the expected directory structure and file presence.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| FS-01 | Core files exist | Verify: README.md, CLAUDE.md, AGENTS.md, installation.md, threatmodel.md, agentconfig.json, .env.example, .gitignore, .gitattributes | [OFFLINE] |
| FS-02 | Memory structure exists | Verify: memory/MEMORY.md, memory/Knowledgebase/ with subfolders (Program, ExecutiveReviews, ProgramExecutionCouncil, Workstreams, Specifications/{SoC,System,Software,Firmware}) | [OFFLINE] |
| FS-03 | WeeklyReports directory exists | `memory/WeeklyReports/` exists with `.gitkeep` | [OFFLINE] |
| FS-04 | All 9 skills have required structure | Each skill in `skills/` has: `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `agency.json` | [OFFLINE] |
| FS-05 | Scripts directory exists | `scripts/pre-commit` and `scripts/security-audit.ps1` exist | [OFFLINE] |
| FS-06 | Pre-commit hook installed | `.git/hooks/pre-commit` exists and matches `scripts/pre-commit` | [OFFLINE] |

---

## 3. JSON Schema Validation

Verify all JSON config files parse correctly and contain required fields.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| JSON-01 | `agentconfig.json` is valid JSON | Parse with `python -m json.tool` | [OFFLINE] |
| JSON-02 | `agentconfig.json` has embedding config | Verify: `.memory.embedding.provider`, `.memory.embedding.azure_openai.endpoint`, `.deployment`, `.model`, `.api_version` | [OFFLINE] |
| JSON-03 | All 9 `plugin.json` files are valid JSON | Parse each with `python -m json.tool` | [OFFLINE] |
| JSON-04 | All `plugin.json` files have required fields | Each has: `name`, `version`, `description`, `keywords` (array), `author.name` | [OFFLINE] |
| JSON-05 | All `plugin.json` author is "Agency Cowork" | Verify `author.name == "Agency Cowork"` for all 9 | [OFFLINE] |
| JSON-06 | All 9 `agency.json` files are valid JSON | Parse each | [OFFLINE] |
| JSON-07 | All `agency.json` files have required fields | Each has: `category` (string), `engines` (array) | [OFFLINE] |
| JSON-08 | `.mcp.json` is valid JSON | Parse; verify server entries | [OFFLINE] |
| JSON-09 | Third-party skills have required structure | `plugin.json`, `agency.json`, `SKILL.md` exist for each third-party skill | [OFFLINE] |
| JSON-10 | Third-party `plugin.json` valid with required fields | Each has: `name`, `version`, `description`, `keywords`, `author.name` (original author preserved) | [OFFLINE] |
| JSON-11 | Third-party skills have LICENSE file | MIT/Apache/etc. LICENSE file exists at skill root | [OFFLINE] |
| JSON-12 | Third-party `agency.json` valid with required fields | Each has: `category` (string), `engines` (array) | [OFFLINE] |

---

## 4. SKILL.md Frontmatter Validation

Verify all SKILL.md files have valid YAML frontmatter.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| SKL-01 | All 9 SKILL.md files start with `---` | Check first line of each SKILL.md | [OFFLINE] |
| SKL-02 | All SKILL.md files have `name:` field | Parse YAML frontmatter | [OFFLINE] |
| SKL-03 | All SKILL.md files have `description:` field | Parse YAML frontmatter | [OFFLINE] |
| SKL-04 | No SKILL.md wrapped in code fences | Verify `---` at line 1, not ` ```skill ` | [OFFLINE] |
| SKL-05 | SKILL.md names match plugin.json names | Cross-reference `name` in frontmatter vs `name` in plugin.json | [OFFLINE] |

---

## 5. Documentation Validation

Verify documentation is complete, links are valid, and content is generic.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| DOC-01 | README.md contains project description | Verify "Agency with a Soul" or equivalent tagline | [OFFLINE] |
| DOC-02 | README.md lists all 9 skills | Skills table has 9 rows | [OFFLINE] |
| DOC-03 | README.md has Security Best Practices section | Section heading exists | [OFFLINE] |
| DOC-04 | README.md has Customizing section | Section heading exists | [OFFLINE] |
| DOC-05 | installation.md has tenant ID discovery steps | "Finding Your Tenant ID" section exists with 4 methods | [OFFLINE] |
| DOC-06 | installation.md skill paths use `Agency-Cowork` | No domain-specific paths | [OFFLINE] |
| DOC-07 | installation.md lists all 9 skills in installed_plugins | 8 entries (markitdown through weekly-report) | [OFFLINE] |
| DOC-08 | CLAUDE.md has domain knowledge | Identity, communication principles, and domain knowledge section present | [OFFLINE] |
| DOC-09 | MEMORY.md has placeholder user profile | Uses `youralias@yourorg.com` or similar | [OFFLINE] |
| DOC-10 | threatmodel.md has all 9 threat categories | T1 through T9 present with mitigations | [OFFLINE] |
| DOC-11 | AGENTS.md lists all 9 skills | Skills table has entries for all skills | [OFFLINE] |
| DOC-12 | Internal markdown links resolve | All `[text](path)` links point to existing files | [OFFLINE] |

---

## 6. Security Controls

Verify all security hardening measures function correctly.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| SEC-01 | Pre-commit blocks real API key | Stage a file with `AZURE_OPENAI_API_KEY=realkey123`; commit should fail | [OFFLINE] |
| SEC-02 | Pre-commit blocks .env file | `git add .env`; commit should fail | [OFFLINE] |
| SEC-03 | Pre-commit blocks large files | Stage a file >1MB; commit should fail | [OFFLINE] |
| SEC-04 | Pre-commit blocks JWT tokens | Stage a file with `eyJhbGciOiJIUzI1NiJ9.test`; commit should fail | [OFFLINE] |
| SEC-05 | Pre-commit blocks PEM keys | Stage a file with `-----BEGIN RSA PRIVATE KEY-----`; commit should fail | [OFFLINE] |
| SEC-06 | Pre-commit allows clean commits | Stage a normal markdown file; commit should succeed | [OFFLINE] |
| SEC-07 | Pre-commit skips security scripts | Modifying `scripts/pre-commit` does not trigger self-blocking | [OFFLINE] |
| SEC-08 | Security audit passes on clean repo | `security-audit.ps1` exits with code 0 | [OFFLINE] |
| SEC-09 | Security audit detects planted secret | Add secret to a tracked file (unstaged); audit should flag it | [OFFLINE] |
| SEC-10 | Security audit checks identity file integrity | Modify `CLAUDE.md` without committing; audit should warn | [OFFLINE] |
| SEC-11 | Security audit checks MCP config | Verify it reads `~/.copilot/mcp-config.json` and validates endpoints | [OFFLINE] |
| SEC-12 | Security audit detects risky scheduled tasks | Create a task JSON with "forward all emails"; audit should warn | [OFFLINE] |
| SEC-13 | .gitignore excludes .env, .env.local | Verify patterns present | [OFFLINE] |
| SEC-14 | .gitignore excludes QMD cache | `skills/qmd-memory/cache/` pattern present | [OFFLINE] |
| SEC-15 | .gitignore excludes Teams cache | `skills/teams/cache/` pattern present (except recentcontacts.md) | [OFFLINE] |
| SEC-16 | .gitattributes marks binaries correctly | PDF, DOCX, GGUF, PNG files marked as binary | [OFFLINE] |

---

## 7. Script Execution

Verify scripts run without errors in isolation.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| SCR-01 | `security-audit.ps1` runs without parse errors | `powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1` exits 0 | [OFFLINE] |
| SCR-02 | `task-manager.ps1 list` runs with empty tasks dir | No tasks -> clean output, exit 0 | [OFFLINE] |
| SCR-03 | `task-manager.ps1 create` creates a task JSON | Creates valid JSON in `skills/task-scheduler/tasks/` | [OFFLINE] |
| SCR-04 | `task-manager.ps1 list` shows created task | Created task appears in list output | [OFFLINE] |
| SCR-05 | `task-manager.ps1 delete` removes task | Task JSON file is removed | [OFFLINE] |
| SCR-06 | `convert-to-md.ps1` runs with `--help` or missing args | Shows usage, does not crash | [LOCAL-DEP] |
| SCR-07 | `setup-qmd.ps1 -SkipInstall` runs | Attempts to create collections (may warn if QMD not installed) | [LOCAL-DEP] |
| SCR-08 | `cache-manager.py` imports without errors | `python -c "import json, pathlib, datetime"` (dependencies check) | [OFFLINE] |
| SCR-09 | `validate_report.py` runs with test fixtures | Test against `tests/fixtures/valid_report.md` and `invalid_report.md` | [OFFLINE] |
| SCR-10 | `verify_citations.py` runs with test fixtures | Returns pass/fail on fixture files | [OFFLINE] |
| SCR-11 | `source_evaluator.py` runs with sample input | Scores a sample source | [OFFLINE] |
| SCR-12 | `citation_manager.py` parses sample citations | Returns structured output | [OFFLINE] |
| SCR-13 | No Unicode em-dashes (U+2014) in PS1 files | Scan all `.ps1` files; 0 matches for `\u2014` | [OFFLINE] |
| SCR-14 | All PS1 files parse without errors | `[Parser]::ParseFile()` returns 0 errors for every `.ps1` | [OFFLINE] |

---

## 8. Skill Registration

Verify skills load correctly in Agency/Copilot CLI.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| REG-01 | All 9 skills appear in `/skills` command | After configuring `installed_plugins`, run `/skills list` | [LOCAL-DEP] |
| REG-02 | Each skill description matches plugin.json | Compare displayed description with plugin.json `description` field | [LOCAL-DEP] |
| REG-03 | Skills with YAML frontmatter parse correctly | No "failed to parse" errors in agent output | [LOCAL-DEP] |

---

## 9. MCP Server Connectivity

Verify Microsoft 365 MCP integrations work end-to-end.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| MCP-01 | WorkIQ responds to a query | Ask "What meetings do I have this week?" | [LIVE-M365] |
| MCP-02 | Teams MCP lists chats | Ask "List my recent Teams chats" | [LIVE-M365] |
| MCP-03 | Outlook Mail MCP searches email | Ask "Search my recent emails" | [LIVE-M365] |
| MCP-04 | SharePoint MCP lists sites | Ask "Find my SharePoint sites" | [LIVE-M365] |
| MCP-05 | QMD MCP returns search results | Ask "Search my memory for program status" | [LOCAL-DEP] |

---

## 10. End-to-End Skill Workflows

Verify complete skill workflows function correctly.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| E2E-01 | Send-email: compose and confirm flow | Ask agent to draft an email; verify confirmation before sending | [LIVE-M365] [MANUAL] |
| E2E-02 | Teams: read channel messages | Ask agent to read messages from a known channel | [LIVE-M365] |
| E2E-03 | Weekly-report: generate report | Ask agent to generate a weekly report for a program | [LIVE-M365] [MANUAL] |
| E2E-04 | Markitdown: convert a test PDF | Provide a PDF file; verify markdown output in Knowledgebase | [LOCAL-DEP] |
| E2E-05 | Task-scheduler: create and list task | Create a task, list it, then delete it | [LOCAL-DEP] |
| E2E-06 | QMD-memory: search daily logs | Create a daily log, run `qmd update`, then search for content | [LOCAL-DEP] |
| E2E-07 | Spec-kit: initialize in temp project | Run `specify init . --ai claude` and `specify check` | [LOCAL-DEP] |
| E2E-08 | SharePoint-download: download a file | Provide a SharePoint URL; verify file downloaded locally | [LIVE-M365] |
| E2E-09 | Deep-research: initiate research | Ask for enterprise research on a topic; verify WorkIQ queries fire | [LIVE-M365] [MANUAL] |

---

## 11. Identity & Memory System

Verify the identity/memory system loads and works correctly.

| ID | Test | Method | Tag |
|----|------|--------|-----|
| ID-01 | Agent loads CLAUDE.md at session start | Ask "What is your name?" - should respond with identity from CLAUDE.md | [LOCAL-DEP] [MANUAL] |
| ID-02 | Agent loads MEMORY.md at session start | Ask about user profile - should reference MEMORY.md content | [LOCAL-DEP] [MANUAL] |
| ID-03 | Agent creates daily log | Start a session; verify `memory/YYYY-MM-DD.md` is created | [LOCAL-DEP] [MANUAL] |
| ID-04 | Agent updates MEMORY.md | Tell agent a new preference; verify MEMORY.md is updated | [LOCAL-DEP] [MANUAL] |
| ID-05 | Agent uses CLAUDE.md communication style | Ask for a status summary; verify formal, executive-ready tone | [LOCAL-DEP] [MANUAL] |

---

## 12. Dashboard Skill

### 12a. Automated Tests (71 tests — `node --test tests/test-dashboard-skill.mjs`)

| Sub-category | Tests | Tag |
|---|---|---|
| Skill metadata (plugin.json, skill.json, SKILL.md, template) | 5 | [OFFLINE] |
| Path validation security (traversal, HTML write-protect, scoping) | 7 | [OFFLINE] |
| scanMemoryDirectory (categories, exclusions, content, truncation) | 10 | [OFFLINE] |
| patchFrontmatter YAML (create, update, add, multi-field) | 4 | [OFFLINE] |
| Template HTML correctness (bridge, CRUD, dark mode, a11y) | 18 | [OFFLINE] |
| Preload API surface (14 dashboard APIs exposed) | 14 | [OFFLINE] |
| main.js IPC handler registration (13 handlers) | 13 | [OFFLINE] |

### 12b. Manual UI Verification (8 tests)

| ID | Test | Steps | Tag |
|----|------|-------|-----|
| DASH-M01 | Dashboard appears in sidebar | Create `memory/Dashboards/test.html` from template; verify it shows in sidebar | [MANUAL] |
| DASH-M02 | Dashboard loads and renders data | Click dashboard in sidebar; verify KB articles, daily logs render | [MANUAL] |
| DASH-M03 | File watcher auto-refresh | Edit a file in `memory/Knowledgebase/`; dashboard re-renders within 2s | [MANUAL] |
| DASH-M04 | startTask button launches AI session | Click an AI action button on dashboard; new chat session opens with the prompt | [MANUAL] |
| DASH-M05 | openFile launches external app | Click a file's "Open" button; file opens in default app | [MANUAL] |
| DASH-M06 | Dark mode renders correctly | Switch OS theme to dark; dashboard colors invert properly | [MANUAL] |
| DASH-M07 | saveFile CRUD from dashboard | Dashboard with inline editor saves content; verify file updated on disk | [MANUAL] |
| DASH-M08 | Debug tools produce output | Trigger dumpData; verify `.debug-data.json` appears in `memory/Dashboards/` | [MANUAL] |

---

## Execution Summary

| Category | Total | [OFFLINE] | [LOCAL-DEP] | [LIVE-M365] | [MANUAL] |
|----------|-------|-----------|-------------|-------------|----------|
| 1. Sanitization | 13 | 13 | 0 | 0 | 0 |
| 2. File Structure | 6 | 6 | 0 | 0 | 0 |
| 3. JSON Validation | 12 | 12 | 0 | 0 | 0 |
| 4. SKILL.md Validation | 5 | 5 | 0 | 0 | 0 |
| 5. Documentation | 12 | 12 | 0 | 0 | 0 |
| 6. Security Controls | 16 | 16 | 0 | 0 | 0 |
| 7. Script Execution | 14 | 10 | 4 | 0 | 0 |
| 8. Skill Registration | 3 | 0 | 3 | 0 | 0 |
| 9. MCP Connectivity | 5 | 0 | 1 | 4 | 0 |
| 10. E2E Workflows | 9 | 0 | 4 | 5 | 5 |
| 11. Identity & Memory | 5 | 0 | 5 | 0 | 5 |
| 12. Dashboard Skill | 71 + 8 manual | 71 | 0 | 0 | 8 |
| **Total** | **179** | **145** | **17** | **9** | **18** |

### Recommended Execution Order

1. **Automated first pass** — Run categories 1-6, 12-automated (143 tests) with validation scripts. Zero external dependencies.
2. **Local dependency tests** — Install markitdown, QMD, specify-cli, then run categories 7-8.
3. **Live integration tests** — Configure MCP servers, then run categories 9-10.
4. **Manual acceptance** — Walk through categories 11, 12-manual interactively.
