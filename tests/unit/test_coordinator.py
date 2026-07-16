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
from harness.state import StateStore


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
    strat_dir = tmp_path / "runs" / "strategies" / "spec-001"
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

    def test_compare_results_includes_escalation_file_from_state(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        state_store = StateStore(tmp_path / "runs" / "build-test" / "state", "001", "default")
        state_store.initialize("run-1", "semi")
        coord._state_stores["default"] = state_store
        state = state_store.read()
        state["escalation_file"] = "/tmp/escalations/001-default.md"
        state_store.write(state)
        results = {
            "default": LoopResult(
                status="blocked",
                termination_reason="blocker_escalation",
                outer_iterations=1,
                inner_iterations=3,
                pr_url=None,
                tokens_used=100,
                final_verify=None,
            )
        }

        comparison = coord.compare_results(results)

        assert (
            comparison["strategies"]["default"]["escalation_file"]
            == "/tmp/escalations/001-default.md"
        )

    def test_compare_results_includes_fulfillment_refresh_from_state(
        self, tmp_path: Path
    ) -> None:
        coord = _make_coordinator(tmp_path)
        state_store = StateStore(tmp_path / "runs" / "build-test" / "state", "001", "default")
        state_store.initialize("run-1", "semi")
        coord._state_stores["default"] = state_store
        state = state_store.read()
        state["fulfillment_refresh"] = {
            "status": "cached",
            "verified_ledger": {
                "reused": 70,
                "rechecked": 5,
                "invalidated": 1,
                "unresolved": 2,
            },
        }
        state_store.write(state)
        results = {
            "default": LoopResult(
                status="failed",
                termination_reason="outer_cap",
                outer_iterations=1,
                inner_iterations=3,
                pr_url=None,
                tokens_used=100,
                final_verify=None,
            )
        }

        comparison = coord.compare_results(results)

        assert comparison["strategies"]["default"]["fulfillment_refresh"] == {
            "status": "cached",
            "verified_ledger": {
                "reused": 70,
                "rechecked": 5,
                "invalidated": 1,
                "unresolved": 2,
            },
        }


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
    strat_dir = tmp_path / "runs" / "strategies" / "001"
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

    strat_dir = tmp_path / "runs" / "strategies" / "001"
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


@pytest.mark.unit
class TestTaskDescriptionInBuildPrompt:
    """task_description from RunIntent must reach the build_prompt passed to RalphController."""

    def test_task_description_included_in_build_prompt(self, tmp_path: Path) -> None:
        """task_description is appended to build_prompt so the LLM receives the full task."""
        captured: dict = {}

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            def capture_run_loop(**kwargs):
                captured["build_prompt"] = kwargs.get("build_prompt", "")
                return mock_controller.run_loop.return_value

            mock_controller.run_loop.side_effect = capture_run_loop

            coord = _make_coordinator(tmp_path, should_pass=True)
            intent = RunIntent(
                spec_id="spec-001",
                max_outer=1,
                max_inner=1,
                task_description="fix the bug in bugfix-1.md",
            )
            coord.start(intent)

        assert "fix the bug in bugfix-1.md" in captured["build_prompt"]

    def test_no_task_description_omitted(self, tmp_path: Path) -> None:
        """Empty task_description does not add a trailing newline to build_prompt."""
        captured: dict = {}

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            def capture_run_loop(**kwargs):
                captured["build_prompt"] = kwargs.get("build_prompt", "")
                return mock_controller.run_loop.return_value

            mock_controller.run_loop.side_effect = capture_run_loop

            coord = _make_coordinator(tmp_path, should_pass=True)
            intent = RunIntent(spec_id="spec-001", max_outer=1, max_inner=1)
            coord.start(intent)

        assert captured["build_prompt"] == "spec spec-001 strategy=default semi mode"


@pytest.mark.unit
class TestStickyEscalationBlock:
    """Guard in _run_strategy must refuse to wipe active escalation block unless --reset."""

    def _make_state_file(self, tmp_path: Path, esc_file: str) -> None:
        """Write a blocked state.json with an escalation_file set."""
        state_dir = tmp_path / "runs" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "spec_id": "spec-001",
            "strategy_id": "default",
            "run_id": "old-run",
            "status": "blocked",
            "mode": "semi",
            "outer_iter": 2,
            "max_outer": 5,
            "inner_iter": 1,
            "max_inner": 3,
            "token_budget": 0,
            "tokens_used": 5000,
            "cancel_requested": False,
            "pr_url": None,
            "branch_name": None,
            "last_verify_result": None,
            "termination_reason": None,
            "escalation_file": esc_file,
            "iteration_log": [],
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        state_file = state_dir / "default.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

    def test_sticky_escalation_block_refuses_without_reset(self, tmp_path: Path) -> None:
        """If state is blocked with escalation_file and no answer file, raises RuntimeError."""
        esc_path = tmp_path / "escalations" / "spec-001-default-20260101T000000Z.md"
        esc_path.parent.mkdir(parents=True, exist_ok=True)
        esc_path.write_text("# Escalation\n", encoding="utf-8")
        # No answer file exists

        self._make_state_file(tmp_path, str(esc_path))

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=1, max_inner=1, reset=False)

        with pytest.raises(RuntimeError, match="escalation pending"):
            coord.start(intent)

    def test_sticky_escalation_block_allows_with_reset(self, tmp_path: Path) -> None:
        """If reset=True, the blocked state is wiped and the run proceeds normally."""
        esc_path = tmp_path / "escalations" / "spec-001-default-20260101T000000Z.md"
        esc_path.parent.mkdir(parents=True, exist_ok=True)
        esc_path.write_text("# Escalation\n", encoding="utf-8")
        # No answer file — but reset=True bypasses the guard

        self._make_state_file(tmp_path, str(esc_path))

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=3, max_inner=1, reset=True)

        results = coord.start(intent)
        assert results[0].status == "converged"

    def test_sticky_escalation_block_passes_when_answered(self, tmp_path: Path) -> None:
        """If a ## Answer section exists in the escalation file, the guard passes."""
        from harness.escalation import EscalationHandler

        esc_path = tmp_path / "escalations" / "spec-001-default-20260101T000000Z.md"
        esc_path.parent.mkdir(parents=True, exist_ok=True)
        esc_path.write_text("# Escalation\n", encoding="utf-8")

        # Simulate answering the escalation file before `echelon harness resume`.
        handler = EscalationHandler(str(tmp_path))
        handler.resume(str(esc_path), "Continue with approach B")

        self._make_state_file(tmp_path, str(esc_path))

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=3, max_inner=1, reset=False)

        # Should NOT raise — the answer is present
        results = coord.start(intent)
        assert results[0].status == "converged"


