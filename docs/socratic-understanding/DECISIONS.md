# Socratic Understanding decisions

**Status:** authoritative
**Rule:** only accepted decisions belong here. Proposed architecture choices
remain in `HANDOFF.md` or `OPEN-QUESTIONS.md` until approved.

## Decision register

### SU-D001 — Authority order

**Decision:** `SPECIFICATION.md` and `DECISIONS.md` are authoritative.
`TRANSCRIPT.md` is historical background only.

**Rationale:** the source discussion evolved and contains tentative or corrected
ideas. Curated documents must prevent old phrasing from silently regaining
authority.

### SU-D002 — Agreement is not truth

**Decision:** never equate reader/agent agreement with truth, authorial intent,
or implementation correctness.

**Rationale:** multiple runs can share common-mode errors or converge socially.
Agreement is evidence of reproducibility under stated conditions.

### SU-D003 — Cold reconstruction isolation

**Decision:** interpretation runs operate independently before aggregation.
They do not receive other interpretations, aggregates, divergence reports,
reasoning journals, or squad state.

**Rationale:** exposure would contaminate the sample and make convergence partly
a product of coordination.

**Repository alignment:** the original SRP isolation contract routes directly
through model-provider calls rather than squad dispatch; standalone SUE calls
use neutral temporary working directories.

### SU-D004 — Structured operators over philosopher personas

**Decision:** use explicit cognitive operators and deterministic transition
policies. Platonic names may label lens policies, but cold readers are not
philosopher personas.

**Rationale:** personas add uncontrolled priors and stylistic confounds.
Operators are inspectable and testable.

### SU-D005 — Provenance is mandatory

**Decision:** every scored claim, edge, assumption, conflict, and behavioural
assertion links to a source requirement/span or is explicitly marked
ungrounded. Run/provider/framing identity is preserved.

**Rationale:** ungrounded agreement is not auditable evidence.

### SU-D006 — Preserve disagreement

**Decision:** aggregation retains minority variants, unmatched records, and
sampling noise. It never force-merges interpretations to manufacture consensus.

**Rationale:** disagreement is the diagnostic signal.

### SU-D007 — Separate uncertainty layers

**Decision:** report vocabulary divergence, extraction instability,
provider/model variance, and specification ambiguity separately.

**Rationale:** the same observed difference can originate in the specification,
the extractor, the model sample, or the alignment procedure. Repair depends on
which layer failed.

### SU-D008 — Behavioural consequences outrank text similarity

**Decision:** material compatibility is evaluated through grounded relations and
behavioural consequences, not raw prose similarity alone.

**Rationale:** different wording can mean the same thing, and similar wording can
mandate incompatible behaviour.

### SU-D009 — Aporia is diagnostic

**Decision:** `APORIA_UNDEFINED`, `APORIA_CONTRADICTED`, and
`APORIA_UNDERDETERMINED` are legitimate diagnostic outcomes. `BOUNDED_STOP` is
not a verdict.

**Rationale:** forcing an answer hides missing definitions, conflict, or
underdetermination.

### SU-D010 — Diagnose only; never silently rewrite

**Decision:** SUE does not edit the challenged specification. A separate,
explicitly approved change workflow owns any rewrite.

**Rationale:** diagnosis and authorial change have different authority and audit
requirements.

### SU-D011 — Deterministic baseline remains distinct

**Decision:** SUE supplements, not replaces, Echelon's provider-free
Understanding metrics. The two evidence channels remain separately identifiable.

**Rationale:** deterministic quality metrics are cheap and reproducible; sampled
semantic reconstruction has different variance and cost.

### SU-D012 — SRP before workflow authority

**Decision:** validate the Semantic Reproducibility Probe before granting SUE
blocking workflow authority.

**Current interpretation:** the original probe specification and smoke run
already exist. The next gate is extraction stability (A1), not rebuilding the
greenfield prototype.

### SU-D013 — Experimental failure is a valid result

**Decision:** if a pre-registered gate fails, record FIX-EXTRACTION or HALT.
Do not weaken thresholds after observing results merely to promote the system.

**Rationale:** the subsystem is intended to test understanding, so its own
claims must be falsifiable.

### SU-D014 — Decision-relative evaluation

**Decision:** compatibility is relative to a stated engineering decision and its
material behaviours. Non-material divergence remains visible but does not
automatically block.

**Rationale:** not every ambiguity matters to every implementation, test, or
architecture decision.

### SU-D015 — Controller-owned evidence

**Decision:** integrated measurement evidence and certified state are
controller-owned. Qualitative agents may interpret but may not recalculate or
overwrite them.

**Rationale:** this matches Echelon's current Understanding evidence boundary and
prevents sampled agents from certifying their own output.

### SU-D016 — Human authority over normative changes

**Decision:** a model may identify a missing decision or propose a question, but
it cannot invent the normative answer and present it as specification truth.

**Rationale:** source silence must remain visible; human/product authority owns
new requirements.

### SU-D017 — Privacy and cost are part of the evidence

**Decision:** every run discloses that specification content is sent to the
selected provider and records call, model/provider, timeout, and cost-relevant
configuration.

**Rationale:** reproducibility, confidentiality, and operational viability
depend on these facts.

## Decisions explicitly not yet accepted

The following are proposals, not decisions:

- the exact `decision_context` schema;
- adding a `phase3-socratic-understanding` workflow node;
- exact controller state and journal type names;
- promoting stable SUE findings to blocking severity;
- glossary-canonical alignment semantics;
- the witness-verification call contract;
- justification-graph promotion after H-D2;
- the full corpus budget; and
- whether this handoff supersedes or indexes all earlier SUE design documents.
