import pytest
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

from harness.element_identity_store import IdentityStore, IdentityStoreError


DATABASE = ".echelon/identity/registry.sqlite3"
FIELDS = ("workspace_uuid", "epoch_uuid", "run_id", "context_id", "spec_path",
          "source_registration_operation_id", "source_manifest_sha256")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def manifest_value():
    return {"version": "1", "files": [], "trees": [{"path": "specs/demo", "exists": "true",
        "directories": [{"path": "specs/demo", "mode": "493"}], "files": []}]}


def seed(path, *, value=None, spec="demo", context="source", operation="source-registration"):
    from harness.squad_source_manifest_codec import decode_source_manifest
    from harness.element_identity_managed import ManagedIdentityRequest
    store = IdentityStore.initialize(path)
    manifest = decode_source_manifest(canonical(manifest_value() if value is None else value))
    source = store.register_source_context(spec_id=spec, context_id=context, operation_id=operation, manifest=manifest)
    request = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"], "first", context,
                                     "specs/demo", operation, manifest.sha256)
    return store, request


def register(store, request, operation="managed-registration", spec="demo"):
    return store.register_managed_identity(spec_id=spec, operation_id=operation, request=request)


def state(path):
    with closing(sqlite3.connect(path / DATABASE)) as connection:
        return tuple(connection.iterdump())


def wire_request():
    from harness.element_identity_managed import ManagedIdentityRequest
    return ManagedIdentityRequest("12345678-1234-1234-1234-123456789abc",
        "23456789-2345-2345-2345-23456789abcd", "first", "source", "specs/demo",
        "source-registration", "a" * 64)


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available
    if not _secure_posix_capabilities_available():
        pytest.skip("secure POSIX source capture unavailable")


def test_register_fresh_managed_spec_retains_namespace_and_source(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    root = tmp_path.resolve()
    (root / "specs/demo").mkdir(parents=True)
    squad = root / "runs/first"
    squad.mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, squad, "6" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(root)
    source = store.register_source_context(spec_id="demo", context_id="first-source",
        operation_id="source-registration", manifest=manifest)
    assert source["sequence"] == "0"
    register = store.register_managed_identity
    from harness.element_identity_managed import ManagedIdentityRequest
    request = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"],
        "first", "first-source", "specs/demo", "source-registration", manifest.sha256)
    receipt = register(spec_id="demo", operation_id="managed-registration", request=request)
    assert receipt == {"version": "1", "workspace_uuid": source["workspace_uuid"],
        "epoch_uuid": source["epoch_uuid"], "spec_id": "demo",
        "operation_id": "managed-registration", "run_id": "first",
        "context_id": "first-source", "spec_path": "specs/demo",
        "source_registration_operation_id": "source-registration",
        "source_manifest_sha256": manifest.sha256}
    assert IdentityStore.open(root).managed_identity(spec_id="demo") == receipt


def test_closed_codec_independent_wire_and_exact_record(tmp_path):
    from harness.element_identity_managed import encode_managed_identity_request, decode_managed_identity_request
    expected = ('{"context_id":"source","epoch_uuid":"23456789-2345-2345-2345-23456789abcd",'
        '"run_id":"first","source_manifest_sha256":"' + "a" * 64 + '",'
        '"source_registration_operation_id":"source-registration","spec_path":"specs/demo",'
        '"version":"1","workspace_uuid":"12345678-1234-1234-1234-123456789abc"}')
    assert encode_managed_identity_request(wire_request()) == expected
    assert decode_managed_identity_request(expected) == wire_request()
    store, request = seed(tmp_path)
    before_history = store.identity_history(spec_id="demo")
    receipt = register(store, request)
    assert receipt == {"version": "1", "workspace_uuid": request.workspace_uuid,
        "epoch_uuid": request.epoch_uuid, "spec_id": "demo", "operation_id": "managed-registration",
        "run_id": "first", "context_id": "source", "spec_path": "specs/demo",
        "source_registration_operation_id": "source-registration", "source_manifest_sha256": request.source_manifest_sha256}
    assert store.identity_history(spec_id="demo") == before_history
    original = receipt.copy()
    receipt["run_id"] = "mutated"
    assert register(store, request) == original
    assert store.managed_identity(spec_id="absent") is None
    counts = store.audit()["table_counts"]
    assert counts["managed_identity_specs"] == "1" and counts["operations"] == "2"
    assert all(counts[t] == "0" for t in ("counters", "reservations", "revisions", "publication_intents"))


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("damage", [None, True, [], " ", "\ud800", "delete"])
def test_frozen_fields_revalidated_at_codec_and_store_entries(tmp_path, monkeypatch, field, damage):
    from harness.element_identity_managed import encode_managed_identity_request
    request = wire_request()
    if damage == "delete": object.__delattr__(request, field)
    else: object.__setattr__(request, field, damage)
    with pytest.raises(ValueError) as error: encode_managed_identity_request(request)
    assert len(str(error.value)) < 100 and error.value.__suppress_context__
    store = IdentityStore.initialize(tmp_path)
    entered = []
    def forbidden(**kwargs):
        entered.append(kwargs)
        raise AssertionError("malformed request reached transaction")
    monkeypatch.setattr(store, "_transaction", forbidden)
    with pytest.raises(IdentityStoreError) as error: register(store, request)
    assert len(str(error.value)) < 100 and error.value.__suppress_context__
    assert not entered


