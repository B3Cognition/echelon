"""Tests for RalphController outer loop.

Per T032 task specification:
- Outer loop converges on first iteration
- Outer loop hits cap
- Budget exhaustion terminates loop
- SIGTERM sets interrupted status
- cancel_requested terminates between iterations
"""

from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig, ResourceLimits, NetworkConfig
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.provider import (
    Capability,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)
from harness.ralph import RalphController
from harness.state import StateStore
from harness.verify_result import VerifyResult


# === Mock SandboxProvider ===


class MockProvider(SandboxProvider):
    """Mock sandbox provider for testing."""

    def __init__(
        self,
        verify_results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._exec_count = 0
        self._verify_results = verify_results or []
        self._verify_idx = 0
        self.created = False
        self.destroyed = False

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        self.created = True
        return SandboxHandle(id="mock-sandbox-1", session_id="sess-1")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        self._exec_count += 1

        # If cmd is verify, return from verify_results
        if "verify" in cmd:
            if self._verify_idx < len(self._verify_results):
                data = self._verify_results[self._verify_idx]
                self._verify_idx += 1
                return ExecResult(
                    exit_code=0 if data.get("passed", False) else 1,
                    stdout=json.dumps(data),
                    stderr="",
                    duration_ms=1000,
                    resource_stats=None,
                )
            return ExecResult(
                exit_code=1,
                stdout=json.dumps({"passed": False, "failures": []}),
                stderr="",
                duration_ms=1000,
                resource_stats=None,
            )

        # Default: build/feedback succeeds
        return ExecResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1000,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        self.destroyed = True


# === Fixtures ===


def _make_config() -> HarnessConfig:
    return HarnessConfig(
        target_repo="git@github.com:test/repo.git",
        target_default_branch="main",
        provider="docker",
    )


def _make_gitops() -> MagicMock:
    gitops = MagicMock()
    gitops.create_worktree.return_value = "/tmp/worktree"
    gitops.destroy_worktree.return_value = None
    gitops.commit.return_value = "abc123"
    gitops.push.return_value = None
    gitops.create_draft_pr.return_value = "https://github.com/test/repo/pull/1"
    gitops.promote_pr_ready.return_value = None
    return gitops


def _make_controller(
    tmp_path: Path,
    verify_results: Optional[List[Dict[str, Any]]] = None,
    mode: str = "semi",
    llm_provider: Optional[Any] = None,
) -> tuple:
    config = _make_config()
    provider = MockProvider(verify_results=verify_results)
    gitops = _make_gitops()
    state_store = StateStore(tmp_path, "spec-001", "default")
    mode_controller = ModeController(mode)
    escalation_handler = EscalationHandler(str(tmp_path / "harness"))

    state_store.initialize("run-1", mode)
    state_store.transition("running")

    controller = RalphController(
        provider=provider,
        gitops=gitops,
        state_store=state_store,
        mode_controller=mode_controller,
        escalation_handler=escalation_handler,
        spec_id="spec-001",
        strategy_id="default",
        config=config,
        llm_provider=llm_provider,
    )
    return controller, provider, gitops, state_store


@pytest.mark.unit
class TestOuterLoopConvergence:
    """Test outer loop converges on first iteration."""

    def test_converges_first_iteration(self, tmp_path: Path) -> None:
        """Verify passes on first try -> converged."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 1
        assert result.pr_url is not None
        assert provider.created is True
        assert provider.destroyed is True
        gitops.create_worktree.assert_called_once()
        gitops.promote_pr_ready.assert_called_once()

    def test_converges_second_outer_iteration(self, tmp_path: Path) -> None:
        """Verify fails first outer, passes on second outer -> converged."""
        # First outer: verify fails, inner loop fails (different errors to avoid same-failure)
        # Second outer: verify passes immediately
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                # Outer 0: initial verify fails
                {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail-a"}]},
                # Outer 0, inner 1: re-verify fails (different error)
                {"passed": False, "failures": [{"category": "test", "id": "t2", "error": "fail-b"}]},
                # Outer 1: initial verify passes
                {"passed": True, "failures": []},
            ],
        )

        result = controller.run_loop(max_outer=5, max_inner=1)

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestOuterLoopCap:
    """Test outer loop hits cap."""

    def test_outer_cap_reached(self, tmp_path: Path) -> None:
        """All verifications fail -> outer_cap."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [{"category": "test", "id": f"t{i}", "error": f"fail-{i}"}]}
                for i in range(100)  # More than enough for all iterations
            ],
        )

        result = controller.run_loop(max_outer=2, max_inner=1)

        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestBudgetExhaustion:
    """Test budget exhaustion terminates loop."""

    def test_budget_exhaustion(self, tmp_path: Path) -> None:
        """Token budget hit -> budget_exhausted."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [], "token_usage": 100000}
                for _ in range(20)
            ],
        )

        # Very tight budget
        result = controller.run_loop(max_outer=10, max_inner=3, token_budget=100)

        assert result.status == "failed"
        assert result.termination_reason == "budget_exhausted"


@pytest.mark.unit
class TestCancelRequested:
    """Test cancel_requested terminates between iterations."""

    def test_cancel_terminates(self, tmp_path: Path) -> None:
        """cancel_requested flag -> killed_by_coordinator."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail"}]}
                for _ in range(20)
            ],
        )

        # Set cancel_requested after first exec
        original_exec = provider.exec

        def cancelling_exec(handle, cmd, **kwargs):
            result = original_exec(handle, cmd, **kwargs)
            if provider._exec_count >= 2:
                state = state_store.read()
                state["cancel_requested"] = True
                state_store.write(state)
            return result

        provider.exec = cancelling_exec

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "cancelled"
        assert result.termination_reason == "killed_by_coordinator"


