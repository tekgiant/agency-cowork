"""Credential scanner for outbound Teams messages.

Scans text for common credential patterns (API keys, JWTs, connection strings,
SAS tokens, passwords, private keys, etc.) and blocks sending if found.

Usage (CLI)::

    python -m scripts.rich.credential_scanner --text "message content"
    python -m scripts.rich.credential_scanner --file draft.html

Exit codes: 0 = clean, 1 = credentials detected, 2 = usage error.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Credential pattern definitions
# ---------------------------------------------------------------------------

# Each entry: (pattern_name, compiled_regex, description)
# Patterns are ordered roughly by severity / specificity.

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # Private keys (PEM-encoded)
    (
        "private_key",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|DSA\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
        "PEM-encoded private key header",
    ),
    # JWT tokens (three base64url segments separated by dots)
    (
        "jwt_token",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        "JSON Web Token (JWT)",
    ),
    # Azure Storage / SAS tokens
    (
        "azure_sas_token",
        re.compile(
            r"(?:sv=\d{4}-\d{2}-\d{2}&.*?sig=[A-Za-z0-9%+/=]{20,})"
            r"|(?:SharedAccessSignature\s+sr=[^\s]{10,})",
            re.IGNORECASE,
        ),
        "Azure SAS token or Shared Access Signature",
    ),
    # Azure Storage account keys (base64, 88 chars)
    (
        "azure_storage_key",
        re.compile(r"(?:AccountKey|account_key)\s*=\s*[A-Za-z0-9+/]{86}=="),
        "Azure Storage account key",
    ),
    # AWS access keys
    (
        "aws_access_key",
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "AWS access key ID",
    ),
    # AWS secret keys (40-char base64 near context keywords)
    (
        "aws_secret_key",
        re.compile(
            r"(?:aws_secret_access_key|secret_access_key|aws_secret)\s*[:=]\s*[A-Za-z0-9+/]{40}",
            re.IGNORECASE,
        ),
        "AWS secret access key",
    ),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    (
        "github_token",
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
        "GitHub personal access / OAuth / app token",
    ),
    # Azure AD / Entra client secrets (~34+ chars, tilde prefix)
    (
        "azure_client_secret",
        re.compile(
            r"(?:client_secret|clientSecret|AZURE_CLIENT_SECRET)\s*[:=]\s*[^\s\"',]{20,}",
            re.IGNORECASE,
        ),
        "Azure AD / Entra client secret",
    ),
    # Generic API key patterns (key=value with long values)
    # Catches: "api_key=xxx", "api_key: xxx", "api_key -> xxx", "api-key xxx"
    (
        "generic_api_key",
        re.compile(
            r"(?:api[_-]?key|apikey|x-api-key|api_secret)\s*(?:[:=]|->)\s*[\"']?[A-Za-z0-9_\-+/]{20,}[\"']?",
            re.IGNORECASE,
        ),
        "Generic API key assignment",
    ),
    # Bearer token in header-like context
    # Catches: "Authorization: Bearer xxx", "Bearer:xxx", "Bearer = xxx",
    # and multi-line "Bearer\n  xxx" via \s* which includes newlines.
    (
        "bearer_token",
        re.compile(
            r"(?:Authorization|Bearer)\s*[:=]\s*(?:Bearer\s*)?[A-Za-z0-9_\-.]{40,}",
            re.IGNORECASE,
        ),
        "Bearer authorization token",
    ),
    # Connection strings (SQL Server, PostgreSQL, MongoDB, Redis)
    (
        "connection_string",
        re.compile(
            r"(?:"
            r"(?:Server|Data\s+Source)\s*=\s*[^;]+;\s*(?:.*?Password|.*?Pwd)\s*=\s*[^;]+"
            r"|mongodb(?:\+srv)?://[^\s\"']{10,}"
            r"|postgres(?:ql)?://[^\s\"']{10,}"
            r"|redis://[^\s\"']{10,}"
            r"|mysql://[^\s\"']{10,}"
            r")",
            re.IGNORECASE,
        ),
        "Database connection string with credentials",
    ),
    # Password / secret assignments (context-dependent)
    (
        "password_assignment",
        re.compile(
            r"(?:password|passwd|pwd|secret|token|credential)\s*[:=]\s*[\"']?[^\s\"',]{8,}[\"']?",
            re.IGNORECASE,
        ),
        "Password or secret value assignment",
    ),
    # Well-known environment variable patterns
    (
        "env_secret",
        re.compile(
            r"(?:AZURE_OPENAI_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN|SLACK_TOKEN|"
            r"SENDGRID_API_KEY|TWILIO_AUTH_TOKEN|STRIPE_SECRET_KEY|DATABASE_URL|"
            r"REDIS_URL|MONGO_URI|SECRET_KEY|ENCRYPTION_KEY)"
            r"\s*=\s*[^\s]{8,}",
            re.IGNORECASE,
        ),
        "Environment variable containing a secret",
    ),
    # Azure OpenAI key pattern (32-char hex)
    (
        "azure_openai_key",
        re.compile(
            r"(?:api[_-]?key|ocp-apim-subscription-key)\s*[:=]\s*[0-9a-f]{32}",
            re.IGNORECASE,
        ),
        "Azure OpenAI / Cognitive Services subscription key",
    ),
]

# Patterns that are too noisy to use alone — only flag if multiple occur or
# if they appear near context keywords.  For v1, the above list is sufficient.

# ---------------------------------------------------------------------------
# Allowlist — known safe patterns that trigger false positives
# ---------------------------------------------------------------------------

_ALLOWLIST: list[re.Pattern] = [
    # Correlation IDs — MUST be strict UUID format (8-4-4-4-12 hex with hyphens)
    # to prevent masking JWTs or other base64 tokens that happen to start with
    # a 36-char prefix.
    re.compile(
        r"CorrelationId:\s*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b",
        re.IGNORECASE,
    ),
    # Git commit SHAs — only match exactly 40 hex chars (not longer base64)
    re.compile(r"(?<![A-Za-z0-9+/])[0-9a-f]{40}(?![A-Za-z0-9+/=])"),
    # UUIDs (common in Teams chat IDs, user IDs, etc.)
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    # Base64 content that is clearly a Teams chat/message ID
    re.compile(r"19:meeting_[A-Za-z0-9+/=]+@thread\.v2"),
    re.compile(r"19:[0-9a-f]+@thread\.(?:v2|tacv2)"),
    re.compile(r"19:[0-9a-f-]+_[0-9a-f-]+@unq\.gbl\.spaces"),
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single credential detection."""

    type: str  # pattern name
    description: str
    match_preview: str  # first 60 chars of the match (redacted)
    line_number: int | None = None


