"""Confluence REST API client.

Uses `requests` with session cookies from auth.py to call the Confluence
Server REST API v1 (/rest/api/content, /rest/api/search, etc.).

Usage:
    from scripts.wiki_client import ConfluenceClient
    client = ConfluenceClient()
    pages = client.search("type=page AND space=M300 AND title~'Meeting'")
"""

import os
import re
import sys
from html.parser import HTMLParser
from typing import Optional

from . import auth

BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://ahsiwiki.corp.microsoft.com")


class _HTMLToText(HTMLParser):
    """Simple HTML to plain text converter."""

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        elif tag == "br":
            self._text.append("\n")
        elif tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._text.append("\n")
        elif tag == "td":
            self._text.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._text.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return "".join(self._text).strip()


def html_to_text(html: str) -> str:
    """Convert HTML to plain text."""
    parser = _HTMLToText()
    parser.feed(html)
    return parser.get_text()


def html_to_markdown(html: str) -> str:
    """Convert Confluence storage HTML to approximate markdown."""
    text = html
    # Headers
    for i in range(6, 0, -1):
        text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", r"\n" + "#" * i + r" \1\n", text, flags=re.DOTALL)
    # Bold / italic
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
    # Links
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text)
    # Lists
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL)
    # Line breaks
    text = re.sub(r"<br\s*/?>", "\n", text)
    # Paragraphs
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.DOTALL)
    # Tables (simplified)
    text = re.sub(r"<th[^>]*>(.*?)</th>", r"| \1 ", text, flags=re.DOTALL)
    text = re.sub(r"<td[^>]*>(.*?)</td>", r"| \1 ", text, flags=re.DOTALL)
    text = re.sub(r"<tr[^>]*>", "", text)
    text = re.sub(r"</tr>", "|\n", text)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ConfluenceClient:
    """Confluence REST API client with session cookie auth."""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = auth.get_session()
        return self._session

    def _get(self, path: str, params: Optional[dict] = None):
        r = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json_data: dict):
        r = self.session.post(f"{self.base_url}{path}", json=json_data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, json_data: dict):
        r = self.session.put(f"{self.base_url}{path}", json=json_data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str):
        r = self.session.delete(f"{self.base_url}{path}", timeout=30)
        r.raise_for_status()

    # --- Spaces ---

    def list_spaces(self, limit: int = 200) -> list[dict]:
        """List all accessible spaces."""
        results = []
        start = 0
        while True:
            data = self._get("/rest/api/space", {"limit": limit, "start": start})
            results.extend(data.get("results", []))
            if data.get("size", 0) < limit:
                break
            start += data["size"]
        return results

    def get_space(self, key: str) -> dict:
        """Get space details by key."""
        return self._get(f"/rest/api/space/{key}", {"expand": "description.plain,homepage"})

    # --- Pages ---

    def get_page(self, page_id: str, expand: str = "body.storage,version,space,ancestors") -> dict:
        """Get page by ID with expandable fields."""
        return self._get(f"/rest/api/content/{page_id}", {"expand": expand})

    def get_page_by_title(self, space_key: str, title: str) -> Optional[dict]:
        """Find a page by space key and exact title."""
        data = self._get("/rest/api/content", {
            "spaceKey": space_key,
            "title": title,
            "expand": "version,space",
        })
        results = data.get("results", [])
        return results[0] if results else None

    def get_children(self, page_id: str, limit: int = 100) -> list[dict]:
        """Get child pages of a given page."""
        data = self._get(f"/rest/api/content/{page_id}/child/page", {
            "limit": limit,
            "expand": "version",
        })
        return data.get("results", [])

    def get_descendants(self, page_id: str, depth: int = 3) -> list[dict]:
        """Recursively get descendants up to given depth."""
        children = self.get_children(page_id)
        result = []
        for child in children:
            child["_depth"] = 1
            result.append(child)
            if depth > 1:
                for desc in self.get_descendants(child["id"], depth - 1):
                    desc["_depth"] = desc.get("_depth", 1) + 1
                    result.append(desc)
        return result

    # --- Search ---

    def search(self, cql: str, limit: int = 25, expand: str = "space") -> dict:
        """CQL search. Returns full response including totalSize."""
        return self._get("/rest/api/content/search", {
            "cql": cql,
            "limit": limit,
            "expand": expand,
        })

    def search_pages(self, query: str, space: Optional[str] = None, limit: int = 25) -> list[dict]:
        """Search pages by text, optionally filtered to a space."""
        cql = f'type=page AND text~"{query}"'
        if space:
            cql += f" AND space={space}"
        data = self.search(cql, limit)
        return data.get("results", [])

    # --- Create / Update / Delete ---

    def create_page(
        self,
        space_key: str,
        title: str,
        body_html: str,
        parent_id: Optional[str] = None,
    ) -> dict:
        """Create a new page. Returns the created page."""
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        return self._post("/rest/api/content", payload)

    def update_page(
        self,
        page_id: str,
        title: str,
        body_html: str,
        version_number: Optional[int] = None,
    ) -> dict:
        """Update a page. Auto-fetches current version if not provided."""
        if version_number is None:
            current = self.get_page(page_id, expand="version,space")
            version_number = current["version"]["number"]
            space_key = current["space"]["key"]
        else:
            current = self.get_page(page_id, expand="space")
            space_key = current["space"]["key"]

        payload = {
            "id": str(page_id),
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
            "version": {"number": version_number + 1},
        }
        return self._put(f"/rest/api/content/{page_id}", payload)

    def delete_page(self, page_id: str) -> None:
        """Delete a page by ID."""
        self._delete(f"/rest/api/content/{page_id}")

    def append_to_page(self, page_id: str, html_to_append: str) -> dict:
        """Append HTML content to an existing page."""
        current = self.get_page(page_id)
        existing_body = current["body"]["storage"]["value"]
        new_body = existing_body + html_to_append
        return self.update_page(
            page_id, current["title"], new_body, current["version"]["number"]
        )

    # --- Utility ---

    def build_table_html(self, headers: list[str], rows: list[list[str]]) -> str:
        """Build an HTML table from headers and rows."""
        html = "<table><thead><tr>"
        for h in headers:
            html += f"<th>{h}</th>"
        html += "</tr></thead><tbody>"
        for row in rows:
            html += "<tr>"
            for cell in row:
                html += f"<td>{cell}</td>"
            html += "</tr>"
        html += "</tbody></table>"
        return html

    def page_url(self, page_data: dict) -> str:
        """Get the web URL for a page."""
        links = page_data.get("_links", {})
        base = links.get("base", self.base_url)
        webui = links.get("webui", "")
        return f"{base}{webui}"
