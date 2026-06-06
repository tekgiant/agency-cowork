"""Prompt injection scanner for untrusted external content.

Scans text from emails, Teams messages, SharePoint documents, and task prompts
for common prompt injection attack vectors. Returns structured results with
severity levels and matched patterns.

Usage (CLI)::

    python scripts/prompt_guard.py --text "content to scan"
    python scripts/prompt_guard.py --file message.txt
    python scripts/prompt_guard.py --text "..." --source email --json

Exit codes: 0 = clean, 1 = injection detected, 2 = usage error.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

CRITICAL = "critical"  # Direct instruction override / system prompt hijack
HIGH = "high"          # Role injection, tool/function call injection
MEDIUM = "medium"      # Social engineering, output manipulation
LOW = "low"            # Suspicious but possibly benign

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Each entry: (pattern_name, compiled_regex, description, severity)

_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    # --- CRITICAL: System prompt override ---
    (
        "ignore_instructions",
        re.compile(
            r"(?:ignore|disregard|forget|override|bypass)\s+"
            r"(?:all\s+)?(?:previous|prior|above|earlier|existing|your)\s+"
            r"(?:instructions|prompts?|rules?|guidelines?|constraints?|directives?)",
            re.IGNORECASE,
        ),
        "Attempt to override system instructions",
        CRITICAL,
    ),
    (
        "new_system_prompt",
        re.compile(
            r"(?:new|updated?|revised?|replacement)\s+"
            r"(?:system\s+)?(?:prompt|instructions?|directives?)\s*[:\-]",
            re.IGNORECASE,
        ),
        "Attempt to inject a new system prompt",
        CRITICAL,
    ),
    (
        "you_are_now",
        re.compile(
            r"(?:you\s+are\s+now|from\s+now\s+on\s+you\s+are|"
            r"your\s+new\s+(?:role|identity|persona)\s+is|"
            r"you\s+(?:must|should|shall)\s+now\s+(?:act|behave|respond)\s+as)",
            re.IGNORECASE,
        ),
        "Attempt to redefine agent identity",
        CRITICAL,
    ),
    (
        "instruction_delimiter",
        re.compile(
            r"(?:<\s*/?(?:system|s|SYS|INST|instructions?|rules?)\s*>|"
            r"\[\s*(?:INST|SYS(?:TEM)?|SYSTEM_PROMPT)\s*\]|"
            r"<<\s*SYS\s*>>|"
            r"###\s*(?:System|SYSTEM|Instructions?)\s*(?:Prompt)?:)",
            re.IGNORECASE,
        ),
        "Fake instruction delimiter tags",
        CRITICAL,
    ),

    # --- HIGH: Role / tool injection ---
    (
        "roleplay_injection",
        re.compile(
            r"(?:pretend|imagine|act\s+as\s+if|roleplay|simulate|play\s+the\s+role)\s+"
            r"(?:you\s+are|that\s+you|to\s+be|you're)\s+",
            re.IGNORECASE,
        ),
        "Attempt to make agent adopt a different persona",
        HIGH,
    ),
    (
        "tool_invocation",
        re.compile(
            r"(?:call|invoke|execute|run|trigger|use)\s+(?:the\s+)?(?:function|tool|command|api|endpoint|script)\s+",
            re.IGNORECASE,
        ),
        "Attempt to direct agent to invoke specific tools",
        HIGH,
    ),
    (
        "shell_injection",
        re.compile(
            r"(?:^|[\s;|&])"   # start or after separator
            r"(?:"
            r"(?:&&|\|\||;)\s*\w+"              # cmd1 && cmd2
            r"|`[^`]+`"                          # backtick execution
            r"|\$\([^)]+\)"                      # $(cmd) subshell
            r"|>\s*/\w+|>>\s*/\w+"               # redirect to file
            r"|(?:rm|del|format|shutdown|kill|stop-process)\s" # destructive cmds
            r")",
            re.IGNORECASE,
        ),
        "Shell metacharacters or dangerous command patterns",
        HIGH,
    ),
    (
        "data_exfiltration",
        re.compile(
            r"(?:forward|send|email|post|upload|share|exfiltrate|transmit)\s+"
            r"(?:all|every|the|my|your|this)\s+"
            r"(?:emails?|messages?|files?|documents?|data|secrets?|keys?|passwords?|credentials?|tokens?)",
            re.IGNORECASE,
        ),
        "Instruction to exfiltrate data via outbound channels",
        HIGH,
    ),

    # --- MEDIUM: Output manipulation / social engineering ---
    (
        "output_manipulation",
        re.compile(
            r"(?:respond|reply|answer|output|return|print|display)\s+"
            r"(?:only\s+with|exactly|nothing\s+(?:but|except)|"
            r"with\s+(?:just|only)|the\s+(?:exact|following))",
            re.IGNORECASE,
        ),
        "Attempt to control agent output format",
        MEDIUM,
    ),
    (
        "false_authority",
        re.compile(
            r"(?:the\s+(?:admin|administrator|system|owner|user|manager)\s+"
            r"(?:has\s+)?(?:authorized|approved|instructed|confirmed|requested|requires?)|"
            r"(?:as\s+(?:the|an?)\s+(?:admin|administrator|system\s+admin|owner)))",
            re.IGNORECASE,
        ),
        "False authority claim to bypass controls",
        MEDIUM,
    ),
    (
        "urgency_override",
        re.compile(
            r"(?:this\s+is\s+(?:urgent|critical|emergency|time-sensitive)|"
            r"(?:override|bypass|skip|disable)\s+(?:security|safety|confirmation|verification|checks?)|"
            r"do\s+(?:this|it)\s+(?:immediately|now|right\s+away)\s+without\s+(?:asking|checking|confirming))",
            re.IGNORECASE,
        ),
        "Urgency-based security bypass attempt",
        MEDIUM,
    ),
    (
        "hidden_instruction",
        re.compile(
            r"(?:hidden\s+instruction|secret\s+(?:instruction|command|prompt)|"
            r"invisible\s+(?:text|instruction)|"
            r"(?:do\s+not|don't)\s+(?:show|display|reveal)\s+this\s+(?:to|for)\s+the\s+user)",
            re.IGNORECASE,
        ),
        "Attempt to hide instructions from user review",
        MEDIUM,
    ),
    (
        "context_manipulation",
        re.compile(
            r"(?:the\s+user\s+(?:said|asked|wants|requested|confirmed)|"
            r"(?:user|human)\s+(?:message|input|request)\s*:\s+|"
            r"previous\s+(?:conversation|context|response)\s*:\s+)",
            re.IGNORECASE,
        ),
        "Fake conversation context injection",
        MEDIUM,
    ),

    # --- LOW: Suspicious but ambiguous ---
    (
        "encoded_payload",
        re.compile(
            r"(?:(?:base64|b64)\s*:\s*[A-Za-z0-9+/=]{40,}|"
            r"\\u[0-9a-fA-F]{4}(?:\\u[0-9a-fA-F]{4}){3,}|"
            r"\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){5,}|"
            r"(?:eval|decode|unescape)\s*\()",
            re.IGNORECASE,
        ),
        "Encoded payload or eval-style execution",
        LOW,
    ),
    (
        "repetitive_override",
        re.compile(
            r"(?:(?:IMPORTANT|NOTE|WARNING|ATTENTION|CRITICAL|REMEMBER)\s*:\s*){2,}|"
            r"(?:you\s+(?:MUST|SHOULD|SHALL)\s+){2,}",
            re.IGNORECASE,
        ),
        "Repetitive emphasis suggesting adversarial prompt",
        LOW,
    ),
    (
        "do_anything_now",
        re.compile(
            r"(?:DAN|do\s+anything\s+now|jailbreak|unrestricted\s+mode|"
            r"developer\s+mode|god\s+mode|no\s+(?:rules?|restrictions?|limits?)\s+mode)",
            re.IGNORECASE,
        ),
        "Known jailbreak pattern (DAN, developer mode, etc.)",
        HIGH,
    ),
    (
        "markdown_injection",
        re.compile(
            r"!\[.*?\]\(https?://[^\s)]+\)|"          # image exfil ![](url)
            r"\[.*?\]\((?:javascript|data|vbscript):", # link with script proto
            re.IGNORECASE,
        ),
        "Markdown-based data exfiltration or script injection",
        HIGH,
    ),
    (
        "prompt_leak_request",
        re.compile(
            r"(?:(?:show|print|display|reveal|output|repeat|dump)\s+"
            r"(?:your|the|system|initial|original|full)\s+"
            r"(?:system\s+)?(?:prompt|instructions?|rules?|guidelines?|configuration))",
            re.IGNORECASE,
        ),
        "Request to leak system prompt or configuration",
        MEDIUM,
    ),
]


# ---------------------------------------------------------------------------
# Allowlist for false positives
# ---------------------------------------------------------------------------

_ALLOWLIST: list[re.Pattern] = [
    # Discussions about prompt injection (security docs, code reviews)
    re.compile(
        r"(?:prompt\s+injection\s+(?:attack|technique|example|detection|prevention|scanner)|"
        r"(?:how|what)\s+(?:to|is)\s+(?:a\s+)?prompt\s+injection|"
        r"threat\s+model.*prompt\s+injection|"
        r"security\s+(?:audit|review|scan).*injection)",
        re.IGNORECASE,
    ),
    # Code/regex patterns being discussed (contains pattern text but is about scanning)
    re.compile(
        r"(?:re\.compile|regex|pattern|_PATTERNS\s*=|detection_pattern|scan_for)",
        re.IGNORECASE,
    ),
    # Documentation / README content
    re.compile(
        r"(?:SKILL\.md|README\.md|AGENTS\.md|threatmodel\.md|CLAUDE\.md)",
        re.IGNORECASE,
    ),
    # Quoted/attributed content being summarized (the agent summarizing an email)
    re.compile(
        r"(?:the\s+email\s+(?:says|contains|reads|states)|"
        r"the\s+message\s+(?:says|contains|reads|states)|"
        r"quoting\s+from|according\s+to\s+the\s+email)",
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Core scanning function
# ---------------------------------------------------------------------------

@dataclass
class InjectionFinding:
    pattern_name: str
    description: str
    severity: str
    matched_text: str


@dataclass
class InjectionScanResult:
    clean: bool
    findings: list[InjectionFinding] = field(default_factory=list)
    max_severity: str = ""
    source: str = ""
    scanned_length: int = 0

    def __post_init__(self):
        if self.findings and not self.max_severity:
            severity_order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
            self.max_severity = min(
                (f.severity for f in self.findings),
                key=lambda s: severity_order.get(s, 99),
            )


def _is_allowlisted(text: str) -> bool:
    """Check if the text matches an allowlist pattern (likely benign discussion)."""
    return any(pat.search(text) for pat in _ALLOWLIST)


# ---------------------------------------------------------------------------
# Text normalisation — applied before pattern matching to defeat evasion
# ---------------------------------------------------------------------------

# Zero-width and invisible characters that attackers insert between trigger
# words to break regex matches while remaining visually identical.
_INVISIBLE_RE = re.compile(
    "["
    "\u00ad"   # soft hyphen
    "\u2060"   # word joiner
    "\ufeff"   # BOM / zero-width no-break space
    "\u034f"   # combining grapheme joiner
    "\u061c"   # Arabic letter mark
    "\u115f"   # Hangul Choseong filler
    "\u1160"   # Hangul Jungseong filler
    "\u17b4"   # Khmer vowel inherent Aq
    "\u17b5"   # Khmer vowel inherent Aa
    "\u180e"   # Mongolian vowel separator
    "\u2000-\u200f"
    "\u202a-\u202e"  # bidi overrides
    "\u2066-\u2069"  # bidi isolates
    "\ufff9-\ufffb"  # interlinear annotations
    "]+"
)


def _normalise_text(text: str) -> str:
    """Normalise untrusted text to defeat common evasion techniques.

    1. NFKD decomposition  — collapses fullwidth chars (ignore → ignore)
       and many confusable Unicode codepoints to their ASCII base forms.
    2. Strip invisible / zero-width characters — defeats ZWS/ZWNJ/soft-hyphen
       injection that breaks word boundaries without visible effect.
    3. Decode HTML character references — defeats &#105;gnore → ignore.
    4. Case-fold (the existing regexes already use IGNORECASE, but folding
       catches edge cases in Turkish-I etc.).

    The original text is still available for matched_text reporting; only the
    normalised version is used for pattern matching.
    """
    # 1. NFKD normalisation (fullwidth, compatibility decomposition)
    text = unicodedata.normalize("NFKD", text)

    # 2. Strip invisible / zero-width characters
    text = _INVISIBLE_RE.sub("", text)

    # 3. Decode HTML character references (&#105; → i, &amp; → &, etc.)
    text = html.unescape(text)

    # 4. Case-fold for locale-safe lowering (not strictly required given
    #    IGNORECASE, but prevents edge cases)
    # NOTE: we do NOT casefold here because the regexes use IGNORECASE;
    # casefolding would break the matched_text offset alignment.

    return text


def scan_for_injections(
    text: str,
    source: str = "unknown",
) -> InjectionScanResult:
    """Scan text for prompt injection patterns.

    Args:
        text: The untrusted text to scan.
        source: Where the text came from (email, teams, task, monitor, etc.)

    Returns:
        InjectionScanResult with findings (if any).
    """
    # Normalise BEFORE the empty-text guard so zero-width-only payloads
    # are stripped and do not short-circuit scanning.
    normalised = _normalise_text(text) if text else ""

    if not normalised or not normalised.strip():
        return InjectionScanResult(clean=True, source=source, scanned_length=0)

    # Determine if text is allowlisted (likely benign security discussion).
    # CHANGED: allowlist now REDUCES severity to LOW instead of suppressing
    # detection entirely.  This prevents the allowlist-abuse bypass where an
    # attacker embeds "threatmodel.md" to disable the whole scanner.
    # Run on normalised text to prevent Unicode-escaped allowlist terms from re-enabling the bypass
    is_allowlisted = _is_allowlisted(normalised)

    findings: list[InjectionFinding] = []

    for pattern_name, regex, description, severity in _PATTERNS:
        match = regex.search(normalised)
        if match:
            matched = match.group(0)
            # Truncate matched text for logging
            if len(matched) > 120:
                matched = matched[:117] + "..."

            # If allowlisted, demote severity to LOW instead of skipping
            effective_severity = LOW if is_allowlisted else severity

            findings.append(InjectionFinding(
                pattern_name=pattern_name,
                description=description,
                severity=effective_severity,
                matched_text=matched,
            ))

    return InjectionScanResult(
        clean=len(findings) == 0,
        findings=findings,
        source=source,
        scanned_length=len(normalised),
    )


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parent.parent / "skills" / "teams" / "logs"
_MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
_DAILY_LOGS_DIR = _MEMORY_DIR / "DailyLogs"


def log_injection_event(
    result: InjectionScanResult,
    text_preview: str = "",
) -> None:
    """Log an injection detection event to JSONL and daily memory log."""
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = ts.strftime("%Y-%m-%d")

    # Truncated preview for logging (no secrets)
    preview = text_preview[:200] if text_preview else ""

    entry = {
        "timestamp": ts_str,
        "source": result.source,
        "max_severity": result.max_severity,
        "finding_count": len(result.findings),
        "findings": [asdict(f) for f in result.findings],
        "text_preview": preview,
        "scanned_length": result.scanned_length,
    }

    # 1. JSONL log
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = log_dir / "prompt-guard.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

    # 2. Daily memory log
    try:
        if _MEMORY_DIR.exists():
            _DAILY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            daily_log = _DAILY_LOGS_DIR / f"{date_str}.md"
            patterns = ", ".join(f.pattern_name for f in result.findings)
            md = (
                f"\n### ⚠️ Prompt Injection Detected [{ts.strftime('%H:%M')}]\n"
                f"- **Source:** {result.source}\n"
                f"- **Severity:** {result.max_severity}\n"
                f"- **Patterns:** {patterns}\n"
                f"- **Preview:** {preview[:100]}\n"
            )
            with open(daily_log, "a", encoding="utf-8") as f:
                f.write(md)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan text for prompt injection patterns",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text to scan")
    group.add_argument("--file", help="File to scan")
    parser.add_argument("--source", default="cli",
                        help="Source label (email, teams, task, monitor)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    args = parser.parse_args()

    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        text = args.text

    result = scan_for_injections(text, source=args.source)

    if args.json_output:
        print(json.dumps(asdict(result), indent=2))
    else:
        if result.clean:
            print(f"✓ Clean ({result.scanned_length} chars scanned)")
        else:
            print(f"⚠ INJECTION DETECTED — {len(result.findings)} finding(s), "
                  f"max severity: {result.max_severity}")
            for f in result.findings:
                print(f"  [{f.severity}] {f.pattern_name}: {f.description}")
                print(f"    matched: {f.matched_text[:80]}")

    sys.exit(0 if result.clean else 1)


if __name__ == "__main__":
    main()
