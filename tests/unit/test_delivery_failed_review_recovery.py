"""Recover failed or interrupted reviews without losing implementation history."""
import json
import pytest

from harness.ai_cli_backend import CliRunResult
from harness.delivery_slice_journal import DeliverySliceJournal
from tests.unit.test_delivery_controller_integration import _controller, _reconstruct
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _steps
from tests.unit.test_delivery_unknown_dispatch_recovery import _build
from tests.unit.test_delivery_slice_recovery import ProcessLost


def _failed_review(fixture, tmp_path, step, usage=7, *, unknown=False):
    rounds = 0

    def script(assignment, payload, root):
        nonlocal rounds
        if assignment["step"] == "implementer":
            rounds += 1
        if rounds == 1 and assignment["step"] == "code_reviewer":
            payload.update(verdict="CHANGES_REQUESTED", summary="Repair the current defect",
                           findings=["app.py:1 returns incorrect greeting"])
        if rounds == 2 and assignment["step"] == step:
            if unknown:
                raise ProcessLost()
            return CliRunResult(1, "Selected model is at capacity", "", token_usage=usage)

    controller, store = _controller(fixture, tmp_path, ScriptedExecutor(script))
    if unknown:
        with pytest.raises(ProcessLost):
            _build(controller, fixture)
    else:
        assert _build(controller, fixture)["build_reason"] == "delivery_provider_failed"
    journal = DeliverySliceJournal(controller._delivery_operation_evidence_root(),
                                   store.read()["delivery_slice_operation"]["id"])
    with journal:
        data = journal.load(required=True)
    return controller, store, journal, data


@pytest.mark.parametrize("step,remaining", [
    ("spec_guard", ["spec_guard", "code_reviewer", "test_guardian"]),
    ("code_reviewer", ["code_reviewer", "test_guardian"]),
    ("test_guardian", ["test_guardian"]),
])
@pytest.mark.parametrize("usage,unknown", [(7, False), (None, False), (None, True)])
def test_resume_preserves_completed_round_and_retries_only_failed_review(slice_project, tmp_path, step, remaining, usage, unknown):
    controller, store, parent, original = _failed_review(slice_project, tmp_path, step, usage, unknown=unknown)
    previous_tokens = store.read()["tokens_used"]
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == remaining
    state = store.read()
    assert state["tokens_used"] == 56 + (usage or 0)
    assert result["tokens"] == state["tokens_used"] - previous_tokens
    assert state.get("provider_token_usage_unknown_count", 0) == (1 if usage is None else 0)
    operation = state["delivery_slice_operation"]
    with DeliverySliceJournal(controller._delivery_operation_evidence_root(), operation["id"]) as successor:
        recovered = successor.load(required=True)
    assert recovered["records"][:len(original["records"]) - 1] == original["records"][:-1]
    assert recovered["records"][-1]["repair_attempt"] == 1
    with parent:
        sealed = parent.load(required=True)
    assert sealed["records"][:-1] == original["records"][:-1]
    assert sealed["records"][-1]["raw_result"] == (None if unknown else "Selected model is at capacity")
    seal = "delivery_dispatch_outcome_unknown_superseded:" if unknown else "delivery_provider_failure_superseded:"
    assert sealed["records"][-1]["error"] == seal + operation["id"]
    executor.calls.clear()
    assert _build(_reconstruct(controller, store, executor), slice_project)["tokens"] == 0
    assert not executor.calls
    assert store.read()["tokens_used"] == state["tokens_used"]


@pytest.mark.parametrize("unknown", [False, True])
def test_failed_review_cannot_authorize_changed_candidate(slice_project, tmp_path, unknown):
    controller, store, _, _ = _failed_review(slice_project, tmp_path, "spec_guard", unknown=unknown)
    (slice_project[0] / "app.py").write_text("unreviewed replacement")
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown
    result = _build(resumed, slice_project)
    assert not result["passed"]
    assert "candidate changed" in result["build_reason"]
    assert not executor.calls


