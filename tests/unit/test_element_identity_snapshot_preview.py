from contextlib import closing, contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import json
import sqlite3
import sys

import pytest

from harness import element_identity_lifecycle_store as lifecycle_store
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.element_identity_lifecycle import (
    ElementCreate, ElementAdopt, ElementRevision, ElementRetirement, ElementTransition,
)
from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence
from harness.element_identity_publication import PublicationOperation, PublicationIntentRequest
from harness.element_identity_request_codec import encode_request


pytestmark = pytest.mark.unit
HASH = "a" * 64


def sql_state(path):
    with closing(sqlite3.connect(path / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(encoded(value).encode("ascii")).hexdigest()


def empty_expected(path, spec="demo"):
    marker = json.loads((path / ".echelon/identity/authority.json").read_text())
    return dict(version="1", workspace_uuid=marker["workspace_uuid"], epoch_uuid=marker["epoch_uuid"],
                spec_id=spec, entities=[], revisions=[], lineage=[], reference_claims=[], issue_occurrences=[])


def entity(label, kind, ordinal, subject, status="active", revision="1", spec="demo"):
    return dict(spec_id=spec, element_id=label, kind=kind, ordinal=ordinal,
                subject=subject, status=status, revision=revision)


def revision(label, number, subject, content, operation, status="active", reason=None, spec="demo"):
    return dict(spec_id=spec, element_id=label, revision=number, subject=subject, content=content,
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                status=status, reason=reason, operation_id=operation)


def op(method, operation_id, *entries):
    return PublicationOperation(method, operation_id, encode_request(method, entries))


def assert_exact(snapshot, expected):
    assert json.loads(snapshot.payload) == expected
    assert snapshot.payload == encoded(expected)
    assert snapshot.sha256 == digest(expected)


def apply_and_compare(store, path, operations, expected, publication="publication", spec="demo"):
    before = sql_state(path)
    retained = store.identity_history(spec_id=spec)
    proposed = store.preview_identity_history(spec_id=spec, operations=operations)
    assert_exact(proposed, expected)
    assert sql_state(path) == before
    assert store.identity_history(spec_id=spec) == retained
    store.prepare_identity_publication(spec_id=spec, operation_id=publication,
        request=PublicationIntentRequest(HASH, "test recovery", operations))
    assert store.identity_history(spec_id=spec) == retained
    store.apply_identity_publication(spec_id=spec, operation_id=publication)
    assert proposed == store.identity_history(spec_id=spec)
    store = IdentityStore.open(path)
    assert proposed == store.identity_history(spec_id=spec)
    store.release_identity_publication(spec_id=spec, operation_id=publication, completion_payload="complete")
    assert proposed == store.identity_history(spec_id=spec)
    return proposed


def test_preview_matches_real_journal_application(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    changes = (ElementCreate(label, "Scene", "Initial scene", "reserve"),)
    operation = PublicationOperation("lifecycle", "create", encode_request("lifecycle", changes))
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity("FR-000001", "FR", "1", "Scene")]
    expected["revisions"] = [revision("FR-000001", "1", "Scene", "Initial scene", "create")]
    proposed = apply_and_compare(store, tmp_path, (operation,), expected)
    with pytest.raises(FrozenInstanceError):
        proposed.payload = "changed"
    decoded = json.loads(proposed.payload)
    decoded["entities"][0]["subject"] = "changed"
    assert_exact(proposed, expected)


def test_empty_reserved_imported_all_families_and_explicit_adoption(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    expected = empty_expected(tmp_path)
    assert_exact(store.preview_identity_history(spec_id="demo"), expected)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    apply_and_compare(store, tmp_path, (), expected, "empty")
    definitions = (("A-old", "Assumption"), ("AC-001", "Acceptance"), ("FR-999999", "Legacy"),
                   ("FR-1000000", "Wide"), ("FR-opaque", "Opaque"), ("ISS-old", "Issue"),
                   ("NFR-000009", "Constraint"), ("T-S01", "Task"), ("U-old", "Unknown"))
    store.import_identities(spec_id="demo", operation_id="import", definitions=definitions)
    expected["entities"] = [entity(label, kind, ordinal, subject, "imported", None)
        for label, kind, ordinal, subject in (
            ("A-old", "A", None, "Assumption"), ("AC-001", "AC", "1", "Acceptance"),
            ("FR-999999", "FR", "999999", "Legacy"), ("FR-1000000", "FR", "1000000", "Wide"),
            ("FR-opaque", "FR", None, "Opaque"), ("ISS-old", "ISS", None, "Issue"),
            ("NFR-000009", "NFR", "9", "Constraint"), ("T-S01", "T", None, "Task"),
            ("U-old", "U", None, "Unknown"))]
    apply_and_compare(store, tmp_path, (), expected, "imported")
    operations = (op("lifecycle", "adopt", ElementAdopt("U-old", "Unknown", "Assessed naïve body")),)
    expected["entities"][-1].update(status="active", revision="1")
    expected["revisions"] = [revision("U-old", "1", "Unknown", "Assessed naïve body", "adopt")]
    apply_and_compare(store, tmp_path, operations, expected, "adoption")


def test_every_lifecycle_transition_preserves_complete_history(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    labels = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=5)
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity(labels[0], "FR", "1", "One")]
    expected["revisions"] = [revision(labels[0], "1", "One", "Body", "create")]
    apply_and_compare(store, tmp_path, (op("lifecycle", "create", ElementCreate(labels[0], "One", "Body", "reserve")),), expected, "p-create")
    # Explicit independent rows also make revision/lineage ordering mistakes visible.
    expected["entities"][0].update(status="superseded", revision="2")
    expected["entities"].append(entity(labels[1], "FR", "2", "Two"))
    expected["revisions"].extend([revision(labels[0], "2", "One", "Body", "replace", "superseded", "replace reason"),
                                  revision(labels[1], "1", "Two", "Body two", "replace")])
    expected["lineage"].append(dict(spec_id="demo", predecessor_id=labels[0], predecessor_revision="1",
        successor_id=labels[1], successor_revision="1", kind="replace", reason="replace reason", operation_id="replace"))
    apply_and_compare(store, tmp_path, (op("lifecycle", "replace", ElementTransition("replace", ((labels[0], "1"),),
        (ElementCreate(labels[1], "Two", "Body two", "reserve"),), "replace reason")),), expected, "p-replace")
    expected["entities"][1].update(status="superseded", revision="2")
    expected["entities"].extend([entity(labels[2], "FR", "3", "Three"), entity(labels[3], "FR", "4", "Four")])
    expected["revisions"].extend([revision(labels[1], "2", "Two", "Body two", "split", "superseded", "split reason"),
        revision(labels[2], "1", "Three", "Body three", "split"), revision(labels[3], "1", "Four", "Body four", "split")])
    expected["lineage"].extend(dict(spec_id="demo", predecessor_id=labels[1], predecessor_revision="1",
        successor_id=successor, successor_revision="1", kind="split", reason="split reason", operation_id="split")
        for successor in (labels[2], labels[3]))
    apply_and_compare(store, tmp_path, (op("lifecycle", "split", ElementTransition("split", ((labels[1], "1"),), (
        ElementCreate(labels[2], "Three", "Body three", "reserve"), ElementCreate(labels[3], "Four", "Body four", "reserve")),
        "split reason")),), expected, "p-split")
    expected["entities"][2].update(status="superseded", revision="2")
    expected["entities"][3].update(status="superseded", revision="2")
    expected["entities"].append(entity(labels[4], "FR", "5", "Five"))
    expected["revisions"].insert(5, revision(labels[2], "2", "Three", "Body three", "merge", "superseded", "merge reason"))
    expected["revisions"].extend([revision(labels[3], "2", "Four", "Body four", "merge", "superseded", "merge reason"),
                                  revision(labels[4], "1", "Five", "Body five", "merge")])
    expected["lineage"].extend(dict(spec_id="demo", predecessor_id=predecessor, predecessor_revision="1",
        successor_id=labels[4], successor_revision="1", kind="merge", reason="merge reason", operation_id="merge")
        for predecessor in (labels[2], labels[3]))
    apply_and_compare(store, tmp_path, (op("lifecycle", "merge", ElementTransition("merge", ((labels[2], "1"), (labels[3], "1")),
        (ElementCreate(labels[4], "Five", "Body five", "reserve"),), "merge reason")),), expected, "p-merge")
    expected["entities"][-1].update(revision="2")
    expected["revisions"].append(revision(labels[4], "2", "Five", "Révision", "revise"))
    apply_and_compare(store, tmp_path, (op("lifecycle", "revise", ElementRevision(labels[4], "1", "Five", "Révision")),), expected, "p-revise")
    expected["entities"][-1].update(status="retired", revision="3")
    expected["revisions"].append(revision(labels[4], "3", "Five", "Révision", "retire", "retired", "retirement reason"))
    apply_and_compare(store, tmp_path, (op("lifecycle", "retire", ElementRetirement(labels[4], "2", "retirement reason")),), expected, "p-retire")


def expected_claim(operation, index, target, target_revision, relation="evidence", anchor="span:0"):
    row = dict(operation_id=operation, entry_index=str(index), spec_id="demo", source_path="evidence.md",
               source_sha256=HASH, source_anchor=anchor, target_id=target, target_revision=target_revision,
               relation=relation)
    return row | {"payload_sha256": digest(["reference_claims", row])}


def expected_occurrence(operation, index, label, number, title, body):
    # Independently specified simple-title/body fingerprint wire, not the production fingerprint helper.
    fingerprint = hashlib.sha256(json.dumps(dict(version=1, title=title, body=body, fields={}), sort_keys=True).encode()).hexdigest()
    row = dict(operation_id=operation, entry_index=str(index), spec_id="demo", issue_id=label,
               issue_revision=number, report_id=f"report-{index}", report_sha256=HASH,
               display_id=f"ISS-{index}", title=title, body=body, issue_fingerprint=fingerprint)
    return row | {"payload_sha256": digest(["issue_occurrences", row])}


def test_projected_bindings_old_evidence_historical_issues_and_none_are_exact(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    fr, = store.reserve(spec_id="demo", kind="FR", operation_id="r-fr", count=1)
    iss, = store.reserve(spec_id="demo", kind="ISS", operation_id="r-iss", count=1)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("U-old", "Unknown"),))
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(fr, "Scene", "Old body", "r-fr"), ElementCreate(iss, "Issue", "Old issue", "r-iss")))
    store.record_reference_claims(spec_id="demo", operation_id="old-evidence", claims=(
        ReferenceClaim("evidence.md", HASH, "span:0", fr, "1", "evidence"),))
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity(fr, "FR", "1", "Scene", revision="2"), entity(iss, "ISS", "1", "Issue", revision="2"),
                            entity("U-old", "U", None, "Unknown", "imported", None)]
    expected["revisions"] = [revision(fr, "1", "Scene", "Old body", "create"), revision(fr, "2", "Scene", "New body", "life"),
        revision(iss, "1", "Issue", "Old issue", "create"), revision(iss, "2", "Issue", "New issue", "life")]
    claims = tuple(ReferenceClaim("evidence.md", HASH, f"span:{i}", "U-old" if i == 1 else fr,
                    None if i == 1 else "2", "requires") for i in range(1, 13))
    expected["reference_claims"] = [expected_claim("claims", i, "U-old" if i == 1 else fr,
        None if i == 1 else "2", "requires", f"span:{i}") for i in range(1, 13)] + [expected_claim("old-evidence", 1, fr, "1")]
    occurrences = tuple(IssueOccurrence(iss, "2", f"report-{i}", HASH, f"ISS-{i}", "Issue", "New issue") for i in range(1, 13))
    expected["issue_occurrences"] = [expected_occurrence("occurrences", i, iss, "2", "Issue", "New issue") for i in range(1, 13)]
    operations = (op("lifecycle", "life", ElementRevision(fr, "1", "Scene", "New body"), ElementRevision(iss, "1", "Issue", "New issue")),
                  op("reference_claims", "claims", *claims), op("issue_occurrences", "occurrences", *occurrences))
    proposed = apply_and_compare(store, tmp_path, operations, expected)
    # A retired head still permits explicitly historical active occurrences and None/old references.
    expected["entities"][0].update(status="retired", revision="3")
    expected["entities"][1].update(status="retired", revision="3")
    expected["revisions"].insert(2, revision(fr, "3", "Scene", "New body", "retire", "retired", "done"))
    expected["revisions"].append(revision(iss, "3", "Issue", "New issue", "retire", "retired", "done"))
    expected["reference_claims"].extend([expected_claim("z-claims", 1, fr, "1", "depends"), expected_claim("z-claims", 2, fr, None, "requires", "none")])
    expected["issue_occurrences"].append(expected_occurrence("z-occurrences", 1, iss, "1", "Issue", "Old issue"))
    apply_and_compare(store, tmp_path, (
        op("lifecycle", "retire", ElementRetirement(fr, "2", "done"), ElementRetirement(iss, "2", "done")),
        op("reference_claims", "z-claims", ReferenceClaim("evidence.md", HASH, "span:0", fr, "1", "depends"),
           ReferenceClaim("evidence.md", HASH, "none", fr, None, "requires")),
        op("issue_occurrences", "z-occurrences", IssueOccurrence(iss, "1", "report-1", HASH, "ISS-1", "Issue", "Old issue")),
    ), expected, "retirement")
    assert json.loads(proposed.payload)["entities"][0]["status"] == "active"


