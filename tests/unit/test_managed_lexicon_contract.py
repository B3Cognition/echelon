"""Managed derivation owns text, never source identities or gate authority."""
from dataclasses import replace

import pytest

from harness.discovery_candidate import author_artifacts, build_discovery_changes
from harness.discovery_producer import producer_phase, producer_role
from harness.discovery_semantics import (
    DiscoveryAssignment, decode_discovery_assignment, validate_discovery_reply,
)


def assignment(step="author", **changes):
    value = DiscoveryAssignment(
        "lexicon-" + "a" * 32, "attempt-1-" + step, "game", "first", step,
        "b" * 64, ("requirements.lexicon.md",), producer="lexicon",
        routing=(("verdict", "DONE"), ("state_updates", {})) if step == "review" else None,
    )
    return replace(value, **changes)


def authored(selected, text="Uncertified translation of FR-000001.\n"):
    return {**selected.identity(), "action": "final",
        "artifacts": {"requirements.lexicon.md": text},
        "routing": {"verdict": "DONE", "state_updates": {}}}


def test_source_metadata_uses_exact_captured_bytes_not_model_computation():
    from harness import discovery_lexicon
    metadata = getattr(discovery_lexicon, "source_metadata", None)
    assert callable(metadata), "The host must supply source metadata to the derivation"
    assert metadata("Source café\r\n") == {"source_name": "spec.md", "source_sha256":
        "f7483dc87ec9cf6044f0a3522f448adef0015386beee6724aaea7d26cb3ca45f"}


def test_derivation_returns_one_uncertified_artifact_not_a_gate_verdict():
    selected = assignment()
    reply = authored(selected)
    assert validate_discovery_reply(reply, selected) == reply
    assert decode_discovery_assignment(selected.identity()) == selected
    artifacts = author_artifacts(selected, reply, before={"requirements.lexicon.md": None})
    assert [(item.path, item.role, item.after_text) for item in artifacts] == [
        ("requirements.lexicon.md", "references", "Uncertified translation of FR-000001.\n")]
    assert producer_phase("lexicon") == "phase1-lexicon-derive"
    assert producer_role("lexicon", "producer") == "echelon.lexicon-producer"
    assert producer_role("lexicon", "reviewer") == "echelon.lexicon-reviewer"


@pytest.mark.parametrize("path", ["spec.md", "requirements-overview.md", "spec-lexicon-report.json"])
def test_derivation_cannot_select_source_or_controller_outputs(path):
    assignment().identity()
    with pytest.raises(ValueError):
        assignment(artifact_paths=(path,)).identity()


@pytest.mark.parametrize("field,value", [
    ("editable_revisions", (("FR-000001", "1"),)),
    ("assigned_ids", ("AC-1000000",)),
])
def test_derivation_cannot_acquire_identity_edit_authority(field, value):
    assignment().identity()
    with pytest.raises(ValueError):
        assignment(**{field: value}).identity()


def test_empty_derivation_proposal_allocates_and_revises_nothing():
    selected = assignment("propose")
    proposal = {**selected.identity(), "action": "final", "new_subjects": [], "revisions": []}
    assert validate_discovery_reply(proposal, selected) == proposal
    author = assignment()
    artifacts = author_artifacts(author, authored(author), before={"requirements.lexicon.md": None})
    assert build_discovery_changes(selected, proposal, reservations=(), artifacts=artifacts, existing_subjects={}) == ()
    for key, value in (
        ("new_subjects", [{"key": "move", "kind": "FR", "subject": "Move", "caption": "Move"}]),
        ("revisions", [{"id": "FR-000001", "expected_revision": "1"}]),
    ):
        with pytest.raises(ValueError):
            validate_discovery_reply({**proposal, key: value}, selected)


@pytest.mark.parametrize("routing", [
    {"verdict": "PASS", "state_updates": {}},
    {"verdict": " DONE ", "state_updates": {}},
    {"verdict": "DONE", "state_updates": {"lexicon_pass": True}},
    {"verdict": "DONE", "state_updates": {"lexicon_attempts": 0}},
    {"verdict": "DONE", "state_updates": {"spec_quality_status": "passed"}},
    {"verdict": "DONE", "state_updates": {}, "next_phase": "checkpoint-assess"},
])
def test_derivation_cannot_supply_certification_counters_or_routing_override(routing):
    selected = assignment()
    reply = authored(selected)
    with pytest.raises(ValueError):
        validate_discovery_reply({**reply, "routing": routing}, selected)


def test_failed_derivation_preserves_exact_fail_without_claiming_gate_failure():
    selected = assignment()
    reply = authored(selected)
    reply["routing"]["verdict"] = "FAIL"
    assert validate_discovery_reply(reply, selected)["routing"] == {"verdict": "FAIL", "state_updates": {}}


def test_review_is_bound_to_the_exact_author_result_and_has_no_identity_writes():
    selected = assignment("review")
    reply = {**selected.identity(), "action": "final", "verdict": "accept",
        "reason": "Faithful translation; the deterministic gate still owns certification.", "assessments": []}
    assert validate_discovery_reply(reply, selected) == reply
    assert decode_discovery_assignment(selected.identity()) == selected
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, replace(selected, routing=(("verdict", "FAIL"), ("state_updates", {}))))


@pytest.mark.parametrize("text", ["", " \n", "bad\x00text"])
def test_derivation_requires_nonblank_utf8_text(text):
    selected = assignment()
    with pytest.raises(ValueError):
        validate_discovery_reply(authored(selected, text), selected)
