import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.element_identity_lifecycle import ElementAdopt, ElementCreate, ElementRevision
from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence
from harness.element_identity_publication import (
    PublicationIntentRequest, PublicationOperation, PublicationIntentError,
    encode_publication_request, decode_publication_request,
)
from harness.element_identity_request_codec import encode_request
from tests.unit.test_element_identity_source_store import (
    BASELINE, DATABASE, canonical, state, seed_empty, source_request, mixed_seed,
)


pytestmark = pytest.mark.unit
HASH = "a" * 64


def digest(payload):
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def op(method, operation_id, *entries):
    return PublicationOperation(method, operation_id, encode_request(method, entries))


def bind(store, request):
    proposed = store.preview_identity_history(spec_id="demo", operations=request.operations)
    return replace(request, proposed_history_sha256=proposed.sha256), proposed


def test_history_bound_publication_retains_exact_snapshot(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_publication import PublicationOperation, PublicationIntentRequest
    from harness.element_identity_request_codec import encode_request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    changes = (ElementCreate(label, "Scene", "Initial scene", "reserve"),)
    operation = PublicationOperation("lifecycle", "create", encode_request("lifecycle", changes))
    proposed = store.preview_identity_history(spec_id="demo", operations=(operation,))
    request = PublicationIntentRequest("a" * 64, "test recovery", (operation,),
                                       proposed_history_sha256=proposed.sha256)
    store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=request)
    receipt = store.apply_identity_publication(spec_id="demo", operation_id="publication")
    assert receipt["version"] == "3"
    assert receipt["identity_history_sha256"] == proposed.sha256
    assert store.identity_history(spec_id="demo") == proposed


@pytest.mark.parametrize("sources,history,version", [(False, False, "1"), (True, False, "2"), (False, True, "3"), (True, True, "3")])
def test_literal_wire_and_complete_empty_receipt_compatibility(tmp_path, sources, history, version):
    store, registration = seed_empty(tmp_path)
    proposed = store.preview_identity_history(spec_id="demo")
    request = source_request() if sources else PublicationIntentRequest(HASH, "opaque recovery")
    if history:
        request = replace(request, proposed_history_sha256=proposed.sha256)
    # These are independent closed wire expectations, not an encoder roundtrip.
    expected = {"version": version, "manifest_sha256": HASH, "recovery_payload": "opaque recovery", "operations": []}
    if sources:
        expected["sources"] = {"context_id": "run", "expected_operation_id": "reg", "baseline_payload": BASELINE}
    if history:
        expected["proposed_history_sha256"] = proposed.sha256
    wire = canonical(expected)
    assert encode_publication_request(request) == wire
    assert decode_publication_request(wire) == request
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    expected_preparation = {"version": "1", "workspace_uuid": registration["workspace_uuid"],
        "epoch_uuid": registration["epoch_uuid"], "spec_id": "demo", "operation_id": "pub",
        "request_sha256": digest(wire), "plan_sha256": digest('{"lineage":[],"revisions":[]}')}
    assert preparation == expected_preparation
    receipt = {"version": version, "publication": expected_preparation, "operations": []}
    if sources:
        receipt["sources"] = {**registration, "operation_id": "pub", "sequence": "1"}
    if history:
        receipt["identity_history_sha256"] = proposed.sha256
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == receipt
    assert store.identity_history(spec_id="demo") == proposed
    assert store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done") == {
        "version": "1", "publication": preparation, "application_sha256": digest(canonical(receipt)),
        "completion_sha256": digest("done")}


@pytest.mark.parametrize("damage", ["v1-history", "v2-history", "missing", "null", "uppercase", "numeric", "boolean", "short", "extra", "sources-null", "sources-extra", "source-marker", "duplicate", "history-duplicate", "numeric-version"])
def test_v3_closed_wire_rejects_malformed_history_and_source_shapes(damage):
    value = {"version": "3", "manifest_sha256": HASH, "recovery_payload": "recover", "operations": [],
        "proposed_history_sha256": "b" * 64}
    if damage == "v1-history": value["version"] = "1"
    if damage == "v2-history":
        value.update(version="2", sources={"context_id": "run", "expected_operation_id": "reg", "baseline_payload": BASELINE})
    if damage == "missing": del value["proposed_history_sha256"]
    if damage in {"null", "uppercase", "numeric", "boolean", "short"}:
        value["proposed_history_sha256"] = {"null": None, "uppercase": "B" * 64, "numeric": 1, "boolean": True, "short": "b" * 63}[damage]
    if damage == "extra": value["identity_history_sha256"] = "b" * 64
    if damage == "sources-null": value["sources"] = None
    if damage in {"sources-extra", "source-marker"}:
        value["sources"] = {"context_id": "run", "expected_operation_id": "reg", "baseline_payload": BASELINE}
        if damage == "sources-extra": value["sources"]["extra"] = "x"
        else: value["manifest_sha256"] = "c" * 64
    if damage == "numeric-version": value["version"] = 3
    wire = canonical(value)
    if damage == "duplicate": wire = wire[:-1] + ',"version":"3"}'
    if damage == "history-duplicate": wire = wire[:-1] + ',"proposed_history_sha256":"' + "b" * 64 + '"}'
    with pytest.raises(PublicationIntentError):
        decode_publication_request(wire)