def test_wide_ordinal_revision_order_and_new_seven_digit_creation(tmp_path):
    limit = sys.get_int_max_str_digits()
    huge = "1" + "0" * 4999
    store = IdentityStore.initialize(tmp_path)
    labels = ("FR-9", "FR-10", "FR-999999", "FR-1000000", f"FR-{huge}", "FR-opaque")
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple((label, "Legacy") for label in labels))
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity(label, "FR", ordinal, "Legacy", "imported", None)
                             for label, ordinal in zip(labels, ("9", "10", "999999", "1000000", huge, None))]
    numbers = ("9", "10", "999999", "1000000", huge)
    # Authenticated sparse legacy rows exercise arbitrary-width history without billions of writes.
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        for index, number in enumerate(numbers):
            row = revision("FR-9", number, "Legacy", "Body", f"fixture-{index}")
            connection.execute("INSERT INTO operations VALUES (?,?,?,?)", (f"fixture-{index}", "lifecycle", "demo", "fixture digest"))
            connection.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)", tuple(row.values()))
            receipt = [dict(element_id="FR-9", revision=number, status="active", lineage=[])]
            connection.execute("INSERT INTO lifecycle_receipts VALUES (?,?,?)", (f"fixture-{index}", encoded(receipt), digest(receipt)))
            expected["revisions"].append(row)
        connection.execute("UPDATE lifecycle_heads SET status='active',revision=? WHERE element_id='FR-9'", (huge,))
    expected["entities"][0].update(status="active", revision=huge[:-1] + "1")
    expected["revisions"].append(revision("FR-9", huge[:-1] + "1", "Legacy", "Later", "wide-revise"))
    apply_and_compare(store, tmp_path, (op("lifecycle", "wide-revise", ElementRevision("FR-9", huge, "Legacy", "Later")),), expected)
    assert sys.get_int_max_str_digits() == limit
    store.import_identities(spec_id="seven", operation_id="seven-import", definitions=(("AC-999999", "Legacy"),))
    label, = store.reserve(spec_id="seven", kind="AC", operation_id="seven-reserve", count=1)
    assert label == "AC-1000000"
    expected = empty_expected(tmp_path, "seven")
    expected["entities"] = [entity("AC-999999", "AC", "999999", "Legacy", "imported", None, "seven"),
                            entity("AC-1000000", "AC", "1000000", "New", spec="seven")]
    expected["revisions"] = [revision("AC-1000000", "1", "New", "Body", "seven-create", spec="seven")]
    apply_and_compare(store, tmp_path, (op("lifecycle", "seven-create", ElementCreate(label, "New", "Body", "seven-reserve")),),
                      expected, "seven-publication", "seven")


