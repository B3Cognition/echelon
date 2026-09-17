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

The PASS-feasibility authoring/publication and structural-gate milestone is
verified below. Public managed admission remains closed; KILL/DEFER and timing
parity belong to Task 5, and whole-Phase-2 acceptance remains Task 6.

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
- [x] Add the closed first-entry v31 publication association to the existing
  publisher/completion owner, retaining exact approved v30 ancestry. Confine
  native handoff to `phase2-feasibility-structural`; author verdicts cannot skip
  structural evaluation. This lower-level handoff does not open public managed
  Phase 2 admission or execute the gate.
- [x] Add a closed first-entry v32 structural association using the captured
  native evaluator and existing report/graph publisher, completion and recovery
  owners. Bind the actual released v31 PASS parent, first-attempt counter,
  resolved configuration, exact report bytes and native route. This is a
  report/handoff increment only: it does not authorize retry authoring or open
  public Phase 2 admission.
- [x] Authenticate retry selection/execution from the actual released v32 repair
  gate and its accepted author predecessor, retaining the native counters and
  exact failed report. Publish the reviewed repair with a distinct closed v33
  association through the existing completion owner, returning to structural
  gate entry.
- [x] Add the distinct v34 structural recheck association from the released v33
  repair author. Recover cumulative attempts, configuration and routing from
  its exact authorizing gate; verify PASS and repeated warn/block exhaustion
  through existing publication and interruption recovery.

- [x] Add real-parent tests refusing rejection, stale evidence and forged phase
  markers before any dispatch. Positive PASS must stop at
  `phase2-strategic-overview`, not execute strategy implicitly.
- [x] Extend existing retained selection/component ownership and exact receipt
  decoding for this producer. Capture all declared templates/calibration/journal
  inputs; explicit absence is evidence, not authority to search the host.
- [x] Publish only reviewed outputs plus graph, then exact captured gate report
  plus graph. Bind counters/configuration/native route into sealed completion.
  ```python
  assert state["phase"] == "phase2-strategic-overview"
  assert identity.identity_history(spec_id="game") == history_before
  assert not state["phase_dispatch_counts"].get("phase3-specialists")
  ```
- [x] Test scripted Codex/Claude calls, structural retry, changed-input refusal,
  before/after publication interruption and zero-call restart; commit verified work.
- [x] Verify managed disabled/non-structural bypass and cap-one warn/block
  exhaustion from fresh approval ancestry, without changing native policy.

## Task 4: Strategy and alignment continuation

Files: existing Task 2/3 modules plus `managed_commander.py` and native human
resolution association; new `tests/unit/test_managed_phase2_alignment.py`.
Consumes actual released feasibility PASS and then actual strategy completion.
Produces native alignment/structural outcome or sealed clarification resolution.

- [x] Authenticate strategy entry from the exact released feasibility-gate
  successor and capture its required source/template/context through existing
  input owners. This first slice must not open strategy execution/publication.
- [x] Extend existing protected round/receipt/operation owners for strategy and
  bind its reviewed derived document through a closed v35 publication to the
  actual released feasibility gate. Recover native completion without another
  provider call, stopping at alignment entry; alignment execution stays closed.
- [x] Authenticate first-entry alignment from the actual released v35 strategy,
  capture its exact inputs, and extend existing protected rounds and provider
  composition. Publish reviewed ALIGNED/DRIFT through a closed v36 association
  and recover the native handoff to `phase2-intent-alignment-structural`, without
  executing that gate. STOP_AND_ASK cannot use this ordinary-result association.
- [x] Add closed first-entry v37 alignment structural publication through the
  existing captured evaluator and report/graph completion owner. Verify fresh
  Codex bypass and Claude warning handoffs/recovery to Phase 3 entry without
  executing Phase 3. Full repair/block handoffs, repair authoring and structural
  rechecks remain below; unit routing coverage is not their acceptance evidence.
- [x] Admit the first structural repair only from its released v37 failure,
  retain the accepted alignment predecessor and exact diagnostic evidence,
  publish reviewed repair through v38, and recover to structural recheck entry.
  Recheck publication stays closed until its retained-budget association is
  verified; this checkpoint does not claim a complete alignment repair loop.
- [x] Bind the first repaired alignment structural recheck through a distinct
  v39 association, retaining the released v38/v37 ancestry and native budgets.
  Verify successful recheck, tamper refusal and interrupted completion without
  dispatching Phase 3. Repeated v39-to-author repair remains a later increment.
- [x] Admit subsequent alignment repairs only from an actual released v39
  repair result; retain the entire accepted author/gate chain and original
  limits. Verify unchanged-output retries, warning/block exhaustion, refusal
  of another author after exhaustion, and interrupted publication/recovery.
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

### Task 3 first-entry guarded publication and native handoff sub-slice

- Extended the existing publication/recovery envelope with closed v31
  feasibility association: exact approved v30 checkpoint decision/receipt,
  accepted operation, source capture, matching author/reviewer routing, empty
  identity operations/reservations and unchanged history. The only published
  files are reviewed feasibility outputs and the captured identity graph;
  non-KILL preserves the captured kill-report slot.
- Native completion is confined to `phase2-decide` ->
  `phase2-feasibility-structural`. Direct strategy, Phase 3, terminal and WHAT
  destinations are refused. No new publisher, policy owner, provider prose,
  live-model call or public Phase 2 admission was added.
- Red/green checks used the real retained Codex reviewed-candidate fixture
  (`pytest-313/test_feasibility_parent_is_rea0`). Publication initially lacked
  the producer-specific envelope; after that addition, the destination test
  proved that structural skipping was accepted until the native guard was
  added. Initial standalone replay also correctly rejected a different Prosaic
  inspector; retained scripted receipts were subsequently replayed with their
  original test inspector, without weakening production receipt matching.
- Read-only review identified a historical checkpoint validation error: after
  native advancement, v30 live-effects decoding still required the old phase.
  A real retained Claude/Banzai checkpoint reproduced it. Released ancestry
  now uses its authenticated historical proof, preserving current genesis,
  bootstrap, native parent/COMMANDER evidence and exact resolution receipt.
  Direct live decoding still rejects advanced state, and changed receipt,
  identity or bootstrap is refused. Follow-up review found no remaining issue.
- The retained Codex continuation recovered interruptions before promotion,
  after batch promotion and after identity application, then released at
  structural-gate entry. Exact published bytes/graph, unchanged identity
  history and zero-call settled replay were verified. A test-only field-name
  typo was corrected to the native `feasibility_verdict`; the two in-progress
  fresh prefixes were deliberately interrupted and restarted with the corrected
  assertions. Those interrupted runs (`pytest-323`/`pytest-324`) are not passes.
- A stricter fresh-run assertion then exposed that the test's supposed
  per-file interruption wrapped the whole promotion loop: all five writes were
  already present. The test now injects through the publisher's existing
  position fault hook at position 1 and requires a nonempty, incomplete prefix
  before recovery. No publication implementation or source guard was changed.
  The two pre-correction runs (`pytest-326`/`pytest-327`) failed that assertion
  after reaching native handoff and are not passes. With the corrected hook,
  the complete publication/negative-binding/historical-proof/handoff helper
  sequence passed against retained Claude/Banzai candidate `pytest-320`,
  including exact partial-prefix recovery, post-identity-apply recovery,
  unchanged history/dispatch counts, one usage charge and zero extra calls.
