# Feature Specification: SUE Validation Gates and Workflow Evidence

**Feature Branch**: `031-sue-validation-gates`  
**Created**: 2026-07-31  
**Status**: Draft  
**Input**: User description: "Specify and complete the missing SUE capabilities: A1 extraction stability, cross-provider parity, glossary alignment, stable witness verification, blinded graph adjudication, workflow integration, and future source adapters."

## Problem Statement

SUE can execute cold reconstruction, typed graph extraction, aggregation,
justification-graph analysis, and bounded dialectic drills. Its latest forensic
run completed, but semantic reproducibility was fractured (`0.266`) and the
system is not yet validated as a reliable measurement instrument or integrated
as controller-owned workflow evidence. This feature defines the evidence and
acceptance contract for the missing validation, alignment, adjudication,
integration, and adapter capabilities without granting SUE blocking authority
prematurely.

The feature is diagnose-only. It does not rewrite specifications, claim that
reader agreement is truth, or replace the deterministic Understanding gate.

## User Scenarios & Testing

### User Story 1 - Validate extraction stability (Priority: P1)

As a SUE maintainer, I want a pre-registered A1 experiment on clean
specifications so that I know whether repeated cold readers produce a stable
typed interpretation before relying on absolute reproducibility scores.

**Why this priority**: A1 is the prerequisite for every later promotion gate.

**Independent Test**: Run the locked A1 protocol on the approved clean corpus
and inspect the signed report, raw evidence, and pass/fail decision without
running parity, mutation, or workflow integration.

**Acceptance Scenarios**:

1. **Given** a frozen clean specification, decision context, reader matrix,
   schema, prompts, and policy, **when** the A1 protocol runs, **then** every
   reader/pass has an immutable run identity, source digest, configuration
   record, typed output, and validation result.
2. **Given** the A1 results, **when** the gate evaluates them, **then** it
   reports mean typed-edge agreement and per-spec minimum agreement against the
   approved thresholds (`>=0.80` mean and `>=0.70` minimum) without changing
   those thresholds after observing results.
3. **Given** an A1 failure or unreconstructable evidence, **when** the run is
   finalized, **then** the result is recorded as `FIX-EXTRACTION` or
   `HALT`, and later promotion gates do not run.

### User Story 2 - Measure provider and framing parity (Priority: P2)

As a SUE evaluator, I want a controlled cross-provider comparison so that I
can distinguish specification ambiguity from provider, model, or framing
variance.

**Why this priority**: Parity is meaningful only after the extraction
instrument passes A1.

**Independent Test**: With an A1-passing corpus and locked prompts, run the
   balanced provider-by-framing matrix and verify the report separates
   within-provider, between-provider, and framing effects.

**Acceptance Scenarios**:

1. **Given** identical source units and decision contexts, **when** each
   approved provider/model/framing cell is sampled, **then** unit coverage,
   schema version, prompt family, and pass identity are comparable across
   cells.
2. **Given** the completed matrix, **when** parity is analyzed, **then** the
   report contains separate variance estimates for repeatability, provider or
   model family, framing, and changed-condition reproducibility.
3. **Given** provider disagreement without a stable source-grounded
   behavioural conflict, **when** results are classified, **then** the finding
   is reported as provider variance and is non-blocking.

### User Story 3 - Verify behavioural witnesses (Priority: P2)

As a requirements reviewer, I want candidate witness differences tested against
an explicit situation so that a wording difference is not promoted as a real
incompatibility.

**Why this priority**: Behavioural consequences are more decision-relevant than
prose or graph disagreement, but current witnesses are heuristic candidates.

**Independent Test**: Supply a stable candidate pair and verify that the
verifier emits `incompatible`, `equivalent`, or `undetermined` with citations
to both sides and a reproducible situation.

**Acceptance Scenarios**:

1. **Given** two independently grounded candidate consequences, **when** the
   verifier evaluates a concrete situation, **then** it records the situation,
   both incompatible outcomes (if present), source spans for both sides, and
   the verification run identity.
