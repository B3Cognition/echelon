"""Tests for gitops_skill CLI.

Verifies that each subcommand calls the correct GitOpsManager method,
prints the expected output, and exits with the correct code.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from harness.skills.gitops_skill import main


def _mock_gitops(**kwargs) -> MagicMock:
    """Return a pre-configured GitOpsManager mock."""
    m = MagicMock()
    for attr, val in kwargs.items():
        setattr(m, attr, val)
    return m


@pytest.mark.unit
class TestFindBranch:
    def test_found(self, capsys):
        gitops = _mock_gitops()
        gitops.find_feature_branch.return_value = "001-weather-dashboard"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["find-branch", "001"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "001-weather-dashboard"
        gitops.find_feature_branch.assert_called_once_with("001")

    def test_not_found_prints_empty(self, capsys):
        gitops = _mock_gitops()
        gitops.find_feature_branch.return_value = None
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["find-branch", "001"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == ""


@pytest.mark.unit
class TestCreateWorktree:
    def test_with_base_branch(self, capsys):
        gitops = _mock_gitops()
        gitops.create_worktree.return_value = "/tmp/worktree/001/default/iter-0"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["create-worktree", "001", "default", "0", "--base-branch", "001-feature"])
        assert rc == 0
        assert "/tmp/worktree" in capsys.readouterr().out
        gitops.create_worktree.assert_called_once_with(
            "001", "default", 0, base_branch="001-feature"
        )

    def test_without_base_branch_passes_none(self, capsys):
        gitops = _mock_gitops()
        gitops.create_worktree.return_value = "/tmp/worktree/001/default/iter-0"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["create-worktree", "001", "default", "0"])
        assert rc == 0
        gitops.create_worktree.assert_called_once_with(
            "001", "default", 0, base_branch=None
        )

    def test_empty_base_branch_passes_none(self, capsys):
        gitops = _mock_gitops()
        gitops.create_worktree.return_value = "/tmp/worktree"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["create-worktree", "001", "default", "0", "--base-branch", ""])
        assert rc == 0
        gitops.create_worktree.assert_called_once_with(
            "001", "default", 0, base_branch=None
        )


@pytest.mark.unit
class TestCommitPush:
    def test_commit_and_push(self, capsys):
        gitops = _mock_gitops()
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["commit-push", "/wt/path", "001-feature", "harness: 001 iter-0"])
        assert rc == 0
        assert "branch: 001-feature" in capsys.readouterr().out
        gitops.commit.assert_called_once_with("/wt/path", "harness: 001 iter-0")
        gitops.push.assert_called_once_with("/wt/path", "001-feature")


@pytest.mark.unit
class TestOpenPr:
    def test_uses_existing_pr(self, capsys):
        gitops = _mock_gitops()
        gitops.find_existing_pr.return_value = "https://github.com/org/repo/pull/7"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["open-pr", "001-feature", "001", "default", "my-feature"])
        assert rc == 0
        assert "https://github.com/org/repo/pull/7" in capsys.readouterr().out
        gitops.create_draft_pr.assert_not_called()
        gitops.promote_pr_ready.assert_not_called()

    def test_creates_and_promotes_when_no_existing(self, capsys):
        gitops = _mock_gitops()
        gitops.find_existing_pr.return_value = None
        gitops.create_draft_pr.return_value = "https://github.com/org/repo/pull/8"
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["open-pr", "001-feature", "001", "default", "my-feature"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "https://github.com/org/repo/pull/8" in out
        gitops.create_draft_pr.assert_called_once_with(
            "001-feature", "001", "default", "my-feature"
        )
        gitops.promote_pr_ready.assert_called_once_with("https://github.com/org/repo/pull/8")


@pytest.mark.unit
class TestMergePr:
    def test_merged(self, capsys):
        gitops = _mock_gitops()
        gitops.merge_pr.return_value = True
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["merge-pr", "https://github.com/org/repo/pull/7"])
        assert rc == 0
        assert "True" in capsys.readouterr().out
        gitops.merge_pr.assert_called_once_with("https://github.com/org/repo/pull/7")

    def test_blocked(self, capsys):
        gitops = _mock_gitops()
        gitops.merge_pr.return_value = False
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["merge-pr", "https://github.com/org/repo/pull/7"])
        assert rc == 0
        assert "False" in capsys.readouterr().out


@pytest.mark.unit
class TestLocalMerge:
    def test_local_merge(self, capsys):
        gitops = _mock_gitops()
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["local-merge", "001-feature", "001", "my-feature"])
        assert rc == 0
        assert "merged: True" in capsys.readouterr().out
        gitops.local_merge.assert_called_once_with("001-feature", "001", "my-feature")


@pytest.mark.unit
class TestErrorHandling:
    def test_exception_returns_1(self, capsys):
        gitops = _mock_gitops()
        gitops.find_feature_branch.side_effect = RuntimeError("mirror missing")
        with patch("harness.skills.gitops_skill._make_gitops", return_value=gitops):
            rc = main(["find-branch", "001"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err
