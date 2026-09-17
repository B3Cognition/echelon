# Managed Phase 2 Implementation Plan

> For agentic workers: use superpowers:executing-plans, inline as approved.

**Goal:** Continue the released native Phase 1 approval through Phase 2 and stop
before Phase 3 execution.

**Architecture:** Extend existing managed producer/round/receipt contracts and
native Squad routing. Keep structural policy in its existing owner and publish
captured results through the existing guarded publisher/completion transactions.

**Tech Stack:** Python, pytest, neutral Prosaic, existing SQLite identity store.

**Spec:** `docs/superpowers/specs/2026-09-17-managed-phase2-design.md`

## Global constraints

- Inline in the existing isolated worktree; baseline `2194f08f`.
- Stop before executing `phase3-specialists`.
- No installation, migration, live model spending, push, merge, legacy build,
  AGENTS.md or CLAUDE.md changes.
- No additional allocator, publisher, decision log, policy owner or COMMANDER role.
- Preserve Codex/Claude neutrality, current native policies, IDs/history,
  cumulative accounting and recovery; performance optimization is deferred.
- Use the existing repository virtualenv for every test and append
  `-o tmp_path_retention_count=200 -o tmp_path_retention_policy=all`.

## Task 1: Captured structural evaluation

Files: `src/harness/governance_structural_gate.py`, `src/lexicon/structural.py`,
`src/lexicon/manifest.py`, `tests/unit/test_captured_governance_gate.py`.
Consumes captured text/configuration plus native counters. Produces
`evaluate_captured_governance_structural_gate(...) -> (GovernanceStructuralGateResult,
dict | None)`, with no live input reads or report writes. Bundled validator
resources (the Lexicon grammar) may load. Existing native runner stays public.

- [x] Add red tests for both artifact types, source/template capture, missing
  input, bypass, counters, warn/block exhaustion and write-free evaluation.
  Assert literal outcomes, for example:
  ```python
  assert result.action == "repair"
  assert result.attempts == 2
  assert report["ok"] is False
  assert not report_path.exists()
  ```
- [x] Run `python -m pytest tests/unit/test_captured_governance_gate.py -q` and
  confirm missing captured entry, not a fixture/import error.
- [x] Add `required_sections_from_text(text)` in the existing manifest owner,
  and optional captured `template_text` to `structural_validate`. Extract shared
  report-to-outcome policy in the existing governance owner; preserve native
  write-failure accounting. Captured evaluation requires every declared input
  rather than falling back to live paths.
- [x] Run new tests plus `test_governance_structural_gate.py` and
  `test_structural_*.py`; compare live/captured results and reports on real inputs.
- [x] Commit this inactive, verified evaluation boundary; do not claim Phase 2
  runtime admission or whole-milestone completion.

## Task 2: Closed Phase 2 producer contracts

Files: new `src/harness/discovery_assessment.py`; existing
`discovery_semantics.py`, `discovery_producer.py`, `discovery_candidate.py`,
`discovery_reservations.py` (the same persisted-assignment decoder);
new `tests/unit/test_managed_assessment_contract.py` and neutral Prosaic role
contracts for feasibility, strategy and alignment author/reviewer turns.
Consumes `DiscoveryAssignment`. Produces closed artifact/routing validation for
producers `feasibility`, `strategy`, `alignment`, all with no identity edit scope.

- [x] Add assignment/reply tests using these literal write sets:
  ```python
  feasibility = {"feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md"}
  strategy = {"strategic-overview.md"}
  alignment = {"intent-alignment-check.md"}
  ```
  Require a kill report for KILL; conditional absence must be explicit. Reject
  source edits, structural state/counters, invented identities and mismatched
  review routing. Clarification metadata must follow native STOP_AND_ASK rules.
- [x] Run the new contract suite red; extend only semantic decoding and neutral
  role mappings, not runtime admission. Bind reviews to exact author routing.
- [x] Run semantic, candidate, reservation and existing producer contract tests;
  commit only the closed contract/role slice after read-only review.

## Task 3: Retained feasibility producer and structural gate

