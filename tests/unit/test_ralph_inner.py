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

from harness.build_result import BuildResult
from harness.config import HarnessConfig
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.ralph import RalphController, _is_fulfillment_refresh_deferred
from harness.state import StateStore
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


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
        assert result.status == "verified"
        assert result.inner_iterations > 0

    def test_runnability_sandbox_prerequisite_blocks_without_product_feedback(
        self, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ctrl = _make_controller(tmp_path, [])
        ctrl._exec_feedback = MagicMock()
        unavailable = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "user-runnability-sandbox-prerequisite",
                    "Docker daemon is unavailable.",
                )
            ],
        )

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=unavailable,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            build_prompt="repair product",
        )

        assert result["blocked"] is True
        assert result["blocked_reason"] == "user_runnability_sandbox_prerequisite"
        assert result["inner_count"] == 0
        ctrl._exec_feedback.assert_not_called()

    def test_unchanged_concrete_fulfillment_gaps_without_product_delta_block(
        self, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        ctrl = _make_controller(tmp_path, [])
        gap = FailureEntry(
            FailureCategory.OTHER,
            "fulfillment-gaps",
            "FR-001 [UNVERIFIED]: runtime receipt absent",
            details={
                "gaps": [
                    {
                        "requirement_id": "FR-001",
                        "status": "UNVERIFIED",
                        "summary": "runtime receipt absent",
                        "recommended_action": "record a measured invocation",
                    }
                ]
            },
        )
        unchanged = VerifyResult(passed=False, failures=[gap])
        ctrl._exec_feedback = MagicMock(
            return_value={
                "exit_code": 0,
                "passed": True,
                "build_status": "done",
                "build_reason": "no applicable source change",
                "duration_s": 0.0,
                "tokens": 0,
                "task_ids": [],
            }
        )
        ctrl._try_checkpoint_progress_commit = MagicMock(return_value=None)
        ctrl._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
        ctrl._refresh_fulfillment_report = MagicMock(return_value=unchanged)
        ctrl._apply_fulfillment_gate = MagicMock(return_value=unchanged)

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=unchanged,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            build_prompt="repair fulfillment",
        )

        assert result["blocked"] is True
        assert result["blocked_reason"] == "fulfillment_no_progress"
        assert result["inner_count"] == 1
        assert ctrl._exec_feedback.call_count == 1
        escalation_file = Path(ctrl._state_store.read()["escalation_file"])
        assert "FR-001" in escalation_file.read_text(encoding="utf-8")

    def test_concrete_fulfillment_gap_with_product_delta_remains_repairable(
        self, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        product = worktree / "hello.py"
        product.write_text("print('before')\n", encoding="utf-8")
        ctrl = _make_controller(tmp_path, [])
        gap = FailureEntry(
            FailureCategory.OTHER,
            "fulfillment-gaps",
            "FR-001 [UNVERIFIED]: runtime receipt absent",
            details={
                "gaps": [
                    {
                        "requirement_id": "FR-001",
                        "status": "UNVERIFIED",
                        "summary": "runtime receipt absent",
                        "recommended_action": "record a measured invocation",
                    }
                ]
            },
        )
        unchanged_gap = VerifyResult(passed=False, failures=[gap])

        def repair(*_args: object, **_kwargs: object) -> dict[str, object]:
            product.write_text("print('after')\n", encoding="utf-8")
            return {
                "exit_code": 0,
                "passed": True,
                "build_status": "done",
                "build_reason": "changed product evidence",
                "duration_s": 0.0,
                "tokens": 0,
                "task_ids": [],
            }

        ctrl._exec_feedback = MagicMock(side_effect=repair)
        ctrl._try_checkpoint_progress_commit = MagicMock(return_value=None)
        ctrl._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
        ctrl._refresh_fulfillment_report = MagicMock(return_value=unchanged_gap)
        ctrl._apply_fulfillment_gate = MagicMock(return_value=unchanged_gap)

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=unchanged_gap,
            outer_iter=0,
            max_inner=1,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            build_prompt="repair fulfillment",
        )

        assert result["blocked"] is False
        assert result["inner_count"] == 1
        assert ctrl._state_store.read().get("escalation_file") is None

    def test_not_applicable_documentation_schema_repairs_in_one_cycle(
        self, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        report = spec_dir / "documentation-impact-report.md"
        report.write_text(
            "---\n"
            "docs_required: false\n"
            'reason: "README already covers the behavior."\n'
            "---\n",
            encoding="utf-8",
        )
        ctrl = _make_controller(tmp_path, [])
        state = ctrl._state_store.read()
        state["spec_dir"] = str(spec_dir)
        ctrl._state_store.write(state)
        initial = ctrl._apply_documentation_gate(
            VerifyResult(passed=True), str(worktree)
        )
        assert initial.failures[0].id == "documentation-not-applicable-without-reason"

        def repair(*_args: object, **_kwargs: object) -> dict[str, object]:
            report.write_text(
                "---\n"
                "docs_required: false\n"
                'not_applicable_reason: "README already covers the behavior."\n'
                "---\n",
                encoding="utf-8",
            )
            return {
                "exit_code": 0,
                "passed": True,
                "build_status": "done",
                "build_reason": "wrote exact report field",
                "duration_s": 0.0,
                "tokens": 0,
                "task_ids": [],
            }

        ctrl._exec_feedback = MagicMock(side_effect=repair)
        ctrl._try_checkpoint_progress_commit = MagicMock(return_value=None)
        ctrl._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
        ctrl._refresh_fulfillment_report = MagicMock(
            side_effect=lambda verify, *_args, **_kwargs: verify
        )

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=initial,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            build_prompt="repair documentation schema",
        )

        assert result["converged"] is True
        assert result["inner_count"] == 1
        assert ctrl._exec_feedback.call_count == 1


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
        state = ctrl._state_store.read()
        state["build_status"] = "provider_session_limit"
        state["build_reason"] = "stale provider limit"
        state["provider_limit_message"] = "stale provider limit text"
        state["provider_reset_hint"] = "2:30am"
        ctrl._state_store.write(state)

        result = ctrl.run_loop(max_outer=1, max_inner=5)
        assert result.status == "blocked"
        assert result.termination_reason == "blocker_escalation"
        escalation_file = next((tmp_path / "harness" / "escalations").glob("*.md"))
        escalation_text = escalation_file.read_text(encoding="utf-8")
        assert "3 consecutive time(s)" in escalation_text
        assert "threshold=3" in escalation_text
        assert "fingerprints=1" in escalation_text
        assert "1 time(s)" not in escalation_text
        state = ctrl._state_store.read()
        assert state["escalation_file"] == str(escalation_file)
        assert state.get("build_status") != "provider_session_limit"
        assert "provider_limit_message" not in state
        assert "provider_reset_hint" not in state
        assert "suggested_answers" in escalation_text

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
        # The ordinary outer cap is a typed blocked outcome.
        assert result.status == "blocked"
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
        assert result.status == "verified"
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
        # Banzai reaches the ordinary outer cap, not same-failure escalation.
        assert result.status == "blocked"
        assert result.termination_reason == "outer_cap"


