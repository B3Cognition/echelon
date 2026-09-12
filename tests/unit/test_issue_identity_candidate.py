"""Real authority checks for explicit report provenance and issue lifecycle."""

from contextlib import closing, contextmanager
from dataclasses import replace
import hashlib
import sqlite3
from typing import get_type_hints

import pytest

from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_lifecycle import (
    ElementCreate, ElementRevision, ElementRetirement, ElementTransition,
)
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit
TITLE = "Collision handling is missing"
BODY = "**Severity:** HIGH\n**Evidence:** Movement can cross a wall.\n"
LABEL = "ISS-000001"


def state(path):
    with closing(sqlite3.connect(path / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


def render(label=LABEL, title=TITLE, body=BODY):
    return f"### {label}: {title}\n{body}"


def occurrence(report=None, *, label=LABEL, display=None, revision="1", report_id="review-1",
               title=TITLE, body=BODY):
    report = render(display or label, title, body) if report is None else report
    return IssueOccurrence(label, revision, report_id, hashlib.sha256(report.encode()).hexdigest(),
                           display or label, title, body)


def context(before=None, after=None, *, path="issues.md", before_id="review-1", after_id="review-1"):
    from harness.element_identity_issue_candidate import IssueReportContext
    return IssueReportContext(path, None if before is None else before_id,
                              None if after is None else after_id, before or (), after or ())


def seeded(path, *, record=True, display=LABEL, body=BODY):
    store = IdentityStore.initialize(path)
    store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=4)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(LABEL, TITLE, body, "reserve"),))
    report = render(display, body=body)
    entry = occurrence(report, display=display, body=body)
    if record:
        store.record_issue_occurrences(spec_id="demo", operation_id="observe", occurrences=(entry,))
    return store, report, entry


def check(store, path, before, after, ctx, *, ids=(LABEL,), writable=("issues.md",),
          unowned=("issues.md",), changes=(), artifacts=None):
    original = state(path)
    try:
        return store.check_identity_candidate(
            spec_id="demo", artifacts=artifacts or (CandidateArtifact("issues.md", "issues", before, after),),
            scope=IdentityEditScope(writable, ids, unowned), changes=changes, issue_reports=ctx)
    finally:
        assert state(path) == original


def codes(result):
    return {item.code for item in result.diagnostics}


def test_reserved_issue_creation_binds_body_without_writing_history(tmp_path):
    from contextlib import closing
    import hashlib
    import sqlite3
    from harness.element_identity_bindings import IssueOccurrence
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_issue_candidate import IssueReportContext
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1)
    title = "Collision handling is missing"
    body = "**Severity:** HIGH\nMovement can cross a wall.\n"
    report = f"### {label}: {title}\n{body}"
    occurrence = IssueOccurrence(label, "1", "review-1",
        hashlib.sha256(report.encode("utf-8")).hexdigest(), label, title, body)

    def logical_state():
        with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
            return tuple(connection.iterdump())

    original = logical_state()
    result = store.check_identity_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("issues.md", "issues", None, report),),
        scope=IdentityEditScope(("issues.md",), (label,), ("issues.md",)),
        changes=(ElementCreate(label, title, body, "reserve-issue"),),
        issue_reports=(IssueReportContext("issues.md", None, "review-1", (), (occurrence,)),),
    )
    assert result.diagnostics == ()
    assert logical_state() == original
    assert store.lookup(spec_id="demo", element_id=label) is None


def test_current_issue_can_enter_another_explicit_report(tmp_path):
    store, report, entry = seeded(tmp_path)
    new = replace(entry, report_id="review-2")
    result = check(store, tmp_path, None, report, (context(None, (new,), after_id="review-2"),))
    assert result.diagnostics == ()


@pytest.mark.parametrize("retained", [False, True])
def test_before_requires_exact_real_retained_occurrence(tmp_path, retained):
    store, report, entry = seeded(tmp_path, record=retained)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),))
    assert codes(result) == (set() if retained else {"unrecorded_issue_occurrence"})


