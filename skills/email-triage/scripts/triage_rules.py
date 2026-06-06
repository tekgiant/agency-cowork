"""Deterministic triage matching rules — pure functions, no I/O.

All functions are stateless and take email message dicts + profile config.
This is the reliability core — every function must be testable in isolation.

Categories (priority order):
    1. VIP → always "urgent" (Layer 1 guarantee)
    2. Noise → always "noise" (auto-archive)
    3. Tier 1 + urgent signals → "urgent"
    4. Tier 1 + in To → "needs_response"
    5. Tier 1 + CC only → "fyi"
    6. Tier 2 + urgent signals → "urgent"
    7. Tier 2 + in To → "needs_response"
    8. Tier 2 + CC only → "fyi"
    9. Calendar auto-responses → "archive"
    10. Unmatched → "skip" (leave in inbox)
"""

import re
from dataclasses import dataclass
from typing import Optional

from scripts.mail_client import (
    get_sender_email,
    get_sender_alias,
    get_sender_name,
    get_to_emails,
    get_cc_emails,
    is_user_in_to,
    is_user_in_cc_only,
    get_recipient_count,
)


# --- ET-10: ReDoS protection for user-provided regex patterns ---

# Patterns that indicate potential ReDoS vulnerability (nested quantifiers)
_REDOS_INDICATORS = re.compile(
    r"(\+|\*|\{[0-9]+,\})\s*(\+|\*|\?|\{[0-9]+,\})"  # nested quantifiers: (a+)+
    r"|(\([^)]*(\+|\*)[^)]*\))\s*(\+|\*|\{)"            # group with quantifier repeated
)
_MAX_PATTERN_LENGTH = 500  # Reject extremely long patterns


def _safe_compile(pattern: str, flags: int = 0) -> Optional[re.Pattern]:
    """Compile a user-provided regex with ReDoS protection.

    Returns compiled pattern, or None if the pattern is unsafe or invalid.
    """
    if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
        return None
    if _REDOS_INDICATORS.search(pattern):
        return None
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


@dataclass
class MatchResult:
    """Result of matching an email against rules."""
    category: str  # urgent, needs_response, fyi, archive, noise, skip
    tier: int  # 0=VIP, 1=Tier1, 2=Tier2, -1=noise, -2=archive, 99=unmatched
    contact_name: str | None = None
    signals: list[str] | None = None
    confidence: float = 1.0


# --- Urgent keyword patterns ---

URGENT_SUBJECT_PATTERNS = [
    re.compile(r"\[URGENT\]", re.IGNORECASE),
    re.compile(r"\[ACTION REQUIRED\]", re.IGNORECASE),
    re.compile(r"\[ESCALATION\]", re.IGNORECASE),
]

URGENT_KEYWORDS = re.compile(
    r"\b(blocker|critical|escalation|ASAP|urgent|"
    r"by EOD|by end of day|decision needed|decision required|"
    r"immediate|time.?sensitive)\b",
    re.IGNORECASE,
)

# --- Needs response patterns ---

NEEDS_RESPONSE_KEYWORDS = re.compile(
    r"\b(your input|please review|can you|could you|would you|"
    r"your thoughts|your feedback|please confirm|let me know|"
    r"what do you think|action item|follow up|assigned to)\b",
    re.IGNORECASE,
)

# --- FYI patterns ---

FYI_KEYWORDS = re.compile(
    r"\b(FYI|for your information|no action needed|"
    r"just a heads up|status update|weekly update|"
    r"meeting notes|recap|for awareness)\b",
    re.IGNORECASE,
)

# --- Archive patterns ---

CALENDAR_RESPONSE_PATTERNS = [
    re.compile(r"^(Accepted|Declined|Tentative):?\s", re.IGNORECASE),
    re.compile(r"^(Canceled|Updated):?\s", re.IGNORECASE),
]

READ_RECEIPT_PATTERN = re.compile(r"^Read:\s", re.IGNORECASE)
OOF_PATTERN = re.compile(r"^(Out of Office|Automatic reply):?\s", re.IGNORECASE)
FORWARD_PATTERN = re.compile(r"^(FW|Fwd):\s", re.IGNORECASE)

# --- @mention detection ---

MENTION_PATTERNS = []  # populated from profile in _build_mention_patterns()

# --- Deadline/due-date detection ---

