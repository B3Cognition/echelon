"""E2E test: Same-failure escalation (E2E-02).

Per T049 task specification:
- Ralph-loop with stub LLM returning same wrong fix 3 times
- Same-failure detection triggers after 3rd identical failure
- State set to blocked
- Escalation file written with correct structure

Per FR-LOOP-003a: same failure 3x triggers escalation.
Per SC-006: escalation file written within 60 seconds.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.loop_result import LoopResult

from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM


@pytest.mark.e2e
class TestRalphEscalation:
    """E2E-02: Same-failure escalation with stub LLM."""

    def test_escalation_triggers_after_3x_same_failure(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Same failure 3x triggers escalation and blocks loop."""
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
            max_inner=5,  # More inner iterations to accumulate 3 same failures
            token_budget=500_000,
        )

        start_time = time.monotonic()
        result = controller.run_loop(
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )
        elapsed = time.monotonic() - start_time

        assert result.status == "blocked", (
            f"Expected blocked status, got {result.status} "
            f"(reason: {result.termination_reason})"
        )
        assert result.termination_reason == "blocker_escalation"

    def test_state_is_blocked_after_escalation(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """State file shows blocked status after escalation."""
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

        final_state = state_store.read()
        assert final_state["status"] == "blocked"

    def test_escalation_file_created(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Escalation file is written with correct structure."""
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

        # Check escalation directory for files
        esc_dir = tmp_harness_dir / "runs" / "escalations"
        esc_files = list(esc_dir.glob("*.md"))
        assert len(esc_files) > 0, "Escalation file should have been created"

        # Verify escalation file content structure
        content = esc_files[0].read_text(encoding="utf-8")
        assert "# Escalation:" in content
        assert "same_failure_repeat" in content
        assert "## Question" in content
        assert "## Context" in content

    def test_escalation_within_timeout(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Escalation completes within 60 seconds (SC-006)."""
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

        start = time.monotonic()
        result = controller.run_loop(
            max_outer=5,
            max_inner=5,
            token_budget=500_000,
        )
        elapsed = time.monotonic() - start

        assert result.status == "blocked"
        assert elapsed < 60.0, (
            f"Escalation should complete within 60 seconds, took {elapsed:.1f}s"
        )

    def test_banzai_mode_skips_same_failure_escalation(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Banzai mode does not escalate on same_failure_repeat."""
        stub = StubLLM(mode="same_failure_3x", tokens_per_call=500)

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
            max_inner=5,
            token_budget=500_000,
        )

        result = controller.run_loop(
            max_outer=2,
            max_inner=5,
            token_budget=500_000,
        )

        # Banzai mode should not block on same_failure, it should hit outer cap
        assert result.status != "blocked", (
            "Banzai mode should not block on same_failure_repeat"
        )
        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