@pytest.mark.parametrize("field,value", [
    ("report_sha256", "0" * 64), ("report_id", "wrong"), ("title", "Wrong title"),
    ("body", BODY + "Extra\n"), ("display_id", "ISS-other"),
])
@pytest.mark.parametrize("image", ["before", "after"])
def test_exact_report_payload_mapping(tmp_path, field, value, image):
    store, report, entry = seeded(tmp_path)
    bad = replace(entry, **{field: value})
    ctx = context((bad if image == "before" else entry,), (bad if image == "after" else entry,))
    result = check(store, tmp_path, report, report, (ctx,))
    assert "issue_occurrence_mismatch" in codes(result)


@pytest.mark.parametrize("case", ["missing", "extra", "duplicate", "canonical_duplicate", "display_duplicate"])
def test_report_occurrences_are_one_to_one(tmp_path, case):
    store, report, entry = seeded(tmp_path)
    entries = (entry,)
    if case == "missing":
        entries = ()
    elif case == "extra":
        entries += (replace(entry, issue_id="ISS-000002", display_id="ISS-000002"),)
    elif case == "duplicate":
        entries += (entry,)
    else:
        second_display = "ISS-000002" if case == "canonical_duplicate" else LABEL
        report += render(second_display)
        entries = (occurrence(report), occurrence(report, display=second_display,
                   label=LABEL if case == "canonical_duplicate" else "ISS-000002"))
    result = check(store, tmp_path, None, report, (context(None, entries),))
    assert "issue_occurrence_mismatch" in codes(result)


@pytest.mark.parametrize("case,expected", [
    ("missing", "issue_report_context_missing"), ("target_missing", "issue_report_mismatch"),
    ("wrong_role", "issue_report_mismatch"), ("present_without_id", "issue_report_mismatch"),
    ("absent_with_id", "issue_report_mismatch"), ("absent_with_entries", "issue_report_mismatch"),
])
def test_context_relationships_are_blocking_diagnostics(tmp_path, case, expected):
    store, report, entry = seeded(tmp_path)
    ctx = context((entry,), (entry,))
    before = report
    artifacts = None
    if case == "missing":
        contexts = ()
    else:
        if case == "target_missing":
            ctx = replace(ctx, path="missing.md")
        elif case == "wrong_role":
            artifacts = (CandidateArtifact("issues.md", "references", report, report),)
        elif case == "present_without_id":
            ctx = replace(ctx, after_report_id=None)
        elif case == "absent_with_id":
            before = None
            ctx = replace(ctx, before_occurrences=())
        elif case == "absent_with_entries":
            before = None
            ctx = replace(ctx, before_report_id=None)
        contexts = (ctx,)
    result = check(store, tmp_path, before, report, contexts, artifacts=artifacts)
    assert expected in codes(result)


@pytest.mark.parametrize("case", ["wrong_descriptor", "wrong_occurrence", "path", "report_id", "duplicate_path", "sequence"])
def test_invalid_context_inputs_fail_before_authority(tmp_path, monkeypatch, case):
    store, report, entry = seeded(tmp_path)
    ctx = context((entry,), (entry,))
    if case == "wrong_descriptor":
        contexts = ({"path": "issues.md"},)
    elif case == "duplicate_path":
        contexts = (ctx, ctx)
    else:
        ctx = replace(ctx, **{
            "wrong_occurrence": {"after_occurrences": (object(),)},
            "path": {"path": "a/../issues.md"},
            "report_id": {"after_report_id": " "},
            "sequence": {"before_occurrences": "not a sequence"},
        }[case])
        contexts = (ctx,)
    def forbidden():
        pytest.fail("invalid input must not enter authority")
    monkeypatch.setattr(store, "_transaction", forbidden)
    with pytest.raises(IdentityStoreError):
        check(store, tmp_path, report, report, contexts)