2. **Given** equivalent outcomes expressed at different granularity, **when**
   the verifier evaluates them, **then** it returns `equivalent` rather than a
   blocking contradiction.
3. **Given** insufficient evidence or incompatible assumptions, **when** the
   verifier cannot decide, **then** it returns `undetermined` and preserves
   the candidate as diagnostic evidence.
4. **Given** a witness that is not stable across clean passes, **when** witness
   promotion is attempted, **then** it is rejected from decision evidence.

### User Story 4 - Consume SUE as governed workflow evidence (Priority: P3)

As an Echelon controller and human reviewer, I want SUE evidence persisted and
   routed through the workflow without contaminating cold readers or silently
   blocking implementation, so that findings are auditable and decision-relative.

**Why this priority**: Integration is valuable only after the measurement and
verification gates establish that the evidence is fit for purpose.

**Independent Test**: Feed a valid, stale, inconclusive, diagnostic, and
blocking-qualified SUE evidence package into the workflow adapter and verify
state ownership, routing, invalidation, and human override behavior.

**Acceptance Scenarios**:

1. **Given** a completed SUE package whose specification digest, decision
   context, policy, and tool/schema identity match the current run, **when**
   the controller consumes it, **then** it stores a digest-addressed evidence
   reference and a typed status without copying hidden reasoning.
2. **Given** a stale, corrupt, or mismatched package, **when** consumption is
   attempted, **then** the controller rejects it as unusable and does not route
   its findings as current evidence.
3. **Given** extraction instability, provider variance, aporia, or an
   unverified witness, **when** the workflow routes the result, **then** it is
   diagnostic/non-blocking and remains visible to the reviewer.
4. **Given** a verified, grounded, decision-material incompatibility and all
   promotion gates passed, **when** the workflow routes the result, **then** it
   may request review or return to the appropriate planning decision; it never
   rewrites the specification automatically.
5. **Given** a human override, **when** the workflow continues, **then** the
   override actor, reason, evidence digest, and resulting decision are
   recorded in the controller-owned audit trail.

### User Story 5 - Align vocabulary and source formats (Priority: P3)

As a SUE evaluator, I want declared glossary aliases and supported source
formats normalized without forced merges so that vocabulary differences are
not misclassified as semantic disagreement.

**Why this priority**: Canonical alignment improves measurement quality, but
must not hide genuine differences and is gated by A1 evidence.

**Independent Test**: Run the alignment fixtures and source-adapter fixtures
without provider calls, then verify exact, declared-alias, ambiguous, and
unsupported cases.

**Acceptance Scenarios**:

1. **Given** exact terms or declared aliases, **when** records are aligned,
   **then** they resolve to the same canonical term while retaining original
   labels and source citations.
2. **Given** an ambiguous alias, overlapping term, or conflicting glossary
   entry, **when** alignment runs, **then** the records remain unmatched and
   the ambiguity is reported rather than force-merged.
3. **Given** Markdown, generic-manifest, XML-ID, page-paragraph, Gherkin,
   OpenAPI, or ReqIF input, **when** the corresponding adapter is enabled,
   **then** it emits the same source-bundle contract or an explicit
   unsupported-format result with no silent source loss.
4. **Given** A1 has not passed, **when** a new adapter or canonicalizer is
   evaluated, **then** it may produce diagnostic evidence but cannot promote
   SUE to blocking workflow authority.

### User Story 6 - Adjudicate justification-graph quality (Priority: P3)

As a SUE researcher, I want a blinded human adjudication of graph evidence so
that graph conflict metrics are not treated as validated decision evidence
before their auditability is measured.

**Why this priority**: The graph is currently an instrumented pilot and needs
independent validation before it can influence blocking decisions.

**Independent Test**: Execute the pre-registered blinded packages with human
primary adjudication and cross-family review, then compare graph-only results
with the reference adjudication.

**Acceptance Scenarios**:

