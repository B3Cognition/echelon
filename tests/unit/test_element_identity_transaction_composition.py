from contextlib import closing
import hashlib
import sqlite3

import pytest

from harness import element_identity_binding_store as binding_store
from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle_store as lifecycle_store
from harness.element_identity_lifecycle import ElementCreate, ElementRetirement, ElementRevision
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


SPEC = "demo"
SOURCE_SHA256 = hashlib.sha256(b"source").hexdigest()


def database(path):
    return path / ".echelon/identity/registry.sqlite3"


def sql_state(path):
    with closing(sqlite3.connect(database(path))) as connection:
        return tuple(connection.iterdump())


def reference(label, revision, *, anchor="span:0:6"):
    return bindings.ReferenceClaim(
        "evidence.md", SOURCE_SHA256, anchor, label, revision, "evidence",
    )


def occurrence(label, revision, title, body):
    return bindings.IssueOccurrence(
        label,
        revision,
        "report-1",
        SOURCE_SHA256,
        "ISS-legacy",
        title,
        body,
    )


def test_lifecycle_and_reference_binding_rollback_together(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Scene body", "reserve")
    claim = reference(label, "1")
    before = sql_state(tmp_path)
    with pytest.raises(RuntimeError, match="injected after both effects"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
            rows = binding_store.record(
                connection,
                store,
                "reference_claims",
                SPEC,
                "bind",
                bindings.request((claim,), bindings.ReferenceClaim),
            )
            assert rows[0]["target_revision"] == "1"
            assert connection.in_transaction
            raise RuntimeError("injected after both effects")
    assert sql_state(tmp_path) == before
    assert store.lookup(spec_id=SPEC, element_id=label) is None
    assert store.high_water(spec_id=SPEC, kind="FR") == "1"


def test_lifecycle_and_reference_binding_commit_as_one_unobserved_transaction(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Scene body", "reserve")
    claim = reference(label, "1")
    observer = sqlite3.connect(database(tmp_path))
    observer.execute("BEGIN")
    assert observer.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 0
    transaction = store._transaction
    statements = []
    with transaction(write=True) as connection:
        connection.set_trace_callback(statements.append)
        with monkeypatch.context() as context:
            context.setattr(
                store,
                "_transaction",
                lambda **_arguments: pytest.fail("helper opened a nested store transaction"),
            )
            lifecycle_receipt = lifecycle_store.apply_changes(
                connection, store, SPEC, "create", (create,),
            )
            binding_receipt = binding_store.record(
                connection,
                store,
                "reference_claims",
                SPEC,
                "bind",
                bindings.request((claim,), bindings.ReferenceClaim),
            )
        assert connection.in_transaction
        assert observer.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 0
        observer.rollback()
        observer.close()
        assert not any(
            statement.lstrip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"))
            for statement in statements
        )

    assert store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=(create,)) == lifecycle_receipt
    assert store.record_reference_claims(
        spec_id=SPEC, operation_id="bind", claims=(claim,),
    ) == binding_receipt
    saved = store.reference_claims(
        spec_id=SPEC, source_path="evidence.md", source_sha256=SOURCE_SHA256,
    )
    assert saved == (binding_receipt[0] | {
        "target_status": "active", "target_revision_matches_current": True,
    },)
    assert store.lookup(spec_id=SPEC, element_id=label)["content"] == "Scene body"
    counts = store.audit()["table_counts"]
    assert {name: counts[name] for name in (
        "operations", "entities", "revisions", "lifecycle_receipts",
        "reference_claims", "binding_receipts",
    )} == {
        "operations": "3",
        "entities": "1",
        "revisions": "1",
        "lifecycle_receipts": "1",
        "reference_claims": "1",
        "binding_receipts": "1",
    }


def test_lifecycle_and_issue_occurrence_commit_and_audit_together(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="ISS", operation_id="reserve", count=1)
    create = ElementCreate(label, "Broken movement", "Repair movement.", "reserve")
    item = occurrence(label, "1", "Broken movement", "Repair movement.")
    with store._transaction(write=True) as connection:
        lifecycle_receipt = lifecycle_store.apply_changes(
            connection, store, SPEC, "create", (create,),
        )
        occurrence_receipt = binding_store.record(
            connection,
            store,
            "issue_occurrences",
            SPEC,
            "observe",
            bindings.request((item,), bindings.IssueOccurrence),
        )
        assert connection.in_transaction

    assert store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=(create,)) == lifecycle_receipt
    assert store.record_issue_occurrences(
        spec_id=SPEC, operation_id="observe", occurrences=(item,),
    ) == occurrence_receipt
    assert store.issue_occurrences(spec_id=SPEC, issue_id=label) == occurrence_receipt
    report = store.audit()
    assert report["table_counts"]["revisions"] == "1"
    assert report["table_counts"]["issue_occurrences"] == "1"


def test_multiple_lifecycle_operations_bind_revisions_and_retry_exact_receipts(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "First body", "reserve")
    revise = ElementRevision(label, "1", "Scene", "Second body")
    retire = ElementRetirement(label, "2", "No longer required")
    requests = (("create", create), ("revise", revise), ("retire", retire))
    lifecycle_receipts = {}
    binding_receipts = {}
    with store._transaction(write=True) as connection:
        for index, (operation_id, change) in enumerate(requests, 1):
            lifecycle_receipts[operation_id] = lifecycle_store.apply_changes(
                connection, store, SPEC, operation_id, (change,),
            )
            claim = reference(label, str(index), anchor=f"revision-{index}")
            binding_receipts[operation_id] = binding_store.record(
                connection,
                store,
                "reference_claims",
                SPEC,
                f"bind-{operation_id}",
                bindings.request((claim,), bindings.ReferenceClaim),
            )
            assert connection.in_transaction

    before_retries = store.audit()["table_counts"]
    for operation_id, change in requests:
        assert store.apply_lifecycle(
            spec_id=SPEC, operation_id=operation_id, changes=(change,),
        ) == lifecycle_receipts[operation_id]
        index = ("create", "revise", "retire").index(operation_id) + 1
        claim = reference(label, str(index), anchor=f"revision-{index}")
        assert store.record_reference_claims(
            spec_id=SPEC, operation_id=f"bind-{operation_id}", claims=(claim,),
        ) == binding_receipts[operation_id]
    assert store.audit()["table_counts"] == before_retries
    assert store.lookup(spec_id=SPEC, element_id=label)["status"] == "retired"
    assert sorted(row["target_revision"] for row in store.reference_claims(
        spec_id=SPEC, source_path="evidence.md", source_sha256=SOURCE_SHA256,
    )) == ["1", "2", "3"]


def test_downstream_binding_failure_rolls_back_lifecycle_and_operation_receipt(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="ISS", operation_id="reserve", count=1)
    create = ElementCreate(label, "Broken movement", "Repair movement.", "reserve")
    mismatched = occurrence(label, "1", "Different title", "Repair movement.")
    before = sql_state(tmp_path)
    with pytest.raises(ValueError, match="exact historical active issue content"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
            binding_store.record(
                connection,
                store,
                "issue_occurrences",
                SPEC,
                "observe",
                bindings.request((mismatched,), bindings.IssueOccurrence),
            )
    assert sql_state(tmp_path) == before
    assert store.lookup(spec_id=SPEC, element_id=label) is None
    assert store.high_water(spec_id=SPEC, kind="ISS") == "1"


def test_conflicts_and_invalid_changes_roll_back_the_callers_whole_transaction(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    labels = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=2)
    first = ElementCreate(labels[0], "Scene", "First body", "reserve")
    store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=(first,))
    failures = (
        ("other-spec", "create", (first,)),
        (SPEC, "create", (ElementRevision(labels[0], "1", "Scene", "Changed payload"),)),
        (SPEC, "reserve", (ElementCreate(labels[1], "Second", "Body", "reserve"),)),
        (SPEC, "stale", (ElementRevision(labels[0], "2", "Scene", "Body"),)),
        (SPEC, "subject", (ElementRevision(labels[0], "1", "Different", "Body"),)),
        (SPEC, "duplicate", (
            ElementRevision(labels[0], "1", "Scene", "Body"),
            ElementRevision(labels[0], "1", "Scene", "Body"),
        )),
    )
    for spec_id, operation_id, changes in failures:
        before = sql_state(tmp_path)
        with pytest.raises((IdentityStoreError, ValueError)):
            with store._transaction(write=True) as connection:
                lifecycle_store.apply_changes(
                    connection, store, spec_id, operation_id, changes,
                )
        assert sql_state(tmp_path) == before


def test_damaged_counter_fails_before_retry_and_rolls_back_full_transaction(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Body", "reserve")
    receipt = store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=(create,))
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute("UPDATE counters SET high_water='0' WHERE spec_id=? AND kind='FR'", (SPEC,))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="counter is missing or below"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
    assert receipt[0]["revision"] == "1"
    assert sql_state(tmp_path) == before


def test_helper_requires_active_writable_transaction_before_operation_insert(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Body", "reserve")
    with sqlite3.connect(database(tmp_path), isolation_level=None) as connection:
        operation_count = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        with pytest.raises(IdentityStoreError, match="active transaction"):
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == operation_count

    before = sql_state(tmp_path)
    with pytest.raises(sqlite3.OperationalError, match="readonly database"):
        with store._transaction() as connection:
            connection.execute("PRAGMA query_only=ON")
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
    assert sql_state(tmp_path) == before


def test_direct_helper_and_public_wrapper_validate_before_writes(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Body", "reserve")
    object.__setattr__(create, "content", "\x00")
    before = sql_state(tmp_path)
    with pytest.raises(ValueError, match="without NUL"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
    assert sql_state(tmp_path) == before

    with monkeypatch.context() as context:
        context.setattr(
            store,
            "_transaction",
            lambda **_arguments: pytest.fail("public wrapper entered a transaction for invalid input"),
        )
        with pytest.raises(ValueError, match="nonempty sequence"):
            store.apply_lifecycle(spec_id=SPEC, operation_id="invalid", changes=())
