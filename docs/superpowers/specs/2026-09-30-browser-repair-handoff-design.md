# Delivery browser-failure repair handoff

Status: design approved by user instruction to proceed; implementation not started.

Implementation plan: [browser repair handoff](../plans/2026-09-30-browser-repair-handoff.md).

Parent milestone: STAB-1. S6 and S7 remain parked.

## Outcome and constraints

When browser capture for one task finds a failure owned by another accepted
task, Echelon must repair the actual owner and return to the unfinished task.
It must not ask an out-of-scope implementer to keep repairing that failure.

Use the existing Ralph controller, controlled task runner, ownership selector,
and journal/evidence conventions. No new agent, general workflow engine,
recursive repair stack, manual demo changes, gate exemptions, counter resets,
or automatic increases to configured limits.

Success means a real owner repair, fresh browser evidence, and normal reviews
of the resulting candidate. A passing handoff is not final Delivery acceptance.

## Evidence and current boundary

- `20e88b0d` completed structured browser-failure retention. Version 3 browser
  receipts preserve failure identities and diagnostics; version 2 receipts are
  readable without rewriting them, with structured failures explicitly absent.
- An isolated Docker capture reproduced `CT-NET-001`. Reading its new receipt
  and using `select_delivery_repair_task` selected T-012, not T-011. The candidate
  fingerprint and live Delivery state were unchanged.
- The stopped run remains blocked at `delivery_browser_evidence_request_repeated`.
  Its unfinished T-011 operation contains two completed implementer requests;
  its retained browser receipt is version 2. There is no unknown dispatch to
  reconcile. Existing unknown/provider-failure supersession is not applicable.
- A delivery journal binds every dispatch to one task, input set, and candidate
  chain. Changing its task ID or accepting an unexplained candidate change would
  defeat those checks.
- Normal verification sets a build-directory environment variable that the
  browser-capture command does not set. Therefore passing normal verification
  alone does not prove that this browser failure was repaired.

## Decision

Use one explicit, durable handoff between two ordinary task operations, followed
by a linked continuation of the original task. Keep at most one foreign owner
active at a time. The handoff does not become a general task queue.

Rejected alternatives:

- Reassign the existing operation: breaks task and candidate bindings.
- Let T-011 finish and rely only on normal verification: can miss this failure.
- Nest arbitrary repairs: adds recursion and unclear ownership/budget behavior.

## Ownership and authority

The slice runner authenticates the capture receipt and returns a typed handoff
request, not `DONE`, not an agent-authored routing instruction, and not a
success-shaped blocker. It grants no task progress.

Ralph validates that request against the retained journal and current candidate,
then uses the existing ownership selector. Eligibility requires all failures to
have unambiguous identities resolving to one different, accepted task inside
the allowed target scope. Mixed owners, unidentified failures, invalid/stale
receipts, and unaccepted owners do not authorize a handoff. Same-owner failures
stay in the existing task repair flow.

`delivery_slice_operation` remains the single persisted active-operation
authority. Its handoff metadata identifies the paused operation and evidence,
the selected repair operation, and the return continuation. Referenced journals
are immutable evidence, not independently runnable pending jobs. CLI and agents
do not interpret or mutate this metadata.

## Required transitions

| Boundary | Durable evidence and action | Condition to advance |
| --- | --- | --- |
| Detect | Bind the failed browser receipt to the originating dispatch, task, candidate, inputs, and scope. Record the selected foreign owner. | Receipt and ownership validation succeed. |
| Hand off | Preserve the source operation snapshot and journal digest. Prepare the repair operation with a deterministic identity, then atomically select it before any provider dispatch. | The persisted active operation authorizes exactly that repair. |
| Repair | Run the selected owner through the existing implementer and independent reviews, with the actual browser failure as feedback. | Required reviews pass for the current candidate. |
| Recheck | Rerun the failing browser-capture command in the normal isolated runtime, without substituting the ordinary verify script or injecting a workaround environment. Retain the new receipt. | The browser failure is resolved, not merely absent from a different verification path. |
| Return | Prepare a deterministic continuation of the original task linked to the source journal, repair receipts, and post-repair candidate. Select it durably. | The candidate transition and remaining budgets authenticate. |
| Finish source task | Obtain current browser proposals, re-enter the original implementer, and perform its normal independent reviews. | No acceptance or visual evidence from the pre-repair candidate is reused as current approval. |

The recheck remains inside the handoff until resolved. A repeated failure owned
by the selected repair task feeds its next bounded repair round. That round
must record the controller-observed rejection before another implementer
dispatch; passing role reviews alone cannot close the handoff. It does not
create a fresh allowance. A failure needing a third task stops with the retained
evidence and a clear ownership blocker rather than opening a nested handoff.
Owner review completion alone does not retire the repair or grant new progress;
the recheck must pass first. Owner acceptance never grants progress to the source
task.

The returned task obtains its own fresh, task-bound capture even if the repair
recheck used the same unchanged candidate. The owner's recheck proves repair;
its images are not silently offered as the source task's proposals. If the
candidate changes afterward, fresh capture is required again. Receipt identities
are never relabeled to make evidence fit a different task.

## Journal and replay contract

