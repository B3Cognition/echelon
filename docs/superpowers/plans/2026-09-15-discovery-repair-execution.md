# Discovery repair execution and publication

> **For agentic workers:** Use superpowers:executing-plans. Implementation is inline; independent read-only review is required before the local checkpoint commit.

**Goal:** Execute an authenticated WHY1 repair, publish its same-subject revision safely, and stop before dependency refresh/re-review.

**Architecture:** Extend the selected repair unit with immutable execution binding and turn-marker metadata. Its existing attempts remain the only attempt ledger. Adapt the shared Discovery operation, receipt and publication owners with an explicit repair-unit argument; preserve original records and existing completion encodings.

**Tech Stack:** Existing Python, SQLite, Prosaic and pytest.

**Spec:** The managed Discovery integration design, checkpoint-1 admission record, and the inline storage extension approved by the user on 2026-09-15. This approval supersedes the selection-only shape restriction for new execution metadata, not the unit identity, selection or attempt semantics.

## Global constraints

- Exact IDs and subjects, six-digit-minimum new numbers with no application width cap; never renumber old evidence.
- One repair budget: initial attempt plus two retries; unknown provider completion blocks and restart does not reset progress or usage.
- Reuse existing state, allocation, publication, completion and Prosaic owners for Claude and Codex.
- No installation, activation, live spending, migration, push/merge, original smoke workspace, legacy build, AGENTS.md or CLAUDE.md changes.
- Return to the authenticated requesting WHY1 destination, guarded against stale dependency/review replay until checkpoint 3.

## Task 1: Per-unit execution through existing state and receipt owners

Files: discovery_repair_state.py, discovery_producer.py, discovery_operation_state.py, discovery_turn_state.py, squad_state.py, discovery_turns.py, discovery_reservations.py; test_discovery_repair_execution.py.

- [x] RED: call `advance_discovery_operation(binding, "prepare", repair_unit=unit)` after retaining original Discovery; verify the unsupported argument fails.
- [x] Add optional `execution={binding, turns}` to a selected unit. `operation_from_state(..., repair_unit=unit)` exposes the existing attempts, not a second list. Bind scope/origin/findings exactly and reject changed binding or turns.
- [x] GREEN: two state-owner tests pass; beginning twice is idempotent, the fourth attempt rejects, original Discovery is unchanged, generic save cannot alter metadata.
- [x] Extend existing isolated receipt paths through concrete turn/reservation owners. Reject mismatched unit/operation and deny provider reads of run-owned receipts.

## Task 2: Authenticated execution, publication and retained return

Files: discovery_operation.py, discovery_publication.py, discovery_completion.py, squad_completion.py, squad.py; test_discovery_repair_execution.py and existing admission tests.

- [x] RED: real managed entry through WHY1 FAIL, then resume with a scripted same-subject camera repair. Assert WHY1 return, released publication, revision 3, unchanged historical issue occurrence, original receipts and cumulative 105 tokens.
- [x] Capture post-WHY1 sources using existing released projections; keep downstream artifacts, staging and reasoning read-only. Reuse native issue-report contexts and exclude authenticated generated context only from duplicate definition parsing.
- [x] Pass `repair_unit` through shared proposal/author/review, binding, isolated journals and repair attempt transitions. Persist normalized progress in the existing result.
- [x] Seal and authenticate a distinct v8 repair completion with exact selected unit and WHY1 parent. Older encodings remain unchanged; full source/graph guards and existing completion recovery remain authoritative.
- [x] Use existing host-controlled routing override for the authenticated return phase. Guard subsequent execution before old WHY1/Tracker/Synthesis records can replay.
- [x] GREEN: two-provider normal acceptance; restart at accepted candidate and publication/release; no-progress/exhaustion; unknown turn and missing receipt; source/scope tampering. Prior admission tests continue proving selection alone without requiring runtime to remain unsupported.

## Task 3: Review and checkpoint

