# Durable element identities and bounded discovery repair

## Status and scope

The user approved fixing the browser-game smoke-test findings and requested
at least six numeric digits, with capacity for millions of identifiers over
years. This document makes the migration and enforcement contract explicit
before implementation. The user approved this design. Implementation progress
is tracked below; approval is not a claim that all enforcement is implemented.

### Implementation checkpoints

- Numeric compatibility: implemented and independently reviewed in
  `6230eb97` and `841743fc`. Focused compatibility suites passed 239 tests;
  internalization integration passed 34 checks; review fixes passed 59 focused
  tests. Existing labels remain unchanged; new numeric labels use six digits
  minimum and readers accept wider values.
- Wider regression check: 9,139 passed and one earlier-branch prompt-contract
  failure. The four missing delivery rule headings were corrected in
  `8a6cc1b9`, with 89 covering tests passing and a clean independent review.
  This does not relabel the original full-suite result as an all-pass run.
- Durable allocation authority: implemented and independently reviewed in
  `c67c1e53` and `5fab792b`, not active. Final scoped run: 144 passing tests,
  including real-process contention/recovery and one million imported IDs.
  The final million-record run measured 9.751 seconds to import and
  130,846,720 database bytes with indexed allocation/integrity checks.
  Detectable counter/history contradictions reject without counter repair.
- Lifecycle foundation: implemented and independently reviewed in `07573c2b`
  and `779ed4ae`, not active. The lifecycle/allocation/formatter/process suite
  passed 184 tests; the audit review fix passed 141 covering tests. One million
  imported/unbound entities took 13.974 seconds and 168,841,216 database bytes
  with the lifecycle schema; these are not one million assessed revisions.
- Typed artifact adapters: implemented in `3e066a66`, corrected in `cb2eece6`
  and `14bc922d`, and independently reviewed. Final adapter/compatibility run:
  101 tests passing. Sanitized smoke fixtures preserve the changed question
  captions and retained references. Parsing does not yet enforce publication.
- Revision-bound reference claims and issue-occurrence storage: implemented in
  `7e5596a3` and independently reviewed with no findings, not active. Combined
  storage/lifecycle/identity/process tests: 291 passed, with only the previously
  measured million-record import test deselected because routine allocation
  and import paths were unchanged. The binding-specific suite passed 92 tests.
  Recorded provenance is not semantic verification or publication authority.
- Read-only lifecycle preflight: implemented in `f975bd53` and independently
  reviewed with no findings. Focused preview tests: 20 passed; combined
  storage/lifecycle/process tests: 258 passed, with one unchanged capacity case
  deselected. Preview shares application rules without mutating history or
  reserving a publication baseline.
- Offline discovery candidate preflight: implemented in `547ecd03`, corrected
  in `d5d73a1a`, and independently reviewed. Initial combined tests: 392 passed;
  caption/subject correction: 182 covering tests passed. Sanitized smoke
  reassignment/removal rejects without registry effects. Captured inputs are
  not yet authenticated by publication, and structural checks are not semantic
  approval.
- General requirement/task definition preflight: implemented in `55241162`
  and independently reviewed with no findings. Focused tests: 37 passed;
  combined candidate/lifecycle/adapter/task/Lexicon tests: 358 passed. Six-family
  structural checks preserve explicit nested ancestor/descendant scope and block
  non-active dependencies. A subsequent integration check found absent native
  Lexicon images were parsed as empty documents; corrected in `2db1ba96`, with
  237 covering tests passing and clean scoped review. Present empty documents
  remain invalid.
- Immutable ancillary artifact validation: implemented in `581e8cc4` and
  independently reviewed with no findings. Focused tests: 36 passed; complete
  requested compatibility set: 224 passed. Pure Lexicon/source/glossary and
  inventory APIs preserve existing rules while validating exact supplied text;
  legacy Path behavior remains distinct.
