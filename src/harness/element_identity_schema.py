"""Canonical DDL and additive migration on an existing caller-owned connection.

No filesystem access, authority creation, commits, or transaction ownership.
The marker/user_version retain format 1; metadata versions the database schema.
"""

SCHEMA_VERSION = "6"
_CANONICAL = "{0} NOT GLOB '*[^0-9]*' AND ({0} = '0' OR {0} GLOB '[1-9]*')"
ALLOCATION_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
    "counters": "CREATE TABLE counters (spec_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "high_water TEXT NOT NULL CHECK (" + _CANONICAL.format("high_water") + "), "
        "PRIMARY KEY (spec_id, kind)) WITHOUT ROWID",
    "operations": "CREATE TABLE operations (operation_id TEXT PRIMARY KEY, method TEXT NOT NULL, "
        "spec_id TEXT NOT NULL, digest TEXT NOT NULL) WITHOUT ROWID",
    "reservations": "CREATE TABLE reservations (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), "
        "spec_id TEXT NOT NULL, kind TEXT NOT NULL, first_ordinal TEXT NOT NULL CHECK (" +
        _CANONICAL.format("first_ordinal") + " AND first_ordinal != '0'), "
        "first_length INTEGER NOT NULL, last_ordinal TEXT NOT NULL CHECK (" +
        _CANONICAL.format("last_ordinal") + "), count TEXT NOT NULL CHECK (" +
        _CANONICAL.format("count") + " AND count != '0')) WITHOUT ROWID",
    "reservation_ranges": "CREATE UNIQUE INDEX reservation_ranges ON reservations "
        "(spec_id, kind, first_length, first_ordinal)",
    "reservation_maxima": "CREATE INDEX reservation_maxima ON reservations "
        "(spec_id, kind, length(last_ordinal), last_ordinal)",
    "entities": "CREATE TABLE entities (spec_id TEXT NOT NULL, element_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, subject TEXT NOT NULL, ordinal TEXT CHECK (ordinal IS NULL OR (" +
        _CANONICAL.format("ordinal") + " AND ordinal != '0')), "
        "PRIMARY KEY (spec_id, element_id)) WITHOUT ROWID",
    "entity_ordinals": "CREATE UNIQUE INDEX entity_ordinals ON entities (spec_id, kind, ordinal)",
    "entity_maxima": "CREATE INDEX entity_maxima ON entities "
        "(spec_id, kind, length(ordinal), ordinal) WHERE ordinal IS NOT NULL",
}
LIFECYCLE_SCHEMA = {
    "revisions": "CREATE TABLE revisions (spec_id TEXT NOT NULL, element_id TEXT NOT NULL, "
        "revision TEXT NOT NULL CHECK (" + _CANONICAL.format("revision") + " AND revision != '0'), "
        "subject TEXT NOT NULL, content TEXT NOT NULL, content_sha256 TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK (status IN ('active','retired','superseded')), reason TEXT, "
        "operation_id TEXT NOT NULL REFERENCES operations(operation_id), "
        "PRIMARY KEY (spec_id, element_id, revision), "
        "FOREIGN KEY (spec_id, element_id) REFERENCES entities(spec_id, element_id)) WITHOUT ROWID",
    "revision_maxima": "CREATE INDEX revision_maxima ON revisions "
        "(spec_id, element_id, length(revision), revision)",
    "lifecycle_heads": "CREATE TABLE lifecycle_heads (spec_id TEXT NOT NULL, element_id TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK (status IN ('imported','active','retired','superseded')), revision TEXT, "
        "CHECK ((status='imported' AND revision IS NULL) OR (status!='imported' AND revision IS NOT NULL)), "
        "PRIMARY KEY (spec_id, element_id), "
        "FOREIGN KEY (spec_id, element_id) REFERENCES entities(spec_id, element_id), "
        "FOREIGN KEY (spec_id, element_id, revision) REFERENCES revisions(spec_id, element_id, revision)) WITHOUT ROWID",
    "lifecycle_lineage": "CREATE TABLE lifecycle_lineage (spec_id TEXT NOT NULL, predecessor_id TEXT NOT NULL, "
        "predecessor_revision TEXT NOT NULL, successor_id TEXT NOT NULL, successor_revision TEXT NOT NULL, "
        "kind TEXT NOT NULL CHECK (kind IN ('replace','split','merge')), reason TEXT NOT NULL, "
        "operation_id TEXT NOT NULL REFERENCES operations(operation_id), "
        "PRIMARY KEY (spec_id, predecessor_id, successor_id), "
        "FOREIGN KEY (spec_id, predecessor_id, predecessor_revision) REFERENCES revisions(spec_id, element_id, revision), "
        "FOREIGN KEY (spec_id, successor_id, successor_revision) REFERENCES revisions(spec_id, element_id, revision)) WITHOUT ROWID",
    "lineage_successors": "CREATE INDEX lineage_successors ON lifecycle_lineage (spec_id, successor_id)",
    "lifecycle_receipts": "CREATE TABLE lifecycle_receipts (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), "
        "receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL) WITHOUT ROWID",
}
SCHEMA_V2 = ALLOCATION_SCHEMA | LIFECYCLE_SCHEMA
BINDING_SCHEMA = {
    "reference_claims": "CREATE TABLE reference_claims (operation_id TEXT NOT NULL REFERENCES operations(operation_id), "
        "entry_index TEXT NOT NULL CHECK (" + _CANONICAL.format("entry_index") + " AND entry_index != '0'), "
        "spec_id TEXT NOT NULL, source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_anchor TEXT NOT NULL, "
        "target_id TEXT NOT NULL, target_revision TEXT, relation TEXT NOT NULL, payload_sha256 TEXT NOT NULL, "
        "PRIMARY KEY (operation_id, entry_index), "
        "FOREIGN KEY (spec_id, target_id) REFERENCES entities(spec_id, element_id), "
        "FOREIGN KEY (spec_id, target_id, target_revision) REFERENCES revisions(spec_id, element_id, revision)) WITHOUT ROWID",
    "reference_sources": "CREATE INDEX reference_sources ON reference_claims "
        "(spec_id, source_path, source_sha256, operation_id, length(entry_index), entry_index)",
    "reference_operations": "CREATE INDEX reference_operations ON reference_claims "
        "(operation_id, length(entry_index), entry_index)",
    "issue_occurrences": "CREATE TABLE issue_occurrences (operation_id TEXT NOT NULL REFERENCES operations(operation_id), "
        "entry_index TEXT NOT NULL CHECK (" + _CANONICAL.format("entry_index") + " AND entry_index != '0'), "
        "spec_id TEXT NOT NULL, issue_id TEXT NOT NULL, issue_revision TEXT NOT NULL, report_id TEXT NOT NULL, "
        "report_sha256 TEXT NOT NULL, display_id TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, "
        "issue_fingerprint TEXT NOT NULL, payload_sha256 TEXT NOT NULL, PRIMARY KEY (operation_id, entry_index), "
        "FOREIGN KEY (spec_id, issue_id) REFERENCES entities(spec_id, element_id), "
        "FOREIGN KEY (spec_id, issue_id, issue_revision) REFERENCES revisions(spec_id, element_id, revision)) WITHOUT ROWID",
    "occurrence_issues": "CREATE INDEX occurrence_issues ON issue_occurrences "
        "(spec_id, issue_id, operation_id, length(entry_index), entry_index)",
    "occurrence_operations": "CREATE INDEX occurrence_operations ON issue_occurrences "
        "(operation_id, length(entry_index), entry_index)",
    "binding_receipts": "CREATE TABLE binding_receipts (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), "
        "receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL) WITHOUT ROWID",
}
SCHEMA_V3 = SCHEMA_V2 | BINDING_SCHEMA
PUBLICATION_SCHEMA = {
    "publication_intents": "CREATE TABLE publication_intents (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), "
        "spec_id TEXT NOT NULL, request TEXT NOT NULL, request_sha256 TEXT NOT NULL, plan TEXT NOT NULL, "
        "plan_sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('prepared','applied','released')), "
        "application_receipt TEXT, application_receipt_sha256 TEXT, completion_payload TEXT, completion_payload_sha256 TEXT, "
        "CHECK ((state='prepared' AND application_receipt IS NULL AND application_receipt_sha256 IS NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) "
        "OR (state='applied' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NULL AND completion_payload_sha256 IS NULL) "
        "OR (state='released' AND application_receipt IS NOT NULL AND application_receipt_sha256 IS NOT NULL AND completion_payload IS NOT NULL AND completion_payload_sha256 IS NOT NULL))) WITHOUT ROWID",
    "publication_pending_specs": "CREATE UNIQUE INDEX publication_pending_specs ON publication_intents (spec_id) WHERE state!='released'",
    "publication_operation_claims": "CREATE TABLE publication_operation_claims (operation_id TEXT PRIMARY KEY, "
        "publication_id TEXT NOT NULL REFERENCES publication_intents(operation_id), method TEXT NOT NULL "
        "CHECK (method IN ('lifecycle','reference_claims','issue_occurrences')), digest TEXT NOT NULL) WITHOUT ROWID",
    "publication_claim_methods": "CREATE UNIQUE INDEX publication_claim_methods ON publication_operation_claims (publication_id, method)",
}
SCHEMA_V4 = SCHEMA_V3 | PUBLICATION_SCHEMA
SOURCE_SCHEMA = {
    "source_contexts": "CREATE TABLE source_contexts (spec_id TEXT NOT NULL, context_id TEXT NOT NULL, "
        "registration_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id), "
        "manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, "
        "head_publication_id TEXT REFERENCES publication_intents(operation_id), "
        "PRIMARY KEY (spec_id,context_id)) WITHOUT ROWID",
    "source_publications": "CREATE TABLE source_publications (publication_id TEXT PRIMARY KEY REFERENCES publication_intents(operation_id), "
        "spec_id TEXT NOT NULL, context_id TEXT NOT NULL, sequence TEXT NOT NULL CHECK (" +
        _CANONICAL.format("sequence") + " AND sequence != '0'), "
        "predecessor_operation_id TEXT NOT NULL REFERENCES operations(operation_id), "
        "manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, application_sha256 TEXT, "
        "FOREIGN KEY (spec_id,context_id) REFERENCES source_contexts(spec_id,context_id)) WITHOUT ROWID",
    "source_publication_sequences": "CREATE UNIQUE INDEX source_publication_sequences ON source_publications (spec_id,context_id,sequence)",
    "source_publication_heads": "CREATE INDEX source_publication_heads ON source_publications "
        "(spec_id,context_id,length(sequence),sequence) WHERE application_sha256 IS NOT NULL",
    "source_registration_specs": "CREATE INDEX source_registration_specs ON operations (spec_id,operation_id) WHERE method='source_context'",
}
SCHEMA_V5 = SCHEMA_V4 | SOURCE_SCHEMA
MANAGED_SCHEMA = {
    "managed_identity_specs": "CREATE TABLE managed_identity_specs (spec_id TEXT NOT NULL PRIMARY KEY, "
        "run_id TEXT NOT NULL UNIQUE, context_id TEXT NOT NULL, "
        "operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id), "
        "request TEXT NOT NULL, request_sha256 TEXT NOT NULL, "
        "FOREIGN KEY (spec_id,context_id) REFERENCES source_contexts(spec_id,context_id)) WITHOUT ROWID",
    "managed_identity_operations": "CREATE INDEX managed_identity_operations ON operations "
        "(spec_id,operation_id) WHERE method='managed_identity'",
}
SCHEMA = SCHEMA_V5 | MANAGED_SCHEMA


