# Published spec runnability plan amendment

Status: proposed design for owner review. No implementation is authorized by this document.

## Outcome and scope

Echelon must be able to correct a published Spec that omitted a task owning a
stack-required `.echelon/runnability.yml`, without hand-editing the product or
reimplementing unrelated tasks. The correction must be a normal, reusable
Echelon operation for any supported target and required runnability stack, not
a rule keyed to the rugby demo, a particular task ID, or an old run ID.

Normal new Spec runs do not use this amendment. Their existing PLAN instruction
and capability-aware readiness gate require exactly one task to declare the
target's runnability contract before publication. The amendment path is opt-in
only after a published plan fails that same ownership invariant. It does not
relax the invariant or make an absent candidate contract count as verified.

This design covers one typed planning omission: a required runnability
contract has no canonical task owner. It does not become a general spec repair
engine, migrate old Phase A state, reconcile unknown Delivery dispatches, or
change browser, semantic visual, fulfillment, or review acceptance rules.

## Existing boundaries

- `phase_a_readiness.py` already detects missing or duplicate contract owners
  from canonical task `Files` declarations, scoped to each target.
- `delivery_slice.py` already routes a missing, invalid, or disabled candidate
  contract to one accepted declared owner for a controlled four-role repair.
  It cannot select an owner when the published plan declares none.
- `spec_amendment.py` can prepare an isolated control-repository worktree from
  a pinned spec branch and can compare-and-swap a promoted commit. It currently
  prepares a pre-build amendment; it does not author or promote this correction.
  Its ref update alone does not synchronize an active working checkout.
- A built Spec's working `tasks.md` may contain uncommitted Delivery progress.
  The preserved acceptance workspace has exactly that shape on its Spec branch.
  Its working `spec.md` also has a lifecycle-status edit and fulfillment reports
  exist beside it. The amendment must preserve those bytes and never treat the
  published branch alone as the current workspace state.
- `spec reopen` consumes verified fulfillment gaps. A stale fulfillment report
  is not authority to invent a runnability task.
- `checkpoint_input_hash` includes task definitions. Appending a task changes
  that hash even if every older task is unchanged. Fresh Delivery currently
  inherits checkpoint progress only for an exact hash and candidate ancestry.

The last point prevents a plain `tasks.md` append followed by `delivery run` from
being a safe recovery recipe. The amendment and any carry-forward must be
explicit and independently validated.

## Native amendment flow

1. **Preview.** A thin Spec command delegates to a typed harness operation. It
   resolves authoritative stack selection, published spec branch, declared
   targets, and current readiness. It separates published task definitions
   from recognized task-progress edits and spec lifecycle-only edits in the
   working checkout. It reports each target missing a contract owner, the
   proposed new task ID, and whether
   a prior candidate appears eligible for carry-forward. Unrecognized working
   edits block the proposal. No provider runs, files change, or run state is
   allocated during preview.
2. **Prepare.** Reuse the existing isolated amendment worktree and per-spec
   mutation lock. Pin the published spec commit and its checkpoint-input hash.
   Require no active Spec step, Delivery dispatch, publication transaction, or
   spec mutation for this spec. Preserve the old published branch and candidate.
3. **Plan.** A deterministic harness planner appends one canonical PENDING task
   per missing target. It assigns the next unused task ID, the exact
   target-qualified `.echelon/runnability.yml` in `Files`, a dependency on the
   target's preceding work, and acceptance language requiring a real composed
   journey under the selected stack. The Delivery implementer, not the planner,
   chooses project-specific install/start/readiness/browser/stop commands.
   The planner updates task counts and an amendment record, but does not alter
   old task blocks, coverage obligations, product code, or prior receipts.
4. **Validate and promote.** Validate canonical tasks, target scope, unique
   ownership, structural and capability-aware readiness, and an allowlisted
   diff against the pinned baseline. A durable amendment transaction uses the
   existing publication journal to install the appended task into the active
   checkout while retaining its exact task-progress overlay, then uses the
   existing compare-and-swap branch update and synchronizes the index to the
   promoted commit. Recovery settles or rolls back each exact owned effect;
   it never overwrites subsequent user edits or unrelated status/reports. If
   the branch, working file, stack contract, targets, or proposed diff changed,
   stop and require a new
   preview. Do not leave a moved branch ref with a stale active checkout.
