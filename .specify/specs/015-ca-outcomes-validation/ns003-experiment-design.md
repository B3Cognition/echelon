# NS-003 Prototype Experiment Design
**Agent**: ARCHITECT (HOW) | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Covers**: REQ-015-006 (NS-003 Prototype Experiment Design)
**Status**: Experiment specification — not an implementation. Running this experiment is a post-spec engineering task.

---

## 1. Purpose

This document specifies a complete, self-contained experiment that a third party can execute to determine whether NS-003 (Self-Correcting Artifact Store) achieves acceptable compliance and contradiction-catching performance on Echelon's specific artifact protocol. It is a PASS/FAIL binary experiment with pre-registered verdict criteria.

The experiment tests two NS-003 components independently:
- **NS-003-A** (Generator-Critic): Does a deterministic Critic with retry loops produce acceptable schema compliance on Echelon agent outputs?
- **NS-003-B** (Belief Revision): Does an AGM-consistent belief graph correctly flag artificially injected contradictions with acceptable precision and recall?

---

## 2. Test Codebase

### Primary Recommendation: Echelon Extension Itself

**Path**: `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`

**Rationale**:
- (a) Known complexity: the Echelon extension has been fully analyzed in spec 014, so expected agent outputs are predictable and schema violations are detectable without ambiguity.
- (b) Already analyzed in spec 014: output structure, scope boundaries per agent, and contradiction failure modes (ISS-001: ASSESS reproducing DISCOVER findings) are documented.
- (c) Reproducible reference point: any third party running this experiment on the same codebase will encounter the same analysis task, enabling cross-run comparability and direct comparison with the U-CA-004 gate experiment (which uses the same codebase).
- (d) Non-trivial scale: 42 agent definitions across 7 tiers, plus COMMANDER dispatch protocol, schema definitions, and configuration — sufficient to expose scope violations and contradictions across adjacent agent stages.

**Alternative (if Echelon extension is unavailable)**: Any single well-understood Java or Python monorepo containing 20-50 files, with documented expected outputs for DISCOVER and ASSESS stages. The alternative must have a publicly accessible version to enable experiment reproduction.

---

## 3. Evaluation Set Sizes

### NS-003-A: Generator-Critic

**N = 30 agent invocations** on the test codebase.

**Rationale**: 30 invocations × estimated 5 schema fields per artifact section type = 150 field-level validation events. At 80% statistical power to detect compliance rate differences of 15 percentage points (e.g., 65% vs 80%), N=30 per condition is sufficient by normal approximation for a two-proportion z-test (α=0.05, two-tailed). The 30 invocations are distributed across all 6 analysis-tier agent types (DISCOVER, WHY, WHAT, ASSESS, HOW, PLAN) — 5 invocations per agent type minimum.

**Invocation distribution**:

| Agent Type | Target Invocations | Schema Complexity Rationale |
|---|---|---|
| DISCOVER | 5 | Highest field count per output; most likely to expose schema incompleteness |
| WHY | 5 | Causal chain assertions; tests relationship field types |
| WHAT | 5 | Enumeration fields; tests list and nested structure types |
| ASSESS | 5 | Cross-references DISCOVER fields; highest contradiction risk |
| HOW | 5 | Design decision fields; tests enum + narrative combination |
| PLAN | 5 | Task list structure; tests ordered sequence types |

### NS-003-B: Belief Revision

**N = 20 artificially contradicted artifact pairs**.

**Contradiction injection method**: Rule-based injection. This method is preferred over LLM adversarial generation or manual injection because: (a) it is deterministic and reproducible, (b) it produces a known ground truth with no labeling ambiguity, (c) it can be automated for exact reproduction.

**Injection protocol**:
1. Take a factual assertion from a DISCOVER output artifact (e.g., "This codebase uses Java 21").
2. Copy the full DISCOVER artifact to an ASSESS output context.
3. In the ASSESS artifact, change the value of the same field to a logically contradictory value (e.g., "This codebase uses Java 17").
4. The injected contradiction must be a direct logical contradiction (not a borderline ambiguity): the two values for the same field cannot both be true simultaneously.

