"""Discovery candidates exercise real identity authority without publication."""

import sqlite3
from pathlib import Path

import pytest

from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_lifecycle import (
    ElementAdopt, ElementCreate, ElementRetirement, ElementRevision, ElementTransition,
)
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


def logical_state(workspace):
    with sqlite3.connect(workspace / ".echelon/identity/registry.sqlite3") as connection:
        return tuple(connection.iterdump())


def test_smoke_question_reassignment_rejects_without_registry_effect(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope

    fixture = Path(__file__).parents[1] / "fixtures/element_identity/discovery"
    before = (fixture / "before/unknowns.md").read_text()
    after = (fixture / "after/unknowns.md").read_text()
    declarations = parse_identity_artifact(
        path="unknowns.md", role="unknowns", text=before).declarations
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="001-game", operation_id="import", definitions=tuple(
        (entry.element_id, entry.caption) for entry in declarations))
    store.apply_lifecycle(spec_id="001-game", operation_id="adopt", changes=tuple(
        ElementAdopt(entry.element_id, entry.caption, entry.content) for entry in declarations))
    original = logical_state(tmp_path)
    result = store.check_discovery_candidate(
        spec_id="001-game",
        artifacts=(CandidateArtifact("unknowns.md", "unknowns", before, after),),
        scope=DiscoveryEditScope(("unknowns.md",), tuple(
            entry.element_id for entry in declarations)))
    codes = {(entry.code, entry.element_id) for entry in result.diagnostics}
    assert ("subject_changed", "U-002") in codes
    assert ("definition_removed", "U-005") in codes
    assert logical_state(tmp_path) == original


FIRST = "### U-001: Café question\r\nOriginal body.\r\n"
SECOND = "### U-002: Second question\r\nOther body.\r\n"


def seeded(workspace, text=FIRST, role="unknowns"):
    store = IdentityStore.initialize(workspace)
    declarations = parse_identity_artifact(path="questions.md", role=role, text=text).declarations
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple(
        (entry.element_id, entry.caption) for entry in declarations))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(
        ElementAdopt(entry.element_id, entry.caption, entry.content) for entry in declarations))
    return store


def check(store, workspace, before=FIRST, after=FIRST, *, changes=(), ids=("U-001",),
          writable=("questions.md",), unowned=(), extras=(), role="unknowns"):
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope

    original = logical_state(workspace)
    result = store.check_discovery_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("questions.md", role, before, after), *extras),
        scope=DiscoveryEditScope(writable, ids, unowned), changes=changes)
    assert logical_state(workspace) == original
    keys = [(d.path or "", d.element_id or "", d.code, d.detail) for d in result.diagnostics]
    assert keys == sorted(set(keys))
    return result


def codes(result):
    return {entry.code for entry in result.diagnostics}


@pytest.mark.parametrize("role,text,label", [
    ("unknowns", FIRST, "U-001"),
    ("assumptions", "### A-001: Browser support\nChrome.\n", "A-001"),
])
def test_unchanged_and_authorized_same_caption_revision(tmp_path, role, text, label):
    store = seeded(tmp_path, text, role)
    assert not check(store, tmp_path, text, text, role=role, ids=()).diagnostics
    revised = text.replace("Original", "Updated").replace("Chrome.", "Firefox.")
    caption = "Café question" if role == "unknowns" else "Browser support"
    result = check(store, tmp_path, text, revised, role=role, ids=(label,), changes=(
        ElementRevision(label, "1", caption, revised),))
    assert not result.diagnostics