- Post-change focused completion/state/contracts/checkpoint/captured-gate
  regression group (`test_squad_completion.py`, `test_managed_assessment_contract.py`,
  `test_managed_feasibility_rounds.py`, `test_managed_constitution_contract.py`,
  `test_discovery_checkpoint.py`, `test_captured_governance_gate.py`,
  `test_governance_structural_gate.py`): **435 passed in 141.92s**. Native structural/feasibility/
  alignment routing: **16 passed, 501 deselected in 5.73s**. The earlier shared
  publication/completion/contracts group passed **219 tests** before the
  historical-checkpoint fix. Final shared regression (`test_discovery_completion.py`,
  `test_discovery_publication.py`, `test_discovery_restoration_completion.py`,
  `test_managed_lexicon_contract.py`, `test_managed_lexicon_rounds.py`):
  **153 passed in 361.48s**. All pytest runs use the repository virtualenv,
  `-q --tb=short`, and global retention flags; the native selection uses
  `tests/integration/test_squad_controller.py -k 'structural or feasibility or alignment'`.
- Corrected fresh Codex/guided corridor, Lexicon disabled:
  `test_managed_feasibility_publication.py -k codex`:
  **1 passed, 1 deselected in 698.67s**. Fixture
  `pytest-330/test_real_review_seals_only_fe0` is now a released v31 input at
  `phase2-feasibility-structural`, with no structural/Phase 3 execution. This
  includes fresh approved ancestry, reviewed provider receipts, closed negative
  cases, all three corrected interruptions, exact publication and zero-call replay.
- Corrected fresh Claude/Banzai corridor, Lexicon enabled:
  `test_managed_feasibility_publication.py -k claude`:
  **1 passed, 1 deselected in 916.60s**. Fixture
  `pytest-331/test_real_review_seals_only_fe0` is likewise a released v31 input
  at structural-gate entry. The native COMMANDER approval route, extra Lexicon
  ancestry, all corrected crash boundaries and no-extra-call replay passed.
  Neither fresh corridor made live provider calls. Final verification totals
  **606 passing focused tests**, excluding earlier, interrupted and faulty-hook
  runs. Both faulty-hook fixture completions (`pytest-326`/`pytest-327`) were
  also safely drained and released with exact bytes and no extra calls/charges.
- Read-only review and follow-up are complete with no remaining actionable
  findings. Final diff checks passed. The native handoff is verified, but the
  structural evaluation/report itself and public runtime admission remain open.
- Retained user rejection (`pytest-268/test_managed_checkpoint_uses_n1`) and
  COMMANDER rejection (`pytest-234/test_managed_gate_pass_reaches0`) still refuse
  first-entry feasibility after the historical-proof change.
- Remaining Task 3: captured structural report publication/completion, released
  gate retry authority, native PASS handoff to strategy, and public managed
  Phase 2 admission only when its full approved corridor is ready. Structural
  evaluation was not executed by this publication/handoff slice; Task 3 is not
  complete and Phase 2 remains inactive.

### Task 3 first structural report/handoff increment

- Added `discovery_assessment_gate.py`, the association module already named
  by Task 3. It consumes the existing captured governance evaluator; it does
  not add another gate policy, allocator, publisher, decision owner or model
  role. Only the fixed feasibility report and captured graph may be written.
- The closed v32 proof requires actual released first-entry v31 PASS authoring,
  unchanged identity history, no identity operations, zero prior structural
  attempts and no pre-existing structural report. Captured inputs determine the
  exact report/result; current source/config guards and native completion
  authenticate publication and recovery. KILL/DEFER and structural retry
  authoring remain unadmitted in this slice.
- Native transition literals are checked against the workflow definition and
  replayed with the existing condition evaluator. The completion owner rejects
  changed destinations, including skipping to Phase 3. Native repair increments
  iteration once; a successful gate hands off to strategy without dispatching
  its provider. No workflow definition, provider prose, Banzai decision policy,
  installation or public managed admission was changed.
- Red tests first failed for the absent adapter/preparation entry point. Two
  test setup errors were corrected: dependency schemas must load before the
  no-input-I/O check, and the workflow list is `phases`, not `nodes`.
- Retained Codex `pytest-330/test_real_review_seals_only_fe0` and Claude/Banzai
  `pytest-331/test_real_review_seals_only_fe0` now have released v32 completion
  `cccccccccccccccccccccccccccccccc`, native repair handoff, attempts=1 and
  iteration=1. Their deliberately incomplete authored documents failed the
  unmodified structural rules. Report/graph publication, interruption after
  identity application, recovery, unchanged history, unchanged dispatch/usage
  counts and settled zero-call replay passed on both retained corridors.
  On both, the original checkpoint approval is also explicitly refused as
  authority for another feasibility operation after the gate's repair handoff.
- The Codex continuation initially hit a test-only assertion: graph bytes can
  remain unchanged in report-only publication, so counting equal postimages
  does not prove the physical promotion position. The test now asserts the
  actual publisher fault hook fired at position 1. Its existing pending
  completion was then safely recovered; no receipt/source reset was used.
  Claude subsequently passed the full corrected helper sequence, including
  that per-operation interruption.
- A further negative test reproduced Python's `True == 1` equality loophole in
  the new result decoder. Canonical JSON comparison now rejects boolean, float
  and string substitutions for the integer attempt count. The actual retained
  report still decodes; the typed-result regression is in the managed helper.
- Read-only review and a follow-up found no remaining code issue. Review noted
  that native bypass and first-attempt warn/block exhaustion still need full
  managed publication/handoff coverage before activation; their captured
  evaluation, counter outcomes and native route selection are unit-tested.
- Verification so far: focused contracts/state/completion/checkpoint/gates
  **462 passed in 140.39s**; shared publication/completion/restoration and
  Lexicon contracts/rounds **153 passed in 351.07s**; native structural,
  feasibility and alignment routing **16 passed, 501 deselected in 5.61s**.
  All pytest commands use the repository virtualenv and retention flags.
  A post-type-fix contracts/state/completion rerun passed **378 tests in 6.38s**
  (overlaps the 462 above; do not add it to the unique test total).
- Fresh Codex/guided, Lexicon-disabled repair corridor:
  `test_managed_feasibility_gate.py::test_reviewed_feasibility_gate_uses_guarded_report_handoff[codex-guided-False]`:
  **1 passed in 722.74s**. Fixture
  `pytest-337/test_reviewed_feasibility_gate0` is a released v32 native repair
  handoff at `phase2-decide`, attempts=1 and iteration=1, with no retry dispatch.
- Fresh Claude/Banzai, Lexicon-enabled successful structural corridor:
  `test_managed_feasibility_gate.py::test_valid_claude_banzai_feasibility_reaches_strategy_without_dispatch`:
  **1 passed in 874.24s**. Fixture `pytest-339/test_valid_claude_banzai_feasi0`
  is a released v32 handoff at `phase2-strategic-overview`, attempts=0 and
  iteration=0. Native COMMANDER approval, valid reviewed feasibility, exact
  report/graph publication, both interruption boundaries and zero-call recovery
  passed. STRATEGIST and Phase 3 were not dispatched.
- Post-run inspection with the final decoder confirmed both fresh released
  handoffs and rejected boolean, float and string counter substitutions for
  both repair (1) and pass (0). Unique final verification total: **633 passing
  focused tests**, plus the retained-corridor checks above. This is not a claim
  that the full repository suite, every policy branch or live activation ran.
- Remaining Task 3: released gate retry authority and reviewed retry execution,
  remaining policy-branch managed handoff coverage, and public Phase 2 admission
  only after the complete approved corridor is ready. Strategy/alignment,
  terminal/defer paths and activation tasks remain open. Task 3 is not complete.

### Task 3 released repair authority and reviewed retry publication

- The existing feasibility parent check now distinguishes initial approval from
  an actual released v32 structural repair. Repair admission verifies the exact
  gate receipt, accepted predecessor, current identity source head, quality/debt
  authority, resolved configuration, complete native result and strict integer
  iteration/attempt/cap values. An old checkpoint approval cannot restart a
  repair or reset its budget. Protected round selection remains the same owner.
- Capture supplies the exact failed structural report as read-only model
  evidence, alongside the existing document/template/runtime inputs. The report
  is neither an identity-definition source nor a provider-writable output.
  Reviewed repairs retain empty identity operations and unchanged history.
