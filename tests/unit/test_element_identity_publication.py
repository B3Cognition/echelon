import pytest
from contextlib import closing, contextmanager
from dataclasses import replace
import hashlib
import json
import sqlite3

from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.element_identity_lifecycle import (
    ElementCreate, ElementAdopt, ElementRevision, ElementRetirement, ElementTransition,
)
from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence
from harness.element_identity_request_codec import encode_request, decode_request


pytestmark = pytest.mark.unit


def test_prepared_intent_blocks_new_spec_writes_without_applying_reserved_ids(tmp_path):
    from harness.element_identity_store import IdentityStore, IdentityStoreError
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_request_codec import encode_request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    payload = encode_request("lifecycle", (ElementCreate(label, "Scene", "Body", "reserve"),))
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    request = PublicationIntentRequest("a" * 64, "controller recovery bytes", (
        PublicationOperation("lifecycle", "publication-child", payload),
    ))
    receipt = store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=request)
    assert receipt["operation_id"] == "publication"
    assert store.lookup(spec_id="demo", element_id=label) is None
    with pytest.raises(IdentityStoreError, match="pending"):
        store.reserve(spec_id="demo", kind="FR", operation_id="later", count=1)
    assert store.high_water(spec_id="demo", kind="FR") == "1"


HASH = "a" * 64
DATABASE = ".echelon/identity/registry.sqlite3"


def sql_state(path):
    with closing(sqlite3.connect(path / DATABASE)) as connection:
        return tuple(connection.iterdump())


def request_for(*operations):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    return PublicationIntentRequest(HASH, "controller\r\nrecovery ž", tuple(
        PublicationOperation(method, operation_id, encode_request(method, entries))
        for method, operation_id, entries in operations
    ))


def seed(path):
    store = IdentityStore.initialize(path)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-007", "Legacy"),))
    changes = (ElementCreate(label, "Issue", "Body\r\nž", "reserve"),)
    claims = (ReferenceClaim("evidence.md", HASH, "E1", label, "1", "evidence"),
              ReferenceClaim("evidence.md", HASH, "E2", "FR-007", None, "reference"))
    occurrences = (IssueOccurrence(label, "1", "report", HASH, "ISS-legacy", "Issue", "Body\r\nž"),)
    request = request_for(("lifecycle", "child-life", changes),
                          ("reference_claims", "child-ref", claims),
                          ("issue_occurrences", "child-issue", occurrences))
    return store, label, request