@pytest.mark.parametrize("field,value", [
    ("workspace_uuid", "12345678123412341234123456789abc"),
    ("workspace_uuid", "12345678-1234-1234-1234-123456789ABC"),
    ("epoch_uuid", "wrong"), ("spec_path", "/specs/demo"), ("spec_path", "specs/../demo"),
    ("spec_path", "specs//demo"), ("spec_path", "specs/demo/"), ("spec_path", "."),
    ("source_manifest_sha256", "A" * 64), ("source_manifest_sha256", "a" * 63),
])
def test_constructor_rejects_noncanonical_fields(field, value):
    with pytest.raises(ValueError): replace(wire_request(), **{field: value})


@pytest.mark.parametrize("damage", ["extra", "missing", "numeric", "bool", "duplicate", "noncanonical", "unicode", "deep", "list"])
def test_decode_closed_strict_wire_and_bounded_errors(damage):
    from harness.element_identity_managed import encode_managed_identity_request, decode_managed_identity_request
    payload = encode_managed_identity_request(wire_request())
    value = json.loads(payload)
    if damage == "extra": value["optional"] = "false"
    if damage == "missing": del value["run_id"]
    if damage == "numeric": value["version"] = 1
    if damage == "bool": value["version"] = True
    payload = canonical(value)
    if damage == "duplicate": payload = payload[:-1] + ',"version":"1"}'
    if damage == "noncanonical": payload += " "
    if damage == "unicode": payload = '"\ud800"'
    if damage == "deep": payload = "[" * 5000 + "]" * 5000
    if damage == "list": payload = "[]"
    with pytest.raises(ValueError) as error: decode_managed_identity_request(payload)
    assert len(str(error.value)) < 100 and error.value.__suppress_context__


def test_exact_types_pure_codec_and_baseexception(monkeypatch):
    import harness.element_identity_managed as managed
    class Derived(managed.ManagedIdentityRequest): pass
    with pytest.raises(ValueError): Derived(*(getattr(wire_request(), field) for field in FIELDS))
    class Text(str): pass
    with pytest.raises(ValueError): managed.decode_managed_identity_request(Text("{}"))
    def stop(_): raise KeyboardInterrupt()
    monkeypatch.setattr(managed, "strict_json", stop)
    with pytest.raises(KeyboardInterrupt): managed.decode_managed_identity_request("{}")


def test_codec_is_pure_and_normalizes_ordinary_failures(monkeypatch):
    import harness.element_identity_managed as managed
    request = wire_request()
    expected = managed.encode_managed_identity_request(request)
    def forbidden(*args, **kwargs): raise AssertionError("codec performed I/O")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    assert managed.encode_managed_identity_request(request) == expected
    assert managed.decode_managed_identity_request(expected) == request
    def ordinary(*args): raise RuntimeError("untrusted" * 10000)
    monkeypatch.setattr(managed, "_canonical", ordinary)
    with pytest.raises(ValueError) as error: managed.encode_managed_identity_request(request)
    assert len(str(error.value)) < 100 and error.value.__cause__ is None and error.value.__suppress_context__


