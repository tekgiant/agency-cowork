"""Triage engine — main orchestrator for deterministic email classification.

Fetches emails, applies rules, categorizes, creates Todo tasks, and
generates a summary report. Designed for EVP-grade reliability.

Layers:
    1. NEVER-MISS: VIP senders → always urgent, zero LLM
    2. RULE-BASED: Tier 1/2 matching, keywords, importance headers
    3. LLM ENRICHMENT: (future) Content analysis for ambiguous items

State management:
    - Atomic writes (temp file + rename)
    - Rolling 7-day dedup via processed message IDs
    - Append-only audit trail (triage-history.jsonl)

Usage:
    python -m scripts.triage_engine [--dry-run] [--since ISO8601] [--top N]
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, ".")

from scripts.mail_client import MailClient, get_sender_email, get_sender_name, build_outlook_deeplink
from scripts.triage_rules import classify, MatchResult

# --- Prompt Guard Integration (ET-1) ---
# Import the project-wide prompt injection scanner so we can scan email content
# before it enters the audit trail or gets surfaced to the LLM agent.
_prompt_guard = None
try:
    _PROMPT_GUARD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "prompt_guard.py"
    if _PROMPT_GUARD_PATH.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_guard", _PROMPT_GUARD_PATH)
        _prompt_guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_prompt_guard)
except Exception:
    _prompt_guard = None


def _scan_email_content(msg: dict) -> Optional[dict]:
    """Scan email subject + body preview for prompt injection patterns.

    Returns None if clean or guard unavailable, dict with findings otherwise.
    """
    if _prompt_guard is None:
        return None

    subject = msg.get("Subject", "")
    body_preview = msg.get("BodyPreview", "")
    text = f"{subject}\n{body_preview}"

    if not text.strip():
        return None

    result = _prompt_guard.scan_for_injections(text, source="email-triage")
    if not result.clean:
        _prompt_guard.log_injection_event(result, text_preview=text[:200])
        return {
            "max_severity": result.max_severity,
            "finding_count": len(result.findings),
            "patterns": [f.pattern_name for f in result.findings],
        }
    return None

# --- Paths ---

CACHE_DIR = Path(__file__).parent.parent / "cache"
STATE_FILE = CACHE_DIR / "triage-state.json"
HISTORY_FILE = CACHE_DIR / "triage-history.jsonl"
PROCESSED_FILE = CACHE_DIR / "processed-ids.json"
DRAFTED_FILE = CACHE_DIR / "drafted-ids.json"

# Profile locations (checked in order)
PROFILE_PATHS = [
    Path.home() / ".agency-cowork" / "triage-profile.json",
    Path(__file__).parent / "triage-rules.json",  # fallback
]


def _ensure_cache_dir():
    """Create cache directory if needed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict):
    """Write JSON atomically via temp file + rename."""
    _ensure_cache_dir()
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _append_history(record: dict):
    """Append a triage record to the audit trail."""
    _ensure_cache_dir()
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# --- Profile Loading ---

def load_profile(path: Optional[str] = None) -> dict:
    """Load triage profile from disk.

    Search order:
    1. Explicit path (if provided)
    2. ~/.agency-cowork/triage-profile.json (personalization)
    3. scripts/triage-rules.json (fallback)
    """
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    for p in PROFILE_PATHS:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            # Legacy triage-rules.json has different structure
            if "tier1_contacts" not in data and "contacts" in data:
                return _migrate_legacy_profile(data)
            return data

    raise FileNotFoundError(
        "No triage profile found. Run 'python -m scripts.triage_engine --setup' "
        "to create one, or copy defaults/triage-defaults.json to "
        "~/.agency-cowork/triage-profile.json"
    )


def _migrate_legacy_profile(legacy: dict) -> dict:
    """Convert legacy triage-rules.json to new profile format."""
    contacts = legacy.get("contacts", {})
    return {
        "user": legacy.get("user", {}),
        "vip_contacts": contacts.get("auto_urgent", []),
        "tier1_contacts": contacts.get("tier1", []),
        "tier2_patterns": contacts.get("tier2_patterns", {}),
        "noise_filters": legacy.get("noise_filters", {}),
        "preferences": legacy.get("preferences", {
            "draft_mode": "tier1_only",
            "todo_enabled": True,
            "todo_folder": "Email Triage",
        }),
    }


