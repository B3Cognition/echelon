"""E2E test: Token budget exhaustion (E2E-04).

Per T051 task specification:
- Ralph-loop with tight token budget
- Stub LLM reports high token usage
- Loop terminates at >= 95% budget threshold
- termination_reason = budget_exhausted
- PR stays as draft (not promoted since not converged)
- Tokens tracked correctly in state

Per FR-LOOP-004: termination conditions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.delivery_results import ImplementationResult

from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM


@pytest.mark.e2e
class TestRalphBudget:
    """E2E-04: Budget exhaustion with 95% threshold."""

    def test_budget_exhaustion_terminates_loop(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Loop terminates when tokens_used >= 95% of budget."""
        # Each call uses 2000 tokens, budget is 5000
        # After 3 calls (build=2000, verify=2000 -> 4000, that is 80%)
        # After build(2000)+verify(2000)+feedback(2000)=6000 -> 120% over 5000
        # But check happens at loop start, so it depends on when the check runs
        stub = StubLLM(mode="never_converge", tokens_per_call=2000)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="banzai",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="banzai",
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        result = controller.run_loop(
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        # Should terminate due to budget, not outer cap
        assert result.termination_reason == "budget_exhausted", (
            f"Expected budget_exhausted, got {result.termination_reason}"
        )
        assert result.status == "blocked"

    def test_tokens_tracked_in_state(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Token usage tracked correctly in state file."""
        stub = StubLLM(mode="never_converge", tokens_per_call=2000)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="banzai",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="banzai",
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        result = controller.run_loop(
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        final_state = state_store.read()
        assert final_state.get("tokens_used", 0) > 0
        assert result.tokens_used > 0
        assert result.tokens_used >= 5000 * 0.95, (
            f"Tokens used ({result.tokens_used}) should be >= 95% of budget (4750)"
        )

    def test_pr_stays_draft_on_budget_exhaustion(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """PR remains as draft when loop does not converge."""
        stub = StubLLM(mode="never_converge", tokens_per_call=2000)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="banzai",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="banzai",
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        result = controller.run_loop(
            max_outer=10,
            max_inner=5,
            token_budget=5000,
        )

        assert result.status == "blocked"
        # PR may or may not be created depending on timing, but should NOT be promoted
        assert not gitops.pr_promoted, "PR should not be promoted when not converged"

    def test_unlimited_budget_does_not_trigger_exhaustion(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """With no token budget, loop runs until outer cap."""
        stub = StubLLM(mode="never_converge", tokens_per_call=10000)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="banzai",
        )

        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="banzai",
            max_outer=2,
            max_inner=2,
            token_budget=0,
        )

        result = controller.run_loop(
            max_outer=2,
            max_inner=2,
            token_budget=None,  # Unlimited
        )

        assert result.termination_reason == "outer_cap", (
            f"Expected outer_cap with unlimited budget, got {result.termination_reason}"
        )