Files: `discovery_assessment.py`, new `discovery_assessment_gate.py`; existing
`discovery_operation.py`, `discovery_turns.py`, `discovery_receipts.py`,
`discovery_publication.py`, `discovery_completion.py`, `squad.py`, `squad_state.py`;
new `tests/unit/test_managed_feasibility.py`.
Consumes released v30 Phase 1 approval, captured context and Task 1 evaluator.
Produces protected feasibility rounds and native structural completion proof.

First-entry sub-slice completed; the execution/publication milestone below is
still open:

- [x] Authenticate an actual released v30 approval, exact native decision and
  receipt, current identity source head and current quality/debt authorization.
- [x] Extend the existing captured-input owner for first-entry feasibility,
  including exact templates, read-only diagnostics and explicit calibration and
  journal absence. Verify against real retained approvals and a fresh prefix.
- [x] Add protected feasibility rounds to the existing state owner, with exact
  initial approval association, full-state CAS, immutable predecessors and
  round-specific provider/reservation receipts. Structural-retry selection is
  shape-only until the released gate proof and runtime route are implemented.
- [x] Connect first-entry feasibility proposal/author/reviewer composition to
  the shared provider turn and identity-preview owners; retain routing in the
  review assignment, candidate and progress digests. Preserve source issue
  provenance without creating identity or occurrence changes.

- [ ] Add real-parent tests refusing rejection, stale evidence and forged phase
  markers before any dispatch. Positive PASS must stop at
  `phase2-strategic-overview`, not execute strategy implicitly.
- [ ] Extend existing retained selection/component ownership and exact receipt
  decoding for this producer. Capture all declared templates/calibration/journal
  inputs; explicit absence is evidence, not authority to search the host.
- [ ] Publish only reviewed outputs plus graph, then exact captured gate report
  plus graph. Bind counters/configuration/native route into sealed completion.
  ```python
  assert state["phase"] == "phase2-strategic-overview"
  assert identity.identity_history(spec_id="game") == history_before
  assert not state["phase_dispatch_counts"].get("phase3-specialists")
  ```
- [ ] Test scripted Codex/Claude calls, structural retry, changed-input refusal,
  before/after publication interruption and zero-call restart; commit verified work.

## Task 4: Strategy and alignment continuation

Files: existing Task 2/3 modules plus `managed_commander.py` and native human
resolution association; new `tests/unit/test_managed_phase2_alignment.py`.
Consumes actual released feasibility PASS and then actual strategy completion.
Produces native alignment/structural outcome or sealed clarification resolution.

- [ ] Add tests proving strategy cannot run from KILL/DEFER, alignment cannot
  skip strategy, and only assigned derived documents are published.
- [ ] Bind both producers through the same retained rounds, source capture and
  completion owners. Apply Task 1 evaluation to captured alignment output.
- [ ] Connect STOP_AND_ASK to existing native decision sealing, clarification
  and COMMANDER judgment transport, preserving exact resolver provenance.
  ```python
  assert decision["resolved_by"] == "COMMANDER"  # eligible Banzai scripted case
  assert state["phase"] == "phase3-specialists"  # entry only
  assert not state["phase_dispatch_counts"].get("phase3-specialists")
  ```
- [ ] Test ALIGNED/DRIFT and guided/semi/Banzai clarification, repair, stale
  intent/report refusal, interrupted resolution and exact replay; commit.

## Task 5: Native branch, budget and timing parity

Files: existing assessment integration, `squad.py`, `squad_state.py` and
`tests/unit/test_managed_feasibility.py`, `test_managed_phase2_alignment.py`.
Consumes the same accepted outcomes; produces no new policy API.

- [ ] Add literal KILL/DEFER and bounded-loop expectations:
  ```python
  assert killed["phase"] == "done"
  assert deferred["phase"] == "phase1-what"
  assert deferred["defer_count"] == before["defer_count"] + 1
  ```
  Verify exhausted DEFER uses native escalation, not another fresh round budget.
- [ ] Bind KILL report production to the existing publisher and preserve native
  terminal effects. Connect DEFER to existing WHAT repair/review/approval path;
  never let feasibility directly revise source identities or preserve stale proof.
- [ ] Preserve native timing window start/continuation/expiry and cumulative
  provider usage across repair and restart; add cancellation/unknown-call tests.
- [ ] Run native routing/human/state regressions and scripted branch corridors;
  commit after review, without changing defaults or activating installation.

