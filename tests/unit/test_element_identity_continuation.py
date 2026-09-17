"""A completion-owned restoration advances history without early release."""
from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.element_identity_lifecycle import ElementCreate, ElementSnapshotMembership
from harness.element_identity_request_codec import encode_request
from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
from tests.unit.test_element_identity_source_store import seed_empty, source_request, state

pytestmark = pytest.mark.unit


def seeded(path):
    store, _ = seed_empty(path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    operation = PublicationOperation("lifecycle", "create", encode_request("lifecycle", (
        ElementCreate(label, "Lighting", "Light the scene", "reserve"),)))
    request = replace(source_request(operations=(operation,)), continuation_id="restore")
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    return store, request


def continuation(store):
    from harness.element_identity_publication import PublicationContinuationClaim
    parent = store.identity_publication(spec_id="demo", operation_id="pub")
    claim = PublicationContinuationClaim("pub", parent["preparation"]["request_sha256"],
        hashlib.sha256(parent["application_receipt"].encode("ascii")).hexdigest(),
        "native-completion", "c" * 64)
    operation = PublicationOperation("lifecycle", "membership", encode_request("lifecycle", (
        ElementSnapshotMembership("FR-000001", "1", False, None, "candidate-a"),)))
    request = replace(source_request("pub", operations=(operation,)), continuation=claim)
    proposed = store.preview_identity_history(spec_id="demo", operations=(operation,),
        publication_id="restore", continuation_request=request)
    return replace(request, proposed_history_sha256=proposed.sha256)


def test_linked_restoration_keeps_original_receipt_and_releases_atomically(tmp_path):
    store, request = seeded(tmp_path)
    original = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    store = IdentityStore.open(tmp_path)
    assert store.pending_identity_publication(spec_id="demo")["preparation"]["operation_id"] == "pub"
    before = state(tmp_path)
    for operation in ("pub", "restore"):
        with pytest.raises(IdentityStoreError):
            store.release_identity_publication(spec_id="demo", operation_id=operation, completion_payload="done")
        assert state(tmp_path) == before
    application = store.apply_identity_publication(spec_id="demo", operation_id="restore")
    assert application["identity_history_sha256"] == child.proposed_history_sha256
    assert store.lookup(spec_id="demo", element_id="FR-000001")["present"] is False
    assert store.lookup(spec_id="demo", element_id="FR-000001")["revision"] == "2"
    assert store.source_context(spec_id="demo", context_id="run")["operation_id"] == "restore"
    assert store.source_context(spec_id="demo", context_id="run")["sequence"] == "2"
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == original
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    with pytest.raises(IdentityStoreError):
        store.reserve(spec_id="demo", kind="FR", operation_id="unrelated", count=1)
    with pytest.raises(IdentityStoreError):
        store.release_identity_publication(spec_id="demo", operation_id="restore", completion_payload="done")
    store.audit()
    released = store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    store = IdentityStore.open(tmp_path)
    assert store.pending_identity_publication(spec_id="demo") is None
    assert store.identity_publication(spec_id="demo", operation_id="restore")["completion_payload"] == "done"
    assert store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    assert store.apply_identity_publication(spec_id="demo", operation_id="restore") == application
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == original
    assert store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done") == released
    assert store.reserve(spec_id="demo", kind="FR", operation_id="next", count=1) == ("FR-000002",)
    store.audit()


def test_parent_cannot_release_without_promised_continuation(tmp_path):
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    assert state(tmp_path) == before


@pytest.mark.parametrize("damage", ["id", "parent", "request", "application", "context", "predecessor"])
def test_continuation_requires_exact_pending_owner_and_source(tmp_path, damage):
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    operation = "restore"
    if damage == "id": operation = "unowned"
    if damage == "parent": child = replace(child, continuation=replace(child.continuation, parent_operation_id="missing"))
    if damage == "request": child = replace(child, continuation=replace(child.continuation, parent_request_sha256="d" * 64))
    if damage == "application": child = replace(child, continuation=replace(child.continuation, parent_application_sha256="d" * 64))
    if damage == "context": child = replace(child, sources=replace(child.sources, context_id="other"))
    if damage == "predecessor": child = replace(child, sources=replace(child.sources, expected_operation_id="reg"))
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id=operation, request=child)
    assert state(tmp_path) == before


