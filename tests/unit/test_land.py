"""Tests for harness.land — idempotent spec completion."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.land import find_pr_url, land


def _write_state(state_dir: Path, spec_id: str, strategy: str, pr_url: str | None) -> None:
    d = state_dir / spec_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{strategy}.json").write_text(
        json.dumps({"spec_id": spec_id, "pr_url": pr_url}), encoding="utf-8"
    )


def _make_gitops(
    feature_branch: str | None = "042-my-feature",
    merge_result: bool = True,
    delete_result: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.find_feature_branch.return_value = feature_branch
    m.merge_pr.return_value = merge_result
    m.delete_remote_branch.return_value = delete_result
    return m


@pytest.mark.unit
class TestFindPrUrl:
    def test_returns_url_from_state_file(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", "https://github.com/o/r/pull/7")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/7"

    def test_returns_none_when_spec_dir_missing(self, tmp_path: Path) -> None:
        assert find_pr_url("042", tmp_path) is None

    def test_returns_none_when_all_files_lack_pr_url(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", None)
        assert find_pr_url("042", tmp_path) is None

    def test_skips_corrupt_json(self, tmp_path: Path) -> None:
        d = tmp_path / "042"
        d.mkdir()
        (d / "bad.json").write_text("{not json}", encoding="utf-8")
        _write_state(tmp_path, "042", "good", "https://github.com/o/r/pull/9")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/9"


@pytest.mark.unit
class TestLand:
    def test_returns_true_when_feature_branch_not_found(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()

    def test_merges_pr_when_feature_branch_and_pr_url_exist(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")

    def test_deletes_remote_branch_after_merge(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.delete_remote_branch.assert_called_once_with(
            "042-my-feature", project_dir=str(tmp_path)
        )

    def test_returns_false_when_merge_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops(merge_result=False)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is False
        gitops.delete_remote_branch.assert_not_called()

    def test_skips_merge_when_no_pr_url(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        gitops.delete_remote_branch.assert_called_once()

    def test_calls_ensure_on_default_branch(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

    def test_writes_landed_status_to_spec_frontmatter(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("---\ntargets: []\n---\n# Spec\n", encoding="utf-8")
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_is_idempotent_when_branch_already_deleted(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True

    def test_cleans_up_worktrees(self, tmp_path: Path) -> None:
        worktree_dir = (
            tmp_path / ".specify" / "harness" / "worktrees" / "042" / "default" / "iter-0"
        )
        worktree_dir.mkdir(parents=True)
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)

    def test_accepts_explicit_state_dir(self, tmp_path: Path) -> None:
        custom_state = tmp_path / "custom-state"
        _write_state(custom_state, "042", "default", "https://github.com/o/r/pull/9")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops, state_dir=custom_state)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/9")


@pytest.mark.unit
class TestDeleteHarnessBranches:
    """Tests for _delete_harness_branches via land() integration."""

    def test_deletes_legacy_harness_branches(self, tmp_path: Path) -> None:
        """Simulate two harness/* branches existing for spec 042."""
        gitops = _make_gitops()
        list_result = MagicMock(returncode=0, stdout="  harness/042/codegen/iter-0\n  harness/042/codegen/iter-1\n")
        delete_result = MagicMock(returncode=0, stdout="")
        with patch("harness.land.subprocess.run") as mock_run:
            mock_run.side_effect = [list_result, delete_result, delete_result]
            land("042", project_dir=tmp_path, gitops=gitops)
        # First call: git branch --list harness/042/*
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ["git", "branch", "--list", "harness/042/*"]
        # Subsequent calls: git branch -D <branch>
        delete_calls = mock_run.call_args_list[1:]
        deleted_branches = [c[0][0][3] for c in delete_calls]
        assert "harness/042/codegen/iter-0" in deleted_branches
        assert "harness/042/codegen/iter-1" in deleted_branches

    def test_no_error_when_no_harness_branches(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        empty_result = MagicMock(returncode=0, stdout="")
        with patch("harness.land.subprocess.run") as mock_run:
            mock_run.return_value = empty_result
            result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True


@pytest.mark.unit
class TestLandIntegration:
    """Integration tests using real tmp dirs and real git repos."""

    def test_writes_status_and_cleans_worktrees_in_real_filesystem(self, tmp_path: Path) -> None:
        """Full filesystem integration: state file, spec.md, worktree dir all created."""
        import subprocess as sp

        # Set up a minimal git repo so _delete_harness_branches can run
        sp.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)
        (tmp_path / "README.md").write_text("hi")
        sp.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)

        # State file with PR URL
        state_dir = tmp_path / ".specify" / "harness" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")

        # Spec dir
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("---\ntargets: []\n---\n# Body\n", encoding="utf-8")

        # Worktree dir
        worktree_dir = tmp_path / ".specify" / "harness" / "worktrees" / "042" / "default" / "iter-0"
        worktree_dir.mkdir(parents=True)

        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")
        gitops.delete_remote_branch.assert_called_once()
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"