@pytest.mark.parametrize("case", ["missing", "imported", "wrong_revision", "wrong_body", "wrong_title", "terminal"])
def test_after_requires_current_active_exact_issue_revision(tmp_path, case):
    store, report, entry = seeded(tmp_path)
    if case in {"missing", "imported"}:
        label = "ISS-099legacy"
        if case == "imported":
            store.import_identities(spec_id="demo", operation_id="legacy", definitions=((label, TITLE),))
        report, entry = render(label), occurrence(label=label)
    elif case == "wrong_revision":
        entry = replace(entry, issue_revision="2")
    elif case in {"wrong_body", "wrong_title"}:
        title, body = ("Other", BODY) if case == "wrong_title" else (TITLE, "Other\n")
        report = render(title=title, body=body)
        entry = occurrence(report, title=title, body=body)
    else:
        store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(ElementRetirement(LABEL, "1", "Old"),))
    result = check(store, tmp_path, None, report, (context(None, (entry,)),))
    assert "issue_revision_mismatch" in codes(result)


def test_exact_revision_uses_issue_body_and_keeps_original_provenance(tmp_path):
    store, before, old = seeded(tmp_path)
    body = BODY.replace("cross a wall", "cross two walls")
    after = render(body=body)
    new = occurrence(after, revision="2", report_id="review-2", body=body)
    result = check(store, tmp_path, before, after, (context((old,), (new,), after_id="review-2"),),
                   changes=(ElementRevision(LABEL, "1", TITLE, body),))
    assert result.diagnostics == ()
    assert store.issue_occurrences(spec_id="demo", issue_id=LABEL)[0]["issue_revision"] == "1"


@pytest.mark.parametrize("case", ["reservation", "subject", "active_without_after", "unrepresented", "terminal_without_before"])
def test_lifecycle_requires_valid_scope_presence_and_shared_planner(tmp_path, case):
    store, report, entry = seeded(tmp_path)
    before, after = report, report
    ctx = context((entry,), (entry,))
    ids = (LABEL, "ISS-000002")
    if case == "reservation":
        after = render("ISS-000002")
        ctx = context((entry,), (occurrence(label="ISS-000002"),))
        change = ElementCreate("ISS-000002", TITLE, BODY, "missing-reservation")
        expected = "lifecycle_rejected"
    elif case == "subject":
        change = ElementRevision(LABEL, "1", "Different", BODY)
        expected = "lifecycle_rejected"
    elif case == "active_without_after":
        after, ctx = "", context((entry,), ())
        change = ElementRevision(LABEL, "1", TITLE, BODY + "More\n")
        expected = "issue_occurrence_missing"
    elif case == "unrepresented":
        change = ElementCreate("ISS-000002", TITLE, BODY, "reserve")
        expected = "lifecycle_without_artifact"
    else:
        before, ctx = None, context(None, (entry,))
        change = ElementRetirement(LABEL, "1", "Old")
        expected = "lifecycle_without_artifact"
    result = check(store, tmp_path, before, after, (ctx,), changes=(change,), ids=ids)
    assert expected in codes(result)