def test_mixed_batch_exact_receipts_restart_release_and_later_heads(tmp_path):
    store, label, request = seed(tmp_path)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    marker = json.loads((tmp_path / ".echelon/identity/authority.json").read_text())
    assert set(preparation) == {"version", "workspace_uuid", "epoch_uuid", "spec_id", "operation_id",
                                "request_sha256", "plan_sha256"}
    assert preparation["version"] == "1"
    assert preparation["workspace_uuid"] == marker["workspace_uuid"]
    assert preparation["epoch_uuid"] == marker["epoch_uuid"]
    assert store.lookup(spec_id="demo", element_id=label) is None
    assert store.audit()["table_counts"]["publication_operation_claims"] == "3"
    before = sql_state(tmp_path)
    assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    assert sql_state(tmp_path) == before
    application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert set(application) == {"version", "publication", "operations"}
    assert application["publication"] == preparation
    assert application["operations"][0] == {"method": "lifecycle", "operation_id": "child-life", "receipt": [
        {"element_id": "ISS-000001", "revision": "1", "status": "active", "lineage": []}]}
    for operation in request.operations:
        entries = decode_request(operation.method, operation.payload)
        method, keyword = {"lifecycle": (store.apply_lifecycle, "changes"),
                           "reference_claims": (store.record_reference_claims, "claims"),
                           "issue_occurrences": (store.record_issue_occurrences, "occurrences")}[operation.method]
        assert list(method(spec_id="demo", operation_id=operation.operation_id, **{keyword: entries})) == next(
            item["receipt"] for item in application["operations"] if item["method"] == operation.method)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    completion = "owner-authenticated completion\r\nž"
    released = store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload=completion)
    assert released == {"version": "1", "publication": preparation,
                        "application_sha256": hashlib.sha256(json.dumps(application, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest(),
                        "completion_sha256": hashlib.sha256(completion.encode()).hexdigest()}
    store.apply_lifecycle(spec_id="demo", operation_id="later", changes=(ElementRevision(label, "1", "Issue", "new body"),))
    store = IdentityStore.open(tmp_path)
    assert store.pending_identity_publication(spec_id="demo") is None
    assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == application
    assert store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload=completion) == released
    record = store.identity_publication(spec_id="demo", operation_id="pub")
    assert set(record) == {"preparation", "state", "request", "application_receipt", "completion_payload"}
    assert record["state"] == "released" and record["completion_payload"] == completion
    record["preparation"]["operation_id"] = "mutated"
    assert store.identity_publication(spec_id="demo", operation_id="pub")["preparation"] == preparation
    assert store.audit()["table_counts"]["publication_intents"] == "1"


@pytest.mark.parametrize("state", ["prepared", "applied"])
def test_guard_all_writers_global_claims_and_exact_prior_retries(tmp_path, state):
    store, label, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    if state == "applied":
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    before = sql_state(tmp_path)
    rejected = [
        lambda: store.reserve(spec_id="demo", kind="AC", operation_id="new", count=1),
        lambda: store.import_identities(spec_id="demo", operation_id="new", definitions=()),
        lambda: store.apply_lifecycle(spec_id="demo", operation_id="new", changes=decode_request("lifecycle", request.operations[0].payload)),
        lambda: store.record_reference_claims(spec_id="demo", operation_id="new", claims=decode_request("reference_claims", request.operations[1].payload)),
        lambda: store.record_issue_occurrences(spec_id="demo", operation_id="new", occurrences=decode_request("issue_occurrences", request.operations[2].payload)),
        lambda: store.prepare_identity_publication(spec_id="demo", operation_id="new", request=request_for()),
        lambda: store.reserve(spec_id="other", kind="FR", operation_id="child-life", count=1),
        lambda: store.prepare_identity_publication(spec_id="other", operation_id="child-ref", request=request_for()),
        lambda: store.prepare_identity_publication(spec_id="other", operation_id="another", request=request),
        lambda: store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=replace(request, recovery_payload="changed")),
        lambda: store.identity_publication(spec_id="other", operation_id="pub"),
        lambda: store.identity_publication(spec_id="demo", operation_id="reserve"),
        lambda: store.apply_identity_publication(spec_id="demo", operation_id="missing"),
        lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload=" "),
        lambda: store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=2),
    ]
    if state == "prepared":
        rejected.extend([
            lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done"),
            lambda: store.apply_lifecycle(spec_id="demo", operation_id="child-life", changes=decode_request("lifecycle", request.operations[0].payload)),
        ])
    for call in rejected:
        with pytest.raises(IdentityStoreError):
            call()
        assert sql_state(tmp_path) == before
    assert store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1) == (label,)
    assert store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-007", "Legacy"),)) is None
    assert sql_state(tmp_path) == before
    assert store.reserve(spec_id="other", kind="FR", operation_id="other-reserve", count=1) == ("FR-000001",)
    assert store.identity_publication(spec_id="demo", operation_id="absent") is None


def test_empty_batch_retains_guard_until_explicit_release(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request_for())
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == {
        "version": "1", "publication": preparation, "operations": []}
    with pytest.raises(IdentityStoreError, match="pending"):
        store.import_identities(spec_id="demo", operation_id="import", definitions=())
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="different")
    assert sql_state(tmp_path) == before
    assert store.import_identities(spec_id="demo", operation_id="import", definitions=()) is None


@pytest.mark.parametrize("kind,predecessors,successors", [("replace", 1, 1), ("split", 1, 2), ("merge", 2, 1)])
def test_retained_plan_all_transition_kinds_and_adoption(tmp_path, kind, predecessors, successors):
    store = IdentityStore.initialize(tmp_path)
    old = tuple(f"FR-old{i}" for i in range(predecessors))
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple((x, x) for x in old))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(ElementAdopt(x, x, "body") for x in old))
    labels = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=successors)
    transition = ElementTransition(kind, tuple((x, "1") for x in old),
                                   tuple(ElementCreate(x, x, "next", "reserve") for x in labels), "reason ž")
    request = request_for(("lifecycle", "child", (transition,)))
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert len(application["operations"][0]["receipt"]) == predecessors + successors
    assert store.lineage(spec_id="demo", element_id=old[0])[0]["kind"] == kind
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(ElementRetirement(labels[0], "1", "finished"),))
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == application
    store.audit()


