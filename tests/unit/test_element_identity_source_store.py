import pytest
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

from harness.element_identity_store import IdentityStore, IdentityStoreError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


DATABASE = ".echelon/identity/registry.sqlite3"
EMPTY = '{"files":[],"trees":[],"version":"1"}'
BASELINE = ('{"files":[],"publication":{"marker":{"manifest_sha256":"' + "a" * 64 +
            '","schema_version":"1","transaction_id":"11111111111111111111111111111111"},'
            '"operations":[]},"trees":[],"version":"1"}')


def empty_manifest():
    from harness.squad_source_manifest_codec import decode_source_manifest
    return decode_source_manifest(EMPTY)


def source_request(predecessor="reg", context="run", baseline=BASELINE, operations=()):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    return PublicationIntentRequest("a" * 64, "opaque recovery", operations,
                                    PublicationSourceClaim(context, predecessor, baseline))


def seed_empty(path):
    store = IdentityStore.initialize(path)
    registration = store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=empty_manifest())
    return store, registration


def state(path):
    with closing(sqlite3.connect(path / DATABASE)) as connection:
        return tuple(connection.iterdump())


def accepted(store, parent="pub", predecessor="reg"):
    request = source_request(predecessor)
    store.prepare_identity_publication(spec_id="demo", operation_id=parent, request=request)
    receipt = store.apply_identity_publication(spec_id="demo", operation_id=parent)
    store.release_identity_publication(spec_id="demo", operation_id=parent, completion_payload="done")
    return receipt


def test_registration_global_ownership_pending_guard_and_detached_reads(tmp_path):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    from harness.element_identity_request_codec import encode_request
    from harness.element_identity_lifecycle import ElementAdopt
    store, registration = seed_empty(tmp_path)
    assert store.source_context(spec_id="other", context_id="absent") is None
    for operation, context in [("different", "run"), ("reg", "other")]:
        before = state(tmp_path)
        with pytest.raises(IdentityStoreError):
            store.register_source_context(spec_id="demo", context_id=context, operation_id=operation, manifest=empty_manifest())
        assert state(tmp_path) == before
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-old", "Old"),))
    child = PublicationOperation("lifecycle", "claimed", encode_request("lifecycle", (ElementAdopt("FR-old", "Old", "Body"),)))
    request = PublicationIntentRequest("a" * 64, "opaque", (child,))
    store.prepare_identity_publication(spec_id="demo", operation_id="legacy", request=request)
    assert store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=empty_manifest()) == registration
    for operation in ("fresh", "claimed", "legacy", "import"):
        with pytest.raises(IdentityStoreError):
            store.register_source_context(spec_id="demo", context_id="second", operation_id=operation, manifest=empty_manifest())
    store.register_source_context(spec_id="other", context_id="run", operation_id="other-reg", manifest=empty_manifest())
    application = store.apply_identity_publication(spec_id="demo", operation_id="legacy")
    assert set(application) == {"version", "publication", "operations"} and application["version"] == "1"
    with pytest.raises(IdentityStoreError):
        store.register_source_context(spec_id="demo", context_id="second", operation_id="fresh", manifest=empty_manifest())
    store.release_identity_publication(spec_id="demo", operation_id="legacy", completion_payload="done")
    with pytest.raises(IdentityStoreError):
        store.register_source_context(spec_id="other", context_id="claimed", operation_id="claimed", manifest=empty_manifest())
    store.register_source_context(spec_id="demo", context_id="second", operation_id="fresh", manifest=empty_manifest())
    registration["manifest"]["payload"] = "mutated"
    assert store.source_context(spec_id="demo", context_id="run")["manifest"]["payload"] == EMPTY


@pytest.mark.parametrize("field", ["context_id", "expected_operation_id", "baseline_payload"])
@pytest.mark.parametrize("damage", [None, True, [], " ", "\ud800", "delete"])
def test_source_claim_revalidates_exact_frozen_fields(field, damage):
    from harness.element_identity_publication import PublicationSourceClaim, PublicationIntentError, encode_publication_request
    claim = PublicationSourceClaim("run", "reg", BASELINE)
    request = source_request()
    if damage == "delete":
        object.__delattr__(claim, field)
    else:
        object.__setattr__(claim, field, damage)
    object.__setattr__(request, "sources", claim)
    with pytest.raises(PublicationIntentError) as error:
        encode_publication_request(request)
    assert len(str(error.value)) < 100 and error.value.__suppress_context__


@pytest.mark.parametrize("damage", ["v1sources", "v2missing", "null", "extra", "numeric", "duplicate", "noncanonical", "marker", "deep", "unicode"])
def test_closed_version2_wire_rejects_malformed_shapes(damage):
    from harness.element_identity_publication import encode_publication_request, decode_publication_request, PublicationIntentError
    wire = encode_publication_request(source_request())
    value = json.loads(wire)
    if damage == "v1sources": value["version"] = "1"
    if damage == "v2missing": del value["sources"]
    if damage == "null": value["sources"] = None
    if damage == "extra": value["sources"]["after_sha256"] = "a" * 64
    if damage == "numeric": value["version"] = 2
    if damage == "noncanonical": value["sources"]["baseline_payload"] += " "
    if damage == "marker": value["manifest_sha256"] = "b" * 64
    wire = canonical(value)
    if damage == "duplicate": wire = wire[:-1] + ',"version":"2"}'
    if damage == "deep": wire = "[" * 5000 + "]" * 5000
    if damage == "unicode": wire = '"\ud800"'
    with pytest.raises(PublicationIntentError) as error:
        decode_publication_request(wire)
    assert len(str(error.value)) < 100 and error.value.__suppress_context__


