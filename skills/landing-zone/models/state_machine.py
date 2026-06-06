"""Landing Zone state machine — canonical states, transitions, and gating rules."""

from enum import Enum
from typing import Any


class LZState(Enum):
    """Canonical Landing Zone requirement states."""
    NEW = "New"
    STRAWMAN = "Strawman"
    WELL_DEFINED = "Well defined"
    READY_FOR_ARCH_RESPONSE = "Ready for Architecture Response"
    GRADED_POR_PENDING = "Graded - POR Pending"
    AT_RISK = "At Risk"
    CLOSED_POR = "Closed POR"
    CLOSED = "Closed"
    # ADO variations that map to canonical states
    COMMITTED = "Committed"
    REMOVED = "Removed"
    ACTIVE = "Active"


# Map ADO state strings (case-insensitive) to canonical enum
_STATE_ALIASES: dict[str, LZState] = {}
for _s in LZState:
    _STATE_ALIASES[_s.value.lower()] = _s
# Extra aliases
_STATE_ALIASES["graded por pending"] = LZState.GRADED_POR_PENDING
_STATE_ALIASES["well-defined"] = LZState.WELL_DEFINED
_STATE_ALIASES["ready for arch response"] = LZState.READY_FOR_ARCH_RESPONSE
_STATE_ALIASES["closed - por"] = LZState.CLOSED_POR
_STATE_ALIASES["obsolete"] = LZState.CLOSED
_STATE_ALIASES["duplicate"] = LZState.CLOSED


def parse_state(state_str: str) -> LZState | None:
    """Parse an ADO state string into a canonical LZState."""
    if not state_str:
        return None
    return _STATE_ALIASES.get(state_str.strip().lower())


# Allowed transitions: from_state -> set of valid target states
ALLOWED_TRANSITIONS: dict[LZState, set[LZState]] = {
    LZState.NEW: {LZState.STRAWMAN, LZState.WELL_DEFINED, LZState.CLOSED, LZState.REMOVED},
    LZState.STRAWMAN: {LZState.WELL_DEFINED, LZState.CLOSED, LZState.REMOVED},
    LZState.WELL_DEFINED: {LZState.READY_FOR_ARCH_RESPONSE, LZState.CLOSED, LZState.REMOVED},
    LZState.READY_FOR_ARCH_RESPONSE: {LZState.GRADED_POR_PENDING, LZState.AT_RISK, LZState.CLOSED, LZState.REMOVED},
    LZState.GRADED_POR_PENDING: {LZState.CLOSED_POR, LZState.AT_RISK, LZState.CLOSED, LZState.REMOVED},
    LZState.AT_RISK: {LZState.READY_FOR_ARCH_RESPONSE, LZState.GRADED_POR_PENDING, LZState.CLOSED, LZState.REMOVED},
    LZState.CLOSED_POR: {LZState.CLOSED, LZState.REMOVED},
    LZState.ACTIVE: {LZState.STRAWMAN, LZState.WELL_DEFINED, LZState.READY_FOR_ARCH_RESPONSE, LZState.CLOSED},
    LZState.COMMITTED: {LZState.CLOSED_POR, LZState.CLOSED},
}

# Terminal states
TERMINAL_STATES = {LZState.CLOSED, LZState.CLOSED_POR, LZState.REMOVED}

# States that count as "grading complete"
GRADED_STATES = {LZState.GRADED_POR_PENDING, LZState.CLOSED_POR, LZState.COMMITTED}


def can_move_to_ready(item: dict[str, Any]) -> tuple[bool, str]:
    """Check if an item can move to Ready for Architecture Response.

    Gate: Minimum/Target set AND arch response teams listed.
    """
    reasons = []
    if not item.get("minimum"):
        reasons.append("Minimum not set")
    if not item.get("target"):
        reasons.append("Target not set")
    teams = item.get("arch_response_teams", [])
    if not teams:
        reasons.append("No Architecture Response teams identified")
    if reasons:
        return False, "; ".join(reasons)
    return True, "OK"


def can_move_to_graded(item: dict[str, Any]) -> tuple[bool, str]:
    """Check if an item can move to Graded POR Pending.

    Gate: All listed teams have provided grades.
    """
    teams = item.get("arch_response_teams", [])
    if not teams:
        return False, "No Architecture Response teams identified"
    ungraded = [t.get("team", "?") for t in teams if not t.get("grade")]
    if ungraded:
        return False, f"Missing grades from: {', '.join(ungraded)}"
    return True, "OK"


def can_move_to_closed_por(item: dict[str, Any]) -> tuple[bool, str]:
    """Check if an item can move to Closed POR.

    Gate: Fully graded AND POR field is non-empty.
    """
    graded_ok, graded_reason = can_move_to_graded(item)
    if not graded_ok:
        return False, f"Not fully graded: {graded_reason}"
    if not item.get("por"):
        return False, "POR field not set"
    return True, "OK"


def is_at_risk(item: dict[str, Any]) -> tuple[bool, str]:
    """Check if an item should be flagged At Risk.

    Trigger: Any supporting team indicates Minimum not feasible.
    """
    teams = item.get("arch_response_teams", [])
    at_risk_teams = []
    for t in teams:
        grade = (t.get("grade") or "").lower()
        if "not feasible" in grade or "at risk" in grade or "cannot" in grade:
            at_risk_teams.append(t.get("team", "?"))
    if at_risk_teams:
        return True, f"At risk from: {', '.join(at_risk_teams)}"
    return False, "No risk signals"


def validate_transition(
    item: dict[str, Any], target_state: LZState
) -> tuple[bool, str]:
    """Validate a proposed state transition.

    Returns (ok, reason).
    """
    current = parse_state(item.get("state", ""))
    if current is None:
        return False, f"Unknown current state: {item.get('state')}"

    if target_state in TERMINAL_STATES and target_state in {LZState.CLOSED, LZState.REMOVED}:
        return True, "Terminal state always allowed"

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target_state not in allowed:
        return False, f"Transition {current.value} → {target_state.value} not allowed"

    # Check gating rules for specific targets
    if target_state == LZState.READY_FOR_ARCH_RESPONSE:
        return can_move_to_ready(item)
    if target_state == LZState.GRADED_POR_PENDING:
        return can_move_to_graded(item)
    if target_state == LZState.CLOSED_POR:
        return can_move_to_closed_por(item)

    return True, "OK"


def grading_status(item: dict[str, Any]) -> dict[str, Any]:
    """Get grading status summary for an item."""
    teams = item.get("arch_response_teams", [])
    total = len(teams)
    graded = sum(1 for t in teams if t.get("grade"))
    return {
        "total_teams": total,
        "graded": graded,
        "ungraded": total - graded,
        "percent": round(graded / total * 100) if total > 0 else 0,
        "ungraded_teams": [t.get("team", "?") for t in teams if not t.get("grade")],
        "fully_graded": graded == total and total > 0,
    }
