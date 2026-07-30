# Controller Publication Outbox Design

## Goal

Make controller-owned product-input, Phase A, and manual spec publication
failure-safe without weakening routing attestation or adding a compatibility
mode. No external artifact may become visible before its routing decision is
durable, and any interrupted publication must recover deterministically before
another phase can run.

The same change replaces provider token accounting's split load/modify/save
sequence with the state store's atomic increment operation.

## Root Cause

`SquadStateStore.advance()` currently validates a sealed routing decision and
its phase/revision/dispatch compare-and-swap, then invokes `before_commit()`,
then saves the routing state. The callback writes several independent targets:

- product-input `traceability.json`, `traceability.md`, and
  `requirement-context.md`;
- active/published spec artifacts, product evidence, constitution, run
  history, report, artifact index, feature metadata, and KB reports;
- manual-run constitution and artifact index metadata.

Some validations occur after earlier writes. A callback failure, a later
publication failure, or `_save_unlocked()` failure therefore leaves externally
visible changes while routing remains at the old phase. A process crash has the
same result because there is no durable publication identity or recovery gate.

Provider usage has a separate instance of the same lost-update shape:
`_record_provider_usage()` loads state, calculates a token total, then calls
`save()`. A concurrent locked mutation between those calls either makes the
save stale or, without compare-and-swap protection, loses the concurrent
change. `SquadStateStore.increment_token_usage()` already provides the exact
atomic operation.

## Chosen Architecture

Use two controller-owned durable outbox transactions:

1. Prepare every external change in a hidden run-local staging directory.
2. Prepare the bounded post-dispatch completion intent in a separate hidden
   run-local staging directory.
3. Fully validate, digest, flush, sync, and reread both staged results.
4. Seal the exact completion marker and any applicable publication marker into
   the routing decision.
5. Commit routing state and all applicable markers through one existing
   state-store CAS.
6. Publish exact manifest operations idempotently.
7. Verify all postimages, then atomically clear the publication marker and
   advance the completion marker to its first effect in one exact-CAS save.
8. Replay each completion effect through an intrinsic idempotency receipt.
9. Verify every applicable receipt, mark the dispatch complete, and atomically
   clear the exact completion marker.

The existing Phase A and spec-run execution locks remain the single-writer
boundary. Recovery runs while both locks are held and before normal or manual
phase/status handling. A route without file publication still commits a
completion marker in its routing CAS, starting at its first effect. Terminal
reconciliation commits both markers through one exact state mutation and uses
explicit terminal provenance rather than an older `last_dispatch`.

This ordering is preferred to external-first rollback. External-first rollback
would preserve the old phase on a publication failure, but it needs a
cross-resource rollback protocol and must infer whether a crash occurred before
or after the state commit. State-first outbox publication has one authoritative
commit point: external visibility is permitted only when state already contains
the durable pending marker.

## Components

### Publication transaction module

A focused `harness.squad_publication` module owns:

- the marker and manifest schemas;
- exact validation and safe path resolution;
- durable stage-file and manifest writes;
- preimage/postimage digest calculation;
- idempotent file installation and deletion;
- recovery loading and verification;
- stage cleanup only after durable marker removal.

The transaction root is fixed beneath the run directory. State contains only a
bounded transaction identifier and manifest digest, never an arbitrary stage
path. Recovery derives the stage path from the trusted run directory and the
validated identifier.

### Controller staging adapter

`SquadController` builds a virtual published-spec tree in staging so existing
generators and validators can operate without visibility. It then emits a
file-level manifest containing only paths owned by Echelon:

- the three controller-owned product-input files;
- files supplied by the active Echelon spec tree, excluding runtime
  `.echelon` metadata;
- the owned published `inputs/**` evidence subtree;
- generated `constitution.md`, `targets.yml`, `run-history.json`,
  `squad-report.md`, `ARTIFACTS.md`, `feature-metadata.yml`, and owned
  `kb/**` reports;
- the manual path's generated `constitution.md` and `ARTIFACTS.md`.