def test_projected_terminal_issue_accepts_old_active_but_rejects_terminal_revision(tmp_path):
    store, label, request = seed(tmp_path)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=decode_request("lifecycle", request.operations[0].payload))
    terminal = (ElementRetirement(label, "1", "fixed"),)
    occurrence = decode_request("issue_occurrences", request.operations[2].payload)[0]
    invalid = request_for(("lifecycle", "terminal", terminal), ("issue_occurrences", "occ", (replace(occurrence, issue_revision="2"),)))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=invalid)
    assert sql_state(tmp_path) == before
    valid = request_for(("lifecycle", "terminal", terminal), ("issue_occurrences", "occ", (occurrence,)))
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=valid)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    store.audit()


def test_codec_roundtrip_wide_strings_and_closed_shapes():
    from harness.element_identity_publication import encode_publication_request, decode_publication_request
    request = request_for(("lifecycle", "wide", (ElementRevision("FR-007", "9" * 5000, "S", "body\r\nž"),)))
    encoded = encode_publication_request(request)
    assert encoded.isascii() and "9" * 5000 in encoded
    assert decode_publication_request(encoded) == request
    assert encode_publication_request(request_for()) == '{"manifest_sha256":"' + HASH + '","operations":[],"recovery_payload":"controller\\r\\nrecovery \\u017e","version":"1"}'


@pytest.mark.parametrize("payload", [None, True, 1, [], "", "{", "[]", "null", "true", "9" * 5000,
    '[NaN]', '[Infinity]', '{"version":"1","version":"1"}',
    '[' * 2000 + ']' * 2000, '"\\ud800"'])
def test_codec_normalizes_malformed_inputs(payload):
    from harness.element_identity_publication import decode_publication_request, PublicationIntentError
    with pytest.raises(PublicationIntentError) as caught:
        decode_publication_request(payload)
    assert len(str(caught.value)) < 300


@pytest.mark.parametrize("field,value", [("version", 1), ("version", "2"), ("manifest_sha256", None),
    ("recovery_payload", False), ("operations", ""), ("extra", "bad")])
def test_codec_rejects_unexpected_keys_and_types(field, value):
    from harness.element_identity_publication import decode_publication_request, PublicationIntentError
    value_map = {"version": "1", "manifest_sha256": HASH, "operations": [], "recovery_payload": "recovery"}
    value_map[field] = value
    with pytest.raises(PublicationIntentError):
        decode_publication_request(json.dumps(value_map))


def test_frozen_subclasses_mutations_and_noncanonical_children_fail_before_transaction(tmp_path, monkeypatch):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation, PublicationIntentError, encode_publication_request
    store = IdentityStore.initialize(tmp_path)
    monkeypatch.setattr(store, "_transaction", lambda **kw: pytest.fail("entered transaction with malformed input"))
    class Derived(PublicationIntentRequest):
        pass
    with pytest.raises(PublicationIntentError):
        Derived(HASH, "recovery")
    bad = [object.__new__(Derived), object(), "request"]
    missing = request_for()
    object.__delattr__(missing, "manifest_sha256")
    bad.append(missing)
    for field, value in [("manifest_sha256", "A" * 64), ("recovery_payload", "\ud800"), ("operations", [])]:
        mutated = request_for()
        object.__setattr__(mutated, field, value)
        bad.append(mutated)
    for request in bad:
        with pytest.raises(IdentityStoreError):
            store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    for spec, operation in [("\ud800", "pub"), ("demo", "\x00"), (True, "pub")]:
        with pytest.raises(IdentityStoreError):
            store.apply_identity_publication(spec_id=spec, operation_id=operation)
    child = PublicationOperation("lifecycle", "child", encode_request("lifecycle", (ElementAdopt("FR-old", "S", "B"),)))
    for field, value in [("method", "unknown"), ("operation_id", " "), ("payload", child.payload + " ")]:
        mutated = replace(child)
        object.__setattr__(mutated, field, value)
        request = request_for()
        object.__setattr__(request, "operations", (mutated,))
        with pytest.raises(PublicationIntentError):
            encode_publication_request(request)