@pytest.mark.parametrize("case", ["stale", "subject", "unreserved", "alias", "missing-target", "missing-revision", "wrong-issue", "terminal-issue"])
def test_invalid_planned_effects_leave_every_table_unchanged_and_release_locks(tmp_path, case):
    store = IdentityStore.initialize(tmp_path)
    fr, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    iss, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(fr, "Scene", "Body", "reserve"), ElementCreate(iss, "Issue", "Body", "reserve-issue")))
    operations = {
        "stale": (op("lifecycle", "new", ElementRevision(fr, "2", "Scene", "Later")),),
        "subject": (op("lifecycle", "new", ElementRevision(fr, "1", "Changed", "Later")),),
        "unreserved": (op("lifecycle", "new", ElementCreate("FR-000002", "Other", "Body", "reserve")),),
        "alias": (op("lifecycle", "new", ElementCreate("FR-001", "Other", "Body", "reserve")),),
        "missing-target": (op("reference_claims", "new", ReferenceClaim("evidence.md", HASH, "a", "FR-000002", None, "reference")),),
        "missing-revision": (op("reference_claims", "new", ReferenceClaim("evidence.md", HASH, "a", fr, "2", "reference")),),
        "wrong-issue": (op("lifecycle", "new", ElementRevision(iss, "1", "Issue", "Later")),
            op("issue_occurrences", "occ", IssueOccurrence(iss, "2", "report", HASH, "ISS-1", "Issue", "Wrong"))),
        "terminal-issue": (op("lifecycle", "new", ElementRetirement(iss, "1", "done")),
            op("issue_occurrences", "occ", IssueOccurrence(iss, "2", "report", HASH, "ISS-1", "Issue", "Body"))),
    }[case]
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo", operations=operations)
    assert sql_state(tmp_path) == before
    store.apply_lifecycle(spec_id="demo", operation_id="valid-after-failure", changes=(ElementRevision(fr, "1", "Scene", "Later"),))
    assert store.lookup(spec_id="demo", element_id=fr)["revision"] == "2"