**Contradiction categories (5 pairs per category, 20 pairs total)**:

| Category | Example Assertion (DISCOVER) | Example Contradiction (ASSESS) | Field Type |
|---|---|---|---|
| (a) Technology version | "Java 21" | "Java 17" | String enum |
| (b) File count | "42 agent definition files" | "38 agent definition files" | Integer |
| (c) Component count | "7 tiers" | "6 tiers" | Integer |
| (d) Pattern classification | "Sequential dispatch with EVOI" | "Parallel broadcast dispatch" | Categorical |

**Control set**: An equal-sized set of N=20 non-contradicted artifact pairs is used to measure false positive rate. These are real adjacent artifact pairs from prior Echelon spec runs (runs 008-014) with no injected contradictions.

---

## 4. Metrics with Formulas

### NS-003-A Primary Metric: First-Pass Compliance Rate (FPCR)

```
FPCR = (number of agent invocations where Critic accepts output on attempt 1)
       / (total agent invocations)
```

**Acceptance threshold**: FPCR ≥ 0.80

**Interpretation zones**:
- FPCR ≥ 0.80: PASS. The Generator-Critic mechanism produces acceptable compliance on Echelon's artifact protocol.
- 0.50 ≤ FPCR < 0.80: INCONCLUSIVE. The compliance rate is non-trivially above chance but below threshold. This zone indicates schema specificity problems: the schemas may be under-specified, leading to false rejection (Critic rejects valid output) or over-specified, leading to avoidable retry overhead. Action: redesign schema specificity for the failing agent types before proceeding.
- FPCR < 0.50: FAIL. The mechanism requires fundamental redesign for this task class. The Critic validation logic or the output schema is misaligned with how LLMs generate structured markdown. Action: diagnose whether failure is in schema design (structural mismatch) or retry prompt design (LLM cannot correct the specific error type signaled).

### NS-003-A Secondary Metric: Retry Resolution Rate (RRR)

```
RRR = (number of invocations where Critic rejected attempt 1 but accepted attempt 2)
      / (number of invocations where Critic rejected attempt 1)
```

**Purpose**: Reports self-correction capability. An RRR of 1.0 means every first-rejection was resolved on retry. A low RRR (< 0.50) means the retry prompt does not give the LLM sufficient information to fix the specific violation, and the CriticReport structure needs more precise error signaling.

**No acceptance threshold for RRR** (secondary metric; informational). Report alongside FPCR.

### NS-003-B Primary Metric: Contradiction Catch Rate (CCR)

```
CCR = (number of injected contradictions correctly flagged as ConflictSignal)
      / (total injected contradictions)
```

**Acceptance threshold**: CCR ≥ 0.80

**Definition of "correctly flagged"**: The belief graph emits a ConflictSignal event for the specific field where the contradiction was injected, before the contradictory assertion is committed to the artifact store. A ConflictSignal on a different field in the same artifact does NOT count as a correct catch for the injected contradiction.

### NS-003-B Secondary Metric: False Positive Rate (FPR)

```
FPR = (number of ConflictSignal events on non-contradicted control pairs)
      / (total non-contradicted control pairs evaluated)
```

**Acceptance threshold**: FPR ≤ 0.20

**Purpose**: Measures precision of the contradiction detection. A high FPR (> 0.20) means the belief graph is too sensitive — it raises ConflictSignal for legitimate field updates that are not contradictions (e.g., ASSESS refining a value from DISCOVER is expected behavior, not a contradiction).

---

## 5. Baseline Comparison

### Baseline Condition

The same 30 agent invocations are run **without** the Generator-Critic layer active. The LLM generates output in the standard Echelon mode (current production prompts, no Critic, no retry). The output is then evaluated post-hoc against the same schemas to measure raw compliance.

**Baseline metric**: Raw Compliance Rate (RCR)

