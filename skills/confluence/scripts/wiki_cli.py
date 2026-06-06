"""Confluence wiki CLI — browse, read, search, create, edit, and manage pages.

Usage:
    cd skills/confluence
    python -m scripts.wiki_cli spaces
    python -m scripts.wiki_cli search --cql 'type=page AND space=PROJ'
    python -m scripts.wiki_cli read --id 230290071
    python -m scripts.wiki_cli tree --space PROJ
    python -m scripts.wiki_cli create --space PROJ --title "New Page" --body "<p>Hi</p>"
    python -m scripts.wiki_cli edit --id 230290071 --body "<p>Updated</p>"
    python -m scripts.wiki_cli table --id 230290071 --headers "Col1,Col2" --rows "A,B;C,D"
    python -m scripts.wiki_cli browse --space PROJ --page 116951249
"""

import argparse
import json
import sys

from .wiki_client import ConfluenceClient, html_to_markdown, html_to_text


def cmd_spaces(client: ConfluenceClient, args):
    """List accessible Confluence spaces."""
    spaces = client.list_spaces()
    if args.json:
        print(json.dumps(spaces, indent=2))
        return

    print(f"{'Key':<10} {'Name':<40} {'Type':<12}")
    print("-" * 62)
    for s in sorted(spaces, key=lambda x: x.get("key", "")):
        key = s.get("key", "")
        name = s.get("name", "")[:38]
        stype = s.get("type", "")
        print(f"{key:<10} {name:<40} {stype:<12}")
    print(f"\nTotal: {len(spaces)} spaces")


def cmd_read(client: ConfluenceClient, args):
    """Read a page by ID or space+title."""
    if args.id:
        page = client.get_page(str(args.id))
    elif args.space and args.title:
        page = client.get_page_by_title(args.space, args.title)
        if not page:
            print(f"Page not found: '{args.title}' in space {args.space}", file=sys.stderr)
            sys.exit(1)
        page = client.get_page(page["id"])
    else:
        print("Provide --id or --space + --title", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(page, indent=2))
        return

    body_html = page.get("body", {}).get("storage", {}).get("value", "")
    title = page.get("title", "Untitled")
    space = page.get("space", {}).get("key", "?")
    version = page.get("version", {}).get("number", "?")
    url = client.page_url(page)

    print(f"# {title}")
    print(f"Space: {space} | Version: {version} | ID: {page['id']}")
    print(f"URL: {url}")
    print()

    if args.raw:
        print(body_html)
    elif args.text:
        print(html_to_text(body_html))
    else:
        print(html_to_markdown(body_html))


def cmd_search(client: ConfluenceClient, args):
    """Search pages using CQL."""
    cql = args.cql
    if not cql and args.query:
        cql = f'type=page AND text~"{args.query}"'
        if args.space:
            cql += f" AND space={args.space}"

    if not cql:
        print("Provide --cql or --query [--space]", file=sys.stderr)
        sys.exit(1)

    data = client.search(cql, limit=args.limit or 25)
    results = data.get("results", [])
    total = data.get("totalSize", len(results))

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"Results: {len(results)} of {total}")
    print(f"{'ID':<12} {'Space':<8} {'Title':<60}")
    print("-" * 80)
    for r in results:
        rid = r.get("id", "")
        space = r.get("space", {}).get("key", "?")
        title = r.get("title", "")[:58]
        print(f"{rid:<12} {space:<8} {title:<60}")


def cmd_tree(client: ConfluenceClient, args):
    """Show page hierarchy for a space or page."""
    if args.page:
        root_id = str(args.page)
    elif args.space:
        space_info = client.get_space(args.space)
        hp = space_info.get("homepage", {})
        if not hp:
            hp = space_info.get("_expandable", {}).get("homepage", "")
            if hp and "/" in hp:
                root_id = hp.rstrip("/").split("/")[-1]
            else:
                print(f"No homepage found for space {args.space}", file=sys.stderr)
                sys.exit(1)
        else:
            root_id = hp.get("id", hp) if isinstance(hp, dict) else hp
    else:
        print("Provide --space or --page", file=sys.stderr)
        sys.exit(1)

    depth = args.depth or 3

    root = client.get_page(str(root_id), expand="version,space")
    print(f"# {root['title']} (id: {root['id']})")
    descendants = client.get_descendants(str(root_id), depth)
    for d in descendants:
        indent = "  " * d.get("_depth", 1)
        print(f"{indent}- {d['title']} (id: {d['id']})")

    print(f"\nTotal: {len(descendants) + 1} pages")