@pytest.mark.parametrize("kind", ["replace", "split", "merge", "retire"])
def test_issue_transitions_and_retirement_project_without_history_writes(tmp_path, kind):
    store, before, old = seeded(tmp_path)
    predecessors = ((LABEL, "1"),)
    before_entries = (old,)
    if kind == "merge":
        store.apply_lifecycle(spec_id="demo", operation_id="second", changes=(
            ElementCreate("ISS-000002", TITLE, BODY, "reserve"),))
        before += render("ISS-000002")
        before_entries = (occurrence(before), occurrence(before, label="ISS-000002"))
        store.record_issue_occurrences(spec_id="demo", operation_id="observe-pair", occurrences=before_entries)
        predecessors += (("ISS-000002", "1"),)
    successors = () if kind == "retire" else (
        ElementCreate("ISS-000003", "New repair", "New repair body\n", "reserve"),)
    if kind == "split":
        successors += (ElementCreate("ISS-000004", "Other repair", "Other repair body\n", "reserve"),)
    after = "".join(render(s.element_id, s.subject, s.content) for s in successors)
    after_entries = tuple(occurrence(after, label=s.element_id, title=s.subject, body=s.content) for s in successors)
    change = ElementRetirement(LABEL, "1", "Obsolete") if kind == "retire" else ElementTransition(
        kind, predecessors, successors, "Explicit change")
    result = check(store, tmp_path, before, after, (context(before_entries, after_entries),),
                   changes=(change,), ids=tuple(p[0] for p in predecessors) + tuple(s.element_id for s in successors))
    assert result.diagnostics == ()


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("change", ["unchanged", "bytes", "report_id", "tuple"])
def test_historic_exception_requires_complete_authenticated_unchanged_report(tmp_path, terminal, change):
    store, before, old = seeded(tmp_path)
    store.apply_lifecycle(spec_id="demo", operation_id="advance", changes=(
        ElementRetirement(LABEL, "1", "Old") if terminal else ElementRevision(LABEL, "1", TITLE, BODY + "More\n"),))
    after, new = before, old
    report_id = "review-1"
    if change == "bytes":
        after = "# Rerendered\n" + before
        new = occurrence(after)
    elif change == "report_id":
        report_id = "new-report"
        new = replace(old, report_id=report_id)
    elif change == "tuple":
        new = replace(old, issue_revision="2")
    result = check(store, tmp_path, before, after, (context((old,), (new,), after_id=report_id),))
    assert codes(result) == (set() if change == "unchanged" else {"issue_revision_mismatch"})


def test_proposed_retirement_can_retain_exact_historic_rendering(tmp_path):
    store, report, entry = seeded(tmp_path)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),),
                   changes=(ElementRetirement(LABEL, "1", "Explicit retirement"),))
    assert result.diagnostics == ()


@pytest.mark.parametrize("canonical_after", [False, True])
def test_historic_display_alias_needs_exact_binding_and_canonical_after_label(tmp_path, canonical_after):
    store, before, old = seeded(tmp_path, display="ISS-001")
    after = render() if canonical_after else before
    new = occurrence(after, display=LABEL if canonical_after else "ISS-001")
    result = check(store, tmp_path, before, after, (context((old,), (new,)),))
    assert codes(result) == (set() if canonical_after else {"issue_display_identity_mismatch"})


@pytest.mark.parametrize("permission", ["none", "alias", "canonical"])
def test_alias_scope_maps_full_original_block_to_durable_identity(tmp_path, permission):
    store, before, old = seeded(tmp_path, display="ISS-001")
    after, new = render(), occurrence()
    ids = {"none": (), "alias": ("ISS-001",), "canonical": (LABEL,)}[permission]
    result = check(store, tmp_path, before, after, (context((old,), (new,)),), ids=ids, unowned=())
    assert ("element_out_of_scope" in codes(result)) == (permission != "canonical")
    if permission == "canonical":
        assert result.diagnostics == ()


@pytest.mark.parametrize("edit", ["remove", "body", "header", "footer", "guidance"])
def test_report_scope_owns_only_full_issue_blocks(tmp_path, edit):
    body = BODY + "\n### Resolution Guidance\nRepair collision checks.\n"
    store, before, old = seeded(tmp_path, body=body)
    new_body, after = body, before
    if edit == "remove":
        after, entries = "", ()
    else:
        if edit == "body":
            new_body = body.replace("wall", "floor")
        elif edit == "guidance":
            new_body = body.replace("Repair collision checks", "Repair movement checks")
        after = render(body=new_body)
        if edit == "header":
            after = "# Review\n" + after
        elif edit == "footer":
            after += "\n## Summary\nReport complete.\n"
        entries = (occurrence(after, body=new_body),)
    result = check(store, tmp_path, before, after, (context((old,), entries),),
                   ids=() if edit in {"remove", "body", "guidance"} else (LABEL,), unowned=())
    assert ("element_out_of_scope" if edit in {"remove", "body", "guidance"} else "unowned_text_changed") in codes(result)


