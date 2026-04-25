"""Integration tests for StateStore lockfile operations.

Tests lock acquire/release, stale lock reclaim, concurrent contention.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.state import StateStore, LockContentionError


class TestLockAcquireRelease:
    """Tests for lock acquire and release."""

    def test_lock_acquired_with_pid(self, tmp_path):
        """Lock acquired and released cleanly."""
        store = StateStore(tmp_path, "spec-001", "default")
        store.acquire_lock("run-001")

        lock_file = tmp_path / "spec-001" / ".lock"
        assert lock_file.exists()
        content = lock_file.read_text(encoding="utf-8")
        assert f"pid={os.getpid()}" in content
        assert "run_id=run-001" in content

        store.release_lock()
        assert not lock_file.exists()

    def test_lock_released_cleanly(self, tmp_path):
        """Release removes lock file."""
        store = StateStore(tmp_path, "spec-001", "default")
        store.acquire_lock("run-001")
        store.release_lock()

        lock_file = tmp_path / "spec-001" / ".lock"
        assert not lock_file.exists()

    def test_stale_lock_reclaimed(self, tmp_path):
        """Stale lock (dead PID) reclaimed with warning."""
        store = StateStore(tmp_path, "spec-001", "default")

        # Write a lock with a dead PID
        lock_dir = tmp_path / "spec-001"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / ".lock"
        lock_file.write_text(
            "pid=999999999\ntimestamp=2026-01-01T00:00:00Z\nrun_id=old-run\n",
            encoding="utf-8",
        )

        # Should reclaim the stale lock (PID 999999999 is almost certainly dead)
        store.acquire_lock("new-run")

        content = lock_file.read_text(encoding="utf-8")
        assert f"pid={os.getpid()}" in content
        assert "run_id=new-run" in content

    def test_concurrent_contention_raises(self, tmp_path):
        """Second process gets LockContention error."""
        store1 = StateStore(tmp_path, "spec-001", "default")
        store1.acquire_lock("run-001")

        store2 = StateStore(tmp_path, "spec-001", "default")
        with pytest.raises(LockContentionError):
            store2.acquire_lock("run-002")

        store1.release_lock()
