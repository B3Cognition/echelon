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

- [ ] Add parameterized tests to `tests/unit/test_coverage_contract.py` rejecting symbolic/open-ended case IDs, prose, missing hyphens and malformed IDs. Preserve existing valid-list tests.
- [ ] Run `.venv/bin/pytest -q tests/unit/test_coverage_contract.py` and verify the new cases fail because the parser currently accepts them.
- [ ] Add `is_coverage_case_id(value: str) -> bool` to `src/harness/coverage_contract.py` using the observer-compatible uppercase hyphenated grammar. Call it from `parse_coverage_obligations`; raise `CoverageContractError` with an explicit enumerate-cases remedy.
- [ ] Reuse that predicate in Ralph's coverage repair guidance, removing its private duplicate regex.
- [ ] Replace TEST GUARDIAN's obsolete coverage table with the canonical template reference and explicit preservation rules. Explain that aliases require meaningful matching assertions and each case must identify one physical test.
- [ ] Add a Phase A readiness regression for an open-ended case and run coverage/readiness/Ralph regressions.
- [ ] Commit only the tested phase; leave legacy demo coverage untouched.

## Phase 2: Bounded advisory diagnosis

- [ ] Validate the existing provider containment mechanism before adding an automatic dispatch. The diagnostic must not be able to modify product/spec files; prompt-only prohibitions are insufficient.
- [ ] Build harness-owned input from canonical obligations, source-bound observer receipts and current source/test identity. Bound work and mark omitted evidence explicitly; an incomplete search cannot justify `missing_test`.
- [ ] Invoke the existing TEST GUARDIAN diagnostic mode at most once per immutable input fingerprint. Preserve the original failed verification result even on diagnostic error, timeout or unsupported containment.
- [ ] Validate structured recommendations against input IDs and source locations. Keep `matching_test`, `insufficient_assertions`, `missing_test`, and `invalid_obligation` separate. Do not permit a recommendation to claim verified/complete.
- [ ] Store advisory output under the verify run, expose its path in CLI output, and retain blocked status. Ordinary successful verification must not dispatch this review.
- [ ] Add fake-provider tests for no dispatch on success, bounded dispatch on coverage debt, invalid output, timeout, unchanged inputs, and no ledger/spec mutation.
- [ ] Validate with the retained demo receipts before spending another browser/DB run. Do not apply recommendations to the demo automatically.

## Phase 3: Repair and fresh verification

- [ ] Feed owner-approved dispositions into the existing implementation flow. Keep requirements/required test boundaries intact; missing assertions need test repairs, not aliases.
- [ ] Reacquire authoritative evidence after any accepted source/test or coverage-map change. Rebuild graphs only from resulting compatible verified rows.