def test_store_preserves_baseexception(tmp_path, monkeypatch):
    store, request = seed(tmp_path)
    def stop(**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr(store, "_transaction", stop)
    with pytest.raises(KeyboardInterrupt): register(store, request)
    with pytest.raises(KeyboardInterrupt): store.managed_identity(spec_id="demo")


@pytest.mark.parametrize("damage", ["nonempty", "missing", "nested", "empty-selection", "wrong-selection"])
def test_first_enrollment_requires_exact_empty_selected_root(tmp_path, damage):
    value = manifest_value()
    tree = value["trees"][0]
    if damage == "nonempty": tree["directories"].append({"path": "specs/demo/nested", "mode": "493"})
    if damage == "missing": tree.update(exists="false", directories=[])
    if damage == "nested": tree.update(path="specs/demo/nested", directories=[{"path": "specs/demo/nested", "mode": "493"}])
    if damage == "empty-selection": value["trees"] = []
    if damage == "wrong-selection": tree.update(path="specs", directories=[{"path": "specs", "mode": "493"}])
    store, request = seed(tmp_path, value=value)
    before, source = state(tmp_path), store.source_context(spec_id="demo", context_id="source")
    with pytest.raises(IdentityStoreError): register(store, request)
    assert state(tmp_path) == before
    assert store.source_context(spec_id="demo", context_id="source") == source


@pytest.mark.parametrize("field,value", [("workspace_uuid", "12345678-1234-1234-1234-123456789abc"),
    ("epoch_uuid", "12345678-1234-1234-1234-123456789abc"), ("context_id", "unknown"),
    ("source_registration_operation_id", "unknown"), ("source_manifest_sha256", "b" * 64)])
def test_first_enrollment_rejects_wrong_associations_without_changes(tmp_path, field, value):
    store, request = seed(tmp_path)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): register(store, replace(request, **{field: value}))
    assert state(tmp_path) == before


@pytest.mark.parametrize("history", ["reservation-gap", "import", "active", "terminal", "publication"])
def test_first_enrollment_rejects_retained_identity_history(tmp_path, history):
    from harness.element_identity_lifecycle import ElementCreate, ElementRetirement
    from harness.element_identity_publication import PublicationIntentRequest
    store, request = seed(tmp_path)
    if history in {"reservation-gap", "active", "terminal"}:
        label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    if history in {"active", "terminal"}:
        store.apply_lifecycle(spec_id="demo", operation_id="life", changes=(ElementCreate(label, "Title", "Body", "reserve"),))
    if history == "terminal":
        store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(ElementRetirement(label, "1", "done"),))
    if history == "import": store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-old", "Old"),))
    if history == "publication":
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=PublicationIntentRequest("a" * 64, "opaque", ()))
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    before, history_wire = state(tmp_path), store.identity_history(spec_id="demo")
    with pytest.raises(IdentityStoreError): register(store, request)
    assert state(tmp_path) == before and store.identity_history(spec_id="demo") == history_wire


def test_other_specs_history_dependencies_and_unusual_valid_root_mode(tmp_path):
    value = manifest_value()
    value["trees"][0]["directories"][0]["mode"] = "448"
    value["files"] = [{"path": "dependency.md", "image": {"kind": "file", "mode": "420", "sha256": "a" * 64}}]
    store, request = seed(tmp_path, value=value)
    store.import_identities(spec_id="other", operation_id="import", definitions=(("FR-old", "Old"),))
    store.reserve(spec_id="other", kind="AC", operation_id="reserve", count=3)
    assert register(store, request)["run_id"] == "first"


def test_conflicts_and_global_run_operation_ownership(tmp_path):
    from harness.squad_source_manifest_codec import decode_source_manifest
    store, request = seed(tmp_path)
    receipt = register(store, request)
    store.register_source_context(spec_id="other", context_id="source", operation_id="other-source",
        manifest=decode_source_manifest(canonical(manifest_value())))
    for changed, operation, spec in [(replace(request, run_id="second"), "managed-registration", "demo"),
        (request, "another", "demo"), (request, "source-registration", "demo"),
        (request, "managed-registration", "other"),
        (replace(request, source_registration_operation_id="other-source"), "another", "other")]:
        before = state(tmp_path)
        with pytest.raises(IdentityStoreError): register(store, changed, operation, spec)
        assert state(tmp_path) == before
    assert store.managed_identity(spec_id="demo") == receipt