Extend the journal contract only for explicit controller-owned continuation and
verification-rejection checkpoints. Keep provider results assignment-bound and
unchanged. A controller checkpoint is not a fabricated provider result.

Original dispatch records and receipts remain unchanged. A new continuation
links to the old journal by digest and explains the candidate change through
the repair journal. It starts with the original task's remaining repair/capture
allowances, not a fresh operation's defaults. Old passing reviews remain history;
the returned candidate must earn its own reviews.

Use deterministic operation/checkpoint identities derived from the triggering
operation and receipt, so replay selects the same work. Prepare evidence before
atomically selecting the active operation; never dispatch while its selection
is uncommitted. Unselected preparation artifacts are inert and can be validated
and reused on retry.

On restart, validate the active operation, its referenced predecessors, spec
and scope bindings, and expected candidate before performing any effect. An
interruption during owner work resumes that owner; one during return resumes
the return. Existing unknown-dispatch rules still apply to genuinely unknown
provider outcomes. They are not used to erase completed work.

Capture intents consume their allowance durably before execution. A completed
receipt is reused after a crash. If capture completion cannot be proven, retry
requires remaining capture allowance; do not silently refund the earlier attempt.

## Accounting and limits

- Preserve the run's token, inner, and outer counters. A handoff within pending
  work is not a new outer iteration or an excuse to restart an exhausted loop.
- Charge each provider receipt once using the existing accounted-token delta
  convention. Replaying predecessors must neither recharge nor omit their usage.
- The original task retains consumed review rounds and capture requests across
  its continuation. The selected repair task also retains its consumed rounds
  across failed post-repair browser checks; each new repair consumes the next
  round rather than creating a new five-round allowance.
- Available tokens remain bounded by both the run budget and the outstanding
  operation allowance. Owner repair spending reduces what remains for the
  original task. Unknown usage retains existing fail-closed behavior.
- Persisted continuation accounting must agree with the retained journal
  lineage. It is not a second mutable budget authority.
- Exhaustion returns an honest, resumable blocker. This change does not raise
  limits or add a new CLI budget policy.

## The stopped run and older evidence

Do not migrate or rewrite its version 2 browser receipt, infer case IDs from
diagnostic text, or attach the separate diagnostic probe as live-run authority.

For a completed, unchanged browser-request boundary with no structured failure
data, the controller may record a fresh capture intent and obtain a new bound
receipt using the existing remaining capture allowance. This also covers the
current completed duplicate request; it is not an unknown-dispatch retry.
The retained requests remain counted. Missing allowance, changed candidate,
unknown provider work, or inconsistent bindings block this refresh.

Older journals remain validated under their original schema. Any new recovery
checkpoint belongs to an explicitly linked current continuation, not an in-place
upgrade of old evidence. Once a structured receipt exists, normal eligibility
rules decide whether a handoff is justified.

## Implementation boundaries

- `delivery_slice_runner.py`: authenticate capture failures, expose the typed
  request, and handle explicit continuation/recheck checkpoints.
- `delivery_slice_journal.py`: validate those checkpoints, their sequence,
  lineage, candidate transitions, and carried allowances.
- `ralph.py`: select and persist the active owner/return operation, preserving
  accounting and normal task/progress/verification ownership.
- A small handoff-specific helper/result type is acceptable to keep validation
  out of CLI and agent prose. It must not become a generic routing framework.

No changes to generated application files, task ownership declarations, visual
thresholds, provider permissions, or final acceptance requirements.

## Verification and bounded rollout

Implement and verify one boundary at a time, with failing regression tests first:

1. Handoff/continuation journal validation: real files, immutable predecessor
   records, candidate transitions, carried allowances, and tamper rejection.
2. Controller execution: T-011 capture failure selects T-012; owner repair and
   browser recheck precede return; fresh T-011 reviews remain mandatory.
3. Recovery: interrupt before/after each durable selection and receipt write;
   verify no duplicate provider dispatch, accounting, task progress, or reset.
4. Negative cases: same owner, unknown/mixed owners, out-of-scope owner, third
   owner during repair, stale candidate, missing evidence, failed reviews,
   repeated browser failure, and exhausted/unknown budgets.
5. Older-evidence path: refresh from an unchanged version 2 boundary within
   the remaining allowance; never modify its existing bytes or route from prose.
6. After review and focused functional checks, resume the existing disposable
   Delivery run through its native command. Observe the handoff, owner repair,
   recheck, and return. Do not manually fix the demo if any step fails.

Run the repository gate and report unrelated failures separately. The known
`test_converges_within_3_outer_iterations` fixture failure is not permission to
claim a green suite or expand this repair into a stale-test cleanup.

## Completion tracking

- [x] Structured failure receipts and feedback: `20e88b0d`; 209 focused tests;
  isolated Docker evidence-to-owner probe; independent review approved.
- [x] Written handoff design approved.
- [ ] Implementation plan approved and execution method selected.
- [ ] Handoff and recovery implemented, functionally verified, and reviewed.
- [ ] Existing workspace demonstrates owner repair and return without manual
  demo edits or gate exemptions.
- [ ] Checkpoint recorded; remaining STAB-1 acceptance work explicitly reported.
