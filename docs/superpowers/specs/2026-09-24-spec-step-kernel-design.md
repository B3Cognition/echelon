# Phase A Spec-Step Kernel Design

**Date:** 2026-09-24  
**Milestone:** S5 — Reduce spec authoring to one controller kernel and publication boundary

## Intent

Phase A spec authoring must have one understandable durable loop:

```text
recover pending step -> plan route -> execute phase -> seal step
    -> apply/verify effects -> commit final state
```

The change is a hard cutover for newly created runs. Historical or unversioned
Phase A run state is not migrated or resumed. Existing project modes, source
layouts, CLI behavior, phase graphs, provider execution, and publication
safety remain supported.

The implementation must simplify orchestration without rewriting the proven
filesystem-safety primitives underneath publication.

## Current-System Inventory

The active path begins in `echelon.spec_service`, constructs a
`SquadController`, and enters `SquadController.run()`. The active ownership
knot is approximately:

- `src/harness/squad.py`: 15,899 lines; `SquadController` spans 14,947 lines.
- `src/harness/squad_state.py`: 7,313 lines; `SquadStateStore` spans 5,150 lines.
- `src/harness/squad_executors.py`: 4,140 lines.
- `src/harness/squad_completion.py`: 3,966 lines.
- `src/harness/squad_publication.py`: 2,990 lines.
- `src/echelon/spec_service.py`: 8,519 lines.

One logical routed result currently becomes several overlapping durable
representations:

1. a prepared provider result;
2. a prepared routing decision and state snapshot;
3. `pending_external_publication` plus its failure lifecycle;
4. a publication transaction and manifest in `.publication-outbox`;
5. `pending_controller_completion` plus its failure lifecycle;
6. a second intent/receipt transaction in `.completion-outbox`;
7. an effect plan and cursor encoded in the completion marker;
8. final dispatch, phase, and completion-history state.

Recovery and validation are consequently split between `SquadController`,
`SquadStateStore`, `squad_completion`, and `squad_publication`. The store knows
completion intent semantics, the controller knows receipt and outbox mechanics,
and publication can be pending independently of its matching completion.

The large surface is protected by substantial behavioral coverage. The
pre-design baseline passed 513 focused spec-controller tests; the exact base
tree also passed the repository's 9,832-test unit gate. The design therefore
reuses established low-level primitives and replaces only the duplicated
protocol ownership.

## Product Ruling: Current Runs Only

Every newly initialized Phase A state contains an exact
`phase_a_state_version`. The first supported value is `1`.

An existing run is resumable only when its version exactly matches the current
version. Missing, older, or unknown versions are rejected before controller
construction. The error tells the user that the run is unsupported and must be
restarted explicitly with `echelon spec run --reset`.

There is no migration adapter, compatibility decoder, best-effort repair, or
fallback into the old controller. Reset creates a new run using the current
contract; it does not translate the previous state.

This ruling applies to run-state compatibility, not project topology. New Phase
A runs may still target greenfield, brownfield, self-analysis, or configured
workspace sources.

## Target Architecture

### Controller

`SquadController` owns the phase-level loop only:

1. acquire the existing execution locks;
2. recover the one pending spec step, if present;
3. stop if recovery remains blocked;
4. select and execute the current phase;
5. validate the provider result and plan the route;
6. seal and persist one spec step;
7. ask the step kernel to drain it;
8. continue only after the pending step is cleared.

The controller does not inspect receipt files, advance effect cursors, operate
outboxes, or publish files directly.

### Spec-Step Kernel

A focused `harness.spec_step` module owns immutable step types, exact canonical
serialization, validation, and marker/receipt identities. It does not import
the controller, state store, executor implementations, or publication module.

A focused `harness.spec_step_effects` module owns recovery and ordered effect
application. It loads the sealed intent, verifies the current cursor and
receipts, calls one effect adapter, and asks the state store to advance or
complete the step.

This is a Phase A kernel, not a generic workflow framework. No abstraction is
added for Delivery, RE, or unrelated transaction systems.

### State Store

`SquadStateStore` remains the single owner of atomic state persistence and CAS
checks. Its spec-step interface is deliberately small:

