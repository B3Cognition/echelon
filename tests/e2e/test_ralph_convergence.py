"""E2E test: Ralph loop convergence (E2E-01).

Per T048 task specification:
- Full ralph-loop against Python fixture repo with stub LLM
- Stub provides correct fix on first feedback iteration
- Loop converges within 3 outer iterations
- PR created as draft, promoted to ready
- State file shows converged status
- Iteration log has correct entries
- Zero host pollution

Per SC-004: converge within 3 outer iterations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from harness.config import HarnessConfig, NetworkConfig, ResourceLimits
from harness.loop_result import LoopResult
from harness.state import StateStore

from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM


@pytest.mark.e2e
class TestRalphConvergence:
    """E2E-01: Full ralph-loop convergence with stub LLM."""

    def test_converges_within_3_outer_iterations(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Loop converges on first outer iteration with correct fix."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
            stub_llm=stub,
            tmp_dir=tmp_harness_dir,
            harness_config=harness_config,
            mode="semi",
        )

        # Initialize and run
        state_store.acquire_lock("test-run")
        state_store.initialize(
            run_id="test-run",
            mode="semi",
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        # Verify convergence
        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations <= 3, (
            f"Expected convergence within 3 iterations, got {result.outer_iterations}"
        )
        assert gitops.local_merges, "Verified branch must be merged into default branch"
        assert gitops.local_merges[-1]["default_branch"] == "main"

    def test_pr_created_and_promoted(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Draft PR created on first iteration, promoted on convergence."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        assert result.status == "converged"
        assert gitops.pr_created, "Draft PR should have been created"
        assert gitops.pr_promoted, "PR should have been promoted after convergence"
        assert gitops.local_merges, "Default branch merge must happen before convergence"
        assert result.pr_url is not None

    def test_state_file_shows_converged(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """State file has converged status after loop completion."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        # Read state file directly
        final_state = state_store.read()
        assert final_state["status"] == "converged"
        assert final_state.get("termination_reason") == "converged"

    def test_iteration_log_has_correct_entries(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Iteration log records build, verify, and fix phases."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        final_state = state_store.read()
        log = final_state.get("iteration_log", [])
        assert len(log) > 0, "Iteration log should have entries"

        # First entry should be build
        phases = [entry["phase"] for entry in log]
        assert "build" in phases, "Should have a build phase entry"
        assert "verify" in phases, "Should have a verify phase entry"

        # Each entry should have required fields
        for entry in log:
            assert "outer_iter" in entry
            assert "phase" in entry
            assert "exit_code" in entry
            assert "passed" in entry
            assert "duration_s" in entry
            assert "tokens" in entry
            assert "timestamp" in entry

    def test_tokens_tracked(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Token usage is tracked across the loop."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        assert result.tokens_used > 0, "Should have used some tokens"
        # RalphController estimates tokens from stdout length (len/4),
        # not from the stub's internal counter. Just verify positive and
        # consistent with state.
        final_state = state_store.read()
        assert final_state.get("tokens_used", 0) == result.tokens_used, (
            "LoopResult tokens should match state file tokens"
        )

    def test_zero_host_pollution(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """No files created outside .specify/ directory."""
        stub = StubLLM(mode="converge_on_first", tokens_per_call=500)

        # Record files before run
        specify_dir = tmp_harness_dir / ".specify"
        worktree_dir = tmp_harness_dir / "worktrees"

        # Get initial top-level contents (excluding .specify and worktrees)
        initial_contents = {
            p.name for p in tmp_harness_dir.iterdir()
            if p.name not in (".specify", "worktrees", "runs")
        }

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        # Check no new top-level files/dirs (besides .specify and worktrees)
        post_contents = {
            p.name for p in tmp_harness_dir.iterdir()
            if p.name not in (".specify", "worktrees", "runs")
        }
        new_items = post_contents - initial_contents
        assert not new_items, f"Host pollution detected: new items {new_items}"

    def test_converges_on_inner_loop(
        self, tmp_harness_dir: Path, harness_config: HarnessConfig,
    ) -> None:
        """Loop converges after inner loop fix cycle."""
        stub = StubLLM(mode="converge_on_inner", tokens_per_call=500)

        controller, state_store, gitops, provider, _ = make_ralph_controller(
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
            max_inner=3,
            token_budget=100_000,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            token_budget=100_000,
        )

        assert result.status == "converged"
        assert result.inner_iterations > 0, "Should have used inner loop"