- A distinct v33 association retains the gate source and accepted predecessor;
  v31 initial approval and v32 first-gate contracts remain unchanged. Existing
  ancestry validation walks through the actual repair gate and prior author.
  Native completion returns only to `phase2-feasibility-structural`, preserves
  cumulative attempts/iteration and authenticates their exact values on recovery.
- Red checks first refused the released repair as a non-checkpoint source, then
  refused its captured structural report, and finally refused publication under
  the original first-entry decoder. A separate red completion check accepted an
  altered iteration; the new v33 live authentication rejects changed values and
  boolean/float/string counter substitutions through canonical JSON comparison.
- The shared publication fault helper now records the actual per-operation
  promotion hook. Counting unequal bytes is not a valid interruption assertion
  when a repair legitimately preserves most published documents byte-for-byte.
- Implementation stays inline. Read-only review of the bounded increment and
  final counter/fault-test delta found no critical or important findings. No
  provider prose, Banzai decision route, allocator, policy owner, installation,
  migration, public admission, live calls, merge or push changed in this increment.
- Retained real Codex repair (`pytest-337/test_reviewed_feasibility_gate0`) and
  Claude/Banzai/Lexicon repair (`pytest-331/test_real_review_seals_only_fe0`) both
  passed exact parent/negative checks, three scripted repair turns, no-call
  reviewed replay, closed v33 publication, native handoff and interrupted
  recovery. Both now retain released completion `dddddddddddddddddddddddddddddddd`
  at structural-gate entry, attempts=1 and iteration=1. No state/history reset
  or live provider call was used. The Codex completion additionally supplied
  the red/green live-counter test; both pass all final typed-counter negatives.
- Retained user rejection (`pytest-268/test_managed_checkpoint_uses_n1`) and
  COMMANDER rejection (`pytest-234/test_managed_gate_pass_reaches0`) remain
  inadmissible. The passing v32 gate at
  `pytest-339/test_valid_claude_banzai_feasi0` cannot authorize a repair even with
  a forged `phase2-decide` label. Those checks left all three fixtures unchanged.
- Focused regression command, repository virtualenv, `-q --tb=short` and global
  retention flags: `test_discovery_inputs.py`, `test_discovery_operation.py`,
  `test_discovery_turns.py`, `test_discovery_semantics.py`, `test_discovery_candidate.py`,
  `test_discovery_reservations.py`, `test_prosaic_prompt_loader.py`,
  `test_squad_completion.py`, `test_managed_feasibility_rounds.py`,
  `test_managed_assessment_contract.py`, `test_discovery_assessment_gate.py`,
  `test_captured_governance_gate.py`, `test_governance_structural_gate.py`:
  **767 passed in 93.11s**. This process preceded the final live v33 counter guard;
  the final completion group and actual retained corridors verify that guard.
  Native `tests/integration/test_squad_controller.py -k 'structural or feasibility
  or alignment'`: **16 passed, 501 deselected in 5.65s**.
- Shared completion/publication/restoration group after the live counter guard,
  before the subsequent active-source guard: `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py`, `test_squad_completion.py`:
  **352 passed in 373.05s**. The last file overlaps the 767-test group; these
  counts must not be added as unique tests. Same interpreter/options as above.
- The first fresh retry test failed after **504.72s** at the existing detached
  retry negative, before publication. Looking up a round by the supplied source
  could retrieve the now-inactive initial approval; when the identity head was
  still checkpoint, the source-head guard alone did not refuse it. The exact
  failure reproduced on `pytest-349/test_released_structural_gate_0`. Requiring
  an existing source round to be active before either admission branch fixes
  it; the same negative passes and the genuinely active approval still works.
  No fixture state was rewritten. Added a fast round regression that verifies
  refusal before identity lookup, and obtained follow-up read-only review of
  that fix. The failed fresh run is not counted as a passing corridor.
- After the active-source fix and added fast regression, feasibility rounds,
  assessment contracts and structural associations passed **154 tests in 4.02s**.
  Same interpreter/options as above; this overlaps the earlier 767-test group.
- The complete shared completion/publication/restoration group was rerun after
  that fix: **352 passed in 371.51s**. Same selection/options; this replaces,
  rather than adds to, the earlier 352-test result.
- The complete final helpers also passed against the unused retained Codex
  repair at `pytest-330/test_real_review_seals_only_fe0`: real authority,
  reviewed repair, exact failed-report feedback, zero-call replay, changed
  spec/report/context refusal without state changes, v33 publication, native
  handoff, all interruption boundaries and strict live budgets. This fixture
  now has released v33 completion `dddddddddddddddddddddddddddddddd`, at
  structural-gate entry with attempts=1 and iteration=1.
- Read-only captured evaluation of the repaired documents in retained
  `pytest-337` and `pytest-331` reports PASS under their existing configuration,
  using previous_attempts=1. This preview did not publish a second report or
  perform a structural transition, and is not claimed as managed second-gate
  acceptance.
- Corrected fresh Codex/guided, Lexicon-disabled full prefix and repair:
  `tests/unit/test_managed_feasibility_retry.py -k codex -q --tb=short` with the
  repository virtualenv and global retention flags: **1 passed, 1 deselected
  in 1005.65s**. Fixture `pytest-352/test_released_structural_gate_0` includes
  real approved Phase 1 ancestry, first reviewed author and failed structural
  gate, exact retry authorization, reviewed repair, changed-input refusal,
  both publication generations, interruption/recovery, no-call replay and
  altered-counter refusal. It ends with released v33 completion
  `dddddddddddddddddddddddddddddddd`, two outer feasibility dispatches,
  attempts=1 and iteration=1, without executing the next gate or Phase 3.
  No fresh Claude prefix or full repository suite was rerun for this increment;
  the retained Claude continuation is reported separately above. Final diff
  checks passed. No live acceptance or public activation is claimed.
- Remaining Task 3: evaluate/publish the next structural gate from the released
  v33 author while retaining the prior budget, plus remaining managed bypass and
  exhaustion policy branches. Strategy/alignment, terminal/defer routes and
  activation remain open; this is not completion of Task 3 or Phase 2.

### Structural rechecks and cumulative exhaustion (v34)

- Extend the existing captured feasibility gate to consume a released v33
  reviewed repair. The distinct v34 association recovers prior attempts from
  that author's exact released repair gate, retaining its configuration and
  routing counters. V32 remains first-entry-only. Repeated v33/v34 ancestry
  uses the existing authority, completion and guarded publication owners.
- Native governance still decides PASS, repair, warning or block. A passing
  recheck resets attempts through native policy; a failed recheck consumes the
  original budget. No workflow, provider prose, Banzai decision route or public
  admission changes are part of this increment.
- An actual retained gate exposed the live authentication typed-counter gap:
  with Python equality restored, the negative test failed with `DID NOT RAISE`
  for a boolean/numeric substitution. Canonical JSON comparison plus a strict
  integer iteration guard makes the same actual gate reject boolean, float,
  string and changed counter values. The final retained Codex PASS completion
  passes all of those negatives without state changes.
- Retained Codex `pytest-337/test_reviewed_feasibility_gate0` and
  Claude/Banzai/Lexicon `pytest-331/test_real_review_seals_only_fe0` both passed
  v34 PASS publication, exact report/graph checks, partial promotion and
  post-identity-apply recovery, release and zero-call replay. Both reach
  `phase2-strategic-overview` with attempts=0 and iteration=1, without executing
  strategy. These are retained continuations, not fresh prefixes.
- Final preparation-refusal helper also passed against the unused released
  v33 author at `pytest-352/test_released_structural_gate_0`. Cloned reset,
  inflated and typed attempts, changed/typed iteration, changed cap, forged
  receipt and injected policy override all refuse before publication. Actual
  durable state, requirement history and pending publication remain unchanged.
