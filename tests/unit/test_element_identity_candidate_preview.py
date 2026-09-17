"""Coherent candidate and journal observations do not authorize publication."""

from collections.abc import Sequence
from contextlib import closing, contextmanager
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import sqlite3
import subprocess
import sys
from threading import Event, Thread

import pytest

from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_candidate import CandidateArtifact, CandidateDiagnostic, IdentityEditScope
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_lifecycle import ElementCreate, ElementRevision, ElementRetirement, ElementTransition
from harness.element_identity_publication import PublicationOperation, PublicationIntentRequest
from harness.element_identity_request_codec import encode_request
from harness.element_identity_store import IdentityStore, IdentityStoreError

pytestmark = pytest.mark.unit


def sql_state(path):
    with closing(sqlite3.connect(path / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


def op(method, operation_id, *entries):
    return PublicationOperation(method, operation_id, encode_request(method, entries))


def revision_fixture(path):
    store = IdentityStore.initialize(path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    before = f"- **{label}**: Move using WASD.\n"
    after = f"- **{label}**: Move using arrow keys.\n"
    old, = parse_identity_artifact(path="spec.md", role="requirements", text=before).declarations
    new, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Movement", old.content, "reserve"),))
    return store, dict(spec_id="demo",
        artifacts=(CandidateArtifact("spec.md", "requirements", before, after),),
        scope=IdentityEditScope(("spec.md",), (label,)),
        operations=(op("lifecycle", "revise", ElementRevision(label, "1", "Movement", new.content)),))


def observe(store, path, **request):
    before = sql_state(path)
    try:
        result = store.preview_identity_candidate(**request)
        assert (result.history is None) == bool(result.check.diagnostics)
        return result
    finally:
        assert sql_state(path) == before


def apply_history(store, path, request, history, publication="publication"):
    # This opaque test manifest/recovery payload is not filesystem publication.
    intent = PublicationIntentRequest("a" * 64, "opaque test recovery", request.get("operations", ()),
                                      proposed_history_sha256=history.sha256)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id=publication, request=intent)
    assert store.prepare_identity_publication(spec_id="demo", operation_id=publication, request=intent) == preparation
    receipt = store.apply_identity_publication(spec_id="demo", operation_id=publication)
    assert receipt["version"] == "3"
    assert receipt["identity_history_sha256"] == history.sha256
    reopened = IdentityStore.open(path)
    assert reopened.apply_identity_publication(spec_id="demo", operation_id=publication) == receipt
    assert reopened.identity_history(spec_id="demo") == history
    reopened.release_identity_publication(spec_id="demo", operation_id=publication, completion_payload="test complete")
    assert reopened.identity_history(spec_id="demo") == history


def test_candidate_preview_uses_exact_journal_operations(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000001"
    before = f"- **{label}**: Move using WASD.\n"
    after = f"- **{label}**: Move using arrow keys.\n"
    old, = parse_identity_artifact(path="spec.md", role="requirements", text=before).declarations
    new, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Movement", old.content, "reserve"),))
    changes = (ElementRevision(label, "1", "Movement", new.content),)
    operations = (PublicationOperation("lifecycle", "revise", encode_request("lifecycle", changes)),)
    artifacts = (CandidateArtifact("spec.md", "requirements", before, after),)
    scope = IdentityEditScope(("spec.md",), (label,))
    existing_check = store.check_identity_candidate(
        spec_id="demo", artifacts=artifacts, scope=scope, changes=changes)
    assert existing_check.diagnostics == ()
    existing_history = store.preview_identity_history(spec_id="demo", operations=operations)
    value = json.loads(existing_history.payload)
    assert [row["revision"] for row in value["revisions"]] == ["1", "2"]
    assert value["revisions"][0]["content"] == old.content
    assert value["revisions"][1]["content"] == new.content
    original = sql_state(tmp_path)
    result = store.preview_identity_candidate(
        spec_id="demo", artifacts=artifacts, scope=scope, operations=operations)
    assert result.check == existing_check
    assert result.history == existing_history
    assert sql_state(tmp_path) == original
    apply_history(store, tmp_path, {"operations": operations}, result.history)


@pytest.mark.parametrize("kind", ["replace", "split", "merge", "retire"])
def test_exact_transition_and_retirement_history(tmp_path, kind):
    from tests.unit.test_definition_identity_candidate import seed_artifacts, requirement_transition_fixture
    before, predecessors = requirement_transition_fixture(kind)
    store = seed_artifacts(tmp_path, (("spec.md", "requirements", before),))
    if kind == "retire":
        after, successors = "", ()
        changes = (ElementRetirement(predecessors[0], "1", "Reviewed retirement"),)
    else:
        reserved = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=2)
        successors = reserved if kind == "split" else reserved[:1]
        after = "".join(f"- **{label}**: Successor requirement.\n" for label in successors)
        declarations = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
        changes = (ElementTransition(kind, tuple((label, "1") for label in predecessors), tuple(
            ElementCreate(row.element_id, "Successor", row.content, "reserve") for row in declarations),
            "Reviewed transition"),)
    request = dict(spec_id="demo", artifacts=(CandidateArtifact("spec.md", "requirements", before, after),),
        scope=IdentityEditScope(("spec.md",), predecessors + successors), operations=(op("lifecycle", kind, *changes),))
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == ()
    value = json.loads(result.history.payload)
    assert {(row["element_id"], row["status"], row["revision"]) for row in value["entities"]} == (
        {(label, "retired" if kind == "retire" else "superseded", "2") for label in predecessors}
        | {(label, "active", "1") for label in successors})
    assert {(row["predecessor_id"], row["successor_id"], row["kind"]) for row in value["lineage"]} == {
        (old, new, kind) for old in predecessors for new in successors}
    apply_history(store, tmp_path, request, result.history)


@pytest.mark.parametrize("wide", [False, True])
def test_reserved_creation_keeps_six_and_seven_digit_strings(tmp_path, wide):
    store = IdentityStore.initialize(tmp_path)
    if wide:
        store.import_identities(spec_id="demo", operation_id="legacy", definitions=(("FR-999999", "Old"),))
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == ("FR-1000000" if wide else "FR-000001")
    after = f"- **{label}**: Move.\n"
    declaration, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
    request = dict(spec_id="demo", artifacts=(CandidateArtifact("spec.md", "requirements", None, after),),
        scope=IdentityEditScope(("spec.md",), (label,)),
        operations=(op("lifecycle", "create", ElementCreate(label, "Movement", declaration.content, "reserve")),))
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == ()
    entities = json.loads(result.history.payload)["entities"]
    assert entities[-1]["element_id"] == label
    assert entities[-1]["ordinal"] == ("1000000" if wide else "1")
    if wide:
        assert (entities[0]["element_id"], entities[0]["status"], entities[0]["revision"]) == ("FR-999999", "imported", None)
    apply_history(store, tmp_path, request, result.history)


@pytest.mark.parametrize("case", ["nested", "task", "unknown", "assumption"])
def test_native_nested_and_legacy_edits_preserve_subjects(tmp_path, case):
    from tests.unit.test_definition_identity_candidate import seed_artifacts, nested_requirement, canonical_task
    role, before = {
        "nested": ("requirements", nested_requirement()),
        "task": ("tasks", canonical_task("T-S01", req="T-S01")),
        "unknown": ("unknowns", "### U-001: Lighting\nOriginal.\n"),
        "assumption": ("assumptions", "### A-001: Lighting\nOriginal.\n"),
    }[case]
    after = before.replace("Arrow keys move", "WASD moves").replace("Implement movement", "Implement arrows").replace("Original.", "Revised.")
    declarations = parse_identity_artifact(path="spec.md", role=role, text=after).declarations
    subjects = {row.element_id: row.caption if case in {"unknown", "assumption"} else "Stable subject" for row in declarations}
    store = seed_artifacts(tmp_path, (("spec.md", role, before),), subjects=subjects)
    request = dict(spec_id="demo", artifacts=(CandidateArtifact("spec.md", role, before, after),),
        scope=IdentityEditScope(("spec.md",), tuple(subjects)), operations=(op("lifecycle", "revise", *(
            ElementRevision(row.element_id, "1", subjects[row.element_id], row.content) for row in declarations)),))
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == ()
    assert {row["element_id"]: row["subject"] for row in json.loads(result.history.payload)["entities"]} == subjects
    apply_history(store, tmp_path, request, result.history)


@pytest.mark.parametrize("case", ["removed", "renumbered", "scope", "content"])
def test_rejected_edits_have_independent_exact_diagnostics(tmp_path, case):
    store, request = revision_fixture(tmp_path)
    artifact, = request["artifacts"]
    rows = []
    if case == "removed":
        request.update(operations=(), artifacts=(replace(artifact, after_text=""),))
        rows = [("definition_removed", "FR-000001", "active declaration removed without retirement or transition")]
    elif case == "renumbered":
        request.update(operations=(), artifacts=(replace(artifact, after_text=artifact.before_text.replace("FR-000001", "FR-000002")),),
                       scope=IdentityEditScope(("spec.md",), ("FR-000001", "FR-000002")))
        rows = [("definition_removed", "FR-000001", "active declaration removed without retirement or transition"),
                ("unallocated_definition", "FR-000002", "declaration has no materialized or projected identity"),
                ("unallocated_definition", "FR-000002", "new declaration requires exact reserved creation or transition successor")]
    elif case == "scope":
        request.update(operations=(), scope=IdentityEditScope((), ()))
        rows = [("artifact_out_of_scope", None, "changed artifact is not writable"),
                ("definition_content_mismatch", "FR-000001", "declaration differs from exact current or projected content"),
                ("element_out_of_scope", "FR-000001", "definition changed outside element scope")]
        rows.insert(1, ("unowned_text_changed", None, "text outside authorized definition spans changed"))
    else:
        request["operations"] = (op("lifecycle", "wrong-content", ElementRevision("FR-000001", "1", "Movement", "Other content")),)
        rows = [("definition_content_mismatch", "FR-000001", "declaration differs from exact current or projected content")]
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == tuple(CandidateDiagnostic(code, "spec.md", label, detail) for code, label, detail in rows)
    assert result.history is None


@pytest.mark.parametrize("mutation", [None, "hash", "span", "target", "relation", "revision", "omitted"])
def test_proposed_claims_authenticate_sources_without_relabeling_observations(tmp_path, mutation):
    store, request = revision_fixture(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("U-001", "Unknown"),))
    text = "See FR-000001 and U-001."
    claim = ReferenceClaim("evidence.md", hashlib.sha256(text.encode()).hexdigest(), "span:4:13", "FR-000001", "2", "evidence")
    store.record_reference_claims(spec_id="demo", operation_id="old-evidence", claims=(replace(claim, target_revision="1"),))
    request["artifacts"] += (CandidateArtifact("evidence.md", "evidence", text, text),)
    if mutation not in {None, "omitted"}:
        claim = replace(claim, **{
            "hash": {"source_sha256": "b" * 64}, "span": {"source_anchor": "span:0:9"},
            "target": {"target_id": "U-001"}, "relation": {"relation": "reference"},
            "revision": {"target_revision": "999"},
        }[mutation])
    if mutation != "omitted":
        request["operations"] += (op("reference_claims", "new-evidence", claim,
            ReferenceClaim("evidence.md", hashlib.sha256(text.encode()).hexdigest(), "span:18:23", "U-001", None, "evidence")),)
    if mutation == "revision":
        with pytest.raises(IdentityStoreError):
            observe(store, tmp_path, **request)
        return
    result = observe(store, tmp_path, **request)
    assert [(row.target_id, row.assessed_revisions, row.assessment_state) for row in result.check.references] == [
        ("FR-000001", ("1",), "historical"), ("U-001", (), "unassessed")]
    if mutation in {"hash", "span", "target", "relation"}:
        code, detail = (("reference_source_hash_mismatch", "claim source hash does not match supplied after image")
            if mutation == "hash" else ("reference_source_binding_mismatch", "claim requires an exact parsed span, target and relation match"))
        assert result.check.diagnostics == (CandidateDiagnostic(code, "evidence.md", claim.target_id, detail),)
    else:
        assert result.check.diagnostics == ()
        value = json.loads(result.history.payload)
        assert next(row for row in value["reference_claims"] if row["operation_id"] == "old-evidence")["target_revision"] == "1"
        assert len(value["reference_claims"]) == (1 if mutation == "omitted" else 3)
        apply_history(store, tmp_path, request, result.history)


@pytest.mark.parametrize("case", ["orphan", "missing", "changed-missing", "changed-matched", "historic", "repeat", "bad-provenance"])
def test_issue_children_and_reports_require_full_association(tmp_path, case):
    from tests.unit.test_issue_identity_candidate import seeded, context, render, occurrence, LABEL, BODY
    store, report, entry = seeded(tmp_path, record=case != "bad-provenance")
    ctx = context((entry,), (entry,))
    artifacts = (CandidateArtifact("issues.md", "issues", report, report),)
    operations = ()
    expected = ()
    if case == "orphan":
        artifacts = (CandidateArtifact("notes.md", "references", "", ""),)
        contexts = ()
        operations = (op("issue_occurrences", "orphan", entry),)
        expected = (CandidateDiagnostic("issue_operation_unbound", None, LABEL,
            "proposed occurrence requires an exact captured after report occurrence"),)
    else:
        if case in {"missing", "changed-missing", "changed-matched"}:
            body = BODY + "New evidence.\n" if case.startswith("changed") else BODY
            after = render(body=body)
            new = occurrence(after, body=body, report_id="review-2", revision="2" if case.startswith("changed") else "1")
            ctx = context((entry,), (new,), after_id="review-2")
            artifacts = (CandidateArtifact("issues.md", "issues", report, after),)
            if case.startswith("changed"):
                operations = (op("lifecycle", "revise", ElementRevision(LABEL, entry.issue_revision, entry.title, body)),)
            if case == "changed-matched":
                operations += (op("issue_occurrences", "observe-after", new),)
            else:
                expected = (CandidateDiagnostic("issue_operation_missing", "issues.md", LABEL,
                    "after occurrence requires an exact proposed operation or retained provenance"),)
        elif case == "historic":
            store.apply_lifecycle(spec_id="demo", operation_id="later", changes=(
                ElementRevision(LABEL, "1", entry.title, BODY + "Later body.\n"),))
        elif case == "repeat":
            operations = (op("issue_occurrences", "observe-again", entry),)
        elif case == "bad-provenance":
            operations = (op("issue_occurrences", "observe-after", entry),)
            expected = (CandidateDiagnostic("unrecorded_issue_occurrence", "issues.md", LABEL,
                "before occurrence lacks exact authenticated retained provenance"),)
        contexts = (ctx,)
    request = dict(spec_id="demo", artifacts=artifacts,
        scope=IdentityEditScope(tuple(row.path for row in artifacts), (LABEL,), tuple(row.path for row in artifacts)),
        operations=operations, issue_reports=contexts)
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == expected
    if not expected:
        apply_history(store, tmp_path, request, result.history)


@pytest.mark.parametrize("field,value", [
    ("issue_id", "ISS-000002"), ("issue_revision", "2"), ("report_id", "other"),
    ("report_sha256", "b" * 64), ("display_id", "ISS-000002"), ("title", "Different title"), ("body", "Different body"),
])
def test_issue_operation_matches_every_native_occurrence_field(tmp_path, field, value):
    from tests.unit.test_issue_identity_candidate import seeded, context, LABEL
    store, report, entry = seeded(tmp_path)
    after = replace(entry, report_id="review-2")
    proposed = replace(after, **{field: value})
    result = observe(store, tmp_path, spec_id="demo",
        artifacts=(CandidateArtifact("issues.md", "issues", report, report),),
        scope=IdentityEditScope((), ()), issue_reports=(context((entry,), (after,), after_id="review-2"),),
        operations=(op("issue_occurrences", "new", proposed),))
    assert result.check.diagnostics == (
        CandidateDiagnostic("issue_operation_unbound", None, proposed.issue_id,
            "proposed occurrence requires an exact captured after report occurrence"),
        CandidateDiagnostic("issue_operation_missing", "issues.md", LABEL,
            "after occurrence requires an exact proposed operation or retained provenance"),
    )


def test_matching_child_cannot_authenticate_malformed_report(tmp_path):
    from tests.unit.test_issue_identity_candidate import seeded, context, LABEL
    store, report, entry = seeded(tmp_path)
    bad = replace(entry, report_sha256="b" * 64)
    result = observe(store, tmp_path, spec_id="demo",
        artifacts=(CandidateArtifact("issues.md", "issues", None, report),),
        scope=IdentityEditScope(("issues.md",), (LABEL,), ("issues.md",)),
        issue_reports=(context(None, (bad,)),), operations=(op("issue_occurrences", "new", bad),))
    assert result.check.diagnostics == (CandidateDiagnostic("issue_occurrence_mismatch", "issues.md", LABEL,
        "after: occurrence must match exact report hash, ID, title and typed body"),)


def test_supplemental_descriptors_are_native_and_detached(tmp_path, monkeypatch):
    from harness.element_identity_bundle import LexiconProjectionSource, EvidenceInventoryContext
    from tests.unit.test_supplemental_identity_bundle import SOURCE, projection, inventory, seeded_store
    store = seeded_store(tmp_path)
    descriptor = LexiconProjectionSource("projection.lexicon", "spec.md")
    seeds = ["https://example.test/AC-3000000"]
    inventory_context = EvidenceInventoryContext("evidence.json", seeds)
    text, evidence = projection(), inventory()
    request = dict(spec_id="demo", scope=IdentityEditScope((), ()),
        artifacts=[CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
            CandidateArtifact("projection.lexicon", "lexicon_projection", text, text),
            CandidateArtifact("evidence.json", "evidence_inventory", evidence, evidence)],
        projection_sources=[descriptor], evidence_inventories=[inventory_context])
    original = store._transaction
    @contextmanager
    def mutate_at_entry(**kwargs):
        object.__setattr__(descriptor, "source_path", "wrong.md")
        object.__setattr__(inventory_context, "path", "wrong.json")
        seeds.append("https://unread.test")
        with original(**kwargs) as connection:
            yield connection
    monkeypatch.setattr(store, "_transaction", mutate_at_entry)
    result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == ()
    assert len(json.loads(result.history.payload)["entities"]) == 3


@pytest.mark.parametrize("before,after,unowned,expected", [
    (None, "", False, ("unowned_text_changed",)), (None, "", True, ()),
    ("", None, False, ("unowned_text_changed",)), ("", "", False, ()),
])
def test_absent_and_empty_images_retain_native_scope_meaning(tmp_path, before, after, unowned, expected):
    store = IdentityStore.initialize(tmp_path)
    result = observe(store, tmp_path, spec_id="demo", artifacts=(CandidateArtifact("glossary.md", "glossary", before, after),),
        scope=IdentityEditScope(("glossary.md",), (), ("glossary.md",) if unowned else ()))
    assert tuple(row.code for row in result.check.diagnostics) == expected


@pytest.mark.parametrize("owner_spec", ["demo", "other"])
@pytest.mark.parametrize("phase", ["ordinary", "prepared", "applied", "released"])
def test_used_and_claimed_children_are_global_and_pending_is_spec_local(tmp_path, owner_spec, phase):
    store, request = revision_fixture(tmp_path)
    if phase == "ordinary":
        store.import_identities(spec_id=owner_spec, operation_id="revise", definitions=(("U-001", "Unknown"),))
    else:
        store.reserve(spec_id=owner_spec, kind="AC", operation_id="reserve-ac", count=1)
        child = op("lifecycle", "revise", ElementCreate("AC-000001", "Acceptance", "Body", "reserve-ac"))
        store.prepare_identity_publication(spec_id=owner_spec, operation_id="parent",
            request=PublicationIntentRequest("a" * 64, "test recovery", (child,)))
        if phase in {"applied", "released"}:
            store.apply_identity_publication(spec_id=owner_spec, operation_id="parent")
        if phase == "released":
            store.release_identity_publication(spec_id=owner_spec, operation_id="parent", completion_payload="complete")
    with pytest.raises(IdentityStoreError) as error:
        observe(store, tmp_path, **request)
    assert error.value.__cause__ is None and error.value.__context__ is None
    unchanged = replace(request["artifacts"][0], after_text=request["artifacts"][0].before_text)
    request.update(artifacts=(unchanged,), operations=())
    if owner_spec == "demo" and phase in {"prepared", "applied"}:
        with pytest.raises(IdentityStoreError):
            observe(store, tmp_path, **request)
    else:
        assert observe(store, tmp_path, **request).check.diagnostics == ()


def test_stale_lifecycle_remains_candidate_diagnostic(tmp_path):
    store, request = revision_fixture(tmp_path)
    request["operations"] = (op("lifecycle", "stale", ElementRevision("FR-000001", "2", "Movement", "New")),)
    result = observe(store, tmp_path, **request)
    assert tuple(row.code for row in result.check.diagnostics) == ("lifecycle_rejected",)


@pytest.mark.parametrize("other_spec", [False, True])
def test_full_retained_audit_precedes_malformed_candidate(tmp_path, other_spec):
    store, request = revision_fixture(tmp_path)
    if other_spec:
        store.import_identities(spec_id="other", operation_id="other-import", definitions=(("U-001", "Unknown"),))
        from harness.element_identity_lifecycle import ElementAdopt
        store.apply_lifecycle(spec_id="other", operation_id="other-adopt", changes=(ElementAdopt("U-001", "Unknown", "Original"),))
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        if other_spec:
            connection.execute("UPDATE revisions SET content='damaged' WHERE spec_id='other'")
        else:
            connection.execute("UPDATE revisions SET content='damaged'")
        connection.commit()
    request["artifacts"] = (replace(request["artifacts"][0], role="unsupported"),)
    with pytest.raises(IdentityStoreError) as error:
        observe(store, tmp_path, **request)
    assert str(error.value) == "invalid identity candidate preview authority or request"
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_real_writer_cannot_commit_between_candidate_and_overlay(tmp_path, monkeypatch):
    from harness import element_identity_candidate_store as candidate_store
    store, request = revision_fixture(tmp_path)
    expected = observe(store, tmp_path, **request)
    writer = IdentityStore.open(tmp_path)
    start, committing, committed = Event(), Event(), Event()
    failures = []
    original_write_transaction = writer._transaction
    @contextmanager
    def traced_writer(**kwargs):
        with original_write_transaction(**kwargs) as connection:
            connection.set_trace_callback(lambda sql: committing.set() if sql == "COMMIT" else None)
            yield connection
    monkeypatch.setattr(writer, "_transaction", traced_writer)
    def write():
        try:
            assert start.wait(5)
            writer.import_identities(spec_id="demo", operation_id="concurrent", definitions=(("U-001", "Unknown"),))
            committed.set()
        except BaseException as error:
            failures.append(error)
            committing.set()
    original_check = candidate_store.check_identity
    def coordinated_check(*args, **kwargs):
        result = original_check(*args, **kwargs)
        start.set()
        assert committing.wait(5)
        assert not failures
        assert not committed.is_set()
        return result
    original_transaction = store._transaction
    transactions = []
    writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}
    @contextmanager
    def readonly(**kwargs):
        transactions.append(kwargs)
        with original_transaction(**kwargs) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            connection.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK)
            yield connection
    thread = Thread(target=write)
    thread.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(candidate_store, "check_identity", coordinated_check)
            patch.setattr(store, "_transaction", readonly)
            result = store.preview_identity_candidate(**request)
        assert result == expected
        assert transactions == [{}]
    finally:
        start.set()
        thread.join(5)
    assert not thread.is_alive() and not failures and committed.is_set()
    assert store.lookup(spec_id="demo", element_id="U-001")["revision"] is None
    # Lifecycle proposal is still valid; the complete materialized history hash
    # is stale because the second writer introduced an unrelated entity.
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="stale-publication",
            request=PublicationIntentRequest("a" * 64, "opaque test recovery", request["operations"],
                proposed_history_sha256=result.history.sha256))