@pytest.mark.parametrize("method", ["prepare", "apply", "release", "read", "pending", "audit"])
def test_connection_helpers_require_caller_transaction(tmp_path, method):
    from harness import element_identity_publication_store as journal
    store = IdentityStore.initialize(tmp_path)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        arguments = {"prepare": ("demo", "pub", request_for()), "apply": ("demo", "pub"),
                     "release": ("demo", "pub", "done"), "read": ("demo", "pub"),
                     "pending": ("demo",), "audit": ()}[method]
        with pytest.raises(IdentityStoreError, match="transaction"):
            getattr(journal, method)(connection, store, *arguments)
        assert not connection.in_transaction


def test_connection_helpers_revalidate_none_and_do_not_own_transactions_or_pragmas(tmp_path):
    from harness import element_identity_publication_store as journal
    store = IdentityStore.initialize(tmp_path)
    with store._transaction(write=True) as connection:
        for method, args in [(journal.read, (None, "missing")), (journal.read, ("demo", None)),
                             (journal.pending, (None,))]:
            with pytest.raises(IdentityStoreError):
                method(connection, store, *args)
        statements = []
        connection.set_trace_callback(statements.append)
        preparation = journal.prepare(connection, IdentityStore, "demo", "pub", request_for())
        assert journal.read(connection, store, "demo", "pub")["preparation"] == preparation
        journal.apply(connection, store, "demo", "pub")
        journal.audit(connection, IdentityStore)
        journal.release(connection, store, "demo", "pub", "done")
        assert journal.pending(connection, store, "demo") is None
        assert connection.in_transaction
        assert not any(s.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK")) or
                       (s.upper().startswith("PRAGMA") and "=" in s) for s in statements)


def test_read_wrappers_one_query_only_transaction_and_prewrite_snapshots(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request_for())
    original = store._transaction
    observations = []
    @contextmanager
    def transaction(*, write=False):
        observations.append(write)
        with original(write=write) as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    monkeypatch.setattr(store, "_transaction", transaction)
    store.identity_publication(spec_id="demo", operation_id="pub")
    store.pending_identity_publication(spec_id="demo")
    assert observations == [False, False]


@pytest.mark.parametrize("owner", ["missing", "other", "pub"])
def test_private_owner_cannot_bypass_exact_claim_association(tmp_path, owner):
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    before = sql_state(tmp_path)
    with pytest.raises(ValueError):
        with store._transaction(write=True) as connection:
            store._operation(connection, "child-life", "lifecycle", "demo", "wrong digest", _publication_id=owner)
    assert sql_state(tmp_path) == before


def test_pending_and_global_claim_queries_are_indexed(tmp_path):
    from harness import element_identity_publication_store as journal
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    with store._transaction() as connection:
        for query, value in [(journal._PENDING, "demo"), (journal._CLAIM, "child-life")]:
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, (value,)))
            assert "SEARCH" in plan and "SCAN" not in plan and "TEMP B-TREE" not in plan
            print(plan)


@pytest.mark.parametrize("stage", ["reference_claims", "issue_occurrences", "application"])
def test_sqlite_fault_rolls_back_every_child_effect_and_preserves_guard(tmp_path, stage):
    store, label, request = seed(tmp_path)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    table = stage if stage != "application" else "publication_intents"
    # Fault at the actual SQLite statement inside the validated transaction.
    before = sql_state(tmp_path)
    from harness import element_identity_publication_store as journal
    with pytest.raises(IdentityStoreError):
        with store._transaction(write=True) as connection:
            def deny(action_code, target, column, _db, _source):
                if ((stage == "application" and action_code == sqlite3.SQLITE_UPDATE and target == table and column == "state")
                        or (stage != "application" and action_code == sqlite3.SQLITE_INSERT and target == table)):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(deny)
            journal.apply(connection, store, "demo", "pub")
    assert sql_state(tmp_path) == before
    store = IdentityStore.open(tmp_path)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    assert store.lookup(spec_id="demo", element_id=label) is None
    assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["publication"] == preparation