Existing destination-only files outside those owned paths are copied into the
virtual tree for correct index generation but never appear as manifest
operations. No whole input/spec directory is swapped or removed. Type
collisions, symlinks, overlapping operations, or a staged change outside the
owned set fail preparation.

MemPalace mining is not part of the file transaction. It is already best-effort
and uses deterministic drawer identities. It is a bounded completion effect
after durable file publication, so a restart records one deterministic outcome
without leaving completion authority pending forever.

### Completion transaction module

A focused completion transaction module owns:

- the exact completion-marker, intent, and receipt schemas;
- bounded detachment and canonical JSON serialization;
- durable intent and receipt writes beneath the run directory;
- route, terminal, publication, and dispatch provenance verification;
- monotonic effect-plan transitions;
- journal batch identity and drift detection;
- final receipt verification and safe stage cleanup.

The transaction root is fixed at
`.completion-outbox/<completion_id>/`. It contains canonical `intent.json` and
canonical `receipts.json`; state never stores their path or provider text. The
completion ID is a 32-character lowercase hexadecimal value. For routed work
it is also the pre-generated, routing-attested `dispatch_id`. Terminal
reconciliation uses a fresh completion ID and explicit terminal provenance.

The intent is first detached with the same concrete-type, depth, node,
collection, string, integer, finite-float, and cycle limits used by prepared
results. Its canonical UTF-8 JSON representation must be at most 4,194,304
bytes. `receipts.json` must be at most 1,048,576 bytes. Oversized values fail
before either marker can commit. The intent contains no arbitrary path,
provider raw output, stderr, or unbounded object. Its exact top-level schema is:

```json
{
  "schema_version": 1,
  "completion_id": "<32 lowercase hex>",
  "origin": "routed | terminal",
  "publication": {
    "kind": "none | external",
    "marker": "<required exact publication marker only for external>"
  },
  "route": {
    "kind": "routed | terminal",
    "from_phase": "<routed only>",
    "to_phase": "<routed only>",
    "manual_phase_run": "<Boolean, routed only>",
    "record_completion": "<Boolean, routed only>",
    "terminal_phase": "<terminal only>"
  },
  "effect_plan": [
    "journal | timing | checkpoint | context | mining"
  ],
  "checkpoint_prestate": {
    "kind": "none | git_head",
    "head": "<40- or 64-character lowercase hex; git_head only>"
  },
  "context_reason": "<bounded controller-generated string>",
  "mine_phase_a": "<Boolean>",
  "judgment_payload_sha256": ["<64 lowercase hex>"],
  "judgments": [
    {
      "echelon_result": "<bounded detached object>",
      "quarantined_state_updates": "<bounded detached object>"
    }
  ]
}
```

The `publication` and `route` objects are exact tagged unions: `kind: none`
has no `marker`; `kind: external` has exactly one valid marker; routed route
fields and terminal route fields cannot overlap. Judgment payload digests must
match both the canonical detached payloads in the intent and durable
`last_dispatch`. `effect_plan` contains each applicable effect at most once in
the fixed order shown. `checkpoint_prestate` is also an exact tagged union:
`{"kind": "none"}` is required when `checkpoint` is absent from the effect
plan, while a planned checkpoint requires
`{"kind": "git_head", "head": <captured object ID>}`. The object ID is captured
before the completion marker can commit and is the only authority for a later
`no_change` receipt. Terminal completion permits only `mining`. Commander
recovery uses `journal` followed by `checkpoint`; ordinary routed completion
uses `journal`, `timing`, `checkpoint`, `context`, and optionally `mining`.
The existing caller-side commander-recovery checkpoint is removed so top-of-run
and inline recovery have one path-independent durable behavior.
The exact publication variants are `{"kind": "none"}` and
`{"kind": "external", "marker": <exact publication marker>}`. The exact route
variants are:

```json
{
  "kind": "routed",
  "from_phase": "<non-empty phase>",
  "to_phase": "<non-empty phase>",
  "manual_phase_run": false,
  "record_completion": true
}
```

and:

```json
{
  "kind": "terminal",
  "terminal_phase": "<exact terminal phase>"
}
```