def test_caller_records_and_sequences_are_owned_before_transaction(tmp_path, monkeypatch):
    from tests.unit.test_issue_identity_candidate import seeded, context
    store, report, entry = seeded(tmp_path)
    after = replace(entry, report_id="review-2")
    ctx = context((entry,), [after], after_id="review-2")
    artifact = CandidateArtifact("issues.md", "issues", report, report)
    artifacts, reports, writable, labels = [artifact], [ctx], ["issues.md"], [entry.issue_id]
    scope = IdentityEditScope(writable, labels)
    operation = op("issue_occurrences", "new", after)
    request = dict(spec_id="demo", artifacts=artifacts, scope=scope, issue_reports=reports, operations=(operation,))
    expected = observe(store, tmp_path, **request)
    original = store._transaction
    @contextmanager
    def mutate(**kwargs):
        object.__setattr__(artifact, "after_text", "corrupted")
        object.__setattr__(after, "body", "corrupted")
        object.__setattr__(entry, "report_sha256", "b" * 64)
        object.__setattr__(ctx, "after_report_id", "corrupted")
        object.__setattr__(scope, "element_ids", ())
        object.__setattr__(operation, "payload", "corrupted")
        artifacts.clear(); reports.clear(); writable.clear(); labels.clear()
        with original(**kwargs) as connection:
            yield connection
    monkeypatch.setattr(store, "_transaction", mutate)
    assert observe(store, tmp_path, **request) == expected


