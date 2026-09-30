"""Browser failures retain identity without changing delivery ownership or gates."""
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness import browser_baseline_evidence as receipts
from harness.delivery_slice import DeliverySliceError, select_delivery_repair_task
from harness.product_inventory import product_evidence_fingerprint
from harness.provider import SandboxHandle
from harness.visual_ralph import BrowserBaselineCapture, VisualRalphController
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, _run, slice_project
from tests.unit.test_visual_ralph import _exec_result, _make_config


TITLE = "[echelon:CT-NET-001] production runtime requests only same-origin bundled content"
ERROR = "Unexpected runtime requests: http://127.0.0.1:4174/assets/index-EBFWlY2n.js"


def _verification(title=TITLE, *, extra_titles=(), status="failed", error=ERROR,
                  secret="runtime-secret-value"):
    # Only the external process is replaced; parsing and failure construction are real.
    provider = MagicMock()
    provider.exec.return_value = _exec_result(exit_code=1, stdout=json.dumps({
        "suites": [{"specs": [{
            "title": name, "file": "tests/e2e/runtime-network.spec.ts",
            "tests": [{"projectName": "chromium", "expectedStatus": "passed",
                       "results": [{"status": status, "error": {"message": error}}]}],
        } for name in (title, *extra_titles)]}],
    }))
    controller = VisualRalphController(provider=provider, config=_make_config(), spec_id="001")
    controller._runtime_env = {"SERVICE_TOKEN": secret}
    return controller._exec_visual_verify(SandboxHandle(id="browser", session_id="test"))


def _capture(candidate="candidate-a", **kwargs):
    return BrowserBaselineCapture(candidate, _verification(**kwargs), {
        "tests/e2e/degradation.spec.ts-snapshots/pitch-chromium.png": b"proposal",
    }, "Browser tests failed")


def _roundtrip(tmp_path, capture=None):
    bindings = dict(operation_id="operation-1", task_id="T-011", input_fingerprint="inputs-a")
    ref = receipts.write_browser_baseline_receipt(
        evidence_root=tmp_path, capture=capture or _capture(), **bindings,
    )
    observation = receipts.read_browser_baseline_observation(
        ref, candidate_fingerprint="candidate-a", **bindings,
    )
    return ref, observation, bindings


def _tasks(spec):
    (spec / "tasks.md").write_text(
        "- [x] T-011 complexity=complex phase=integration req=FR-1 depends=none\n"
        "  **Status:** DONE\n  **Test Tasks:**\n"
        "  - [x] Implement `E2E-START-002`.\n"
        "- [x] T-012 complexity=standard phase=release req=FR-2 depends=T-011\n"
        "  **Status:** DONE\n  **Test Tasks:**\n"
        "  - [x] Implement `CT-NET-001`.\n"
    )


def test_browser_failure_roundtrip_resolves_actual_case_to_other_task(tmp_path):
    _tasks(tmp_path)
    ref, observation, _ = _roundtrip(tmp_path / "evidence")
    failures = observation.verification_failures
    assert failures == [{
        "category": "playwright_test", "id": TITLE, "error": ERROR,
        "details": {
            "test_id": f"tests/e2e/runtime-network.spec.ts::{TITLE}::chromium::0",
            "file": "tests/e2e/runtime-network.spec.ts", "project": "chromium",
            "failed_test_case_ids": ["CT-NET-001"], "unidentified_test_failures": 0,
        },
    }]
    assert observation.verification_passed is False
    assert json.loads(ref.path.read_text())["verification_failures"] == failures
    assert select_delivery_repair_task(tmp_path, {"failures": failures}, {"T-011", "T-012"}) == {
        "task_id": "T-012", "failed_test_case_ids": ["CT-NET-001"],
        "reason": "unique_test_case_owner",
    }