@pytest.mark.parametrize("case,expected", [
    ("unallocated", "unallocated_definition"), ("wrong_reservation", "lifecycle_rejected"),
    ("padding_alias", "lifecycle_rejected"), ("stale_revision", "lifecycle_rejected"),
    ("revision_content", "definition_content_mismatch"),
    ("missing_after", "definition_removed"), ("missing_bundle", "lifecycle_without_artifact"),
    ("scope", "element_out_of_scope"),
])
def test_lifecycle_requires_exact_materialization_and_artifact_mapping(tmp_path, case, expected):
    store = seeded(tmp_path)
    label, = store.reserve(spec_id="demo", kind="U", operation_id="reserve", count=1)
    new = f"### {label}: New question\nNew body.\n"
    after, changes, ids = FIRST + new, (), ("U-001", label)
    if case in {"wrong_reservation", "padding_alias"}:
        if case == "padding_alias":
            label = "U-02"
            new = "### U-02: New question\nNew body.\n"
            after, ids = FIRST + new, ("U-001", label)
        changes = (ElementCreate(label, "New question", new,
                                 "wrong" if case == "wrong_reservation" else "reserve"),)
    elif case == "stale_revision":
        after = FIRST.replace("Original", "Updated")
        changes = (ElementRevision("U-001", "2", "Café question", after),)
    elif case == "revision_content":
        after = FIRST.replace("Original", "Updated")
        changes = (ElementRevision("U-001", "1", "Café question", FIRST + "different"),)
    elif case == "missing_after":
        after = ""
        changes = (ElementRevision("U-001", "1", "Café question", FIRST),)
    elif case == "missing_bundle":
        after = FIRST
        changes = (ElementCreate(label, "New question", new, "reserve"),)
    elif case == "scope":
        changes = (ElementCreate(label, "New question", new, "reserve"),)
        ids = ("U-001",)
    assert expected in codes(check(store, tmp_path, after=after, changes=changes, ids=ids))


def test_reserved_create_is_read_only_and_legacy_adoption_cannot_import_baseline(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="U", operation_id="reserve", count=1)
    after = f"### {label}: New question\nNew body.\n"
    assert not check(store, tmp_path, None, after, ids=(label,), changes=(
        ElementCreate(label, "New question", after, "reserve"),)).diagnostics
    store.import_identities(spec_id="demo", operation_id="legacy", definitions=(("U-010", "Legacy"),))
    text = "### U-010: Legacy\nBody.\n"
    assert "baseline_identity_mismatch" in codes(check(
        store, tmp_path, text, text, ids=("U-010",), changes=(ElementAdopt("U-010", "Legacy", text),)))
    result = check(store, tmp_path, None, text, ids=("U-010",), changes=(
        ElementAdopt("U-010", "Legacy", text),))
    assert "unallocated_definition" in codes(result)


@pytest.mark.parametrize("kind", ["replace", "split", "merge"])
def test_explicit_transitions_use_reserved_successors_and_preserve_history(tmp_path, kind):
    before = FIRST + SECOND if kind == "merge" else FIRST
    store = seeded(tmp_path, before)
    labels = store.reserve(spec_id="demo", kind="U", operation_id="reserve", count=2)
    labels = labels if kind == "split" else labels[:1]
    successors = tuple(ElementCreate(label, "Successor", f"### {label}: Successor\nBody.\n", "reserve")
                       for label in labels)
    predecessors = (("U-001", "1"), ("U-002", "1")) if kind == "merge" else (("U-001", "1"),)
    transition = ElementTransition(kind, predecessors, successors, "Reviewed")
    ids = tuple(label for label, _ in predecessors) + labels
    for retain in (False, True):
        after = (before if retain else "") + "".join(row.content for row in successors)
        assert not check(store, tmp_path, before, after, ids=ids, changes=(transition,)).diagnostics


def test_retirement_and_subsequent_terminal_candidates(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    evidence = CandidateArtifact("evidence.md", "evidence", "U-001\n", "U-001\n")
    retirement = ElementRetirement("U-001", "1", "Resolved")
    for after in (FIRST, ""):
        result = check(store, tmp_path, after=after, changes=(retirement,), extras=(evidence,))
        assert not result.diagnostics
        assert result.references[0].assessment_state == "unassessed"
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(retirement,))
    assert not check(store, tmp_path, ids=()).diagnostics
    assert not check(store, tmp_path, after=None).diagnostics
    assert "subject_changed" in codes(check(store, tmp_path, after=FIRST.replace("Café", "New")))
    assert "terminal_content_changed" in codes(check(store, tmp_path, after=FIRST.replace("Original", "Updated")))
    assert "terminal_content_changed" in codes(check(store, tmp_path, None, FIRST.replace("Original", "Updated")))
    assert store.lookup(spec_id="demo", element_id="U-001")["status"] == "retired"