def damaged_operation(**changes):
    value = op("lifecycle", "new", ElementCreate("FR-000001", "Scene", "Body", "reserve"))
    for key, replacement in changes.items():
        object.__setattr__(value, key, replacement)
    return value


@pytest.mark.parametrize("case", ["list", "none", "tuple-subclass", "record-subclass", "missing-field", "method", "id", "payload-type", "malformed", "noncanonical", "damaged-entry", "duplicate-method", "reordered", "duplicate-id"])
def test_operation_shape_and_codec_damage_fail_before_transaction(tmp_path, monkeypatch, case):
    store = IdentityStore.initialize(tmp_path)
    first = damaged_operation()
    claim = op("reference_claims", "refs", ReferenceClaim("evidence.md", HASH, "a", "FR-000001", None, "reference"))
    class Tuple(tuple):
        pass
    class Record(PublicationOperation):
        pass
    subclass = object.__new__(Record)
    for key in ("method", "operation_id", "payload"):
        object.__setattr__(subclass, key, getattr(first, key))
    missing = object.__new__(PublicationOperation)
    cases = {"list": [first], "none": None, "tuple-subclass": Tuple((first,)), "record-subclass": (subclass,),
        "missing-field": (missing,), "method": (damaged_operation(method="unknown"),), "id": (damaged_operation(operation_id=""),),
        "payload-type": (damaged_operation(payload=1),), "malformed": (damaged_operation(payload="["),),
        "noncanonical": (damaged_operation(payload=first.payload + " "),),
        "damaged-entry": (damaged_operation(payload=first.payload.replace('"subject":"Scene"', '"subject":false')),),
        "duplicate-method": (first, damaged_operation(operation_id="second")), "reordered": (claim, first),
        "duplicate-id": (first, op("reference_claims", "new", ReferenceClaim("evidence.md", HASH, "a", "FR-000001", None, "reference")))}
    monkeypatch.setattr(store, "_transaction", lambda **kw: pytest.fail("invalid input opened transaction"))
    with pytest.raises(IdentityStoreError) as caught:
        store.preview_identity_history(spec_id="demo", operations=cases[case])
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert len(str(caught.value)) < 100


