# Creating an Organization Setup Repo for Agency Cowork

This guide walks you through creating an **org-specific setup repo** that customizes Agency Cowork for your team or program. Once created, your repo can be included in the setup wizard so team members get a fully configured environment on first launch.

---

## Overview

An org setup repo contains team-specific configuration — ADO queries, Confluence spaces, triage contacts, report structures, knowledgebase content — that layers on top of the base Agency Cowork installation. The setup wizard discovers and applies it during first-run or upgrade.

**Reference implementation:** [ahsi-cobalt-agency-cowork-setup](https://github.com/ahsi-microsoft/ahsi-cobalt-agency-cowork-setup)

---

## Step 1: Create the Repository

### 1.1 Use StartRight to Create the Repo

All Microsoft internal GitHub repos must be created through the **StartRight** portal:

> **https://aka.ms/startright**

1. Navigate to [https://aka.ms/startright](https://aka.ms/startright)
2. Select your GitHub organization (e.g., `ahsi-microsoft`, `your-org`)
3. Name your repo following the convention: `<team>-agency-cowork-setup`
   - Example: `ahsi-cobalt-agency-cowork-setup`, `surface-fw-agency-cowork-setup`
4. Set visibility to **Internal** (recommended) or **Private**
5. Select the README template option — StartRight scaffolds `.github/` compliance files automatically
6. Complete the repo creation wizard

> **Important:** Do NOT create repos directly through the GitHub UI. StartRight ensures compliance with Microsoft security policies, sets up required `.github/` scaffolding, and registers the repo with 1ES tooling.

### 1.2 Ensure Two Owners

Microsoft policy requires at least **two owners** for every internal repository. This ensures continuity if one owner leaves the team or org.

1. During StartRight creation, add a second owner (your manager, tech lead, or a trusted peer)
2. Both owners appear in `.github/compliance/inventory.yml`:
   ```yaml
   inventory:
   - source: DirectOwners
     items:
     - id: yourAlias@microsoft.com
     - id: secondOwner@microsoft.com
     isProduction: false
   ```

---

## Step 2: Set Up Entra Security Groups

Before configuring repo access, create **mail-enabled security groups** in the Entra portal for role-based access control.

### 2.1 Create Groups in Entra

1. Navigate to the [Entra Admin Center](https://entra.microsoft.com/#view/Microsoft_AAD_IAM/GroupsManagementMenuBlade/~/AllGroups)
2. Click **New group** and create two groups:

| Group Name | Type | Purpose |
|---|---|---|
| `<Team>-AgencyCowork-Maintainers` | Mail-enabled security | Repo admins — can approve PRs, manage settings, push to protected branches |
| `<Team>-AgencyCowork-Writers` | Mail-enabled security | Contributors — can push branches and submit PRs |

   Example: `Cobalt-AgencyCowork-Maintainers`, `Cobalt-AgencyCowork-Writers`

3. Add members to each group:
   - **Maintainers:** Team leads, repo owners, anyone who approves PRs
   - **Writers:** All team members who will customize or contribute to the setup repo

4. Set a group owner (typically the same person as the repo owner)

> **Why mail-enabled?** GitHub EMU (Enterprise Managed Users) syncs Entra security groups for repo access. Mail-enabled groups are discoverable and can receive notifications.

### 2.2 Configure Repo Access (`.github/acl/access.yml`)

Map the Entra groups to GitHub repo roles:

```yaml
# .github/acl/access.yml
name: Access control list
description: List of teams and their permission levels
resource: repository
where:
configuration:
  manageAccess:
  - member: yourAlias           # Owner 1
    role: Maintain
  - member: secondOwnerAlias    # Owner 2
    role: Maintain
  - team: <Team>-AgencyCowork-Maintainers
    role: Maintain
  - team: <Team>-AgencyCowork-Writers
    role: Push
```

> **Critical:** You must have **writers defined** to enable PR approval workflows. Without writers, there is no one to submit PRs and no one to approve them. A repo with only maintainers and no branch protection is a security risk.

---

## Step 3: Configure Branch Protection

Set up branch protection on `main` to require PR reviews:

1. Go to **Settings → Branches → Branch protection rules**
2. Add a rule for `main`:
   - ✅ Require a pull request before merging
   - ✅ Require at least 1 approval
   - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require conversation resolution before merging

This ensures all changes to the setup repo are reviewed before they reach team members.

---

## Step 4: Scaffold the Repo

Your setup repo needs the following structure. Use [ahsi-cobalt-agency-cowork-setup](https://github.com/ahsi-microsoft/ahsi-cobalt-agency-cowork-setup) as a reference.

### Required Structure

```
your-team-agency-cowork-setup/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   └── JitAccess.yml        # JIT admin access request template
│   ├── acl/
│   │   └── access.yml           # Role-based access control
│   ├── compliance/
│   │   └── inventory.yml        # Repo owners for compliance
│   └── policies/
│       └── jit.yml              # Just-in-time access policy
├── config/
│   ├── CLAUDE.md                # Team-specific agent identity & domain knowledge
│   ├── AGENTS.md                # Team-specific operational instructions
│   ├── agentconfig-overrides.json  # Config overrides (ADO URLs, skill toggles)
│   └── triage-profile.json      # Email triage contacts (optional)
├── knowledgebase/               # Pre-built .md files for memory/Knowledgebase/
│   ├── Program/
│   │   └── overview.md          # Program overview, milestones, org chart
│   └── Processes/
│       └── release-process.md   # Team-specific processes
├── apply.ps1                    # Windows setup script (idempotent)
├── apply.sh                     # macOS/Linux setup script (idempotent)
├── agency.json                  # Skill manifest for auto-discovery
├── README.md                    # Team-facing documentation
└── SKILL.md                     # Skill documentation (for the agent)
```

### Key Files

**`apply.ps1`** — The entry point. Must be idempotent (safe to re-run). Typical operations:
- Copy `config/CLAUDE.md` → project root (merge with existing, don't overwrite)
- Copy `config/AGENTS.md` → project root (merge with existing, don't overwrite)
- Copy `knowledgebase/` → `memory/Knowledgebase/`
- Patch `agentconfig.json` with team-specific values
- Print a summary of what was applied

**`agency.json`** — Skill manifest so the agent auto-discovers the setup skill:
```json
{
  "name": "your-team-setup",
  "description": "Organization-specific configuration for <Team Name>",
  "version": "1.0.0"
}
```

**`SKILL.md`** — Tells the agent what this skill does and when to use it.

### `.github/` Compliance Files

StartRight creates most of these. Ensure they are populated correctly:

**`.github/compliance/inventory.yml`**
```yaml
inventory:
- source: DirectOwners
  items:
  - id: owner1@microsoft.com
  - id: owner2@microsoft.com
  isProduction: false
```

**`.github/policies/jit.yml`**
```yaml
id: id
name: JIT_Access
description: Policy for admin JIT for repos in this org
resource: repository
configuration:
    jitAccess:
        enabled: true
        maxHours: 2
        approvers:
            role: Maintain
        requestors:
            role: Write
```

---

## Step 5: Request Inclusion in the Setup Wizard

Once your repo is scaffolded and tested, submit a PR to the [agency-cowork](https://github.com/ahsi-microsoft/agency-cowork) repo to register it as an available org setup option.

### What to Include in the PR

1. **Update `scripts/setup.ps1`** — Add your repo URL to the org setup registry
2. **Update `scripts/setup.sh`** — Same for macOS/Linux
3. **Update `ui/src/App.jsx`** — Add your org to the setup wizard dropdown (if applicable)
4. **Test the flow** — Verify that a fresh install with your setup repo produces a working environment

### PR Template

Title: `feat: add <Team> org setup repo`

Body:
```markdown
## Organization Setup Repo Registration

- **Repo:** https://github.com/<org>/<team>-agency-cowork-setup
- **Team/Program:** <Team Name>
- **Owners:** @owner1, @owner2
- **Entra Groups:** <Team>-AgencyCowork-Maintainers, <Team>-AgencyCowork-Writers

### Checklist
- [ ] Repo created via https://aka.ms/startright
- [ ] Two owners defined in `.github/compliance/inventory.yml`
- [ ] Entra security groups created for Maintainers and Writers
- [ ] Writers assigned in `.github/acl/access.yml` (enables PR approval)
- [ ] Branch protection enabled on `main` (require 1 approval)
- [ ] `apply.ps1` / `apply.sh` tested and idempotent
- [ ] `agency.json` and `SKILL.md` present
- [ ] Knowledgebase content populated
- [ ] README.md documents what the setup configures
```

---

## Best Practices

### Security
- **Never store secrets** in the setup repo — use `agentconfig.json` environment variables or `.env` files (gitignored)
- **Use Internal visibility** — makes the repo accessible to all Microsoft FTEs without explicit access grants
- Keep triage profiles and contact lists **in the setup repo, not the main repo** — they contain PII-adjacent data

### Maintainability
- **Make `apply.ps1` idempotent** — users will re-run it on every upgrade. Use merge logic, not overwrite
- **Version your config** — include a version field in `agency.json` so the agent knows when to re-apply
- **Document everything** — your `README.md` is the first thing a new team member sees

### Access Control
- **Maintainers** = can approve PRs, push to main (via branch protection bypass), manage repo settings
- **Writers** = can push branches, open PRs, but cannot merge without maintainer approval
- At minimum, have **2 Maintainers** and **3+ Writers** to ensure healthy PR flow

### Naming Conventions

| Resource | Convention | Example |
|---|---|---|
| Repo | `<team>-agency-cowork-setup` | `ahsi-cobalt-agency-cowork-setup` |
| Maintainers group | `<Team>-AgencyCowork-Maintainers` | `Cobalt-AgencyCowork-Maintainers` |
| Writers group | `<Team>-AgencyCowork-Writers` | `Cobalt-AgencyCowork-Writers` |
| Skill name | `<team>-setup` | `cobalt-setup` |

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Can't create repo via StartRight | Ensure you have org membership. Request access via [GiM docs](https://aka.ms/gim/docs) |
| Entra groups not syncing to GitHub | Allow up to 24 hours for AAD → GitHub EMU sync. Check group type is "Security" or "Mail-enabled security" |
| PR approvals not working | Verify writers are defined in `access.yml` AND branch protection requires approvals |
| Setup wizard doesn't show my org | Submit a PR to register your repo — see Step 5 above |
| `apply.ps1` fails on re-run | Script must be idempotent — check for existing files before overwriting |

---

## References

- [StartRight — Create a Microsoft internal repo](https://aka.ms/startright)
- [Entra Admin Center — Group Management](https://entra.microsoft.com/#view/Microsoft_AAD_IAM/GroupsManagementMenuBlade/~/AllGroups)
- [GitHub inside Microsoft (GiM) Docs](https://aka.ms/gim/docs)
- [GiM Access Control](https://aka.ms/StartRight/README-TEmplates/gim/policies/access)
- [GiM Branch Protection](https://aka.ms/StartRight/README-Template/gim/policies/branch-protection)
- [Reference implementation: ahsi-cobalt-agency-cowork-setup](https://github.com/ahsi-microsoft/ahsi-cobalt-agency-cowork-setup)