def test_release_commit_failure_retains_original_application_and_guard(tmp_path):
    from harness import element_identity_publication_store as journal
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    before = sql_state(tmp_path)
    with pytest.raises(sqlite3.DatabaseError):
        with store._transaction(write=True) as connection:
            journal.release(connection, store, "demo", "pub", "done")
            connection.set_authorizer(lambda action, arg, *_: sqlite3.SQLITE_DENY
                                      if action == sqlite3.SQLITE_TRANSACTION and arg == "COMMIT" else sqlite3.SQLITE_OK)
    assert sql_state(tmp_path) == before
    store = IdentityStore.open(tmp_path)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == application
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")


@pytest.mark.parametrize("state", ["prepared", "applied", "released"])
@pytest.mark.parametrize("damage", [
    "DELETE FROM publication_operation_claims WHERE method='reference_claims'",
    "UPDATE publication_operation_claims SET digest='broken' WHERE method='lifecycle'",
    "UPDATE publication_operation_claims SET publication_id='orphan' WHERE method='lifecycle'",
    "UPDATE publication_intents SET request_sha256='broken'",
    "UPDATE publication_intents SET plan_sha256='broken'",
    "UPDATE publication_intents SET plan='{}'",
    "UPDATE publication_intents SET request='{}'",
    "UPDATE operations SET digest='broken' WHERE operation_id='pub'",
    "UPDATE operations SET spec_id='other' WHERE operation_id='pub'",
    "UPDATE operations SET method='import' WHERE operation_id='pub'",
    "DELETE FROM operations WHERE operation_id='pub'",
    "DELETE FROM publication_intents",
    "INSERT INTO operations VALUES ('orphan','identity_publication','demo','broken')",
])
def test_audit_rejects_damaged_journal_claims_and_parent_associations(tmp_path, state, damage):
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    if state != "prepared":
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    if state == "released":
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute(damage)
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.audit()
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("damage", [
    "DELETE FROM operations WHERE operation_id='child-life'",
    "UPDATE operations SET method='import' WHERE operation_id='child-ref'",
    "UPDATE operations SET digest='bad' WHERE operation_id='child-issue'",
    "UPDATE operations SET spec_id='other' WHERE operation_id='child-life'",
    "DELETE FROM lifecycle_receipts WHERE operation_id='child-life'",
    "DELETE FROM binding_receipts WHERE operation_id='child-ref'",
    "UPDATE publication_intents SET application_receipt='{}'",
    "UPDATE publication_intents SET application_receipt_sha256='bad'",
    "UPDATE revisions SET content='damaged'",
    "UPDATE revisions SET reason='invented'",
    "UPDATE entities SET ordinal='9' WHERE kind='ISS'",
    "UPDATE publication_intents SET completion_payload_sha256='bad'",
])
def test_applied_and_released_retries_reject_damaged_original_effects(tmp_path, damage):
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute(damage)
    before = sql_state(tmp_path)
    for action in [store.audit, lambda: store.apply_identity_publication(spec_id="demo", operation_id="pub"),
                   lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")]:
        with pytest.raises(IdentityStoreError):
            action()
        assert sql_state(tmp_path) == before


@pytest.mark.parametrize("state", ["prepared", "applied", "released"])
def test_backup_restore_preserves_journal_namespace_receipts_and_guard(tmp_path, state):
    source = tmp_path / "source"
    source.mkdir()
    store, _, request = seed(source)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    if state != "prepared":
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    if state == "released":
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    original = store.identity_publication(spec_id="demo", operation_id="pub")
    store.backup(tmp_path / "backup")
    destination = tmp_path / "restored"
    destination.mkdir()
    restored = IdentityStore.restore(destination, tmp_path / "backup")
    assert restored.identity_publication(spec_id="demo", operation_id="pub") == original
    assert restored.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    restored.audit()
    before = sql_state(destination)
    IdentityStore.upgrade(destination)
    assert sql_state(destination) == before
    if state != "released":
        with pytest.raises(IdentityStoreError, match="pending"):
            restored.reserve(spec_id="demo", kind="FR", operation_id="new", count=1)
    else:
        assert restored.pending_identity_publication(spec_id="demo") is None
    with pytest.raises(IdentityStoreError):
        restored.reserve(spec_id="other", kind="FR", operation_id="child-life", count=1)


def test_codec_rejects_duplicate_nested_keys_method_order_and_child_ids():
    from harness.element_identity_publication import (PublicationIntentRequest, PublicationOperation,
        PublicationIntentError, encode_publication_request, decode_publication_request)
    lifecycle_op = PublicationOperation("lifecycle", "child", encode_request("lifecycle", (ElementAdopt("FR-old", "S", "B"),)))
    reference_op = PublicationOperation("reference_claims", "ref", encode_request("reference_claims", (
        ReferenceClaim("evidence.md", HASH, "E1", "FR-old", None, "reference"),)))
    for operations in [(reference_op, lifecycle_op), (lifecycle_op, lifecycle_op),
                       (lifecycle_op, replace(reference_op, operation_id="child")), "batch", [lifecycle_op]]:
        with pytest.raises(PublicationIntentError):
            PublicationIntentRequest(HASH, "recovery", operations)
    payload = encode_publication_request(PublicationIntentRequest(HASH, "recovery", (lifecycle_op,)))
    for corrupted in [payload.replace('"method":"lifecycle"', '"method":"lifecycle","method":"lifecycle"'),
                      payload.replace('"operation_id":"child"', '"operation_id":null'),
                      payload.replace('"operation_id":"child"', '"operation_id":false'),
                      payload.replace('"operation_id":"child"', '"operation_id":' + "9" * 5000)]:
        with pytest.raises(PublicationIntentError):
            decode_publication_request(corrupted)
    class DerivedOperation(PublicationOperation):
        pass
    with pytest.raises(PublicationIntentError):
        DerivedOperation("lifecycle", "child", lifecycle_op.payload)
    forged = object.__new__(PublicationOperation)
    request = request_for()
    object.__setattr__(request, "operations", (forged,))
    with pytest.raises(PublicationIntentError):
        encode_publication_request(request)


def test_exact_completed_lifecycle_and_binding_receipts_remain_available_while_pending(tmp_path):
    store, _, request = seed(tmp_path)
    original = []
    for operation in request.operations:
        method, keyword = {"lifecycle": (store.apply_lifecycle, "changes"),
                           "reference_claims": (store.record_reference_claims, "claims"),
                           "issue_occurrences": (store.record_issue_occurrences, "occurrences")}[operation.method]
        arguments = {"spec_id": "demo", "operation_id": operation.operation_id,
                     keyword: decode_request(operation.method, operation.payload)}
        original.append((method, arguments, method(**arguments)))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="executed"):
        store.prepare_identity_publication(spec_id="demo", operation_id="reject-executed", request=request)
    assert sql_state(tmp_path) == before
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request_for())
    for state in ("prepared", "applied"):
        if state == "applied":
            store.apply_identity_publication(spec_id="demo", operation_id="pub")
        before = sql_state(tmp_path)
        for method, arguments, receipt in original:
            assert method(**arguments) == receipt
        assert sql_state(tmp_path) == before


