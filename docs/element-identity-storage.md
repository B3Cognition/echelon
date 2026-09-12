# Element identity allocation, lifecycle, binding, and publication journal storage

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
glossary and product inputs require an explicit complete selection. The joint
inspection below captures that declared selection in one scope; sequential
snapshots are not an atomic cross-tree read set. Candidate writing, provider
dispatch, identity allocation/lifecycle/binding, controller routing, publication
promotion and activation are unchanged.
Existing Phase A completion transactions, candidate isolation and repair remain
the integration owners. Rejected candidates stay diagnostic and cannot update
canonical artifacts, graphs or memory. Published labels, including `FR-001` and
historical composite IDs, remain exactly as published.

## Joint sealed-publication and selected-source inspection boundary

`PreparedSquadPublication.inspect_sources(tree_paths=(), file_paths=())` is an
inactive, read-only building block for a future durable identity publication
intent. The controller supplies both sequences explicitly. Before opening
descriptors or acquiring the lock, the reader copies and validates every exact
UTF-8 string using the existing canonical nonempty project-relative path grammar.
Empty batches are valid; strings and bytes are not batches. Duplicate paths and
component-wise ancestor/descendant selections fail within and across both batches,
including file/file overlaps. Prefix siblings such as `spec/a` and `spec/ab`
remain distinct. A sealed operation target may also appear in the source
selection; this is necessary for baseline observation.

The frozen `PublicationSourcesSnapshot` in `harness.squad_source_snapshot`
contains the entire unchanged `PublicationSnapshot`, a path-sorted tuple of
`ProjectTreeSnapshot` values and a path-sorted tuple of `ProjectPathSnapshot`
values. Individual paths carry `path`, the exact `PublicationImageDescriptor`,
and `content`: a missing file or ancestor gives a missing descriptor and `None`,
while an empty regular file gives its actual hash/mode and `b""`. Directories,
symlinks and special files are rejected for individual file selections. Trees
retain their complete iterative traversal semantics, including hidden/binary
files, all directory modes and memberships, and nested empty directories. Stable
hardlinked regular files retain the existing read-only capture behavior; link
count, content and identity changes still invalidate their pins. Absence is never
materialized, and resource or capability failures fail closed without truncation.

Both public inspectors share one sealed-capture implementation, and both tree
readers share one traversal implementation. Joint inspection acquires exactly
one existing project inspection scope and publication lock associated with its
retained root descriptor. All selected sources, missing components, directories,
file identities and sealed transaction resources belong to that scope's resource
owner. Immediately before yielding and again on normal exit, it jointly verifies
all retained source bindings/memberships and the sealed transaction, even when
both selections are empty. A source changed while a later source is being read
cannot escape before yield; body-time drift fails normal exit. Caller exceptions
propagate unchanged and release the lock and owned descriptors.

There is no implicit workspace scan, extension filter, Markdown decoding, role
inference, external-project traversal or filtering of sealed operations. Source
trees/files observe current canonical bytes; operation postimages describe the
sealed proposed bytes. No staged bytes are overlaid onto source observations.
An interrupted promotion still exposes the existing global prefix lower bound
and no-op ambiguity; current postimages cannot reconstruct original preimage
bytes. The future intent owner must authenticate declared dependency coverage,
retain original before images, validate typed role/scope mappings and semantic
review, and perform candidate checks on one guarded ledger baseline.

Keep this controller-owned scope short: do not run providers or recursively
inspect, publish or discard inside it. Successful observation includes normal
context exit. A caller write committed inside the body is not undone by a later
source-drift exception and must not be considered completed on yield alone.
These detached values supply no receipt, durable lease, graph permission,
semantic assessment, promotion authority or post-exit freshness. Pending-write
protection, recovery/finalization, graph receipts, managed producers and bounded
repair remain required. There is no new schema, on-disk protocol, identity write,
provider routing, promotion/discard behavior or activation. Existing Phase A
completion transactions, candidate isolation and repair remain the owners, and
published labels and string IDs retain their exact spelling.

## Initial source-baseline recovery codec

`harness.squad_source_baseline_codec` is a pure, inactive codec for losslessly
retaining a successful joint observation before any target is promoted.
`encode_initial_publication_sources(snapshot)` accepts only the exact frozen
snapshot, publication, marker, operation, image, tree, directory and file value
types with exact tuple sequences. The publication prefix must be the exact integer
zero, and every operation's current descriptor and actual bytes must independently
match its preimage. Zero alone is not evidence that original bytes remain. Writes
must carry a present file postimage and exact staged bytes; deletes must carry the
missing postimage. Empty and exact no-op operations remain valid.

The version-1 payload is canonical ASCII JSON with sorted object keys, compact
separators and no trailing newline. Its root contains only string `version="1"`,
`publication`, `trees`, and `files`. Publication contains only `marker` and
`operations`; the marker contains string `schema_version="1"`, transaction ID and
manifest SHA-256. The zero prefix is implicit and is not serialized. Each operation
contains only `action`, `target`, `preimage`, and `postimage`. Each image contains
only `kind`, `sha256`, `mode`, and `content_base64`: missing images use `"missing"`
and three JSON nulls, while files use their lowercase digest, canonical decimal
permission-mode string, and canonical ASCII base64 of the exact bytes. Empty files
therefore use an empty base64 string rather than null.

Each tree contains only `path`, string `exists` (`"true"` or `"false"`),
`directories`, and `files`. Directory entries contain only `path` and canonical
decimal `mode`; tree and selected-file entries contain only `path` and an image.
Paths preserve exact valid UTF-8 code points and use the existing canonical
project-relative grammar. Trees and selected paths retain complete sorted,
non-overlapping membership, including hidden and binary files, CRLF, Unicode,
empty/missing files, nested empty directories and permission distinctions. A
target represented by that complete selection must agree with the selected
original observation. Selection does not grant write scope, and operations outside
the selection remain fully retained.

`decode_initial_publication_sources(payload)` uses strict duplicate- and
number-rejecting JSON parsing, exact closed key sets and exact scalar types. It
reconstructs every operation's `current` descriptor and bytes from the retained
preimage, never from a live target, and returns detached tuples, frozen values and
bytes. Re-encoding must equal the supplied payload byte-for-byte, so alternate
whitespace, key order, escaping, base64 spelling and decimal padding are rejected.
Both functions raise only bounded `PublicationError("manifest_invalid")` for
malformed input and perform no filesystem, database, clock, randomness, network,
provider or store access.

This format retains claims; it does not authenticate them. It lacks manifest stage
filenames and therefore cannot recompute the sealed manifest digest. A
self-consistent altered payload can decode. A future completion owner must compare
the value with its intended authority, accepted baseline and authenticated sealed
publication, then validate unchanged dependencies under the existing publication
lock before promotion. Decoding, digest equality or round-trip success does not
authorize publication. The codec does not select dependencies, infer artifact
roles or source associations, enroll namespaces, reserve or allocate identities,
persist a recovery packet, publish, update graphs or memory, or activate any
controller/provider/producer path. Historical evidence remains retained evidence;
it is not relabeled as proof of new content. Complete crash recovery across artifact
promotion, ledger publication and graph projection remains future completion-owner
integration and must prevent duplicate allocation and false completion.

## Selected source observation manifest

`harness.squad_source_manifest.snapshot_source_manifest(trees=..., files=...)`
is an inactive, pure fingerprinting helper for the exact immutable tree and file
tuples returned by a successful selected-source capture. It does not accept the
publication snapshot and does not inspect operations, marker, transaction ID or
promotion state. The same sources therefore produce the same value across
transactions, while a valid observation made before, partway through or after
publication can produce a different value as the selected current sources change.
That difference describes only observation; it does not classify publication
state or authorize completion.

The version-1 payload is compact canonical ASCII JSON with exactly `version`,
`trees` and `files` at its root. It retains the selection's canonical paths,
string-valued existence flags, complete directory membership and decimal modes,
and regular-file or missing image descriptors. File descriptors retain the exact
lowercase content SHA-256 and decimal mode; missing files retain null hash and
mode. Original bytes and `content_base64` are deliberately omitted only after the
shared initial-baseline validators have checked those bytes against every retained
image. `SourceManifestSnapshot.sha256` is the lowercase SHA-256 of the exact ASCII
payload without a prefix. Both result fields are detached strings on a frozen,
slotted value.