@pytest.mark.parametrize("title", [
    "untagged failure", "[echelon:CT-NET-001] [echelon:CT-NET-002] ambiguous",
    "[echelon:invalid] invalid", "[echelon:CT-NET-001 missing bracket",
])
def test_unknown_failure_is_not_hidden_by_an_identified_failure(tmp_path, title):
    _tasks(tmp_path)
    _, observation, _ = _roundtrip(tmp_path / "evidence", _capture(extra_titles=(title,)))
    assert len(observation.verification_failures) == 2
    assert observation.verification_failures[1]["details"]["unidentified_test_failures"] == 1
    with pytest.raises(DeliverySliceError, match="unidentified test failures"):
        select_delivery_repair_task(tmp_path, {"failures": observation.verification_failures}, None)


def test_skipped_case_remains_a_failure_with_identity(tmp_path):
    _, observation, _ = _roundtrip(tmp_path, _capture(status="skipped"))
    assert observation.verification_passed is False
    assert observation.verification_failures[0]["id"].startswith("playwright_skipped::")
    assert observation.verification_failures[0]["details"]["failed_test_case_ids"] == ["CT-NET-001"]


def test_structured_error_redacts_runtime_secrets_before_persistence(tmp_path):
    ref, observation, _ = _roundtrip(tmp_path, _capture(error="request used runtime-secret-value"))
    assert "runtime-secret-value" not in ref.path.read_text()
    assert observation.verification_failures[0]["error"] == "request used [REDACTED:environment]"


def test_secret_in_case_tag_is_not_persisted_or_used_as_repair_identity(tmp_path):
    ref, observation, _ = _roundtrip(tmp_path, _capture(
        title="[echelon:CT-NET-001,CT-RUNTIME-SECRET-VALUE] request",
        secret="RUNTIME-SECRET-VALUE",
    ))
    assert "RUNTIME-SECRET-VALUE" not in ref.path.read_text()
    details = observation.verification_failures[0]["details"]
    assert details["failed_test_case_ids"] == []
    assert details["unidentified_test_failures"] == 1


def test_error_mentions_never_supply_missing_test_identity(tmp_path):
    _, observation, _ = _roundtrip(tmp_path, _capture(title="untagged test", error=TITLE))
    details = observation.verification_failures[0]["details"]
    assert details["failed_test_case_ids"] == []
    assert details["unidentified_test_failures"] == 1


def test_terminal_tag_uses_shared_case_grammar(tmp_path):
    _, observation, _ = _roundtrip(tmp_path, _capture(title="network [echelon:CT-NET-001]"))
    assert observation.verification_failures[0]["details"]["failed_test_case_ids"] == ["CT-NET-001"]


def test_passing_capture_preserves_empty_failures(tmp_path):
    capture = _capture()
    capture.verification.passed = True
    capture.verification.failures.clear()
    _, observation, _ = _roundtrip(tmp_path, capture)
    assert observation.verification_passed is True
    assert observation.verification_failures == []


def test_inconsistent_passing_capture_is_rejected_on_write_and_read(tmp_path):
    ref, _, bindings = _roundtrip(tmp_path)
    capture = _capture()
    capture.verification.passed = True
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="failure"):
        receipts.write_browser_baseline_receipt(evidence_root=tmp_path, capture=capture, **bindings)
    payload = json.loads(ref.path.read_text())
    payload["verification_passed"] = True
    ref = _rewrite_receipt(ref, payload)
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="failure"):
        receipts.read_browser_baseline_observation(ref, candidate_fingerprint="candidate-a", **bindings)


def _rewrite_receipt(ref, payload):
    payload.pop("receipt_sha256", None)
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    payload["receipt_sha256"] = digest
    ref.path.write_text(json.dumps(payload))
    return receipts.BrowserBaselineEvidenceRef(ref.path, digest)


def test_older_receipt_is_read_only_and_does_not_infer_identity_from_diagnostic(tmp_path):
    ref, _, bindings = _roundtrip(tmp_path)
    payload = json.loads(ref.path.read_text())
    payload.pop("verification_failures", None)
    payload.update(schema_version=2, verification_diagnostic=TITLE + ": " + ERROR)
    ref = _rewrite_receipt(ref, payload)
    original = ref.path.read_bytes()
    observation = receipts.read_browser_baseline_observation(ref, candidate_fingerprint="candidate-a", **bindings)
    assert observation.verification_failures is None  # unavailable, not an empty/passing list
    assert observation.verification_passed is False
    receipts.validate_historical_browser_baseline(ref, **bindings)
    assert ref.path.read_bytes() == original