def test_publication_adoption_then_revision_with_5000_digit_baseline(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-007", "Legacy"),))
    adopted = request_for(("lifecycle", "adopt", (ElementAdopt("FR-007", "Legacy", "Original"),)))
    store.prepare_identity_publication(spec_id="demo", operation_id="adoption", request=adopted)
    store.apply_identity_publication(spec_id="demo", operation_id="adoption")
    store.release_identity_publication(spec_id="demo", operation_id="adoption", completion_payload="done")
    assert store.lookup(spec_id="demo", element_id="FR-007")["revision"] == "1"
    # A separate legacy authority exercises arbitrarily wide historical revision
    # strings without rewriting an already retained publication's plan.
    wide_path = tmp_path / "wide"
    wide_path.mkdir()
    wide = IdentityStore.initialize(wide_path)
    wide.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-007", "Legacy"),))
    wide.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(ElementAdopt("FR-007", "Legacy", "Original"),))
    huge = "9" * 5000
    with sqlite3.connect(wide_path / DATABASE) as connection:
        connection.execute("UPDATE revisions SET revision=?", (huge,))
        connection.execute("UPDATE lifecycle_heads SET revision=?", (huge,))
        receipt = json.dumps([{"element_id": "FR-007", "revision": huge, "status": "active", "lineage": []}], sort_keys=True, separators=(",", ":"))
        connection.execute("UPDATE lifecycle_receipts SET receipt=?,receipt_sha256=?", (receipt, hashlib.sha256(receipt.encode()).hexdigest()))
    revision = request_for(("lifecycle", "revise", (ElementRevision("FR-007", huge, "Legacy", "Next\r\nž"),)))
    wide.prepare_identity_publication(spec_id="demo", operation_id="pub", request=revision)
    application = wide.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert application["operations"][0]["receipt"][0]["revision"] == "1" + "0" * 5000
    wide.audit()