- Supplemental bundle integration: implemented in `5aa44f08`, corrected in
  `ac9f6e73`, and independently reviewed. Required compatibility suite: 402
  passed; absent/empty supplemental scope correction: 163 covering tests
  passed. Derived Lexicon keeps explicit source associations without duplicate
  identity authority; glossary and inventory retain exact image scope. An extra
  broad run was interrupted without a failure summary and is not accepted as
  passing evidence. Five possible cached delivery-test failures passed in a
  focused root check; final full integration remains required.
- Issue occurrence candidate authorization: implemented in `2d043bba`, corrected
  in `43b0ad36`, and independently reviewed. Required compatibility suite: 544
  passed; candidate history-adoption bypass correction: 269 covering tests
  passed. Exact report provenance, current/projected revisions, retained history
  and original fingerprint guards are preserved without writes. Seven-family
  structural coverage remains limited to supported typed grammar: unrecognized
  legacy issue headings and complete report/gate authentication still require
  explicit managed integration. No live enforcement is activated.
- Explicit authority administration: implemented in `eb00b2db`, corrected in
  `44ec4322`, and independently reviewed. Required compatibility suite: 311
  passed; malformed JSON decoder error correction: 36 admin tests passed.
  Query-only integrity reports and explicit initialize/upgrade/backup/restore/
  subject-only import operations do not activate managed identities or assess
  imported history.
- Historical identity inventory: implemented in `bd5f1be6`, corrected in
  `bcaf569e`, and independently reviewed. Required compatibility suite: 736
  passed; exact malformed-declaration spans and issue-range mapping correction:
  704 covering tests passed. Explicit captured snapshots retain hashes, source
  spans and unassessed references while reporting competing definitions,
  disappearances and issue correspondence needs. Unsupported explicit headings
  and bullets now reject rather than silently disappear. This report is not
  authenticated history reconciliation. A reproduced bare-reference limitation
  (`FR-001.other` / `FR-001-extra` read as `FR-001`) required the subsequent
  explicit lexical/locator checkpoint below.
- Lifecycle transaction composition: implemented in `ca663b9e` and independently
  reviewed with no findings. Exact eight-module compatibility suite: 426 passed.
  Lifecycle and evidence/issue writers now share one caller-owned transaction;
  rollback, visibility and original retry receipts are tested against real
  SQLite. This does not authenticate historical sources or canonical publication.
- Whole reference-token classification: implemented in `d86093ca`, corrected in
  `9febb653`, and independently reviewed. Final seven-module compatibility suite:
  1,532 passed. Unsupported whole labels, URI/path qualifications and malformed
  intervals now retain diagnostic spans instead of leaking local prefixes.
  Existing artifact tests pass unchanged, including local investigation filename
  anchors. The bounded lexical contract separates literal dots from sentence
  punctuation and treats ambiguous URI-style prefixes conservatively. Qualified
  resolution, interval application and authenticated historical reconciliation
  remain explicit unsupported integrations, not guessed successes.
- Sealed publication inspection: implemented in `d610e2bf`, corrected in
  `04f2d655` and `38dd7664`, and independently reviewed. Initial four-module
  suite: 409 passed; final lock-association correction: 171 covering tests
  passed. Immutable current/staged images share the existing lock and prefix
  rules, including interrupted publication. Real root-swap and transient-swap
  regressions bind the acquired lock to the retained root descriptor. This
  does not supply original bytes after promotion, complete unchanged dependency
  capture, semantic authority or a durable identity intent.
- Strict request recovery codec: implemented in `5a85aedf` and independently
  reviewed with no findings. Exact four-module compatibility suite: 259 passed.
  Lifecycle/reference/issue payloads reconstruct immutable requests using the
  existing validators and unchanged digest bytes; malformed JSON, nested shapes
  and numeric coercions reject. Reopened-store retries preserve original receipts
  after later history. Decoding is not semantic, adoption or publication authority
  and does not persist or activate a durable intent.
