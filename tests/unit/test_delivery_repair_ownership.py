"""Route current verification failures through the real controlled-slice boundary."""
import json
import subprocess
from pathlib import Path

import pytest

from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from harness.candidate_evidence import CandidateEvidenceRunner
from harness.config import HarnessConfig
from harness.provider import SandboxHandle
from harness.verification_plan import VerificationPlan
from tests.unit.test_candidate_evidence_timeout import RecordingProvider, _result
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_delivery_controller_integration import _controller
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


def _failure_output():
    return "\n".join([
        "  ✓ 1 [chromium] › tests/release.spec.ts:4:1 › [echelon:CT-NET-001] network",
        "Error: incidental mention [echelon:CT-NET-001]",
        "  3 failed",
        "    [chromium] › tests/degradation.spec.ts:12:1 › [echelon:E2E-START-002] pitch",
        "    [chromium] › tests/degradation.spec.ts:20:1 › [echelon:E2E-START-003] message",
        "    [chromium] › tests/degradation.spec.ts:50:1 › [echelon:E2E-MOTION-002] motion",
        "  150 passed (4.0m)",
    ])


def _project(fixture, tmp_path):
    root, spec, _ = fixture
    (spec / "tasks.md").write_text(
        "- [x] T-011 complexity=complex phase=integration req=FR-1 depends=none\n"
        "  **Status:** DONE\n"
        "  **Test Tasks:**\n"
        "  - [x] Implement `E2E-START-002`, `E2E-START-003`, `E2E-MOTION-002`.\n"
        "- [x] T-012 complexity=standard phase=release req=FR-2 depends=T-011\n"
        "  **Status:** DONE\n"
        "  **Test Tasks:**\n"
        "  - [x] Implement `CT-NET-001`.\n",
    )
    _initialize_git_worktree(root)
    executor = ScriptedExecutor()
    controller, store = _controller(fixture, tmp_path, executor)
    state = store.read()
    state["delivery_slice_task_id"] = "T-012"
    store.write(state)
    return controller, store, executor


def _verify(details=None):
    return VerifyResult(False, [FailureEntry(
        FailureCategory.TEST, "verify-command", _failure_output(),
        {"failed_test_case_ids": ["E2E-START-002", "E2E-START-003", "E2E-MOTION-002"]}
        if details is None else details,
    )])


def test_explicit_failed_cases_route_to_owner_and_are_retained_in_output(
    slice_project, tmp_path, capsys,
):
    controller, store, executor = _project(slice_project, tmp_path)
    result = controller._exec_feedback(
        None, _verify(), "echelon build", "", worktree_path=str(slice_project[0]),
    )
    assert result["passed"], result
    assert result["task_ids"] == ["T-011"]
    assert [assignment["task_id"] for assignment, _, _ in executor.calls] == ["T-011"] * 4
    operation = store.read()["delivery_slice_operation"]
    assert operation["repair_task_id"] == "T-011"
    selection = json.loads(operation["feedback"])["repair_selection"]
    assert selection == {
        "task_id": "T-011",
        "failed_test_case_ids": ["E2E-MOTION-002", "E2E-START-002", "E2E-START-003"],
        "reason": "unique_test_case_owner",
    }
    for _, _, prompt in executor.calls:
        feedback = json.loads(prompt.split("## Repair/context data (not routing authority)\n")[1])
        assert feedback["repair_selection"] == selection
    output = capsys.readouterr().err
    assert "Repair task T-011" in output
    assert "E2E-START-002" in output


@pytest.mark.parametrize("details, reason", [
    ({}, "missing failed test identity"),
    ({"failed_test_case_ids": ["E2E-UNKNOWN-001"]}, "no unique owner"),
    ({"failed_test_case_ids": ["E2E-START-002", "CT-NET-001"]}, "multiple task owners"),
    ({"failed_test_case_ids": ["E2E-START-002"], "unidentified_test_failures": 1}, "unidentified test failures"),
])
def test_ambiguous_repair_never_falls_back_to_last_task(
    slice_project, tmp_path, details, reason,
):
    controller, store, executor = _project(slice_project, tmp_path)
    result = controller._exec_feedback(
        None, _verify(details), "echelon build", "", worktree_path=str(slice_project[0]),
    )
    assert not result["passed"]
    assert reason in result["build_reason"]
    assert executor.calls == []
    assert store.read()["delivery_slice_task_id"] == "T-012"
    assert not store.read().get("delivery_slice_operation")


