# Build & Release Guide

How to build, sign, and publish Agency Cowork releases.

## Prerequisites

### Tools

| Tool | Required | Install |
|------|----------|---------|
| Node.js LTS | Yes | `winget install OpenJS.NodeJS.LTS` |
| Python 3.12 | Yes | `winget install Python.Python.3.12` |
| PowerShell 7 | Yes | `winget install Microsoft.PowerShell` |
| Azure CLI | Signing only | `winget install Microsoft.AzureCLI` |
| GitHub CLI | Publishing only | `winget install GitHub.cli` |

### Code Signing (Azure Trusted Signing)

Create `ui/.env.signing` (gitignored) with your Azure AD service principal credentials:

```ini
AZURE_TENANT_ID=<your-tenant-id>
AZURE_CLIENT_ID=<your-client-id>
AZURE_CLIENT_SECRET=<your-client-secret>
```

The service principal must have the **Artifact Signing Certificate Profile Signer** role
on the Trusted Signing account resource. The signing config (endpoint, account, profile)
is in `ui/package.json` under `build.azureSignOptions`.

## Quick Reference

```powershell
# Full signed production release (both arches)
pwsh -ExecutionPolicy Bypass -File ui/scripts/release-win.ps1 -Stable

# Prerelease / beta
pwsh -ExecutionPolicy Bypass -File ui/scripts/release-win.ps1 -Tag rc1

# Unsigned local test build (no creds needed)
pwsh -ExecutionPolicy Bypass -File ui/scripts/release-win.ps1 -SkipSign -SkipCommit -SkipPublish

# Dry run (preview what would happen)
pwsh -ExecutionPolicy Bypass -File ui/scripts/release-win.ps1 -Stable -DryRun
```

## Release Process

### 1. Prepare

```powershell
# Sync to main
git checkout main
git pull upstream main

# Verify version in package.json matches intended release
node -p "require('./ui/package.json').version"

# If version needs bumping, the script can do it:
#   release-win.ps1 -Version 1.0.8
```

### 2. Build & Sign

```powershell
cd <repo-root>
pwsh -ExecutionPolicy Bypass -File ui/scripts/release-win.ps1 -Stable -SkipCommit
```

The script:
1. Loads signing credentials from `ui/.env.signing`
2. Builds the Vite renderer (`npm run build`)
3. Builds NSIS installers for both x64 and arm64 via `build-win.js`
4. Signs all `.exe` and `.dll` files via Azure Trusted Signing
5. Renames installers with arch suffix (e.g., `Agency Cowork Setup 1.0.7-x64.exe`)
6. Verifies artifacts exist and signatures are valid

**Output:** `ui/release/Agency Cowork Setup <version>-<arch>.exe`

Use `-SkipCommit` when the version was already set (no package.json bump needed).
Use `-SkipPublish` to build without creating the GitHub release (publish manually).

### 3. Write Release Notes

Delete any existing draft/release for the same tag, then publish with curated notes:

```powershell
# Delete stale release if re-building
gh release delete v1.0.7 --yes --cleanup-tag

# Or let the script publish automatically (omit -SkipPublish)
```

#### Release Notes Structure

Use this template for release notes. Include a **contributor table** at the top.

```markdown
## Agency Cowork v<version>

### :busts_in_silhouette: Contributors

| Contributor | Role | PRs |
|---|---|---|
| @author1 | Author, Release Manager | #1, #2, #3 |
| @reviewer1 | Reviewer | #1, #2 |
| @author2 | Author | #4 (short description) |
| @dependabot | Automated | #5, #6 |

### :lock: Critical Security Fixes
- **Title** — Description. (#PR)

### :sparkles: New Features
- **Title** — Description. (#PR)

### :bug: Bug Fixes
- **Title** — Description. (#PR)

### :shield: Code Signing
All executables in this release are digitally signed via Azure Trusted Signing.
- **Signer:** CN=..., O=..., L=..., S=..., C=...
- **Timestamp:** Microsoft Public RSA Time Stamping Authority

### :warning: Upgrade Recommendation
Summary of why users should upgrade.
```

