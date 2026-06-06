"""Memory write validator — screens content before it persists into agent memory.

Validates text destined for MEMORY.md, CLAUDE.md, Knowledgebase/, or DailyLogs/
to detect behavioural instructions that could alter the agent's future actions.
This complements the prompt guard (which catches injection syntax) by detecting
*semantic* manipulation: natural-language instructions disguised as business
content that would modify agent behaviour across sessions.

Design rationale (SHIELD Security Assessment F-007, 2026-03-24):
  All 9 memory poisoning payloads tested bypassed the prompt guard at 100%
  because they use natural language framing ("compliance requirement",
  "partnership agreement", "action items") with no injection trigger words.
  Regex fundamentally cannot detect these. This module provides heuristic
  detection + provenance tracking + audit logging.

Usage (programmatic)::

    from scripts.memory_guard import screen_memory_write, ContentSource

    result = screen_memory_write(
        content=converted_document_text,
        target="memory/Knowledgebase/Q3-report.md",
        source=ContentSource.SHAREPOINT,
        source_detail="partner@contoso.com via SharePoint",
    )
    if result.requires_review:
        # Present to user for confirmation before writing
        ...
    if result.provenance_tag:
        # Prepend provenance tag to content before writing
        content = result.provenance_tag + "\n\n" + content

Usage (CLI)::

    python scripts/memory_guard.py --text "content" --target memory/MEMORY.md --source email
    python scripts/memory_guard.py --file doc.md --target memory/Knowledgebase/doc.md --source sharepoint

Exit codes: 0 = safe, 1 = requires review, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath


# ---------------------------------------------------------------------------
# Content source classification
# ---------------------------------------------------------------------------

class ContentSource(str, Enum):
    """Where the content originated. Determines trust level."""
    USER = "user"              # Direct user input in session — trusted
    EMAIL = "email"            # Email body/subject — untrusted
    TEAMS = "teams"            # Teams message — untrusted
    SHAREPOINT = "sharepoint"  # SharePoint document (markitdown) — untrusted
    MEETING = "meeting"        # Meeting notes/transcript — untrusted
    TASK = "task"              # Scheduled task output — semi-trusted
    AGENT = "agent"            # Agent-generated content — semi-trusted
    UNKNOWN = "unknown"        # Default — treated as untrusted


# Sources that require validation before memory persistence
_UNTRUSTED_SOURCES = {
    ContentSource.EMAIL,
    ContentSource.TEAMS,
    ContentSource.SHAREPOINT,
    ContentSource.MEETING,
    ContentSource.TASK,
    ContentSource.UNKNOWN,
}

# Internal domains — used by external_email_routing pattern to distinguish
# internal from external recipients. Extend this set for multi-org deployments.
_INTERNAL_DOMAINS: set[str] = {"microsoft.com"}

# High-value targets that warrant extra scrutiny
_CRITICAL_TARGETS = {
    "CLAUDE.md",
    "AGENTS.md",
    "memory/MEMORY.md",
}


# ---------------------------------------------------------------------------
# Behavioural instruction heuristics
# ---------------------------------------------------------------------------

# Patterns that indicate content is trying to modify agent behaviour,
# communication patterns, or email routing. These are NOT prompt injection
# patterns (those are in prompt_guard.py) — they detect natural-language
# instructions that would persist into memory.

_BEHAVIOURAL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "routing_instruction",
        re.compile(
            r"(?:always|must|should|shall|need\s+to)\s+"
            r"(?:include|add|cc|bcc|copy|forward|send|share)\s+"
            r"[^\n]*@[^\s]+",
            re.IGNORECASE,
        ),
        "Instruction to modify email routing or add recipients",
    ),
    (
        "behaviour_modification",
        re.compile(
            r"(?:from\s+now\s+on|going\s+forward|henceforth|in\s+(?:all\s+)?future|"
            r"whenever|each\s+time|next\s+time|"
            r"when(?:ever)?\s+(?:you\s+)?(?:send|reply|email|respond|forward|compose)|"
            r"moving\s+(?:ahead|forward))\s+"
            r"(?:sessions?|conversations?|interactions?|responses?|communications?|,|you\s+)",
            re.IGNORECASE,
        ),
        "Instruction to change behaviour across future sessions",
    ),
    (
        "config_update_instruction",
        re.compile(
            r"(?:update|modify|change|edit|add\s+to|append\s+to)\s+"
            r"(?:your\s+)?(?:CLAUDE\.md|AGENTS\.md|MEMORY\.md|config|settings|rules|instructions)",
            re.IGNORECASE,
        ),
        "Instruction to modify agent configuration files",
    ),
    (
        "compliance_framing",
        re.compile(
            r"(?:compliance|regulatory|legal|audit|policy)\s+"
            r"(?:requirement|mandate|obligation|directive)\s*"
            r"[:\-]?\s*"
            r"(?:all|every|any)",
            re.IGNORECASE,
        ),
        "Authority claim using compliance/legal framing",
    ),
    (
        "action_item_with_agent_target",
        re.compile(
            r"(?:action\s+item|todo|task|instruction)\s*"
            r"[:\-]\s*"
            r"(?:.*?agent|.*?cowork|.*?assistant|.*?AI|.*?bot)",
            re.IGNORECASE,
        ),
        "Action item directed at the agent",
    ),
    (
        "external_email_routing",
        re.compile(
            r"(?:forward|send|email|cc|bcc)\s+"
            r"(?:.*?to\s+)?"
            r"[a-zA-Z0-9._%+-]+@(?!"
            + r"|".join(re.escape(d) for d in sorted(_INTERNAL_DOMAINS))
            + r")[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            re.IGNORECASE,
        ),
        "Instruction to route data to external email address",
    ),
    (
        "hidden_instruction_markers",
        re.compile(
            r"(?:IMPORTANT\s+NOTE\s+FOR\s+AGENT|"
            r"AGENT\s+CONFIGURATION|"
            r"SYSTEM\s+INSTRUCTION|"
            r"NOTE\s+FOR\s+(?:THE\s+)?AI|"
            r"AUTOMATED?\s+INSTRUCTION)",
            re.IGNORECASE,
        ),
        "Explicit marker targeting the agent in content",
    ),
]


# ---------------------------------------------------------------------------
# Screening result
# ---------------------------------------------------------------------------

@dataclass
class BehaviouralFinding:
    pattern_name: str
    description: str
    matched_text: str


@dataclass
class MemoryScreenResult:
    """Result of screening content before memory persistence."""
    safe: bool
    requires_review: bool
    source: str
    target: str
    findings: list[BehaviouralFinding] = field(default_factory=list)
    provenance_tag: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Core screening function
# ---------------------------------------------------------------------------

def screen_memory_write(
    content: str,
    target: str,
    source: ContentSource = ContentSource.UNKNOWN,
    source_detail: str = "",
) -> MemoryScreenResult:
    """Screen content before persisting to agent memory.

    Args:
        content: The text to be written to a memory file.
        target: The relative file path (e.g., "memory/MEMORY.md").
        source: Where the content originated.
        source_detail: Freeform detail (e.g., sender email, document URL).

    Returns:
        MemoryScreenResult indicating whether the write is safe, requires
        human review, and a provenance tag to prepend to the content.
    """
    # Content size guard — reject oversized payloads before any processing
    MAX_CONTENT_SIZE = 100_000  # 100 KB
    if len(content) > MAX_CONTENT_SIZE:
        return MemoryScreenResult(
            safe=False,
            requires_review=True,
            source=source.value,
            target=target,
            findings=[BehaviouralFinding(
                pattern_name="content_size_exceeded",
                description=f"Content length ({len(content)}) exceeds {MAX_CONTENT_SIZE} byte limit",
                matched_text=f"len={len(content)}",
            )],
            reason=f"Content exceeds {MAX_CONTENT_SIZE} byte limit",
        )

    ts = datetime.now(timezone.utc)

    # Sanitize source_detail to prevent HTML comment breakout in provenance tag
    source_detail = (source_detail or "").replace("-->", "—>")

    # Build provenance tag
    provenance_tag = (
        f"<!-- memory-guard: source={source.value}, "
        f"detail={source_detail!r}, "
        f"target={target}, "
        f"screened={ts.strftime('%Y-%m-%dT%H:%M:%SZ')} -->"
    )

    # Trusted sources writing to non-critical targets: pass through
    if source not in _UNTRUSTED_SOURCES:
        return MemoryScreenResult(
            safe=True,
            requires_review=False,
            source=source.value,
            target=target,
            provenance_tag=provenance_tag,
        )

    # Check for behavioural instruction patterns
    findings: list[BehaviouralFinding] = []
    for pattern_name, regex, description in _BEHAVIOURAL_PATTERNS:
        match = regex.search(content)
        if match:
            matched = match.group(0)
            if len(matched) > 120:
                matched = matched[:117] + "..."
            findings.append(BehaviouralFinding(
                pattern_name=pattern_name,
                description=description,
                matched_text=matched,
            ))

    # Determine if review is required — normalize path to defeat traversal tricks
    target_normalized = target.replace("\\", "/")
    target_filename = PurePosixPath(target_normalized).name
    is_critical_target = any(
        target_filename == ct.split("/")[-1] or target_normalized.endswith(ct)
        for ct in _CRITICAL_TARGETS
    )
    has_findings = len(findings) > 0

    requires_review = has_findings or (
        source in _UNTRUSTED_SOURCES and is_critical_target
    )

    reason = ""
    if has_findings:
        pattern_names = ", ".join(f.pattern_name for f in findings)
        reason = f"Behavioural instruction patterns detected: {pattern_names}"
    elif is_critical_target and source in _UNTRUSTED_SOURCES:
        reason = f"Untrusted source ({source.value}) writing to critical target ({target})"

    return MemoryScreenResult(
        safe=not requires_review,
        requires_review=requires_review,
        source=source.value,
        target=target,
        findings=findings,
        provenance_tag=provenance_tag,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def log_memory_screen(result: MemoryScreenResult, content_preview: str = "") -> None:
    """Log a memory screening event to the audit log."""
    ts = datetime.now(timezone.utc)
    preview = content_preview[:200] if content_preview else ""

    entry = {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": result.source,
        "target": result.target,
        "safe": result.safe,
        "requires_review": result.requires_review,
        "reason": result.reason,
        "finding_count": len(result.findings),
        "findings": [asdict(f) for f in result.findings],
        "content_preview": preview,
    }

    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "memory-guard.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Screen content before writing to agent memory",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Content to screen")
    group.add_argument("--file", help="File containing content to screen")
    parser.add_argument("--target", required=True,
                        help="Target memory path (e.g., memory/MEMORY.md)")
    parser.add_argument("--source", default="unknown",
                        choices=[s.value for s in ContentSource],
                        help="Content source")
    parser.add_argument("--source-detail", default="",
                        help="Freeform source detail (sender, URL, etc.)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    args = parser.parse_args()

    if args.file:
        try:
            content = Path(args.file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        content = args.text

    source = ContentSource(args.source)
    result = screen_memory_write(
        content=content,
        target=args.target,
        source=source,
        source_detail=args.source_detail,
    )

    log_memory_screen(result, content_preview=content)

    if args.json_output:
        print(json.dumps(asdict(result), indent=2))
    else:
        if result.safe:
            print(f"SAFE — content can be written to {args.target}")
        else:
            print(f"REVIEW REQUIRED — {result.reason}")
            for f in result.findings:
                print(f"  [{f.pattern_name}] {f.description}")
                print(f"    matched: {f.matched_text[:80]}")
            print(f"\nProvenance tag: {result.provenance_tag}")

    sys.exit(0 if result.safe else 1)


if __name__ == "__main__":
    main()
