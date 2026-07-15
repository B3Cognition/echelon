"""Contract checks for E2E GitOps test doubles."""

from __future__ import annotations

import inspect

from harness.gitops import GitOpsManager
from tests.e2e.conftest import MockGitOps


def test_mock_gitops_create_worktree_accepts_codegraph_prepare_flag() -> None:
    """E2E mock accepts the runtime-preparation flag Ralph passes in delivery."""
    real_param = inspect.signature(GitOpsManager.create_worktree).parameters[
        "prepare_codegraph"
    ]
    mock_param = inspect.signature(MockGitOps.create_worktree).parameters[
        "prepare_codegraph"
    ]

    assert mock_param.kind == real_param.kind
    assert mock_param.default is real_param.default