def test_source_claim_preserves_baseexception(monkeypatch):
    import harness.squad_source_baseline_codec as codec
    from harness.element_identity_publication import PublicationSourceClaim
    def stop(_): raise KeyboardInterrupt()
    monkeypatch.setattr(codec, "decode_initial_publication_sources", stop)
    with pytest.raises(KeyboardInterrupt): PublicationSourceClaim("run", "reg", BASELINE)


@pytest.mark.parametrize("damage", [
    "DELETE FROM source_contexts",
    "UPDATE source_contexts SET registration_operation_id='missing'",
    "UPDATE operations SET digest='bad' WHERE operation_id='reg'",
    "UPDATE operations SET method='import' WHERE operation_id='reg'",
    "UPDATE source_contexts SET manifest_sha256='bad'",
    "DELETE FROM source_publications WHERE publication_id='pub2'",
    "UPDATE source_contexts SET head_publication_id=NULL",
    "UPDATE source_contexts SET head_publication_id='pub'",
    "UPDATE source_contexts SET head_publication_id='missing'",
    "UPDATE source_publications SET predecessor_operation_id='reg' WHERE publication_id='pub2'",
    "UPDATE source_publications SET sequence='9' WHERE publication_id='pub2'",
    "UPDATE source_publications SET context_id='wrong' WHERE publication_id='pub2'",
    "UPDATE source_publications SET spec_id='wrong' WHERE publication_id='pub2'",
    "UPDATE source_publications SET application_sha256=NULL WHERE publication_id='pub2'",
    "UPDATE source_publications SET application_sha256='bad' WHERE publication_id='pub2'",
    "UPDATE source_publications SET manifest_sha256='bad' WHERE publication_id='pub2'",
    "UPDATE publication_intents SET application_receipt_sha256='bad' WHERE operation_id='pub2'",
])
def test_damaged_source_authority_blocks_reads_retries_audit_backup_without_repair(tmp_path, damage):
    store, _ = seed_empty(tmp_path)
    accepted(store)
    accepted(store, "pub2", "pub")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute(damage)
    before = state(tmp_path)
    for action in (lambda: store.source_context(spec_id="demo", context_id="run"), store.audit,
                   lambda: store.identity_history(spec_id="demo"), lambda: store.backup(tmp_path / "bad-backup"),
                   lambda: store.apply_identity_publication(spec_id="demo", operation_id="pub2"),
                   lambda: store.prepare_identity_publication(spec_id="demo", operation_id="pub2", request=source_request("pub"))):
        with pytest.raises(IdentityStoreError): action()
        assert state(tmp_path) == before


def test_prepared_pointer_cross_context_and_premature_acceptance_block(tmp_path):
    store, _ = seed_empty(tmp_path)
    store.register_source_context(spec_id="demo", context_id="second", operation_id="reg2", manifest=empty_manifest())
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=source_request())
    for statement in ("UPDATE source_contexts SET head_publication_id='pub' WHERE context_id='run'",
                      "UPDATE source_contexts SET head_publication_id='pub' WHERE context_id='second'",
                      "UPDATE source_publications SET application_sha256='bad'"):
        with pytest.raises(IdentityStoreError):
            with store._transaction(write=True) as connection:
                connection.execute(statement)
                from harness import element_identity_source_store as sources
                sources.audit(connection, store)
    assert store.source_context(spec_id="demo", context_id="run")["sequence"] == "0"


def test_missing_context_orphan_registration_check_is_conservative_and_spec_bounded(tmp_path):
    store, _ = seed_empty(tmp_path)
    with sqlite3.connect(tmp_path / DATABASE) as connection: connection.execute("DELETE FROM source_contexts")
    for context in ("run", "unknown"):
        with pytest.raises(IdentityStoreError): store.source_context(spec_id="demo", context_id=context)
    assert store.source_context(spec_id="other", context_id="run") is None


def mixed_seed(path):
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence
    from harness.element_identity_publication import PublicationOperation
    from harness.element_identity_request_codec import encode_request
    store, registration = seed_empty(path)
    changes = []
    labels = []
    for kind in ("AC", "FR", "NFR", "ISS", "U", "A", "T"):
        label, = store.reserve(spec_id="demo", kind=kind, operation_id="reserve-" + kind, count=1)
        labels.append(label)
        changes.append(ElementCreate(label, kind + " subject", "Original\r\nž", "reserve-" + kind))
    operations = tuple(PublicationOperation(method, operation, encode_request(method, entries)) for method, operation, entries in (
        ("lifecycle", "life", tuple(changes)),
        ("reference_claims", "refs", (ReferenceClaim("evidence.md", "b" * 64, "anchor", "FR-000001", "1", "reference"),)),
        ("issue_occurrences", "issues", (IssueOccurrence("ISS-000001", "1", "report", "b" * 64, "ISS-display", "ISS subject", "Original\r\nž"),)),
    ))
    return store, registration, source_request(operations=operations), labels


