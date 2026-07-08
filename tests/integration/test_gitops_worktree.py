"""Integration tests for GitOps worktree operations.

Tests create_worktree and destroy_worktree lifecycle.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager


class TestCreateWorktree:
    """Tests for GitOpsManager.create_worktree."""

    def test_create_worktree_creates_directory(self, tmp_path, bare_repo, harness_config):
        """create_worktree creates worktree with correct branch naming convention."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))

        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        assert Path(worktree_path).exists()
        assert Path(worktree_path).is_dir()
        # Verify it contains files from the repo
        assert (Path(worktree_path) / "README.md").exists()

    def test_worktree_on_correct_branch(self, tmp_path, bare_repo, harness_config):
        """Worktree is based on target default branch HEAD with correct branch name."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))

        worktree_path = mgr.create_worktree("012-payment", "conservative", 3)

        # Check branch name
        result = subprocess.run(
            ["git", "-C", worktree_path, "branch", "--show-current"],
            capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == "harness/012-payment/conservative/iter-3"

    def test_create_worktree_supports_empty_target_repo(self, tmp_path):
        """A new source repo with no commits can still get an orphan harness worktree."""
        target = tmp_path / "empty-target"
        subprocess.run(
            ["git", "init", "-b", "main", str(target)],
            capture_output=True,
            text=True,
            check=True,
        )
        source = tmp_path / ".specify" / "extensions" / "echelon"
        (source / "agents" / "control").mkdir(parents=True)
        (source / "workflow").mkdir()
        (source / "agents" / "control" / "commander.md").write_text(
            "# Commander\n",
            encoding="utf-8",
        )
        (source / "workflow" / "definition.yaml").write_text(
            "phases: {}\n",
            encoding="utf-8",
        )
        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
            pr_host="none",
        )
        mgr = GitOpsManager(config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(target))

        worktree_path = mgr.create_worktree("001-new-tool", "default", 0)

        assert Path(worktree_path).exists()
        current = subprocess.run(
            ["git", "-C", worktree_path, "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert current.stdout.strip() == "harness/001-new-tool/default/iter-0"
        status = subprocess.run(
            ["git", "-C", worktree_path, "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "No commits yet" in status.stdout


class TestDestroyWorktree:
    """Tests for GitOpsManager.destroy_worktree."""

    def test_destroy_worktree_removes_directory(self, tmp_path, bare_repo, harness_config):
        """destroy_worktree removes worktree, logs warning on failure."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))

        worktree_path = mgr.create_worktree("012-payment", "default", 1)
        assert Path(worktree_path).exists()

        mgr.destroy_worktree(worktree_path, keep_branch=True)

        # Worktree directory should be gone
        assert not Path(worktree_path).exists()

    def test_destroy_worktree_keeps_branch(self, tmp_path, bare_repo, harness_config):
        """keep_branch=True preserves branch on mirror."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))

        worktree_path = mgr.create_worktree("012-payment", "default", 1)
        mgr.destroy_worktree(worktree_path, keep_branch=True)

        # Branch should still exist in mirror
        result = subprocess.run(
            ["git", "-C", str(mgr.mirror_path), "branch", "--list",
             "harness/012-payment/default/iter-1"],
            capture_output=True, text=True, check=True,
        )
        assert "harness/012-payment/default/iter-1" in result.stdout