def test_continuation_wire_roundtrip_preserves_legacy_encoding(tmp_path):
    from harness.element_identity_publication import encode_publication_request, decode_publication_request
    store, root = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    for request in (root, continuation(store)):
        wire = encode_publication_request(request)
        assert json.loads(wire)["version"] == "4"
        assert decode_publication_request(wire) == request
    legacy = source_request()
    assert json.loads(encode_publication_request(legacy))["version"] == "2"
    assert decode_publication_request(encode_publication_request(legacy)) == legacy


def test_declared_continuation_id_is_reserved_globally(tmp_path):
    store, _ = seeded(tmp_path)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.reserve(spec_id="other", kind="FR", operation_id="restore", count=1)
    assert state(tmp_path) == before
    store.reserve(spec_id="other", kind="FR", operation_id="other-reservation", count=1)
    before = state(tmp_path)
    operation = PublicationOperation("lifecycle", "restore", encode_request("lifecycle", (
        ElementCreate("FR-000001", "Other", "Other body", "other-reservation"),)))
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="other", operation_id="other",
            request=PublicationIntentRequest("a" * 64, "other", (operation,)))
    assert state(tmp_path) == before


@pytest.mark.parametrize("step", ["prepare", "apply", "release"])
def test_fault_rolls_back_entire_continuation_step(tmp_path, monkeypatch, step):
    from harness import element_identity_source_store as sources
    store, _ = seeded(tmp_path)
    original = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    if step in {"apply", "release"}:
        store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    if step == "release":
        store.apply_identity_publication(spec_id="demo", operation_id="restore")
        # Inject inside the caller's real transaction, after both row updates.
        from contextlib import contextmanager
        transaction = store._transaction
        @contextmanager
        def fail_commit(*args, **kwargs):
            with transaction(*args, **kwargs) as connection:
                yield connection
                if kwargs.get("write"):
                    raise RuntimeError("injected commit fault")
        monkeypatch.setattr(store, "_transaction", fail_commit)
        action = lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    else:
        method = getattr(sources, "prepare" if step == "prepare" else "accept")
        def fail_after(*args, **kwargs):
            method(*args, **kwargs)
            raise RuntimeError("injected source fault")
        monkeypatch.setattr(sources, "prepare" if step == "prepare" else "accept", fail_after)
        action = (lambda: store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)) if step == "prepare" else (
            lambda: store.apply_identity_publication(spec_id="demo", operation_id="restore"))
    before = state(tmp_path)
    with pytest.raises(RuntimeError, match="injected"):
        action()
    assert state(tmp_path) == before
    monkeypatch.undo()
    store = IdentityStore.open(tmp_path)
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == original
    store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    store.apply_identity_publication(spec_id="demo", operation_id="restore")
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    store.audit()


def test_schema7_explicit_upgrade_preserves_pending_legacy_publication(tmp_path):
    from harness import element_identity_schema as schema
    from tests.unit.test_element_identity_source_store import DATABASE
    store, _ = seed_empty(tmp_path)
    request = source_request()
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        for name in schema.CONTINUATION_SCHEMA:
            connection.execute(f"DROP INDEX {name}")
        connection.execute(schema.PUBLICATION_SCHEMA["publication_pending_specs"])
        connection.execute("UPDATE metadata SET value='7' WHERE key='schema_version'")
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path)
    assert state(tmp_path) == before
    upgraded = IdentityStore.upgrade(tmp_path)
    assert upgraded.audit()["database_schema_version"] == "8"
    assert upgraded.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    upgraded.apply_identity_publication(spec_id="demo", operation_id="pub")
    upgraded.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")


