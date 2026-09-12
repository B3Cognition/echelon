# Element identity allocation, lifecycle, and binding storage

`harness.element_identity_store.IdentityStore` is an inactive library. It is not
wired into spec producers, providers, artifact adapters, evidence, or squad
publication. Existing authoring behavior remains in place. Importing this module
does not activate identity management or create workspace state.

## Sealed publication inspection boundary

`PreparedSquadPublication.inspect()` is a read-only context manager on the existing
sealed publisher. It reloads and authenticates the schema-1 manifest and stages
against the existing `PublicationMarker`, then captures exact current target and
sealed postimage bytes under the existing project publication lock. It never
trusts the prepared object's mutable manifest. It performs no promotion, deletion,
restoration, stage sealing/discard, identity write, graph write, receipt, checkpoint
or completion update. The existing lock may create its
`.echelon/runtime/publication.lock` control path; this is its only incidental write.

The detached frozen values live in `harness.squad_publication_snapshot`:
`PublicationSnapshot` contains the marker, `promoted_prefix`, and an ordered tuple
of `PublicationOperationSnapshot` values. Each operation contains its action and
manifest-relative target, preimage/postimage/current `PublicationImageDescriptor`
values, `current_bytes`, and `postimage_bytes`. Descriptors preserve exact validated
hashes and modes. Missing images use kind `missing`, null hash/mode and `None`
bytes; a present empty file is kind `file` with `b""`. Deletes have no postimage
bytes. Writes always expose the sealed bytes, including already-promoted targets.

The prefix is the existing global manifest-order promotion rule's lower bound.
Equal pre/post images do not force the boundary, so this is not a count of images
that match postimages. Every current image must match its recorded preimage or
postimage, and the whole list must admit one legal prefix. Corruption or drift
rejects the entire inspection. No-follow descriptor traversal retains root,
ancestor, file and absence bindings and revalidates them, the manifest and stages
before yielding and on successful context exit. Absent target parents are not
created. Caller exceptions propagate and release retained descriptors and the lock.
The project-root chain is pinned before acquiring that lock. The existing lock
helper borrows the retained root descriptor and compares its own opened root's
identity with it before creating control paths or acquiring the lock. The path
chain is also revalidated immediately after acquisition, before loading sealed
authority. A temporary replacement followed by restoration of the original root
cannot associate inspection with the replacement root's independent lock.

The body is for short controller-owned validation or identity transactions, not
provider work. Do not recursively call `publish`, `discard`, or `inspect` while
holding the non-reentrant publication lock. Inspection introduces no additional
lock hierarchy. Its authority ends when that context exits.

Successful inspection includes successful exit validation, not just receipt of
the yielded value. A future caller that persists a pending intent inside the body
must leave it pending if exit validation fails: this reader cannot roll back a
separately committed database transaction. Do not mark publication, graph or
completion successful inside the body.

For an already-promoted target, `preimage` is the authenticated original manifest
descriptor, but `current_bytes` contains its current postimage. Inspection cannot
recover the original bytes. A future durable intent must retain accepted before
images before promotion and match their hashes and modes to the preimage
descriptor; it must never treat current postimage bytes as the baseline.

Snapshot coverage is limited to manifest operations, not every unchanged semantic
or dependent input. This API does not authenticate semantic review, provide
complete candidate capture, reserve identity intents, finalize lifecycle/bindings,
produce graph receipts, or integrate identity at run-local acceptance/final export.
Existing Phase A completion transactions, candidate isolation and repair remain
the integration owners. Rejected candidates remain diagnostics and cannot update
canonical artifacts, graphs or memory. Published labels, including `FR-001` and
historical composite IDs, retain their exact spelling.

## Complete selected source-tree inspection boundary

`harness.squad_source_snapshot.inspect_project_tree(project_root, tree_path)` is
an inactive, read-only source-observation prerequisite. The caller explicitly
selects one tree using an exact nonempty project-relative POSIX string. Empty
paths, workspace-root aliases, dot/dot-dot components, backslashes and invalid
encodings fail rather than normalize. Project roots retain the sealed inspector's
existing real-directory validation, including supported relative `Path` inputs
that validate to an absolute root. Symlinks do not grant access.

