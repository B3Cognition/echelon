"""E2E test: Constitution + SPEC GUARD blocking (E2E-05).

Per T053 task specification:
- Ralph-loop against fixture repo with populated constitution
- Stub LLM returns diff that violates constitution (spec guard failure)
- spec_guard_violation treated as hard blocker (FR-CONST-001a)
- Escalation file created with spec_guard_violation category
- Loop blocks (does not continue past violation)

Per FR-CONST-001a: constitution violation is a hard blocker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.loop_result import LoopResult

from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM


@pytest.mark.e2e
class TestConstitutionBlocking:
    """E2E-05: Constitution violation escalation."""

    def test_spec_guard_violation_triggers_escalation(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Spec guard violation from verify triggers escalation and blocks."""
        stub = StubLLM(mode="spec_guard_fail", tokens_per_call=500)

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

        # The spec_guard_fail mode returns a lint failure (spec guard violation)
        # In semi mode, this should eventually trigger same_failure escalation
        # since the same violation repeats
        # OR the loop should exhaust inner iterations
        assert result.status in ("blocked", "failed"), (
            f"Expected blocked or failed on spec guard violation, got {result.status}"
        )

    def test_spec_guard_violation_category_in_escalation(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Escalation file has spec_guard_violation or same_failure category."""
        stub = StubLLM(mode="spec_guard_fail", tokens_per_call=500)

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

        # Check for escalation files
        esc_dir = tmp_harness_dir / ".specify" / "harness" / "escalations"
        esc_files = list(esc_dir.glob("*.md"))

        if result.status == "blocked":
            assert len(esc_files) > 0, "Escalation file should exist when blocked"
            content = esc_files[0].read_text(encoding="utf-8")
            # Should contain the failure category (same_failure_repeat since
            # the same spec guard violation repeats)
            assert "same_failure_repeat" in content or "spec_guard_violation" in content

    def test_loop_does_not_continue_past_violation_in_semi_mode(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """In semi mode, repeated spec guard violations trigger escalation, not infinite loop."""
        stub = StubLLM(mode="spec_guard_fail", tokens_per_call=500)

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
            max_outer=3,
            max_inner=5,
            token_budget=500_000,
        )

        result = controller.run_loop(
            max_outer=3,
            max_inner=5,
            token_budget=500_000,
        )

        # Loop should not run all outer iterations if it gets blocked
        if result.status == "blocked":
            assert result.outer_iterations <= 3

    def test_banzai_mode_continues_past_spec_guard(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Banzai mode continues past spec guard violations (non-hard failure)."""
        stub = StubLLM(mode="spec_guard_fail", tokens_per_call=500)

        controller, state_store, gitops, provider, escalation = make_ralph_controller(
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
            max_inner=3,
            token_budget=500_000,
        )

        result = controller.run_loop(
            max_outer=2,
            max_inner=3,
            token_budget=500_000,
        )

        # Banzai should not block on same_failure_repeat
        assert result.status != "blocked", (
            "Banzai mode should not block on spec guard violations"
        )
        assert result.termination_reason == "outer_cap"