def test_all_seven_family_mixed_application_retains_old_revision_evidence(tmp_path):
    from harness.element_identity_lifecycle import ElementRevision
    from harness.element_identity_request_codec import decode_request
    store, registration, request, labels = mixed_seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert all(store.lookup(spec_id="demo", element_id=label) is None for label in labels)
    receipt = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert [entry["element_id"] for entry in receipt["operations"][0]["receipt"]] == labels
    assert receipt["sources"] == {**registration, "operation_id": "pub", "sequence": "1"}
    for action in (
        lambda: store.reserve(spec_id="demo", kind="FR", operation_id="new-reserve", count=1),
        lambda: store.import_identities(spec_id="demo", operation_id="new-import", definitions=(("FR-old", "Old"),)),
        lambda: store.apply_lifecycle(spec_id="demo", operation_id="new-life", changes=(ElementRevision("FR-000001", "1", "FR subject", "New"),)),
        lambda: store.register_source_context(spec_id="demo", context_id="other", operation_id="new-reg", manifest=empty_manifest()),
        lambda: store.record_reference_claims(spec_id="demo", operation_id="new-refs", claims=decode_request("reference_claims", request.operations[1].payload)),
        lambda: store.record_issue_occurrences(spec_id="demo", operation_id="new-issues", occurrences=decode_request("issue_occurrences", request.operations[2].payload)),
    ):
        with pytest.raises(IdentityStoreError): action()
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    store.apply_lifecycle(spec_id="demo", operation_id="new-life", changes=(ElementRevision("FR-000001", "1", "FR subject", "New"),))
    assert store.read_revision(spec_id="demo", element_id="FR-000001", revision="1")["content"] == "Original\r\nž"
    assert store.reference_claims(spec_id="demo", source_path="evidence.md", source_sha256="b" * 64)[0]["target_revision_matches_current"] is False
    assert store.issue_occurrences(spec_id="demo", issue_id="ISS-000001")[0]["body"] == "Original\r\nž"
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == receipt
    assert store.audit()["table_counts"]["source_publications"] == "1"


@pytest.mark.parametrize("stage", ["plan", "child", "head", "acceptance", "receipt", "commit"])
def test_source_and_child_sql_failures_rollback_as_one_transaction(tmp_path, stage):
    from harness import element_identity_publication_store as journal
    store, registration, request, labels = mixed_seed(tmp_path)
    if stage != "plan": store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    before = state(tmp_path)
    with pytest.raises((IdentityStoreError, sqlite3.DatabaseError)):
        with store._transaction(write=True) as connection:
            def deny(action, target, column, *_):
                denied = {
                    "plan": (sqlite3.SQLITE_INSERT, "source_publications", None),
                    "child": (sqlite3.SQLITE_INSERT, "reference_claims", None),
                    "head": (sqlite3.SQLITE_UPDATE, "source_contexts", "head_publication_id"),
                    "acceptance": (sqlite3.SQLITE_UPDATE, "source_publications", "application_sha256"),
                    "receipt": (sqlite3.SQLITE_UPDATE, "publication_intents", "application_receipt"),
                    "commit": (sqlite3.SQLITE_TRANSACTION, "COMMIT", None),
                }[stage]
                return sqlite3.SQLITE_DENY if (action, target, column) == denied else sqlite3.SQLITE_OK
            connection.set_authorizer(deny)
            if stage == "plan": journal.prepare(connection, store, "demo", "pub", request)
            else: journal.apply(connection, store, "demo", "pub")
    assert state(tmp_path) == before
    store = IdentityStore.open(tmp_path)
    assert store.source_context(spec_id="demo", context_id="run") == registration
    assert all(store.lookup(spec_id="demo", element_id=label) is None for label in labels)
    assert (store.pending_identity_publication(spec_id="demo") is None) == (stage == "plan")
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["sources"]["sequence"] == "1"


def test_uncertain_outcome_after_actual_commit_recovers_coherent_original_receipt(tmp_path, monkeypatch):
    import harness.element_identity_store as authority
    store, registration, request, labels = mixed_seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    original = authority._database
    class ReportAfterCommit:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise sqlite3.OperationalError("uncertain outcome after actual COMMIT")
    @contextmanager
    def database(*args, **kwargs):
        with original(*args, **kwargs) as connection: yield ReportAfterCommit(connection)
    with monkeypatch.context() as patch:
        patch.setattr(authority, "_database", database)
        with pytest.raises(IdentityStoreError, match="uncertain outcome"):
            store.apply_identity_publication(spec_id="demo", operation_id="pub")
    store = IdentityStore.open(tmp_path)
    before = state(tmp_path)
    retained = json.loads(store.identity_publication(spec_id="demo", operation_id="pub")["application_receipt"])
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == retained
    assert store.source_context(spec_id="demo", context_id="run") == retained["sources"]
    assert retained["sources"] == {**registration, "sequence": "1", "operation_id": "pub"}
    assert all(store.lookup(spec_id="demo", element_id=label)["revision"] == "1" for label in labels)
    assert state(tmp_path) == before


def competing_prepare(path, parent, ready, go, results):
    store = IdentityStore.open(Path(path))
    ready.put(parent)
    go.wait(20)
    try:
        store.prepare_identity_publication(spec_id="demo", operation_id=parent, request=source_request())
        store.apply_identity_publication(spec_id="demo", operation_id=parent)
        store.release_identity_publication(spec_id="demo", operation_id=parent, completion_payload="done")
        results.put(("accepted", parent))
    except IdentityStoreError: results.put(("rejected", parent))


