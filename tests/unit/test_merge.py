"""Tests for auto-merge logic.

Per T046 task specification:
- Successful merge with all preconditions met
- Merge skipped -- mode=guided
- Merge skipped -- N>1 strategies
- Merge skipped -- status=failed
- Merge failure -- branch protection
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.delivery_results import DeliveryResult
from harness.merge import attempt_auto_merge
from harness.run_intent import RunIntent
from harness.verify_result import VerifyResult


def _make_converged_result() -> DeliveryResult:
    return DeliveryResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=1,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=10000,
        final_verify=VerifyResult(passed=True, failures=[]),
        blocked_phase=None,
    )


def _make_failed_result() -> DeliveryResult:
    return DeliveryResult(
        status="failed",
        termination_reason="state_corruption",
        outer_iterations=5,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=50000,
        final_verify=VerifyResult(passed=False, failures=[]),
        blocked_phase=None,
    )


@pytest.mark.unit
class TestAutoMerge:
    """Test auto-merge precondition checks."""

    def test_successful_merge(self) -> None:
        intent = RunIntent(spec_id="001", mode="banzai", auto_merge=True)
        gitops = MagicMock()
        gitops.merge_pr.return_value = True

        result = attempt_auto_merge(_make_converged_result(), intent, gitops)

        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/t/r/pull/1")

    def test_merge_skipped_guided_mode(self) -> None:
        # guided + auto_merge can't be constructed via RunIntent (validation),
        # so test directly
        intent = RunIntent.__new__(RunIntent)
        intent.spec_id = "001"
        intent.mode = "guided"
        intent.auto_merge = True
        intent.strategies = ["default"]

        gitops = MagicMock()
        result = attempt_auto_merge(_make_converged_result(), intent, gitops)
        assert result is False
        gitops.merge_pr.assert_not_called()

    def test_merge_skipped_multiple_strategies(self) -> None:
        intent = RunIntent(
            spec_id="001", mode="banzai", auto_merge=True,
            strategies=["fast", "safe"],
        )
        gitops = MagicMock()
        result = attempt_auto_merge(_make_converged_result(), intent, gitops)
        assert result is False
        gitops.merge_pr.assert_not_called()

    def test_merge_skipped_not_converged(self) -> None:
        intent = RunIntent(spec_id="001", mode="banzai", auto_merge=True)
        gitops = MagicMock()
        result = attempt_auto_merge(_make_failed_result(), intent, gitops)
        assert result is False
        gitops.merge_pr.assert_not_called()

    def test_merge_failure_branch_protection(self) -> None:
        intent = RunIntent(spec_id="001", mode="banzai", auto_merge=True)
        gitops = MagicMock()
        gitops.merge_pr.return_value = False

        result = attempt_auto_merge(_make_converged_result(), intent, gitops)
        assert result is False

    def test_merge_not_requested(self) -> None:
        intent = RunIntent(spec_id="001", mode="banzai", auto_merge=False)
        gitops = MagicMock()
        result = attempt_auto_merge(_make_converged_result(), intent, gitops)
        assert result is False
        gitops.merge_pr.assert_not_called()
