"""Tests for RalphController inner loop + same-failure escalation.

Per T033 task specification:
- Inner loop converges after 1 fix
- Same failure 3x triggers escalation
- Same failure 2x does not trigger
- max_inner exhaustion returns to outer loop
- Banzai mode suppresses same_failure escalation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from harness.config import HarnessConfig
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.ralph import RalphController
from harness.state import StateStore


class MockProvider(SandboxProvider):
    """Mock provider with configurable verify results."""

    def __init__(self, verify_results: Optional[List[Dict[str, Any]]] = None) -> None:
        self._verify_results = verify_results or []
        self._verify_idx = 0

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return SandboxHandle(id="mock-1", session_id="sess-1")

    def exec(self, handle, cmd, cwd=None, env=None, timeout_ms=1_200_000):
        if "verify" in cmd:
            if self._verify_idx < len(self._verify_results):
                data = self._verify_results[self._verify_idx]
                self._verify_idx += 1
                return ExecResult(
                    exit_code=0 if data.get("passed") else 1,
                    stdout=json.dumps(data),
                    stderr="", duration_ms=1000, resource_stats=None,
                )
            return ExecResult(exit_code=1, stdout=json.dumps({"passed": False, "failures": []}),
                              stderr="", duration_ms=1000, resource_stats=None)
        return ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=1000, resource_stats=None)

    def write_file(self, handle, path, content): pass
    def read_file(self, handle, path): return b""
    def destroy(self, handle): pass


def _make_controller(tmp_path, verify_results, mode="semi"):
    config = HarnessConfig(target_repo="git@example.com:t/r.git", target_default_branch="main", provider="docker")
    gitops = MagicMock()
    gitops.create_worktree.return_value = "/tmp/wt"
    gitops.create_draft_pr.return_value = "https://github.com/t/r/pull/1"
    state_store = StateStore(tmp_path, "spec-001", "default")
    mode_ctrl = ModeController(mode)
    escalation = EscalationHandler(str(tmp_path / "harness"))
    state_store.initialize("run-1", mode)
    state_store.transition("running")
    ctrl = RalphController(
        provider=MockProvider(verify_results),
        gitops=gitops, state_store=state_store,
        mode_controller=mode_ctrl, escalation_handler=escalation,
        spec_id="spec-001", strategy_id="default", config=config,
    )
    return ctrl


@pytest.mark.unit
class TestInnerLoopConvergence:
    """Test inner loop converges after 1 fix."""

    def test_inner_converges_after_fix(self, tmp_path: Path) -> None:
        """First verify fails, feedback fixes, re-verify passes."""
        ctrl = _make_controller(tmp_path, [
            # Outer 0 initial verify: fail
            {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail-a"}]},
            # Inner 1 re-verify: pass
            {"passed": True, "failures": []},
        ])
        result = ctrl.run_loop(max_outer=5, max_inner=3)
        assert result.status == "converged"
        assert result.inner_iterations > 0


@pytest.mark.unit
class TestSameFailureEscalation:
    """Test same-failure detection triggers escalation."""

    def test_same_failure_3x_triggers_escalation(self, tmp_path: Path) -> None:
        """Same failure fingerprint 3x in inner loop -> blocked."""
        same_failure = {"category": "test", "id": "t1", "error": "assertion failed: expected 4 got 5"}
        ctrl = _make_controller(tmp_path, [
            # Outer 0 initial verify: fail
            {"passed": False, "failures": [same_failure]},
            # Inner 1 re-verify: same failure
            {"passed": False, "failures": [same_failure]},
            # Inner 2 re-verify: same failure
            {"passed": False, "failures": [same_failure]},
            # Inner 3 re-verify: same failure (threshold=3 reached at this point)
            {"passed": False, "failures": [same_failure]},
        ])
        result = ctrl.run_loop(max_outer=1, max_inner=5)
        assert result.status == "blocked"
        assert result.termination_reason == "blocker_escalation"

    def test_same_failure_2x_does_not_trigger(self, tmp_path: Path) -> None:
        """Same failure 2x should NOT trigger escalation (threshold=3)."""
        same_failure = {"category": "test", "id": "t1", "error": "assertion failed"}
        ctrl = _make_controller(tmp_path, [
            {"passed": False, "failures": [same_failure]},
            {"passed": False, "failures": [same_failure]},
            # Different failure breaks the streak
            {"passed": False, "failures": [{"category": "test", "id": "t2", "error": "different error"}]},
        ])
        result = ctrl.run_loop(max_outer=1, max_inner=2)
        # Should NOT be blocked (inner exhausted, outer cap)
        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"


@pytest.mark.unit
class TestInnerLoopExhaustion:
    """Test max_inner exhaustion returns to outer loop."""

    def test_inner_exhaustion_returns_to_outer(self, tmp_path: Path) -> None:
        """Inner loop exhausted -> continue outer loop."""
        ctrl = _make_controller(tmp_path, [
            # Outer 0: initial verify fail
            {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail-a"}]},
            # Inner 1 re-verify: different fail
            {"passed": False, "failures": [{"category": "test", "id": "t2", "error": "fail-b"}]},
            # Outer 1: initial verify pass
            {"passed": True, "failures": []},
        ])
        result = ctrl.run_loop(max_outer=5, max_inner=1)
        assert result.status == "converged"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestBanzaiModeSuppression:
    """Test banzai mode suppresses same_failure escalation."""

    def test_banzai_continues_past_same_failure(self, tmp_path: Path) -> None:
        """Banzai mode does not escalate on same_failure_repeat."""
        same_failure = {"category": "test", "id": "t1", "error": "assertion failed: same error"}
        ctrl = _make_controller(tmp_path, [
            {"passed": False, "failures": [same_failure]},
            {"passed": False, "failures": [same_failure]},
            {"passed": False, "failures": [same_failure]},
            {"passed": False, "failures": [same_failure]},
            # Eventually a different error
            {"passed": False, "failures": [{"category": "test", "id": "t2", "error": "different"}]},
        ], mode="banzai")
        result = ctrl.run_loop(max_outer=1, max_inner=4)
        # Banzai should NOT block on same_failure_repeat
        assert result.status != "blocked"
