"""Tests for RalphController._commit_and_push — specifically the feature-branch push fix.

Regression: _commit_and_push() used to hardcode 'harness/{spec}/{strategy}/iter-N'
as the branch name and pass it to gitops.push(). In feature-branch mode
(echelon flow) the worktree is checked out on the echelon feature branch
(e.g. '001-weather-dashboard'), not on a harness/* branch, so the push would
fail silently and the generated code would never reach the upstream repo.

The fix reads the actual current branch from the worktree's HEAD before pushing.
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest

from harness.config import HarnessConfig
from harness.escalation import EscalationHandler
from harness.mode import ModeController
from harness.ralph import RalphController
from harness.state import StateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ralph(tmp_path, spec_id="001-feature", strategy_id="default"):
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    state_dir = tmp_path / ".specify" / "extensions" / "echelon" / "harness" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    esc_dir = tmp_path / ".specify" / "extensions" / "echelon" / "harness" / "escalations"
    esc_dir.mkdir(parents=True, exist_ok=True)

    state_store = StateStore(state_dir, spec_id, strategy_id)
    mode = ModeController("banzai")
    esc_handler = EscalationHandler(str(esc_dir.parent))
    gitops = MagicMock()

    ralph = RalphController(
        spec_id=spec_id,
        strategy_id=strategy_id,
        state_store=state_store,
        mode_controller=mode,
        escalation_handler=esc_handler,
        provider=MagicMock(),
        gitops=gitops,
        config=config,
    )
    return ralph, gitops


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCommitAndPushBranchDetection:
    """_commit_and_push reads actual worktree branch, not hardcoded harness/* name."""

    def test_feature_branch_mode_pushes_correct_branch(self, tmp_path):
        """When worktree is on a feature branch, push that branch — not harness/*."""
        ralph, gitops = _make_ralph(tmp_path, spec_id="001-feature")
        worktree_path = str(tmp_path / "worktree")

        with patch("harness.gitops._run_git") as mock_run_git:
            mock_run_git.return_value = MagicMock(stdout="001-feature\n", returncode=0)
            ralph._commit_and_push(worktree_path, outer_iter=0)

        gitops.commit.assert_called_once_with(worktree_path,
                                               "harness: 001-feature/default iter-0")
        gitops.push.assert_called_once_with(worktree_path, "001-feature")

    def test_feature_branch_push_not_hardcoded_harness_name(self, tmp_path):
        """Regression: push must NOT use hardcoded 'harness/{spec}/{strategy}/iter-N'."""
        ralph, gitops = _make_ralph(tmp_path, spec_id="042-payment-flow",
                                    strategy_id="codegen")

        with patch("harness.gitops._run_git") as mock_run_git:
            mock_run_git.return_value = MagicMock(
                stdout="042-payment-flow\n", returncode=0
            )
            ralph._commit_and_push(worktree_path="/tmp/wt", outer_iter=3)

        pushed_branch = gitops.push.call_args[0][1]
        assert pushed_branch == "042-payment-flow", (
            f"Expected feature branch '042-payment-flow', got '{pushed_branch}'. "
            "Regression: hardcoded harness/* branch name silently misses the upstream push."
        )
        assert not pushed_branch.startswith("harness/"), (
            "Hardcoded harness/* branch name detected — this silently fails in "
            "feature-branch mode."
        )

    def test_detached_head_falls_back_to_legacy_name(self, tmp_path):
        """Detached HEAD (no branch) falls back to legacy harness/* name gracefully."""
        ralph, gitops = _make_ralph(tmp_path, spec_id="007-spec", strategy_id="alpha")

        with patch("harness.gitops._run_git") as mock_run_git:
            mock_run_git.return_value = MagicMock(stdout="", returncode=0)
            ralph._commit_and_push(worktree_path="/tmp/wt", outer_iter=1)

        pushed_branch = gitops.push.call_args[0][1]
        assert "007-spec" in pushed_branch
        assert "alpha" in pushed_branch

    def test_commit_failure_still_warns_not_raises(self, tmp_path):
        """Commit failure is caught and logged as warning, not raised."""
        ralph, gitops = _make_ralph(tmp_path)
        gitops.commit.side_effect = Exception("git commit failed")

        with patch("harness.gitops._run_git") as mock_run_git:
            mock_run_git.return_value = MagicMock(stdout="001-feature\n", returncode=0)
            # Should not raise
            ralph._commit_and_push(worktree_path="/tmp/wt", outer_iter=0)

        gitops.push.assert_not_called()

    def test_push_failure_still_warns_not_raises(self, tmp_path):
        """Push failure is caught and logged as warning, not raised."""
        ralph, gitops = _make_ralph(tmp_path)
        gitops.push.side_effect = Exception("network error")

        with patch("harness.gitops._run_git") as mock_run_git:
            mock_run_git.return_value = MagicMock(stdout="001-feature\n", returncode=0)
            # Should not raise
            ralph._commit_and_push(worktree_path="/tmp/wt", outer_iter=0)