def test_same_issue_in_two_reports_remains_independently_artifact_scoped(tmp_path):
    store, report, entry = seeded(tmp_path)
    second = replace(entry, report_id="review-2")
    store.record_issue_occurrences(spec_id="demo", operation_id="second-report", occurrences=(second,))
    contexts = (context((entry,), (entry,)), context((second,), (), path="second.md", before_id="review-2", after_id="review-2"))
    artifacts = (CandidateArtifact("issues.md", "issues", report, report), CandidateArtifact("second.md", "issues", report, ""))
    result = check(store, tmp_path, report, report, contexts, artifacts=artifacts)
    assert "artifact_out_of_scope" in codes(result)
    assert "duplicate_definition" not in codes(result)
    result = check(store, tmp_path, report, report, contexts, artifacts=artifacts,
                   writable=("issues.md", "second.md"), unowned=("issues.md", "second.md"))
    assert result.diagnostics == ()


def test_exact_crlf_unicode_and_guidance_body_excludes_report_footer(tmp_path):
    body = "**Evidence:** Žluťoučký 🧱\r\n\r\n### Resolution Guidance\r\n  Opravit.  \r\n"
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1)
    report = f"### {LABEL}: {TITLE}\r\n{body}## Summary\r\nDone.\r\n"
    entry = occurrence(report, body=body)
    result = check(store, tmp_path, None, report, (context(None, (entry,)),),
                   changes=(ElementCreate(LABEL, TITLE, body, "reserve"),))
    assert result.diagnostics == ()


@pytest.mark.parametrize("before,after", [(None, ""), ("", None), ("", "")])
def test_present_empty_reports_have_identity_without_invented_occurrences(tmp_path, before, after):
    store = IdentityStore.initialize(tmp_path)
    ctx = context(None if before is None else (), None if after is None else ())
    result = check(store, tmp_path, before, after, (ctx,), ids=())
    assert result.diagnostics == ()


def test_report_omission_does_not_close_or_rewrite_resolution_history(tmp_path):
    from copy import deepcopy
    from harness.issue_identity import issue_fingerprint, matching_issue_resolution
    store, before, entry = seeded(tmp_path)
    fingerprint = issue_fingerprint(TITLE, BODY)
    ledger = {LABEL: {"status": "validated", "issue_fingerprint": fingerprint}}
    original_ledger = deepcopy(ledger)
    retained = store.issue_occurrences(spec_id="demo", issue_id=LABEL)
    result = check(store, tmp_path, before, "", (context((entry,), ()),))
    assert result.diagnostics == ()
    assert store.lookup(spec_id="demo", element_id=LABEL)["status"] == "active"
    assert store.issue_occurrences(spec_id="demo", issue_id=LABEL) == retained
    assert ledger == original_ledger
    assert matching_issue_resolution(ledger, fingerprint) == ledger[LABEL]
    changed = BODY.replace("wall", "floor")
    assert not matching_issue_resolution(ledger, issue_fingerprint(TITLE, changed))
    assert matching_issue_resolution(ledger, issue_fingerprint(TITLE, BODY.replace("HIGH", "LOW"))) == ledger[LABEL]


@pytest.mark.parametrize("damage", [
    "UPDATE issue_occurrences SET body='Damaged'",
    "UPDATE binding_receipts SET receipt='[]' WHERE operation_id='observe'",
    "DELETE FROM binding_receipts WHERE operation_id='observe'",
    "DELETE FROM revisions WHERE element_id='ISS-000001'",
])
def test_retained_record_receipt_and_target_damage_raises_without_repair(tmp_path, damage):
    store, report, entry = seeded(tmp_path)
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute(damage)
        connection.commit()
    with pytest.raises(IdentityStoreError):
        check(store, tmp_path, report, report, (context((entry,), (entry,)),))