The routed Boolean values may each be either concrete Boolean; no field is
optional within its selected variant. An empty effect plan begins at
`complete`.

Before marker commit, the canonical intent and empty receipt document are
written through durable temporary files, file-synced, atomically replaced,
directory-synced, reread, and rehashed.

### State store integration

`pending_external_publication` becomes a controller-owned, provider-reserved,
trusted routing effect. Its exact schema is:

```json
{
  "schema_version": 1,
  "transaction_id": "<lowercase hex>",
  "manifest_sha256": "<64 lowercase hex>"
}
```

Old state without the key remains valid. Unknown fields, wrong concrete types,
unsafe identifiers, malformed digests, and non-exact markers are rejected.

`pending_controller_completion` is a separate controller-owned,
provider-reserved trusted effect with this exact schema:

```json
{
  "schema_version": 1,
  "completion_id": "<32 lowercase hex>",
  "intent_sha256": "<64 lowercase hex>",
  "publication_binding_sha256": "<64 lowercase hex>",
  "receipts_sha256": "<64 lowercase hex>",
  "origin": "routed | terminal",
  "step": "awaiting_publication | journal | timing | checkpoint | context | mining | complete"
}
```

`publication_binding_sha256` is the digest of the exact tagged publication
object in the intent, including the `kind: none` sentinel. Explicit nulls,
unknown fields, and non-exact concrete types are malformed. Key membership,
not `.get()` truthiness, distinguishes an absent marker from a malformed one.

The sealed decision carries the completion marker and any applicable
publication marker as transaction-owned updates and attests the pre-generated
`dispatch_id`. `advance()` persists that exact ID in `last_dispatch`, sets
`post_dispatch_complete` to false, and persists the immutable
`completion_intent_sha256`, `completion_origin`, and
`completion_publication_binding_sha256` alongside the phase and judgment
digests. Those same values are routing-attested. They authenticate recovery
even if the pending marker is corrupt or missing. For old `last_dispatch`
records, an absent `post_dispatch_complete` means complete.
`advance()` no longer invokes a mutating `before_commit` callback. Stale
decisions and true pre-save failures leave only unreferenced hidden stages,
which are discarded without touching targets. If a save writes durably and
then raises, the controller reloads state and requires an exact match on phase,
routing digest, attested dispatch ID, both expected markers, and token total
before accepting that the commit won. It then resumes completion without a
second advance, diagnostic merge, or token increment.

The store also provides exact compare-and-swap operations to:

- record a bounded `external_publication_failure` diagnostic while preserving
  the pre-diagnostic status and blocked reason;
- record a bounded `controller_completion_failure` diagnostic while preserving
  the pre-diagnostic status and blocked reason;
- clear the exact publication marker and failure diagnostic while advancing
  the exact completion marker to the first bound effect in one save;
- advance one exact completion step only to its next bound step;
- after verified receipts, clear the exact completion marker, restore lifecycle
  fields, set routed `last_dispatch.post_dispatch_complete` to true, persist
  the final receipt digest and completed publication-binding digest, and set
  terminal status to `done` in one save.

Routed finalization adds these bounded fields to the exact matching
`last_dispatch`: `completion_intent_sha256`,
`completion_receipts_sha256`, `completed_publication_binding_sha256`, and
`post_dispatch_complete: true`; Phase 4 completion additionally stores
`phase_a_active_source_sha256` and
`phase_a_published_postimage_sha256`. Terminal finalization writes this
separate controller-owned exact receipt while setting status:

```json
{
  "last_terminal_completion": {
    "schema_version": 1,
    "completion_id": "<32 lowercase hex>",
    "intent_sha256": "<64 lowercase hex>",
    "receipts_sha256": "<64 lowercase hex>",
    "publication_binding_sha256": "<64 lowercase hex>",
    "terminal_phase": "<exact terminal phase>"
  }
}
```

Providers cannot set, replace, or remove these receipt fields.

