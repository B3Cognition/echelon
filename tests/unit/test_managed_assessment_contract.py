"""Phase 2 semantic contracts do not admit runtime execution or identity edits."""
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from harness.discovery_candidate import author_artifacts, build_discovery_changes
from harness.discovery_producer import producer_phase, producer_role, producer_operation_id
from harness.discovery_semantics import (
    DiscoveryAssignment, decode_discovery_assignment, validate_discovery_reply,
)


OUTPUTS = {
    "feasibility": ("feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md"),
    "strategy": ("strategic-overview.md",),
    "alignment": ("intent-alignment-check.md",),
}
VERDICTS = {"feasibility": "PASS", "strategy": "DONE", "alignment": "ALIGNED"}
PHASES = {"feasibility": "phase2-decide", "strategy": "phase2-strategic-overview",
          "alignment": "phase2-tracker-alignment"}


def assignment(producer, step="author", **changes):
    value = DiscoveryAssignment(producer + "-" + "a" * 32, "attempt-1-" + step,
        "game", "first", step, "b" * 64, OUTPUTS[producer], producer=producer,
        routing=(("verdict", VERDICTS[producer]), ("state_updates", {})) if step == "review" else None)
    return replace(value, **changes)


def authored(selected, verdict=None, updates=None):
    verdict = verdict or VERDICTS[selected.producer]
    return {**selected.identity(), "action": "final",
        "artifacts": {path: None if path == "kill-report.md" and verdict != "KILL"
            else "Assessment of FR-000001.\n" for path in selected.artifact_paths},
        "routing": {"verdict": verdict, "state_updates": updates or {}}}


@pytest.mark.parametrize("producer,version", [("feasibility", 9), ("strategy", 10), ("alignment", 11)])
def test_exact_outputs_round_trip_without_identity_or_runtime_authority(producer, version):
    selected = assignment(producer)
    reply = authored(selected)
    assert selected.identity()["schema_version"] == version
    assert validate_discovery_reply(reply, selected) == reply
    assert decode_discovery_assignment(selected.identity()) == selected
    artifacts = author_artifacts(selected, reply, before=dict.fromkeys(OUTPUTS[producer]))
    assert {item.path for item in artifacts} == set(OUTPUTS[producer]) - {"kill-report.md"}
    assert all(item.role == "references" for item in artifacts)
    propose = assignment(producer, "propose")
    proposal = {**propose.identity(), "action": "final", "new_subjects": [], "revisions": []}
    assert build_discovery_changes(propose, proposal, reservations=(), artifacts=artifacts, existing_subjects={}) == ()
    assert producer_phase(producer) == PHASES[producer]
    assert producer_role(producer, "producer") == "echelon." + producer + "-producer"
    assert producer_role(producer, "reviewer") == "echelon." + producer + "-reviewer"
    with pytest.raises(ValueError):
        producer_operation_id({}, producer)  # Semantic decoding is not runtime admission.


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("change", [dict(artifact_paths=("spec.md",)),
    dict(artifact_paths=("feasibility-structural-report.json",)),
    dict(editable_revisions=(("FR-000001", "1"),)), dict(assigned_ids=("AC-1000000",))])
def test_assessment_cannot_acquire_source_report_or_identity_scope(producer, change):
    assignment(producer).identity()
    with pytest.raises(ValueError):
        assignment(producer, **change).identity()


def test_feasibility_requires_all_five_slots_including_explicit_conditional_absence():
    selected = assignment("feasibility")
    reply = authored(selected)
    del reply["artifacts"]["kill-report.md"]
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)
    with pytest.raises(ValueError):
        replace(selected, artifact_paths=OUTPUTS["feasibility"][:-1]).identity()


@pytest.mark.parametrize("verdict", ["PASS", "KILL", "DEFER"])
def test_feasibility_preserves_native_verdicts_and_conditional_kill_report(verdict):
    selected = assignment("feasibility")
    reply = authored(selected, verdict, {"status": "killed"} if verdict == "KILL" else {})
    assert validate_discovery_reply(reply, selected)["routing"]["verdict"] == verdict
    candidate = author_artifacts(selected, reply, before=dict.fromkeys(selected.artifact_paths))
    assert ("kill-report.md" in {item.path for item in candidate}) == (verdict == "KILL")
    if verdict == "KILL":
        reply["artifacts"]["kill-report.md"] = None
        with pytest.raises(ValueError):
            validate_discovery_reply(reply, selected)


def test_nonkill_preserves_existing_kill_report_without_creating_or_rewriting_one():
    selected = assignment("feasibility")
    reply = authored(selected)
    before = dict.fromkeys(selected.artifact_paths)
    before["kill-report.md"] = "Earlier retained kill evidence.\n"
    with pytest.raises(ValueError):
        author_artifacts(selected, reply, before=before)
    reply["artifacts"]["kill-report.md"] = before["kill-report.md"]
    assert len(author_artifacts(selected, reply, before=before)) == 5
    with pytest.raises(ValueError):
        author_artifacts(selected, reply, before=dict.fromkeys(selected.artifact_paths))
    reply["artifacts"]["kill-report.md"] = "Replaced prior evidence.\n"
    with pytest.raises(ValueError):
        author_artifacts(selected, reply, before=before)


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("key", ["feasibility_verdict", "feasibility_structural_pass",
    "intent_alignment_check_structural_attempts", "phase", "defer_count", "resolved_by"])
def test_assessment_cannot_supply_controller_certification_or_decisions(producer, key):
    selected = assignment(producer)
    reply = authored(selected, updates={key: 0})
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)