def real_advance_setup(root):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    from harness.element_identity_managed import ManagedIdentityRequest
    (root / "specs/demo").mkdir(parents=True)
    (root / "dependency").write_bytes(b"real external dependency\x00\xff")
    squad = root / "runs/first"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(root, squad, "7" * 32)
    stage = transaction.build_path("definition")
    stage.write_bytes(b"new selected spec file")
    transaction.add_write(Path("specs/demo/definition.md"), stage,
                          owned_paths={Path("specs/demo/definition.md")})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=("dependency",)) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
        baseline = encode_initial_publication_sources(initial)
    store = IdentityStore.initialize(root)
    source = store.register_source_context(spec_id="demo", context_id="source", operation_id="source-registration", manifest=manifest)
    managed = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"], "first", "source",
        "specs/demo", "source-registration", manifest.sha256)
    request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "opaque recovery", (),
        PublicationSourceClaim("source", "source-registration", baseline))
    return store, managed, prepared, initial, request


@pytest.mark.parametrize("enroll_first", [True, False])
def test_real_source_advance_preserves_only_original_enrollment(tmp_path, secure_posix, enroll_first):
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_publication import PublicationIntentRequest
    root = tmp_path.resolve()
    store, request, prepared, initial, publication = real_advance_setup(root)
    if enroll_first: receipt = register(store, request)
    prepared.publish_sources(initial,
        before_publish=lambda _: store.prepare_identity_publication(spec_id="demo", operation_id="source-pub", request=publication),
        after_publish=lambda _: store.apply_identity_publication(spec_id="demo", operation_id="source-pub"))
    store.release_identity_publication(spec_id="demo", operation_id="source-pub", completion_payload="done")
    head = store.source_context(spec_id="demo", context_id="source")
    assert head["sequence"] == "1" and head["manifest"]["sha256"] != request.source_manifest_sha256
    if not enroll_first:
        before = state(root)
        with pytest.raises(IdentityStoreError): register(store, request)
        assert state(root) == before
        return
    creations = []
    for kind in ("AC", "FR", "NFR", "ISS", "U", "A", "T"):
        label, = store.reserve(spec_id="demo", kind=kind, operation_id="reserve-" + kind, count=1)
        creations.append(ElementCreate(label, kind + " title", "Body", "reserve-" + kind))
    store.apply_lifecycle(spec_id="demo", operation_id="seven-families", changes=tuple(creations))
    store.apply_lifecycle(spec_id="demo", operation_id="revision", changes=(ElementRevision(creations[0].element_id, "1", "AC title", "Updated body"),))
    history = store.identity_history(spec_id="demo")
    store.prepare_identity_publication(spec_id="demo", operation_id="pending", request=PublicationIntentRequest("a" * 64, "opaque", ()))
    store = IdentityStore.open(root)
    before = state(root)
    assert register(store, request) == receipt
    assert store.managed_identity(spec_id="demo") == receipt
    assert store.identity_history(spec_id="demo") == history
    assert state(root) == before
    assert store.audit()["table_counts"]["managed_identity_specs"] == "1"
    from harness import element_identity_managed_store as managed
    with store._transaction() as connection:
        forbidden = {"entities", "revisions", "lifecycle_heads", "lifecycle_lineage", "lifecycle_receipts",
                     "reference_claims", "issue_occurrences", "binding_receipts", "reservations", "counters"}
        connection.set_authorizer(lambda action, table, *_:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table in forbidden else sqlite3.SQLITE_OK)
        assert managed.read(connection, store, "demo") == receipt
        assert managed.register(connection, store, "demo", "managed-registration", request) == receipt


@pytest.mark.parametrize("phase", ["prepared", "released"])
def test_permanent_publication_child_claim_cannot_be_reused(tmp_path, phase):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_request_codec import encode_request
    store, request = seed(tmp_path)
    store.import_identities(spec_id="other", operation_id="import", definitions=(("FR-old", "Old"),))
    child = PublicationOperation("lifecycle", "claimed", encode_request("lifecycle", (ElementAdopt("FR-old", "Old", "Body"),)))
    store.prepare_identity_publication(spec_id="other", operation_id="pub", request=PublicationIntentRequest("a" * 64, "opaque", (child,)))
    if phase == "released":
        store.apply_identity_publication(spec_id="other", operation_id="pub")
        store.release_identity_publication(spec_id="other", operation_id="pub", completion_payload="done")
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): register(store, request, "claimed")
    assert state(tmp_path) == before


