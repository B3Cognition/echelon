"""Controller capture checkpoints cannot impersonate task acceptance."""
import json
from pathlib import Path

import pytest

from harness.delivery_browser_handoff import resolve_browser_repair
from harness.product_inventory import product_evidence_fingerprint
from tests.unit.test_browser_capture_failures import _capture, _tasks
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, _run, slice_project
from tests.unit.test_delivery_slice_recovery import ProcessLost


def _resolver(fixture):
    from harness.delivery_slice_runner import _digest, _spec_inputs
    root, spec, evidence = fixture
    return lambda request: resolve_browser_repair(
        request, evidence_root=evidence, spec_dir=spec,
        candidate_fingerprint=product_evidence_fingerprint(root),
        input_fingerprint=_digest(_spec_inputs(spec, root)), allowed_task_ids={"T-011", "T-012"},
    )


def _passing_capture(worktree):
    result = _capture(product_evidence_fingerprint(Path(worktree)))
    result.verification.passed = True
    result.verification.failures.clear()
    return result


def _old_pending(fixture):
    from tests.unit.test_delivery_browser_handoff import _pending
    from tests.unit.test_browser_capture_failures import _rewrite_receipt
    from harness.browser_baseline_evidence import BrowserBaselineEvidenceRef
    path, parent, executor = _pending(fixture)
    ref = parent["records"][-1]["browser_evidence"]
    payload = json.loads(Path(ref["path"]).read_text())
    payload.pop("verification_failures")
    payload["schema_version"] = 2
    updated = _rewrite_receipt(BrowserBaselineEvidenceRef(Path(ref["path"]), ref["receipt_sha256"]), payload)
    ref["receipt_sha256"] = updated.receipt_sha256
    path.write_text(json.dumps(parent))
    return path, parent, executor


def test_foreign_browser_failure_yields_before_another_role(slice_project):
    _tasks(slice_project[1])
    before = (slice_project[1] / "tasks.md").read_bytes()

    def request(assignment, payload, root):
        payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                       browser_evidence_request={"purpose": "baseline_capture"})

    executor = ScriptedExecutor(request)
    result = _run(slice_project, executor, repair_task_id="T-011",
                  browser_baseline_capture=lambda path: _capture(product_evidence_fingerprint(Path(path))),
                  resolve_browser_owner=_resolver(slice_project))
    assert result.status == "browser_repair_required"
    assert not result.succeeded and not result.task_ids
    assert result.browser_repair_request is not None
    assert [(a["task_id"], a["step"]) for a, _, _ in executor.calls] == [("T-011", "implementer")]
    assert result.token_usage == 7
    assert (slice_project[1] / "tasks.md").read_bytes() == before


def test_passing_reviews_do_not_accept_failed_browser_recheck(slice_project):
    _tasks(slice_project[1])
    captures = []

    def capture(worktree):
        captures.append(worktree)
        if len(captures) == 1:
            return _capture(product_evidence_fingerprint(Path(worktree)))
        return _passing_capture(worktree)

    executor = ScriptedExecutor()
    result = _run(slice_project, executor, repair_task_id="T-012", require_browser_recheck=True,
                  browser_baseline_capture=capture, resolve_browser_owner=_resolver(slice_project))
    assert result.succeeded and result.task_ids == ["T-012"], result.reason
    assert [a["step"] for a, _, _ in executor.calls] == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ] * 2
    assert len(captures) == 2 and result.token_usage == 56
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert [row["repair_attempt"] for row in journal["records"]] == [0] * 4 + [1] * 4
    assert len(journal["browser_checks"]) == 2


def test_repeated_failed_browser_recheck_exhausts_existing_rounds(slice_project):
    _tasks(slice_project[1])
    executor = ScriptedExecutor()
    capture = lambda path: _capture(product_evidence_fingerprint(Path(path)))
    result = _run(slice_project, executor, repair_task_id="T-012", require_browser_recheck=True,
                  browser_baseline_capture=capture, resolve_browser_owner=_resolver(slice_project))
    assert not result.succeeded and not result.task_ids
    assert "repair_limit" in result.reason
    assert len(executor.calls) == 20
    replay = ScriptedExecutor()
    resumed = _run(slice_project, replay, repair_task_id="T-012", require_browser_recheck=True,
                   browser_baseline_capture=lambda _: pytest.fail("exhausted operation must not recapture"),
                   resolve_browser_owner=_resolver(slice_project), journal_required=True)
    assert resumed.reason == result.reason
    assert not replay.calls


