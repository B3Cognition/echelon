"""Real-storage contracts for inactive assessed content and lifecycle lineage."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError

pytestmark = pytest.mark.unit


def operations():
    from harness.element_identity_lifecycle import (
        ElementCreate, ElementAdopt, ElementRevision, ElementRetirement, ElementTransition,
    )
    return ElementCreate, ElementAdopt, ElementRevision, ElementRetirement, ElementTransition


def apply(store, *changes, operation_id="change"):
    return store.apply_lifecycle(spec_id="demo", operation_id=operation_id, changes=changes)


def lookup(store, label="AC-000001"):
    return store.lookup(spec_id="demo", element_id=label)


def seeded(tmp_path):
    Create, *_ = operations()
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="AC", operation_id="allocate", count=10)
    apply(store, Create("AC-000001", "Movement", "Original body.", "allocate"), operation_id="create")
    return store


def rows(tmp_path):
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        return tuple(connection.iterdump())


def test_revision_keeps_id_and_prior_content(tmp_path):
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision

    store = IdentityStore.initialize(tmp_path)
    assert store.reserve(spec_id="001-game", kind="AC", operation_id="allocate", count=1) == ("AC-000001",)
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate("AC-000001", "Player movement", "Moves with WASD.", "allocate"),
    ))
    assert store.lookup(spec_id="001-game", element_id="AC-000001")["revision"] == "1"
    store.apply_lifecycle(spec_id="001-game", operation_id="revise", changes=(
        ElementRevision("AC-000001", "1", "Player movement", "Moves with WASD and arrow keys."),
    ))
    assert store.lookup(spec_id="001-game", element_id="AC-000001")["revision"] == "2"
    assert store.read_revision(spec_id="001-game", element_id="AC-000001", revision="1")["content"] == "Moves with WASD."
    assert store.high_water(spec_id="001-game", kind="AC") == "1"


def test_types_reject_malformed_payloads_and_are_frozen():
    Create, Adopt, Revision, Retirement, Transition = operations()
    item = Create("AC-000001", "Subject", "body", "reserve")
    with pytest.raises(FrozenInstanceError):
        item.content = "changed"
    invalid = [
        lambda: Create("AC-0", "s", "body", "r"),
        lambda: Create("AC-1", " ", "body", "r"),
        lambda: Create("AC-1", "s", 3, "r"),
        lambda: Create("AC-1", "s", "body", ""),
        lambda: Adopt("FR-001", "s", "\x00"),
        lambda: Revision("AC-1", "01", "s", "body"),
        lambda: Revision("AC-1", 1, "s", "body"),
        lambda: Retirement("AC-1", "0", "reason"),
        lambda: Transition("rename", (("AC-1", "1"),), (item,), "reason"),
        lambda: Transition("split", (("AC-1", "1"),), (item,), "reason"),
        lambda: Transition("replace", [("AC-1", "1")], (item,), "reason"),
        lambda: Transition("replace", (("AC-1", "1"),), (item,), ""),
        lambda: Transition("replace", (("AC-000001", "1"),), (item,), "overlap"),
        lambda: Transition("merge", (("AC-2", "1"), ("AC-2", "1")), (item,), "duplicate"),
        lambda: Create("AC-1", "s", "body", "r", extra=True),
    ]
    for request in invalid:
        with pytest.raises((ValueError, TypeError)):
            request()


@pytest.mark.parametrize("case", ["subject", "stale", "unreserved", "alias", "operation", "duplicate"])
def test_rejected_batch_preserves_entire_prestate(tmp_path, case):
    Create, _, Revision, _, Transition = operations()
    store = seeded(tmp_path)
    changes = {
        "subject": (Revision("AC-000001", "1", "Different", "body"),),
        "stale": (Revision("AC-000001", "2", "Movement", "body"),),
        "unreserved": (Create("AC-000011", "new", "body", "allocate"),),
        "alias": (Create("AC-02", "new", "body", "allocate"),),
        "operation": (Revision("AC-000001", "1", "Movement", "body"),),
        "duplicate": (Revision("AC-000001", "1", "Movement", "body"),) * 2,
    }
    before = rows(tmp_path)
    with pytest.raises(ValueError):
        apply(store, *changes[case], operation_id="allocate" if case == "operation" else "bad")
    assert rows(tmp_path) == before


def test_import_is_unbound_until_explicit_adoption(tmp_path):
    _, Adopt, *_ = operations()
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-001", "Original subject"),))
    record = lookup(store, "FR-001")
    assert (record["status"], record["revision"], record["content"], record["content_sha256"]) == ("imported", None, None, None)
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        apply(store, Adopt("FR-001", "replacement subject", "body"))
    assert rows(tmp_path) == before
    request = Adopt("FR-001", "Original subject", "Assessed body.")
    receipt = apply(store, request)
    assert apply(store, request) == receipt
    assert lookup(store, "FR-001")["revision"] == "1"
    with pytest.raises(IdentityStoreError):
        apply(store, request, operation_id="second-adoption")


def test_retirement_keeps_content_and_reservation_counter(tmp_path):
    Create, _, Revision, Retirement, _ = operations()
    store = seeded(tmp_path)
    apply(store, Retirement("AC-000001", "1", "No longer required"))
    store = IdentityStore.open(tmp_path)
    record = lookup(store)
    assert (record["status"], record["revision"], record["content"]) == ("retired", "2", "Original body.")
    assert store.read_revision(spec_id="demo", element_id="AC-000001", revision="1")["status"] == "active"
    assert store.read_revision(spec_id="demo", element_id="AC-000001", revision="2")["reason"] == "No longer required"
    for item in (Revision("AC-000001", "2", "Movement", "body"), Create("AC-000001", "Movement", "body", "allocate")):
        before = rows(tmp_path)
        with pytest.raises(IdentityStoreError):
            apply(store, item, operation_id="recreate")
        assert rows(tmp_path) == before
    assert store.reserve(spec_id="demo", kind="AC", operation_id="next", count=1) == ("AC-000011",)


@pytest.mark.parametrize("kind", ["replace", "split", "merge"])
def test_transitions_atomically_bind_predecessor_revisions_and_successors(tmp_path, kind):
    Create, _, _, _, Transition = operations()
    store = seeded(tmp_path)
    predecessors = (("AC-000001", "1"),)
    if kind == "merge":
        apply(store, Create("AC-000002", "second", "Second.", "allocate"), operation_id="second")
        predecessors += (("AC-000002", "1"),)
    labels = ("AC-000003", "AC-000004") if kind == "split" else ("AC-000003",)
    successors = tuple(Create(label, label, "New assessed body.", "allocate") for label in labels)
    receipt = apply(store, Transition(kind, predecessors, successors, "Reviewed change"))
    assert len(receipt) == len(predecessors) + len(successors)
    for label, revision in predecessors:
        assert lookup(store, label)["status"] == "superseded"
        links = store.lineage(spec_id="demo", element_id=label)
        assert {link["successor_id"] for link in links} == set(labels)
        assert all(link["predecessor_revision"] == revision and link["operation_id"] == "change"
                   and link["reason"] == "Reviewed change" and link["kind"] == kind for link in links)
    for label in labels:
        assert lookup(store, label)["revision"] == "1"
        assert {link["predecessor_id"] for link in store.lineage(spec_id="demo", element_id=label)} == {p[0] for p in predecessors}


def test_last_successor_failure_rolls_back_all_changes(tmp_path):
    Create, _, _, _, Transition = operations()
    store = seeded(tmp_path)
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        apply(store, Transition("split", (("AC-000001", "1"),), (
            Create("AC-000002", "a", "A", "allocate"),
            Create("FR-000001", "b", "B", "nonexistent"),
        ), "split"))
    assert rows(tmp_path) == before
    store.reserve(spec_id="demo", kind="FR", operation_id="fr", count=1)
    apply(store, Transition("split", (("AC-000001", "1"),), (
        Create("AC-000002", "a", "A", "allocate"),
        Create("FR-000001", "b", "B", "fr"),
    ), "split"))
    assert lookup(store, "FR-000001")["status"] == "active"


def test_retry_returns_original_receipt_after_later_edit(tmp_path):
    _, _, Revision, *_ = operations()
    store = seeded(tmp_path)
    change = Revision("AC-000001", "1", "Movement", "Second.")
    receipt = apply(store, change)
    receipt[0]["content"] = "caller tampering"
    original = apply(store, change)
    apply(store, Revision("AC-000001", "2", "Movement", "Third."), operation_id="later")
    assert apply(IdentityStore.open(tmp_path), change) == original
    assert lookup(store)["revision"] == "3"
    with pytest.raises(IdentityStoreError):
        store.import_identities(spec_id="demo", operation_id="change", definitions=())


@pytest.mark.parametrize("damage", ["digest", "head", "subject", "missing_head"])
def test_damaged_revision_or_head_fails_closed(tmp_path, damage):
    _, _, Revision, *_ = operations()
    store = seeded(tmp_path)
    apply(store, Revision("AC-000001", "1", "Movement", "Second."))
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        if damage == "digest":
            connection.execute("UPDATE revisions SET content_sha256='wrong' WHERE revision='2'")
        elif damage == "head":
            connection.execute("UPDATE lifecycle_heads SET revision='1'")
        elif damage == "subject":
            connection.execute("UPDATE revisions SET subject='changed' WHERE revision='2'")
        else:
            connection.execute("DELETE FROM lifecycle_heads")
    before = rows(tmp_path)
    for action in (lambda: lookup(store),
                   lambda: store.read_revision(spec_id="demo", element_id="AC-000001", revision="2"),
                   lambda: apply(store, Revision("AC-000001", "2", "Movement", "Third."), operation_id="bad")):
        with pytest.raises(IdentityStoreError):
            action()
    assert rows(tmp_path) == before


def test_revision_arithmetic_beyond_signed_64_bit(tmp_path):
    _, _, Revision, *_ = operations()
    store = seeded(tmp_path)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE revisions SET revision='9223372036854775808'")
        connection.execute("UPDATE lifecycle_heads SET revision='9223372036854775808'")
    apply(store, Revision("AC-000001", "9223372036854775808", "Movement", "Next."))
    assert lookup(store)["revision"] == "9223372036854775809"


def legacy_authority(tmp_path):
    directory = tmp_path / ".echelon/identity"
    directory.mkdir(parents=True)
    marker = {"version": 1, "workspace_uuid": "11111111-1111-4111-8111-111111111111", "epoch_uuid": "22222222-2222-4222-8222-222222222222"}
    (directory / "authority.json").write_text(json.dumps(marker))
    with sqlite3.connect(directory / "registry.sqlite3") as connection:
        connection.executescript((Path(__file__).parents[1] / "fixtures/element_identity/authority-v1.sql").read_text())
        connection.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", [(key, str(value)) for key, value in marker.items()])
        connection.execute("INSERT INTO entities(spec_id,element_id,kind,subject,ordinal) VALUES ('demo','FR-001','FR','Legacy subject','1')")
        connection.execute("INSERT INTO counters(spec_id,kind,high_water) VALUES ('demo','FR','1')")
        connection.execute("INSERT INTO operations(operation_id,method,spec_id,digest) VALUES ('old-reserve','reserve','demo',?)",
                           (hashlib.sha256(b'["reserve","demo","AC","2"]').hexdigest(),))
        connection.execute("INSERT INTO reservations(operation_id,spec_id,kind,first_ordinal,first_length,last_ordinal,count) "
                           "VALUES ('old-reserve','demo','AC','1',1,'2','2')")
        connection.execute("INSERT INTO counters(spec_id,kind,high_water) VALUES ('demo','AC','2')")
    return directory


def test_explicit_upgrade_preserves_marker_and_unbound_imports_and_is_idempotent(tmp_path):
    directory = legacy_authority(tmp_path)
    marker = (directory / "authority.json").read_bytes()
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError, match="upgrade"):
        IdentityStore.open(tmp_path)
    assert rows(tmp_path) == before
    store = IdentityStore.upgrade(tmp_path)
    assert (directory / "authority.json").read_bytes() == marker
    assert lookup(store, "FR-001")["status"] == "imported"
    assert lookup(store, "FR-001")["content"] is None
    assert store.reserve(spec_id="demo", kind="AC", operation_id="old-reserve", count=2) == ("AC-000001", "AC-000002")
    upgraded = rows(tmp_path)
    IdentityStore.upgrade(tmp_path)
    assert rows(tmp_path) == upgraded


def test_interrupted_upgrade_rolls_back_all_schema_and_data(tmp_path, monkeypatch):
    import harness.element_identity_schema as schema
    directory = legacy_authority(tmp_path)
    before = rows(tmp_path)
    original = schema.upgrade
    def interrupted(connection):
        original(connection)
        raise RuntimeError("interrupted")
    monkeypatch.setattr(schema, "upgrade", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        IdentityStore.upgrade(tmp_path)
    assert rows(tmp_path) == before
    assert (directory / "authority.json").exists()


@pytest.mark.parametrize("damage", ["unknown", "counter", "missing"])
def test_upgrade_rejects_unrecognized_or_damaged_authority(tmp_path, damage):
    directory = legacy_authority(tmp_path)
    with sqlite3.connect(directory / "registry.sqlite3") as connection:
        if damage == "unknown":
            connection.execute("CREATE TABLE surprise (value TEXT)")
        elif damage == "counter":
            connection.execute("DELETE FROM counters")
        else:
            connection.execute("DROP TABLE entities")
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert rows(tmp_path) == before


def test_current_backup_restores_history_lineage_and_retry_receipts(tmp_path):
    Create, _, Revision, _, Transition = operations()
    source = tmp_path / "source"
    source.mkdir()
    store = seeded(source)
    change = Transition("replace", (("AC-000001", "1"),), (Create("AC-000002", "new", "New.", "allocate"),), "replacement")
    receipt = apply(store, change)
    apply(store, Revision("AC-000002", "1", "new", "Edited."), operation_id="later")
    store.backup(tmp_path / "backup")
    destination = tmp_path / "destination"
    destination.mkdir()
    restored = IdentityStore.restore(destination, tmp_path / "backup")
    assert apply(restored, change) == receipt
    assert lookup(restored)["status"] == "superseded"
    assert restored.read_revision(spec_id="demo", element_id="AC-000002", revision="1")["content"] == "New."
    assert restored.lineage(spec_id="demo", element_id="AC-000001") == store.lineage(spec_id="demo", element_id="AC-000001")


@pytest.mark.parametrize("unknown", [False, True])
def test_legacy_backup_is_validated_before_destination_creation_and_upgraded_only_there(tmp_path, unknown):
    source = tmp_path / "source"
    backup = legacy_authority(source)
    if unknown:
        with sqlite3.connect(backup / "registry.sqlite3") as connection:
            connection.execute("INSERT INTO metadata VALUES ('schema_version','999')")
    digest = hashlib.sha256((backup / "registry.sqlite3").read_bytes()).hexdigest()
    (backup / "manifest.json").write_text(json.dumps({"version": 1, "completed": True,
        "authority": json.loads((backup / "authority.json").read_text()), "database_sha256": digest}))
    before = rows(source)
    destination = tmp_path / "destination"
    destination.mkdir()
    if unknown:
        with pytest.raises(IdentityStoreError):
            IdentityStore.restore(destination, backup)
        assert not (destination / ".echelon").exists()
    else:
        restored = IdentityStore.restore(destination, backup)
        assert lookup(restored, "FR-001")["status"] == "imported"
        assert lookup(restored, "FR-001")["revision"] is None
    assert rows(source) == before


@pytest.mark.parametrize("damage", ["digest", "head", "missing_head", "missing_revision", "lineage", "receipt", "schema"])
def test_restore_rejects_corrupt_lifecycle_before_claiming_destination(tmp_path, damage):
    Create, _, _, _, Transition = operations()
    store = seeded(tmp_path)
    apply(store, Transition("replace", (("AC-000001", "1"),),
                           (Create("AC-000002", "new", "New.", "allocate"),), "reason"))
    backup = tmp_path / "backup"
    store.backup(backup)
    with sqlite3.connect(backup / "registry.sqlite3") as connection:
        statement = {
            "digest": "UPDATE revisions SET content_sha256='wrong' WHERE revision='1'",
            "head": "UPDATE lifecycle_heads SET revision='1' WHERE element_id='AC-000001'",
            "missing_head": "DELETE FROM lifecycle_heads",
            "missing_revision": "DELETE FROM revisions WHERE element_id='AC-000001' AND revision='1'",
            "lineage": "DELETE FROM lifecycle_lineage",
            "receipt": "DELETE FROM lifecycle_receipts",
            "schema": "DROP INDEX revision_maxima",
        }[damage]
        connection.execute(statement)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["database_sha256"] = hashlib.sha256((backup / "registry.sqlite3").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, backup)
    assert not (destination / ".echelon").exists()


def test_failure_after_writes_rolls_back_materialization_revision_and_receipt(tmp_path, monkeypatch):
    Create, *_ = operations()
    store = seeded(tmp_path)
    before = rows(tmp_path)
    def interrupted(*args):
        raise RuntimeError("interrupted after writes")
    monkeypatch.setattr(store, "_lineage", interrupted)
    with pytest.raises(RuntimeError, match="after writes"):
        apply(store, Create("AC-000002", "new", "body", "allocate"))
    assert rows(tmp_path) == before


def test_terminal_revision_cannot_certify_changed_content(tmp_path):
    _, _, _, Retirement, _ = operations()
    store = seeded(tmp_path)
    apply(store, Retirement("AC-000001", "1", "reason"))
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE revisions SET content='Different',content_sha256=? WHERE revision='2'",
                           (hashlib.sha256(b"Different").hexdigest(),))
    with pytest.raises(IdentityStoreError):
        lookup(store)


def test_upgrade_rejects_legacy_entity_overlapping_retained_reservation(tmp_path):
    directory = legacy_authority(tmp_path)
    with sqlite3.connect(directory / "registry.sqlite3") as connection:
        connection.execute("INSERT INTO entities VALUES ('demo','AC-001','AC','conflict','1')")
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert rows(tmp_path) == before


def test_upgrade_rejects_lost_reservation_history(tmp_path):
    directory = legacy_authority(tmp_path)
    with sqlite3.connect(directory / "registry.sqlite3") as connection:
        connection.execute("DELETE FROM reservations")
    before = rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert rows(tmp_path) == before


@pytest.mark.parametrize("action", ["upgrade", "restore"])
@pytest.mark.parametrize("damage", ["ordinal", "kind", "subject"])
def test_current_audit_rejects_corrupt_import_binding(tmp_path, action, damage):
    store = seeded(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-001", "Legacy subject"),))
    store.reserve(spec_id="demo", kind="NFR", operation_id="nfr", count=1)
    # Current-schema audits must accept legitimate reservation materialization.
    IdentityStore.upgrade(tmp_path)
    if action == "restore":
        database_dir = tmp_path / "backup"
        store.backup(database_dir)
    else:
        database_dir = tmp_path / ".echelon/identity"
    with sqlite3.connect(database_dir / "registry.sqlite3") as connection:
        statement = {
            "ordinal": "UPDATE entities SET ordinal=NULL WHERE element_id='FR-001'",
            "kind": "UPDATE entities SET kind='NFR' WHERE element_id='FR-001'",
            "subject": "UPDATE entities SET subject=' ' WHERE element_id='FR-001'",
        }[damage]
        connection.execute(statement)
    if action == "restore":
        manifest_path = database_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["database_sha256"] = hashlib.sha256((database_dir / "registry.sqlite3").read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        destination = tmp_path / "destination"
        destination.mkdir()
        before = (database_dir / "registry.sqlite3").read_bytes()
        with pytest.raises(IdentityStoreError):
            IdentityStore.restore(destination, database_dir)
        assert not (destination / ".echelon").exists()
        assert (database_dir / "registry.sqlite3").read_bytes() == before
    else:
        before = rows(tmp_path)
        with pytest.raises(IdentityStoreError):
            IdentityStore.upgrade(tmp_path)
        assert rows(tmp_path) == before