`ProjectTreeSnapshot` contains the selected `path`, `exists`, and sorted tuples of
frozen `ProjectDirectorySnapshot` and `ProjectFileSnapshot` values. Paths include
the selected prefix. Directories include the root and all nested empty
directories with exact permission modes. Files include every regular file,
including hidden and non-Markdown files, with its exact bytes and existing
`PublicationImageDescriptor` hash/mode. Binary, Unicode, CRLF, whitespace and empty
content are preserved without truncation. A missing tree has `exists=False` and
two empty tuples; a present empty tree has `exists=True` and its root directory.
Missing trees and ancestors are never created.

This reader and sealed inspection share one private owner for retained root
descriptors, the existing publication lock, its borrowed expected-root descriptor
association and immediate acquisition validation. Iterative no-follow traversal
retains each directory and file identity and complete sorted directory membership.
Directory/file/absence bindings, names, original directory modes and exact file
images are checked before yielding and on normal exit. Additions, removals,
renames, replacements, permission or content drift, and previously absent tree
appearance invalidate successful capture. Unsupported entries and read/listing
failures are rejected with bounded `PublicationError` codes, never skipped.
Caller exceptions propagate unchanged, and all owned descriptors and the lock
close on failure. Only initialization of the existing publication lock control
path is an incidental filesystem effect.

Success includes normal context exit. Keep the body short and controller-owned;
do not run providers or recursively inspect, publish or discard inside it. These
detached observations establish neither historical provenance nor semantic
approval, a baseline reserved across provider execution, or canonical acceptance.
There is no freshness claim after exit. A future controller must retain the
successful before image, recapture and compare the complete tree before promotion,
and bind the exact image set, edit scope and review to a durable intent.

One selected tree does not cover all external semantic dependencies. Constitution,
glossary and product inputs must be bound by a future complete-bundle owner under
one coherent validation scope; sequential snapshots are not an atomic cross-tree
read set. Candidate writing, provider dispatch, identity allocation/lifecycle/
binding, controller routing, publication promotion and activation are unchanged.
Existing Phase A completion transactions, candidate isolation and repair remain
the integration owners. Rejected candidates stay diagnostic and cannot update
canonical artifacts, graphs or memory. Published labels, including `FR-001` and
historical composite IDs, remain exactly as published.

## Strict request recovery codec

`harness.element_identity_request_codec` is a pure, inactive compatibility helper
for exact existing immutable request payloads. `encode_request(method, entries)`
first re-runs the existing lifecycle or binding request validator, then emits the
same canonical ASCII JSON bytes used by operation digest serialization: sorted
keys, compact separators, and ASCII escaping. The payload is the existing array,
without an envelope, version, inferred method, or changed digest input. Labels,
IDs, revisions, CRLF, Unicode, and whitespace remain strings with their exact
published spelling.

`decode_request(method, payload)` accepts only the explicit methods `lifecycle`,
`reference_claims`, and `issue_occurrences`. It uses closed class maps and exact
dataclass field sets, rejects duplicate keys, numeric and non-finite JSON tokens,
and reconstructs transition predecessor and successor collections as detached
tuples of frozen values. Existing constructors and batch validators remain the
schema authority. Decoding supports `ElementAdopt` only for recovery compatibility;
it does not authorize adoption in a managed candidate.

Successful decoding proves request shape only. The codec performs no filesystem,
database, network, provider, or store calls and creates no persisted envelope.
It establishes no namespace ownership, reservation or head validity, source
authenticity, semantic approval, pending intent, publication acceptance, or
receipt authority. Existing store transactions and future controllers retain
those responsibilities; accepting bytes alone grants no adoption or publication
authority.

## Authority and API

Call `IdentityStore.initialize(workspace)` explicitly once for a fresh authority.
The workspace must already exist. State lives in `.echelon/identity/`:

- `authority.json`: marker format version, workspace UUID, and authority epoch UUID.
- `registry.sqlite3`: matching authority metadata, operation receipts, counters,
  reservation ranges, entities, lifecycle heads, immutable content revisions,
  direct lineage, immutable reference claims, issue occurrences, and receipts.
  Database schema version is separate metadata (`schema_version=3`); marker
  format and SQLite `user_version` remain 1.

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

