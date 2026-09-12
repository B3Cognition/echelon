"""Immutable provenance and historical occurrence contracts on real SQLite state."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
import sqlite3

import pytest

from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


SPEC = "demo"
HASH = hashlib.sha256(b"report bytes").hexdigest()


def seeded(path):
    store = IdentityStore.initialize(path)
    for kind in ("AC", "ISS"):
        store.reserve(spec_id=SPEC, kind=kind, operation_id="allocate-" + kind, count=2)
        store.apply_lifecycle(spec_id=SPEC, operation_id="create-" + kind, changes=(
            ElementCreate(kind + "-000001", "Movement", "Repair movement.", "allocate-" + kind),
        ))
    return store


def claim(**changes):
    from harness.element_identity_bindings import ReferenceClaim
    return replace(ReferenceClaim("evidence.md", HASH, "E1", "AC-000001", "1", "evidence"), **changes)


def occurrence(**changes):
    from harness.element_identity_bindings import IssueOccurrence
    return replace(IssueOccurrence("ISS-000001", "1", "report-1", HASH, "ISS-legacy", "Movement", "Repair movement."), **changes)


def record(store, *claims, operation_id="assess"):
    return store.record_reference_claims(spec_id=SPEC, operation_id=operation_id, claims=claims)


def observe(store, *occurrences, operation_id="report"):
    return store.record_issue_occurrences(spec_id=SPEC, operation_id=operation_id, occurrences=occurrences)


def read(store):
    return store.reference_claims(spec_id=SPEC, source_path="evidence.md", source_sha256=HASH)


def issues(store):
    return store.issue_occurrences(spec_id=SPEC, issue_id="ISS-000001")


def database(path):
    return path / ".echelon/identity/registry.sqlite3"


def state(path):
    with sqlite3.connect(database(path)) as connection:
        return tuple(connection.iterdump())


def test_old_evidence_is_not_rebound_after_requirement_revision(tmp_path):
    from harness.element_identity_bindings import ReferenceClaim

    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="001-game", kind="AC", operation_id="allocate", count=1)
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate("AC-000001", "Player movement", "Moves with WASD.", "allocate"),
    ))
    source_hash = hashlib.sha256(b"Movement observation E1").hexdigest()
    claim = ReferenceClaim("evidence-grades.md", source_hash, "E1",
                           "AC-000001", "1", "evidence")
    original = store.record_reference_claims(
        spec_id="001-game", operation_id="assess-one", claims=(claim,))
    store.apply_lifecycle(spec_id="001-game", operation_id="revise", changes=(
        ElementRevision("AC-000001", "1", "Player movement", "Moves with arrows."),
    ))
    saved = store.reference_claims(spec_id="001-game", source_path="evidence-grades.md",
                                   source_sha256=source_hash)
    assert saved[0]["target_revision"] == "1"
    assert saved[0]["target_revision_matches_current"] is False
    assert "verified" not in saved[0] and "passed" not in saved[0]
    assert store.record_reference_claims(
        spec_id="001-game", operation_id="assess-one", claims=(claim,)) == original


def test_unassessed_and_reassessed_claims_retain_separate_provenance(tmp_path):
    store = seeded(tmp_path)
    store.import_identities(spec_id=SPEC, operation_id="legacy", definitions=(("FR-old", "Old"),))
    record(store, claim(target_id="FR-old", target_revision=None), operation_id="legacy-claim")
    first = record(store, claim())
    assert read(store)[0]["target_revision_matches_current"] is True
    store.apply_lifecycle(spec_id=SPEC, operation_id="revise", changes=(
        ElementRevision("AC-000001", "1", "Movement", "Repair arrows."),))
    record(store, claim(target_revision="2"), operation_id="reassess")
    saved = read(store)
    assert [(r["operation_id"], r["target_revision"], r["target_revision_matches_current"])
            for r in saved] == [("assess", "1", False), ("legacy-claim", None, False), ("reassess", "2", True)]
    assert saved[1]["target_status"] == "imported"
    saved[0]["source_anchor"] = "mutated"
    first[0]["target_revision"] = "999"
    assert record(IdentityStore.open(tmp_path), claim())[0]["target_revision"] == "1"
    assert read(store)[0]["source_anchor"] == "E1"


@pytest.mark.parametrize("terminal", ["retired", "superseded"])
def test_historical_and_terminal_references_never_certify_terminal_heads(tmp_path, terminal):
    from harness.element_identity_lifecycle import ElementRetirement, ElementTransition
    store = seeded(tmp_path)
    record(store, claim())
    change = ElementRetirement("AC-000001", "1", "Done") if terminal == "retired" else ElementTransition(
        "replace", (("AC-000001", "1"),),
        (ElementCreate("AC-000002", "Arrows", "New.", "allocate-AC"),), "Replace")
    store.apply_lifecycle(spec_id=SPEC, operation_id="terminal", changes=(change,))
    record(store, claim(target_revision="2"), operation_id="terminal-claim")
    assert [(r["target_revision"], r["target_status"], r["target_revision_matches_current"])
            for r in read(store)] == [("1", terminal, False), ("2", terminal, False)]


@pytest.mark.parametrize("changes", [
    {"target_id": "AC-000002"}, {"target_id": "FR-000001"}, {"target_revision": "2"},
    {"target_revision": "9" * 5000},
])
def test_invalid_final_target_rolls_back_complete_operation(tmp_path, changes):
    store = seeded(tmp_path)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        record(store, claim(), claim(source_anchor="E2", **changes))
    assert state(tmp_path) == before
    with pytest.raises(IdentityStoreError):
        store.record_reference_claims(spec_id="other", operation_id="assess", claims=(claim(),))
    assert state(tmp_path) == before


@pytest.mark.parametrize("changes", [
    {"source_path": x} for x in ("/root.md", "../a", "a/../b", "a//b", "./a", "a/", "a\\b", "a\x00b", "")
] + [
    {"source_sha256": "F" * 64}, {"source_sha256": "a" * 63}, {"source_anchor": " "},
    {"target_id": "XX-1"}, {"target_revision": True}, {"target_revision": 1},
    {"target_revision": "01"}, {"target_revision": "0"}, {"relation": "verified"},
    {"source_anchor": []}, {"source_path": {}},
])
def test_claim_rejects_malformed_scalar_fields(changes):
    with pytest.raises((ValueError, TypeError)):
        claim(**changes)


@pytest.mark.parametrize("changes", [
    {"issue_id": "AC-000001"}, {"display_id": "FR-1"}, {"report_id": " "},
    {"report_sha256": "A" * 64}, {"issue_revision": False}, {"title": []}, {"body": {}},
    {"issue_fingerprint": "a" * 64},
])
def test_occurrence_rejects_invalid_types_and_caller_fingerprints(changes):
    with pytest.raises((ValueError, TypeError)):
        occurrence(**changes)


def test_invalid_batches_and_cross_method_operation_reuse_leave_prestate(tmp_path):
    store = seeded(tmp_path)
    record(store, claim())
    observe(store, occurrence())
    before = state(tmp_path)
    for action in (
        lambda: record(store), lambda: observe(store),
        lambda: record(store, claim(), claim()), lambda: observe(store, occurrence(), occurrence()),
        lambda: record(store, asdict(claim())), lambda: observe(store, asdict(occurrence())),
        lambda: record(store, claim(relation="reference")),
        lambda: observe(store, occurrence(), operation_id="assess"),
        lambda: record(store, claim(), operation_id="report"),
        lambda: record(store, claim(), operation_id="allocate-AC"),
        lambda: observe(store, occurrence(), operation_id="create-ISS"),
        lambda: store.reserve(spec_id=SPEC, kind="AC", operation_id="assess", count=1),
        lambda: store.import_identities(spec_id=SPEC, operation_id="report", definitions=()),
        lambda: store.apply_lifecycle(spec_id=SPEC, operation_id="assess", changes=(ElementRevision("AC-000001", "1", "Movement", "Next."),)),
    ):
        with pytest.raises(IdentityStoreError):
            action()
        assert state(tmp_path) == before


def test_occurrences_keep_historical_fingerprints_and_explicit_display_mapping(tmp_path):
    from harness.issue_identity import matching_issue_resolution
    from harness.element_identity_lifecycle import ElementRetirement
    store = seeded(tmp_path)
    original = observe(store, occurrence(), occurrence(display_id="ISS-other"))
    assert original[0]["issue_fingerprint"] == original[1]["issue_fingerprint"]
    assert {r["display_id"] for r in original} == {"ISS-legacy", "ISS-other"}
    assert store.lookup(spec_id=SPEC, element_id="ISS-legacy") is None
    store.apply_lifecycle(spec_id=SPEC, operation_id="issue-revision", changes=(
        ElementRevision("ISS-000001", "1", "Movement", "Repair arrows with evidence."),))
    later = observe(store, occurrence(issue_revision="2", body="Repair arrows with evidence.", report_id="report-2"), operation_id="report-2")
    assert later[0]["issue_fingerprint"] != original[0]["issue_fingerprint"]
    assert matching_issue_resolution({"ISS-legacy": {"status": "validated", "issue_fingerprint": original[0]["issue_fingerprint"]}}, later[0]["issue_fingerprint"]) == {}
    store.apply_lifecycle(spec_id=SPEC, operation_id="retire-issue", changes=(ElementRetirement("ISS-000001", "2", "Done"),))
    saved = issues(store)
    assert [r["issue_revision"] for r in saved] == ["1", "1", "2"]
    assert observe(IdentityStore.open(tmp_path), occurrence(), occurrence(display_id="ISS-other")) == original
    saved[0]["body"] = "mutated"
    assert issues(store)[0]["body"] == "Repair movement."
    assert store.high_water(spec_id=SPEC, kind="ISS") == "2"


@pytest.mark.parametrize("changes", [
    {"issue_id": "ISS-000002"}, {"issue_revision": "2"},
    {"title": "Different"}, {"body": "Changed repair."},
])
def test_occurrence_must_match_exact_assessed_content_atomically(tmp_path, changes):
    store = seeded(tmp_path)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        observe(store, occurrence(), occurrence(report_id="report-2", **changes))
    assert state(tmp_path) == before


def test_occurrence_rejects_imported_or_terminal_revision_but_allows_active_history(tmp_path):
    from harness.element_identity_lifecycle import ElementRetirement
    store = seeded(tmp_path)
    store.import_identities(spec_id=SPEC, operation_id="legacy", definitions=(("ISS-old", "Movement"),))
    store.apply_lifecycle(spec_id=SPEC, operation_id="retire", changes=(ElementRetirement("ISS-000001", "1", "Done"),))
    before = state(tmp_path)
    for item in (occurrence(issue_id="ISS-old"), occurrence(issue_revision="2")):
        with pytest.raises(IdentityStoreError):
            observe(store, item)
        assert state(tmp_path) == before
    assert observe(store, occurrence())[0]["issue_revision"] == "1"


def test_binding_reads_sort_numeric_entries_and_use_indexed_access(tmp_path):
    store = seeded(tmp_path)
    record(store, *(claim(source_anchor=f"E{i}") for i in range(12)), operation_id="z")
    record(store, claim(), operation_id="a")
    observe(store, *(occurrence(report_id=f"report-{i}") for i in range(12)))
    assert [(r["operation_id"], r["entry_index"]) for r in read(store)] == [("a", "1")] + [("z", str(i)) for i in range(1, 13)]
    assert [r["entry_index"] for r in issues(store)] == [str(i) for i in range(1, 13)]
    with sqlite3.connect(database(tmp_path)) as connection:
        queries = (
            ("SELECT * FROM reference_claims WHERE spec_id=? AND source_path=? AND source_sha256=? ORDER BY operation_id,length(entry_index),entry_index", (SPEC, "evidence.md", HASH)),
            ("SELECT * FROM issue_occurrences WHERE spec_id=? AND issue_id=? ORDER BY operation_id,length(entry_index),entry_index", (SPEC, "ISS-000001")),
            ("SELECT * FROM reference_claims WHERE operation_id=? ORDER BY length(entry_index),entry_index", ("z",)),
            ("SELECT * FROM binding_receipts WHERE operation_id=?", ("z",)),
        )
        for query, parameters in queries:
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, parameters))
            assert "SEARCH" in plan and "SCAN" not in plan
            assert "TEMP B-TREE" not in plan


def older_authority(path, version, *, store=None):
    """Freeze real retained data into the reviewed older DDL, never derived DDL."""
    store = store or seeded(path)
    store.import_identities(spec_id=SPEC, operation_id="old-import", definitions=(("FR-001", "Legacy"),))
    db = database(path)
    with sqlite3.connect(db) as source, sqlite3.connect(":memory:") as target:
        target.executescript((Path(__file__).parents[1] / f"fixtures/element_identity/authority-v{version}.sql").read_text())
        for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if table == "metadata":
                rows = [(k, v) for k, v in rows if k != "schema_version"]
                if version in {"2", "3"}:
                    rows.append(("schema_version", version))
            if version == "1" and table in {"operations", "reservations", "entities", "counters"}:
                # Allocation schema did not allow materialized reservation labels.
                rows = {"operations": [r for r in rows if r[1] != "lifecycle"],
                        "entities": [r for r in rows if r[1] == "FR-001"]}.get(table, rows)
            if rows:
                target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
        target.execute("PRAGMA user_version=1")
        target.commit()
        target.backup(source)
    return path / ".echelon/identity"


def manifest(directory):
    (directory / "manifest.json").write_text(json.dumps({"version": 1, "completed": True,
        "authority": json.loads((directory / "authority.json").read_text()),
        "database_sha256": hashlib.sha256((directory / "registry.sqlite3").read_bytes()).hexdigest()}))


@pytest.mark.parametrize("version", ["1", "2", "3"])
def test_exact_older_upgrade_preserves_retries_and_never_fabricates_bindings(tmp_path, version):
    directory = older_authority(tmp_path, version)
    before = state(tmp_path)
    marker = (directory / "authority.json").read_bytes()
    with pytest.raises(IdentityStoreError, match="upgrade"):
        IdentityStore.open(tmp_path)
    assert state(tmp_path) == before
    store = IdentityStore.upgrade(tmp_path)
    assert read(store) == () and issues(store) == ()
    assert store.lookup(spec_id=SPEC, element_id="FR-001")["revision"] is None
    assert store.reserve(spec_id=SPEC, kind="AC", operation_id="allocate-AC", count=2) == ("AC-000001", "AC-000002")
    store.import_identities(spec_id=SPEC, operation_id="old-import", definitions=(("FR-001", "Legacy"),))
    if version in {"2", "3"}:
        assert store.apply_lifecycle(spec_id=SPEC, operation_id="create-AC", changes=(ElementCreate("AC-000001", "Movement", "Repair movement.", "allocate-AC"),))[0]["revision"] == "1"
    assert (directory / "authority.json").read_bytes() == marker
    upgraded = state(tmp_path)
    IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == upgraded


@pytest.mark.parametrize("version", ["1", "2", "3"])
def test_interrupted_binding_upgrade_rolls_back_ddl_data_metadata(tmp_path, version, monkeypatch):
    from harness import element_identity_schema as schema
    older_authority(tmp_path, version)
    before = state(tmp_path)
    original = schema.upgrade
    def interrupted(connection):
        original(connection)
        raise RuntimeError("interrupt after DDL and metadata")
    monkeypatch.setattr(schema, "upgrade", interrupted)
    with pytest.raises(RuntimeError, match="interrupt"):
        IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before


@pytest.mark.parametrize("version", ["1", "2", "3"])
def test_each_frozen_source_history_is_audited_before_upgrade_mutation(tmp_path, version):
    store = seeded(tmp_path)
    if version == "3":
        record(store, claim())
    older_authority(tmp_path, version, store=store)
    with sqlite3.connect(database(tmp_path)) as connection:
        if version == "1":
            connection.execute("DELETE FROM reservations")
        elif version == "2":
            connection.execute("UPDATE lifecycle_receipts SET receipt_sha256='bad'")
        else:
            connection.execute("UPDATE binding_receipts SET receipt_sha256='bad'")
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before


@pytest.mark.parametrize("version", ["1", "2", "3", "5"])
@pytest.mark.parametrize("damage", [None, "unknown", "ordinal", "receipt"])
def test_restore_audits_each_schema_before_destination_claim(tmp_path, version, damage):
    source = tmp_path / "source"
    source.mkdir()
    if version in {"3", "5"}:
        store = seeded(source)
        original_reference = record(store, claim())
        original_occurrence = observe(store, occurrence())
        directory = source / ".echelon/identity"
        if version == "3":
            older_authority(source, version, store=store)
    else:
        directory = older_authority(source, version)
    with sqlite3.connect(database(source)) as connection:
        if damage == "unknown":
            connection.execute("CREATE TABLE surprise (value TEXT)")
        elif damage == "ordinal":
            connection.execute("UPDATE entities SET kind='NFR' WHERE element_id=(SELECT element_id FROM entities LIMIT 1)")
        elif damage == "receipt":
            connection.execute("DELETE FROM reservations")
    manifest(directory)
    before = state(source)
    source_bytes = database(source).read_bytes()
    destination = tmp_path / "destination"
    destination.mkdir()
    if damage:
        with pytest.raises(IdentityStoreError):
            IdentityStore.restore(destination, directory)
        assert not (destination / ".echelon").exists()
    else:
        restored = IdentityStore.restore(destination, directory)
        if version in {"3", "5"}:
            assert record(restored, claim()) == original_reference
            assert observe(restored, occurrence()) == original_occurrence
        else:
            assert read(restored) == () and issues(restored) == ()
    assert state(source) == before
    assert database(source).read_bytes() == source_bytes


@pytest.mark.parametrize("damage", [
    "UPDATE reference_claims SET source_sha256='" + "b" * 64 + "'",
    "UPDATE reference_claims SET target_revision=NULL",
    "UPDATE issue_occurrences SET issue_fingerprint='" + "b" * 64 + "'",
    "UPDATE issue_occurrences SET body='Damaged'",
    "UPDATE binding_receipts SET receipt='[]'",
    "UPDATE operations SET method='import' WHERE operation_id='assess'",
    "UPDATE operations SET spec_id='wrong' WHERE operation_id='report'",
    "UPDATE operations SET digest='damaged' WHERE operation_id='assess'",
    "DELETE FROM reference_claims",
    "DELETE FROM issue_occurrences",
    "DELETE FROM binding_receipts",
    "DELETE FROM operations WHERE operation_id='report'",
    "UPDATE lifecycle_heads SET revision='9' WHERE element_id='AC-000001'",
    "UPDATE revisions SET content='Damaged' WHERE element_id='ISS-000001'",
    "DELETE FROM counters WHERE kind='AC'",
])
def test_corrupt_binding_audit_and_restore_reject_without_repair(tmp_path, damage):
    store = seeded(tmp_path)
    record(store, claim())
    observe(store, occurrence())
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute(damage)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before
    directory = tmp_path / ".echelon/identity"
    manifest(directory)
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, directory)
    assert not (destination / ".echelon").exists()
    assert state(tmp_path) == before


@pytest.mark.parametrize("method,damage", [
    ("reference", "UPDATE reference_claims SET source_anchor='different'"),
    ("reference", "UPDATE reference_claims SET target_revision=NULL"),
    ("reference", "UPDATE operations SET digest='broken' WHERE operation_id='assess'"),
    ("reference", "UPDATE operations SET spec_id='other' WHERE operation_id='assess'"),
    ("reference", "DELETE FROM binding_receipts WHERE operation_id='assess'"),
    ("reference", "DELETE FROM counters WHERE kind='AC'"),
    ("reference", "UPDATE entities SET ordinal='2' WHERE element_id='AC-000001'"),
    ("issue", "UPDATE issue_occurrences SET issue_fingerprint='broken'"),
    ("issue", "UPDATE issue_occurrences SET report_id='other'"),
    ("issue", "UPDATE revisions SET content_sha256='broken' WHERE element_id='ISS-000001'"),
    ("issue", "DELETE FROM binding_receipts WHERE operation_id='report'"),
])
def test_routine_reads_and_retries_authenticate_retained_payloads(tmp_path, method, damage):
    store = seeded(tmp_path)
    record(store, claim())
    observe(store, occurrence())
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute(damage)
    before = state(tmp_path)
    actions = (lambda: read(store), lambda: record(store, claim())) if method == "reference" else (
        lambda: issues(store), lambda: observe(store, occurrence()))
    for action in actions:
        with pytest.raises(IdentityStoreError):
            action()
        assert state(tmp_path) == before


def test_backup_restores_original_receipts_after_both_entities_change(tmp_path):
    from harness.element_identity_lifecycle import ElementRetirement
    store = seeded(tmp_path)
    reference = record(store, claim())
    issue = observe(store, occurrence())
    store.apply_lifecycle(spec_id=SPEC, operation_id="later", changes=(
        ElementRevision("AC-000001", "1", "Movement", "Arrows."),
        ElementRetirement("ISS-000001", "1", "Fixed"),))
    store.backup(tmp_path / "backup")
    destination = tmp_path / "destination"
    destination.mkdir()
    restored = IdentityStore.restore(destination, tmp_path / "backup")
    assert record(restored, claim()) == reference
    assert observe(restored, occurrence()) == issue
    assert read(restored)[0]["target_revision_matches_current"] is False
    assert issues(restored)[0]["body"] == "Repair movement."
    assert issues(restored)[0]["report_sha256"] == HASH


def test_invalid_frozen_request_bypass_is_revalidated_before_transaction(tmp_path, monkeypatch):
    store = seeded(tmp_path)
    reference = claim()
    issue = occurrence()
    object.__setattr__(reference, "source_anchor", [])
    object.__setattr__(issue, "body", {})
    def forbidden_transaction(**kwargs):
        raise AssertionError("invalid request reached transaction boundary")
    monkeypatch.setattr(store, "_transaction", forbidden_transaction)
    for action in (lambda: record(store, reference), lambda: observe(store, issue)):
        with pytest.raises(IdentityStoreError):
            action()


def test_large_assessed_revision_is_bound_without_machine_integer_casts(tmp_path):
    store = seeded(tmp_path)
    huge = "9" * 5000
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute("UPDATE revisions SET revision=? WHERE element_id='AC-000001'", (huge,))
        connection.execute("UPDATE lifecycle_heads SET revision=? WHERE element_id='AC-000001'", (huge,))
    assert record(store, claim(target_revision=huge))[0]["target_revision"] == huge
    assert read(store)[0]["target_revision_matches_current"] is True


@pytest.mark.parametrize("version,method", [("1", "reference_claims"), ("2", "issue_occurrences"),
                                           ("3", "identity_publication"), ("5", "unknown")])
def test_audit_rejects_operation_methods_that_cannot_belong_to_schema(tmp_path, version, method):
    if version == "5":
        seeded(tmp_path)
    else:
        older_authority(tmp_path, version)
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute("INSERT INTO operations VALUES ('impossible',?,'demo','digest')", (method,))
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before
    directory = tmp_path / ".echelon/identity"
    manifest(directory)
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, directory)
    assert not (destination / ".echelon").exists()
