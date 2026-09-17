"""Discovery semantic content feeds real identity checks, never storage writes."""
from dataclasses import replace
import json

import pytest

from harness.element_identity_candidate import IdentityEditScope, CandidateArtifact
from harness.element_identity_lifecycle import ElementAdopt
from harness.element_identity_publication import PublicationOperation
from harness.element_identity_request_codec import encode_request
from harness.element_identity_store import IdentityStore
from harness.discovery_semantics import DiscoveryAssignment, parse_discovery_reply


BEFORE = "### U-001: Lighting choice\r\nOriginal question.\r\n\r\n"
AFTER = "### U-001: Lighting choice\r\nClarified question.\r\n\r\n### U-000002: Camera choice\r\nIsometric?\r\n"


@pytest.fixture
def case(tmp_path):
    from harness.discovery_candidate import DiscoveryReservation
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="game", operation_id="import", definitions=(("U-001", "lighting-subject"),))
    store.apply_lifecycle(spec_id="game", operation_id="adopt", changes=(ElementAdopt("U-001", "lighting-subject", BEFORE),))
    label, = store.reserve(spec_id="game", kind="U", operation_id="reservation", count=1)
    assert label == "U-000002"
    bound = DiscoveryAssignment("op", "proposal-turn", "game", "run", "propose", "a" * 64,
                                ("unknowns.md",), (("U-001", "1"),))
    proposal = {**bound.identity(), "action": "final", "new_subjects": [
        dict(key="camera", kind="U", subject="camera-subject", caption="Camera choice")],
        "revisions": [dict(id="U-001", expected_revision="1")]}
    return store, bound, proposal, (DiscoveryReservation("camera", label, "reservation"),)


def translate(case, after=AFTER, *, reservations=None, subjects=None):
    from harness.discovery_candidate import author_artifacts, build_discovery_changes
    store, bound, proposal, bindings = case
    author = replace(bound, step="author", dispatch_id="author-turn", input_fingerprint="b" * 64)
    reply = parse_discovery_reply(json.dumps({**author.identity(), "action": "final", "artifacts": {"unknowns.md": after}}), author)
    artifacts = author_artifacts(author, reply, before={"unknowns.md": BEFORE})
    changes = build_discovery_changes(bound, proposal, reservations=bindings if reservations is None else reservations,
        artifacts=artifacts, existing_subjects={"U-001": "lighting-subject"} if subjects is None else subjects)
    return artifacts, changes


def preview(case, artifacts, changes, *, scope=None):
    store = case[0]
    ops = (PublicationOperation("lifecycle", "candidate", encode_request("lifecycle", changes)),) if changes else ()
    return store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=scope or IdentityEditScope(("unknowns.md",), ("U-001", "U-000002"), ("unknowns.md",)), operations=ops)


def test_translated_creation_and_revision_pass_real_preview_without_publication(case):
    store = case[0]
    history = store.identity_history(spec_id="game")
    artifacts, changes = translate(case)
    assert [(type(item).__name__, item.element_id, item.subject) for item in changes] == [
        ("ElementCreate", "U-000002", "camera-subject"), ("ElementRevision", "U-001", "lighting-subject")]
    assert changes[0].content == "### U-000002: Camera choice\r\nIsometric?\r\n"
    assert changes[1].expected_revision == "1"
    result = preview(case, artifacts, changes)
    assert not result.check.diagnostics
    assert result.history is not None and result.history != history
    assert store.identity_history(spec_id="game") == history
    assert store.lookup(spec_id="game", element_id="U-000002") is None


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "wrong_kind", "legacy_alias", "wrong_key"])
def test_reservation_mapping_must_cover_proposal_once_with_numeric_reserved_ids(case, change):
    from harness.discovery_candidate import DiscoveryReservation
    bindings = case[3]
    if change == "missing":
        bindings = ()
    elif change == "extra":
        bindings += (DiscoveryReservation("extra", "U-000003", "other"),)
    elif change == "duplicate":
        bindings *= 2
    else:
        bindings = (replace(bindings[0], **{
            "wrong_kind": {"element_id": "A-000002"}, "legacy_alias": {"element_id": "U-002"},
            "wrong_key": {"key": "other"}}[change]),)
    with pytest.raises(ValueError):
        translate(case, reservations=bindings)


@pytest.mark.parametrize("after", [
    AFTER.replace("Camera choice", "Movement choice"), AFTER.replace("Lighting choice", "Unrelated question"),
    AFTER.replace("U-000002", "U-000003"), AFTER.split("### U-000002")[0],
    AFTER + "\n### U-000002: Duplicate\nOther.\n", AFTER.replace("U-001", "U-000001"),
])
def test_candidate_cannot_relabel_remove_or_duplicate_proposed_subjects(case, after):
    with pytest.raises(ValueError):
        translate(case, after)


def test_unreserved_descriptor_is_not_allocation_authority(case):
    from harness.discovery_candidate import DiscoveryReservation
    artifacts, changes = translate(case, AFTER.replace("U-000002", "U-000099"),
        reservations=(DiscoveryReservation("camera", "U-000099", "invented"),))
    result = preview(case, artifacts, changes, scope=IdentityEditScope(
        ("unknowns.md",), ("U-001", "U-000099"), ("unknowns.md",)))
    assert result.check.diagnostics
    assert result.history is None
    assert case[0].lookup(spec_id="game", element_id="U-000099") is None