## Explicit administration and audit

The authority has a separate, explicit administration entry point. Every path is
required; the commands never default to the current directory, discover a ledger
from documents, or modify the main Echelon CLI:

```text
python -m harness.element_identity_admin initialize --workspace PATH
python -m harness.element_identity_admin audit --workspace PATH
python -m harness.element_identity_admin upgrade --workspace PATH
python -m harness.element_identity_admin backup --workspace PATH --destination PATH
python -m harness.element_identity_admin restore --workspace PATH --backup PATH
python -m harness.element_identity_admin import-labels --workspace PATH --input PATH
python -m harness.element_identity_admin inventory-history --input PATH
```

Only `initialize` claims a new authority. `audit`, `backup`, and `import-labels`
open an existing current-schema authority; `upgrade` is the only command that
upgrades a recognized older schema, and `restore` retains the fresh-destination
and completed whole-ledger backup rules described below. A failed command prints
no success object. Successful audit and historical inventory commands print their
reports; other successful commands print an acknowledgement of the completed
storage operation.

### Read-only historical inventory

The pure API is
harness.element_identity_history.inventory_history(request: object) -> dict.
HistoryInventoryError identifies malformed explicitly supplied inputs. The
inventory-history command reads only its named strict UTF-8 JSON input and
prints the deterministic report directly. It has no workspace argument and
discovers no authority, Git history, directories, current artifact files or
registry maxima. Duplicate JSON object keys, malformed JSON/Unicode and invalid
input shapes return exit 2 with concise stderr and no report. Exit 0 means an
inventory was produced, including a report containing conflicts.

Input has exactly these keys at every level:

~~~json
{"schema_version":1,"spec_id":"demo","snapshots":[{"snapshot_id":"before","artifacts":[{"path":"unknowns.md","role":"unknowns","text":"### U-005: Collision\nInvestigate.\n"},{"path":"evidence.md","role":"evidence","text":"U-005 needs evidence.\n"}]},{"snapshot_id":"after","artifacts":[{"path":"unknowns.md","role":"unknowns","text":""},{"path":"evidence.md","role":"evidence","text":"U-005 needs evidence.\n"}]}]}
~~~

The schema version is integer 1 (not a boolean). Spec and unique snapshot IDs
are nonblank UTF-8 strings without NUL. Snapshot and artifact arrays are nonempty.
Within each snapshot a canonical relative POSIX path has exactly one role and
one captured image. Duplicate paths are rejected even when their roles or texts
differ. Across snapshots the same paths must be captured with the same assigned
roles; the manifest does not accept multiple parser views of one physical file.
Roles are the existing adapter roles: unknowns, assumptions,
requirements, tasks, issues, lexicon, lexicon_projection, investigation,
evidence, and references. Text is an exact UTF-8/NUL-free string or null:
null captures absence; empty text captures a present document. Present Lexicon
is validated by its existing native grammar, including empty documents; absent
Lexicon skips grammar parsing. No glossary or inventory JSON grammar is inferred.

The report's exact top-level fields are report_version: 1, spec_id,
input_sha256, coverage: "declared_snapshots_only",
source_authentication: "caller_supplied", assessment: "unassessed",
snapshots, and conflicts. Snapshot order is caller-declared history order,
not authenticated Git chronology. Artifacts sort by path; the digest binds
validated input encoded as canonical JSON with sorted keys, compact separators
and ASCII escaping, artifacts sorted by path and snapshot order retained.
No timestamps or external state enter the digest.

Each snapshot contains only snapshot_id and artifacts. Each artifact reports
path, role, present, content_sha256 (null for absence), declarations,
references, and diagnostics. Source facts preserve parser order. Declarations
contain element_id, kind, disposition, caption, span, label_span,
and content_sha256 for the exact typed declaration content. Spans are character
offsets start/end plus one-based line, preserving CRLF and Unicode source.
Raw declaration bodies are not printed. ISS occurrences also report
typed_fingerprint, computed with the existing issue fingerprint function from
the parsed caption and exact typed body after the first heading newline. This
uses the adapter's Resolution Guidance and footer boundaries. It is a newly
computed typed-body fingerprint, not an authenticated old resolution fingerprint
or closure transfer. Repeated display IDs and identical fingerprints retain all
source occurrences; projections never become authoritative entities.

