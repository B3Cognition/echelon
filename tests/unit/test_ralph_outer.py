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
from harness.convergence import ConvergenceLease, ProgressSnapshot
from harness.documentation_gate import DocumentationGateResult
from harness.errors import SandboxCreationError
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.fulfillment_runner import FulfillmentRefreshResult
from harness.delivery_results import ImplementationResult
from harness.mode import ModeController
from harness.provider import (
    Capability,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)
from harness import ralph
from harness.build_result import BuildResult
from harness.coverage_observer_runner import (
    CoverageObserverRun,
    CoverageVerificationBundle,
)
from harness.coverage_observation import (
    CoverageObservationRef,
    CoverageObservationResult,
    CoverageObservationValidation,
)
from harness.llm_tool_policy import LlmToolPolicy
from harness.product_inventory import product_evidence_fingerprint
from harness.ralph import RalphController, _completed_task_coverage_case_ids
from harness.runnability_contract import LocalBoundaryProbe
from harness.runnability_evidence import RunnabilityEvidenceRef
from harness.runnability_runner import RunnabilityRunResult
from harness.stacks.resolver import (
    ResolvedCoverageObserver,
    ResolvedRunnability,
    ResolvedStacks,
)
from harness.stacks.schema import StackCoverageObserver
from harness.state import StateStore
from harness.verification_evidence import VerificationStage, write_verification_receipt


def _valid_plan_conformance_json() -> str:
    return json.dumps(
        {
            "status": "pass",
            "findings": [],
            "sources": [
                "spec.md",
                "requirements-overview.md",
                "plan.md",
                "tasks.md",
            ],
        },
        indent=2,
    ) + "\n"
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


def test_raw_outer_ordinal_does_not_exhaust_meaningful_attempt_budget(
    tmp_path: Path,
) -> None:
    """Provider interruptions may advance provenance without spending repair attempts."""
    controller, provider, gitops, state_store = _make_controller(
        tmp_path,
        verify_results=[{"passed": True, "failures": []}],
    )
    state = state_store.read()
    state["outer_iter"] = 5
    state["convergence_lease"] = {
        **ConvergenceLease().to_state(),
        "meaningful_attempts": 2,
        "infrastructure_attempts": 3,
    }
    state_store.write(state)

    result = controller.run_loop(max_outer=3, max_inner=1)

    assert result.status == "verified"
    gitops.create_worktree.assert_called_once()
    assert gitops.create_worktree.call_args.args[1] == 5
    assert provider.create_count == 0


def test_equivalent_authoritative_observations_stop_on_convergence_patience(
    tmp_path: Path,
) -> None:
    controller, _, _, state_store = _make_controller(tmp_path)
    verify = VerifyResult(
        passed=False,
        failures=[FailureEntry(FailureCategory.TEST, "unit-a", "noise")],
    )

    first = controller._record_convergence_observation(
        verify, "/tmp/worktree", hard_ceiling=12
    )
    second = controller._record_convergence_observation(
        verify, "/tmp/worktree", hard_ceiling=12
    )
    third = controller._record_convergence_observation(
        verify, "/tmp/worktree", hard_ceiling=12
    )

    assert first.should_stop is False
    assert second.should_stop is False
    assert third.should_stop is True
    assert third.stop_reason == "stall_patience"
    state = state_store.read()["convergence_lease"]
    assert state["meaningful_attempts"] == 3
    assert state["stalled_attempts"] == 2


def test_infrastructure_finalization_is_excluded_from_meaningful_attempts(
    tmp_path: Path,
) -> None:
    controller, _, _, state_store = _make_controller(tmp_path)

    controller._finalize(
        status="blocked",
        reason="sandbox_verification_unavailable",
        outer_iterations=4,
        inner_iterations=0,
        pr_url=None,
        tokens_used=0,
        final_verify=None,
    )

    lease = state_store.read()["convergence_lease"]
    assert lease["meaningful_attempts"] == 0
    assert lease["infrastructure_attempts"] == 1
    assert lease["last_infrastructure_reason"] == "sandbox_verification_unavailable"


def test_regressed_high_water_context_is_bounded_and_provider_actionable(
    tmp_path: Path,
) -> None:
    controller, _, _, state_store = _make_controller(tmp_path)
    best = ProgressSnapshot.from_verify_result(
        VerifyResult(
            passed=False,
            failures=[FailureEntry(FailureCategory.TEST, "unit-a", "secret noise")],
        ),
        completed_tasks=3,
        total_tasks=4,
        product_fingerprint="fingerprint-best",
        checkpoint_commit="commit-best",
    )
    current = ProgressSnapshot.from_verify_result(
        VerifyResult(
            passed=False,
            failures=[
                FailureEntry(FailureCategory.TEST, "unit-a", "different secret noise"),
                FailureEntry(FailureCategory.TEST, "unit-b", "more secret noise"),
            ],
        ),
        completed_tasks=3,
        total_tasks=4,
        product_fingerprint="fingerprint-current",
        checkpoint_commit="commit-current",
    )
    lease = ConvergenceLease.from_state(None).observe(best, hard_ceiling=12).lease
    lease = lease.observe(current, hard_ceiling=12).lease
    state = state_store.read()
    state["convergence_lease"] = lease.to_state()
    state_store.write(state)

    prompt = controller._make_iter_prompt("Build it", 7, "current failure")

    assert "High-water convergence context" in prompt
    assert "best checkpoint: commit-best" in prompt
    assert "completed tasks: 3/4" in prompt
    assert "Recover or improve on that authoritative high-water evidence" in prompt
    assert "secret noise" not in prompt


def test_convergence_observation_emits_content_free_telemetry(tmp_path: Path) -> None:
    controller, _, _, state_store = _make_controller(tmp_path)
    verify = VerifyResult(
        passed=False,
        failures=[FailureEntry(FailureCategory.TEST, "unit-a", "raw secret noise")],
    )

    controller._record_convergence_observation(
        verify, "/tmp/worktree", hard_ceiling=12
    )

    events_path = state_store.state_dir.parent / "telemetry" / "events.jsonl"
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "delivery.convergence_observation"
    assert event["outcome"] == "baseline"
    assert event["meaningful_attempts"] == 1
    assert event["hard_ceiling"] == 12
    assert event["blocking_failure_count"] == 1
    assert "raw secret noise" not in events_path.read_text(encoding="utf-8")


def test_tool_access_classifier_uses_categorized_filesystem_commands() -> None:
    """Containment command matching is maintained by category, not regex archaeology."""
    commands_by_category = ralph._FILESYSTEM_ACCESS_COMMANDS_BY_CATEGORY

    assert "shell_reader" in commands_by_category
    assert "test_build_runner" in commands_by_category
    assert "cat" in commands_by_category["shell_reader"]
    assert "pytest" in commands_by_category["test_build_runner"]

    for command in ("cat", "tree", "pytest", "npm", "swift", "python"):
        assert ralph._looks_like_tool_access_line(f"  {command} src/harness/ralph.py")


def test_provider_budget_arithmetic_counts_only_reported_positive_usage() -> None:
    assert ralph._known_token_count(4321) == 4321
    assert ralph._known_token_count(None) == 0
    assert ralph._known_token_count(0) == 0


def test_plain_blocker_is_not_verification_deferral() -> None:
    assert (
        ralph._is_verification_environment_deferral(
            {
                "completion_marker_explicit": True,
                "build_status": "blocked",
                "blocker_kind": None,
            }
        )
        is False
    )


def test_only_explicit_verification_environment_blocker_is_deferral() -> None:
    assert (
        ralph._is_verification_environment_deferral(
            {
                "completion_marker_explicit": True,
                "build_status": "blocked",
                "blocker_kind": "verification_environment",
            }
        )
        is True
    )
    assert (
        ralph._is_verification_environment_deferral(
            {
                "completion_marker_explicit": False,
                "build_status": "blocked",
                "blocker_kind": "verification_environment",
            }
        )
        is False
    )


def test_verify_state_serialization_preserves_evidence_reference() -> None:
    evidence = {
        "path": "/tmp/receipt.json",
        "receipt_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "candidate_commit": "c" * 40,
        "candidate_fingerprint": "d" * 64,
        "passed": True,
    }

    payload = ralph._verify_to_dict(
        VerifyResult(
            passed=True, failures=[], verification_evidence=evidence
        )
    )

    assert payload["verification_evidence"] == evidence


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
        self.create_count = 0
        self.destroyed = False
        self.spec: Optional[SandboxSpec] = None

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        self.created = True
        self.create_count += 1
        self.spec = spec
        return SandboxHandle(
            id=f"mock-sandbox-{self.create_count}",
            session_id=f"sess-{self.create_count}",
        )

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


class SyntheticBuildProvider(SandboxProvider):
    """SandboxProvider that mutates the real git worktree without invoking an LLM."""

    def __init__(self) -> None:
        self.worktree: Optional[Path] = None
        self.created = False
        self.destroyed = False

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        self.created = True
        self.worktree = Path(spec.worktree_mount)
        return SandboxHandle(id="synthetic-sandbox-1", session_id="synthetic")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        del handle, cwd, env, timeout_ms
        if "verify" in cmd:
            return ExecResult(
                exit_code=0,
                stdout=json.dumps({"passed": True, "failures": []}),
                stderr="",
                duration_ms=100,
                resource_stats=None,
            )
        assert self.worktree is not None
        (self.worktree / "built.txt").write_text("synthetic delivery\n", encoding="utf-8")
        return ExecResult(
            exit_code=0,
            stdout="synthetic build complete",
            stderr="",
            duration_ms=100,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        self.destroyed = True


class SyntheticDirtyBuildProvider(SyntheticBuildProvider):
    """Synthetic provider that also leaves disposable cache output."""

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        result = super().exec(handle, cmd, cwd=cwd, env=env, timeout_ms=timeout_ms)
        if "verify" not in cmd:
            assert self.worktree is not None
            cache = self.worktree / ".pytest_cache" / "v" / "cache"
            cache.mkdir(parents=True)
            (cache / "nodeids").write_text("tests/test_demo.py::test_demo\n", encoding="utf-8")
        return result


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
    gitops.get_default_branch.return_value = "main"
    gitops.local_merge.return_value = None
    gitops.create_draft_pr.return_value = "https://github.com/test/repo/pull/1"
    gitops.promote_pr_ready.return_value = None
    gitops.base_dir = Path("/tmp/project")
    return gitops


def _make_controller(
    tmp_path: Path,
    verify_results: Optional[List[Dict[str, Any]]] = None,
    mode: str = "semi",
    llm_provider: Optional[Any] = None,
    fulfillment_runner: Optional[Any] = None,
    config: Optional[HarnessConfig] = None,
    fresh_delivery: bool = False,
    defer_target_merge: bool = False,
    resume_worktree_path: str | None = None,
) -> tuple:
    config = config or _make_config()
    provider = MockProvider(verify_results=verify_results)
    gitops = _make_gitops()
    state_store = StateStore(tmp_path, "spec-001")
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
                config=config,
        llm_provider=llm_provider,
        fulfillment_runner=fulfillment_runner,
        build_id="build-1",
        fresh_delivery=fresh_delivery,
        defer_target_merge=defer_target_merge,
        resume_worktree_path=resume_worktree_path,
    )
    controller._exec_controlled_slice = MagicMock(
        return_value={
            "exit_code": 0,
            "passed": True,
            "build_status": "done",
            "completion_marker_explicit": True,
            "build_reason": "controlled slice completed",
            "duration_s": 0,
            "tokens": 0,
            "task_ids": [],
            "stdout": "",
            "stderr": "",
        }
    )
    verification_results = [
        VerifyResult.from_dict(result) for result in (verify_results or [])
    ]
    if verification_results:
        controller._candidate_evidence_runner.run_standard = MagicMock(
            side_effect=verification_results
        )
    return controller, provider, gitops, state_store