@pytest.mark.parametrize("damage", ["empty", "nested", "extra", "no-source", "bad-hash", "missing-key", "scalar"])
def test_closed_continuation_wire_rejects_invalid_claims(tmp_path, damage):
    from harness.element_identity_publication import encode_publication_request, decode_publication_request, PublicationIntentError
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    value = json.loads(encode_publication_request(continuation(store)))
    if damage == "empty": value["continuation"] = None
    if damage == "nested": value["continuation_id"] = "grandchild"
    if damage == "extra": value["continuation"]["authorize"] = True
    if damage == "no-source": del value["sources"]
    if damage == "bad-hash": value["continuation"]["parent_application_sha256"] = "wrong"
    if damage == "missing-key": del value["continuation"]["completion_id"]
    if damage == "scalar": value["continuation"] = 1
    with pytest.raises(PublicationIntentError):
        decode_publication_request(json.dumps(value))


@pytest.mark.parametrize("damage", [
    "DELETE FROM publication_intents WHERE operation_id='pub'",
    "UPDATE publication_intents SET application_receipt_sha256='bad' WHERE operation_id='pub'",
    "UPDATE publication_intents SET request_sha256='bad' WHERE operation_id='restore'",
    "UPDATE publication_intents SET state='released', completion_payload='done', completion_payload_sha256='bad' WHERE operation_id='restore'",
    "UPDATE source_contexts SET head_publication_id='pub'",
    "DELETE FROM snapshot_memberships",
])
def test_corrupted_continuation_rejects_restart_reads_audit_and_retry(tmp_path, damage):
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    store.apply_identity_publication(spec_id="demo", operation_id="restore")
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute(damage)
    before = state(tmp_path)
    for action in (store.audit,
            lambda: store.identity_history(spec_id="demo"),
            lambda: store.pending_identity_publication(spec_id="demo"),
            lambda: store.apply_identity_publication(spec_id="demo", operation_id="pub"),
            lambda: store.apply_identity_publication(spec_id="demo", operation_id="restore"),
            lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")):
        with pytest.raises(IdentityStoreError):
            action()
        assert state(tmp_path) == before


@pytest.mark.parametrize("step", ["prepare", "apply", "release"])
def test_uncertain_commit_outcome_replays_without_duplicate_history(tmp_path, monkeypatch, step):
    from contextlib import contextmanager
    import harness.element_identity_store as authority
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    if step in {"apply", "release"}:
        store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child)
    if step == "release":
        store.apply_identity_publication(spec_id="demo", operation_id="restore")
    action = {
        "prepare": lambda: store.prepare_identity_publication(spec_id="demo", operation_id="restore", request=child),
        "apply": lambda: store.apply_identity_publication(spec_id="demo", operation_id="restore"),
        "release": lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done"),
    }[step]
    original = authority._database
    class CommitThenFail:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise sqlite3.OperationalError("uncertain commit")
    @contextmanager
    def database(*args, **kwargs):
        with original(*args, **kwargs) as connection:
            yield CommitThenFail(connection)
    with monkeypatch.context() as patch:
        patch.setattr(authority, "_database", database)
        with pytest.raises(IdentityStoreError, match="uncertain commit"):
            action()
    store = IdentityStore.open(tmp_path)
    before = state(tmp_path)
    action()
    assert state(tmp_path) == before
    store.audit()


def test_unrelated_preview_remains_blocked_while_continuation_is_pending(tmp_path):
    store, _ = seeded(tmp_path)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    child = continuation(store)
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo", operations=child.operations)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo", operations=child.operations,
            publication_id="unowned", continuation_request=child)
    assert state(tmp_path) == before


def test_old_schema_cannot_smuggle_a_new_continuation_through_upgrade(tmp_path):
    from harness import element_identity_schema as schema
    seeded(tmp_path)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        for name in schema.CONTINUATION_SCHEMA:
            connection.execute(f"DROP INDEX {name}")
        connection.execute(schema.PUBLICATION_SCHEMA["publication_pending_specs"])
        connection.execute("UPDATE metadata SET value='7' WHERE key='schema_version'")
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert state(tmp_path) == before


def test_promise_cannot_coexist_with_a_foreign_operation(tmp_path):
    store, _ = seeded(tmp_path)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("INSERT INTO operations VALUES ('restore','reserve','other','bad')")
    with pytest.raises(IdentityStoreError):
        store.identity_publication(spec_id="demo", operation_id="pub")