References contain target_id, range_end_id, owner_id, relation, span,
and assessment: "unassessed". Even a unique local target supplies no assessed
revision, current head or verification certification. Diagnostics retain their
original code, span, and detail. Visible explicit unsupported declarations
are diagnostics, rather than disappearing or becoming shorter references.
Markdown active-source exclusions and successful identity grammars are retained.
The reference scanner classifies complete visible tokens. The supported numeric
and composite grammar (including AC-001a, FR-001abc, T-S01 and unbounded decimal
values) is unchanged. Identity-shaped tokens with unsupported spelling, including
FR-001.other, FR-001-extra, FR-001_extra, Unicode or internal wrapper characters,
and digit-free ISS-legacy, produce `unsupported_reference` over their exact
spelling. They cannot produce shorter accepted targets. Embedded words such as
NOTFR-001 are not references. This lexical grammar is narrower than the opaque
registry envelope; unsupported historical identities remain reserved and opaque.

Whitespace and prose/list/Markdown separators delimit mentions. Balanced enclosing
backticks (with matching run lengths), stars and underscores are syntax; internal
or unmatched wrapper-like characters remain token content. Outside inline code,
exactly one final full stop is sentence punctuation: `See FR-001.` references
FR-001. A literal final dot inside an inline-code span belongs to the label and
is unsupported. Two dots remain interval syntax. Frontmatter, fenced and indented
code, HTML comments and quoted blocks remain inactive. Source is never joined
across exclusions or rewritten, and source hashes and Python-string offsets stay
anchored to the caller's original image.

The only implicit local filename shorthand is exactly
`investigation/<supported-ID>.md`, plain or inside inline code. Its reference span
is the ID substring. Bare U-001.md, other paths, leading `./`, traversal, absolute
paths, foreign-spec prefixes, extra suffixes, queries, fragments, URIs and
`scope::label` qualifications produce `unsupported_qualified_reference` over the
complete locator, including when the basename is opaque. No basename lookup,
path normalization, percent decoding or namespace resolution occurs.
Any syntactically scheme-shaped prefix (`[A-Za-z][A-Za-z0-9+.-]*:`) followed
immediately by non-whitespace content has URI precedence, including
`urn:FR-001`, `mailto:FR-001@example.org` and ambiguous `Label:FR-001` or
`FR-001:FR-002`. No scheme allowlist is guessed. Ordinary colon-delimited prose
uses whitespace after the colon, as in `See: FR-001` and `FR-001: FR-002`.

En dash, em dash, two dots and a whitespace-surrounded ASCII hyphen may form an
unexpanded interval with exactly two complete, same-family numeric endpoints in
nondecreasing order. Unsupported endpoints, composite endpoints, reversals,
cross-family pairs, missing endpoints and chains produce `invalid_range` for the
whole expression; qualification takes precedence as
`unsupported_qualified_reference`. No shorter singleton escapes a rejected
interval. An ASCII dash followed by prose, as in FR-001 - implementation note,
leaves an ordinary singleton. Repeated separators after an identity interval
starts remain one rejected expression. For en dash, em dash and two dots,
an immediately adjacent bare atom is retained as an unsupported endpoint even
across whitespace: `See ..FR-001` includes See in its diagnostic span. An
explicit enclosing expression wrapper or ordinary delimiter separates outside
prose; `See` followed by the inline-code expression `..FR-001` diagnoses only
the expression. Query-position wrappers within a qualified locator are literal
locator content and cannot detach a local ID. Discovery and history consumers still block
interval application and qualifications. This scanner is not a namespace
resolver, historical-source authenticator or semantic assessor. Managed
consumers remain inactive, and explicit historical reconciliation remains
required before activation; stored labels and historical evidence are not
renamed or relabeled as proof of new content.

Every conflict has exactly code, element_ids, locations, and detail.
Locations contain snapshot_id, path, artifact_sha256, and span; missing
definition locations use the explicitly captured following artifact hash
(null when absent) and null span. Exact published label strings remain intact.

