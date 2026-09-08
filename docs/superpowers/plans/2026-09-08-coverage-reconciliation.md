# Coverage reconciliation implementation plan

**Goal:** Diagnose and repair traceability debt without promoting unproven requirements.

**Approved design:** First align the coverage contract, then reuse TEST GUARDIAN for bounded advisory diagnosis. Matching tests, insufficient assertions, missing tests and invalid obligations remain separate dispositions. Application uses the existing implementation/reverification flow, never direct ledger promotion.

**Architecture:** Keep `coverage_contract` and source-bound observers authoritative. Retain legacy artifacts unchanged. A diagnostic result is advisory and cannot satisfy fulfillment, landing or graph gates.

**Execution:** Inline, with a verification checkpoint after each independently usable phase.

## Constraints

- No edits to the demo specification, tests, requirements, or evidence receipts.
- No new agent, SOAR execution, automatic tag guessing, or relaxed observer matching.
- Retain valid case lists separated by comma, slash or semicolon and coupled requirement rows.
- Do not expand symbolic case ranges or invent their endpoints.
- Keep existing receipt-backed fulfillment reconciliation separate from coverage repair.

## Phase 1: Align planning and repair contracts

- [x] Add parameterized tests to `tests/unit/test_coverage_contract.py` rejecting symbolic/open-ended case IDs, prose, missing hyphens and malformed IDs. Preserve existing valid-list tests.
- [x] Run `.venv/bin/pytest -q tests/unit/test_coverage_contract.py` and verify the new cases fail because the parser currently accepts them.
- [x] Add `is_coverage_case_id(value: str) -> bool` to `src/harness/coverage_contract.py` using the observer-compatible uppercase hyphenated grammar. Call it from `parse_coverage_obligations`; raise `CoverageContractError` with an explicit enumerate-cases remedy.
- [x] Reuse that predicate in Ralph's coverage repair guidance, removing its private duplicate regex.
- [x] Replace TEST GUARDIAN's obsolete coverage table with the canonical template reference and explicit preservation rules. Explain that aliases require meaningful matching assertions and each case must identify one physical test.
- [x] Add a Phase A readiness regression for an open-ended case and run coverage/readiness/Ralph regressions.
- [x] Commit only the tested phase; leave legacy demo coverage untouched.

## Phase 2: Bounded advisory diagnosis

- [x] Validate the existing provider containment mechanism before adding an automatic dispatch. The diagnostic must not be able to modify product/spec files; prompt-only prohibitions are insufficient.
- [x] Build harness-owned input from canonical obligations, source-bound observer receipts and current source/test identity. Bound work and mark omitted evidence explicitly; an incomplete search cannot justify `missing_test`.
- [x] Run one diagnostic session per immutable input fingerprint within a verify run. Following the approved incremental adjustment, use one-requirement batches with a shared 120-second budget and at most 20 batches; save each completed batch before the next dispatch. Preserve the original failed verification result even on diagnostic error, timeout or unsupported containment.
- [x] Validate structured recommendations against input IDs and source locations. Keep `matching_test`, `insufficient_assertions`, `missing_test`, and `invalid_obligation` separate. Do not permit a recommendation to claim verified/complete.
- [x] Store advisory output under the verify run (or `.echelon/coverage-diagnostics/<run-key>` when the run is inside the product inventory), expose its path in CLI output, and retain blocked status. Ordinary successful verification must not dispatch this review.
- [x] Add fake-provider tests for no dispatch on success, bounded dispatch on coverage debt, invalid output, timeout, unchanged inputs, and no ledger/spec mutation.
- [x] Validate with compatible demo receipts. Do not apply recommendations to the demo automatically.

## Phase 3: Repair and fresh verification

- [ ] Feed owner-approved dispositions into the existing implementation flow. Keep requirements/required test boundaries intact; missing assertions need test repairs, not aliases.
- [ ] Reacquire authoritative evidence after any accepted source/test or coverage-map change. Rebuild graphs only from resulting compatible verified rows.

## Execution record — 2026-09-08

- Phase 1 completed in `ea26312d`; 438 relevant tests passed. Symbolic case ranges are rejected, not expanded; existing demo artifacts are retained unchanged.
- Phase 2 implemented and independently reviewed. Review fixes preserve the existing product fingerprint algorithm by storing overlapping diagnostic output in the existing control-plane boundary, and propagate unmapped requirement IDs as structured failure details.
- The final combined coverage/provider/CLI/readiness/Ralph regression run passed 527 tests in 53.83 seconds. Diagnostic work is capped at 20 unresolved active requirements and 120 seconds; omitted requirements stay explicitly unreviewed.
- Containment currently supports Codex with the existing enforced host boundary. Other provider/platform combinations return an explicit unsupported-boundary report without dispatch; prompt-only restrictions are not accepted.
- CLI installed from this feature worktree, not merged to main. Retained-demo validation produced `provider_failed` with no advice. A narrowed follow-up rejected a changed candidate fingerprint as `stale_evidence` before dispatch. Live successful diagnosis remains unvalidated; no automatic demo repair or graph promotion occurred. Provider failures now retain bounded redacted exit/timeout/stderr diagnostics.
- Phase 3 remains owner-controlled application of reviewed recommendations followed by fresh verification; it does not add an automatic repair loop.

### Incremental diagnostic validation

- Fresh run `verify-spec-003-create-browser-first-3d-20260908-123207` passed standard verification after the existing one-time browser retry (35 browser tests passed), then passed the composed journey and persistence checks. It remained blocked by the legacy symbolic coverage case `C-HTTP-001..N`.
- The original 20-requirement diagnostic timed out at 120 seconds while inspecting source; a one-requirement probe returned successfully. This led to the owner-approved incremental adjustment, without changing requirements or observer acceptance.
- The incremental live run retained three source-cited advisory findings (AC-001 through AC-003) before the fourth batch exhausted the shared budget at 120.09 seconds. All 73 other requirements remain unreviewed. Findings are recommendations needing review, not new fulfillment evidence. No demo repair or graph promotion occurred.
- Live report: `runs/verify-spec-003-create-browser-first-3d-20260908-123207/coverage-diagnostic/2b6933af6c4944ec463dd099731a93bbc31eba6af2673559226f4952f452a9bb/report.json` in the demo workspace. This retained report predates the final stop-label refinement; future deadline stops are labeled `budget_exhausted`.
- Regression coverage includes durable partial results, one shared decreasing timeout, batch-local IDs, malformed later output, input changes, and exceptions/unreadable inputs invalidating earlier findings. Independent review's exception-path finding was fixed and re-reviewed.
- Final relevant regression run: 533 passed in 54.94 seconds. Reinstalled the CLI from this feature worktree; no merge to main or demo repair was performed.