def test_result_owns_fresh_candidate_observation_records(tmp_path, monkeypatch):
    from harness import element_identity_candidate_store as candidate_store
    store, request = revision_fixture(tmp_path)
    request["artifacts"] += (CandidateArtifact("notes.md", "references", "FR-000001", "FR-000001"),)
    request["operations"] = ()
    observations = []
    original = candidate_store.check_identity
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        observations.append(result)
        return result
    monkeypatch.setattr(candidate_store, "check_identity", capture)
    result = observe(store, tmp_path, **request)
    retained = repr(result)
    with pytest.raises(FrozenInstanceError):
        result.history = "invalid"
    with pytest.raises(FrozenInstanceError):
        result.check.references[0].target_id = "FR-other"
    object.__setattr__(observations[0].references[0], "target_id", "FR-other")
    object.__setattr__(observations[0].diagnostics[0], "detail", "corrupted")
    assert repr(result) == retained


class BrokenSequence(Sequence):
    def __len__(self):
        return 1
    def __getitem__(self, index):
        raise RuntimeError("source-bearing sequence failure")


class RecursiveSequence(Sequence):
    def __len__(self):
        return len(self)
    def __getitem__(self, index):
        return self[index]


@pytest.mark.parametrize("case", [
    "artifact-subclass", "artifact-missing", "artifact-text", "artifact-role", "spec-subclass", "spec-bool",
    "scope-subclass", "scope-missing", "scope-recursive", "scope-custom", "artifacts-custom", "artifacts-recursive",
    "operation-missing", "operation-subclass", "operation-list", "operation-unicode", "operation-order",
    "projection-missing", "inventory-custom", "report-missing", "occurrence-missing", "occurrence-subclass",
])
def test_malformed_request_is_bounded_before_authority(tmp_path, monkeypatch, case):
    from harness.element_identity_bundle import LexiconProjectionSource, EvidenceInventoryContext
    from harness.element_identity_issue_candidate import IssueReportContext
    from harness.element_identity_bindings import IssueOccurrence
    store, request = revision_fixture(tmp_path)
    artifact = request["artifacts"][0]
    if case == "artifact-subclass":
        class Artifact(CandidateArtifact): pass
        request["artifacts"] = (Artifact(artifact.path, artifact.role, artifact.before_text, artifact.after_text),)
    elif case == "artifact-missing": object.__delattr__(artifact, "before_text")
    elif case == "artifact-text": object.__setattr__(artifact, "after_text", True)
    elif case == "artifact-role": object.__setattr__(artifact, "role", "\ud800")
    elif case == "spec-subclass": request["spec_id"] = type("Text", (str,), {})("demo")
    elif case == "spec-bool": request["spec_id"] = True
    elif case == "scope-subclass":
        class Scope(IdentityEditScope): pass
        request["scope"] = Scope(("spec.md",), ("FR-000001",))
    elif case == "scope-missing": object.__delattr__(request["scope"], "element_ids")
    elif case.startswith("scope-"):
        object.__setattr__(request["scope"], "element_ids", RecursiveSequence() if case.endswith("recursive") else BrokenSequence())
    elif case.startswith("artifacts-"):
        request["artifacts"] = RecursiveSequence() if case.endswith("recursive") else BrokenSequence()
    elif case == "operation-missing": object.__delattr__(request["operations"][0], "payload")
    elif case == "operation-subclass":
        class Operation(PublicationOperation): pass
        original = request["operations"][0]
        subclass = object.__new__(Operation)
        for field in ("method", "operation_id", "payload"):
            object.__setattr__(subclass, field, getattr(original, field))
        request["operations"] = (subclass,)
    elif case == "operation-list": request["operations"] = list(request["operations"])
    elif case == "operation-unicode": object.__setattr__(request["operations"][0], "operation_id", "\ud800")
    elif case == "operation-order": request["operations"] *= 2
    elif case == "projection-missing":
        descriptor = LexiconProjectionSource("p.lexicon", "spec.md")
        object.__delattr__(descriptor, "glossary_path")
        request["projection_sources"] = (descriptor,)
    elif case == "inventory-custom": request["evidence_inventories"] = (EvidenceInventoryContext("e.json", BrokenSequence()),)
    else:
        entry = IssueOccurrence("ISS-000001", "1", "report", "a" * 64, "ISS-000001", "Issue", "Body")
        context = IssueReportContext("issues.md", None, "report", (), (entry,))
        if case == "report-missing": object.__delattr__(context, "after_report_id")
        elif case == "occurrence-missing": object.__delattr__(entry, "body")
        else:
            class Occurrence(IssueOccurrence): pass
            object.__setattr__(context, "after_occurrences", (Occurrence("ISS-000001", "1", "report", "a" * 64, "ISS-000001", "Issue", "Body"),))
        request["issue_reports"] = (context,)
    monkeypatch.setattr(store, "_transaction", lambda **kw: pytest.fail("malformed input acquired authority"))
    with pytest.raises(IdentityStoreError) as error:
        store.preview_identity_candidate(**request)
    assert str(error.value) == "invalid identity candidate preview authority or request"
    assert error.value.__cause__ is None and error.value.__context__ is None