@pytest.mark.parametrize("spec", [None, "", " ", "bad\x00id", b"demo", 1, True, [], "\ud800", type("Spec", (str,), {})("demo")])
def test_exact_spec_validation_precedes_transaction(tmp_path, monkeypatch, spec):
    store = IdentityStore.initialize(tmp_path)
    monkeypatch.setattr(store, "_transaction", lambda **kw: pytest.fail("invalid input opened transaction"))
    with pytest.raises(IdentityStoreError) as caught:
        store.preview_identity_history(spec_id=spec)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("owner_spec", ["demo", "other"])
@pytest.mark.parametrize("state", ["ordinary", "prepared", "applied", "released"])
def test_global_old_operations_and_permanent_child_claims_are_never_replayed(tmp_path, owner_spec, state):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=owner_spec, kind="FR", operation_id="reserve", count=1)
    operation = op("lifecycle", "claimed", ElementCreate(label, "Scene", "Body", "reserve"))
    if state == "ordinary":
        store.apply_lifecycle(spec_id=owner_spec, operation_id="claimed", changes=(ElementCreate(label, "Scene", "Body", "reserve"),))
    else:
        store.prepare_identity_publication(spec_id=owner_spec, operation_id="parent", request=PublicationIntentRequest(HASH, "recover", (operation,)))
        if state in {"applied", "released"}:
            store.apply_identity_publication(spec_id=owner_spec, operation_id="parent")
        if state == "released":
            store.release_identity_publication(spec_id=owner_spec, operation_id="parent", completion_payload="complete")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo", operations=(operation,))
    assert sql_state(tmp_path) == before
    if owner_spec == "other":
        assert_exact(store.preview_identity_history(spec_id="demo"), empty_expected(tmp_path))