def test_sandbox_setup_error_is_a_typed_verification_failure(tmp_path: Path) -> None:
    controller, provider, *_ = _make_controller(tmp_path)
    provider.create = MagicMock(side_effect=SandboxCreationError("daemon unavailable"))

    result = controller._exec_verify(None, worktree_path=str(tmp_path))

    assert result.passed is False
    assert result.failures[0].id == "sandbox-verification-unavailable"


def test_standard_verification_delegates_to_shared_candidate_evidence_runner(
    tmp_path: Path,
) -> None:
    controller, provider, *_ = _make_controller(tmp_path)
    shared = MagicMock()
    expected = VerifyResult(passed=True, verification_evidence={"passed": True})
    shared.run_standard.return_value = expected
    controller._candidate_evidence_runner = shared

    result = controller._exec_verify(None, worktree_path=str(tmp_path))

    assert result is expected
    shared.run_standard.assert_called_once_with(
        handle=None,
        worktree=tmp_path,
        allow_legacy_structured=False,
    )
    assert provider.created is False










def _required_browser_runnability() -> ResolvedRunnability:
    return ResolvedRunnability(
        classification="user_facing",
        policy="required",
        runner="linux_container",
        capabilities=("install", "start", "primary_journey", "stop"),
        required_observations=("browser_dom",),
        sources=("browser-game",),
    )


def _required_coverage_stacks() -> ResolvedStacks:
    return ResolvedStacks(
        selected_ids=["browser-game"],
        resolved_ids=["browser-game"],
        implied_by={},
        capabilities={},
        tools={},
        required_commands=[],
        required_registries=[],
        context_files=[],
        coverage_observers=[
            ResolvedCoverageObserver(
                owner_stack_id="browser-game",
                observer=StackCoverageObserver(
                    id="vitest-unit",
                    test_types=("unit",),
                    command="pnpm exec vitest run --reporter=json",
                    report_path=".echelon/coverage-reports/unit.json",
                    adapter="vitest-json",
                    mode="isolated",
                    required=True,
                ),
            )
        ],
    )


def _write_enabled_runnability_contract(worktree: Path) -> None:
    contract = worktree / ".echelon" / "runnability.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        "schema_version: 1\n"
        "enabled: true\n"
        "install_commands: []\n"
        "bootstrap_commands: []\n"
        "start_commands: [make start]\n"
        "readiness:\n"
        "  url: http://127.0.0.1:${ECHELON_PORT}/health\n"
        "  timeout_ms: 30000\n"
        "primary_journey:\n"
        "  kind: browser\n"
        "  url: ${ECHELON_BASE_URL}\n"
        "  requirements: [FR-001]\n"
        "  real_services_required: [web]\n"
        "  steps:\n"
        "    - action: goto\n"
        "      path: /\n"
        "  observations:\n"
        "    - id: canvas-visible\n"
        "      kind: browser_dom\n"
        "      selector: canvas\n"
        "      expectation: present\n"
        "stop_commands: [make stop]\n",
        encoding="utf-8",
    )


@pytest.mark.unit
def test_required_user_facing_stack_cannot_pass_gate_without_candidate_contract(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._config.resolved_runnability = _required_browser_runnability()
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = controller._apply_user_runnability_gate(
        VerifyResult(passed=True),
        str(worktree),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence" / "user-runnability",
    )

    assert result.passed is False
    assert result.failures[0].id == "user-runnability-contract-missing"
    assert result.failures[0].details["contract"] == ".echelon/runnability.yml"


def test_runnability_gate_delegates_to_shared_candidate_evidence_runner(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    shared = MagicMock()
    expected = VerifyResult(passed=True, verification_evidence={"passed": True})
    gate = MagicMock(verify_result=expected, state_summary={"status": "runnable"})
    shared.apply_runnability.return_value = gate
    controller._candidate_evidence_runner = shared
    controller._find_existing_spec_dir = MagicMock(return_value=tmp_path / "spec")
    controller._record_user_runnability_state = MagicMock()

    result = controller._apply_user_runnability_gate(
        VerifyResult(passed=True),
        str(tmp_path),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
    )

    assert result is expected
    shared.apply_runnability.assert_called_once_with(
        verify_result=shared.apply_runnability.call_args.kwargs["verify_result"],
        worktree=tmp_path,
        spec_dir=tmp_path / "spec",
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
    )
    controller._record_user_runnability_state.assert_called_once_with(
        {"status": "runnable"}
    )


@pytest.mark.unit
def test_post_verify_gates_run_runnability_before_fulfillment_judgment(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    calls: list[str] = []

    def passthrough(name: str):
        def apply(result: VerifyResult, *_args, **_kwargs) -> VerifyResult:
            calls.append(name)
            return result

        return apply

    controller._apply_task_progress_gate = MagicMock(
        side_effect=passthrough("tasks")
    )
    controller._apply_user_runnability_gate = MagicMock(
        side_effect=passthrough("runnability")
    )
    controller._apply_coverage_observation_gate = MagicMock(
        side_effect=passthrough("coverage")
    )
    controller._refresh_fulfillment_report = MagicMock(
        side_effect=passthrough("refresh")
    )
    controller._apply_fulfillment_gate = MagicMock(
        side_effect=passthrough("fulfillment")
    )
    controller._apply_documentation_gate = MagicMock(
        side_effect=passthrough("documentation")
    )

    result = controller._apply_post_verify_gates(
        VerifyResult(passed=True), str(tmp_path)
    )

    assert result.passed is True
    assert calls == [
        "tasks",
        "runnability",
        "coverage",
        "refresh",
        "fulfillment",
        "documentation",
        "tasks",
    ]


@pytest.mark.unit
def test_green_aggregate_verifier_cannot_converge_with_unbound_coverage(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "tests").mkdir()
    (worktree / "tests" / "feature.test.ts").write_text(
        "it('untagged test', () => {});\n", encoding="utf-8"
    )
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | UT-PERSIST-001 | unit | deferred-automation | deferred-automation | test | add tagged test |\n",
        encoding="utf-8",
    )
    fingerprint = product_evidence_fingerprint(worktree)
    evidence_dir = tmp_path / "evidence"
    standard_receipt = write_verification_receipt(
        evidence_dir=evidence_dir / "verification",
        spec_id="spec-001",
        target_id="game",
                build_id="build-001",
        candidate_commit="a" * 40,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(
            VerificationStage(
                name="verify",
                command=("pnpm", "verify"),
                exit_code=0,
                duration_ms=1,
                stdout=b"ok",
                stderr=b"",
            ),
        ),
        attempt_sequence=1,
        sensitive_environment={},
    )
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)
    bundle = CoverageVerificationBundle(
        standard_receipt=standard_receipt,
        observer_runs=(
            CoverageObserverRun(
                observer_id="vitest-unit",
                receipt=standard_receipt,
                executions=(),
                status="passed",
            ),
        ),
    )
    with patch(
        "harness.candidate_evidence._current_git_commit", return_value="a" * 40
    ), patch(
        "harness.candidate_evidence.run_coverage_observers", return_value=bundle
    ):
        result = controller._apply_coverage_observation_gate(
            VerifyResult(
                passed=True,
                verification_evidence=standard_receipt.as_mapping(),
            ),
            str(worktree),
        )

    assert result.passed is False
    assert result.failures[0].id == "coverage-observation-gaps"
    assert result.failures[0].details["requirements"] == {"FR-001": "unbound"}
    assert result.failures[0].details["test_cases"] == {
        "UT-PERSIST-001": {
            "test_type": "unit",
            "status": "unbound",
            "reason": "no executed tagged test matches the planned case",
        }
    }


@pytest.mark.unit
def test_coverage_gate_rejects_an_unavailable_type_before_starting_observers(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | RUST-001 | rust-unit | deferred-automation | deferred-automation | test | repair |\n",
        encoding="utf-8",
    )
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)

    with patch("harness.candidate_evidence.run_coverage_observers") as observers:
        result = controller._apply_coverage_observation_gate(
            VerifyResult(passed=True), str(worktree)
        )

    assert result.passed is False
    assert result.failures[0].id == "coverage-observer-unavailable"
    assert "rust-unit" in result.failures[0].error
    observers.assert_not_called()


