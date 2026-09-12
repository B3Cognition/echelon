"""Fail-closed allocation authority contracts, exercised against real files."""

from __future__ import annotations

import json
import sqlite3
import stat

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


def reserve(store, **overrides):
    arguments = dict(spec_id="001-demo", kind="AC", operation_id="dispatch-1", count=2)
    return store.reserve(**(arguments | overrides))


def import_one(store, label="FR-001", subject="original", **overrides):
    arguments = dict(spec_id="001-demo", operation_id="import-1", definitions=[(label, subject)])
    return store.import_identities(**(arguments | overrides))


def test_reservation_retry_survives_reopen_and_never_materializes_entities(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    assert store.high_water(spec_id="001-demo", kind="AC") == "0"
    assert reserve(store) == ("AC-000001", "AC-000002")
    reopened = IdentityStore.open(tmp_path)
    assert reserve(reopened) == ("AC-000001", "AC-000002")
    assert reserve(reopened, operation_id="dispatch-2", count=1) == ("AC-000003",)
    assert reopened.lookup(spec_id="001-demo", element_id="AC-000001") is None
    assert reopened.high_water(spec_id="001-demo", kind="AC") == "3"


@pytest.mark.parametrize("change", [{"count": 1}, {"kind": "FR"}, {"spec_id": "002-other"}])
def test_operation_ids_bind_all_arguments_and_conflicts_do_not_allocate(tmp_path, change):
    store = IdentityStore.initialize(tmp_path)
    reserve(store)
    with pytest.raises(IdentityStoreError):
        reserve(store, **change)
    assert reserve(store, operation_id="new", count=1) == ("AC-000003",)


def test_counters_are_independent_and_all_kinds_are_supported(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    for kind in ("AC", "FR", "NFR", "ISS", "U", "A", "T"):
        assert reserve(store, kind=kind, operation_id=kind, count=1) == (f"{kind}-000001",)
    assert reserve(store, spec_id="002-other", operation_id="other", count=1) == ("AC-000001",)


@pytest.mark.parametrize("change", [
    {"count": True}, {"count": False}, {"count": 0}, {"count": -1}, {"count": 1.5},
    {"count": "2"}, {"count": None}, {"kind": "XX"}, {"kind": "ac"},
    {"kind": None}, {"spec_id": " "}, {"operation_id": ""}, {"spec_id": 1},
])
def test_invalid_reservation_requests_fail_without_advancing(tmp_path, change):
    store = IdentityStore.initialize(tmp_path)
    with pytest.raises(IdentityStoreError):
        reserve(store, **change)
    assert reserve(store) == ("AC-000001", "AC-000002")


def test_legacy_import_preserves_subject_padding_and_copied_lookup(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    import_one(store)
    import_one(store)
    import_one(store, operation_id="same-definition-again")
    record = store.lookup(spec_id="001-demo", element_id="FR-001")
    assert record["element_id"] == "FR-001"
    assert record["subject"] == "original"
    record["subject"] = "tampered"
    assert store.lookup(spec_id="001-demo", element_id="FR-001")["subject"] == "original"
    assert reserve(store, kind="FR", count=1) == ("FR-000002",)


@pytest.mark.parametrize("label,subject", [("FR-000001", "original"), ("FR-001", "changed")])
def test_import_rejects_padding_alias_or_changed_subject(tmp_path, label, subject):
    store = IdentityStore.initialize(tmp_path)
    import_one(store)
    with pytest.raises(IdentityStoreError):
        import_one(store, label, subject, operation_id="different")


def test_import_retry_binds_spec_and_definitions_and_operation_type(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    import_one(store)
    for arguments in ({"spec_id": "002-other"}, {"definitions": [("FR-002", "other")]},
                      {"definitions": [("FR-001", "changed")]}):
        with pytest.raises(IdentityStoreError):
            import_one(store, **arguments)
    with pytest.raises(IdentityStoreError):
        reserve(store, operation_id="import-1")
    reserve(store)
    with pytest.raises(IdentityStoreError):
        import_one(store, operation_id="dispatch-1")


def test_opaque_composite_imports_do_not_raise_numeric_counters(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    import_one(store, "AC-legacy-999999", "opaque")
    import_one(store, "AC-001.002", "other opaque", operation_id="second")
    assert store.lookup(spec_id="001-demo", element_id="AC-legacy-999999")["subject"] == "opaque"
    assert reserve(store, count=1) == ("AC-000001",)


@pytest.mark.parametrize("definitions", [
    [("FR-001", "one"), ("FR-001", "one")], [("XX-001", "one")],
    [("FR-", "one")], [("FR-a b", "one")], [("FR-001", "")],
    [("FR-000", "zero")], [(None, "one")], [("FR-001", None)], [("FR-001",)],
])
def test_invalid_import_is_atomic(tmp_path, definitions):
    store = IdentityStore.initialize(tmp_path)
    with pytest.raises(IdentityStoreError):
        import_one(store, definitions=definitions)
    assert store.high_water(spec_id="001-demo", kind="FR") == "0"
    assert store.lookup(spec_id="001-demo", element_id="FR-001") is None


def test_mixed_import_conflict_rolls_back_entities_counters_and_operation(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    import_one(store)
    with pytest.raises(IdentityStoreError):
        import_one(store, operation_id="mixed", definitions=[("AC-999", "new"), ("FR-001", "changed")])
    assert store.lookup(spec_id="001-demo", element_id="AC-999") is None
    assert store.high_water(spec_id="001-demo", kind="AC") == "0"
    import_one(store, "AC-002", "valid retry after rollback", operation_id="mixed")
    assert store.high_water(spec_id="001-demo", kind="AC") == "2"


@pytest.mark.parametrize("label", ["AC-1", "AC-000002", "AC-3"])
def test_import_cannot_materialize_abandoned_reservation(tmp_path, label):
    store = IdentityStore.initialize(tmp_path)
    reserve(store, count=3)
    with pytest.raises(IdentityStoreError):
        import_one(store, label)
    assert reserve(IdentityStore.open(tmp_path), operation_id="later", count=1) == ("AC-000004",)


@pytest.mark.parametrize("ordinal,next_id", [
    ("999999", "AC-1000000"), ("9223372036854775808", "AC-9223372036854775809"),
    ("9999999999999999999999999999999999999999", "AC-10000000000000000000000000000000000000000"),
])
def test_unbounded_numeric_ordinals_are_persisted_as_decimal_text(tmp_path, ordinal, next_id):
    store = IdentityStore.initialize(tmp_path)
    import_one(store, f"AC-{ordinal}")
    assert store.high_water(spec_id="001-demo", kind="AC") == ordinal
    assert reserve(IdentityStore.open(tmp_path), count=1) == (next_id,)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        assert connection.execute("SELECT typeof(high_water) FROM counters").fetchone() == ("text",)


def test_initialize_is_explicit_and_incomplete_state_is_never_rebuilt(tmp_path):
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path)
    assert not (tmp_path / ".echelon/identity").exists()
    (tmp_path / ".echelon/identity").mkdir(parents=True)
    with pytest.raises(IdentityStoreError):
        IdentityStore.initialize(tmp_path)


@pytest.mark.parametrize("damage", ["delete_db", "delete_marker", "corrupt_db", "corrupt_marker", "mismatch", "schema", "version"])
def test_damaged_authority_fails_closed_and_cannot_reinitialize(tmp_path, damage):
    store = IdentityStore.initialize(tmp_path)
    reserve(store)
    directory = tmp_path / ".echelon/identity"
    database = directory / "registry.sqlite3"
    marker = directory / "authority.json"
    if damage == "delete_db":
        database.unlink()
    elif damage == "delete_marker":
        marker.unlink()
    elif damage == "corrupt_db":
        database.write_bytes(b"not sqlite")
    elif damage == "corrupt_marker":
        marker.write_text("{broken")
    elif damage == "mismatch":
        data = json.loads(marker.read_text())
        data["epoch_uuid"] = "00000000-0000-4000-8000-000000000000"
        marker.write_text(json.dumps(data))
    else:
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE entities" if damage == "schema" else "PRAGMA user_version=999")
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path)
    with pytest.raises(IdentityStoreError):
        reserve(store, operation_id="after-damage")
    with pytest.raises(IdentityStoreError):
        IdentityStore.initialize(tmp_path)
    if damage == "delete_db":
        assert not database.exists()


@pytest.mark.parametrize("component", [".echelon", ".echelon/identity", ".echelon/identity/authority.json", ".echelon/identity/registry.sqlite3", ".echelon/identity/registry.sqlite3-journal"])
def test_symlinked_authority_components_are_rejected(tmp_path, component):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = IdentityStore.initialize(workspace)
    target = workspace / component
    escaped = tmp_path / "escaped"
    if target.exists():
        target.rename(escaped)
    else:
        escaped.write_text("untouched")
    target.symlink_to(escaped, target_is_directory=escaped.is_dir())
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(workspace)
    with pytest.raises(IdentityStoreError):
        reserve(store)


def test_fresh_initialize_rejects_parent_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".echelon").symlink_to(outside, target_is_directory=True)
    with pytest.raises(IdentityStoreError):
        IdentityStore.initialize(workspace)
    assert list(outside.iterdir()) == []


def test_sensitive_files_and_directories_have_owner_only_permissions(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    reserve(store)
    backup = tmp_path / "backup"
    store.backup(backup)
    for directory in (tmp_path / ".echelon/identity", backup):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for child in directory.iterdir():
            assert stat.S_IMODE(child.stat().st_mode) == 0o600


def test_unreadable_authority_is_rejected(tmp_path):
    IdentityStore.initialize(tmp_path)
    marker = tmp_path / ".echelon/identity/authority.json"
    marker.chmod(0)
    try:
        with pytest.raises(IdentityStoreError):
            IdentityStore.open(tmp_path)
    finally:
        marker.chmod(0o600)


def test_backup_restore_preserves_identity_epoch_imports_and_reservations(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = IdentityStore.initialize(workspace)
    import_one(store)
    reserve(store)
    backup = tmp_path / "backup"
    store.backup(backup)
    reserve(store, operation_id="after-snapshot")
    restored_workspace = tmp_path / "restored"
    restored_workspace.mkdir()
    restored = IdentityStore.restore(restored_workspace, backup)
    assert reserve(restored) == ("AC-000001", "AC-000002")
    assert reserve(restored, operation_id="restored-next", count=1) == ("AC-000003",)
    assert restored.lookup(spec_id="001-demo", element_id="FR-001")["subject"] == "original"
    assert (restored_workspace / ".echelon/identity/authority.json").read_bytes() == (workspace / ".echelon/identity/authority.json").read_bytes()
    with pytest.raises(IdentityStoreError):
        store.backup(backup)
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(workspace, backup)


@pytest.mark.parametrize("damage", ["manifest_missing", "digest", "manifest_malformed", "identity", "schema", "symlink"])
def test_malformed_backup_cannot_create_destination_authority(tmp_path, damage):
    import hashlib

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = IdentityStore.initialize(workspace)
    backup = tmp_path / "backup"
    store.backup(backup)
    manifest = backup / "manifest.json"
    database = backup / "registry.sqlite3"
    if damage == "manifest_missing":
        manifest.unlink()
    elif damage == "digest":
        with database.open("ab") as stream:
            stream.write(b"corruption")
    elif damage == "manifest_malformed":
        manifest.write_text("[]")
    elif damage == "identity":
        data = json.loads((backup / "authority.json").read_text())
        data["workspace_uuid"] = "00000000-0000-4000-8000-000000000000"
        (backup / "authority.json").write_text(json.dumps(data))
    elif damage == "schema":
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE entities")
        data = json.loads(manifest.read_text())
        data["database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data))
    else:
        escaped = tmp_path / "escaped.sqlite3"
        database.rename(escaped)
        database.symlink_to(escaped)
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, backup)
    assert not (destination / ".echelon/identity").exists()


def test_decimal_ordinals_exceed_python_string_conversion_guard_without_global_changes(tmp_path):
    import sys

    guard = sys.get_int_max_str_digits()
    store = IdentityStore.initialize(tmp_path)
    import_one(store, "AC-" + "9" * 5000)
    assert reserve(store, count=1) == ("AC-1" + "0" * 5000,)
    assert store.high_water(spec_id="001-demo", kind="AC") == "1" + "0" * 5000
    assert sys.get_int_max_str_digits() == guard


def test_reservation_collision_query_handles_length_boundaries_and_gaps(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    import_one(store, "AC-8")
    assert reserve(store, count=3) == ("AC-000009", "AC-000010", "AC-000011")
    import_one(store, "AC-100", operation_id="raise")
    reserve(store, operation_id="above-100", count=3)
    import_one(store, "AC-099", operation_id="gap")
    for label in ("AC-09", "AC-10", "AC-011", "AC-102", "AC-0103"):
        with pytest.raises(IdentityStoreError):
            import_one(store, label, operation_id=label)
    assert store.high_water(spec_id="001-demo", kind="AC") == "103"


def test_existing_handle_rejects_replacement_with_another_valid_database(tmp_path):
    workspace = tmp_path / "one"
    other = tmp_path / "two"
    workspace.mkdir()
    other.mkdir()
    store = IdentityStore.initialize(workspace)
    IdentityStore.initialize(other)
    (workspace / ".echelon/identity/registry.sqlite3").write_bytes(
        (other / ".echelon/identity/registry.sqlite3").read_bytes())
    with pytest.raises(IdentityStoreError):
        reserve(store)


def test_marker_with_duplicate_keys_is_malformed(tmp_path):
    IdentityStore.initialize(tmp_path)
    marker = tmp_path / ".echelon/identity/authority.json"
    marker.write_text(marker.read_text().replace('"version":1', '"version":999,"version":1'))
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path)


def test_backup_manifest_authority_version_must_be_an_integer(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = IdentityStore.initialize(workspace)
    backup = tmp_path / "backup"
    store.backup(backup)
    manifest = backup / "manifest.json"
    data = json.loads(manifest.read_text())
    data["authority"]["version"] = True
    manifest.write_text(json.dumps(data))
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, backup)
    assert not (destination / ".echelon/identity").exists()


@pytest.mark.parametrize("sidecar", ["-journal", "-wal", "-shm"])
def test_backup_with_sqlite_sidecars_is_not_a_completed_standalone_snapshot(tmp_path, sidecar):
    store = IdentityStore.initialize(tmp_path)
    backup = tmp_path / "backup"
    store.backup(backup)
    (backup / ("registry.sqlite3" + sidecar)).write_bytes(b"unexpected snapshot sidecar")
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError):
        IdentityStore.restore(destination, backup)
    assert not (destination / ".echelon/identity").exists()


def authority_rows(database):
    """Capture all durable rows to detect repair, leaked receipts, or new claims."""
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("metadata", "counters", "operations", "reservations", "entities")
        }


def damage_counter(database, kind, value):
    with sqlite3.connect(database) as connection:
        if value is None:
            connection.execute("DELETE FROM counters WHERE spec_id=? AND kind=?", ("001-demo", kind))
        else:
            connection.execute("UPDATE counters SET high_water=? WHERE spec_id=? AND kind=?",
                               (value, "001-demo", kind))


@pytest.mark.parametrize("counter", ["1", None])
@pytest.mark.parametrize("action", ["reserve", "reserve_retry", "import", "lookup", "high_water"])
def test_counter_below_reservations_fails_without_repair_or_new_claims(tmp_path, counter, action):
    store = IdentityStore.initialize(tmp_path)
    assert reserve(store, count=3) == ("AC-000001", "AC-000002", "AC-000003")
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    damage_counter(database, "AC", counter)
    before = authority_rows(database)
    reopened = IdentityStore.open(tmp_path)
    with pytest.raises(IdentityStoreError, match="counter.*retained"):
        if action == "reserve":
            reserve(reopened, operation_id="subsequent", count=1)
        elif action == "reserve_retry":
            reserve(reopened, count=3)
        elif action == "import":
            import_one(reopened, "AC-100", operation_id="new-import")
        elif action == "lookup":
            reopened.lookup(spec_id="001-demo", element_id="AC-000002")
        else:
            reopened.high_water(spec_id="001-demo", kind="AC")
    assert authority_rows(database) == before


@pytest.mark.parametrize("counter", ["9", None])
@pytest.mark.parametrize("action", ["reserve", "import", "import_retry", "lookup", "high_water"])
def test_counter_below_imports_uses_numeric_max_and_keeps_legacy_labels(tmp_path, counter, action):
    store = IdentityStore.initialize(tmp_path)
    definitions = [("FR-009", "nine"), ("FR-10", "ten"), ("FR-opaque-99999", "opaque")]
    import_one(store, definitions=definitions)
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    damage_counter(database, "FR", counter)
    before = authority_rows(database)
    reopened = IdentityStore.open(tmp_path)
    with pytest.raises(IdentityStoreError, match="counter.*retained"):
        if action == "reserve":
            reserve(reopened, kind="FR", operation_id="subsequent", count=1)
        elif action == "import":
            import_one(reopened, "FR-100", operation_id="new-import")
        elif action == "import_retry":
            import_one(reopened, definitions=definitions)
        elif action == "lookup":
            reopened.lookup(spec_id="001-demo", element_id="FR-009")
        else:
            reopened.high_water(spec_id="001-demo", kind="FR")
    assert authority_rows(database) == before
    assert before["entities"] == [
        ("001-demo", "FR-009", "FR", "nine", "9"),
        ("001-demo", "FR-10", "FR", "ten", "10"),
        ("001-demo", "FR-opaque-99999", "FR", "opaque", None),
    ]


def test_retained_reservation_maxima_compare_endpoints_numerically(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    reserve(store, count=9)
    reserve(store, operation_id="at-ten", count=1)
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    damage_counter(database, "AC", "9")
    before = authority_rows(database)
    with pytest.raises(IdentityStoreError, match="counter.*retained"):
        reserve(store, operation_id="must-not-reuse-ten", count=1)
    assert authority_rows(database) == before


def test_namespace_audit_uses_true_maximum_endpoint_not_maximum_range_start(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    reserve(store, count=3)
    reserve(store, operation_id="later", count=1)
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE reservations SET last_ordinal='100', count='100' WHERE operation_id='dispatch-1'")
    before = authority_rows(database)
    with pytest.raises(IdentityStoreError, match="counter.*retained"):
        reserve(store, operation_id="after-corruption", count=1)
    assert authority_rows(database) == before


@pytest.mark.parametrize("source", ["reservations", "imports"])
@pytest.mark.parametrize("counter", ["9", None])
def test_restore_audits_retained_claims_before_creating_destination(tmp_path, source, counter):
    import hashlib

    store = IdentityStore.initialize(tmp_path)
    if source == "reservations":
        reserve(store, count=10)
    else:
        import_one(store, definitions=[("AC-009", "nine"), ("AC-10", "ten")])
    backup = tmp_path / "backup"
    store.backup(backup)
    database = backup / "registry.sqlite3"
    damage_counter(database, "AC", counter)
    manifest = backup / "manifest.json"
    data = json.loads(manifest.read_text())
    data["database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    before = authority_rows(database)
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(IdentityStoreError, match="counter.*retained"):
        IdentityStore.restore(destination, backup)
    assert not (destination / ".echelon").exists()
    assert authority_rows(database) == before
