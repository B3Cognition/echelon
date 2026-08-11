# EGR GitHub Reconciliation and Validity Audit Design

**Date:** 2026-08-11
**Scope:** Reconcile the Echelon Grounded Review register with GitHub, then
re-evaluate the seven unresolved findings against current source and tests.

## Objective

Restore exact parity between the authoritative EGR register and GitHub issues,
then determine which currently unresolved EGRs remain valid after substantial
repository changes. This is an audit and tracking task; production-code changes
are outside scope.

## Authority and Completion Rules

- `docs/findings/echelon-grounded-review-register.md` is the source of truth.
- The first reconciliation uses the register exactly as it exists before the
  validity audit.
- For this audit, an EGR may be marked `fixed` when current implementation and
  focused tests prove the finding is addressed. A missing `[Unreleased]`
  changelog entry is noted but does not keep the finding open.
- Findings remain `in-progress` when implemented slices exist but the original
  observable gap remains, and `open` when the confirmed gap is not addressed.
- `superseded` requires a newer finding or architectural decision that replaces
  the original contract. `accepted-risk` requires an explicit rationale rather
  than mere absence of implementation.

## Phase 1: Initial GitHub Reconciliation

Run the repository's idempotent `scripts/sync-egr-issues.py` against
`B3Cognition/echelon`. It must create missing EGR issues, update titles, bodies,
priorities and status labels, reopen unresolved findings, and close findings
whose register status is terminal.

Capture the resulting created/updated totals and verify that every register EGR
has exactly one matching GitHub issue with the expected state and managed
labels. This establishes a known synchronized baseline before evaluation.

## Phase 2: Current-Code Validity Audit

Audit these unresolved register rows at current `main`:

- EGR-115
- EGR-118
- EGR-119
- EGR-142
- EGR-144
- EGR-146
- EGR-149

For each finding:

1. Restate the original observable failure and completion contract.
2. Locate current implementation paths and focused tests relevant to that
   contract.
3. Inspect recent changes that may have fixed, narrowed, or obsoleted it.
4. Run the smallest focused test set that can prove implemented behavior.
5. Record a verdict, evidence, remaining gap, and confidence.

The audit must not infer completion from filenames, plans, comments, or
historical progress notes alone. A `fixed` verdict requires executable source
and passing tests that cover the material contract. When a finding contains
multiple material requirements, unimplemented requirements keep it
`in-progress` unless a later architecture decision makes them obsolete.

## Phase 3: Register Update and Final Sync

Update each audited register row with its current priority, status, evidence,
and next action. Advance `Last delta review HEAD` to the audited commit and set
`Last updated` to the audit date. Preserve dated historical finding documents.

Run the GitHub synchronization a second time so audit verdicts are reflected in
issue bodies, labels, and open/closed state. Verify final parity across:

- one GitHub issue per EGR ID;
- issue open/closed state versus register status;
- `priority:*` label versus register priority;
- `status:*` label versus register status;
- issue title and body versus the current register row.

## Failure Handling

- Stop before mutation if GitHub authentication or repository access fails.
- If initial synchronization partially succeeds, inspect exact issue state and
  rerun the idempotent sync rather than manually guessing what remains.
- If focused tests fail for reasons relevant to a finding, do not mark it
  `fixed`.
- If tests cannot establish the original contract, retain the nonterminal status
  and describe the missing evidence or coverage.
- Preserve unrelated worktree changes. The audit begins from a clean worktree;
  any unexpected changes are treated as a stop condition.

## Verification and Deliverables

The completed task produces:

1. A synchronized baseline of all EGR GitHub issues.
2. An evidence matrix for the seven unresolved findings.
3. An updated authoritative register and delta-review metadata.
4. Passing focused verification for any EGR changed to `fixed`.
5. Final register/GitHub parity verification and a concise list of the EGRs
   that remain unresolved.