def test_supplied_subject_cannot_replace_registry_subject(case):
    artifacts, changes = translate(case, subjects={"U-001": "invented-subject"})
    result = preview(case, artifacts, changes)
    assert result.check.diagnostics
    assert result.history is None
    assert case[0].lookup(spec_id="game", element_id="U-001")["subject"] == "lighting-subject"


def test_stale_revision_is_rejected_by_existing_authority(case):
    store, bound, payload, bindings = case
    bound = replace(bound, editable_revisions=(("U-001", "2"),))
    payload.update(bound.identity())
    payload["revisions"][0]["expected_revision"] = "2"
    changed_case = store, bound, payload, bindings
    artifacts, changes = translate(changed_case)
    assert preview(changed_case, artifacts, changes).history is None
    assert store.lookup(spec_id="game", element_id="U-001")["revision"] == "1"


@pytest.mark.parametrize("reference", ["U-001", "U-999999"])
def test_dependent_evidence_is_checked_without_rewriting_it(case, reference):
    artifacts, changes = translate(case)
    evidence = f"Investigated {reference}.\n"
    artifacts += (CandidateArtifact("investigation.md", "investigation", evidence, evidence),)
    result = preview(case, artifacts, changes)
    assert bool(result.check.diagnostics) is (reference == "U-999999")
    assert artifacts[-1].after_text == evidence


def test_unchanged_revision_does_not_create_new_history(case):
    artifacts, changes = translate(case, AFTER.replace("Clarified question.", "Original question."))
    assert [item.element_id for item in changes] == ["U-000002"]
    assert not preview(case, artifacts, changes).check.diagnostics


def test_existing_scope_checker_remains_required(case):
    artifacts, changes = translate(case)
    result = preview(case, artifacts, changes, scope=IdentityEditScope(("unknowns.md",), ("U-000002",)))
    assert result.check.diagnostics
    assert result.history is None


@pytest.mark.parametrize("before", [{}, {"unknowns.md": BEFORE, "state.json": "{}"}, {"unknowns.md": 3}])
def test_author_materialization_requires_exact_captured_baseline_keys(case, before):
    from harness.discovery_candidate import author_artifacts
    author = replace(case[1], step="author")
    value = {**author.identity(), "action": "final", "artifacts": {"unknowns.md": AFTER}}
    with pytest.raises(ValueError):
        author_artifacts(author, value, before=before)


def test_nonfinal_or_wrong_step_reply_cannot_materialize_artifacts(case):
    from harness.discovery_candidate import author_artifacts, build_discovery_changes
    with pytest.raises(ValueError):
        author_artifacts(case[1], case[2], before={"unknowns.md": BEFORE})
    with pytest.raises(ValueError):
        build_discovery_changes(case[1], {**case[1].identity(), "action": "blocked", "reason": "Stop."},
            reservations=(), artifacts=(), existing_subjects={})


def test_fresh_assumptions_and_millionth_question_use_actual_reservations(tmp_path):
    from harness.discovery_candidate import DiscoveryReservation, author_artifacts, build_discovery_changes
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="game", operation_id="high-water", definitions=(("U-999999", "Prior subject"),))
    assert store.reserve(spec_id="game", kind="U", operation_id="reserve-u", count=1) == ("U-1000000",)
    assert store.reserve(spec_id="game", kind="A", operation_id="reserve-a", count=1) == ("A-000001",)
    bound = DiscoveryAssignment("op", "proposal", "game", "run", "propose", "a" * 64,
                                ("unknowns.md", "assumptions.md"))
    proposal = {**bound.identity(), "action": "final", "new_subjects": [
        dict(key="question", kind="U", subject="Question subject", caption="Question"),
        dict(key="assumption", kind="A", subject="Assumption subject", caption="Assumption")], "revisions": []}
    author = replace(bound, step="author", dispatch_id="author")
    authored = {**author.identity(), "action": "final", "artifacts": {
        "unknowns.md": "### U-1000000: Question\nDoes A-000001 hold?\n",
        "assumptions.md": "### A-000001: Assumption\nBrowser only.\n"}}
    artifacts = author_artifacts(author, authored, before={"unknowns.md": None, "assumptions.md": None})
    changes = build_discovery_changes(bound, proposal, reservations=(
        DiscoveryReservation("question", "U-1000000", "reserve-u"),
        DiscoveryReservation("assumption", "A-000001", "reserve-a")), artifacts=artifacts, existing_subjects={})
    result = store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=IdentityEditScope(bound.artifact_paths, ("U-1000000", "A-000001"), bound.artifact_paths),
        operations=(PublicationOperation("lifecycle", "new-subjects", encode_request("lifecycle", changes)),))
    assert not result.check.diagnostics
    entities = json.loads(result.history.payload)["entities"]
    assert {(item["element_id"], item["subject"]) for item in entities} == {
        ("U-999999", "Prior subject"), ("U-1000000", "Question subject"), ("A-000001", "Assumption subject")}
    assert store.lookup(spec_id="game", element_id="A-000001") is None
