"""Tests that the coordinator injects review-fix content into Phase 1 re-entry prompt."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from harness.config import HarnessConfig, ReviewLoopConfig
from harness.coordinator import StrategyCoordinator
from harness.loop_result import LoopResult
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
    )


def _loop_result(status: str, pr_url: str = "https://github.com/org/repo/pull/1") -> LoopResult:
    return LoopResult(
        status=status,
        termination_reason=status,
        outer_iterations=1,
        inner_iterations=0,
        pr_url=pr_url,
        tokens_used=0,
        final_verify=None,
    )


@pytest.mark.unit
class TestCoordinatorReviewReentry:

    def test_build_reentry_prompt_injects_review_fix_content(self, tmp_path):
        """_build_reentry_prompt reads review-fix-*.md from the feature branch."""
        config = _config(tmp_path)
        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=MagicMock(),
            config=config,
            base_dir=str(tmp_path),
        )

        # Simulate git ls-tree listing one review-fix file
        ls_result = MagicMock()
        ls_result.returncode = 0
        ls_result.stdout = "specs/005-my-spec/review-fix-1.md\n"

        # Simulate git show returning the file content
        show_result = MagicMock()
        show_result.returncode = 0
        show_result.stdout = "# Review Fix 1\nFix the z-index issue.\n"

        # Ensure the spec dir exists so glob finds it
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)

        with patch("subprocess.run", side_effect=[ls_result, show_result]):
            result = coord._build_reentry_prompt("spec 005 semi mode", "005")

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

        ls_result = MagicMock()
        ls_result.returncode = 0
        ls_result.stdout = "specs/005-my-spec/spec.md\nspecs/005-my-spec/tasks.md\n"

        with patch("subprocess.run", return_value=ls_result):
            result = coord._build_reentry_prompt("spec 005 semi mode", "005")

        assert result == "spec 005 semi mode"

    def test_reentry_run_loop_receives_review_content(self, tmp_path):
        """Coordinator passes injected prompt to RalphController on Phase 1 re-entry."""
        config = _config(tmp_path)

        # Create spec dir so _build_reentry_prompt can find it
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)

        gitops = MagicMock()
        gitops.get_latest_worktree.return_value = str(tmp_path)

        coord = StrategyCoordinator(
            provider=MagicMock(),
            gitops=gitops,
            config=config,
            base_dir=str(tmp_path),
        )

        captured_prompts: list[str] = []

        def phase1_run_loop(**kwargs):
            captured_prompts.append(kwargs.get("build_prompt", ""))
            return _loop_result("converged")

        # git ls-tree returns one review-fix file; git show returns its content
        ls_result = MagicMock(returncode=0,
                              stdout="specs/005-my-spec/review-fix-1.md\n")
        show_result = MagicMock(returncode=0,
                                stdout="# Review Fix 1\nFix the z-index.\n")

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
             patch("harness.coordinator.RepairLoop", SpyRepairLoop, create=True), \
             patch("harness.coordinator.StateStore") as MockState, \
             patch("harness.coordinator.load_strategies") as mock_strat, \
             patch("subprocess.run", side_effect=[ls_result, show_result]):

            # Phase 1: first call converges, second call (re-entry) converges too
            ralph_instance = MagicMock()
            ralph_instance.run_loop.side_effect = [
                _loop_result("converged"),   # initial Phase 1
                _loop_result("converged"),   # Phase 1 re-entry after review_fix_queued
            ]
            MockRalph.return_value = ralph_instance

            # Phase 3: first call returns review_fix_queued, second converged
            review_instance = MagicMock()
            review_instance.run_loop.side_effect = [
                _loop_result("review_fix_queued"),
                _loop_result("converged"),
            ]
            MockReview.return_value = review_instance

            # State store: no-op
            state_instance = MagicMock()
            state_instance.read.return_value = {"status": "initialized"}
            MockState.return_value = state_instance

            # Strategy loader
            from harness.strategy_loader import StrategySpec
            mock_strat.return_value = {"default": StrategySpec()}

            coord._run_strategy(intent, "default", budget=None, spec=StrategySpec())

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
