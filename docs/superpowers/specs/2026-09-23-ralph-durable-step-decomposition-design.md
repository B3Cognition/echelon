# Ralph Durable-Step Decomposition Design

## Purpose

Finish milestone S4 by making the supported single Delivery run understandable
as a sequence of explicit durable steps. The single-controller cutover is
complete and verified; this design addresses the remaining orchestration
complexity without changing Delivery behavior or its persisted state contract.

The priority is controlled simplification. Extract existing checkpoint
boundaries one at a time, characterize each boundary before moving it, and keep
the repository green after every extraction.

## Current Evidence

The single-run cutover removed the abandoned strategy dimension and established
one `DeliveryController`, one `DeliveryResult`, and one run-scoped
`delivery.json`. Its repository gate passed 9,830 tests with zero failures.

The remaining orchestration is concentrated in two methods:

- `DeliveryController._run_delivery`: approximately 1,028 lines;
- `RalphController._run_loop_inner`: approximately 992 lines.

The durable boundaries are already visible in production state and tests:

- `delivery_slice_operation` journals a controlled implementation slice;
- `checkpoint_commits` records accepted progress;
- registered worktree and `verified_commit` bind a verified candidate;
- `pending_review_reentry` records a bounded downstream repair;
- `verified_publish_checkpoint` makes verified publication resumable;
- phase-qualified blocked/interrupted state identifies the exact resume point.

The problem is therefore not a missing workflow abstraction. The problem is
that the proven steps are embedded in large control methods with local state,
early returns, and effect ordering that are difficult to review independently.

## Decision

Extract checkpoint-led methods in place before considering file-level moves.

`DeliveryController._run_delivery` remains the top-level owner of one run.
`RalphController._run_loop_inner` remains the implementation-phase loop. Each
becomes a short dispatcher over explicit methods whose inputs and outcomes are
typed. The extraction preserves the current order of state transitions and
external effects.

No generic workflow engine, new state-machine framework, or phase registry is
introduced. Stable methods may be moved to focused modules in a later plan only
if the completed extraction demonstrates a clear independent responsibility.
File size alone is not sufficient reason to add module boundaries during this
plan.

## Fixed State Contract

This decomposition does not change the `delivery.json` schema. It preserves:

- state and lock filenames;
- all status values and legal transitions;
- phase checkpoint fields and resume mapping;
- `delivery_slice_operation` shape and receipt validation;
- `checkpoint_commits` records and task-progress accounting;
- registered-worktree and verified-candidate provenance;
- `pending_review_reentry` shape and consumption rules;
- `verified_publish_checkpoint` shape and recovery rules;
- iteration, token, convergence, escalation, and terminal accounting.

There is no migration step and no compatibility adapter. A state file written
before this refactor must resume identically after it.

## Control Model

The control flow remains synchronous and controller-owned:

```text
DeliveryController.run(intent)
        |
        v
open or resume delivery state
        |
        v
dispatch current Delivery phase
        |
        +--> Ralph implementation loop
        |       |
        |       +--> recover pending slice
        |       +--> prepare candidate worktree
        |       +--> execute one controlled slice
        |       +--> commit accepted progress
        |       +--> verify candidate
        |       `--> continue, block, or return verified
        |
        +--> visual checkpoint
        +--> review / bounded re-entry
        +--> verified publication
        `--> terminal finalization
```

Providers return evidence and proposed task progress. They do not mutate
controller state. Only the Python controller writes durable transitions and
operation journals.

## Typed Outcomes

Use narrow, domain-specific result types rather than dictionaries or a generic
workflow result.

### Implementation iteration outcome

An internal Ralph outcome represents exactly one outer-loop decision:

- `continue_loop`: accepted progress was checkpointed and another iteration is
  required;
- `verified`: candidate verification succeeded and the existing
  `ImplementationResult` can be returned;
- `terminal`: the existing finalized `ImplementationResult` must be returned;
- `retry_inner`: verification feedback remains inside the current bounded
  repair path and does not advance the outer loop.

The outcome carries only values currently maintained as loop locals: worktree,
branch, iteration counters, token usage, last verification, PR URL, and whether
the worktree must be preserved. It does not duplicate durable state.

### Delivery phase outcome

Delivery phase methods continue returning existing domain results:

- implementation returns `ImplementationResult`;
- visual and review return their existing result types;
- finalization returns `DeliveryResult`.

No one-entry result map or strategy-qualified wrapper is reintroduced.

## Extraction Boundaries

### 1. Open or resume the run

Extract Delivery setup and resume classification from `_run_delivery`:

- resolve immutable workspace/source/target context;
- acquire the single state lock;
- migrate only the current state version using the existing migration helper;
- return an already-terminal result without dispatching providers;
- validate enabled phase and phase-qualified resume checkpoint;
- restore registered worktree and verified candidate provenance.

The extracted method returns a typed run context plus the current phase. It
does not run a phase or write a terminal result.

### 2. Recover a pending slice operation

Extract Ralph reconciliation of `delivery_slice_operation` before any new work
is selected:

- validate that the persisted worktree path is absolute, non-symlinked, and a
  directory;
- reuse the persisted operation and candidate when safe;
- block with `delivery_reconciliation_required` when reconciliation cannot be
  proven;
- never dispatch the provider before recovery is complete.

This boundary must remain idempotent when invoked repeatedly against unchanged
state.

### 3. Prepare one implementation iteration

Extract worktree selection and preparation:

- recover an existing operation worktree;
- consume a registered downstream-reentry worktree once;
- otherwise create the iteration worktree using the current build ID and
  feature-branch rules;
- synchronize Phase A inputs;
- return either a prepared iteration context or the existing blocked result.

Worktree cleanup remains owned by the outer loop's `finally` path so extraction
cannot accidentally delete a candidate needed for recovery.

### 4. Execute one controlled slice

Keep `_exec_controlled_slice` as the effect boundary and extract its surrounding
outer-loop orchestration:

- clear stale build status;
- snapshot containment and HEAD;
- build the exact existing prompt;
- dispatch once;
- validate source/harness containment;
- account for known tokens;
- validate provider-reported task IDs;
- append the existing iteration log.

The method returns a typed slice outcome. It does not mark tasks complete,
commit progress, or begin candidate verification.

### 5. Commit accepted progress

Extract the progress checkpoint step around existing helpers:

- apply accepted task IDs to canonical `tasks.md`;
- reject mismatched provider and canonical completion sets;
- commit only meaningful product progress under existing rules;
- bind operation accounting and checkpoint receipt idempotently;
- preserve verification-deferred checkpoint behavior;
- clear `delivery_slice_operation` only at the same proven completion point as
  today.

This step retains `_checkpoint_progress_commit` as the Git/evidence primitive;
the extraction makes its invocation and state transition explicit.

### 6. Verify the candidate checkpoint

Extract the outer verification decision:

- execute the configured verification path;
- apply task-progress, fulfillment, documentation, runnability, coverage, and
  evidence gates in their current order;
- bind registered worktree and verified commit;
- return an existing verified, blocked, or repair outcome;
- never publish the candidate before downstream visual/review gates complete.

The extraction must not combine or reorder gates. Existing gate helpers remain
unchanged unless a signature needs a typed context instead of many loop locals.

### 7. Process bounded review re-entry

Extract Delivery handling of `pending_review_reentry`:

- validate the persisted payload before provider dispatch;
- resume effects-only completion without rerunning implementation;
- when repair is required, transition to implementation exactly once with the
  existing task and evidence context;
- clear the checkpoint only after the repaired candidate is verified and the
  review decision is accepted;
- preserve re-entry ceilings and escalation behavior.

Review re-entry remains a Delivery phase decision, not a second implementation
workflow.

### 8. Publish the verified candidate

Extract the call boundary around existing verified-publication recovery:

- validate `verified_publish_checkpoint` against worktree, commit, evidence,
  and branch;
- resume only the incomplete push/merge/PR effect;
- record the same recovery metadata;
- block with existing publication reasons on failure;
- clear the checkpoint only after publication succeeds.

`RalphController.resume_verified_publication` and its existing primitives are
preserved first; the caller becomes explicit before any later movement between
classes is considered.

### 9. Finalize the run

Keep `_finalize_delivery` as the single terminal Delivery boundary and reduce
its caller to one explicit step:

- validate verified provenance and fulfillment metadata;
- publish deferred target candidates only after downstream gates;
- persist the terminal transition once;
- return one `DeliveryResult`;
- release the run lock in the existing outer `finally` block.

No intermediate extraction may create a second terminal writer.

## Error and Interruption Semantics

Every extracted step must preserve current fail-closed behavior:

- malformed or missing durable context blocks at the owning phase;
- interruption preserves the exact phase and resumable candidate;
- provider and infrastructure failures keep their existing termination reason;
- invalid pending operations never fall through to fresh provider work;
- publication failures preserve the verified candidate and publication
  checkpoint;
- cleanup never removes a worktree referenced by a pending durable operation.

Exceptions already converted into controlled blocked results remain converted
at the same boundary. Programming errors are not broadly swallowed by new
catch-all handlers.

## Implementation Order

The extraction order follows the durable state dependency chain:

1. characterize and extract pending-slice recovery;
2. characterize and extract iteration/worktree preparation;
3. characterize and extract one controlled slice dispatch;
4. characterize and extract progress checkpointing;
5. characterize and extract candidate verification;
6. flatten `RalphController._run_loop_inner` around the extracted steps;
7. characterize and extract Delivery open/resume classification;
8. characterize and extract review re-entry;
9. characterize and extract verified publication dispatch;
10. flatten `DeliveryController._run_delivery` and retain one finalization path;
11. update current architecture documentation and run repository verification.

Each item is independently committed and reviewed. A later extraction does not
begin until the focused recovery and orchestration tests for the prior boundary
are green.

## Test Strategy

Tests characterize behavior before implementation changes.

For each extraction:

1. add or tighten a test at the durable boundary;
2. run it red only when it asserts the new callable seam;
3. move the minimum existing behavior behind that seam;
4. rerun the boundary test and its adjacent recovery partition;
5. commit the independently reviewable extraction.

The focused partitions include:

- `tests/unit/test_ralph_inner.py`;
- `tests/unit/test_ralph_outer.py`;
- `tests/unit/test_delivery_controller.py`;
- `tests/unit/test_delivery_controller_review_reentry.py`;
- `tests/unit/test_run_skill_checkpoint_recovery.py`;
- `tests/unit/test_harness_recovery.py`;
- `tests/unit/test_delivery_finalization.py`;
- `tests/integration/test_controlled_review_reentry.py`;
- `tests/integration/test_polyrepo_delivery_convergence.py`;
- `tests/integration/test_ralph_controller.py`.

Acceptance requires:

- the fixed state-contract tests remain unchanged and green;
- interruption at each durable checkpoint resumes without skipped or duplicate
  effects;
- pending operations prevent fresh provider dispatch;
- verified candidates are not published before downstream gates;
- the two top-level orchestration methods read as dispatchers over named steps;
- focused Delivery/Ralph/recovery suites pass;
- the repository merge-verification gate passes and is recorded in
  `docs/simplification-control.md`.

## Non-Goals

This work does not:

- change Delivery CLI behavior;
- change state keys, versions, or migration policy;
- change retry, token, convergence, or escalation policy;
- merge visual, review, or fulfillment gates;
- introduce asynchronous execution or parallel phase dispatch;
- move state mutation into providers or agent output;
- create a reusable workflow framework;
- split modules solely to reduce line counts;
- consolidate historical RE protocols or Phase A orchestration.

## Alternatives Rejected

### New workflow or state-machine framework

A framework would require translating proven state and transition semantics into
a second abstraction before the current boundaries are independently testable.
That increases behavioral risk and conflicts with the S4 quick-simplification
goal.

### Immediate module-per-phase split

Moving large blocks before their inputs and outcomes are explicit would convert
local-variable coupling into import and constructor coupling. Method extraction
first provides a safer seam and lets later module boundaries follow evidence.

### Rewrite the Ralph loop

A rewrite could make the happy path smaller, but it would likely lose recovery,
containment, evidence, and publication edge cases accumulated in the current
tests. This design moves proven behavior instead of recreating it.

## Completion Boundary

This design is complete when the two large orchestration methods are reduced to
clear dispatch loops over the named durable steps, all existing state and
recovery contracts remain intact, focused verification is green, and the
repository gate is recorded. S4 may then be marked complete; S5 does not begin
before that evidence exists.