Only the caller's explicit tree and file selection participates. Equal
fingerprints make no claim about unselected project content, dependency-selection
completeness, source ownership, semantic approval or accepted authority. The
factory performs no filesystem access, namespace lookup, parsing, provider work,
clock/random operation, registration, storage or compare-and-swap. In particular,
it neither replaces the initial byte-retention codec nor weakens that codec's
pre-promotion guard: crash recovery still requires retained original bytes.

A later completion owner must durably bind a complete declared selection to the
appropriate namespace and publication receipt, store its accepted manifest,
recapture under the existing guarded scope, and compare against that authority
while coordinating source, ledger and graph completion. No accepted-source head,
schema, provider API or controller activation is introduced here.

## Selected source manifest wire validation

`harness.squad_source_manifest_codec` is a pure, inactive representation boundary
for the exact metadata wire already emitted by `snapshot_source_manifest`.
`decode_source_manifest(payload)` accepts only the canonical ASCII version-1 JSON
shape and returns a fresh existing `SourceManifestSnapshot` containing the
unchanged payload and its lowercase, unprefixed SHA-256. It does not reconstruct
source bytes, an initial publication capture, a publication snapshot or a receipt.
`validate_source_manifest(snapshot)` requires the exact existing frozen snapshot
type, decodes its payload, validates the supplied digest and returns the detached
decoded value. The intentionally simple snapshot constructor remains unchanged.

The decoder closes every object key set and requires exact JSON arrays and scalar
types. It rejects duplicate keys, numeric or Boolean substitutes, unknown aliases,
alternate versions, noncanonical whitespace, ordering, escaping, literal non-ASCII
text and trailing data. Tree existence remains the exact strings `"true"` and
`"false"`; modes remain canonical decimal permission strings; paths retain the
existing exact project-relative UTF-8 grammar. File images contain only `kind`,
`sha256` and `mode`. Present files require the publisher's lowercase SHA-256 rule
and canonical mode range. Missing images require both null fields and are valid
only for explicitly selected files, never for tree membership. There is no
`content_base64` field in this metadata representation.

Tree directory and file sequences retain the same sorted, unique, component-aware
layout rules as initial source-baseline encoding. Both codecs call one shared
private layout validator for absent-tree emptiness, root membership, explicit
directory parents, path containment, collisions and regular-file ancestors. The
initial codec still independently validates every exact dataclass, actual byte,
hash and mode before that shared layout check; factoring the hierarchy rules does
not weaken its pre-promotion byte-retention boundary.

Both public wire functions normalize malformed JSON, Unicode, structure, type,
mode, hash, path, selection and recursion failures to bounded
`PublicationError("manifest_invalid")` without retaining untrusted exception
context. They do not access the filesystem, SQLite, a provider, network, clock or
randomness and do not mutate the payload or supplied snapshot.

Canonical decoding is validation of a metadata claim, not authentication. A
caller can replace a file SHA-256, canonically re-encode the payload and obtain a
different self-consistent decoded fingerprint because this wire deliberately has
no original bytes or accepted authority to compare. Such a value is not an
accepted baseline, proof of actual-source integrity, publication permission or a
provenance receipt. Durable accepted-source heads still require explicit
namespace/spec/run/source context, compare-and-swap ownership and binding to the
guarded publication receipt. No store/schema/source-head registration, capture,
publisher, controller, provider, graph or producer path is added or activated by
this codec.

## Expected final publication source projection

`harness.squad_source_projection.project_publication_source_manifest(initial)`
is an inactive, pure projection from one validated initial joint publication/source
capture to the exact selected-source fingerprint expected after every sealed
operation succeeds. It first applies the existing initial source-baseline encoder
as its pre-promotion and structural guard. It does not manufacture an initial
capture from a partial or final observation, and it preserves the guard's bounded
publication failure.

Projection is component-relative and cannot expand the explicit selection. Exact
writes replace selected file images with their sealed postimage and bytes; exact
deletes make explicitly selected files missing. Within a selected tree, writes add
their file and only absent directory ancestors down through the selected root.
Those newly required directories use `PUBLICATION_DIRECTORY_MODE`, the existing
publisher's `0755` mode for directories it successfully creates; existing directory
objects and modes remain unchanged. Deletes remove only the exact regular file and
retain directories. Missing no-op deletes create nothing, absent trees remain
absent unless a write below them creates their root, and empty directories, hidden
files, binary content, empty content and permission distinctions remain represented.
The existing source-manifest factory owns final canonicalization and hashing.

A write at or above a selected tree root, or strictly above or below an explicitly
selected file, is rejected because the resulting regular-file/directory shape could
not be captured as selected. Component-prefix siblings and operations outside every
selected source do not affect the result. This check says nothing about whether an
outside operation had valid ownership, review or write scope.

The projection performs no capture, publication, parsing, persistence, clock,
randomness, provider or network work. It predicts only a successful final state: it
does not authenticate the seal or selection, classify an interrupted prefix, make
interference recoverable, compare a fresh observation, or authorize completion.
A later completion owner must bind expected and observed fingerprints to durable
namespace, accepted-source, candidate-review and sealed-publication authority and
compare them under descriptor and lock continuity before promotion. Partial-state
recovery, run-local versus published source association, managed-producer
enforcement, graph/memory currentness and bounded repair remain outside this helper.

## Guarded selected-source publication

`PreparedSquadPublication.publish_sources(initial, ...)` is an opt-in physical
publication boundary. It validates the retained original with the existing
initial codec and final projection guard, then holds one descriptor-associated
publication lock while using the same promotion loop as `publish()`. The
original root and sealed stages remain pinned; guarded target reads, parent
creation, replacement, deletion and directory durability checks use the retained
project descriptor. Legacy `publish()` remains the default behavior.
Existing target ancestors retain their descriptor/entry associations for the
whole invocation; newly created or first traversed target parents join that
owner before traversal descriptors close. No old membership or missing-entry
pins are retained across authorized mutations. This inode association lasts
only for the invocation; serialized originals have no inode authority across
recovery calls. Read-only non-target source directories retain checked-capture
semantics.

Each short observation compares the complete explicitly selected source manifest
against the original plus the authenticated ordered operation prefix. This
includes hidden and binary members, file and directory modes, empty directories,
individual files and absences. The sole extra intermediate shape is a contiguous
canonical `0755` parent-directory prefix for the next unfinished write. It cannot
authorize siblings, later-operation parents, temporary files or noncanonical
directory modes. Unclassified damage remains blocked and recovery material is
retained; this is not arbitrary interrupted-state repair.

Trusted short `before_publish` and `after_publish` callbacks execute under that
same lock with actual captured snapshots whose normal pins survive callback
return and exit validation. The first callback follows source/seal validation;
the second follows exact final validation. Both may repeat on retries and must
have independently idempotent owner effects. Callback exceptions propagate;
before-callback failure promotes nothing, while after-callback failure can leave
all files published without reporting success. Hooks must not recurse into lock
owners, run providers or perform broad or long-running work.

The caller must separately authenticate the original capture, selection
completeness, namespace/context, scope and semantic acceptance. A self-consistent
snapshot that omits a dependency cannot reveal that omission to this method.
These checks cover observation boundaries under a cooperating publisher lock;
they do not detect every transient mutation restored between observations.
The method creates no identity intent, releases no journal, discards no stage,
and activates no controller, producer, graph, memory or provider path. A closed
versioned source bundle and durable intent still belong under the existing
SquadController completion owner before any live integration.

## Captured candidate source assembly

`harness.element_identity_candidate_sources.assemble_candidate_sources` is an
inactive, pure adapter between a validated initial `PublicationSourcesSnapshot`
and the existing immutable `CandidateArtifact` input. It first invokes the initial
source-baseline encoder as the structural and original-image guard. Invalid source
authority therefore remains a bounded `PublicationError`; the adapter neither
rebuilds a baseline from current postimages nor authenticates an encoded round trip.

The caller supplies an explicit one-to-one `CandidateSourceBinding` for every typed
physical source it wants to expose. Physical `source_path` values use the captured
project-relative POSIX namespace. Logical `artifact_path` values use the candidate
artifact/reference namespace, and `role` must be one of the existing identity roles.
No prefix is stripped, root derived, filename interpreted, or role inferred. A
source is available only when it is a sealed operation target, an explicitly
selected file, or a component-wise member of a completely selected tree. Exact
directories, descendants of known regular files, textual prefix siblings, and
otherwise uncaptured paths are controller mapping errors. Missing selected files,
missing tree members, and missing operation targets remain absent; present empty
files remain empty strings.

