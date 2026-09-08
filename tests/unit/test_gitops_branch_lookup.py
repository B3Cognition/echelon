"""Regression tests for feature-branch lookup failure semantics."""
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from harness.errors import GitOpsError
from harness.gitops import GitOpsManager


def _manager_with_mirror(tmp_path: Path) -> GitOpsManager:
    manager = object.__new__(GitOpsManager)
    manager._mirror_path = tmp_path
    return manager


@pytest.mark.unit
def test_find_feature_branch_propagates_fetch_failure(tmp_path: Path) -> None:
    manager = _manager_with_mirror(tmp_path)
    error = GitOpsError("fetch failed", command="git fetch --all --prune")

    with patch.object(manager, "fetch_mirror", side_effect=error):
        with pytest.raises(GitOpsError, match="fetch failed"):
            manager.find_feature_branch("042")


@pytest.mark.unit
def test_fetch_mirror_reports_locked_worktree_as_incomplete(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    manager = _manager_with_mirror(tmp_path)
    error = GitOpsError(
        "fatal: refusing to fetch into branch 'refs/heads/harness/007/default/iter-0' checked out",
        command="git fetch --all --prune",
    )

    with patch("harness.gitops._run_git", side_effect=error):
        manager.fetch_mirror()

    assert "Mirror refresh incomplete" in caplog.text
    assert "Fetched mirror at" not in caplog.text


@pytest.mark.unit
def test_commit_is_ancestor_checks_selected_delivery_lineage(tmp_path: Path) -> None:
    manager = _manager_with_mirror(tmp_path)

    with patch(
        "harness.gitops._run_git",
        return_value=CompletedProcess([], 0, stdout="", stderr=""),
    ) as run_git:
        assert manager.commit_is_ancestor("a" * 40, "b" * 40) is True

    assert run_git.call_args.args[0] == [
        "merge-base",
        "--is-ancestor",
        "a" * 40,
        "b" * 40,
    ]


@pytest.mark.unit
def test_find_feature_branch_propagates_branch_listing_failure(
    tmp_path: Path,
) -> None:
    manager = _manager_with_mirror(tmp_path)
    error = GitOpsError("list failed", command="git branch --list")

    with (
        patch.object(manager, "fetch_mirror"),
        patch("harness.gitops._run_git", side_effect=error),
    ):
        with pytest.raises(GitOpsError, match="list failed"):
            manager.find_feature_branch("042")


@pytest.mark.unit
def test_find_feature_branch_falls_back_to_numeric_alias(tmp_path: Path) -> None:
    manager = _manager_with_mirror(tmp_path)

    def list_branches(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        pattern = args[-1]
        output = "  906\n" if pattern == "906" else ""
        return CompletedProcess(args, 0, stdout=output, stderr="")

    with (
        patch.object(manager, "fetch_mirror"),
        patch("harness.gitops._run_git", side_effect=list_branches),
    ):
        assert manager.find_feature_branch("906-cli-output-styling") == "906"


@pytest.mark.unit
def test_find_feature_branch_promotes_fetched_upstream_branch(tmp_path: Path) -> None:
    """A local target's fetched canonical branch must become the delivery base."""
    manager = _manager_with_mirror(tmp_path)
    commands: list[list[str]] = []

    def git_result(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(args)
        if args[:3] == ["branch", "--remotes", "--list"]:
            output = "  upstream/003-create-browser-first-3d\n" if args[-1] == "*/003-create-browser-first-3d" else ""
            return CompletedProcess(args, 0, stdout=output, stderr="")
        if args[:3] == ["show-ref", "--verify", "--quiet"]:
            return CompletedProcess(args, 1, stdout="", stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    with (
        patch.object(manager, "fetch_mirror"),
        patch("harness.gitops._run_git", side_effect=git_result),
    ):
        assert (
            manager.find_feature_branch("003-create-browser-first-3d")
            == "003-create-browser-first-3d"
        )

    assert [
        "branch",
        "--no-track",
        "003-create-browser-first-3d",
        "upstream/003-create-browser-first-3d",
    ] in commands


@pytest.mark.unit
def test_find_feature_branch_ignores_nested_remote_harness_candidate(
    tmp_path: Path,
) -> None:
    manager = _manager_with_mirror(tmp_path)
    commands: list[list[str]] = []
    branch = "harness/003-create-browser-first-3d/default/iter-2"

    def git_result(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(args)
        if args[:3] == ["branch", "--remotes", "--list"]:
            output = f"  upstream/{branch}\n" if args[-1].endswith("003-*") else ""
            return CompletedProcess(args, 0, stdout=output, stderr="")
        if args[:3] == ["show-ref", "--verify", "--quiet"]:
            raise AssertionError("nested harness branch must not be promoted")
        if args[:2] == ["branch", "--no-track"]:
            raise AssertionError("nested harness branch must not be recreated")
        return CompletedProcess(args, 0, stdout="", stderr="")

    with (
        patch.object(manager, "fetch_mirror"),
        patch("harness.gitops._run_git", side_effect=git_result),
    ):
        assert manager.find_feature_branch("003-create-browser-first-3d") is None