- [x] Run affected state, operation, receipt, source, publication, completion and WHY1 regressions in bounded partitions.
- [x] Independent read-only review; reproduce and fix concrete findings test-first.
- [x] Record exact verification and deferred checkpoint-3 boundary in existing convergence records; checkpoint is ready for its local commit.

## Evidence

Starting HEAD `63293baf`, clean linked worktree on `fix/delivery-controller-contract`.
Repair prerequisite baseline: 35 passed in 138.91s.
State test RED: unsupported `repair_unit` argument. Initial GREEN: 2 passed in 8.51s.
Initial managed integration RED: `managed_review_repair_not_supported` (102.50s).
The first publication integration exposed a missing required `controller_updates`
argument; the fix uses the existing routing override with an empty updates map.

Test-first safety corrections:

- Out-of-scope new subjects and omitted selected targets initially reached author
  execution. Both now stop before reservation/allocation. Scope plus the original
  two-provider acceptance partition: 4 passed in 395.60s.
- A low-level repair completion initially accepted a non-WHY1 parent. It now
  authenticates the actual WHY1 FAIL route and recomputes native findings from
  exact retained reviewed inputs. The regression failed before the fix.
- Resetting the repair dispatch count initially passed admission. The count now
  matches the original operation plus retained units with execution metadata;
  selection alone remains uncharged. The regression failed before the fix.
- Retry fixtures originally shadowed an upstream executor rejection flag, causing
  Tracker to reject before repair. Renaming that test-only flag restored the
  intended path; production retry semantics were not weakened. Progress fixtures
  use distinct substantive camera investigation evidence, not attempt labels.

Affected regression partitions:

- Operation, turns, repair retention and captured repair inputs: 144 passed in
  207.17s.
- Discovery completion/publication/checkpoints, Squad completion, Tracker round
  state and WHY1 candidates/receipts: 393 passed in 440.76s.
- WHY1 repair admission: 25 passed in 561.76s. Selection-only assertions call the
  admission owner under both real leases; execution is no longer unsupported.

Independent read-only review reproduced the allocation-scope problem, identified
the parent-authentication gap, reviewed both fixes and the dispatch-count guard,
and found no blocker for the local checkpoint commit. The reviewer independently
passed the counter and single-attempt-authority cases (2 passed in 11.97s).

Final current-code execution partitions:

- State ownership/immutability, dispatch count, pre-allocation scope and invalid
  review parent: 6 passed in 53.47s.
- Codex guided/checkpoint-on U repair, Claude Banzai/checkpoint-off U repair,
  Codex semi/checkpoint-on A repair: 3 passed in 602.20s. Each reaches the guarded
  WHY1 return with 15 provider calls / 105 tokens and preserves prior history.
- Read-only drift after staging, source/receipt corruption and dispatch count:
  3 passed in 480.03s. The unchanged drift case is not rerun in the final other
  partitions.
- No-progress/retry-exhaustion restarts and exact accepted sources/receipts:
  3 passed in 650.91s. Missing selected turn/reservation journals block without
  recreation or fallback; restoring the exact inputs permits one publication
  without extra calls. Changed issues, target definitions, generated context and
  SAGE template evidence also block without state or identity changes.
- Accepted-candidate, promoted-identity and released-publication interruption
  recovery, plus unknown provider completion: 4 passed in 729.47s. Completed
  calls/publication are not duplicated, and unknown completion blocks without
  resetting the selected unit or usage.

All 17 current execution tests have passing partitioned evidence, alongside 562
distinct affected regression cases (144 + 393 + 25). Counts exclude overlapping
baseline and intermediate reruns. `git diff --check` passed. Independent review
cleared this local checkpoint; dependency refresh/re-review remains checkpoint 3.

No full-suite, live-provider, installation or activation claim is made. Only
external process responses are scripted; identity, state, publication, checkpoint,
completion and recovery owners are real.