@pytest.mark.unit
class TestSignalHandling:
    """Test SIGTERM handling."""

    def test_interrupt_flag_set(self, tmp_path: Path) -> None:
        """SIGTERM sets _interrupted flag."""
        controller, _, _, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": False, "failures": []}],
        )
        controller._interrupted = False
        controller._handle_signal(signal.SIGTERM, None)
        assert controller._interrupted is True


@pytest.mark.unit
class TestLlmProviderDispatch:
    def test_exec_build_uses_llm_provider_when_set(self, tmp_path: Path) -> None:
        """When llm_provider is set, _exec_build delegates to it."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, provider, _, _ = _make_controller(tmp_path, llm_provider=llm)
        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        llm.exec_build.assert_called_once_with(str(tmp_path), "build this")
        assert result["passed"] is True

    def test_exec_build_falls_back_to_sandbox_when_no_llm_provider(self, tmp_path: Path) -> None:
        """When llm_provider is None, _exec_build uses provider.exec() even with args."""
        controller, provider, _, _ = _make_controller(tmp_path, llm_provider=None)

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        assert provider._exec_count == 1
        assert result["passed"] is True

    def test_exec_feedback_uses_llm_provider_when_set(self, tmp_path):
        """When llm_provider is set, _exec_feedback delegates to it."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult
        from harness.verify_result import VerifyResult

        llm = MagicMock(spec=AICodingCliProvider)
        llm.exec_feedback.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, _ = _make_controller(tmp_path, llm_provider=llm)
        verify = VerifyResult(passed=False, failures=[], duration_s=1.0, token_usage=0)

        result = controller._exec_feedback(
            handle=MagicMock(),
            verify_result=verify,
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="fix this",
        )

        llm.exec_feedback.assert_called_once_with(str(tmp_path), "fix this")
        assert result["passed"] is True
        assert result["impasse"] is False

    def test_exec_build_falls_back_when_prompt_empty(self, tmp_path: Path) -> None:
        """When prompt is empty, _exec_build falls back to sandbox even if provider set."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        controller, provider, _, _ = _make_controller(tmp_path, llm_provider=llm)

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="",  # empty → fallback
        )

        llm.exec_build.assert_not_called()
        assert provider._exec_count == 1


@pytest.mark.unit
class TestPromptHelpers:
    def test_make_iter_prompt_iter0_returns_base(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("spec 001", outer_iter=0, last_failures="")
        assert result == "spec 001"

    def test_make_iter_prompt_iter1_appends_failures(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("spec 001", outer_iter=1, last_failures="[lint] f1: error")
        assert "iteration 1" in result
        assert "[lint] f1: error" in result
        assert "spec 001" in result

    def test_make_iter_prompt_empty_base_returns_empty(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("", outer_iter=1, last_failures="error")
        assert result == ""

    def test_make_feedback_prompt_contains_failures(self, tmp_path: Path) -> None:
        from harness.verify_result import FailureEntry, FailureCategory, VerifyResult
        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[FailureEntry(category=FailureCategory.TEST, id="t1", error="AssertionError")],
            duration_s=1.0,
            token_usage=0,
        )
        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)
        assert "AssertionError" in result
        assert "spec 001" in result
        assert "re-running" in result


@pytest.mark.unit
class TestSignalDuringBuild:
    """SIGINT during build must set interrupted status without running verify."""

    def test_sigint_during_build_yields_interrupted_status(self, tmp_path: Path) -> None:
        """_interrupted set inside exec_build → status=interrupted, final_verify=None."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        controller, provider, gitops, _ = _make_controller(tmp_path, llm_provider=llm)

        def build_sets_interrupted(worktree_path: str, prompt: str) -> BuildResult:
            controller._interrupted = True
            return BuildResult(
                exit_code=1, status="unknown", impasse_file=None,
                stdout="", stderr="", duration_ms=500,
            )

        llm.exec_build.side_effect = build_sets_interrupted

        result = controller.run_loop(
            max_outer=2,
            build_command="echelon codegen",
            build_prompt="build a hello world",
        )

        assert result.status == "interrupted"
        assert result.termination_reason == "user_cancel"
        # Verify must not have run — an interrupted build has no verified output
        assert result.final_verify is None


@pytest.mark.unit
class TestVerifyLocallyUnknownProjectType:
    """Unknown project type must fail verification, not silently pass."""

    def test_unknown_project_type_returns_failed_verify(self, tmp_path: Path) -> None:
        """Empty worktree → VerifyResult(passed=False) with id='local-verify-skipped'."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].id == "local-verify-skipped"
        assert result.failures[0].category == FailureCategory.BUILD

    def test_unknown_project_type_does_not_converge(self, tmp_path: Path) -> None:
        """Build succeeds + unknown project type → status=failed, not converged."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        controller, _, gitops, _ = _make_controller(tmp_path, llm_provider=llm)

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)

        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,  # skip inner loop — not under test here
            build_command="echelon codegen",
            build_prompt="build a hello world",
        )

        assert result.status == "failed"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert any(f.id == "local-verify-skipped" for f in result.final_verify.failures)
