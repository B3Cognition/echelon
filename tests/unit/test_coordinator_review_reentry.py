"""Tests that the coordinator injects review-fix content into Phase 1 re-entry prompt."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig, ReviewLoopConfig, VisualTestsConfig
from harness.coordinator import StrategyCoordinator
from harness.delivery_results import ImplementationResult, ReviewResult, VisualResult
from harness.verify_result import VerifyResult
from harness.repair_loop import RepairLoop
from harness.run_intent import RunIntent


def _config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        review_loop=ReviewLoopConfig(
            enabled=True,
            max_fix_iterations=2,
        ),
        visual_tests=VisualTestsConfig(enabled=True, max_iterations=1),
    )


def _implementation_result(
    status: str,
    pr_url: str = "https://github.com/org/repo/pull/1",
    *,
    outer_iterations: int = 1,
    tokens_used: int = 0,
) -> ImplementationResult:
    return ImplementationResult(
        status="verified" if status == "converged" else status,
        termination_reason="converged" if status == "converged" else status,
        outer_iterations=outer_iterations,
        inner_iterations=0,
        pr_url=pr_url,
        tokens_used=tokens_used,
        final_verify=None,
    )


@pytest.mark.unit
class TestCoordinatorReviewReentry:

    def test_build_reentry_prompt_injects_review_fix_content(self, tmp_path):
        """_build_reentry_prompt reads canonical review-fix artifacts directly."""
        config = _config(tmp_path)
        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=MagicMock(),
            config=config,
            base_dir=str(tmp_path),
        )

        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "review-fix-1.md").write_text(
            "# Review Fix 1\nFix the z-index issue.\n",
            encoding="utf-8",
        )

        with patch("subprocess.run") as run_git:
            result = coord._build_reentry_prompt(
                "spec 005 semi mode",
                "005",
                spec_dir=spec_dir,
            )

        run_git.assert_not_called()
        assert "## Review Feedback" in result
        assert "Review Fix 1" in result
        assert "Fix the z-index issue." in result
        assert result.startswith("spec 005 semi mode")

    def test_build_reentry_prompt_returns_base_when_no_spec_dir(self, tmp_path):
        """Returns base prompt unchanged when no spec directory exists."""
        config = _config(tmp_path)
        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=MagicMock(),
            config=config,
            base_dir=str(tmp_path),
        )

        result = coord._build_reentry_prompt("spec 099 semi mode", "099")

        assert result == "spec 099 semi mode"

    def test_build_reentry_prompt_returns_base_when_no_review_fix_files(self, tmp_path):
        """Returns base prompt unchanged when branch has no review-fix files."""
        config = _config(tmp_path)
        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=MagicMock(),
            config=config,
            base_dir=str(tmp_path),
        )

        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)

        result = coord._build_reentry_prompt("spec 005 semi mode", "005")

        assert result == "spec 005 semi mode"

    def test_reentry_run_loop_receives_review_content(self, tmp_path):
        """Coordinator passes injected prompt to RalphController on Phase 1 re-entry."""
        workspace = tmp_path / "workspace"
        harness_root = workspace / "runs" / "targets" / "api"
        worktree = harness_root / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        config = _config(workspace)

        spec_dir = workspace / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "review-fix-1.md").write_text(
            "# Review Fix 1\nFix the z-index.\n",
            encoding="utf-8",
        )

        gitops = MagicMock()
        gitops.get_latest_worktree.return_value = str(worktree)

        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=gitops,
            config=config,
            base_dir=str(harness_root),
            build_id="build-1",
            orchestration_root=workspace,
        )

        captured_prompts: list[str] = []

        def phase1_run_loop(**kwargs):
            captured_prompts.append(kwargs.get("build_prompt", ""))
            return _implementation_result("converged")

        intent = RunIntent(
            spec_id="005",
            mode="semi",
            strategies=["default"],
            max_outer=1,
            max_inner=1,
        )
        repair_loop_runs = []

        class SpyRepairLoop(RepairLoop):
            def run(self, draft):
                repair_loop_runs.append(draft)
                return super().run(draft)

        with patch("harness.coordinator.RalphController") as MockRalph, \
             patch("harness.coordinator.ReviewLoopController") as MockReview, \
             patch("harness.coordinator.VisualRalphController") as MockVisual, \
             patch("harness.coordinator.RepairLoop", SpyRepairLoop, create=True), \
             patch("harness.coordinator.StateStore") as MockState, \
             patch("harness.coordinator.load_strategies") as mock_strat:

            # Phase 1: first call converges, second call (re-entry) converges too
            ralph_instance = MagicMock()
            ralph_instance.run_loop.side_effect = [
                _implementation_result(
                    "converged", outer_iterations=2, tokens_used=11
                ),  # initial Phase 1
                _implementation_result(
                    "converged", outer_iterations=3, tokens_used=13
                ),  # Phase 1 re-entry after review_fix_queued
            ]
            MockRalph.return_value = ralph_instance

            # Phase 3: first call returns review_fix_queued, second converged
            review_instance = MagicMock()
            review_instance.run_loop.side_effect = [
                ReviewResult(
                    status="review_fix_queued",
                    termination_reason="review_fix_queued",
                    iterations=1,
                    pr_url="https://github.com/org/repo/pull/1",
                    tokens_used=5,
                ),
                ReviewResult(
                    status="completed",
                    termination_reason="converged",
                    iterations=1,
                    pr_url="https://github.com/org/repo/pull/1",
                    tokens_used=7,
                ),
            ]
            MockReview.return_value = review_instance

            MockVisual.return_value.run_loop.side_effect = [
                VisualResult("passed", "converged", 1, 3, VerifyResult(True, [])),
                VisualResult("passed", "converged", 1, 5, VerifyResult(True, [])),
            ]

            # State store: no-op
            state_instance = MagicMock()
            state_instance.read.return_value = {"status": "initialized"}
            MockState.return_value = state_instance

            # Strategy loader
            from harness.strategy_loader import StrategySpec
            mock_strat.return_value = {"default": StrategySpec()}

            result = coord._run_strategy(
                intent, "default", budget=None, spec=StrategySpec()
            )

        assert len(repair_loop_runs) == 1

        # Phase 1 was called twice
        assert ralph_instance.run_loop.call_count == 2

        # Second call (re-entry) must have review content in build_prompt
        reentry_call = ralph_instance.run_loop.call_args_list[1]
        reentry_prompt = reentry_call.kwargs.get(
            "build_prompt", reentry_call.args[0] if reentry_call.args else ""
        )
        assert "## Review Feedback" in reentry_prompt, (
            f"Expected '## Review Feedback' in re-entry build_prompt, got:\n{reentry_prompt!r}"
        )
        assert "Review Fix 1" in reentry_prompt
        assert MockReview.call_args.kwargs["base_dir"] == str(harness_root)
        assert MockReview.call_args.kwargs["spec_dir"] == spec_dir.resolve()
        assert MockVisual.return_value.run_loop.call_count == 2
        assert result.final_verify == VerifyResult(True, [])
        assert result.outer_iterations == 9
        assert result.tokens_used == 44
