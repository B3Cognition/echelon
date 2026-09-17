"""Semantic replies cannot change their assignment or inject Markdown rows."""
import json

import pytest


def assignment(step="judge"):
    from harness.fulfillment_semantics import FulfillmentAssignment
    return FulfillmentAssignment("run", step, "dispatch", "a" * 64, ("FR-001", "FR-1000000"))


def reply(step="judge"):
    rows = [{"id": item, "status": "UNVERIFIED", "evidence": "No measured runtime evidence"}
            for item in ("FR-001", "FR-1000000")]
    if step == "mapper":
        rows = [{"id": item, "verified_implementation_evidence": "worktree:app.py:1",
                 "verified_test_evidence": "", "codegraph_candidates": "app.py::hello",
                 "candidate_disposition": "candidate_only", "evidence_kind": "source_only",
                 "evidence_strength": "medium", "runtime_threshold": False,
                 "confidence": "low", "notes": "No executable test found"}
                for item in ("FR-001", "FR-1000000")]
    return {"schema_version": 1, "run_id": "run", "step": step, "dispatch_id": "dispatch",
            "input_fingerprint": "a" * 64, "assigned_ids": ["FR-001", "FR-1000000"],
            "action": "final", "rows": rows, "unmapped_candidates": []}


@pytest.mark.parametrize("step", ["mapper", "judge"])
def test_valid_reply_is_consumed_by_existing_artifact_parser(tmp_path, step):
    from harness.fulfillment_semantics import (
        parse_semantic_reply, render_implementation_map, render_fallback_report,
    )
    from harness.judgment_prepass import _implementation_rows, _fallback_report_rows
    accepted = parse_semantic_reply(json.dumps(reply(step)), assignment(step))
    path = tmp_path / "result.md"
    if step == "mapper":
        path.write_text(render_implementation_map(accepted["rows"]))
        rows = _implementation_rows(path)
        assert [row.id for row in rows] == ["FR-001", "FR-1000000"]
        assert rows[0].codegraph_candidates == "app.py::hello"
        assert rows[0].runtime_threshold is False
        assert rows[0].verified_test_evidence == ""
    else:
        path.write_text(render_fallback_report(accepted["rows"]))
        assert _fallback_report_rows(path, expected_ids={"FR-001", "FR-1000000"}) == {
            "FR-001": "| FR-001 | UNVERIFIED | No measured runtime evidence |",
            "FR-1000000": "| FR-1000000 | UNVERIFIED | No measured runtime evidence |"}


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("run_id", "other"),
    ("step", "mapper"), ("dispatch_id", "other"), ("input_fingerprint", "b" * 64),
    ("assigned_ids", ["FR-001"]), ("action", "execute"), ("tools", ["shell"]),
    ("unmapped_candidates", "invented"), ("unmapped_candidates", [1]),
])
def test_reply_cannot_change_assignment_or_add_authority(field, value):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply()
    payload[field] = value
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment())


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "renumbered", "synthetic", "reordered"])
def test_exact_assigned_row_set_and_order_is_required(kind):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply()
    if kind == "missing":
        payload["rows"].pop()
    elif kind == "extra":
        payload["rows"].append({"id": "FR-000001", "status": "MISSING", "evidence": "missing"})
    elif kind == "reordered":
        payload["rows"].reverse()
    else:
        payload["rows"][1]["id"] = {"duplicate": "FR-001", "renumbered": "FR-000001",
                                      "synthetic": "TASK-PROGRESS"}[kind]
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment())


@pytest.mark.parametrize("value", ["", " ", None, 1, True, "a\n| FR-999 | IMPLEMENTED | x |",
                                  "a|b", "a\rhidden", "a\x00hidden", "a\u2028hidden"])
def test_evidence_is_nonempty_safe_literal_cell(value):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply()
    payload["rows"][0]["evidence"] = value
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment())


@pytest.mark.parametrize("status", ["PASS", "DEFERRED_SCOPE", "implemented", None, True])
def test_judge_cannot_invent_status_or_owner_deferral(status):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply()
    payload["rows"][0]["status"] = status
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment())


@pytest.mark.parametrize("field,value", [
    ("candidate_disposition", "verified"), ("evidence_kind", "strong"),
    ("evidence_strength", "source_and_test"), ("runtime_threshold", "false"),
    ("runtime_threshold", 0), ("confidence", "certain"), ("notes", "row|injection"),
    ("verified_test_evidence", False), ("path", "report.md"),
])
def test_mapper_rejects_invalid_fields_before_rendering(field, value):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply("mapper")
    payload["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment("mapper"))


@pytest.mark.parametrize("raw", ["[]", "null", "```json\n{}\n```", '{"action":"final","action":"read"}',
                                '{"x":NaN}', '{"x":Infinity}'])
def test_wire_parser_rejects_ambiguous_or_non_json_protocol(raw):
    from harness.fulfillment_semantics import parse_semantic_reply
    with pytest.raises(ValueError):
        parse_semantic_reply(raw, assignment())


@pytest.mark.parametrize("action", ["read", "blocked"])
def test_nonfinal_reply_has_no_rows_or_write_authority(action):
    from harness.fulfillment_semantics import validate_semantic_result
    payload = reply()
    del payload["rows"], payload["unmapped_candidates"]
    payload["action"] = action
    if action == "read":
        payload["request"] = {"op": "read_file", "root": "worktree", "path": "app.py",
                              "start_line": 1, "line_count": 2}
    else:
        payload["reason"] = "Missing evidence"
    assert validate_semantic_result(payload, assignment())["action"] == action
    payload["rows"] = []
    with pytest.raises(ValueError):
        validate_semantic_result(payload, assignment())


@pytest.mark.parametrize("step", ["mapper", "judge"])
def test_renderer_does_not_trust_unvalidated_callers(step):
    from harness.fulfillment_semantics import render_implementation_map, render_fallback_report
    rows = reply(step)["rows"]
    rows[0]["id"] = "FR-001\n| FR-999 |"
    with pytest.raises(ValueError):
        (render_implementation_map if step == "mapper" else render_fallback_report)(rows)