@pytest.mark.unit
class TestInnerLoopDeferredFulfillment:
    """A post-fix deferred banzai fulfillment refresh must end the inner loop.

    Regression (milestone-boundary defer-loop): a real failure
    (`task-progress-mismatch`) pulls the build into the inner fix loop; the fix
    succeeds and the re-verify returns only the benign
    `fulfillment-refresh-deferred` signal. The loop must EXIT (so the outer loop
    checkpoints the slice and advances to the next task) instead of dispatching
    fixers against an unfixable deferral until max_inner. In banzai mode the
    same-failure escalation is suppressed, so without an explicit exit the loop
    runs every inner iteration each outer cycle and never advances.
    """

    def test_post_fix_deferred_exits_inner_loop(self, tmp_path: Path) -> None:
        ctrl = _make_controller(tmp_path, [], mode="banzai")

        entry = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "task-progress-mismatch",
                    "state task_results done but tasks.md has pending",
                )
            ],
        )
        deferred = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-refresh-deferred",
                    "deferred until task completion",
                )
            ],
        )

        # Fix succeeds; the post-fix re-verify resolves to the deferred signal.
        ctrl._exec_feedback = MagicMock(
            return_value={"exit_code": 0, "passed": True, "tokens": 0, "duration_s": 0.0}
        )
        ctrl._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
        ctrl._refresh_fulfillment_report = MagicMock(return_value=deferred)
        ctrl._apply_fulfillment_gate = MagicMock(side_effect=lambda vr, wt: vr)

        state = ctrl._state_store.read()
        handle = ctrl._provider.create(None)
        result = ctrl._run_inner_loop(
            handle=handle,
            verify_result=entry,
            outer_iter=0,
            max_inner=5,
            tokens_used=0,
            token_budget=None,
            state=state,
            build_command="build",
            strategy_context="",
            worktree_path="/tmp/wt",
            build_prompt="build the next task",
        )

        # Exits after exactly ONE fix, not max_inner=5 (the defer-loop).
        assert result["inner_count"] == 1
        assert result["converged"] is False
        assert result["blocked"] is False
        # Only one fixer was dispatched against the deferral.
        assert ctrl._exec_feedback.call_count == 1
        assert _is_fulfillment_refresh_deferred(result["final_verify"])