def test_coverage_gate_delegates_to_shared_candidate_evidence_runner(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    shared = MagicMock()
    expected = VerifyResult(passed=True, verification_evidence={"passed": True})
    gate = MagicMock(
        verify_result=expected,
        state_summary={"status": "passed"},
    )
    shared.apply_coverage.return_value = gate
    controller._candidate_evidence_runner = shared
    controller._find_existing_spec_dir = MagicMock(return_value=tmp_path / "spec")
    controller._record_coverage_observation_summary = MagicMock()

    result = controller._apply_coverage_observation_gate(
        VerifyResult(passed=True), str(tmp_path)
    )

    assert result is expected
    shared.apply_coverage.assert_called_once()
    kwargs = shared.apply_coverage.call_args.kwargs
    assert kwargs["worktree"] == tmp_path
    assert kwargs["spec_dir"] == tmp_path / "spec"
    controller._record_coverage_observation_summary.assert_called_once_with(
        {"status": "passed"}
    )


def test_partial_delivery_coverage_uses_only_completed_task_ownership(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "# Tasks\n\n"
        "- [x] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n"
        "  **Status:** DONE\n"
        "  **Named Test Ownership:** `UT-DONE-001`, `E2E-DONE-002`.\n\n"
        "- [ ] T-002 complexity=standard phase=feature req=FR-002 depends=T-001\n"
        "  **Named Test Ownership:** `UT-FUTURE-001`.\n",
        encoding="utf-8",
    )

    assert _completed_task_coverage_case_ids(tasks) == {
        "UT-DONE-001",
        "E2E-DONE-002",
    }


def test_partial_delivery_coverage_accepts_existing_ownership_label(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "# Tasks\n\n"
        "- [x] T-001 complexity=standard phase=foundation req=FR-012 depends=none\n"
        "  **Status:** DONE\n"
        "  **Test Case IDs Owned:** `UT-NAV-004`, `UT-NAV-005`, `UT-NAV-006`.\n\n"
        "- [ ] T-002 complexity=standard phase=feature req=FR-013 depends=T-001\n"
        "  **Test Case IDs Owned:** `IT-FUTURE-001`.\n",
        encoding="utf-8",
    )

    assert _completed_task_coverage_case_ids(tasks) == {
        "UT-NAV-004",
        "UT-NAV-005",
        "UT-NAV-006",
    }


def test_completed_delivery_coverage_uses_full_map(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "# Tasks\n\n"
        "- [x] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n"
        "  **Status:** DONE\n"
        "  **Named Test Ownership:** `UT-DONE-001`.\n",
        encoding="utf-8",
    )

    assert _completed_task_coverage_case_ids(tasks) is None


def test_coverage_gate_passes_partial_delivery_scope_to_evidence_runner(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n"
        "- [x] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n"
        "  **Status:** DONE\n"
        "  **Named Test Ownership:** `UT-DONE-001`.\n\n"
        "- [ ] T-002 complexity=standard phase=feature req=FR-002 depends=T-001\n"
        "  **Named Test Ownership:** `UT-FUTURE-001`.\n",
        encoding="utf-8",
    )
    controller, *_ = _make_controller(tmp_path)
    shared = MagicMock()
    expected = VerifyResult(passed=True)
    shared.apply_coverage.return_value = MagicMock(
        verify_result=expected,
        state_summary={"status": "passed"},
    )
    controller._candidate_evidence_runner = shared
    controller._find_existing_spec_dir = MagicMock(return_value=spec_dir)

    result = controller._apply_coverage_observation_gate(
        VerifyResult(passed=True), str(tmp_path)
    )

    assert result is expected
    assert shared.apply_coverage.call_args.kwargs["required_case_ids"] == {
        "UT-DONE-001"
    }


@pytest.mark.unit
def test_coverage_gate_does_not_treat_an_unmapped_requirement_as_deferred(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# FR-001\n", encoding="utf-8")
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)

    with patch("harness.candidate_evidence.run_coverage_observers") as observers:
        result = controller._apply_coverage_observation_gate(
            VerifyResult(passed=True), str(worktree)
        )

    assert result.passed is False
    assert result.failures[0].id == "coverage-observer-map-incomplete"
    assert result.failures[0].details["requirements"] == {"FR-001": "unmapped"}
    assert "FR-001" in result.failures[0].error
    observers.assert_not_called()


@pytest.mark.unit
def test_coverage_gate_never_materializes_spec_into_verified_candidate(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "src").mkdir()
    (worktree / "src" / "game.ts").write_text("export {};\n", encoding="utf-8")
    external_spec = tmp_path / "specs" / "spec-001"
    external_spec.mkdir(parents=True)
    (external_spec / "coverage-map.md").write_text("# Coverage\n", encoding="utf-8")
    state = state_store.read()
    state["spec_dir"] = str(external_spec)
    state_store.write(state)
    fingerprint_before = product_evidence_fingerprint(worktree)

    result = controller._apply_coverage_observation_gate(
        VerifyResult(passed=True),
        str(worktree),
    )

    assert result.passed is False
    assert result.failures[0].id == "coverage-observer-spec-missing"
    assert not (worktree / "specs").exists()
    assert product_evidence_fingerprint(worktree) == fingerprint_before


@pytest.mark.unit
def test_strict_observation_is_validated_and_handed_to_fulfillment(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | UT-001 | unit | deferred-automation | deferred-automation | test | repair |\n",
        encoding="utf-8",
    )
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)
    ref = CoverageObservationRef(
        path=tmp_path / "evidence" / "attempt-0001.json",
        receipt_sha256="a" * 64,
        observation_sha256="b" * 64,
        candidate_fingerprint=product_evidence_fingerprint(worktree),
        passed=True,
    )
    observation = CoverageObservationResult(
        ref=ref,
        test_cases={},
        requirements={},
    )
    controller._fulfillment_runner = MagicMock()
    controller._fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
        status="cached", exit_code=0
    )
    controller._prepare_delivery_context(str(worktree))

    with patch("harness.ralph.load_coverage_observation", return_value=observation), patch(
        "harness.ralph.validate_coverage_observation",
        return_value=CoverageObservationValidation(valid=True),
    ), patch("harness.ralph._current_git_commit", return_value="a" * 40):
        result = controller._refresh_fulfillment_report(
            VerifyResult(
                passed=True,
                verification_evidence={"coverage_observation": ref.as_mapping()},
            ),
            str(worktree),
        )

    assert result.passed is True
    kwargs = controller._fulfillment_runner.refresh.call_args.kwargs
    assert kwargs["observer_required"] is True
    assert kwargs["coverage_observation"] is observation


@pytest.mark.unit
def test_invalid_strict_observation_stops_before_fulfillment(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | UT-001 | unit | deferred-automation | deferred-automation | test | repair |\n",
        encoding="utf-8",
    )
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)
    controller._fulfillment_runner = MagicMock()

    result = controller._refresh_fulfillment_report(
        VerifyResult(passed=True, verification_evidence={}),
        str(worktree),
    )

    assert result.passed is False
    assert result.failures[0].id == "coverage-observation-invalid"
    controller._fulfillment_runner.refresh.assert_not_called()