- Final focused command uses the repository virtualenv, `-q --tb=short` and
  the global retention flags, with `test_discovery_assessment_gate.py`,
  `test_captured_governance_gate.py`, `test_governance_structural_gate.py`,
  `test_squad_completion.py`, `test_managed_feasibility_rounds.py` and
  `test_managed_assessment_contract.py`: **421 passed in 7.70s**. The previous
  invalid-state fixture now uses -1 rather than 1: positive retained attempts
  are valid only when authenticated by the released repair ancestry.
- Native `tests/integration/test_squad_controller.py -k 'structural or
  feasibility or alignment'`, same interpreter/options: **16 passed,
  501 deselected in 5.68s**. Bounded read-only review found no critical or
  important findings; the reviewer did not run tests or mutate files.
- Shared `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py` and `test_squad_completion.py`,
  same interpreter/options: **352 passed in 372.48s**. The completion file
  overlaps the focused group; these counts are not a unique-test total.
- Fresh Codex/guided, Lexicon-disabled blocking corridor:
  `tests/unit/test_managed_feasibility_recheck.py -k 'exhaust and codex'`,
  same interpreter/options: **1 passed, 3 deselected in 1150.12s**. Fixture
  `pytest-357/test_rechecks_exhaust_original0` set cap=2/block before managed
  bootstrap, then executed actual Phase 1 approval, first author/gate, reviewed
  repair and v34 recheck with publication interruptions, recovery and no-call
  replay. Final state is `terminal-blocked`, status=blocked, attempts=2 and
  iteration=1. Exhausted proof cannot authorize another repair even with forged
  phase/status labels. No strategy or Phase 3 dispatch occurred. This run was
  started before the additional preparation-refusal helper was added; that
  helper's independent retained verification is recorded above.
- Retained Claude/Banzai/Lexicon warning corridor continued from the unused
  released v31 author at `pytest-320/test_feasibility_parent_is_rea0`, without
  changing its existing cap=3/warn configuration. The first v32 failed gate
  and two successive reviewed v33 repair/v34 recheck cycles passed the same
  publication, exact ancestry, cumulative accounting, changed-input refusal,
  interruption/recovery and live typed-counter helpers. Final state is
  `phase2-strategic-overview`, status=running, attempts=3, iteration=2 and
  `structural_action=proceed_with_warning`; strategy and Phase 3 were not
  dispatched. Exhausted proof cannot authorize another repair. The standalone
  continuation used the exact fixture-bound Prosaic inspector and scripted
  provider, not a weakened production check or live call. This process also
  preceded the additional preparation-refusal helper, verified separately above.
- No identity/history reset, new policy owner, live model spending, installation,
  migration, merge, push or public activation occurred. Remaining Task 3 checks
  include managed bypass and first-attempt exhaustion branches. Strategy and
  alignment, KILL/DEFER/timing parity and final acceptance remain open. This
  increment does not complete Task 3 or the full Phase 2 milestone.

### First-check bypass and exhaustion coverage

- Added `test_managed_feasibility_policy.py` with fresh approval-to-gate
  corridors for globally disabled governance, a non-structural feasibility
  tier, cap=1/block and cap=1/warn. Configuration is set before managed
  bootstrap, not rewritten underneath retained authority. Codex/guided uses
  Lexicon disabled; Claude/Banzai uses Lexicon enabled and COMMANDER approval.
- Extended only the shared test helpers for graph-only publication. Bypass
  expectations require no report, no attempt charge and no exhausted marker;
  cap-one expectations require native warning/block after exactly one author
  dispatch. Every case checks unchanged requirement history, no implicit
  strategy/Phase 3 dispatch, strict live counters and no repair authority.
- A graph-only transaction interrupts after its sole operation, before
  identity application. Report-producing transactions retain their existing
  partial-promotion test. Both use the existing post-identity-apply recovery,
  actual release and zero-call replay assertions. No production code or policy
  changes were made for this coverage slice.
- Read-only review found no actionable findings, including review of the
  graph-only interruption boundary. The reviewer ran no tests or mutations.
- Focused command with the repository virtualenv, `-q --tb=short` and global
  retention flags: `test_discovery_assessment_gate.py`,
  `test_captured_governance_gate.py`, `test_governance_structural_gate.py`,
  `test_squad_completion.py`, `test_managed_feasibility_rounds.py` and
  `test_managed_assessment_contract.py`: **421 passed in 8.08s**.
- Native `tests/integration/test_squad_controller.py -k 'structural or
  feasibility or alignment'`, same interpreter/options: **16 passed,
  501 deselected in 5.79s**.
- Fresh policy commands use `tests/unit/test_managed_feasibility_policy.py`
  with one `-k` selector each, the repository virtualenv and the same options:
  - `disabled`: **1 passed, 3 deselected in 793.54s**;
    `pytest-362/test_first_gate_preserves_nati0` reaches strategy entry with
    attempts=0 and no structural report or strategy execution.
  - `block`: **1 passed, 3 deselected in 791.08s**;
    `pytest-364/test_first_gate_preserves_nati0` reaches `terminal-blocked`,
    status=blocked, attempts=1, iteration=0 and the native exhausted reason.
  - `nonstructural`: **1 passed, 3 deselected in 1037.68s**;
    `pytest-363/test_first_gate_preserves_nati0` reaches strategy entry with
    attempts=0 and no structural report or strategy execution.
  - `warn`: **1 passed, 3 deselected in 1035.28s**;
    `pytest-365/test_first_gate_preserves_nati0` reaches strategy entry with
    attempts=1, iteration=0 and `proceed_with_warning`, without strategy
    execution. Both Claude cases retain actual COMMANDER approval provenance.
- All four fresh cases completed publication/recovery, strict live counter
  checks and refusal of forged repair authority. These tests exercise existing
  behavior and passed without a production change; no fix or red/green defect
  reproduction is claimed. No additional full repository suite was run for
  this test-only slice. Final diff checks passed.
- Task 3's PASS-feasibility/structural milestone is now verified across the
  recorded increments. This is not public activation or full Phase 2 acceptance.
  Next is Task 4's strategy/alignment continuation from actual released gate
  proofs, followed by Task 5 branch/timing parity and Task 6 acceptance. No live
  calls, installation, migration, merge or push occurred in this increment.

### Task 4 — strategy admission and captured inputs

- Added current strategy-parent authentication to the existing assessment
  owner. It requires an actually released v32/v34 gate routed to strategy with
  a PASS author verdict, exact current dispatch and source head, no pending
  transaction, and current quality/debt authority. The existing completion
  authenticator receives the actual saved proof and checks native counters,
  configuration and full ancestry. There is no parallel gate policy.
- Extended the existing captured-input reader for strategy's sole output slot,
  `strategic-overview.md`, its template and authenticated source/context. Exact
  structural/Lexicon/debt diagnostics remain read-only evidence, not identity
  definitions. Journal absence is explicit; no host search is authorized.
- Red tests first exposed the missing strategy-parent admission; both a minimal
  forged phase and an actual released Codex gate failed at that missing entry.
  After admission was implemented, the actual capture failed with
  `discovery_runtime_identity_context_not_admitted` because strategy lacked
  authenticated released-input projection. The same retained capture and its
  changed-input checks passed after connecting the existing projectors.
- Strategy retained rounds, provider execution, publication and all alignment
  continuation remain closed. This is only the first Task 4 sub-slice; no
  provider prose, COMMANDER behavior, policy owner or activation changed.
- Bounded read-only review found no actionable findings and ran no tests or
  mutations. It noted that repaired/PASS gate coverage relies on the retained
  matrix; the new fresh parametrization covers bypass/warning ancestry.
- Focused command with the repository virtualenv, `-q --tb=short` and global
  retention flags: `test_discovery_inputs.py`, `test_discovery_operation.py`,
  `test_discovery_turns.py`, `test_discovery_semantics.py`,
  `test_discovery_candidate.py`, `test_discovery_reservations.py`,
  `test_prosaic_prompt_loader.py`, `test_managed_assessment_contract.py`,
  `test_managed_feasibility_rounds.py`, `test_discovery_assessment_gate.py`:
  **501 passed in 90.18s**. Minimal forged-phase negative:
  `tests/unit/test_managed_strategy.py -k phase_label`, same options:
  **1 passed, 2 deselected in 0.44s** after the observed red failure.