@dataclass
class CredentialScanResult:
    """Result of scanning text for credentials."""

    is_clean: bool
    findings: List[Finding] = field(default_factory=list)
    redacted_text: str = ""


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities for scanning."""
    # Remove tags
    clean = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    clean = html.unescape(clean)
    return clean


def _is_allowlisted(match_text: str) -> bool:
    """Check if a match is a known false positive."""
    for pattern in _ALLOWLIST:
        if pattern.search(match_text):
            return True
    return False


def _redact(match_text: str, max_show: int = 8) -> str:
    """Redact a match, showing only first few chars."""
    if len(match_text) <= max_show:
        return "***"
    return match_text[:max_show] + "***[REDACTED]"


def _url_decode(text: str) -> str:
    """Decode URL percent-encoding (e.g. %3D → =, %3B → ;)."""
    try:
        from urllib.parse import unquote
        return unquote(text)
    except Exception:
        return text


def _decode_html_entities(text: str) -> str:
    """Decode HTML character references (&#115; → s, &amp; → &)."""
    return html.unescape(text)


def _scan_text_variant(
    text: str,
    variant_label: str,
    findings: list[Finding],
    seen_matches: set[str],
) -> None:
    """Scan a single text variant for credential patterns."""
    lines = text.split("\n")
    for pattern_name, regex, description in _PATTERNS:
        for line_num, line in enumerate(lines, start=1):
            for m in regex.finditer(line):
                match_text = m.group(0)

                if match_text in seen_matches:
                    continue

                if _is_allowlisted(match_text):
                    continue

                seen_matches.add(match_text)
                findings.append(
                    Finding(
                        type=pattern_name,
                        description=description,
                        match_preview=_redact(match_text),
                        line_number=line_num,
                    )
                )


def scan_for_credentials(text: str) -> CredentialScanResult:
    """Scan text for credential patterns.

    Args:
        text: The message content to scan. Can be HTML or plain text.

    Returns:
        CredentialScanResult with is_clean=True if no credentials found.

    The scanner now checks multiple decoded variants of the input to defeat
    evasion via HTML attributes, URL-encoding, and HTML entity encoding:
      1. Raw text (catches credentials in HTML attributes/comments)
      2. HTML-stripped + entity-decoded text (original behaviour)
      3. URL-decoded text (catches %3D-encoded connection strings)
      4. HTML entity-decoded raw text (catches &#115;k- API keys)
    """
    findings: list[Finding] = []
    seen_matches: set[str] = set()

    # Variant 1: Scan the RAW text (catches creds in HTML attributes/comments)
    _scan_text_variant(text, "raw", findings, seen_matches)

    # Variant 2: HTML-stripped + entity-decoded (original behaviour)
    if "<" in text and ">" in text:
        plain_text = _strip_html(text)
        _scan_text_variant(plain_text, "html_stripped", findings, seen_matches)
    else:
        plain_text = text

    # Variant 3: URL-decoded (catches %3D, %3B encoded connection strings)
    url_decoded = _url_decode(text)
    if url_decoded != text:
        _scan_text_variant(url_decoded, "url_decoded", findings, seen_matches)

    # Variant 4: HTML entity-decoded (catches &#115;&#107;- API keys)
    entity_decoded = _decode_html_entities(text)
    if entity_decoded != text:
        _scan_text_variant(entity_decoded, "entity_decoded", findings, seen_matches)

    # Build redacted text from the plain version
    redacted = plain_text
    for pattern_name, regex, _ in _PATTERNS:
        redacted = regex.sub(f"[REDACTED-{pattern_name}]", redacted)

    return CredentialScanResult(
        is_clean=len(findings) == 0,
        findings=findings,
        redacted_text=redacted,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan text for credential patterns before sending."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text to scan (inline)")
    group.add_argument("--file", help="File to read and scan")
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON (default: human-readable)"
    )
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")
    else:
        text = args.text

    result = scan_for_credentials(text)

    if args.json:
        output = {
            "is_clean": result.is_clean,
            "finding_count": len(result.findings),
            "findings": [asdict(f) for f in result.findings],
        }
        print(json.dumps(output, indent=2))
    else:
        if result.is_clean:
            print("✅ Clean — no credentials detected.")
        else:
            print(f"🛑 BLOCKED — {len(result.findings)} credential(s) detected:\n")
            for f in result.findings:
                line_info = f" (line {f.line_number})" if f.line_number else ""
                print(f"  • [{f.type}] {f.description}{line_info}")
                print(f"    Preview: {f.match_preview}")
                print()

    return 0 if result.is_clean else 1


if __name__ == "__main__":
    sys.exit(main())
