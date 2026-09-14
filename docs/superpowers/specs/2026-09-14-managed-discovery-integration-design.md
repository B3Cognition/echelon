# Managed discovery: producer-to-publication integration

Status: written integration design approved by the user on 2026-09-14.
The first contract checkpoint is implemented and independently reviewed in
`../plans/2026-09-14-discovery-producer-contracts.md` (551 passing affected tests).
The inactive reservation-binding slice is also implemented and reviewed in
`../plans/2026-09-14-discovery-reservation-binding.md` (613 passing affected tests).
The inactive selected-state/bootstrap slice is implemented and reviewed in
`../plans/2026-09-14-discovery-bootstrap.md` (848 passing affected tests plus
397 managed/Squad exclusion regressions). Provider-turn recovery and positive
managed runtime activation remain open.
Baseline: `0db43e2a`, branch `fix/delivery-controller-contract`.

## Outcome and boundary

Prove that ordinary Squad discovery can create and repair questions and
assumptions without changing what an existing ID means or corrupting retained
references. Connect the existing allocation, candidate, source/graph publication
and completion owners; do not build another identity foundation or controller.

The first proving slice covers U/A creation and same-subject revision in an
explicit fresh managed spec, plus bounded discovery repair and restart. It does
not activate all managed spec phases. The next unsupported producer must stop
before dispatch, not fall back to legacy execution. FR/NFR/AC/T/ISS integration
remains required subsequent work under the existing convergence record.

The stopped browser-game workspace stays untouched. No installation, migration,
live model spending, default activation, push or merge is authorized here.
AGENTS.md, CLAUDE.md and legacy build are outside scope.

## Existing mechanisms and the missing connections

- `IdentityStore.reserve` already supports exact idempotent requests and
  permanent reservations. New labels have six digits minimum and no digit cap.
- `register_source_context`, `register_managed_identity` and managed-context
  authentication retain fresh-spec genesis, namespace and accepted source heads.
  Registration must precede reservations: existing genesis admission correctly
  rejects a spec with prior identity operations.
- Candidate adapters, `preview_identity_candidate` and proposed-history helpers
  already validate scope, definitions, revision-bound references and history.
  A passing preview is not semantic approval or publication authority.
- `PreparedSquadPublication.inspect_sources` and `publish_sources` already own
  sealed images, guarded promotion and partial-publication recovery. The identity
  publication journal can bind their manifest, source baseline and proposed
  history in a version-3 request.
- Squad's `_prepare_controller_completion` and
  `_drain_pending_controller_completion` own durable post-dispatch effects.
  The current drain calls ordinary `publish()`; managed publication must select
  the guarded composition at this owner, including on restart.
- `_run_with_execution_lease` currently rejects managed execution before
  recovery. It needs explicit authenticated managed admission for the supported
  slice, while retaining legacy exclusion everywhere else.

The discovery and graph/publication characterization suites passed 102 tests in
13.22s at this baseline. They do not prove the missing runtime connections.

## Chosen producer handoff

Use two semantic producer turns: **propose**, then **author** with host-assigned
IDs. This uses an additional turn but establishes subjects and exact reservations
before final artifacts exist. Preallocating speculative ID blocks would make
subject binding less explicit and waste reservations. Post-hoc renumbering of
finished Markdown would reintroduce the reference-rewriting hazard.

Both turns use one neutral Prosaic producer role, with an explicit assignment
operation rather than invocation-specific orchestration prose. A separate neutral
semantic reviewer assesses the final candidate. Python invokes each turn and
owns all transitions. Neither role dispatches agents, writes state, allocates
IDs, runs helpers or publishes files. Reuse the accepted no-tools inspection
interface and host-serviced reads for Claude and Codex; no native agent lookup.
Leave the existing command-driven SCOUT contract intact for legacy callers.

### Assignment and proposal

The controller supplies a versioned, closed assignment containing operation and
dispatch IDs, selected spec/run, creation or repair intent, baseline/context
digests, allowed artifact roles, editable existing IDs/revisions and the exact
repair findings when applicable. Replies must echo the assignment binding.

The proposal reply contains:

- New subjects: unique operation-local key, U/A kind, immutable subject text and
  intended caption. Keys are proposal handles, not canonical IDs or Markdown
  placeholders. Their spelling must never become an entity identity.
- Existing revisions: literal existing ID and expected revision, confined to
  the controller's edit scope. Subject and caption remain unchanged in ordinary
  discovery repair. No implied retirement, replacement, split or merge.
- An explicit blocked result when the requested repair cannot fit that scope.

