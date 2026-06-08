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
import subprocess
import sys
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
    gitops.base_dir = Path("/tmp/project")
    return gitops


def _make_controller(
    tmp_path: Path,
    verify_results: Optional[List[Dict[str, Any]]] = None,
    mode: str = "semi",
    llm_provider: Optional[Any] = None,
    llm_build_runner: Optional[Any] = None,
    fulfillment_runner: Optional[Any] = None,
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
        llm_build_runner=llm_build_runner,
        fulfillment_runner=fulfillment_runner,
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

    def test_fulfillment_gate_reads_orchestration_spec_dir_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Fulfillment gate uses orchestration spec artifacts, not target worktree discovery."""
        controller, _, gitops, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )
        gitops.base_dir = orchestration_root
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert str(spec_dir / "fulfillment-report.md") in result.failures[0].error

    def test_task_progress_gap_turns_passing_verify_into_failure(self, tmp_path: Path) -> None:
        """Ralph does not converge when state progress disagrees with tasks.md."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        state = state_store.read()
        state["build"] = {
            "total_tasks": 1,
            "completed_tasks": 1,
            "tasks_completed_pct": 100,
            "task_results": {"T-001": {"status": "DONE"}},
        }
        state_store.write(state)

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_task_progress_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "task-progress-mismatch"
        assert "state completed_tasks=1 but tasks.md has 0 checked task rows" in result.failures[0].error

    def test_task_progress_gate_reads_orchestration_tasks_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Task-progress gate uses orchestration tasks.md when target worktree has no specs."""
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        state = state_store.read()
        state["build"] = {
            "total_tasks": 1,
            "completed_tasks": 1,
            "tasks_completed_pct": 100,
            "task_results": {"T-001": {"status": "DONE"}},
        }
        state_store.write(state)

        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        gitops.base_dir = orchestration_root
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_task_progress_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "task-progress-mismatch"

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

    def test_convergence_writes_ready_to_land_status(self, tmp_path: Path) -> None:
        """Ralph owns the implemented-but-not-landed status transition."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        assert "**Status**: ready_to_land" in (spec_dir / "spec.md").read_text(
            encoding="utf-8"
        )
        history = json.loads((spec_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["authoritative_run"] == "run-1"
        assert history["runs"][-1]["phase"] == "B"
        assert history["runs"][-1]["status"] == "ready_to_land"
        assert history["runs"][-1]["verification_result"] == "PASS"
        artifacts = spec_dir / "ARTIFACTS.md"
        assert artifacts.exists()
        text = artifacts.read_text(encoding="utf-8")
        assert "Lifecycle stage: verified" in text
        assert "`run-history.json`" in text

    def test_convergence_writes_ready_status_to_orchestration_spec_dir(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo harness convergence updates the orchestration spec, not target worktree."""
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        controller, _, gitops, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        from harness.spec_frontmatter import read_frontmatter

        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        assert (spec_dir / "run-history.json").exists()
        assert (spec_dir / "ARTIFACTS.md").exists()

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

    def test_runs_verify_spec_before_fulfillment_gate_when_runner_available(
        self, tmp_path: Path
    ) -> None:
        """Ralph refreshes fulfillment evidence after sandbox verification passes."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )

        def write_fulfillment_gap(
            worktree_path: str,
            spec_id: str,
            *,
            orchestration_root: Path | str | None = None,
        ) -> int:
            (spec_dir / "fulfillment-report.md").write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | MISSING | none | high | absent |\n",
                encoding="utf-8",
            )
            return 0

        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.side_effect = write_fulfillment_gap
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c \"pass\""
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        fulfillment_runner.refresh.assert_called_once_with(
            str(worktree),
            "spec-001",
            orchestration_root=str(worktree),
        )
        assert result.status == "failed"
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-gaps"

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

    def test_llm_build_incomplete_returns_blocked_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Missing build status should block gracefully instead of raising."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
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
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "missing build status marker" in captured.err
        assert ".harness-build-status.json" in captured.err
        assert "echelon harness resume spec-001" in captured.err
        assert "missing Phase A artifacts" not in captured.err
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_impasse_reports_marker_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Explicit impasse marker must not be reported as a missing marker."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="impasse",
            impasse_file=None,
            reason="scope exceeds build budget",
            stdout="",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "build reported status 'impasse'" in captured.err
        assert "scope exceeds build budget" in captured.err
        assert "missing build status marker" not in captured.err
        state = state_store.read()
        assert state["build_status"] == "impasse"
        assert state["build_reason"] == "scope exceeds build budget"
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_real_repo_gets_dirty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects when the LLM writes outside the isolated worktree."""
        from harness.build_result import BuildResult

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        (project / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=project, check=True)

        worktree = project / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)

        llm_build_runner = MagicMock()

        def dirty_real_repo(_worktree_path: str, _prompt: str):
            (project / "escaped.txt").write_text("wrong root\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="done",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = dirty_real_repo
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "CONTAINMENT VIOLATION" in captured.err
        assert "escaped.txt" in captured.err
        assert state_store.read()["termination_reason"] == "containment_violation"
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_build_incomplete_salvages_dirty_worktree_to_commit(
        self, tmp_path: Path
    ) -> None:
        """Useful build output is committed before blocking on missing status marker."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)
        (worktree / "generated.txt").write_text("salvaged\n", encoding="utf-8")

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
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
            llm_build_runner=llm_build_runner,
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        state = state_store.read()
        salvage_commit = state["salvage_commit"]
        assert len(salvage_commit) == 40
        assert state["salvage_branch"] == "main"
        assert state["salvage_verified"] == "not_run"
        assert state["branch"] == "main"
        assert (
            subprocess.run(
                ["git", "show", f"{salvage_commit}:generated.txt"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            == "salvaged\n"
        )
        assert subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""

    def test_checkpoint_commit_records_task_progress_delta(self, tmp_path: Path) -> None:
        """Ralph commits a dirty worktree when build state shows task progress."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "generated.txt").write_text("new code\n", encoding="utf-8")
        gitops.commit.return_value = "abc123def456"

        before = {
            "build": {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
        }
        after = {
            "build": {
                "completed_tasks": 2,
                "current_phase_group": "phase-2-foundation",
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-002": {"status": "DONE"},
                },
            }
        }

        with patch.object(controller, "_has_file_changes", return_value=True):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path=str(worktree),
                before_state=before,
                after_state=after,
                outer_iter=0,
                inner_iter=0,
                phase="build",
            )

        assert checkpoint is not None
        gitops.commit.assert_called_once()
        message = gitops.commit.call_args.args[1]
        assert "harness-checkpoint:" in message
        assert "T-002" in message
        assert "phase-2-foundation" in message
        state = state_store.read()
        assert state["checkpoint_commits"][0]["commit"] == "abc123def456"
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-002"]

    def test_checkpoint_commit_uses_phase_when_task_ids_unknown(self, tmp_path: Path) -> None:
        """Stage 1 records truthful phase/wave metadata instead of fake task IDs."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.commit.return_value = "feedface"
        before = {"build": {"completed_tasks": 0}}
        after = {
            "build": {
                "completed_tasks": 1,
                "current_phase_group": "phase-3-play-loop",
                "task_results": {},
            }
        }

        with patch.object(controller, "_has_file_changes", return_value=True):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state=before,
                after_state=after,
                outer_iter=1,
                inner_iter=2,
                phase="fix",
            )

        assert checkpoint is not None
        message = gitops.commit.call_args.args[1]
        assert "phase-3-play-loop" in message
        assert "tasks-unknown" in message
        state = state_store.read()
        assert state["checkpoint_commits"][0]["task_ids"] == []
        assert state["checkpoint_commits"][0]["phase_group"] == "phase-3-play-loop"

    def test_checkpoint_commit_skips_when_no_file_changes(self, tmp_path: Path) -> None:
        """Progress metadata alone does not create empty checkpoint commits."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )

        with patch.object(controller, "_has_file_changes", return_value=False):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state={"build": {"completed_tasks": 0}},
                after_state={"build": {"completed_tasks": 1}},
                outer_iter=0,
                inner_iter=0,
                phase="build",
            )

        assert checkpoint is None
        gitops.commit.assert_not_called()
        assert "checkpoint_commits" not in state_store.read()

    def test_run_loop_checkpoints_after_successful_build_progress(
        self, tmp_path: Path
    ) -> None:
        """Ralph checkpoints progress after a build invocation before verification."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def complete_one_task(_worktree_path: str, _prompt: str):
            state = state_store.read()
            state["build"] = {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
            state_store.write(state)
            (worktree / "generated.txt").write_text("task output\n", encoding="utf-8")
            (worktree / ".harness-build-status.json").write_text(
                '{"status":"done"}\n',
                encoding="utf-8",
            )
            return BuildResult(
                exit_code=0,
                status="done",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = complete_one_task
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree

        with patch.object(
            controller,
            "_exec_verify",
            return_value=VerifyResult(passed=True, failures=[]),
        ):
            result = controller.run_loop(
                max_outer=1,
                max_inner=0,
                build_prompt="implement one task",
            )

        assert result.status == "converged"
        state = state_store.read()
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-001"]

    def test_build_incomplete_keeps_checkpoint_before_blocking(
        self, tmp_path: Path
    ) -> None:
        """If a build advances progress then misses the marker, recovery has a checkpoint."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def advance_progress_without_marker(_worktree_path: str, _prompt: str):
            state = state_store.read()
            state["build"] = {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
            state_store.write(state)
            (worktree / "generated.txt").write_text("partial task output\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="unknown",
                impasse_file=None,
                stdout="missing marker",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = advance_progress_without_marker
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement one task",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        state = state_store.read()
        checkpoint = state["checkpoint_commits"][0]
        assert checkpoint["task_ids"] == ["T-001"]
        assert checkpoint["commit"]
        assert "salvage_commit" not in state
        assert subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""

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
    def test_exec_build_uses_llm_build_runner_when_set(self, tmp_path: Path) -> None:
        """When llm_build_runner is set, _exec_build delegates to it."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, provider, _, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        build_runner.exec_build.assert_called_once()
        assert build_runner.exec_build.call_args.args[0] == str(tmp_path)
        assert "build this" in build_runner.exec_build.call_args.args[1]
        assert result["passed"] is True

    def test_exec_build_injects_deterministic_harness_context(self, tmp_path: Path) -> None:
        """LLM build prompts receive the exact state file instead of discovering it."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        worktree = tmp_path / "worktree"

        controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            prompt="build this",
        )

        sent_prompt = build_runner.exec_build.call_args.args[1]
        assert f"state_file: {state_store.state_file}" in sent_prompt
        assert f"state_dir: {state_store.state_dir}" in sent_prompt
        assert "Do not search for state.json" in sent_prompt
        assert "build this" in sent_prompt

    def test_exec_build_injects_authoritative_spec_paths(self, tmp_path: Path) -> None:
        """LLM build prompts receive spec paths from the harness, not discovery."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        project_root = tmp_path / "polyrepo"
        spec_dir = project_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("- [ ] T-001 req=FR-001\n", encoding="utf-8")
        gitops.base_dir = project_root
        worktree = tmp_path / "polyrepo" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"

        controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            prompt="build this",
        )

        sent_prompt = build_runner.exec_build.call_args.args[1]
        assert f"spec_dir: {spec_dir}" in sent_prompt
        assert f"tasks_file: {spec_dir / 'tasks.md'}" in sent_prompt
        assert f"spec_file: {spec_dir / 'spec.md'}" in sent_prompt
        assert "Do not discover spec artifacts with `find`, `ls`, globbing" in sent_prompt

    def test_exec_build_falls_back_to_sandbox_when_no_llm_build_runner(self, tmp_path: Path) -> None:
        """When llm_build_runner is None, _exec_build uses provider.exec() even with args."""
        controller, provider, _, _ = _make_controller(tmp_path, llm_build_runner=None)

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        assert provider._exec_count == 1
        assert result["passed"] is True

    def test_exec_feedback_uses_llm_build_runner_when_set(self, tmp_path):
        """When llm_build_runner is set, _exec_feedback delegates to it."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult
        from harness.verify_result import VerifyResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_feedback.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        verify = VerifyResult(passed=False, failures=[], duration_s=1.0, token_usage=0)

        result = controller._exec_feedback(
            handle=MagicMock(),
            verify_result=verify,
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="fix this",
        )

        build_runner.exec_feedback.assert_called_once()
        assert build_runner.exec_feedback.call_args.args[0] == str(tmp_path)
        assert "fix this" in build_runner.exec_feedback.call_args.args[1]
        assert result["passed"] is True
        assert result["impasse"] is False

    def test_exec_build_falls_back_when_prompt_empty(self, tmp_path: Path) -> None:
        """When prompt is empty, _exec_build falls back to sandbox even if build runner set."""
        from harness.llm_build_runner import LlmBuildRunner

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, provider, _, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="",  # empty → fallback
        )

        build_runner.exec_build.assert_not_called()
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
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, provider, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        def build_sets_interrupted(worktree_path: str, prompt: str) -> BuildResult:
            controller._interrupted = True
            return BuildResult(
                exit_code=1, status="unknown", impasse_file=None,
                stdout="", stderr="", duration_ms=500,
            )

        build_runner.exec_build.side_effect = build_sets_interrupted

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
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)

        build_runner.exec_build.return_value = BuildResult(
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
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
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
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
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
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        controller.run_loop(max_outer=5, max_inner=3,
                            build_command="echelon codegen", build_prompt="x")
        # Build must only have been called once (hard stop, no retries)
        assert build_runner.exec_build.call_count == 1

    def test_resume_with_verify_command_configured_reruns(self, tmp_path: Path) -> None:
        """After blocking, resume with verify_command set → loop re-enters."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult
        from harness.config import HarnessConfig

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
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
        build_runner.exec_build.reset_mock()
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        with patch("subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = controller.run_loop(max_outer=1, max_inner=0,
                                         build_command="echelon codegen", build_prompt="x")

        # Loop re-entered: build was called again
        assert build_runner.exec_build.call_count == 1

    def test_resume_without_verify_command_still_blocked(self, tmp_path: Path) -> None:
        """Resume without configuring verify_command → still blocked, banner printed."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
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