@pytest.mark.parametrize("after_receipt", [False, True])
def test_owner_capture_checkpoint_survives_process_loss(slice_project, monkeypatch, after_receipt):
    from harness.delivery_slice_journal import DeliverySliceJournal
    _tasks(slice_project[1])
    save = DeliverySliceJournal.save
    crashed = False
    captures = []

    def crash(journal, data):
        nonlocal crashed
        save(journal, data)
        checks = data.get("browser_checks", [])
        if checks and bool(checks[-1]["receipt"]) == after_receipt and not crashed:
            crashed = True
            raise ProcessLost()

    def capture(path):
        captures.append(path)
        return _passing_capture(path)

    monkeypatch.setattr(DeliverySliceJournal, "save", crash)
    with pytest.raises(ProcessLost):
        _run(slice_project, ScriptedExecutor(), repair_task_id="T-012", require_browser_recheck=True,
             browser_baseline_capture=capture, resolve_browser_owner=_resolver(slice_project))
    replay = ScriptedExecutor()
    result = _run(slice_project, replay, repair_task_id="T-012", require_browser_recheck=True,
                  browser_baseline_capture=capture, resolve_browser_owner=_resolver(slice_project),
                  journal_required=True)
    assert result.succeeded and not replay.calls, result.reason
    assert len(captures) == 1
    data = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert [row["request_ordinal"] for row in data["browser_checks"]] == ([1] if after_receipt else [1, 2])


def test_refresh_continuation_preserves_history_and_consumes_next_capture(slice_project):
    from harness.delivery_browser_handoff import JournalRef, journal_sha256, prepare_browser_continuation
    from harness.delivery_slice_runner import _candidate_fingerprint
    path, parent, _ = _old_pending(slice_project)
    before = path.read_bytes()
    continuation = prepare_browser_continuation(
        kind="refresh", predecessors=[JournalRef("source-op", journal_sha256(parent))],
        evidence_root=slice_project[2],
        candidate_fingerprint=_candidate_fingerprint(slice_project[0], slice_project[1]),
        input_fingerprint=parent["input_fingerprint"], token_limit=100,
    )
    captures = []
    def capture(worktree):
        captures.append(worktree)
        return _capture(product_evidence_fingerprint(Path(worktree)))
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, operation_id="refresh-op", repair_task_id="T-011",
                  continuation=continuation, browser_baseline_capture=capture,
                  resolve_browser_owner=_resolver(slice_project), token_budget=100)
    assert result.status == "browser_repair_required", result.reason
    assert not executor.calls and len(captures) == 1
    assert path.read_bytes() == before
    from harness.delivery_slice_journal import DeliverySliceJournal
    data = DeliverySliceJournal(slice_project[2], "refresh-op").load(required=True)
    assert data["browser_checks"][0]["request_ordinal"] == 2
    assert not data["records"]
    resumed = _run(slice_project, executor, operation_id="refresh-op", repair_task_id="T-011",
                   continuation=continuation, browser_baseline_capture=lambda _: pytest.fail("duplicate capture"),
                   resolve_browser_owner=_resolver(slice_project), token_budget=100, journal_required=True)
    assert resumed.status == "browser_repair_required", resumed.reason
    assert not executor.calls and result.token_usage == resumed.token_usage == 0