def validate(connection, marker, *, allow_old=False):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported identity database schema version")
    actual = {row[0]: row[1] for row in connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    )}
    if actual not in (ALLOCATION_SCHEMA, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA):
        raise ValueError("identity database schema or required indexes are malformed")
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    expected = {key: str(value) for key, value in marker.items()}
    version = ("1" if actual == ALLOCATION_SCHEMA else "2" if actual == SCHEMA_V2
               else "3" if actual == SCHEMA_V3 else "4" if actual == SCHEMA_V4
               else "5" if actual == SCHEMA_V5 else SCHEMA_VERSION)
    if version != "1":
        expected["schema_version"] = version
    if metadata != expected:
        raise ValueError("authority marker and database identity/schema version do not match")
    if version != SCHEMA_VERSION and not allow_old:
        raise ValueError(f"schema {version} authority requires explicit IdentityStore.upgrade")
    return version


def upgrade(connection):
    """Caller must validate the exact old schema/history inside its transaction."""
    if not connection.in_transaction:
        raise ValueError("schema upgrade requires a caller-owned transaction")
    version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if version is None:
        for statement in LIFECYCLE_SCHEMA.values():
            connection.execute(statement)
        connection.execute("INSERT INTO lifecycle_heads (spec_id,element_id,status,revision) "
                           "SELECT spec_id,element_id,'imported',NULL FROM entities")
    if version is None or version[0] == "2":
        for statement in BINDING_SCHEMA.values():
            connection.execute(statement)
    if version is None or version[0] in {"2", "3"}:
        for statement in PUBLICATION_SCHEMA.values():
            connection.execute(statement)
    if version is None or version[0] in {"2", "3", "4"}:
        for statement in SOURCE_SCHEMA.values():
            connection.execute(statement)
    if version is None or version[0] in {"2", "3", "4", "5"}:
        for statement in MANAGED_SCHEMA.values():
            connection.execute(statement)
    connection.execute("INSERT INTO metadata (key,value) VALUES ('schema_version',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SCHEMA_VERSION,))