- Pinned source-tree capture: implemented in `83b5a04a` and independently
  reviewed with no findings. Exact three-module compatibility suite: 255 passed.
  Complete selected-directory membership, directory modes and exact regular-file
  bytes share the reviewed root/lock/pin owner; missing and empty trees remain
  distinct. This is an observation of one selected tree during a bounded context,
  not post-exit freshness, complete external dependency coverage or publication
  authority. No provider authoring isolation or live workflow is activated.
- Projected binding preflight: implemented in `e368efc1` and independently
  reviewed with no findings. Exact five-module compatibility suite: 292 passed.
  Proposed lifecycle rows and retained historical revisions share the existing
  binding target policy in one query-only transaction. Unassessed references
  remain unassessed; historical active issue occurrences retain their original
  meaning after a projected retirement. This does not reserve a baseline,
  authenticate evidence or authorize publication.
- Joint publication/source capture: implemented in `ef44b0ec` and independently
  reviewed with no findings. Exact four-module compatibility suite: 411 passed.
  Sealed operations, complete selected trees and external selected files now
  share one descriptor-bound lock and joint before-yield/normal-exit checks.
  Stable hard-linked reads preserve existing behavior, with link/content drift
  rejected. Source selection still requires controller-owned complete dependency
  coverage, and current bytes are not invented historical preimages.
- Durable identity publication journal: implemented in `c7df1107` and independently
  reviewed with no findings. Exact eleven-module suite: 581 passed, including
  real-process contention/restart and one million imported IDs. Import took
  14.154 seconds, the next allocation 0.014163 seconds, and the database used
  168,890,368 bytes; these are imported identities, not assessed revisions.
  Prepared and applied intents retain a spec-wide write guard and permanent
  child operation claims through restart/restore. Original receipts survive
  later history. Opaque recovery/completion payloads are retained caller claims,
  not semantic, source, graph or filesystem authority; no workflow is activated.
- Coherent materialized-history snapshot: implemented in `3f62ac6c`, with
  complete-row regression assertions strengthened in `76f6abfc`, and independently
  reviewed. Exact seven-module suite: 405 passed; test-only correction: 32 passed.
  One full-audit transaction yields stable per-spec history bytes including
  unassessed/terminal entities, every revision/lineage row and original reference/
  occurrence bindings. Unused reservations and publication release do not alter
  this history digest. It is not a restore backup, cheap per-ID lookup, source
  authentication or graph/semantic completion; live consumers remain unwired.
- Pure retained-history graph projection: implemented in `ec3cc4cf` and
  independently reviewed with no findings. Exact six-module suite: 198 passed.
  Published entity keys remain stable; separate immutable revision, reference,
  occurrence and provenance nodes preserve historical bindings. Legacy complete
  verification edges remain explicitly unassessed. Canonical history validation
  and detached ownership do not authenticate the caller's source/namespace or
  activate any live graph builder, audit, publisher or memory consumer.
- Identity-aware read-only graph selectors and traversal: implemented in
  `6e947d75` and independently reviewed with no findings. Exact four-module
  suite: 116 passed. Bare labels prefer their durable entity while preserving
  cross-spec ambiguity; typed impact includes retained revisions, provenance,
  evidence and occurrences without reverse Spec fanout or successor lineage.
  Results preserve assessment metadata and do not certify current sources,
  invalidate workflow stages or activate live managed graph loading.
- Remaining memory ID-width compatibility: corrected in `f68a49ea` and
  independently reviewed with no findings. Two-module covering run: 80 passed;
  subsequent test-only self-review additions: 19 focused checks passed.
  The only production change removes a 512-character requirement-ID guard;
  existing deterministic drawer keys, exact-write/readback checks and other
  validation remain unchanged. Real parser/planner tests retain 5,000-digit
  labels independently of existing body-content secret scrubbing. This does
  not activate live memory or establish lifecycle/current-revision authority.
