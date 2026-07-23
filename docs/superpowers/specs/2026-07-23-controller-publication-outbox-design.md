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

Use a controller-owned durable outbox transaction:

1. Prepare every external change in a hidden run-local staging directory.
2. Fully validate and digest the staged result.
3. Seal an exact pending-publication marker into the routing decision.
4. Commit routing state and that marker through the existing state-store CAS.
5. Publish exact manifest operations idempotently.
6. Verify all postimages, then atomically clear the marker.

The existing Phase A and spec-run execution locks remain the single-writer
boundary. Recovery runs while both locks are held and before normal or manual
phase/status handling.

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
and uses deterministic drawer identities. It moves after durable file
publication and marker clearance so it can never precede routing state.

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

The sealed decision carries the marker as a transaction-owned update.
`advance()` no longer invokes a mutating `before_commit` callback. Stale
decisions and `_save_unlocked()` failures leave only an unreferenced hidden
stage, which is discarded without touching targets.

The store also provides exact compare-and-swap operations to:

- record a bounded `external_publication_failure` diagnostic while preserving
  the pre-diagnostic status and blocked reason;
- clear the exact pending marker and failure diagnostic after publication,
  restoring the preserved lifecycle fields when needed.

These operations load and save under the state lock. If marker-clear saving
fails, the durable pending marker remains and recovery repeats safely.

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

After all operations, revalidate every postimage. Only then clear the exact
state marker. Empty directories beneath known owned subtrees may be pruned
after their file deletions; unrelated directories and files are untouched.

If publication, digest verification, or marker clearing fails, the controller
records only a fixed error code such as `target_drift`, `stage_missing`,
`manifest_invalid`, `publish_io`, or `state_finalize`. Raw exceptions, target
paths, and staged content do not enter state. The pending marker is never
silently cleared.

At the start of every normal or manual execution:

1. Load and exact-validate the pending marker.
2. Derive and load its stage and manifest.
3. Fail closed with a bounded diagnostic if the stage is absent/corrupt or its
   digest differs.
4. Replay the idempotent algorithm.
5. Atomically clear the marker and diagnostic.
6. Remove the stage only after a fresh state load proves the marker is absent.
7. Continue normal phase/status handling.

Unreferenced prepared stages have never had permission to publish. They may be
removed after proving no state marker references them.

## Controller Flow

Normal and manual successful-result paths become:

1. capture routing snapshot and prepare the detached result;
2. stage and validate product/spec/manual effects;
3. add the marker and planned Phase A identity to controller-owned routing
   updates;
4. construct and seal the routing decision;
5. call state-store `advance()`;
6. publish and durably clear the marker;
7. write pending judgment journals;
8. apply timing transition, checkpoint, and context refresh.

Product mapping or Phase A readiness failures occur during staging. The
existing repair/block behavior runs against the unchanged routing snapshot and
unchanged visible artifacts.

Terminal Phase A reconciliation uses the same staged file transaction without a
new routing transition. It first commits a pending marker through an exact
state mutation, publishes, clears it, then completes terminal handling.

## Failure Semantics

- **Staging/generation/validation failure:** visible targets and routing state
  are unchanged; hidden stage is discarded.
- **Routing construction or CAS failure:** visible targets are unchanged;
  hidden stage is discarded.
- **Routing `_save_unlocked()` failure:** marker is not durable, publication is
  not attempted, and visible targets remain unchanged.
- **First or later file-operation failure:** routing plus marker is durable;
  any completed operations match postimages and recovery resumes at the first
  preimage-matching operation.
- **External target drift:** do not overwrite it, retain marker, and record a
  bounded fail-closed diagnostic.
- **Missing/corrupt stage or manifest mismatch:** do not touch targets or clear
  marker; record a bounded fail-closed diagnostic.
- **Marker-clear save failure:** all targets already match postimages; recovery
  skips them and retries the state clear.
- **Crash at any point:** the state marker is the authority. No marker means no
  publication permission; a marker means replay and verify before further
  controller work.

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

- provider and untrusted controller updates cannot set/remove the pending key;
- valid markers are sealed and persisted;
- malformed or extra marker fields are rejected;
- old states without a marker load and advance unchanged;
- exact marker CAS is required for failure recording and clearing.

### Staging visibility and validation

- product JSON/Markdown/context helpers fail at each write/validation boundary
  without changing visible files;
- Phase A copy, product evidence, finalization, index, metadata, and readiness
  failures leave the published spec byte-identical;
- manual constitution/index failures leave the spec byte-identical;
- the manifest contains only exact owned files and preserves unrelated files.

### Commit and recovery faults

- injected routing `_save_unlocked()` failure publishes nothing and leaves old
  routing state;
- failure before the first operation, between product files, between product
  and spec files, and at every later operation leaves a durable marker;
- retry skips matching postimages and completes exactly once;
- marker-clear `_save_unlocked()` failure retries without rewriting artifacts;
- target drift before initial publication and between retries fails closed;
- missing stage, corrupt manifest, manifest digest mismatch, corrupt staged
  file, and unsafe target fail closed without clearing the marker;
- normal and manual entry points recover before any phase/status mutation;
- success journals, timing, and checkpoints occur only after durable marker
  clearance.

### Token race

A deterministic concurrent mutation is injected at the old load/save boundary.
The regression proves the unrelated mutation survives and provider tokens are
added exactly once through `increment_token_usage()`.

## Compatibility and Scope

There is one behavior, not a switch. Existing runs without a pending marker use
the normal path. Successful runs finish with the same externally visible
artifacts and routing decisions; the internal marker commit/clear adds a state
revision. Interrupted runs gain a recoverable state instead of partial,
untracked publication.

No general filesystem transaction framework, database transaction, new
dependency, or unrelated publication path is introduced.
