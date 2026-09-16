"""Binding queries on the caller's connection; no transaction or file ownership."""

from dataclasses import fields
import json

from harness import element_identity_bindings as bindings
from harness import element_identity_store as authority
from harness.element_identity_lifecycle import text
from harness.issue_identity import issue_fingerprint


_TYPES = {"reference_claims": bindings.ReferenceClaim, "issue_occurrences": bindings.IssueOccurrence}


def _target(connection, store, spec_id, payload, method, projected_view=None):
    reference = method == "reference_claims"
    label = payload["target_id" if reference else "issue_id"]
    revision = payload["target_revision" if reference else "issue_revision"]
    kind, ordinal = authority._parse_label(label)
    store._high_water(connection, spec_id, kind)
    head = (store._head(connection, spec_id, label) if projected_view is None
            else projected_view.head(label))
    if head is None:
        raise ValueError("binding entity must already exist in the same spec")
    text(head["subject"], "stored subject")
    if (head["kind"], head["ordinal"]) != (kind, ordinal):
        raise ValueError("identity label, kind and ordinal binding disagree")
    if revision is not None:
        historical = (store._revision(connection, spec_id, label, revision)
                      if projected_view is None else projected_view.revision(label, revision))
        if historical is None:
            raise ValueError("binding requires an existing assessed revision")
        if not reference and (historical["status"] != "active" or historical["subject"] != payload["title"]
                              or historical["content"] != payload["body"]):
            raise ValueError("occurrence must match exact historical active issue content")
    return head


def _entry(spec_id, operation_id, index, payload, method):
    result = {"spec_id": spec_id, "operation_id": operation_id, "entry_index": authority._decimal(index), **payload}
    if method == "issue_occurrences":
        result["issue_fingerprint"] = issue_fingerprint(payload["title"], payload["body"])
    return result


def materialized_row(spec_id, operation_id, index, payload, method):
    result = _entry(spec_id, operation_id, index, payload, method)
    return result | {"payload_sha256": authority._digest([method, result])}


def receipt(connection, store, method, spec_id, operation_id):
    """Authenticate complete retained operation, including all record associations."""
    operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                   (operation_id,)).fetchone()
    saved = connection.execute("SELECT receipt,receipt_sha256 FROM binding_receipts WHERE operation_id=?",
                               (operation_id,)).fetchone()
    if operation is None or tuple(operation)[:2] != (method, spec_id) or saved is None:
        raise ValueError("binding operation/receipt association is missing or inconsistent")
    # Table name is selected exclusively by an internal method constant.
    rows = connection.execute(f"SELECT * FROM {method} WHERE operation_id=? "
                              "ORDER BY length(entry_index),entry_index", (operation_id,)).fetchall()
    if not rows:
        raise ValueError("binding operation is missing its records")
    payloads, results = [], []
    entry_type = _TYPES[method]
    for index, row in enumerate(rows, 1):
        payload = {field.name: row[field.name] for field in fields(entry_type)}
        entry_type(**payload)
        result = _entry(spec_id, operation_id, index, payload, method)
        if dict(row) != materialized_row(spec_id, operation_id, index, payload, method):
            raise ValueError("binding record payload or operation binding is damaged")
        _target(connection, store, spec_id, payload, method)
        payloads.append(payload)
        results.append(result)
    bindings.request(tuple(entry_type(**payload) for payload in payloads), entry_type)
    if operation["digest"] != authority._digest([method, spec_id, operation_id, payloads]):
        raise ValueError("binding operation request digest is inconsistent")
    if saved["receipt"] != authority._json(results) or saved["receipt_sha256"] != authority._digest(results):
        raise ValueError("binding receipt is damaged or missing record associations")
    return tuple(json.loads(saved["receipt"]))


def record(connection, store, method, spec_id, operation_id, payloads):
    """Caller validates the immutable batch and owns its single write transaction."""
    digest = authority._digest([method, spec_id, operation_id, payloads])
    if store._operation(connection, operation_id, method, spec_id, digest):
        return receipt(connection, store, method, spec_id, operation_id)
    results = []
    for index, payload in enumerate(payloads, 1):
        _target(connection, store, spec_id, payload, method)
        result = _entry(spec_id, operation_id, index, payload, method)
        row = materialized_row(spec_id, operation_id, index, payload, method)
        connection.execute(f"INSERT INTO {method} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                           tuple(row.values()))
        results.append(result)
    connection.execute("INSERT INTO binding_receipts (operation_id,receipt,receipt_sha256) VALUES (?,?,?)",
                       (operation_id, authority._json(results), authority._digest(results)))
    return tuple(results)


def read(connection, store, method, spec_id, parameters):
    predicate = "source_path=? AND source_sha256=?" if method == "reference_claims" else "issue_id=?"
    rows = connection.execute(f"SELECT operation_id,entry_index FROM {method} WHERE spec_id=? AND {predicate} "
                              "ORDER BY operation_id,length(entry_index),entry_index", (spec_id, *parameters))
    operations, result = {}, []
    for operation_id, entry_index in rows:
        if operation_id not in operations:
            operations[operation_id] = {entry["entry_index"]: entry for entry in
                receipt(connection, store, method, spec_id, operation_id)}
        entry = dict(operations[operation_id][entry_index])
        if method == "reference_claims":
            head = _target(connection, store, spec_id, entry, method)
            entry.update(target_status=head["status"], target_revision_matches_current=(
                entry["target_revision"] is not None and entry["target_revision"] == head["revision"]
                and head["status"] == "active" and head.get("present") is not False))
            if "present" in head:
                entry["target_present"] = head["present"]
        result.append(entry)
    return tuple(result)


def audit(connection, store):
    """Full scans only at explicit audit/upgrade/restore, including orphan rows."""
    operations = connection.execute("SELECT operation_id FROM binding_receipts UNION "
        "SELECT operation_id FROM reference_claims UNION SELECT operation_id FROM issue_occurrences UNION "
        "SELECT operation_id FROM operations WHERE method IN ('reference_claims','issue_occurrences')")
    for (operation_id,) in operations:
        operation = connection.execute("SELECT method,spec_id FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if operation is None or operation["method"] not in _TYPES:
            raise ValueError("binding records have a missing or conflicting operation")
        other = "issue_occurrences" if operation["method"] == "reference_claims" else "reference_claims"
        if connection.execute(f"SELECT 1 FROM {other} WHERE operation_id=? LIMIT 1", (operation_id,)).fetchone():
            raise ValueError("binding operation is associated with a different record method")
        receipt(connection, store, operation["method"], operation["spec_id"], operation_id)
