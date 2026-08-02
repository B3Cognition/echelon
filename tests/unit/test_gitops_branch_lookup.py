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
