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
`discovery_semantics.py`, `discovery_producer.py`, `discovery_candidate.py`;
new `tests/unit/test_managed_assessment_contract.py` and neutral Prosaic role
contracts for feasibility, strategy and alignment author/reviewer turns.
Consumes `DiscoveryAssignment`. Produces closed artifact/routing validation for
producers `feasibility`, `strategy`, `alignment`, all with no identity edit scope.

- [ ] Add assignment/reply tests using these literal write sets:
  ```python
  feasibility = {"feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md"}
  strategy = {"strategic-overview.md"}
  alignment = {"intent-alignment-check.md"}
  ```
  Require a kill report for KILL; conditional absence must be explicit. Reject
  source edits, structural state/counters, invented identities and mismatched
  review routing. Clarification metadata must follow native STOP_AND_ASK rules.
- [ ] Run the new contract suite red; extend only semantic decoding and neutral
  role mappings, not runtime admission. Bind reviews to exact author routing.
- [ ] Run semantic, candidate, reservation and existing producer contract tests;
  commit only the closed contract/role slice after read-only review.

## Task 3: Retained feasibility producer and structural gate

Files: `discovery_assessment.py`, new `discovery_assessment_gate.py`; existing
`discovery_operation.py`, `discovery_turns.py`, `discovery_receipts.py`,
`discovery_publication.py`, `discovery_completion.py`, `squad.py`, `squad_state.py`;
new `tests/unit/test_managed_feasibility.py`.
Consumes released v30 Phase 1 approval, captured context and Task 1 evaluator.
Produces protected feasibility rounds and native structural completion proof.

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