Unknown fields, repeated keys, duplicate IDs, invented existing IDs, unsupported
types or conflicting bindings reject. Proposal order has no semantic authority.
The controller validates and saves canonical proposal bytes before reservation.

### Reservations and authoring

For each kind, save a reservation intent binding the repair/creation operation,
proposal digest and sorted new-key list before calling the existing allocator.
Persist its exact key-to-ID result before the author turn. An interrupted
reservation replays the identical request; never infer success from Markdown.
An abandoned reservation leaves a gap.

A repair unit retains its key/subject/reservation associations across attempts.
An unchanged proposed subject reuses its saved association; a key cannot acquire
a different subject. Additional subjects require new keys and new reservations,
without resetting repair attempts. Do not add fuzzy subject deduplication.

The author receives this immutable mapping, accepted baseline and allowed scope.
It returns exact UTF-8 candidate artifact text keyed only by controller-assigned
logical paths, together with the assignment binding. There is no placeholder
replacement pass. Python stages those texts within the existing publication
transaction and constructs lifecycle operations from the parsed declarations
and saved proposal—not from model-supplied storage requests.

Every proposed definition must be represented exactly once with its assigned
ID and proposed caption. All references must resolve under the existing typed
adapters. Missing or extra definitions, padding aliases and altered existing subjects reject. A
rejected author result does not advance identity history, source heads, graph,
accepted artifacts or completion.

## Artifact scope and independent review

Creation uses the existing discovery output set: glossary, mental model,
boundaries, assumptions, unknowns and greenfield reference architectures. Keep
their formats/templates. U/A are definitions; other artifacts use explicit
existing typed or opaque roles, never guessed roles from filenames.

Repair starts with an accepted source snapshot and controller-selected element
and artifact scope. Unrelated text is preserved by the existing candidate
validator. Investigation/evidence dependencies are captured read-only. A repair
requiring writes by another owner stops with that dependency identified; this
first checkpoint does not give discovery unrestricted cross-owner writes.
Retirement and other advanced lifecycle operations also block explicitly until
a necessary, separately specified producer path can preserve their consumers.

After authoring, structural preview checks the complete candidate and dependency
set. The reviewer then sees the bound before/after images, reserved subjects,
allowed edits and retained reference/evidence targets. Its closed response gives
an accept/reject disposition for every created or revised U/A definition and
specific candidate-bound findings. Review claims cannot override structural
failure or expand scope. Python binds the accepted review to the exact candidate,
assignment, role/profile, source baseline and proposed-history digest.

Reviewer finding keys identify entries within that immutable review receipt;
they do not masquerade as durable ISS entities. Existing authoritative review
findings used to request repair retain their original report/occurrence binding.
Normal WHY/quality gates remain necessary before broader Phase A progression;
this identity review neither replaces those gates nor marks the spec complete.

## Managed admission and publication ownership

The first implementation exposes an internal, explicit discovery capability to
the real Squad execution path for offline acceptance. It adds no public rollout
flag or automatic enrollment of existing workspaces. A future public selection
must be specified when the remaining producers can safely run.

Under the existing Phase A and selected-run execution locks, bootstrap a fresh
selected spec using the existing source-context and genesis APIs, then durably
bind that exact registration to run state before any producer or reservation.
All bootstrap retry IDs and source selection are persisted first. Resume must
authenticate both the independent selected run/spec and retained authority;
missing state metadata cannot select legacy execution. Missing or contradictory
established storage blocks without reconstructing it from file maxima.

The internal capability admits discovery and its recovery only. It must not
weaken manual-entry, human-input, rewind, retarget or projection exclusion guards.
Pending managed completion is authenticated and drained before deciding whether
the next phase is supported. Preserve that next phase as the resume destination,
but stop before its provider dispatch when its managed implementation is absent.

Compose accepted publication at the existing Squad completion boundary:

1. Seal the candidate and graph derived from its exact projected images and
   proposed history. Retain the complete accepted source baseline and read set.
2. Bind the semantic receipt, publication manifest, source claim, lifecycle and
   reference operations to a version-3 identity publication intent. Persist its
   association with the existing pending publication/completion markers before
   promotion. Neither an arbitrary recovery payload nor a supplied hash grants
   authority; the controller authenticates the association on every recovery.
3. Use the existing guarded `publish_sources` promotion loop and identity intent
   APIs, following the already tested graph/source/publication composition.
   Confirm final source and graph bytes before applying the bound identity
   operations; stale history or source drift leaves a blocked pending operation.