These operations load and save under the state lock. If marker-clear saving
fails before its save, the exact old marker remains and recovery repeats. If it
raises after its save, only an exact reload of the next marker or final durable
receipt proves that the mutation won.
Every post-save exception is resolved by reloading and accepting only the exact
old or next marker identity. No provider result, queued update, routing update,
or transaction removal can install, advance, or remove completion authority.
Step APIs receive the validated typed intent, recompute its canonical digest,
and permit only the immediate successor in its bound effect plan. Skips,
repeats, regressions, origin changes, and transitions not named by that intent
fail without state mutation.

The marker's `receipts_sha256` initially binds the canonical empty receipt
document. Before each effect, recovery requires either:

1. the receipt document exactly matching the marker-bound prefix; or
2. that exact prefix plus the single exact receipt for the current effect,
   whose immutable effect plan and any referenced fixed substage verify.

The second case is the crash-after-effect/before-step-CAS case and advances
without rerunning the producer when its postimage verifies. If its postimage is
not yet complete, recovery may finish only that exact immutable plan from its
validated substage, then verify it and advance. It never regenerates the plan.
The next marker binds the new complete receipt prefix. Rollback, mutation of an
earlier receipt, multiple uncommitted receipts, or a receipt for a
future/inapplicable effect fails closed.

### Completion effects and receipts

`receipts.json` has the exact top-level fields `schema_version`,
`completion_id`, and `effects`. The `effects` object may contain only effects
listed in the bound plan. Each effect writes and verifies its exact receipt
before the state step can advance:

- **Journal:** The controller reconstructs only the intent's detached judgment
  entries and controller quarantine warnings. It overwrites any
  provider-supplied `id`, `timestamp`, `phase`, or reserved completion fields,
  then stamps every emitted row with the exact completion ID, zero-based entry
  index, and canonical content digest.
  The digest covers the canonical row after controller phase assignment but
  excludes generated numeric ID, generated timestamp, and the completion stamp
  itself, avoiding a recursive digest. The intent binds the ordered expected
  content digests. If a crash leaves exact stamped rows but no receipt, recovery
  adopts their existing IDs/timestamps only after validating consecutive
  unique IDs, one shared valid timestamp, exact phase, ordinals, and content
  digests; it never regenerates different metadata over a visible batch.
  Under a dedicated journal lock shared by every harness journal writer, it
  rereads and validates the complete journal, preserves all unrelated rows,
  rejects malformed JSON, duplicate indexes, missing indexes, unexpected rows,
  or same-ID content drift, then writes the preserved-plus-missing batch
  through a durable temporary file, `fsync`, atomic replace, and parent
  directory `fsync`. A replay either verifies the exact complete batch or
  fails closed; it never appends a duplicate or overwrites an unrelated row.
  The receipt records the ordered row digests and adopted stable metadata. All
  repository writers of `reasoning-journal.jsonl`, including Python executors
  and shell timing/hormone hooks, use the same lock before read, append, or
  replace.
- **Timing:** The existing transition helper is replay-convergent:
  an already-finished close is accepted and an already-started open is reused.
  Every new close/open timing event used as a receipt embeds the exact
  completion ID and a stable event identity
  `<completion_id>:timing:<close|open>:<phase>`. Recovery discovers and
  validates those fields directly after a crash; post-hoc hashes alone are
  insufficient. The receipt records the exact close/open phase and hashes of
  those tagged events. A crash after telemetry write but before receipt/step
  CAS reuses the exact tagged event and does not append duplicates.
- **Checkpoint:** Automatic checkpoints carry the completion ID in both a Git
  trailer and the ledger record. Replay first validates an exact ledger
  receipt. If the commit happened before the ledger write, it performs a
  bounded search of at most 256 commits reachable from repository refs,
  requires the exact completion/run/spec/phase/next identity and unique commit,
  and repairs only the ledger receipt. Ledger mutation is serialized by its
  lock and uses a sibling temporary file, file `fsync`, atomic replace, and
  parent-directory `fsync` before its receipt can advance state. If a bound
  checkpoint receipt survives but the ledger is missing or truncated, recovery
  may repair that ledger only after the receipt and the one unique bounded
  commit prove the exact same identity; other prior-effect postimage loss or
  drift remains a fail-closed condition. It never creates a second commit for
  the same completion ID. The receipt records the verified commit and ledger
  identity. When no owned change exists, the intent-captured HEAD must still be
  current and an exact `no_change` receipt records it; no trailer-bearing commit
  is claimed or created. A no-active-spec checkpoint has a distinct exact
  `not_applicable` receipt.
