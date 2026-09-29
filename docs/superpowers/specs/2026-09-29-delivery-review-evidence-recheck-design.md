# Delivery review evidence recheck

## Purpose and observed failure

In the rugby-demo Delivery run, SPEC GUARD claimed that no candidate test
imported `startBrowserApplication` and that rendered-style outcome coverage was
absent. Both test files existed in the candidate and appeared in the
controller's test-path inventory. TEST GUARDIAN and CODE REVIEWER used them.
The controller accepted SPEC GUARD's structurally valid but factually stale
FAIL and sent it into an implementation-repair round. The real listener and
RAF-test findings must remain blocking; the false absence claim must not cause
an implementer to change working product code or spend another repair round.

## Decision

Extend the existing controlled-slice journal with one bounded, same-role,
read-only evidence recheck. Keep the four roles, their gate order, and all
passing requirements. This is a correction of review context, not a new
implementation attempt or an approval override.

The controller indexes runnable candidate tests independently of the task's
non-exhaustive Files list. It derives a bounded task-relevant audit set from
declared tests, their runnable siblings, changed tests, and tests referencing
the selected task's source paths. Both the full path inventory and audit set
are bound to the candidate fingerprint. A negative SPEC GUARD or TEST
GUARDIAN result must report which candidate tests it inspected. The controller
validates that the audit set was accounted for. Incomplete evidence is not yet
an actionable product finding.
The controller records the incomplete result, supplies the omitted test sources
as read-only context, and dispatches the same reviewer once more. The second
result replaces the first review verdict for this candidate and gate. A
well-grounded FAIL enters the existing aggregate implementation-repair flow;
a PASS proceeds to the next gate. A second incomplete evidence report blocks
with an explicit reviewer-context reason, never with a fabricated product gap.

This is a process guarantee, not a claim that Python can decide whether a test
semantically proves an acceptance criterion. The reviewer retains that
judgment. The controller guarantees that an omitted candidate test cannot
silently become an implementation-repair instruction.

## Alternatives considered

- Prompt-only reminder or larger path list: cheapest, but the observed failure
  happened with both paths already supplied. It does not create a checkable
  boundary.
- A second adjudicator role: another model opinion and another dispatch path,
  with no stronger evidence contract. It adds cost and protocol surface.
- Chosen: one same-role recheck with controller-validated test-path accounting.
  This uses the journal's existing per-dispatch receipt pattern and keeps
  genuine findings in the established repair loop.

## Data and state flow

1. Before each review dispatch, enumerate runnable tracked and untracked test
   files in the current candidate. Exclude fixtures and non-test support files.
   Derive a bounded audit set from declared tests, all runnable tests in their
   directories, tests changed since the candidate's current Git HEAD, and
   tests whose content references selected source paths or their extensionless
   stems. Treat the task Files list as a starting point, not a whitelist.
   Bind both inventories to the exact candidate fingerprint already in the
   assignment. Never silently truncate the audit set.
2. For a negative SPEC GUARD or TEST GUARDIAN result, require a structured
   `reviewed_test_paths` list. Validate that each path is in the candidate and
   that the audit set is accounted for. The reviewer may inspect and cite any
   additional candidate test. Existing stored receipts retain their prior
   meaning; new dispatches use the new check.
3. Persist the provider result, its inventory identity, and the controller's
   evidence-completeness decision in one journal save before advancing. A
   recorded incomplete result permits exactly one repeat of the same role on
   the same candidate and repair round. The follow-up prompt includes the
   prior finding and the omitted files' bounded read-only content or, when too
   large to inline, exact paths with mandatory read access. Neither result
   counts as an implementation repair until the recheck resolves the finding.
4. On replay, derive the next dispatch from validated receipts. A completed
   recheck is never rerun; an intent with unknown completion still requires
   reconciliation. A candidate/spec/role binding change still fails closed.
   Count all reviewer token usage, including rechecks, exactly once.
5. Only the final reviewer verdict participates in the aggregate review round.
   Other independent reviewers still run. A genuine negative result routes to
   the implementer through the existing bounded repair path. No reviewer
   result is silently converted to PASS.

## Boundaries and errors

- Rechecks are read-only and cannot edit the candidate, task progress, or
  control-plane files. They do not reset or raise the implementation repair cap.
- Inventory failures, audit-set overflow, path escapes, changed candidate
  contents, unknown
  provider completion, and a second incomplete review stop with explicit
  reconciliation/context reasons. No attempt is retried merely because it
  returned an unfavorable verdict.
- The candidate test source packet has a fixed byte limit. If content cannot
  fit, the reviewer receives exact candidate paths and must read them through
  its existing read-only tool boundary; absence claims without accounting for
  them remain incomplete.
- No generated demo files are manually edited by this change. Existing
  operations retain their recorded receipts; no historical run migration or
  gate relaxation is required.

## Verification

Use scripted-provider tests against the real runner and journal to prove:

- A reviewer that overlooks existing tests outside the task Files list gets
  one same-role recheck and can correct its verdict without an implementer
  repair or task acceptance shortcut.
- A recheck that confirms a real gap routes that finding to the implementer;
  other reviewers' findings are still aggregated.
- A repeated incomplete review blocks explicitly, without consuming a repair
  round or silently accepting the task.
- Crash/replay before dispatch, after intent, after result, and before
  advancement dispatches no duplicate external work or stale review.
- Candidate mutation, forged paths, oversize source context, and token-budget
  exhaustion retain fail-closed behavior.

After repository tests, install only Echelon's changed runtime and exercise a
small disposable review probe before resuming the rugby-demo Delivery run. Do
not infer success from unit tests alone.