## Task 6: Acceptance and milestone closeout

Files: the new tests, this record, convergence/deferred-scope records.

- [ ] Run both scripted provider paths from real Phase 1 approval through Phase 2,
  including debt, rejection, structural repair/exhaustion, DEFER and clarification.
  Assert exact unchanged requirement history except authorized WHAT revisions.
- [ ] Verify retained reports, context and checkpoints across interrupted state
  application, partial publication, completion and restart without extra calls.
- [ ] Run affected identity, completion, structural, human-decision and provider
  regressions; record exact commands/results and distinguish retained/fresh runs.
- [ ] Obtain read-only review, resolve actionable findings test-first, update
  convergence records, and commit. Leave Phase 3 and public/live activation closed.

## Verification record

Approved Phase 2 scope recorded before implementation. No runtime admission or
Phase 2 acceptance is claimed by creating this plan.

### Task 1 — captured structural evaluation

- Initial red: 22 failures, each at the missing captured-entry assertion.
- Template confinement: two new cases failed before the guard, then passed.
- PASS compatibility: two new cases exposed eager failure-budget evaluation;
  restored native failure-only evaluation, then both passed.
- Fresh verification: `test_captured_governance_gate.py`,
  `test_governance_structural_gate.py`, `test_structural_*.py`: **77 passed**.
- Native `tests/integration/test_squad_controller.py -k 'structural or feasibility
  or alignment'`: **16 passed, 501 deselected**. All pytest invocations used the
  repository virtualenv and the global retention flags above.
- Read-only review: no actionable findings after template confinement. Its
  coverage note is addressed by cold-grammar alignment tests (valid and invalid
  references), allowing only the bundled grammar read, not live input/report I/O.
- No managed runtime caller, provider dispatch, installation or activation added.

### Task 2 — closed Phase 2 producer contracts

- Added assignment versions 9/10/11 for feasibility/strategy/alignment, exact
  output-slot sets, native verdict syntax, empty identity edit scopes and bound
  author routing on reviews. Native selection/operation admission remains closed.
- KILL requires a nonblank kill report. Non-KILL preserves its captured slot
  exactly (including explicit null for absence); it cannot create, erase or
  rewrite prior kill evidence. Existing identity preview rejects unknown
  references and leaves durable history unchanged for all three producers.
- Added six neutral Prosaic producer/reviewer role bodies; no provider-specific
  prose, new COMMANDER role, native decision policy or dispatch path added.
- Initial contract run: **65 failed, 8 passed**; failures identified unsupported
  producers/missing roles, not missing imports. Nine added persisted-reply
  round-trip cases then failed at the older decoder whitelist; extending that
  whitelist uses the same closed decoder and does not admit execution.
- Broader testing exposed two pre-existing Constitution routing-test failures:
  its unchanged HEAD test double omitted `policy_resolution`, already consumed
  by unchanged native completion code. Added only the missing false field to
  that test double; no production completion behavior changed.
- Final combined command used the repository virtualenv, `-q --tb=short` and the
  global retention flags, selecting these unit tests: `test_captured_governance_gate.py`,
  `test_governance_structural_gate.py`, `test_structural_*.py`,
  `test_managed_assessment_contract.py`, `test_discovery_semantics.py`,
  `test_discovery_candidate.py`, `test_discovery_reservations.py`,
  `test_managed_spec_contract.py`, `test_managed_lexicon_contract.py`,
  `test_managed_constitution_contract.py`, `test_discovery_turns.py`,
  `test_prosaic_prompt_loader.py`: **479 passed in 17.43s**.
- Native `tests/integration/test_squad_controller.py -k 'structural or feasibility
  or alignment'`, same interpreter/options: **16 passed, 501 deselected in 5.64s**.
- Read-only review of the contract slice and final decoder/test additions found
  no blockers. `git diff --check` passed. No full-suite or live acceptance claim.
- Next: Task 3 retained feasibility execution and structural completion from an
  actual released Phase 1 checkpoint. Tasks 3–6 remain open; Phase 2 is not active.

### Task 3 first-entry approval and capture sub-slice