@pytest.mark.unit
def test_owner_deferred_coverage_does_not_require_an_observer_run(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_stacks = _required_coverage_stacks()
    controller, *_rest, state_store = _make_controller(tmp_path, config=config)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | UT-001 | unit | deferred-automation | deferred-automation | test | repair |\n",
        encoding="utf-8",
    )
    (spec_dir / "deferred-scope.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "defer-001",
                        "status": "deferred",
                        "selected_ids": ["FR-001"],
                        "derived_task_ids": [],
                        "prior_task_statuses": {},
                        "reason": "owner-approved scope deferral",
                        "deferred_at": "2026-09-05T00:00:00Z",
                        "planned_at": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = state_store.read()
    state["spec_dir"] = str(spec_dir)
    state["target_repo"] = "target"
    state_store.write(state)

    with patch("harness.candidate_evidence.run_coverage_observers") as observers:
        result = controller._apply_coverage_observation_gate(
            VerifyResult(passed=True),
            str(worktree),
        )

    assert result.passed is True
    observers.assert_not_called()


@pytest.mark.unit
def test_required_user_facing_stack_cannot_converge_without_candidate_contract(
    tmp_path: Path,
) -> None:
    config = _make_config()
    config.resolved_runnability = _required_browser_runnability()
    controller, _provider, gitops, _state = _make_controller(
        tmp_path,
        verify_results=[{"passed": True, "failures": []}],
        config=config,
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    gitops.create_worktree.return_value = str(worktree)

    result = controller.run_loop(max_outer=1, max_inner=0)

    assert result.status != "verified"
    assert result.final_verify is not None
    assert result.final_verify.failures[0].id == "user-runnability-contract-missing"


@pytest.mark.unit
def test_candidate_disabled_contract_cannot_downgrade_required_stack(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._config.resolved_runnability = _required_browser_runnability()
    worktree = tmp_path / "worktree"
    contract = worktree / ".echelon" / "runnability.yml"
    contract.parent.mkdir(parents=True)
    contract.write_text("schema_version: 1\nenabled: false\n", encoding="utf-8")

    result = controller._apply_user_runnability_gate(
        VerifyResult(passed=True),
        str(worktree),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence" / "user-runnability",
    )

    assert result.passed is False
    assert result.failures[0].id == "user-runnability-contract-disabled"


@pytest.mark.unit
def test_non_runnable_stack_without_contract_preserves_existing_gate_result(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._config.resolved_runnability = ResolvedRunnability()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    original = VerifyResult(passed=True)

    result = controller._apply_user_runnability_gate(
        original,
        str(worktree),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence" / "user-runnability",
    )

    assert result is original


@pytest.mark.unit
def test_runnability_failure_persists_compact_state_and_actionable_report_context(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._config.resolved_runnability = _required_browser_runnability()
    controller._config.resolved_stacks = object()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _write_enabled_runnability_contract(worktree)
    evidence_dir = tmp_path / "evidence" / "user-runnability"
    evidence_dir.mkdir(parents=True)
    report = evidence_dir / "attempt-0001-a.md"
    evidence = RunnabilityEvidenceRef(
        path=evidence_dir / "attempt-0001-a.json",
        markdown_path=report,
        receipt_sha256="receipt",
        evidence_sha256="evidence",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        status="not_runnable",
    )
    run_result = RunnabilityRunResult(
        status="not_runnable",
        failed_stage="primary_journey",
        failure_class="primary_journey_failed",
        summary="The canvas never became interactive.",
        stages=(),
        evidence=evidence,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        user_commands={"start": ("make start",)},
        local_journey_status="unverified",
        local_journey_reason="No compatible local runner executed these commands.",
        local_user_commands={
            "provision": ("docker compose up -d postgres",),
            "verify": ("make verify-local",),
            "cleanup": ("docker compose down -v",),
        },
        local_boundary_probes=(
            LocalBoundaryProbe(
                id="postgres-from-app",
                service="postgres",
                command="make probe-local-db",
            ),
        ),
    )

    with patch("harness.candidate_evidence.RunnabilityRunner") as runner_type:
        runner_type.return_value.run.return_value = run_result
        result = controller._apply_user_runnability_gate(
            VerifyResult(passed=True),
            str(worktree),
            candidate_commit="a" * 40,
            evidence_dir=evidence_dir,
        )

    assert result.passed is False
    assert result.failures[0].id == "user-runnability-primary-journey-failed"
    assert result.failures[0].details["report"] == str(report)
    assert result.failures[0].details["required_repair"].startswith("Repair the candidate")
    prompt = controller._make_feedback_prompt("Continue delivery.", result, 1)
    assert "primary_journey_failed" in prompt
    assert str(report) in prompt
    state = controller._state_store.read()["user_runnability"]
    assert state == {
        "status": "not_runnable",
        "failed_stage": "primary_journey",
        "failure_class": "primary_journey_failed",
        "summary": "The canvas never became interactive.",
        "report": str(report),
        "candidate_fingerprint": "product-1",
        "contract_hash": "contract-1",
        "stack_hash": "stack-1",
        "user_commands": {"start": ["make start"]},
        "local_journey": {
            "status": "unverified",
            "reason": "No compatible local runner executed these commands.",
            "commands": {
                "provision": ["docker compose up -d postgres"],
                "verify": ["make verify-local"],
                "cleanup": ["docker compose down -v"],
            },
            "boundary_probes": [
                {
                    "id": "postgres-from-app",
                    "service": "postgres",
                    "command": "make probe-local-db",
                }
            ],
        },
    }


@pytest.mark.unit
def test_passing_runnability_is_attached_to_downstream_verification_evidence(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._config.resolved_runnability = _required_browser_runnability()
    controller._config.resolved_stacks = object()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _write_enabled_runnability_contract(worktree)
    evidence = RunnabilityEvidenceRef(
        path=(tmp_path / "attempt.json").resolve(),
        markdown_path=(tmp_path / "attempt.md").resolve(),
        receipt_sha256="receipt",
        evidence_sha256="evidence",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        status="runnable",
    )
    run_result = RunnabilityRunResult(
        status="runnable",
        failed_stage=None,
        failure_class="",
        summary="Composed journey passed.",
        stages=(),
        evidence=evidence,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        user_commands={},
    )
    original = VerifyResult(
        passed=True,
        verification_evidence={"path": "/tmp/host-receipt.json"},
    )

    with patch("harness.candidate_evidence.RunnabilityRunner") as runner_type:
        runner_type.return_value.run.return_value = run_result
        result = controller._apply_user_runnability_gate(
            original,
            str(worktree),
            candidate_commit="a" * 40,
            evidence_dir=tmp_path / "evidence" / "user-runnability",
        )

    assert result.passed is True
    assert result.verification_evidence["path"] == "/tmp/host-receipt.json"
    assert result.verification_evidence["runnability_evidence"] == evidence.as_mapping()


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _commit_worktree_changes(path: str, message: str, **_kwargs: object) -> str:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=path
    ).returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=path,
            check=True,
            capture_output=True,
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_no_impact_documentation_report(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: false\n"
        "readme_updated: false\n"
        "changelog_updated: false\n"
        "changelog_format: not_required\n"
        'not_applicable_reason: "Fixture build has no user-visible documentation impact."\n'
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )


@pytest.mark.unit
class TestOuterLoopConvergence:

    def test_verification_deferral_checkpoints_without_task_progress(
        self, tmp_path: Path
    ) -> None:
        controller, _, gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(worktree)
        (worktree / "candidate.txt").write_text(
            "implemented\n", encoding="utf-8"
        )
        before = state_store.read().get("build", {}).get(
            "completed_tasks", 0
        )
        gitops.commit.side_effect = _commit_worktree_changes

        commit = controller._checkpoint_verification_deferred_candidate(
            str(worktree), outer_iter=0, inner_iter=0, phase="build"
        )

        assert commit == subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        gitops.commit.assert_called_once()
        after = state_store.read().get("build", {}).get("completed_tasks", 0)
        assert after == before
        checkpoint = state_store.read()["checkpoint_commits"][-1]
        assert checkpoint["provenance"] == "verification_deferred"



    """Test outer loop converges on first iteration."""

    def test_sync_phase_a_inputs_overwrites_stale_worktree_constitution(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in (
            "00-overview.md",
            "requirements-overview.md",
            "spec.md",
            "plan.md",
            "plan-conformance.md",
            "plan-conformance.json",
            "research.md",
            "data-model.md",
        ):
            content = (
                _valid_plan_conformance_json()
                if name == "plan-conformance.json"
                else f"# {name}\n"
            )
            (source / name).write_text(content, encoding="utf-8")
        for name in ("test-strategy.md", "test-architecture.md", "coverage-map.md"):
            content = (
                "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
                "|---|---|---|---|---|---|---|\n"
                "| FR-001 | UT-001 | unit | planned | planned | tests | implement |\n"
                if name == "coverage-map.md"
                else f"# {name}\n"
            )
            (source / name).write_text(content, encoding="utf-8")
        (source / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        (source / "constitution.md").write_text(
            "# Real Constitution\n\nProject-specific governance.\n",
            encoding="utf-8",
        )
        canonical = project / ".echelon" / "constitution.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("# Real Constitution\n", encoding="utf-8")

        worktree = tmp_path / "worktree"
        stale = worktree / "specs" / "spec-001-demo"
        stale.mkdir(parents=True)
        (stale / "constitution.md").write_text(
            "# [PROJECT_NAME] Constitution\n\n[PRINCIPLE_1_NAME]\n",
            encoding="utf-8",
        )
        stale_canonical = worktree / ".echelon" / "constitution.md"
        stale_canonical.parent.mkdir(parents=True)
        stale_canonical.write_text("# [PROJECT_NAME] Constitution\n", encoding="utf-8")

        state = state_store.read()
        state["spec_dir"] = str(source)
        state_store.write(state)

        blockers = controller._sync_phase_a_inputs_into_worktree(worktree)

        assert blockers == []
        assert "[PROJECT_NAME]" not in (stale / "constitution.md").read_text(encoding="utf-8")
        assert "Real Constitution" in (stale / "constitution.md").read_text(encoding="utf-8")
        assert "[PROJECT_NAME]" not in stale_canonical.read_text(encoding="utf-8")

    def test_sync_phase_a_inputs_reconciles_state_task_progress(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in (
            "00-overview.md",
            "requirements-overview.md",
            "spec.md",
            "plan.md",
            "plan-conformance.md",
            "plan-conformance.json",
            "research.md",
            "data-model.md",
        ):
            content = (
                _valid_plan_conformance_json()
                if name == "plan-conformance.json"
                else f"# {name}\n"
            )
            (source / name).write_text(content, encoding="utf-8")
        for name in ("test-strategy.md", "test-architecture.md", "coverage-map.md"):
            content = (
                "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
                "|---|---|---|---|---|---|---|\n"
                "| FR-001 | UT-001 | unit | planned | planned | tests | implement |\n"
                if name == "coverage-map.md"
                else f"# {name}\n"
            )
            (source / name).write_text(content, encoding="utf-8")
        (source / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "\n"
            "  **Acceptance Criteria:**\n"
            "  - [ ] Gate passes\n"
            "\n"
            "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001\n",
            encoding="utf-8",
        )
        (source / "constitution.md").write_text(
            "# Real Constitution\n\nProject-specific governance.\n",
            encoding="utf-8",
        )
        canonical = project / ".echelon" / "constitution.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("# Real Constitution\n", encoding="utf-8")

        state = state_store.read()
        state["spec_dir"] = str(source)
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 1,
            "tasks_completed_pct": 50,
            "task_results": {
                "T-001": {"status": "DONE"},
                "T-002": {"status": "PENDING"},
            },
        }
        state_store.write(state)

        worktree = tmp_path / "worktree"
        blockers = controller._sync_phase_a_inputs_into_worktree(worktree)

        assert blockers == []
        synced_tasks = worktree / "specs" / "spec-001-demo" / "tasks.md"
        text = synced_tasks.read_text(encoding="utf-8")
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in text
        assert "  **Status:** DONE" in text
        assert "  - [x] Gate passes" in text
        assert "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001" in text

    def test_sync_phase_a_inputs_blocks_invalid_worktree_copy(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
        ):
            (source / name).write_text(f"# {name}\n", encoding="utf-8")
        (source / "constitution.md").write_text(
            "# [PROJECT_NAME] Constitution\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["spec_dir"] = str(source)
        state_store.write(state)

        blockers = controller._sync_phase_a_inputs_into_worktree(tmp_path / "worktree")

        assert any("constitution.md contains unresolved template markers" in blocker for blocker in blockers)



















    def test_target_progress_completes_when_its_scoped_tasks_are_done(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "workspace" / "sources" / "api"
        spec_dir = tmp_path / "workspace" / "specs" / "001-dashboard"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001\n",
            encoding="utf-8",
        )
        state = state_store.read()
        state["spec_dir"] = str(spec_dir)
        state["target_path"] = str(worktree)
        state_store.write(state)
        monkeypatch.setenv("ECHELON_TARGET_TASK_IDS", "T-001")

        applied = controller._apply_build_task_progress(
            worktree_path=str(worktree),
            task_ids=["T-001"],
        )

        assert applied == ["T-001"]
        build = state_store.read()["build"]
        assert build["total_tasks"] == 1
        assert build["completed_tasks"] == 1
        assert build["tasks_completed_pct"] == 100
        assert controller._all_canonical_tasks_complete(str(worktree)) is True










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
        assert result.failures[0].details == {
            "gaps": [
                {
                    "requirement_id": "FR-001",
                    "status": "MISSING",
                    "summary": "none",
                    "recommended_action": "Run `echelon spec reopen spec-001` or implement and verify FR-001.",
                }
            ]
        }
        assert "FR-001 [MISSING]: none" in result.failures[0].error
        assert "echelon spec reopen spec-001" in result.failures[0].error

    def test_fulfillment_gate_treats_unverified_as_blocking_for_harness(
        self, tmp_path: Path
    ) -> None:
        """Harness convergence requires strict fulfillment, including UNVERIFIED."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=build req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | UNVERIFIED | src/a.py | medium | no executable proof |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert "UNVERIFIED" in result.failures[0].error

    def test_fulfillment_gate_rejects_unledgered_deferred_scope_row(
        self, tmp_path: Path
    ) -> None:
        """A DEFERRED_SCOPE report row must be backed by committed scope state."""
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
            "| FR-001 | DEFERRED_SCOPE | defer:defer-001: owner decision | high | deferred |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-deferred-scope-invalid"
        assert "FR-001 has no active defer entry" in result.failures[0].error

    def test_fulfillment_gate_blocks_stale_report_for_current_head(
        self, tmp_path: Path
    ) -> None:
        """Harness must not trust a fulfillment report stamped for an older commit."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: spec-001\n"
            "verified_commit: old123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        with patch("harness.ralph._current_git_commit", return_value="new456"):
            result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-report-stale"
        assert "old123" in result.failures[0].error
        assert "new456" in result.failures[0].error

    def test_fulfillment_gate_rejects_scoped_report_as_convergence_evidence(
        self, tmp_path: Path
    ) -> None:
        """Scoped fulfillment reports are incremental evidence, not final proof."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: spec-001\n"
            "verified_commit: head456\n"
            "verify_scope: scoped\n"
            "base_full_verify_commit: base123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        with patch("harness.ralph._current_git_commit", return_value="head456"):
            result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-report-scoped"
        assert "Do not regenerate fulfillment artifacts in a build slice" in result.failures[0].error
        assert "Ralph must run a full fulfillment refresh before convergence" in result.failures[0].error

    def test_fulfillment_gate_reads_orchestration_spec_dir_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Fulfillment gate uses orchestration spec artifacts, not target worktree discovery."""
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "iter-0"
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
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert str(spec_dir / "fulfillment-report.md") in result.failures[0].error

    def test_documentation_gate_blocks_convergence_when_required_docs_missing(
        self, tmp_path: Path
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (worktree / "README.md").write_text("# Demo\n", encoding="utf-8")
        (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (spec_dir / "documentation-impact-report.md").write_text(
            "---\n"
            "docs_required: true\n"
            "readme_updated: true\n"
            "changelog_updated: true\n"
            "changelog_format: keep_a_changelog\n"
            'not_applicable_reason: ""\n'
            "---\n"
            "# Documentation Impact Report\n",
            encoding="utf-8",
        )
        _commit_all(worktree)
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

        result = controller._apply_documentation_gate(verify, str(worktree))

        assert not result.passed
        assert result.failures[0].id == "documentation-required-without-doc-changes"




    def test_documentation_gate_blocks_when_prior_branch_commit_changed_target(
        self, tmp_path: Path
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "README.md").write_text("# Target\n", encoding="utf-8")
        _commit_all(worktree)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=worktree, check=True)
        (worktree / "src").mkdir()
        (worktree / "src" / "cli.js").write_text("console.log('styled')\n", encoding="utf-8")
        _commit_all(worktree, "implement cli styling")
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

        result = controller._apply_documentation_gate(
            verify,
            str(worktree),
            changed_files=[],
        )

        assert not result.passed
        assert result.failures[0].id == "documentation-impact-report-missing"
        assert not (spec_dir / "documentation-impact-report.md").exists()

    def test_documentation_gate_receives_delivery_slice_changed_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)
        seen: dict[str, object] = {}

        def fake_gate(
            worktree_path: Path,
            resolved_spec_dir: Path,
            *,
            changed_files=None,
            runnability_report=None,
            runnability_required=False,
            require_independent_review=False,
        ):
            seen["worktree_path"] = worktree_path
            seen["spec_dir"] = resolved_spec_dir
            seen["changed_files"] = changed_files
            return DocumentationGateResult(passed=True)

        monkeypatch.setattr("harness.ralph.evaluate_documentation_gate", fake_gate)

        result = controller._apply_documentation_gate(
            verify,
            str(worktree),
            changed_files=["README.md", "CHANGELOG.md"],
        )

        assert result.passed
        assert seen["worktree_path"] == worktree
        assert seen["spec_dir"] == spec_dir
        assert seen["changed_files"] == ["README.md", "CHANGELOG.md"]

    def test_documentation_gate_includes_docs_committed_after_task_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller, *_rest, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "README.md").write_text("# Before\n", encoding="utf-8")
        (worktree / "CHANGELOG.md").write_text("# Before\n", encoding="utf-8")
        _commit_all(worktree)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=worktree, check=True)
        (worktree / "src").mkdir()
        (worktree / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(worktree, "implement feature")
        (worktree / "README.md").write_text("# Feature\n", encoding="utf-8")
        (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        _commit_all(worktree, "document feature")
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        seen: dict[str, object] = {}

        def fake_gate(
            worktree_path: Path,
            resolved_spec_dir: Path,
            *,
            changed_files=None,
            runnability_report=None,
            runnability_required=False,
            require_independent_review=False,
        ):
            seen["changed_files"] = changed_files
            return DocumentationGateResult(passed=True)

        monkeypatch.setattr("harness.ralph.evaluate_documentation_gate", fake_gate)

        result = controller._apply_documentation_gate(
            VerifyResult(passed=True, failures=[]),
            str(worktree),
            changed_files=[],
        )

        assert result.passed
        assert {"README.md", "CHANGELOG.md"} <= set(seen["changed_files"])
        evidence = state_store.read()["documentation_evidence"]
        assert evidence["head"] == subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert {"README.md", "CHANGELOG.md"} <= set(evidence["changed_files"])

    def test_missing_documentation_report_is_repairable_by_tech_writer(
        self, tmp_path: Path
    ) -> None:
        """TECH WRITER owns docs artifacts even when spec artifacts are external."""
        controller, *_rest, state_store = _make_controller(tmp_path)
        state = state_store.read()
        state["target_repo"] = "target-app"
        state["target_path"] = str(tmp_path / "target-app")
        state_store.write(state)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "documentation-impact-report-missing",
                    "missing documentation-impact-report.md",
                )
            ],
        )

        assert controller._is_external_spec_artifact_failure(verify) is False

    def test_missing_task_owned_coverage_case_is_external_spec_blocker(
        self, tmp_path: Path
    ) -> None:
        controller, *_rest, state_store = _make_controller(tmp_path)
        state = state_store.read()
        state["target_repo"] = "target-app"
        state["target_path"] = str(tmp_path / "target-app")
        state_store.write(state)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "coverage-observer-scope-invalid",
                    "Completed task coverage ownership is absent from "
                    "coverage-map.md: UT-GEST-006",
                )
            ],
        )

        assert controller._is_external_spec_artifact_failure(verify) is True

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

    def test_open_canonical_task_turns_passing_verify_into_failure(
        self, tmp_path: Path
    ) -> None:
        """A passing test suite cannot converge before every target task is terminal."""
        controller, *_rest = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-015 complexity=standard phase=verification req=INFRA depends=none\n",
            encoding="utf-8",
        )

        result = controller._apply_task_progress_gate(
            VerifyResult(passed=True, failures=[]), str(worktree)
        )

        assert result.passed is False
        assert result.failures[0].id == "task-progress-incomplete"
        assert "T-015" in result.failures[0].error

    def test_completed_task_missing_declared_file_turns_passing_verify_into_failure(
        self, tmp_path: Path
    ) -> None:
        """A task cannot be complete when a declared source deliverable is absent."""
        controller, *_rest, state_store = _make_controller(tmp_path)
        state = state_store.read()
        state["implementation_target"] = "sources/demo"
        state_store.write(state)
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-015 complexity=standard phase=verification req=INFRA depends=none\n"
            "\n"
            "  **Files:**\n"
            "  - `sources/demo/README.md` - setup guide\n",
            encoding="utf-8",
        )

        result = controller._apply_task_progress_gate(
            VerifyResult(passed=True, failures=[]), str(worktree)
        )

        assert result.passed is False
        assert result.failures[0].id == "task-deliverable-missing"
        assert "T-015: README.md" in result.failures[0].error

    def test_completed_task_ignores_inline_code_after_declared_file(
        self, tmp_path: Path
    ) -> None:
        """Only the leading code span in a Files bullet names a deliverable."""
        worktree = tmp_path / "worktree"
        declared_files = (
            "apps/api/src/http/progress-routes.ts",
            "apps/api/src/http/collection-routes.ts",
            "package.json",
            "apps/web/src/scene/interaction-controller.tsx",
        )
        for declared_file in declared_files:
            path = worktree / declared_file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        markdown = (
            "- [x] T-005 complexity=standard phase=authority req=FR-003 "
            "depends=none target=sources/demo\n"
            "\n"
            "  **Files:**\n"
            "  - `sources/demo/apps/api/src/http/progress-routes.ts` - strict "
            "`GET /api/v1/progress`\n"
            "  - `sources/demo/apps/api/src/http/collection-routes.ts` - strict "
            "`POST /api/v1/collections`\n"
            "  - `sources/demo/package.json` - pin `@fastify/rate-limit`\n"
            "  - `sources/demo/apps/web/src/scene/interaction-controller.tsx` - "
            "handle the `E` key\n"
        )

        missing = ralph._missing_completed_task_deliverables(
            markdown,
            task_statuses={"T-005": "DONE"},
            worktree_path=worktree,
            implementation_target="sources/demo",
        )

        assert missing == []

    def test_build_reported_task_ids_mark_canonical_tasks_done(
        self, tmp_path: Path
    ) -> None:
        """Ralph applies build status marker task IDs to tasks.md before verify."""
        controller, _, _, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        tasks_path = spec_dir / "tasks.md"
        tasks_path.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "\n"
            "  **Acceptance Criteria:**\n"
            "  - [ ] Gate passes\n"
            "\n"
            "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001\n",
            encoding="utf-8",
        )

        applied = controller._apply_build_task_progress(
            worktree_path=str(worktree),
            task_ids=["T-001"],
        )

        assert applied == ["T-001"]
        text = tasks_path.read_text(encoding="utf-8")
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in text
        assert "  **Status:** DONE" in text
        assert "  - [x] Gate passes" in text
        assert "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001" in text
        build = state_store.read()["build"]
        assert build["completed_tasks"] == 1
        assert build["task_results"]["T-001"]["status"] == "DONE"

    def test_build_reported_unknown_task_ids_are_not_silently_applied(
        self, tmp_path: Path
    ) -> None:
        """Ralph exposes failed task-ledger updates for the build loop to block."""
        controller, _, _, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        tasks_path = spec_dir / "tasks.md"
        tasks_path.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        applied = controller._apply_build_task_progress(
            worktree_path=str(worktree),
            task_ids=["T-999"],
        )

        assert applied == []
        assert "- [ ] T-001" in tasks_path.read_text(encoding="utf-8")

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

        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
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

        assert result.status == "verified"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 1
        assert result.pr_url is not None
        assert provider.created is False
        assert provider.destroyed is False
        gitops.create_worktree.assert_called_once()
        gitops.promote_pr_ready.assert_called_once()
        gitops.local_merge.assert_called_once_with(
            "harness/spec-001/build-1/iter-0",
            "spec-001",
        )
        gitops.destroy_worktree.assert_not_called()

    def test_fresh_delivery_requests_fresh_legacy_iteration_branch(
        self, tmp_path: Path
    ) -> None:
        controller, _, gitops, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            fresh_delivery=True,
        )

        controller.run_loop(max_outer=1, max_inner=0)

        assert gitops.create_worktree.call_args.kwargs["fresh_branch"] is True

    def test_merge_failure_blocks_convergence(self, tmp_path: Path) -> None:
        """Verified branch cannot be reported converged until it lands on default."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.local_merge.side_effect = RuntimeError("merge conflict")

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "blocked"
        assert result.termination_reason == "target_merge_failed"
        gitops.local_merge.assert_called_once_with(
            "harness/spec-001/build-1/iter-0",
            "spec-001",
        )
        gitops.promote_pr_ready.assert_not_called()
        assert provider.destroyed is False
        gitops.destroy_worktree.assert_not_called()
        final_state = state_store.read()
        assert final_state["status"] == "running"
        assert final_state["target_merge"]["error"] == "merge conflict"

    def test_mirror_only_publication_reports_unsynced_target_truthfully(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.local_merge.return_value = {
            "mirror_landed": True,
            "pushed": False,
            "target_synced": False,
            "target_sync_skipped": True,
            "target_sync_skip_reason": "dirty_local_worktree",
            "target_repo": str(tmp_path / "target"),
        }
        state = state_store.read()
        state["status"] = "running"
        state_store.write(state)

        published = controller._merge_verified_branch(
            str(tmp_path / "worktree"),
            "harness/spec-001/build-1/iter-0",
            VerifyResult(passed=True, failures=[]),
            force=True,
        )

        assert published is True
        assert "target checkout remains unsynced" in caplog.text
        assert "Merged verified delivery branch" not in caplog.text

    def test_downstream_gates_defer_target_merge_after_phase1(
        self, tmp_path: Path
    ) -> None:
        """A verified candidate is not published before visual/review gates pass."""
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            defer_target_merge=True,
        )

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        gitops.local_merge.assert_not_called()
        deferred = state_store.read()["target_merge"]
        assert deferred["status"] == "deferred"
        assert deferred["branch"] == result.branch
        assert deferred["default_branch"] == "main"
        assert deferred["verified"] is True
        assert deferred["worktree_path"] == gitops.create_worktree.return_value
        assert deferred["verify_result"]["passed"] is True

    def test_downstream_reentry_reuses_registered_repaired_worktree(
        self, tmp_path: Path
    ) -> None:
        """A dirty visual repair is not replaced by a new branch/worktree."""
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            resume_worktree_path=str(tmp_path),
        )

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        gitops.create_worktree.assert_not_called()
        assert gitops.commit.call_args.args[0] == str(tmp_path)



    def test_convergence_does_not_write_delivery_status(self, tmp_path: Path) -> None:
        """Ralph keeps phase evidence separate from delivery state transitions."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "In Progress"
        assert "**Status**: In Progress" in (spec_dir / "spec.md").read_text(
            encoding="utf-8"
        )
        assert not (spec_dir / "run-history.json").exists()
        assert not (spec_dir / "ARTIFACTS.md").exists()

    def test_publish_does_not_require_a_ready_to_land_marker(
        self, tmp_path: Path
    ) -> None:
        """Publishing Phase 1 evidence does not write delivery state."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        def assert_phase_evidence_committed(
            path: str, message: str, **_kwargs: object
        ) -> str:
            del message
            from harness.spec_frontmatter import read_frontmatter

            committed_spec_dir = Path(path) / "specs" / "spec-001-demo"
            assert read_frontmatter(committed_spec_dir)["status"] == "In Progress"
            assert "**Status**: In Progress" in (
                committed_spec_dir / "spec.md"
            ).read_text(encoding="utf-8")
            return "abc123"

        gitops.commit.side_effect = assert_phase_evidence_committed

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        assert gitops.push.call_count == 2
        gitops.promote_pr_ready.assert_called_once()

    def test_convergence_leaves_orchestration_delivery_status_unchanged(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo Phase 1 does not update orchestration delivery status."""
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        _init_git_repo(orchestration_root)
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        _commit_all(orchestration_root, "initial spec")
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        from harness.spec_frontmatter import read_frontmatter

        assert read_frontmatter(spec_dir)["status"] == "In Progress"
        assert not (spec_dir / "run-history.json").exists()
        assert not (spec_dir / "ARTIFACTS.md").exists()

    def test_convergence_commits_orchestration_artifacts_without_delivery_status(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo Phase 1 commits artifacts without moving delivery state."""
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        _init_git_repo(orchestration_root)
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        _commit_all(orchestration_root, "initial spec")
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state_store.write(state)

        with patch.object(
            controller,
            "_apply_documentation_gate",
            side_effect=lambda verify, *_args, **_kwargs: verify,
        ):
            result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "verified"
        committed_spec = subprocess.run(
            ["git", "show", f"HEAD:{spec_dir.relative_to(orchestration_root) / 'spec.md'}"],
            cwd=orchestration_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "status: In Progress" in committed_spec
        assert "**Status**: In Progress" in committed_spec
        assert "run-history.json" not in subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=orchestration_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

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

        assert result.status == "blocked"
        assert result.termination_reason == "outer_cap"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert result.final_verify.failures[0].id == "fulfillment-gaps"
        gitops.promote_pr_ready.assert_not_called()


    def test_refresh_uses_state_workspace_root_for_external_spec_artifacts(
        self, tmp_path: Path
    ) -> None:
        """Target runtime storage must not redefine the workspace artifact root."""
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        runtime_root = workspace / "runs" / "targets" / "prosaic"
        worktree = runtime_root / "runs" / "build-1" / "worktrees" / "iter-0"
        spec_dir = workspace / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        worktree.mkdir(parents=True)
        gitops.base_dir = runtime_root
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["target_repo"] = "prosaic"
        state["target_path"] = str(workspace / "sources" / "prosaic")
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)
        controller._fulfillment_runner = MagicMock()
        controller._fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="cached",
            exit_code=0,
            used_cache=True,
        )
        controller._prepare_delivery_context(str(worktree))

        result = controller._refresh_fulfillment_report(
            VerifyResult(
                passed=True,
                failures=[],
                verification_evidence={
                    "path": "/tmp/receipt.json",
                    "passed": True,
                },
            ),
            str(worktree),
        )

        assert result.passed is True
        controller._fulfillment_runner.refresh.assert_called_once()
        args = controller._fulfillment_runner.refresh.call_args
        assert args.args == (str(worktree), "spec-001")
        assert args.kwargs["spec_dir"] == spec_dir
        assert args.kwargs["orchestration_root"] == workspace
        assert args.kwargs["verification_evidence"] == {
            "path": "/tmp/receipt.json",
            "passed": True,
        }




    def test_multi_target_slice_accepts_scoped_fulfillment_at_target_boundary(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "workspace" / "sources" / "api"
        spec_dir = tmp_path / "workspace" / "specs" / "001-dashboard"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\nverify_scope: scoped\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/api.ts | high | ok |\n",
            encoding="utf-8",
        )
        state = state_store.read()
        state["spec_dir"] = str(spec_dir)
        state["build"] = {
            "total_tasks": 1,
            "completed_tasks": 1,
            "tasks_completed_pct": 100,
        }
        state_store.write(state)
        monkeypatch.setenv("ECHELON_TARGET_TASK_IDS", "T-001")

        decision = controller._fulfillment_refresh_decision(str(worktree))
        result = controller._apply_fulfillment_gate(
            VerifyResult(passed=True, failures=[], duration_s=0),
            str(worktree),
        )

        assert decision["action"] == "scoped"
        assert result.passed is True

    def test_single_target_completion_uses_full_fulfillment_refresh(
        self, tmp_path: Path
    ) -> None:
        """A one-target delivery at 100% progress must bootstrap full evidence."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "workspace" / "sources" / "prosaic"
        spec_dir = tmp_path / "workspace" / "specs" / "001-dashboard"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        state = state_store.read()
        state["implementation_target"] = "sources/prosaic"
        state["declared_targets"] = ["sources/prosaic"]
        state["target_task_ids"] = ["T-001", "T-002"]
        state["spec_dir"] = str(spec_dir)
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 2,
            "tasks_completed_pct": 100,
        }
        state_store.write(state)

        decision = controller._fulfillment_refresh_decision(str(worktree))

        assert decision["action"] == "full"
        assert decision["reason"] == "single target convergence boundary reached"

    def test_resumed_single_target_uses_canonical_tasks_for_full_refresh(
        self, tmp_path: Path
    ) -> None:
        """Resume must not lose convergence when transient build counters are absent."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "workspace" / "sources" / "game"
        spec_dir = tmp_path / "workspace" / "specs" / "001-game"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
            "- [x] T-002 complexity=standard phase=build req=FR-002 depends=T-001\n",
            encoding="utf-8",
        )
        state = state_store.read()
        state["implementation_target"] = "sources/game"
        state["declared_targets"] = ["sources/game"]
        state["target_task_ids"] = ["T-001", "T-002"]
        state["spec_dir"] = str(spec_dir)
        state.pop("build", None)
        state_store.write(state)

        decision = controller._fulfillment_refresh_decision(str(worktree))

        assert decision["action"] == "full"
        assert decision["reason"] == "single target convergence boundary reached"

    def test_convergence_only_fulfillment_policy_skips_failed_slice_refresh(
        self, tmp_path: Path
    ) -> None:
        """Incomplete task slices should not pay for full verify-spec refresh."""
        controller, _provider, _gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": True, "failures": []},
            ],
            fulfillment_runner=MagicMock(),
        )
        controller._config.fulfillment.refresh_policy = "convergence_only"
        state = _state_store.read()
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 1,
            "tasks_completed_pct": 50,
        }
        _state_store.write(state)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "blocked"
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-refresh-deferred"
        controller._fulfillment_runner.refresh.assert_not_called()





    def test_publish_failure_blocks_and_preserves_worktree(self, tmp_path: Path) -> None:
        """Verified work must not be reported converged when commit/push fails."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.push.side_effect = Exception("network error")

        with patch.object(controller, "_current_head", return_value="verified-head"), \
             patch(
                 "harness.ralph._safe_product_evidence_fingerprint",
                 return_value="product-fingerprint",
             ):
            result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "blocked"
        assert result.termination_reason == "publish_failed"
        assert result.branch == "harness/spec-001/build-1/iter-0"
        gitops.promote_pr_ready.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

        state = state_store.read()
        assert state["status"] == "running"
        assert state["termination_reason"] == "publish_failed"
        assert state["branch"] == "harness/spec-001/build-1/iter-0"
        assert state["verified_publish_checkpoint"]["stage"] == "push"
        assert state["verified_publish_checkpoint"]["commit"] == "verified-head"
        assert state["publication_failure"] == {
            "stage": "push",
            "error": "Push failed: network error",
            "branch": "harness/spec-001/build-1/iter-0",
            "worktree_path": state["verified_publish_checkpoint"]["worktree_path"],
        }

    def test_verified_publish_resume_retries_effects_without_provider_build(
        self, tmp_path: Path
    ) -> None:
        controller, provider, gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        state = state_store.read()
        state.update(
            {
                "termination_reason": "publish_failed",
                "last_verify_result": {
                    "passed": True,
                    "failures": [],
                    "duration_s": 1.0,
                    "token_usage": 0,
                },
                "verified_publish_checkpoint": {
                    "schema_version": 1,
                    "stage": "push",
                    "worktree_path": str(worktree),
                    "branch": "harness/spec-001/build-1/iter-0",
                    "commit": "verified-head",
                    "product_evidence_fingerprint": "product-fingerprint",
                },
                "publication_failure": {
                    "stage": "push",
                    "error": "old network failure",
                },
            }
        )
        state_store.write(state)

        with patch.object(controller, "_current_head", return_value="verified-head"), \
             patch(
                 "harness.ralph._safe_product_evidence_fingerprint",
                 return_value="product-fingerprint",
             ):
            result = controller.resume_verified_publication()

        assert result is not None
        assert result.status == "verified"
        assert result.termination_reason == "converged"
        gitops.push.assert_called_once_with(
            str(worktree), "harness/spec-001/build-1/iter-0"
        )
        gitops.local_merge.assert_called_once()
        assert provider._exec_count == 0
        recovered_state = state_store.read()
        assert "verified_publish_checkpoint" not in recovered_state
        assert "publication_failure" not in recovered_state
        assert recovered_state["verified_publish_recovery"]["status"] == "completed"






































































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

        with patch.object(
            controller, "_has_non_verify_worktree_changes", return_value=True
        ):
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

    def test_checkpoint_commit_preserves_dirty_finalization_without_task_progress(
        self, tmp_path: Path
    ) -> None:
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.commit.return_value = "feedface"
        unchanged = {"build": {"completed_tasks": 24, "task_results": {}}}

        with patch.object(
            controller, "_has_non_verify_worktree_changes", return_value=True
        ):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state=unchanged,
                after_state=unchanged,
                outer_iter=2,
                inner_iter=1,
                phase="fix",
                allow_without_task_progress=True,
            )

        assert checkpoint is not None
        message = gitops.commit.call_args.args[1]
        assert "fix tasks-unknown" in message
        state = state_store.read()
        assert state["checkpoint_commits"][0]["task_ids"] == []
        assert state["checkpoint_commits"][0]["completed_tasks_before"] == 24
        assert state["checkpoint_commits"][0]["completed_tasks_after"] == 24
        gitops.push.assert_called_once_with(
            "/tmp/worktree",
            "harness/spec-001/build-1/iter-2",
        )

    def test_checkpoint_commit_skips_dirty_attempt_without_task_progress_by_default(
        self, tmp_path: Path
    ) -> None:
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        unchanged = {"build": {"completed_tasks": 24, "task_results": {}}}

        with patch.object(
            controller, "_has_non_verify_worktree_changes", return_value=True
        ):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state=unchanged,
                after_state=unchanged,
                outer_iter=2,
                inner_iter=1,
                phase="fix",
            )

        assert checkpoint is None
        gitops.commit.assert_not_called()
        gitops.push.assert_not_called()
        assert "checkpoint_commits" not in state_store.read()

    def test_checkpoint_commit_skips_when_no_file_changes(self, tmp_path: Path) -> None:
        """Progress metadata alone does not create empty checkpoint commits."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )

        with patch.object(
            controller, "_has_non_verify_worktree_changes", return_value=False
        ):
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

    def test_checkpoint_commit_skips_verify_owned_artifacts_only(
        self, tmp_path: Path
    ) -> None:
        """Playwright output alone must not create an empty tasks-unknown commit."""
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
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
        results = worktree / "test-results"
        results.mkdir()
        (results / ".last-run.json").write_text("{}\n", encoding="utf-8")

        checkpoint = controller._checkpoint_progress_commit(
            worktree_path=str(worktree),
            before_state={"build": {"completed_tasks": 12}},
            after_state={"build": {"completed_tasks": 12}},
            outer_iter=0,
            inner_iter=1,
            phase="fix",
            allow_without_task_progress=True,
        )

        assert checkpoint is None
        gitops.commit.assert_not_called()
        gitops.push.assert_not_called()
        assert "checkpoint_commits" not in state_store.read()

    def test_commit_and_push_skips_empty_commit_for_verify_artifacts(
        self, tmp_path: Path
    ) -> None:
        """Final publication pushes HEAD without manufacturing an empty commit."""
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
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
        results = worktree / "test-results"
        results.mkdir()
        (results / ".last-run.json").write_text("{}\n", encoding="utf-8")

        branch = controller._commit_and_push(str(worktree), 0)

        assert branch == "main"
        gitops.commit.assert_not_called()
        gitops.push.assert_called_once_with(str(worktree), "main")





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

        assert result.status == "verified"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestOuterLoopCap:
    """Test outer loop hits cap."""

    def test_open_tasks_block_without_misreporting_publication_failure(
        self, tmp_path: Path
    ) -> None:
        """Open canonical tasks are not a failed checkpoint publication."""
        controller, _provider, gitops, _state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        _commit_all(worktree)
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = worktree
        task_gap = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "task-progress-incomplete",
                    "canonical delivery tasks remain open: T-014, T-015.",
                )
            ],
        )

        with patch.object(controller, "_exec_verify", return_value=task_gap):
            result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "blocked"
        assert result.termination_reason == "task_progress_incomplete"
        gitops.commit.assert_not_called()
        gitops.push.assert_not_called()

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

        assert result.status == "blocked"
        assert result.termination_reason == "outer_cap"
        assert result.outer_iterations == 2
        assert gitops.destroy_worktree.call_count == 2


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

        state = state_store.read()
        state["cancel_requested"] = True
        state_store.write(state)

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
class TestPromptHelpers:

    def test_provider_attempt_summary_is_compact_and_persisted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        summary = controller._record_provider_attempt_summary(
            phase="fix",
            attempt=2,
            result={
                "provider_invocation": {"provider": "codex"},
                "stdout": "Adjusted the HUD stacking order and reran the focused test.",
            },
            verify_result=VerifyResult(
                passed=False,
                failures=[FailureEntry(FailureCategory.TEST, "e2e", "canvas intercepts click")],
            ),
            changed_files=["apps/web/src/styles.css", "test-results/trace.zip"],
        )

        assert summary == {
            "provider": "codex",
            "phase": "fix",
            "attempt": 2,
            "outcome": "verification failed",
            "changed_files": ["apps/web/src/styles.css"],
            "provider_note": "Adjusted the HUD stacking order and reran the focused test.",
            "primary_failure": "canvas intercepts click",
        }
        output = capsys.readouterr().err
        assert "CODEX REPAIR 2" in output
        assert "test-results/trace.zip" not in output
        assert controller._state_store.read()["provider_attempts"] == [summary]

    def test_provider_attempt_summary_extracts_named_multiline_failure(
        self, tmp_path: Path
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        summary = controller._record_provider_attempt_summary(
            phase="build",
            attempt=1,
            result={
                "provider_invocation": {"provider": "codex"},
                "stdout": "Implemented the migration.",
            },
            verify_result=VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    FailureCategory.TEST,
                    "verify-command",
                    (
                        "lots of passing output\n"
                        " × checked-in PostgreSQL migrations > rejects a schema-version mismatch\n"
                        "AssertionError: expected rollback error\n"
                    ),
                )],
            ),
            changed_files=["migrations/002.ts"],
        )

        assert summary["primary_failure"] == (
            "verify-command: checked-in PostgreSQL migrations > "
            "rejects a schema-version mismatch"
        )

    def test_provider_attempt_summary_extracts_playwright_failure_marker(
        self, tmp_path: Path
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        summary = controller._record_provider_attempt_summary(
            phase="fix",
            attempt=1,
            result={"provider_invocation": {"provider": "codex"}, "stdout": ""},
            verify_result=VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    FailureCategory.TEST,
                    "verify-command",
                    (
                        "28 tests passed\n"
                        "  ✘   5 [chromium] › tests/e2e/concurrent-sessions.spec.ts:4:1 "
                        "› two sessions converge\n"
                        "attachment #1: screenshot\n"
                    ),
                )],
            ),
            changed_files=[],
        )

        assert summary["primary_failure"] == (
            "verify-command: 5 [chromium] › "
            "tests/e2e/concurrent-sessions.spec.ts:4:1 › two sessions converge"
        )

    def test_provider_attempt_summary_extracts_playwright_tail_summary(
        self, tmp_path: Path
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        summary = controller._record_provider_attempt_summary(
            phase="fix",
            attempt=1,
            result={"provider_invocation": {"provider": "codex"}, "stdout": ""},
            verify_result=VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    FailureCategory.TEST,
                    "verify-command",
                    (
                        "r that at /workspace/tests/e2e/concurrent-sessions.spec.ts:37:16\n"
                        "attachment #1: screenshot\n"
                        "  1 failed\n"
                        "    [chromium] › tests/e2e/concurrent-sessions.spec.ts:4:1 "
                        "› two sessions converge\n"
                    ),
                )],
            ),
            changed_files=[],
        )

        assert summary["primary_failure"] == (
            "verify-command: [chromium] › "
            "tests/e2e/concurrent-sessions.spec.ts:4:1 › two sessions converge"
        )

    def test_provider_attempt_summary_surfaces_evidence_integrity_counts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Provider summaries identify skipped journeys and concrete coverage debt."""
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        summary = controller._record_provider_attempt_summary(
            phase="fix",
            attempt=1,
            result={
                "provider_invocation": {"provider": "codex"},
                "stdout": "Added the persistence journey.",
            },
            verify_result=VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-gaps",
                    "Required coverage is not automated.",
                    details={
                        "gaps": [
                            {"requirement_id": "FR-013", "status": "UNVERIFIED"}
                        ]
                    },
                )],
                verification_evidence={
                    "playwright": {"total": 1, "passed": 0, "failed": 0, "skipped": 1}
                },
            ),
            changed_files=["tests/journey.spec.ts"],
        )

        assert summary is not None
        assert summary["playwright"] == {
            "total": 1,
            "passed": 0,
            "failed": 0,
            "skipped": 1,
        }
        assert summary["evidence_gaps"] == ["FR-013 [UNVERIFIED]"]
        output = capsys.readouterr().err
        assert "1 total, 0 passed, 0 failed, 1 skipped" in output
        assert "FR-013 [UNVERIFIED]" in output

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

    def test_second_feedback_prompt_requires_diagnostic_before_another_edit(
        self, tmp_path: Path
    ) -> None:
        """Repeated UI failures must not invite another speculative repair."""
        from harness.verify_result import FailureEntry, FailureCategory, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.TEST,
                    id="verify-command",
                    error="canvas subtree intercepts pointer events",
                )
            ],
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=2)

        assert "diagnose before editing" in result
        assert "focused failing check" in result
        assert "hit target" in result

    def test_feedback_prompt_reserves_browser_execution_for_ralph(
        self, tmp_path: Path
    ) -> None:
        """A coding CLI must not launch Chromium during a browser repair."""
        from harness.verify_result import FailureEntry, FailureCategory, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.TEST,
                    id="verify-command",
                    error="Playwright concurrent-session journey failed",
                )
            ],
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=2)

        assert "Do not launch Chromium" in result
        assert "Do not run Playwright" in result
        assert "configured authoritative verifier" in result
        assert "focused non-browser checks" in result


    def test_feedback_prompt_names_exact_coverage_case_repair_debt(
        self, tmp_path: Path
    ) -> None:
        """Repairs receive source-bound coverage debt, not an opaque aggregate."""
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="coverage-observation-gaps",
                    error="Required coverage observations did not pass.",
                    details={
                        "test_cases": {
                            "E2E-SCENE-001": {
                                "test_type": "e2e",
                                "status": "invalid_report",
                                "reason": "test reporter basename did not identify a tagged source file",
                            },
                            "UT-SCENE-002": {
                                "test_type": "unit",
                                "status": "duplicate_binding",
                                "reason": "case tag maps to more than one physical test identity",
                            },
                        }
                    },
                )
            ],
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)

        assert "## Coverage Observation Repair Contract" in result
        assert "`[echelon:E2E-SCENE-001]` (e2e)" in result
        assert "invalid_report: test reporter basename" in result
        assert "`[echelon:UT-SCENE-002]` (unit)" in result
        assert "exactly one physical test identity" in result
        assert "Do not edit the coverage map" in result

    def test_verify_owned_artifact_includes_playwright_results(self) -> None:
        from harness.ralph import _is_verify_owned_artifact

        assert _is_verify_owned_artifact(
            "test-results/failure-reconciliation/trace.zip"
        )

    def test_make_feedback_prompt_carries_exact_documentation_schema_repair(
        self, tmp_path: Path
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="documentation-not-applicable-without-reason",
                    error=(
                        "documentation-impact-report.md must set a non-empty "
                        "`not_applicable_reason`; narrative prose or `reason` does "
                        "not satisfy the schema"
                    ),
                )
            ],
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)

        assert "`not_applicable_reason`" in result
        assert "`reason`" in result
        assert "does not satisfy the schema" in result

    def test_make_feedback_prompt_overrides_manual_verify_spec_repair(
        self, tmp_path: Path
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-report-stale",
                    error=(
                        "fulfillment report is stale for current HEAD abc123: "
                        "/tmp/specs/001/fulfillment-report.md was verified at old456. "
                        "Run `echelon spec verify spec-001` before convergence."
                    ),
                )
            ],
            duration_s=1.0,
            token_usage=0,
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)

        assert "Do not run `echelon spec verify`" in result
        assert "Ralph owns fulfillment refresh" in result
        assert "Run `echelon spec verify spec-001` before convergence." in result

    @pytest.mark.parametrize(
        "failure_id",
        ["fulfillment-report-stale", "fulfillment-report-scoped"],
    )
    def test_inner_loop_does_not_dispatch_llm_for_fulfillment_freshness_failure(
        self, tmp_path: Path, failure_id: str
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        controller._exec_feedback = MagicMock()
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id=failure_id,
                    error=f"{failure_id} is Ralph-owned fulfillment evidence",
                )
            ],
            duration_s=1.0,
            token_usage=0,
        )

        result = controller._run_inner_loop(
            handle=SandboxHandle(id="mock-sandbox-1", session_id="sess-1"),
            verify_result=verify,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state={},
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            build_prompt="spec 001",
        )

        controller._exec_feedback.assert_not_called()
        assert result["inner_count"] == 0
        assert result["final_verify"] is verify