| Conflict | Meaning |
| --- | --- |
| artifact_diagnostic | A parser diagnostic is retained, with its original code/detail and source location. |
| invalid_identity_label | A parsed label fails strict lifecycle validation, including ordinal zero; it remains a fact but cannot supply resolvable authority. |
| duplicate_definition | Multiple authoritative declarations use an exact label within one snapshot. |
| padding_alias | Distinct numeric spellings claim the same family/positive ordinal anywhere in the supplied history. Opaque composites are not numeric aliases. |
| definition_changed | An exact authoritative label has different typed content hashes. All variants remain available for explicit lifecycle/semantic reconciliation; this does not claim every edit changed the subject. |
| definition_missing | A definition disappears in the immediately following captured snapshot. Introduction or movement between captured files is not retirement. |
| issue_mapping_required | Every ISS display-label group requires explicit durable-issue mapping, including single occurrences, identical fingerprints, bare issue references and valid explicitly named ISS range endpoints. Intermediate range identities are never expanded. |
| unresolved_reference | A supported bare target lacks authoritative declaration in its own snapshot. Other snapshots, projections and prose mentions cannot resolve it. |
| ambiguous_reference | Duplicate declarations or historical numeric aliases prevent a unique target interpretation. |
| unsupported_reference_range | The typed interval is retained without expanding it into allocated identities or resolving only one endpoint. |

Parser diagnostics and conflicts coexist: the inventory is not a publication
gate, historical import/adoption, semantic approval, automatic reconciliation or
activation. It cannot authenticate completeness, historical quotations or Git
chronology, resolve unknown grammar/qualified references, merge competing
allocations, or relabel retained evidence as proof of new content. It writes no
report file or authority state. Explicit authenticated historical reconciliation,
lifecycle application, publication receipts and managed producer review remain
separate required work. No inventory authorizes resuming the stopped run or
bootstrapping authority from its latest files.

`IdentityStore.audit()` performs the complete existing counter, entity,
lifecycle, reference, occurrence, receipt, foreign-key, and SQLite integrity
checks within one query-only read snapshot. Its report contains the authenticated
authority marker, current database schema version, and canonical decimal row
counts for the fixed authority data tables. It does not repair data, create
receipts or checkpoints, initialize directories, or upgrade old state. Audit
integrity means that the ledger is internally consistent; it does not establish
semantic correctness, approved evidence, current publication, or managed
readiness.

`import-labels` accepts only an explicitly selected UTF-8 JSON document:

```json
{"schema_version":1,"spec_id":"demo","operation_id":"history-import-1","definitions":[{"element_id":"U-005","subject":"Largest-step collision behavior"}]}
```

This command delegates one atomic, idempotent subject-only import to the existing
authority. It preserves exact published labels, including padded labels such as
`FR-001` and composite historical IDs. It does not scan Markdown, infer IDs from
filenames, allocate from document maxima, import evidence or occurrences, or
invent lifecycle revisions. Imported labels remain `imported` and unassessed
until a separate explicit lifecycle and historical reconciliation process. Label
reservation claims unused new identities; historical adoption reconciles an
existing label and its meaning. They are deliberately different operations.

Backup is a complete point-in-time ledger copy for fresh-destination restore,
not permission to run two independently writable clones. Audit is likewise a
storage integrity operation, not activation of the still-inactive managed
identity rollout.

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
including imports, lifecycle changes, reference claims, and issue occurrences.
Reusing it with the same complete request returns the original
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
Conflicting reuse of the global operation ID fails across all record APIs.

Use `store.preview_lifecycle(spec_id=..., changes=(...))` to validate and project
the same batch against one current read snapshot without applying it. Application
and preview share the same connection-owned planner and namespace high-water
integrity checks. Preview returns one detached dictionary per planned head, in
input order and, within a transition, predecessor order followed by successor
order. Every dictionary has exactly `element_id`, `expected_status`,
`expected_revision`, `subject`, `content`, `content_sha256`, `revision`, and
`status`. The expected fields describe the actual head in that snapshot:
`None`/`None` for an unused reserved identity and `imported`/`None` for an
adoption. The remaining fields describe the proposed head. Terminal projections
retain the predecessor's content and digest.