@pytest.mark.parametrize("damage", ["capture_count", "round", "tokens", "input", "candidate", "predecessor"])
def test_continuation_cannot_reset_allowances_or_change_lineage(slice_project, damage):
    from harness.delivery_browser_handoff import JournalRef, journal_sha256, prepare_browser_continuation
    from harness.delivery_slice_runner import _candidate_fingerprint
    path, parent, _ = _old_pending(slice_project)
    continuation = prepare_browser_continuation(
        kind="refresh", predecessors=[JournalRef("source-op", journal_sha256(parent))],
        evidence_root=slice_project[2], candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
        input_fingerprint=parent["input_fingerprint"], token_limit=100,
    )
    if damage == "capture_count":
        continuation["allowance"]["browser_requests_in_round"] = 0
    elif damage == "round":
        continuation["allowance"]["repair_attempt"] = 1
    elif damage == "tokens":
        continuation["allowance"]["tokens_consumed"] = 0
    elif damage in {"input", "candidate"}:
        continuation[f"entry_{damage}_fingerprint"] = "0" * 64
    else:
        path.write_text(path.read_text() + " ")  # Canonical hash unchanged; alter real authority below.
        parent["budget_limit"] = 101
        path.write_text(json.dumps(parent))
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, operation_id="refresh-op", repair_task_id="T-011",
                  continuation=continuation, token_budget=100,
                  browser_baseline_capture=lambda _: pytest.fail("invalid lineage must not capture"))
    assert not result.succeeded and not executor.calls
    assert "continuation" in result.reason or "predecessor" in result.reason


@pytest.mark.parametrize("after_receipt", [False, True])
def test_requested_capture_crash_keeps_consumed_attempt(slice_project, monkeypatch, after_receipt):
    from harness.delivery_slice_journal import DeliverySliceJournal
    _tasks(slice_project[1])
    original = DeliverySliceJournal.save
    interrupted = False
    def save(journal, data):
        nonlocal interrupted
        original(journal, data)
        checks = data.get("browser_checks", [])
        if checks and bool(checks[-1]["receipt"]) == after_receipt and not interrupted:
            interrupted = True
            raise ProcessLost()
    def request(assignment, payload, root):
        payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Capture needed",
                       browser_evidence_request={"purpose": "baseline_capture"})
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    captures = []
    def capture(worktree):
        captures.append(worktree)
        return _capture(product_evidence_fingerprint(Path(worktree)))
    first = ScriptedExecutor(request)
    with pytest.raises(ProcessLost):
        _run(slice_project, first, repair_task_id="T-011", resolve_browser_owner=_resolver(slice_project),
             browser_baseline_capture=capture)
    replay = ScriptedExecutor()
    result = _run(slice_project, replay, repair_task_id="T-011", resolve_browser_owner=_resolver(slice_project),
                  browser_baseline_capture=capture, journal_required=True)
    assert result.status == "browser_repair_required", result.reason
    assert len(first.calls) == len(captures) == 1 and not replay.calls
    data = DeliverySliceJournal(slice_project[2], "active").load(required=True)
    assert [row["request_ordinal"] for row in data["browser_checks"]] == ([1] if after_receipt else [1, 2])


