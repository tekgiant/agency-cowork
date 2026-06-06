"""Pre-send validator for Teams rich messages.

Checks that all emoji CDN images and hyperlinks in the generated HTML
resolve to valid endpoints.  Run this on the output of
``markdown_to_teams_html()`` *before* posting to Teams so broken images
and dead links never reach the recipient.

Usage (CLI)::

    # Validate markdown body (converts to HTML first)
    python -m scripts.rich.validate_message --body ":rocket: Visit https://github.com"

    # Validate raw HTML (already converted)
    python -m scripts.rich.validate_message --html "<p><a href='https://example.com'>link</a></p>"

    # Pipe HTML from stdin
    echo "<p>hello</p>" | python -m scripts.rich.validate_message --stdin

Exit codes:
    0 — All emojis and links are valid
    1 — One or more broken emojis or links detected
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .utils import markdown_to_teams_html, EMOJI_MAP, _EMOJI_CDN


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single broken emoji or link."""
    kind: str          # "emoji" or "link"
    url: str           # the URL that failed
    identifier: str    # emoji ID or link text
    status: int | str  # HTTP status code or error description


@dataclass
class ValidationResult:
    """Aggregate result of message validation."""
    ok: bool = True
    emoji_count: int = 0
    link_count: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "emoji_count": self.emoji_count,
            "link_count": self.link_count,
            "issues": [
                {"kind": i.kind, "url": i.url, "identifier": i.identifier, "status": i.status}
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# URL checker (HEAD with fallback to GET)
# ---------------------------------------------------------------------------

_TIMEOUT = 8  # seconds per request

def _check_url(url: str) -> tuple[bool, int | str]:
    """Return (reachable, status_or_error) for a URL.

    Uses HEAD first (cheap); falls back to GET if HEAD returns 405.
    Follows redirects.  Returns the final HTTP status code on success
    or an error string on failure.
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url,
                method=method,
                headers={"User-Agent": "AgencyCowork-Validator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                code = resp.getcode()
                if code and code < 400:
                    return True, code
                return False, code
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code == 405:
                continue  # retry with GET
            return False, exc.code
        except urllib.error.URLError as exc:
            return False, str(exc.reason)
        except Exception as exc:
            return False, str(exc)
    return False, "unknown"


# ---------------------------------------------------------------------------
# HTML extractors
# ---------------------------------------------------------------------------

# Matches Teams emoji <img> tags produced by build_emoji_html()
_EMOJI_IMG_RE = re.compile(
    r'<img\s[^>]*itemtype="http://schema\.skype\.com/Emoji"[^>]*'
    r'itemid="([^"]+)"[^>]*src="([^"]+)"',
    re.IGNORECASE,
)

# Matches <a href="..."> tags
_LINK_RE = re.compile(
    r'<a\s[^>]*href="([^"]+)"[^>]*>([^<]*)</a>',
    re.IGNORECASE,
)


def _extract_emoji_urls(html: str) -> list[tuple[str, str]]:
    """Return list of (emoji_id, cdn_url) from emoji <img> tags."""
    return _EMOJI_IMG_RE.findall(html)


def _extract_links(html: str) -> list[tuple[str, str]]:
    """Return list of (url, link_text) from <a> tags."""
    return _LINK_RE.findall(html)


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_html(html: str, *, max_workers: int = 10) -> ValidationResult:
    """Validate all emoji CDN images and hyperlinks in the HTML.

    Performs HEAD requests in parallel to check that each URL resolves.
    Returns a ``ValidationResult`` summarising all findings.

    Args:
        html: The Teams-formatted HTML (output of ``markdown_to_teams_html``).
        max_workers: Max parallel HTTP requests.

    Returns:
        A ``ValidationResult`` with ``.ok == True`` when everything resolves.
    """
    result = ValidationResult()

    # Collect all URLs to check:  (url, kind, identifier)
    checks: list[tuple[str, str, str]] = []

    for emoji_id, cdn_url in _extract_emoji_urls(html):
        result.emoji_count += 1
        checks.append((cdn_url, "emoji", emoji_id))

    for url, text in _extract_links(html):
        # Skip mailto: and javascript: links
        if url.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        result.link_count += 1
        checks.append((url, "link", text or url))

    if not checks:
        return result

    # Parallel HEAD checks
    with ThreadPoolExecutor(max_workers=min(max_workers, len(checks))) as pool:
        future_map = {
            pool.submit(_check_url, url): (url, kind, ident)
            for url, kind, ident in checks
        }
        for future in as_completed(future_map):
            url, kind, ident = future_map[future]
            try:
                ok, status = future.result()
            except Exception as exc:
                ok, status = False, str(exc)
            if not ok:
                result.ok = False
                result.issues.append(
                    ValidationIssue(kind=kind, url=url, identifier=ident, status=status)
                )

    return result


def validate_markdown(body: str, **kwargs) -> ValidationResult:
    """Convert markdown to Teams HTML then validate.

    Convenience wrapper that calls ``markdown_to_teams_html()`` first.
    """
    html = markdown_to_teams_html(body)
    return validate_html(html, **kwargs)


# ---------------------------------------------------------------------------
# Static EMOJI_MAP audit (no network needed)
# ---------------------------------------------------------------------------

def audit_emoji_map(*, max_workers: int = 20) -> ValidationResult:
    """Check every Teams ID in EMOJI_MAP against the CDN.

    Useful for periodic validation that the entire map is correct.
    """
    result = ValidationResult()
    checks: list[tuple[str, str, str]] = []

    for shortcode, (teams_id, title, _alt) in EMOJI_MAP.items():
        url = f"{_EMOJI_CDN}/{teams_id}/default/20_f.png"
        checks.append((url, "emoji", f":{shortcode}: → {teams_id}"))
    result.emoji_count = len(checks)

    if not checks:
        return result

    # Deduplicate by teams_id (many shortcodes map to the same ID)
    seen: dict[str, list[str]] = {}
    for url, _kind, ident in checks:
        seen.setdefault(url, []).append(ident)
    unique_checks = [(url, "emoji", idents[0]) for url, idents in seen.items()]

    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_checks))) as pool:
        future_map = {
            pool.submit(_check_url, url): (url, idents)
            for url, idents in seen.items()
        }
        for future in as_completed(future_map):
            url, idents = future_map[future]
            try:
                ok, status = future.result()
            except Exception as exc:
                ok, status = False, str(exc)
            if not ok:
                result.ok = False
                for ident in idents:
                    result.issues.append(
                        ValidationIssue(kind="emoji", url=url, identifier=ident, status=status)
                    )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Teams message HTML — check emoji CDN images and links",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--body",
        help="Markdown body to convert and validate",
    )
    group.add_argument(
        "--html",
        help="Raw Teams HTML to validate (already converted)",
    )
    group.add_argument(
        "--stdin",
        action="store_true",
        help="Read HTML from stdin",
    )
    group.add_argument(
        "--audit-map",
        action="store_true",
        help="Audit the entire EMOJI_MAP against the CDN (no message needed)",
    )

    args = parser.parse_args()

    if args.audit_map:
        print("Auditing entire EMOJI_MAP against Teams CDN...", file=sys.stderr)
        result = audit_emoji_map()
    elif args.body:
        result = validate_markdown(args.body)
    elif args.stdin:
        html = sys.stdin.read()
        result = validate_html(html)
    else:
        result = validate_html(args.html)

    # Output
    output = result.to_dict()
    print(json.dumps(output, indent=2))

    if not result.ok:
        print(
            f"\n❌ VALIDATION FAILED: {len(result.issues)} issue(s) found",
            file=sys.stderr,
        )
        for issue in result.issues:
            print(
                f"  [{issue.kind.upper()}] {issue.identifier} → {issue.status} ({issue.url})",
                file=sys.stderr,
            )
        sys.exit(1)
    else:
        print(
            f"\n✅ All clear: {result.emoji_count} emoji(s), {result.link_count} link(s) validated",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
