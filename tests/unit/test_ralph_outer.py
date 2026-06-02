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

    def test_fulfillment_gap_turns_passing_verify_into_failure(self, tmp_path: Path) -> None:
        """Passing tests are not enough when verify-spec found blocking gaps."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert "echelon reopen spec-001" in result.failures[0].error

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

    def test_does_not_converge_when_fulfillment_report_has_gaps(
        self, tmp_path: Path
    ) -> None:
        """Fulfillment gaps keep Ralph iterating even when sandbox verification passes."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | PARTIAL | src/a.py | high | missing edge case |\n",
            encoding="utf-8",
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert result.final_verify.failures[0].id == "fulfillment-gaps"
        gitops.promote_pr_ready.assert_not_called()

    def test_publish_failure_blocks_and_preserves_worktree(self, tmp_path: Path) -> None:
        """Verified work must not be reported converged when commit/push fails."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.push.side_effect = Exception("network error")

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "blocked"
        assert result.termination_reason == "publish_failed"
        assert result.branch == "harness/spec-001-default-iter-0"
        gitops.promote_pr_ready.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

        state = state_store.read()
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "publish_failed"
        assert state["branch"] == "harness/spec-001-default-iter-0"

    def test_llm_build_incomplete_returns_blocked_result(self, tmp_path: Path) -> None:
        """Missing build status should block gracefully instead of raising."""
        from harness.build_result import BuildResult

        llm_provider = MagicMock()
        llm_provider.exec_build.return_value = BuildResult(
            exit_code=0,
            status="unknown",
            impasse_file=None,
            stdout="done without status file",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_provider=llm_provider,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

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

        assert result.status == "blocked"
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

    def test_unknown_project_type_blocks_with_verify_command_needed(self, tmp_path: Path) -> None:
        """Build succeeds + unknown project type → status=blocked, reason=verify_command_needed."""
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
            max_inner=0,
            build_command="echelon codegen",
            build_prompt="build a hello world",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "verify_command_needed"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert any(f.id == "local-verify-skipped" for f in result.final_verify.failures)


@pytest.mark.unit
class TestVerifyCommandNeeded:
    """local-verify-skipped escalates to blocked, not silent failure."""

    def test_banner_printed_to_stderr(self, tmp_path: Path, capsys) -> None:
        """Unknown project type → escalation banner printed to stderr."""
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

        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        err = capsys.readouterr().err
        assert "TEST RUNNER MISSING" in err
        assert "verify_command" in err
        assert "echelon harness resume" in err

    def test_state_written_as_blocked(self, tmp_path: Path) -> None:
        """Unknown project type → StateStore reflects blocked + verify_command_needed."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        controller, _, gitops, state_store = _make_controller(tmp_path, llm_provider=llm)

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        state = state_store.read()
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "verify_command_needed"

    def test_does_not_iterate_build_loop(self, tmp_path: Path) -> None:
        """Hard-stop after first verify_command_needed — LLM not called again."""
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

        controller.run_loop(max_outer=5, max_inner=3,
                            build_command="echelon codegen", build_prompt="x")
        # Build must only have been called once (hard stop, no retries)
        assert llm.exec_build.call_count == 1

    def test_resume_with_verify_command_configured_reruns(self, tmp_path: Path) -> None:
        """After blocking, resume with verify_command set → loop re-enters."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult
        from harness.config import HarnessConfig

        llm = MagicMock(spec=AICodingCliProvider)
        controller, _, gitops, state_store = _make_controller(tmp_path, llm_provider=llm)

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        # First run: blocks
        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        assert state_store.read()["termination_reason"] == "verify_command_needed"

        # Now configure verify_command on the controller's config
        controller._config = HarnessConfig(
            **{**controller._config.__dict__, "verify_command": "pytest"}
        )
        llm.exec_build.reset_mock()
        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        with patch("subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = controller.run_loop(max_outer=1, max_inner=0,
                                         build_command="echelon codegen", build_prompt="x")

        # Loop re-entered: build was called again
        assert llm.exec_build.call_count == 1

    def test_resume_without_verify_command_still_blocked(self, tmp_path: Path) -> None:
        """Resume without configuring verify_command → still blocked, banner printed."""
        from harness.llm_provider import AICodingCliProvider
        from harness.build_result import BuildResult

        llm = MagicMock(spec=AICodingCliProvider)
        controller, _, gitops, state_store = _make_controller(tmp_path, llm_provider=llm)

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        llm.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        # First run blocks
        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")

        # Resume without adding verify_command → still blocked
        result = controller.run_loop(max_outer=1, max_inner=0,
                                     build_command="echelon codegen", build_prompt="x")
        assert result.status == "blocked"
        assert result.termination_reason == "verify_command_needed"


@pytest.mark.unit
class TestVerifyLocallySwift:
    """Swift project detection and verification."""

    def test_root_package_swift_detected(self, tmp_path: Path) -> None:
        """Package.swift at worktree root → swift build + swift test."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value="/usr/bin/swift"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["swift", "build"] in calls
        assert ["swift", "test"] in calls

    def test_nested_package_swift_detected(self, tmp_path: Path) -> None:
        """Package.swift in a subdirectory → detected and used as package dir."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        pkg_dir = worktree / "Packages" / "MyLib"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value="/usr/bin/swift"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert mock_run.call_args_list[0].kwargs.get("cwd") == str(pkg_dir) or \
               mock_run.call_args_list[0].args[1] == str(pkg_dir) or \
               all(c.kwargs.get("cwd") == str(pkg_dir) for c in mock_run.call_args_list)

    def test_swift_build_failure_reported(self, tmp_path: Path) -> None:
        """swift build non-zero exit → failure with id='swift-build', test not run."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        def _side_effect(cmd, **kwargs):
            if cmd == ["swift", "build"]:
                return MagicMock(returncode=1, stdout="error: compile error", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_side_effect), \
             patch("shutil.which", return_value="/usr/bin/swift"):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-build"
        assert result.failures[0].category == FailureCategory.BUILD

    def test_swift_test_failure_reported(self, tmp_path: Path) -> None:
        """swift test non-zero exit → failure with id='swift-test'."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        def _side_effect(cmd, **kwargs):
            if cmd == ["swift", "test"]:
                return MagicMock(returncode=1, stdout="", stderr="Test failed: assertion error")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_side_effect), \
             patch("shutil.which", return_value="/usr/bin/swift"):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-test"
        assert result.failures[0].category == FailureCategory.TEST

    def test_swift_not_on_path_returns_clear_error(self, tmp_path: Path) -> None:
        """swift toolchain absent → passed=False, id='swift-not-found'."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("shutil.which", return_value=None):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-not-found"
        assert "swift" in result.failures[0].error.lower()

    def test_python_takes_priority_over_swift(self, tmp_path: Path) -> None:
        """pyproject.toml + Package.swift → Python path taken, not Swift."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')
        (worktree / "pyproject.toml").write_text('[project]\nname = "x"\n')

        with patch.object(controller, "_exec_verify_python") as mock_py, \
             patch.object(controller, "_exec_verify_swift") as mock_sw:
            mock_py.return_value = MagicMock(passed=True, failures=[])
            result = controller._exec_verify_locally(str(worktree))

        mock_py.assert_called_once()
        mock_sw.assert_not_called()