def test_nested_sequences_snapshot_before_single_query_only_transaction(tmp_path, monkeypatch):
    store, report, entry = seeded(tmp_path)
    before_entries, after_entries = [entry], [entry]
    contexts = [context(before_entries, after_entries)]
    transaction = store._transaction
    entered, statements = [], []
    @contextmanager
    def tracked():
        entered.append(True)
        before_entries.clear()
        after_entries.clear()
        contexts.clear()
        with transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    monkeypatch.setattr(store, "_transaction", tracked)
    result = check(store, tmp_path, report, report, contexts)
    assert result.diagnostics == ()
    assert len(entered) == 1
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for sql in statements)
    assert "issue_reports" in get_type_hints(IdentityStore.check_identity_candidate)


@pytest.mark.parametrize("change", ["report", "target"])
def test_issue_reference_claims_retain_original_source_and_revision(tmp_path, change):
    from harness.element_artifacts import parse_identity_artifact
    store, before, old = seeded(tmp_path, body="**Evidence:** See FR-000001.\n")
    store.reserve(spec_id="demo", kind="FR", operation_id="fr-reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="fr-create", changes=(
        ElementCreate("FR-000001", "Movement", "Move.\n", "fr-reserve"),))
    parsed = parse_identity_artifact(path="issues.md", role="issues", text=before)
    reference, = parsed.references
    claim = ReferenceClaim("issues.md", parsed.content_sha256,
                           f"span:{reference.span.start}:{reference.span.end}", "FR-000001", "1", reference.relation)
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(claim,))
    after, new = before, old
    if change == "report":
        after = "# New rendering\n" + before
        new = replace(old, report_sha256=hashlib.sha256(after.encode()).hexdigest())
    else:
        store.apply_lifecycle(spec_id="demo", operation_id="fr-revise", changes=(
            ElementRevision("FR-000001", "1", "Movement", "Move differently.\n"),))
    result = check(store, tmp_path, before, after, (context((old,), (new,)),))
    assert result.diagnostics == ()
    assert result.references[0].assessment_state == ("unassessed" if change == "report" else "historical")
    saved, = store.reference_claims(spec_id="demo", source_path="issues.md", source_sha256=claim.source_sha256)
    assert saved["source_sha256"] == claim.source_sha256
    assert saved["target_revision"] == "1"


def test_active_revision_needs_new_occurrence_even_if_old_report_is_retained(tmp_path):
    store, report, entry = seeded(tmp_path)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),),
                   changes=(ElementRevision(LABEL, "1", TITLE, BODY + "More\n"),))
    assert "issue_occurrence_missing" in codes(result)


@pytest.mark.parametrize("before,after", [(None, ""), ("", None), ("", "")])
def test_empty_report_presence_changes_need_unowned_permission(tmp_path, before, after):
    store = IdentityStore.initialize(tmp_path)
    ctx = context(None if before is None else (), None if after is None else ())
    result = check(store, tmp_path, before, after, (ctx,), ids=(), unowned=())
    assert codes(result) == ({"unowned_text_changed"} if before != after else set())


def test_old_body_boundary_is_rejected_without_rewriting_its_binding(tmp_path):
    old_body = BODY + "## Summary\nPreviously included footer.\n"
    store, report, entry = seeded(tmp_path, body=old_body)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),))
    assert "issue_occurrence_mismatch" in codes(result)
    saved, = store.issue_occurrences(spec_id="demo", issue_id=LABEL)
    assert saved["body"] == old_body


def test_fingerprint_equal_before_changes_do_not_authenticate_payload(tmp_path):
    from harness.issue_identity import issue_fingerprint
    store, before, entry = seeded(tmp_path)
    body = BODY.replace("HIGH", "LOW")
    report, changed = render(body=body), occurrence(body=body)
    assert issue_fingerprint(TITLE, BODY) == issue_fingerprint(TITLE, body)
    result = check(store, tmp_path, report, report, (context((changed,), (changed,)),))
    assert "unrecorded_issue_occurrence" in codes(result)
    saved, = store.issue_occurrences(spec_id="demo", issue_id=LABEL)
    assert saved["report_sha256"] == entry.report_sha256


