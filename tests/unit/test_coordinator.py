"""Tests for StrategyCoordinator.

Per T040 task specification:
- Single strategy passthrough
- 2 strategies with independent mocked RalphControllers
- One strategy fails, other continues
- Status aggregation with mixed states
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig
from harness.coordinator import StrategyCoordinator
from harness.exec_result import ExecResult
from harness.loop_result import LoopResult
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.run_intent import RunIntent


class MockProvider(SandboxProvider):
    """Mock provider that converges on first verify."""

    def __init__(self, should_pass: bool = True) -> None:
        self._should_pass = should_pass

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return SandboxHandle(id="m-1", session_id="s-1")

    def exec(self, handle, cmd, cwd=None, env=None, timeout_ms=1_200_000):
        if "verify" in cmd:
            data = {"passed": self._should_pass, "failures": []}
            return ExecResult(exit_code=0 if self._should_pass else 1,
                              stdout=json.dumps(data), stderr="",
                              duration_ms=500, resource_stats=None)
        return ExecResult(exit_code=0, stdout="ok", stderr="",
                          duration_ms=500, resource_stats=None)

    def write_file(self, handle, path, content): pass
    def read_file(self, handle, path): return b""
    def destroy(self, handle): pass


def _make_coordinator(tmp_path: Path, should_pass: bool = True) -> StrategyCoordinator:
    config = HarnessConfig(
        target_repo="git@example.com:t/r.git",
        target_default_branch="main",
        provider="docker",
    )
    gitops = MagicMock()
    gitops.create_worktree.return_value = str(tmp_path / "worktree")
    gitops.create_draft_pr.return_value = "https://github.com/t/r/pull/1"

    # Create strategy dir for default
    strat_dir = tmp_path / ".specify" / "harness" / "strategies" / "spec-001"
    strat_dir.mkdir(parents=True, exist_ok=True)

    return StrategyCoordinator(
        provider=MockProvider(should_pass=should_pass),
        gitops=gitops,
        config=config,
        base_dir=str(tmp_path),
    )


@pytest.mark.unit
class TestSingleStrategy:
    """Test N=1 passthrough."""

    def test_single_strategy_converges(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=3, max_inner=1)
        results = coord.start(intent)
        assert len(results) == 1
        assert results[0].status == "converged"

    def test_single_strategy_fails(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path, should_pass=False)
        intent = RunIntent(spec_id="spec-001", max_outer=1, max_inner=1)
        results = coord.start(intent)
        assert len(results) == 1
        assert results[0].status == "failed"


@pytest.mark.unit
class TestStatusAggregation:
    """Test status method."""

    def test_no_active_loops(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        status = coord.status()
        assert status["active_loops"] == 0

    def test_status_after_run(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=3, max_inner=1)
        coord.start(intent)
        status = coord.status()
        assert "strategies" in status


@pytest.mark.unit
class TestCompareResults:
    """Test results comparison."""

    def test_compare_mixed_results(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        results = {
            "fast": LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=2, inner_iterations=3,
                pr_url="https://github.com/t/r/pull/1", tokens_used=50000,
                final_verify=None,
            ),
            "safe": LoopResult(
                status="failed", termination_reason="outer_cap",
                outer_iterations=5, inner_iterations=15,
                pr_url=None, tokens_used=80000,
                final_verify=None,
            ),
        }
        comparison = coord.compare_results(results)
        assert comparison["strategy_count"] == 2
        assert comparison["strategies"]["fast"]["converged"] is True
        assert comparison["strategies"]["safe"]["converged"] is False
        assert comparison["summary"]["converged"] == 1
        assert comparison["summary"]["failed"] == 1
        assert comparison["summary"]["total_tokens"] == 130000


from harness.ralph import RalphController


def test_coordinator_runs_visual_loop_after_convergence(tmp_path):
    """StrategyCoordinator triggers visual loop when Phase 1 converges and visual_tests.enabled."""
    from harness.config import VisualTestsConfig
    from harness.visual_ralph import VisualRalphController

    config = HarnessConfig(
        target_repo="git@example.com:t/r.git",
        target_default_branch="main",
        provider="docker",
    )
    config.visual_tests = VisualTestsConfig(
        enabled=True,
        max_iterations=1,
        test_command="npx playwright test --reporter=json",
        serve_command="npm run preview",
        timeout_ms=60_000,
        screenshot_dir="playwright-report",
    )

    # Phase 1 converges immediately
    phase1_result = LoopResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=1,
        inner_iterations=0,
        pr_url=None,
        tokens_used=50,
        final_verify=None,
    )

    # Phase 2 also converges
    phase2_result = LoopResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=1,
        inner_iterations=0,
        pr_url=None,
        tokens_used=30,
        final_verify=None,
    )

    # Create strategy dir
    strat_dir = tmp_path / ".specify" / "harness" / "strategies" / "001"
    strat_dir.mkdir(parents=True, exist_ok=True)

    gitops = MagicMock()
    gitops.create_worktree.return_value = str(tmp_path / "worktree")
    gitops.create_draft_pr.return_value = "https://github.com/t/r/pull/1"
    gitops.get_latest_worktree.return_value = str(tmp_path / "worktree")

    with patch.object(RalphController, "run_loop", return_value=phase1_result), \
         patch.object(VisualRalphController, "run_loop", return_value=phase2_result) as mock_visual:
        coordinator = StrategyCoordinator(
            provider=MockProvider(should_pass=True),
            gitops=gitops,
            config=config,
            base_dir=str(tmp_path),
        )
        intent = RunIntent(spec_id="001", strategies=["default"], mode="banzai",
                           max_outer=3, max_inner=2, token_budget=None, kill_losers=False)
        results = coordinator.start(intent)

    assert mock_visual.called, "VisualRalphController.run_loop must be called"
    assert results[0].status == "converged"
    assert results[0].outer_iterations == 2   # 1 (phase1) + 1 (phase2)
    assert results[0].tokens_used == 80       # 50 (phase1) + 30 (phase2)
    assert results[0].inner_iterations == 0   # preserved from phase1
    assert results[0].pr_url is None          # preserved from phase1


def test_coordinator_skips_visual_loop_when_phase1_fails(tmp_path):
    """Visual loop must NOT be triggered when Phase 1 fails, even if visual_tests.enabled."""
    from harness.config import VisualTestsConfig
    from harness.visual_ralph import VisualRalphController

    config = HarnessConfig(
        target_repo="git@example.com:t/r.git",
        target_default_branch="main",
        provider="docker",
    )
    config.visual_tests = VisualTestsConfig(
        enabled=True,
        max_iterations=1,
        test_command="npx playwright test --reporter=json",
        serve_command="npm run preview",
        timeout_ms=60_000,
        screenshot_dir="playwright-report",
    )

    phase1_fail = LoopResult(
        status="failed",
        termination_reason="outer_cap",
        outer_iterations=3,
        inner_iterations=0,
        pr_url=None,
        tokens_used=50,
        final_verify=None,
    )

    strat_dir = tmp_path / ".specify" / "harness" / "strategies" / "001"
    strat_dir.mkdir(parents=True, exist_ok=True)

    gitops = MagicMock()
    gitops.create_worktree.return_value = str(tmp_path / "worktree")
    gitops.create_draft_pr.return_value = ""
    gitops.get_latest_worktree.return_value = str(tmp_path / "worktree")

    with patch.object(RalphController, "run_loop", return_value=phase1_fail), \
         patch.object(VisualRalphController, "run_loop") as mock_visual:
        coordinator = StrategyCoordinator(
            provider=MockProvider(should_pass=False),
            gitops=gitops,
            config=config,
            base_dir=str(tmp_path),
        )
        intent = RunIntent(spec_id="001", strategies=["default"], mode="banzai",
                           max_outer=3, max_inner=2, token_budget=None, kill_losers=False)
        results = coordinator.start(intent)

    mock_visual.assert_not_called()
    assert results[0].status == "failed"