For an operation target, the candidate before image is the retained initial
`current_bytes` and its after image is the sealed `postimage_bytes`. Other selected
sources have identical before and after images. Exact UTF-8 text is preserved,
including BOMs, CRLF, whitespace and Unicode. An invalid typed before image is a
bounded request error because authenticated history cannot be offered as candidate
repair. An invalid proposed after image produces `candidate_source_not_text` and
omits only that artifact. Unbound selected binary and hidden files remain in the
retained physical snapshot without being decoded or relabeled.

Every sealed operation, including no-op writes, missing deletes and mode-only
changes, is checked using exact physical path equality. A target outside
`writable_paths` receives `artifact_out_of_scope`; a target lacking either a typed
binding or explicit `opaque_write_paths` classification receives
`publication_target_unbound`. Opaque paths must also be writable and cannot overlap
typed bindings. They authorize only the declared physical operation: they produce
no artifact and convey no role, namespace, semantic, or source-selection approval.
Diagnostics use physical paths and the existing deterministic candidate ordering;
artifacts use logical paths and are sorted independently. Callers must reject any
diagnostics before treating the artifact tuple as successfully assembled.

This helper performs no filesystem, database, network, clock, randomness, store,
parser, provider, publication, allocation, lifecycle, reference resolution, or
semantic-review action. It does not prove source-selection completeness, namespace
ownership, edit-scope correctness, accepted-source freshness, or publication
authority. Later controller integration must retain the complete physical snapshot,
bind it to durable accepted-source and managed-run contracts, combine these physical
diagnostics with structural and semantic review, and reject diagnostics before any
publication, ledger, graph, memory, or completion update.

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

## Inactive durable publication journal

`harness.element_identity_publication` defines exact frozen, slotted request types:
`PublicationOperation(method, operation_id, payload)` and
`PublicationIntentRequest(manifest_sha256, recovery_payload, operations=(), sources=None, proposed_history_sha256=None)`.
The operations tuple contains at most one operation for each of `lifecycle`,
`reference_claims`, and `issue_occurrences`, in that order; any subset, including
the empty tuple, is valid. Child IDs are unique, exact nonblank UTF-8 strings
without NUL and cannot equal the parent ID. Each child payload must already be
the canonical ASCII output of the existing method-specific request codec.

Without optional source/history claims, `encode_publication_request` produces canonical ASCII JSON with exactly `version`
(string `"1"`), `manifest_sha256`, `recovery_payload`, and `operations`; every
operation contains exactly `method`, `operation_id`, and `payload`.
`decode_publication_request` accepts that closed shape, rejects duplicate keys at
every level, numeric/nonfinite tokens, malformed/deep input, unknown fields and
versions, and invalid UTF-8. Both codecs share one strict JSON parser. All public
and internal request boundaries revalidate exact types, including altered frozen
objects. No integer coercion changes labels or arbitrarily wide revision strings.
Codec failures use bounded `PublicationIntentError`; store failures normalize to
`IdentityStoreError`.

The manifest hash uses the existing exact lowercase SHA-256 grammar. Recovery
payload is retained as an exact nonblank/NUL-free UTF-8 string. Storage neither
parses nor certifies its source coverage, original preimages, semantic judgments,
or filesystem paths. A future completion owner must construct and authenticate
the complete versioned recovery bundle; a provider assertion does not supply that
authority.

The store exposes these keyword-only methods:

- `prepare_identity_publication(spec_id, operation_id, request)` validates the
  lifecycle plan and projected bindings on one `BEGIN IMMEDIATE` snapshot, then
  atomically retains the parent operation, request, exact plan and child claims.
  It applies no child operation and does not materialize reserved IDs.
- `apply_identity_publication(spec_id, operation_id)` authenticates the prepared
  journal and baseline, then invokes the existing connection-owned lifecycle
  and binding writers in request order. Every child effect, its original receipt,
  the application receipt and the state change commit together. A failure before
  commit rolls them all back, retaining the prepared intent and guard. A failure
  reported after an actual commit is an uncertain outcome recovered by reading
  and retrying the original receipt; it is not evidence of rollback.
- `release_identity_publication(spec_id, operation_id, completion_payload)`
  requires an applied intent and retains exact nonblank/NUL-free UTF-8 completion
  data. Only this explicit transition releases the spec guard. It supplies no
  independent verification of graph or completion evidence.
- `identity_publication(spec_id, operation_id)` and
  `pending_identity_publication(spec_id)` use one query-only transaction and return
  detached records with exactly `preparation`, `state`, `request`,
  `application_receipt`, and `completion_payload`. Request/application fields are
  canonical JSON strings, with an absent application or completion represented by
  `None`. A missing intent returns `None`; an ID belonging to another method or
  spec fails instead.

The corresponding connection-owned functions in
`harness.element_identity_publication_store` are `prepare(connection, store,
spec_id, operation_id, request)`, `apply(connection, store, spec_id, operation_id)`,
`release(connection, store, spec_id, operation_id, completion_payload)`,
`read(connection, store, spec_id, operation_id)`, `pending(connection, store,
spec_id)`, and `audit(connection, store)`. They require an active caller transaction,
revalidate inputs, and never begin, commit, roll back, or change PRAGMAs themselves.
Callers must let an exception roll back their composed write transaction.

State moves only `prepared` → `applied` → `released`. Empty batches still gain an
application receipt and stay guarded until release. Prepared records cannot
release. There is no cancellation, timeout, automatic release, process-exit release,
guard-clearing CLI, or history deletion. Abandoned reservations remain allocated.

The guard is spec-wide: every new reservation, import, lifecycle change, reference
claim, issue occurrence, or publication preparation for the pending spec fails,
even if it concerns another element. This deliberately trades write concurrency
inside a spec for a stable preparation baseline. Other specs continue except
that child IDs are globally claimed. Exact already-completed ordinary retries
retain their original receipt behavior; conflicting arguments fail. A prepared
child cannot execute through a public writer even with matching arguments. After
application/release, only its exact original receipt can replay. Claims remain
permanent after release and prevent method/spec/digest takeover. A missing applied
child is damaged history, never permission to recreate it.

The common operation gate remains the only child-operation insert path. A private
per-call adapter delegates to existing validators/writers and passes its owner ID
only at that gate, which authenticates the prepared owner and exact request/claim
association. Public writer signatures expose no owner bypass. Pending-spec and
global-child lookups use indexes; ordinary allocation/import algorithms remain
unchanged.

Schema 4 adds only `publication_intents`, its unique partial `publication_pending_specs`
index, `publication_operation_claims`, and its unique `publication_claim_methods`
index. The parent operation method is `identity_publication`; child claims need
not yet have an operation row. The retained plan is canonical ASCII JSON with
`revisions` (the existing eight-field planner rows) and `lineage` (the existing
seven-field rows), empty without lifecycle work. Request, plan, and application
hashes cover ASCII bytes; completion hashes cover exact UTF-8 bytes. The parent
digest is the existing `_digest(["identity_publication", spec_id, operation_id,
request_json, plan_sha256])`. Existing child digest formulas, SQL writers and
receipt formats remain unchanged.

Preparation receipts contain exactly string `version="1"`, `workspace_uuid`,
`epoch_uuid`, `spec_id`, `operation_id`, `request_sha256`, and `plan_sha256`.
Namespace identity comes from validated metadata on the same connection, including
class-based upgrade/restore audits. Application receipts contain string
`version="1"`, `publication` (the original preparation receipt), and `operations`
(ordered objects containing `method`, `operation_id`, and the original child
`receipt` as an array). Release receipts contain string `version="1"`,
`publication`, `application_sha256`, and `completion_sha256`.

Exact preparation/application/release retries authenticate retained history and
return the original receipt; changed request or completion arguments fail. Released
requests are never replanned against newer current heads. Audits include decimal
string counts for both new tables and detect malformed hashes, plans, receipts,
claims, parent/child associations, orphan records, premature or incomplete child
application, and differences between persisted rows/lineage and the retained plan.
These are authority failures, not repair findings. Hash checks do not protect
against coherent malicious rewriting of all SQLite history and hashes.