def test_two_unchanged_reports_can_show_same_canonical_issue(tmp_path):
    store, report, entry = seeded(tmp_path)
    second = replace(entry, report_id="review-2")
    store.record_issue_occurrences(spec_id="demo", operation_id="second-report", occurrences=(second,))
    result = check(store, tmp_path, report, report, (
        context((entry,), (entry,)),
        context((second,), (second,), path="second.md", before_id="review-2", after_id="review-2")),
        artifacts=(CandidateArtifact("issues.md", "issues", report, report),
                   CandidateArtifact("second.md", "issues", report, report)), ids=(), writable=(), unowned=())
    assert result.diagnostics == ()


def test_existing_legacy_spelling_stays_canonical_in_managed_reports(tmp_path):
    from harness.element_identity_lifecycle import ElementAdopt
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="legacy", definitions=(("ISS-007", TITLE),))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(ElementAdopt("ISS-007", TITLE, BODY),))
    report, entry = render("ISS-007"), occurrence(label="ISS-007")
    result = check(store, tmp_path, None, report, (context(None, (entry,)),), ids=("ISS-007",))
    assert result.diagnostics == ()
    padded = render("ISS-000007")
    bad = occurrence(padded, label="ISS-007", display="ISS-000007")
    result = check(store, tmp_path, None, padded, (context(None, (bad,)),), ids=("ISS-007",))
    assert codes(result) == {"issue_display_identity_mismatch"}


def test_historic_old_report_and_fresh_revision_report_can_coexist(tmp_path):
    store, before, old = seeded(tmp_path)
    body = BODY + "More evidence.\n"
    after = render(body=body)
    new = occurrence(after, revision="2", report_id="review-2", body=body)
    result = check(store, tmp_path, before, before, (
        context((old,), (old,)), context(None, (new,), path="second.md", after_id="review-2")),
        artifacts=(CandidateArtifact("issues.md", "issues", before, before),
                   CandidateArtifact("second.md", "issues", None, after)),
        writable=("second.md",), unowned=("second.md",),
        changes=(ElementRevision(LABEL, "1", TITLE, body),))
    assert result.diagnostics == ()


def test_mixed_issue_and_requirement_creation_share_one_planner(tmp_path, monkeypatch):
    from harness import element_identity_lifecycle_store
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="ISS", operation_id="issues", count=1)
    store.reserve(spec_id="demo", kind="FR", operation_id="requirements", count=1)
    body = "**Evidence:** See FR-000001.\n"
    report = render(body=body)
    requirement = "- **FR-000001**: Stop at walls.\n"
    calls = []
    original_planner = element_identity_lifecycle_store.plan_changes
    def tracked(connection, authority, spec_id, changes):
        calls.append(tuple(change.element_id for change in changes))
        return original_planner(connection, authority, spec_id, changes)
    monkeypatch.setattr(element_identity_lifecycle_store, "plan_changes", tracked)
    result = check(store, tmp_path, None, report, (context(None, (occurrence(report, body=body),)),),
        artifacts=(CandidateArtifact("issues.md", "issues", None, report),
                   CandidateArtifact("spec.md", "requirements", None, requirement)),
        ids=(LABEL, "FR-000001"), writable=("issues.md", "spec.md"), unowned=("issues.md", "spec.md"),
        changes=(ElementCreate(LABEL, TITLE, body, "issues"),
                 ElementCreate("FR-000001", "Movement", requirement, "requirements")))
    assert result.diagnostics == ()
    assert result.references[0].target_id == "FR-000001"
    assert result.references[0].assessment_state == "unassessed"
    assert calls == [(LABEL, "FR-000001")]


def test_terminal_effect_cannot_use_unrecorded_before_presence(tmp_path):
    store, report, entry = seeded(tmp_path, record=False)
    result = check(store, tmp_path, report, "", (context((entry,), ()),),
                   changes=(ElementRetirement(LABEL, "1", "Old"),))
    assert {"unrecorded_issue_occurrence", "lifecycle_without_artifact"} <= codes(result)