DEADLINE_KEYWORDS = re.compile(
    r"\b(due\s+(eod|by|today|tomorrow|friday|monday|tuesday|wednesday|thursday)"
    r"|deadline|by\s+(end\s+of\s+day|cob|eow|eob|close\s+of\s+business)"
    r"|due\s+\d{1,2}/\d{1,2})\b",
    re.IGNORECASE,
)


def _match_sender(email_addr: str, alias: str, contact: dict,
                   sender_name: str = "") -> bool:
    """Check if sender matches a contact entry.

    Matching hierarchy:
    1. Exact email match
    2. Exact alias match (part before @)
    3. Alias contained in sender email local part (e.g., 'jsmith' matches 'john.smith')
    4. Display name match (e.g., 'John Smith' contains 'John Smith')
    """
    contact_email = (contact.get("email") or "").lower()
    contact_alias = (contact.get("alias") or "").lower()
    contact_name = (contact.get("name") or "").lower()

    # 1. Exact email
    if contact_email and email_addr == contact_email:
        return True

    # 2. Exact alias
    if contact_alias and alias == contact_alias:
        return True

    # 3. Alias contained in sender local part (handles dotted aliases like john.smith)
    if contact_alias and len(contact_alias) >= 3 and contact_alias in alias:
        return True

    # 4. Display name match
    if contact_name and sender_name and contact_name in sender_name.lower():
        return True

    return False


def is_noise(msg: dict, profile: dict) -> bool:
    """Check if email matches noise filter patterns. Fast, first pass."""
    noise = profile.get("noise_filters", {})
    sender_email = get_sender_email(msg)
    subject = msg.get("Subject", "")

    # Exact sender match
    for pattern in noise.get("senders", []):
        if sender_email == pattern.lower():
            return True

    # Domain match
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    for d in noise.get("domains", []):
        if domain == d.lower():
            return True

    # Subject regex match (ET-10: ReDoS-safe compilation)
    for pattern in noise.get("subjects", []):
        compiled = _safe_compile(pattern, re.IGNORECASE)
        if compiled and compiled.search(subject):
            return True

    return False


def match_vip(msg: dict, profile: dict) -> Optional[dict]:
    """Check if sender is a VIP contact. Layer 1 guarantee."""
    sender_email = get_sender_email(msg)
    sender_alias = get_sender_alias(msg)
    sender_name = get_sender_name(msg)

    for contact in profile.get("vip_contacts", []):
        if _match_sender(sender_email, sender_alias, contact, sender_name):
            return contact
    return None


def match_tier1(msg: dict, profile: dict) -> Optional[dict]:
    """Check if sender is a Tier 1 contact."""
    sender_email = get_sender_email(msg)
    sender_alias = get_sender_alias(msg)
    sender_name = get_sender_name(msg)

    for contact in profile.get("tier1_contacts", []):
        if _match_sender(sender_email, sender_alias, contact, sender_name):
            return contact
    return None


def match_tier2(msg: dict, profile: dict) -> bool:
    """Check if email matches Tier 2 patterns (DLs, subject keywords)."""
    tier2 = profile.get("tier2_patterns", {})
    subject = msg.get("Subject", "")
    all_recipients = get_to_emails(msg) + get_cc_emails(msg)

    # Check To/CC patterns (ET-10: ReDoS-safe compilation)
    for pattern in tier2.get("to_cc", []):
        regex_str = pattern.replace("*", ".*")
        compiled = _safe_compile(regex_str, re.IGNORECASE)
        if compiled:
            for recipient in all_recipients:
                if compiled.match(recipient):
                    return True

    # Check subject patterns (ET-10: ReDoS-safe compilation)
    for pattern in tier2.get("subjects", []):
        compiled = _safe_compile(pattern, re.IGNORECASE)
        if compiled and compiled.search(subject):
            return True

    return False


