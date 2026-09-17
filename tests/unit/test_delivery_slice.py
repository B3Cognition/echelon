"""Scope and verdict mistakes must never turn into accepted delivery work."""
import json
from pathlib import Path

import pytest


def _tasks(tmp_path, rows):
    (tmp_path / "tasks.md").write_text("# Tasks\n" + rows, encoding="utf-8")
    return tmp_path


def test_selects_first_dependency_ready_task_not_first_unfinished_row(tmp_path):
    from harness.delivery_slice import select_delivery_task
    spec = _tasks(tmp_path,
        "- [ ] T-002 complexity=standard phase=build req=FR-2 depends=T-001\n"
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n")
    assert select_delivery_task(spec) == "T-001"


def test_scope_and_completed_dependency_are_respected(tmp_path):
    from harness.delivery_slice import select_delivery_task
    spec = _tasks(tmp_path,
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
        "- [x] T-002 complexity=standard phase=build req=FR-2 depends=none\n"
        "- [ ] T-003 complexity=standard phase=build req=FR-3 depends=T-002\n")
    assert select_delivery_task(spec, allowed_task_ids={"T-003"}) == "T-003"
    assert select_delivery_task(spec, repair_task_id="T-002") == "T-002"


def test_canonical_row_with_trailing_whitespace_is_selected(tmp_path):
    from harness.delivery_slice import select_delivery_task
    spec = _tasks(tmp_path, "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none  \n")
    assert select_delivery_task(spec) == "T-001"


@pytest.mark.parametrize("rows,scope,repair", [
    ("", None, None),
    ("- [ ] T-001 broken row\n", None, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=T-999\n", None, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=T-001\n", None, None),
    ("- [x] T-001 complexity=standard phase=build req=FR-1 depends=none\n", None, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n", set(), None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n", {"T-999"}, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n", {"T-001"}, "T-999"),
    ("- [x] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
     "  **Status:** DEGRADED\n"
     "- [ ] T-002 complexity=standard phase=build req=FR-2 depends=T-001\n", {"T-002"}, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=T-002\n"
     "- [ ] T-002 complexity=standard phase=build req=FR-2 depends=T-001\n", None, None),
    ("- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n" * 2, None, None),
])
def test_invalid_or_unready_scope_is_refused(tmp_path, rows, scope, repair):
    from harness.delivery_slice import DeliverySliceError, select_delivery_task
    with pytest.raises(DeliverySliceError):
        select_delivery_task(_tasks(tmp_path, rows), allowed_task_ids=scope, repair_task_id=repair)


def _assignment():
    from harness.delivery_slice import DeliveryAssignment
    return DeliveryAssignment("d-1", "spec_guard", "T-001", "candidate", "inputs")


def _response(**changes):
    payload = dict(schema_version=1, dispatch_id="d-1", step="spec_guard", task_id="T-001",
                   candidate_fingerprint="candidate", input_fingerprint="inputs",
                   verdict="PASS", summary="Checked source against criteria", findings=[])
    payload.update(changes)
    return json.dumps(payload)


def test_bound_passing_result_is_accepted():
    from harness.delivery_slice import validate_delivery_result
    assert validate_delivery_result(_response(), _assignment())["verdict"] == "PASS"


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"schema_version": 2}, {"dispatch_id": "stale"},
    {"step": "test_guardian"}, {"task_id": "T-002"}, {"candidate_fingerprint": "old"},
    {"input_fingerprint": "old"}, {"verdict": "DEGRADED"}, {"verdict": "SKIP"},
    {"verdict": "WARN"}, {"verdict": "APPROVED"}, {"summary": ""},
    {"findings": ["unfixed bug"]}, {"findings": {}}, {"extra": "unexpected"},
    {"verdict": "FAIL", "findings": []}, {"summary": 42},
])
def test_invalid_result_cannot_approve(changes):
    from harness.delivery_slice import DeliverySliceError, validate_delivery_result
    with pytest.raises(DeliverySliceError):
        validate_delivery_result(_response(**changes), _assignment())


@pytest.mark.parametrize("raw", ["done", "{}", "[]", "```json\n{}\n```", "x" * 100001],
                         ids=["text", "empty", "array", "fence", "oversized"])
def test_no_free_text_or_legacy_result_fallback(raw):
    from harness.delivery_slice import DeliverySliceError, validate_delivery_result
    with pytest.raises(DeliverySliceError):
        validate_delivery_result(raw, _assignment())
