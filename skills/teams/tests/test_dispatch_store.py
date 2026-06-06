"""Unit tests for the persistent DispatchStore.

Covers CRUD, crash recovery, cleanup, persistence, and display formatting.
"""

import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase, main

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from monitor.dispatch_store import (
    DispatchStore, DispatchRecord,
    PENDING, IN_PROGRESS, DONE, FAILED, TIMEOUT, CANCELLED,
)


class TestDispatchStore(TestCase):
    """Tests for DispatchStore CRUD and lifecycle operations."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self.path = Path(self._tmp.name)
        self.path.unlink(missing_ok=True)  # start fresh
        self.store = DispatchStore(store_path=self.path)

    def tearDown(self):
        self.path.unlink(missing_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)

    # ── Add & Query ──────────────────────────────────────────────────

    def test_add_returns_id(self):
        did = self.store.add("test prompt", "Alice", "mri:alice", "conv1", "key1")
        self.assertIsInstance(did, str)
        self.assertEqual(len(did), 12)

    def test_add_creates_pending_record(self):
        did = self.store.add("test", "Alice", "mri:alice", "conv1", "key1")
        pending = self.store.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, did)
        self.assertEqual(pending[0].status, PENDING)
        self.assertEqual(pending[0].prompt, "test")

    def test_get_all_sorted_descending(self):
        self.store.add("first", "A", "mri:a", "c1", "k1")
        time.sleep(0.01)
        self.store.add("second", "B", "mri:b", "c2", "k2")
        all_recs = self.store.get_all()
        self.assertEqual(len(all_recs), 2)
        self.assertEqual(all_recs[0].prompt, "second")  # most recent first

    def test_get_recent_limits(self):
        for i in range(5):
            self.store.add(f"prompt {i}", "A", "mri:a", "c1", "k1")
        recent = self.store.get_recent(limit=3)
        self.assertEqual(len(recent), 3)

    def test_get_incomplete(self):
        d1 = self.store.add("p1", "A", "mri:a", "c1", "k1")
        d2 = self.store.add("p2", "A", "mri:a", "c1", "k1")
        self.store.update_status(d1, IN_PROGRESS)
        incomplete = self.store.get_incomplete()
        self.assertEqual(len(incomplete), 2)  # one pending, one in_progress

    # ── Status Transitions ───────────────────────────────────────────

    def test_update_to_in_progress(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, IN_PROGRESS)
        rec = self.store._records[did]
        self.assertEqual(rec.status, IN_PROGRESS)
        self.assertGreater(rec.started_at, 0)

    def test_update_to_done(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, DONE, result_summary="all good")
        rec = self.store._records[did]
        self.assertEqual(rec.status, DONE)
        self.assertGreater(rec.completed_at, 0)
        self.assertEqual(rec.result_summary, "all good")

    def test_update_to_failed(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, FAILED, error="crash")
        rec = self.store._records[did]
        self.assertEqual(rec.status, FAILED)
        self.assertEqual(rec.error, "crash")

    def test_update_nonexistent_id(self):
        # Should not raise
        self.store.update_status("nonexistent", DONE)

    # ── Cancel ───────────────────────────────────────────────────────

    def test_cancel_pending(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        result = self.store.cancel(did)
        self.assertTrue(result)
        self.assertEqual(self.store._records[did].status, CANCELLED)

    def test_cancel_in_progress(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, IN_PROGRESS)
        result = self.store.cancel(did)
        self.assertTrue(result)
        self.assertEqual(self.store._records[did].status, CANCELLED)

    def test_cancel_terminal_returns_false(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, DONE)
        result = self.store.cancel(did)
        self.assertFalse(result)
        self.assertEqual(self.store._records[did].status, DONE)

    def test_cancel_nonexistent_returns_false(self):
        result = self.store.cancel("nonexistent")
        self.assertFalse(result)

    # ── Crash Recovery ───────────────────────────────────────────────

    def test_mark_interrupted_resets_in_progress(self):
        d1 = self.store.add("p1", "A", "mri:a", "c1", "k1")
        d2 = self.store.add("p2", "A", "mri:a", "c1", "k1")
        self.store.update_status(d1, IN_PROGRESS)
        # d2 stays pending
        count = self.store.mark_interrupted_as_pending()
        self.assertEqual(count, 1)
        self.assertEqual(self.store._records[d1].status, PENDING)
        self.assertEqual(self.store._records[d1].started_at, 0.0)
        self.assertEqual(self.store._records[d2].status, PENDING)

    def test_mark_interrupted_skips_terminal(self):
        d1 = self.store.add("p1", "A", "mri:a", "c1", "k1")
        self.store.update_status(d1, DONE)
        count = self.store.mark_interrupted_as_pending()
        self.assertEqual(count, 0)
        self.assertEqual(self.store._records[d1].status, DONE)

    # ── Cleanup ──────────────────────────────────────────────────────

    def test_cleanup_old_removes_completed(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, DONE)
        # Backdate completed_at
        self.store._records[did].completed_at = time.time() - 80 * 3600
        self.store._save()
        count = self.store.cleanup_old(max_age_hours=72)
        self.assertEqual(count, 1)
        self.assertEqual(len(self.store._records), 0)

    def test_cleanup_preserves_recent(self):
        did = self.store.add("test", "A", "mri:a", "c1", "k1")
        self.store.update_status(did, DONE)
        count = self.store.cleanup_old(max_age_hours=72)
        self.assertEqual(count, 0)
        self.assertEqual(len(self.store._records), 1)

    def test_cleanup_preserves_pending(self):
        """Pending items with completed_at=0 must never be cleaned up."""
        self.store.add("test", "A", "mri:a", "c1", "k1")
        count = self.store.cleanup_old(max_age_hours=0)  # zero hours = aggressive
        self.assertEqual(count, 0)

    # ── Persistence ──────────────────────────────────────────────────

    def test_persist_and_reload(self):
        d1 = self.store.add("persistent prompt", "Alice", "mri:alice", "conv1", "key1")
        self.store.update_status(d1, IN_PROGRESS)

        # Reload from disk
        store2 = DispatchStore(store_path=self.path)
        self.assertEqual(len(store2._records), 1)
        rec = store2._records[d1]
        self.assertEqual(rec.prompt, "persistent prompt")
        self.assertEqual(rec.status, IN_PROGRESS)
        self.assertEqual(rec.sender_name, "Alice")

    def test_empty_file_loads_empty(self):
        self.path.write_text("{}", encoding="utf-8")
        store = DispatchStore(store_path=self.path)
        self.assertEqual(len(store._records), 0)

    def test_corrupt_file_loads_empty(self):
        self.path.write_text("not json at all", encoding="utf-8")
        store = DispatchStore(store_path=self.path)
        self.assertEqual(len(store._records), 0)

    def test_unknown_fields_ignored(self):
        """Future schema additions should not crash loading."""
        data = {
            "version": 1,
            "dispatches": [{
                "id": "abc123", "prompt": "test", "sender_name": "A",
                "sender_mri": "mri:a", "conversation_id": "c1",
                "session_key": "k1", "status": "pending",
                "enqueued_at": time.time(),
                "future_field": "should be ignored",
            }],
        }
        self.path.write_text(json.dumps(data), encoding="utf-8")
        store = DispatchStore(store_path=self.path)
        self.assertEqual(len(store._records), 1)
        self.assertFalse(hasattr(store._records["abc123"], "future_field"))

    # ── Display Formatting ───────────────────────────────────────────

    def test_to_display_contains_index(self):
        did = self.store.add("show me the money", "Bob", "mri:bob", "c1", "k1")
        rec = self.store._records[did]
        display = rec.to_display(1)
        self.assertIn("[1]", display)
        self.assertIn("show me the money", display)
        self.assertIn("Bob", display)
        self.assertIn("[PENDING]", display)

    def test_to_display_truncates_long_prompt(self):
        long_prompt = "x" * 200
        did = self.store.add(long_prompt, "A", "mri:a", "c1", "k1")
        rec = self.store._records[did]
        display = rec.to_display(1)
        self.assertIn("...", display)
        self.assertLessEqual(len(rec.prompt[:120] + "..."), 123)


if __name__ == "__main__":
    main()