@pytest.mark.parametrize("case,expected", [
    ("missing", "baseline_identity_mismatch"), ("drift", "baseline_identity_mismatch"),
    ("unbound", "baseline_identity_mismatch"),
])
def test_baseline_must_have_exact_validated_assessed_head(tmp_path, case, expected):
    store = seeded(tmp_path)
    text = FIRST
    if case == "missing":
        text = FIRST.replace("U-001", "U-009")
    elif case == "drift":
        text = FIRST.replace("Original", "Drifted")
    else:
        with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
            connection.execute("DELETE FROM revisions")
            connection.execute("UPDATE lifecycle_heads SET status='imported',revision=NULL")
    assert expected in codes(check(store, tmp_path, text, text))


@pytest.mark.parametrize("case,expected", [
    ("path", "artifact_out_of_scope"), ("element", "element_out_of_scope"),
    ("comment", "unowned_text_changed"), ("order", "unowned_text_changed"),
    ("newline", "unowned_text_changed"), ("unscoped_with_unowned", "element_out_of_scope"),
])
def test_exact_span_scope_preserves_unicode_crlf_comments_and_order(tmp_path, case, expected):
    before = "<!-- outside café -->\r\n" + FIRST + SECOND
    store = seeded(tmp_path, before)
    after, ids, writable, unowned = before, ("U-001", "U-002"), ("questions.md",), ()
    changes = ()
    if case in {"path", "element", "unscoped_with_unowned"}:
        after = before.replace("Original", "Updated")
        changes = (ElementRevision("U-001", "1", "Café question", FIRST.replace("Original", "Updated")),)
        if case == "path":
            writable = ()
        else:
            ids = ("U-002",)
        if case == "unscoped_with_unowned":
            unowned = ("questions.md",)
    elif case == "comment":
        after = before.replace("outside", "changed")
    elif case == "newline":
        after = before.replace("-->\r\n", "-->\n")
    else:
        after = "<!-- outside café -->\r\n" + SECOND + FIRST
    assert expected in codes(check(store, tmp_path, before, after, ids=ids,
                                  writable=writable, unowned=unowned, changes=changes))