def test_separate_process_source_cas_has_one_winner(tmp_path):
    import multiprocessing
    store, _ = seed_empty(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready, results, go = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=competing_prepare, args=(str(tmp_path), parent, ready, go, results)) for parent in ("left", "right")]
    for process in processes: process.start()
    try:
        assert {ready.get(timeout=20), ready.get(timeout=20)} == {"left", "right"}
        go.set()
        outcomes = [results.get(timeout=20), results.get(timeout=20)]
        assert sorted(status for status, _ in outcomes) == ["accepted", "rejected"]
        winner = next(parent for status, parent in outcomes if status == "accepted")
        assert store.source_context(spec_id="demo", context_id="run")["operation_id"] == winner
        assert store.audit()["table_counts"]["source_publications"] == "1"
    finally:
        for process in processes:
            process.join(20)
            if process.is_alive(): process.terminate(); process.join()
        for queue in (ready, results): queue.close(); queue.join_thread()


@pytest.mark.parametrize("selection", ["empty", "different", "other-predecessor"])
def test_registered_selection_and_context_predecessor_cannot_be_substituted(tmp_path, selection):
    from harness.squad_source_manifest_codec import decode_source_manifest
    store = IdentityStore.initialize(tmp_path)
    manifest = decode_source_manifest('{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},"path":"dependency"}],"trees":[],"version":"1"}')
    store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=manifest)
    store.register_source_context(spec_id="demo", context_id="other", operation_id="other-reg", manifest=empty_manifest())
    baseline = json.loads(BASELINE)
    if selection != "empty":
        baseline["files"] = [{"path": "different" if selection == "different" else "dependency", "image": {"kind": "missing", "mode": None, "sha256": None, "content_base64": None}}]
    request = source_request("other-reg" if selection == "other-predecessor" else "reg", baseline=canonical(baseline))
    with pytest.raises(IdentityStoreError): store.prepare_identity_publication(spec_id="demo", operation_id="bad", request=request)
    # A self-consistent explicit claim for the other context is an allowed caller selection.
    store.prepare_identity_publication(spec_id="demo", operation_id="allowed", request=source_request("other-reg", "other"))
    assert store.apply_identity_publication(spec_id="demo", operation_id="allowed")["sources"]["context_id"] == "other"


V4_PUBLICATION_DDL = """
CREATE TABLE publication_intents (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), spec_id TEXT NOT NULL, request TEXT NOT NULL, request_sha256 TEXT NOT NULL, plan TEXT NOT NULL, plan_sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('prepared','applied','released')), application_receipt TEXT, application_receipt_sha256 TEXT, completion_payload TEXT, completion_payload_sha256 TEXT, CHECK ((state='prepared' AND application_receipt IS NULL AND application_receipt_sha256 IS NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) OR (state='applied' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) OR (state='released' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NOT NULL AND completion_payload_sha256 IS NOT NULL))) WITHOUT ROWID;
CREATE UNIQUE INDEX publication_pending_specs ON publication_intents (spec_id) WHERE state!='released';
CREATE TABLE publication_operation_claims (operation_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publication_intents(operation_id), method TEXT NOT NULL CHECK (method IN ('lifecycle','reference_claims','issue_occurrences')), digest TEXT NOT NULL) WITHOUT ROWID;
CREATE UNIQUE INDEX publication_claim_methods ON publication_operation_claims (publication_id, method);
"""


def freeze_v4(path):
    ddl = (Path(__file__).parents[1] / "fixtures/element_identity/authority-v3.sql").read_text() + V4_PUBLICATION_DDL
    with closing(sqlite3.connect(path / DATABASE)) as source, closing(sqlite3.connect(":memory:")) as target:
        target.executescript(ddl)
        for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if table == "metadata": rows = [(key, "4" if key == "schema_version" else value) for key, value in rows]
            if rows: target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
        target.execute("PRAGMA user_version=1")
        target.commit()
        target.backup(source)


def backup_manifest(directory):
    (directory / "manifest.json").write_text(canonical({"version": 1, "completed": True,
        "authority": json.loads((directory / "authority.json").read_text()),
        "database_sha256": hashlib.sha256((directory / "registry.sqlite3").read_bytes()).hexdigest()}))