@pytest.mark.parametrize("stage", ["operation", "registry", "commit"])
def test_real_sql_failures_roll_back_both_records(tmp_path, stage):
    from harness import element_identity_managed_store as managed
    store, request = seed(tmp_path)
    before = state(tmp_path)
    with pytest.raises((IdentityStoreError, sqlite3.DatabaseError)):
        with store._transaction(write=True) as connection:
            denied = {"operation": (sqlite3.SQLITE_INSERT, "operations"),
                      "registry": (sqlite3.SQLITE_INSERT, "managed_identity_specs"),
                      "commit": (sqlite3.SQLITE_TRANSACTION, "COMMIT")}[stage]
            connection.set_authorizer(lambda action, target, *_:
                sqlite3.SQLITE_DENY if (action, target) == denied else sqlite3.SQLITE_OK)
            managed.register(connection, store, "demo", "managed-registration", request)
    assert state(tmp_path) == before
    assert IdentityStore.open(tmp_path).managed_identity(spec_id="demo") is None
    assert register(store, request)["operation_id"] == "managed-registration"


def test_uncertainty_after_actual_commit_recovers_original_receipt(tmp_path, monkeypatch):
    import harness.element_identity_store as authority
    store, request = seed(tmp_path)
    original = authority._database
    class ReportAfterCommit:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise sqlite3.OperationalError("uncertainty after actual COMMIT")
    @contextmanager
    def database(*args, **kwargs):
        with original(*args, **kwargs) as connection: yield ReportAfterCommit(connection)
    with monkeypatch.context() as patch:
        patch.setattr(authority, "_database", database)
        with pytest.raises(IdentityStoreError): register(store, request)
    reopened = IdentityStore.open(tmp_path)
    retained, before = reopened.managed_identity(spec_id="demo"), state(tmp_path)
    assert retained["operation_id"] == "managed-registration"
    assert register(reopened, request) == retained
    assert state(tmp_path) == before
    assert reopened.audit()["table_counts"]["operations"] == "2"


def test_current_backup_restore_and_upgrade_preserve_genesis(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    store, request = seed(source)
    receipt = register(store, request)
    store.reserve(spec_id="demo", kind="AC", operation_id="reserved", count=1)
    before = state(source)
    backup = tmp_path / "backup"
    store.backup(backup)
    destination = tmp_path / "restored"
    destination.mkdir()
    restored = IdentityStore.restore(destination, backup)
    assert restored.managed_identity(spec_id="demo") == receipt
    assert register(restored, request) == receipt
    assert state(source) == before and state(destination) == before
    assert IdentityStore.upgrade(source).managed_identity(spec_id="demo") == receipt
    assert state(source) == before


def competing_register(path, payload, operation, ready, go, results):
    from harness.element_identity_managed import decode_managed_identity_request
    store = IdentityStore.open(Path(path))
    ready.put(operation)
    go.wait(20)
    try:
        register(store, decode_managed_identity_request(payload), operation)
        results.put(("accepted", operation))
    except IdentityStoreError:
        results.put(("rejected", operation))


def test_two_real_spawned_processes_cannot_replace_genesis(tmp_path):
    import multiprocessing
    from harness.element_identity_managed import encode_managed_identity_request
    store, request = seed(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready, results, go = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=competing_register,
        args=(str(tmp_path), encode_managed_identity_request(request), operation, ready, go, results))
        for operation in ("left", "right")]
    for process in processes: process.start()
    try:
        assert {ready.get(timeout=20), ready.get(timeout=20)} == {"left", "right"}
        go.set()
        outcomes = [results.get(timeout=20), results.get(timeout=20)]
        assert sorted(status for status, _ in outcomes) == ["accepted", "rejected"]
        winner = next(operation for status, operation in outcomes if status == "accepted")
        assert store.managed_identity(spec_id="demo")["operation_id"] == winner
        assert store.audit()["table_counts"]["managed_identity_specs"] == "1"
    finally:
        for process in processes:
            process.join(20)
            if process.is_alive(): process.terminate(); process.join()
        for queue in (ready, results): queue.close(); queue.join_thread()


def backup_manifest(directory):
    (directory / "manifest.json").write_text(canonical({"version": 1, "completed": True,
        "authority": json.loads((directory / "authority.json").read_text()),
        "database_sha256": hashlib.sha256((directory / "registry.sqlite3").read_bytes()).hexdigest()}))