- capture a routing snapshot;
- begin a step against that exact snapshot;
- record a bounded step failure;
- advance the cursor with an exact receipt digest;
- complete the step with its exact final state postimage;
- discard the entire run only through explicit reset.

The store validates marker structure, snapshot identity, allowed cursor
movement, and exact final postimage identity. It does not interpret publication,
journal, timing, quality, checkpoint, context, mining, or retarget behavior.

### Publication

`SquadPublicationTransaction` remains the low-level descriptor-safe filesystem
publisher. Existing protections remain intact, including manifest sealing,
target-drift checks, pinned file identities, directory safety, atomic writes,
fsync behavior, and postimage authentication.

S5 does not merge or rewrite the physical publication outbox. A publication
stage uses the spec step's `step_id`, and the sealed step intent authenticates
its marker. Publication no longer has an independent marker or failure
lifecycle in `state.json`; it is the first optional step effect.

The existing completion outbox is replaced by `.spec-step-outbox/<step-id>/`.
Reusable deterministic effect implementations may be moved out of
`squad_completion`, but its completion marker, intent lifecycle, recovery
orchestrator, and `.completion-outbox` are deleted after the final cutover.

## Durable State Contract

New run state contains:

```json
{
  "phase_a_state_version": 1,
  "pending_spec_step": {
    "schema_version": 1,
    "step_id": "<32 lowercase hex characters>",
    "intent_sha256": "<sha256>",
    "receipts_sha256": "<sha256>",
    "cursor": "publication",
    "origin": "routed",
    "publication_binding_sha256": "<sha256 or null>",
    "failure": null
  }
}
```

The marker is an exact schema. `origin` is one of `routed`, `terminal`, or
`resolution`; automatic routing and manual phase replay both use `routed`,
distinguished by the sealed route identity. The cursor is either the next
declared effect or `commit`.
Failure, when present, has an exact bounded schema containing the effect name,
failure code, attempt count, and lifecycle status to restore after recovery.

The full immutable intent stays in the spec-step outbox and includes:

- source state revision and previous-dispatch identity;
- origin and routing identity;
- authenticated prepared-result identity;
- ordered effects;
- optional publication marker binding;
- controller-owned state updates and removals;
- exact final state postimage and digest;
- any judgment or checkpoint provenance required by the route.

Large payloads and staged files are never duplicated into `state.json`.

At most one `pending_spec_step` may exist. A controller cannot dispatch another
provider while the marker is present.

## Step Flow

### Planning and Sealing

The controller validates the provider result and computes one complete route
before making external changes. The step builder creates the exact final state
postimage and ordered effect list, seals the immutable intent and initial empty
receipts, then rereads and verifies both.

`SquadStateStore.begin_spec_step()` performs one CAS write against the routing
snapshot. That write adds the pending marker but does not advance the phase or
expose the final completion history. If the CAS fails, the unreferenced stage is
discarded and no effect runs.

### Recovery and Effect Application

Recovery always runs before provider dispatch:

1. load the current-version state;
2. load the exact intent and receipts named by `pending_spec_step`;
3. verify marker, intent, receipt, state-snapshot, and publication bindings;
4. apply or verify the effect named by the cursor;
5. durably append its receipt;
6. atomically update the receipt digest and advance the cursor;
7. repeat until the cursor is `commit`;
8. atomically install the exact final state postimage and remove the marker;
9. discard the completed step stage best-effort.

Recovery never regenerates a missing intent, silently restarts a phase, or
redispatches the provider.

### Ordered Effects

An intent contains only the effects required by its route, in canonical order:

```text
publication -> journal -> timing -> checkpoint -> quality
            -> context -> mining -> retarget -> commit
```

Each effect adapter:

- reads the sealed intent and any existing receipt;
- verifies and returns an existing completed postimage when replayed;
- otherwise performs the effect once;
- returns a bounded receipt with effect identity and postimage evidence;
- never mutates routing state directly.

The final `commit` is a state-store operation, not an external effect. It owns
phase advancement, dispatch history, completion history, counters, and
lifecycle status together.

## Failure Semantics