@pytest.mark.parametrize("producer", OUTPUTS)
def test_assessment_cannot_propose_new_or_revised_identities(producer):
    selected = assignment(producer, "propose")
    proposal = {**selected.identity(), "action": "final", "new_subjects": [], "revisions": []}
    for key, value in [("new_subjects", [dict(key="movement", kind="FR", subject="Move", caption="Move")]),
                       ("revisions", [dict(id="FR-000001", expected_revision="1")])]:
        with pytest.raises(ValueError):
            validate_discovery_reply({**proposal, key: value}, selected)


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("reference", ["FR-000001", "FR-999999"])
def test_existing_identity_preview_checks_assessment_references_without_history_changes(tmp_path, producer, reference):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_candidate import IdentityEditScope
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="game", operation_id="import", definitions=(("FR-000001", "movement"),))
    store.apply_lifecycle(spec_id="game", operation_id="adopt", changes=(
        ElementAdopt("FR-000001", "movement", "Movement requirement."),))
    history = store.identity_history(spec_id="game")
    selected = assignment(producer)
    reply = authored(selected)
    reply["artifacts"][selected.artifact_paths[0]] = "Assessment of " + reference + ".\n"
    artifacts = author_artifacts(selected, reply, before=dict.fromkeys(selected.artifact_paths))
    paths = tuple(path for path in selected.artifact_paths if path != "kill-report.md")
    preview = store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=IdentityEditScope(paths, (), paths), operations=())
    assert bool(preview.check.diagnostics) is (reference == "FR-999999")
    assert store.identity_history(spec_id="game") == history
    assert store.lookup(spec_id="game", element_id="FR-999999") is None


@pytest.mark.parametrize("producer", OUTPUTS)
def test_review_is_bound_to_exact_author_routing(producer):
    selected = assignment(producer, "review")
    reply = {**selected.identity(), "action": "final", "verdict": "accept",
        "reason": "Candidate is supported; no gate certification is claimed.", "assessments": []}
    assert validate_discovery_reply(reply, selected) == reply
    assert decode_discovery_assignment(selected.identity()) == selected
    reply["routing"] = {"verdict": "DEFER", "state_updates": {}}
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)
    with pytest.raises(ValueError):
        replace(selected, routing=None).identity()


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("step", ["propose", "author", "review"])
def test_retained_reply_assignment_uses_the_same_closed_decoder(producer, step):
    from harness.discovery_reservations import _assignment
    selected = assignment(producer, step)
    retained = {**selected.identity(), "action": "final"}
    assert _assignment(retained) == selected
    for version in (8, 9, 10, 11, 12):
        if version != selected.identity()["schema_version"]:
            with pytest.raises(ValueError):
                decode_discovery_assignment({**selected.identity(), "schema_version": version})


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("routing", [
    {"verdict": " PASS ", "state_updates": {}},
    {"verdict": "APPROVED", "state_updates": {}},
    {"verdict": "DONE", "state_updates": {}, "next_phase": "phase3-specialists"},
])
def test_assessment_rejects_aliases_and_additional_routing_fields(producer, routing):
    selected = assignment(producer)
    reply = authored(selected)
    with pytest.raises(ValueError):
        validate_discovery_reply({**reply, "routing": routing}, selected)


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("text", ["", " \n", "bad\x00text", None])
def test_required_assessment_outputs_must_be_nonblank_text(producer, text):
    selected = assignment(producer)
    reply = authored(selected)
    reply["artifacts"][selected.artifact_paths[0]] = text
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)


def clarification():
    return dict(status="blocked", blocked_reason="human_clarification_required",
        escalation_question="Is the reduced map scope acceptable?")


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT", "STOP_AND_ASK"])
def test_alignment_uses_native_verdict_and_clarification_contract(verdict):
    selected = assignment("alignment")
    reply = authored(selected, verdict, clarification() if verdict == "STOP_AND_ASK" else {})
    assert validate_discovery_reply(reply, selected) == reply
    if verdict == "STOP_AND_ASK":
        reply["routing"]["state_updates"].update(escalation_recommended_answer="Retain the original scope.",
            escalation_risk_level="high")
        assert validate_discovery_reply(reply, selected) == reply


@pytest.mark.parametrize("updates", [{}, {"status": "blocked"},
    {**clarification(), "blocked_reason": "other"},
    {**clarification(), "escalation_recommended_answer": "Retain scope."},
    {**clarification(), "escalation_risk_level": "high"},
    {**clarification(), "escalation_recommended_answer": "Retain scope.", "escalation_risk_level": "unknown"}])
def test_alignment_rejects_incomplete_or_non_native_clarification(updates):
    selected = assignment("alignment")
    reply = authored(selected, "STOP_AND_ASK", updates)
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT"])
def test_alignment_cannot_hide_a_question_in_an_ordinary_verdict(verdict):
    selected = assignment("alignment")
    reply = authored(selected, verdict, clarification())
    with pytest.raises(ValueError):
        validate_discovery_reply(reply, selected)


@pytest.mark.parametrize("producer", OUTPUTS)
@pytest.mark.parametrize("role", ["producer", "reviewer"])
def test_assessment_roles_are_neutral_prosaic_sources(producer, role):
    path = Path(__file__).resolve().parents[2] / "prosaic/subagents" / ("echelon." + producer + "-" + role + ".md")
    assert path.is_file(), "Phase 2 needs neutral producer/reviewer contracts"
    _, metadata, body = path.read_text().split("---", 2)
    frontmatter = yaml.safe_load(metadata)
    assert frontmatter["name"] == "echelon." + producer + "-" + role
    assert frontmatter["tools"] == "read"
    assert frontmatter["model_tier"] == "strong" and frontmatter["effort"] == "high"
    assert not {"provider", "model", "adapter"} & frontmatter.keys()
    assert "ALWAYS" in body and "NEVER" in body
    assert not any(token in body.lower() for token in (".claude/", ".codex/", "claude", "codex"))