- Initial source-baseline recovery codec: implemented in `1dcf8875`, corrected
  in `4c292b84`, and independently reviewed. Exact four-module suite: 378 passed;
  overlap fix covering module: 36 passed. Complete selected source bytes and
  original target images survive partial promotion without reading changed files.
  Strict canonical encoding rejects structural contradictions, including
  interleaved ancestor/descendant targets. The retained snapshot remains a
  caller claim, not sealed-manifest authentication, accepted-source authority,
  semantic approval or complete publication recovery. No live wiring is enabled.
- Exact proposed source-reference binding: implemented in `c19043b1`, corrected
  in `3b535ed0`, and independently reviewed. The amended eight-module suite passed
  1,513 tests; bounded-traceback fix coverage passed 51 source-validation tests.
  Supplied postimage hashes and exact parser span/target/relation triples now
  have a pure validator complementary to target-side preflight. A prior Lexicon
  compatibility defect exposed by the original 1,510-pass/1-fail run was corrected
  narrowly: rejected declaration labels no longer also become reference facts,
  while real body references remain. No semantic approval, accepted-source
  authentication or live publication enforcement is claimed.
- Captured candidate source assembly: implemented in `57b0d2cf`, corrected in
  `f8f74234`, and independently reviewed. Five-module suite: 364 passed;
  amended module: 38 passed. Original and proposed images now join through an
  explicit physical-to-logical binding; every sealed operation needs exact
  writable scope and typed or opaque classification. Real changed-evidence
  composition accepts its after hash and rejects its retained before hash.
  Caller-input errors are bounded; snapshot validation remains separate.
  This inactive adapter does not establish accepted-source or semantic authority.
- Selected-source observation fingerprint: implemented in `dcb18f54` and
  independently reviewed. Exact four-module suite: 249 passed. The pure factory
  validates retained byte/hash/mode and complete selected membership before
  emitting a canonical metadata-only digest. Real initial/partial/final captures
  and retry are distinguished without changing the initial-source guard.
  Source ownership, accepted baseline persistence and coordinated publication
  remain required; a supplied observation hash is not acceptance authority.
- Expected final source projection: implemented in `b39a9b29`, test assertion
  strengthened in `426a7992`, and independently reviewed. Four-module suite:
  179 passed; exact mode-only regression fix: 21 covering tests passed.
  Sealed postimages now produce an expected complete selected fingerprint,
  preserving unrelated files and existing directory modes while sharing the
  publisher's actual new-directory mode. Real publication and interrupted retry
  match the retained original's expectation. This is not a fresh observation
  or guarded-promotion/accepted-source authority; those remain integration work.
- Guarded selected-source publication: implemented in `1227855d`, corrected
  in `dc4a4964` and `3a79678f`, and independently reviewed. Initial six-module
  suite: 438 passed; final three-module fix coverage: 298 passed. The opt-in
  publisher uses the existing lock and sole promotion loop, checks complete
  selected sources at publication boundaries, and retains distinct target
  ancestor bindings through the invocation. Real replacement and bounded-handle
  regressions caught and corrected both lifetime and resource-growth gaps.
  Interrupted prefixes retain recovery material; callbacks do not establish
  accepted-source, semantic, namespace or completion authority. No live caller
  has been switched to this API.
- Stored source-fingerprint validation: implemented in `40ff5fbf` and
  independently reviewed. Five-module suite: 240 passed; a subsequent test-only
  empty-tree refinement passed its focused check. The strict decoder validates
  the existing canonical metadata format and shares tree-layout rules with
  the original-byte codec. Self-consistent changed metadata remains a claim,
  not provenance, accepted-source authority or a publication receipt.