def test_unowned_permission_and_reference_only_dependencies(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact

    before = "<!-- outside -->\r\n" + FIRST
    store = seeded(tmp_path, before)
    assert not check(store, tmp_path, before, before.replace("outside", "changed"),
                     unowned=("questions.md",)).diagnostics
    dependency = CandidateArtifact("notes.md", "references", "U-001", "U-001\n")
    assert "artifact_out_of_scope" in codes(check(store, tmp_path, before, before, extras=(dependency,)))
    assert "unowned_text_changed" in codes(check(store, tmp_path, before, before, extras=(dependency,),
                                                writable=("questions.md", "notes.md")))
    assert not check(store, tmp_path, before, before, extras=(dependency,),
                     writable=("questions.md", "notes.md"), unowned=("notes.md",)).diagnostics


@pytest.mark.parametrize("text,role,expected", [
    ("### U-001 No colon\n", "unknowns", "unsupported_declaration"),
    ("### FR-001: Other family\n", "requirements", "unsupported_role"),
    ("U-001\n", "invented", "unsupported_role"),
    ("U-001..U-009\n", "references", "unsupported_reference_range"),
    ("other::U-001\n", "references", "unsupported_qualified_reference"),
    ("U-01\n", "references", "reference_identity_mismatch"),
    ("U-009\n", "references", "reference_identity_mismatch"),
    ("### U-001: Cannot define\n", "evidence", "unexpected_definition"),
])
def test_parser_diagnostics_and_unsupported_coverage_block(tmp_path, text, role, expected):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    result = check(store, tmp_path, extras=(CandidateArtifact("notes.md", role, text, text),))
    assert expected in codes(result)
    if expected in {"unsupported_declaration", "unsupported_qualified_reference", "unexpected_definition"}:
        assert any("before" in d.detail for d in result.diagnostics if d.code == expected)
        assert any("after" in d.detail for d in result.diagnostics if d.code == expected)
    if expected == "unsupported_reference_range":
        assert not result.references


@pytest.mark.parametrize("alias", ["U-001", "U-01", "U-" + "0" * 5000 + "1"], ids=["duplicate", "alias", "unbounded-alias"])
def test_cross_file_duplicates_and_unbounded_padding_aliases_are_rejected(tmp_path, alias):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    duplicate = FIRST.replace("U-001", alias)
    result = check(store, tmp_path, extras=(CandidateArtifact("duplicate.md", "unknowns", duplicate, duplicate),))
    assert ("duplicate_definition" if alias == "U-001" else "numeric_padding_alias") in codes(result)


def test_unexpected_overlapping_declaration_spans_are_blocked():
    from dataclasses import replace
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope, scope_diagnostics

    parsed = parse_identity_artifact(path="questions.md", role="unknowns", text=FIRST + SECOND)
    overlapping = replace(parsed, declarations=(parsed.declarations[0], replace(
        parsed.declarations[1], span=replace(parsed.declarations[1].span, start=1))))
    result = scope_diagnostics(CandidateArtifact("questions.md", "unknowns", FIRST + SECOND, FIRST + SECOND),
                               overlapping, overlapping, DiscoveryEditScope(("questions.md",), ("U-001", "U-002")))
    assert "overlapping_definition_spans" in {entry.code for entry in result}


@pytest.mark.parametrize("anchor,revision,state", [
    ("span", "1", "current"), ("span", None, "unassessed"), ("other", "1", "unassessed"),
])
def test_reference_assessment_requires_exact_span_and_nonnull_revision(tmp_path, anchor, revision, state):
    from dataclasses import fields
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    source = "Café proof: U-001\r\n"
    parsed = parse_identity_artifact(path="evidence.md", role="evidence", text=source)
    ref, = parsed.references
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(ReferenceClaim(
        "evidence.md", parsed.content_sha256,
        f"span:{ref.span.start}:{ref.span.end}" if anchor == "span" else "section:proof", "U-001", revision, "evidence"),))
    result = check(store, tmp_path, extras=(CandidateArtifact("evidence.md", "evidence", source, source),))
    assert not result.diagnostics
    reference, = result.references
    assert (reference.start, reference.end) == (12, 17)
    assert reference.source_sha256 == parsed.content_sha256
    assert reference.assessed_revisions == ((revision,) if anchor == "span" else ())
    assert reference.assessment_state == state
    assert {field.name for field in fields(result)} == {"diagnostics", "references"}


def test_unchanged_evidence_becomes_historical_but_changed_source_is_unassessed(tmp_path):
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    source = "U-001\n"
    parsed = parse_identity_artifact(path="evidence.md", role="evidence", text=source)
    for operation_id, revision in (("z-claim", None), ("a-claim", "1")):
        store.record_reference_claims(spec_id="demo", operation_id=operation_id, claims=(ReferenceClaim(
            "evidence.md", parsed.content_sha256, "span:0:5", "U-001", revision, "evidence"),))
    revised = FIRST.replace("Original", "Updated")
    proposal = ElementRevision("U-001", "1", "Café question", revised)
    for changed in (False, True):
        result = check(store, tmp_path, after=revised, changes=(proposal,),
                       extras=(CandidateArtifact("evidence.md", "evidence", source, source + "\n" if changed else source),),
                       writable=("questions.md", "evidence.md"), unowned=("evidence.md",))
        assert not result.diagnostics
        reference, = result.references
        assert reference.assessed_revisions == (() if changed else ("1", None))
        assert reference.assessment_state == ("unassessed" if changed else "historical")


