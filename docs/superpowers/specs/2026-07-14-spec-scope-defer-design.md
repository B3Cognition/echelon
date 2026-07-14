# Spec Scope Deferral Design

## Purpose

Let an owner deliberately defer an authored task, requirement, acceptance
criterion, success criterion, or non-functional requirement without throwing
away the reason, the affected work, or the implemented remainder of the spec.

The result must be deterministic and must let `echelon spec continue`, delivery
verification, and landing proceed only when every remaining in-scope item is
fulfilled. It replaces the unsafe use of `--allow-fulfillment-gaps` for planned
exceptions.

## Commands

```text
echelon spec defer <spec-id> <id> [<id> ...] --reason <text> [--dry-run]
echelon spec plan <spec-id> <id> [<id> ...] [--dry-run]
```

Accepted identifiers are canonical task IDs (`T-*`) and canonical fulfillment
IDs (`FR-*`, `NFR-*`, `AC-*`, and `SC-*`). The commands do not invoke an LLM.

`defer` requires a non-empty reason. It writes an active, versioned defer entry.
`plan` changes every active entry that selected or derived the supplied ID back
to planned scope while preserving the record and its original reason. It is the
user-facing inverse of `defer`.

Both commands support `--dry-run`. A dry run performs all identifier and mapping
validation but changes no files. It shows direct IDs, derived task effects,
active related requirements, dependency scheduling effects, and whether the
operation would change gap accounting.

## Persistent Ledger

Each spec owns `deferred-scope.json` beside `spec.md`, `tasks.md`, and the
fulfillment report. It is committed with the spec and is the only authority for
deferral state.

```json
{
  "schema_version": 1,
  "entries": [
    {
      "entry_id": "defer-001",
      "status": "deferred",
      "selected_ids": ["NFR-008"],
      "derived_task_ids": ["T-016"],
      "reason": "Pairwise contrast requirement is contradictory.",
      "deferred_at": "2026-07-14T12:00:00Z",
      "planned_at": null
    }
  ]
}
```

The schema stores only user-selected requirement/gate IDs and derived task IDs.
It never records transitive requirement closures. `plan` sets the entry status to
`planned` and writes `planned_at`; it does not erase history.

## Narrow Propagation Rules

Deferral is intentionally non-transitive:

1. A selected requirement/gate ID is marked `DEFERRED_SCOPE` for fulfillment
   accounting while an active ledger entry supports it.
2. A selected task ID is marked `DEFERRED` in task progress accounting.
3. Every task directly mapped to a selected requirement/gate ID is also marked
   `DEFERRED` as a whole.
4. Requirements mapped to a derived deferred task remain active unless they were
   explicitly selected. Deferral never expands from a task to its other
   requirements, nor from those requirements to more tasks.

For example, deferring `NFR-008` may derive `T-016`. If `T-016` also maps to
`FR-001`, `FR-001` remains active and must still be fulfilled, deferred
explicitly, or otherwise resolved. The dry-run output must name this condition.

`DEFERRED` is terminal for scheduling: a task depending on a deferred task may
be scheduled. Verification remains the safety net for any semantic dependency
the task graph did not express.

## Verification And Landing

Fulfillment parsing gains a `DEFERRED_SCOPE` status. A row may use that status
only when its canonical ID has an active ledger entry. The report must include
the entry ID and reason for every deferred row.

Blocking-gap calculations, fulfillment freshness checks, `spec continue`, and
delivery convergence exclude supported `DEFERRED_SCOPE` rows. They continue to
block on every other `MISSING`, `PARTIAL`, `UNVERIFIED`, or `DEVIATED` row.

Landing accepts supported deferred rows without `--allow-fulfillment-gaps` and
prints a visible deferred-scope summary. An unresolved row that lacks a ledger
entry remains a landing blocker. The legacy override is retained for compatibility
but is not a substitute for a ledger entry and should be surfaced as an unsafe
override in the landing output.

## Errors And Guardrails

- Reject unknown IDs, malformed ledgers, duplicate active deferrals, and missing
  `--reason` before changing files.
- Refuse `plan` for IDs without active entries that selected or derived them.
- Validate `tasks.md` and requirement mappings before resolving derived tasks.
- A task-only defer never suppresses its mapped requirement gaps. Dry-run calls
  this out so an owner can explicitly defer the relevant requirement IDs when
  that is the intended scope decision.
- Ledger writes are atomic and validated before commit; commands display the
  spec path and changed entry IDs.

## Test Strategy

Unit tests cover ledger parsing/writing, all accepted ID families, narrow direct
task derivation, mixed-scope task behavior, `defer`/`plan` history, dry runs,
and invalid input atomicity. Integration tests cover fulfillment blocking,
delivery continuation, land readiness, and CLI output. All tests use local
fixtures and mocks; no provider or LLM invocation is required.
