# Managed WHY1 implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Implementation is inline at the user's request; use independent read-only review before committing verified changes.

**Goal:** Continue the managed greenfield run through WHY1 review, preserving stable issue/unknown identities, native routing and safe human clarification.

**Architecture:** Extend the existing selected-producer, reservation, review, source/publication and completion owners. Retain WHY1 rounds separately from Tracker without changing old records. Bind reports and routing to exact captured sources and accepted completion proof; no second review authority or repair controller.

**Tech Stack:** Existing Python, SQLite, Prosaic and pytest.

**Spec:** Inline WHY1 boundary approved in chat on 2026-09-15: assumption-review.md, optional issues.md and justified unknown additions; original assumptions stay read-only. New U/ISS use the existing authority. PASS reaches Constitution, FAIL follows native Discovery/iteration routing, STOP_AND_ASK uses existing policy. Downstream Constitution and repair execution remain separate.

**Status:** Tasks 1 and 2 complete for the approved internal WHY1 boundary.
Partitioned acceptance and affected regressions passed; independent read-only
review findings were fixed and verified. Downstream repair/Constitution execution,
installation, live-provider acceptance and activation remain outside this checkpoint.

## Global constraints

- Preserve exact existing IDs, immutable subjects and historical evidence. New numeric IDs have at least six digits and no application width cap.
- No new allocator, controller, mutable copies of prior producer state, or decision ledger.
- Codex/Claude use neutral Prosaic; do not load provider-native agents or add provider-specific prose.
- Preserve guided/semi/Banzai eligibility and existing iteration/dispatch/token limits.
- WHY1 does not run Understanding metrics or invent certified scores.
- Keep managed execution guards on unsupported phases. Do not redispatch initial Discovery as an alleged repair.
- No installation, activation, live spending, push/merge, stopped game workspace, legacy build, AGENTS.md or CLAUDE.md changes.

## Task 1: Closed WHY1 candidate and receipt contract

**Files:** `src/harness/discovery_semantics.py`, `discovery_candidate.py`, `discovery_receipts.py`, `discovery_reservations.py`; `tests/unit/test_why1_candidate.py`, `tests/unit/test_why1_receipts.py`.

**Interfaces:** Existing `DiscoveryAssignment` gains a closed version-4 WHY1 assignment, leaving v1/v2/v3 exact. WHY1 selects assumption-review.md, issues.md and unknowns.md. Reports are reference/issue roles; all earlier artifacts remain read-only. Only new U/ISS and explicitly permitted same-subject ISS revisions are admitted. Existing unknown definitions cannot be rewritten by the reviewer. The author returns exact artifacts and PASS/FAIL/STOP_AND_ASK/BLOCKED routing; the independent candidate reviewer echoes that routing. Missing optional issues remain null only when absent before/after. Existing receipt owners require the exact WHY1 round operation and never select flat/fallback Tracker paths.

- [x] Add a real managed-entry test using `controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-why1"}, create_managed_discovery=True)` and assert it reaches `phase1-constitution`; observe unsupported selection before implementation.
- [x] Add semantic/candidate tests using real identity previews: `DiscoveryAssignment(..., producer="why1").identity()`; author U/ISS from exact reserved IDs; reject foreign families, editable assumptions, changed existing unknown definitions, optional deletion and review-routing substitution. Observe RED, implement the closed contract and rerun.
- [x] Exercise `DiscoveryReceiptFile(..., producer="why1", round_operation_id="why1-" + parent_id)` with real reservation/turn journals; prove namespace separation and exact assignment recovery without reallocating.
- [x] Run affected old semantic/candidate/receipt suites; record evidence and review this independently testable contract.

## Task 2: Managed execution, publication and clarification

**Files:** existing `src/harness/discovery_producer.py`, `discovery_operation_state.py`, `discovery_turn_state.py`, `discovery_operation.py`, `discovery_turns.py`, `discovery_publication.py`, `discovery_completion.py`, `tracker_clarification.py`, `squad_state.py`, `squad_completion.py`, `squad.py`; neutral WHY1 producer/reviewer roles; `tests/unit/test_managed_why1.py`.

**Interfaces:** Extend the existing round-selection helpers to a closed WHY1 producer argument while retaining exact Tracker keys, fields and source/completion formats. `SquadStateStore.prepare_why1_round(source)` selects accepted Tracker as first parent; later rounds require the exact resolved WHY1 decision and existing human completion receipt. Continue through WHY1 only when explicitly selected internally. Existing completion/source proof adds distinct WHY1 encodings; old encodings remain unchanged. Captured source includes the SAGE templates and admitted reasoning context. Existing human-resolution preparation is reused with producer-specific association, not by relabeling WHY1 as Tracker. A FAIL stops at its native destination until authenticated repair integration exists; an already accepted initial Discovery operation never serves as that repair.

