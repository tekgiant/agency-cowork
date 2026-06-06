#!/usr/bin/env python3
"""Regression test: _is_running() must not false-positive on dead PIDs.

Bug: https://github.com/ahsi-microsoft/agency-cowork/issues/131
Date: 2026-03-23
Root cause: OpenProcess returns a valid handle for terminated processes with
            outstanding kernel references.  Must call GetExitCodeProcess to
            verify STILL_ACTIVE (259).
"""
import os
import subprocess
import sys
import time

# Add skills/teams to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "teams"))
from scripts.monitor.service import _is_running


def test_dead_process_not_running():
    """Spawn a short-lived process, wait for it to exit, verify _is_running returns False."""
    # Start a process that exits immediately
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait()  # ensure it's dead
    time.sleep(0.5)  # give kernel time to update state

    result = _is_running(proc.pid)
    assert not result, (
        f"_is_running({proc.pid}) returned True for a dead process — "
        f"stale PID false-positive bug (issue #131) has regressed"
    )
    print(f"  PASS: _is_running({proc.pid}) correctly returned False for dead process")


def test_live_process_is_running():
    """Spawn a long-lived process, verify _is_running returns True, then clean up."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        result = _is_running(proc.pid)
        assert result, f"_is_running({proc.pid}) returned False for a live process"
        print(f"  PASS: _is_running({proc.pid}) correctly returned True for live process")
    finally:
        proc.kill()
        proc.wait()


def test_nonexistent_pid():
    """A PID that was never used should return False."""
    # PID 4 is System on Windows, use a very high PID unlikely to exist
    fake_pid = 99999999
    result = _is_running(fake_pid)
    assert not result, f"_is_running({fake_pid}) returned True for nonexistent PID"
    print(f"  PASS: _is_running({fake_pid}) correctly returned False for nonexistent PID")


if __name__ == "__main__":
    print("Running stale PID detection regression tests...")
    test_dead_process_not_running()
    test_live_process_is_running()
    test_nonexistent_pid()
    print("All stale PID tests PASSED ✓")
