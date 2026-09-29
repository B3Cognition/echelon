"""Integration tests for GitOps mirror operations.

Tests clone_mirror and fetch_mirror against a local bare repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.gitops import GitOpsManager


class TestCloneMirror:
    """Tests for GitOpsManager.clone_mirror."""

    def test_clone_creates_bare_mirror(self, tmp_path, bare_repo, harness_config):
        """clone_mirror creates bare mirror at expected path."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))

        mirror_path = mgr.clone_mirror(str(bare_repo))

        assert Path(mirror_path).exists()
        assert Path(mirror_path).is_dir()
        # Verify it's a bare repo (has HEAD file)
        assert (Path(mirror_path) / "HEAD").exists()

    def test_clone_mirror_idempotent(self, tmp_path, bare_repo, harness_config):
        """Calling clone_mirror twice fetches on second call (no error)."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))

        mirror_path1 = mgr.clone_mirror(str(bare_repo))
        mirror_path2 = mgr.clone_mirror(str(bare_repo))

        assert mirror_path1 == mirror_path2


class TestFetchMirror:
    """Tests for GitOpsManager.fetch_mirror."""

    def test_fetch_preserves_local_delivery_candidate_branch(
        self, tmp_path, bare_repo, harness_config,
    ):
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))
        mirror = str(mgr.mirror_path)
        head = subprocess.run(
            ["git", "-C", mirror, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        branch = "refs/heads/harness/001-feature/build-1/iter-0"
        subprocess.run(
            ["git", "-C", mirror, "update-ref", branch, head],
            capture_output=True, check=True,
        )

        mgr.fetch_mirror()

        result = subprocess.run(
            ["git", "-C", mirror, "rev-parse", "--verify", branch],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == head

    def test_fetch_updates_mirror(self, tmp_path, bare_repo, harness_config):
        """fetch_mirror updates mirror from remote."""
        mgr = GitOpsManager(harness_config, base_dir=str(tmp_path))
        mgr.clone_mirror(str(bare_repo))

        # Add a new commit to the bare repo (via a temp clone)
        clone_dir = tmp_path / "temp-clone"
        subprocess.run(
            ["git", "clone", str(bare_repo), str(clone_dir)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "config", "user.name", "Test"],
            capture_output=True, check=True,
        )
        (clone_dir / "new-file.txt").write_text("new content")
        subprocess.run(
            ["git", "-C", str(clone_dir), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "commit", "-m", "Second commit"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "push"],
            capture_output=True, check=True,
        )

        # Fetch should succeed
        mgr.fetch_mirror()

        # Verify mirror has the new commit
        result = subprocess.run(
            ["git", "-C", str(mgr.mirror_path), "log", "--oneline"],
            capture_output=True, text=True, check=True,
        )
        assert "Second commit" in result.stdout
