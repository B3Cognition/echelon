# Authoritative Standalone Spec Verification Implementation Plan

**Goal:** Reuse delivery's managed sandbox evidence pipeline from standalone
`echelon spec verify`, then prove the refreshed graph can support evidence-led
SAGE escalation.

**Design:** `docs/superpowers/specs/2026-09-07-authoritative-spec-verification-design.md`

## Task 1: Preserve and characterize delivery evidence behavior

- [ ] Add focused tests for standard receipt, required runnability, required
  coverage observation, failure propagation, cleanup, and candidate immutability.
- [ ] Run each new test against current delivery and confirm its expected result.
- [ ] Introduce a shared harness candidate-evidence result and runner using the
  existing verification/runnability/coverage modules.
- [ ] Make Ralph delegate without changing state, failure IDs, repair policy, or
  receipt contents.
- [ ] Run Ralph, runnability, coverage observer, and landing regression tests.

## Task 2: Give standalone verification an authoritative evidence session

- [ ] Add failing CLI/service tests proving strict standalone verification
  resolves stacks, uses a sandbox provider, and supplies all required evidence
  to fulfillment.
- [ ] Add failing tests proving environment/harness failures do not become
  product gaps and partial runs become durably blocked.
- [ ] Reuse the delivery stack-resolution function through a harness-owned
  module rather than importing private CLI delivery functions.
- [ ] Allocate the verify run before evidence acquisition and allow
  `FulfillmentRunner` to use that caller-owned run.
- [ ] Wire `_run_spec_verify` to the shared evidence service and deterministic
  lifecycle finalization.
- [ ] Run the focused CLI, fulfillment, verify-run, and evidence suites.

## Task 3: Validate graph lifecycle on the demo workspace

- [ ] Install the updated CLI and refresh managed workspace runtime.
- [ ] Run authoritative reconciliation for spec 003.
- [ ] Inspect immutable standard, runnability, and coverage receipts and the
  complete verified fulfillment ledger.
- [ ] Regenerate and audit the spec/workspace graph.
- [ ] Confirm spec 003 remains landed and both repositories retain only expected
  generated artifacts or are clean under their documented ownership rules.

## Task 4: Reconnect to the original autonomy problem

- [ ] Inspect the refreshed graph and MemPalace for evidence relevant to spec
  007's interaction behavior and boundary question.
- [ ] Resume or reproduce the decision and verify graph/memory evidence is
  consulted before human escalation.
- [ ] Record any remaining SAGE bounded-default policy gap separately; do not
  disguise it as a verification or graph lifecycle failure.

## Final verification

- [ ] Run the complete unit suite.
- [ ] Run `git diff --check` and inspect repository status.
- [ ] Request an independent code review and address important findings.
- [ ] Re-run the demo acceptance path after the final installed CLI build.