# --- State Management ---

def load_state() -> dict:
    """Load triage state (last run, stats, etc.)."""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_run": None,
        "last_run_count": 0,
        "total_runs": 0,
        "total_processed": 0,
        "stats": {
            "urgent": 0, "needs_response": 0, "fyi": 0,
            "noise": 0, "archive": 0, "skip": 0,
        },
    }


def save_state(state: dict):
    """Save triage state atomically."""
    _atomic_write_json(STATE_FILE, state)


def load_processed_ids() -> dict:
    """Load processed message IDs (rolling 7-day window)."""
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"ids": {}, "last_pruned": None}


def save_processed_ids(data: dict):
    """Save processed IDs atomically."""
    _atomic_write_json(PROCESSED_FILE, data)


def prune_processed_ids(data: dict, days: int = 7) -> dict:
    """Remove message IDs older than N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pruned = {
        mid: ts for mid, ts in data.get("ids", {}).items()
        if ts > cutoff
    }
    return {"ids": pruned, "last_pruned": datetime.now(timezone.utc).isoformat()}


def load_drafted_ids() -> dict:
    """Load message IDs that already have drafts created (rolling 14-day window).

    Returns dict: {"ids": {message_id: {"draft_id": ..., "created_at": ...}}, "last_pruned": ...}
    """
    if DRAFTED_FILE.exists():
        try:
            with open(DRAFTED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            # Corrupted file — reset rather than crash the triage run
            print(f"  ⚠️ Corrupted {DRAFTED_FILE.name} — resetting")
    return {"ids": {}, "last_pruned": None}


def save_drafted_ids(data: dict):
    """Save drafted IDs atomically."""
    _atomic_write_json(DRAFTED_FILE, data)


def prune_drafted_ids(data: dict, days: int = 14) -> dict:
    """Remove drafted entries older than N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pruned = {}
    for mid, info in data.get("ids", {}).items():
        ts = info.get("created_at") if isinstance(info, dict) else info
        if ts and ts > cutoff:
            pruned[mid] = info
    return {"ids": pruned, "last_pruned": datetime.now(timezone.utc).isoformat()}


# --- Anomaly Detection (ET-5) ---

# Thresholds for anomaly detection
_ANOMALY_URGENT_THRESHOLD = 50     # Max urgent emails per run before flagging
_ANOMALY_VOLUME_MULTIPLIER = 5.0   # Flag if volume is Nx above historical average


def _check_anomalies(result: 'TriageResult', state: dict) -> None:
    """ET-5: Check for anomalous triage patterns and log warnings."""
    warnings = []

    # Check urgent volume spike
    urgent_count = result.stats.get("urgent", 0)
    if urgent_count > _ANOMALY_URGENT_THRESHOLD:
        warnings.append(
            f"ANOMALY: {urgent_count} urgent emails in single run "
            f"(threshold: {_ANOMALY_URGENT_THRESHOLD}). "
            f"Possible targeted campaign or classification error."
        )

    # Check total volume spike vs historical average
    total_runs = state.get("total_runs", 1)
    total_processed = state.get("total_processed", 0)
    if total_runs > 5:  # Need enough history for meaningful average
        avg_per_run = total_processed / total_runs
        if avg_per_run > 0 and result.new_count > (avg_per_run * _ANOMALY_VOLUME_MULTIPLIER):
            warnings.append(
                f"ANOMALY: {result.new_count} emails processed (avg: {avg_per_run:.0f}). "
                f"Volume is {result.new_count / avg_per_run:.1f}x historical average."
            )

    # Check injection-to-total ratio
    if result.injection_flags and result.new_count > 0:
        injection_rate = len(result.injection_flags) / result.new_count
        if injection_rate > 0.1:  # >10% injection rate
            warnings.append(
                f"ANOMALY: {len(result.injection_flags)}/{result.new_count} emails "
                f"({injection_rate:.0%}) flagged for prompt injection. "
                f"Possible coordinated injection attack."
            )

    for warning in warnings:
        print(f"  🚨 {warning}")
        _append_history({
            "timestamp": result.timestamp,
            "anomaly_warning": warning,
            "stats": result.stats,
            "injection_count": len(result.injection_flags),
        })


# --- Main Engine ---