- The final retained strategy helpers passed admission, altered-state refusals,
  exact capture and changed feasibility/report/context refusal for six actual
  released gate successors: Codex bypass `pytest-362`, Claude non-structural
  bypass `pytest-363`, Claude warning `pytest-365`, Claude first PASS
  `pytest-339`, Codex repaired PASS `pytest-337` and Claude repaired PASS
  `pytest-331`. The policy fixtures use `test_first_gate_preserves_nati0`;
  other fixture names are recorded in the preceding gate verification sections.
  Thus both v32 and v34 predecessors are exercised. The exact fixture-bound
  Prosaic inspector was used; no production authentication was replaced.
- Actual one-attempt block `pytest-364`, repeated-exhaustion block `pytest-357`
  and not-yet-rechecked author `pytest-352` all refused strategy admission even
  with forged strategy/running/PASS labels. No fixture state, history, identity
  head or proof was rewritten. Changed-input fault checks restored exact bytes
  and timestamps. These are retained checks, not new full prefixes.
- Shared completion/publication/restoration command with the same interpreter
  and options: `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py`, `test_squad_completion.py`:
  **352 passed in 368.40s**. No full repository or live-provider suite was run.
- Fresh Codex/guided, Lexicon-disabled run:
  `tests/unit/test_managed_strategy.py -k codex`, same interpreter/options:
  **1 passed, 2 deselected in 808.26s**. The actual Phase 1 approval, reviewed
  feasibility author, bypass publication/recovery and released gate precede
  strategy admission/capture in `pytest-370/test_strategy_captures_release0`.
  Altered receipt/verdict/counter/phase and changed input checks all passed.
  No strategy dispatch occurred. The fresh Claude parametrization was not run
  this increment; its actual retained warning/PASS/repaired cases passed above.
- Final diff checks passed. Commit only this admission/capture increment; no
  installation, migration, activation, merge or push. Next is protected strategy
  round selection, reviewed provider execution and publication/native handoff
  through the existing owners. Alignment and whole Task 4 remain unfinished.

### Strategy execution and guarded handoff (2026-09-17)

- Added strategy to the existing retained round, operation, turn and receipt
  owners. Selection requires an exact settled feasibility-gate source and full
  state CAS; ordinary saves cannot replace protected components. This first
  strategy round has no resolution or repair predecessor. Provider contracts
  stay neutral Prosaic, with no identity allocation/revision scope.
- Shared composition retains the exact DONE routing in author/reviewer receipts,
  candidate and progress digests. Feasibility/Lexicon/debt diagnostics remain
  captured evidence, not duplicate identity definitions. Existing issue
  provenance is retained without identity operations or history changes.
- The existing publisher/completion owner now accepts a closed v35 strategy
  association. It authenticates the actual released v32/v34 proceeding PASS gate,
  source chain, native state/counters and configuration. Only reviewed
  `strategic-overview.md` plus the recomputed graph may publish. Native completion
  permits only `phase2-tracker-alignment`; alignment and Phase 3 do not execute.
- RED strategy selection failed with `invalid specification producer` before
  wiring. Round-owner verification then passed **41 tests in 4.34s**. The first
  retained execution attempt on `pytest-362/test_first_gate_preserves_nati0`
  retained rejected attempt receipts before composition was connected; those
  receipts were not reset or rewritten. A separate actual released parent was
  used for the successful final execution.
- Retained Codex/guided bypass parent
  `pytest-370/test_strategy_captures_release0` passed exact three-call/21-token
  author/review and zero-call replay. Publication RED failed at the absent v35
  association before implementation. Final publication, forged-binding refusal,
  wrong-route refusal, strict counter/type checks, interruptions before promotion,
  after partial promotion and after identity application, and zero-call/idempotent
  recovery all passed. Identity history and accumulated counters stayed unchanged;
  canonical strategy/graph postimages matched and alignment was not dispatched.
- With the repository virtualenv, `-q --tb=short` and the global retention flags,
  `test_discovery_operation.py`, `test_discovery_turns.py`,
  `test_discovery_semantics.py`, `test_discovery_candidate.py`,
  `test_discovery_reservations.py`, `test_managed_assessment_contract.py`,
  `test_managed_strategy_rounds.py`, `test_managed_feasibility_rounds.py` passed
  **404 tests in 64.28s**. Shared `test_discovery_completion.py`,
  `test_discovery_publication.py`, `test_discovery_restoration_completion.py`,
  `test_squad_completion.py` passed **352 tests in 374.22s**.
- Bounded read-only reviews of execution and publication found no actionable
  findings. No tests, writes or additional agents were delegated by the reviewer.
  These results do not claim whole-Phase-2 acceptance or live/public activation.
- Retained Codex repaired-PASS parent
  `pytest-337/test_reviewed_feasibility_gate0` also passed the complete strategy
  execution, publication, tamper/refused-route checks and interrupted handoff
  helpers, preserving iteration 1 and the actual v34 gate ancestry. The retained
  checks used the exact fixture-bound Prosaic inspector, not replacements for
  production authentication or source authority.
- Fresh Claude/Banzai with Lexicon enabled and cap-one warning policy:
  `tests/unit/test_managed_strategy_execution.py -k claude`, same interpreter
  and options: **1 passed, 1 deselected in 1247.40s**. Actual Phase 1 approval,
  reviewed feasibility, structural publication/recovery and released warning
  gate precede strategy's three-call author/review and zero-call replay in
  `pytest-376/test_released_gate_authorizes_0`. Strategy preserved the original
  requirement history and warning gate's one attempt. The fresh Codex
  parametrization was not rerun; its retained bypass/repaired checks are above.
- The same fresh Claude run was then continued in place with the publication,
  closed-binding and interrupted-handoff helpers in
  `test_managed_strategy_publication.py`. All passed, including the warning
  counter's exact type/value, zero additional provider calls and settled
  idempotent recovery at alignment entry. This was a continuation of the fresh
  prefix, not a second fresh full-prefix pytest invocation.
- Final diff checks passed. Commit this verified strategy increment only; no
  installation, migration, activation, live model calls, merge or push. Next is
  alignment entry/producer/publication and its native structural/clarification
  routes within Task 4; Task 4 and the Phase 2 milestone remain unfinished.

### Ordinary alignment execution and guarded handoff (2026-09-17)

- Added first-entry alignment admission to the existing assessment owner. It
  authenticates the actual released v35 strategy, exact settled dispatch and
  identity head, underlying v32/v34 feasibility ancestry, current counters and
  configuration, and current Phase 1 quality/debt authority. A phase label or
  an earlier released gate alone cannot authorize alignment.
- Extended the existing capture, protected round, operation, turn and receipt
  owners. Alignment has one first-entry round, no resolution or repair
  predecessor, and no identity allocation/revision scope. Its exact source,
  context and template are captured; diagnostics remain read-only evidence.
  Neutral Prosaic contracts serve both providers without provider-specific prose.
- The existing publisher/completion owner now admits a closed v36 association
  for ALIGNED/DRIFT only. Reviewed alignment report and recomputed graph are the
  sole writes. Exact strategy/gate ancestry, native counters/configuration and
  author/reviewer routing are authenticated. Native completion clears its usual
  transient warning/reason fields and stops at alignment structural-gate entry.
  STOP_AND_ASK remains closed until its native decision association is connected.
- RED admission failed at the missing parent entry; the first actual capture
  then failed at the missing released-input wiring. RED round selection failed
  with `invalid specification producer`. After wiring, focused alignment/strategy
  owner and minimal-parent checks passed **23 tests, 2 deselected in 2.14s**.