1. **Given** blinded claim/evidence packages and a known reference set, **when**
   reviewers adjudicate them, **then** completeness, provenance accuracy,
   conflict recovery, and reviewer disagreement are reported separately.
2. **Given** the graph fails its pre-registered completeness or auditability
   threshold, **when** the experiment closes, **then** the graph remains a
   diagnostic pilot and cannot independently create a workflow blocker.
3. **Given** a passing adjudication result, **when** the evidence is consumed,
   **then** the report records the gate version and does not generalize beyond
   the tested corpus and protocol.

### Edge Cases

- A reader returns valid JSON containing an ungrounded label or citation: the
  evidence item is quarantined and counted; the whole chunk is not discarded.
- A reader returns malformed structure, unknown requirement IDs, invalid edge
  types, impossible line numbers, or duplicate keys: the attempt is a hard
  validation failure and remains in the manifest.
- One provider or framing cell has partial reader loss: the report marks the
  cell incomplete and does not silently treat missing readers as agreement.
- A specification digest changes between extraction and workflow consumption:
  prior evidence is stale and cannot supply current findings.
- A candidate witness has only one cited side, only heuristic similarity, or no
  reproducible situation: it remains diagnostic and cannot block.
- A workflow run lacks a decision context or material-behaviour list: SUE
  evidence is inconclusive and cannot block.
- A provider is not approved for the specification's confidentiality class:
  the run stops before sending source content.
- The cost, call, or wall-clock budget is exhausted: the run records a bounded
  stop and does not convert partial output into a verdict.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST freeze and record the specification snapshot,
  specification digest, decision context, corpus membership, reader matrix,
  prompt/framing policy, schema version, model/provider identity, and cost
  policy before an A1 run begins.
- **FR-002**: The A1 protocol MUST use clean, human-approved specifications
  and at least two repeated passes with identical declared conditions.
- **FR-003**: The A1 gate MUST compute mean typed-edge agreement and the minimum
  per-spec agreement, preserving per-requirement scores and unmatched records.
- **FR-004**: The A1 gate MUST pass only when mean agreement is at least `0.80`
  and every included specification is at least `0.70`; thresholds MUST be
  versioned policy inputs and MUST NOT be weakened after a result is observed.
- **FR-005**: An A1 failure, invalid evidence package, or unreconstructable
  pass MUST produce a durable `FIX-EXTRACTION` or `HALT` outcome and MUST gate
  all downstream promotion experiments.
- **FR-006**: The parity experiment MUST use identical source units, decision
  contexts, schema, and prompt semantics across approved provider/model and
  framing cells, while recording every intentional difference.
- **FR-007**: Parity reporting MUST distinguish same-condition repeatability,
  provider/model variance, framing variance, and changed-condition
  reproducibility; it MUST NOT treat provider diversity as proof of epistemic
  independence.
- **FR-008**: The parity experiment MUST report cell completeness, retries,
  quarantined evidence, failed attempts, calls, tokens when available, and
  wall-clock duration.
- **FR-009**: Witness candidates MUST be intersected across clean passes before
  verification; a last-pass-only candidate MUST NOT become blocking evidence.
- **FR-010**: The witness verifier MUST evaluate an explicit situation and
  return exactly one of `incompatible`, `equivalent`, or `undetermined`.
- **FR-011**: An `incompatible` witness MUST include grounded citations to both
  sides, two outcomes that cannot both hold in the stated situation, the
  decision context, and a reproducible verification record.
- **FR-012**: `equivalent`, `undetermined`, unstable, or incompletely cited
  witnesses MUST remain diagnostic and MUST NOT block workflow decisions.
- **FR-013**: The workflow adapter MUST persist SUE evidence using a versioned,
  digest-addressed record containing status, report path, evidence digest,
  specification digest, decision-context identity, measurement-gate result,
  blocking findings, and diagnostic findings.
- **FR-014**: The workflow controller MUST be the sole writer of SUE state and
  journal entries; qualitative readers and reviewers MUST NOT recalculate,
  overwrite, or rewrite controller-certified evidence.