- Durable accepted source contexts: implemented in `f8911aef`, corrected in
  `7e7a177a`, and independently reviewed with no findings. Eleven-module
  checkpoint: 668 passed; final amended source/publication modules: 208 passed.
  The checkpoint imported one million IDs in 14.496 seconds using 168,914,944
  database bytes, with next allocation taking 0.016208 seconds. Source heads
  advance atomically with the existing publication journal, retain original
  receipts, and reject stale predecessors or damaged history without fallback.
  Current source reads avoid identity-history scans; full audits retain deeper
  checks. Real interrupted promotion and commit uncertainty are tested. These
  are explicit observation contexts, not managed-run/namespace authentication,
  dependency completeness, semantic approval or live completion enforcement.
- Immutable managed-spec genesis registration: implemented in `0daa82c1` and
  independently reviewed with no findings. Ten-module checkpoint: 759 passed,
  one unchanged capacity case excluded; the final fresh-only amendment passed
  124 managed tests. Enrollment binds the actual namespace, first run and
  original accepted source operation/hash. It rejects historical specs even
  when only an import operation survives, while exact retries retain genesis
  after later source/identity history. This explicit inactive API does not yet
  protect runtime metadata, bind later run transitions or enable producers.
- Managed identity state preservation: implemented in `91a4c48a`, corrected in
  `e5130edc`, and independently reviewed. Five-module plus named simulated
  controller checkpoint: 912 passed; final exception-normalization correction:
  354 covering tests passed. The existing writer preserves immutable genesis
  through same-run initialization and rejects provider/routing replacement or
  removal before changing state or backup. Real fresh/manual controller paths,
  guided/semi/banzai modes, CAS and interrupted writes are covered. This field
  still needs registry authentication and independent runtime selection; external
  deletion, subsequent runs and physical source ownership are not certified.
- Explicit managed context authentication: implemented in `a095707a`, with
  distinct-spec/run test coverage in `d5438181`, and independently reviewed.
  Five-module implementation suite: 470 passed; final test-only amendment:
  40 focused tests passed. One query-only transaction compares an independently
  selected spec/run and supplied record to durable genesis, then returns the
  associated accepted source head. It neither enrolls nor repairs authority.
  Runtime mode selection, removed-metadata detection, physical source freshness
  and publication/semantic completion remain separate required integrations.
- Reference/publication enforcement, producer integration, targeted repair,
  and new live verification: outstanding. No global installation or stopped-run
  mutation. Capacity measurements do not prove semantic identity preservation.

The work covers AC, FR, NFR, ISS, U, A, and T identities; their readers,
producers, references, evidence lineage; and the failed Phase A discovery
repair path. Other typed element families can register with the same allocator
without inventing another counter. Spec directory numbers, run IDs, telemetry
span IDs, and every unrelated numeric field are not renumbered by this work.

The stopped smoke workspace and its checkpoints remain unchanged. Do not
resume it, increase its limits, or install modified bundles into it as an
implementation step. The normal installed Echelon CLI remains untouched until
an explicit rollout checkpoint.

## Evidence and existing mechanisms

The retained run is `spec-20260912-055832-031402` in
`/Users/michalbachorik/work/echelon-game-smoke`.

- The change from checkpoint `9976af0` to `76f2b80` reassigned U-001 through
  U-004 and removed U-005 while retaining their investigation references.
- Later reviews repeatedly rejected the inconsistent identities. After five
  actual discovery executions, the next attempted dispatch exceeded the cap.
  The run exited blocked after 59m 49s without changing `sources/game`.
- `src/understanding/requirement_projection.py` restricts conventional and
  heading requirement IDs to three or four digits.
- `src/harness/review_artifacts.py::_allocate_canonical_task_ids` derives IDs
  from surviving rows and explicitly refuses allocation beyond T-9999.
- `src/echelon/spec_graph.py` keys requirement nodes as
  `req:<spec-id>:<requirement-id>`. Silent reassignment changes the meaning of
  a node without changing its key.
- `src/harness/issue_identity.py` already protects resolution authority using
  content fingerprints and retained history. Keep this protection; a stable
  entity ID does not prove that a resolution still applies to revised content.
