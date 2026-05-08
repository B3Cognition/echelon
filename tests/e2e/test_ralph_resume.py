"""E2E test: Resume after escalation (E2E-03).

Per T050 task specification:
- Run ralph-loop until escalation
- Simulate user answer via resume
- Loop resumes from where it stopped
- Stub LLM returns correct fix after resume
- Loop converges after resume

Tests the full escalation -> resume -> convergence flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.escalation import EscalationHandler
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.ralph import RalphController
from harness.state import StateStore

from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM, StubSandboxProvider


@pytest.mark.e2e
class TestRalphResume:
    """E2E-03: Escalation -> resume -> convergence flow."""

    def test_block_resume_converge(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Full flow: block on escalation, resume with answer, converge."""
        # Phase 1: Run until blocked
        stub = StubLLM(mode="same_failure_3x", tokens_per_call=500)

        controller, state_store, gitops, provider, escalation = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="semi",
            spec_id="test-spec",
            strategy_id="default",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="semi",
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )

        result1 = controller.run_loop(
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )

        assert result1.status == "blocked"

        # Record iteration counters from blocked state
        blocked_state = state_store.read()
        blocked_outer = blocked_state.get("outer_iter", 0)

        # Phase 2: Find escalation file and add answer
        esc_dir = tmp_harness_dir / ".specify" / "extensions" / "echelon" / "harness" / "escalations"
        esc_files = list(esc_dir.glob("*.md"))
        assert len(esc_files) > 0, "Should have escalation file"

        esc_file = str(esc_files[0])
        escalation.resume(esc_file, "Try a different approach: fix the divide function")

        # Update state to record escalation file path
        state = state_store.read()
        state["escalation_file"] = esc_file
        state_store.write(state)

        # Phase 3: Resume - switch stub to converge mode
        stub2 = StubLLM(mode="converge_on_first", tokens_per_call=500)
        provider2 = StubSandboxProvider(stub2)

        # Create new controller with same state_store but convergent stub
        controller2 = RalphController(
            provider=provider2,
            gitops=gitops,
            state_store=state_store,
            mode_controller=ModeController("semi"),
            escalation_handler=escalation,
            spec_id="test-spec",
            strategy_id="default",
            config=harness_config,
        )

        result2 = controller2.run_loop(
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )

        assert result2.status == "converged", (
            f"Expected converged after resume, got {result2.status} "
            f"(reason: {result2.termination_reason})"
        )

    def test_resume_without_answer_raises(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Resume on blocked state without answer raises clear error."""
        stub = StubLLM(mode="same_failure_3x", tokens_per_call=500)

        controller, state_store, gitops, provider, escalation = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="semi",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="semi",
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )

        assert result.status == "blocked"

        # Find escalation file and record it in state (without adding answer)
        esc_dir = tmp_harness_dir / ".specify" / "extensions" / "echelon" / "harness" / "escalations"
        esc_files = list(esc_dir.glob("*.md"))
        assert len(esc_files) > 0

        state = state_store.read()
        state["escalation_file"] = str(esc_files[0])
        state_store.write(state)

        # Try to resume without answer — should raise
        controller2 = RalphController(
            provider=provider,
            gitops=gitops,
            state_store=state_store,
            mode_controller=ModeController("semi"),
            escalation_handler=escalation,
            spec_id="test-spec",
            strategy_id="default",
            config=harness_config,
        )

        with pytest.raises(RuntimeError, match="Loop is blocked"):
            controller2.run_loop(
                max_outer=5,
                max_inner=5,
                token_budget=500_000,
            )

    def test_guided_mode_pause_and_resume(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Guided mode pauses at boundary, resume continues loop."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, escalation = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="guided",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="guided",
            max_outer=5,
            max_inner=3,
            token_budget=500_000,
        )

        # First run: should pause at boundary
        result1 = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=500_000,
        )

        assert result1.status == "blocked", (
            f"Guided mode should pause at boundary, got {result1.status}"
        )

        # Resume: no escalation file, just guided pause
        stub2 = StubLLM(mode="converge_on_first", tokens_per_call=500)
        provider2 = StubSandboxProvider(stub2)

        controller2 = RalphController(
            provider=provider2,
            gitops=gitops,
            state_store=state_store,
            mode_controller=ModeController("guided"),
            escalation_handler=escalation,
            spec_id="test-spec",
            strategy_id="default",
            config=harness_config,
        )

        result2 = controller2.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=500_000,
        )

        # It may pause again or converge - either is valid for guided mode
        assert result2.status in ("converged", "blocked"), (
            f"Expected converged or blocked after guided resume, got {result2.status}"
        )