@pytest.mark.parametrize("phase", ["prepared", "applied", "released"])
def test_frozen_schema4_upgrade_restore_preserve_original_journal_bytes(tmp_path, phase):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence
    from harness.element_identity_request_codec import encode_request
    from harness import element_identity_publication_store as journal
    source = tmp_path / "source"
    source.mkdir()
    store = IdentityStore.initialize(source)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1)
    operations = tuple(PublicationOperation(method, operation, encode_request(method, entries)) for method, operation, entries in (
        ("lifecycle", "life", (ElementCreate(label, "Issue", "Body", "reserve"),)),
        ("reference_claims", "refs", (ReferenceClaim("evidence.md", "b" * 64, "anchor", label, "1", "reference"),)),
        ("issue_occurrences", "issues", (IssueOccurrence(label, "1", "report", "b" * 64, "ISS-display", "Issue", "Body"),)),
    ))
    request = PublicationIntentRequest("a" * 64, "opaque\r\nrecovery", operations)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="legacy", request=request)
    if phase != "prepared": application = store.apply_identity_publication(spec_id="demo", operation_id="legacy")
    if phase == "released": release = store.release_identity_publication(spec_id="demo", operation_id="legacy", completion_payload="done")
    record = store.identity_publication(spec_id="demo", operation_id="legacy")
    freeze_v4(source)
    original = state(source)
    directory = source / ".echelon/identity"
    marker = (directory / "authority.json").read_bytes()
    with pytest.raises(IdentityStoreError, match="upgrade"): IdentityStore.open(source)
    with pytest.raises(IdentityStoreError, match="upgrade"): store.reserve(spec_id="demo", kind="FR", operation_id="no", count=1)
    with closing(sqlite3.connect(source / DATABASE)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        statements = []
        connection.set_trace_callback(statements.append)
        journal.audit(connection, IdentityStore, source_state=False)
        assert not any("source_contexts" in statement or "source_publications" in statement for statement in statements)
    backup_manifest(directory)
    restored_path = tmp_path / "restored"
    restored_path.mkdir()
    restored = IdentityStore.restore(restored_path, directory)
    assert state(source) == original
    upgraded = IdentityStore.upgrade(source)
    assert (directory / "authority.json").read_bytes() == marker
    for candidate in (upgraded, restored):
        assert candidate.identity_publication(spec_id="demo", operation_id="legacy") == record
        assert candidate.prepare_identity_publication(spec_id="demo", operation_id="legacy", request=request) == preparation
        if phase != "prepared": assert candidate.apply_identity_publication(spec_id="demo", operation_id="legacy") == application
        if phase == "released": assert candidate.release_identity_publication(spec_id="demo", operation_id="legacy", completion_payload="done") == release
        assert (candidate.pending_identity_publication(spec_id="demo") is None) == (phase == "released")
        assert candidate.audit()["database_schema_version"] == "5"


def test_frozen_schema4_rejects_version2_without_reading_source_tables(tmp_path):
    from harness.element_identity_publication import PublicationIntentRequest, encode_publication_request
    from harness import element_identity_publication_store as journal
    store = IdentityStore.initialize(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=PublicationIntentRequest("a" * 64, "opaque"))
    freeze_v4(tmp_path)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.execute("UPDATE publication_intents SET request=?", (encode_publication_request(source_request()),))
        connection.commit()
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        statements = []
        connection.set_trace_callback(statements.append)
        with pytest.raises(IdentityStoreError, match="unsupported"):
            journal.audit(connection, IdentityStore, source_state=False)
        assert not any("source_contexts" in statement or "source_publications" in statement for statement in statements)
    with pytest.raises(IdentityStoreError): IdentityStore.upgrade(tmp_path)


def test_backup_restore_source_heads_and_recomputed_local_damage(tmp_path):
    store, registration = seed_empty(tmp_path)
    receipt = accepted(store)
    backup = tmp_path / "backup"
    store.backup(backup)
    destination = tmp_path / "restored"
    destination.mkdir()
    restored = IdentityStore.restore(destination, backup)
    assert restored.source_context(spec_id="demo", context_id="run") == receipt["sources"]
    assert restored.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=empty_manifest()) == registration
    # Recompute local hashes and application bytes: retained parent baseline/projection still binds the source row.
    altered = '{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},"path":"substituted"}],"trees":[],"version":"1"}'
    altered_hash = hashlib.sha256(altered.encode("ascii")).hexdigest()
    receipt["sources"]["manifest"] = {"payload": altered, "sha256": altered_hash}
    payload = canonical(receipt)
    digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
    with sqlite3.connect(backup / "registry.sqlite3") as connection:
        connection.execute("UPDATE source_publications SET manifest=?,manifest_sha256=?,application_sha256=?", (altered, altered_hash, digest))
        connection.execute("UPDATE publication_intents SET application_receipt=?,application_receipt_sha256=?", (payload, digest))
    backup_manifest(backup)
    rejected = tmp_path / "rejected"
    rejected.mkdir()
    with pytest.raises(IdentityStoreError): IdentityStore.restore(rejected, backup)
    assert not (rejected / ".echelon").exists()


@pytest.mark.parametrize("method", ["register", "read", "prepare", "validate_plan", "accept", "audit"])
def test_source_helpers_require_an_active_caller_transaction(tmp_path, method):
    from harness import element_identity_source_store as sources
    store = IdentityStore.initialize(tmp_path)
    arguments = {"register": ("demo", "run", "reg", empty_manifest()), "read": ("demo", "run"),
        "prepare": ("demo", "pub", source_request()), "validate_plan": ("demo", "pub", source_request()),
        "accept": ("demo", "pub", source_request(), {}), "audit": ()}[method]
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        with pytest.raises(IdentityStoreError, match="transaction"): getattr(sources, method)(connection, store, *arguments)
        assert not connection.in_transaction


def test_source_read_uses_one_query_only_transaction_and_indexed_head(tmp_path, monkeypatch):
    from harness import element_identity_source_store as sources
    store, _ = seed_empty(tmp_path)
    accepted(store)
    accepted(store, "pub2", "pub")
    original = store._transaction
    observations, statements = [], []
    @contextmanager
    def transaction(*, write=False):
        observations.append(write)
        with original(write=write) as connection:
            connection.set_trace_callback(statements.append)
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    with monkeypatch.context() as patch:
        patch.setattr(store, "_transaction", transaction)
        for _ in range(3): assert store.source_context(spec_id="demo", context_id="run")["sequence"] == "2"
    assert observations == [False, False, False]
    assert not any(s.upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    with store._transaction() as connection:
        queries = [(sources._HEAD, ("demo", "run"), "source_publication_heads"),
            ("SELECT * FROM source_contexts WHERE spec_id=? AND context_id=?", ("demo", "run"), "PRIMARY KEY"),
            ("SELECT * FROM source_publications WHERE publication_id=?", ("pub2",), "PRIMARY KEY"),
            ("SELECT * FROM publication_intents WHERE operation_id=?", ("pub2",), "PRIMARY KEY"),
            ("SELECT operation_id FROM operations WHERE method='source_context' AND spec_id=?", ("demo",), "source_registration_specs")]
        for query, parameters, index in queries:
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, parameters))
            assert "SEARCH" in plan and index in plan and "SCAN" not in plan and "TEMP B-TREE" not in plan