@pytest.mark.parametrize("damage", [False, 3, [], "A" * 64, "b" * 63, type("Hash", (str,), {})("b" * 64), "delete"])
def test_damaged_frozen_history_fails_before_transaction(tmp_path, monkeypatch, damage):
    store = IdentityStore.initialize(tmp_path)
    request = PublicationIntentRequest(HASH, "recover", proposed_history_sha256="b" * 64)
    if damage == "delete": object.__delattr__(request, "proposed_history_sha256")
    else: object.__setattr__(request, "proposed_history_sha256", damage)
    monkeypatch.setattr(store, "_transaction", lambda **kw: pytest.fail("invalid claim opened transaction"))
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)


def test_bound_request_detaches_exact_strings_before_transaction(tmp_path, monkeypatch):
    store, _, request, _ = mixed_seed(tmp_path)
    request, proposed = bind(store, replace(request, recovery_payload="recover\r\nž"))
    original_wire = encode_publication_request(request)
    original_transaction = store._transaction
    @contextmanager
    def transaction(**kwargs):
        object.__setattr__(request, "proposed_history_sha256", "f" * 64)
        object.__setattr__(request.operations[0], "payload", "broken")
        object.__setattr__(request.sources, "baseline_payload", "broken")
        with original_transaction(**kwargs) as connection:
            yield connection
    with monkeypatch.context() as patch:
        patch.setattr(store, "_transaction", transaction)
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert store.identity_publication(spec_id="demo", operation_id="pub")["request"] == original_wire
    receipt = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert receipt["identity_history_sha256"] == proposed.sha256
    assert [entry["method"] for entry in receipt["operations"]] == ["lifecycle", "reference_claims", "issue_occurrences"]
    assert store.read_revision(spec_id="demo", element_id="ISS-000001", revision="1")["content"] == "Original\r\nž"
    assert store.identity_history(spec_id="demo") == proposed


def history_seed(path):
    store, registration = seed_empty(path)
    store.import_identities(spec_id="demo", operation_id="wide", definitions=(("FR-1000000", "Wide"),))
    fr, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve-fr", count=1)
    issue, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-iss", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="initial", changes=(ElementAdopt("FR-1000000", "Wide", "Old"),
        ElementCreate(fr, "Feature", "Old\r\nž", "reserve-fr"), ElementCreate(issue, "Issue", "Body", "reserve-iss")))
    store.record_reference_claims(spec_id="demo", operation_id="old-evidence", claims=(ReferenceClaim("old.md", HASH, "old", fr, "1", "evidence"),))
    operation = op("lifecycle", "proposal", ElementRevision(fr, "1", "Feature", "New\r\nž"))
    request, proposed = bind(store, source_request(operations=(operation,)))
    return store, registration, request, proposed, fr, issue


@pytest.mark.parametrize("change", ["entity", "reference", "occurrence"])
def test_legitimate_unrelated_history_invalidates_prepare_without_mutation(tmp_path, change):
    store, registration, request, proposed, fr, issue = history_seed(tmp_path)
    if change == "entity":
        store.apply_lifecycle(spec_id="demo", operation_id="unrelated", changes=(ElementRevision("FR-1000000", "1", "Wide", "Later"),))
    elif change == "reference":
        store.record_reference_claims(spec_id="demo", operation_id="unrelated", claims=(ReferenceClaim("new.md", HASH, "new", fr, "1", "evidence"),))
    else:
        store.record_issue_occurrences(spec_id="demo", operation_id="unrelated", occurrences=(IssueOccurrence(issue, "1", "report", HASH, "ISS-old", "Issue", "Body"),))
    fresh = store.preview_identity_history(spec_id="demo", operations=request.operations)
    assert fresh.sha256 != proposed.sha256  # The exact child proposal still validates.
    assert store.source_context(spec_id="demo", context_id="run") == registration
    before = state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert state(tmp_path) == before
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=replace(request, proposed_history_sha256=fresh.sha256))
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["identity_history_sha256"] == fresh.sha256
    assert store.identity_history(spec_id="demo") == fresh