- Parent admission, changed-state/source refusals, exact capture and changed-input
  checks passed on actual retained Codex bypass strategy
  `pytest-370/test_strategy_captures_release0` and Claude warning strategy
  `pytest-376/test_released_gate_authorizes_0`. Repaired-PASS strategy
  `pytest-337/test_reviewed_feasibility_gate0` also passed parent/capture checks;
  its subsequent RED execution retained rejected attempt receipts before shared
  composition was connected. Those receipts were not reset or rewritten.
- Actual retained released-gate-only `pytest-339`, blocked-gate `pytest-364`,
  and not-yet-rechecked repair `pytest-352` refused alignment despite forged
  alignment/running/PASS labels. No state or identity authority was rewritten.
- Final retained Codex ALIGNED and Claude DRIFT author/review helpers passed
  three scripted calls/21 tokens apiece, unchanged canonical inputs/history,
  and exact zero-call replay. Publication RED exposed the missing v36 binding.
  After implementation, both passed publication, forged-binding and wrong-route
  refusals, strict live counter/type checks, interruption before promotion,
  after partial promotion and after identity application, and idempotent recovery.
  Canonical postimages matched, identities/history and prior dispatch/budget
  counters were preserved, and the 21-token completion charge was applied once.
  Neither alignment structural evaluation nor Phase 3 was dispatched.
- These are continuations of previously recorded real scripted prefixes, not new
  full-prefix pytest runs. The exact fixture-bound Prosaic inspector was used;
  production authentication was not replaced. New parametrized full-prefix tests
  are included, but their complete prefixes were not rerun in this increment.
- With the repository virtualenv, `-q --tb=short` and global retention flags,
  `test_discovery_operation.py`, `test_discovery_turns.py`,
  `test_discovery_semantics.py`, `test_discovery_candidate.py`,
  `test_discovery_reservations.py`, `test_managed_assessment_contract.py`,
  `test_managed_alignment_rounds.py`, `test_managed_strategy_rounds.py`,
  `test_managed_feasibility_rounds.py`: **415 passed in 62.73s**.
- Shared completion/publication/restoration regression with the same interpreter
  and options: `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py`, `test_squad_completion.py`:
  **352 passed in 340.01s**. Final diff checks passed. These selected regressions
  are not a full repository or live-provider acceptance claim.
- Bounded read-only execution and publication reviews found no actionable
  findings and ran no tests or mutations. The optional cleanup-assertion coverage
  note concerns alignment structural fields not produced by this first-entry
  slice; existing native cleanup remains unchanged.
- This increment does not complete Task 4 or whole Phase 2. Alignment structural
  publication, repair/retry/exhaustion, native clarification and existing COMMANDER
  routing, remaining branch/timing parity and full acceptance remain. No installed
  workspace, public activation, live provider, merge or push changed.

### First alignment structural publication (2026-09-17)

- Extended the existing assessment-gate adapter, sealed report/graph publisher
  and completion decoder for closed v37 `alignment_gate`. The native governance
  evaluator remains the only structural policy owner. Source selection confines
  the alignment artifact, template, cross-references and report; it grants no
  live-input fallback or identity edit authority.
- First-entry admission requires the actual released v36 ordinary alignment,
  its v35 strategy and v32/v34 feasibility ancestry, unchanged feasibility
  budgets/configuration, and zero prior alignment attempts. Completion admits
  only the native repair, terminal-blocked or Phase 3 entry destination; it does
  not execute any successor. Repaired alignment and STOP_AND_ASK remain closed.
- RED adapter/routing tests exposed the missing alignment entries. An initial
  test-only I/O guard also blocked the permitted bundled grammar load; it was
  narrowed to allow only that resource, retaining the live-input prohibition.
  Alignment/feasibility adapter and captured-policy checks then passed
  **79 tests in 0.57s**. Publication RED against the actual retained v36 Codex
  parent exposed the missing alignment publication entry before implementation.
- Initial retained publication helpers exposed two test-only mistakes: a wrong
  artifact key for template tampering, and a bypass action tamper that did not
  change the original value. Both were corrected. Publication/refusal then
  passed on retained Codex `pytest-370` and Claude `pytest-376`, but native
  handoff correctly rejected the test's completion ID because strategy had
  already used it. Both blocked records, receipts and sealed evidence remain
  untouched. The gate helper now creates a unique completion ID. These failed
  handoffs are not represented as successful recovery or reset for retesting.
- New verification uses a separate fresh temporary root,
  `/tmp/echelon-alignment-checks.CnKAq8`, with the same retention flags. This
  avoids automatic retirement of older acceptance evidence from the original
  pytest root; no retained fixture was moved, reset, rewritten or deleted.
- With the repository virtualenv, `-q --tb=short` and global retention flags,
  `test_discovery_alignment_gate.py`, `test_discovery_assessment_gate.py`,
  `test_captured_governance_gate.py`, `test_governance_structural_gate.py`,
  `test_squad_completion.py`, `test_managed_alignment_rounds.py` passed
  **329 tests in 4.40s** before the final additional reference/template/state
  cases. Native `tests/integration/test_squad_controller.py -k 'structural or
  feasibility or alignment'` passed **16 tests, 501 deselected in 5.43s**.
- The added cross-reference test initially supplied an unparseable Markdown
  heading as its specification; native Lexicon deliberately cannot resolve IDs
  without a parsed specification. Replacing that test input with the existing
  valid controlled-language fixture made the unresolved-reference assertion
  meaningful. Final focused command above, including all added cases:
  **336 passed in 4.74s**. Production structural policy was not changed.
- Read-only admission checks on actual retained gate-only `pytest-339` and
  strategy-only `pytest-337` refused both as alignment-gate parents without
  changing their state. A released alignment author is required.
- Shared `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py`, `test_squad_completion.py`, same
  interpreter/options and isolated temporary root: **352 passed in 351.26s**.
  The prior combined run had **382 passed, 1 failed in 341.40s**; its only
  failure was the invalid cross-reference test fixture described above.
- The actual released repaired-feasibility v34 proof under
  `pytest-337/test_reviewed_feasibility_gate0` also passed retained proof
  validation and shared decoding with its original `proceed` result. This
  read-only regression changed no state and is not a new repaired full prefix.
- Read-only review found no remaining actionable production defects after the
  helper correction. Full managed repair/block handoff coverage remains distinct
  from the bypass/warning corridors and must not be claimed from routing tests.
- Fresh scripted Codex/guided, Lexicon-disabled full prefix:
  `tests/unit/test_managed_alignment_gate.py -k codex`, repository virtualenv,
  `-q --tb=short`, global retention flags and the fresh temporary root:
  **1 passed, 1 deselected in 1637.11s**. The fixture is
  `pytest-of-michalbachorik/pytest-2/test_alignment_gate_reaches_ph0` under that
  root. Actual released Phase 1 approval, feasibility, strategy and ALIGNED
  publication precede the new v37 bypass. The graph-only handoff, tamper and
  wrong-route refusals, strict counter/type checks, interruption after promotion
  and identity application, and exact recovery all passed. It stops settled at
  `phase3-specialists` entry, with zero Phase 3 dispatches, 210 cumulative scripted
  tokens, unchanged IDs/history and no extra gate provider calls or charges.
- Fresh scripted Claude/Banzai, Lexicon-enabled cap-one warning full prefix:
  `tests/unit/test_managed_alignment_gate.py -k claude`, same interpreter/options
  and temporary root: **1 passed, 1 deselected in 2042.69s**. The fixture is
  `pytest-of-michalbachorik/pytest-3/test_alignment_gate_reaches_ph0` under that
  root. Existing COMMANDER Phase 1 approval, reviewed feasibility, strategy and
  DRIFT publication precede the v37 warning gate. Exact report/graph writes,
  binding/route/counter refusals, partial publication and post-identity-apply
  interruptions, recovery and zero-call replay passed. It stops settled at
  `phase3-specialists` entry, `proceed_with_warning`, alignment attempts=1,
  preserved feasibility attempts=1 and 238 cumulative scripted tokens. No
  Phase 3 dispatch, additional gate usage or identity/history change occurred.
