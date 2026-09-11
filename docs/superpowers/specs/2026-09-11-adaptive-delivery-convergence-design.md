# Adaptive Delivery Convergence Design

**Date:** 2026-09-11

**Status:** Approved

## Problem

Delivery currently treats `max_outer=5` as a ceiling on outer-loop indexes. That
counter does not distinguish a completed product-repair slice from a provider
session limit, an unavailable verification sandbox, or another interruption
that produces no authoritative product observation. The existing outer
no-progress guard is also based on whether any file changed, so report churn can
reset it while verified product progress goes unnoticed.

Delivery 011 exposed both failures. Two of its five outer slots ended at
provider boundaries, while the final slot produced a useful repair and then
stopped solely because its index reached the ceiling.

## Goals

- Continue autonomous delivery while authoritative evidence improves.
- Stop repeated, evidence-equivalent repairs before they waste the full budget.
- Keep an absolute owner-configurable safety ceiling and token budget.
- Do not charge provider, sandbox, or verification-infrastructure interruptions
  as product-repair attempts.
- Persist convergence accounting across `delivery continue` and process restarts.
- Apply identical convergence semantics in banzai, semi, and guided modes;
  guided mode retains its existing phase-boundary pauses.
- Make the decision and its evidence visible in delivery state, status output,
  summaries, and telemetry.

## Non-goals

- Automatically rewriting requirements or weakening verification criteria.
- Treating provider assertions or arbitrary file changes as progress.
- Replacing token, time, cancellation, containment, or security stops.
- Rewriting published branch history to recover a prior candidate.

## Policy

Delivery uses a persisted **convergence lease**. `max_outer` becomes the maximum
number of chargeable outer observations, rather than a maximum raw loop index.
The default safety ceiling increases from 5 to 12. Explicit CLI and configuration
overrides remain authoritative.

The lease has these defaults:

- hard ceiling: 12 meaningful outer observations;
- minimum meaningful observations before stall termination: 3;
- stall patience: 2 consecutive non-improving comparable observations;
- same-root-cause inner behavior: retain the existing three-observation
  threshold, which permits at most two repair invocations after the initial
  observation;
- token and cancellation limits: unchanged and always authoritative.

An outer attempt is chargeable only after authoritative verification produces a
comparable product result. Provider exits, provider session limits, host-tool
permission failures, missing verification infrastructure, sandbox outages,
guided pauses, cancellation, and publication failures do not advance the
meaningful-attempt counter.

## Authoritative progress snapshot

After a failed outer repair slice, Ralph constructs a deterministic snapshot
from controller-owned evidence:

- completed and total canonical task counts;
- blocking fulfillment requirement IDs and their statuses from structured
  `FailureEntry.details.gaps`;
- normalized failure identities based on failure category, stable failure ID,
  and structured test-case IDs when present;
- the earliest failing verification gate;
- the candidate product-evidence fingerprint;
- the latest existing checkpoint commit, retained as provenance.

The fingerprint proves that the candidate changed, but never establishes
progress by itself.

Status severity is ordered as `MISSING/DEVIATED > UNVERIFIED > PARTIAL > absent`.
A snapshot improves when at least one of these controller-observed facts moves
forward without being outweighed by a higher-priority regression:

1. canonical completed-task count increases;
2. verification advances to a later gate;
3. weighted fulfillment debt decreases;
4. the set of stable blocking failure identities shrinks.

The comparison is deliberately lexicographic. Task completion outranks all
other evidence. Verification-gate advancement comes next because reaching a
later gate may expose fulfillment debt that could not be observed earlier;
treating that newly visible debt as a regression would stop genuine progress.
Fulfillment debt then outranks generic failure-count changes, preventing a large
noisy test suite from masking requirement progress. A changed product
fingerprint with equivalent evidence is classified as `stalled`, not improved.