def test_unused_reservations_and_other_specs_do_not_invalidate_history(tmp_path):
    store, _, request, proposed, _, _ = history_seed(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="unused", count=4)
    label, = store.reserve(spec_id="other", kind="FR", operation_id="other-reserve", count=1)
    store.apply_lifecycle(spec_id="other", operation_id="other-create", changes=(ElementCreate(label, "Other", "Body", "other-reserve"),))
    assert store.preview_identity_history(spec_id="demo", operations=request.operations) == proposed
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=replace(request, proposed_history_sha256="b" * 64))
    for action in (lambda: store.preview_identity_history(spec_id="demo"),
                   lambda: store.reserve(spec_id="demo", kind="FR", operation_id="blocked", count=1),
                   lambda: store.apply_lifecycle(spec_id="demo", operation_id="proposal", changes=(ElementRevision("FR-1000001", "1", "Feature", "New\r\nž"),))):
        with pytest.raises(IdentityStoreError): action()
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["identity_history_sha256"] == proposed.sha256


def test_stale_prepare_checks_history_before_attempting_any_insert(tmp_path):
    from harness import element_identity_publication_store as journal
    store, _, request, _, _, _ = history_seed(tmp_path)
    store.apply_lifecycle(spec_id="demo", operation_id="unrelated", changes=(ElementRevision("FR-1000000", "1", "Wide", "Later"),))
    before = state(tmp_path)
    attempted_writes = []
    with pytest.raises(IdentityStoreError, match="proposed complete identity history"):
        with store._transaction(write=True) as connection:
            def deny_writes(action, table, *_):
                if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                    attempted_writes.append(table)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(deny_writes)
            journal.prepare(connection, store, "demo", "pub", request)
    assert attempted_writes == []
    assert state(tmp_path) == before


def inject_coherent_reference_fault(connection, label):
    """Raw SQL corruption fixture: bypass pending ownership, never a legitimate writer."""
    payload = {"source_path": "fault.md", "source_sha256": HASH, "source_anchor": "fault",
               "target_id": label, "target_revision": "1", "relation": "evidence"}
    entry = {"spec_id": "demo", "operation_id": "fault", "entry_index": "1", **payload}
    row = {**entry, "payload_sha256": digest(canonical(["reference_claims", entry]))}
    connection.execute("INSERT INTO operations VALUES (?,?,?,?)", ("fault", "reference_claims", "demo",
        digest(canonical(["reference_claims", "demo", "fault", [payload]]))))
    connection.execute(f"INSERT INTO reference_claims ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    connection.execute("INSERT INTO binding_receipts VALUES (?,?,?)", ("fault", canonical([entry]), digest(canonical([entry]))))


def test_prepared_read_is_retained_but_apply_rechecks_complete_history_before_writers(tmp_path, monkeypatch):
    from harness import element_identity_lifecycle_store, element_identity_binding_store
    store, _, request, _, fr, _ = history_seed(tmp_path)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    retained = store.identity_publication(spec_id="demo", operation_id="pub")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        inject_coherent_reference_fault(connection, fr)
    store.audit()  # Internally consistent fault; freshness is a separate application check.
    assert store.identity_publication(spec_id="demo", operation_id="pub") == retained
    before = state(tmp_path)
    def forbidden(*args, **kwargs): pytest.fail("stale prepared application reached child writer")
    monkeypatch.setattr(element_identity_lifecycle_store, "apply_changes", forbidden)
    monkeypatch.setattr(element_identity_binding_store, "record", forbidden)
    with pytest.raises(IdentityStoreError, match="complete identity history"):
        store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert state(tmp_path) == before
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"


def test_extra_consistent_child_effect_after_precheck_rolls_back_sources_parent_and_all_rows(tmp_path, monkeypatch):
    from harness import element_identity_lifecycle_store as lifecycle_store
    store, registration, request, _ = mixed_seed(tmp_path)
    request, proposed = bind(store, request)
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    before = state(tmp_path)
    original = lifecycle_store.apply_changes
    def faulty(connection, *args, **kwargs):
        result = original(connection, *args, **kwargs)
        inject_coherent_reference_fault(connection, "FR-000001")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, "apply_changes", faulty)
        with pytest.raises(IdentityStoreError, match="applied complete identity history"):
            store.apply_identity_publication(spec_id="demo", operation_id="pub")
    assert state(tmp_path) == before
    store = IdentityStore.open(tmp_path)
    assert store.source_context(spec_id="demo", context_id="run") == registration
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["identity_history_sha256"] == proposed.sha256
    assert store.identity_history(spec_id="demo") == proposed