- Final diff checks passed. Commit this verified first-entry gate increment,
  not whole Task 4 or Phase 2 acceptance. Next: full repair/block gate handoffs,
  protected alignment repair/recheck/no-progress/exhaustion, native clarification
  and existing COMMANDER routes; then remaining branch/timing parity and full
  acceptance. No installation, migration, public activation, live model call,
  merge or push. Disk remains nearly full; no retained evidence was cleaned up.

### Task 4 — first protected alignment repair publication

- Continuing the existing worktree from `f030705e`; no installation, migration,
  public activation, live provider call, Phase 3 execution, merge or push.
- Test-first round selection reproduced the missing structural-repair parent
  transition (**1 failed, 11 passed**). The protected owner now retains the
  accepted predecessor and separate receipt round without changing native
  counters or earlier rounds; **12 passed** after the change. A separate RED
  test confirmed the missing released repair authority helper before adding it.
- First repair admits only the actual released v37 `repair` result and its
  accepted v36 author. It authenticates current native state/configuration and
  managed identity authority, captures the failed report as exact read-only
  evidence, and publishes only alignment/graph through a closed v38 binding.
  Historical projection validates the predecessor chain; live recovery retains
  alignment and feasibility budgets. No question resolution can be substituted.
- Full repair-gate and repaired-author continuation was verified against
  the retained Claude/Banzai run at original temporary root
  `pytest-331/test_real_review_seals_only_fe0`. Its existing released repaired
  feasibility v34 prefix is reused as-is, not reconstructed, reset or rewritten.
  Fresh dual-provider test composition is present but has not been run in this
  increment. It must not be represented as fresh dual-provider acceptance.
- With repository virtualenv, `-q --tb=short`, isolated temporary root
  `/tmp/echelon-alignment-checks.CnKAq8` and retention count 200/policy all,
  alignment round/repair-boundary, captured structural policy, assessment gate
  and shared completion-shape tests passed **338 tests, 2 deselected in 5.42s**.
  Native controller structural/feasibility/alignment routing passed
  **16 tests, 501 deselected in 5.55s**.
- Shared protected strategy/feasibility rounds and discovery turns passed
  **109 tests in 21.92s**, with the same interpreter and retention settings.
- Shared discovery completion, publication and restoration regressions passed
  **127 tests in 360.12s**, with the same interpreter and retention settings.
- After adding an inactive-round refusal assertion before identity lookup, the
  focused suite passed again: **338 tests, 2 deselected in 5.22s**.
- Read-only authentication of the actual previously released first v37 gates
  passed on fresh-prefix Codex `pytest-2` and Claude `pytest-3` in the isolated
  temporary root. State/history remained unchanged. The first invocation used
  the macOS `/tmp` symlink and was refused before reading identity state; the
  retry used its resolved `/private/tmp` path, without modifying any evidence.
- Independent read-only review found no actionable production defects. Its
  optional explicit boundary assertion was added: actual released v38 cannot
  enter the still-unadmitted recheck publisher. Acceptance findings and final
  recovery are recorded below.
- The actual retained Claude continuation completed reviewed strategy v35,
  ordinary alignment v36 and failed first structural gate v37. The repair
  handoff passed wrong-route and typed-counter refusal, partial report/graph
  promotion, interruption after identity application, exact recovery and
  zero-call/zero-charge replay. It is settled at alignment repair entry with
  iteration 2, alignment attempts 1, feasibility attempts 0 and 259 cumulative
  scripted tokens. Identity history is unchanged and Phase 3 was not dispatched.
  Repaired v38 author/publication recovery continued against that release.
- Retained Claude repair authority and its altered-source/counter/iteration/
  configuration/verdict refusals passed. Reviewed repair and exact zero-call
  replay also passed: three scripted turns, 21 pending tokens, exact failed
  report evidence, no identity operations/history changes, unchanged canonical
  documents, preserved first round, and a separate second accepted round.
- The v38 package passed closed-binding/tamper and exact write-scope checks,
  but native handoff exposed a defect before promotion: v38 live authentication
  incorrectly expected the previous alignment pass/findings/report state fields
  to survive authoring. Native routing deliberately clears those certification
  fields, retaining attempts and the report artifact. The failed pending
  completion and its `intent_mismatch` diagnostic were retained, not reset.
- Corrected only v38 expectation to match native semantic cleanup; lifecycle
  status/reason restoration remains owned by existing completion recovery.
  Added explicit stale-certification refusal and byte-identical retained report
  assertions. The pending-recovery test helper now also admits an actual stored
  failed completion without re-preparing or rewriting its proof. Recovery of
  that same retained pending v38 passed through the native owner: stale-field
  and counter/type refusal, partial promotion, interruption after identity
  application, finalization and exact zero-call replay. The original diagnostic
  was restored/cleared only by normal completion; no fixture or sealed evidence
  was reset or rewritten to repair the test.
- Final retained state: running `phase2-intent-alignment-structural`, iteration
  2/max 5, alignment attempts 1, feasibility attempts 0, 280 cumulative scripted
  tokens, two alignment author dispatches, no Phase 3 dispatch, no pending
  publication/completion or failure diagnostic. The original v38 completion
  `00475663f2c3499eb303cbd58146e579` is released. Identity history and all
  non-target documents (including the old failed report) remain unchanged.
  Structural pass/findings/report state fields are absent per native policy;
  the next gate must evaluate the repaired document using the retained budget.
- The actual released v38 was refused by the still-closed recheck parent guard.
  This is verified repair authoring/publication/recovery, not a passing repaired
  structural recheck or complete Task 4. Follow-up read-only review confirmed
  the cleanup fix and test factoring; its pre-routing dispatch-count assertion
  was restored. Post-fix focused checks: **338 passed, 2 deselected in 5.29s**.
- Post-fix protected rounds/turns plus native structural/feasibility/alignment
  routing checks: **125 passed, 501 deselected in 16.98s** (same interpreter,
  isolated temporary root and retention settings).
- Final read-only released-v38 authentication passed with the original fixture
  Prosaic metadata inspector and unchanged state/history. An initial standalone
  check omitted that fixture inspector and was refused; no production authority
  or retained proof was changed to make the check pass.
- The post-fix shared completion/publication/restoration rerun was interrupted
  by disk exhaustion: **120 passed, 2 failed, 5 setup errors in 355.78s**.
  Failures were inability to write fixture Git/config/context files or create
  fixture directories (`ENOSPC`), so this run is not a green regression result.
- Following explicit cleanup approval, removed only disposable `pytest-5`
  through `pytest-19` under the isolated temporary root above (permanently,
  about 400 MiB). Retained Codex `pytest-2`, Claude `pytest-3`, and the entire
  original macOS pytest root including the released-v38 `pytest-331` evidence
  were preserved. No repository, environment or other user data was removed.
- Post-cleanup focused checks passed again: **338 passed, 2 deselected in
  5.20s**; protected rounds/turns and native routing: **125 passed, 501
  deselected in 16.61s**. Read-only authentication again confirmed the actual
  released v38 with unchanged retained state/history and zero Phase 3 dispatches.
- The post-cleanup shared completion/publication/restoration rerun completed
  cleanly: **127 passed in 324.85s**, with the same interpreter, isolated root
  and retention settings. Final diff checks passed. This closes verification
  for the first protected alignment repair checkpoint, not full Task 4 or
  fresh dual-provider repair acceptance; installation/activation remains out
  of scope for this checkpoint.
- Next after this checkpoint: v39 structural recheck with retained native
  attempts/configuration, successful repair and repeated-failure exhaustion/
  no-progress evidence; then native clarification/COMMANDER and remaining
  branch/timing parity. No controller approval policy or identity semantics
  are being changed.

### Task 4 — first repaired alignment structural recheck