@pytest.mark.parametrize("damage", [
    "DELETE FROM managed_identity_specs", "DELETE FROM operations WHERE operation_id='managed-registration'",
    "UPDATE operations SET method='import' WHERE operation_id='managed-registration'",
    "UPDATE operations SET spec_id='other' WHERE operation_id='managed-registration'",
    "UPDATE operations SET digest='bad' WHERE operation_id='managed-registration'",
    "UPDATE managed_identity_specs SET run_id='changed'", "UPDATE managed_identity_specs SET context_id='unknown'",
    "UPDATE managed_identity_specs SET spec_id='other'",
    "UPDATE managed_identity_specs SET request_sha256='bad'", "UPDATE managed_identity_specs SET request='{}'",
    "UPDATE managed_identity_specs SET operation_id='source-registration'",
    "DELETE FROM source_contexts", "DELETE FROM operations WHERE operation_id='source-registration'",
    "UPDATE source_contexts SET head_publication_id='missing'",
    "UPDATE source_contexts SET registration_operation_id='managed-registration'",
    "INSERT INTO operations VALUES ('orphan','managed_identity','demo','bad')",
    "namespace-rehashed", "context-rehashed", "source-operation-rehashed", "source-manifest-rehashed",
    "genesis-hash-rehashed", "nonempty-original-rehashed",
])
def test_corruption_blocks_query_audit_snapshot_backup_restore_without_repair(tmp_path, damage):
    import harness.element_identity_store as authority
    store, request = seed(tmp_path)
    register(store, request)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        if not damage.endswith("rehashed"):
            connection.execute(damage)
        else:
            if damage in {"source-manifest-rehashed", "nonempty-original-rehashed"}:
                value = manifest_value()
                value["trees"][0]["directories"][0]["mode"] = "448"
                if damage == "nonempty-original-rehashed":
                    value["trees"][0]["directories"].append({"path": "specs/demo/nested", "mode": "493"})
                payload = canonical(value)
                digest = hashlib.sha256(payload.encode()).hexdigest()
                connection.execute("UPDATE source_contexts SET manifest=?,manifest_sha256=?", (payload, digest))
                connection.execute("UPDATE operations SET digest=? WHERE operation_id='source-registration'",
                    (authority._digest(["source_context", "demo", "source", payload]),))
                if damage == "source-manifest-rehashed":
                    connection.commit()
            if damage != "source-manifest-rehashed":
                value = json.loads(connection.execute("SELECT request FROM managed_identity_specs").fetchone()[0])
                if damage == "namespace-rehashed": value["workspace_uuid"] = wire_request().workspace_uuid
                if damage == "context-rehashed": value["context_id"] = "unknown"
                if damage == "source-operation-rehashed": value["source_registration_operation_id"] = "managed-registration"
                if damage == "genesis-hash-rehashed": value["source_manifest_sha256"] = "b" * 64
                if damage == "nonempty-original-rehashed": value["source_manifest_sha256"] = digest
                payload = canonical(value)
                connection.execute("UPDATE managed_identity_specs SET request=?,request_sha256=?,context_id=?",
                    (payload, hashlib.sha256(payload.encode()).hexdigest(), value["context_id"]))
                connection.execute("UPDATE operations SET digest=? WHERE operation_id='managed-registration'",
                    (authority._digest(["managed_identity", "demo", "managed-registration", payload]),))
        connection.commit()
    before = state(tmp_path)
    for action in (lambda: store.managed_identity(spec_id="demo"), lambda: register(store, request),
                   store.audit, lambda: store.identity_history(spec_id="demo"),
                   lambda: store.backup(tmp_path / "backup")):
        with pytest.raises(IdentityStoreError): action()
        assert state(tmp_path) == before
    assert not (tmp_path / "backup").exists()
    backup_manifest(tmp_path / ".echelon/identity")
    destination = tmp_path / "restored"
    destination.mkdir()
    with pytest.raises(IdentityStoreError): IdentityStore.restore(destination, tmp_path / ".echelon/identity")
    assert not (destination / ".echelon").exists()
    assert state(tmp_path) == before


def test_first_enrollment_audits_all_existing_authority_before_operation_insert(tmp_path):
    store, request = seed(tmp_path)
    store.reserve(spec_id="other", kind="AC", operation_id="reserve", count=1)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.execute("UPDATE reservations SET last_ordinal='3'")
        connection.commit()
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): register(store, request)
    assert state(tmp_path) == before