@pytest.mark.parametrize("stage", ["source-plan", "child", "head", "receipt", "commit"])
def test_v3_real_sql_failure_rolls_back_before_commit(tmp_path, stage):
    from harness import element_identity_publication_store as journal
    store, registration, request, _ = mixed_seed(tmp_path)
    request, proposed = bind(store, request)
    if stage != "source-plan": store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    before = state(tmp_path)
    denied = {"source-plan": (sqlite3.SQLITE_INSERT, "source_publications", None),
        "child": (sqlite3.SQLITE_INSERT, "issue_occurrences", None),
        "head": (sqlite3.SQLITE_UPDATE, "source_contexts", "head_publication_id"),
        "receipt": (sqlite3.SQLITE_UPDATE, "publication_intents", "application_receipt"),
        "commit": (sqlite3.SQLITE_TRANSACTION, "COMMIT", None)}[stage]
    with pytest.raises((IdentityStoreError, sqlite3.DatabaseError)):
        with store._transaction(write=True) as connection:
            connection.set_authorizer(lambda action, target, column, *_: sqlite3.SQLITE_DENY
                if (action, target, column) == denied else sqlite3.SQLITE_OK)
            if stage == "source-plan": journal.prepare(connection, store, "demo", "pub", request)
            else: journal.apply(connection, store, "demo", "pub")
    assert state(tmp_path) == before
    assert store.source_context(spec_id="demo", context_id="run") == registration
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub")["identity_history_sha256"] == proposed.sha256


def test_v3_postcommit_uncertainty_reopen_retains_original_receipt(tmp_path, monkeypatch):
    from harness import element_identity_store as authority
    store, _, request, _ = mixed_seed(tmp_path)
    request, proposed = bind(store, request)
    preparation = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
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
    assert retained["identity_history_sha256"] == proposed.sha256
    assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparation
    assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == retained
    assert store.source_context(spec_id="demo", context_id="run") == retained["sources"]
    assert store.identity_history(spec_id="demo") == proposed
    assert state(tmp_path) == before


@pytest.mark.parametrize("sources", [False, True])
@pytest.mark.parametrize("damage", ["request-only", "request-history", "receipt-history", "missing-history", "null-history", "extra", "old-version", "sources-null", "duplicate"])
def test_rehashed_history_or_closed_receipt_damage_rejects_association(tmp_path, sources, damage):
    store, _ = seed_empty(tmp_path)
    request, _ = bind(store, source_request() if sources else PublicationIntentRequest(HASH, "recover"))
    store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request)
    application = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        if damage in {"request-only", "request-history"}:
            changed = encode_publication_request(replace(request, proposed_history_sha256="b" * 64))
            plan_sha = connection.execute("SELECT plan_sha256 FROM publication_intents WHERE operation_id='pub'").fetchone()[0]
            connection.execute("UPDATE publication_intents SET request=?,request_sha256=? WHERE operation_id='pub'", (changed, digest(changed)))
            connection.execute("UPDATE operations SET digest=? WHERE operation_id='pub'", (
                digest(canonical(["identity_publication", "demo", "pub", changed, plan_sha])),))
            # Also repair preparation association to isolate the history mismatch.
            if damage == "request-history": application["publication"]["request_sha256"] = digest(changed)
        if damage == "receipt-history": application["identity_history_sha256"] = "b" * 64
        if damage == "missing-history": del application["identity_history_sha256"]
        if damage == "null-history": application["identity_history_sha256"] = None
        if damage == "extra": application["proposed_history_sha256"] = "b" * 64
        if damage == "old-version": application["version"] = "2" if sources else "1"
        if damage == "sources-null": application["sources"] = None
        encoded = canonical(application)
        if damage == "duplicate": encoded = encoded[:-1] + ',"version":"3"}'
        connection.execute("UPDATE publication_intents SET application_receipt=?,application_receipt_sha256=? WHERE operation_id='pub'", (encoded, digest(encoded)))
        connection.execute("UPDATE source_publications SET application_sha256=? WHERE publication_id='pub'", (digest(encoded),))
    before = state(tmp_path)
    checks = [store.audit, lambda: store.identity_publication(spec_id="demo", operation_id="pub"),
        lambda: store.apply_identity_publication(spec_id="demo", operation_id="pub"),
        lambda: store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done"),
        lambda: store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request),
        lambda: store.identity_history(spec_id="demo")]
    if sources: checks.append(lambda: store.source_context(spec_id="demo", context_id="run"))
    for action in checks:
        with pytest.raises(IdentityStoreError): action()
        assert state(tmp_path) == before


