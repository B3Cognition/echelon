"""Tracker claims feed the existing identity authority; they grant no execution."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from harness.discovery_candidate import DiscoveryReservation, author_artifacts, build_discovery_changes
from harness.discovery_semantics import DiscoveryAssignment, parse_discovery_reply, validate_discovery_reply
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_lifecycle import ElementAdopt
from harness.element_identity_store import IdentityStore
from tests.unit.test_element_identity_candidate_preview import op, sql_state
from tests.unit.test_intent_identities import artifact


PATHS = ("user-intent.md", "stakeholder-model.md")


def assignment(step="propose", *, kind="UI", revision=False):
    return DiscoveryAssignment("tracker-" + "a" * 32, "turn-" + step, "game", "run", step,
        "b" * 64, PATHS, ((kind + "-001", "1"),) if revision else (),
        (kind + ("-001" if revision else "-000001"),) if step != "propose" else (), producer="tracker",
        routing=tuple(routing().items()) if step == "review" else None)


def routing(verdict="ALIGNED"):
    return dict(verdict=verdict, question="Which movement controls?" if verdict == "STOP_AND_ASK" else None,
        recommended_answer="Use arrow keys" if verdict == "STOP_AND_ASK" else None,
        risk_level="low" if verdict == "STOP_AND_ASK" else None)


def reply(bound, *, verdict="ALIGNED", stakeholder=None):
    value = {**bound.identity(), "action": "final"}
    if bound.step == "propose":
        kind = bound.editable_revisions[0][0].split("-")[0] if bound.editable_revisions else "UI"
        value.update(new_subjects=[] if bound.editable_revisions else [dict(
            key="movement", kind=kind, subject="Player movement", caption="Move freely")],
            revisions=[dict(id=label, expected_revision=revision) for label, revision in bound.editable_revisions])
    elif bound.step == "author":
        label, = bound.assigned_ids
        value.update(artifacts={"user-intent.md": artifact(label.split("-")[0], label),
            "stakeholder-model.md": stakeholder}, routing=routing(verdict))
    else:
        value.update(verdict="accept", reason="Matches the source request.", assessments=[dict(
            id=label, verdict="accept", reason="Same movement intent.", evidence=["candidate:user-intent.md:hash#" + label])
            for label in bound.assigned_ids])
    return value


@pytest.mark.parametrize("step", ["propose", "author", "review"])
def test_tracker_envelope_is_closed_version_three_and_keeps_exact_assignment(step):
    bound = assignment(step)
    payload = reply(bound)
    assert payload["schema_version"] == 3
    accepted = parse_discovery_reply(json.dumps(payload), bound)
    assert accepted == payload
    damaged = deepcopy(payload)
    damaged["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_discovery_reply(damaged, bound)


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT", "STOP_AND_ASK"])
def test_tracker_author_retains_routing_and_absence_without_turning_them_into_authority(verdict):
    bound = assignment("author")
    payload = reply(bound, verdict=verdict)
    accepted = validate_discovery_reply(payload, bound)
    assert accepted["routing"] == routing(verdict)
    assert accepted["artifacts"]["stakeholder-model.md"] is None
    payload["routing"]["verdict"] = "DONE"
    assert accepted["routing"]["verdict"] == verdict
    artifacts = author_artifacts(bound, accepted, before=dict.fromkeys(PATHS))
    assert [(item.path, item.role, item.before_text) for item in artifacts] == [("user-intent.md", "intent", None)]


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_tracker_reservations_feed_real_identity_preview_without_publication(tmp_path, kind):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="game", kind=kind, operation_id="reserve", count=1)
    bound = assignment(kind=kind)
    proposed = reply(bound)
    proposed["new_subjects"][0]["kind"] = kind
    author = assignment("author", kind=kind)
    authored = reply(author)
    artifacts = author_artifacts(author, authored, before=dict.fromkeys(PATHS))
    before = sql_state(tmp_path)
    changes = build_discovery_changes(bound, proposed, reservations=(DiscoveryReservation("movement", label, "reserve"),),
        artifacts=artifacts, existing_subjects={})
    result = store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=IdentityEditScope(("user-intent.md",), (label,), ("user-intent.md",)),
        operations=(op("lifecycle", "candidate", *changes),))
    assert result.check.diagnostics == ()
    assert [(item.element_id, item.subject) for item in changes] == [(kind + "-000001", "Player movement")]
    assert result.history is not None
    assert store.lookup(spec_id="game", element_id=label) is None
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_tracker_revision_preserves_legacy_id_subject_and_historical_evidence(tmp_path, kind):
    import hashlib
    store = IdentityStore.initialize(tmp_path)
    label = kind + "-001"
    before_text = artifact(kind, label)
    row, = parse_identity_artifact(path="user-intent.md", role="intent", text=before_text).declarations
    store.import_identities(spec_id="game", operation_id="import", definitions=((label, "Player movement"),))
    store.apply_lifecycle(spec_id="game", operation_id="adopt", changes=(ElementAdopt(label, "Player movement", row.content),))
    evidence = "See " + label + "."
    store.record_reference_claims(spec_id="game", operation_id="assessment", claims=(ReferenceClaim(
        "evidence.md", hashlib.sha256(evidence.encode()).hexdigest(), "span:4:10", label, "1", "evidence"),))
    bound = assignment(kind=kind, revision=True)
    author = assignment("author", kind=kind, revision=True)
    authored = reply(author)
    authored["artifacts"]["user-intent.md"] = artifact(kind, label, "Move using arrow keys")
    artifacts = author_artifacts(author, authored, before={"user-intent.md": before_text, "stakeholder-model.md": None})
    changes = build_discovery_changes(bound, reply(bound), reservations=(), artifacts=artifacts,
        existing_subjects={label: "Player movement"})
    before = sql_state(tmp_path)
    result = store.preview_identity_candidate(spec_id="game", artifacts=artifacts + (
        CandidateArtifact("evidence.md", "evidence", evidence, evidence),),
        scope=IdentityEditScope(("user-intent.md",), (label,)), operations=(op("lifecycle", "candidate", *changes),))
    assert result.check.diagnostics == ()
    assert [(item.element_id, item.subject, item.expected_revision) for item in changes] == [(label, "Player movement", "1")]
    assert [(item.target_id, item.assessed_revisions, item.assessment_state) for item in result.check.references] == [
        (label, ("1",), "historical")]
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT", "STOP_AND_ASK"])
def test_tracker_review_is_bound_to_the_exact_authored_routing(verdict):
    bound = replace(assignment("review"), routing=tuple(routing(verdict).items()))
    payload = reply(bound)
    accepted = validate_discovery_reply(payload, bound)
    assert accepted["routing"] == routing(verdict)
    for field, value in (("verdict", "DONE"), ("question", "Different question"),
            ("recommended_answer", "Different answer"), ("risk_level", "critical")):
        changed = deepcopy(payload)
        changed["routing"][field] = value
        with pytest.raises(ValueError):
            validate_discovery_reply(changed, bound)


@pytest.mark.parametrize("damage", ["missing_routing", "missing_field", "extra_field", "done", "wrong_type",
    "no_question", "blank_question", "unsafe_question", "metadata_without_question", "answer_without_stop",
    "risk_without_answer", "unknown_risk", "blank_answer", "state_updates", "authority"])
def test_tracker_author_cannot_smuggle_routing_or_human_input_authority(damage):
    bound = assignment("author")
    payload = reply(bound, verdict="STOP_AND_ASK")
    if damage == "missing_routing": del payload["routing"]
    elif damage == "missing_field": del payload["routing"]["question"]
    elif damage == "extra_field": payload["routing"]["next_phase"] = "phase1-why1"
    elif damage == "done": payload["routing"]["verdict"] = "DONE"
    elif damage == "wrong_type": payload["routing"]["verdict"] = []
    elif damage == "no_question": payload["routing"]["question"] = None
    elif damage == "blank_question": payload["routing"]["question"] = " "
    elif damage == "unsafe_question": payload["routing"]["question"] = "Bad\x00question"
    elif damage == "metadata_without_question": payload["routing"]["verdict"] = "ALIGNED"
    elif damage == "answer_without_stop": payload["routing"].update(verdict="DRIFT", question=None, risk_level=None)
    elif damage == "risk_without_answer": payload["routing"]["recommended_answer"] = None
    elif damage == "unknown_risk": payload["routing"]["risk_level"] = "safe"
    elif damage == "blank_answer": payload["routing"]["recommended_answer"] = " "
    elif damage == "state_updates": payload["state_updates"] = {"status": "running"}
    else: payload["routing"]["automatic_eligible"] = True
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, bound)


@pytest.mark.parametrize("risk", [None, "low", "medium", "high", "critical"])
def test_tracker_recommendation_preserves_risk_without_deciding_eligibility(risk):
    bound = assignment("author")
    payload = reply(bound, verdict="STOP_AND_ASK")
    payload["routing"]["risk_level"] = risk
    assert validate_discovery_reply(payload, bound)["routing"]["risk_level"] == risk
    payload["routing"].update(risk_level=None, recommended_answer=None)
    assert validate_discovery_reply(payload, bound)["routing"]["recommended_answer"] is None


@pytest.mark.parametrize("field,value", [("user-intent.md", None), ("user-intent.md", "  "),
    ("stakeholder-model.md", False), ("stakeholder-model.md", "bad\x00text"),
    ("user-intent.md", "\ud800"), ("unknowns.md", "### U-000001: Replacement")])
def test_tracker_outputs_are_exact_utf8_and_cannot_author_other_producers_artifacts(field, value):
    bound = assignment("author")
    payload = reply(bound)
    payload["artifacts"][field] = value
    with pytest.raises(ValueError):
        validate_discovery_reply(payload, bound)


def test_optional_output_cannot_silently_erase_retained_stakeholders():
    bound = assignment("author")
    payload = reply(bound)
    before = {"user-intent.md": None, "stakeholder-model.md": "# Stakeholders\nPlayers and referees.\n"}
    with pytest.raises(ValueError):
        author_artifacts(bound, payload, before=before)
    payload["artifacts"]["stakeholder-model.md"] = before["stakeholder-model.md"]
    materials = author_artifacts(bound, payload, before=before)
    assert [(item.path, item.role) for item in materials] == [("user-intent.md", "intent"), ("stakeholder-model.md", "references")]
    assert materials[1].before_text == materials[1].after_text == before["stakeholder-model.md"]


@pytest.mark.parametrize("field,value", [("artifact_paths", ("unknowns.md",)),
    ("artifact_paths", ("user-intent.md", "unknowns.md")), ("artifact_paths", ("stakeholder-model.md",)),
    ("editable_revisions", (("U-001", "1"),)), ("assigned_ids", ("A-000001",)),
    ("assigned_ids", ("UI-000001", "UI-000001")), ("routing", (("verdict", "ALIGNED"),))])
def test_tracker_assignment_cannot_expand_identity_or_artifact_scope(field, value):
    bound = replace(assignment("author"), **{field: value})
    with pytest.raises(ValueError):
        bound.identity()


@pytest.mark.parametrize("producer", ["discovery", "synthesizer"])
def test_prior_producers_keep_their_exact_reply_versions_and_reject_tracker_metadata(producer):
    from tests.unit.test_discovery_semantics import assignment as discovery_assignment, reply as discovery_reply
    bound = replace(discovery_assignment(), producer=producer)
    payload = discovery_reply()
    if producer == "synthesizer": payload.update(schema_version=2, producer="synthesizer")
    assert validate_discovery_reply(payload, bound) == payload
    assert "routing" not in bound.identity()
    payload["new_subjects"][0]["kind"] = "UI"
    with pytest.raises(ValueError): validate_discovery_reply(payload, bound)
    with pytest.raises(ValueError): replace(bound, routing=tuple(routing().items())).identity()


@pytest.mark.parametrize("damage", ["old_spelling", "zero", "unassigned_kind", "wrong_caption", "wrong_key", "missing", "unreserved"])
def test_tracker_cannot_introduce_unreserved_or_repurposed_definitions(tmp_path, damage):
    store = IdentityStore.initialize(tmp_path)
    reserved, = store.reserve(spec_id="game", kind="UI", operation_id="reserve", count=1)
    label = {"old_spelling": "UI-001", "zero": "UI-000000", "unassigned_kind": "II-000001", "unreserved": "UI-000099"}.get(damage, reserved)
    author = replace(assignment("author"), assigned_ids=(label,))
    before = sql_state(tmp_path)
    try:
        payload = reply(author)
        if damage == "wrong_caption": payload["artifacts"]["user-intent.md"] = artifact("UI", label, "Unrelated intent")
        if damage == "missing": payload["artifacts"]["user-intent.md"] = "# No intent definitions\n"
        materials = author_artifacts(author, payload, before=dict.fromkeys(PATHS))
        changes = build_discovery_changes(assignment(), reply(assignment()), reservations=(DiscoveryReservation(
            "foreign" if damage == "wrong_key" else "movement", label, "invented" if damage == "unreserved" else "reserve"),),
            artifacts=materials, existing_subjects={})
    except ValueError:
        assert damage != "unreserved"  # Only the existing authority can reject this forged receipt.
    else:
        result = store.preview_identity_candidate(spec_id="game", artifacts=materials,
            scope=IdentityEditScope(("user-intent.md",), (label,), ("user-intent.md",)),
            operations=(op("lifecycle", "candidate", *changes),))
        assert result.check.diagnostics and result.history is None
    assert sql_state(tmp_path) == before