def test_modified_structured_failure_fails_digest_validation(tmp_path):
    ref, _, bindings = _roundtrip(tmp_path)
    payload = json.loads(ref.path.read_text())
    payload["verification_failures"][0]["error"] = "different error"
    ref.path.write_text(json.dumps(payload))
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="digest"):
        receipts.read_browser_baseline_observation(ref, candidate_fingerprint="candidate-a", **bindings)


@pytest.mark.parametrize("failures", [None, {}, [{}], [{
    "category": "not-a-category", "id": "test", "error": "error", "details": {},
}]])
def test_malformed_structured_failure_is_rejected_even_with_valid_digest(tmp_path, failures):
    ref, _, bindings = _roundtrip(tmp_path)
    payload = json.loads(ref.path.read_text())
    payload["verification_failures"] = failures
    ref = _rewrite_receipt(ref, payload)
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="failure"):
        receipts.read_browser_baseline_observation(ref, candidate_fingerprint="candidate-a", **bindings)


def test_oversized_failures_are_rejected_not_silently_dropped(tmp_path, monkeypatch):
    ref, _, bindings = _roundtrip(tmp_path)
    monkeypatch.setattr(receipts, "MAX_BROWSER_VERIFICATION_BYTES", 50, raising=False)
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="failure"):
        receipts.write_browser_baseline_receipt(evidence_root=tmp_path, capture=_capture(), **bindings)
    with pytest.raises(receipts.BrowserBaselineEvidenceError, match="failure"):
        receipts.read_browser_baseline_observation(ref, candidate_fingerprint="candidate-a", **bindings)


@pytest.mark.parametrize("secret_tag", [False, True])
def test_browser_failure_replay_preserves_feedback_without_switching_task(slice_project, secret_tag):
    root, spec, evidence = slice_project
    _tasks(spec)
    tasks_before = (spec / "tasks.md").read_bytes()
    stop = False

    def request(assignment, payload, _root):
        payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need browser evidence",
                       browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        nonlocal stop
        stop = True
        kwargs = ({"title": "[echelon:CT-RUNTIME-SECRET-VALUE] request",
                   "secret": "RUNTIME-SECRET-VALUE"} if secret_tag else {})
        return _capture(product_evidence_fingerprint(Path(worktree)), **kwargs)

    first = _run(slice_project, ScriptedExecutor(request), repair_task_id="T-011",
                 operation_id="capture-op", browser_baseline_capture=capture, stop_requested=lambda: stop)
    assert first.reason == "delivery_slice_cancelled"
    receipt_path = next(evidence.rglob("receipt.json"))
    before = receipt_path.read_bytes()

    def inspect(assignment, payload, _root):
        payload.update(verdict="BLOCKED", summary="Inspect feedback only")

    executor = ScriptedExecutor(inspect)
    resumed = _run(slice_project, executor, repair_task_id="T-011", operation_id="capture-op",
                   journal_required=True, browser_baseline_capture=lambda _: pytest.fail("must not recapture"))
    feedback = json.loads(executor.calls[0][2].split("## Repair/context data (not routing authority)\n")[1])
    failures = feedback["browser_verification"]["failures"]
    assert failures[0]["error"] == ERROR
    if secret_tag:
        assert "RUNTIME-SECRET-VALUE" not in executor.calls[0][2]
        with pytest.raises(DeliverySliceError, match="unidentified test failures"):
            select_delivery_repair_task(spec, {"failures": failures}, None)
    else:
        assert select_delivery_repair_task(spec, {"failures": failures}, None)["task_id"] == "T-012"
    assert [assignment["task_id"] for assignment, _, _ in executor.calls] == ["T-011"]
    assert resumed.status == "blocked" and not resumed.task_ids
    assert (spec / "tasks.md").read_bytes() == tasks_before
    assert receipt_path.read_bytes() == before