@pytest.mark.parametrize("applied", [False, True])
def test_pending_same_spec_rejects_even_empty_preview_but_retained_history_remains(tmp_path, applied):
    store = IdentityStore.initialize(tmp_path)
    before_history = store.identity_history(spec_id="demo")
    store.prepare_identity_publication(spec_id="demo", operation_id="pending", request=PublicationIntentRequest(HASH, "recover"))
    if applied:
        store.apply_identity_publication(spec_id="demo", operation_id="pending")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo")
    assert sql_state(tmp_path) == before
    assert store.identity_history(spec_id="demo") == before_history
    assert_exact(store.preview_identity_history(spec_id="other"), empty_expected(tmp_path, "other"))


def test_detaches_operation_values_before_transaction(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    operation = damaged_operation()
    transaction = store._transaction
    @contextmanager
    def mutate_caller_value():
        object.__setattr__(operation, "payload", "broken after validation")
        with transaction() as connection:
            yield connection
    monkeypatch.setattr(store, "_transaction", mutate_caller_value)
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity("FR-000001", "FR", "1", "Scene")]
    expected["revisions"] = [revision("FR-000001", "1", "Scene", "Body", "new")]
    assert_exact(store.preview_identity_history(spec_id="demo", operations=(operation,)), expected)


def test_one_query_only_transaction_rejects_actual_planner_write_and_cleans_up(tmp_path, monkeypatch):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    before = sql_state(tmp_path)
    transaction, planner = store._transaction, lifecycle_store.plan_changes
    calls, statements = [], []
    @contextmanager
    def tracked(**arguments):
        calls.append(arguments)
        with transaction(**arguments) as connection:
            connection.set_trace_callback(statements.append)
            yield connection
    def attempted_write(connection, *args, **kwargs):
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO operations VALUES ('forbidden','reserve','demo','x')")
        return planner(connection, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(store, "_transaction", tracked)
        context.setattr(lifecycle_store, "plan_changes", attempted_write)
        snapshot = store.preview_identity_history(spec_id="demo", operations=(damaged_operation(),))
    assert calls == [{}]
    assert sum(statement.strip().upper() == "PRAGMA QUERY_ONLY=ON" for statement in statements) == 1
    assert not any(statement.lstrip().upper().startswith(("SAVEPOINT", "ATTACH", "VACUUM")) for statement in statements)
    assert sql_state(tmp_path) == before
    store.apply_lifecycle(spec_id="demo", operation_id="new", changes=(ElementCreate("FR-000001", "Scene", "Body", "reserve"),))
    assert store.identity_history(spec_id="demo") == snapshot


@pytest.mark.parametrize("failure", [ValueError("private " * 1000), RuntimeError("private"), AttributeError("private"), OSError("private"), sqlite3.DatabaseError("private"), KeyboardInterrupt(), SystemExit(7)])
def test_helper_failures_are_bounded_without_context_and_baseexceptions_are_identical(tmp_path, monkeypatch, failure):
    from harness import element_identity_snapshot_preview as preview_module
    store = IdentityStore.initialize(tmp_path)
    before = sql_state(tmp_path)
    def fail(*args, **kwargs):
        raise failure
    with monkeypatch.context() as context:
        context.setattr(preview_module, "preview", fail)
        with pytest.raises(IdentityStoreError if isinstance(failure, Exception) else type(failure)) as caught:
            store.preview_identity_history(spec_id="demo")
    if isinstance(failure, Exception):
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert "private" not in str(caught.value) and len(str(caught.value)) < 100
    else:
        assert caught.value is failure
    assert sql_state(tmp_path) == before
    store.reserve(spec_id="demo", kind="FR", operation_id="after-failure", count=1)


def test_full_audit_rejects_other_spec_damage_without_mutation(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="other", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="other", operation_id="create", changes=(ElementCreate("FR-000001", "Scene", "Body", "reserve"),))
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE revisions SET content_sha256=?", ("f" * 64,))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError) as caught:
        store.preview_identity_history(spec_id="demo")
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert sql_state(tmp_path) == before


def test_preview_never_calls_writers_source_or_provider_paths(tmp_path, monkeypatch):
    import builtins
    from harness import element_identity_binding_store as binding_store
    from harness import element_identity_publication_store as publication_store
    from harness import element_identity_source_store as source_store
    from harness import element_identity_managed_store as managed_store
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    before = sql_state(tmp_path)
    original_import, original_connect = builtins.__import__, sqlite3.connect
    connections = []
    def forbidden(*args, **kwargs):
        pytest.fail("preview invoked a write/source/runtime path")
    def guarded_import(name, *args, **kwargs):
        if name.startswith(("harness.state", "harness.llm_provider", "harness.delivery_controller", "harness.ralph")):
            forbidden()
        return original_import(name, *args, **kwargs)
    class GuardedConnection(sqlite3.Connection):
        def backup(self, *args, **kwargs):
            forbidden()
        def execute(self, sql, *args, **kwargs):
            if sql.lstrip().upper().startswith(("SAVEPOINT", "ATTACH", "VACUUM")):
                forbidden()
            return super().execute(sql, *args, **kwargs)
    def connect(*args, **kwargs):
        connections.append(args)
        return original_connect(*args, **kwargs, factory=GuardedConnection)
    with monkeypatch.context() as context:
        for name in ("_operation", "reserve", "apply_lifecycle", "record_reference_claims", "record_issue_occurrences",
                     "prepare_identity_publication", "apply_identity_publication", "release_identity_publication", "backup", "restore"):
            context.setattr(store, name, forbidden)
        for owner, names in ((lifecycle_store, ("apply_changes",)), (binding_store, ("record",)),
                             (publication_store, ("prepare", "apply", "release")),
                             (source_store, ("prepare",)), (managed_store, ("register",))):
            for name in names:
                context.setattr(owner, name, forbidden)
        context.setattr(builtins, "__import__", guarded_import)
        context.setattr(sqlite3, "connect", connect)
        snapshot = store.preview_identity_history(spec_id="demo", operations=(damaged_operation(),
            op("reference_claims", "claims", ReferenceClaim("evidence.md", HASH, "span:0", "FR-000001", "1", "evidence"))))
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity("FR-000001", "FR", "1", "Scene")]
    expected["revisions"] = [revision("FR-000001", "1", "Scene", "Body", "new")]
    expected["reference_claims"] = [expected_claim("claims", 1, "FR-000001", "1")]
    assert_exact(snapshot, expected)
    assert len(connections) == 1
    assert sql_state(tmp_path) == before


