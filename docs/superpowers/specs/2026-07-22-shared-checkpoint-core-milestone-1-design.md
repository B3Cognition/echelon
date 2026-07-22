# Shared Checkpoint Core — Milestone 1 Design

## Objective

Extract the existing Phase A checkpoint implementation into a reusable internal
checkpoint core and a Spec adapter without changing any observable behavior of
`echelon spec checkpoint` or `echelon spec rewind`.

This is the first milestone of a larger architecture that will later add RE and
Delivery adapters. Milestone 1 does not migrate RE or Delivery and does not
expand the checkpoint schema.

## Primary Constraint

Existing Spec checkpoint and rewind behavior is the compatibility oracle.
Existing tests, ledger files, commit identities, CLI output, and recovery
semantics must continue to work without fixture changes. Any mismatch blocks
the extraction.

## Current Behavior to Preserve

After a successful Phase A transition, `SquadController` calls
`create_phase_checkpoint()`. The checkpoint mechanism:

- commits only active Spec artifacts, optionally the published Spec directory
  and accepted knowledge-base files;
- leaves unrelated staged, unstaged, and untracked paths untouched;
- records a clean `HEAD` when no owned path changed;
- emits `echelon-checkpoint: <spec-id> <phase>` commits with the existing
  structured Echelon trailers;
- writes `<spec-dir>/.echelon/checkpoints.json` using the existing JSON shape;
- replaces an earlier ledger entry with the same checkpoint ID;
- resolves the latest checkpoint by phase or an exact `checkpoint:<id>` selector;
- supports user-accepted and user-committed checkpoints;
- blocks the Spec run when a required automatic checkpoint fails;
- supports safe rewind using a backup ref and preservation of unrelated dirty
  workspace paths;
- reconciles checkpoint SHAs after rebases using immutable commit-message
  identity.

## Architecture

```text
src/harness/checkpoints/
├── __init__.py
├── model.py
├── ledger.py
├── git_store.py
├── adapter.py
└── adapters/
    ├── __init__.py
    └── spec.py

src/harness/phase_checkpoints.py
└── compatibility façade
```

### Model

`model.py` owns the existing `PhaseCheckpoint` and `CheckpointLedger`
dataclasses. Field names, order, defaults, equality, serialization, and import
availability through `harness.phase_checkpoints` remain unchanged.

No schema version or multi-repository fields are added in this milestone.

### Ledger

`ledger.py` owns generic deterministic ledger operations:

- load and write;
- record with same-ID replacement;
- resolve by phase or explicit checkpoint ID;
- enumerate valid selectors.

The Spec adapter supplies the ledger path and Spec identity policy. Existing
ledger JSON is read and written without migration.

### Git Store

`git_store.py` owns generic Git operations needed to create a checkpoint from
explicit owned paths:

- path containment validation;
- force-add of owned paths;
- exclusion of the ledger itself;
- commit-only behavior that does not consume unrelated staged changes;
- clean-owned-slice detection;
- current-HEAD resolution;
- dirty-worktree baseline rejection.

It does not decide which paths a workflow owns.

### Adapter Protocol

`adapter.py` defines the workflow-policy boundary:

```python
class CheckpointAdapter(Protocol):
    def ledger_path(self, context: CheckpointContext) -> Path: ...
    def owned_paths(self, context: CheckpointContext) -> OwnedPaths: ...
    def validate(self, context: CheckpointContext) -> None: ...
    def commit_origin(self) -> str: ...
```

The protocol contains no RE- or Delivery-specific fields in milestone 1. It is
small enough for those adapters to extend through context metadata later rather
than through conditional behavior in the core.

### Spec Adapter

`adapters/spec.py` reproduces existing Phase A policy:

- ledger location `<spec-dir>/.echelon/checkpoints.json`;
- Spec ID derivation from the Spec directory;
- the existing external/staging Spec-ID exception;
- ownership of the active Spec directory;
- optional ownership of a published Spec directory;
- optional ownership of accepted knowledge-base files;
- commit origin `phase-a`.

### Compatibility Façade

