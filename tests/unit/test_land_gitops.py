"""Tests for GitOpsManager.delete_remote_branch."""
from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.config import HarnessConfig
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
    m.push_landed_default_branch = GitOpsManager.push_landed_default_branch.__get__(
        m, GitOpsManager
    )
    return m


def _make_local_merge_gitops(tmp_path, default_branch: str = "main") -> MagicMock:
    """Return a GitOpsManager mock with local_merge bound as a real method."""
    m = MagicMock(spec=GitOpsManager)
    m.get_default_branch.return_value = default_branch
    m._mirror_path = tmp_path / "mirror.git"
    m._base_dir = tmp_path
    m._config = HarnessConfig(target_repo=".", target_default_branch=default_branch)
    m.local_merge = GitOpsManager.local_merge.__get__(m, GitOpsManager)
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

    def test_refuses_refspec_shaped_branch(self, tmp_path) -> None:
        gitops = _make_push_gitops(default_branch="main")

        with (
            patch("harness.gitops._run_git") as run_git,
            pytest.raises(GitOpsError, match="refspec-shaped branch"),
        ):
            gitops.push_prepared_branch(str(tmp_path), "HEAD:main")

        run_git.assert_not_called()

    def test_refuses_force_refspec_shaped_branch(self, tmp_path) -> None:
        gitops = _make_push_gitops(default_branch="main")

        with (
            patch("harness.gitops._run_git") as run_git,
            pytest.raises(GitOpsError, match="refspec-shaped branch"),
        ):
            gitops.push_prepared_branch(str(tmp_path), "+main")

        run_git.assert_not_called()

    def test_land_push_allows_default_branch(self, tmp_path) -> None:
        gitops = _make_push_gitops(default_branch="main")

        with patch("harness.gitops._run_git") as run_git:
            result = gitops.push_landed_default_branch(str(tmp_path), "main")

        assert result is True
        run_git.assert_called_once_with(["push", "origin", "main"], cwd=str(tmp_path))

    def test_land_push_returns_false_on_git_error(self, tmp_path) -> None:
        gitops = _make_push_gitops(default_branch="main")

        with patch("harness.gitops._run_git", side_effect=GitOpsError("rejected")):
            result = gitops.push_landed_default_branch(str(tmp_path), "main")

        assert result is False