@pytest.mark.unit
class TestInnerLoopTaskProgress:
    """Inner-loop task completion must be reconciled before fulfillment gating."""

    def test_llm_feedback_preserves_completed_task_ids(self, tmp_path: Path) -> None:
        class Runner:
            def exec_feedback(
                self,
                worktree_path: str,
                prompt: str,
                *,
                containment_policy_file: str | None = None,
                prompt_metadata: dict[str, object] | None = None,
            ) -> BuildResult:
                return BuildResult(
                    exit_code=0,
                    status="done",
                    impasse_file=None,
                    reason="implemented T-002",
                    stdout="",
                    stderr="",
                    duration_ms=100,
                    task_ids=["T-002"],
                )

        ctrl = _make_controller(tmp_path, [])
        ctrl._llm_build_runner = Runner()

        result = ctrl._exec_feedback(
            handle=ctrl._provider.create(None),
            verify_result=VerifyResult(passed=False),
            build_command="echelon build",
            strategy_context="",
            worktree_path="/tmp/wt",
            prompt="fix it",
        )

        assert result["build_status"] == "done"
        assert result["build_reason"] == "implemented T-002"
        assert result["task_ids"] == ["T-002"]

    def test_completed_inner_task_exits_fulfillment_gap_loop(
        self, tmp_path: Path
    ) -> None:
        ctrl = _make_controller(tmp_path, [])
        initial_failure = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-gaps",
                    "full spec still has unresolved gaps",
                )
            ],
        )
        post_fix_failure = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-gaps",
                    "full spec still has unresolved gaps",
                )
            ],
        )

        def apply_progress(*, worktree_path: str, task_ids: object) -> list[str]:
            state = ctrl._state_store.read()
            state["build"] = {
                "total_tasks": 24,
                "completed_tasks": 2,
                "tasks_completed_pct": 8,
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-002": {"status": "DONE"},
                },
            }
            ctrl._state_store.write(state)
            return ["T-002"]

        ctrl._exec_feedback = MagicMock(
            return_value={
                "exit_code": 0,
                "passed": True,
                "build_status": "done",
                "build_reason": "implemented T-002",
                "duration_s": 0.0,
                "tokens": 0,
                "task_ids": ["T-002"],
            }
        )
        ctrl._apply_build_task_progress = MagicMock(side_effect=apply_progress)
        ctrl._try_checkpoint_progress_commit = MagicMock(
            return_value={"commit": "abc123"}
        )
        ctrl._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
        ctrl._refresh_fulfillment_report = MagicMock(
            side_effect=lambda verify, *_args, **_kwargs: verify
        )
        ctrl._apply_fulfillment_gate = MagicMock(return_value=post_fix_failure)

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=initial_failure,
            outer_iter=0,
            max_inner=5,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path="/tmp/wt",
            build_prompt="build the next task",
        )

        assert result["inner_count"] == 1
        assert result["converged"] is False
        assert result["blocked"] is False
        assert result["final_verify"] == post_fix_failure
        assert ctrl._exec_feedback.call_count == 1
        ctrl._apply_build_task_progress.assert_called_once()
        ctrl._try_checkpoint_progress_commit.assert_called_once()
        state = ctrl._state_store.read()
        assert state["build"]["task_results"]["T-002"]["status"] == "DONE"

    def test_explicit_feedback_blocker_stops_without_another_verify(self, tmp_path: Path) -> None:
        """A spec-governance blocker must not become another fulfillment-gap retry."""
        ctrl = _make_controller(tmp_path, [])
        entry = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-gaps",
                    "NFR-008 remains deviated",
                )
            ],
        )
        ctrl._exec_feedback = MagicMock(
            return_value={
                "exit_code": 0,
                "passed": False,
                "build_status": "blocked",
                "build_reason": "NFR-008 requires an owner spec decision",
                "duration_s": 0.0,
                "tokens": 0,
                "task_ids": [],
            }
        )
        ctrl._try_checkpoint_progress_commit = MagicMock(return_value=None)
        ctrl._exec_verify = MagicMock()

        result = ctrl._run_inner_loop(
            handle=ctrl._provider.create(None),
            verify_result=entry,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state=ctrl._state_store.read(),
            build_command="echelon build",
            strategy_context="",
            worktree_path="/tmp/wt",
            build_prompt="build the next task",
        )

        assert result["blocked"] is True
        assert result["blocked_reason"] == "build_blocked"
        assert result["inner_count"] == 1
        assert result["final_verify"].failures[0].id == "build-blocked"
        assert "owner spec decision" in result["final_verify"].failures[0].error
        ctrl._exec_verify.assert_not_called()
