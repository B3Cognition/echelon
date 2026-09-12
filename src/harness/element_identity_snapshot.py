"""Canonical read-only observation of retained materialized identity history."""

from dataclasses import dataclass

from harness import element_identity_lifecycle as lifecycle
from harness import element_identity_store as authority


@dataclass(frozen=True, slots=True)
class IdentityHistorySnapshot:
    payload: str
    sha256: str


def _rows(connection, query, spec_id):
    return [dict(row) for row in connection.execute(query, (spec_id,))]


def canonical_snapshot(value) -> IdentityHistorySnapshot:
    """Encode detached complete rows in the retained snapshot's exact SQL order."""
    def entity_key(row):
        ordinal = row["ordinal"]
        return row["kind"], ordinal is None, len(ordinal or ""), ordinal or "", row["element_id"]

    value["entities"].sort(key=entity_key)
    keys = {row["element_id"]: entity_key(row) for row in value["entities"]}
    value["revisions"].sort(key=lambda row: (
        keys[row["element_id"]], len(row["revision"]), row["revision"]))
    value["lineage"].sort(key=lambda row: (
        keys[row["predecessor_id"]], keys[row["successor_id"]], row["kind"], row["operation_id"]))
    for method in ("reference_claims", "issue_occurrences"):
        value[method].sort(key=lambda row: (
            row["operation_id"], len(row["entry_index"]), row["entry_index"]))
    return IdentityHistorySnapshot(payload=authority._json(value), sha256=authority._digest(value))


@authority._public
def capture(connection, store, spec_id: str) -> IdentityHistorySnapshot:
    """Observe one spec's complete retained materialized history in a caller transaction."""
    lifecycle.text(spec_id, "spec_id")
    namespace = authority.IdentityStore._namespace(connection)
    store._audit(connection, lifecycle_state=True, binding_state=True, publication_state=True, source_state=True, managed_state=True)

    entity_order = (
        "e.kind,e.ordinal IS NULL,length(coalesce(e.ordinal,'')),"
        "coalesce(e.ordinal,''),e.element_id"
    )
    entities = _rows(
        connection,
        "SELECT e.spec_id,e.element_id,e.kind,e.subject,e.ordinal,h.status,h.revision "
        "FROM entities AS e JOIN lifecycle_heads AS h "
        "ON h.spec_id=e.spec_id AND h.element_id=e.element_id "
        f"WHERE e.spec_id=? ORDER BY {entity_order}",
        spec_id,
    )
    revisions = _rows(
        connection,
        "SELECT r.spec_id,r.element_id,r.revision,r.subject,r.content,r.content_sha256,"
        "r.status,r.reason,r.operation_id FROM revisions AS r JOIN entities AS e "
        "ON e.spec_id=r.spec_id AND e.element_id=r.element_id "
        f"WHERE r.spec_id=? ORDER BY {entity_order},length(r.revision),r.revision",
        spec_id,
    )
    lineage = _rows(
        connection,
        "SELECT l.spec_id,l.predecessor_id,l.predecessor_revision,l.successor_id,"
        "l.successor_revision,l.kind,l.reason,l.operation_id "
        "FROM lifecycle_lineage AS l "
        "JOIN entities AS p ON p.spec_id=l.spec_id AND p.element_id=l.predecessor_id "
        "JOIN entities AS s ON s.spec_id=l.spec_id AND s.element_id=l.successor_id "
        "WHERE l.spec_id=? ORDER BY "
        "p.kind,p.ordinal IS NULL,length(coalesce(p.ordinal,'')),coalesce(p.ordinal,''),p.element_id,"
        "s.kind,s.ordinal IS NULL,length(coalesce(s.ordinal,'')),coalesce(s.ordinal,''),s.element_id,"
        "l.kind,l.operation_id",
        spec_id,
    )
    reference_claims = _rows(
        connection,
        "SELECT operation_id,entry_index,spec_id,source_path,source_sha256,source_anchor,"
        "target_id,target_revision,relation,payload_sha256 FROM reference_claims "
        "WHERE spec_id=? ORDER BY operation_id,length(entry_index),entry_index",
        spec_id,
    )
    issue_occurrences = _rows(
        connection,
        "SELECT operation_id,entry_index,spec_id,issue_id,issue_revision,report_id,"
        "report_sha256,display_id,title,body,issue_fingerprint,payload_sha256 "
        "FROM issue_occurrences WHERE spec_id=? "
        "ORDER BY operation_id,length(entry_index),entry_index",
        spec_id,
    )
    value = {
        "version": "1",
        **namespace,
        "spec_id": spec_id,
        "entities": entities,
        "revisions": revisions,
        "lineage": lineage,
        "reference_claims": reference_claims,
        "issue_occurrences": issue_occurrences,
    }
    return canonical_snapshot(value)