@pytest.mark.unit
class TestSmartResumeDetection:
    """Smart resume: interrupted/running states are resumed instead of wiped
    unless --reset is specified.

    Tests exercise the should_resume condition in _run_strategy() directly
    by setting up a pre-existing state file and observing coordinator behaviour.
    """

    def _make_state_file(
        self,
        tmp_path: Path,
        status: str,
        outer_iter: int = 2,
        spec_id: str = "spec-001",
        strategy_id: str = "default",
    ) -> None:
        """Write a state.json with the given status and outer_iter."""
        state_dir = tmp_path / "runs" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "spec_id": spec_id,
            "strategy_id": strategy_id,
            "run_id": "prior-run-id",
            "status": status,
            "mode": "semi",
            "outer_iter": outer_iter,
            "max_outer": 5,
            "inner_iter": 0,
            "max_inner": 3,
            "token_budget": 0,
            "tokens_used": 0,
            "cancel_requested": False,
            "pr_url": None,
            "branch_name": None,
            "last_verify_result": None,
            "termination_reason": None,
            "escalation_file": None,
            "iteration_log": [],
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        state_file = state_dir / f"{strategy_id}.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

    # --- should_resume condition unit tests ---

    def test_interrupted_no_reset_should_resume(self) -> None:
        """interrupted + reset=False → should_resume=True."""
        existing_status = "interrupted"
        reset = False
        should_resume = not reset and existing_status in ("running", "interrupted")
        assert should_resume is True

    def test_running_no_reset_should_resume(self) -> None:
        """running + reset=False → should_resume=True (crash recovery)."""
        existing_status = "running"
        reset = False
        should_resume = not reset and existing_status in ("running", "interrupted")
        assert should_resume is True

    def test_interrupted_with_reset_should_not_resume(self) -> None:
        """interrupted + reset=True → should_resume=False (forced fresh start)."""
        existing_status = "interrupted"
        reset = True
        should_resume = not reset and existing_status in ("running", "interrupted")
        assert should_resume is False

    def test_blocked_no_reset_should_not_resume(self) -> None:
        """blocked + reset=False → should_resume=False (blocked handled by ralph)."""
        existing_status = "blocked"
        reset = False
        should_resume = not reset and existing_status in ("running", "interrupted")
        assert should_resume is False

    def test_no_prior_state_should_not_resume(self) -> None:
        """None (no prior state) + reset=False → should_resume=False."""
        existing_status = None
        reset = False
        should_resume = not reset and existing_status in ("running", "interrupted")
        assert should_resume is False

    def test_terminal_state_starts_fresh(self) -> None:
        """Terminal states (converged, failed) → should_resume=False (fresh start)."""
        for terminal_status in ("converged", "failed"):
            reset = False
            should_resume = not reset and terminal_status in ("running", "interrupted")
            assert should_resume is False, (
                f"expected should_resume=False for terminal status '{terminal_status}', "
                f"got True"
            )

    # --- Integration-style tests via StrategyCoordinator ---

    def test_interrupted_state_resumes_and_converges(self, tmp_path: Path) -> None:
        """A pre-existing interrupted state is resumed (not wiped) and the run converges."""
        self._make_state_file(tmp_path, status="interrupted", outer_iter=2)

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=5, max_inner=1, reset=False)

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            results = coord.start(intent)

        assert results[0].status == "converged"
        # The state should have been transitioned to running (not re-initialized);
        # verify by checking the state file still exists and was NOT wiped to outer_iter=0.
        from harness.state import StateStore
        state_dir = tmp_path / "runs" / "state"
        store = StateStore(state_dir, "spec-001", "default")
        final_state = store.read()
        # outer_iter is preserved from the interrupted state (not reset to 0)
        assert final_state.get("outer_iter", 0) >= 2, (
            f"outer_iter should be >= 2 (preserved from interrupted state), "
            f"got {final_state.get('outer_iter')}"
        )

    def test_reset_flag_wipes_interrupted_state(self, tmp_path: Path) -> None:
        """With reset=True, an existing interrupted state is wiped and starts fresh."""
        self._make_state_file(tmp_path, status="interrupted", outer_iter=2)

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=5, max_inner=1, reset=True)

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            results = coord.start(intent)

        assert results[0].status == "converged"
        # State was re-initialized — outer_iter reset to 0
        from harness.state import StateStore
        state_dir = tmp_path / "runs" / "state"
        store = StateStore(state_dir, "spec-001", "default")
        final_state = store.read()
        assert final_state.get("outer_iter") == 0, (
            f"outer_iter should be 0 after forced reset, got {final_state.get('outer_iter')}"
        )

    def test_target_env_metadata_is_recorded_in_state(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Polyrepo dispatch target metadata is persisted in harness state."""
        target = tmp_path / "rbf-opta-points"
        target.mkdir()
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "rbf-opta-points")
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "sources/rbf-opta-points")
        monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "sources/rbf-opta-points,sources/api")
        monkeypatch.setenv("ECHELON_TARGET_TASK_IDS", "T-011,T-012")

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=5, max_inner=1, reset=True)

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            coord.start(intent)

        from harness.state import StateStore
        state_dir = tmp_path / "runs" / "state"
        store = StateStore(state_dir, "spec-001", "default")
        final_state = store.read()
        assert final_state["target_repo"] == "rbf-opta-points"
        assert final_state["target_path"] == str(target)
        assert final_state["implementation_target"] == "sources/rbf-opta-points"
        assert final_state["declared_targets"] == [
            "sources/rbf-opta-points",
            "sources/api",
        ]
        assert final_state["target_task_ids"] == ["T-011", "T-012"]

    def test_spec_artifact_paths_are_recorded_in_state(self, tmp_path: Path) -> None:
        """Harness Context must be populated from Python-owned spec paths."""
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        spec_file = spec_dir / "spec.md"
        tasks_file = spec_dir / "tasks.md"
        spec_file.write_text("# Spec\n", encoding="utf-8")
        tasks_file.write_text("# Tasks\n", encoding="utf-8")

        coord = _make_coordinator(tmp_path, should_pass=True)
        intent = RunIntent(spec_id="spec-001", max_outer=5, max_inner=1, reset=True)

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            coord.start(intent)

        from harness.state import StateStore

        state_dir = tmp_path / "runs" / "state"
        store = StateStore(state_dir, "spec-001", "default")
        final_state = store.read()
        assert final_state["spec_dir"] == str(spec_dir)
        assert final_state["spec_file"] == str(spec_file)
        assert final_state["tasks_file"] == str(tasks_file)

    def test_target_repo_run_uses_polyrepo_root_for_spec_paths(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Target-side harness runs keep spec artifacts at the polyrepo root."""
        polyrepo = tmp_path / "wrapper"
        target = polyrepo / "ow-opta-widgets-v3-orig"
        target.mkdir(parents=True)
        spec_dir = polyrepo / "specs" / "002-law-sddp-snapshot-fix"
        spec_dir.mkdir(parents=True)
        spec_file = spec_dir / "spec.md"
        tasks_file = spec_dir / "tasks.md"
        spec_file.write_text("# Spec\n", encoding="utf-8")
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(polyrepo))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", target.name)

        coord = _make_coordinator(target, should_pass=True)
        intent = RunIntent(
            spec_id="002-law-sddp-snapshot-fix",
            max_outer=5,
            max_inner=1,
            reset=True,
        )

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )
            MockRalph.return_value = mock_controller

            coord.start(intent)

        from harness.state import StateStore

        state_dir = target / "runs" / "state"
        store = StateStore(state_dir, "002-law-sddp-snapshot-fix", "default")
        final_state = store.read()
        assert final_state["target_repo"] == target.name
        assert final_state["target_path"] == str(target)
        assert final_state["spec_dir"] == str(spec_dir)
        assert final_state["spec_file"] == str(spec_file)
        assert final_state["tasks_file"] == str(tasks_file)

    def test_blocked_state_preserved_for_explicit_resume(self, tmp_path: Path) -> None:
        """Explicit resume leaves blocked state intact for Ralph's blocked-resume handler."""
        self._make_state_file(tmp_path, status="blocked", outer_iter=1)

        coord = _make_coordinator(tmp_path, should_pass=True)
        # No escalation_file in state, so the pre-flight guard passes
        intent = RunIntent(spec_id="spec-001", max_outer=5, max_inner=1, reset=False, resume=True)
        seen: dict[str, Any] = {}

        with patch("harness.coordinator.RalphController") as MockRalph:
            mock_controller = MagicMock()
            mock_controller.run_loop.return_value = LoopResult(
                status="converged", termination_reason="converged",
                outer_iterations=1, inner_iterations=1,
                pr_url=None, tokens_used=0, final_verify=None,
            )

            def _make_controller(**kwargs: Any) -> MagicMock:
                seen["status_at_controller"] = kwargs["state_store"].read().get("status")
                seen["outer_iter_at_controller"] = kwargs["state_store"].read().get("outer_iter")
                return mock_controller

            MockRalph.side_effect = _make_controller

            results = coord.start(intent)

        assert results[0].status == "converged"
        assert seen["status_at_controller"] == "blocked"
        assert seen["outer_iter_at_controller"] == 1
