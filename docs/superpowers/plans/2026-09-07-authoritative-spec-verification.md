# Authoritative Standalone Spec Verification Implementation Plan

**Goal:** Reuse delivery's managed sandbox evidence pipeline from standalone
`echelon spec verify`, then prove the refreshed graph can support evidence-led
SAGE escalation.

**Design:** `docs/superpowers/specs/2026-09-07-authoritative-spec-verification-design.md`

## Task 1: Preserve and characterize delivery evidence behavior

- [x] Add focused tests for standard receipt, required runnability, required
  coverage observation, failure propagation, cleanup, and candidate immutability.
- [x] Run each new test against current delivery and confirm its expected result.
- [x] Introduce a shared harness candidate-evidence result and runner using the
  existing verification/runnability/coverage modules.
- [x] Make Ralph delegate without changing state, failure IDs, repair policy, or
  receipt contents.
- [x] Run Ralph, runnability, coverage observer, and landing regression tests.

## Task 2: Give standalone verification an authoritative evidence session

- [x] Add failing CLI/service tests proving strict standalone verification
  resolves stacks, uses a sandbox provider, and supplies all required evidence
  to fulfillment.
- [x] Add failing tests proving environment/harness failures do not become
  product gaps and partial runs become durably blocked.
- [x] Reuse the delivery stack-resolution function through a harness-owned
  module rather than importing private CLI delivery functions.
- [x] Allocate the verify run before evidence acquisition and allow
  `FulfillmentRunner` to use that caller-owned run.
- [x] Wire `_run_spec_verify` to the shared evidence service and deterministic
  lifecycle finalization.
- [x] Run the focused CLI, fulfillment, verify-run, and evidence suites.

## Task 3: Validate graph lifecycle on the demo workspace

- [x] Install the updated CLI and refresh managed workspace runtime.
- [x] Run authoritative reconciliation for spec 003.
- [x] Inspect immutable standard, runnability, and coverage receipts; record that
  the historical ledger remains unverified because its planned test IDs were
  never bound to delivered test metadata.
- [x] Regenerate and audit the spec/workspace graph; spec 007 resolves canonical
  requirement definitions while the workspace audit separately reports the
  known historical 003/006 evidence debt.
- [ ] Confirm spec 003 remains landed and both repositories retain only expected
  generated artifacts or are clean under their documented ownership rules.

## Task 4: Reconnect to the original autonomy problem

- [x] Inspect the refreshed graph and MemPalace for evidence relevant to spec
  007's interaction behavior and boundary question.
- [x] Resume or reproduce the decision and verify graph/memory evidence is
  consulted before human escalation.
- [x] Retrieve with the exact pending question across requirement and supporting
  context rooms, and reconcile hits against canonical artifact hashes.
- [x] Add one durable retry per distinct question with a bounded run-level cap;
  leave ordinary escalation unchanged when trusted evidence is absent.
- [x] Persist the controller-derived WHY3 repair owner before deterministic
  routing so downstream repairs retain the current issue evidence instead of
  replaying Phase 1 and overwriting it.
- [x] Preserve DISCOVER ownership in WHY2/WHY3 repair routing instead of
  collapsing discovery-artifact findings into CARTOGRAPHER.
- [x] Record any remaining SAGE bounded-default policy gap separately; do not
  disguise it as a verification or graph lifecycle failure.
- [x] Route discovery-owned WHY2 failures before proportional candidate capture
  and give each changed certified spec a fresh downstream validation epoch.
- [x] Prefer explicit requirement definitions over earlier ID references in
  canonical graph and memory provenance.
- [x] Bind each evidence-led WHY2 retry to an immutable, hash-verified run-local
  snapshot rather than a mutable context file.
- [x] Evaluate persisted WHY3 repair-owner routes before the generic quality
  fallback.
- [x] Limit malformed dispatch-cap compatibility recovery to one attempt per
  phase and certified source fingerprint.

## Final verification

- [x] Run the complete affected non-SOAR suite (1,662 passing tests); SOAR was
  explicitly excluded at operator request.
- [x] Run `git diff --check` and inspect repository status.
- [x] Request an independent code review and address important findings.
- [x] Re-run the demo acceptance path after the final installed CLI build:
  runtime deployment matches source, spec 007 remains complete, its graph
  resolves canonical FR-014, and exact-question MemPalace search returns the
  relevant boundary evidence. Historical 003/006 workspace debt remains
  separately visible.
