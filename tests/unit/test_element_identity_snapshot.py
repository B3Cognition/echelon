from contextlib import closing, contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

import pytest

from harness import element_identity_binding_store as binding_store
from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle_store as lifecycle_store
from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
from harness.element_identity_lifecycle import (
    ElementAdopt,
    ElementCreate,
    ElementRetirement,
    ElementRevision,
    ElementTransition,
)
from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
from harness.element_identity_request_codec import encode_request
from harness.element_identity_snapshot import IdentityHistorySnapshot, capture
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


DATABASE = ".echelon/identity/registry.sqlite3"
HASH = "a" * 64


def database(path):
    return path / DATABASE


def sql_state(path):
    with closing(sqlite3.connect(database(path))) as connection:
        return tuple(connection.iterdump())


def value(snapshot):
    return json.loads(snapshot.payload)


def publication_request(*operations):
    return PublicationIntentRequest(HASH, "controller recovery", tuple(
        PublicationOperation(method, operation_id, encode_request(method, entries))
        for method, operation_id, entries in operations
    ))


def record_digest(method, row):
    payload = json.dumps([method, row], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def expected_revision(element_id, revision, subject, content, status, reason, operation_id):
    return {
        "spec_id": "demo",
        "element_id": element_id,
        "revision": revision,
        "subject": subject,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "status": status,
        "reason": reason,
        "operation_id": operation_id,
    }


def test_snapshot_retains_old_revision_and_evidence_after_retirement(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Scene", "Original body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim("evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Scene", "Revised body"),))
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(
        ElementRetirement(label, "2", "No longer an active obligation"),))
    snapshot = store.identity_history(spec_id="demo")
    value = json.loads(snapshot.payload)
    assert value["entities"][0]["status"] == "retired"
    assert [row["revision"] for row in value["revisions"]] == ["1", "2", "3"]
    assert value["revisions"][0]["content"] == "Original body"
    assert value["reference_claims"][0]["target_revision"] == "1"


