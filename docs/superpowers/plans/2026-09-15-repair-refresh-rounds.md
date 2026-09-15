# Repair refresh round retention

> **For agentic workers:** Use superpowers:executing-plans. Execute inline; independent read-only review precedes the local checkpoint commit.

**Goal:** Retain fresh Synthesis/Tracker/WHY1 round associations after a released Discovery repair without overwriting original operations or enabling refresh execution.

**Architecture:** Extend the existing producer round and Squad state owners with a closed refresh association. Preserve flat original Synthesis records; new Synthesis rounds refer to that original predecessor without copying it. Existing Tracker/WHY1 rows remain exact, with refresh distinguished from human clarification. Authenticate the repair and previous producer publication through existing retained completion readers before a full-state CAS.

**Tech Stack:** Existing Python, SQLite, Prosaic and pytest.

**Spec:** Inline checkpoint-3 design approved by the user: (1) retain refresh rounds, (2) refresh changed dependencies, (3) rerun the requesting WHY1. This plan implements step 1 only. The managed Discovery integration design and convergence records retain the broader boundary.

## Global constraints

- Preserve original state, receipts, exact IDs, immutable subjects and revision-sensitive historical evidence.
- New numeric IDs retain six digits minimum with no application width cap; this step allocates none.
- No new controller, allocator or attempt ledger. New rounds use existing operation/turn slots, initially null.
- Neutral Prosaic for both providers; unchanged guided/semi/Banzai and cumulative limits.
- No refresh execution, dependency selection policy, re-review, installation, migration, live-provider spending, push, merge, original smoke workspace, legacy build, AGENTS.md or CLAUDE.md edits.

## Task 1: Protected round associations

Files: `discovery_producer.py`, `squad_state.py`; `tests/unit/test_repair_refresh_rounds.py`.

Interface: `SquadStateStore.prepare_refresh_round(producer, source, refresh, *, expected_state)`; refresh is closed `{repair_unit, repair_source, predecessor_source}`. Rows reuse `{source, resolution, predecessor, operation, turns}` plus `refresh`; resolution is null, predecessor is the exact prior producer operation. Original Synthesis stays flat; `managed_synthesizer_rounds` contains only new rounds. Explicit operation-id reads distinguish those from the original operation. This first admission supports the repair itself as current source; subsequent refreshed parents belong to step 2.

- [x] RED: select a round from real completed repair state and assert original records, attempts, usage and dispatch counts remain unchanged; the absent entry point must fail.
- [x] Add closed, acyclic, connected validation with one round per producer/repair. Reject incomplete repair, changed origin, duplicate association, invalid predecessor, generic edits and changed CAS state.
- [x] Keep refresh operation initialization closed until step 2; selecting a row does not confer dispatch/publication authority. Existing state validation rejects non-null operation/turns, so the operation owner itself needs no new code.
- [x] GREEN: exact retry/reopen returns the same saved state; historical original components remain readable. Mixed human-clarification ancestry has a separate review regression below.

## Task 2: Authenticated inactive preparation

Files: `discovery_repair_admission.py`, `tracker_clarification.py`; `tests/unit/test_repair_refresh_rounds.py`.

Interface: `prepare_repair_refresh_round(project_root, state_store, producer)` under caller execution leases. Read current released repair and its full ancestry; derive the selected repair unit and exact previous producer completion, then call Task 1 with the captured full-state comparison.

- [x] RED: real managed repair return followed by preparation preserves receipts/history and remains at the existing unsupported-refresh guard.
- [x] Reuse retained completion projection to authenticate actual Discovery→WHY1 repair and requesting WHY1 ancestry; never trust caller-supplied digests as publication evidence. Explicitly compare the authenticated predecessor operation with the state owner's selection.
- [x] Reject modified published inputs, stale source, foreign producer, pending publication and malformed/unreleased repair without writes.
- [x] GREEN: all three producer associations, exact replay, mutation/CAS rejection and old recovery regressions.

## Task 3: Review and checkpoint

- [x] Run focused state/operation/repair tests and selected real completion regressions; record exact results, not a full-suite claim.
- [x] Independent read-only review, test-first corrections if needed.
- [x] Update existing convergence/deferred records; verified changes are ready for the local checkpoint commit. Keep execution/refresh policy and re-review as the next steps.

## Evidence

Starting HEAD `a9e13d98`, clean existing linked worktree. Baseline operation and
Tracker-round tests: 43 passed in 49.27s.

New state/admission tests RED: both missing entry points after the real released
repair (2 failed in 182.88s); the focused owner case also failed independently
in 0.44s. First GREEN: 2 passed in 211.41s. It covers all three producers,
historical component reads, generic mutation/CAS rejection, blocked operation
initialization, exact resume with zero additional calls, and changed captured
source/template/context rejection.

Independent review found that the existing clarification reader stops at null
resolution, so a fresh Tracker refresh row hides earlier Tracker answers from
historical WHY1 decoding. The real combined Tracker-question → WHY1-question →
repair regression reproduced this (1 failed in 495.77s). A separate diagnostic
using genuine resolved decisions and an isolated round lookup reproduced the
same loss before the fix. The fix follows refresh predecessors without adding
a decision. Resuming the failed real fixture with current code subsequently
preserved both answers through all three associations and exact retries.

Current verification:

- Original owner/admission tests rerun after the final production changes:
  2 passed in 210.52s.
- Tracker rounds, Discovery operation/repair retention/completion and Squad
  completion regressions: 336 passed in 296.83s.
- After the clarification fix: clarification candidate, Tracker rounds and
  Discovery operation tests: 66 passed in 45.65s (43 overlap the prior group).
- Fresh full clarification/repair/refresh integration: 1 passed in 499.66s.
  Claude guided execution retains both Tracker and WHY1 answers through all
  three refresh associations, their exact retries, historical and newly selected
  WHY1 history reads, and the unchanged controller guard. Usage remains 147
  tokens / 21 scripted calls. Ordinary Codex retention keeps 105 / 15.
- Independent review cleared the final production diff, including the explicit
  predecessor check. Fresh integration verification now passes. `git diff --check`
  passed. In total, 3 new cases and 359 distinct affected regression cases have
  passing partitioned evidence; overlapping baseline/reruns are excluded.
  No full-suite or live-provider claim is made.

Dependency comparison, active refreshed producer outputs and later clarification
ancestry remain step 2; re-review remains step 3. This checkpoint does not claim
those execution paths from inactive association tests.