def cmd_browse(client: ConfluenceClient, args):
    """Browse immediate children of a space or page."""
    if args.page:
        children = client.get_children(str(args.page))
        parent = client.get_page(str(args.page), expand="space")
        print(f"Children of: {parent['title']} (id: {parent['id']})")
    elif args.space:
        space_info = client.get_space(args.space)
        hp = space_info.get("homepage", {})
        if not hp:
            print(f"No homepage for space {args.space}", file=sys.stderr)
            sys.exit(1)
        root_id = hp.get("id", hp) if isinstance(hp, dict) else hp
        children = client.get_children(str(root_id))
        print(f"Children of: {args.space} homepage (id: {root_id})")
    else:
        print("Provide --space or --page", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(children, indent=2))
        return

    print(f"\n{'ID':<12} {'Title':<60} {'Version':<8}")
    print("-" * 80)
    for c in children:
        cid = c.get("id", "")
        title = c.get("title", "")[:58]
        ver = c.get("version", {}).get("number", "?")
        print(f"{cid:<12} {title:<60} {ver:<8}")
    print(f"\nTotal: {len(children)} pages")


def cmd_create(client: ConfluenceClient, args):
    """Create a new page."""
    body = args.body or ""

    # Read body from file if specified
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()

    # Simple markdown-to-HTML if body looks like markdown
    if body and not body.strip().startswith("<"):
        body = _markdown_to_html(body)

    result = client.create_page(args.space, args.title, body, args.parent)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Created: {result['title']} (id: {result['id']})")
    print(f"URL: {client.page_url(result)}")