class TriageResult:
    """Results from a single triage run."""

    def __init__(self):
        self.results: list[dict] = []  # {msg, match_result, action}
        self.stats = {
            "urgent": 0, "needs_response": 0, "fyi": 0,
            "noise": 0, "archive": 0, "skip": 0,
        }
        self.new_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.injection_flags: list[dict] = []  # ET-1: prompt injection detections
        self.draft_results: list[dict] = []  # Draft creation results
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def add(self, msg: dict, match: MatchResult, action: str = "classified"):
        """Add a classified email to results."""
        msg_id = msg.get("Id", "")
        self.results.append({
            "message_id": msg_id,
            "conversation_id": msg.get("ConversationId", ""),
            "subject": msg.get("Subject", ""),
            "sender": get_sender_name(msg),
            "sender_email": get_sender_email(msg),
            "received": msg.get("ReceivedDateTime", ""),
            "category": match.category,
            "tier": match.tier,
            "contact_name": match.contact_name,
            "signals": match.signals,
            "confidence": match.confidence,
            "action": action,
            "web_link": msg.get("WebLink", "") or build_outlook_deeplink(msg_id),
        })
        self.stats[match.category] = self.stats.get(match.category, 0) + 1
        self.new_count += 1

    @property
    def urgent_items(self) -> list[dict]:
        return [r for r in self.results if r["category"] == "urgent"]

    @property
    def needs_response_items(self) -> list[dict]:
        return [r for r in self.results if r["category"] == "needs_response"]

    @property
    def actionable_items(self) -> list[dict]:
        return [r for r in self.results
                if r["category"] in ("urgent", "needs_response")]

    def deduplicated_results(self, categories: Optional[list[str]] = None) -> list[dict]:
        """Return results deduplicated by ConversationId.

        For each conversation thread, keeps only the newest message (by
        ReceivedDateTime). This prevents the summary from showing the same
        thread multiple times when several replies arrive in one triage window.

        VIP/urgent messages are never suppressed: if any message in a thread
        is urgent, the urgent one is kept regardless of timestamp.

        Args:
            categories: If set, only dedup results in these categories.
                        Others are returned as-is.
        """
        # Partition into dedup-eligible and passthrough
        eligible = []
        passthrough = []
        for r in self.results:
            if categories and r["category"] not in categories:
                passthrough.append(r)
            else:
                eligible.append(r)

        # Group eligible by ConversationId (empty/missing = unique)
        from collections import defaultdict
        convos: dict[str, list[dict]] = defaultdict(list)
        no_convo = []
        for r in eligible:
            cid = r.get("conversation_id", "")
            if cid:
                convos[cid].append(r)
            else:
                no_convo.append(r)

        # Pick winner per conversation
        deduped = []
        for cid, msgs in convos.items():
            if len(msgs) == 1:
                deduped.append(msgs[0])
                continue
            # Prefer urgent over non-urgent, then newest by received time
            urgent = [m for m in msgs if m["category"] == "urgent"]
            if urgent:
                deduped.append(max(urgent, key=lambda m: m.get("received", "")))
            else:
                deduped.append(max(msgs, key=lambda m: m.get("received", "")))

        return passthrough + no_convo + deduped

    def summary_line(self) -> str:
        """One-line summary for logs."""
        parts = []
        for cat in ("urgent", "needs_response", "fyi", "noise", "archive", "skip"):
            n = self.stats.get(cat, 0)
            if n:
                icon = {"urgent": "🔴", "needs_response": "🟡",
                        "fyi": "🔵", "noise": "⚪", "archive": "📦",
                        "skip": "⬜"}.get(cat, "")
                parts.append(f"{icon}{n}")
        return f"Triaged {self.new_count} emails: {' '.join(parts)}"