def test_unbounded_source_sequence_arithmetic_and_numeric_head_index(tmp_path):
    from harness import element_identity_store as authority, element_identity_source_store as sources
    # Synthetic numeric boundary only; this does not claim thousands of accepted publications.
    huge = "9" * 5000
    following = authority._decimal(authority._integer(huge) + 1)
    assert following == "1" + "0" * 5000
    store, _ = seed_empty(tmp_path)
    accepted(store)
    accepted(store, "pub2", "pub")
    with store._transaction(write=True) as connection:
        connection.execute("UPDATE source_publications SET sequence=? WHERE publication_id='pub'", (huge,))
        connection.execute("UPDATE source_publications SET sequence=? WHERE publication_id='pub2'", (following,))
        assert connection.execute(sources._HEAD, ("demo", "run")).fetchone()["publication_id"] == "pub2"
        with pytest.raises(IdentityStoreError): sources.read(connection, store, "demo", "run")


def real_change(project):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/empty").mkdir(parents=True)
    (project / "specs").chmod(0o750)
    (project / "specs/empty").chmod(0o700)
    (project / "specs/.binary").write_bytes(b"FR-1000000\r\n\x00\xff")
    (project / "specs/a").write_bytes(b"before\r\n")
    (project / "specs/delete").write_bytes(b"deleted")
    (project / "specs/noop").write_bytes(b"same")
    (project / "dependency").write_bytes(b"rules")
    transaction = SquadPublicationTransaction.begin(project, squad, "8" * 32)
    stages = []
    for index, (target, data) in enumerate((("specs/a", b"after\r\n\x00\xff"), ("specs/nested/value", b"new"), ("specs/noop", b"same"))):
        stage = transaction.build_path(str(index))
        stage.write_bytes(data)
        stage.chmod(0o640)
        transaction.add_write(Path(target), stage, owned_paths={Path(target)})
        stages.append(stage)
    transaction.add_delete(Path("specs/delete"), owned_paths={Path("specs/delete")})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent", "dependency")) as initial:
        baseline = encode_initial_publication_sources(initial)
    manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(project)
    registration = store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=manifest)
    request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "opaque retained recovery", sources=PublicationSourceClaim("run", "reg", baseline))
    return store, registration, prepared, initial, request, stages


def test_real_prefix_interruption_reloads_retained_original_and_accepts_final_sources(tmp_path, secure_posix):
    from harness.squad_publication import PublicationError, load_prepared_publication
    from harness.element_identity_publication import decode_publication_request
    from harness.squad_source_baseline_codec import decode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    store, registration, prepared, initial, request, stages = real_change(project)
    def before(_): store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    def after(_): store.apply_identity_publication(spec_id="demo", operation_id="pub")
    def stop(position):
        if position == 1: raise RuntimeError("interrupted real prefix")
    with pytest.raises(PublicationError): prepared.publish_sources(initial, before_publish=before, after_publish=after, fault_hook=stop)
    assert (project / "specs/a").read_bytes() == b"after\r\n\x00\xff"
    assert (project / "specs/delete").read_bytes() == b"deleted"
    assert all(stage.exists() for stage in stages)
    assert store.source_context(spec_id="demo", context_id="run") == registration
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    retained = decode_publication_request(store.identity_publication(spec_id="demo", operation_id="pub")["request"])
    original = decode_initial_publication_sources(retained.sources.baseline_payload)
    assert next(file.content for file in original.trees[0].files if file.path == "specs/a") == b"before\r\n"
    loaded = load_prepared_publication(project, prepared._squad_dir, prepared.marker)
    final = loaded.publish_sources(original, before_publish=before, after_publish=after)
    head = store.source_context(spec_id="demo", context_id="run")
    final_manifest = snapshot_source_manifest(trees=final.trees, files=final.files)
    assert head["manifest"] == {"payload": final_manifest.payload, "sha256": final_manifest.sha256}
    assert head["sequence"] == "1" and head["operation_id"] == "pub"
    assert (project / "specs/nested/value").read_bytes() == b"new"
    assert (project / "specs/noop").read_bytes() == b"same"
    assert (project / "specs/.binary").read_bytes() == b"FR-1000000\r\n\x00\xff"
    assert not (project / "specs/delete").exists()
    for path in ("specs/a", "specs/nested/value", "specs/noop"):
        assert (project / path).stat().st_mode & 0o777 == 0o640
    assert (project / "specs/empty").is_dir() and (project / "specs/empty").stat().st_mode & 0o777 == 0o700
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    assert all(stage.exists() for stage in stages)
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="owner explicitly complete")
    assert store.pending_identity_publication(spec_id="demo") is None


