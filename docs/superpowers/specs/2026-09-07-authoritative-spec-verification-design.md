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

### Decision-time evidence retrieval

Graph health must not make canonical product decisions invisible. Before a
Banzai WHY2 clarification becomes human-owned, the controller queries MemPalace
with the exact pending question across every room, including supporting context.
It reconciles every returned drawer against the current canonical artifact hash
and lifecycle status, rebuilds the existing prior-spec context, and retries WHY2
only when at least one drawer survives reconciliation.

The retry is controller-owned and durable. The controller writes an immutable,
question-specific evidence snapshot below the run directory, then a bounded
ledger records the decision ID, question hash, snapshot path and content hash,
accepted drawer IDs, timestamp, and `armed`/`consumed` status. Only the armed
retry dispatch reads that snapshot, after verifying its regular-file type, run
containment, size, and content hash. The executor atomically consumes the binding
at the provider-dispatch boundary, so later WHY2 work cannot inherit historical
question evidence; mutable context files are not authoritative. The same
question can be retried once; distinct questions can each be retried, up to a
small run-level cap. No retrieved answer is applied directly—the SAGE pass must
still cite and interpret the supplied evidence. If retrieval is unavailable,
stale, empty, or already consumed, the existing human/default decision policy is
unchanged.

If a WHY2 or later WHY3 review identifies an agent-repairable artifact defect,
the controller derives and persists the smallest responsible repair phase from
the current `issues.md` before routing. DISCOVER-owned evidence returns to
DISCOVER rather than being collapsed into CARTOGRAPHER. Likewise, WHY3 must not
fall back through Phase 1 when HOW, SENTINEL, or PLAN owns the repair: that replay
can replace the current WHY report and erase the repair evidence before its
owner receives it.
Owner-specific WHY3 transitions are evaluated before the generic quality-gate
fallback, so a simultaneous metric failure cannot preempt the persisted owner.

### Repair epochs and canonical graph provenance

A discovery-owned WHY2 failure is not a proportional `spec.md` candidate.
Controller-derived DISCOVER ownership therefore routes before proportional
candidate capture; all proportional integrity, budget, and no-progress checks
remain authoritative for WHAT-owned specification repairs.

When WHY2 certifies a changed `spec.md` content fingerprint, downstream Lexicon
and checkpoint dispatch counters start a new certification epoch. Authoring and
WHY counters are retained. This prevents legitimate repaired candidates from
inheriting lifetime one-shot counts while preserving the existing bounded
authoring policies. Recovery from an older malformed dispatch-cap state is
allowed only when the persisted Phase 1 quality prerequisite is still current,
and only once for the same phase and certified source fingerprint. The
compatibility recovery records that consumed epoch before dispatch; a repeated
identical state fails closed.

Graph requirement provenance prefers an explicit requirement definition over
an earlier textual reference to the same ID. Reference-only IDs remain valid
fallback inventory entries, but an acceptance criterion such as `Verification:
FR-014` must never replace the canonical `FR-014` definition in graph or memory
evidence.

### Deferred autonomy policy

This design does not add the proposed owner-enabled “super-Banzai” authority.
When no trusted evidence exists, reversible bounded defaults remain a separate
SAGE policy improvement. Security, safety, legal, external-fact, and
irreversible product commitments continue to require the existing authority
boundary until that explicit opt-in mode is designed and approved.

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
- No weakening of human ownership when trusted decision evidence is absent.

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
