"""Integration tests for GitOps safety guards.

Tests self-targeting detection and never-push-default-branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.errors import GitOpsError, SelfTargetError
from harness.gitops import GitOpsManager


class TestSelfTargeting:
    """Tests for validate_not_self_targeting (FR-INIT-001)."""

    def test_same_local_path_allowed(self, tmp_path, bare_repo, harness_config):
        """Local same-path is explicitly allowed — supports single-repo model (target_repo: '.')."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))

        # Create a git repo at tmp_path to simulate harness repo
        subprocess.run(
            ["git", "init", str(tmp_path)],
            capture_output=True, check=True,
        )

        # Must NOT raise: local paths are always allowed by design
        mgr.validate_not_self_targeting(str(tmp_path), str(tmp_path))

    def test_different_path_allowed(self, tmp_path, bare_repo, harness_config):
        """Different paths are allowed."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))

        other_dir = tmp_path / "other-repo"
        other_dir.mkdir()

        # Should not raise
        mgr.validate_not_self_targeting(str(other_dir), str(tmp_path))


class TestNeverPushDefault:
    """Tests for FR-REPO-004: never push to default branch."""

    def test_push_default_branch_rejected(self, tmp_path, bare_repo, harness_config):
        """Push to default branch always rejected."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        with pytest.raises(GitOpsError, match="default branch"):
            mgr.push(worktree_path, "main")