The first comparable snapshot establishes the baseline. Later snapshots are
classified as `improved`, `stalled`, or `regressed`. Both `stalled` and
`regressed` consume patience; `improved` resets patience to zero and replaces the
persisted high-water snapshot.

## High-water candidate behavior

The lease records the best authoritative snapshot, its product fingerprint, and
its checkpoint commit. A regression does not cause a history rewrite or a hard
reset of a source-owned feature branch. Instead, Ralph supplies the high-water
evidence to the next repair prompt and grants one recovery attempt within the
normal patience window. If that attempt does not recover or improve on the
high-water mark, delivery stops with `convergence_stalled`.

This preserves the recoverable candidate without risking automatic reversal of
canonical task/spec artifacts. A future isolated-candidate branch mechanism may
add automatic tree restoration, but it is not safe to introduce as part of this
controller-policy change.

## Loop and resume semantics

`outer_iter` remains a monotonically increasing execution ordinal used for logs,
worktree names, and prompts. `convergence_lease.meaningful_attempts` controls the
hard ceiling. Therefore an infrastructure interruption may advance execution
provenance while leaving the repair allowance unchanged.

The lease is stored in strategy state and survives resume. Continuing a run does
not erase its high-water mark or stall history. An explicit reset starts a new
lease. Increasing `max_outer` extends the same lease; it does not make prior
stalled attempts disappear.

If `convergence_stalled` is reached:

- banzai stops autonomously with the evidence delta and best checkpoint;
- semi stops with the same deterministic diagnosis and may accept owner guidance;
- guided retains its existing boundary behavior and uses the same accounting
  when verification is allowed to proceed.

## State contract

Strategy state gains:

```json
{
  "convergence_lease": {
    "schema_version": 1,
    "meaningful_attempts": 3,
    "stalled_attempts": 0,
    "infrastructure_attempts": 2,
    "last_outcome": "improved",
    "last_reason": "fulfillment debt decreased from 73 to 21",
    "last_snapshot": {},
    "best_snapshot": {},
    "best_checkpoint_commit": "10d0fc3de2ae...",
    "updated_at": "..."
  }
}
```

Legacy states without this field are reconstructed from the latest comparable
verification observation when possible and otherwise start with an empty lease.
No existing state field changes meaning except that the controller no longer
uses raw `outer_iter` as the `max_outer` budget counter.

## Reporting and telemetry

`echelon delivery status` and terminal summaries show:

- meaningful attempts / hard ceiling;
- stall patience used / available;
- last convergence outcome and reason;
- infrastructure attempts excluded from the budget;
- best checkpoint when available.

Each observation emits a content-free telemetry event containing counts,
classification, reason code, and fingerprint hashes. It must not duplicate raw
provider output or requirement text.

## Compatibility and rollout

- `--max-outer` remains supported and now names the meaningful-attempt ceiling.
- `--max-inner` and explicit non-default values remain supported unchanged.
- Default `max_inner` remains 3 to avoid reducing repairs for genuinely changing
  root causes.
- Existing hard blockers continue to return immediately.
- Existing `same_failure_repeat` remains an inner-loop optimization; the lease is
  the cross-outer policy.
- The implementation is introduced behind deterministic state helpers and is
  exercised against all three modes plus legacy state and resume fixtures.

## Acceptance criteria

1. The default intent and initialized state use `max_outer=12`.
2. Two provider/infrastructure interruptions followed by three comparable outer
   observations leave the lease at three meaningful attempts, not five.
3. A verified improvement at the former fifth raw outer index continues delivery
   when the meaningful hard ceiling is not exhausted.
4. Two consecutive non-improving observations after at least three meaningful
   observations stop with `convergence_stalled`.
5. Task, fulfillment, stable-failure, and gate improvements reset patience.
6. File or fingerprint changes without evidence improvement do not reset patience.
7. Resume preserves the lease and a reset creates a fresh lease.
8. Banzai, semi, and guided retain their established pause/escalation contracts.
9. Status, summary, and telemetry expose the convergence decision without raw
   failure content.