- `src/harness/review_artifacts.py` already has locked allocation and durable
  publication recovery. Extend its allocator integration, not its ownership.
- Discovery currently follows the ordinary full-output protocol on repair.
  Its output set excludes investigation evidence even when the finding needs
  those dependent artifacts reconciled.

The earlier atomic-spec-element design remains deferred and has a broader RE
execution scope. This work does not silently activate or implement that entire
design. Existing Phase A completion transactions, candidate isolation, and
repair facilities remain the integration owners.

## Approach

Use one harness-owned identity service with a durable allocation ledger,
typed artifact adapters, and publication validation. A prose-only change is
insufficient because it cannot prevent malformed output from being accepted.
A counter-only change is insufficient because it cannot prevent an existing
ID being attached to a different subject. Replacing every existing ID with a
UUID would break compatibility unnecessarily.

Keep existing human-readable IDs and graph keys stable. Record identity
revisions, lifecycle events, and reference provenance beside them. Agents
propose content and edits; they do not allocate IDs, mutate the ledger, or
certify publication.

## Identity contract

### Namespaces and format

An identity is qualified by workspace identity, canonical spec identity, type,
and numeric ordinal. Counters are per canonical spec and type, consistent with
the existing spec-qualified graph. Bare AC or issue labels are never globally
unique cross-spec graph keys.

New labels use a minimum width of six decimal digits:

```text
AC-000001
FR-000042
NFR-999999
AC-1000000
```

Six is a minimum display width, not a storage width or maximum value. There is
no six- or seven-digit application cap, truncation, wrapping, or lexicographic
numeric ordering. Persist counters as decimal strings and use Python integer
arithmetic so storage and JSON consumers cannot silently round large values.
IDs travel through interfaces as strings.

Existing labels, including FR-001 and historical composite IDs, remain exactly
as published. Import reserves their identity and numeric ordinal where one
exists. FR-001 must not coexist with a newly allocated FR-000001 representing
another entity in the same spec. Unsupported composite legacy formats remain
opaque reserved identities; migration must not reinterpret them heuristically.

### Durable allocation

Use a workspace-owned SQLite ledger under `.echelon/identity/`, outside ordinary
spec Git rewind and provider write scope. SQLite uses the standard library and
indexed records; allocation must not rewrite a million-entry JSON file or scan
all historical Markdown for each request.

The ledger records namespaces, high-water counters, reservation requests,
entities, content revisions, lifecycle events, reference bindings, and
publication receipts. Allocate under one database transaction. A request is
bound to the spec, type, durable operation ID, count, and request digest.

- The same request returns the same IDs after retries or process restart.
- Reusing a request ID with different arguments fails closed.
- Concurrent successful requests cannot overlap.
- Failed or abandoned reservations leave gaps; numbers are never recycled.
- Rewind, retirement, deletion of a rendered row, and regeneration cannot
  decrement the counter.
- Database corruption or a missing previously established ledger blocks
  allocation; it must not silently initialize from current document maxima.

The registry has a persistent workspace identity and epoch. Export and restore
include the ledger's identity, counters, reservations, revisions, and receipts,
not just the active rows. A manifest bound to publication travels with spec
artifacts for auditing and recovery. The local database is authoritative for
allocation; graph and Markdown are consumers, not independent allocators.

One local authority supports concurrent processes and worktrees that share the
same orchestration workspace. Independently writable clones are not a shared
counter service. Imported histories with competing allocations block for
explicit reconciliation; do not merge same-looking IDs by assumption. An
independent workspace receives a distinct namespace. Distributed global
allocation is outside this change.

### Entity lifecycle

- `create`: consumes a controller-reserved ID and establishes its subject.
- `revise`: retains the ID, stores the prior revision, and binds the new
  content to a new revision. A status change is not a new entity.
- `retire`: preserves the entity and historical references; active consumers
  cannot silently treat it as a current obligation.