def test_existing_other_family_reference_is_readable_but_changes_are_blocked(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve-fr", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create-fr", changes=(
        ElementCreate("FR-000001", "Requirement", "Body", "reserve-fr"),))
    extra = CandidateArtifact("notes.md", "references", "FR-000001", "FR-000001")
    assert not check(store, tmp_path, extras=(extra,)).diagnostics
    result = check(store, tmp_path, extras=(extra,), changes=(
        ElementRevision("FR-000001", "1", "Requirement", "Updated"),))
    assert "unsupported_lifecycle_kind" in codes(result)


@pytest.mark.parametrize("case", [
    "empty", "artifact_class", "scope_class", "path", "duplicate_path", "null_images", "text_type",
    "nul", "utf8", "role_type", "spec_type", "duplicate_scope", "scope_path", "unowned_subset",
    "writable_bundle", "scope_family", "changes_type", "duplicate_changes", "artifact_sequence",
])
def test_invalid_request_shape_is_rejected_before_transaction(tmp_path, case):
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope

    store = seeded(tmp_path)
    artifacts = (CandidateArtifact("questions.md", "unknowns", FIRST, FIRST),)
    scope, changes, spec = DiscoveryEditScope(("questions.md",), ("U-001",)), (), "demo"
    if case == "empty":
        artifacts = ()
    elif case == "artifact_class":
        artifacts = ({"path": "questions.md"},)
    elif case == "artifact_sequence":
        artifacts = iter(artifacts)
    elif case == "scope_class":
        scope = {}
    elif case == "duplicate_path":
        artifacts *= 2
    elif case == "duplicate_scope":
        scope = DiscoveryEditScope(("questions.md",), ("U-001", "U-001"))
    elif case == "scope_path":
        scope = DiscoveryEditScope(("./questions.md",), ())
    elif case == "writable_bundle":
        scope = DiscoveryEditScope(("other.md",), ())
    elif case == "unowned_subset":
        scope = DiscoveryEditScope((), (), ("questions.md",))
    elif case == "scope_family":
        scope = DiscoveryEditScope((), ("FR-001",))
    elif case == "spec_type":
        spec = 1
    elif case == "changes_type":
        changes = None
    elif case == "duplicate_changes":
        changes = (ElementRetirement("U-001", "1", "Done"),) * 2
    else:
        path, role, before, after = "questions.md", "unknowns", FIRST, FIRST
        if case == "path":
            path = "../questions.md"
        elif case == "null_images":
            before = after = None
        elif case == "text_type":
            after = 5
        elif case == "nul":
            after = "\x00"
        elif case == "utf8":
            after = "\ud800"
        elif case == "role_type":
            role = 1
        artifacts = (CandidateArtifact(path, role, before, after),)
    # Removing the database makes any premature transaction observably fail for
    # authority availability instead of the invalid request.
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    database.rename(database.with_suffix(".saved"))
    with pytest.raises(IdentityStoreError) as exc:
        store.check_discovery_candidate(spec_id=spec, artifacts=artifacts, scope=scope, changes=changes)
    assert "registry" not in str(exc.value) and "missing" not in str(exc.value)


