# Element identity allocation and lifecycle storage

`harness.element_identity_store.IdentityStore` is an inactive library. It is not
wired into spec producers, providers, artifact adapters, evidence, or squad
publication. Existing authoring behavior remains in place. Importing this module
does not activate identity management or create workspace state.

## Authority and API

Call `IdentityStore.initialize(workspace)` explicitly once for a fresh authority.
The workspace must already exist. State lives in `.echelon/identity/`:

- `authority.json`: marker format version, workspace UUID, and authority epoch UUID.
- `registry.sqlite3`: matching authority metadata, operation receipts, counters,
  reservation ranges, entities, lifecycle heads, immutable content revisions,
  direct lineage, and lifecycle receipts. Database schema version is separate
  metadata (`schema_version=2`); marker format and SQLite `user_version` remain 1.

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
including imports and lifecycle changes. Reusing it with the same complete request returns the original
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
imports unbound legacy entities. It retains exact label
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
It also exposes `status`, `revision`, `content`, and `content_sha256`. Imported
subject-only rows have status `imported` and null revision/content/digest; no
assessed content is invented from their captions. Mutation of a returned
dictionary cannot change any stored binding.

## Assessed content and lifecycle

`harness.element_identity_lifecycle` provides frozen, strictly validated requests:

- `ElementCreate(element_id, subject, content, reservation_operation_id)` consumes
  only the exact controller-issued numeric label from the matching spec/type
  reservation. Aliases, imported or previously materialized IDs, and mismatched
  reservations fail. A partial batch leaves all unused reservation claims intact.
- `ElementAdopt(element_id, subject, content)` attaches first assessed content to
  an imported entity, preserving the exact subject and label.
- `ElementRevision(element_id, expected_revision, subject, content)` changes an
  active entity's body with an exact current revision and unchanged subject.
- `ElementRetirement(element_id, expected_revision, reason)` adds a terminal
  `retired` revision retaining prior content and its digest.
- `ElementTransition(kind, predecessors, successors, reason)` replaces one entity
  with one, splits one into at least two, or merges at least two into one.
  Predecessors are tuples of exact label and expected revision. Successors are
  tuples of `ElementCreate` requests backed by supported type reservations.
  Predecessors receive terminal `superseded` revisions retaining their content;
  each direct link records the original assessed predecessor revision, successor
  revision `1`, reason, transition kind, and creating operation ID.

Use `store.apply_lifecycle(spec_id=..., operation_id=..., changes=(...))` for one
atomic batch. Every affected entity is validated against the initial state before
any materialization or revision is written. Duplicate or overlapping entity
changes, stale revisions, and invalid final successors reject the entire batch.
No lineage, head update, or receipt escapes rollback. The result is a tuple of
fresh dictionaries containing `element_id`, `revision`, `status`, and `lineage`.
An identical retry returns the original durable receipt even after later changes.
Conflicting reuse of the global operation ID fails across all three APIs.

First assessed revision is the decimal string `"1"`. Revision arithmetic uses the
same unbounded Python integer conversion as allocation, storing canonical decimal
TEXT without fixed-width casts. Content edits and status changes never allocate
new entity IDs or advance allocation counters. Retired and superseded entities
cannot be revised, adopted, or recreated.

`read_revision(spec_id=..., element_id=..., revision=...)` returns a copy of the
immutable historical subject, content, SHA-256 digest, status, reason, operation
ID and revision, or `None` for an unknown revision. `lineage(spec_id=...,
element_id=...)` returns direct incoming/outgoing links; it does not recursively
traverse ancestry. Reads verify content digests, immutable subject bindings,
terminal content retention, head/status bindings and indexed maximum retained
revision. Missing heads never become new imports, and lowering a head cannot hide
newer history. Damaged state fails without rebuilding from subject captions or
current artifact text. These checks detect stored contradictions, not arbitrary
coherent rewrites of the entire authority by someone with direct database access.

The library does not establish semantic continuity. Supplying the same subject
string does not prove that rewritten prose describes the same thing. Future
publication still requires semantic review and allowed edit scope, typed artifact
adapters, revision-bound references/evidence, issue occurrences, publication
intents/receipts, graph/memory history, and bounded discovery repair. Consumers
must reject transitions they cannot represent before publication. This library
does not perform graph writes, provider routing, or canonical file publication.