No filesystem, provider, candidate, graph, controller-routing, or producer
integration is activated here. The existing completion owner must authenticate
sealed/current files under the existing publication lock before application, and
mandatory graph/history and completion evidence before release. A call to release
inside an inspection body before its normal-exit verification is invalid integration.
Storage receipts prove retained ledger transitions, not semantic approval, file
acceptance, complete dependency capture, or graph completion. Run-local/manual
acceptance and final export still need one shared integration without duplicate
revisions; historical reconciliation, managed feature snapshots, all seven
producers, bounded repair, and offline/live checkpoints remain follow-on work.

## Durable accepted source contexts (inactive schema 5)

`register_source_context(spec_id=..., context_id=..., operation_id=..., manifest=...)`
explicitly accepts one validated, detached `SourceManifestSnapshot` as the initial
head of a caller-selected observation scope. `context_id` is an opaque name within
the canonical spec, not a pathname or inferred run. Multiple contexts may coexist.
Registration neither allocates IDs nor changes revisions, files, or the materialized
identity-history wire. It cannot replace a context, reset its history, or silently
refresh dependencies. It records an ordinary globally owned `source_context`
operation with `_digest(["source_context", spec_id, context_id, manifest.payload])`
and joins the existing pending-spec and permanent-child guard. An exact registration
retry returns its original receipt even during another pending publication or after
later accepted heads; changed arguments and other operation IDs cannot take over.

`source_context(spec_id=..., context_id=...)` reads one detached current-head record
in one query-only transaction. Both APIs return exactly string `version="1"`,
`workspace_uuid`, `epoch_uuid`, `spec_id`, `context_id`,
`registration_operation_id`, `operation_id`, `sequence`, and `manifest` (exactly
`payload` and `sha256`). Registration has sequence `"0"` and its own operation ID.
Accepted publications use their parent operation ID and a positive unbounded
canonical decimal sequence. Even equal-content publications advance once. The
compare-and-swap token is the original predecessor receipt identity, not equal
content hashes. Missing context reads return `None` only without associated orphan
source authority; orphan registration operations cause conservative rejection
within that spec because their digest cannot reconstruct a deleted context name.

The optional exact frozen/slotted `PublicationSourceClaim(context_id,
expected_operation_id, baseline_payload)` makes a publication source-bound.
`baseline_payload` is the unchanged canonical initial-source encoding, retaining
all original prefix-zero images and complete selected bytes. Its marker hash must
equal the enclosing request's manifest hash. Codecs revalidate intact exact types
at every boundary, reject malformed/deep/Unicode inputs with bounded errors, and
perform no I/O. Recovery and completion payloads retain their existing opaque
contracts. A source-bearing request without a history claim has string version `"2"` and exactly the
version-1 root fields plus `sources`, whose only fields are the three claim fields.
There is no `sources:null` wire variant. Source-less requests retain their exact
version-1 bytes, decoded defaults, child codecs, operation order, and receipts
when no history claim is supplied. History-bound version `"3"` is described below.

First prepare requires the exact current predecessor and the exact before manifest
derived from the retained source trees/files. Ordered selected tree roots and
explicit file paths must equal registration and the projected after selection.
The existing final projector derives the after manifest; callers cannot supply
an arbitrary after hash. The next sequence, predecessor and projected source plan
are retained atomically with the existing parent/child claims. Prepared rows have
no application digest and do not advance the head. Apply uses the existing three
child writers, then atomically accepts that plan and advances the independent
context pointer from its exact predecessor. Without a history claim, its closed version-2 application
receipt contains exactly `version`, `publication`, `operations`, and `sources`
(the full new source-head receipt). The canonical application hash is stored in
both the parent and source row, without a circular self-hash. Release retains its
version-1 shape and binds that exact application hash. Original prepare/apply/release
retries validate retained associations before any comparison with today's head,
so later accepted publications do not reapply or rewind old receipts.

Schema 5 adds only `source_contexts`, `source_publications`, the unique context
sequence index, the partial numeric accepted-head index, and the partial
spec/operation registration index. The initial registration manifest is immutable;
only `source_contexts.head_publication_id` advances. A current read requires this
independent pointer to match the indexed highest accepted row. Missing pointed
rows, highest-row deletion, pointer-only rewind/clearing, premature acceptance,
or cross-context pointers fail without repair or fallback to registration.
Exact context/parent lookups use primary keys; head reads validate the current row
and its immediate retained predecessor without recursive history replay or reads
of historical identity child tables. They validate indexed parent/child ownership,
the closed application envelope and preparation binding, and source/state/digest
associations. Full historical child-effect reconstruction remains in explicit
journal reads/retries and full authority audits. Full
audits validate every chain, contiguous sequence increments, original registration
digests, parent/source associations, and highest heads. Recomputed local hashes
cannot make a source plan disagree with its retained request or predecessor.
This detects contradictions; it cannot authenticate a coherently substituted
older entire database against an external authority.

Connection-owned helpers in `element_identity_source_store` require an active
caller transaction and never own commits, change PRAGMAs, acquire publication
locks, read files, or call providers. The real guarded publisher is composed with
prepare/apply only in tests: interrupted promotion keeps the original source head
and prepared intent, recovery decodes the stored original baseline, and explicit
release follows successful owner completion. After-callback failure retains the
pending guard and recovery material. No controller, provider, graph, CLI, or memory
producer is activated.

Contexts and complete selections are trusted caller declarations. A genuinely
empty selection is valid metadata, not proof of dependency completeness. A
self-consistent request naming another registered context is judged against that
context; this library cannot authenticate which context the live caller should
choose. Future managed-run wiring must bind the exact context and namespace,
authenticate complete dependencies and their refresh, canonical relocation,
semantic review, graph bytes, and completion, and protect ledger access. Source
acceptance does not establish filesystem freshness or semantic approval. Shared
external-dependency changes require an authenticated owner transition, not an
accepted-head overwrite. Historical reconciliation, bounded repair, revision-aware
memory, and live/offline controller matrices remain separate work.

## Immutable managed genesis registration (inactive schema 6)

`register_managed_identity(spec_id=..., operation_id=..., request=...)` explicitly
enrolls one fresh, unallocated spec. Its frozen `ManagedIdentityRequest` has exactly
seven string fields: `workspace_uuid`, `epoch_uuid`, `run_id`, `context_id`,
`spec_path`, `source_registration_operation_id`, and `source_manifest_sha256`.
The pure codec uses canonical ASCII JSON with those fields and version string
`"1"`; it rejects noncanonical UUIDs, paths, hashes, malformed text and wire shapes.
The supplied namespace must equal the actual retained authority.

The source context must already exist for this spec and still have its original
sequence-0 head. Its original operation and manifest SHA must match the request.
The original manifest must select `spec_path` as a tree root that exists, contains
exactly its root directory entry, and contains no files. Existing valid root modes
are retained; other selected trees/files may contain external dependencies. This
fresh-enrollment check does not authenticate the completeness of source selection.
The registration transaction audits the full existing authority before inserting
its operation, then rejects any counters, reservations (including abandoned gaps),
entities, lifecycle history, bindings, or identity publications for this spec.
Retained non-source operations also reject enrollment, including an empty import
or a legacy import whose entity rows have been removed.
Other specs may have valid history. Existing or imported identities cannot be
enrolled through this path, even when rendered files or active rows are empty.

Schema 6 adds `managed_identity_specs`, one immutable row per spec with a globally
unique run ID, and the partial `managed_identity_operations` index. Registration
records one globally owned ordinary `managed_identity` operation with digest
`_digest(["managed_identity", spec_id, operation_id, request_payload])`, atomically
with its registry row. It allocates no IDs and creates no lifecycle, source
acceptance, or publication effects. Common pending and permanent child ownership
guards apply. There is no replacement, update, deletion, or implicit enrollment API.

`managed_identity(spec_id=...)` returns a detached record containing version string
`"1"`, the seven request fields, `spec_id`, and `operation_id`. Exact original
operation/request retries return that record after later source acceptance,
identity revisions, pending publications, and reopen. They validate the original
source registration and its independently retained manifest hash; they do not
require the current source head to remain initial or its current tree to be empty.
Rehashing a changed original source manifest and its local operation still
contradicts the genesis hash. Ordinary reads use indexed registry, operation, and
source lookups without identity child-history scans. A missing registry row means
`None` only when no retained managed operation for that spec indicates damage.
Full audit, history capture, backup, upgrade, and restore validate registry rows
and orphan operations. The materialized identity-history wire/digest is unchanged.
These checks detect local contradictions, not coherent substitution of an older
entire database.