def test_malformed_numeric_definition_is_a_candidate_diagnostic(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    result = check(store, tmp_path, extras=(CandidateArtifact(
        "zero.md", "unknowns", "### U-000: Invalid ordinal\n", "### U-000: Invalid ordinal\n"),))
    assert "invalid_definition_identity" in codes(result)


def test_rejected_subject_change_still_identifies_reused_caption(tmp_path):
    store = seeded(tmp_path)
    after = FIRST.replace("Café question", "Unrelated subject")
    result = check(store, tmp_path, after=after, changes=(
        ElementRevision("U-001", "1", "Unrelated subject", after),))
    assert {"subject_changed", "lifecycle_rejected"} <= codes(result)


def test_public_candidate_type_annotations_resolve():
    from typing import get_type_hints

    assert get_type_hints(IdentityStore.check_discovery_candidate)["return"].__name__ == "DiscoveryCandidateCheck"


def test_one_read_transaction_snapshots_all_caller_sequences(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope

    store = seeded(tmp_path)
    revised = FIRST.replace("Original", "Updated")
    artifacts = [CandidateArtifact("questions.md", "unknowns", FIRST, revised)]
    writable, labels, unowned = ["questions.md"], ["U-001"], []
    changes = [ElementRevision("U-001", "1", "Café question", revised)]
    original = logical_state(tmp_path)
    transaction = store._transaction
    entered = 0

    @contextmanager
    def read_transaction():
        nonlocal entered
        entered += 1
        if entered != 1:
            raise AssertionError("candidate opened more than one authority transaction")
        for caller_sequence in (artifacts, writable, labels, unowned, changes):
            caller_sequence.clear()
        with transaction() as connection:
            connection.execute("PRAGMA query_only=ON")
            yield connection

    monkeypatch.setattr(store, "_transaction", read_transaction)
    result = store.check_discovery_candidate(spec_id="demo", artifacts=artifacts,
        scope=DiscoveryEditScope(writable, labels, unowned), changes=changes)
    assert not result.diagnostics
    assert entered == 1
    assert logical_state(tmp_path) == original


def test_binding_reader_rejects_damaged_receipt_as_authority_error_without_reassessing(tmp_path):
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    source = "U-001\n"
    parsed = parse_identity_artifact(path="evidence.md", role="evidence", text=source)
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(ReferenceClaim(
        "evidence.md", parsed.content_sha256, "span:0:5", "U-001", "1", "evidence"),))
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE binding_receipts SET receipt='[]'")
    original = logical_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="receipt"):
        check(store, tmp_path, extras=(CandidateArtifact("evidence.md", "evidence", source, source),))
    assert logical_state(tmp_path) == original


def test_reference_relation_and_exact_occurrence_are_not_interchangeable(tmp_path):
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded(tmp_path)
    source = "U-001 and U-001\n"
    parsed = parse_identity_artifact(path="evidence.md", role="evidence", text=source)
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(
        ReferenceClaim("evidence.md", parsed.content_sha256, "span:0:5", "U-001", "1", "reference"),
        ReferenceClaim("evidence.md", parsed.content_sha256, "span:10:15", "U-001", "1", "evidence"),
    ))
    result = check(store, tmp_path, extras=(CandidateArtifact("evidence.md", "evidence", source, source),))
    assert not result.diagnostics
    assert [(row.start, row.assessed_revisions, row.assessment_state) for row in result.references] == [
        (0, (), "unassessed"), (10, ("1",), "current"),
    ]


@pytest.mark.parametrize("damage", ["counter", "head", "binding", "reservation", "revision_digest"])
def test_damaged_authority_fails_closed_without_candidate_diagnostics_or_writes(tmp_path, damage):
    store = seeded(tmp_path)
    label, = store.reserve(spec_id="demo", kind="U", operation_id="reserve", count=1)
    new = f"### {label}: New question\nBody.\n"
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        if damage == "counter":
            connection.execute("UPDATE counters SET high_water='0'")
        elif damage == "head":
            connection.execute("UPDATE lifecycle_heads SET revision='2'")
        elif damage == "binding":
            connection.execute("UPDATE entities SET ordinal='2'")
        elif damage == "reservation":
            connection.execute("UPDATE reservations SET first_length=99")
        else:
            connection.execute("UPDATE revisions SET content='corrupt'")
    original = logical_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        check(store, tmp_path, after=FIRST + new, ids=("U-001", label), changes=(
            ElementCreate(label, "New question", new, "reserve"),))
    assert logical_state(tmp_path) == original