- **Context:** Context generation writes only the fixed output set into a
  completion-local substage. Once generated, the exact canonical bytes,
  fixed-name digests, source state revision, and preparation time are durably
  added as the current one-ahead context receipt before any visible context
  write. Visible installation then uses a file-level preimage/postimage
  algorithm equivalent to publication. Recovery with that receipt installs or
  verifies the frozen bytes and never invokes the generator again, even if the
  clock, state revision, or MemPalace inputs changed. If generation crashes
  before the receipt, no visible context write is permitted and regeneration
  is safe. No arbitrary path is accepted.
- **Mining:** The deterministic MemPalace drawer identity makes replay
  convergent. The helper returns one bounded outcome:
  `written`, `already_present`, `unavailable`, `failed`, or `not_applicable`,
  plus only validated bounded drawer IDs and the canonical spec digest.
  If an exact one-ahead receipt already exists, recovery verifies its canonical
  spec postimage and deterministic drawer identities before considering a
  producer replay. The outcome is durably receipted and the step advances even
  for best-effort `unavailable` or `failed`, preventing an infinite pending
  completion.

After the marker reaches `complete`, finalization reloads the intent and
receipts, verifies an exact receipt for every applicable effect and no receipt
for an inapplicable effect, revalidates external identities where applicable,
and only then invokes the final exact-CAS removal. Routed finalization sets the
same `last_dispatch.dispatch_id` to `post_dispatch_complete: true` and stores
the receipt digest plus the exact completed publication-binding digest.
Terminal finalization sets `status: done` in that same save. A latest completed
Phase 4-to-terminal dispatch whose stored publication binding matches the
published identity is durable proof for terminal readiness. For Phase 4, final
state also persists canonical `phase_a_active_source_sha256` and
`phase_a_published_postimage_sha256` inventory digests. A fresh controller
recomputes both exact owned inventories; only equal digests suppress a second
time-varying terminal publication. A mismatch triggers normal terminal
reconciliation. A final-save exception is success only when a reload proves
the marker absent and the durable routed `last_dispatch` or
`last_terminal_completion` receipt fields exact.

### Global lock order

All code paths use one declared outer-to-inner lock rank:

1. `PhaseAExecutionLock`;
2. `SpecRunExecutionLock`;
3. publication exclusivity lock;
4. completion-outbox lock;
5. checkpoint ledger lock;
6. reasoning-journal lock;
7. telemetry-store write lock;
8. `SquadStateStore` file lock.

Locks at ranks 3 through 7 are acquired only for their individual side effect
and released before the state step CAS unless the total order above is
preserved. State-store code never calls a filesystem publisher, completion
producer, journal writer, telemetry writer, or controller callback while its
lock is held. Every writer of the reasoning journal uses rank 6. Equal-rank
reentry is permitted only for the exact same logical lock identity. A static
lock-rank assertion plus an adversarial two-thread regression covers every
used nested pair, fails on reverse acquisition, and rejects different lock
identities at the same rank.

## Manifest and Ownership Contract

The manifest is immutable after routing commit and contains a sorted list of
exact operations. Each operation records:

```json
{
  "action": "write | delete",
  "target": "<workspace-relative POSIX file path>",
  "preimage": {
    "kind": "missing | file",
    "sha256": "<64 lowercase hex or omitted for missing>"
  },
  "postimage": {
    "kind": "missing | file",
    "sha256": "<64 lowercase hex or omitted for delete>"
  },
  "staged": "<transaction-relative file path, write only>"
}
```

Targets must resolve inside the project root and match an explicitly supplied
owned-path set. Transaction and staged paths must remain inside the derived
transaction root. Duplicate, ancestor-overlapping, absolute, `..`, symlink,
device, socket, and directory-as-file targets are rejected. The manifest digest
is calculated from canonical JSON and checked against the state marker on every
load.