@pytest.mark.parametrize("failure", [RuntimeError("secret source"), AttributeError("secret source"),
    KeyboardInterrupt("stop"), SystemExit("stop"), GeneratorExit("stop")])
def test_public_exception_boundary_and_process_control(tmp_path, monkeypatch, failure):
    from harness import element_identity_candidate_store as candidate_store
    store, request = revision_fixture(tmp_path)
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(candidate_store, "check_identity", fail)
    with pytest.raises(IdentityStoreError if isinstance(failure, Exception) else type(failure)) as caught:
        observe(store, tmp_path, **request)
    if isinstance(failure, Exception):
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert "secret" not in str(caught.value)
    else:
        assert caught.value is failure


@pytest.mark.parametrize("first", ["element_identity_store", "element_identity_candidate_preview"])
def test_import_orders_keep_native_class_identity(first):
    code = f"""
import importlib
importlib.import_module('harness.{first}')
from harness.element_identity_candidate_preview import IdentityCandidatePreview
from harness.element_identity_candidate import IdentityCandidateCheck
from harness.element_identity_snapshot import IdentityHistorySnapshot
from typing import get_type_hints
assert get_type_hints(IdentityCandidatePreview) == {{'check': IdentityCandidateCheck, 'history': IdentityHistorySnapshot | None}}
"""
    import os
    completed = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == completed.stderr == ""


