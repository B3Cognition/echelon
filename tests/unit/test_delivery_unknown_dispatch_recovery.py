"""Exercise recovery through real Ralph and receipt boundaries."""
import json
import pytest
from harness.ai_cli_backend import CliRunResult
from harness.delivery_slice_journal import DeliverySliceJournal
from tests.unit.test_delivery_controller_integration import _controller, _reconstruct
from tests.unit.test_delivery_slice_recovery import ProcessLost
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _steps


def _lost(fixture, tmp_path, *, repair=False, known=False, step="implementer", external=False):
    if repair:
        tasks = fixture[1] / "tasks.md"
        tasks.write_text(tasks.read_text().replace(
            "  **Acceptance Criteria:**", "  **Test Tasks:**\n  - Implement `UT-GREETING-001`.\n  **Acceptance Criteria:**", 1,
        ))
    controller, store = _controller(fixture, tmp_path, ScriptedExecutor())
    root = str(fixture[0])
    if external:
        destination = tmp_path / "canonical" / fixture[1].name
        destination.parent.mkdir()
        fixture[1].rename(destination)
        state = store.read()
        state.update(target_repo="demo", target_task_ids=["T-001", "T-002"], spec_dir=str(destination))
        store.write(state)
    if repair:
        first = controller._exec_build(None, "echelon build", "", worktree_path=root, prompt="build")
        assert first["passed"]
        controller._apply_build_task_progress(worktree_path=root, task_ids=first["task_ids"])
    def lose(assignment, payload, worktree):
        if assignment["step"] == step:
            if known:
                return CliRunResult(1, "provider unavailable", "", token_usage=7)
            raise ProcessLost()
    controller._llm_provider = ScriptedExecutor(lose)
    def dispatch():
        if repair:
            from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
            failure = VerifyResult(False, [FailureEntry(FailureCategory.TEST, "UT-GREETING-001", "wrong greeting")])
            return controller._exec_feedback(None, failure, "echelon build", "", worktree_path=root, prompt="build")
        return _build(controller, fixture)
    if known:
        assert dispatch()["build_reason"] == "delivery_provider_failed"
    else:
        with pytest.raises(ProcessLost):
            dispatch()
    journal = DeliverySliceJournal(controller._delivery_operation_evidence_root(), store.read()["delivery_slice_operation"]["id"])
    return controller, store, journal


def _build(controller, fixture):
    return controller._exec_build(None, "echelon build", "", worktree_path=str(fixture[0]), prompt="build")


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("external", [False, True])
def test_unknown_recovery_retains_candidate_and_reruns_all_gates(slice_project, tmp_path, repair, external):
    controller, store, journal = _lost(slice_project, tmp_path, repair=repair, external=external)
    original = store.read()
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._reconcile_unknown_dispatch = True
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    state = store.read()
    op = state["delivery_slice_operation"]
    assert op["id"] != original["delivery_slice_operation"]["id"]
    for key in ("worktree_path", "repair_task_id", "feedback", "outer_iter"):
        assert op[key] == original["delivery_slice_operation"][key]
    assert state["tokens_used"] == original["tokens_used"] + 28
    assert state["provider_token_usage_unknown_count"] == 1
    with journal:
        sealed = journal.load(required=True)
    assert sealed["records"][0]["result"] is None
    assert sealed["records"][0]["token_usage"] is None
    assert sealed["records"][0]["error"] == "delivery_dispatch_outcome_unknown_superseded:" + op["id"]
    executor.calls.clear()
    replay = _build(_reconstruct(controller, store, executor), slice_project)
    assert replay["passed"] and replay["tokens"] == 0
    assert not executor.calls
    assert store.read()["provider_token_usage_unknown_count"] == 1


def test_known_provider_failure_continue_retries_and_keeps_usage(slice_project, tmp_path):
    controller, store, journal = _lost(slice_project, tmp_path, known=True)
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert store.read()["tokens_used"] == 35
    assert not store.read().get("provider_token_usage_unknown_count")
    with journal:
        assert journal.load(required=True)["records"][0]["token_usage"] == 7