Before the marker CAS commit:

- every staged file is flushed and `fsync`ed;
- each staged digest is recomputed and matched;
- the canonical manifest is flushed, `fsync`ed, and reread;
- relevant stage directories are synced following the state store's durability
  convention.

The stage remains intact until clearing the state marker has completed
durably.

## Publication and Recovery Algorithm

For each sorted operation:

1. Read the target's current kind and digest without following symlinks.
2. If it exactly matches the postimage, skip it. This is the idempotent recovery
   case.
3. Otherwise require an exact preimage match. Unexpected creation, deletion,
   content drift, or type drift fails closed.
4. For a write, copy the immutable staged file to a sibling temporary file,
   flush and sync it, recheck the target preimage, atomically replace the target,
   sync the parent directory, and verify the postimage digest.
5. For a deletion, recheck the preimage, unlink only that exact owned file,
   sync the parent, and verify absence.

After all operations, revalidate every postimage. Only then perform the atomic
publication-to-completion handoff: clear the exact publication marker and its
diagnostic, restore its lifecycle, and move the exact completion marker from
`awaiting_publication` to the first bound effect in one save. Empty directories
beneath known owned subtrees may be pruned after their file deletions;
unrelated directories and files are untouched.

If publication, digest verification, or marker clearing fails, the controller
records only a fixed error code such as `target_drift`, `stage_missing`,
`manifest_invalid`, `publish_io`, or `state_finalize`. Raw exceptions, target
paths, and staged content do not enter state. The pending marker is never
silently cleared.

At the start of every normal or manual execution:

1. Test marker presence by key membership and exact-validate the completion
   marker plus any applicable publication marker.
2. Derive and load both independent stages, their manifest/intent, and receipts.
3. Cross-check intent provenance against the markers and durable dispatch.
4. Fail closed before additional visible writes if either stage is
   absent/corrupt or any digest differs.
5. Replay file publication when its marker is present.
6. Atomically hand off from publication to completion.
7. Replay the current completion effect and verify/write its durable receipt.
8. Advance only to the next effect permitted by the bound plan.
9. Verify all receipts, atomically mark complete and clear completion authority.
10. Remove each stage only after a fresh state load and provenance check proves
    that neither state marker nor an incomplete bound `last_dispatch`
    authorizes it.
11. Continue normal phase/status handling. A recovered manual completion
    returns without redispatching the manual phase.

Unreferenced prepared stages have never had permission to publish. They may be
removed only after the same fresh proof. A routed orphan intent is retained
while a matching `last_dispatch.dispatch_id` has
`post_dispatch_complete: false`, even if its state marker is corrupt or
missing. Old state with neither completion marker nor the new dispatch sentinel
continues normally.

## Controller Flow

Normal and manual successful-result paths become:

1. capture routing snapshot and prepare the detached result;
2. stage and validate product/spec/manual effects when applicable;
3. generate the future dispatch/completion ID and stage the exact completion
   intent;
4. add applicable publication and completion markers plus planned Phase A
   identity to controller-owned routing updates;
5. construct and seal the routing decision, including the dispatch ID;
6. call state-store `advance()` once;
7. publish and atomically hand off to completion when applicable;
8. drain journal, timing, checkpoint, context, and mining effects through
   monotonic receipt-backed steps;
9. verify all receipts and atomically finalize the dispatch.

Routes without publication begin at their first completion effect in the same
routing save. Direct commander recovery uses the same durable completion path,
with a journal-only plan when it has a judgment journal. No successful
post-dispatch effect remains only in `_pending_judgment_results`.

Product mapping or Phase A readiness failures occur during staging. The
existing repair/block behavior runs against the unchanged routing snapshot and
unchanged visible artifacts.

Terminal Phase A reconciliation uses the same staged file transaction without a
new routing transition. It stages an explicit terminal completion intent,
commits both markers in one exact state mutation, publishes, hands off to
terminal mining, and sets terminal status to `done` only in the receipt-verified
final completion CAS. It never derives completion work from stale
`last_dispatch`. Conversely, a completed latest Phase 4 routed receipt with the
same publication binding suppresses redundant terminal reconciliation after a
process restart.