- `replace`, `split`, and `merge`: reserve new IDs and record explicit lineage
  to retained predecessor entities. Replacing a subject is not an in-place
  revision. Superseded evidence stays attached to its original revision.

A content hash is a revision/integrity binding, not the entity identity. A
stable ID does not authorize arbitrary subject changes: updates require the
controller's edit scope and semantic review. The harness can prove allowed
IDs, fields, references, and content boundaries; it cannot prove semantic
equivalence of arbitrary rewritten prose.

### Issues and evidence

Separate a durable issue from an occurrence in a particular review. A review
may report an existing issue or propose a new one. The controller validates
the existing identity or allocates a new one and retains review occurrences.
It does not reset ISS numbering for each replacement `issues.md`.

Existing fingerprint-based resolution guards remain. Changed evidence or
repair obligations must not inherit a closed resolution merely because the
display ID is unchanged. Legacy reports that reused ISS-001 are imported as
distinct historical occurrences using report provenance and fingerprints;
ambiguous correspondence to a durable current issue blocks reconciliation.

References bind the qualified entity and, where they assert verification,
the assessed revision. Editing a requirement invalidates current verification
unless it is re-established for that revision. Historical evidence is retained,
not relabeled as proof of the new content.

## Publication and graph safety

Typed adapters distinguish definitions from references in supported Markdown,
task rows, Lexicon, and investigation artifacts. Do not infer new definitions
from every textual mention or infer authority from historical journal quotes.

For every candidate, validate before accepting it:

1. All introduced definitions use allocated IDs of the expected type/scope.
2. Existing entities are preserved or have an authorized lifecycle event.
3. No duplicate definitions or padding aliases create competing entities.
4. References resolve to the appropriate namespace and lifecycle/revision.
5. Edits remain within the declared artifact/element set; unrelated baseline
   content and immutable identity fields remain unchanged.
6. The canonical inputs still match the captured publication baseline.

Keep failed candidates as diagnostics; do not update canonical artifacts,
graphs, or memory from rejected candidates. Publication uses a durable intent
and idempotent receipt integrated with existing completion transactions. A
crash between artifact promotion, ledger publication, and graph projection
must be recoverable without duplicate allocation or false completion. A
pending publication blocks conflicting writes until reconciled.

Existing graph keys remain valid. Add revision and lifecycle metadata and
explicit predecessor links; historical edges retain their original binding.
Any consumer unable to represent a lifecycle operation must block that
operation until its adapter is available, rather than dropping history.

## Targeted discovery repair

Distinguish creation from repair in controller inputs, not by making SCOUT
guess from previous prose or the invocation name.

The controller constructs a content-bound repair packet containing:

- authoritative findings and their occurrence identities;
- the accepted baseline and relevant definitions;
- the identity reservation and permitted lifecycle operations;
- the writable artifact/element set and read-only dependent references;
- expected validation and return-to-review destination;
- durable repair attempt and no-progress accounting.

Ordinary discovery repair preserves question identity and subject headings.
New questions require new allocated IDs. Retiring a resolved question keeps
its registry entry and evidence bindings; it is not removed and replaced by
another question under the same label.

When a repair crosses ownership boundaries, the controller dispatches the
responsible owners against one isolated candidate and validates the complete
dependency set before publication. It does not grant SCOUT unrestricted
writes to all investigation or requirement artifacts.

The prose invariant is short: preserve existing identities and unrelated
content, use controller-reserved IDs, and return explicit proposed lifecycle
changes. Harness code owns allocation, enforcement, retry limits, routing,
publication, and recovery. No “when called from delivery/spec then orchestrate”
instructions are added to role prose.

After a repair, rerun integrity checks and the relevant semantic review.
Invalidate and rerun dependent stages only when their bound inputs changed.
Do not replay unrelated discovery/synthesis/intent stages solely to return to
the failed reviewer. Full existing quality gates still apply before Phase A
can advance. Identity failures cannot become quality debt or banzai waivers.

