"""Reconstruct real controllers across interrupted durable/external boundaries."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _run, _steps


class ProcessLost(BaseException):
    pass


def _review_evidence_recheck_journal(slice_project):
    from harness.delivery_slice_journal import _validate

    assert _run(slice_project, ScriptedExecutor()).succeeded
    data = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    data["records"] = data["records"][:2]
    first = data["records"][1]
    raw = json.loads(first["raw_result"])
    raw.update(verdict="FAIL", findings=["tests/integration/bootstrap.test.ts:1 missing coverage"],
               reviewed_test_paths=["tests/integration/bootstrap.test.ts"])
    first["raw_result"] = json.dumps(raw)
    first["result"] = {**first["result"], **{
        key: raw[key] for key in ("verdict", "findings", "reviewed_test_paths")
    }}
    first["review_evidence"] = {
        "audit_test_paths": ["tests/integration/bootstrap.test.ts",
                             "tests/integration/main-entry.test.ts"],
        "incomplete": True,
    }
    _validate(data)
    return data


def test_review_evidence_recheck_allows_one_same_role_intent(slice_project):
    from harness.delivery_slice_journal import _validate

    data = _review_evidence_recheck_journal(slice_project)
    repeat = deepcopy(data["records"][1])
    repeat["assignment"]["dispatch_id"] = "same-role-recheck"
    repeat.update(raw_result=None, result=None, candidate_after=None, token_usage=None,
                  error=None)
    repeat.pop("review_evidence")
    data["records"].append(repeat)

    assert repeat["assignment"]["step"] == "spec_guard"
    assert repeat["repair_attempt"] == data["records"][1]["repair_attempt"]
    _validate(data)


def test_review_evidence_recheck_second_incomplete_is_terminal(slice_project):
    from harness.delivery_slice_journal import _validate

    data = _review_evidence_recheck_journal(slice_project)
    repeat = deepcopy(data["records"][1])
    repeat["assignment"]["dispatch_id"] = "same-role-recheck"
    repeat["raw_result"] = json.dumps({**json.loads(repeat["raw_result"]),
                                       "dispatch_id": "same-role-recheck",
                                       "verdict": "PASS", "findings": []})
    repeat["result"].update(dispatch_id="same-role-recheck", verdict="PASS", findings=[])
    data["records"].append(repeat)
    _validate(data)

    third = deepcopy(repeat)
    third["assignment"]["dispatch_id"] = "forbidden-third-recheck"
    third.update(raw_result=None, result=None, candidate_after=None, token_usage=None,
                 error=None)
    third.pop("review_evidence")
    data["records"].append(third)
    with pytest.raises(Exception, match="terminal"):
        _validate(data)


@pytest.mark.parametrize("damage", ["forged_complete", "unsafe_audit_path", "review_mutation"])
def test_review_evidence_recheck_rejects_forged_receipt(slice_project, damage):
    from harness.delivery_slice_journal import _validate

    data = _review_evidence_recheck_journal(slice_project)
    first = data["records"][1]
    if damage == "forged_complete":
        first["review_evidence"]["incomplete"] = False
    elif damage == "unsafe_audit_path":
        first["review_evidence"]["audit_test_paths"].append("../outside.test.ts")
    else:
        first["candidate_after"] = "mutated"
    with pytest.raises(Exception):
        _validate(data)


@pytest.mark.parametrize("damage", ["missing_evidence", "narrowed_audit"])
def test_review_evidence_recheck_requires_same_audit_on_second_receipt(slice_project, damage):
    from harness.delivery_slice_journal import _validate

    data = _review_evidence_recheck_journal(slice_project)
    repeat = deepcopy(data["records"][1])
    repeat["assignment"]["dispatch_id"] = "same-role-recheck"
    raw = json.loads(repeat["raw_result"])
    raw.update(dispatch_id="same-role-recheck", verdict="PASS", findings=[])
    repeat["raw_result"] = json.dumps(raw)
    repeat["result"].update(dispatch_id="same-role-recheck", verdict="PASS", findings=[])
    if damage == "missing_evidence":
        repeat.pop("review_evidence")
    else:
        repeat["review_evidence"] = {
            "audit_test_paths": ["tests/integration/bootstrap.test.ts"], "incomplete": False,
        }
    data["records"].append(repeat)
    with pytest.raises(Exception):
        _validate(data)


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


def test_capture_written_before_journal_update_can_be_recaptured_on_resume(
    slice_project, monkeypatch,
):
    from harness.delivery_slice_journal import DeliverySliceJournal
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    captures = []

    def capture(worktree):
        captures.append(worktree)
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    original = DeliverySliceJournal.save

    def crash_before_reference(self, data):
        if data["records"] and "browser_evidence" in data["records"][-1]:
            raise ProcessLost()
        original(self, data)

    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", crash_before_reference)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(request), browser_baseline_capture=capture)

    replay = ScriptedExecutor()
    result = _run(slice_project, replay, browser_baseline_capture=capture)
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert len(captures) == 2
    assert len(list(slice_project[2].rglob("browser-baselines/*/*/receipt.json"))) == 2
    assert _steps(replay) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]


def test_stale_capture_is_not_journaled_and_can_be_retried(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    def capture(worktree, *, fingerprint):
        return BrowserBaselineCapture(
            candidate_fingerprint=fingerprint,
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    blocked = _run(
        slice_project, ScriptedExecutor(request),
        browser_baseline_capture=lambda worktree: capture(worktree, fingerprint="stale"),
    )
    assert blocked.status == "blocked" and "stale" in blocked.reason
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert "browser_evidence" not in journal["records"][0]

    replay = ScriptedExecutor()
    resumed = _run(
        slice_project, replay,
        browser_baseline_capture=lambda worktree: capture(
            worktree, fingerprint=product_evidence_fingerprint(Path(worktree)),
        ),
    )
    assert resumed.succeeded and resumed.task_ids == ["T-001"], resumed.reason


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


def test_changed_implementation_target_never_reuses_receipts(
    slice_project, monkeypatch,
):
    _project, spec, _evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n",
        encoding="utf-8",
    )
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 1)
        with pytest.raises(ProcessLost):
            _run(
                slice_project,
                ScriptedExecutor(),
                implementation_target="sources/demo",
            )

    resumed = ScriptedExecutor()
    result = _run(
        slice_project,
        resumed,
        implementation_target="sources/other",
    )

    assert result.reason == "delivery_reconciliation_required: operation binding changed"
    assert not result.succeeded and not resumed.calls


def test_exhausted_repairs_remain_exhausted_after_restart(slice_project):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong result"])
    first = ScriptedExecutor(reject)
    assert not _run(slice_project, first).succeeded
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(first) == chain * 5
    second = ScriptedExecutor()
    result = _run(slice_project, second)
    assert not result.succeeded and "repair_limit" in result.reason
    assert not second.calls and result.token_usage == 140


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
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(resumed) == chain * 4
    assert "wrong result" in resumed.calls[0][2]


def test_restart_finishes_rejected_review_round_before_repair(slice_project, monkeypatch):
    rejected = False

    def reject_once(assignment, payload, root):
        nonlocal rejected
        if assignment["step"] == "spec_guard" and not rejected:
            rejected = True
            payload.update(
                verdict="FAIL",
                findings=["app.py:1 wrong result"],
            )

    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(reject_once))

    resumed = ScriptedExecutor(reject_once)
    result = _run(slice_project, resumed)

    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.succeeded, result.reason
    assert _steps(resumed) == ["code_reviewer", "test_guardian"] + chain
    assert "wrong result" in resumed.calls[2][2]


def test_saved_finite_budget_cannot_reset_on_restart(slice_project, monkeypatch):
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 1)
        with pytest.raises(ProcessLost):
            _run(slice_project, ScriptedExecutor(), token_budget=14)
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, token_budget=1000)
    assert not result.succeeded and "budget_exhausted" in result.reason
    assert _steps(resumed) == ["spec_guard"] and result.token_usage == 14


def test_explicit_budget_extension_replays_receipt_and_finishes_reviews(slice_project):
    first = ScriptedExecutor()
    blocked = _run(slice_project, first, token_budget=7)
    assert not blocked.succeeded and "budget_exhausted" in blocked.reason
    assert _steps(first) == ["implementer"]

    resumed = ScriptedExecutor()
    result = _run(
        slice_project, resumed, token_budget=100,
        budget_extension_limit=100, journal_required=True,
    )

    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert _steps(resumed) == ["spec_guard", "code_reviewer", "test_guardian"]
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert journal["budget_limit"] == 100
    assert len(journal["records"]) == 4


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