- `require_feasibility_parent` authenticates only first entry from the released
  v30 native `checkpoint-assess` approval. It rejects phase-label-only claims,
  rejected/altered decisions, changed receipt/source digests, cancellation and
  non-running state. The current identity source head must still be that exact
  approval, and current quality or accepted-debt evidence remains required.
- The existing `_capture` owner now supports that authenticated first-entry
  context. It uses existing full ancestry/context projectors and source guards;
  no second input inspector was introduced. It captures all five native
  templates, including the actual `kill-report.md` template name, plus required
  source documents and read-only quality/debt/Lexicon diagnostics.
- Calibration/estimates and journal absence is explicit, following the native
  Phase 2 context contract. A real managed prefix may have no journal entries;
  this is recorded as absence rather than fabricated history. Required template
  absence still blocks. Populated evidence preserves exact bytes, including CRLF.
- RED: focused missing-parent-entry assertion failed before implementation.
  Real approved input capture then failed at the old runtime identity-context
  admission because feasibility had no ancestry projection; the added branch
  reuses the existing authenticated projection and passes.
- Five retained real parent corridors passed without editing their state or
  history: user approval/rejection (`pytest-268/test_managed_checkpoint_uses_n0`
  and `n1`), COMMANDER approval (`pytest-259/test_managed_checkpoint_uses_n0`),
  COMMANDER rejection (`pytest-234/test_managed_gate_pass_reaches0`), and accepted
  debt (`pytest-192/test_managed_quality_debt_choi0`). All three approved captures
  also passed, preserving source history and the existing debt authorization.
- Fresh scripted Codex/guided prefix and first-entry parent assertions:
  `tests/unit/test_managed_feasibility.py -k 'real_native_checkpoint and codex'`:
  **1 passed, 3 deselected in 368.32s**. The test process started before the later
  capture assertions were added. Those current helpers were separately executed
  successfully against its fresh `pytest-305/test_feasibility_parent_is_rea0`
  fixture: capture; stale spec/context refusal; missing-template refusal; exact
  populated calibration/estimates/journal bytes; restored absence and recapture.
  Fault helpers changed only test-owned files and restored the originals.
- Regression commands used the repository virtualenv, `-q --tb=short` and the
  global retention flags. `test_discovery_inputs.py`, `test_discovery_operation.py`,
  `test_managed_assessment_contract.py`, `test_captured_governance_gate.py`:
  **232 passed**. `test_discovery_semantics.py`, `test_discovery_candidate.py`,
  `test_discovery_reservations.py`, `test_managed_spec_contract.py`,
  `test_managed_lexicon_contract.py`, `test_managed_constitution_contract.py`,
  `test_discovery_turns.py`, `test_prosaic_prompt_loader.py`: **305 passed**.
  Native `tests/integration/test_squad_controller.py -k 'structural or feasibility
  or alignment'`: **16 passed, 501 deselected**.
- Read-only review found no blocker in this bounded sub-slice. Its populated
  evidence coverage suggestion was addressed with the exact-byte checks above.
  `git diff --check` passed. No fresh Claude prefix or full-suite claim is made.
- Remaining Task 3: protected feasibility rounds/provider turns, exact candidate
  and structural-report publication/completion, native repair and PASS handoff,
  and interruption/replay acceptance. No Phase 2 execution or activation admitted
  by this commit; all later tasks remain open.

### Task 3 protected rounds and reviewed-candidate sub-slice

- Feasibility uses the existing protected round owner, not a new journal or
  state authority. Initial selection retains the exact checkpoint decision and
  resolution receipt. Selection is full-state CAS and idempotent; preparing the
  operation charges the outer `phase2-decide` dispatch exactly once. Structural
  retry shapes retain an accepted predecessor and separate receipt namespace.
- Shape selection is not released-parent authorization. The first-entry proof
  helper now also checks the selected feasibility round: an existing structural
  retry cannot reuse the initial approval. Actual structural retry execution is
  still closed pending its own released gate proof and cumulative native budget.
- Shared neutral turns now protect the entire run directory for feasibility.
  Completed steps replay without another provider call; unknown or malformed
  turns remain frozen. No provider-specific roles, COMMANDER policy changes,
  identity edits or new publication owner were introduced.