- A provider or routing failure before sealing uses the existing phase-level
  blocked result. No spec step exists.
- A retryable effect I/O failure retains the step and cursor, records its
  bounded failure, and resumes at that effect.
- Target drift or authentication failure blocks without overwriting the target.
- A missing or corrupt authoritative intent, receipt, or required publication
  stage blocks as `spec_step_corrupt`.
- A final state-commit failure retains the fully receipted step at `commit` and
  retries only that commit.
- An unknown state version blocks before controller construction with explicit
  reset guidance.
- Explicit reset may discard the old run and its outboxes. Ordinary resume may
  not discard authoritative artifacts.

The old `external_publication_failure` and `controller_completion_failure`
objects are replaced by the one bounded step failure record.

## Safety Strategy

The cutover must make the system less fragile after completion without placing
the secure filesystem implementation at risk during development.

Therefore:

- preserve provider-result validation and routing snapshot/CAS validation;
- preserve the publication transaction implementation until all paths use the
  new adapter;
- retain fail-closed behavior for missing, corrupt, or mismatched evidence;
- require every effect to be idempotent or postimage-verifiable;
- cut over vertical behavior paths before deleting old ownership;
- never dual-write old and new production state for the same run;
- delete the old protocol only after all active origins use the step kernel.

The primary cutover risk is incorrect sequencing between persistence and an
external effect. Fault-injection tests at every durable boundary are mandatory,
not optional hardening.

## Cutover Sequence

1. Add the current-only state version and reject old or unversioned runs.
2. Add sealed spec-step intent, marker, receipts, outbox, and state-store
   primitives without routing production behavior through them.
3. Cut over ordinary routed phase completion.
4. Cut over terminal Phase A completion.
5. Cut over human-resolution completion.
6. Route all external publication through the step effect adapter.
7. Move or retain reusable deterministic effect primitives behind adapters.
8. Delete both old pending keys, both failure lifecycles, the completion
   orchestrator, completion marker/intent, and `.completion-outbox` ownership.
9. Flatten the controller around the single recovery and step-dispatch path.
10. Update current documentation and run focused and repository verification.

Every production cutover task must leave the selected behavior partition green
and produce an independently reviewable commit.

## Verification

Each origin and effect boundary needs behavioral coverage for:

- normal completion;
- interruption before the step marker is persisted;
- interruption after persistence and before the first effect;
- interruption after an effect and before its receipt is advanced;
- interruption between every subsequent pair of effects;
- interruption after all effects and before final state commit;
- repeated recovery after every interruption;
- missing or corrupt intent, receipts, and publication stage;
- target drift and authentication mismatch;
- stale state revision and previous-dispatch conflicts;
- no provider redispatch during recovery;
- no duplicated publication, journal, timing, checkpoint, context, mining, or
  retarget effects.

Focused verification covers spec-service boundaries, squad controller,
state-store contracts, completion effects, publication transactions, human
input routing, manual phase replay, terminal completion, and recovery. The
repository merge-verification gate remains mandatory at the end.

## Acceptance Criteria

- New Phase A runs contain exactly one supported state version.
- Historical and unversioned runs are rejected with reset guidance.
- At most one durable spec step is pending.
- Recovery has one controller entry point.
- Publication has one controller-facing effect boundary.
- `SquadStateStore` contains no external-effect orchestration.
- `SquadController` contains no receipt or outbox mechanics.
- Production contains no retired pending keys, old completion/publication
  failure lifecycles, or old completion recovery entry point.
- Secure publication primitives and their safety tests remain intact.
- Ordinary routed, terminal, resolution, and manual replay behaviors pass.
- Focused Phase A verification and the repository gate pass with zero new
  failures.

## Non-Goals

- Migrating or resuming historical Phase A run state.
- Changing the phase graph, prompts, agents, or provider protocol.
- Changing the meaning of guided, semi, Banzai, proportional, perfectionist,
  greenfield, brownfield, or self-analysis modes.
- Simplifying RE protocols; that remains S6.
- Reusing the kernel for Delivery or creating a generic workflow engine.
- Rewriting descriptor-safe publication or relaxing evidence integrity.
