"""Integration tests for RalphController — cancel_requested state handling.

Mirrors the squad harness fix in commit 34981c4:
  fix: stale cancel_requested from Ctrl+C no longer breaks next echelon run

These tests exercise the full state-file code path (StateStore on disk)
rather than mocking, so they live in integration/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from harness.config import HarnessConfig, NetworkConfig, ResourceLimits
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.ralph import RalphController
from harness.state import StateStore


# === Minimal mock provider ===


class _ConvergeProvider(SandboxProvider):
    """Provider that immediately passes verification so the loop converges."""

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return SandboxHandle(id="mock-1", session_id="sess-1")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        # Always report a passing verify so the loop converges immediately.
        return ExecResult(
            exit_code=0,
            stdout=json.dumps({"passed": True, "failures": []}),
            stderr="",
            duration_ms=50,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        pass


# === Helpers ===


def _make_gitops() -> MagicMock:
    gitops = MagicMock()
    gitops.create_worktree.return_value = "/tmp/worktree"
    gitops.destroy_worktree.return_value = None
    gitops.commit.return_value = "abc123"
    gitops.push.return_value = None
    gitops.create_draft_pr.return_value = "https://github.com/test/repo/pull/1"
    gitops.promote_pr_ready.return_value = None
    return gitops


def _make_controller(tmp_path: Path, mode: str = "semi") -> tuple:
    """Create a minimal RalphController with real StateStore on disk."""
    config = HarnessConfig(
        target_repo="git@github.com:test/repo.git",
        target_default_branch="main",
        provider="docker",
    )
    state_store = StateStore(tmp_path, "spec-001", "default")
    mode_controller = ModeController(mode)
    escalation_handler = EscalationHandler(str(tmp_path / "harness"))
    provider = _ConvergeProvider()
    gitops = _make_gitops()

    controller = RalphController(
        provider=provider,
        gitops=gitops,
        state_store=state_store,
        mode_controller=mode_controller,
        escalation_handler=escalation_handler,
        spec_id="spec-001",
        strategy_id="default",
        config=config,
    )
    return controller, state_store


# === Tests ===


class TestStaleCancelRequestedClearedOnResume:
    """Regression: stale cancel_requested from a previous Ctrl+C/coordinator cancel
    must not block the next run from proceeding.

    Mirrors test_stale_cancel_requested_cleared_on_resume from the squad harness
    (tests/integration/test_squad_controller.py).

    Scenario: the coordinator wrote cancel_requested=True to this strategy's state
    (kill_losers), the strategy's process ended, and on re-invocation the state file
    still has cancel_requested=True from the previous run.  The new invocation calls
    initialize() which resets to status=initialized but a race or other codepath could
    leave cancel_requested stale.  The fix in _run_loop_inner clears it immediately
    after transitioning to running.
    """

    def test_stale_cancel_requested_cleared_on_resume(self, tmp_path: Path) -> None:
        """cancel_requested left in state.json by a previous run does not
        prevent a fresh invocation from proceeding."""
        controller, state_store = _make_controller(tmp_path)

        # Simulate: fresh initialize(), then a stale cancel_requested is present
        # (e.g. written by coordinator kill_losers on the previous run, before
        # initialize() flushed it, or by any other pre-existing path).
        state_store.initialize("run-fresh", "semi")
        # Inject cancel_requested=True directly into the initialized state,
        # mirroring what the coordinator's kill_losers path does.
        state = state_store.read()
        state["cancel_requested"] = True
        state_store.write(state)

        # Confirm the stale flag is on disk before calling run_loop.
        on_disk = state_store.read()
        assert on_disk["cancel_requested"] is True
        assert on_disk["status"] == "initialized"

        # run_loop must clear cancel_requested and proceed rather than
        # immediately exiting with status=cancelled.
        result = controller.run_loop(max_outer=3, max_inner=1)

        assert result.status in ("verified", "failed", "interrupted"), (
            f"Expected run to proceed past stale cancel_requested. "
            f"Got status={result.status!r}, reason={result.termination_reason!r}"
        )

    def test_fresh_init_not_affected(self, tmp_path: Path) -> None:
        """Fresh initialization already starts with cancel_requested=False;
        the fix is a no-op and the run proceeds normally."""
        controller, state_store = _make_controller(tmp_path)
        state_store.initialize("run-fresh", "semi")

        on_disk = state_store.read()
        assert on_disk["cancel_requested"] is False

        result = controller.run_loop(max_outer=3, max_inner=1)
        assert result.status in ("verified", "failed", "interrupted")


class TestBudgetBumpAutoResume:
    """Budget-exhausted auto-resume: when a run writes status=blocked with
    termination_reason=budget_exhausted, the next call with a higher budget
    should resume rather than starting fresh.
    """

    def test_budget_bump_auto_resumes(self, tmp_path: Path) -> None:
        """Calling run_loop with a budget higher than stored usage resumes
        the run (status is not blocked)."""
        controller, state_store = _make_controller(tmp_path)

        # Simulate a prior run that hit the budget limit
        state_store.initialize("run-001", "semi")
        state_store.transition("running")
        state = state_store.read()
        state["tokens_used"] = 5000
        state["termination_reason"] = "budget_exhausted"
        state["outer_iter"] = 1
        state["inner_iter"] = 0
        state_store.write(state)
        state_store.transition(
            "blocked", updates={"blocked_phase": "implementation"}
        )

        # Confirm setup
        on_disk = state_store.read()
        assert on_disk["status"] == "blocked"
        assert on_disk["termination_reason"] == "budget_exhausted"
        assert on_disk["tokens_used"] == 5000

        # Re-invoke with a higher budget — should resume, not stay blocked
        result = controller.run_loop(max_outer=3, max_inner=1, token_budget=10000)

        assert result.status != "blocked", (
            f"Expected run to resume after budget bump. "
            f"Got status={result.status!r}, reason={result.termination_reason!r}"
        )

    def test_budget_still_exhausted_returns_blocked(self, tmp_path: Path) -> None:
        """Calling run_loop with a budget still below stored usage keeps
        status=blocked with reason=budget_exhausted."""
        controller, state_store = _make_controller(tmp_path)

        # Simulate a prior run that hit the budget limit
        state_store.initialize("run-002", "semi")
        state_store.transition("running")
        state = state_store.read()
        state["tokens_used"] = 5000
        state["termination_reason"] = "budget_exhausted"
        state["outer_iter"] = 1
        state["inner_iter"] = 0
        state_store.write(state)
        state_store.transition(
            "blocked", updates={"blocked_phase": "implementation"}
        )

        # Re-invoke with a budget still less than usage — should stay blocked
        result = controller.run_loop(max_outer=3, max_inner=1, token_budget=4000)

        assert result.status == "blocked", (
            f"Expected status=blocked when budget still exhausted. "
            f"Got status={result.status!r}"
        )
        assert result.termination_reason == "budget_exhausted", (
            f"Expected termination_reason=budget_exhausted. "
            f"Got {result.termination_reason!r}"
        )

    def test_unlimited_budget_auto_resumes(self, tmp_path: Path) -> None:
        """Calling run_loop with token_budget=None (unlimited) resumes from a
        budget_exhausted blocked state."""
        controller, state_store = _make_controller(tmp_path)

        # Simulate a prior run that hit the budget limit
        state_store.initialize("run-003", "semi")
        state_store.transition("running")
        state = state_store.read()
        state["tokens_used"] = 5000
        state["termination_reason"] = "budget_exhausted"
        state["outer_iter"] = 1
        state["inner_iter"] = 0
        state_store.write(state)
        state_store.transition(
            "blocked", updates={"blocked_phase": "implementation"}
        )

        # Confirm setup
        on_disk = state_store.read()
        assert on_disk["status"] == "blocked"
        assert on_disk["termination_reason"] == "budget_exhausted"
        assert on_disk["tokens_used"] == 5000

        # Re-invoke with unlimited budget — should resume, not stay blocked
        result = controller.run_loop(max_outer=3, max_inner=1, token_budget=None)

        assert result.status != "blocked", (
            f"Expected run to resume with unlimited budget. "
            f"Got status={result.status!r}, reason={result.termination_reason!r}"
        )


# === No-progress guard providers ===


class _AlwaysFailNoChangesProvider(SandboxProvider):
    """Provider that always fails verification and writes no files to worktree.

    Simulates an LLM that is stuck — it consistently fails and never makes
    progress (no file changes between outer iterations).
    """

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return SandboxHandle(id="mock-noprogress", session_id="sess-np")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        # Build always succeeds (exit 0) but verify always fails.
        if "verify" in cmd:
            return ExecResult(
                exit_code=1,
                stdout=json.dumps({
                    "passed": False,
                    "failures": [{"category": "test", "id": "test-fail", "error": "always failing"}],
                }),
                stderr="",
                duration_ms=50,
                resource_stats=None,
            )
        return ExecResult(
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=50,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass  # Never write anything — simulates no file changes

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        pass


class _FailThenChangeProvider(SandboxProvider):
    """Provider that fails consistently but writes a file on the second outer iter.

    Iteration behaviour:
      - outer iter 0: fail verify, no file changes  -> no_progress_count = 1
      - outer iter 1: fail verify, write a file     -> no_progress_count reset to 0
      - outer iter 2: fail verify, no file changes  -> no_progress_count = 1 (< 2, no escalation)

    This exercises that the counter properly resets when file changes occur,
    preventing premature escalation.
    """

    def __init__(self, worktree_path: str) -> None:
        self._worktree_path = worktree_path
        self._outer_call_count = 0  # counts create() calls (one per outer iter)

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        outer = self._outer_call_count
        self._outer_call_count += 1
        return SandboxHandle(id=f"mock-change-{outer}", session_id=f"sess-{outer}")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        # Determine which outer iteration this is from the handle id.
        outer = int(handle.id.split("-")[-1])

        # On outer iter 1: write a file to the worktree to simulate file changes.
        if "verify" not in cmd and outer == 1:
            import os
            wt = self._worktree_path
            if os.path.isdir(wt):
                with open(os.path.join(wt, "progress_marker.txt"), "w") as f:
                    f.write("changed\n")

        # Always fail verify
        if "verify" in cmd:
            return ExecResult(
                exit_code=1,
                stdout=json.dumps({
                    "passed": False,
                    "failures": [{"category": "test", "id": "test-fail", "error": "still failing"}],
                }),
                stderr="",
                duration_ms=50,
                resource_stats=None,
            )
        return ExecResult(
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=50,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        pass


def _make_controller_with_provider(
    tmp_path: Path,
    provider: SandboxProvider,
    mode: str = "semi",
) -> tuple:
    """Create a RalphController with a custom provider and real StateStore."""
    config = HarnessConfig(
        target_repo="git@github.com:test/repo.git",
        target_default_branch="main",
        provider="docker",
    )
    state_store = StateStore(tmp_path, "spec-001", "default")
    mode_controller = ModeController(mode)
    escalation_handler = EscalationHandler(str(tmp_path / "harness"))
    gitops = _make_gitops()

    controller = RalphController(
        provider=provider,
        gitops=gitops,
        state_store=state_store,
        mode_controller=mode_controller,
        escalation_handler=escalation_handler,
        spec_id="spec-001",
        strategy_id="default",
        config=config,
    )
    return controller, state_store


class TestNoProgressGuard:
    """No-progress guard: escalate early when LLM is stuck (no file changes)."""

    def test_no_progress_triggers_escalation_after_two_fails(
        self, tmp_path: Path
    ) -> None:
        """Two consecutive failed outer iterations with no file changes trigger
        a no_progress escalation before max_outer is exhausted."""
        import unittest.mock as mock

        provider = _AlwaysFailNoChangesProvider()
        controller, state_store = _make_controller_with_provider(tmp_path, provider)
        state_store.initialize("run-np-001", "semi")

        # Patch _has_file_changes to always return False (no file changes in a
        # real git repo would require actual git setup, so we simulate via mock).
        with mock.patch.object(controller, "_has_file_changes", return_value=False):
            result = controller.run_loop(max_outer=5, max_inner=1)

        assert result.status == "blocked", (
            f"Expected status=blocked after no-progress escalation. "
            f"Got status={result.status!r}, reason={result.termination_reason!r}"
        )
        assert result.termination_reason == "no_progress", (
            f"Expected termination_reason=no_progress. "
            f"Got {result.termination_reason!r}"
        )
        # Should escalate after 2 iterations, not burn through all 5
        assert result.outer_iterations <= 3, (
            f"Expected escalation before outer iter 3, "
            f"got outer_iterations={result.outer_iterations}"
        )

    def test_progress_resets_no_progress_count(self, tmp_path: Path) -> None:
        """File changes on iter 2 reset the no_progress counter so iter 3
        alone is insufficient to trigger escalation (count=1, threshold=2)."""
        import unittest.mock as mock

        # Sequence: [False, True, False] — no change, change, no change
        file_change_sequence = [False, True, False]
        call_counter = {"n": 0}

        def _side_effect(wt_path: str) -> bool:
            idx = call_counter["n"]
            call_counter["n"] += 1
            if idx < len(file_change_sequence):
                return file_change_sequence[idx]
            return False  # extra calls: no change (but shouldn't be reached)

        provider = _AlwaysFailNoChangesProvider()
        controller, state_store = _make_controller_with_provider(tmp_path, provider)
        state_store.initialize("run-np-002", "semi")

        with mock.patch.object(controller, "_has_file_changes", side_effect=_side_effect):
            result = controller.run_loop(max_outer=3, max_inner=1)

        # Should NOT have escalated with no_progress — after iter 2 the counter
        # was reset to 0, so iter 3 only brought it to 1 (below threshold=2).
        assert result.termination_reason != "no_progress", (
            f"no_progress escalation should not fire when count was reset. "
            f"Got status={result.status!r}, reason={result.termination_reason!r}"
        )