@pytest.mark.unit
class TestCommitDefaultBranchAncestryGuard:
    def test_refuses_delivery_evidence_commit_on_main_before_harness_branch_lands(
        self, tmp_path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)

        subprocess.run(
            ["git", "checkout", "-b", "harness/910/default/iter-1"],
            cwd=repo,
            check=True,
        )
        (repo / "feature.txt").write_text("model_tier support\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "feature"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)

        (repo / "test-results.json").write_text('{"fresh": true}\n', encoding="utf-8")
        message = build_echelon_commit_message(
            "chore: refresh evidence",
            EchelonCommitMetadata(
                origin="delivery",
                action="verification-evidence",
                spec_id="910",
                strategy="default",
            ),
        )
        gitops = GitOpsManager(
            config=HarnessConfig(target_repo=str(repo), target_default_branch="main"),
            base_dir=str(repo),
        )

        with pytest.raises(GitOpsError, match="unmerged harness branch"):
            gitops.commit(str(repo), message)

        head = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == "main"
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert status == "?? test-results.json"

    def test_allows_delivery_evidence_commit_after_harness_branch_lands(
        self, tmp_path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)

        subprocess.run(
            ["git", "checkout", "-b", "harness/910/default/iter-1"],
            cwd=repo,
            check=True,
        )
        (repo / "feature.txt").write_text("model_tier support\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "feature"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "merge", "--no-ff", "harness/910/default/iter-1", "-m", "merge"],
            cwd=repo,
            check=True,
        )

        (repo / "test-results.json").write_text('{"fresh": true}\n', encoding="utf-8")
        message = build_echelon_commit_message(
            "chore: refresh evidence",
            EchelonCommitMetadata(
                origin="delivery",
                action="verification-evidence",
                spec_id="910",
                strategy="default",
            ),
        )
        gitops = GitOpsManager(
            config=HarnessConfig(target_repo=str(repo), target_default_branch="main"),
            base_dir=str(repo),
        )

        sha = gitops.commit(str(repo), message)

        assert sha
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert log == "[skip ci] chore: refresh evidence"


@pytest.mark.unit
class TestLocalMerge:
    def test_proves_feature_branch_is_on_default_before_push(self, tmp_path) -> None:
        gitops = _make_local_merge_gitops(tmp_path)

        with patch("harness.gitops._run_git") as run_git:
            gitops.local_merge("harness/909/default/iter-1", "909")

        mirror_cwd = str(gitops._mirror_path)
        landing_dir = (
            tmp_path
            / "runs"
            / "worktrees"
            / f"land-909-harness-909-default-iter-1-{os.getpid()}"
        )
        landing_cwd = str(landing_dir)
        run_git.assert_any_call(
            ["worktree", "add", landing_cwd, "main"],
            cwd=mirror_cwd,
        )
        run_git.assert_any_call(
            [
                "merge",
                "--no-ff",
                "harness/909/default/iter-1",
                "-m",
                "merge: 909",
            ],
            cwd=landing_cwd,
        )
        run_git.assert_any_call(
            [
                "merge-base",
                "--is-ancestor",
                "harness/909/default/iter-1",
                "main",
            ],
            cwd=landing_cwd,
        )
        run_git.assert_any_call(["push", "upstream", "main"], cwd=landing_cwd)

    @pytest.mark.integration
    def test_updates_local_target_default_branch_from_mirror_branch(self, tmp_path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=target,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=target,
            check=True,
        )
        (target / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=target, check=True)
        subprocess.run(
            ["git", "config", "receive.denyCurrentBranch", "updateInstead"],
            cwd=target,
            check=True,
        )

        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        )
        gitops = GitOpsManager(config=config, base_dir=str(tmp_path / "harness"))
        gitops.clone_mirror(str(target))

        feature_worktree = tmp_path / "feature-worktree"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "harness/909/default/iter-1",
                str(feature_worktree),
                "main",
            ],
            cwd=gitops.mirror_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=feature_worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=feature_worktree,
            check=True,
        )
        (feature_worktree / "built.txt").write_text("spec 909\n", encoding="utf-8")
        subprocess.run(["git", "add", "built.txt"], cwd=feature_worktree, check=True)
        subprocess.run(["git", "commit", "-m", "build 909"], cwd=feature_worktree, check=True)

        result = gitops.local_merge("harness/909/default/iter-1", "909")

        contains = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "harness/909/default/iter-1", "main"],
            cwd=gitops.mirror_path,
            check=False,
        )
        assert contains.returncode == 0
        assert (target / "built.txt").read_text(encoding="utf-8") == "spec 909\n"
        assert result["mirror_landed"] is True
        assert result["pushed"] is True
        assert result["target_synced"] is True

    @pytest.mark.integration
    def test_dirty_local_target_skips_checkout_sync_after_mirror_landing(
        self, tmp_path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=target,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=target,
            check=True,
        )
        (target / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=target, check=True)
        (target / "dirty.txt").write_text("do not overwrite\n", encoding="utf-8")

        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        )
        gitops = GitOpsManager(config=config, base_dir=str(tmp_path / "harness"))
        gitops.clone_mirror(str(target))
        mirror_main_before = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=gitops.mirror_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        feature_worktree = tmp_path / "feature-worktree"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "harness/909/default/iter-1",
                str(feature_worktree),
                "main",
            ],
            cwd=gitops.mirror_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=feature_worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=feature_worktree,
            check=True,
        )
        (feature_worktree / "built.txt").write_text("spec 909\n", encoding="utf-8")
        subprocess.run(["git", "add", "built.txt"], cwd=feature_worktree, check=True)
        subprocess.run(["git", "commit", "-m", "build 909"], cwd=feature_worktree, check=True)

        result = gitops.local_merge("harness/909/default/iter-1", "909")

        mirror_main_after = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=gitops.mirror_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert mirror_main_after != mirror_main_before
        contains = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "harness/909/default/iter-1", "main"],
            cwd=gitops.mirror_path,
            check=False,
        )
        assert contains.returncode == 0
        assert not (target / "built.txt").exists()
        assert (target / "dirty.txt").read_text(encoding="utf-8") == "do not overwrite\n"
        assert result["mirror_landed"] is True
        assert result["pushed"] is False
        assert result["target_synced"] is False
        assert result["target_sync_skipped"] is True
        assert result["target_sync_skip_reason"] == "dirty_local_worktree"

    @pytest.mark.integration
    def test_failed_local_merge_push_rolls_back_mirror_default(
        self, tmp_path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=target,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=target,
            check=True,
        )
        (target / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=target, check=True)

        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        )
        gitops = GitOpsManager(config=config, base_dir=str(tmp_path / "harness"))
        gitops.clone_mirror(str(target))
        mirror_main_before = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=gitops.mirror_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        feature_worktree = tmp_path / "feature-worktree"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "harness/909/default/iter-1",
                str(feature_worktree),
                "main",
            ],
            cwd=gitops.mirror_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=feature_worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=feature_worktree,
            check=True,
        )
        (feature_worktree / "built.txt").write_text("spec 909\n", encoding="utf-8")
        subprocess.run(["git", "add", "built.txt"], cwd=feature_worktree, check=True)
        subprocess.run(["git", "commit", "-m", "build 909"], cwd=feature_worktree, check=True)

        import harness.gitops as gitops_module

        original_run_git = gitops_module._run_git
        with patch("harness.gitops._run_git") as run_git:
            def fail_push(args, **kwargs):
                if args == ["push", "upstream", "main"]:
                    raise GitOpsError("remote rejected")
                return original_run_git(args, **kwargs)

            run_git.side_effect = fail_push
            with pytest.raises(GitOpsError, match="remote rejected"):
                gitops.local_merge("harness/909/default/iter-1", "909")

        mirror_main_after = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=gitops.mirror_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert mirror_main_after == mirror_main_before


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
