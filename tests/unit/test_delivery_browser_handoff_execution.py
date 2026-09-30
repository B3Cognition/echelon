"""Run real Ralph selection, journals, reviews and accounting across browser repair."""
import json
from pathlib import Path

import pytest

from harness.delivery_slice_journal import DeliverySliceJournal
from harness.product_inventory import product_evidence_fingerprint
from harness.visual_ralph import VisualRalphController
from tests.unit.test_browser_capture_failures import _capture
from tests.unit.test_delivery_browser_checkpoints import _passing_capture
from tests.unit.test_delivery_repair_ownership import _project, _verify
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


def _handoff_project(fixture, tmp_path, monkeypatch, *, recheck="pass"):
    controller, store, _ = _project(fixture, tmp_path)
    captures = []
    source_bytes = {}
    candidate_at_capture = None

    def script(assignment, payload, root):
        if len(executor.calls) == 1:
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need current screenshots",
                           browser_evidence_request={"purpose": "baseline_capture"})
        elif assignment["task_id"] == "T-011" and assignment["step"] == "implementer":
            # The scripted external agent accepts the current proposal without
            # changing the candidate. Production harness still controls every gate.
            (root / "app.py").write_bytes(candidate_at_capture)

    executor = ScriptedExecutor(script)
    controller._llm_provider = executor

    def capture(visual, worktree):
        nonlocal candidate_at_capture
        candidate_at_capture = (Path(worktree) / "app.py").read_bytes()
        operation = store.read()["delivery_slice_operation"]
        captures.append(operation["repair_task_id"])
        if len(captures) == 1 or len(captures) == 2 and recheck != "pass":
            title = "[echelon:E2E-START-002] startup" if len(captures) == 2 and recheck == "third" else "[echelon:CT-NET-001] network"
            return _capture(product_evidence_fingerprint(Path(worktree)), title=title)
        return _passing_capture(worktree)

    original = DeliverySliceJournal.save
    def save(journal, data):
        original(journal, data)
        if (data["task_id"] == "T-011" and len(data["records"]) == 1
                and data["records"][0].get("browser_evidence") is not None):
            source_bytes.setdefault(journal.path, journal.path.read_bytes())
    monkeypatch.setattr(VisualRalphController, "capture_baselines", capture)
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    return controller, store, executor, captures, source_bytes


def _drive(controller, fixture):
    return controller._exec_feedback(None, _verify(), "echelon build", "", worktree_path=str(fixture[0]))


@pytest.mark.parametrize("recheck,rounds", [("pass", 1), ("retry", 2)])
def test_ralph_repairs_owner_then_returns_to_source_with_normal_reviews(slice_project, tmp_path, monkeypatch, recheck, rounds):
    controller, store, executor, captures, retained = _handoff_project(slice_project, tmp_path, monkeypatch, recheck=recheck)
    before = store.read()
    task_bytes = (slice_project[1] / "tasks.md").read_bytes()
    result = _drive(controller, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    roles = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert [(a["task_id"], a["step"]) for a, _, _ in executor.calls] == (
        [("T-011", "implementer")] + [("T-012", role) for role in roles] * rounds
        + [("T-011", role) for role in roles])
    assert captures == ["T-011"] + ["T-012"] * rounds + ["T-011"]
    assert store.read()["tokens_used"] == result["tokens"] == (63 if rounds == 1 else 91)
    assert retained and all(path.read_bytes() == content for path, content in retained.items())
    assert (slice_project[1] / "tasks.md").read_bytes() == task_bytes
    for key in ("outer_iter", "inner_iter"):
        assert store.read().get(key) == before.get(key)
    operation = store.read()["delivery_slice_operation"]
    assert operation["browser_handoff"]["phase"] == "return"
    assert operation["accepted_task_id"] == "T-011"
    controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    assert store.read()["delivery_slice_operation"]["progress_applied"] is True
    receipts = [json.loads(path.read_text()) for path in controller._delivery_operation_evidence_root().rglob("receipt.json")]
    assert [row["task_id"] for row in receipts].count("T-011") == 2
    assert [row["task_id"] for row in receipts].count("T-012") == rounds


def test_owner_recheck_never_opens_a_nested_foreign_repair(slice_project, tmp_path, monkeypatch):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch, recheck="third")
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"]
    assert "third_owner" in result["build_reason"], result
    assert len(executor.calls) == 5 and captures == ["T-011", "T-012"]
    assert store.read()["delivery_slice_operation"]["browser_handoff"]["phase"] == "owner"
    assert not store.read()["delivery_slice_operation"].get("accepted_task_id")


@pytest.mark.parametrize("damage", ["spec", "scope", "role"])
def test_owner_resume_rejects_changed_context_before_dispatch(slice_project, tmp_path, monkeypatch, damage):
    from harness.state import StateStore
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    from tests.unit.test_delivery_controller_integration import _reconstruct
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    original = StateStore.write
    crashed = False
    def write(current_store, state):
        nonlocal crashed
        original(current_store, state)
        if state.get("delivery_slice_operation", {}).get("browser_handoff", {}).get("phase") == "owner" and not crashed:
            crashed = True
            raise ProcessLost()
    monkeypatch.setattr(StateStore, "write", write)
    with pytest.raises(ProcessLost):
        _drive(controller, slice_project)
    assert len(executor.calls) == 1
    if damage == "spec":
        (slice_project[1] / "spec.md").write_text("Changed requirement\n")
    elif damage == "role":
        path = slice_project[0] / ".echelon/prosaic/subagents/echelon.delivery-implementer.md"
        path.write_text(path.read_text() + "\nChanged instructions\n")
    else:
        state = store.read()
        state["target_task_ids"] = ["T-011"]
        store.write(state)
    resumed = _reconstruct(controller, store, executor)
    result = _drive(resumed, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 1


@pytest.mark.parametrize("damage", ["scope", "role"])
def test_selection_authenticates_source_context_again(slice_project, tmp_path, monkeypatch, damage):
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    select = controller._select_browser_repair_operation
    def changed(request, **kwargs):
        if damage == "scope":
            state = store.read()
            state["target_task_ids"] = ["T-012"]
            store.write(state)
        else:
            path = slice_project[0] / ".echelon/prosaic/subagents/echelon.delivery-implementer.md"
            path.write_text(path.read_text() + "\nChanged instructions\n")
        return select(request, **kwargs)
    monkeypatch.setattr(controller, "_select_browser_repair_operation", changed)
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 1


@pytest.mark.parametrize("budget,expected_calls", [(7, 1), (10, 2), (14, 2), (35, 5), (42, 6)])
def test_handoff_never_renews_token_allowance(slice_project, tmp_path, monkeypatch, budget, expected_calls):
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    controller._controlled_slice_budget = budget
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert "budget_exhausted" in result["build_reason"], result
    assert len(executor.calls) == expected_calls
    assert store.read()["tokens_used"] == 7 * expected_calls
    again = _drive(controller, slice_project)
    assert not again["passed"] and "budget_exhausted" in again["build_reason"], again
    assert len(executor.calls) == expected_calls
    assert store.read()["tokens_used"] == 7 * expected_calls
