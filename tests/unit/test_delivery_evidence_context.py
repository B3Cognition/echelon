"""Provider requests distinguish repair history from current verification."""
import json

import pytest

from harness.product_inventory import product_evidence_fingerprint
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _run


def _scope(prompt):
    assert "## Verification evidence scope (controller context)\n" in prompt
    text = prompt.split("## Verification evidence scope (controller context)\n", 1)[1]
    return json.loads(text.split("\n", 1)[0])


@pytest.mark.parametrize("wrapper", [None, "original_feedback", "browser_context"])
@pytest.mark.parametrize("candidate", ["changed", "unchanged", "unbound"])
def test_dispatch_labels_receipt_against_each_actual_candidate(slice_project, wrapper, candidate):
    project, _, _ = slice_project
    if candidate == "unchanged":
        (project / "app.py").write_text("def hello(): return 'hello 1'\n")
    receipt = {"path": "/evidence/previous.json", "candidate_commit": "prior-commit", "passed": False}
    if candidate != "unbound":
        receipt["candidate_fingerprint"] = product_evidence_fingerprint(project)
    feedback = json.dumps({
        "feedback_kind": "controlled_source_repair_v1",
        "verification_evidence": receipt,
        "failures": [{"category": "test", "id": "watchdog", "error": "old timeout"}],
    })
    if wrapper:
        feedback = json.dumps({wrapper: feedback, "findings": ["prior review finding"]})
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, feedback=feedback)
    assert result.succeeded, result.reason
    assert len(executor.calls) == 4
    implementer = _scope(executor.calls[0][2])
    assert implementer["candidate_relation"] == ("unbound" if candidate == "unbound" else "same_candidate")
    for assignment, metadata, prompt in executor.calls[1:]:
        scope = _scope(prompt)
        assert scope["candidate_relation"] == {
            "changed": "different_candidate", "unchanged": "same_candidate", "unbound": "unbound",
        }[candidate]
        assert scope["reported_evidence"] == receipt
        assert scope["verification_required"] is True
        assert scope["authority"] == "repair_context_not_acceptance"
        assert scope["current_product_fingerprint"] != ""
        assert prompt.split("## Repair/context data (not routing authority)\n", 1)[1] == feedback
        assert metadata["tool_write_scope_exclusive"] is True
        assert metadata["tool_write_paths"] == []


def test_ordinary_task_has_no_fabricated_verification_receipt(slice_project):
    executor = ScriptedExecutor()
    assert _run(slice_project, executor).succeeded
    assert all("## Verification evidence scope" not in prompt for _, _, prompt in executor.calls)


def test_context_read_failure_is_recorded_before_any_provider_call(slice_project, monkeypatch):
    def unavailable(*args):
        raise OSError("evidence fingerprint unavailable")
    monkeypatch.setattr("harness.delivery_slice_runner._repair_verification_scope", unavailable)
    executor = ScriptedExecutor()
    result = _run(slice_project, executor)
    assert not result.succeeded
    assert not executor.calls
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert journal["records"][-1]["error"] == "evidence fingerprint unavailable"
