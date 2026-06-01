"""Tests for GitOpsManager.delete_remote_branch."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from harness.errors import GitOpsError
from harness.gitops import GitOpsManager


def _make_gitops() -> MagicMock:
    """Return a GitOpsManager mock with delete_remote_branch bound as a real method."""
    m = MagicMock(spec=GitOpsManager)
    m.delete_remote_branch = GitOpsManager.delete_remote_branch.__get__(m, GitOpsManager)
    return m


def _make_push_gitops(default_branch: str = "main") -> MagicMock:
    """Return a GitOpsManager mock with push_prepared_branch bound as a real method."""
    m = MagicMock(spec=GitOpsManager)
    m.get_default_branch.return_value = default_branch
    m._ensure_not_default_branch_push = GitOpsManager._ensure_not_default_branch_push.__get__(
        m, GitOpsManager
    )
    m.push_prepared_branch = GitOpsManager.push_prepared_branch.__get__(m, GitOpsManager)
    return m


@pytest.mark.unit
class TestDeleteRemoteBranch:
    def test_calls_git_push_delete(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "push", "origin", "--delete", "042-my-feature"]

    def test_uses_project_dir_as_cwd(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gitops.delete_remote_branch("042-my-feature", project_dir=str(tmp_path))
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == str(tmp_path)

    def test_returns_false_on_git_error(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(128, "git")
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is False

    def test_returns_false_on_timeout(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 60)
            result = gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path)
            )
        assert result is False

    def test_accepts_custom_remote(self, tmp_path) -> None:
        gitops = _make_gitops()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gitops.delete_remote_branch(
                "042-my-feature", project_dir=str(tmp_path), remote="upstream"
            )
        cmd = mock_run.call_args[0][0]
        assert cmd[2] == "upstream"


@pytest.mark.unit
class TestPushPreparedBranch:
    def test_pushes_branch_to_origin_without_force_by_default(self, tmp_path) -> None:
        gitops = _make_push_gitops()
        with patch("harness.gitops._run_git") as run_git:
            gitops.push_prepared_branch(str(tmp_path), "042-my-feature")

        run_git.assert_called_once_with(
            ["push", "origin", "042-my-feature"], cwd=str(tmp_path)
        )

    def test_pushes_with_force_with_lease_when_requested(self, tmp_path) -> None:
        gitops = _make_push_gitops()
        with patch("harness.gitops._run_git") as run_git:
            gitops.push_prepared_branch(
                str(tmp_path), "042-my-feature", force_with_lease=True
            )

        run_git.assert_called_once_with(
            ["push", "--force-with-lease", "origin", "042-my-feature"],
            cwd=str(tmp_path),
        )

    def test_refuses_to_push_default_branch(self, tmp_path) -> None:
        gitops = _make_push_gitops(default_branch="main")

        with (
            patch("harness.gitops._run_git") as run_git,
            pytest.raises(GitOpsError, match="Refusing to push to default branch"),
        ):
            gitops.push_prepared_branch(str(tmp_path), "main")

        run_git.assert_not_called()


@pytest.mark.unit
class TestDeleteRemoteBranchIntegration:
    def test_returns_false_for_nonexistent_remote_branch(self, tmp_path) -> None:
        """Uses a real local git repo — delete_remote_branch on a branch that doesn't exist."""
        import subprocess as sp
        # Set up a bare remote and a clone
        remote = tmp_path / "remote.git"
        remote.mkdir()
        sp.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

        clone = tmp_path / "clone"
        sp.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "config", "user.email", "test@test.com"], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "config", "user.name", "Test"], check=True, capture_output=True)
        # Make an initial commit so the remote has a HEAD
        (clone / "README.md").write_text("hi")
        sp.run(["git", "-C", str(clone), "add", "."], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "commit", "-m", "init"], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "push", "origin", "HEAD:main"], check=True, capture_output=True)

        # Now try to delete a branch that doesn't exist on remote.
        # "Already gone" is treated as success — no cleanup needed.
        m = MagicMock(spec=GitOpsManager)
        m.delete_remote_branch = GitOpsManager.delete_remote_branch.__get__(m, GitOpsManager)
        result = m.delete_remote_branch("nonexistent-branch", project_dir=str(clone))
        assert result is True  # branch not found = already gone = cleanup succeeded

    def test_returns_true_for_existing_remote_branch(self, tmp_path) -> None:
        """Uses a real local git repo — delete_remote_branch on a branch that exists."""
        import subprocess as sp
        remote = tmp_path / "remote.git"
        remote.mkdir()
        sp.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

        clone = tmp_path / "clone"
        sp.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "config", "user.email", "test@test.com"], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "config", "user.name", "Test"], check=True, capture_output=True)
        (clone / "README.md").write_text("hi")
        sp.run(["git", "-C", str(clone), "add", "."], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "commit", "-m", "init"], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "push", "origin", "HEAD:main"], check=True, capture_output=True)
        # Create and push a feature branch
        sp.run(["git", "-C", str(clone), "checkout", "-b", "042-my-feature"], check=True, capture_output=True)
        sp.run(["git", "-C", str(clone), "push", "origin", "042-my-feature"], check=True, capture_output=True)

        m = MagicMock(spec=GitOpsManager)
        m.delete_remote_branch = GitOpsManager.delete_remote_branch.__get__(m, GitOpsManager)
        result = m.delete_remote_branch("042-my-feature", project_dir=str(clone))
        assert result is True

        # Verify branch is gone from remote
        ls = sp.run(["git", "-C", str(clone), "ls-remote", "--heads", "origin"], capture_output=True, text=True)
        assert "042-my-feature" not in ls.stdout