- [x] Drive the Task 1 normal-entry test GREEN using existing proposal/reservation/author/review and publication/checkpoint completion owners. Assert source assumptions/old unknown definitions unchanged, stable ISS/U creation, retained Tracker proof and exact cumulative usage.
- [x] Test PASS/FAIL/STOP_AND_ASK/BLOCKED with literal expected destinations, unchanged native iteration policy and preserved failure output. Guard report/routing consistency and stale review sources before publication.
- [x] Test `resume_with_human_input("...")` and existing Banzai decision execution through WHY1; assert exact previous round/receipt retention and no duplicate charges. Unjustified automatic answers remain human-gated.
- [x] Inject interruptions at accepted candidate, staging, route, publication, context, completion and release; reconstruct the controller and verify exact recovery, no duplicate IDs or checkpoint append.
- [x] Test source/report/receipt tampering, missing selected journals, unknown usage, no-progress and existing phase caps. Reuse real owners, scripting external processes only.
- [x] Run Codex/Claude × guided/semi/Banzai × checkpoints off/on acceptance, then affected Discovery/Synthesis/Tracker/human-input regressions.
- [x] Independent read-only review; fix demonstrated findings with RED/GREEN tests. Update the existing convergence/deferred records and commit only verified changes locally.

## Evidence

Clean starting HEAD: `13d72892`. Existing SAGE/quality contract baseline: 27 passed in 0.29s. Existing isolated convergence worktree retained; no new workspace or installation needed.

### Intermediate verification and review

- The two-provider normal entry initially failed at unsupported selection, then
  passed through Constitution: 2 passed in 195.74s. Optional issues stay absent.
- Native issue creation/publication passed: 1 passed in 98.64s. Native report
  occurrence provenance and body-only ISS lifecycle content are reused.
- Guided clarification and accepted-operation recovery passed: 2 passed in
  366.31s. The earlier human-resume fixture incorrectly defaulted to Banzai;
  explicit guided/semi cases now test human paths independently of eligibility.
- FAIL, BLOCKED and iteration-limit failure all reached the native destinations
  without running repair. The same pre-fix process then reproduced the missing
  reasoning input (3 passed, 1 failed); the reasoning capture regression passed
  separately after its fix: 1 passed in 131.97s.
- Independent candidate review found subject/title mismatch, trailing-newline
  mutation, and a historical report/head-revision mismatch. Each has a RED/GREEN
  regression. The candidate/receipt group passes 46 tests in 1.17s.
- Focused semantic, identity, receipt, round, clarification and completion
  regressions: 554 passed in 18.93s. Independent read-only runtime review found
  no additional concrete issue; its separate recovery regression group passed
  98 tests in 199.75s.
- The expanded normal matrix initially used a universal-newline text reader in
  a byte-preservation assertion. It now compares raw UTF-8 bytes, including CRLF.
  The corrected 12-case matrix and remaining fault/re-entry acceptance are
  running; those results are not yet included in completed evidence.

### Subsequent verification

- Corrected provider/mode/checkpoint matrix: all 12 passed, partitioned by
  guided (4 in 670.83s), semi (4 in 673.23s), and Banzai (4 in 675.49s).
- Existing execution, runtime-input and human-input regression group:
  571 passed in 262.64s. Quality/prose-template regressions: 29 passed in 0.55s.
- Candidate/receipt tests including forged round selection: 50 passed in 1.89s.
- WHY1 uses the existing iterative cap (`max_iterations + 1`), not Tracker's
  fixed non-iterative limit. The corrected configured-budget test passed in
  226.38s; the earlier partition still contains its old test expectation.
- Report/source changes and forged clarification bindings are rejected. After
  release, the existing retained database completion proof—not the mutable
  process journal—is authoritative. A test that expected the journal to be
  reread was corrected after independent review against the existing Tracker
  implementation; no production relaxation was made. The corrected tampering
  test passed in 176.24s, preserving the exact accepted parent and answer.
- Remaining recovery partitions are still running; do not infer completion.
- New-unknown publication plus six existing Tracker acceptance cases passed:
  7 in 1078.28s. This includes both providers, ordinary Tracker continuation,
  guided/semi clarification with retained receipts, and native Banzai decisions.
- Recovery partition 1 passed all 10 cases in 1828.23s. Partition 2 passed its
  first nine cases, then failed the old non-iterative cap expectation in 1944.49s;
  the corrected iterative-budget case above supplies that case's passing result.
  No native dispatch policy was changed to accommodate the test.
- Fresh shared candidate, receipt, state, semantics and completion regression:
  558 passed in 16.55s, including the four additional protected-round tests.
  Collection confirms 44 current WHY1 acceptance cases; the last recovery
  partition is still required before closing this checkpoint.

### Final checkpoint verification

This supersedes the intermediate running status above. The last recovery
partition passed all 10 cases in 2015.89s. All 44 collected WHY1 acceptance cases
have passing results: 12 normal matrix, 29 other cases across the three recovery
partitions, the separately corrected cap case, new-U publication, and the final
tampering/binding case. The old cap expectation's failure is retained above for
auditability; its corrected test passed without changing production policy.

Affected regressions include the fresh 558-case shared group, the 571-case
execution/input group, 29 quality/template cases and six existing Tracker
acceptance cases. These are selected/partitioned runs, not a full repository
suite. Model and Prosaic processes are scripted; state, identity, publication,
checkpoint, context and completion owners are real. Independent review found no
remaining concrete issue after the three documented candidate fixes.

The same checkpoint updates the existing convergence and deferred-scope records.
Next work is authenticated review-origin repair/return, then downstream managed
continuation and the original renumbering/evidence acceptance. No downstream
execution, installation, live-provider spending, push, merge or activation occurred.