Use an initial repair attempt plus at most two automatic retries for a selected
repair unit; persist consumption before dispatch. An unchanged failing candidate
stops early with the same findings, not a fresh unit identity. Outer workflow
limits remain effective. Recovery, changed display ordering, and regenerated
findings cannot reset the unit's budget.

## Migration and rollout

1. Make consumers accept legacy IDs plus six- and seven-plus-digit IDs before
   producers emit the new format. Preserve existing labels and graph keys.
2. Add allocation/lifecycle mechanics and explicit import/audit/export tools.
   Bootstrap from declared definitions and bound historical evidence, not the
   latest current file alone. Report conflicting historical meanings; do not
   guess which reassignment was legitimate.
3. Integrate producers and enforce candidate identity/reference validation for
   newly initialized identity-managed specs. A feature snapshot distinguishes
   managed runs from legacy runs. Partial integration cannot claim coverage
   across all requested entity families.
4. Integrate bounded discovery repair and publication recovery, then exercise
   the exact smoke failure as offline fixtures and a simulated provider run.
5. After tests and review, create a separate live smoke run with matching Python
   and deployed bundles. Do not silently upgrade the stopped run in place.

The stopped run's conflicting identity history requires an explicit migration
report and approved reconciliation if it is ever resumed under this model.
The current work does not automatically accept the latest relabeled document
as the historical source of truth.

## Test checkpoints

### Phase 1: numeric compatibility

Real parsing/projection, task allocation, canonical inventory, graph,
traceability, and memory-consumer tests cover 000001, 999999, 1000000, and
10000000, mixed with preserved legacy labels. Verify full IDs are consumed,
not truncated prefixes, and large ordinals sort numerically. Existing graph
keys remain byte-for-byte stable when a legacy spec is read.

### Phase 2: durable authority

Use real on-disk transactions to test cross-process contention, duplicate
requests, request conflicts, crash/reopen, unused reservations, retirement,
rewind, missing/corrupt storage, and import/export. Exercise a million-entry
ledger without whole-ledger allocation scans; report measured performance and
storage behavior rather than claiming capacity from formatting alone.

### Phase 3: identity and reference enforcement

Use sanitized minimal fixtures derived from checkpoints 9976af0 and 76f2b80.
Reassigning U-002, removing referenced U-005, changing a reference without its
target, reusing a retired ID, and bypassing allocations must fail before
canonical publication. Authorized revisions, splits, retirement, and complete
reference updates preserve history. Stale evidence must not certify a revised
requirement. Exercise issue occurrence migration and fingerprint guards.

### Phase 4: bounded repair and recovery

A simulated provider repairs only the authorized candidate. Verify limited
write scope, owner handoffs, early no-progress blocking, exactly bounded
attempts, no unrelated replay, and full quality-gate preservation. Inject
crashes at reservation, candidate validation, promotion, ledger finalization,
and graph update boundaries; recovery must neither duplicate effects nor
claim completion from incomplete evidence. Test every banzai mode against the
same integrity rules.

### Phase 5: live verification

Run a fresh version-pinned browser-game spec trial. Record phase progression,
identity allocations, repairs, gate verdicts, token accounting, and retained
evidence. Spec success does not claim delivery-gate success. Any live provider
failure or unresolved identity migration remains explicit.

## Implementation boundaries

Prefer focused modules for identity storage, artifact adapters, and repair
packets; do not add another controller that bypasses `squad.py` completion.
Integrate the existing review-task publisher and reopen task producer through
the same service. Keep `issue_identity.py` as the revision-sensitive issue
authority guard, not an alternate allocator. Update requirement projection,
canonical inventory, graph, and memory consumers through compatibility tests.

The separate generic Codex diagnostic warning discovered during the trial has
already received work on main (`fc805544`). Inspect that change during later
integration rather than duplicating it on this branch. No merge, global
installation, or live retry is authorized by the design-document checkpoint.
