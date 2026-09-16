"""Snapshot membership rows owned by the existing lifecycle transaction.

No independent writer, allocation, filesystem, or candidate-selection authority.
"""
from harness import element_identity_lifecycle as lifecycle


def available(connection):
    # Old authorities are inspected only during explicit upgrade/restore audit.
    return connection.execute("SELECT 1 FROM sqlite_master WHERE name='snapshot_memberships'").fetchone() is not None


def rows(connection, *, spec_id=None, operation_id=None):
    if not available(connection):
        return []
    field, value = ("operation_id", operation_id) if operation_id is not None else ("spec_id", spec_id)
    result = [dict(row) for row in connection.execute(
        f"SELECT * FROM snapshot_memberships WHERE {field}=? ORDER BY element_id,length(revision),revision", (value,))]
    for row in result:
        row["present"] = bool(row["present"])
    return result


def current(connection, spec_id, element_id, revision=None):
    if not available(connection):
        return None
    params = [spec_id, element_id]
    bound = ""
    if revision is not None:
        bound = " AND (length(revision),revision)<=(?,?)"
        params.extend((len(revision), revision))
    row = connection.execute(
        "SELECT present FROM snapshot_memberships WHERE spec_id=? AND element_id=?" + bound +
        " ORDER BY length(revision) DESC,revision DESC LIMIT 1", params).fetchone()
    return None if row is None else bool(row[0])


def planned_rows(spec_id, operation_id, changes, planned):
    revisions = {row[0]: row[1] for row in planned}
    return [dict(spec_id=spec_id, element_id=change.element_id, revision=revisions[change.element_id],
                 present=change.present, source_revision=change.source_revision,
                 snapshot_id=change.snapshot_id, operation_id=operation_id)
            for change in changes if type(change) is lifecycle.ElementSnapshotMembership]


def plan_change(connection, store, spec_id, change):
    content = None
    if change.present:
        source = store._revision(connection, spec_id, change.element_id, change.source_revision)
        if source is None or source["status"] != "active" or current(
                connection, spec_id, change.element_id, change.source_revision) is False:
            raise ValueError("snapshot source must be a retained present active revision")
        content = source["content"]
    elif current(connection, spec_id, change.element_id) is False:
        raise ValueError("requirement is already absent")
    return store._existing_change(connection, spec_id, change.element_id, change.expected_revision,
                                  content=content, membership=True)


def receipt_fields(row):
    return {key: row[key] for key in ("present", "source_revision", "snapshot_id")}


def validate_row(connection, store, row):
    from harness.element_identity_store import _decimal, _integer

    previous_number = _integer(row["revision"]) - 1
    expected = _decimal(previous_number)
    change = lifecycle.ElementSnapshotMembership(row["element_id"], expected, row["present"],
                                                  row["source_revision"], row["snapshot_id"])
    previous = store._revision(connection, row["spec_id"], row["element_id"], expected)
    revision = store._revision(connection, row["spec_id"], row["element_id"], row["revision"])
    source = store._revision(connection, row["spec_id"], row["element_id"], change.source_revision) if change.present else previous
    if (previous is None or previous["status"] != "active" or revision is None
            or revision["status"] != "active" or revision["operation_id"] != row["operation_id"]
            or source is None or source["status"] != "active" or source["content"] != revision["content"]
            or (change.present and (_integer(change.source_revision) > previous_number
                or current(connection, row["spec_id"], row["element_id"], change.source_revision) is False))
            or (not change.present and current(connection, row["spec_id"], row["element_id"], expected) is False)):
        raise ValueError("snapshot membership revision binding is inconsistent")


def validate_receipt(connection, store, spec_id, operation_id, receipt):
    retained = rows(connection, operation_id=operation_id)
    for entry in receipt:
        if "snapshot_membership" in entry:
            fields = entry["snapshot_membership"]
            if (type(fields) is not dict or set(fields) != {"present", "source_revision", "snapshot_id"}
                    or type(fields["present"]) is not bool):
                raise ValueError("invalid snapshot membership receipt fields")
    expected = {(entry["element_id"], entry["revision"]): entry["snapshot_membership"]
                for entry in receipt if "snapshot_membership" in entry}
    actual = {}
    for row in retained:
        if row["spec_id"] != spec_id:
            raise ValueError("snapshot membership spec mismatch")
        validate_row(connection, store, row)
        actual[row["element_id"], row["revision"]] = receipt_fields(row)
    if actual != expected:
        raise ValueError("snapshot membership receipt differs from retained rows")


def audit(connection, store):
    if not available(connection):
        return
    for row in connection.execute("SELECT DISTINCT operation_id,spec_id FROM snapshot_memberships"):
        operation = connection.execute("SELECT method,spec_id FROM operations WHERE operation_id=?",
                                       (row["operation_id"],)).fetchone()
        if operation is None or tuple(operation) != ("lifecycle", row["spec_id"]):
            raise ValueError("snapshot membership has a missing or conflicting lifecycle operation")
        store._receipt(connection, row["operation_id"], row["spec_id"])
