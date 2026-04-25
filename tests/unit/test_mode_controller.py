"""Tests for ModeController.

Per T029 task specification:
- 6 tests covering mode resolution for all 3 modes
- 3 tests for should_escalate per mode
- 1 test for mid-run rejection (validate_mode_change)
"""

from __future__ import annotations

import pytest

from harness.mode import ModeController, ModeValidationError


@pytest.mark.unit
class TestModeControllerConstruction:
    """Test mode initialization and validation."""

    def test_banzai_mode(self) -> None:
        mc = ModeController("banzai")
        assert mc.mode == "banzai"

    def test_semi_mode(self) -> None:
        mc = ModeController("semi")
        assert mc.mode == "semi"

    def test_guided_mode(self) -> None:
        mc = ModeController("guided")
        assert mc.mode == "guided"

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ModeValidationError, match="Invalid mode"):
            ModeController("turbo")

    def test_empty_mode_raises(self) -> None:
        with pytest.raises(ModeValidationError, match="Invalid mode"):
            ModeController("")

    def test_mode_is_readonly(self) -> None:
        mc = ModeController("semi")
        with pytest.raises(AttributeError):
            mc.mode = "banzai"  # type: ignore[misc]


@pytest.mark.unit
class TestShouldPauseAtBoundary:
    """Test should_pause_at_boundary for all modes."""

    def test_guided_pauses_after_build(self) -> None:
        mc = ModeController("guided")
        assert mc.should_pause_at_boundary("after_build") is True

    def test_guided_pauses_after_verify(self) -> None:
        mc = ModeController("guided")
        assert mc.should_pause_at_boundary("after_verify") is True

    def test_semi_does_not_pause(self) -> None:
        mc = ModeController("semi")
        assert mc.should_pause_at_boundary("after_build") is False
        assert mc.should_pause_at_boundary("after_verify") is False

    def test_banzai_does_not_pause(self) -> None:
        mc = ModeController("banzai")
        assert mc.should_pause_at_boundary("after_build") is False
        assert mc.should_pause_at_boundary("after_verify") is False


@pytest.mark.unit
class TestShouldEscalate:
    """Test should_escalate per mode."""

    def test_guided_escalates_everything(self) -> None:
        mc = ModeController("guided")
        assert mc.should_escalate("same_failure_repeat") is True
        assert mc.should_escalate("spec_guard_violation") is True
        assert mc.should_escalate("why_quality_regression") is True
        assert mc.should_escalate("budget_exhaustion") is True
        assert mc.should_escalate("infra_failure") is True
        assert mc.should_escalate("any_unknown_category") is True

    def test_semi_escalates_blockers(self) -> None:
        mc = ModeController("semi")
        assert mc.should_escalate("same_failure_repeat") is True
        assert mc.should_escalate("spec_guard_violation") is True
        assert mc.should_escalate("why_quality_regression") is True
        assert mc.should_escalate("budget_exhaustion") is True
        assert mc.should_escalate("infra_failure") is True
        # Unknown categories NOT escalated
        assert mc.should_escalate("minor_issue") is False

    def test_banzai_only_hard_failures(self) -> None:
        mc = ModeController("banzai")
        assert mc.should_escalate("infra_failure") is True
        assert mc.should_escalate("budget_exhaustion") is True
        # Soft failures NOT escalated
        assert mc.should_escalate("same_failure_repeat") is False
        assert mc.should_escalate("spec_guard_violation") is False
        assert mc.should_escalate("why_quality_regression") is False
        assert mc.should_escalate("minor_issue") is False


@pytest.mark.unit
class TestModeImmutability:
    """Test FR-MODE-002: mode is immutable after initialization."""

    def test_validate_mode_change_always_raises(self) -> None:
        mc = ModeController("semi")
        with pytest.raises(ModeValidationError, match="FR-MODE-002"):
            mc.validate_mode_change("banzai")

    def test_validate_mode_change_raises_with_no_args(self) -> None:
        mc = ModeController("banzai")
        with pytest.raises(ModeValidationError, match="FR-MODE-002"):
            mc.validate_mode_change()
