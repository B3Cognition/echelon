"""Regression tests for feature-branch lookup failure semantics."""
from __future__ import annotations

from pathlib import Path
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