def run_triage(
    profile: dict,
    since: Optional[str] = None,
    top: int = 200,
    dry_run: bool = False,
    categorize_outlook: bool = True,
    create_drafts: bool = True,
) -> TriageResult:
    """Run the triage engine.

    Args:
        profile: Triage profile (contacts, rules, preferences)
        since: ISO 8601 timestamp — only process emails after this time
        top: Maximum emails to fetch
        dry_run: If True, classify but don't modify anything
        categorize_outlook: If True, set Outlook categories on emails
        create_drafts: If True, create reply drafts for actionable items

    Returns:
        TriageResult with all classifications and stats.
    """
    result = TriageResult()

    # Load state and processed IDs
    state = load_state()
    processed = load_processed_ids()
    processed_ids = processed.get("ids", {})
    drafted = load_drafted_ids()
    drafted_ids = drafted.get("ids", {})

    # Determine time window
    if not since:
        since = state.get("last_run")
        if not since:
            # First run: look back 24 hours
            dt = datetime.now(timezone.utc) - timedelta(hours=24)
            since = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch emails
    client = MailClient()
    print(f"Fetching emails since {since}...")
    messages = client.list_messages(since=since, top=top)
    print(f"  Fetched {len(messages)} emails")

    # Preference: category names
    prefs = profile.get("preferences", {})
    cat_names = prefs.get("categories", {})

    # Reverse map: Outlook category label → triage category
    server_cat_map = {}
    for triage_cat, label in cat_names.items():
        server_cat_map[label.lower()] = triage_cat
    # Also map emoji-prefixed categories from server rules
    server_cat_map["🔴 urgent"] = "urgent"
    server_cat_map["🟡 tier 1"] = "needs_response"

    for msg in messages:
        msg_id = msg.get("Id", "")

        # Skip already-processed
        if msg_id in processed_ids:
            result.skipped_count += 1
            continue

        try:
            # ET-1: Scan email content for prompt injection before processing
            injection = _scan_email_content(msg)
            if injection:
                result.injection_flags.append({
                    "message_id": msg_id,
                    "subject": msg.get("Subject", ""),
                    "sender": get_sender_email(msg),
                    **injection,
                })
                print(f"  ⚠️ Prompt injection detected in '{msg.get('Subject', '')[:40]}' "
                      f"[{injection['max_severity']}]: {', '.join(injection['patterns'])}")

            # Check if Outlook server rules already categorized this email
            existing_cats = [c.lower() for c in (msg.get("Categories") or [])]
            server_category = None
            for cat_label in existing_cats:
                if cat_label in server_cat_map:
                    server_category = server_cat_map[cat_label]
                    break

            if server_category:
                # Server already classified — use that, skip Python re-classification
                match = MatchResult(
                    category=server_category,
                    tier=0 if server_category == "urgent" else 1,
                    signals=["outlook_server_rule", f"category:{existing_cats[0]}"],
                    confidence=1.0,
                )
            else:
                # No server category — run Python classification
                match = classify(msg, profile)

            # Record result
            result.add(msg, match)

            # Apply Outlook actions (unless dry run)
            update_ok = True
            if not dry_run and categorize_outlook and match.category != "skip":
                try:
                    # Build a single PATCH payload for all changes
                    patch = {}

                    if match.category == "urgent":
                        # Urgent/VIP → High Importance + Flag (always, even if server-categorized)
                        if msg.get("Importance") != "High":
                            patch["Importance"] = "High"
                        flag_status = (msg.get("Flag") or {}).get("FlagStatus", "NotFlagged")
                        if flag_status != "Flagged":
                            patch["Flag"] = {"FlagStatus": "Flagged"}
                    elif match.category in ("needs_response",):
                        # Needs Response → Flag
                        flag_status = (msg.get("Flag") or {}).get("FlagStatus", "NotFlagged")
                        if flag_status != "Flagged":
                            patch["Flag"] = {"FlagStatus": "Flagged"}

                    # Set category label if not already set by server
                    if not server_category and match.category != "noise":
                        cat_label = cat_names.get(match.category, match.category.title())
                        patch["Categories"] = [cat_label]

                    if patch:
                        update_ok = False
                        for attempt in range(3):
                            try:
                                client.update_message(msg_id, patch)
                                update_ok = True
                                break
                            except Exception:
                                if attempt < 2:
                                    time.sleep(5 * (attempt + 1))
                                else:
                                    raise
                    else:
                        update_ok = True
                except Exception as e:
                    update_ok = False
                    print(f"  ! Failed to update {msg_id[:20]}...: {e}")

            # Mark processed only after successful update (or dry run / skip)
            if not dry_run:
                if match.category == "skip" or not categorize_outlook or update_ok:
                    processed_ids[msg_id] = datetime.now(timezone.utc).isoformat()

            # Append to audit trail
            if not dry_run:
                history_record = {
                    "timestamp": result.timestamp,
                    "message_id": msg_id,
                    "subject": msg.get("Subject", ""),
                    "sender": get_sender_email(msg),
                    "category": match.category,
                    "tier": match.tier,
                    "contact": match.contact_name,
                    "signals": match.signals,
                }
                # ET-1: Include injection flag in audit trail
                if injection:
                    history_record["injection_detected"] = injection
                _append_history(history_record)

        except Exception as e:
            result.error_count += 1
            print(f"  ❌ Error classifying {msg.get('Subject', '')[:40]}: {e}")

    # Create reply drafts for actionable items (thread-deduped)
    if not dry_run and create_drafts and result.actionable_items:
        draft_mode = profile.get("preferences", {}).get("draft_mode", "tier1_only")
        if draft_mode != "never":
            try:
                from scripts.draft_composer import create_drafts_for_results

                # Dedup: only draft the newest message per conversation thread
                deduped_actionable = result.deduplicated_results(
                    categories=["urgent", "needs_response"]
                )
                deduped_actionable = [r for r in deduped_actionable
                                      if r["category"] in ("urgent", "needs_response")]

                print(f"\nCreating drafts (mode: {draft_mode}, "
                      f"{len(deduped_actionable)}/{len(result.actionable_items)} "
                      f"after thread dedup)...")
                draft_results = create_drafts_for_results(
                    deduped_actionable, client=client,
                    profile=profile, dry_run=False,
                    drafted_ids=drafted_ids,
                )
                result.draft_results = draft_results
                created = sum(1 for d in draft_results
                              if d.get("type") not in ("error", "already_drafted"))
                skipped = sum(1 for d in draft_results
                              if d.get("type") == "already_drafted")
                print(f"  {created} draft(s) created, {skipped} skipped (already drafted)")

                # Persist new draft IDs (with conversation_id for cross-ref)
                for d in draft_results:
                    if d.get("draft_id") and d.get("type") not in ("error", "dry_run", "already_drafted"):
                        drafted_ids[d["message_id"]] = {
                            "draft_id": d["draft_id"],
                            "conversation_id": d.get("conversation_id", ""),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                drafted = prune_drafted_ids({"ids": drafted_ids})
                save_drafted_ids(drafted)
            except Exception as e:
                print(f"  \u26a0\ufe0f Draft creation failed: {e}")

    # Save state
    if not dry_run:
        # Use the latest ReceivedDateTime from the fetched batch as the watermark
        # for the next run. This ensures replies that arrive during processing are
        # not missed. Fall back to wall-clock time if no messages were fetched.
        # Subtract 60s overlap to cover clock skew and in-flight deliveries.
        #
        # Security: Validate timestamps are within a sane range to prevent a
        # crafted far-future ReceivedDateTime from poisoning the watermark and
        # causing all future runs to return zero emails (denial of service).
        _now = datetime.now(timezone.utc)
        _MAX_FUTURE_SKEW = timedelta(hours=1)
        _MIN_VALID_DATE = datetime(2020, 1, 1, tzinfo=timezone.utc)

        latest_received = None
        for msg in messages:
            rd = msg.get("ReceivedDateTime", "")
            if not rd:
                continue
            try:
                ts = rd.replace("Z", "+00:00")
                dt_obj = datetime.fromisoformat(ts)
                # Reject timestamps outside a reasonable window
                if dt_obj > _now + _MAX_FUTURE_SKEW or dt_obj < _MIN_VALID_DATE:
                    continue
                if not latest_received or rd > latest_received:
                    latest_received = rd
            except (ValueError, TypeError):
                continue  # Skip malformed timestamps

        if latest_received:
            # Parse and subtract 60s for overlap safety
            try:
                ts = latest_received.replace("Z", "+00:00")
                dt_obj = datetime.fromisoformat(ts) - timedelta(seconds=60)
                state["last_run"] = dt_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                state["last_run"] = _now.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            state["last_run"] = _now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state["last_run_count"] = result.new_count
        state["total_runs"] = state.get("total_runs", 0) + 1
        state["total_processed"] = state.get("total_processed", 0) + result.new_count
        for cat, count in result.stats.items():
            state["stats"][cat] = state["stats"].get(cat, 0) + count

        # ET-5: Anomaly detection — flag unusual triage runs
        _check_anomalies(result, state)

        # Commit state + processed IDs as a unit to prevent divergence
        # (state advancing but processed IDs lost = re-process + duplicate drafts)
        try:
            # Prune old processed IDs (every 10 runs)
            if state["total_runs"] % 10 == 0:
                processed = prune_processed_ids({"ids": processed_ids})
                processed_ids = processed["ids"]

            # Save processed IDs first (replay barrier), then state
            save_processed_ids({"ids": processed_ids,
                               "last_pruned": processed.get("last_pruned")})
            save_state(state)
            print(f"  State saved: {len(processed_ids)} processed IDs, "
                  f"run #{state['total_runs']}")
        except Exception as e:
            print(f"  \U0001f6a8 CRITICAL: Failed to save state/processed IDs: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(
                f"Triage state commit failed: {e}. "
                f"Emails were classified but state was not persisted -- "
                f"next run may re-process {result.new_count} emails."
            ) from e

    return result


def format_summary(result: TriageResult, verbose: bool = False) -> str:
    """Format triage results as a readable summary.

    Uses ConversationId-based dedup to collapse thread replies into a
    single entry per conversation (keeping the newest or most urgent).
    Raw stats still reflect all processed messages for audit accuracy.
    """
    lines = []
    lines.append(f"## Email Triage -- {result.timestamp[:16]}")
    lines.append("")
    lines.append(result.summary_line())
    lines.append("")

    # Dedup actionable items by conversation for display
    deduped = result.deduplicated_results(
        categories=["urgent", "needs_response", "fyi"]
    )
    urgent_deduped = [r for r in deduped if r["category"] == "urgent"]
    nr_deduped = [r for r in deduped if r["category"] == "needs_response"]
    fyi_deduped = [r for r in deduped if r["category"] == "fyi"]

    if urgent_deduped:
        lines.append("### \U0001f534 Urgent")
        for r in urgent_deduped:
            contact = f" ({r['contact_name']})" if r.get("contact_name") else ""
            lines.append(f"- **{r['sender']}{contact}**: {r['subject']}")
        lines.append("")

    if nr_deduped:
        lines.append("### \U0001f7e1 Needs Response")
        for r in nr_deduped:
            contact = f" ({r['contact_name']})" if r.get("contact_name") else ""
            lines.append(f"- **{r['sender']}{contact}**: {r['subject']}")
        lines.append("")

    if verbose and fyi_deduped:
        lines.append(f"### \U0001f535 FYI ({len(fyi_deduped)} threads)")
        for r in fyi_deduped[:10]:
            lines.append(f"- {r['sender']}: {r['subject']}")
        if len(fyi_deduped) > 10:
            lines.append(f"- ... and {len(fyi_deduped) - 10} more")
        lines.append("")

    # Thread dedup stats (if any threads were collapsed)
    raw_actionable = len(result.urgent_items) + len(result.needs_response_items)
    deduped_actionable = len(urgent_deduped) + len(nr_deduped)
    if deduped_actionable < raw_actionable:
        lines.append(f"*{raw_actionable - deduped_actionable} duplicate thread "
                     f"replies collapsed*")
        lines.append("")

    if result.error_count:
        lines.append(f"\u26a0\ufe0f {result.error_count} errors during triage")

    # Draft summary
    if result.draft_results:
        created = [d for d in result.draft_results
                   if d.get("type") not in ("error", "already_drafted")]
        skipped = [d for d in result.draft_results
                   if d.get("type") == "already_drafted"]
        if created:
            lines.append(f"\n\U0001f4dd **{len(created)} draft(s) created** in Drafts folder")
        if skipped:
            lines.append(f"\u23ed\ufe0f {len(skipped)} draft(s) skipped (already exist)")

    # ET-1: Prompt injection warnings
    if result.injection_flags:
        lines.append(f"\U0001f6e1\ufe0f **{len(result.injection_flags)} email(s) flagged for prompt injection**")
        for flag in result.injection_flags[:5]:
            lines.append(f"- [{flag['max_severity'].upper()}] {flag['sender']}: "
                        f"{flag['subject'][:50]} -- {', '.join(flag['patterns'])}")
        if len(result.injection_flags) > 5:
            lines.append(f"- ... and {len(result.injection_flags) - 5} more")

    return "\n".join(lines)


# --- CLI ---

def _log(msg: str, *, file=None):
    """Print to the designated log stream (stderr in JSON mode, stdout otherwise)."""
    print(msg, file=file or sys.stdout)


def main():
    parser = argparse.ArgumentParser(description="Email Triage Engine")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify but don't modify emails or state")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO 8601 timestamp — process emails after this time")
    parser.add_argument("--top", type=int, default=200,
                        help="Max emails to fetch (default: 200)")
    parser.add_argument("--profile", type=str, default=None,
                        help="Path to triage profile JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show FYI items in summary")
    parser.add_argument("--no-categorize", action="store_true",
                        help="Skip setting Outlook categories")
    parser.add_argument("--no-drafts", action="store_true",
                        help="Skip creating reply drafts")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON (logs go to stderr, "
                             "clean JSON on stdout)")
    parser.add_argument("--include-todo", action="store_true",
                        help="Run Todo sync and include results in output")
    parser.add_argument("--include-teams-html", action="store_true",
                        help="Include Teams-ready HTML summary in JSON output")

    args = parser.parse_args()

    # Ensure UTF-8 output on Windows
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    # In JSON mode, redirect all print() to stderr so stdout is clean JSON
    if args.json:
        _real_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print
        import builtins
        _original_print = builtins.print
        def _stderr_print(*a, **kw):
            kw.setdefault("file", sys.stderr)
            _original_print(*a, **kw)
        builtins.print = _stderr_print

    # Preflight auth check — verify cached token is valid before mutations
    try:
        client = MailClient()
        # Quick auth test: list 1 message
        client.list_messages(since=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             top=1)
    except Exception as e:
        msg = f"PREFLIGHT FAILED: Auth/connectivity check failed: {e}"
        if args.json:
            # Restore print for clean JSON error output
            import builtins
            builtins.print = _original_print
            print(json.dumps({"error": msg, "stage": "preflight"}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(3)

    profile = load_profile(args.profile)
    print(f"Profile loaded: {len(profile.get('vip_contacts', []))} VIPs, "
          f"{len(profile.get('tier1_contacts', []))} Tier 1, "
          f"noise patterns: {len(profile.get('noise_filters', {}).get('senders', []))}")

    result = run_triage(
        profile=profile,
        since=args.since,
        top=args.top,
        dry_run=args.dry_run,
        categorize_outlook=not args.no_categorize,
        create_drafts=not args.no_drafts,
    )

    # Optional: Todo sync
    todo_results = None
    if args.include_todo and not args.dry_run:
        try:
            from scripts.triage_report import sync_to_todo
            todo_results = sync_to_todo(result, profile)
            print(f"Todo sync: {todo_results}")
        except Exception as e:
            todo_results = {"error": str(e)}
            print(f"Todo sync failed: {e}")

    if args.json:
        # Restore print for clean JSON output to stdout
        import builtins
        builtins.print = _original_print

        output = {
            "timestamp": result.timestamp,
            "summary": result.summary_line(),
            "stats": result.stats,
            "new_count": result.new_count,
            "skipped": result.skipped_count,
            "errors": result.error_count,
            "urgent": result.urgent_items,
            "needs_response": result.needs_response_items,
            "deduped_actionable": [
                r for r in result.deduplicated_results(
                    categories=["urgent", "needs_response"]
                ) if r["category"] in ("urgent", "needs_response")
            ],
            "draft_results": [
                {k: v for k, v in d.items() if k != "body"}
                for d in (result.draft_results or [])
            ],
            "injection_flags": result.injection_flags,
        }

        # Include Teams HTML if requested
        if args.include_teams_html:
            try:
                from scripts.triage_report import format_teams_html
                output["teams_html"] = format_teams_html(result)
            except Exception as e:
                output["teams_html_error"] = str(e)

        # Include Todo results if requested
        if todo_results is not None:
            output["todo_sync"] = todo_results

        print(json.dumps(output, indent=2, default=str))
    else:
        print()
        print(format_summary(result, verbose=args.verbose))

    # Exit code: 2 if errors, 0 otherwise
    sys.exit(2 if result.error_count > 0 else 0)


if __name__ == "__main__":
    main()
