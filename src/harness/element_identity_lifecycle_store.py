"""Connection-owned lifecycle planning and persistence shared by store APIs."""

import hashlib

from harness import element_identity_lifecycle as lifecycle


def apply_changes(connection, store, spec_id, operation_id, changes):
    """Apply a validated lifecycle operation in the caller's active transaction."""
    # Import locally so this connection-owned helper remains safe in the store's
    # existing module cycle: element_identity_store imports this module.
    from harness.element_identity_store import (
        IdentityStoreError,
        _digest,
        _identifier,
        _json,
        _parse_label,
    )

    _identifier(spec_id, "spec_id")
    _identifier(operation_id, "operation_id")
    changes, payload, labels = lifecycle.request(changes)
    if not connection.in_transaction:
        raise IdentityStoreError("lifecycle changes require an active transaction")
    digest = _digest(["lifecycle", spec_id, payload])
    for kind in {_parse_label(label)[0] for label in labels}:
        store._high_water(connection, spec_id, kind)
    if store._operation(connection, operation_id, "lifecycle", spec_id, digest):
        return store._receipt(connection, operation_id, spec_id)
    planned, links = plan_changes(connection, store, spec_id, changes)
    for label, revision, subject, content, status, reason, kind, ordinal in planned:
        if kind is not None:
            connection.execute(
                "INSERT INTO entities (spec_id,element_id,kind,subject,ordinal) VALUES (?,?,?,?,?)",
                (spec_id, label, kind, subject, ordinal),
            )
        connection.execute(
            "INSERT INTO revisions "
            "(spec_id,element_id,revision,subject,content,content_sha256,status,reason,operation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (spec_id, label, revision, subject, content,
             hashlib.sha256(content.encode("utf-8")).hexdigest(),
             status, reason, operation_id),
        )
        connection.execute(
            "INSERT INTO lifecycle_heads (spec_id,element_id,status,revision) VALUES (?,?,?,?) "
            "ON CONFLICT(spec_id,element_id) DO UPDATE SET status=excluded.status,revision=excluded.revision",
            (spec_id, label, status, revision),
        )
    connection.executemany(
        "INSERT INTO lifecycle_lineage "
        "(spec_id,predecessor_id,predecessor_revision,successor_id,successor_revision,kind,reason,operation_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ((*link, operation_id) for link in links),
    )
    result = [
        {
            "element_id": row[0],
            "revision": row[1],
            "status": row[4],
            "lineage": [
                link for link in store._lineage(connection, spec_id, row[0])
                if link["operation_id"] == operation_id
            ],
        }
        for row in planned
    ]
    receipt = _json(result)
    connection.execute(
        "INSERT INTO lifecycle_receipts (operation_id,receipt,receipt_sha256) VALUES (?,?,?)",
        (operation_id, receipt, hashlib.sha256(receipt.encode("ascii")).hexdigest()),
    )
    return tuple(result)


def plan_changes(connection, store, spec_id, changes):
    changes, _, labels = lifecycle.request(changes)
    for kind in {label.split("-", 1)[0] for label in labels}:
        store._high_water(connection, spec_id, kind)
    planned, links = [], []
    for change in changes:
        if type(change) is lifecycle.ElementCreate:
            planned.append(store._creation(connection, spec_id, change))
        elif type(change) is lifecycle.ElementAdopt:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, None,
                subject=change.subject, content=change.content, adopt=True,
            ))
        elif type(change) is lifecycle.ElementRevision:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                subject=change.subject, content=change.content,
            ))
        elif type(change) is lifecycle.ElementRetirement:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                status="retired", reason=change.reason,
            ))
        else:
            for label, expected in change.predecessors:
                planned.append(store._existing_change(
                    connection, spec_id, label, expected,
                    status="superseded", reason=change.reason,
                ))
            for successor in change.successors:
                planned.append(store._creation(connection, spec_id, successor))
            links.extend(
                (spec_id, label, expected, successor.element_id, "1", change.kind, change.reason)
                for label, expected in change.predecessors
                for successor in change.successors
            )
    return planned, links
