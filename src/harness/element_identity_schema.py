"""Canonical DDL and additive migration on an existing caller-owned connection.

No filesystem access, authority creation, commits, or transaction ownership.
The marker/user_version retain format 1; metadata versions the database schema.
"""

SCHEMA_VERSION = "2"
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
SCHEMA = ALLOCATION_SCHEMA | LIFECYCLE_SCHEMA


def validate(connection, marker, *, allow_old=False):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported identity database schema version")
    actual = {row[0]: row[1] for row in connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    )}
    if actual not in (ALLOCATION_SCHEMA, SCHEMA):
        raise ValueError("identity database schema or required indexes are malformed")
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    expected = {key: str(value) for key, value in marker.items()}
    old = actual == ALLOCATION_SCHEMA
    if not old:
        expected["schema_version"] = SCHEMA_VERSION
    if metadata != expected:
        raise ValueError("authority marker and database identity/schema version do not match")
    if old and not allow_old:
        raise ValueError("allocation-only authority requires explicit IdentityStore.upgrade")
    return "1" if old else SCHEMA_VERSION


def upgrade(connection):
    """Caller must validate the exact old schema/history inside its transaction."""
    if not connection.in_transaction:
        raise ValueError("schema upgrade requires a caller-owned transaction")
    for statement in LIFECYCLE_SCHEMA.values():
        connection.execute(statement)
    connection.execute("INSERT INTO lifecycle_heads (spec_id,element_id,status,revision) "
                       "SELECT spec_id,element_id,'imported',NULL FROM entities")
    connection.execute("INSERT INTO metadata (key,value) VALUES ('schema_version',?)", (SCHEMA_VERSION,))