def extract_signals(msg: dict, profile: dict | None = None) -> dict:
    """Extract classification signals from an email."""
    subject = msg.get("Subject", "")
    body_preview = msg.get("BodyPreview", "")
    text = f"{subject} {body_preview}"

    signals = {
        "importance_high": msg.get("Importance") == "High",
        "has_urgent_subject_tag": any(p.search(subject) for p in URGENT_SUBJECT_PATTERNS),
        "has_urgent_keywords": bool(URGENT_KEYWORDS.search(text)),
        "has_response_keywords": bool(NEEDS_RESPONSE_KEYWORDS.search(text)),
        "has_fyi_keywords": bool(FYI_KEYWORDS.search(text)),
        "is_calendar_response": any(p.search(subject) for p in CALENDAR_RESPONSE_PATTERNS),
        "is_read_receipt": bool(READ_RECEIPT_PATTERN.search(subject)),
        "is_oof": bool(OOF_PATTERN.search(subject)),
        "is_draft": msg.get("IsDraft", False),
        "has_attachments": msg.get("HasAttachments", False),
        "recipient_count": get_recipient_count(msg),
        "is_read": msg.get("IsRead", False),
        # New signal types
        "is_forwarded": bool(FORWARD_PATTERN.search(subject)),
        "has_deadline": bool(DEADLINE_KEYWORDS.search(text)),
        "has_mention": _check_mentions(text, profile) if profile else False,
    }

    # Collect human-readable signal list
    active = [k for k, v in signals.items() if v is True]
    signals["active_signals"] = active

    return signals


def _check_mentions(text: str, profile: dict | None) -> bool:
    """Check if the email body mentions the user by name or alias."""
    if not profile:
        return False
    user = profile.get("user", {})
    name = user.get("display_name", "")
    alias = user.get("alias", "")

    # Build patterns from user identity
    patterns = []
    if name:
        # "@First Last" or "@First" — at-mention style
        parts = name.split()
        patterns.append(re.compile(rf"@{re.escape(name)}\b", re.IGNORECASE))
        if parts:
            patterns.append(re.compile(rf"@{re.escape(parts[0])}\b", re.IGNORECASE))
        # Direct address: "FirstName," or "Hi FirstName" or "FirstName -"
        if parts:
            patterns.append(re.compile(
                rf"(?:^|[\n,;])\s*(?:Hi|Hey|Hello|Dear|Thanks|Thank you)?\s*{re.escape(parts[0])}\s*[,\-]",
                re.IGNORECASE,
            ))
    if alias:
        patterns.append(re.compile(rf"@{re.escape(alias)}\b", re.IGNORECASE))

    return any(p.search(text) for p in patterns)