## Failure Semantics

- **Staging/generation/validation failure:** visible targets and routing state
  are unchanged; hidden stage is discarded.
- **Routing construction or true pre-save CAS failure:** visible targets are
  unchanged; hidden stages are discarded after fresh non-authority proof.
- **Routing or terminal save-then-raise:** reload and prove the exact committed
  markers/dispatch. A winning commit resumes without a second route or token
  charge; a non-winning commit follows pre-save cleanup.
- **First or later file-operation failure:** routing plus marker is durable;
  any completed operations match postimages and recovery resumes at the first
  preimage-matching operation.
- **External target drift:** do not overwrite it, retain marker, and record a
  bounded fail-closed diagnostic.
- **Missing/corrupt stage or manifest mismatch:** do not touch targets or clear
  marker; record a bounded fail-closed diagnostic.
- **Publication-handoff save failure:** all targets already match postimages;
  recovery skips them and exact-retries or accepts the handoff after reload.
- **Missing/corrupt completion intent or receipts:** retain all authority, do
  not run further effects, and record only a bounded completion code.
- **Publication marker without completion authority:** this cannot reconstruct
  bounded success intent. Preserve the exact publication marker, publish
  nothing further, and block with bounded `completion_missing`; do not infer
  provenance from `last_dispatch`.
- **Effect failure:** retain the exact current step and completion stage,
  preserve resumable lifecycle in a bounded diagnostic, and retry before any
  phase work.
- **Crash after an effect but before step CAS:** verify or recreate the
  effect-specific idempotency receipt, then advance exactly once.
- **Final completion save failure:** reload; absence plus exact durable dispatch
  or terminal receipt proves success, otherwise retain the stage and retry.
- **Crash at any point:** publication authority controls visible file effects;
  completion authority controls post-dispatch effects. Neither runner executes
  until both authorities are absent and any matching dispatch sentinel is
  complete.

## Token Accounting

`_record_provider_usage()` keeps its existing concrete-result, concrete-positive
integer, deferred-routing, and local telemetry-lock checks. Its non-deferred
branch calls:

```python
self._state_store.increment_token_usage(raw)
```

It performs no independent load, normalization, or save. The state store's
exclusive mutation preserves all concurrent state fields and increments tokens
exactly once.

## Test Strategy

Tests use real temporary files and deterministic fault injection. Every
production behavior is introduced through a red-green cycle.

### State and marker contract

- provider and untrusted controller updates cannot set, advance, or remove
  either pending key;
- valid completion and applicable publication markers are sealed and persisted
  together in one save;
- malformed, explicit-null, extra-field, wrong-origin, and illegal-step
  markers are rejected by key membership and exact schemas;
- old states without either marker or the dispatch completion sentinel load and
  advance unchanged;
- exact marker and dispatch CAS is required for failure recording, handoff,
  every monotonic step, and final clearing;
- intent concrete-type/structure limits, the 4 MiB canonical size limit, exact
  tagged unions, digest reread, and effect-plan transition table are covered.

### Staging visibility and validation

- product JSON/Markdown/context helpers fail at each write/validation boundary
  without changing visible files;
- Phase A copy, product evidence, finalization, index, metadata, and readiness
  failures leave the published spec byte-identical;
- manual constitution/index failures leave the spec byte-identical;
- the manifest contains only exact owned files and preserves unrelated files.

### Commit and recovery faults

- injected true pre-save routing failure publishes nothing and leaves old
  routing state;
- route and terminal save-then-raise faults prove the exact committed markers
  resume without a second advance or token charge, including nonzero deferred
  tokens;
- failure before the first operation, between product files, between product
  and spec files, and at every later operation leaves a durable marker;
- retry skips matching postimages and completes exactly once;
- publication-handoff `_save_unlocked()` failure retries without rewriting
  artifacts and cannot expose completion effects before the exact handoff;
- target drift before initial publication and between retries fails closed;
- missing stage, corrupt manifest, manifest digest mismatch, corrupt staged
  file, and unsafe target fail closed without clearing the marker;