- Composition sends empty identity proposal scopes, exact derived-output slots
  and PASS/KILL/DEFER routing instructions. Review is bound to author routing;
  candidate and no-progress digests retain it. Existing issue-report context
  authenticates unchanged source issues; controller diagnostics remain captured
  model evidence rather than being reparsed as identity-definition documents.
- RED: the initial round tests had **15 failed, 4 passed**, at the closed
  producer-selection boundary. After round integration, the provider read-root
  test failed because feasibility had not yet inherited whole-run exclusion;
  adding it to the existing exclusion branch made the test pass.
- The first real retained approval-to-operation check stopped safely with
  `discovery_no_progress` after four scripted calls. Read-only preview diagnosis
  identified `issue_report_context_missing` for the unchanged source `issues.md`;
  the existing issue context path resolves that diagnostic without operations.
  The failed test-owned `pytest-305/test_feasibility_parent_is_rea0` is retained,
  not reset or rewritten to pretend it passed.
- A detached, structurally valid retry round initially passed the first-entry
  approval helper (RED); exact selected-round association now refuses it (GREEN).
- Targeted regressions (repository virtualenv, `-q --tb=short`, global retention
  flags): operation/turn/round/semantic/candidate/reservation/COMMANDER and parent
  suites **472 passed**; kernel state, Tracker round and captured gate suites
  **286 passed**; native structural/feasibility/alignment routing **16 passed,
  501 deselected**; remaining spec/Lexicon/Constitution contracts, Prosaic loader
  and input capture **146 passed**. Final focused feasibility round suite,
  including five additional malformed retained-state cases: **29 passed**.
- Read-only review of both the state/receipt and operation integration deltas
  found no actionable issue. Full KILL/DEFER operation corridors remain Task 5;
  this slice exercises PASS composition and does not admit native routing.
- Retained user rejection (`pytest-268/test_managed_checkpoint_uses_n1`) and
  COMMANDER rejection (`pytest-234/test_managed_gate_pass_reaches0`) still refuse
  feasibility admission. Accepted-debt approval and capture
  (`pytest-192/test_managed_quality_debt_choi0`) pass with unchanged state/history.
- Fresh Codex/guided approval-to-reviewed-candidate corridor, with Lexicon
  disabled: `test_managed_feasibility.py -k 'real_native_checkpoint and codex'`:
  **1 passed, 3 deselected in 523.17s**. Its test-owned fixture is
  `pytest-313/test_feasibility_parent_is_rea0`. This run included
  capture fault checks, populated evidence, exact approval association, three
  scripted turns, unchanged identity history/source files, and two receipt-only
  replays with no additional calls or state changes.
- The first fresh Claude/Banzai run reached released COMMANDER approval but
  failed a fault-test expectation (**1 failed, 3 deselected in 551.35s**,
  `pytest-314/test_feasibility_parent_is_rea0`). Diagnosis traced the refusal to
  native Lexicon freshness: the fault helper restored `spec.md` bytes but left
  its modified timestamp newer than the certified report. The test now restores
  its own captured timestamp and verifies passing capture after each restored
  source/context fault. No production freshness check or report was changed.
- The corrected fault helper and recapture passed against retained
  COMMANDER/Lexicon approval (`pytest-259/test_managed_checkpoint_uses_n0`) and
  the fresh Codex reviewed-candidate fixture (`pytest-313`), including exact
  restored source bytes/mtime and unchanged state/history. Final fast feasibility
  round plus first-entry selection: **30 passed, 3 deselected in 3.22s**.
- Corrected fresh Claude/Banzai approval-to-reviewed-candidate corridor, with
  Lexicon enabled: `test_managed_feasibility.py -k 'real_native_checkpoint and
  claude and banzai'`: **1 passed, 3 deselected in 672.21s**. Its test-owned
  fixture is `pytest-320/test_feasibility_parent_is_rea0`. Native COMMANDER
  judgment approved the checkpoint; the same full capture/fault/three-turn/
  two-replay assertions passed. No live provider calls were made in either run.
- Final staged diff checks passed. The reviewed-candidate slice is verified;
  no full Phase 2, KILL/DEFER integration, publication or activation claim is made.
- Remaining Task 3: exact candidate publication/completion, captured structural
  report publication/completion, native structural retry and PASS handoff, plus
  publication interruption/replay acceptance. Public runtime admission remains
  closed; nothing has been installed or activated.