Version 1 identifies the fixed seven-family genesis contract. This is immutable
first-run metadata, not an active-run pointer or an enforcement switch. No existing
runtime is enrolled or activated. Future controller/producer integration must
consume this record before dispatch/completion, prevent metadata removal or
downgrade, bind subsequent run transitions explicitly, isolate candidates, and
retain source/identity/graph recovery. Retarget, replay, manual and historical
enrollment transitions require separate retained protocols. This task does not
choose provider proposal formats, graph staging, or later run transitions.

### Opt-in managed context authentication

`check_managed_context(spec_id=..., run_id=..., record=...)` is the read-only
authority association for one explicitly selected managed context. The caller
supplies the selected spec and run independently of the record. The method first
applies the exact lifecycle string rules and the closed ten-string record
validator, then requires the independently supplied identifiers and the complete
record to equal the retained managed genesis. It does not derive selection from
mutable state or provider output, fill missing values, normalize labels, or treat
a structurally valid state record as durable provenance.

One existing query-only identity transaction reads the retained genesis and its
source context. The result is a detached dictionary with exactly
`managed_identity` and `source_context`: the former is the unchanged original
ten-string genesis, while the latter is the full current retained source receipt,
including namespace, spec/context/registration/operation identifiers, sequence,
and manifest payload/hash. The source receipt must remain associated with the
matched genesis namespace, spec, context, and original source-registration
operation. Existing managed and source readers continue to own row, digest,
operation, parent, head, and immediate-predecessor integrity validation. The
checker adds no schema, files, locks, writes, enrollment, recovery, or child-history
scan, and a missing genesis is an error rather than a legacy result.

Original genesis and current source observation are intentionally different
facts. Later accepted source publication changes only the returned current head;
it does not copy the new operation or manifest hash into immutable genesis.
A prepared publication still exposes the old accepted head, while applied and
released publications expose the newly accepted head. Release is not certified
by this check, and neither a pending nor a released journal proves coordinated
completion. The returned head is only a coherent transaction snapshot: it is not
a reservation or freshness guarantee after return, and a later publisher must
still compare-and-swap that exact head and authenticate newly captured bytes.

The checker observes registry metadata, not current source files. Physical files
may differ after capture without changing the retained result; trusted runtime
owners must separately validate state before calling, authenticate current
physical source scope and bytes, and keep state reads outside the identity
transaction. Missing or damaged authority, changed handle namespace, orphaned
managed/source ownership, and unsupported old schema reject without initialize,
upgrade, repair, or a legacy fallback. This bounded association check is not a
full authority audit and does not certify arbitrary identity child history,
semantic assessment, graph publication, recovery, or completion. No controller,
provider, CLI, startup path, or producer invokes it in this phase.

## Authority and API

Call `IdentityStore.initialize(workspace)` explicitly once for a fresh authority.
The workspace must already exist. State lives in `.echelon/identity/`:

- `authority.json`: marker format version, workspace UUID, and authority epoch UUID.
- `registry.sqlite3`: matching authority metadata, operation receipts, counters,
  reservation ranges, entities, lifecycle heads, immutable content revisions,
  direct lineage, immutable reference claims, issue occurrences, publication
  intents, permanent child-operation claims, source contexts/publications,
  managed genesis registrations, and receipts.
  Database schema version is separate metadata (`schema_version=6`); marker
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

### Proposed materialized history before publication intent

`IdentityStore.preview_identity_history(spec_id=..., operations=())` returns the
existing frozen `IdentityHistorySnapshot` described below. The spec ID must be an
exact nonblank, NUL-free UTF-8 string. Operations must be an exact tuple of exact
`PublicationOperation` values, each using the existing canonical child request
encoding. Methods are unique and ordered `lifecycle`, `reference_claims`, then
`issue_occurrences`; operation IDs are unique. Values are revalidated and detached
before transaction use, including damaged frozen records. An empty tuple is valid.

This is a pre-intent observation for new, globally unclaimed child operations.
It rejects IDs already executed or permanently claimed by any publication in any
spec, and rejects a pending publication for the selected spec even for an empty
tuple. `identity_history` remains available during pending state. Another spec's
pending publication does not prevent an otherwise valid independent preview.

Preview uses one existing query-only transaction and the retained snapshot's full
authority audit. It overlays the journal's shared lifecycle plan and projected
binding validation on detached complete history, using the existing writers' row
construction and the same canonical ordering and encoding. Existing entities keep
their immutable identity fields; all prior revisions, lineage, references and
occurrences remain present. Imports remain unassessed unless explicitly adopted.
Historical active issue occurrences remain valid after retirement, and nullable
reference revisions retain their existing unassessed meaning. Candidate-only
active-dependency rules are not additional preview policy.

On an unchanged accepted database, applying exactly those child operations through
the existing journal produces byte-for-byte equal retained history payload and
hash. The wire remains version `"1"` with no proposed-state metadata. No parent,
source manifest, seal, receipt, reservation or claim is fabricated or written.
Planning does not simulate writes, use savepoints or copy SQLite. Ordinary input,
helper and storage failures produce a fixed bounded `IdentityStoreError` without
retained cause/context; `BaseException` propagation and transaction cleanup remain
intact.

The returned value has no lease, receipt or reserved baseline. A later legitimate
write can stale the original proposal; a fresh preview can observe changed
history, and actual prepare still owns parent-ID validation, new claims,
baseline comparison and recovery. Full history capture scales with retained
history; this API adds no ledger scan to allocation or managed-context checks.

The existing graph projection and rendering helpers can use this value to compute
`spec-artifact-graph.json` before sealing the complete source tree. Preview does
not certify rendered Markdown, captured graph source rows, future namespace
selection, semantic evidence, publication freshness or runtime metadata. A
captured-source graph builder, source/semantic authorization, complete staged
producer scope, coordinated completion/recovery and bounded repair still require
integration. This API activates no controller, runtime or provider path.

### Optional complete proposed-history binding

`PublicationIntentRequest.proposed_history_sha256` is an optional exact lowercase
SHA-256 string, appended after `sources`; existing positional arguments retain
their meaning. Supply the `sha256` from the proposed complete history preview to
bind that exact materialized result to the journal. It accepts no snapshot object,
numeric conversion, or fallback digest. Namespace and spec are already included
in the snapshot hash.

Without the claim, request bytes remain exactly version `"1"` (no sources) or
`"2"` (sources). A history-bound request uses version `"3"`, the original root
fields, mandatory `proposed_history_sha256`, and `sources` only when supplied.
These are two closed shapes: absent/null history, null sources, duplicate or
extra keys, invalid hashes and damaged frozen values reject. Versions 1/2 reject
the history field. This changes the stored payload version only; no database
migration or schema change is needed. Older binaries reject unsupported version 3
when interpreting it, so matching code remains a rollout requirement. Decoding
alone grants no execution or semantic authority.

For a new preparation, the journal plans the detached ordered operations and
overlays the shared planned rows on actual fully audited retained history inside
its existing write transaction. It checks equality before inserting any parent,
child claims or source plan. An intervening legitimate same-spec entity revision,
reference or issue occurrence invalidates a stale hash even if the child proposal
still validates and the source head is unchanged. Unused reservations and valid
other-spec changes do not alter this spec's materialized digest. Existing global
child ownership and pending guards still apply, including empty publications.
An exact prior preparation retry returns the original preparation before a fresh
history comparison; changing only the claim under the same parent ID conflicts.

Application first validates the retained prepared parent, plan and child claims,
then checks the exact overlay on current complete history before any child writer.
Public preview continues to reject pending publications; only the validated
prepared owner reuses the small private pure overlay. After existing child writers,
source acceptance and the parent applied-state/receipt update, the journal captures
actual complete history again inside the same uncommitted transaction. A mismatch
or ordinary failure rolls back child rows, source heads and parent application
state together. No additional transaction, savepoint, database copy, filesystem
write or callback is used by this check.

A history-bound application receipt uses version `"3"`, retains complete
`publication` and `operations`, adds `identity_history_sha256` equal to the request
claim, and includes the existing exact `sources` receipt when present. Preparation
and release formats are unchanged; their request/application hashes transitively
bind the history claim. Retained receipt reconstruction and source envelope checks
validate that association without recapturing today's history. Reads, exact retries,
reopen, full audit, backup and restore retain the original claim and receipt after
later history and source-head advances. Rehashing only a request or receipt cannot
hide disagreements in retained associations; a coherent malicious rewrite of all
authority rows is outside this integrity guarantee.