@pytest.mark.parametrize("damage", ["ordinary_continue", "spec", "binding", "raw_result", "candidate_after", "token_usage", "later_implementer", "budget"])
def test_unknown_review_recovery_remains_explicit_and_fail_closed(slice_project, tmp_path, damage):
    step = "implementer" if damage == "later_implementer" else "code_reviewer"
    controller, store, parent, _ = _failed_review(slice_project, tmp_path, step, unknown=True)
    if damage == "spec":
        (slice_project[1] / "spec.md").write_text("changed specification")
    elif damage == "binding":
        state = store.read()
        state["delivery_slice_operation"]["feedback"] = "different assignment"
        store.write(state)
    elif damage in {"raw_result", "candidate_after", "token_usage", "budget"}:
        with parent:
            data = parent.load(required=True)
            if damage == "budget":
                data["budget_limit"] = 42  # Six retained receipts exhaust this limit.
            else:
                data["records"][-1][damage] = 7 if damage == "token_usage" else "partial result"
            if damage == "budget":
                parent.save(data)
            else:
                # Simulate a corrupt/partial on-disk receipt; normal save rejects it.
                parent.path.write_text(json.dumps(data))
    original_operation = store.read()["delivery_slice_operation"]
    original_journal = parent.path.read_bytes()
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True  # Ordinary continue must not infer permission.
    resumed._reconcile_unknown_dispatch = damage != "ordinary_continue"
    result = _build(resumed, slice_project)
    assert not result["passed"]
    assert not executor.calls
    assert store.read()["delivery_slice_operation"]["id"] == original_operation["id"]
    assert parent.path.read_bytes() == original_journal


def test_review_retry_does_not_reset_consumed_budget(slice_project, tmp_path):
    controller, store, parent, _ = _failed_review(slice_project, tmp_path, "spec_guard")
    with parent:
        data = parent.load(required=True)
        data["budget_limit"] = 48  # 35 retained + 7 failed leaves only 6.
        parent.save(data)
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    result = _build(resumed, slice_project)
    assert result["build_reason"] == "delivery_slice_budget_exhausted"
    assert _steps(executor) == ["spec_guard"]
    assert store.read()["tokens_used"] == 49


@pytest.mark.parametrize("error", ["delivery_reviewer_mutated_candidate", "invalid provider JSON"])
def test_only_provider_failures_are_retryable(slice_project, tmp_path, error):
    controller, store, parent, _ = _failed_review(slice_project, tmp_path, "spec_guard")
    with parent:
        data = parent.load(required=True)
        data["records"][-1]["error"] = error
        parent.save(data)
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    assert not _build(resumed, slice_project)["passed"]
    assert not executor.calls


def test_repeated_provider_failure_requires_another_explicit_resume(slice_project, tmp_path):
    controller, store, parent, _ = _failed_review(slice_project, tmp_path, "spec_guard")
    executor = ScriptedExecutor(lambda *args: CliRunResult(1, "still unavailable", "", token_usage=3))
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    assert _build(resumed, slice_project)["build_reason"] == "delivery_provider_failed"
    assert _steps(executor) == ["spec_guard"]
    assert not _build(_reconstruct(controller, store, executor), slice_project)["passed"]
    assert _steps(executor) == ["spec_guard"]
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    assert _build(resumed, slice_project)["passed"]
    assert _steps(executor) == ["spec_guard", "code_reviewer", "test_guardian"]
    assert store.read()["tokens_used"] == 66


def test_successor_cannot_drop_retained_review_rounds(slice_project, tmp_path):
    controller, store, _, _ = _failed_review(slice_project, tmp_path, "spec_guard")
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    assert _build(resumed, slice_project)["passed"]
    with DeliverySliceJournal(controller._delivery_operation_evidence_root(),
                              store.read()["delivery_slice_operation"]["id"]) as journal:
        data = journal.load(required=True)
        data["records"] = []
        journal.save(data)
    executor.calls.clear()
    result = _build(_reconstruct(controller, store, executor), slice_project)
    assert result["build_reason"] == "delivery_reconciliation_required: retained review history changed"
    assert not executor.calls