- normal and manual entry points recover before any phase/status mutation;
- success journals, timing, checkpoints, context, and mining occur only after
  durable publication-marker clearance;
- a completely new controller instance reconstructs intent and resumes after
  route CAS with and without publication, after the publication handoff, after
  every effect and before its step CAS, and after final completion clear;
- journal replay preserves unrelated rows and rejects missing, duplicate,
  malformed, spoofed, or digest-drifted completion identities;
- timing, checkpoint commit/ledger repair, context, and mining each prove
  crash-after-effect/before-step-CAS convergence and verified receipts;
- timing tests require completion-tagged stable event identities; context tests
  change the clock and state revision after its prepared receipt and prove
  recovery installs the original frozen bytes without regeneration;
- every state transition injects pre-save and save-then-raise faults;
- missing/corrupt intent or receipts retain authority and only bounded
  diagnostics;
- corrupt existing failure diagnostics are replaced by one canonical bounded
  diagnostic under exact raw-marker CAS, for valid and malformed markers;
- best-effort mining outcomes advance deterministically;
- recovered manual work never redispatches, terminal provenance never replays
  stale route effects, and a completed Phase 4 receipt prevents redundant
  terminal publication after final-clear restart;
- orphan intent cleanup requires fresh proof that neither state marker nor an
  incomplete bound `last_dispatch` authorizes the stage.
- lock-rank static assertions and adversarial acquisition tests prove the
  execution/publication/completion/checkpoint/journal/telemetry/state order
  cannot invert.

### Token race

A deterministic concurrent mutation is injected at the old load/save boundary.
The regression proves the unrelated mutation survives and provider tokens are
added exactly once through `increment_token_usage()`.

## Compatibility and Scope

There is one behavior, not a switch. Existing runs without either pending
marker use the normal path; old `last_dispatch` records without the completion
sentinel are treated as complete. Successful runs finish with the same
externally visible artifacts and routing decisions; internal marker/receipt
transitions add state revisions and bounded dispatch receipt fields.
Interrupted runs gain a recoverable state instead of partial, untracked
publication or lost post-dispatch work.

A state containing `pending_external_publication` but no completion marker is
not treated as a normal old state: it retains publication authority and blocks
with `completion_missing`, because no safe journal/provenance intent can be
reconstructed. A state containing neither marker remains fully valid.

No general filesystem transaction framework, database transaction, new
dependency, or unrelated publication path is introduced.

## Implementation Status

Implemented and release-verified through the completion-outbox plan. The
durable completion sequence is:

1. `0a9a93f1` — exact completion intent and stage;
2. `c45001a7` — attested state machine and exact CAS;
3. `69fdaad4` — replay-safe journal receipts;
4. `51737ec2` — completion-tagged timing and checkpoint receipts;
5. `6e02779e` — frozen context and deterministic mining receipts;
6. `81c572e9` — controller recovery gate and ambiguous-save handling;
7. `908a9b8f` — fresh-controller fault and lock-order matrix.

Task 8 also corrected the Phase 4 integration fixture in `72a60b89` so it
exercises the configured-wing deterministic mining plan used by the durable
protocol; production behavior was unchanged.

The enforced outer-to-inner lock order is Phase A, spec-run, publication,
completion, checkpoint, journal, telemetry, then state. Journal writers use
rank 6, and same-rank reentry is valid only for the exact same logical lock
identity.

Fresh release evidence:

- repository suite: `5560 passed, 9 skipped, 4 deselected`;
- focused completion protocol: `1150 passed`;
- expanded publication boundary suite: `963 passed`;
- complete fresh-controller orchestration matrix: `64 passed`;
- publication fault engine: `90 passed`;
- lock-order assertions: `24 passed`;
- shell post-dispatch hook: `13 passed, 0 failed`;
- workflow dry-run: `138 passed, 1 expected warning, 0 failed`.

Version metadata remains synchronized and unchanged at `3.7.14`. Static
compilation and diff checks pass. Ruff was not installed in the Task 8
environment, and the exact unavailability is retained in the final report.