#### Gathering Contributors

```powershell
# Get author and title for each PR in the release
$prs = @(163, 161, 159)  # list all PR numbers
foreach ($pr in $prs) {
    gh pr view $pr --json number,title,author --jq '"\(.number) | \(.author.login) | \(.title)"'
}

# Get reviewers
foreach ($pr in $prs) {
    gh pr view $pr --json number,reviews --jq '"\(.number) | \([.reviews[].author.login] | unique | join(", "))"'
}
```

### 4. Publish

If you used `-SkipPublish`, upload manually:

```powershell
gh release create v1.0.7 --title "v1.0.7" --notes-file notes.md `
  "ui/release/Agency Cowork Setup 1.0.7-x64.exe" `
  "ui/release/Agency Cowork Setup 1.0.7-arm64.exe"
```

To update notes on an existing release:

```powershell
gh release edit v1.0.7 --notes-file notes.md
```

### 5. Verify

```powershell
# Confirm release is Latest (not prerelease, not draft)
gh release view v1.0.7 --json tagName,isPrerelease,isDraft,assets `
  --jq '{tag: .tagName, prerelease: .isPrerelease, draft: .isDraft, assets: [.assets[].name]}'
```

The stable channel update checker (`GET /releases/latest`) only returns releases
marked as **Latest**. Beta channel uses `GET /releases?per_page=1` which includes
prereleases.

## Script Reference

### `ui/scripts/release-win.ps1`

Main release automation script.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Version` | from package.json | Semver to set (e.g., `1.0.8`) |
| `-Tag` | *(none)* | Suffix like `rc1`, `beta1` — auto-marks as prerelease |
| `-Arch` | `all` | `x64`, `arm64`, or `all` |
| `-Stable` | off | Marks release as Latest (stable channel) |
| `-SkipBuild` | off | Use existing artifacts in `ui/release/` |
| `-SkipSign` | off | Build without code signing |
| `-SkipCommit` | off | Skip git commit of version bump |
| `-SkipPublish` | off | Build only, don't create GitHub release |
| `-DryRun` | off | Preview actions without executing |
| `-Prerelease` | off | Force prerelease flag (auto-set when Tag is present) |

### `ui/scripts/build-win.js`

Low-level builder called by `release-win.ps1`. Handles:
- Swapping node-pty native binaries per target arch (x64/arm64)
- Invoking `electron-builder` with correct flags
- Renaming output files with arch suffix
- Restoring host binaries after cross-arch builds

### macOS

macOS builds use a separate workflow:
- `ui/scripts/release-mac-manual.sh` — Build + notarize
- `ui/scripts/create-dmg-manual.sh` — Create DMG from .app
- `ui/scripts/notarize-dmg.sh` — Notarize the DMG

## Troubleshooting

### Signing fails with "AZURE_TENANT_ID not found"

Ensure `ui/.env.signing` exists and has all three variables. The script uses
`Set-Item -Path "env:$key"` (not `[Environment]::SetEnvironmentVariable`) so
child processes (node, electron-builder) inherit the vars.

### electron-builder can't find TrustedSigning module

The module is auto-installed by electron-builder on first run. If it fails,
install manually: `Install-Module -Name TrustedSigning -Scope CurrentUser`

### Build produces same filename for both arches

`build-win.js` handles renaming. If running `electron-builder` directly,
you must rename manually between builds — it always outputs
`Agency Cowork Setup <version>.exe` regardless of arch.

### Spectre-mitigated libs error during npm install

Patch node-pty bindings: `node ui/scripts/patch-node-pty.js`
(changes `SpectreMitigation: 'Spectre'` to `'false'` in binding.gyp).
The postinstall script does this automatically.
