"""WHAT/WHY2 are closed claims, never provider-owned state or metric writes."""
from dataclasses import replace
from copy import deepcopy

import pytest

from harness.discovery_semantics import DiscoveryAssignment, decode_discovery_assignment, validate_discovery_reply


SPEC = """# Game specification

## Functional requirements
### FR-000001: Player movement
- **Statement**: The system SHALL move the player's character across the generated scene.

## Quality requirements
### NFR-000001: Browser operation
- **Statement**: The scene SHALL run in a browser without installing a client.

## Acceptance criteria
### AC-000001: Movement is visible
- **Statement**: Given the scene is loaded, when the player presses an arrow key, then the character position SHALL change (FR-000001).
"""
PASS_ISSUES = """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 0
- **Verdict:** PASS

## Issues
"""


def assignment(producer="what", step="propose", **kwargs):
    paths = ("spec.md", "requirements-overview.md") if producer == "what" else ("quality-gates.md", "issues.md")
    return DiscoveryAssignment(producer + "-" + "a" * 32, "attempt-1-" + step,
        "game", "first", step, "b" * 64, paths, producer=producer, **kwargs)


def routing(producer="what"):
    updates = dict(evidence_resolution_status="not_required")
    if producer == "what":
        updates["spec_status"] = "planned"
    else:
        updates["finding_routes"] = {"findings": []}
    return dict(verdict="DONE" if producer == "what" else "PASS", state_updates=updates)


@pytest.mark.parametrize("producer", ["discovery", "synthesizer", "tracker", "why1", "constitution"])
def test_upstream_refresh_reads_specification_without_acquiring_write_scope(producer):
    from harness.discovery_semantics import captured_artifact_roles, artifact_roles, identity_kinds
    before = artifact_roles(producer), identity_kinds(producer)
    roles = captured_artifact_roles(producer, after_review=True)
    assert roles["spec.md"] == "requirements" and roles["quality-gates.md"] == "references"
    assert roles["issues.md"] == "issues" and "plan.md" not in roles
    assert captured_artifact_roles(producer, after_review=False) == before[0]
    assert (artifact_roles(producer), identity_kinds(producer)) == before
    with pytest.raises(ValueError):
        DiscoveryAssignment("refresh", "turn", "game", "first", "author", "b" * 64,
            ("spec.md",), producer=producer).identity()


@pytest.mark.parametrize("producer", ["what", "why2"])
def test_spec_assignments_round_trip_and_bind_review_to_exact_routing(producer):
    for step in ("propose", "author", "review"):
        selected = assignment(producer, step, **(dict(routing=tuple(routing(producer).items())) if step == "review" else {}))
        assert decode_discovery_assignment(selected.identity()) == selected
    with pytest.raises(ValueError):
        assignment(producer, "review").identity()
    with pytest.raises(ValueError):
        replace(assignment(producer), artifact_paths=("unknowns.md",)).identity()


def test_what_allocation_translates_all_requirement_kinds_through_existing_authority(tmp_path):
    from harness.discovery_candidate import DiscoveryReservation, author_artifacts, build_discovery_changes
    from harness.element_identity_candidate import IdentityEditScope
    from harness.element_identity_publication import PublicationOperation
    from harness.element_identity_request_codec import encode_request
    from harness.element_identity_store import IdentityStore
    from harness.discovery_reservations import _intents
    store = IdentityStore.initialize(tmp_path)
    selected = assignment()
    subjects = [dict(key=kind.lower(), kind=kind, subject=kind + " subject", caption=caption)
        for kind, caption in (("FR", "Player movement"), ("NFR", "Browser operation"), ("AC", "Movement is visible"))]
    proposal = validate_discovery_reply({**selected.identity(), "action": "final", "new_subjects": subjects, "revisions": []}, selected)
    intents = _intents(dict(operation_id=selected.operation_id), proposal, {})
    assert {item["kind"] for item in intents} == {"FR", "NFR", "AC"}
    bindings = tuple(DiscoveryReservation(item["keys"][0], store.reserve(spec_id="game", kind=item["kind"],
        operation_id=item["operation_id"], count=1)[0], item["operation_id"]) for item in intents)
    author = assignment(step="author")
    artifacts = author_artifacts(author, {**author.identity(), "action": "final", "routing": routing(),
        "artifacts": {"spec.md": SPEC, "requirements-overview.md": "Movement (FR-000001) with visible acceptance (AC-000001).\n"}},
        before={"spec.md": None, "requirements-overview.md": None})
    changes = build_discovery_changes(selected, proposal, reservations=bindings, artifacts=artifacts, existing_subjects={})
    assert {change.element_id for change in changes} == {"FR-000001", "NFR-000001", "AC-000001"}
    preview = store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=IdentityEditScope(selected.artifact_paths, tuple(change.element_id for change in changes), selected.artifact_paths),
        operations=(PublicationOperation("lifecycle", "candidate", encode_request("lifecycle", changes)),))
    assert not preview.check.diagnostics
    assert store.lookup(spec_id="game", element_id="FR-000001") is None