4. Drain existing completion effects idempotently only after accepted publication.
   Release the identity publication guard after all dependent completion receipts
   are durable. Retain recovery material until that release is safe.

No second publication or completion engine is introduced. Extend the existing
validated marker/intent association narrowly if required; never accept an
unvalidated provider state field as the managed branch selector. A saved next
phase is not permission to execute it while completion remains pending.

Graph/context consumers must use the same accepted/projected source and history
as the publication. Preserve old evidence's revision target; a changed body does
not inherit verification. The fresh proving fixture has no linked RE or external
memory domains. Their absence must be established from actual configuration and
source selection, not mocked as empty. If an enabled dependency cannot be captured
and authenticated by existing mechanisms, block the slice. Do not activate a
new general collector or call a guarded legacy writer to bypass this condition.

## Repair and recovery

A repair unit is selected once by the controller from an accepted baseline and
immutable findings. Save its identity, target scope and origin before dispatch.
Candidate hashes, reordered findings and resumed processes cannot create a new
budget for the same unresolved unit. Use initial repair plus at most two automatic
retries, consuming an attempt durably before its first producer turn. Stop early
when normalized findings and scoped candidate content show no progress; IDs or
formatting alone do not demonstrate semantic progress.

Persist each provider intent before dispatch, then validated response and usage
before proceeding. Reuse completed replies and reservations; unknown provider
completion blocks rather than redispatching. Failed calls still count. Existing
provider read, capture, elapsed-time and outer token/dispatch limits apply across
both producer turns and review; restart must not replenish them. Malformed
protocol output is a block, not an unbounded automatic formatting-repair loop.

After a successful repair, return to the exact requesting review destination.
Rerun dependencies only when their bound inputs changed. Unsupported review or
producer destinations stop before execution while retaining the selected route.
Guided, semi and banzai obey the same identity checks and repair ceiling; existing
human-input and quality policy remains unchanged.

## Acceptance exits

Implement in tested checkpoints, each using real controller decisions and real
temporary files/SQLite/Git; script external model or service boundaries only.

1. Closed proposal/author/review contracts and reservation binding: exact retries,
   altered subject/key rejection, mixed legacy/wide IDs and no provider writes.
2. Fresh managed discovery through actual Squad admission, producer dispatch,
   structural/semantic review and guarded publication. Prove U/A create and
   same-subject revision; accepted IDs and references agree with retained history.
3. Fault injection before/after reservation, each provider result, publication
   intent, partial promotion, identity application and completion/release. No
   duplicate allocations, provider dispatch, charges or completion effects.
4. Original smoke reassignment/removal fixtures still fail unchanged. Reproduce
   the same failure through managed discovery using newly allocated six-digit
   IDs, rather than importing the stopped run or disguising it as fresh genesis.
   Reject before canonical mutation; then accept a scoped corrective candidate.
5. Durable repair exhaustion/no-progress, stale evidence, changed inputs, missing
   authority, cross-owner edits and unsupported next-phase admission. Exercise
   Claude/Codex facades and guided/semi/banzai with real shared host boundaries.
6. Legacy Squad, state/publication/completion, graph and candidate regressions.
   Independently review runtime integration before claiming this slice complete.

An internal discovery acceptance is not all-family managed execution, whole-spec
success, installed-bundle acceptance or live-provider proof.

## Deferred dependency disposition

Required here: DEFER-000004's managed publication/completion integration;
DEFER-000002's existing captured graph/history preservation for the selected
source set; DEFER-000003's fresh genesis and recovery APIs; DEFER-000005's existing
typed discovery/reference adapters. DEFER-000001 remains limited to create and
same-subject revise in this slice. No general history UI, migration, new artifact
domains or advanced lifecycle authoring is resumed.

This defines the proposal/reservation and semantic-review handoff for discovery.
The inactive checkpoints now implement wire shapes, durable reservation binding,
selected bootstrap and receipt-backed execution of an individual semantic step.
The [provider recovery plan](../plans/2026-09-14-discovery-provider-recovery.md)
records the latter's tested boundary: shared secure receipt I/O, protected state
selection, no-tools turns through neutral Prosaic roles, retained bounded reads,
explicit checked-result receipts and cumulative accounting. A checked result is
not semantic acceptance or publication authority. The integrated producer still
must own complete input/domain capture, semantic ordering, independent candidate
review, durable repair attempts and guarded Squad publication/completion.
These checkpoints deliberately do not select a public activation configuration. The later
all-family release checkpoint must decide that interface before rollout, without
reinterpreting this internal acceptance capability as a user-facing mode.