The complete-history work is intentionally expensive: each new bound preparation
captures once, and each still-prepared bound application captures before and after
effects. Each capture runs the existing full-authority audit, potentially scanning
history from every spec, then captures the selected spec. Prepared reads remain
retained-intent observations, not complete-history freshness checks. No capture is
added to the journal loader, receipt reconstruction, common child/allocator guard,
or indexed source/managed-context reads. There is no recursive capture or
millions-of-writes throughput claim.

This establishes materialized-history equality only. It does not prove that graph
bytes were rendered from that history, authenticate complete physical source
selection, approve semantics or historical adoption, or select a runtime namespace.
The graph rendering test demonstrates byte equality and old evidence revision
bindings; it does not authenticate graph/source provenance. Captured-source graph
construction, producer proposals/reservations, managed runtime selection, semantic
authorization, coordinated completion/recovery, lifecycle-aware memory and bounded
repair remain separate work. No live caller supplies the new field; all producer,
runtime and live integrations remain off.

### Canonical materialized identity history observation

`IdentityStore.identity_history(spec_id=...)` returns a frozen
`IdentityHistorySnapshot(payload, sha256)`. It validates the exact nonblank,
NUL-free UTF-8 spec ID before opening one query-only transaction, revalidates it
inside the connection-owned capture, validates the current schema and namespace
metadata on that same connection, and runs the existing full authority audit with
lifecycle, binding, and publication state enabled. It then selects only the named
spec's retained materialized rows. Corruption anywhere in the authority, including
another spec, can therefore fail the observation. This is deliberately a
full-authority audit observation, not a cheap per-ID read: its audit can scan all
retained history even though selected-spec materialized rows use their existing
indexed predicates. It makes no million-revision or per-spec-only complexity
promise and does not change allocation costs or run on allocation paths.

The payload is canonical ASCII JSON: object keys are sorted, separators are
compact, and non-ASCII characters are escaped. `sha256` is the lowercase SHA-256
of those exact ASCII bytes. The root contains exactly string `version="1"`,
`workspace_uuid`, `epoch_uuid`, `spec_id`, and the arrays `entities`, `revisions`,
`lineage`, `reference_claims`, and `issue_occurrences`. All IDs, ordinals,
revisions, entry indexes, operation IDs, statuses, reasons, content, provenance,
hashes, and fingerprints remain their exact stored TEXT or NULL values. JSON
numbers, booleans, display renumbering, numeric coercion, current-reference flags,
and inferred content are not introduced. An empty or not-yet-materialized spec,
including a reservation-only spec, returns the actual namespace and spec with five
empty arrays; no spec record is invented.

The arrays contain:

- `entities`: `spec_id`, `element_id`, `kind`, `subject`, `ordinal`, authenticated
  head `status`, and head `revision` for every materialized entity, including
  imported/unassessed, active, retired, and superseded rows. Unconsumed
  reservations are absent; exact content remains in `revisions`.
- `revisions`: every retained `spec_id`, `element_id`, `revision`, `subject`,
  `content`, `content_sha256`, `status`, `reason`, and original `operation_id`.
  Older and terminal bodies and their original associations are not replaced with
  current-head values.
- `lineage`: every retained `spec_id`, `predecessor_id`, `predecessor_revision`,
  `successor_id`, `successor_revision`, `kind`, `reason`, and `operation_id`.
- `reference_claims`: every retained `operation_id`, `entry_index`, `spec_id`,
  `source_path`, `source_sha256`, `source_anchor`, `target_id`, nullable
  `target_revision`, `relation`, and `payload_sha256`. Unassessed and older
  assessed bindings remain historical facts.
- `issue_occurrences`: every retained `operation_id`, `entry_index`, `spec_id`,
  `issue_id`, `issue_revision`, `report_id`, `report_sha256`, `display_id`,
  `title`, `body`, `issue_fingerprint`, and `payload_sha256`. Later issue changes
  do not rewrite original occurrence content or fingerprints.

Entities sort by kind, numeric-before-opaque ordinal, then ordinal length/text and
exact label. Revisions follow that entity order and revision length/text. Lineage
sorts by predecessor entity order, successor entity order, kind, and opaque
operation ID. Both binding arrays sort by opaque operation ID and numeric
entry-index length/text, preserving original per-operation receipt order. These
orders support arbitrarily wide canonical decimals without fixed-width casts or a
process-wide Python digit-limit change; they do not reinterpret opaque suffixes.

The payload intentionally omits counters, unused reservations, general operation
and receipt envelopes, publication intents and claims, prepared/released state,
and completion data. Consequently unrelated-spec writes, selected-spec unused
reservations, and publication state changes alone do not change it, while selected
materialized lifecycle or binding changes do. The full backup remains the complete
allocation and restore export; this observation must not be presented as a backup.
Reading never releases a prepared or applied publication guard, certifies external
completion, or writes, commits, rolls back, starts a nested transaction, or changes
a PRAGMA in the connection-owned helper. A previously returned snapshot is a
detached pair of immutable strings and does not gain post-transaction freshness.

The snapshot constructor is only a value container. Provenance belongs to the
validated capture that returned it; consumers must bind the value to their own
source and intent context and verify the digest. The digest detects accidental
byte differences but is not a signature or cryptographic tamper-resistance claim,
and retained reference/occurrence records are not thereby semantically assessed.
The shared connection-only namespace helper reads valid metadata from its caller's
active transaction. Without the public store caller's marker association it cannot
detect a coherently substituted valid namespace or certify which filesystem marker
the caller intended. There is no externally supplied history decoder, authority
importer, graph/memory/controller wiring, publication activation, or recovery
bundle in this API.

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

### Exact proposed reference source matching

`harness.element_identity_reference_sources.validate_reference_claim_sources(
artifacts, claims)` is a pure, inactive source-side preflight for proposed
`ReferenceClaim` values. It snapshots and strictly revalidates the supplied
candidate artifacts and claims, then compares each claim only with its named
artifact's supplied `after_text`. A missing postimage is distinct from a present
empty file. The claim's lowercase digest must equal the SHA-256 of the exact UTF-8
postimage bytes; neither `before_text` nor a current workspace file is a fallback.
The helper performs no filesystem, database, provider, clock or network access.

For a claimed source with a supported identity role, the existing typed artifact
parser runs once. Glossary and evidence-inventory sources retain their established
empty-fact behavior. A claim matches only an exact
`(span:<start>:<end>, target_id, relation)` triple emitted by that parser. Spans
are parser code-point offsets and retain exact spelling; padded, negative,
non-span or otherwise fabricated anchors are not normalized. Declaration labels,
masked code/comments and unsupported qualified or partial tokens are not source
facts. Supported literal IDs inside inline code retain their exact inner spans.
Range references remain unsupported and are never reduced to their first
endpoint. Unclaimed artifacts are structurally validated but are not parsed or
given semantic diagnostics. Existing historical claims and their anchor schemes
are neither loaded nor rewritten.

An empty diagnostic result establishes only that these proposed claims agree with
the supplied postimage syntax and bytes. It does not establish that the selected
sources are complete, that an `evidence` relation proves anything, or that prose
semantically assesses a target. Different claimed target revisions, including
`None`, are intentionally source-compatible because source matching cannot decide
revision meaning. The complementary target-side
`store.validate_projected_bindings(...)` must still validate target existence,
revision and lifecycle state, and an actual read-only semantic reviewer must
validate meaning. A future completion owner must also authenticate complete
physical before/postimage capture, preserve the accepted baseline through
publication and recovery, revalidate currentness, and combine all checks before
granting publication, graph, memory or completion authority.

### Projected binding storage preflight

`store.validate_projected_bindings(spec_id=..., changes=..., claims=...,
occurrences=...)` validates proposed lifecycle and binding requests together in
one query-only SQLite snapshot. All batches are copied and revalidated before the
store opens its read transaction. Empty batches mean that no operation of that
kind is proposed. A successful call returns `None`; it creates no operation ID,
reservation, entity, revision, binding record, assessment, or receipt.

When lifecycle changes are present, the preflight uses the existing lifecycle
planner on the same connection. Binding targets resolve through its validated
projected heads and exact projected revisions, with authenticated retained heads
and revisions as fallback. Thus references may remain explicitly unassessed,
name an earlier active revision, or name an existing or projected terminal
revision. Issue occurrences retain the stricter storage rule that their exact
revision must be active and their title/body must exactly match its immutable
subject/content. An older active issue revision remains valid even when the
projected head retires or supersedes it. Imported identities accept unassessed
references; an assessed target exists only when the same proposed batch contains
a valid explicit adoption.

