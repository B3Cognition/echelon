"""Unit tests for GC age threshold evaluation.

Tests the logic of identifying stale resources without actual deletion.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from harness.gc import (
    _get_protected_worktrees,
    _get_stale_backups,
    _get_stale_worktrees,
)


class TestStaleWorktreeDetection:
    """Tests for worktree age threshold evaluation."""

    def test_old_worktree_detected(self, tmp_path):
        """Worktrees older than threshold identified for removal."""
        wt_base = tmp_path / "worktrees"
        wt_dir = wt_base / "default" / "iter-1"
        wt_dir.mkdir(parents=True)
        (wt_dir / "README.md").write_text("test")

        # Set mtime to 25 hours ago
        old_time = time.time() - (25 * 3600)
        os.utime(str(wt_dir), (old_time, old_time))

        stale = _get_stale_worktrees(wt_base, max_age_hours=24)
        assert len(stale) == 1
        assert stale[0] == wt_dir

    def test_fresh_worktree_not_detected(self, tmp_path):
        """Worktrees newer than threshold NOT identified."""
        wt_base = tmp_path / "worktrees"
        wt_dir = wt_base / "default" / "iter-1"
        wt_dir.mkdir(parents=True)
        (wt_dir / "README.md").write_text("test")

        # Fresh worktree (just created) should not be stale at 24h threshold
        stale = _get_stale_worktrees(wt_base, max_age_hours=24)
        assert len(stale) == 0

    def test_latest_blocked_worktree_is_protected_from_age_gc(self, tmp_path):
        build_dir = tmp_path / "runs" / "build-1"
        older = build_dir / "worktrees" / "default" / "iter-0"
        latest = build_dir / "worktrees" / "default" / "iter-1"
        older.mkdir(parents=True)
        latest.mkdir(parents=True)
        state_dir = build_dir / "state"
        state_dir.mkdir()
        (state_dir / "default.json").write_text(
            json.dumps({"status": "blocked", "strategy_id": "default"}),
            encoding="utf-8",
        )
        old_time = time.time() - (25 * 3600)
        os.utime(older, (old_time, old_time))
        os.utime(latest, (old_time, old_time))

        protected = _get_protected_worktrees(build_dir)
        stale = _get_stale_worktrees(
            build_dir / "worktrees",
            max_age_hours=24,
            protected=protected,
        )

        assert protected == {latest.resolve()}
        assert stale == [older]

    @pytest.mark.parametrize("status", ["converged", "failed", "cancelled_by_coordinator"])
    def test_terminal_worktrees_are_not_protected(self, tmp_path, status):
        build_dir = tmp_path / "runs" / "build-1"
        worktree = build_dir / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        state_dir = build_dir / "state"
        state_dir.mkdir()
        (state_dir / "default.json").write_text(
            json.dumps({"status": status, "strategy_id": "default"}),
            encoding="utf-8",
        )

        assert _get_protected_worktrees(build_dir) == set()


class TestStaleBackupDetection:
    """Tests for backup file age threshold evaluation."""

    def test_old_backup_detected(self, tmp_path):
        """Backup files older than threshold identified for removal."""
        state_base = tmp_path / "state"
        state_base.mkdir(parents=True)
        bak_file = state_base / "default.json.bak"
        bak_file.write_text("{}")

        # Set mtime to 8 days ago
        old_time = time.time() - (8 * 86400)
        os.utime(str(bak_file), (old_time, old_time))

        stale = _get_stale_backups(state_base, max_age_days=7)
        assert len(stale) == 1
        assert stale[0] == bak_file

    def test_gc_respects_configurable_thresholds(self, tmp_path):
        """GC respects configurable thresholds."""
        state_base = tmp_path / "state"
        state_base.mkdir(parents=True)
        bak_file = state_base / "default.json.bak"
        bak_file.write_text("{}")

        # Set mtime to 3 days ago
        old_time = time.time() - (3 * 86400)
        os.utime(str(bak_file), (old_time, old_time))

        # With 7-day threshold: should NOT be stale
        stale_7d = _get_stale_backups(state_base, max_age_days=7)
        assert len(stale_7d) == 0

        # With 2-day threshold: should be stale
        stale_2d = _get_stale_backups(state_base, max_age_days=2)
        assert len(stale_2d) == 1
