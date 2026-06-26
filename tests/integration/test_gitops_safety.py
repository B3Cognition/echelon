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


class TestSecretScanGate:
    """Tests for deterministic secret scanning before GitOps commits."""

    def test_commit_with_high_confidence_secret_is_rejected(
        self, tmp_path, bare_repo, harness_config
    ):
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.name", "Test"],
            capture_output=True,
            check=True,
        )

        token = "ghp_" + ("A" * 36)
        (Path(worktree_path) / "secrets.env").write_text(
            f"GITHUB_TOKEN={token}\n",
            encoding="utf-8",
        )
        before = subprocess.run(
            ["git", "-C", worktree_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        with pytest.raises(GitOpsError, match="secret scan"):
            mgr.commit(worktree_path, "should be blocked")

        after = subprocess.run(
            ["git", "-C", worktree_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert after == before
