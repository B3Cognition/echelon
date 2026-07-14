"""Tests for run_skill auto-land integration.

Verifies that the run() function calls land() instead of attempt_auto_merge
when auto_merge is True on the intent.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.harness_run_history import history_path
from harness.loop_result import LoopResult
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


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


def _make_checkpoint_result() -> LoopResult:
    return LoopResult(
        status="blocked",
        termination_reason="build_incomplete",
        outer_iterations=2,
        inner_iterations=3,
        pr_url=None,
        tokens_used=0,
        final_verify=None,
        branch="001-demo",
    )


def _make_checkpoint_outer_cap_result() -> LoopResult:
    return LoopResult(
        status="blocked",
        termination_reason="checkpoint_outer_cap",
        outer_iterations=5,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=0,
        final_verify=VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-refresh-deferred",
                    error="full verify-spec refresh deferred",
                )
            ],
        ),
        branch="001-demo",
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
    def test_resume_uses_existing_build_id(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Resuming must continue the selected build directory instead of minting a new one."""
        from harness.paths import current_build_marker
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="semi", auto_merge=False)
        mock_parse.return_value = intent
        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_failed_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run(
            "spec 012 resume",
            provider=provider,
            gitops=gitops,
            base_dir=str(tmp_path),
            resume_build_id="build-existing",
        )

        assert current_build_marker(tmp_path, "012").read_text(encoding="utf-8") == "build-existing"
        assert mock_coordinator_cls.call_args.kwargs["build_id"] == "build-existing"

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

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_branch_recovery_uses_local_target_repo_path(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Polyrepo runtime dirs are not git checkouts; recover target checkout."""
        from harness.config import HarnessConfig
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        target = tmp_path / "repo-a"
        target.mkdir()
        runtime = tmp_path / "wrapper" / "runs" / "targets" / "repo-a"
        runtime.mkdir(parents=True)
        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        )
        intent = RunIntent(spec_id="012", mode="semi", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run(
            "spec 012 semi",
            provider=provider,
            gitops=gitops,
            base_dir=str(runtime),
            config=config,
        )

        gitops.ensure_on_default_branch.assert_called_once_with(str(target.resolve()))

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_not_called_when_not_converged(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
    ) -> None:
        """land() is NOT called when auto_merge is True but no strategy converged."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_failed_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 0, "failed": 1, "total_tokens": 50000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        mock_land.assert_not_called()

    def test_delivery_summary_renders_build_incomplete_as_checkpointed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Recoverable salvaged harness stops should not be summarized as failed."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_checkpoint_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            base_dir="/tmp/nonexistent",
        )

        captured = capsys.readouterr()
        assert "◐ CHECKPOINTED" in captured.err
        assert "stopped: checkpoint recovery needed" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "0 converged, 0 failed, 1 checkpointed" in captured.err

    def test_delivery_summary_renders_provider_session_limit_as_block(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_checkpoint_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                    "build_status": "provider_session_limit",
                    "provider_limit_message": "You've hit your session limit · resets 9:10pm",
                    "provider_reset_hint": "9:10pm",
                    "salvage_commit": "abcdef1234567890abcdef1234567890abcdef12",
                    "salvage_branch": "harness/001-demo/default/iter-0",
                    "salvage_verified": "not_run",
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            base_dir="/tmp/nonexistent",
        )

        captured = capsys.readouterr()
        assert "◐ PROVIDER SESSION LIMIT" in captured.err
        assert "stopped: provider session limit" in captured.err
        assert "You've hit your session limit" in captured.err
        assert "reset: 9:10pm" in captured.err
        assert "salvage commit: abcdef123456" in captured.err
        assert "salvage branch: harness/001-demo/default/iter-0" in captured.err
        assert "salvage verified: not_run" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "0 converged, 0 failed, 1 provider-limited" in captured.err
        assert "CHECKPOINTED" not in captured.err

    def test_delivery_summary_renders_deferred_outer_cap_as_checkpointed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Outer cap with deferred fulfillment is continuation, not failure."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="banzai")
        result = _make_checkpoint_outer_cap_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            base_dir="/tmp/nonexistent",
        )

        captured = capsys.readouterr()
        assert "◐ CHECKPOINTED" in captured.err
        assert "stopped: checkpoint continuation needed" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "verify: deferred" in captured.err
        assert "verify: ✗ FAILED" not in captured.err
        assert "deferred [other] full verify-spec refresh deferred" in captured.err
        assert "✗ [other] full verify-spec refresh deferred" not in captured.err
        assert "0 converged, 0 failed, 1 checkpointed" in captured.err

    def test_delivery_summary_renders_next_step_for_failed_outer_cap(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="banzai")
        result = _make_failed_result()
        result.final_verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-report-stale",
                    error="fulfillment report is stale for current HEAD abc123",
                )
            ],
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            base_dir="/tmp/nonexistent",
        )

        captured = capsys.readouterr()
        assert "stopped: outer_cap" in captured.err
        assert "next: echelon delivery run 001-demo" in captured.err
        assert "continue with a fresh outer-loop budget" in captured.err

    def test_delivery_summary_promotes_fulfillment_gap_remediation(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-gaps.md").write_text(
            "# Fulfillment Gaps\n\n"
            "## Gap 1 - NFR-008\n\n"
            "- **Remediation (WHAT decision):** Choose a palette with measured "
            "simulated contrast of at least 3:1 for every state pair.\n",
            encoding="utf-8",
        )
        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = LoopResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=1,
            inner_iterations=3,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="fulfillment-gaps",
                        error="fulfillment report has unresolved statuses",
                    )
                ],
            ),
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(intent, {"default": result}, comparison, str(tmp_path))

        captured = capsys.readouterr()
        assert "recommended action:" in captured.err
        assert "Choose a palette with measured simulated contrast" in captured.err

    def test_delivery_summary_prints_suggested_answers_from_escalation_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        escalation_file = tmp_path / "runs" / "build-test" / "escalations" / "906-default.md"
        escalation_file.parent.mkdir(parents=True)
        escalation_file.write_text(
            "# Escalation\n\n"
            "## Decision Metadata\n\n"
            "```json\n"
            "{\n"
            '  "schema_version": 1,\n'
            '  "suggested_answers": [\n'
            "    {\n"
            '      "label": "Continue implementing gaps",\n'
            '      "answer": "Continue delivery using fulfillment-gaps.md as mandatory implementation context.",\n'
            '      "consequence": "Runs another harness-owned implementation attempt.",\n'
            '      "recommended": true\n'
            "    },\n"
            "    {\n"
            '      "label": "Stop and reopen/waive through harness",\n'
            '      "answer": "Stop delivery and use echelon spec reopen 906 for the unresolved requirement decision.",\n'
            '      "consequence": "Keeps the fulfillment gate owned by the harness."\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n",
            encoding="utf-8",
        )
        intent = RunIntent(spec_id="906", mode="semi")
        result = LoopResult(
            status="failed",
            termination_reason="outer_cap",
            outer_iterations=1,
            inner_iterations=3,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="fulfillment-gaps",
                        error="fulfillment report has unresolved statuses",
                    )
                ],
            ),
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                    "escalation_file": str(escalation_file),
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(intent, {"default": result}, comparison, str(tmp_path))

        captured = capsys.readouterr()
        assert "suggested answers:" in captured.err
        assert "Continue implementing gaps (recommended)" in captured.err
        assert 'echelon delivery resume 906 "Continue delivery using fulfillment-gaps.md' in captured.err
        assert "Stop and reopen/waive through harness" in captured.err
        assert "bypass" not in captured.err.lower()
        assert "cherry-pick" not in captured.err.lower()

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.skills.run_skill._print_delivery_summary")
    def test_run_prints_harness_history_before_and_after_and_appends_entry(
        self,
        mock_delivery: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        history_path(spec_dir).write_text(
            '{"runs":[{"build_id":"build-old","strategy_id":"default","status":"failed","termination_reason":"outer_cap","tokens_used":1200}]}',
            encoding="utf-8",
        )

        intent = RunIntent(spec_id="001-demo", mode="banzai", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        result = _make_failed_result()
        coordinator_instance.start.return_value = [result]
        coordinator_instance.compare_results.return_value = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": result.tokens_used},
        }
        coordinator_instance.status.return_value = {"strategies": {"default": {}}}
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        with patch("harness.skills.run_skill._print_harness_history_summary") as mock_history:
            run("spec 001-demo mode=banzai", provider=provider, gitops=gitops, base_dir=str(tmp_path))

        assert mock_history.call_count == 2
        history = history_path(spec_dir).read_text(encoding="utf-8")
        assert '"build_id": "build-old"' in history
        assert '"termination_reason": "outer_cap"' in history
        assert '"tokens_used": 50000' in history

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_exception_caught_and_logged(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When land() raises, the exception is caught and a warning is logged."""
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

        mock_land.side_effect = RuntimeError("git merge failed")

        gitops = MagicMock()
        provider = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING, logger="harness.skills.run_skill"):
            # Must not raise
            run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        assert any("land() raised" in record.message for record in caplog.records)
        assert any("git merge failed" in record.message for record in caplog.records)