```
RCR = (number of agent outputs that pass schema validation when evaluated post-hoc)
      / (total agent invocations)
```

Note: RCR is measured by applying the schema validator after the fact, not during generation. This is the compliance rate of raw LLM output before any Critic intervention.

### Comparison Logic

| Metric Pair | Interpretation |
|---|---|
| FPCR (with Critic) vs RCR (without Critic) | Measures the compliance lift from the Generator-Critic layer |
| If FPCR > RCR and FPCR ≥ 0.80 | The Critic improves compliance to acceptable level |
| If FPCR > RCR but FPCR < 0.80 | The Critic improves compliance but not enough; schema redesign needed |
| If FPCR ≤ RCR | The Critic either adds no value or degrades performance via over-rejection |

**Break-even criterion**: NS-003-A is justified (net positive) if the token overhead of retry calls (# retries × average retry token cost) is less than the cost savings from catching and correcting compliance failures at generation time vs catching them post-hoc with manual review.

---

## 6. Pre-registered Verdict Criteria

The verdict is determined before running the experiment. Results are evaluated against these criteria without adjustment.

### PASS
- NS-003-A: FPCR ≥ 0.80
- NS-003-B: CCR ≥ 0.80 AND FPR ≤ 0.20
- Both components must meet their thresholds for an overall PASS verdict.

**Action on PASS**: Proceed to NS-003 prototype implementation. The Echelon-specific validation confirms the mechanism is ready for prototype build. This does not constitute a production deployment decision.

### PARTIAL
- One component passes (meets threshold), one fails (falls below threshold or into INCONCLUSIVE zone).
- Report which component passed and which failed.
- Report the specific failure mode for the failing component (schema design failure, retry prompt design failure, belief revision precision failure, or false positive rate excess).

**Action on PARTIAL**: Redesign the failing component only. The passing component is considered validated at the prototype level. Do not re-run the passing component unless the redesign of the failing component changes the shared infrastructure (e.g., schema changes that affect both Critic validation and belief graph entry format).

### FAIL
- Both NS-003-A and NS-003-B fall below their thresholds (FPCR < 0.70 AND CCR < 0.70).
- Report the failure diagnostic:
  - If FPCR < 0.50: Generator-Critic mechanism requires redesign for this task class (structured markdown with soft constraints is fundamentally different from BNF-constrained Soar rule generation — the NL2GenSym analogy may not transfer).
  - If CCR < 0.50: Belief revision contradiction detection requires redesign (rule-based injection categories may be too coarse to match how the LLM actually represents these assertions, making exact-field matching unreliable).

**Action on FAIL**: Do not proceed to prototype implementation. Document as a domain-transfer failure of the NL2GenSym / Kumiho analogy to Echelon's artifact protocol. Report specific mismatch between source paper task class and Echelon task class.

---

## 7. Implementation Phases

These are technology-agnostic implementation phases. They prescribe what must be built, not how to build it, and do not estimate calendar duration.

### Phase 1: Schema Formalization

Produce a machine-parseable output schema for each of the 6 Echelon analysis-tier agent types: DISCOVER, WHY, WHAT, ASSESS, HOW, PLAN.

Each schema must specify:
- Required fields (failure to populate = Critic rejection)
- Field types (string, integer, enum, list, nested object)
- Cross-field constraints (if field A is populated, field B must not contradict it)
- Scope boundary (which facts this agent is permitted to assert — used by NS-003-B to distinguish scope violations from contradictions)

Schema format: JSON Schema Draft 2020-12 is recommended. The schema must be machine-executable by a Python validator (e.g., `jsonschema` library) without LLM involvement.

**Phase 1 completion criterion**: All 6 schemas parse and validate against known-good sample outputs from prior Echelon runs (runs 008-014). Zero false rejections on known-good samples.

### Phase 2: Generator-Critic Prototype

Build the deterministic Critic function and retry loop:

1. **Critic function**: `critic.validate(output, schema, artifact_store)` → `CriticReport`
   - Runs JSON Schema validation
   - Runs cross-artifact consistency check against belief graph
   - Outputs structured error report (field name, error type, conflicting existing assertion if applicable)

2. **Retry loop**: On Critic rejection, construct a retry prompt that includes:
   - Original agent prompt (unchanged)
   - The raw LLM output that failed
   - The CriticReport (specific field failures listed verbatim)
   - Instruction: "Revise only the fields listed in the violation report. Do not change fields that passed validation."

3. **Maximum retries**: 2 per invocation. After 2 failures, log the failure with full CriticReport and mark the invocation as `ESCALATED`.

**Phase 2 completion criterion**: Critic function correctly rejects 5 manually constructed invalid outputs (known schema violations) and accepts 5 manually constructed valid outputs for each of the 6 agent types. 60 acceptance/rejection decisions correct before proceeding to measurement phase.

### Phase 3: Belief Graph Prototype

Build the directed property graph with AGM-consistent update rule:

1. **Graph structure**: Directed property graph. Each node is a `BeliefNode` with: `content`, `source_agent`, `version_counter`, `confidence_score`, `field_identifier` (the schema field this assertion populates).

2. **Contradiction detection**: When a new assertion is submitted for a field that already has a `BeliefNode`, check logical consistency:
   - Integer fields: contradiction if |new_value - existing_value| > 0
   - String enum fields: contradiction if new_value ≠ existing_value
   - Categorical fields: contradiction if new_value is logically exclusive with existing_value (exclusion list defined per field in the schema)

3. **AGM revision operation**: On `ConflictSignal`, apply AGM K*2 (Success) — the newer, higher-evidence assertion supersedes the older one. The superseded node is retained in the graph with a `SUPERSEDED` flag and a `superseded_by` edge to the new node. This implements minimal change (K*3) and preservation (K*5) by retaining the prior belief with its provenance rather than deleting it.

4. **False positive prevention**: Before emitting `ConflictSignal`, check whether the new assertion is a legitimate refinement of the existing one (value is more specific, not contradictory). Define per-field refinement rules in Phase 1 schemas.

**Phase 3 completion criterion**: Belief graph correctly emits `ConflictSignal` on all 20 injected contradictions from the test set constructed in Phase 1, and does not emit `ConflictSignal` on 20 known-good non-contradicted pairs. This is the pre-measurement calibration check.

### Phase 4: Measurement Run

Execute the full experiment:
- 30 agent invocations on the Echelon extension test codebase with Generator-Critic active (NS-003-A measurement)
- 30 agent invocations on the same codebase without Generator-Critic (baseline RCR measurement)
- 20 artificially contradicted artifact pairs submitted to the belief graph (NS-003-B CCR measurement)
- 20 non-contradicted control pairs submitted to the belief graph (NS-003-B FPR measurement)

Record all metrics per-invocation with: invocation ID, agent type, attempt number, Critic verdict (PASS/FAIL per attempt), ConflictSignal events (with field identifier and whether contradiction was injected), token count per attempt.

Apply pre-registered verdict criteria to the measurement results.

---

## 8. Experiment Reproducibility Requirements

Any third party executing this experiment must:
1. Use the same test codebase (`/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/` or a named public alternative)
2. Use the schemas produced in Phase 1 without modification
3. Use the same 20 contradiction injection pairs (stored as a static labeled dataset, not regenerated per run)
4. Use the same LLM version for all 60 agent invocations within a single experiment run (version lock — record the exact API model string)
5. Apply verdict criteria exactly as pre-registered in Section 6 without post-hoc threshold adjustment

---

## 9. Relationship to U-CA-004 Gate Experiment

This NS-003 experiment and the U-CA-004 gate experiment share the same recommended test codebase. This is intentional: if both experiments pass, the evidence base for NS-003 (component-level + Echelon-specific) and for CA overlays (U-CA-004 positive) can be combined to assess the net benefit of the full integrated system. Cross-experiment comparability requires consistent test codebase and LLM version.