- Continuing from `2642737c` in the same isolated worktree, inline under the
  approved Phase 2 design. No installation, activation, provider spending,
  migration, merge/push, prose change or Phase 3 dispatch is authorized here.
- Test-first against the actual released v38 in retained Claude/Banzai
  `pytest-331/test_real_review_seals_only_fe0`: the new parent assertion failed
  at the existing v36-only admission guard, before canonical writes. The new
  v39 association admits that released repair and retains its authorizing v37
  gate, exact failed report, configuration, iteration and feasibility budget.
  It recovers alignment attempts from the released failure, not live defaults.
- Extended only the existing gate decoder/publisher/authentication and retained
  projection owner. v37 remains first-entry; v39 requires nonzero prior attempts
  and the retained failed report. Both use native captured evaluation and exact
  report/graph publication. A second author after v39 is still deliberately
  closed pending repeated-failure/exhaustion acceptance.
- Retained parent admission and recheck preparation refusals passed: reset,
  inflated/typed attempts, iteration/type, cap, source, configuration override,
  feasibility budget and verdict changes were refused without canonical writes
  or identity-history changes. Focused gate/round/completion tests passed
  **295 tests in 14.29s**, with repository virtualenv, `-q --tb=short`, isolated
  `TMPDIR=/tmp/echelon-alignment-checks.CnKAq8` and retention count 200/policy all.
- Read-only review found no actionable defect. Its coverage boundary remains
  explicit: successful v39 acceptance does not establish repeated repair,
  warn/block exhaustion or fresh dual-provider full-prefix acceptance.
- Actual retained Claude v38 continued through successful v39 recheck using
  the production publisher/controller: exact gate/report/graph binding and
  tamper refusals, partial promotion interruption, interruption after identity
  application, native recovery, settled replay with no provider call or charge,
  and typed-budget authentication passed. Identity history stayed unchanged;
  the run reached `phase3-specialists` entry without dispatching Phase 3.
  This is a retained continuation, not a new full-prefix run. The fresh
  Codex/Claude test compositions are present but not run in this increment.
- A separate final read-only check authenticated the existing isolated-root
  v37 Codex bypass and Claude warning releases, plus this actual v39 release
  `476c322bc86742d6a08a9d60b1c0c374`. All retained states/history remained unchanged.
  v39 is settled at Phase 3 entry, iteration 2, alignment attempts 0 (native
  successful-check semantics), 280 cumulative scripted tokens and zero Phase 3
  dispatches. Its sealed input still records the preceding failed attempt.
  The new explicit forged-phase assertion also refused another author from
  v39; typed iteration/alignment/feasibility counter mutations were refused.
- Shared `test_discovery_completion.py`, `test_discovery_publication.py`,
  `test_discovery_restoration_completion.py`, captured/native governance gates
  and native controller structural/feasibility/alignment routing passed
  **185 tests, 501 deselected in 336.92s**, with the same interpreter, isolated
  root and retention settings. Final diff checks passed. No further temporary
  data was deleted. Disk is critically low (~210 MiB free).
- Checkpoint closes the successful first repaired recheck only. Next: actual
  no-progress repair/warn/block v39 handoffs and repeated-author admission with
  preserved original limits; then native clarification/COMMANDER and remaining
  branch/timing parity. Full activation and whole-Phase-2 acceptance stay open.

### Task 4 — repeated alignment repair and exhaustion

- Continuing inline from `9aacd96d`, with no installation, activation, live
  provider spend, merge/push or Phase 3 execution. User-approved disk cleanup
  removed the disposable recent regression fixtures and 14 abandoned pytest
  `garbage-*` directories; all older numbered runs and retained evidence were
  preserved. Free space recovered to about 115 GiB. Read-only snapshot directory
  permissions had prevented deletion of the abandoned garbage; only directories
  within the validated garbage roots had permissions restored, without following
  symlinks. No repository or test-retention configuration changed.
- New tests deliberately reuse byte-identical invalid alignment output. Codex
  guided/cap-two/block runs from a fresh Phase 1 prefix; Claude Banzai/cap-three/
  warn continues the actual released feasibility gate in original-root
  `pytest-339/test_valid_claude_banzai_feasi0`, without changing its configuration,
  state or proof to manufacture a parent. Both use the existing scripted provider
  and fixture Prosaic inspector, leaving production authority/routing intact.
- Existing focused gate/round/repair-boundary baseline passed: **71 passed,
  2 deselected in 11.71s**, using repository virtualenv, isolated
  `TMPDIR=/tmp/echelon-alignment-checks.CnKAq8`, `-q --tb=short`, retention count
  200/policy all. Full corridor outcomes are recorded separately below.
- The actual retained Claude continuation published strategy and initial
  alignment, released the first repair gate, authored byte-identical invalid
  output and released the v39 second failure with attempts=2. Native partial
  publication/post-identity-application interruption, recovery, exact replay and
  typed-budget refusal passed. The next-author test then failed exactly at
  `require_alignment_repair`'s v37-only version guard, before a third round.
- Minimal production change: both live repair admission and historical
  repaired-author projection now admit v37 or v39, still requiring the exact
  released `repair` route/action and accepted predecessor. Existing recursive
  configuration/iteration/attempt checks own the budget; no allocator, version,
  schema, provider prose or approval policy was added. The same saved released
  second failure resumed at attempt three; no state/proof/configuration reset.
- Post-change focused gate/round/repair, squad completion and captured/native
  governance regressions passed **338 tests, 2 deselected in 14.98s**, with the
  same interpreter and isolated retention settings. Read-only review of the
  actual two-line production change and generalized acceptance tests found no
  actionable defect; complete corridor acceptance remained pending at review.
- Shared discovery completion/publication/restoration and native controller
  structural/feasibility/alignment routing regressions passed **143 tests,
  501 deselected in 356.42s**, using the same interpreter and retention settings.
- Retained Claude continuation passed from the saved second failure through
  third unchanged author, v38 publication and v39 warning exhaustion. The helper
  verified native interruptions/recovery, zero-call replay, typed-budget and
  exhausted-author refusals, exact cumulative accounting, unchanged identity
  history and preservation of older rounds. Final state: settled Phase 3 entry,
  iteration 2, alignment attempts 3, three alignment author dispatches and 280
  scripted tokens; no Phase 3 dispatch. This is retained acceptance, not a fresh
  Claude full-prefix run.
- Fresh Codex guided/cap-two/block acceptance passed **1 test, 1 deselected in
  3201.10s** (`test_managed_alignment_exhaustion.py -k codex`, same interpreter,
  isolated root and retention flags). It traversed the real Phase 1 approval,
  feasibility repair/recheck, strategy and unchanged alignment repair before
  exhaustion. Final state: settled `terminal-blocked`, iteration 2, attempts 2,
  two alignment author dispatches, 252 scripted tokens and no Phase 3 dispatch.
  Preserve its new isolated-root `pytest-4/test_no_progress_alignment_exh0`
  evidence; this is not the disposable older pytest-4 removed during cleanup.
- The fresh Codex process started before the two-line admission patch; its
  cap-two path never needs v39-to-author admission. The retained Claude third
  author supplies that post-change acceptance; the final read-only checks below
  authenticate both exhausted releases and refuse further repair on current code.
- Final read-only current-code verification passed for Codex released v39
  `be60bfb44b22418b818b72ba464dd396` and Claude released v39
  `a6c4a7673b484c01aa60ef98cd5cdb14`: exact actions, previous/current attempts,
  iteration, dispatch counts and usage matched; forged return-to-author phases
  were refused, and saved state/history stayed unchanged. Final diff check passed.
- This checkpoint closes repeated alignment repair/no-progress and warn/block
  exhaustion only. Native clarification/COMMANDER transport, remaining
  branch/timing parity and whole-Phase-2 acceptance remain open. No installation,
  public/live activation, Phase 3 execution, merge or push occurred.
