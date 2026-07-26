# Explicit Checkpoint Rewind Selection Design

## Problem

Automatic Phase A checkpoints use the phase ID as their checkpoint ID. Manual
phase replay and repeated workflow loops can therefore record several
checkpoints with the same `id` and `phase`, each pointing to a different Git
commit.

The checkpoint list currently displays ledger insertion order without saying
that it is doing so, omits `created_at`, and shows a commit that `spec rewind`
cannot accept as a selector. A phase-only rewind silently selects the last
matching ledger entry. The behavior is deterministic, but it is neither
explicit nor sufficiently observable.

## Goals

- Preserve the existing phase-only command and its latest-recorded behavior.
- Allow an operator to select a historical occurrence by phase and commit.
- Make list order and checkpoint creation time visible.
- Fail closed when a commit prefix does not identify a safe target.
- Avoid checkpoint schema changes, migrations, compatibility switches, and
  changes to checkpoint creation.

## Command Contract

The existing command remains valid:

```text
echelon spec rewind phase1-what
```

It selects the last matching checkpoint in durable ledger order.

An optional commit selector identifies a historical checkpoint:

```text
echelon spec rewind phase1-what --commit 98152f1
echelon spec rewind phase1-what --commit 98152f1 --confirm
```

`--commit` accepts a full checkpoint commit or an abbreviated prefix. The
resolver first applies the existing phase-or-checkpoint-ID match, then filters
those matches by commit prefix.

## Resolution Rules

1. Phase or checkpoint ID without `--commit` selects the last matching ledger
   record, preserving current behavior.
2. Phase or checkpoint ID with `--commit` selects the matching commit within
   that target's records.
3. A missing target or commit match fails without changing Git, the ledger, or
   run state.
4. If an abbreviated commit prefix matches different commits, resolution fails
   and reports the candidates.
5. If duplicate records have the same phase and exact commit, the last ledger
   record is selected. Their Git and phase rewind targets are operationally
   identical, and the last record preserves the established ledger-order rule.
6. Preview output includes the same `--commit` argument in the printed
   confirmation command.

Ledger order, not `created_at`, remains authoritative. Timestamps are
diagnostic metadata and are not trusted for routing.

## Checkpoint List

`echelon spec checkpoint list` continues to display records in ledger order,
oldest to newest. It adds an explicit order note, a UTC creation column, and a
latest marker for the final occurrence of each phase:

```text
CHECKPOINTS - spec 001-create-basic-sdk-for
Order: oldest -> newest (ledger order); phase-only rewind selects the last matching row

PHASE                 COMMIT      CREATED UTC          LATEST  SOURCE
phase1-what           189065b     2026-07-23 18:40:12  -       auto
phase1-what           98152f1     2026-07-24 09:15:03  -       auto
phase1-what           383d992     2026-07-26 05:20:14  yes     auto
```

The full checkpoint ID remains available when it differs from the phase, so
user-accepted and user-committed checkpoints remain discoverable.

## Implementation Boundaries

- Extend checkpoint resolution with an optional commit-prefix argument.
- Thread the selector through the legacy CLI, Typer entry points, preview, and
  confirmed rewind.
- Improve list rendering only; do not reorder the persisted ledger.
- Reuse the same resolver for CLI pre-validation and `prepare_rewind` so preview
  and execution cannot select different records.
- Keep ledger truncation based on the resolved record's actual ledger index.

## Error Handling

Errors name the requested phase/ID and commit prefix and show matching
checkpoint candidates with their full commits and creation times. The command
must fail before backup creation, branch reset, ledger truncation, artifact
cleanup, or run-state mutation.

## Testing

Regression coverage must prove:

- phase-only resolution still selects the last ledger match;
- an older duplicate phase is selectable by abbreviated commit;
- unknown and ambiguous commit prefixes fail closed;
- preview and confirmed rewind resolve the same checkpoint;
- preview confirmation retains `--commit`;
- ledger truncation occurs at the explicitly selected record;
- checkpoint list states ledger order, shows UTC timestamps, and marks the
  latest phase occurrence;
- Typer and legacy command paths accept the new option;
- existing checkpoint and rewind tests remain green.

## Out of Scope

- Changing automatic checkpoint IDs.
- Migrating existing ledgers.
- Selecting by timestamp.
- Compatibility switches or alternate checkpoint schemas.
- Adding numeric occurrence selectors.