@pytest.mark.parametrize("mutates_without_recapture", [False, True])
def test_owner_and_return_keep_source_allowance_but_use_distinct_task_receipts(slice_project, mutates_without_recapture):
    from harness.delivery_browser_handoff import (
        JournalRef, journal_sha256, prepare_browser_continuation, continuation_allowance,
    )
    from harness.delivery_slice_journal import DeliverySliceJournal
    from harness.delivery_slice_runner import _candidate_fingerprint
    from tests.unit.test_delivery_browser_handoff import _pending
    path, source, _ = _pending(slice_project)
    before = path.read_bytes()
    source_ref = JournalRef("source-op", journal_sha256(source))
    owner_entry = prepare_browser_continuation(
        kind="owner_retry", predecessors=[source_ref], evidence_root=slice_project[2],
        candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
        input_fingerprint=source["input_fingerprint"], token_limit=100,
    )
    owner_result = _run(slice_project, ScriptedExecutor(), operation_id="owner-op", repair_task_id="T-012",
                        continuation=owner_entry, require_browser_recheck=True,
                        browser_baseline_capture=_passing_capture, token_budget=100)
    assert owner_result.succeeded, owner_result.reason
    owner = DeliverySliceJournal(slice_project[2], "owner-op").load(required=True)
    return_entry = prepare_browser_continuation(
        kind="return", predecessors=[source_ref, JournalRef("owner-op", journal_sha256(owner))],
        evidence_root=slice_project[2], candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
        input_fingerprint=source["input_fingerprint"], token_limit=100,
    )
    assert return_entry["allowance"] == dict(repair_attempt=0, browser_requests_in_round=1,
                                           tokens_consumed=35, usage_known=True, token_limit=100)
    def script(assignment, payload, root):
        if assignment["step"] == "implementer" and mutates_without_recapture:
            (root / "app.py").write_text("changed after capture\n")
    return_executor = ScriptedExecutor(script)
    returned = _run(slice_project, return_executor, operation_id="return-op", repair_task_id="T-011",
                    continuation=return_entry, browser_baseline_capture=_passing_capture, token_budget=100)
    if mutates_without_recapture:
        assert not returned.succeeded and "recapture_required" in returned.reason
        assert len(return_executor.calls) == 1
        return
    assert returned.succeeded and returned.task_ids == ["T-011"], returned.reason
    result = DeliverySliceJournal(slice_project[2], "return-op").load(required=True)
    assert result["browser_checks"][0]["request_ordinal"] == 2
    assert owner["browser_checks"][0]["receipt"] != result["browser_checks"][0]["receipt"]
    return_capture = json.loads(Path(result["browser_checks"][0]["receipt"]["path"]).read_text())
    assert return_capture["task_id"] == "T-011"
    assert return_executor.calls[0][1]["tool_read_roots"]
    assert not return_executor.calls[1][1]["tool_read_roots"] == return_executor.calls[0][1]["tool_read_roots"]
    assert path.read_bytes() == before
    assert continuation_allowance(result, token_limit=100).tokens_consumed == 63


@pytest.mark.parametrize("title,expected_calls,expected_status", [
    ("[echelon:E2E-START-002] startup", 5, "done"),
    ("untagged", 1, "blocked"),
    ("[echelon:E2E-START-002,CT-NET-001] mixed", 1, "blocked"),
])
def test_failed_capture_keeps_same_owner_and_blocks_ambiguous_routing(slice_project, title, expected_calls, expected_status):
    _tasks(slice_project[1])
    def request(assignment, payload, root):
        if len(executor.calls) == 1:
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Capture needed",
                           browser_evidence_request={"purpose": "baseline_capture"})
    executor = ScriptedExecutor(request)
    result = _run(slice_project, executor, repair_task_id="T-011", resolve_browser_owner=_resolver(slice_project),
                  browser_baseline_capture=lambda path: _capture(product_evidence_fingerprint(Path(path)), title=title))
    assert result.status == expected_status, result.reason
    assert len(executor.calls) == expected_calls and result.browser_repair_request is None


@pytest.mark.parametrize("limit", [None, 7, 100])
def test_refresh_preserves_finite_carried_token_limit(slice_project, limit):
    from harness.delivery_browser_handoff import JournalRef, journal_sha256, prepare_browser_continuation
    from harness.delivery_slice_runner import _candidate_fingerprint
    _, parent, _ = _old_pending(slice_project)
    entry = prepare_browser_continuation(
        kind="refresh", predecessors=[JournalRef("source-op", journal_sha256(parent))],
        evidence_root=slice_project[2], candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
        input_fingerprint=parent["input_fingerprint"], token_limit=7,
    )
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, operation_id="refresh-op", repair_task_id="T-011",
                  continuation=entry, token_budget=limit,
                  browser_baseline_capture=lambda _: pytest.fail("spent budget must not capture"))
    assert result.reason == "delivery_slice_budget_exhausted", result.reason
    assert not executor.calls


