"""Persistent dispatch store for the Teams Monitor.

Single-threaded asyncio-compatible JSON-backed dispatch persistence.
Tracks dispatches across their lifecycle: pending -> in_progress -> done/failed/timeout/cancelled.
Survives service crashes and app restarts via atomic file writes.
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)

# Status constants
PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
TIMEOUT = "timeout"
CANCELLED = "cancelled"

_TERMINAL_STATUSES = {DONE, FAILED, TIMEOUT, CANCELLED}
_INCOMPLETE_STATUSES = {PENDING, IN_PROGRESS}


@dataclass
class DispatchRecord:
    """A single dispatch tracked across its lifecycle."""

    id: str
    prompt: str
    sender_name: str
    sender_mri: str
    conversation_id: str
    session_key: str
    status: str  # pending | in_progress | done | failed | timeout | cancelled
    enqueued_at: float
    started_at: float = 0.0
    completed_at: float = 0.0
    result_summary: str = ""
    error: str = ""

    def to_display(self, index: int) -> str:
        """Format for display in a Teams message (ASCII-safe icons)."""
        age = time.time() - self.enqueued_at
        if age < 60:
            age_str = f"{int(age)}s ago"
        elif age < 3600:
            age_str = f"{int(age / 60)}m ago"
        else:
            age_str = f"{age / 3600:.1f}h ago"

        status_icon = {
            PENDING: "[PENDING]",
            IN_PROGRESS: "[RUNNING]",
            DONE: "[OK]",
            FAILED: "[ERROR]",
            TIMEOUT: "[TIMEOUT]",
            CANCELLED: "[CANCEL]",
        }.get(self.status, "[?]")

        prompt_preview = self.prompt[:120] + ("..." if len(self.prompt) > 120 else "")
        return (
            f"{status_icon} <b>[{index}]</b> {prompt_preview}<br>"
            f"&nbsp;&nbsp;&nbsp;From: {self.sender_name} | {age_str} | Status: {self.status}"
        )


class DispatchStore:
    """JSON-backed dispatch persistence.

    Records are stored at ``<monitor_dir>/dispatch-queue.json`` with atomic
    writes (temp file + rename).  The store is designed for single-threaded
    asyncio usage -- no internal locking.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        if store_path is None:
            from pathlib import Path as _P
            monitor_dir = _P(__file__).resolve().parent
            store_path = monitor_dir / "dispatch-queue.json"
        self._path = store_path
        self._records: dict[str, DispatchRecord] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        """Load records from disk with defensive field filtering."""
        if not self._path.exists():
            self._records = {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._records = {}
            known = {f.name for f in fields(DispatchRecord)}
            for raw in data.get("dispatches", []):
                filtered = {k: v for k, v in raw.items() if k in known}
                try:
                    rec = DispatchRecord(**filtered)
                    self._records[rec.id] = rec
                except TypeError:
                    logger.warning("Skipped malformed dispatch record: %s", filtered.get("id", "?"))
            logger.info("Loaded %d dispatch records from %s", len(self._records), self._path)
        except Exception as e:
            logger.warning("Failed to load dispatch store: %s", e)
            self._records = {}

    def _save(self) -> None:
        """Atomic write: temp file + rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            data = {
                "version": 1,
                "dispatches": [asdict(r) for r in self._records.values()],
            }
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            # Atomic rename -- on Windows, target must not exist
            if self._path.exists():
                self._path.unlink()
            tmp.rename(self._path)
        except Exception as e:
            logger.error("Failed to save dispatch store: %s", e)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    # ── CRUD ─────────────────────────────────────────────────────────

    def add(
        self,
        prompt: str,
        sender_name: str,
        sender_mri: str,
        conversation_id: str,
        session_key: str,
    ) -> str:
        """Add a new dispatch as pending.  Returns the dispatch ID."""
        dispatch_id = uuid.uuid4().hex[:12]
        rec = DispatchRecord(
            id=dispatch_id,
            prompt=prompt,
            sender_name=sender_name,
            sender_mri=sender_mri,
            conversation_id=conversation_id,
            session_key=session_key,
            status=PENDING,
            enqueued_at=time.time(),
        )
        self._records[dispatch_id] = rec
        self._save()
        logger.info("Dispatch %s added (pending): %s", dispatch_id, prompt[:80])
        return dispatch_id

    def update_status(
        self,
        dispatch_id: str,
        status: str,
        result_summary: str = "",
        error: str = "",
    ) -> None:
        """Update the status of a dispatch record."""
        rec = self._records.get(dispatch_id)
        if not rec:
            logger.warning("Dispatch %s not found in store", dispatch_id)
            return

        rec.status = status
        if status == IN_PROGRESS:
            rec.started_at = time.time()
        if status in _TERMINAL_STATUSES:
            rec.completed_at = time.time()
        if result_summary:
            rec.result_summary = result_summary
        if error:
            rec.error = error

        self._save()
        logger.debug("Dispatch %s -> %s", dispatch_id, status)

    def cancel(self, dispatch_id: str) -> bool:
        """Cancel a pending/in_progress dispatch.  Returns True if cancelled."""
        rec = self._records.get(dispatch_id)
        if not rec or rec.status in _TERMINAL_STATUSES:
            return False
        rec.status = CANCELLED
        rec.completed_at = time.time()
        self._save()
        logger.info("Dispatch %s cancelled", dispatch_id)
        return True

    # ── Queries ───────────────────────────────────────────────────────

    def get_pending(self) -> list[DispatchRecord]:
        """Return all records with status pending."""
        return [r for r in self._records.values() if r.status == PENDING]

    def get_incomplete(self) -> list[DispatchRecord]:
        """Return all records with status pending or in_progress."""
        return [r for r in self._records.values() if r.status in _INCOMPLETE_STATUSES]

    def get_all(self) -> list[DispatchRecord]:
        """Return all records, sorted by enqueued_at descending."""
        return sorted(self._records.values(), key=lambda r: r.enqueued_at, reverse=True)

    def get_recent(self, limit: int = 20) -> list[DispatchRecord]:
        """Return the most recent N records."""
        return self.get_all()[:limit]

    # ── Maintenance ──────────────────────────────────────────────────

    def cleanup_old(self, max_age_hours: float = 72) -> int:
        """Remove completed records older than max_age_hours.  Returns count removed."""
        cutoff = time.time() - (max_age_hours * 3600)
        to_remove = [
            rid
            for rid, rec in self._records.items()
            if rec.status in _TERMINAL_STATUSES and rec.completed_at < cutoff
        ]
        for rid in to_remove:
            del self._records[rid]
        if to_remove:
            self._save()
            logger.info("Cleaned up %d old dispatch records", len(to_remove))
        return len(to_remove)

    def mark_interrupted_as_pending(self) -> int:
        """Reset in_progress items back to pending (crash recovery).

        Returns count of items reset.
        """
        count = 0
        for rec in self._records.values():
            if rec.status == IN_PROGRESS:
                rec.status = PENDING
                rec.started_at = 0.0
                count += 1
        if count:
            self._save()
            logger.info("Reset %d in-progress dispatches back to pending", count)
        return count