def test_real_guarded_source_recovery_graph_retry_backup_and_bounded_reads(tmp_path, monkeypatch):
    from pathlib import Path
    from tests.unit.test_element_identity_managed_context import real_advance_setup
    from harness.squad_publication import PublicationError, SquadPublicationTransaction, load_prepared_publication, _secure_posix_capabilities_available
    from harness.squad_source_baseline_codec import decode_initial_publication_sources, encode_initial_publication_sources
    from harness.element_identity_publication import PublicationSourceClaim
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness import element_identity_snapshot, element_identity_snapshot_preview, element_identity_source_store
    from echelon.spec_graph import GraphNode, SpecArtifactGraph, render_spec_graph
    from echelon.spec_graph_identity import project_identity_history
    if not _secure_posix_capabilities_available(): pytest.skip("secure POSIX publication unavailable")
    project = tmp_path.resolve()
    store, genesis, registration, prepared, initial, request = real_advance_setup(project)
    store.import_identities(spec_id="demo", operation_id="wide", definitions=(("FR-1000000", "Feature"),))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(ElementAdopt("FR-1000000", "Feature", "Old"),))
    store.record_reference_claims(spec_id="demo", operation_id="old", claims=(ReferenceClaim("evidence.md", HASH, "old", "FR-1000000", "1", "evidence"),))
    operations = (op("lifecycle", "revise", ElementRevision("FR-1000000", "1", "Feature", "New")),)
    request, proposed = bind(store, replace(request, operations=operations))
    base = SpecArtifactGraph("demo", "test", (), (
        GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
        GraphNode("req:demo:FR-1000000", "Requirement", {"requirement_id": "FR-1000000"}),
    ), (), ())
    projected = project_identity_history(base, proposed)
    rendered = render_spec_graph(projected)
    preparations = []
    def before(_): preparations.append(store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request))
    def after(_): store.apply_identity_publication(spec_id="demo", operation_id="pub")
    def stop(position):
        if position == 1: raise RuntimeError("interrupted real physical prefix")
    with pytest.raises(PublicationError):
        prepared.publish_sources(initial, before_publish=before, after_publish=after, fault_hook=stop)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    assert store.source_context(spec_id="demo", context_id="first-source") == registration
    store = IdentityStore.open(project)
    retained = decode_publication_request(store.identity_publication(spec_id="demo", operation_id="pub")["request"])
    assert retained == request
    original = decode_initial_publication_sources(retained.sources.baseline_payload)
    loaded = load_prepared_publication(project, prepared._squad_dir, prepared.marker)
    final_sources = loaded.publish_sources(original, before_publish=before, after_publish=after)
    assert preparations[0] == preparations[1]
    receipt = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    final_manifest = snapshot_source_manifest(trees=final_sources.trees, files=final_sources.files)
    assert receipt["version"] == "3" and receipt["identity_history_sha256"] == proposed.sha256
    assert receipt["sources"]["manifest"] == {"payload": final_manifest.payload, "sha256": final_manifest.sha256}
    assert receipt["sources"]["sequence"] == "1"
    with store._transaction() as connection:
        assert connection.execute("SELECT application_sha256 FROM source_publications WHERE publication_id='pub'").fetchone()[0] == digest(canonical(receipt))
    assert store.identity_history(spec_id="demo") == proposed
    assert render_spec_graph(project_identity_history(base, store.identity_history(spec_id="demo"))) == rendered
    assert [node.id for node in projected.nodes[:2]] == [node.id for node in base.nodes]
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    old = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "1")
    current = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "2")
    assert claim.properties["target_revision_matches_current"] is False
    assert any(edge.source == claim.id and edge.type == "ASSESSES_REVISION" and edge.target == old.id for edge in projected.edges)
    assert not any(edge.source == claim.id and edge.type == "ASSESSES_REVISION" and edge.target == current.id for edge in projected.edges)
    release = store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done")
    # Legitimate later accepted history must not rewrite an original claim/receipt.
    store.apply_lifecycle(spec_id="demo", operation_id="later", changes=(ElementRevision("FR-1000000", "2", "Feature", "Later"),))
    assert store.identity_history(spec_id="demo").sha256 != proposed.sha256
    # Advance the same source head through a second real guarded v3 publication.
    (project / "runs/second").mkdir()
    transaction = SquadPublicationTransaction.begin(project, project / "runs/second", "9" * 32)
    stage = transaction.build_path("definition")
    stage.write_bytes(b"later accepted source\r\n")
    target = Path("runs/first/specs/demo/definition.md")
    transaction.add_write(target, stage, owned_paths={target})
    later_prepared = transaction.seal()
    with later_prepared.inspect_sources(tree_paths=("runs/first/specs/demo",), file_paths=()) as later_initial:
        later_baseline = encode_initial_publication_sources(later_initial)
    later_request, _ = bind(store, PublicationIntentRequest(later_prepared.marker.manifest_sha256, "later recovery",
        sources=PublicationSourceClaim("first-source", "pub", later_baseline)))
    later_prepared.publish_sources(later_initial,
        before_publish=lambda _: store.prepare_identity_publication(spec_id="demo", operation_id="later-pub", request=later_request),
        after_publish=lambda _: store.apply_identity_publication(spec_id="demo", operation_id="later-pub"))
    later_receipt = store.apply_identity_publication(spec_id="demo", operation_id="later-pub")
    store.release_identity_publication(spec_id="demo", operation_id="later-pub", completion_payload="later done")
    assert later_receipt["sources"]["sequence"] == "2"
    store = IdentityStore.open(project)
    before_state = state(project)
    def forbidden(*args, **kwargs): pytest.fail("retained retry or bounded read recaptured complete history")
    with monkeypatch.context() as patch:
        patch.setattr(element_identity_snapshot, "capture", forbidden)
        patch.setattr(element_identity_snapshot_preview, "capture", forbidden)
        assert store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparations[0]
        assert store.apply_identity_publication(spec_id="demo", operation_id="pub") == receipt
        assert store.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done") == release
        assert json.loads(store.identity_publication(spec_id="demo", operation_id="pub")["application_receipt"]) == receipt
    assert state(project) == before_state
    historical = {"entities", "revisions", "lifecycle_lineage", "lifecycle_receipts", "lifecycle_heads",
        "reference_claims", "issue_occurrences", "binding_receipts", "reservations", "counters"}
    original_transaction = store._transaction
    @contextmanager
    def indexed_transaction(**kwargs):
        with original_transaction(**kwargs) as connection:
            connection.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and table in historical else sqlite3.SQLITE_OK)
            yield connection
    with monkeypatch.context() as patch:
        patch.setattr(store, "_transaction", indexed_transaction)
        patch.setattr(element_identity_snapshot, "capture", forbidden)
        assert store.source_context(spec_id="demo", context_id="first-source") == later_receipt["sources"]
        assert store.check_managed_context(spec_id="demo", run_id="first", record=genesis) == {
            "managed_identity": genesis, "source_context": later_receipt["sources"]}
    with store._transaction() as connection:
        for query, parameters in ((element_identity_source_store._HEAD, ("demo", "first-source")),
                ("SELECT * FROM publication_intents WHERE operation_id=?", ("pub",)),
                ("SELECT operation_id,publication_id,method,digest FROM publication_operation_claims WHERE publication_id=?", ("pub",))):
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, parameters))
            assert "SEARCH" in plan and "SCAN" not in plan and "TEMP B-TREE" not in plan
    with monkeypatch.context() as patch:
        patch.setattr(element_identity_snapshot, "capture", forbidden)
        store.reserve(spec_id="demo", kind="FR", operation_id="after", count=1)
    backup = project / "backup"
    store.backup(backup)
    (project / "restored").mkdir()
    restored = IdentityStore.restore(project / "restored", backup)
    restored.audit()
    assert restored.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request) == preparations[0]
    assert restored.apply_identity_publication(spec_id="demo", operation_id="pub") == receipt
    assert restored.release_identity_publication(spec_id="demo", operation_id="pub", completion_payload="done") == release
    assert restored.source_context(spec_id="demo", context_id="first-source") == later_receipt["sources"]
    assert restored.identity_history(spec_id="demo") == store.identity_history(spec_id="demo")