def test_preview_does_not_hold_baseline_and_fresh_request_observes_later_revision(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate("FR-000001", "Scene", "Body", "reserve"),))
    operation = op("lifecycle", "proposed", ElementRevision("FR-000001", "1", "Scene", "Proposed"))
    old = store.preview_identity_history(spec_id="demo", operations=(operation,))
    old_payload = old.payload
    store.apply_lifecycle(spec_id="demo", operation_id="intervening", changes=(ElementRevision("FR-000001", "1", "Scene", "Intervening"),))
    accepted = store.identity_history(spec_id="demo")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.preview_identity_history(spec_id="demo", operations=(operation,))
    with pytest.raises(IdentityStoreError):
        store.prepare_identity_publication(spec_id="demo", operation_id="stale-parent", request=PublicationIntentRequest(HASH, "recover", (operation,)))
    assert sql_state(tmp_path) == before
    expected = empty_expected(tmp_path)
    expected["entities"] = [entity("FR-000001", "FR", "1", "Scene", revision="3")]
    expected["revisions"] = [revision("FR-000001", "1", "Scene", "Body", "create"),
                            revision("FR-000001", "2", "Scene", "Intervening", "intervening"),
                            revision("FR-000001", "3", "Scene", "Proposed", "proposed")]
    apply_and_compare(store, tmp_path, (op("lifecycle", "proposed", ElementRevision("FR-000001", "2", "Scene", "Proposed")),), expected)
    assert old.payload == old_payload and old.sha256 == hashlib.sha256(old_payload.encode("ascii")).hexdigest()
    assert json.loads(accepted.payload)["entities"][0]["revision"] == "2"