@pytest.mark.parametrize("damage", ["premature-operation", "orphan-receipt", "partial-application", "missing-child-after-release"])
def test_premature_partial_and_missing_child_history_is_never_recreated(tmp_path, damage):
    from harness import element_identity_publication_store as journal
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    if damage in {"partial-application", "missing-child-after-release"}:
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    if damage == "missing-child-after-release":
        store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        if damage == "premature-operation":
            claim = connection.execute("SELECT digest FROM publication_operation_claims WHERE operation_id='child-life'").fetchone()[0]
            connection.execute("INSERT INTO operations VALUES ('child-life','lifecycle','demo',?)", (claim,))
        elif damage == "orphan-receipt":
            connection.execute("INSERT INTO lifecycle_receipts VALUES ('child-life','[]',?)", (hashlib.sha256(b"[]").hexdigest(),))
        else:
            connection.execute("DELETE FROM operations WHERE operation_id='child-life'")
    before = sql_state(tmp_path)
    for action in [store.audit, lambda: store.apply_identity_publication(spec_id="demo", operation_id="pub"),
                   lambda: store.apply_lifecycle(spec_id="demo", operation_id="child-life", changes=decode_request("lifecycle", request.operations[0].payload))]:
        with pytest.raises(IdentityStoreError):
            action()
        assert sql_state(tmp_path) == before


def test_prepare_claim_insert_failure_rolls_back_parent_and_entire_intent(tmp_path):
    from harness import element_identity_publication_store as journal
    store, _, request = seed(tmp_path)
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        with store._transaction(write=True) as connection:
            connection.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                                      if action == sqlite3.SQLITE_INSERT and table == "publication_operation_claims" else sqlite3.SQLITE_OK)
            journal.prepare(connection, store, "demo", "pub", request)
    assert sql_state(tmp_path) == before
    assert store.pending_identity_publication(spec_id="demo") is None


def test_receipt_damage_is_detected_even_with_recomputed_local_hash(tmp_path):
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        receipt = '[{"element_id":"ISS-000001","lineage":[],"revision":"1","status":"active"},{"element_id":"ISS-000001","lineage":[],"revision":"1","status":"active"}]'
        connection.execute("UPDATE lifecycle_receipts SET receipt=?,receipt_sha256=?", (receipt, hashlib.sha256(receipt.encode()).hexdigest()))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="complete plan"):
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("field,value", [("content", "changed"), ("kind", "FR"), ("ordinal", "8")])
def test_applied_plan_cannot_disagree_with_exact_persisted_rows(tmp_path, field, value):
    store, _, request = seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    store.apply_identity_publication(spec_id="demo", operation_id="pub")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        encoded, request_json = connection.execute("SELECT plan,request FROM publication_intents").fetchone()
        plan = json.loads(encoded)
        plan["revisions"][0][{"content": 3, "kind": 6, "ordinal": 7}[field]] = value
        encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"))
        sha = hashlib.sha256(encoded.encode("ascii")).hexdigest()
        parent_digest = hashlib.sha256(json.dumps(["identity_publication", "demo", "pub", request_json, sha],
                                                 sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
        connection.execute("UPDATE publication_intents SET plan=?,plan_sha256=?", (encoded, sha))
        connection.execute("UPDATE operations SET digest=? WHERE operation_id='pub'", (parent_digest,))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("index", ["publication_pending_specs", "publication_claim_methods"])
def test_publication_required_indexes_are_exact_schema_authority(tmp_path, index):
    IdentityStore.initialize(tmp_path)
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute(f"DROP INDEX {index}")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.upgrade(tmp_path)
    assert sql_state(tmp_path) == before
