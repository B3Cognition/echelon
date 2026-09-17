# Delivery Controller Phase 3 Implementation Plan

> Execute inline with the executing-plans and test-driven-development skills.
> Request independent read-only review before the phase handoff.

**Goal:** Recover interrupted controlled slices without skipped gates, duplicate
progress, stale approval reuse, or reset repair budgets.

**Architecture:** A controller-owned atomic journal records intent and validated
completion separately. The existing gate loop replays validated receipts to
derive its next step, rather than trusting a persisted next-step counter. Ralph
persists one operation identity until idempotent canonical progress application.

**Tech Stack:** Python, existing durable JSON and StateStore primitives, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-delivery-controller-ownership-design.md`

## Constraints and recovery policy

- Keep the trial flag off by default. No install, live delivery, provider change,
  merge, push, prose migration, or finalization cutover.
- Reuse only validated results bound to operation, task scope, exact candidate,
  spec inputs, and rendered role contracts. Diagnostics are never authority.
- Persist intent before provider entry; persist validated result before the
  next step. An unresolved intent blocks with a reconciliation-required reason;
  ordinary continue must not rerun it or approve diagnostic stdout. No automatic
  reconciliation or new approval/reset CLI is introduced in this checkpoint.
- Initial implementation plus two repairs remains the absolute per-operation
  cap across restarts. Derive attempts from intents, never a resettable counter.
- Serialize the journal with a nonblocking OS-held lock. Malformed, symlinked,
  missing expected journals and binding changes fail closed.
- Accept the exact controller-produced DONE transformation of the selected task
  only after all gates passed, to recover the task-file/state-write crash gap.
- Persist cumulative usage; Ralph accounts only the previously unaccounted delta.
  Unknown provider completion/usage must not become zero-cost retry authority.

## Task 1: durable runner receipts

Files: new `src/harness/delivery_slice_journal.py`, update
`src/harness/delivery_slice_runner.py`, new
`tests/unit/test_delivery_slice_recovery.py`.

- [x] Add crash-injection tests at durable boundaries using real files and the
  phase-2 scripted external provider. Assert exact remaining external steps:

```python
@pytest.mark.parametrize("completed,remaining", [
    (1, ["spec_guard", "code_reviewer", "test_guardian"]),
    (2, ["code_reviewer", "test_guardian"]),
    (3, ["test_guardian"]),
    (4, []),
])
def test_resume_after_validated_completion(completed, remaining):
    # Stop immediately after the selected validated receipt is durably saved.
    # Reconstruct the runner on the same journal and unchanged candidate.
    assert resumed_result.succeeded
    assert observed_external_steps == remaining
```

- [x] Run the recovery tests RED against phase 2. Add intent-before-provider,
  unrecorded-return, stale candidate/spec/scope/role, corrupt/symlinked journal,
  serialized execution, unchanged repair-limit, finite-budget, and diagnostic
  non-authority cases. Every failure must prevent new external work.
- [x] Implement `DeliverySliceJournal(root, operation_id)` as a context manager
  with atomic `save(data)` and strict `load()`; a missing expected journal is an
  error. Bind one journal per operation, derive the replay cursor from receipts.
  Keep runtime-only interruption injection in tests, not production hooks.
- [x] Integrate replay into the existing ordered runner: validate old receipts,
  reuse their original dispatch IDs, and dispatch only the first uncompleted
  step. Save failures, usage and candidate-after fingerprints; never load
  assignment/result diagnostic files as approvals.
- [x] Run new recovery plus phase-2 selector/runner suites GREEN.

## Task 2: Ralph recovery and idempotent application

Files: `src/harness/ralph.py`, `src/harness/coordinator.py`,
`src/harness/product_inventory.py`, `tests/unit/test_delivery_controller_integration.py`.

- [x] Add tests that reconstruct Ralph after result persistence and before
  progress application. A second call must reuse the pending operation, not
  select the next task or run implementation again. Reapplying progress keeps
  completed task count at one; a subsequent fresh build selects T-002.
- [x] Persist operation ID, repair identity and original feedback before dispatch;
  scope changes must invalidate recovery. Scope journals by strategy/run.
  Save the empty journal, then persist the operation pointer before provider
  intent. Preserve the original worktree and skip copying during recovery;
  independently bind published source inputs. Mark progress application in the
  same StateStore write as task counts, but retain the operation through the
  uncommitted Git-checkpoint gap. A subsequent outer iteration or explicit repair
  starts a new operation; ordinary cleanup retires the pointer after destruction.
- [x] Test and implement the exact DONE-transformation crash gap. Never normalize
  away acceptance-criteria changes or unrelated task progress edits.
- [x] Persist cumulative usage accounting in strategy state and return only new
  usage to callers. Test no double charge on receipt replay and no missing charge
  after a crash before the runner returns. Persist any finite operation ceiling.
  Controlled visual/review re-entry adds only usage above its pre-run baseline.
  Product hashing excludes the selected spec directory only on this path; exact
  input/protected hashes still bind its contents and its recorded DONE transform.
- [x] Run build/feedback, modes/banzai, resume/continue, and polyrepo regressions.

## Task 3: review and checkpoint

- [x] Request independent read-only review; reproduce important findings RED and
  fix them. Update design and changelog with actual phase-3 behavior and limits.
- [x] Run the full selected regression set (phase-2's 1,008 tests plus recovery
  additions), durable JSON/StateStore tests and whitespace checks. Record exact
  results and distinguish scripted external execution from a live trial.
- [x] Commit a separate phase-3 checkpoint on the existing isolated branch.

## Verification commands

```bash
python -m pytest -q tests/unit/test_delivery_slice_recovery.py \
  tests/unit/test_delivery_slice.py tests/unit/test_delivery_slice_runner.py \
  tests/unit/test_delivery_controller_integration.py --tb=short
```

## Review record and remaining limits

Final combined regression on 2026-09-11: **1,079 passed in 97.19 seconds**,
including the prior phase's selected suites plus recovery, product inventory,
durable JSON, StateStore logic, atomicity, and lockfile tests. Whitespace checks
passed. This is a selected regression gate, not a full-repository test claim.

All important review findings were reproduced with failing consumer tests before
fixing: durable tightened ceilings, destructive worktree recreation on full-loop
resume, the progress-state/Git-checkpoint gap, and duplicated downstream usage.
Additional regressions cover unknown usage after provider exceptions, mutation
during receipt replay, changed published inputs before and after progress, and
disabling the feature with pending work. Final independent review found no
remaining blocking issues for the offline opt-in checkpoint.

This is not an installed or live-provider delivery trial. Matching receipts can
resume; unknown completion or changed reports/specs require reconciliation.
Controller-generated report changes after later verification and interruption
after committed-worktree cleanup can therefore block rather than auto-resume.
Do not remove journals to bypass those checks. Finalization/output ownership and
the production-default cutover remain phase 4.