A preview is advisory current-prestate information, not an authorization,
accepted candidate, or publication result. It has no operation ID and creates no
operation, revision, entity, head, lineage, or receipt record. Another connection
may commit after the preview ends. Applying the earlier proposal still performs
the normal expected-revision compare-and-swap validation in a new write
transaction and rejects a stale proposal; the detached preview is not updated or
replayed. Only `apply_lifecycle` owns global operation binding, durable receipts,
and matching-retry behavior.

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
publication still requires semantic review and allowed edit scope, integration of
typed artifact adapters and revision-bound claims/occurrences, publication
intents/receipts, graph/memory history, and bounded discovery repair. Consumers
must reject transitions they cannot represent before publication. This library
does not perform graph writes, provider routing, or canonical file publication.

## Immutable references and issue occurrences

`harness.element_identity_bindings` defines two frozen request types. Every field
is a scalar string except the explicitly nullable reference revision:

- `ReferenceClaim(source_path, source_sha256, source_anchor, target_id,
  target_revision, relation)`: the source path is canonical spec-relative POSIX
  syntax, without empty segments, traversal, absolute paths, backslashes or NUL.
  The lowercase SHA256 digest identifies declared source bytes. The nonblank
  anchor is an immutable controller-supplied locator within those bytes. Relation
  is exactly `reference`, `requires`, `depends`, or `evidence`. The target uses an
  existing exact supported label in the same spec. A non-null revision is a
  positive canonical decimal string identifying an existing historical assessed
  revision, including a terminal revision. `None` explicitly means unassessed or
  legacy; it never means the current revision.
- `IssueOccurrence(issue_id, issue_revision, report_id, report_sha256, display_id,
  title, body)`: the durable issue and historical display IDs are exact ISS
  labels. The immutable nonblank report provenance ID and lowercase SHA256 are
  retained separately. The issue must exist in the same spec, and title/body must
  exactly equal the immutable subject and retained content of its specified
  historical **active** revision. Historical active revisions remain usable after
  retirement. A different display label is accepted only as the caller's explicit
  mapping; no heuristic matching, merging, or implicit ISS allocation occurs.

`store.record_reference_claims(spec_id=..., operation_id=..., claims=(...))` and
`store.record_issue_occurrences(spec_id=..., operation_id=..., occurrences=(...))`
atomically retain complete ordered batches. Empty batches, duplicate identical
entries, malformed types, additional fields, mutable nested containers, missing
targets, and inconsistent historical bindings fail without effects. An occurrence
fingerprint is calculated with the existing `issue_fingerprint(title, body)`;
callers cannot supply one as authority. The existing resolution fingerprint guard
is unchanged: resolving an older occurrence does not certify changed repair or
evidence content in a later occurrence.

Record results are tuples of detached dictionaries containing every original
request field, plus `spec_id`, `operation_id`, and `entry_index` (canonical decimal
strings starting at `"1"`). Occurrences additionally contain `issue_fingerprint`.
These durable receipts contain no current-state metadata. Identical retries
return the original receipt after revisions, retirement, restart, or restore.
Conflicting reuse of an operation ID across any record method or spec fails.
A separate operation can retain a reassessed claim to a different revision;
it cannot replace the earlier claim. The future controller owns authorization
to reassess.

`store.reference_claims(spec_id=..., source_path=..., source_sha256=...)` retains
the original fields and adds `target_status` and
`target_revision_matches_current`. The latter is true only for an explicit
revision equal to the current **active** head. Unassessed, stale, retired and
superseded targets are false, including a claim pointing at the terminal head's
exact revision. This metadata is not a `verified`, `passed`, or semantic-gate
verdict. `store.issue_occurrences(spec_id=..., issue_id=...)` returns original
historical content and fingerprints. Both reads sort by `(operation_id, numeric
entry_index)`; this is deterministic ordering, not claimed chronology.