@pytest.mark.parametrize("boundary", ["successor", "seal", "state"])
@pytest.mark.parametrize("unknown", [False, True])
def test_review_recovery_handover_survives_crash_without_double_charging(slice_project, tmp_path, monkeypatch, boundary, unknown):
    controller, store, parent, original = _failed_review(slice_project, tmp_path, "spec_guard", None, unknown=unknown)
    old_id = store.read()["delivery_slice_operation"]["id"]
    save, write = DeliverySliceJournal.save, store.write

    def save_and_crash(self, data):
        save(self, data)
        if boundary == "successor" and self.path != parent.path:
            raise ProcessLost()
        if boundary == "seal" and data["records"][-1]["error"]:
            raise ProcessLost()

    def write_and_crash(state):
        write(state)
        if state.get("delivery_slice_operation", {}).get("id") != old_id:
            raise ProcessLost()

    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown
    with monkeypatch.context() as patch:
        if boundary == "state":
            patch.setattr(resumed._state_store, "write", write_and_crash)
        else:
            patch.setattr(DeliverySliceJournal, "save", save_and_crash)
        with pytest.raises(ProcessLost):
            _build(resumed, slice_project)
    assert not executor.calls
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown and boundary != "state"
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == ["spec_guard", "code_reviewer", "test_guardian"]
    assert store.read()["tokens_used"] == 56
    assert store.read()["provider_token_usage_unknown_count"] == 1


@pytest.mark.parametrize("later_round", [False, True])
@pytest.mark.parametrize("unknown", [False, True])
def test_reviewer_retry_keeps_browser_receipt_bound_to_original_operation(slice_project, tmp_path, monkeypatch, later_round, unknown):
    from pathlib import Path
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture, VisualRalphController

    requests = 0
    def script(assignment, payload, root):
        nonlocal requests
        if assignment["step"] == "implementer":
            requests += 1
            (root / "app.py").write_text("def hello(): return 'repaired'\n" if requests == 3 else "def hello(): return 'hello'\n")
            if requests == 1:
                payload.update(verdict="BROWSER_EVIDENCE_REQUIRED",
                               browser_evidence_request={"purpose": "baseline_capture"})
        if later_round and requests == 2 and assignment["step"] == "code_reviewer":
            payload.update(verdict="CHANGES_REQUESTED", findings=["app.py:1 wrong greeting"])
        if assignment["step"] == "spec_guard" and (not later_round or requests == 3):
            if unknown:
                raise ProcessLost()
            return CliRunResult(1, "provider unavailable", "", token_usage=7)

    captures = []
    def capture(self, worktree):
        captures.append(worktree)
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=True),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )
    monkeypatch.setattr(VisualRalphController, "capture_baselines", capture)
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor(script))
    if unknown:
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    else:
        assert _build(controller, slice_project)["build_reason"] == "delivery_provider_failed"
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == ["spec_guard", "code_reviewer", "test_guardian"]
    assert len(captures) == 1
    assert _build(_reconstruct(controller, store, executor), slice_project)["passed"]
    assert len(captures) == 1


def test_completed_context_recheck_is_not_reexecuted_against_new_candidate(slice_project, tmp_path):
    project = slice_project[0]
    (project / "tests").mkdir()
    (project / "tests/test_hello.py").write_text("def test_hello(): pass\n")
    rounds, reviews = 0, 0
    def script(assignment, payload, root):
        nonlocal rounds, reviews
        if assignment["step"] == "implementer":
            rounds += 1
        if assignment["step"] == "spec_guard":
            if rounds == 2:
                return CliRunResult(1, "provider unavailable", "", token_usage=7)
            reviews += 1
            payload.update(verdict="FAIL", findings=["app.py:1 incorrect greeting"],
                           reviewed_test_paths=["tests/test_hello.py"] if reviews == 2 else [])
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor(script))
    assert _build(controller, slice_project)["build_reason"] == "delivery_provider_failed"
    assert reviews == 2
    executor = ScriptedExecutor()
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = True
    result = _build(resumed, slice_project)
    assert result["passed"], result
    assert _steps(executor) == ["spec_guard", "code_reviewer", "test_guardian"]
    assert _build(_reconstruct(controller, store, executor), slice_project)["passed"]