def test_preview_is_query_only_with_no_source_planner_provider_or_writer_access(tmp_path, monkeypatch):
    import builtins
    from harness import element_identity_snapshot as snapshot
    from harness import element_identity_lifecycle_store as lifecycle_store
    from harness import element_identity_binding_store as binding_store
    from harness import element_identity_publication_store as publication_store
    from harness import element_identity_source_store as source_store
    from harness import element_identity_managed_store as managed_store
    from harness import squad_source_snapshot, squad_source_manifest, squad_source_projection, squad_publication
    from echelon import spec_memory_miner, spec_graph_captured
    store, request = revision_fixture(tmp_path)
    original_transaction, original_capture, original_plan = store._transaction, snapshot.capture, lifecycle_store.plan_changes
    original_import = builtins.__import__
    transactions, captures, statements = [], [], []
    def forbidden(*args, **kwargs):
        pytest.fail("preview acquired a source, provider, graph, memory or write owner")
    def guarded_import(name, *args, **kwargs):
        if name.startswith(("harness.llm_provider", "harness.coordinator", "harness.ralph", "harness.state", "mempalace")):
            forbidden()
        return original_import(name, *args, **kwargs)
    @contextmanager
    def tracked(**kwargs):
        transactions.append(kwargs)
        with original_transaction(**kwargs) as connection:
            connection.set_trace_callback(statements.append)
            yield connection
    def captured(*args, **kwargs):
        captures.append(True)
        return original_capture(*args, **kwargs)
    def plan(connection, *args, **kwargs):
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO operations VALUES ('forbidden','reserve','demo','x')")
        return original_plan(connection, *args, **kwargs)
    with monkeypatch.context() as patch:
        for name in ("reserve", "import_identities", "_operation", "apply_lifecycle", "record_reference_claims", "record_issue_occurrences",
            "prepare_identity_publication", "apply_identity_publication", "release_identity_publication", "backup", "restore",
            "check_identity_candidate", "identity_history", "preview_identity_history", "validate_projected_bindings"):
            patch.setattr(store, name, forbidden)
        for owner, names in (
            (lifecycle_store, ("apply_changes",)), (binding_store, ("record",)),
            (publication_store, ("prepare", "apply", "release")), (source_store, ("prepare",)), (managed_store, ("register",)),
            (squad_source_snapshot, ("_capture_project_tree", "_capture_project_path", "inspect_project_tree")),
            (squad_source_manifest, ("snapshot_source_manifest",)),
            (squad_source_projection, ("project_publication_source_images",)),
            (squad_publication.SquadPublicationTransaction, ("begin", "seal")),
            (spec_graph_captured, ("build_captured_identity_graph",)),
            (spec_memory_miner, ("plan_canonical_requirement_drawers", "SpecMemoryMiner")),
        ):
            for name in names:
                patch.setattr(owner, name, forbidden)
        patch.setattr(builtins, "__import__", guarded_import)
        patch.setattr(store, "_transaction", tracked)
        patch.setattr(snapshot, "capture", captured)
        patch.setattr(lifecycle_store, "plan_changes", plan)
        result = observe(store, tmp_path, **request)
    assert result.check.diagnostics == ()
    assert transactions == [{}] and captures == [True]
    assert statements.count("PRAGMA query_only=ON") == 1
    assert not any(sql.upper().startswith(("SAVEPOINT", "ATTACH", "VACUUM", "BEGIN IMMEDIATE")) for sql in statements)