The connection-owned
`element_identity_binding_preview.validate_projected(...)` helper requires an
already-active caller transaction. It performs reads only, does not change
connection pragmas, and does not begin, commit, roll back, or open another store
transaction. Projected and retained targets pass through the same private binding
target policy, so namespace high-water, label/kind/ordinal, subject, revision and
issue-content checks keep the historical record/read semantics.

This storage preflight is not semantic authorization. It does not authenticate
source bytes or anchors, enforce candidate current-obligation rules, reserve a
baseline, approve adoption for a managed producer, create a publication intent,
or authorize graph completion, activation, or publication. Existing candidate,
repair, Phase A completion and future publication transactions remain the owners
of those decisions and must revalidate their writes against current authority.

Source hashes, anchors, and report provenance are declarations, not proof that
the caller holds or reviewed a file. The APIs never resolve anchors against live
files or infer replacement anchors after edits. A future publication transaction
must authenticate staged bytes and reviewer provenance and enforce allowed scope
and semantic correctness. These inactive records are historical foundations;
recording a hash or matching a current revision does not activate publication or
establish a completion gate.

## Explicit schema upgrade

`IdentityStore.upgrade(workspace)` recognizes only exact reviewed schemas 1
(allocation), 2 (lifecycle), 3 (bindings), 4 (publication journal), 5 (source
contexts), and 6 (managed genesis), with matching metadata. Versions 1–5 remain
frozen, including independent SQL fixtures and literal schema-4/5 DDL tests.
Ordinary `open` on schema 1, 2, 3, 4, or 5 reports that explicit upgrade is required and
does not mutate storage.
Upgrade audits authority, integrity, foreign keys, retained numeric claims,
reservation history and legacy import/reservation overlap inside one
`BEGIN IMMEDIATE` transaction. Schema 1 first gains lifecycle tables and
imported/null heads. Versions 1/2 gain binding tables/indexes; versions 1/2/3
gain the two publication tables and their two indexes. Versions 1–4 gain only the
source tables/indexes; versions 1–5 also gain the empty managed table and index.
The metadata update adds no fabricated bindings, publication intents, child
claims, enrollment records, or completion. Audit
dispatch validates lifecycle for versions 2+, bindings for 3+, and publication
history for 4+, source state for 5+, and managed state for 6 before migration.
Frozen schema-5 audits disable managed-table access and reject managed operations.
Frozen schema-4 journal
audits explicitly disable source-table access and reject version-2 source claims.
Internal namespace validation recognizes frozen schema metadata for these audits;
ordinary public open and transaction boundaries still require the current schema. Exact
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
exists. It fully audits the authority before claiming the destination, uses SQLite
online backup from that same read transaction, writes the bound
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
A recognized schema 1, 2, 3, 4, or 5 backup is validated before claiming destination
state, then upgraded transactionally only in the fresh restored database. The
backup itself is unchanged. Unknown schema versions fail before destination
creation. Current backups retain lifecycle history, immutable claims, original
receipts, report provenance and issue fingerprints. Schema-4 backups also retain
every prepared/applied/released publication and all permanent child claims. Schema-5
backups also retain and audit complete source contexts, source plans, acceptance
receipts and independent head pointers. Schema-6 backups also retain and audit
immutable managed genesis associations. Restore
does not promote files, authenticate completion, or clear a pending guard.

A backup is a point-in-time snapshot. Restoring an old snapshot cannot recover
reservations committed after it. Quiesce the original authority and ensure the
chosen backup includes every externally used reservation before adopting a
restored copy as its successor. Reopening or rewinding a document does not rewind
the live ledger. Never regenerate a missing established ledger from current
document maxima. Independently advancing restored copies must not be merged or
treated as one allocation authority; they share identity/epoch and can issue
overlapping future ordinals.

## Opt-in retained-history graph projection

`echelon.spec_graph_identity.project_identity_history(graph, snapshot)` is a pure
helper accepting exact `SpecArtifactGraph` and `IdentityHistorySnapshot` values.
It returns a detached graph; it does not capture the store, read source files,
query memory, write a graph, or activate any producer. Callers must independently
authenticate the intended workspace/epoch authority and source graph. Canonical
JSON, a self-consistent history hash, a matching label, and a ledger source path
do not authenticate those associations or certify current source content.

The helper checks the canonical ASCII snapshot hash, strict version-1 string
fields and closed row shapes, namespace UUIDs, exact spec binding, entity and
revision targets, head consistency, content/binding digests, issue fingerprints,
and original lineage associations. It is a derived view, not a replacement for
the capture API's full store audit or canonical-source and semantic review.
Malformed inputs fail with a bounded `SpecGraphError` without modifying inputs.
IDs, ordinals and revisions remain strings, including wide decimal values and
legacy padding/composites; unrelated numeric graph metadata remains numeric.

The retained Spec gains exactly:

```json
{"identity_projection":{"version":"1","workspace_uuid":"<uuid>","epoch_uuid":"<uuid>","history_sha256":"<snapshot.sha256>"}}
```

One required `GraphInput` has role `identity_history`, hash
`sha256:<snapshot.sha256>` and path
`identity://<workspace_uuid>/<epoch_uuid>/<URL-quoted-spec-id>`, with the spec ID
quoted using `quote(spec_id, safe="")`. This is a virtual history observation,
not a digest of mutable SQLite bytes. Global graph schema and node-projection
versions remain unchanged; this component uses its own string version `"1"`.
Rebuild from a fresh source graph and complete snapshot: an already projected
graph, generated history keys/relationships, or conflicting virtual input path
is rejected, rather than serving as a retry input.

Existing `_scope_node_id` keys remain `task:<spec>:<T-label>` for tasks and
`req:<spec>:<label>` otherwise. FR/NFR/AC map to Requirement, T to Task, U to
Unknown, A to Assumption and ISS to Issue. All retained entities are represented,
including terminal and imported entities absent from current Markdown. Each has
an `identity` property with exactly `workspace_uuid`, `epoch_uuid`, `kind`,
`ordinal`, `subject`, `status`, `revision`, and `rendered`. `rendered` means only
that the entity node existed in the supplied graph. Original task-progress
status and source properties remain intact. Added entities contain only their
usual human label property (`requirement_id`, `task_id`, or `element_id`) and
`identity`; source content/lines are not invented.

Generated keys concatenate the following prefix with `_canonical_digest` of
`[workspace_uuid, epoch_uuid, spec_id, ...suffix]`, without its `sha256:` prefix:

| Node type | Key prefix | Suffix values |
| --- | --- | --- |
| ElementRevision | `identity-revision:` | `element_id`, `revision` |
| ReferenceClaim | `identity-reference:` | `operation_id`, `entry_index` |
| IssueOccurrence | `identity-occurrence:` | `operation_id`, `entry_index` |
| IdentitySource | `identity-source:` | `source_path`, `source_sha256` |
| IdentityReport | `identity-report:` | `report_id`, `report_sha256` |

These keys exclude the changing whole-history hash and head status. Every
revision/claim/occurrence retains its exact original row properties. Source and
report nodes carry exactly `spec_id` plus their two suffix fields; identical
provenance shares a node, but distinct occurrences are never collapsed.

Relationships are Spec → `HAS_IDENTITY` → entity; entity → `HAS_REVISION` → each
revision and `CURRENT_REVISION` → non-null head; predecessor active revision →
`SUCCESSOR_REVISION` → successor active revision 1, with the complete original
lineage row as edge properties. Terminal revisions remain separate history.
Claims point through `REFERENCES_IDENTITY`, optional `ASSESSES_REVISION`, and
`HAS_SOURCE`. Their additional `target_revision_matches_current` boolean is true
only for an explicit revision equal to an active head; it makes no source
freshness or completion claim. Occurrences point through `OCCURRENCE_OF`,
`OBSERVES_REVISION`, and `HAS_REPORT`, preserving exact historical active issue
content, display ID and fingerprint. Other generated edge properties are empty.

Legacy `VERIFIED_BY` and `STORED_AS` edges touching managed entities retain
endpoints and all properties, including any `complete` field, but gain
`identity_assessment: "unassessed"`. Conflicting assessment metadata is rejected.
Historical evidence is never relabeled proof of new content.

## Read-only identity graph selection and impact