@pytest.mark.parametrize("history", ["empty-import", "removed-legacy-rows"])
def test_first_enrollment_rejects_retained_import_operation_without_entity_rows(tmp_path, history):
    store, request = seed(tmp_path)
    store.import_identities(spec_id="demo", operation_id="legacy-import",
        definitions=() if history == "empty-import" else (("FR-legacy", "Legacy"),))
    if history == "removed-legacy-rows":
        with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
            connection.execute("DELETE FROM lifecycle_heads WHERE spec_id='demo'")
            connection.execute("DELETE FROM entities WHERE spec_id='demo'")
            connection.commit()
    assert store.audit()["table_counts"]["entities"] == "0"
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): register(store, request)
    assert state(tmp_path) == before


def test_helpers_require_transaction_and_revalidate_inputs(tmp_path, monkeypatch):
    from harness import element_identity_managed_store as managed
    store, request = seed(tmp_path)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.row_factory = sqlite3.Row
        for action in (lambda: managed.register(connection, store, "demo", "new", request),
                       lambda: managed.read(connection, store, "demo"), lambda: managed.audit(connection, store)):
            with pytest.raises(IdentityStoreError): action()
        connection.execute("BEGIN")
        broken = replace(request)
        object.__delattr__(broken, "run_id")
        with pytest.raises(IdentityStoreError): managed.register(connection, store, "demo", "new", broken)
        with pytest.raises(IdentityStoreError): managed.read(connection, store, "\ud800")
        def stop(*args): raise KeyboardInterrupt()
        monkeypatch.setattr(managed, "_require", stop)
        with pytest.raises(KeyboardInterrupt): managed.read(connection, store, "demo")


def test_current_reads_and_retries_prohibit_identity_history_scans_and_use_indexes(tmp_path):
    from harness import element_identity_managed_store as managed
    store, request = seed(tmp_path)
    receipt = register(store, request)
    store.reserve(spec_id="demo", kind="AC", operation_id="reserve", count=2)
    with store._transaction() as connection:
        forbidden = {"counters", "reservations", "entities", "revisions", "lifecycle_heads", "lifecycle_lineage",
                     "lifecycle_receipts", "reference_claims", "issue_occurrences", "binding_receipts"}
        connection.set_authorizer(lambda action, table, *_:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table in forbidden else sqlite3.SQLITE_OK)
        assert managed.read(connection, store, "demo") == receipt
        assert managed.register(connection, store, "demo", "managed-registration", request) == receipt
        assert managed.read(connection, store, "absent") is None
        for query, args, index in [
            ("SELECT * FROM managed_identity_specs WHERE spec_id=?", ("demo",), "PRIMARY KEY"),
            ("SELECT operation_id FROM operations WHERE spec_id=? AND method='managed_identity' LIMIT 2", ("demo",), "managed_identity_operations"),
            ("SELECT * FROM operations WHERE operation_id=?", ("managed-registration",), "PRIMARY KEY"),
            ("SELECT * FROM source_contexts WHERE spec_id=? AND context_id=?", ("demo", "source"), "PRIMARY KEY")]:
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, args))
            assert "SEARCH" in plan and index in plan and "SCAN" not in plan


# Literal frozen schema-5 additions, independent of the current schema module.
V5_SOURCE_DDL = """
CREATE TABLE source_contexts (spec_id TEXT NOT NULL, context_id TEXT NOT NULL, registration_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id), manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, head_publication_id TEXT REFERENCES publication_intents(operation_id), PRIMARY KEY (spec_id,context_id)) WITHOUT ROWID;
CREATE TABLE source_publications (publication_id TEXT PRIMARY KEY REFERENCES publication_intents(operation_id), spec_id TEXT NOT NULL, context_id TEXT NOT NULL, sequence TEXT NOT NULL CHECK (sequence NOT GLOB '*[^0-9]*' AND (sequence = '0' OR sequence GLOB '[1-9]*') AND sequence != '0'), predecessor_operation_id TEXT NOT NULL REFERENCES operations(operation_id), manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, application_sha256 TEXT, FOREIGN KEY (spec_id,context_id) REFERENCES source_contexts(spec_id,context_id)) WITHOUT ROWID;
CREATE UNIQUE INDEX source_publication_sequences ON source_publications (spec_id,context_id,sequence);
CREATE INDEX source_publication_heads ON source_publications (spec_id,context_id,length(sequence),sequence) WHERE application_sha256 IS NOT NULL;
CREATE INDEX source_registration_specs ON operations (spec_id,operation_id) WHERE method='source_context';
"""