`harness.phase_checkpoints` remains importable and continues to export the same
public symbols with the same call signatures:

- `PhaseCheckpoint`;
- `CheckpointLedger`;
- `PhaseCheckpointError`;
- `CHECKPOINT_LEDGER_REL`;
- `checkpoint_ledger_path`;
- `load_checkpoint_ledger`;
- `write_checkpoint_ledger`;
- `record_phase_checkpoint`;
- `record_checkpoint_metadata`;
- `resolve_checkpoint`;
- `checkpoint_targets`;
- `new_checkpoint_id`;
- `create_phase_checkpoint`;
- `accept_checkpoint_baseline`;
- `commit_manual_checkpoint`.

Existing callers do not migrate in milestone 1. The façade delegates to the new
core and Spec adapter, making the extraction invisible to CLI, Squad,
Spec-switch, and rewind code.

## Compatibility Test Strategy

Before moving production behavior, characterization tests freeze:

1. Dataclass construction, field order, equality, and `asdict()` output.
2. Ledger location and exact JSON keys.
3. Existing ledger readability without migration.
4. Same-ID replacement and append ordering.
5. Latest phase resolution and explicit checkpoint-ID resolution.
6. Automatic, user-accepted, and user-committed ID generation.
7. Exact commit subject and Echelon identity trailers.
8. Active, published, and knowledge-base owned-path commits.
9. Isolation from unrelated staged, unstaged, and untracked paths.
10. Clean-owned-slice checkpoints referencing current `HEAD`.
11. Wrong-Spec rejection and staging/external identity allowance.
12. CLI checkpoint list formatting and active-Spec lookup precedence.
13. Rewind preview, confirmation, backup-ref creation, dirty-path behavior,
    cleanup, and error messages.
14. Rebased-checkpoint ledger reconciliation.
15. Public imports through `harness.phase_checkpoints` after extraction.

Existing expectations are not rewritten to match new behavior. Tests may only
be changed to add missing characterization or update import assertions that
prove the façade remains compatible.

## Migration Sequence

1. Add characterization coverage while production code is unchanged.
2. Extract models and ledger operations; re-export them through the façade.
3. Extract owned-path Git operations; keep façade behavior unchanged.
4. Add the adapter protocol and Spec adapter.
5. Route automatic, accepted, and manual Spec checkpoint creation through the
   Spec adapter.
6. Run checkpoint, CLI, rewind, Spec-switch, Squad, and full unit verification.

Each step is independently reversible and must keep the compatibility suite
green.

## Failure Handling

- Adapter validation failures use `PhaseCheckpointError` or the existing
  public exception type expected by the calling function.
- Git helper failures retain the existing wrapped messages.
- Automatic checkpoint failure continues to mark the Spec run blocked with
  `phase_checkpoint_failed: <phase>: <error>`.
- No fallback silently bypasses the adapter or writes a different ledger.
- A compatibility-test failure stops the migration before the next extraction
  step.

## Deferred Work

The following belong to later milestones:

- `ReCheckpointAdapter`;
- `DeliveryCheckpointAdapter`;
- multi-repository checkpoint records;
- artifact hashes and verification evidence hashes;
- parent checkpoint chains;
- resumable flags;
- delivery phase-boundary checkpoint creation;
- RE phase-boundary checkpoint creation;
- generic checkpoint CLI commands outside the existing Spec surface;
- ledger schema migration.

Later adapters will reuse the extracted model, ledger, and Git store or extend
them through a versioned schema. They must not add RE or Delivery conditionals
to the Spec adapter.

## Acceptance Criteria

- All existing `test_phase_checkpoints.py` tests pass unchanged.
- All existing checkpoint CLI tests pass unchanged.
- All existing rewind and Spec-switch tests pass unchanged.
- Phase A Squad tests confirm automatic checkpoint failure still blocks the run.
- Existing checkpoint ledgers remain readable and writable without migration.
- Existing commit subjects and trailers are unchanged.
- Existing `harness.phase_checkpoints` imports remain valid.
- Full unit suite passes.
- No RE or Delivery runtime behavior changes in milestone 1.
