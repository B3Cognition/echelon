"""WHY1 reviews cannot become edits to earlier producer definitions."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from harness.discovery_candidate import DiscoveryReservation, author_artifacts, build_discovery_changes
from harness.discovery_semantics import DiscoveryAssignment, decode_discovery_assignment, validate_discovery_reply
from harness.element_identity_candidate import IdentityEditScope
from harness.element_identity_store import IdentityStore
from tests.unit.test_element_identity_candidate_preview import op, sql_state

PATHS = ("assumption-review.md", "issues.md", "unknowns.md")


def routing(verdict="PASS"):
    return dict(verdict=verdict, question="Which audience?" if verdict == "STOP_AND_ASK" else None,
        recommended_answer=None, risk_level=None)


def assignment(step="propose", *, kind="ISS", verdict="PASS"):
    return DiscoveryAssignment("why1-" + "a" * 32, "turn-" + step, "game", "first", step,
        "b" * 64, PATHS, assigned_ids=(kind + "-000001",) if step != "propose" else (),
        producer="why1", routing=tuple(routing(verdict).items()) if step == "review" else None)


def reply(bound, *, kind="ISS", verdict="PASS"):
    result = {**bound.identity(), "action": "final"}
    if bound.step == "propose":
        result.update(new_subjects=[dict(key="audience", kind=kind, subject="Audience" if kind == "ISS" else "Audience ambiguity", caption="Audience")], revisions=[])
    elif bound.step == "author":
        result.update(artifacts={"assumption-review.md": "# Assumption Review\n\n## Verdict: " + ("FAIL" if verdict == "STOP_AND_ASK" else verdict) + "\n",
            "issues.md": "# Issues\n\n### ISS-000001: Audience\nClarify audience.\n" if kind == "ISS" else None,
            "unknowns.md": "# Unknowns\n" + ("\n### U-000001: Audience\nClarify audience.\n" if kind == "U" else "")}, routing=routing(verdict))
    else:
        result.update(verdict="accept", reason="Supported findings.", assessments=[dict(id=label, verdict="accept",
            reason="Correct subject.", evidence=["source:inputs/request.md:hash"]) for label in bound.assigned_ids])
    return result


@pytest.mark.parametrize("step", ["propose", "author", "review"])
@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "STOP_AND_ASK", "BLOCKED"])
def test_why1_exact_assignment_recovery_binds_routing(step, verdict):
    bound = assignment(step, verdict=verdict)
    value = reply(bound, verdict=verdict)
    assert bound.identity()["schema_version"] == 4
    assert decode_discovery_assignment(json.loads(json.dumps(bound.identity()))) == bound
    assert validate_discovery_reply(value, bound) == value
    if step == "review":
        value["routing"]["verdict"] = "FAIL" if verdict == "PASS" else "PASS"
        with pytest.raises(ValueError):
            validate_discovery_reply(value, bound)


@pytest.mark.parametrize("kind", ["U", "ISS"])
def test_why1_new_subjects_use_existing_authority_preview_without_publishing(tmp_path, kind):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="game", kind=kind, operation_id="reserve", count=1)
    proposal, author = assignment(kind=kind), assignment("author", kind=kind)
    materials = author_artifacts(author, reply(author, kind=kind), before=dict.fromkeys(PATHS))
    changes = build_discovery_changes(proposal, reply(proposal, kind=kind), artifacts=materials,
        reservations=(DiscoveryReservation("audience", label, "reserve"),), existing_subjects={})
    before = sql_state(tmp_path)
    paths = tuple(item.path for item in materials)
    operations = (op("lifecycle", "candidate", *changes),)
    contexts = ()
    if kind == "ISS":
        import hashlib
        from harness.element_identity_bindings import IssueOccurrence
        from harness.element_identity_issue_candidate import IssueReportContext
        occurrence = IssueOccurrence(label, "1", "why1-review", hashlib.sha256(reply(author)["artifacts"]["issues.md"].encode()).hexdigest(),
            label, "Audience", "Clarify audience.\n")
        operations += (op("issue_occurrences", "report", occurrence),)
        contexts = (IssueReportContext("issues.md", None, "why1-review", (), (occurrence,)),)
    preview = store.preview_identity_candidate(spec_id="game", artifacts=materials,
        scope=IdentityEditScope(paths, (label,), paths), operations=operations, issue_reports=contexts)
    assert preview.check.diagnostics == ()
    assert [(item.element_id, item.subject) for item in changes] == [(kind + "-000001", "Audience" if kind == "ISS" else "Audience ambiguity")]
    assert sql_state(tmp_path) == before and store.lookup(spec_id="game", element_id=label) is None


@pytest.mark.parametrize("damage", ["assumptions", "old_unknown_revision", "foreign_id", "empty_report", "delete_issues", "change_unknown", "remove_unknown", "change_unknown_whitespace", "bad_verdict", "question_on_fail", "authority"])
def test_why1_contract_rejects_upstream_mutation_and_unbound_authority(damage):
    bound = assignment("author")
    before = dict.fromkeys(PATHS)
    before["unknowns.md"] = "# Unknowns\n\n### U-001: Controls\nPreserve exact evidence.\n"
    payload = reply(bound)
    payload["artifacts"]["unknowns.md"] = before["unknowns.md"]
    if damage == "assumptions": bound = replace(bound, artifact_paths=(*PATHS, "assumptions.md"))
    elif damage == "old_unknown_revision": bound = replace(bound, editable_revisions=(("U-001", "1"),))
    elif damage == "foreign_id": bound = replace(bound, assigned_ids=("A-000001",))
    elif damage == "empty_report": payload["artifacts"]["assumption-review.md"] = " "
    elif damage == "delete_issues":
        before["issues.md"] = payload["artifacts"]["issues.md"]
        payload["artifacts"]["issues.md"] = None
    elif damage == "change_unknown": payload["artifacts"]["unknowns.md"] = before["unknowns.md"].replace("exact", "different")
    elif damage == "remove_unknown": payload["artifacts"]["unknowns.md"] = "# Unknowns\n"
    elif damage == "change_unknown_whitespace": payload["artifacts"]["unknowns.md"] += "\n"
    elif damage == "bad_verdict": payload["routing"]["verdict"] = "DONE"
    elif damage == "question_on_fail": payload["routing"].update(verdict="FAIL", question="Secret decision?")
    else: payload["routing"]["next_phase"] = "phase1-constitution"
    with pytest.raises(ValueError):
        author_artifacts(bound, payload, before=before)


def test_why1_unknown_append_preserves_existing_definition_bytes(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementAdopt
    store = IdentityStore.initialize(tmp_path)
    bound = assignment("author", kind="U")
    before = dict.fromkeys(PATHS)
    before["unknowns.md"] = "# Unknowns\n\n### U-001: Controls\nPreserve exact evidence.\n"
    payload = reply(bound, kind="U")
    store.import_identities(spec_id="game", operation_id="import", definitions=(("U-001", "Controls"),))
    old, = parse_identity_artifact(path="unknowns.md", role="unknowns", text=before["unknowns.md"]).declarations
    store.apply_lifecycle(spec_id="game", operation_id="adopt", changes=(ElementAdopt("U-001", "Controls", old.content),))
    new_id, = store.reserve(spec_id="game", kind="U", operation_id="reserve", count=1)
    assert new_id == "U-000002"
    bound = replace(bound, assigned_ids=(new_id,))
    payload = reply(bound, kind="U")
    payload["artifacts"]["unknowns.md"] = before["unknowns.md"] + "### U-000002: Audience\nClarify audience.\n"
    materials = author_artifacts(bound, payload, before=before)
    assert next(item for item in materials if item.path == "unknowns.md").after_text.startswith(before["unknowns.md"])
    proposal = assignment(kind="U")
    changes = build_discovery_changes(proposal, reply(proposal, kind="U"), artifacts=materials,
        reservations=(DiscoveryReservation("audience", new_id, "reserve"),), existing_subjects={})
    paths = tuple(item.path for item in materials)
    observed = store.preview_identity_candidate(spec_id="game", artifacts=materials,
        scope=IdentityEditScope(paths, (new_id,), paths), operations=(op("lifecycle", "candidate", *changes),))
    assert observed.check.diagnostics == ()
    assert store.lookup(spec_id="game", element_id="U-001")["subject"] == "Controls"


def test_why1_issue_subject_must_match_report_title_before_reservation():
    bound = assignment()
    value = reply(bound)
    value["new_subjects"][0]["subject"] = "Different immutable subject"
    with pytest.raises(ValueError):
        validate_discovery_reply(value, bound)


@pytest.mark.parametrize("report", ["## Verdict: FAIL\n", "## Verdict: PASS\n## Verdict: FAIL\n", "No verdict\n"])
def test_why1_report_cannot_contradict_structured_verdict(report):
    bound = assignment("author")
    payload = reply(bound)
    payload["artifacts"]["assumption-review.md"] = report
    with pytest.raises(ValueError):
        author_artifacts(bound, payload, before=dict.fromkeys(PATHS))


def test_why1_issue_report_composition_reuses_native_provenance(tmp_path):
    from harness.discovery_candidate import issue_report_changes
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="game", kind="ISS", operation_id="reserve", count=1)
    report = "# Issues\n\n### ISS-000001: Audience\nClarify audience.\n"
    artifact = CandidateArtifact("issues.md", "issues", None, report)
    change = ElementCreate(label, "Audience", "Clarify audience.\n", "reserve")
    contexts, occurrences = issue_report_changes((artifact,), (change,), store.identity_history(spec_id="game"), report_id="why1-report")
    operations = (op("lifecycle", "create", change), op("issue_occurrences", "report", *occurrences))
    preview = store.preview_identity_candidate(spec_id="game", artifacts=(artifact,),
        scope=IdentityEditScope(("issues.md",), (label,), ("issues.md",)), operations=operations, issue_reports=contexts)
    assert preview.check.diagnostics == ()
    store.apply_lifecycle(spec_id="game", operation_id="create", changes=(change,))
    store.record_issue_occurrences(spec_id="game", operation_id="report", occurrences=occurrences)
    history = store.identity_history(spec_id="game")
    unchanged = replace(artifact, before_text=report)
    retained, extra = issue_report_changes((unchanged,), (), history, report_id="next-report")
    assert extra == () and retained[0].before_occurrences == retained[0].after_occurrences == occurrences
    updated = replace(unchanged, after_text=report.replace("Clarify audience.", "Audience is clarified."))
    revision = ElementRevision(label, "1", "Audience", "Audience is clarified.\n")
    revised, extra = issue_report_changes((updated,), (revision,), history, report_id="next-report")
    assert revised[0].before_occurrences == occurrences and extra[0].issue_revision == "2"
    preview = store.preview_identity_candidate(spec_id="game", artifacts=(updated,),
        scope=IdentityEditScope(("issues.md",), (label,), ()),
        operations=(op("lifecycle", "revise", revision), op("issue_occurrences", "next-report", *extra)), issue_reports=revised)
    assert preview.check.diagnostics == ()
    with pytest.raises(ValueError):
        issue_report_changes((replace(unchanged, before_text=report + "tampered"),), (), history, report_id="bad")
    # A preserved old report remains evidence after a later lifecycle revision.
    store.apply_lifecycle(spec_id="game", operation_id="revision-elsewhere", changes=(revision,))
    retained, extra = issue_report_changes((unchanged,), (), store.identity_history(spec_id="game"), report_id="historical")
    assert extra == () and retained[0].before_occurrences == occurrences
    preview = store.preview_identity_candidate(spec_id="game", artifacts=(unchanged,),
        scope=IdentityEditScope((), (), ()), operations=(), issue_reports=retained)
    assert preview.check.diagnostics == ()


@pytest.mark.parametrize("producer", ["discovery", "synthesizer", "tracker"])
def test_why1_cannot_relabel_old_assignments(producer):
    value = assignment().identity()
    value["producer"] = producer
    with pytest.raises(ValueError):
        decode_discovery_assignment(value)