The existing `resolve_node_id(model, selector)` keeps exact complete node-key
lookup first. For non-exact shorthand it next checks durable entity labels by
their exact string property: Requirement/`requirement_id`, Task/`task_id`, and
Unknown, Assumption or Issue/`element_id`. Matching is case-insensitive but does
not truncate, remove numeric zeroes, coerce numbers, or infer labels from
revision, claim or occurrence fields. One durable entity wins over repeated
historical mentions. Two or more matching entities remain a bounded, sorted
ambiguity even across specs or namespaces; terminal/imported entities receive
no lower priority. Only when no entity matches does the prior suffix and
arbitrary `*_id` fallback apply unchanged. Thus complete history keys remain
selectable, while a repeated bare history display ID remains ambiguous rather
than selecting a current, first or active record implicitly. A successful
shorthand lookup says nothing about graph-source freshness or audit status.

Default `impact` traversal extends the existing typed table with this exact
conservative policy. `Entity` below independently means Requirement, Task,
Unknown, Assumption and Issue:

| Stored edge | Default directions |
| --- | --- |
| Spec --`HAS_IDENTITY`--> Entity | Spec to Entity only |
| Entity --`HAS_REVISION`--> ElementRevision | both |
| Entity --`CURRENT_REVISION`--> ElementRevision | both |
| ElementRevision --`SUCCESSOR_REVISION`--> ElementRevision | predecessor to successor only |
| ReferenceClaim --`REFERENCES_IDENTITY`--> Entity | both |
| ReferenceClaim --`ASSESSES_REVISION`--> ElementRevision | both |
| ReferenceClaim --`HAS_SOURCE`--> IdentitySource | both |
| IssueOccurrence --`OCCURRENCE_OF`--> Issue | both |
| IssueOccurrence --`OBSERVES_REVISION`--> ElementRevision | both |
| IssueOccurrence --`HAS_REPORT`--> IdentityReport | both |

This traversal exposes a potentially affected entity/history/evidence
neighborhood. It preserves exact lifecycle, revision, current-match, assessment,
fingerprint and provenance properties. It does not suppress terminal entities,
retarget historical edges to a current revision, promote `unassessed` evidence,
approve evidence, or invalidate controller stages. Controller invalidation must
later compare the inputs actually bound to a stage. Omitting reverse Spec
membership prevents one entity from reaching unrelated siblings through their
common Spec; omitting reverse revision lineage prevents successors from
automatically reopening predecessors. Existing `all_relations`, `neighbors`,
`shortest_path`, deterministic breadth-first bounds, cycle handling and
truncation retain their explicit semantics.

Natural and explicit graph queries recognize Unknown, Assumption, Issue,
ElementRevision, ReferenceClaim, IssueOccurrence, IdentitySource and
IdentityReport by their lower-case singular/plural type names. Existing aliases
remain unchanged; in particular `source` and `sources` still mean SourceRoot,
not IdentitySource.

## Deterministic memory occurrence identity compatibility

The inactive canonical memory planner and exact-write protocol accept every
nonempty requirement ID string without a storage-width maximum. Published labels
remain byte-for-byte strings, including `FR-001`, `FR-MP-006`, historical
composite labels, six-digit ordinals, and ordinals wider than six digits. Six is
only the minimum display width for newly allocated numeric labels; it is neither
a storage width nor a maximum value. Memory planning does not normalize padding,
coerce identifiers, allocate IDs, or interpret lifecycle state.

The deterministic drawer ID continues to hash the exact canonical source hash,
complete requirement label, and requirement-content hash using the existing
schema-1 identity JSON. It therefore identifies an immutable source/content
occurrence. It is not the durable registry entity, does not choose a current
revision, and does not certify lifecycle authority or current verification.
Accepting wider labels activates no memory writer, graph publisher, provider,
producer, or controller path; live integration still requires the separate
source, semantic, lifecycle, namespace, retrieval, and publication adapters.

**Live integration remains blocked:** the read-only supplied-model selector and
traversal adapter does not load or publish managed graph history, authenticate a
canonical source audit, or activate a producer. No live producer may publish/use
this output until separate adapters authenticate managed namespace/current
history and source inputs and implement lifecycle-aware obligations/current
verification. The projection tag is not the immutable managed-spec/run feature
snapshot. Source/semantic/recovery/completion integration, memory
current-revision semantics, producer activation and bounded repair remain
separate work; this helper makes no live audit or end-to-end publication claim.

## Inactive managed metadata in squad state

`SquadStateStore.initialize(..., managed_identity=record)` accepts the exact
ten-string genesis record returned by managed registration: `version` (`"1"`),
`workspace_uuid`, `epoch_uuid`, `spec_id`, `operation_id`, `run_id`, `context_id`,
`spec_path`, `source_registration_operation_id`, and `source_manifest_sha256`.
The pure `validate_managed_identity_record` reuses the managed-request codec and
lifecycle text validation and returns a detached flat dictionary. This checks
structure only: a valid record remains a caller claim until a trusted runtime
owner compares it with the durable registry.

The optional initialization argument does not enroll a spec. It supplies initial
`spec_id` and must match the explicitly requested `run_id`. An ordinary legacy
initialization keeps its existing shape and has no `managed_identity` key. A
present null, false, empty, partial, or malformed field is invalid. Only explicit
initialization may introduce metadata into an empty or legacy state store; no
live initialization caller has been changed to supply it.

Once present, the exact genesis record and its run/spec association are immutable
through the state owner. Same-run reinitialization preserves the existing record
and canonical `spec_id`, including when an unchanged controller initializer
omits the new argument. Selection and persistence share the existing exclusive
state lock. Supplied identical metadata is allowed; replacement, removal, a
different run, or invalid retained metadata rejects before state, backup, or
replacement-temp writes. An explicit managed initialization also rejects malformed
prior JSON. Unknown malformed legacy files retain the existing legacy policy;
the owner does not infer authority from substrings in corrupt content.

`MANAGED_IDENTITY_KEYS` reserves this field separately from Phase A routing
identity. Provider echoes, controller enrichment, queued effects, control intents,
ordinary removals, and trusted routing effects cannot own it. Existing prepared
result attestations and the sole `_save_unlocked` writer enforce the boundary,
including exact saves, recovery snapshots, and manual controller state updates.
State revision CAS, human-input write authority, and pre/post-replacement
durability semantics remain in effect. No registry, namespace, or source lookup
runs under the state lock.

The record describes the first registered run and original source root. Mutable
state `spec_dir` need not equal genesis `spec_path`: preservation neither proves
physical source isolation nor authorizes export or relocation. A subsequent run
requires a new explicit bound-state protocol, not relabeling this genesis record.

**Activation remains blocked.** Complete external state deletion, removal of the
field outside this owner, wholly corrupted state that cannot be identified as
managed, a missing registry, and old authority schemas require a future durable
registry gate at trusted startup/dispatch/completion owners. This layer cannot
detect those conditions or authenticate supplied receipt provenance or current
source scope. Candidate isolation, producer reservations, exact
source/identity/graph completion, semantic judgment, and bounded repair remain
separate prerequisites.

## Captured legacy graph-input parser boundaries

Three inactive compatibility helpers parse already-captured text without opening
paths: `extract_canonical_requirements_from_texts`,
`parse_deferred_scope_ledger`, and `parse_verified_ledger`. They return fresh
existing requirement, deferred-scope, and verified-ledger records. The existing
path readers retain their prior absence, decoding, I/O, ordering, default and
error behavior and delegate only their parsing bodies after reading.

These helpers accept exact strings; only the four requirement Markdown images may
be `None`, meaning that source was absent from the capture. An empty supplied
string remains a present empty observation. The requirement helper preserves the
legacy inventory regex, source precedence, line numbering, task fallback and
numeric ordering, including historical family, suffix, composite, range-endpoint
and arbitrarily wide numeric labels. The ledger helpers preserve their existing
permissive schema and row interpretation, including attached historical evidence
references and fresh ordinary nested dictionaries.

Parsed values are observations, not canonical managed definitions, accepted
source authority, evidence authentication or proof of current fulfillment. The
helpers do not validate the managed identity grammar, decide whether a reference
defines a requirement, assess evidence, rebind historical evidence to a current
revision, or authorize graph construction or publication. A future managed graph
owner must authenticate the complete captured dependency set and apply the
existing typed candidate, source and identity checks before building or publishing
a graph. No graph caller, producer, controller, provider, lifecycle or completion
path is activated by these parsing boundaries.

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