def test_empty_and_reservation_only_snapshots_are_exact_canonical_namespace_values(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    marker = json.loads((tmp_path / ".echelon/identity/authority.json").read_text())
    snapshot = store.identity_history(spec_id="empty")
    decoded = json.loads(
        snapshot.payload,
        parse_int=lambda token: pytest.fail(f"numeric JSON token: {token}"),
        parse_float=lambda token: pytest.fail(f"numeric JSON token: {token}"),
    )
    assert set(decoded) == {
        "version", "workspace_uuid", "epoch_uuid", "spec_id", "entities", "revisions",
        "lineage", "reference_claims", "issue_occurrences",
    }
    assert decoded == {
        "version": "1", "workspace_uuid": marker["workspace_uuid"],
        "epoch_uuid": marker["epoch_uuid"], "spec_id": "empty", "entities": [],
        "revisions": [], "lineage": [], "reference_claims": [], "issue_occurrences": [],
    }
    assert snapshot.payload == json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert snapshot.payload.encode("ascii").decode("ascii") == snapshot.payload
    assert snapshot.sha256 == hashlib.sha256(snapshot.payload.encode("ascii")).hexdigest()
    assert isinstance(snapshot.payload, str) and isinstance(snapshot.sha256, str)
    with pytest.raises(FrozenInstanceError):
        snapshot.payload = "changed"

    store.reserve(spec_id="empty", kind="FR", operation_id="unused", count=2)
    assert store.identity_history(spec_id="empty") == snapshot


def test_complete_lifecycle_lineage_and_binding_rows_retain_original_values(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(
        ("FR-001", "Legacy FR"),
        ("U-legacy", "Legacy U"),
        ("NFR-composite.1", "Opaque NFR"),
        ("ISS-old", "Legacy issue"),
        ("A-legacy", "Legacy assumption"),
        ("T-S01", "Legacy task"),
        ("AC-legacy-999999", "Legacy criterion"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(
        ElementAdopt("U-legacy", "Legacy U", "Assessed unknown body"),
    ))
    ac_labels = store.reserve(spec_id="demo", kind="AC", operation_id="reserve-ac", count=4)
    store.apply_lifecycle(spec_id="demo", operation_id="create-ac", changes=(
        ElementCreate(ac_labels[0], "Root", "Root body", "reserve-ac"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="replace", changes=(
        ElementTransition("replace", ((ac_labels[0], "1"),), (
            ElementCreate(ac_labels[1], "Replacement", "Replacement body", "reserve-ac"),
        ), "replacement reason"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="split", changes=(
        ElementTransition("split", ((ac_labels[1], "1"),), (
            ElementCreate(ac_labels[2], "Left", "Left body", "reserve-ac"),
            ElementCreate(ac_labels[3], "Right", "Right body", "reserve-ac"),
        ), "split reason"),
    ))
    fr_label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve-fr", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="merge", changes=(
        ElementTransition("merge", ((ac_labels[2], "1"), (ac_labels[3], "1")), (
            ElementCreate(fr_label, "Merged", "Merged body", "reserve-fr"),
        ), "merge reason"),
    ))
    nfr_label, = store.reserve(spec_id="demo", kind="NFR", operation_id="reserve-nfr", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create-nfr", changes=(
        ElementCreate(nfr_label, "Latency", "First latency body", "reserve-nfr"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="revise-nfr", changes=(
        ElementRevision(nfr_label, "1", "Latency", "Second latency body"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="retire-nfr", changes=(
        ElementRetirement(nfr_label, "2", "superseded constraint"),
    ))
    issue_label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-iss", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create-iss", changes=(
        ElementCreate(issue_label, "Broken arrows", "Repair arrows.", "reserve-iss"),
    ))
    claims = tuple(
        ReferenceClaim(
            "evidence.md", HASH, f"span:{index}",
            "FR-001" if index == 1 else nfr_label,
            None if index == 1 else "1", "reference" if index == 1 else "evidence",
        )
        for index in range(1, 13)
    )
    claim_receipt = store.record_reference_claims(
        spec_id="demo", operation_id="claims", claims=claims,
    )
    occurrence = IssueOccurrence(
        issue_label, "1", "report-1", HASH, "ISS-display", "Broken arrows", "Repair arrows.",
    )
    occurrence_receipt = store.record_issue_occurrences(
        spec_id="demo", operation_id="occurrences", occurrences=(occurrence,),
    )
    store.apply_lifecycle(spec_id="demo", operation_id="revise-iss", changes=(
        ElementRevision(issue_label, "1", "Broken arrows", "Repair arrows with proof."),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="retire-iss", changes=(
        ElementRetirement(issue_label, "2", "fixed"),
    ))

    snapshot = store.identity_history(spec_id="demo")
    decoded = json.loads(
        snapshot.payload,
        parse_int=lambda token: pytest.fail(f"numeric JSON token: {token}"),
        parse_float=lambda token: pytest.fail(f"numeric JSON token: {token}"),
    )
    assert decoded["entities"] == [
        {"spec_id": "demo", "element_id": "A-legacy", "kind": "A",
         "subject": "Legacy assumption", "ordinal": None, "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": ac_labels[0], "kind": "AC", "subject": "Root",
         "ordinal": "1", "status": "superseded", "revision": "2"},
        {"spec_id": "demo", "element_id": ac_labels[1], "kind": "AC", "subject": "Replacement",
         "ordinal": "2", "status": "superseded", "revision": "2"},
        {"spec_id": "demo", "element_id": ac_labels[2], "kind": "AC", "subject": "Left",
         "ordinal": "3", "status": "superseded", "revision": "2"},
        {"spec_id": "demo", "element_id": ac_labels[3], "kind": "AC", "subject": "Right",
         "ordinal": "4", "status": "superseded", "revision": "2"},
        {"spec_id": "demo", "element_id": "AC-legacy-999999", "kind": "AC",
         "subject": "Legacy criterion", "ordinal": None, "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": "FR-001", "kind": "FR", "subject": "Legacy FR",
         "ordinal": "1", "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": fr_label, "kind": "FR", "subject": "Merged",
         "ordinal": "2", "status": "active", "revision": "1"},
        {"spec_id": "demo", "element_id": issue_label, "kind": "ISS", "subject": "Broken arrows",
         "ordinal": "1", "status": "retired", "revision": "3"},
        {"spec_id": "demo", "element_id": "ISS-old", "kind": "ISS", "subject": "Legacy issue",
         "ordinal": None, "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": nfr_label, "kind": "NFR", "subject": "Latency",
         "ordinal": "1", "status": "retired", "revision": "3"},
        {"spec_id": "demo", "element_id": "NFR-composite.1", "kind": "NFR",
         "subject": "Opaque NFR", "ordinal": None, "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": "T-S01", "kind": "T", "subject": "Legacy task",
         "ordinal": None, "status": "imported", "revision": None},
        {"spec_id": "demo", "element_id": "U-legacy", "kind": "U", "subject": "Legacy U",
         "ordinal": None, "status": "active", "revision": "1"},
    ]
    assert decoded["revisions"] == [
        expected_revision(ac_labels[0], "1", "Root", "Root body", "active", None, "create-ac"),
        expected_revision(
            ac_labels[0], "2", "Root", "Root body", "superseded", "replacement reason", "replace",
        ),
        expected_revision(
            ac_labels[1], "1", "Replacement", "Replacement body", "active", None, "replace",
        ),
        expected_revision(
            ac_labels[1], "2", "Replacement", "Replacement body", "superseded", "split reason", "split",
        ),
        expected_revision(ac_labels[2], "1", "Left", "Left body", "active", None, "split"),
        expected_revision(
            ac_labels[2], "2", "Left", "Left body", "superseded", "merge reason", "merge",
        ),
        expected_revision(ac_labels[3], "1", "Right", "Right body", "active", None, "split"),
        expected_revision(
            ac_labels[3], "2", "Right", "Right body", "superseded", "merge reason", "merge",
        ),
        expected_revision(fr_label, "1", "Merged", "Merged body", "active", None, "merge"),
        expected_revision(
            issue_label, "1", "Broken arrows", "Repair arrows.", "active", None, "create-iss",
        ),
        expected_revision(
            issue_label, "2", "Broken arrows", "Repair arrows with proof.", "active", None, "revise-iss",
        ),
        expected_revision(
            issue_label, "3", "Broken arrows", "Repair arrows with proof.", "retired", "fixed", "retire-iss",
        ),
        expected_revision(
            nfr_label, "1", "Latency", "First latency body", "active", None, "create-nfr",
        ),
        expected_revision(
            nfr_label, "2", "Latency", "Second latency body", "active", None, "revise-nfr",
        ),
        expected_revision(
            nfr_label, "3", "Latency", "Second latency body", "retired",
            "superseded constraint", "retire-nfr",
        ),
        expected_revision(
            "U-legacy", "1", "Legacy U", "Assessed unknown body", "active", None, "adopt",
        ),
    ]
    assert decoded["lineage"] == [
        {"spec_id": "demo", "predecessor_id": ac_labels[0], "predecessor_revision": "1",
         "successor_id": ac_labels[1], "successor_revision": "1", "kind": "replace",
         "reason": "replacement reason", "operation_id": "replace"},
        {"spec_id": "demo", "predecessor_id": ac_labels[1], "predecessor_revision": "1",
         "successor_id": ac_labels[2], "successor_revision": "1", "kind": "split",
         "reason": "split reason", "operation_id": "split"},
        {"spec_id": "demo", "predecessor_id": ac_labels[1], "predecessor_revision": "1",
         "successor_id": ac_labels[3], "successor_revision": "1", "kind": "split",
         "reason": "split reason", "operation_id": "split"},
        {"spec_id": "demo", "predecessor_id": ac_labels[2], "predecessor_revision": "1",
         "successor_id": fr_label, "successor_revision": "1", "kind": "merge",
         "reason": "merge reason", "operation_id": "merge"},
        {"spec_id": "demo", "predecessor_id": ac_labels[3], "predecessor_revision": "1",
         "successor_id": fr_label, "successor_revision": "1", "kind": "merge",
         "reason": "merge reason", "operation_id": "merge"},
    ]

    expected_claims = [row | {"payload_sha256": record_digest("reference_claims", row)}
                       for row in claim_receipt]
    assert decoded["reference_claims"] == expected_claims
    assert [row["entry_index"] for row in decoded["reference_claims"]] == [
        str(index) for index in range(1, 13)
    ]
    assert decoded["reference_claims"][0]["target_revision"] is None
    expected_occurrence = occurrence_receipt[0] | {
        "payload_sha256": record_digest("issue_occurrences", occurrence_receipt[0]),
    }
    assert decoded["issue_occurrences"] == [expected_occurrence]
    assert decoded["issue_occurrences"][0]["issue_revision"] == "1"
    assert decoded["issue_occurrences"][0]["body"] == "Repair arrows."
    assert decoded["issue_occurrences"][0]["issue_fingerprint"] == occurrence_receipt[0]["issue_fingerprint"]


def _install_authenticated_high_revisions(path, label, revisions):
    """Create rows constrained and authenticated by the existing full audit contract."""
    with sqlite3.connect(database(path)) as connection:
        for index, revision in enumerate(revisions, 1):
            operation_id = f"synthetic-lifecycle-{index}"
            content = f"body-{index}"
            content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT INTO operations VALUES (?,?,?,?)",
                (operation_id, "lifecycle", "order", "synthetic fixture digest"),
            )
            connection.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)",
                ("order", label, revision, "Subject 0", content, content_sha256,
                 "active", None, operation_id),
            )
            receipt = json.dumps([{
                "element_id": label, "revision": revision, "status": "active", "lineage": [],
            }], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            connection.execute(
                "INSERT INTO lifecycle_receipts VALUES (?,?,?)",
                (operation_id, receipt, hashlib.sha256(receipt.encode("ascii")).hexdigest()),
            )
        connection.execute(
            "UPDATE lifecycle_heads SET status='active',revision=? WHERE spec_id='order' AND element_id=?",
            (revisions[-1], label),
        )


def test_numeric_text_order_supports_million_and_five_thousand_digit_values(tmp_path):
    before_limit = sys.get_int_max_str_digits()
    huge = "1" + "0" * 4999
    store = IdentityStore.initialize(tmp_path)
    labels = ("FR-9", "FR-10", "FR-999999", "FR-1000000", f"FR-{huge}")
    store.import_identities(
        spec_id="order", operation_id="import-order",
        definitions=tuple((label, f"Subject {index}") for index, label in enumerate(labels)),
    )
    revisions = ("9", "10", "999999", "1000000", huge)
    _install_authenticated_high_revisions(tmp_path, "FR-9", revisions)

    decoded = value(store.identity_history(spec_id="order"))
    assert [row["element_id"] for row in decoded["entities"]] == list(labels)
    assert [row["revision"] for row in decoded["revisions"]] == list(revisions)
    assert sys.get_int_max_str_digits() == before_limit


def test_only_selected_materialized_effects_change_snapshot_and_restore_is_exact(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    original = store.identity_history(spec_id="demo")
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=2)
    assert store.identity_history(spec_id="demo") == original
    store.reserve(spec_id="other", kind="AC", operation_id="other-reserve", count=1)
    store.apply_lifecycle(spec_id="other", operation_id="other-create", changes=(
        ElementCreate("AC-000001", "Other", "Other body", "other-reserve"),
    ))
    assert store.identity_history(spec_id="demo") == original

    empty_request = publication_request()
    store.prepare_identity_publication(spec_id="demo", operation_id="empty-pub", request=empty_request)
    assert store.identity_history(spec_id="demo") == original
    store.apply_identity_publication(spec_id="demo", operation_id="empty-pub")
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    assert store.identity_history(spec_id="demo") == original
    store.release_identity_publication(
        spec_id="demo", operation_id="empty-pub", completion_payload="empty complete",
    )
    assert store.identity_history(spec_id="demo") == original

    create = ElementCreate("FR-000001", "Scene", "Scene body", "reserve")
    claim = ReferenceClaim("evidence.md", HASH, "span:1", "FR-000001", "1", "evidence")
    mixed_request = publication_request(
        ("lifecycle", "mixed-life", (create,)),
        ("reference_claims", "mixed-claims", (claim,)),
    )
    preparation = store.prepare_identity_publication(
        spec_id="demo", operation_id="mixed-pub", request=mixed_request,
    )
    assert store.identity_history(spec_id="demo") == original
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    application = store.apply_identity_publication(spec_id="demo", operation_id="mixed-pub")
    applied = store.identity_history(spec_id="demo")
    assert applied.sha256 != original.sha256
    assert value(applied)["reference_claims"][0]["target_revision"] == "1"
    assert store.pending_identity_publication(spec_id="demo")["state"] == "applied"
    assert store.prepare_identity_publication(
        spec_id="demo", operation_id="mixed-pub", request=mixed_request,
    ) == preparation
    assert store.apply_identity_publication(spec_id="demo", operation_id="mixed-pub") == application
    assert store.identity_history(spec_id="demo") == applied
    store.release_identity_publication(
        spec_id="demo", operation_id="mixed-pub", completion_payload="mixed complete",
    )
    assert store.identity_history(spec_id="demo") == applied
    store.reserve(spec_id="demo", kind="FR", operation_id="unused-later", count=1)
    assert store.identity_history(spec_id="demo") == applied
    assert value(original)["entities"] == []
    store.record_reference_claims(spec_id="demo", operation_id="later-claim", claims=(
        ReferenceClaim("later.md", HASH, "span:later", "FR-000001", "1", "reference"),
    ))
    binding_changed = store.identity_history(spec_id="demo")
    assert binding_changed.sha256 != applied.sha256
    store.apply_lifecycle(spec_id="demo", operation_id="later-revision", changes=(
        ElementRevision("FR-000001", "1", "Scene", "Later scene body"),
    ))
    latest = store.identity_history(spec_id="demo")
    assert latest.sha256 != binding_changed.sha256
    store = IdentityStore.open(tmp_path)
    assert store.identity_history(spec_id="demo") == latest
    backup = tmp_path / "backup"
    store.backup(backup)
    restored_workspace = tmp_path / "restored"
    restored_workspace.mkdir()
    restored = IdentityStore.restore(restored_workspace, backup)
    assert restored.identity_history(spec_id="demo") == latest


def test_binding_arrays_sort_opaque_operation_ids_then_numeric_entry_indexes(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    fr_label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve-fr", count=1)
    issue_label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-iss", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(fr_label, "Scene", "Scene body", "reserve-fr"),
        ElementCreate(issue_label, "Issue", "Issue body", "reserve-iss"),
    ))
    store.record_reference_claims(spec_id="demo", operation_id="z", claims=tuple(
        ReferenceClaim("z.md", HASH, f"span:{index}", fr_label, "1", "reference")
        for index in range(1, 13)
    ))
    store.record_reference_claims(spec_id="demo", operation_id="a", claims=(
        ReferenceClaim("a.md", HASH, "span:a", fr_label, "1", "reference"),
    ))
    for operation_id, report_id in (("z-occ", "z-report"), ("a-occ", "a-report")):
        store.record_issue_occurrences(spec_id="demo", operation_id=operation_id, occurrences=(
            IssueOccurrence(issue_label, "1", report_id, HASH, "ISS-display", "Issue", "Issue body"),
        ))
    decoded = value(store.identity_history(spec_id="demo"))
    assert [(row["operation_id"], row["entry_index"]) for row in decoded["reference_claims"]] == [
        ("a", "1"), *(("z", str(index)) for index in range(1, 13)),
    ]
    assert [(row["operation_id"], row["entry_index"]) for row in decoded["issue_occurrences"]] == [
        ("a-occ", "1"), ("z-occ", "1"),
    ]


def test_capture_composes_with_uncommitted_writes_and_caller_rollback(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    before = store.identity_history(spec_id="demo")
    claim = ReferenceClaim("evidence.md", HASH, "span:0", label, "1", "evidence")
    with pytest.raises(RuntimeError, match="caller rollback"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(
                connection, store, "demo", "create",
                (ElementCreate(label, "Scene", "Body", "reserve"),),
            )
            binding_store.record(
                connection, store, "reference_claims", "demo", "claims",
                bindings.request((claim,), bindings.ReferenceClaim),
            )
            observed = capture(connection, store, "demo")
            assert value(observed)["revisions"][0]["content"] == "Body"
            assert value(observed)["reference_claims"][0]["source_anchor"] == "span:0"
            assert connection.in_transaction
            raise RuntimeError("caller rollback")
    assert store.identity_history(spec_id="demo") == before
    assert store.lookup(spec_id="demo", element_id=label) is None


def test_direct_helper_owns_no_transaction_write_or_pragma_change(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    with store._transaction() as connection:
        statements = []
        connection.set_trace_callback(statements.append)
        with monkeypatch.context() as context:
            context.setattr(
                store, "_transaction",
                lambda **_arguments: pytest.fail("capture opened a nested store transaction"),
            )
            snapshot = capture(connection, store, "demo")
        assert value(snapshot)["spec_id"] == "demo"
        assert connection.in_transaction
        helper_statements = tuple(statements)
        connection.set_trace_callback(None)
    mutating = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
    assert not any(statement.lstrip().upper().startswith(mutating) for statement in helper_statements)
    assert not any(
        statement.lstrip().upper().startswith("PRAGMA") and "=" in statement
        for statement in helper_statements
    )
    assert not any(statement.lstrip().upper().startswith(
        ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"),
    ) for statement in helper_statements)


def test_public_wrapper_uses_one_query_only_transaction(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    original_transaction = store._transaction
    calls = []
    statements = []

    @contextmanager
    def tracked_transaction(**arguments):
        calls.append(arguments)
        with original_transaction(**arguments) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(store, "_transaction", tracked_transaction)
    assert value(store.identity_history(spec_id="demo"))["entities"] == []
    assert calls == [{}]
    assert sum(statement.strip().upper() == "PRAGMA QUERY_ONLY=ON" for statement in statements) == 1


@pytest.mark.parametrize("bad", [None, "", "   ", "bad\x00spec", b"demo", 1, True, [], "\ud800"])
def test_invalid_public_spec_fails_before_transaction(tmp_path, monkeypatch, bad):
    store = IdentityStore.initialize(tmp_path)
    monkeypatch.setattr(
        store, "_transaction", lambda **_arguments: pytest.fail("invalid input opened a transaction"),
    )
    with pytest.raises(IdentityStoreError):
        store.identity_history(spec_id=bad)


def test_string_subclass_spec_fails_before_transaction(tmp_path, monkeypatch):
    class Spec(str):
        pass

    store = IdentityStore.initialize(tmp_path)
    monkeypatch.setattr(
        store, "_transaction", lambda **_arguments: pytest.fail("invalid input opened a transaction"),
    )
    with pytest.raises(IdentityStoreError):
        store.identity_history(spec_id=Spec("demo"))


def test_direct_helper_requires_transaction_and_supports_class_store(tmp_path):
    IdentityStore.initialize(tmp_path)
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(IdentityStoreError, match="active caller transaction"):
            capture(connection, IdentityStore, "demo")
        connection.execute("BEGIN")
        snapshot = capture(connection, IdentityStore, "demo")
        assert value(snapshot)["spec_id"] == "demo"
        connection.rollback()


def test_direct_helper_uses_validated_connection_metadata_not_filesystem_marker(tmp_path):
    IdentityStore.initialize(tmp_path)
    replacement = {
        "workspace_uuid": "11111111-1111-4111-8111-111111111111",
        "epoch_uuid": "22222222-2222-4222-8222-222222222222",
    }
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "UPDATE metadata SET value=? WHERE key=?",
            [(replacement[key], key) for key in ("workspace_uuid", "epoch_uuid")],
        )
        snapshot = capture(connection, IdentityStore, "demo")
        assert {key: value(snapshot)[key] for key in replacement} == replacement
        assert all(str(UUID(item)) == item for item in replacement.values())
        connection.rollback()


@pytest.mark.parametrize("key,replacement", [
    ("workspace_uuid", "not-a-uuid"),
    ("epoch_uuid", "not-a-uuid"),
    ("schema_version", "3"),
])
def test_direct_helper_rejects_malformed_or_schema_mismatched_metadata(tmp_path, key, replacement):
    IdentityStore.initialize(tmp_path)
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE metadata SET value=? WHERE key=?", (replacement, key))
        before = tuple(connection.iterdump())
        with pytest.raises(IdentityStoreError):
            capture(connection, IdentityStore, "demo")
        assert tuple(connection.iterdump()) == before
        connection.rollback()


def _seed_damage_authority(path):
    store = IdentityStore.initialize(path)
    labels = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=2)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(labels[0], "Original", "Original body", "reserve"),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="replace", changes=(
        ElementTransition("replace", ((labels[0], "1"),), (
            ElementCreate(labels[1], "Replacement", "Replacement body", "reserve"),
        ), "replace reason"),
    ))
    store.record_reference_claims(spec_id="demo", operation_id="claims", claims=(
        ReferenceClaim("evidence.md", HASH, "span:0", labels[0], "1", "evidence"),
    ))
    request = publication_request()
    store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=request)
    store.apply_identity_publication(spec_id="demo", operation_id="publication")
    store.release_identity_publication(
        spec_id="demo", operation_id="publication", completion_payload="complete",
    )
    other, = store.reserve(spec_id="other", kind="AC", operation_id="other-reserve", count=1)
    store.apply_lifecycle(spec_id="other", operation_id="other-create", changes=(
        ElementCreate(other, "Other", "Other body", "other-reserve"),
    ))
    return store


@pytest.mark.parametrize("damage", [
    "schema", "counter", "head", "revision", "lineage", "binding", "publication", "other_spec",
])
def test_actual_sql_data_faults_fail_full_authority_capture_without_mutation(tmp_path, damage):
    workspace = tmp_path / damage
    workspace.mkdir()
    store = _seed_damage_authority(workspace)
    with sqlite3.connect(database(workspace)) as connection:
        if damage == "schema":
            connection.execute("DROP INDEX revision_maxima")
        elif damage == "counter":
            connection.execute("UPDATE counters SET high_water='1' WHERE spec_id='demo' AND kind='FR'")
        elif damage == "head":
            connection.execute(
                "UPDATE lifecycle_heads SET revision='1',status='active' "
                "WHERE spec_id='demo' AND element_id='FR-000001'"
            )
        elif damage == "revision":
            connection.execute(
                "UPDATE revisions SET content_sha256=? WHERE spec_id='demo' AND element_id='FR-000001'",
                ("f" * 64,),
            )
        elif damage == "lineage":
            connection.execute("UPDATE lifecycle_lineage SET reason='different'")
        elif damage == "binding":
            connection.execute("UPDATE reference_claims SET payload_sha256=?", ("f" * 64,))
        elif damage == "publication":
            connection.execute("UPDATE publication_intents SET request_sha256=?", ("f" * 64,))
        else:
            connection.execute(
                "UPDATE revisions SET content_sha256=? WHERE spec_id='other'", ("f" * 64,),
            )
    before = sql_state(workspace)
    with pytest.raises(IdentityStoreError):
        store.identity_history(spec_id="demo")
    assert sql_state(workspace) == before
