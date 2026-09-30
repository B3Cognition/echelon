"""Authenticate real delivery capture journals without dispatching or rewriting."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from harness.browser_baseline_evidence import BrowserBaselineEvidenceRef
from harness.build_result import BuildResult
from harness.delivery_slice import DeliverySliceError
from harness.product_inventory import product_evidence_fingerprint
from tests.unit.test_browser_capture_failures import _capture, _tasks, _rewrite_receipt
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, _run, slice_project


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _pending(fixture, *, title=None, pending_source=False, pending_owner=False):
    root, spec, evidence = fixture
    _tasks(spec)
    tasks = (spec / "tasks.md").read_text()
    if pending_source:
        tasks = tasks.replace("[x] T-011", "[ ] T-011").replace("**Status:** DONE", "**Status:** PENDING", 1)
    if pending_owner:
        first, second = tasks.split("- [x] T-012")
        tasks = first + "- [ ] T-012" + second.replace("**Status:** DONE", "**Status:** PENDING")
    (spec / "tasks.md").write_text(tasks)
    stop = False

    def request(assignment, payload, root):
        payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Capture needed",
                       browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        nonlocal stop
        stop = True
        return _capture(product_evidence_fingerprint(Path(worktree)), **({"title": title} if title else {}))

    executor = ScriptedExecutor(request)
    result = _run(fixture, executor, operation_id="source-op", repair_task_id="T-011",
                  browser_baseline_capture=capture, stop_requested=lambda: stop)
    assert result.reason == "delivery_slice_cancelled"
    path = next(evidence.rglob("journal.json"))
    return path, json.loads(path.read_text()), executor


def _request(data):
    from harness.delivery_browser_handoff import BrowserRepairRequest, JournalRef
    record = data["records"][-1]
    evidence = record["browser_evidence"]
    return BrowserRepairRequest(JournalRef("source-op", _digest(data)),
                                record["assignment"]["dispatch_id"],
                                BrowserBaselineEvidenceRef(Path(evidence["path"]), evidence["receipt_sha256"]))


def _bindings(fixture, data):
    return dict(evidence_root=fixture[2], spec_dir=fixture[1],
                candidate_fingerprint=product_evidence_fingerprint(fixture[0]),
                input_fingerprint=data["input_fingerprint"], allowed_task_ids={"T-011", "T-012"})


def test_resolves_foreign_owner_without_mutating_or_dispatching(slice_project):
    path, data, executor = _pending(slice_project)
    request = _request(data)
    from harness.delivery_browser_handoff import resolve_browser_repair, handoff_operation_id
    from harness.delivery_slice_journal import DeliverySliceJournal
    before = {p: p.read_bytes() for p in slice_project[2].rglob("*") if p.is_file()}
    with DeliverySliceJournal(slice_project[2], "source-op"):
        assert resolve_browser_repair(request, **_bindings(slice_project, data)) == "T-012"
    assert before == {p: p.read_bytes() for p in slice_project[2].rglob("*") if p.is_file()}
    assert len(executor.calls) == 1
    assert not BuildResult(1, "browser_repair_required", None, "", "", 0,
                           browser_repair_request=request).succeeded
    assert handoff_operation_id(request, "owner") == handoff_operation_id(request, "owner")
    assert len({handoff_operation_id(request, stage) for stage in ("owner", "refresh", "return")}) == 3
    with pytest.raises(DeliverySliceError):
        handoff_operation_id(request, "arbitrary-stage")
    assert type(request).from_mapping(request.as_mapping()) == request


@pytest.mark.parametrize("pending_source,pending_owner,title,expected", [
    (True, False, "[echelon:E2E-START-002] pitch", "T-011"),
    (False, True, "[echelon:CT-NET-001] network", "not an accepted task"),
    (False, False, "untagged test", "unidentified test failures"),
    (False, False, "[echelon:CT-NET-001,E2E-START-002] mixed", "multiple task owners"),
])
def test_owner_resolution_preserves_same_task_and_refuses_unsafe_foreign_work(
    slice_project, pending_source, pending_owner, title, expected,
):
    _, data, _ = _pending(slice_project, title=title, pending_source=pending_source, pending_owner=pending_owner)
    request = _request(data)
    from harness.delivery_browser_handoff import resolve_browser_repair
    if expected == "T-011":
        assert resolve_browser_repair(request, **_bindings(slice_project, data)) == expected
    else:
        with pytest.raises(DeliverySliceError, match=expected):
            resolve_browser_repair(request, **_bindings(slice_project, data))


@pytest.mark.parametrize("damage", ["candidate", "inputs", "scope", "dispatch", "reference",
                                    "digest", "missing", "symlink", "directory_symlink", "old_receipt"])
def test_unsafe_evidence_cannot_authorize_handoff(slice_project, damage):
    path, data, executor = _pending(slice_project)
    request = _request(data)
    from harness.delivery_browser_handoff import resolve_browser_repair
    bindings = _bindings(slice_project, data)
    if damage == "candidate":
        bindings["candidate_fingerprint"] = "different"
    elif damage == "inputs":
        bindings["input_fingerprint"] = "different"
    elif damage == "scope":
        bindings["allowed_task_ids"] = {"T-011"}
    elif damage == "dispatch":
        request = replace(request, dispatch_id="unrecorded")
    elif damage == "reference":
        request = replace(request, receipt=replace(request.receipt, receipt_sha256="0" * 64))
    elif damage == "digest":
        request = replace(request, source=replace(request.source, journal_sha256="0" * 64))
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        moved = path.with_name("retained.json")
        path.rename(moved)
        path.symlink_to(moved)
    elif damage == "directory_symlink":
        moved = path.parent.with_name("retained-journal")
        path.parent.rename(moved)
        path.parent.symlink_to(moved, target_is_directory=True)
    elif damage == "old_receipt":
        payload = json.loads(request.receipt.path.read_text())
        payload.pop("verification_failures")
        payload["schema_version"] = 2
        ref = _rewrite_receipt(request.receipt, payload)
        data["records"][-1]["browser_evidence"] = {"path": str(ref.path), "receipt_sha256": ref.receipt_sha256}
        path.write_text(json.dumps(data))
        request = _request(data)
    before = {p: p.read_bytes() for p in slice_project[2].rglob("*") if p.is_file()}
    with pytest.raises(DeliverySliceError):
        resolve_browser_repair(request, **bindings)
    assert before == {p: p.read_bytes() for p in slice_project[2].rglob("*") if p.is_file()}
    assert len(executor.calls) == 1


@pytest.mark.parametrize("saved,current,want", [(100, 90, 90), (50, 100, 50), (None, None, None), (5, 100, 5)])
def test_allowance_retains_spending_even_after_overshoot(slice_project, saved, current, want):
    _, data, _ = _pending(slice_project)
    from harness.delivery_browser_handoff import continuation_allowance
    data["budget_limit"] = saved
    allowance = continuation_allowance(data, token_limit=current)
    assert (allowance.repair_attempt, allowance.browser_requests_in_round) == (0, 1)
    assert allowance.tokens_consumed == 7
    assert allowance.usage_known
    assert allowance.token_limit == want


@pytest.mark.parametrize("limit", [-1, float("nan"), float("inf"), True])
def test_invalid_budget_is_rejected(slice_project, limit):
    _, data, _ = _pending(slice_project)
    from harness.delivery_browser_handoff import continuation_allowance
    with pytest.raises(DeliverySliceError):
        continuation_allowance(data, token_limit=limit)
    data["budget_limit"] = limit
    with pytest.raises(DeliverySliceError):
        continuation_allowance(data, token_limit=None)


def test_unknown_usage_does_not_become_free_budget(slice_project):
    _, data, _ = _pending(slice_project)
    from harness.delivery_browser_handoff import continuation_allowance
    data["records"][0]["token_usage"] = None
    with pytest.raises(DeliverySliceError, match="unknown"):
        continuation_allowance(data, token_limit=100)
    allowance = continuation_allowance(data, token_limit=None)
    assert allowance.usage_known is False


def test_allowance_keeps_rejected_round_before_capture(slice_project):
    from harness.delivery_browser_handoff import continuation_allowance
    stop = False
    implementations = 0

    def decide(assignment, payload, root):
        nonlocal implementations
        if assignment["step"] == "implementer":
            implementations += 1
            if implementations == 2:
                payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                               browser_evidence_request={"purpose": "baseline_capture"})
        elif assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong greeting"])

    def capture(worktree):
        nonlocal stop
        stop = True
        return _capture(product_evidence_fingerprint(Path(worktree)))

    result = _run(slice_project, ScriptedExecutor(decide), browser_baseline_capture=capture,
                  stop_requested=lambda: stop)
    assert result.reason == "delivery_slice_cancelled"
    data = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    allowance = continuation_allowance(data, token_limit=100)
    assert (allowance.repair_attempt, allowance.browser_requests_in_round, allowance.tokens_consumed) == (1, 1, 35)


def test_allowance_does_not_charge_passing_capture_correction_as_recapture(slice_project):
    from harness.delivery_browser_handoff import continuation_allowance
    implementations = 0

    def request(assignment, payload, root):
        nonlocal implementations
        implementations += 1
        (root / "app.py").write_text("stable candidate\n")
        payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                       browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        captured = _capture(product_evidence_fingerprint(Path(worktree)))
        captured.verification.passed = True
        captured.verification.failures.clear()
        return captured

    result = _run(slice_project, ScriptedExecutor(request), browser_baseline_capture=capture,
                  stop_requested=lambda: implementations == 2)
    assert result.reason == "delivery_slice_cancelled"
    data = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert len(data["records"]) == 2
    allowance = continuation_allowance(data, token_limit=100)
    assert (allowance.repair_attempt, allowance.browser_requests_in_round, allowance.tokens_consumed) == (0, 1, 14)


def test_allowance_rejects_inconsistent_round_history(slice_project):
    _, data, _ = _pending(slice_project)
    from harness.delivery_browser_handoff import continuation_allowance
    data["records"][0]["repair_attempt"] = 2
    with pytest.raises(DeliverySliceError, match="repair history"):
        continuation_allowance(data, token_limit=None)


@pytest.mark.parametrize("damage", ["extra", "source_type", "receipt_type", "relative_path", "bad_digest"])
def test_request_mapping_is_strict(slice_project, damage):
    _, data, _ = _pending(slice_project)
    request = _request(data)
    payload = request.as_mapping()
    if damage == "extra":
        payload["task_override"] = "T-012"
    elif damage == "source_type":
        payload["source"] = None
    elif damage == "receipt_type":
        payload["receipt"] = []
    elif damage == "relative_path":
        payload["receipt"]["path"] = "relative/receipt.json"
    else:
        payload["source"]["journal_sha256"] = "unbound"
    with pytest.raises(DeliverySliceError):
        type(request).from_mapping(payload)
