# Authoritative Standalone Spec Verification Design

## Purpose

Make `echelon spec verify` acquire the same stack-required sandbox evidence as
delivery before it judges fulfillment. This closes the lifecycle gap that leaves
historical landed specs with `UNVERIFIED` graph edges even though Echelon already
knows how to run their browser, service, and persistence journeys.

This is a prerequisite for the original autonomy goal: before SAGE asks a human
for a product decision, Echelon must be able to consult a trustworthy published
specification graph and MemPalace. Passing graph audit is not the terminal goal;
making all available evidence usable by the escalation path is.

## Current Split

Delivery currently performs, in order:

1. standard verification in a managed sandbox;
2. stack-required user runnability;
3. stack-required per-requirement coverage observation; and
4. fulfillment judgment using those immutable receipts.

Standalone `echelon spec verify` currently invokes the fulfillment runner
directly. It does not resolve the target stack, create a sandbox, start ephemeral
services, run the candidate journey, or produce coverage observations. A strict
fulfillment refresh therefore has no authoritative runtime evidence and
correctly records requirements as `UNVERIFIED`.

## Design

### Shared candidate-evidence pipeline

Introduce one harness-owned candidate verification service. It composes the
existing verification plan, immutable verification receipt, runnability runner,
and coverage observer runner. It does not invoke an LLM and it never executes
project verification on the user host.

The service accepts the resolved harness configuration, sandbox provider,
candidate/spec identity, and caller-owned evidence layout. It returns the
standard receipt, runnability reference, coverage observation, and deterministic
failure details. Candidate commit remains informational provenance; product,
spec, stack, runnability-contract, and observer-plan fingerprints remain
authoritative.

Delivery keeps its task, documentation, repair-loop, state, and landing policy,
but delegates evidence acquisition to this service. Standalone verification
resolves the same target stack and invokes the same service before calling the
existing fulfillment runner.

### One direct-verification lifecycle

Standalone verification allocates its Python-owned verify run before evidence
acquisition. Evidence, fulfillment artifacts, reconciliation artifacts, and the
terminal state belong to that one run. A failed evidence phase marks the run
blocked with its immutable partial evidence retained. A successful run is
complete only after fulfillment artifacts and requested reconciliation are
deterministically finalized.

### Failure boundaries

The shared service preserves existing failure identifiers while exposing a
stable top-level class:

- `candidate_failure`: project verification, contract, journey, or coverage did
  not pass;
- `environment_unavailable`: the managed verification environment could not
  provide a declared prerequisite;
- `harness_error`: Echelon could not create, validate, persist, or tear down the
  evidence session; and
- `verified`: all currently required evidence passed.

Only delivery may turn a candidate failure into a coding repair iteration.
Standalone verification reports the result and exits. Environment and harness
failures must never be presented as missing product implementation.

### Graph and historical specifications

The graph schema and completeness policy remain unchanged. A requirement is
complete only when the verified fulfillment ledger contains compatible receipt-
backed evidence. A landed historical spec may receive a fresh evidence refresh
without reopening or redelivery. Its lifecycle remains landed.

After a successful refresh, ordinary graph regeneration consumes the corrected
ledger. If graph audit still fails, that is a separate defect; graph audit is not
weakened to hide missing evidence.

## Phased Rollout

1. Extract the delivery evidence sequence behind a shared service with behavior-
   parity tests. No CLI behavior changes.
2. Wire standalone `spec verify` to that service and its existing verify-run
   lifecycle. Run fresh evidence; do not add evidence caching yet.
3. Validate spec 003 in the browser-game workspace, regenerate/audit the graph,
   and confirm repositories remain clean.
4. Resume or reproduce spec 007 and prove the evidence-led escalation path uses
   graph/Memory Palace context before asking a human. If exact evidence is absent,
   bounded reversible defaults remain the next SAGE-policy layer.

## Non-Goals

- No host dependency installation or host database execution.
- No demo-specific verification commands.
- No new browser, PostgreSQL, or observation implementation.
- No graph-audit relaxation.
- No zero-change delivery workaround.
- No evidence carry-forward/cache until fresh execution is proven.
- No SAGE policy change in the evidence-pipeline phases.

## Acceptance

- Delivery behavior and evidence remain equivalent after extraction.
- Standalone verification of a strict browser/DB target produces standard,
  runnability, and coverage evidence in managed sandboxes.
- Fulfillment consumes those exact receipts and writes a compatible complete
  ledger when the product passes.
- Historical landed lifecycle is preserved.
- The demo spec graph regenerates and audits from the refreshed ledger.
- No project command executes on the host and no credentials are persisted in
  the target repository.
- The resulting graph is demonstrably available to the later SAGE escalation
  resolution path.