def classify(msg: dict, profile: dict) -> MatchResult:
    """Classify an email into a triage category.

    This is the main entry point. Applies rules in priority order.
    Returns a MatchResult with category, tier, contact info, and signals.
    """
    user_email = profile.get("user", {}).get("email", "").lower()
    subject = msg.get("Subject", "")
    signals = extract_signals(msg, profile)

    # Skip drafts
    if signals["is_draft"]:
        return MatchResult("skip", 99, signals=["is_draft"])

    # --- Layer 1: VIP (NEVER skip) ---
    vip = match_vip(msg, profile)
    if vip:
        return MatchResult(
            category="urgent",
            tier=0,
            contact_name=vip.get("name"),
            signals=["vip_sender"] + signals["active_signals"],
            confidence=1.0,
        )

    # --- Noise filter ---
    if is_noise(msg, profile):
        return MatchResult("noise", -1, signals=["noise_filter"])

    # --- Calendar/read receipt/OOF → archive ---
    if signals["is_calendar_response"] or signals["is_read_receipt"]:
        return MatchResult("archive", -2, signals=signals["active_signals"])

    if signals["is_oof"]:
        # OOF from Tier 1 on active thread → keep as fyi
        t1 = match_tier1(msg, profile)
        if t1:
            return MatchResult("fyi", 1, contact_name=t1.get("name"),
                               signals=["oof_from_tier1"])
        return MatchResult("archive", -2, signals=["oof_auto_archive"])

    # --- Tier 1 contacts ---
    t1 = match_tier1(msg, profile)
    if t1:
        # Tier 1 + urgent signals → urgent
        if (signals["importance_high"] or signals["has_urgent_subject_tag"]
                or signals["has_urgent_keywords"]):
            return MatchResult("urgent", 1, contact_name=t1.get("name"),
                               signals=signals["active_signals"])

        # Tier 1 + deadline → urgent (e.g., "Due EOD" from Lisa Vincent)
        if signals["has_deadline"]:
            return MatchResult("urgent", 1, contact_name=t1.get("name"),
                               signals=["tier1_deadline"] + signals["active_signals"])

        # Tier 1 + user in To → needs_response
        if user_email and is_user_in_to(msg, user_email):
            return MatchResult("needs_response", 1, contact_name=t1.get("name"),
                               signals=["tier1_in_to"] + signals["active_signals"])

        # Tier 1 + forwarded to me → needs_response (forwarded = personal action)
        if signals["is_forwarded"] and user_email and is_user_in_to(msg, user_email):
            return MatchResult("needs_response", 1, contact_name=t1.get("name"),
                               signals=["tier1_forwarded"] + signals["active_signals"])

        # Tier 1 + @mention → needs_response
        if signals["has_mention"]:
            return MatchResult("needs_response", 1, contact_name=t1.get("name"),
                               signals=["tier1_mention"] + signals["active_signals"])

        # Tier 1 + has response keywords → needs_response
        if signals["has_response_keywords"]:
            return MatchResult("needs_response", 1, contact_name=t1.get("name"),
                               signals=signals["active_signals"])

        # Tier 1 + CC only or FYI → fyi
        if user_email and is_user_in_cc_only(msg, user_email):
            return MatchResult("fyi", 1, contact_name=t1.get("name"),
                               signals=["tier1_cc_only"])

        # Tier 1 default → needs_response (safer than fyi)
        return MatchResult("needs_response", 1, contact_name=t1.get("name"),
                           signals=["tier1_default_needs_response"])

    # --- Tier 2 patterns ---
    if match_tier2(msg, profile):
        # Tier 2 + urgent signals
        if (signals["importance_high"] or signals["has_urgent_subject_tag"]
                or signals["has_urgent_keywords"]):
            return MatchResult("urgent", 2, signals=signals["active_signals"])

        # Tier 2 + user in To → needs_response
        if user_email and is_user_in_to(msg, user_email):
            return MatchResult("needs_response", 2,
                               signals=["tier2_in_to"] + signals["active_signals"])

        # Tier 2 + CC only → fyi
        if user_email and is_user_in_cc_only(msg, user_email):
            return MatchResult("fyi", 2, signals=["tier2_cc_only"])

        # Tier 2 + FYI keywords → fyi
        if signals["has_fyi_keywords"]:
            return MatchResult("fyi", 2, signals=signals["active_signals"])

        # Tier 2 + large DL with no direct ask → fyi
        if signals["recipient_count"] >= 5 and not signals["has_response_keywords"]:
            return MatchResult("fyi", 2, signals=["tier2_large_dl"])

        # Tier 2 default → needs_response if in To, fyi otherwise
        if user_email and is_user_in_to(msg, user_email):
            return MatchResult("needs_response", 2, signals=["tier2_default_to"])
        return MatchResult("fyi", 2, signals=["tier2_default_fyi"])

    # --- Unmatched sender: direct-TO + signals → needs_response ---
    # Any non-noise sender who emails Yang directly in TO with active signals
    if user_email and is_user_in_to(msg, user_email):
        # @mention or deadline from anyone → needs_response
        if signals["has_mention"] or signals["has_deadline"]:
            return MatchResult("needs_response", 3,
                               signals=["unknown_direct_mention"] + signals["active_signals"])

        # Forwarded directly to me → needs_response
        if signals["is_forwarded"]:
            return MatchResult("needs_response", 3,
                               signals=["unknown_forwarded_to"] + signals["active_signals"])

        # Response keywords + direct TO → needs_response
        if signals["has_response_keywords"]:
            return MatchResult("needs_response", 3,
                               signals=["unknown_to_response_kw"] + signals["active_signals"])

        # Urgent keywords from unknown sender → needs_response (not urgent — unknown trust)
        if signals["has_urgent_keywords"] or signals["importance_high"]:
            return MatchResult("needs_response", 3,
                               signals=["unknown_to_urgent"] + signals["active_signals"])

        # Direct TO with small recipient count (personal email, not DL blast) → fyi
        if signals["recipient_count"] <= 3:
            return MatchResult("fyi", 3,
                               signals=["unknown_direct_to_small"])

    # --- @mention in CC-only from unknown sender → fyi ---
    if signals["has_mention"]:
        return MatchResult("fyi", 3,
                           signals=["unknown_cc_mention"] + signals["active_signals"])

    # --- Unmatched → skip ---
    return MatchResult("skip", 99, signals=["unmatched"])