def test_real_source_drift_never_prepares_and_after_callback_failure_retains_guard(tmp_path, secure_posix):
    from harness.squad_publication import PublicationError
    project = tmp_path.resolve()
    store, registration, prepared, initial, request, stages = real_change(project)
    def before(_): store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    (project / "dependency").write_bytes(b"changed")
    with pytest.raises(PublicationError, match="target_drift"): prepared.publish_sources(initial, before_publish=before)
    assert store.identity_publication(spec_id="demo", operation_id="pub") is None
    assert store.source_context(spec_id="demo", context_id="run") == registration
    (project / "dependency").write_bytes(b"rules")
    def after(_):
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
        raise RuntimeError("owner callback stopped after acceptance")
    with pytest.raises(RuntimeError, match="owner callback"):
        prepared.publish_sources(initial, before_publish=before, after_publish=after)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    assert all(stage.exists() for stage in stages)
    assert store.source_context(spec_id="demo", context_id="run")["sequence"] == "1"


def test_source_store_and_codecs_do_not_open_current_files(tmp_path, monkeypatch):
    import builtins
    from harness import element_identity_source_store as sources, element_identity_publication_store as journal
    store, _ = seed_empty(tmp_path)
    with store._transaction(write=True) as connection:
        statements = []
        connection.set_trace_callback(statements.append)
        def forbidden(*args, **kwargs): raise AssertionError("source helpers must not read files")
        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", forbidden)
            patch.setattr(Path, "open", forbidden)
            journal.prepare(connection, store, "demo", "pub", source_request())
            journal.apply(connection, store, "demo", "pub")
            sources.read(connection, store, "demo", "run")
            sources.audit(connection, store)
            journal.release(connection, store, "demo", "pub", "done")
        assert connection.in_transaction
        assert not any(s.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK")) or
                       (s.upper().startswith("PRAGMA") and "=" in s) for s in statements)


def test_source_plan_helper_rejects_an_altered_parent_request(tmp_path):
    from harness import element_identity_source_store as sources
    store, _ = seed_empty(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=source_request())
    changed = replace(source_request(), recovery_payload="different retained parent")
    with store._transaction() as connection:
        with pytest.raises(IdentityStoreError): sources.validate_plan(connection, store, "demo", "pub", changed)


@pytest.mark.parametrize("phase", ["prepared", "applied", "released"])
def test_missing_parent_and_operation_with_retained_source_row_never_returns_absent(tmp_path, phase):
    store, _ = seed_empty(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=source_request())
    if phase != "prepared": store.apply_identity_publication(spec_id="demo", operation_id="pub")
    if phase == "released": store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute("DELETE FROM publication_intents WHERE operation_id='pub'")
        connection.execute("DELETE FROM operations WHERE operation_id='pub'")
    before = state(tmp_path)
    actions = [lambda: store.identity_publication(spec_id="demo", operation_id="pub"),
               lambda: store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=source_request()),
               store.audit]
    if phase != "prepared": actions.append(lambda: store.source_context(spec_id="demo", context_id="run"))
    for action in actions:
        with pytest.raises(IdentityStoreError): action()
        assert state(tmp_path) == before


@pytest.mark.parametrize("damage", ["source-less-request", "extra-key", "wrong-publication", "wrong-child-receipts"])
def test_source_acceptance_helper_revalidates_complete_application_before_writes(tmp_path, damage):
    from harness import element_identity_source_store as sources
    from harness.element_identity_publication import PublicationIntentRequest
    store, registration = seed_empty(tmp_path)
    request = source_request()
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    application = {"version": "2", "publication": preparation, "operations": [],
                   "sources": {**registration, "operation_id": "pub", "sequence": "1"}}
    if damage == "source-less-request": request = PublicationIntentRequest("a" * 64, "opaque recovery")
    if damage == "extra-key": application["unexpected"] = "value"
    if damage == "wrong-publication": application["publication"] = {**preparation, "operation_id": "other"}
    if damage == "wrong-child-receipts": application["operations"] = [{"method": "lifecycle", "operation_id": "invented", "receipt": []}]
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        with store._transaction(write=True) as connection:
            sources.accept(connection, store, "demo", "pub", request, application)
    assert state(tmp_path) == before


def test_mixed_source_head_read_never_scans_historical_child_tables(tmp_path):
    from harness import element_identity_source_store as sources
    store, _, request, _ = mixed_seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    historical = {"entities", "revisions", "lifecycle_lineage", "lifecycle_receipts", "lifecycle_heads",
                  "reference_claims", "issue_occurrences", "binding_receipts", "reservations", "counters"}
    with store._transaction() as connection:
        def deny_history(action, table, *_):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table in historical else sqlite3.SQLITE_OK
        connection.set_authorizer(deny_history)
        for _ in range(3): assert sources.read(connection, store, "demo", "run") == application["sources"]
        for query, parameters in ((sources._HEAD, ("demo", "run")),
                                 ("SELECT * FROM publication_intents WHERE operation_id=?", ("pub",)),
                                 ("SELECT operation_id,publication_id,method,digest FROM publication_operation_claims WHERE publication_id=?", ("pub",))):
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, parameters))
            assert "SEARCH" in plan and "SCAN" not in plan and "TEMP B-TREE" not in plan