def test_recovery_returns_predecessor_usage_not_accounted_before_crash(slice_project, tmp_path, monkeypatch):
    executor = ScriptedExecutor(lambda *args: CliRunResult(1, "failed", "", token_usage=7))
    controller, store = _controller(slice_project, tmp_path, executor)
    save = DeliverySliceJournal.save
    def crash_after_failure_receipt(self, data):
        save(self, data)
        if data["records"] and data["records"][-1]["error"] == "delivery_provider_failed":
            raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", crash_after_failure_receipt)
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    assert store.read()["tokens_used"] == 0
    resumed = _reconstruct(controller, store, ScriptedExecutor())
    resumed._retry_failed_dispatch = True
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert result["tokens"] == 35  # Ralph's outer loop consumes this delta.
    assert store.read()["tokens_used"] == 35


def test_recovery_does_not_reset_saved_slice_budget(slice_project, tmp_path):
    controller, store, journal = _lost(slice_project, tmp_path, known=True)
    with journal:
        data = journal.load(required=True)
        data["budget_limit"] = 20
        journal.save(data)
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    result = _build(resumed, slice_project)
    assert not result["passed"]
    assert result["build_reason"] == "delivery_slice_budget_exhausted"
    assert _steps(executor) == ["implementer", "spec_guard"]
    assert store.read()["tokens_used"] == 21


@pytest.mark.parametrize("damage", ["binding", "protected", "missing", "reviewer_candidate"])
def test_recovery_cannot_bypass_binding_or_restart_consumed_reviews(slice_project, tmp_path, damage):
    controller, store, journal = _lost(slice_project, tmp_path, step="spec_guard" if damage == "reviewer_candidate" else "implementer")
    if damage == "binding":
        state = store.read()
        state["delivery_slice_operation"]["feedback"] = "changed assignment"
        store.write(state)
    elif damage == "protected":
        (slice_project[1] / "spec.md").write_text("changed spec")
    elif damage == "missing":
        journal.path.unlink()
    elif damage == "reviewer_candidate":
        (slice_project[0] / "app.py").write_text("unreviewed replacement")
    before = store.read()["delivery_slice_operation"]["id"]
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._reconcile_unknown_dispatch = True
    assert not _build(resumed, slice_project)["passed"]
    assert not executor.calls
    assert store.read()["delivery_slice_operation"]["id"] == before


def _crash_handover(controller, store, fixture, journal, monkeypatch, boundary):
    old_id = store.read()["delivery_slice_operation"]["id"]
    save, write = DeliverySliceJournal.save, store.write
    def save_and_crash(self, data):
        save(self, data)
        if boundary == "successor" and self.path != journal.path:
            raise ProcessLost()
        if boundary == "seal" and data["records"] and data["records"][0]["error"]:
            raise ProcessLost()
    def write_and_crash(state):
        write(state)
        if state.get("delivery_slice_operation", {}).get("id") != old_id:
            raise ProcessLost()
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._reconcile_unknown_dispatch = True
    with monkeypatch.context() as patch:
        if boundary == "state":
            patch.setattr(resumed._state_store, "write", write_and_crash)
        else:
            patch.setattr(DeliverySliceJournal, "save", save_and_crash)
        with pytest.raises(ProcessLost):
            _build(resumed, fixture)
    assert not executor.calls


@pytest.mark.parametrize("boundary", ["successor", "seal", "state"])
def test_handover_is_idempotent_across_process_loss(slice_project, tmp_path, monkeypatch, boundary):
    controller, store, journal = _lost(slice_project, tmp_path)
    _crash_handover(controller, store, slice_project, journal, monkeypatch, boundary)
    resumed = _reconstruct(controller, store, ScriptedExecutor())
    resumed._reconcile_unknown_dispatch = boundary != "state"
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert store.read()["provider_token_usage_unknown_count"] == 1
    assert store.read()["tokens_used"] == 28


@pytest.mark.parametrize("damage", ["parent_missing", "parent_changed", "successor_missing"])
def test_recovery_requires_immutable_parent_and_successor(slice_project, tmp_path, monkeypatch, damage):
    controller, store, journal = _lost(slice_project, tmp_path)
    _crash_handover(controller, store, slice_project, journal, monkeypatch, "state")
    if damage == "parent_missing":
        journal.path.unlink()
    elif damage == "parent_changed":
        data = json.loads(journal.path.read_text())
        data["budget_limit"] = 12345
        journal.path.write_text(json.dumps(data))
    else:
        successor = DeliverySliceJournal(controller._delivery_operation_evidence_root(), store.read()["delivery_slice_operation"]["id"])
        successor.path.unlink()
    executor = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, executor), slice_project)
    assert not result["passed"]
    assert not executor.calls