Rows bind their full canonical payload digest, including method, spec, operation,
and entry index. Global operation digests bind the entire ordered request, and
durable receipts bind every associated record. Reads and retries authenticate
these bindings using indexed source/issue/operation access and existing indexed
target, namespace-counter and lifecycle checks. Full audits detect missing or
orphan record/receipt associations. No routine path scans all historical records.
`element_identity_binding_store` receives only the existing store's connection;
it never opens files, commits, reserves IDs, or starts a second transaction.

Source hashes, anchors, and report provenance are declarations, not proof that
the caller holds or reviewed a file. The APIs never resolve anchors against live
files or infer replacement anchors after edits. A future publication transaction
must authenticate staged bytes and reviewer provenance and enforce allowed scope
and semantic correctness. These inactive records are historical foundations;
recording a hash or matching a current revision does not activate publication or
establish a completion gate.

## Explicit schema upgrade

`IdentityStore.upgrade(workspace)` recognizes only exact reviewed schemas 1
(allocation), 2 (lifecycle), and 3 (bindings), with their matching metadata.
Ordinary `open` on schema 1 or 2 reports that explicit upgrade is required and
does not mutate storage.
Upgrade audits authority, integrity, foreign keys, retained numeric claims,
reservation history and legacy import/reservation overlap inside one
`BEGIN IMMEDIATE` transaction. Schema 1 first gains lifecycle tables and
imported/null heads. Both older schemas gain only the binding tables/indexes and
schema metadata update; neither gains fabricated claims or occurrences. Exact
labels, counters, reservations, lifecycle history, retry bindings and UUIDs stay
intact. Current-schema audits retain shared entity label/kind/ordinal/subject
checks; legacy reservation/import overlap rejection applies only to schema 1.
A current-schema retry is an audited no-op. Interrupted DDL,
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

Internal transaction composers may call
`element_identity_lifecycle_store.apply_changes(...)` and
`element_identity_binding_store.record(...)` only with the authenticated
authority connection already inside the caller's active write transaction.
These connection-owned helpers do not open, begin, commit, roll back, or create
savepoints, and composers must let any lifecycle or downstream binding failure
abort the whole transaction. They must not nest public `IdentityStore` methods.
Composition alone does not authenticate historical sources, semantic decisions,
canonical files, or graph completion, and it does not authorize activation or
publication.

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
head bindings, lineage, binding records and durable receipts across all
namespaces before creating destination state. This explicit restore audit may
scan the snapshot to discover every namespace, including ones whose counters
are missing. Digest verification and copying share a read transaction, so a concurrent SQLite writer
cannot commit between them. The destination workspace must exist and have no
identity directory, even an empty one. Restore uses online backup into fresh
owner-only files and preserves the exact workspace UUID, epoch, imported subjects,
operation receipts, counters, and reservations. It never merges or overwrites.
A recognized schema 1 or 2 backup is validated before claiming destination
state, then upgraded transactionally only in the fresh restored database. The
backup itself is unchanged. Unknown schema versions fail before destination
creation. Current backups retain lifecycle history, immutable claims, original
receipts, report provenance and issue fingerprints.

A backup is a point-in-time snapshot. Restoring an old snapshot cannot recover
reservations committed after it. Quiesce the original authority and ensure the
chosen backup includes every externally used reservation before adopting a
restored copy as its successor. Reopening or rewinding a document does not rewind
the live ledger. Never regenerate a missing established ledger from current
document maxima. Independently advancing restored copies must not be merged or
treated as one allocation authority; they share identity/epoch and can issue
overlapping future ordinals.

## Focused verification

The unit contracts are in `tests/unit/test_element_identity_store.py`,
`tests/unit/test_element_identity_lifecycle.py`, and
`tests/unit/test_element_identity_bindings.py`, with frozen reviewed v1 and v2 SQL
fixtures for migration compatibility. Process
contention, committed-process termination, concurrent backup, lock timeout, and
capacity checks and competing revisions from one baseline are in
`tests/integration/test_element_identity_store.py`.
The million-entity capacity test has `integration` and `slow` markers, imports
bounded 10,000-row batches, verifies indexed query plans, and reports elapsed
time and database size without a timing threshold. It is outside the unit suite
(`pytest -m unit`); select its integration file to run it explicitly.