def test_graph_rendering_before_sealing_equals_actual_history_and_keeps_old_evidence(tmp_path):
    from echelon.spec_graph import GraphNode, SpecArtifactGraph, render_spec_graph
    from echelon.spec_graph_identity import project_identity_history
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.import_identities(spec_id="demo", operation_id="tasks", definitions=(("T-S01", "Task"),))
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate("FR-000001", "Scene", "Old body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(ReferenceClaim("evidence.md", HASH, "span:0", "FR-000001", "1", "evidence"),))
    operations = (op("lifecycle", "revise", ElementRevision("FR-000001", "1", "Scene", "New body")),)
    proposed = store.preview_identity_history(spec_id="demo", operations=operations)
    base = SpecArtifactGraph("demo", "test", (), (
        GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
        GraphNode("req:demo:FR-000001", "Requirement", {"requirement_id": "FR-000001"}),
        GraphNode("task:demo:T-S01", "Task", {"task_id": "T-S01", "status": "done"}),
    ), (), ())
    projected = project_identity_history(base, proposed)
    rendered = render_spec_graph(projected)
    store.prepare_identity_publication(spec_id="demo", operation_id="parent", request=PublicationIntentRequest(HASH, "recover", operations))
    store.apply_identity_publication(spec_id="demo", operation_id="parent")
    assert rendered == render_spec_graph(project_identity_history(base, store.identity_history(spec_id="demo")))
    store = IdentityStore.open(tmp_path)
    store.release_identity_publication(spec_id="demo", operation_id="parent", completion_payload="complete")
    assert rendered == render_spec_graph(project_identity_history(base, store.identity_history(spec_id="demo")))
    assert [node.id for node in projected.nodes[:3]] == [node.id for node in base.nodes]
    assert projected.nodes[2].properties["status"] == "done"
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    old = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "1")
    new = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "2")
    assert claim.properties["target_revision_matches_current"] is False
    assert any(edge.source == claim.id and edge.type == "ASSESSES_REVISION" and edge.target == old.id for edge in projected.edges)
    assert not any(edge.source == claim.id and edge.type == "ASSESSES_REVISION" and edge.target == new.id for edge in projected.edges)
    assert "identity" not in base.nodes[1].properties