def freeze_v5(path):
    from tests.unit.test_element_identity_source_store import V4_PUBLICATION_DDL
    ddl = ((Path(__file__).parents[1] / "fixtures/element_identity/authority-v3.sql").read_text()
           + V4_PUBLICATION_DDL + V5_SOURCE_DDL)
    with closing(sqlite3.connect(path / DATABASE)) as source, closing(sqlite3.connect(":memory:")) as target:
        target.executescript(ddl)
        for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if table == "metadata": rows = [(key, "5" if key == "schema_version" else value) for key, value in rows]
            if rows: target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
        target.execute("PRAGMA user_version=1")
        target.commit()
        target.backup(source)


def source_publication_request(predecessor):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    baseline = {**manifest_value(), "publication": {"marker": {"schema_version": "1",
        "transaction_id": "1" * 32, "manifest_sha256": "a" * 64}, "operations": []}}
    return PublicationIntentRequest("a" * 64, "retained\r\nsource recovery", (),
        PublicationSourceClaim("source", predecessor, canonical(baseline)))


@pytest.mark.parametrize("phase", ["prepared", "applied", "released"])
def test_frozen_schema5_upgrade_restore_preserve_source_and_v2_journals(tmp_path, phase):
    from harness.squad_source_manifest_codec import decode_source_manifest
    source = tmp_path / "source"
    source.mkdir()
    store, _ = seed(source)
    original_registration = store.source_context(spec_id="demo", context_id="source")
    old_request = source_publication_request("source-registration")
    store.prepare_identity_publication(spec_id="demo", operation_id="old", request=old_request)
    store.apply_identity_publication(spec_id="demo", operation_id="old")
    store.release_identity_publication(spec_id="demo", operation_id="old", completion_payload="old done")
    request = source_publication_request("old")
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    if phase != "prepared": application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    if phase == "released": release = store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    retained = store.identity_publication(spec_id="demo", operation_id="pub")
    head = store.source_context(spec_id="demo", context_id="source")
    freeze_v5(source)
    before = state(source)
    directory = source / ".echelon/identity"
    marker = (directory / "authority.json").read_bytes()
    with pytest.raises(IdentityStoreError, match="upgrade"): IdentityStore.open(source)
    with pytest.raises(IdentityStoreError, match="upgrade"):
        store.reserve(spec_id="other", kind="AC", operation_id="no", count=1)
    with closing(sqlite3.connect(source / DATABASE)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        statements = []
        connection.set_trace_callback(statements.append)
        IdentityStore._audit(connection, lifecycle_state=True, binding_state=True, publication_state=True, source_state=True)
        assert not any("FROM managed_identity" in statement or "JOIN managed_identity" in statement for statement in statements)
    backup_manifest(directory)
    destination = tmp_path / "restored"
    destination.mkdir()
    restored = IdentityStore.restore(destination, directory)
    assert state(source) == before
    upgraded = IdentityStore.upgrade(source)
    assert (directory / "authority.json").read_bytes() == marker
    for candidate in (restored, upgraded):
        assert candidate.identity_publication(spec_id="demo", operation_id="pub") == retained
        assert candidate.source_context(spec_id="demo", context_id="source") == head
        assert candidate.register_source_context(spec_id="demo", context_id="source", operation_id="source-registration",
            manifest=decode_source_manifest(original_registration["manifest"]["payload"])) == original_registration
        assert candidate.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
        if phase != "prepared": assert candidate.apply_identity_publication(spec_id="demo", operation_id="pub") == application
        if phase == "released": assert candidate.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done") == release
        assert candidate.managed_identity(spec_id="demo") is None
        assert candidate.audit()["database_schema_version"] == "8"


def test_frozen_schema5_rejects_unsupported_managed_operations_without_managed_tables(tmp_path):
    seed(tmp_path)
    freeze_v5(tmp_path)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.execute("INSERT INTO operations VALUES ('impossible','managed_identity','demo','bad')")
        connection.commit()
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        statements = []
        connection.set_trace_callback(statements.append)
        with pytest.raises(IdentityStoreError, match="unsupported"):
            IdentityStore._audit(connection, lifecycle_state=True, binding_state=True, publication_state=True, source_state=True)
        assert not any("FROM managed_identity" in statement or "JOIN managed_identity" in statement for statement in statements)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before
    directory = tmp_path / ".echelon/identity"
    backup_manifest(directory)
    destination = tmp_path / "restored"
    destination.mkdir()
    with pytest.raises(IdentityStoreError): IdentityStore.restore(destination, directory)
    assert not (destination / ".echelon").exists()