5. **Deliver.** Start a new Delivery run against the amended published spec.
   Native candidate selection may retain the previous source commit only after
   the carry-forward check below. The new task is selected as pending and uses
   the ordinary implementer, spec guard, code reviewer, test guardian, and
   final verification gates. The old run remains immutable diagnostic evidence.

Extend the existing `spec amend` surface with a typed `--runnability-owner`
mode. With `--dry-run` it previews; without that flag it prepares the isolated
proposal. `echelon spec amend promote <amendment-id>` promotes after inspection.
These commands only forward requests to the harness; no CLI policy, second
task planner, new agent, or parallel repair controller is added. Preview and
promotion are separate so the owner can inspect the proposed task and
carry-forward decision.

## Carry-forward contract

The amendment records the old and new published spec commits, old and new
checkpoint-input hashes, target identities, unchanged older task-definition
hashes, the preimage and projected working-file hashes, new task IDs, selected
candidate commit, and source checkpoint references. Progress-only differences
between the published baseline and working `tasks.md` are normalized by the
existing task-progress rules; the working `spec.md` status transition is
validated separately and preserved byte-for-byte. Arbitrary edits are not.
This record is evidence for a *new* Delivery run; it never rewrites a saved
operation or claims that an old receipt was issued under the new plan.

Before inheriting any accepted task progress, Delivery rechecks that:

- The amendment is the promoted commit, contains only the allowed append and
  count/status bookkeeping, leaves every older task definition unchanged, and
  has fully settled its workspace publication and Git index effects.
- Each carried task has an accepted checkpoint on the selected candidate's
  ancestry, or is already part of the target's landed baseline under the
  unchanged old task definition. A checked box or provider result alone is not
  proof. An unproven old task is not silently marked accepted; it requires the
  existing task/review path or blocks if that path cannot represent it.
- The selected candidate is clean and unchanged at admission. No pending or
  unknown-dispatch operation is skipped; any such operation must first recover
  under its original sealed inputs.
- Current stack selection and readiness still match the promoted plan. Old
  verification, coverage, and visual receipts are not replayed as new final
  acceptance merely because source files are unchanged.

If these checks pass, only proven old task progress carries forward; the new
task starts PENDING. Delivery then runs fresh ordinary verification, structured
observation, runnability, fulfillment, and visual/review gates as applicable.
If a check fails, the command explains the exact mismatch and performs no
provider dispatch or candidate mutation. There is no last-task fallback and no
automatic reset to the default branch.

## Verification and rollout

Implement in small, independently tested increments:

1. Pure planner and preview: missing-owner, existing-owner, duplicate-owner,
   multi-target, invalid stack, malformed task, and no-op cases. Compare actual
   proposed task bytes and verify no writes or provider calls in preview.
2. Isolated amendment and promotion: real temporary Git repositories, strict
   diff validation, concurrent branch movement, an active dirty checkout with
   legitimate progress, interrupted file/ref/index transitions, and idempotent
   retry. Confirm unrelated workspace edits, source candidate, and Delivery
   journals remain byte-identical; reject an unrecognized task edit.
3. Carry-forward admission: actual checkpoint ancestry and task-definition
   fixtures for accepted, unproven, changed, and pending/unknown-dispatch cases.
   A changed global hash alone must neither discard proven work nor grant new
   authority. No old verification receipt may satisfy the new final gate.
4. Disposable native Spec amendment to Delivery: confirm the new task alone is
   selected when all older tasks are proven, its four reviews run, and fresh
   final evidence—not a snapshot-update proposal—decides acceptance. Stop at
   the first reproducible harness failure and fix it before another run.

Use failing regression tests before each code increment, focused functional
tests after each, then repository/dry-run gates and independent review. The
preserved rugby candidate is used only after the disposable path proves the
flow and its exact old-task carry-forward eligibility is reported. Do not
promise that all twelve tasks can be retained until that eligibility check
passes. No generated demo code, screenshot, baseline, spec artifact, or live
Delivery state is hand-edited for this design.

## Alternatives rejected

- **Annotate a completed task in place:** changes the contract that its
  earlier review accepted and obscures whether it was truly re-reviewed.
- **Append a task directly to the published `tasks.md`:** bypasses Spec
  stewardship, branch compare-and-swap, and checkpoint-input lineage.
- **Start a fresh Spec and reimplement the product:** avoids lineage work but
  discards a potentially reusable candidate and does not provide a normal
  correction path for future published plans.
- **Broaden `spec reopen` to consume the old fulfillment report:** that report
  predates current observer selection and does not establish this planning gap.
