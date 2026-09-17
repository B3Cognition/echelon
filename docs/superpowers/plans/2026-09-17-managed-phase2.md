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
  gate entry. Re-evaluation of that retry remains a separate next increment.

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
