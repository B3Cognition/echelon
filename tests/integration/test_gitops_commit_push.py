"""Integration tests for GitOps commit and push operations.

Tests commit with [skip ci], force-with-lease push, and non-ff retry.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.gitops import GitOpsManager


class TestCommit:
    """Tests for GitOpsManager.commit."""

    def test_commit_with_skip_ci(self, tmp_path, bare_repo, harness_config):
        """Commit message contains [skip ci] when ci_skip_enabled=true."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        # Make a change
        (Path(worktree_path) / "new-file.txt").write_text("hello")

        # Configure git user in worktree
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.name", "Test"],
            capture_output=True, check=True,
        )

        sha = mgr.commit(worktree_path, "test commit", skip_ci=True)

        assert sha  # non-empty SHA

        # Check commit message
        result = subprocess.run(
            ["git", "-C", worktree_path, "log", "-1", "--format=%s"],
            capture_output=True, text=True, check=True,
        )
        assert "[skip ci]" in result.stdout

    def test_commit_without_skip_ci(self, tmp_path, bare_repo, harness_config):
        """Commit message does NOT contain [skip ci] when skip_ci=False."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        (Path(worktree_path) / "new-file.txt").write_text("hello")
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.name", "Test"],
            capture_output=True, check=True,
        )

        sha = mgr.commit(worktree_path, "test commit", skip_ci=False)

        result = subprocess.run(
            ["git", "-C", worktree_path, "log", "-1", "--format=%s"],
            capture_output=True, text=True, check=True,
        )
        assert "[skip ci]" not in result.stdout

    def test_push_force_with_lease(self, tmp_path, bare_repo, harness_config):
        """push --force-with-lease succeeds on clean push."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        worktree_path = mgr.create_worktree("012-payment", "default", 1)

        # The mirror's origin remote uses --mirror push refspec which conflicts
        # with named-branch pushes. Reconfigure the push refspec on the mirror
        # so that pushing a specific branch works.
        subprocess.run(
            ["git", "-C", str(mgr.mirror_path), "config", "--unset-all",
             "remote.origin.mirror"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "-C", str(mgr.mirror_path), "config",
             "remote.origin.push", "+refs/heads/*:refs/heads/*"],
            capture_output=True, check=True,
        )

        (Path(worktree_path) / "new-file.txt").write_text("hello")
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", worktree_path, "config", "user.name", "Test"],
            capture_output=True, check=True,
        )

        mgr.commit(worktree_path, "test commit")

        # Push should succeed (bare_repo as origin)
        branch = "harness/012-payment/default/iter-1"
        mgr.push(worktree_path, branch)

        # Verify the branch exists on the remote (bare repo)
        result = subprocess.run(
            ["git", "-C", str(bare_repo), "branch", "--list", branch],
            capture_output=True, text=True, check=True,
        )
        assert branch in result.stdout
