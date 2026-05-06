"""Tests for run_skill auto-land integration.

Verifies that the run() function calls land() instead of attempt_auto_merge
when auto_merge is True on the intent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.loop_result import LoopResult
from harness.verify_result import VerifyResult


def _make_converged_result() -> LoopResult:
    return LoopResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=1,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=10000,
        final_verify=VerifyResult(passed=True, failures=[]),
    )


def _make_failed_result() -> LoopResult:
    return LoopResult(
        status="failed",
        termination_reason="outer_cap",
        outer_iterations=5,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=50000,
        final_verify=VerifyResult(passed=False, failures=[]),
    )


@pytest.mark.unit
class TestRunSkillAutoLand:
    """Test that run() calls land() when auto_merge is True."""

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_called_when_auto_merge_true(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
    ) -> None:
        """land() is called with correct args when auto_merge is True."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        mock_land.return_value = True

        gitops = MagicMock()
        provider = MagicMock()

        run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        from pathlib import Path
        mock_land.assert_called_once_with(
            "012", project_dir=Path("/tmp/test"), gitops=gitops,
        )

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_not_called_when_auto_merge_false(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
    ) -> None:
        """land() is NOT called when auto_merge is False."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run("spec 012 banzai", provider=provider, gitops=gitops, base_dir="/tmp/test")

        mock_land.assert_not_called()

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_returns_false_logs_warning(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When land() returns False, a warning is logged."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        mock_land.return_value = False

        gitops = MagicMock()
        provider = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING, logger="harness.skills.run_skill"):
            run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        assert any("land() returned False" in record.message for record in caplog.records)