def cmd_edit(client: ConfluenceClient, args):
    """Edit (update) an existing page."""
    current = client.get_page(str(args.id))
    title = args.title or current["title"]
    body = args.body

    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()

    if args.append and body:
        existing = current.get("body", {}).get("storage", {}).get("value", "")
        if body and not body.strip().startswith("<"):
            body = _markdown_to_html(body)
        body = existing + body
    elif body and not body.strip().startswith("<"):
        body = _markdown_to_html(body)

    if not body:
        print("Provide --body or --body-file", file=sys.stderr)
        sys.exit(1)

    result = client.update_page(
        str(args.id), title, body, current["version"]["number"]
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Updated: {result['title']} (id: {result['id']}, v{result['version']['number']})")
    print(f"URL: {client.page_url(result)}")


def cmd_table(client: ConfluenceClient, args):
    """Create or append a table to a page."""
    headers = [h.strip() for h in args.headers.split(",")]
    rows = []
    for row_str in args.rows.split(";"):
        rows.append([c.strip() for c in row_str.split(",")])

    table_html = client.build_table_html(headers, rows)

    if args.id:
        if args.replace:
            current = client.get_page(str(args.id))
            result = client.update_page(
                str(args.id), current["title"], table_html, current["version"]["number"]
            )
        else:
            result = client.append_to_page(str(args.id), table_html)
        print(f"Updated: {result['title']} (id: {result['id']}, v{result['version']['number']})")
    elif args.space and args.title:
        body = table_html
        result = client.create_page(args.space, args.title, body, args.parent)
        print(f"Created: {result['title']} (id: {result['id']})")
    else:
        # Just print the HTML
        print(table_html)


def _markdown_to_html(md: str) -> str:
    """Basic markdown to Confluence storage HTML conversion."""
    lines = md.split("\n")
    html_lines = []
    in_list = False
    in_code = False

    for line in lines:
        stripped = line.strip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code:
                html_lines.append("</ac:plain-text-body></ac:structured-macro>")
                in_code = False
            else:
                lang = stripped[3:].strip() or "text"
                html_lines.append(
                    f'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">{lang}</ac:parameter><ac:plain-text-body><![CDATA['
                )
                in_code = True
            continue

        if in_code:
            html_lines.append(line)
            continue

        # Headers
        if stripped.startswith("######"):
            html_lines.append(f"<h6>{stripped[6:].strip()}</h6>")
        elif stripped.startswith("#####"):
            html_lines.append(f"<h5>{stripped[5:].strip()}</h5>")
        elif stripped.startswith("####"):
            html_lines.append(f"<h4>{stripped[4:].strip()}</h4>")
        elif stripped.startswith("###"):
            html_lines.append(f"<h3>{stripped[3:].strip()}</h3>")
        elif stripped.startswith("##"):
            html_lines.append(f"<h2>{stripped[2:].strip()}</h2>")
        elif stripped.startswith("#"):
            html_lines.append(f"<h1>{stripped[1:].strip()}</h1>")
        # Lists
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if stripped:
                # Bold / italic
                text = stripped
                text = text.replace("**", "<strong>", 1)
                if "**" in text:
                    text = text.replace("**", "</strong>", 1)
                html_lines.append(f"<p>{text}</p>")
            else:
                html_lines.append("")

    if in_list:
        html_lines.append("</ul>")
    if in_code:
        html_lines.append("]]></ac:plain-text-body></ac:structured-macro>")

    return "\n".join(html_lines)


def main():
    parser = argparse.ArgumentParser(description="Confluence wiki CLI")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # spaces
    sub.add_parser("spaces", help="List accessible spaces")

    # read
    p = sub.add_parser("read", help="Read a page")
    p.add_argument("--id", type=str, help="Page ID")
    p.add_argument("--space", type=str, help="Space key (with --title)")
    p.add_argument("--title", type=str, help="Page title (with --space)")
    p.add_argument("--raw", action="store_true", help="Output raw storage HTML")
    p.add_argument("--text", action="store_true", help="Output plain text")

    # search
    p = sub.add_parser("search", help="Search pages")
    p.add_argument("--cql", type=str, help="CQL query")
    p.add_argument("--query", type=str, help="Text search (auto-builds CQL)")
    p.add_argument("--space", type=str, help="Filter by space key")
    p.add_argument("--limit", type=int, default=25, help="Max results")

    # tree
    p = sub.add_parser("tree", help="Show page hierarchy")
    p.add_argument("--space", type=str, help="Space key")
    p.add_argument("--page", type=str, help="Root page ID")
    p.add_argument("--depth", type=int, default=3, help="Max depth")

    # browse
    p = sub.add_parser("browse", help="Browse children of a page")
    p.add_argument("--space", type=str, help="Space key")
    p.add_argument("--page", type=str, help="Parent page ID")

    # create
    p = sub.add_parser("create", help="Create a new page")
    p.add_argument("--space", type=str, required=True, help="Space key")
    p.add_argument("--title", type=str, required=True, help="Page title")
    p.add_argument("--body", type=str, help="Page body (HTML or markdown)")
    p.add_argument("--body-file", type=str, help="Read body from file")
    p.add_argument("--parent", type=str, help="Parent page ID")

    # edit
    p = sub.add_parser("edit", help="Edit a page")
    p.add_argument("--id", type=str, required=True, help="Page ID")
    p.add_argument("--title", type=str, help="New title (keeps current if omitted)")
    p.add_argument("--body", type=str, help="New body (HTML or markdown)")
    p.add_argument("--body-file", type=str, help="Read body from file")
    p.add_argument("--append", action="store_true", help="Append instead of replace")

    # table
    p = sub.add_parser("table", help="Create/append a table")
    p.add_argument("--id", type=str, help="Page ID to update")
    p.add_argument("--space", type=str, help="Space key (for new page)")
    p.add_argument("--title", type=str, help="Page title (for new page)")
    p.add_argument("--parent", type=str, help="Parent page ID (for new page)")
    p.add_argument("--headers", type=str, required=True, help="Comma-separated headers")
    p.add_argument("--rows", type=str, required=True, help="Rows: 'a,b;c,d'")
    p.add_argument("--replace", action="store_true", help="Replace content vs append")

    args = parser.parse_args()
    client = ConfluenceClient()

    commands = {
        "spaces": cmd_spaces,
        "read": cmd_read,
        "search": cmd_search,
        "tree": cmd_tree,
        "browse": cmd_browse,
        "create": cmd_create,
        "edit": cmd_edit,
        "table": cmd_table,
    }

    try:
        commands[args.command](client, args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