def test_two_completed_v2_requests_refresh_once_without_rewriting(slice_project):
    import copy
    from harness.delivery_browser_handoff import JournalRef, journal_sha256, prepare_browser_continuation
    from harness.delivery_slice_runner import _candidate_fingerprint
    from harness.delivery_slice_journal import DeliverySliceJournal
    path, parent, _ = _old_pending(slice_project)
    duplicate = copy.deepcopy(parent["records"][-1])
    duplicate.pop("browser_evidence")
    duplicate["assignment"]["dispatch_id"] = "completed-duplicate"
    duplicate["assignment"]["candidate_fingerprint"] = duplicate["candidate_after"]
    duplicate["result"].update(duplicate["assignment"])
    duplicate["raw_result"] = json.dumps(duplicate["result"])
    parent["records"].append(duplicate)
    with DeliverySliceJournal(slice_project[2], "source-op") as journal:
        journal.save(parent)
    before = path.read_bytes()
    entry = prepare_browser_continuation(
        kind="refresh", predecessors=[JournalRef("source-op", journal_sha256(parent))],
        evidence_root=slice_project[2], candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
        input_fingerprint=parent["input_fingerprint"], token_limit=100,
    )
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, operation_id="refresh-op", repair_task_id="T-011",
                  continuation=entry, token_budget=100, resolve_browser_owner=_resolver(slice_project),
                  browser_baseline_capture=lambda path: _capture(product_evidence_fingerprint(Path(path))))
    assert result.status == "browser_repair_required", result.reason
    assert not executor.calls and path.read_bytes() == before
    current = DeliverySliceJournal(slice_project[2], "refresh-op").load(required=True)
    assert current["browser_checks"][0]["request_ordinal"] == 3
    assert entry["allowance"]["tokens_consumed"] == 14


@pytest.mark.parametrize("damage", ["missing_receipt", "structured_receipt", "pending_dispatch"])
def test_refresh_requires_authenticated_old_completed_evidence(slice_project, damage):
    from harness.delivery_browser_handoff import JournalRef, journal_sha256, prepare_browser_continuation
    from harness.delivery_slice_runner import _candidate_fingerprint
    from harness.delivery_slice import DeliverySliceError
    from tests.unit.test_delivery_browser_handoff import _pending
    path, parent, _ = (_pending if damage == "structured_receipt" else _old_pending)(slice_project)
    if damage == "missing_receipt":
        Path(parent["records"][-1]["browser_evidence"]["path"]).unlink()
    elif damage == "pending_dispatch":
        record = parent["records"][-1]
        record.pop("browser_evidence")
        for key in ("result", "raw_result", "token_usage", "candidate_after"):
            record[key] = None
        path.write_text(json.dumps(parent))
    with pytest.raises((DeliverySliceError, OSError, ValueError)):
        prepare_browser_continuation(
            kind="refresh", predecessors=[JournalRef("source-op", journal_sha256(parent))],
            evidence_root=slice_project[2], candidate_fingerprint=_candidate_fingerprint(*slice_project[:2]),
            input_fingerprint=parent["input_fingerprint"], token_limit=100,
        )


def test_unknown_capture_intents_exhaust_without_reset_or_free_retry(slice_project, monkeypatch):
    from harness.delivery_slice_journal import DeliverySliceJournal
    _tasks(slice_project[1])
    original = DeliverySliceJournal.save
    def save(journal, data):
        original(journal, data)
        checks = data.get("browser_checks", [])
        if checks and checks[-1]["receipt"] is None:
            raise ProcessLost()
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    executor = ScriptedExecutor()
    for _ in range(4):
        with pytest.raises(ProcessLost):
            _run(slice_project, executor, repair_task_id="T-012", require_browser_recheck=True,
                 browser_baseline_capture=lambda _: pytest.fail("crash precedes external capture"))
    result = _run(slice_project, executor, repair_task_id="T-012", require_browser_recheck=True,
                  browser_baseline_capture=lambda _: pytest.fail("capture allowance exhausted"))
    assert result.reason == "delivery_browser_capture_limit" and not result.succeeded
    assert len(executor.calls) == 4 and result.token_usage == 28
    data = DeliverySliceJournal(slice_project[2], "active").load(required=True)
    assert [check["request_ordinal"] for check in data["browser_checks"]] == [1, 2, 3, 4]