## Explicit schema upgrade

`IdentityStore.upgrade(workspace)` recognizes only the exact reviewed allocation
schema and original metadata, or the current schema. Ordinary `open` on the older
format reports that explicit upgrade is required and does not mutate storage.
Upgrade audits authority, integrity, foreign keys, retained numeric claims,
reservation history and legacy import/reservation overlap inside one
`BEGIN IMMEDIATE` transaction. It adds lifecycle tables and imported/null heads;
allocation tables, exact labels, counters, reservations, operation bindings and
UUIDs stay intact. A current-schema retry is an audited no-op. Interrupted DDL,
data insertion, and schema metadata all roll back together. Missing or unknown
state is never initialized or guessed. The schema helper owns DDL only on the
caller's connection, with no file access or independent commit.

Before a reservation, import, retry, lookup, or high-water read uses a namespace,
the store compares its counter with the true numeric maxima of retained range
endpoints and imported numeric ordinals. A missing counter with retained numeric
claims, or a counter below those claims, fails explicitly. The operation does not
repair the counter, reconstruct it from maxima, add a receipt, or alter claims.
An ordinary open still checks only schema/metadata; it does not audit every
namespace. A namespace is checked when used, and restore audits all namespaces.

## Transactions and filesystem boundaries

Every operation uses a short-lived connection. Writes use `BEGIN IMMEDIATE`, a
10-second busy timeout, parameterized statements, rollback on failure, and
SQLite DELETE journaling with `synchronous=FULL` and `fullfsync=ON`. There is no
process-global connection or in-memory allocation counter. Reservation ranges
keep storage proportional to requests rather than reserved label count.
Numeric import collision checks use an indexed predecessor range ordered by
decimal length and text. Entity label/ordinal lookup and counter access are
indexed. Separate namespace/kind/decimal-length indexes locate true maximum
reservation endpoints and imported ordinals with bounded seeks; validation does
not scan entity tables or sort all claims. No SQL numeric casts or floating-point
comparisons are used.

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
This whole-authority rollback limit does not exempt detectable counter/history
contradictions: lowered or missing counters with retained higher claims are
rejected even if direct SQLite edits caused them.

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
foreign keys, authority identity, counter/claim consistency, lifecycle history,
head bindings, lineage and durable lifecycle receipts across all
namespaces before creating destination state. This explicit restore audit may
scan the snapshot to discover every namespace, including ones whose counters
are missing. Digest verification and copying share a read transaction, so a concurrent SQLite writer
cannot commit between them. The destination workspace must exist and have no
identity directory, even an empty one. Restore uses online backup into fresh
owner-only files and preserves the exact workspace UUID, epoch, imported subjects,
operation receipts, counters, and reservations. It never merges or overwrites.
A recognized allocation-only backup is validated before claiming destination
state, then upgraded transactionally only in the fresh restored database. The
backup itself is unchanged. Unknown schema versions fail before destination
creation. Current backups retain all lifecycle tables and history.

A backup is a point-in-time snapshot. Restoring an old snapshot cannot recover
reservations committed after it. Quiesce the original authority and ensure the
chosen backup includes every externally used reservation before adopting a
restored copy as its successor. Reopening or rewinding a document does not rewind
the live ledger. Never regenerate a missing established ledger from current
document maxima. Independently advancing restored copies must not be merged or
treated as one allocation authority; they share identity/epoch and can issue
overlapping future ordinals.

## Focused verification

The unit contracts are in `tests/unit/test_element_identity_store.py` and
`tests/unit/test_element_identity_lifecycle.py`, with a frozen reviewed v1 SQL
fixture for migration compatibility. Process
contention, committed-process termination, concurrent backup, lock timeout, and
capacity checks and competing revisions from one baseline are in
`tests/integration/test_element_identity_store.py`.
The million-entity capacity test has `integration` and `slow` markers, imports
bounded 10,000-row batches, verifies indexed query plans, and reports elapsed
time and database size without a timing threshold. It is outside the unit suite
(`pytest -m unit`); select its integration file to run it explicitly.
