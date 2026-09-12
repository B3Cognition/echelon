"""Query-only proposed materialized history for new, unclaimed journal children."""

import json

from harness import element_identity_binding_store as binding_store
from harness import element_identity_lifecycle_store as lifecycle_store
from harness import element_identity_publication_store as publication_store
from harness.element_identity_snapshot import capture, canonical_snapshot


def preview(connection, store, spec_id, operations):
    """Overlay shared planned rows on the fully audited caller snapshot."""
    publication_store._require(connection, spec_id)
    if connection.execute(publication_store._PENDING, (spec_id,)).fetchone():
        raise ValueError("spec has a pending identity publication")
    children = publication_store.operation_children(operations, spec_id)
    publication_store.require_new_children(connection, children)
    retained = capture(connection, store, spec_id)
    plan = publication_store.planned_effects(connection, store, spec_id, children)
    return _overlay(retained, spec_id, children, plan)


def _overlay(retained, spec_id, children, plan):
    """Pure overlay for public preview or an already validated prepared owner."""
    value = json.loads(retained.payload)
    entities = {row["element_id"]: row for row in value["entities"]}
    for operation, _, payloads, _ in children:
        if operation.method == "lifecycle":
            for planned in plan["revisions"]:
                label, revision, subject, _, status, _, kind, ordinal = planned
                if kind is not None:
                    entity = dict(spec_id=spec_id, element_id=label, kind=kind,
                                  ordinal=ordinal, subject=subject)
                    value["entities"].append(entity)
                    entities[label] = entity
                entities[label].update(status=status, revision=revision)
                value["revisions"].append(lifecycle_store.revision_row(
                    spec_id, operation.operation_id, planned))
            value["lineage"].extend(lifecycle_store.lineage_row(operation.operation_id, link)
                                    for link in plan["lineage"])
        else:
            value[operation.method].extend(binding_store.materialized_row(
                spec_id, operation.operation_id, index, payload, operation.method)
                for index, payload in enumerate(payloads, 1))
    return canonical_snapshot(value)
