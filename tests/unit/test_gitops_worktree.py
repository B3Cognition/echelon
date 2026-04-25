"""Tests for GitOpsManager.get_latest_worktree."""
from __future__ import annotations

import time

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager


def _make_gitops(tmp_path):
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    return GitOpsManager(config=config, base_dir=str(tmp_path))


def test_get_latest_worktree_returns_most_recent(tmp_path):
    """get_latest_worktree returns highest-mtime worktree dir for spec/strategy."""
    gitops = _make_gitops(tmp_path)

    wt_base = tmp_path / ".specify" / "harness" / "worktrees" / "001" / "default"
    iter1 = wt_base / "iter-1"
    iter2 = wt_base / "iter-2"
    iter1.mkdir(parents=True)
    time.sleep(0.02)
    iter2.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result == str(iter2)


def test_get_latest_worktree_returns_none_when_no_dir(tmp_path):
    """get_latest_worktree returns None when strategy directory does not exist."""
    gitops = _make_gitops(tmp_path)
    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_get_latest_worktree_returns_none_when_empty(tmp_path):
    """get_latest_worktree returns None when strategy dir exists but has no children."""
    gitops = _make_gitops(tmp_path)
    wt_base = tmp_path / ".specify" / "harness" / "worktrees" / "001" / "default"
    wt_base.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result is None
