"""Missing observer capability must not become product fulfillment debt."""
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.stacks.resolver import resolve_stacks
from harness.coverage_evidence import build_coverage_evidence
from harness.coverage_observer_runner import CoverageObserverRun, CoverageVerificationBundle
from harness.product_inventory import product_evidence_fingerprint
from harness.test_execution_evidence import ObservedTestExecution
from harness.verification_evidence import VerificationStage, write_verification_receipt
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from tests.unit.test_ralph_outer import _make_controller, _required_coverage_stacks


def _project(tmp_path: Path, selection: str):
    controller, provider, _, store = _make_controller(tmp_path)
    if selection == "empty":
        controller._config.resolved_stacks = resolve_stacks([], {})
    elif selection == "optional":
        stacks = _required_coverage_stacks()
        observer = stacks.coverage_observers[0]
        controller._config.resolved_stacks = replace(stacks, coverage_observers=[
            replace(observer, observer=replace(observer.observer, required=False))
        ])
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    spec = tmp_path / "specs" / "spec-001"
    spec.mkdir(parents=True)
    (spec / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | UT-TIME-001 | unit | deferred-automation | deferred-automation | planned | implement |\n"
    )
    state = store.read()
    state.update(spec_dir=str(spec), target_repo="target")
    store.write(state)
    return controller, provider, store, worktree, spec


@pytest.mark.parametrize("selection", ["unresolved", "empty", "optional"])
def test_missing_observer_stops_before_fulfillment_and_product_repair(tmp_path, selection):
    """Removing capability validation must expose the stale-plan audit regression."""
    controller, provider, store, worktree, _ = _project(tmp_path, selection)
    controller._fulfillment_runner = MagicMock()
    controller._exec_feedback = MagicMock()
    verified = VerifyResult(passed=True, verification_evidence={"retained": "receipt"})

    result = controller._apply_post_verify_gates(verified, str(worktree))

    assert not result.passed
    assert result.failures[0].id == "coverage-observer-unavailable"
    assert "unit" in result.failures[0].error
    assert result.verification_evidence == {"retained": "receipt"}
    assert not controller._fulfillment_runner.mock_calls
    outcome = controller._run_inner_loop(
        None, result, 0, 5, 17, 1000, store.read(), "echelon build", "",
        worktree_path=str(worktree),
    )
    assert outcome["blocked"]
    assert outcome["blocked_reason"] == "coverage_observer_unavailable"
    assert outcome["inner_count"] == 0
    assert outcome["tokens_used"] == 17
    assert outcome["final_verify"] is result
    controller._exec_feedback.assert_not_called()
    assert not provider.created


def test_observer_unavailable_after_repair_keeps_capability_blocker(tmp_path):
    """A capability failure after the final allowed repair is not exhaustion."""
    controller, _, store, worktree, _ = _project(tmp_path, "empty")
    missing = VerifyResult(False, [FailureEntry(
        FailureCategory.OTHER, "coverage-observer-unavailable", "unit observer missing"
    )])
    controller._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
    controller._apply_post_verify_gates = MagicMock(return_value=missing)
    initial = VerifyResult(False, [FailureEntry(FailureCategory.TEST, "UT-TIME-001", "failed")])

    outcome = controller._run_inner_loop(
        None, initial, 0, 1, 0, 1000, store.read(), "echelon build", "",
        worktree_path=str(worktree),
    )

    assert outcome["blocked"]
    assert outcome["blocked_reason"] == "coverage_observer_unavailable"
    assert outcome["final_verify"] is missing


def test_no_completed_coverage_obligations_does_not_require_observers(tmp_path):
    controller, _, _, worktree, spec = _project(tmp_path, "empty")
    result = controller._candidate_evidence_runner.apply_coverage(
        verify_result=VerifyResult(passed=True), worktree=worktree,
        spec_dir=spec, evidence_dir=tmp_path / "evidence", required_case_ids=set(),
    )
    assert result.verify_result.passed
    assert not result.observer_required


def test_no_coverage_contract_and_no_observers_remains_supported(tmp_path):
    controller, _, _, worktree, spec = _project(tmp_path, "empty")
    (spec / "coverage-map.md").unlink()
    result = controller._apply_coverage_observation_gate(VerifyResult(passed=True), str(worktree))
    assert result.passed


def test_outer_loop_retains_capability_reason_without_spending_repair_budget(tmp_path):
    controller, _, store, worktree, _ = _project(tmp_path, "empty")
    controller._gitops.create_worktree.return_value = str(worktree)
    controller._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
    controller._exec_feedback = MagicMock()

    result = controller.run_loop(max_outer=5, max_inner=5)

    assert result.status == "blocked"
    assert result.termination_reason == "coverage_observer_unavailable"
    assert result.inner_iterations == 0
    assert result.final_verify.failures[0].id == "coverage-observer-unavailable"
    assert store.read()["convergence_lease"]["meaningful_attempts"] == 0
    controller._exec_feedback.assert_not_called()


def test_configured_observation_discharges_deferred_plan_without_editing_it(tmp_path, monkeypatch):
    """The capability guard must preserve the existing receipt-to-coverage path."""
    controller, _, _, worktree, spec = _project(tmp_path, "empty")
    controller._config.resolved_stacks = _required_coverage_stacks()
    title = "elapsed time [echelon:UT-TIME-001]"
    (worktree / "timing.test.ts").write_text(f"it('{title}', () => {{}});\n")
    plan_before = (spec / "coverage-map.md").read_bytes()
    fingerprint = product_evidence_fingerprint(worktree)
    receipt = write_verification_receipt(
        evidence_dir=tmp_path / "verification", spec_id="spec-001", target_id="target",
        build_id="build-1", candidate_commit="a" * 40,
        fingerprint_before=fingerprint, fingerprint_after=fingerprint,
        verifier_source="sandbox", stages=(VerificationStage(
            name="verify", command=("npm", "test"), exit_code=0,
            duration_ms=1, stdout=b"passed", stderr=b"",
        ),), attempt_sequence=1, sensitive_environment={},
    )
    bundle = CoverageVerificationBundle(receipt, (CoverageObserverRun(
        observer_id="vitest-unit", receipt=receipt, status="passed",
        executions=(ObservedTestExecution(
            observer_id="vitest-unit", test_type="unit", file="timing.test.ts",
            title=title, project="", status="passed", retry_count=0,
        ),),
    ),))
    # Only external execution is replaced; receipt validation, source binding,
    # observation publication and fulfillment coverage classification remain real.
    monkeypatch.setattr("harness.candidate_evidence._current_git_commit", lambda _: "a" * 40)
    monkeypatch.setattr("harness.candidate_evidence.run_coverage_observers", lambda **_: bundle)

    gate = controller._candidate_evidence_runner.apply_coverage(
        verify_result=VerifyResult(passed=True, verification_evidence=receipt.as_mapping()),
        worktree=worktree, spec_dir=spec, evidence_dir=tmp_path / "observations",
    )

    assert gate.verify_result.passed
    assert gate.observer_required
    coverage = build_coverage_evidence(
        spec_dir=spec, canonical_ids=["FR-001"], deferred_ids=set(),
        observation=gate.observation, observer_required=True,
    )
    assert coverage.by_requirement["FR-001"].status == "observed"
    assert gate.observation.test_cases["UT-TIME-001"].status == "passed"
    assert (spec / "coverage-map.md").read_bytes() == plan_before
