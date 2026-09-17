"""Reconstruct real controllers across interrupted durable/external boundaries."""
import json
from pathlib import Path

import pytest

from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _run, _steps


class ProcessLost(BaseException):
    pass


def _crash_after_receipt(monkeypatch, count):
    from harness.delivery_slice_journal import DeliverySliceJournal
    original = DeliverySliceJournal.save

    def save(self, data):
        original(self, data)
        if len(data["records"]) == count and data["records"][-1]["result"] is not None:
            raise ProcessLost()

    monkeypatch.setattr(DeliverySliceJournal, "save", save)


@pytest.mark.parametrize("completed,remaining", [
    (1, ["spec_guard", "code_reviewer", "test_guardian"]),
    (2, ["code_reviewer", "test_guardian"]),
    (3, ["test_guardian"]), (4, []),
])
def test_resume_after_validated_completion(slice_project, monkeypatch, completed, remaining):
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, completed)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor())
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed)
    assert result.succeeded, result.reason
    assert _steps(resumed) == remaining
    assert result.token_usage == 28


@pytest.mark.parametrize("when", ["intent_saved", "provider_returned"])
def test_unknown_completion_never_reexecutes_or_accepts(slice_project, monkeypatch, when):
    from harness.delivery_slice_journal import DeliverySliceJournal
    original = DeliverySliceJournal.save

    def crash(self, data):
        if when == "provider_returned" and data["records"] and data["records"][-1]["result"] is not None:
            raise ProcessLost()
        original(self, data)
        if when == "intent_saved" and data["records"]:
            raise ProcessLost()

    first = ScriptedExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", crash)
        with pytest.raises(ProcessLost):
            _run(slice_project, first)
    assert len(first.calls) == (0 if when == "intent_saved" else 1)
    # Even an apparently successful diagnostic response cannot fill the gap.
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed)
    assert not result.succeeded and result.task_ids == []
    assert "reconciliation_required" in result.reason
    assert not resumed.calls


def test_crash_before_intent_write_is_safe_to_resume(slice_project, monkeypatch):
    from harness.delivery_slice_journal import DeliverySliceJournal
    original = DeliverySliceJournal.save

    def crash(self, data):
        if data["records"]:
            raise ProcessLost()
        original(self, data)

    first = ScriptedExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", crash)
        with pytest.raises(ProcessLost):
            _run(slice_project, first)
    assert not first.calls
    resumed = ScriptedExecutor()
    assert _run(slice_project, resumed).succeeded
    assert _steps(resumed) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]


@pytest.mark.parametrize("change", ["candidate", "spec", "criteria", "scope", "feedback", "role"])
def test_changed_binding_never_reuses_receipts(slice_project, monkeypatch, change):
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor())
    project, spec, _ = slice_project
    kwargs = {}
    if change == "candidate":
        (project / "app.py").write_text("def hello(): return 'changed'\n")
    elif change == "spec":
        (spec / "spec.md").write_text("# Different requirements\n")
    elif change == "criteria":
        path = spec / "tasks.md"
        path.write_text(path.read_text().replace("Return hello", "Return goodbye"))
    elif change == "scope":
        kwargs["allowed_task_ids"] = {"T-002"}
    elif change == "feedback":
        kwargs["feedback"] = "New unrelated request"
    else:
        path = project / ".echelon/prosaic/subagents/echelon.delivery-spec-guard.md"
        path.write_text(path.read_text() + "\nChanged contract.\n")
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, **kwargs)
    assert not result.succeeded and not resumed.calls


def test_exhausted_repairs_remain_exhausted_after_restart(slice_project):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong result"])
    first = ScriptedExecutor(reject)
    assert not _run(slice_project, first).succeeded
    assert _steps(first) == ["implementer", "spec_guard"] * 3
    second = ScriptedExecutor()
    result = _run(slice_project, second)
    assert not result.succeeded and "repair_limit" in result.reason
    assert not second.calls and result.token_usage == 42


def test_restart_after_rejection_preserves_repair_count_and_feedback(slice_project, monkeypatch):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong result"])
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 4)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(reject))
    resumed = ScriptedExecutor(reject)
    result = _run(slice_project, resumed)
    assert not result.succeeded and "repair_limit" in result.reason
    assert _steps(resumed) == ["implementer", "spec_guard"]
    assert "wrong result" in resumed.calls[0][2]


def test_saved_finite_budget_cannot_reset_on_restart(slice_project, monkeypatch):
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 1)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(), token_budget=14)
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, token_budget=1000)
    assert not result.succeeded and "budget_exhausted" in result.reason
    assert _steps(resumed) == ["spec_guard"] and result.token_usage == 14


@pytest.mark.parametrize("damage", ["json", "schema", "receipt", "symlink"])
def test_corrupt_or_unsafe_journal_never_becomes_fresh_work(slice_project, damage):
    assert _run(slice_project, ScriptedExecutor()).succeeded
    journals = list(slice_project[2].glob("*/journal.json"))
    assert len(journals) == 1
    path = journals[0]
    if damage == "json":
        path.write_text("{")
    elif damage == "symlink":
        other = path.with_name("other.json")
        path.rename(other)
        path.symlink_to(other)
    else:
        data = json.loads(path.read_text())
        if damage == "schema":
            data["schema_version"] = True
        else:
            data["records"][1]["result"]["verdict"] = "SKIP"
        path.write_text(json.dumps(data))
    resumed = ScriptedExecutor()
    assert not _run(slice_project, resumed).succeeded
    assert not resumed.calls


def test_concurrent_runner_cannot_dispatch_same_operation(slice_project):
    competing = ScriptedExecutor()
    observed = []
    def overlap(assignment, payload, root):
        if assignment["step"] == "implementer":
            observed.append(_run(slice_project, competing))
    assert _run(slice_project, ScriptedExecutor(overlap)).succeeded
    assert len(observed) == 1 and not observed[0].succeeded
    assert "locked" in observed[0].reason and not competing.calls


def test_expected_missing_journal_blocks_instead_of_resetting_budget(slice_project):
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, journal_required=True)
    assert not result.succeeded and not executor.calls


def test_tightened_budget_is_durable_across_another_resume(slice_project, monkeypatch):
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 1)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(), token_budget=100)
    assert not _run(slice_project, ScriptedExecutor(), token_budget=14).succeeded
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, token_budget=100)
    assert not result.succeeded and "budget_exhausted" in result.reason
    assert not resumed.calls


def test_provider_exception_preserves_unknown_usage_and_completion(slice_project):
    def lost(assignment, payload, root):
        raise RuntimeError("lost provider transport")
    result = _run(slice_project, ScriptedExecutor(lost))
    assert not result.succeeded and result.token_usage is None
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed)
    assert not result.succeeded and result.token_usage is None and not resumed.calls


def test_candidate_changed_during_receipt_replay_cannot_be_accepted(slice_project):
    assert _run(slice_project, ScriptedExecutor()).succeeded
    def check_cancel():
        (slice_project[0] / "app.py").write_text("def hello(): return 'stale approval'\n")
        return False
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, stop_requested=check_cancel)
    assert not result.succeeded and not resumed.calls