def test_invalid_nested_occurrence_scalars_fail_before_authority(tmp_path, monkeypatch):
    store, report, entry = seeded(tmp_path)
    broken = replace(entry)
    object.__setattr__(broken, "body", "")
    def forbidden():
        pytest.fail("invalid nested scalar must not enter authority")
    monkeypatch.setattr(store, "_transaction", forbidden)
    with pytest.raises(IdentityStoreError):
        check(store, tmp_path, report, report, (context((entry,), (broken,)),))


def test_issue_parser_diagnostics_and_interval_policy_are_preserved(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    body = "**Evidence:** See FR-001..FR-003 and other::FR-004.\n"
    store, report, entry = seeded(tmp_path, body=body)
    parsed = parse_identity_artifact(path="issues.md", role="issues", text=report)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),))
    assert {row.code for row in parsed.diagnostics} <= codes(result)
    assert "unsupported_reference_range" in codes(result)


@pytest.mark.parametrize("explicit_occurrence", [False, True])
def test_digit_free_legacy_heading_is_not_a_managed_parser_declaration(tmp_path, explicit_occurrence):
    store = IdentityStore.initialize(tmp_path)
    report = render("ISS-legacy")
    entries = (occurrence(label="ISS-legacy"),) if explicit_occurrence else ()
    result = check(store, tmp_path, None, report, (context(None, entries),), ids=("ISS-legacy",))
    assert codes(result) == ({"issue_occurrence_mismatch"} if explicit_occurrence else set())


def test_unrepresented_active_issue_creation_reports_missing_occurrence(tmp_path):
    store, report, entry = seeded(tmp_path)
    result = check(store, tmp_path, report, report, (context((entry,), (entry,)),),
                   ids=(LABEL, "ISS-000002"),
                   changes=(ElementCreate("ISS-000002", TITLE, BODY, "reserve"),))
    assert {"issue_occurrence_missing", "lifecycle_without_artifact"} <= codes(result)


@pytest.mark.parametrize("mixed_family", [False, True])
def test_candidate_cannot_adopt_unassessed_issue_history(tmp_path, mixed_family):
    from harness.element_identity_lifecycle import ElementAdopt
    store = IdentityStore.initialize(tmp_path)
    label = "ISS-007"
    store.import_identities(spec_id="demo", operation_id="import", definitions=((label, TITLE),))
    report, entry = render(label), occurrence(label=label)
    artifacts = (CandidateArtifact("issues.md", "issues", None, report),)
    changes = (ElementAdopt(label, TITLE, BODY),)
    ids, paths = (label,), ("issues.md",)
    if mixed_family:
        store.reserve(spec_id="demo", kind="FR", operation_id="requirements", count=1)
        requirement = "- **FR-000001**: Stop at walls.\n"
        artifacts += (CandidateArtifact("spec.md", "requirements", None, requirement),)
        changes += (ElementCreate("FR-000001", "Movement", requirement, "requirements"),)
        ids += ("FR-000001",)
        paths += ("spec.md",)
    result = check(store, tmp_path, None, report, (context(None, (entry,)),),
                   artifacts=artifacts, changes=changes, ids=ids, writable=paths, unowned=paths)
    assert "lifecycle_rejected" in codes(result)
    assert store.lookup(spec_id="demo", element_id=label)["status"] == "imported"
    assert store.lookup(spec_id="demo", element_id="FR-000001") is None


def test_candidate_adoption_rejection_does_not_mask_issue_authority_damage(tmp_path):
    from harness.element_identity_lifecycle import ElementAdopt
    store = IdentityStore.initialize(tmp_path)
    label = "ISS-007"
    store.import_identities(spec_id="demo", operation_id="import", definitions=((label, TITLE),))
    report, entry = render(label), occurrence(label=label)
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("UPDATE counters SET high_water='0' WHERE kind='ISS'")
        connection.commit()
    with pytest.raises(IdentityStoreError, match="below retained numeric claims"):
        check(store, tmp_path, None, report, (context(None, (entry,)),), ids=(label,),
              changes=(ElementAdopt(label, TITLE, BODY),))