- **FR-015**: SUE evidence MUST be invalidated when specification digest,
  decision context, provider/model/framing matrix, policy, or tool/schema
  identity does not match the consuming workflow run.
- **FR-016**: The workflow adapter MUST route SUE after deterministic
  Understanding evidence and before qualitative consensus interpretation, with
  cold-reader outputs isolated from aggregate and workflow context.
- **FR-017**: Before A1 and witness-verification promotion gates pass, SUE
  findings MUST be diagnostic and non-blocking regardless of score.
- **FR-018**: After all required promotion gates pass, only verified,
  source-grounded, decision-material incompatibilities MAY request a blocking
  review; SUE MUST NOT automatically rewrite a requirement or implementation.
- **FR-019**: The system MUST support an explicit human override for every
  proposed blocking finding and record the override decision and rationale.
- **FR-020**: Every run MUST enforce a declared provider allowlist,
  confidentiality policy, call/token/wall-clock budget, retry policy, and stop
  condition, and MUST preserve raw and final evidence references for audit.
- **FR-021**: The system MUST expose report classifications that distinguish
  `VOCABULARY_DIVERGENCE`, `EXTRACTION_INSTABILITY`, `PROVIDER_VARIANCE`,
  `SPEC_AMBIGUITY_CANDIDATE`, `GROUNDED_CONTRADICTION`,
  `BEHAVIOURAL_INCOMPATIBILITY`, aporia states, and `BOUNDED_STOP`.
- **FR-022**: The feature MUST include zero-call tests for schema/provenance
  validation, no-forced-merge behavior, stale evidence rejection, partial
  reader degradation, witness verdicts, workflow routing, human override
  recording, and no specification writes.
- **FR-023**: The canonicalizer MUST apply alignment in this order: exact
  identifier, deterministic normalization, declared glossary alias, and
  type-constrained structural comparison; ambiguous matches MUST remain
  explicitly unmatched.
- **FR-024**: Canonicalization MUST preserve each original label, source span,
  run identity, and the reason for any match, mismatch, or ambiguity.
- **FR-025**: Every source adapter MUST declare its format, source identity,
  unit identifiers, source-span mapping, digest, and schema version; an
  unsupported or malformed format MUST fail explicitly without inventing
  requirements or dropping source provenance.
- **FR-026**: XML-ID, page-paragraph, Gherkin, OpenAPI, and ReqIF adapters MUST
  remain opt-in and non-blocking until their adapter fixtures and source-span
  coverage meet the approved acceptance threshold.
- **FR-027**: The justification-graph adjudication MUST use blinded packages,
  a pre-registered reference set, human-primary adjudication, cross-family
  review, and retained reviewer disagreement.
- **FR-028**: Graph adjudication MUST report completeness, provenance accuracy,
  known-conflict recovery, false conflict rate, and reviewer agreement with
  confidence intervals or an explicitly documented limitation.
- **FR-029**: A graph-adjudication failure MUST preserve the graph as a
  diagnostic instrument and MUST prevent it from independently producing a
  blocking workflow verdict.
- **FR-030**: A1, parity, witness, graph, adapter, and workflow gates MUST each
  have a versioned policy, named evidence package, explicit prerequisite, and
  durable pass/fail/inconclusive outcome.
- **FR-031**: The implementation plan MUST define a migration path from the
  current standalone reports to the workflow evidence contract without
  changing the meaning of historical artifacts.

### Key Entities

- **A1 Experiment Package**: Frozen corpus, reader matrix, policy, outputs,
  metrics, and gate verdict for extraction stability.
- **Parity Matrix**: Comparable provider/model/framing cells with completeness
  and variance measurements.
- **Witness Candidate**: A stable, grounded pair of differing behavioural
  consequences awaiting verification.
- **Witness Verdict**: The explicit situation-based result `incompatible`,
  `equivalent`, or `undetermined`, with evidence for both sides.