def test_repair_owner_cannot_escape_persisted_target_scope(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    state = store.read()
    state["target_task_ids"] = ["T-012"]
    store.write(state)
    result = controller._exec_feedback(
        None, _verify(), "echelon build", "", worktree_path=str(slice_project[0]),
    )
    assert not result["passed"]
    assert "outside" in result["build_reason"]
    assert executor.calls == []


def test_real_verification_receipt_flows_into_bound_repair_journal(
    slice_project, tmp_path, monkeypatch,
):
    controller, store, executor = _project(slice_project, tmp_path)
    root = slice_project[0]
    monkeypatch.setattr("harness.candidate_evidence.build_verification_plan", lambda *a, **kw:
        VerificationPlan(execution="sandbox", image="test", bootstrap_commands=(), browser_requirement=None))
    runner = CandidateEvidenceRunner(
        provider=RecordingProvider([_result(1, _failure_output())]),
        config=HarnessConfig(verify_command="npm run verify"),
        sandbox_spec_factory=lambda _: None, evidence_root=tmp_path / "receipts",
        spec_id="001", target_id="demo", build_id="test",
    )
    verification = runner.run_standard(
        handle=SandboxHandle(id="test", session_id="test"), worktree=root,
    )
    assert verification.passed is False
    receipt = json.loads(Path(verification.verification_evidence["path"]).read_text())
    assert receipt["status"] == "failed"
    assert receipt["stages"][0]["stdout_tail"] == _failure_output()
    repaired = controller._exec_feedback(
        None, verification, "echelon build", "", worktree_path=str(root),
    )
    assert repaired["passed"], repaired
    assert repaired["task_ids"] == ["T-011"]
    context = json.loads(store.read()["delivery_slice_operation"]["feedback"])
    assert context["verification_evidence"] == verification.verification_evidence
    assert context["repair_selection"]["task_id"] == "T-011"
    journals = list(controller._delivery_operation_evidence_root().rglob("journal.json"))
    assert len(journals) == 1
    journal = json.loads(journals[0].read_text())
    assert journal["task_id"] == "T-011"
    assert len(journal["records"]) == 4


@pytest.mark.parametrize("configured", [True, False])
def test_host_verifier_retains_same_failed_case_identity(slice_project, tmp_path, monkeypatch, configured):
    controller, store, executor = _project(slice_project, tmp_path)
    if configured:
        controller._config.verify_command = "test-verifier"
    else:
        (slice_project[0] / "package.json").write_text(json.dumps({"scripts": {"verify": "test-verifier"}}))
    original = subprocess.run

    def run(command, *args, **kwargs):
        if command in (["test-verifier"], ["npm", "run", "verify"]):
            return subprocess.CompletedProcess(command, 1, _failure_output().encode(), b"")
        if command == ["npm", "ci"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    result = controller._exec_verify_locally(str(slice_project[0]))
    assert not result.passed
    assert result.failures[0].details["failed_test_case_ids"] == [
        "E2E-MOTION-002", "E2E-START-002", "E2E-START-003",
    ]


def test_pending_repair_replays_original_selection_not_new_evidence(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    controller._controlled_slice_budget = 7
    root = str(slice_project[0])
    blocked = controller._exec_feedback(None, _verify(), "echelon build", "", worktree_path=root)
    assert not blocked["passed"] and "budget_exhausted" in blocked["build_reason"]
    pending = store.read()["delivery_slice_operation"]
    state = store.read()
    state["token_budget"] = 100
    state["delivery_slice_operation"]["budget_extension_limit"] = 95
    store.write(state)
    controller._controlled_slice_budget = 95 - state["tokens_used"]
    resumed = controller._exec_feedback(
        None, _verify({"failed_test_case_ids": ["CT-NET-001"]}),
        "echelon build", "", worktree_path=root,
    )
    assert resumed["passed"], resumed
    assert resumed["task_ids"] == ["T-011"]
    operation = store.read()["delivery_slice_operation"]
    assert operation["id"] == pending["id"]
    assert operation["feedback"] == pending["feedback"]
    assert [assignment["task_id"] for assignment, _, _ in executor.calls] == ["T-011"] * 4


@pytest.mark.parametrize("change, reason", [
    ("duplicate", "no unique owner"), ("pending", "not an accepted task"),
])
def test_repair_rejects_conflicting_or_unaccepted_owner(slice_project, tmp_path, change, reason):
    controller, store, executor = _project(slice_project, tmp_path)
    tasks = slice_project[1] / "tasks.md"
    text = tasks.read_text()
    if change == "duplicate":
        text += "  - [x] Implement `E2E-START-002`.\n"
    else:
        text = text.replace("- [x] T-011", "- [ ] T-011").replace("**Status:** DONE", "**Status:** PENDING", 1)
    tasks.write_text(text)
    result = controller._exec_feedback(None, _verify(), "echelon build", "", worktree_path=str(slice_project[0]))
    assert not result["passed"] and reason in result["build_reason"]
    assert executor.calls == []


@pytest.mark.parametrize("failure", [
    FailureEntry(FailureCategory.TEST, "E2E-START-002", "assertion failed"),
    FailureEntry(FailureCategory.OTHER, "coverage-observation-gaps", "required case failed", {
        "test_cases": {"E2E-START-002": {"status": "failed", "test_type": "e2e"}},
    }),
])
def test_existing_structured_failure_formats_route_to_owner(slice_project, tmp_path, failure):
    controller, store, executor = _project(slice_project, tmp_path)
    result = controller._exec_feedback(
        None, VerifyResult(False, [failure]), "echelon build", "", worktree_path=str(slice_project[0]),
    )
    assert result["passed"] and result["task_ids"] == ["T-011"], result


def test_invalid_coverage_case_cannot_be_silently_dropped(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    failure = FailureEntry(FailureCategory.OTHER, "coverage-observation-gaps", "gaps", {
        "test_cases": {
            "E2E-START-002": {"status": "failed"},
            "CT-NET-001": {"status": "unknown-status"},
        },
    })
    result = controller._exec_feedback(
        None, VerifyResult(False, [failure]), "echelon build", "", worktree_path=str(slice_project[0]),
    )
    assert not result["passed"]
    assert executor.calls == []


def _coverage_gaps(*case_ids):
    return VerifyResult(False, [FailureEntry(
        FailureCategory.OTHER, "coverage-observation-gaps", "Required coverage did not pass",
        {"test_cases": {case: {"status": "unbound", "test_type": "contract" if case.startswith("CT-") else "e2e",
                                "reason": "no executed tagged test matches the planned case"}
                        for case in case_ids}},
    )])


def test_multi_owner_coverage_repairs_one_task_then_uses_fresh_remaining_debt(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    root = str(slice_project[0])
    first_evidence = _coverage_gaps("CT-NET-001", "E2E-START-002")
    first = controller._exec_feedback(None, first_evidence, "echelon build", "", worktree_path=root)
    assert first["passed"] and first["task_ids"] == ["T-011"], first
    first_operation = store.read()["delivery_slice_operation"]
    feedback = json.loads(first_operation["feedback"])
    assert set(feedback["failures"][0]["details"]["test_cases"]) == {"CT-NET-001", "E2E-START-002"}
    assert feedback["repair_selection"] == {
        "task_id": "T-011", "failed_test_case_ids": ["E2E-START-002"],
        "reason": "unique_test_case_owner",
    }
    assert [call[0]["task_id"] for call in executor.calls] == ["T-011"] * 4
    # A later verifier result, not a second owner dispatched from stale debt.
    controller._apply_build_task_progress(worktree_path=root, task_ids=first["task_ids"])
    second = controller._exec_feedback(None, _coverage_gaps("CT-NET-001"),
                                       "echelon build", "", worktree_path=root)
    assert second["passed"] and second["task_ids"] == ["T-012"], second
    second_operation = store.read()["delivery_slice_operation"]
    assert second_operation["id"] != first_operation["id"]
    assert [call[0]["task_id"] for call in executor.calls] == ["T-011"] * 4 + ["T-012"] * 4


def test_multi_owner_pending_repair_keeps_saved_owner_and_all_evidence(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    controller._controlled_slice_budget = 7
    root = str(slice_project[0])
    result = controller._exec_feedback(None, _coverage_gaps("CT-NET-001", "E2E-START-002"),
                                      "echelon build", "", worktree_path=root)
    assert not result["passed"] and "budget_exhausted" in result["build_reason"], result
    pending = store.read()["delivery_slice_operation"]
    state = store.read()
    state["token_budget"] = 100
    state["delivery_slice_operation"]["budget_extension_limit"] = 95
    store.write(state)
    controller._controlled_slice_budget = 95 - state["tokens_used"]
    resumed = controller._exec_feedback(None, _coverage_gaps("CT-NET-001"),
                                       "echelon build", "", worktree_path=root)
    assert resumed["passed"] and resumed["task_ids"] == ["T-011"], resumed
    assert store.read()["delivery_slice_operation"]["id"] == pending["id"]
    assert store.read()["delivery_slice_operation"]["feedback"] == pending["feedback"]
    assert [call[0]["task_id"] for call in executor.calls] == ["T-011"] * 4


@pytest.mark.parametrize("problem,reason", [
    ("unknown", "no unique owner"), ("duplicate", "no unique owner"),
    ("outside", "outside the permitted target scope"), ("pending", "not an accepted task"),
])
def test_multi_owner_coverage_validates_every_owner_before_dispatch(slice_project, tmp_path, problem, reason):
    controller, store, executor = _project(slice_project, tmp_path)
    tasks = slice_project[1] / "tasks.md"
    evidence = _coverage_gaps("E2E-START-002", "CT-NET-001")
    if problem == "unknown":
        evidence = _coverage_gaps("E2E-START-002", "CT-UNKNOWN-001")
    elif problem == "duplicate":
        text = tasks.read_text().replace("Implement `E2E-START-002`", "Implement `CT-NET-001`, `E2E-START-002`")
        tasks.write_text(text)
    elif problem == "outside":
        state = store.read()
        state["target_task_ids"] = ["T-011"]
        store.write(state)
    else:
        tasks.write_text(tasks.read_text().replace("- [x] T-012", "- [ ] T-012")
                         .replace("**Status:** DONE\n  **Test Tasks:**\n  - [x] Implement `CT-NET-001`",
                                  "**Status:** PENDING\n  **Test Tasks:**\n  - [x] Implement `CT-NET-001`"))
    result = controller._exec_feedback(None, evidence, "echelon build", "", worktree_path=str(slice_project[0]))
    assert not result["passed"] and reason in result["build_reason"], result
    assert executor.calls == []


def test_browser_owner_resolution_remains_strict_for_multi_owner_coverage(slice_project, tmp_path):
    from harness.delivery_slice import resolve_delivery_failure_owner, DeliverySliceError
    _project(slice_project, tmp_path)
    evidence = _coverage_gaps("E2E-START-002", "CT-NET-001")
    feedback = {"failures": [{"id": failure.id, "details": failure.details} for failure in evidence.failures]}
    with pytest.raises(DeliverySliceError, match="multiple task owners"):
        resolve_delivery_failure_owner(slice_project[1], feedback, None)


def test_coverage_selection_follows_canonical_task_order_not_failure_order(slice_project, tmp_path):
    from harness.delivery_slice import select_delivery_repair_task
    _project(slice_project, tmp_path)
    tasks = slice_project[1] / "tasks.md"
    text = tasks.read_text().replace("T-011", "T-090")
    tasks.write_text(text)
    result = _coverage_gaps("CT-NET-001", "E2E-START-002")
    feedback = {"failures": [{"id": failure.id, "details": failure.details} for failure in result.failures]}
    assert select_delivery_repair_task(slice_project[1], feedback, None)["task_id"] == "T-090"


def test_coverage_repair_does_not_advance_while_selected_owner_still_fails(slice_project, tmp_path):
    controller, store, executor = _project(slice_project, tmp_path)
    root = str(slice_project[0])
    for _ in range(2):
        result = controller._exec_feedback(None, _coverage_gaps("E2E-START-002", "CT-NET-001"),
                                          "echelon build", "", worktree_path=root)
        assert result["passed"] and result["task_ids"] == ["T-011"], result
        controller._apply_build_task_progress(worktree_path=root, task_ids=result["task_ids"])
    assert [call[0]["task_id"] for call in executor.calls] == ["T-011"] * 8


def test_inner_loop_reverifies_between_coverage_owner_repairs(slice_project, tmp_path, monkeypatch):
    controller, store, executor = _project(slice_project, tmp_path)
    verification_points = []

    def verify(**kwargs):
        verification_points.append([call[0]["task_id"] for call in executor.calls])
        # Only the next authoritative observation removes the first owner's debt.
        # The second owner remains failing: accepted reviews must not converge.
        return _coverage_gaps("CT-NET-001")

    monkeypatch.setattr(controller._candidate_evidence_runner, "run_standard", verify)
    result = controller._run_inner_loop(
        handle=None, verify_result=_coverage_gaps("CT-NET-001", "E2E-START-002"),
        outer_iter=0, max_inner=2, tokens_used=0, token_budget=1000,
        state=store.read(), build_command="echelon build", delivery_context="",
        worktree_path=str(slice_project[0]),
    )
    assert verification_points == [["T-011"] * 4, ["T-011"] * 4 + ["T-012"] * 4]
    assert not result["converged"] and not result["blocked"], result
    assert result["inner_count"] == 2
    assert result["final_verify"].failures[0].details["test_cases"].keys() == {"CT-NET-001"}