@pytest.mark.unit
class TestSignalDuringBuild:
    """SIGINT during build must set interrupted status without running verify."""



@pytest.mark.unit
class TestVerifyLocallyNode:
    """Node verification must never wait for an interactive package-manager prompt."""

    def test_pnpm_verification_runs_noninteractively(self, tmp_path: Path) -> None:
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "package.json").write_text("{}\n", encoding="utf-8")
        (worktree / "pnpm-lock.yaml").write_text(
            "lockfileVersion: '9.0'\n",
            encoding="utf-8",
        )

        with patch("subprocess.run") as mock_run, patch(
            "harness.ralph._safe_product_evidence_fingerprint",
            return_value="b" * 64,
        ), patch(
            "harness.ralph._current_git_commit", return_value="a" * 40
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert len(mock_run.call_args_list) == 3
        for call in mock_run.call_args_list:
            assert call.kwargs["stdin"] is subprocess.DEVNULL
            assert call.kwargs["env"]["CI"] == "true"

    def test_pnpm_verify_script_is_authoritative_and_receipted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller, _, gitops, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {
                        "test": "exit 9",
                        "verify": "lint-and-browser-journey",
                    }
                }
            ),
            encoding="utf-8",
        )
        (worktree / "pnpm-lock.yaml").write_text(
            "lockfileVersion: '9.0'\n", encoding="utf-8"
        )
        _commit_all(worktree)
        gitops.base_dir = worktree
        command_log = tmp_path / "pnpm-commands.txt"
        executable_dir = tmp_path / "bin"
        executable_dir.mkdir()
        pnpm = executable_dir / "pnpm"
        pnpm.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {command_log}\n",
            encoding="utf-8",
        )
        pnpm.chmod(0o755)
        monkeypatch.setenv(
            "PATH", f"{executable_dir}{os.pathsep}{os.environ['PATH']}"
        )

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert result.verification_evidence["passed"] is True
        commands = command_log.read_text(encoding="utf-8").splitlines()
        assert commands == [
            "install --frozen-lockfile --ignore-scripts",
            "verify",
        ]


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