@pytest.mark.parametrize("damage", ["preparation", "operations", "completion", "plan"])
def test_source_head_structural_parent_checks_survive_recomputed_local_hashes(tmp_path, damage):
    store, _ = seed_empty(tmp_path)
    application = accepted(store)
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        if damage in {"preparation", "operations"}:
            if damage == "preparation": application["publication"]["operation_id"] = "other"
            else: application["operations"] = [{"method": "lifecycle", "operation_id": "other", "receipt": []}]
            encoded = canonical(application)
            digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
            connection.execute("UPDATE publication_intents SET application_receipt=?,application_receipt_sha256=?", (encoded, digest))
            connection.execute("UPDATE source_publications SET application_sha256=?", (digest,))
        elif damage == "completion": connection.execute("UPDATE publication_intents SET completion_payload_sha256='bad'")
        else:
            from harness.element_identity_store import _digest
            plan = '{}'
            plan_hash = hashlib.sha256(plan.encode("ascii")).hexdigest()
            request = connection.execute("SELECT request FROM publication_intents").fetchone()[0]
            connection.execute("UPDATE publication_intents SET plan=?,plan_sha256=?", (plan, plan_hash))
            connection.execute("UPDATE operations SET digest=? WHERE operation_id='pub'", (_digest(["identity_publication", "demo", "pub", request, plan_hash]),))
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError): store.source_context(spec_id="demo", context_id="run")
    assert state(tmp_path) == before


def capture(project, transaction_id="6" * 32):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True, exist_ok=True)
    prepared = SquadPublicationTransaction.begin(project, squad, transaction_id).seal()
    with prepared.inspect_sources(tree_paths=(), file_paths=("absent",)) as initial:
        baseline = encode_initial_publication_sources(initial)
    return prepared, initial, baseline, snapshot_source_manifest(trees=initial.trees, files=initial.files)


def test_source_only_version2_receipts_and_original_retries_after_later_heads(tmp_path, secure_posix):
    from harness.element_identity_publication import (
        PublicationIntentRequest, PublicationSourceClaim, encode_publication_request, decode_publication_request,
    )
    _, initial, baseline, manifest = capture(tmp_path.resolve())
    store = IdentityStore.initialize(tmp_path)
    registration = store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=manifest)
    expected_registration = {"version": "1", "workspace_uuid": store._marker["workspace_uuid"],
        "epoch_uuid": store._marker["epoch_uuid"], "spec_id": "demo", "context_id": "run",
        "registration_operation_id": "reg", "operation_id": "reg", "sequence": "0",
        "manifest": {"payload": '{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},"path":"absent"}],"trees":[],"version":"1"}',
                     "sha256": hashlib.sha256(manifest.payload.encode("ascii")).hexdigest()}}
    assert registration == expected_registration
    history = store.identity_history(spec_id="demo")
    receipts = []
    predecessor = "reg"
    for index, parent in enumerate(("pub1", "pub2", "pub3"), 1):
        claim = PublicationSourceClaim("run", predecessor, baseline)
        request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "opaque recovery", sources=claim)
        expected_wire = canonical({"version": "2", "manifest_sha256": initial.publication.marker.manifest_sha256,
            "recovery_payload": "opaque recovery", "operations": [],
            "sources": {"context_id": "run", "expected_operation_id": predecessor, "baseline_payload": baseline}})
        assert encode_publication_request(request) == expected_wire
        assert decode_publication_request(expected_wire) == request
        preparation = store.prepare_identity_publication(spec_id="demo", operation_id=parent, request=request)
        assert store.source_context(spec_id="demo", context_id="run")["operation_id"] == predecessor
        application = store.apply_identity_publication(spec_id="demo", operation_id=parent)
        expected_head = {**expected_registration, "operation_id": parent, "sequence": str(index)}
        assert application == {"version": "2", "publication": preparation, "operations": [], "sources": expected_head}
        assert store.source_context(spec_id="demo", context_id="run") == expected_head
        release = store.release_identity_publication(spec_id="demo", operation_id=parent, completion_payload="done")
        assert release == {"version": "1", "publication": preparation,
            "application_sha256": hashlib.sha256(canonical(application).encode("ascii")).hexdigest(),
            "completion_sha256": hashlib.sha256(b"done").hexdigest()}
        receipts.append((parent, request, preparation, application, release))
        predecessor = parent
    store = IdentityStore.open(tmp_path)
    assert store.identity_history(spec_id="demo") == history
    assert store.register_source_context(spec_id="demo", context_id="run", operation_id="reg", manifest=manifest) == registration
    for parent, request, preparation, application, release in receipts:
        assert store.prepare_identity_publication(spec_id="demo", operation_id=parent, request=request) == preparation
        assert store.apply_identity_publication(spec_id="demo", operation_id=parent) == application
        assert store.release_identity_publication(spec_id="demo", operation_id=parent, completion_payload="done") == release
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="stale", request=receipts[0][1])
    assert store.audit()["table_counts"]["source_publications"] == "3"


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available
    if not _secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_real_source_context_registration_retains_original_manifest(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/notes.md").write_bytes(b"FR-1000000\r\n\x00\xff")
    prepared = SquadPublicationTransaction.begin(project, squad, "5" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as initial:
        assert initial.trees[0].files[0].content == b"FR-1000000\r\n\x00\xff"
    manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(project)
    receipt = store.register_source_context(
        spec_id="demo", context_id="run-source", operation_id="source-registration",
        manifest=manifest,
    )
    assert receipt["sequence"] == "0"
    assert receipt["manifest"] == {"payload": manifest.payload, "sha256": manifest.sha256}
    assert IdentityStore.open(project).source_context(spec_id="demo", context_id="run-source") == receipt