- **SUE Evidence Package**: Immutable report and manifest bound to source,
  decision context, execution identity, and schema version.
- **Workflow SUE Record**: Controller-owned reference and classification used
  for routing, audit, and invalidation.
- **Promotion Gate**: A versioned experimental condition that controls whether
  a later capability may influence workflow decisions.
- **Canonical Vocabulary Map**: A declared mapping of aliases to canonical
  terms that retains original labels and never resolves ambiguity silently.
- **Source Adapter**: A format-specific loader that produces source units and
  provenance under the portable source-bundle contract.
- **Graph Adjudication Package**: Blinded claims, evidence, reference labels,
  reviewer annotations, disagreement records, and gate metrics.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A1 produces a reproducible pass/fail report for 100% of included
  clean specifications, with no missing run identity or source digest.
- **SC-002**: The implementation reports the pre-registered A1 result without
  threshold changes and blocks downstream promotion when A1 fails.
- **SC-003**: In the parity experiment, 100% of provider/framing cells report
  completeness, configuration identity, and separated variance categories.
- **SC-004**: At least 95% of witness-verification test fixtures produce the
  correct verdict class and retain citations to both source sides where
  applicable.
- **SC-005**: 100% of stale, corrupt, digest-mismatched, or policy-mismatched
  evidence fixtures are rejected as current workflow evidence.
- **SC-006**: 100% of unverified, unstable, provider-variance, and aporia
  findings remain non-blocking in routing tests.
- **SC-007**: 100% of eligible blocking candidates require an explicit human
  review/override record before workflow continuation.
- **SC-008**: The focused zero-call SUE suite passes in both ambient-provider
  and provider-marker-cleared environments, with no writes to the challenged
  specification during any test.
- **SC-009**: Every accepted evidence package can be traced from workflow
  record to report, manifest, source digest, and execution configuration.
- **SC-010**: The feature's measured call, token, and wall-clock totals remain
  within the approved experiment budget, with bounded-stop behavior tested.
- **SC-011**: Alignment fixtures achieve 100% correct handling of exact,
  declared-alias, ambiguous, conflicting, and unknown-term cases without a
  forced merge.
- **SC-012**: Every enabled source adapter passes its source-identity,
  unit-coverage, digest, and source-span fixture suite; unsupported formats are
  reported explicitly.
- **SC-013**: The blinded graph study reports all pre-registered metrics and
  retains 100% of reviewer disagreements and provenance annotations.
- **SC-014**: A failed graph or adapter gate cannot produce a blocking workflow
  status, and its evidence remains auditable as diagnostic or inconclusive.

## Assumptions

- A1 remains the authoritative next experimental gate, as required by the SUE
  decisions and handoff.
- The current V3 source-bundle and evidence-manifest contracts remain the base
  for the new experiments.
- Provider approval and confidentiality classification exist or are supplied
  by the consuming project before any live run.
- Human adjudication is available for the calibration/reference annotations
  and for any proposed blocking workflow finding.
- The deterministic Understanding gate remains independent and is not replaced
  by SUE.
- Existing philosopher names remain labels for deterministic cognitive
  operators, not independent reader identities.

## Scope Boundaries

### In Scope

- A1 extraction-stability protocol and gate.
- Controlled provider/model/framing parity measurement.
- Cross-pass stable witness selection and situation-based verification.
- Declared glossary canonicalization and source-adapter contracts.
- Blinded justification-graph adjudication.
- Immutable SUE workflow evidence, routing, invalidation, and human override.
- Zero-call tests, evidence manifests, cost accounting, and audit reports.

### Out of Scope

- Automatic rewriting of requirements or source specifications.
- Treating agreement as truth or promoting unverified candidates to blockers.
- Replacing deterministic Understanding metrics.
- Full-corpus mutation studies before A1 passes.
- New philosopher personas, embedding-based forced alignment, or recursive SUE.
- Enabling every future source format before its adapter gate passes.
- Legal, patentability, or freedom-to-operate conclusions.
