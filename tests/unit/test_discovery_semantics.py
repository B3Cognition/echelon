"""Producer replies cannot expand a host assignment or grant write authority."""
import json
from dataclasses import replace

import pytest


def assignment(step="propose"):
    from harness.discovery_semantics import DiscoveryAssignment
    return DiscoveryAssignment("op", "turn", "game", "run", step, "a" * 64,
        ("unknowns.md",), (("U-001", "1"),),
        ("U-001", "U-1000000") if step == "review" else ())


def reply(step="propose"):
    value = {**assignment(step).identity(), "action": "final"}
    if step == "propose":
        value.update(new_subjects=[dict(key="lighting", kind="U", subject="Lighting choice", caption="Lighting choice")],
                     revisions=[dict(id="U-001", expected_revision="1")])
    elif step == "author":
        value["artifacts"] = {"unknowns.md": "### U-001: Question\r\nCafé?\r\n"}
    else:
        value.update(verdict="accept", reason="Meaning preserved.", assessments=[
            dict(id=item, verdict="accept", reason="Same subject.", evidence=["baseline:unknowns.md:1"])
            for item in ("U-001", "U-1000000")])
    return value


@pytest.mark.parametrize("step", ["propose", "author", "review"])
def test_closed_reply_preserves_semantic_content_and_detaches(step):
    from harness.discovery_semantics import parse_discovery_reply, validate_discovery_reply
    original = reply(step)
    result = parse_discovery_reply(json.dumps(original), assignment(step))
    assert result == original
    accepted = validate_discovery_reply(original, assignment(step))
    if step == "author":
        original["artifacts"]["unknowns.md"] = "changed"
        assert accepted["artifacts"]["unknowns.md"] == "### U-001: Question\r\nCafé?\r\n"
    elif step == "propose":
        original["new_subjects"][0]["subject"] = "changed"
        assert accepted["new_subjects"][0]["subject"] == "Lighting choice"
    else:
        original["assessments"][0]["evidence"].clear()
        assert accepted["assessments"][0]["evidence"] == ["baseline:unknowns.md:1"]


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", "1"), ("schema_version", 2),
    ("operation_id", "other"), ("dispatch_id", "other"), ("spec_id", "other"),
    ("run_id", "other"), ("step", "author"), ("input_fingerprint", "b" * 64),
    ("artifact_paths", ["other.md"]), ("editable_revisions", []),
    ("assigned_ids", ["U-999"]), ("action", "publish"), ("state_updates", {}),
])
def test_reply_cannot_change_assignment_or_add_authority(field, value):
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply()
    payload[field] = value
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment())


@pytest.mark.parametrize("field,value", [
    ("key", "U-000001"), ("key", "../new"), ("key", ""), ("kind", "FR"),
    ("kind", []), ("subject", ""), ("subject", "new\nsubject"),
    ("caption", "### new\nheading"), ("caption", "\ud800"), ("allocate", True),
])
def test_new_subjects_are_handles_and_plain_text_not_ids_or_commands(field, value):
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply()
    payload["new_subjects"][0][field] = value
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment())


@pytest.mark.parametrize("change", ["duplicate_key", "duplicate_revision", "wrong_revision", "invented_id", "alias"])
def test_proposal_cannot_duplicate_or_rebind_existing_definitions(change):
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply()
    if change == "duplicate_key":
        payload["new_subjects"] *= 2
    elif change == "duplicate_revision":
        payload["revisions"] *= 2
    elif change == "wrong_revision":
        payload["revisions"][0]["expected_revision"] = "2"
    else:
        payload["revisions"][0]["id"] = "U-999" if change == "invented_id" else "U-000001"
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment())


def test_proposal_order_is_canonical_without_changing_meaning():
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply()
    payload["new_subjects"].append(dict(key="camera", kind="U", subject="Camera angle", caption="Camera angle"))
    accepted = validate_discovery_reply(payload, assignment())
    assert [item["key"] for item in accepted["new_subjects"]] == ["camera", "lighting"]
    assert accepted["new_subjects"][1]["subject"] == "Lighting choice"