@pytest.mark.parametrize("producer,kind", [("what", "U"), ("what", "OQ"), ("what", "ISS"), ("why2", "FR"), ("why2", "U")])
def test_spec_producers_cannot_allocate_other_owners_identities(producer, kind):
    selected = assignment(producer)
    with pytest.raises(ValueError):
        validate_discovery_reply({**selected.identity(), "action": "final", "revisions": [],
            "new_subjects": [dict(key="other", kind=kind, subject="Other", caption="Other")]}, selected)


@pytest.mark.parametrize("producer", ["what", "why2"])
@pytest.mark.parametrize("key,value", [("quality_scores", [{"pass": True}]), ("spec_quality_certificate", {}),
    ("understanding_evidence", {}), ("phase", "checkpoint-assess"), ("iteration", 0)])
def test_spec_routing_cannot_write_controller_authority(producer, key, value):
    selected = assignment(producer, "author")
    claim = routing(producer)
    claim["state_updates"][key] = value
    with pytest.raises(ValueError):
        validate_discovery_reply({**selected.identity(), "action": "final", "routing": claim,
            "artifacts": {path: "content" for path in selected.artifact_paths}}, selected)


def test_what_rejects_empty_outputs_and_legacy_open_question_labels():
    from harness.discovery_candidate import author_artifacts
    selected = assignment(step="author")
    for spec in ("", SPEC + "\n- OQ-001: Camera choice\n"):
        with pytest.raises(ValueError):
            author_artifacts(selected, {**selected.identity(), "action": "final", "routing": routing(),
                "artifacts": {"spec.md": spec, "requirements-overview.md": "Overview"}},
                before={"spec.md": None, "requirements-overview.md": None})


def test_why2_reports_must_match_structured_verdict_and_routes():
    from harness.discovery_candidate import author_artifacts
    selected = assignment("why2", "author")
    reply = {**selected.identity(), "action": "final", "routing": routing("why2"),
        "artifacts": {"quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: PASS\n", "issues.md": PASS_ISSUES}}
    before = {path: None for path in selected.artifact_paths}
    assert len(author_artifacts(selected, reply, before=before)) == 2
    for path in selected.artifact_paths:
        changed = deepcopy(reply)
        changed["artifacts"][path] = changed["artifacts"][path].replace("PASS", "FAIL")
        with pytest.raises(ValueError):
            author_artifacts(selected, changed, before=before)
    changed = deepcopy(reply)
    changed["routing"]["state_updates"]["finding_routes"]["findings"] = [
        dict(issue_id="ISS-000001", rationale="Invented finding", route="spec_repair")]
    with pytest.raises(ValueError):
        author_artifacts(selected, changed, before=before)


@pytest.mark.parametrize("producer,verdict", [("what", " DONE "), ("why2", " PASS "), ("what", "done"), ("why2", "pass")])
def test_spec_verdict_encoding_is_exact_before_native_normalization(producer, verdict):
    selected = assignment(producer, "author")
    claim = routing(producer)
    claim["verdict"] = verdict
    with pytest.raises(ValueError):
        validate_discovery_reply({**selected.identity(), "action": "final", "routing": claim,
            "artifacts": {path: "content" for path in selected.artifact_paths}}, selected)


def test_requirement_review_citations_bind_exact_definition_bytes():
    import hashlib
    from harness.discovery_operation import _citations
    from harness.element_identity_candidate import CandidateArtifact
    labels = ("FR-000001", "NFR-000001", "AC-000001")
    citations = _citations((CandidateArtifact("spec.md", "requirements", None, SPEC),), labels)
    digest = hashlib.sha256(SPEC.encode("utf-8")).hexdigest()
    assert citations == {label: f"candidate:spec.md:{digest}#{label}" for label in labels}
