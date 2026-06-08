"""Tests for GitOpsManager.get_latest_worktree."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager, _clean_branch_listing


def _make_gitops(tmp_path):
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    return GitOpsManager(config=config, base_dir=str(tmp_path))


def test_get_latest_worktree_returns_most_recent(tmp_path):
    """get_latest_worktree returns highest-mtime worktree dir for strategy."""
    gitops = _make_gitops(tmp_path)

    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
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
    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
    wt_base.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_sync_runtime_extension_copies_untracked_project_extension(tmp_path):
    """Harness worktrees get the local Echelon extension even when it is untracked."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    assert (
        worktree
        / ".specify"
        / "extensions"
        / "echelon"
        / "agents"
        / "control"
        / "commander.md"
    ).read_text(encoding="utf-8") == "commander\n"
    assert ".specify/extensions/echelon/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_fails_before_llm_when_extension_missing(tmp_path):
    """Missing runtime prompts fail deterministically instead of inviting global search."""
    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)

    try:
        gitops.sync_runtime_extension(worktree)
    except Exception as exc:
        assert ".specify/extensions/echelon" in str(exc)
        assert "Run `echelon init`" in str(exc)
    else:
        raise AssertionError("expected missing runtime extension to fail")


def test_clean_branch_listing_strips_git_worktree_marker():
    """`git branch --list` prefixes branches checked out in worktrees with `+`."""
    assert _clean_branch_listing("+ 001-feature") == "001-feature"
    assert _clean_branch_listing("* main") == "main"
    assert _clean_branch_listing("  002-other") == "002-other"
