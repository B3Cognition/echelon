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
        state_store._data = state_store.read()  # sync cache so write() validates correctly
        state_store.write(state)

        # Confirm the stale flag is on disk before calling run_loop.
        on_disk = state_store.read()
        assert on_disk["cancel_requested"] is True
        assert on_disk["status"] == "initialized"

        # run_loop must clear cancel_requested and proceed rather than
        # immediately exiting with status=cancelled.
        result = controller.run_loop(max_outer=3, max_inner=1)

        assert result.status != "cancelled", (
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
        assert result.status != "cancelled"