@pytest.mark.unit
class TestVerifyCommandNeeded:
    """local-verify-skipped escalates to blocked, not silent failure."""

    def test_verify_command_runs_from_worktree_not_workspace_root(
        self, tmp_path: Path
    ) -> None:
        """Configured verification must exercise the candidate worktree."""
        controller, _, gitops, _ = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "iter-0"
        workspace.mkdir()
        script = worktree / "scripts" / "verify-cwd.sh"
        script.parent.mkdir(parents=True)
        marker = tmp_path / "verify-cwd.txt"
        script.write_text(f"pwd > {marker}\n", encoding="utf-8")
        script.chmod(0o755)
        _init_git_repo(worktree)
        _commit_all(worktree)
        gitops.base_dir = workspace
        controller._config = HarnessConfig(
            **{
                **controller._config.__dict__,
                "verify_command": "bash scripts/verify-cwd.sh",
            }
        )

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert marker.read_text(encoding="utf-8").strip() == str(worktree)


    def test_configured_verify_writes_candidate_bound_receipt(
        self, tmp_path: Path
    ) -> None:
        controller, _, gitops, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "verify.py").write_text(
            "print('journey passed')\n", encoding="utf-8"
        )
        _commit_all(worktree)
        gitops.base_dir = worktree
        controller._config = HarnessConfig(
            **{
                **controller._config.__dict__,
                "verify_command": f"{sys.executable} verify.py",
            }
        )

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert result.verification_evidence["passed"] is True
        receipt = Path(str(result.verification_evidence["path"]))
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["candidate_commit"] == subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert payload["stages"][0]["stdout_tail"] == "journey passed\n"

    def test_verifier_mutation_fails_receipt(self, tmp_path: Path) -> None:
        controller, _, gitops, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "verify.py").write_text(
            "from pathlib import Path\n"
            "Path('generated.txt').write_text('changed')\n",
            encoding="utf-8",
        )
        _commit_all(worktree)
        gitops.base_dir = worktree
        controller._config = HarnessConfig(
            **{
                **controller._config.__dict__,
                "verify_command": f"{sys.executable} verify.py",
            }
        )

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "candidate-mutated-during-verification"
        payload = json.loads(
            Path(str(result.verification_evidence["path"])).read_text(
                encoding="utf-8"
            )
        )
        assert payload["failure_id"] == "candidate_mutated_during_verification"

    def test_detected_python_verify_writes_receipt(self, tmp_path: Path) -> None:
        controller, _, gitops, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        (worktree / "pyproject.toml").write_text(
            "[project]\nname = 'receipt-fixture'\nversion = '0.0.0'\n",
            encoding="utf-8",
        )
        (worktree / "test_demo.py").write_text(
            "def test_demo():\n    assert True\n", encoding="utf-8"
        )
        _commit_all(worktree)
        gitops.base_dir = worktree

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert result.verification_evidence["passed"] is True
        payload = json.loads(
            Path(str(result.verification_evidence["path"])).read_text(
                encoding="utf-8"
            )
        )
        assert payload["verifier_source"] == "detected"
        assert payload["stages"][0]["name"] == "pytest"







@pytest.mark.unit
class TestVerifyLocallySwift:
    """Swift project detection and verification."""

    @pytest.fixture(autouse=True)
    def _bind_candidate_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ralph, "_current_git_commit", lambda _path: "a" * 40
        )
        monkeypatch.setattr(
            ralph,
            "_safe_product_evidence_fingerprint",
            lambda _path: "b" * 64,
        )

    def test_root_package_swift_detected(self, tmp_path: Path) -> None:
        """Package.swift at worktree root → swift build + swift test."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value="/usr/bin/swift"), \
             patch("harness.ralph._current_git_commit", return_value="a" * 40), \
             patch("harness.ralph._safe_product_evidence_fingerprint", return_value="b" * 64):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert result.verification_evidence["passed"] is True
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
