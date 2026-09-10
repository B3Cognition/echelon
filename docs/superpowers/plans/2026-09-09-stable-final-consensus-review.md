# Stable final consensus review implementation plan

> Execute inline, test-first. Design: `docs/superpowers/specs/2026-09-09-phase3-repair-handoff-design.md`, with the owner's approved harness-provenance/final-review amendment.

**Goal:** Finish ordinary consensus without copying cryptographic provenance through the model or repeatedly replanning solely because reviewers regenerate their reports.

**Architecture:** Keep the existing SAGE, GATEKEEPER, PLAN2 executor, sealed controller transitions and durable state. Bind compact provider assessments to the actual dispatch. After successful PLAN2, persist a content-bound pending final review; run both reviewers against that fixed candidate before normal recertification/checkpoints. Review output changes are permitted inside this round, not permission to edit its inputs.

**Constraints:** Banzai, semi and guided share final verification. Existing approval, rejection, budget, token and dispatch policies remain. Legacy stored receipts remain strictly validated. No SOAR, new agents, graph changes, demo edits, budget resets or gate waivers.

## 1. Harness-owned review provenance

- Add failing contract tests for compact schema-2 assessment: selected issue, outcome, rationale and evidence references; accept no model-supplied identity/hash fields. Reject wrong selection, unknown references, unauthorized agents and malformed legacy envelopes.
- Bind valid responses to controller identity and dispatched manifest; retain strict schema-1 persisted receipts and legacy provider compatibility.
- Update both SAGE review call sites and source instructions. Verify actual input hashes again before committing closure.
- Run contract, state and selected-issue executor tests.

## 2. Durable fixed-candidate review round

- Add failing integration tests demonstrating that PLAN2 success followed by changing review reports completes after fresh WHY3 and ASSESS2, without another PLAN2. Parameterize modes and process/store restart; include a fresh spec without repair history.
- Capture the final candidate and its actual non-report context/agent contracts. Record the round through the existing state CAS API. Missing/legacy receipts never authorize skipping work.
- Dispatch final reviewers with an explicit read-only candidate instruction. Only `issues.md`, `quality-gates.md`, and `implementability-report.md` are review outputs. Estimates, scope, contracts and planning inputs remain immutable during this round.
- Compare inputs before/after dispatch. Real changes invalidate the round; changes during review fail closed. New failed gate findings retire the round and use existing routing.
- Drain pending independent issue closures before exiting the final round; do not spend repair iterations for review-only transitions. Require both reviewer results even when no selected issue exists.
- Cover changed requirements, role/context changes, failed planner, failing final reviewer, restart and state-write failure.

## 3. Normal-flow regression verification

- Exercise `SquadController.run`: normal planning → consensus → fixed final review → deterministic task recertification → existing mode-specific checkpoint/finalization path. Substitute the external provider. Use the real requirements metric engine for the failure path and the existing passing metric-engine fixture for the successful branch; keep receipt persistence, freshness guards, recertification and approval routing real. Do not use a phase override as proof of full-flow behavior.
- Run affected routing, controller, journal, state, CLI continue, prompt and mode suites. Review the complete diff for acceptance weakening and lifecycle regressions.

## 4. Install and preserved-run validation

- Install only after tests and review pass; refresh the demo's deployed runtime with the public migration command.
- Resume preserved spec 008 using the supported CLI recovery route, keeping iteration history and total-30 authorization intact. This live recovery complements, not replaces, normal-flow tests.
- Observe for genuine progress or a concrete terminal failure. Do not change product/spec artifacts to manufacture success. Report exactly what passed and whether the live run completed.

## Implementation verification

- New regression/assessment suite: 54 passed, including all three modes, store restart, report-only revisions, changed inputs/contracts, negative closure, large candidates, missing ASSESS2 report, and CAS failure.
- Independent read-only review: three reproduced findings fixed test-first; follow-up found no remaining P1/P2; reviewer independently ran 25 passing focused cases.
- Broad affected suite: 1,436 passed, with two legacy fixture setup failures (absent spec input; persisted iteration budget 10 but controller configured for 5). Corrected those test setups without weakening assertions or production limits; all 13 consensus compatibility cases then passed.
- The normal-flow tests reach actual mode-specific checkpoints/finalization, and intentionally incomplete product artifacts still fail the existing readiness gate. They do not claim a complete generated product from a fake provider.
- Live demo verification remains a separate installation/recovery step. Preserve iteration 20, usage 73,167,667 and the existing total-30 authorization.

## Post-retry boundary correction (approved 2026-09-09)

The live retry stopped at iteration 20/30 with 78,431,540 recorded tokens. It
proved compact provenance binding for two issues, but rejected SAGE's legitimate
workspace-relative citations for the third. It did not reach the durable final
review: ASSESS2 independently rejected a concrete positive-fixture contradiction.

The bounded correction retains the architecture above:

1. Enumerate spec-relative, workspace-relative and absolute aliases of the
   harness-dispatched manifest entries. Never resolve provider paths or accept
   suffix/basename matches. Preserve safe input capture, content rechecks, selected
   identity, strict legacy receipts and state-CAS commits at both review call sites.
2. Defer PLAN2 on completed ASSESS2 rejection, preserving both review verdicts and
   the existing deterministic tasks-recertification → architecture-repair route.
   Retain normal planning for existing accepted-risk dispositions. Incomplete,
   failed or malformed assessments remain failures; no new risk grant is created.
3. Supply the current run-local implementability report as required bounded repair
   context to ARCHITECT even when WHY3 passes. Missing, unsafe or oversized required
   context fails closed. This is repair context, not a new acceptance receipt.
4. Replay the exact captured SAGE payload and the separately reconstructed
   GATEKEEPER rejection through `SquadController.run` in all three modes. Keep real
   state persistence, dispatch, recertification, repair counters and checkpoints.
   Test full passing-review flow, genuine metric failure, legacy inline
   revalidation, input-path rejection, incomplete assessments and accepted-risk
   compatibility. Provider substitution does not establish product correctness.
5. Complete focused and broad regressions plus independent review before any
   installation or live retry. Leave the demo and paused monitor untouched during
   this correction; do not increase or reset its budget.

The existing producer-report availability contract does not independently prove
that a provider rewrote an unchanged report in this dispatch. This correction
does not turn that report into acceptance evidence or introduce a new report
receipt/lifecycle subsystem.

### Correction verification

- The ordinary controller replay first reproduced the path failure as
  `repair_review_stale`, and the conflicting-gates replay first reproduced
  `agent_blocked` before ARCHITECT was reached.
- Final combined review/replay/context suite: **141 passed**. Broader controller,
  state, human-input and repair compatibility suite: **1,220 passed**. A subsequent
  focused deferral check including the final non-consensus scope guard: **15 passed**.
- The accepted-risk planning exception and non-consensus-node guard each have
  observed red → green regressions; neither changes an approval policy.
- Independent read-only review: no remaining P1/P2 findings.
- The checked-in captured SAGE fixture exactly matches the live parsed payload.
  Read-only replay against the actual demo manifest accepts its workspace-relative
  references; required repair context is 202,047 bytes, below the existing bound.
- No installation, workspace migration, live retry, demo edits or budget changes
  were performed during this correction. Spec 008 remains terminal-blocked at
  iteration 20/30 and 78,431,540 tokens; the monitor remains paused.
