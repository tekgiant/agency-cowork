#!/usr/bin/env python3
"""Regression test: file-lock singleton prevents duplicate monitor instances.

Bug: https://github.com/ahsi-microsoft/agency-cowork/issues/149
Date: 2026-03-26
Root cause: PID-file-only check is race-prone -- multiple detached children
            can start before the first one writes its PID.  File-level locking
            via msvcrt.locking (Windows) / fcntl.flock (Unix) eliminates the
            race window.
"""
import os
import sys

# Add skills/teams to path so we can import the module.
# NOTE: This test imports private symbols (_acquire_lock, _release_lock,
# _LOCK_FILE) from service.py. If those are renamed, this test must be
# updated accordingly. The coupling is intentional for regression coverage.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "teams"))
from scripts.monitor.service import _acquire_lock, _release_lock, _LOCK_FILE


def test_lock_acquire_release():
    """First acquire should succeed; release should free it."""
    assert _acquire_lock(), "First _acquire_lock() should return True"
    print(f"  PASS: _acquire_lock() succeeded, lock file: {_LOCK_FILE}")
    _release_lock()
    print("  PASS: _release_lock() completed without error")


def test_lock_blocks_second_instance():
    """While lock is held, a second acquire must fail."""
    assert _acquire_lock(), "First _acquire_lock() should succeed"
    try:
        # Simulate a second instance trying to acquire
        # We need a separate file descriptor to test this properly
        if sys.platform == "win32":
            import msvcrt
            try:
                fd2 = open(_LOCK_FILE, "r+")
                msvcrt.locking(fd2.fileno(), msvcrt.LK_NBLCK, 1)
                fd2.close()
                assert False, "Second lock acquisition should have failed"
            except (OSError, IOError):
                print("  PASS: Second lock attempt correctly blocked (msvcrt)")
        else:
            import fcntl
            try:
                fd2 = open(_LOCK_FILE, "w")
                fcntl.flock(fd2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fd2.close()
                assert False, "Second lock acquisition should have failed"
            except (OSError, IOError):
                print("  PASS: Second lock attempt correctly blocked (fcntl)")
    finally:
        _release_lock()


def test_lock_reacquire_after_release():
    """After release, a new acquire should succeed."""
    assert _acquire_lock(), "First acquire should succeed"
    _release_lock()
    assert _acquire_lock(), "Re-acquire after release should succeed"
    _release_lock()
    print("  PASS: Lock re-acquired successfully after release")


def test_no_non_ascii_in_service():
    """service.py must contain zero non-ASCII characters (cp1252 safety)."""
    svc_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "skills", "teams",
        "scripts", "monitor", "service.py",
    )
    with open(svc_path, "rb") as f:
        content = f.read()
    non_ascii = [(i, b) for i, b in enumerate(content) if b > 127]
    assert not non_ascii, (
        f"service.py contains {len(non_ascii)} non-ASCII byte(s) -- "
        f"first at offset {non_ascii[0][0]}: 0x{non_ascii[0][1]:02X}"
    )
    print(f"  PASS: service.py is fully ASCII ({len(content)} bytes checked)")


if __name__ == "__main__":
    print("Running singleton lock regression tests...")
    test_lock_acquire_release()
    test_lock_blocks_second_instance()
    test_lock_reacquire_after_release()
    test_no_non_ascii_in_service()
    print("All singleton lock tests PASSED")
