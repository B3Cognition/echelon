"""Tests for LoopResult dataclass.

Per T031 task specification:
- LoopResult construction with all fields
- State machine transition tests for cancelled_by_coordinator
- cancel_requested flag persistence
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.loop_result import LoopResult, LoopResultError, VALID_STATUSES
from harness.state import StateStore
from harness.verify_result import VerifyResult


@pytest.mark.unit
class TestLoopResultConstruction:
    """Test LoopResult creation and validation."""

    def test_converged_result(self) -> None:
        verify = VerifyResult(passed=True, failures=[], duration_s=10.5, token_usage=5000)
        result = LoopResult(
            status="converged",
            termination_reason="converged",
            outer_iterations=2,
            inner_iterations=3,
            pr_url="https://github.com/org/repo/pull/42",
            tokens_used=50000,
            final_verify=verify,
        )
        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 2
        assert result.inner_iterations == 3
        assert result.pr_url == "https://github.com/org/repo/pull/42"
        assert result.tokens_used == 50000
        assert result.final_verify is not None
        assert result.final_verify.passed is True

    def test_failed_result(self) -> None:
        result = LoopResult(
            status="failed",
            termination_reason="outer_cap",
            outer_iterations=5,
            inner_iterations=15,
            pr_url=None,
            tokens_used=100000,
            final_verify=None,
        )
        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.pr_url is None
        assert result.final_verify is None

    def test_blocked_result(self) -> None:
        result = LoopResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=1,
            inner_iterations=3,
            pr_url="https://github.com/org/repo/pull/42",
            tokens_used=30000,
            final_verify=None,
        )
        assert result.status == "blocked"

    def test_interrupted_result(self) -> None:
        result = LoopResult(
            status="interrupted",
            termination_reason="user_cancel",
            outer_iterations=1,
            inner_iterations=0,
            pr_url=None,
            tokens_used=10000,
            final_verify=None,
        )
        assert result.status == "interrupted"

    def test_cancelled_result(self) -> None:
        result = LoopResult(
            status="cancelled",
            termination_reason="killed_by_coordinator",
            outer_iterations=2,
            inner_iterations=1,
            pr_url="https://github.com/org/repo/pull/43",
            tokens_used=25000,
            final_verify=None,
        )
        assert result.status == "cancelled"
        assert result.termination_reason == "killed_by_coordinator"

    def test_all_statuses_valid(self) -> None:
        for status in VALID_STATUSES:
            result = LoopResult(
                status=status,
                termination_reason="converged",
                outer_iterations=0,
                inner_iterations=0,
                pr_url=None,
                tokens_used=0,
                final_verify=None,
            )
            assert result.status == status

    def test_visual_failed_is_valid_termination_reason(self) -> None:
        """visual_failed must be accepted as a termination reason."""
        result = LoopResult(
            status="failed",
            termination_reason="visual_failed",
            outer_iterations=2,
            inner_iterations=0,
            pr_url=None,
            tokens_used=100,
            final_verify=None,
        )
        assert result.termination_reason == "visual_failed"


@pytest.mark.unit
class TestLoopResultValidation:
    """Test validation rejection cases."""

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(LoopResultError, match="Invalid status"):
            LoopResult(
                status="running",
                termination_reason="converged",
                outer_iterations=0,
                inner_iterations=0,
                pr_url=None,
                tokens_used=0,
                final_verify=None,
            )

    def test_invalid_termination_reason_raises(self) -> None:
        with pytest.raises(LoopResultError, match="Invalid termination_reason"):
            LoopResult(
                status="converged",
                termination_reason="unknown_reason",
                outer_iterations=0,
                inner_iterations=0,
                pr_url=None,
                tokens_used=0,
                final_verify=None,
            )

    def test_negative_outer_iterations_raises(self) -> None:
        with pytest.raises(LoopResultError, match="outer_iterations"):
            LoopResult(
                status="converged",
                termination_reason="converged",
                outer_iterations=-1,
                inner_iterations=0,
                pr_url=None,
                tokens_used=0,
                final_verify=None,
            )

    def test_negative_tokens_raises(self) -> None:
        with pytest.raises(LoopResultError, match="tokens_used"):
            LoopResult(
                status="converged",
                termination_reason="converged",
                outer_iterations=0,
                inner_iterations=0,
                pr_url=None,
                tokens_used=-1,
                final_verify=None,
            )


@pytest.mark.unit
class TestLoopResultSerialization:
    """Test to_dict serialization."""

    def test_to_dict_with_verify(self) -> None:
        verify = VerifyResult(passed=True, failures=[], duration_s=5.0, token_usage=1000)
        result = LoopResult(
            status="converged",
            termination_reason="converged",
            outer_iterations=1,
            inner_iterations=0,
            pr_url="https://github.com/org/repo/pull/1",
            tokens_used=10000,
            final_verify=verify,
        )
        d = result.to_dict()
        assert d["status"] == "converged"
        assert d["final_verify"]["passed"] is True

    def test_to_dict_without_verify(self) -> None:
        result = LoopResult(
            status="failed",
            termination_reason="outer_cap",
            outer_iterations=5,
            inner_iterations=0,
            pr_url=None,
            tokens_used=50000,
            final_verify=None,
        )
        d = result.to_dict()
        assert d["final_verify"] is None


@pytest.mark.unit
class TestCancelRequestedPersistence:
    """Test cancel_requested field in state store."""

    def test_cancel_requested_persisted(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path, "spec-001", "default")
        data = store.initialize("run-1", "semi")
        assert data["cancel_requested"] is False

        data["cancel_requested"] = True
        store.write(data)

        loaded = store.read()
        assert loaded["cancel_requested"] is True

    def test_cancel_requested_survives_transition(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path, "spec-001", "default")
        store.initialize("run-1", "semi")
        store.transition("running")

        data = store.read()
        data["cancel_requested"] = True
        store.write(data)

        data = store.read()
        assert data["cancel_requested"] is True
        assert data["status"] == "running"
