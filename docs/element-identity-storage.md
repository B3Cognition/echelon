# Element identity allocation storage

`harness.element_identity_store.IdentityStore` is an inactive library. It is not
wired into spec producers, providers, the content lifecycle, evidence, or squad
publication. Existing authoring behavior remains in place. Importing this module
does not activate identity management or create workspace state.

## Authority and API

Call `IdentityStore.initialize(workspace)` explicitly once for a fresh authority.
The workspace must already exist. State lives in `.echelon/identity/`:

- `authority.json`: schema version, workspace UUID, and authority epoch UUID.
- `registry.sqlite3`: matching authority metadata, operation receipts, counters,
  reservation ranges, and imported entities.

The authority directory is created exclusively with mode `0700`; new sensitive
files use `0600`. Existing workspace and `.echelon` directory permissions are not
changed. A partially created or even empty identity directory blocks another
initialization. Preserve that evidence and investigate a failed initialization;
do not delete it and bootstrap from document maxima.

`IdentityStore.open(workspace)` requires both files and opens SQLite in `mode=rw`,
which cannot silently create a missing database. It checks schema version,
required tables/indexes/constraints, and exact marker/database identity. Handles
repeat these checks for each operation and reject changed authority identities.
An open checks the small schema and metadata, not every entity. A missing,
unreadable, or malformed authority raises `IdentityStoreError`, a `ValueError`.
Callers must stop allocation on that error; inventing IDs is not a fallback.

```python
from pathlib import Path
from harness.element_identity_store import IdentityStore

store = IdentityStore.initialize(Path("/existing/workspace"))
ids = store.reserve(
    spec_id="001-demo", kind="AC", operation_id="dispatch-1", count=2,
)
assert ids == ("AC-000001", "AC-000002")
```

`reserve` accepts AC, FR, NFR, ISS, U, A, and T. Each `(spec_id, kind)` has an
independent counter. An operation ID is unique across the entire authority,
including imports. Reusing it with the same complete request returns the original
range; changing count, kind, spec, or operation type fails. A reservation creates
no entity, and `lookup` returns `None` for its labels. Once committed, every claim
remains reserved, including abandoned work and terminated callers.

New labels have a minimum of six decimal digits. This is display padding, not a
storage width or maximum ordinal. Counters, range endpoints, counts, and numeric
entity ordinals are canonical decimal TEXT. Python integer arithmetic advances
them, with chunked conversion for values exceeding Python's decimal string guard;
the library does not change process-wide settings. IDs and `high_water` results
are strings. A counter is `"0"` before any allocation or numeric import.

`import_identities(spec_id=..., operation_id=..., definitions=[(label, subject)])`
is the only entity materialization API in this foundation. It retains exact label
spelling and immutable nonblank subject text. `FR-001` claims ordinal 1, so the
next FR reservation is `FR-000002`; importing `FR-000001` then conflicts. The same
exact label and subject may appear in a later import. Duplicate labels within
one request, changed subjects, and numeric labels intersecting reservations fail
atomically. Retrying an import requires the same ordered definitions. An empty
import is a valid receipt with no entities.

Labels require a recognized uppercase kind followed by `-` and an ASCII suffix
beginning with a letter or digit; the rest may contain letters, digits, `_`, `.`,
and `-`. Entirely decimal suffixes are positive numeric ordinals. Composite
suffixes such as `AC-legacy-999999` and `AC-001.002` are opaque: they retain their
exact labels and do not raise numeric counters. The store does not infer numeric
identity from fragments of composite labels.

`lookup(spec_id=..., element_id=...)` returns a fresh dictionary with `spec_id`,
`element_id`, `kind`, `subject`, and canonical `ordinal` (`None` for opaque labels).
Mutation of the returned dictionary cannot change the stored binding. Revision,
retirement, replacement/split/merge lineage, and publication are later work.

## Transactions and filesystem boundaries

Every operation uses a short-lived connection. Writes use `BEGIN IMMEDIATE`, a
10-second busy timeout, parameterized statements, rollback on failure, and
SQLite DELETE journaling with `synchronous=FULL` and `fullfsync=ON`. There is no
process-global connection or in-memory allocation counter. Reservation ranges
keep storage proportional to requests rather than reserved label count.
Numeric import collision checks use an indexed predecessor range ordered by
decimal length and text. Entity label/ordinal lookup and counter access are
indexed. No SQL numeric casts or floating-point comparisons are used.

Use a local filesystem with working SQLite locking and synchronization. Authority
components, their parent path components, and SQLite sidecar paths must not be
symlinks. The library checks those paths before opening state. Workspace owners
must prevent concurrent filesystem replacement, arbitrary SQL edits, and file
permission changes outside the library: path checks are not a security boundary
against a malicious process that can swap directories between syscalls. Normal
independent allocation processes coordinate through SQLite.
The marker binds authority UUIDs, not the latest database generation: manually
substituting an older valid database from the same authority is not detected as
rollback. Use the restore API and the adoption rules below; it rejects overwrites.

## Backup and restore

`store.backup(destination)` requires a fresh dedicated directory whose parent
exists. It uses SQLite online backup from one read transaction, writes the bound
authority marker, then writes `manifest.json` last. The completed manifest binds
the authority/version and database SHA-256 digest. Files and directories are
synchronized. Existing destinations are never overwritten. A failed operation
may leave a directory without a valid completed manifest; it cannot be restored
or reused as a fresh backup destination.

`IdentityStore.restore(workspace, backup)` checks the completed manifest, strict
metadata, absence of snapshot sidecars, digest, required schema, SQLite integrity,
foreign keys, and authority identity before creating destination state. Digest
verification and copying share a read transaction, so a concurrent SQLite writer
cannot commit between them. The destination workspace must exist and have no
identity directory, even an empty one. Restore uses online backup into fresh
owner-only files and preserves the exact workspace UUID, epoch, imported subjects,
operation receipts, counters, and reservations. It never merges or overwrites.

A backup is a point-in-time snapshot. Restoring an old snapshot cannot recover
reservations committed after it. Quiesce the original authority and ensure the
chosen backup includes every externally used reservation before adopting a
restored copy as its successor. Reopening or rewinding a document does not rewind
the live ledger. Never regenerate a missing established ledger from current
document maxima. Independently advancing restored copies must not be merged or
treated as one allocation authority; they share identity/epoch and can issue
overlapping future ordinals.

## Focused verification

The unit contracts are in `tests/unit/test_element_identity_store.py`. Process
contention, committed-process termination, concurrent backup, lock timeout, and
capacity checks are in `tests/integration/test_element_identity_store.py`.
The million-entity capacity test has `integration` and `slow` markers, imports
bounded 10,000-row batches, verifies indexed query plans, and reports elapsed
time and database size without a timing threshold. It is outside the unit suite
(`pytest -m unit`); select its integration file to run it explicitly.