@pytest.mark.parametrize("artifacts", [{}, {"../unknowns.md": "x"}, {"unknowns.md": "x", "state.json": "{}"},
    {"unknowns.md": None}, {"unknowns.md": "x\x00y"}, {"unknowns.md": "\ud800"}])
def test_author_returns_only_exact_assigned_artifacts(artifacts):
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply("author")
    payload["artifacts"] = artifacts
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment("author"))


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "contradiction", "invalid_verdict", "no_evidence", "bad_evidence"])
def test_review_cannot_omit_subjects_or_hide_rejection(change):
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply("review")
    if change == "missing":
        payload["assessments"].pop()
    elif change == "extra":
        payload["assessments"].append(dict(payload["assessments"][0], id="U-999"))
    elif change == "duplicate":
        payload["assessments"][1]["id"] = "U-001"
    elif change == "contradiction":
        payload["assessments"][0]["verdict"] = "reject"
    elif change == "invalid_verdict":
        payload["verdict"] = "PASS"
    else:
        payload["assessments"][0]["evidence"] = [] if change == "no_evidence" else [False]
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment("review"))


@pytest.mark.parametrize("action", ["read", "blocked"])
def test_intermediate_reply_has_no_final_result_authority(action):
    from harness.discovery_semantics import validate_discovery_reply
    payload = {**assignment().identity(), "action": action}
    if action == "read":
        payload["request"] = {"op": "read_file", "root": "baseline", "path": "unknowns.md", "start_line": 1, "line_count": 5}
    else:
        payload["reason"] = "Missing baseline."
    assert validate_discovery_reply(payload, assignment())["action"] == action
    payload["new_subjects"] = []
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment())


@pytest.mark.parametrize("raw", ["[]", "null", "```json\n{}\n```", '{"x":1,"x":2}', '{"x":NaN}',
    '{"x":Infinity}', "[" * 2000 + "]" * 2000, "\ud800", " " * (256 * 1024 + 1)])
def test_malformed_ambiguous_and_oversize_wire_is_bounded(raw):
    from harness.discovery_semantics import parse_discovery_reply
    with pytest.raises(ValueError):
        parse_discovery_reply(raw, assignment())


@pytest.mark.parametrize("field,value", [("artifact_paths", ("state.json",)), ("artifact_paths", ("unknowns.md", "unknowns.md")),
    ("artifact_paths", ["unknowns.md"]), ("step", "execute"), ("input_fingerprint", "not-a-hash"),
    ("editable_revisions", (("FR-001", "1"),)), ("editable_revisions", (("U-001", 1),)),
    ("editable_revisions", (("U-001", "01"),)), ("assigned_ids", ("U-001", "U-001"))])
def test_invalid_host_assignment_cannot_be_serialized(field, value):
    with pytest.raises(ValueError):
        replace(assignment(), **{field: value}).identity()


def test_unbounded_literal_ids_are_not_truncated():
    from harness.discovery_semantics import validate_discovery_reply
    label = "U-" + "9" * 5000
    bound = replace(assignment(), editable_revisions=((label, "1"),))
    payload = {**bound.identity(), "action": "final", "new_subjects": [],
               "revisions": [dict(id=label, expected_revision="1")]}
    assert validate_discovery_reply(payload, bound)["revisions"][0]["id"] == label


def test_direct_validator_does_not_coerce_tuple_to_wire_array():
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply()
    payload["new_subjects"] = tuple(payload["new_subjects"])
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, assignment())


def test_candidate_wide_rejection_remains_possible_with_accepting_assessments():
    from harness.discovery_semantics import validate_discovery_reply
    payload = reply("review")
    payload.update(verdict="reject", reason="Unrelated boundary content changed.")
    assert validate_discovery_reply(payload, assignment("review"))["verdict"] == "reject"