def test_sealed_capture_candidate_graph_and_v3_history_agree(tmp_path):
    from pathlib import Path
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    from harness.squad_publication import SquadPublicationTransaction, _secure_posix_capabilities_available
    from harness.squad_source_projection import project_publication_source_images
    from echelon.spec_graph import render_spec_graph
    from echelon.spec_graph_captured import CapturedGraphMemory, build_captured_identity_graph
    from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource
    from echelon.spec_memory_miner import plan_canonical_requirement_drawers
    if not _secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX capture unavailable")
    store, request = revision_fixture(tmp_path)
    artifact = request["artifacts"][0]
    store.record_reference_claims(spec_id="demo", operation_id="old-evidence", claims=(
        ReferenceClaim("old-evidence.md", "a" * 64, "span:0:9", "FR-000001", "1", "evidence"),))
    target = Path("specs/demo/spec.md")
    (tmp_path / target).parent.mkdir(parents=True)
    (tmp_path / target).write_bytes(artifact.before_text.encode())
    squad = tmp_path / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(tmp_path, squad, "2" * 32)
    stage = transaction.build_path("after.md")
    content = artifact.after_text.encode()
    stage.write_bytes(content)
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",)) as captured:
        assembled = assemble_candidate_sources(captured,
            (CandidateSourceBinding(target.as_posix(), "spec.md", "requirements"),), writable_paths=(target.as_posix(),))
        assert assembled.diagnostics == ()
        request["artifacts"] = assembled.artifacts
        preview = observe(store, tmp_path, **request)
        assert preview.check.diagnostics == ()
        sources = project_publication_source_images(captured)
    rows = plan_canonical_requirement_drawers(content, source=target.as_posix(), wing="captured-test-wing",
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + hashlib.sha256(content).hexdigest()})
    assert len(rows) == 1
    # An explicit deterministic domain observation is not authenticated semantic review.
    audit = GraphMemoryAudit("returned", 1, "captured-test-wing", "pass", 1, 1, 1, (), (), (), (), (), (), (), ())
    memory = (CapturedGraphMemory("canonical-spec", (GraphMemorySource(target.as_posix(), content, "requirement", ""),), tuple(rows), audit),)
    def graph(history):
        return build_captured_identity_graph(spec_id="demo", lifecycle="phase_a", generator_version="candidate-preview-test",
            sources=sources, policy_paths=(), memory=memory, re_artifacts=(), re_sources=(), history=history)
    projected = graph(preview.history)
    retained_bytes = render_spec_graph(projected)
    requirement = next(node for node in projected.nodes if node.id == "req:demo:FR-000001")
    assert requirement.properties["identity"]["revision"] == "2"
    assert any(node.id == "spec:demo" for node in projected.nodes)
    old = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "1")
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    assert old.properties["content"] == artifact.before_text
    assert any(edge.source == claim.id and edge.type == "ASSESSES_REVISION" and edge.target == old.id for edge in projected.edges)
    assert claim.properties["target_revision_matches_current"] is False
    intent = PublicationIntentRequest(captured.publication.marker.manifest_sha256, "opaque integration recovery", request["operations"],
        proposed_history_sha256=preview.history.sha256)
    store.prepare_identity_publication(spec_id="demo", operation_id="integration", request=intent)
    assert store.apply_identity_publication(spec_id="demo", operation_id="integration")["identity_history_sha256"] == preview.history.sha256
    retained = IdentityStore.open(tmp_path).identity_history(spec_id="demo")
    assert retained == preview.history
    assert render_spec_graph(graph(retained)) == retained_bytes
    # Only the native identity journal was applied: source bytes remain original,
    # and this fixture does not seal or publish a graph or certify review.
    assert (tmp_path / target).read_bytes() == artifact.before_text.encode()
    assert not (tmp_path / "specs/demo/spec-artifact-graph.json").exists()
