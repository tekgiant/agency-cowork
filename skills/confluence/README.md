# Confluence Wiki Skill

Browse, search, create, and edit Confluence wiki pages. Connects to a Confluence Server instance via Azure AD SAML SSO.

## Auth

Uses Playwright CDP (Chrome DevTools Protocol) connection for Azure AD SAML SSO (works even with Edge open). First run requires interactive login; subsequent runs reuse session cookies.

## Quick Start

```bash
cd skills/confluence

# List accessible spaces
python -m scripts.wiki_cli spaces

# Browse a space's page tree
python -m scripts.wiki_cli tree --space PROJ1

# Read a page
python -m scripts.wiki_cli read --id 23456789

# Search for pages
python -m scripts.wiki_cli search --cql 'type=page AND space=PROJ1 AND title~"Meeting"'

# Create a page
python -m scripts.wiki_cli create --space PROJ1 --title "New Page" --body "<p>Content</p>" --parent 12345678

# Edit a page
python -m scripts.wiki_cli edit --id 23456789 --body "<p>Updated content</p>"
```

See `skills/confluence/SKILL.md` for the full decision table.
