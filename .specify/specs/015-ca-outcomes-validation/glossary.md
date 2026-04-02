# Glossary — Spec 015 (CA Outcomes Validation)
**Agent**: SCOUT | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Purpose**: Precise definitions for all technical terms appearing in the claimed spec 014 outcomes. Each entry states what the term is, what it is NOT, and how it is measurable for validation purposes.

---

## Generator-Critic

**What it is**: A two-component pipeline where a Generator produces a structured output (an artifact section, a rule, a schema-conformant document) and a Critic validates that output against a formal specification — a JSON Schema, a typed interface, or execution feedback from an external runtime. The Critic is a deterministic function, not an LLM. Validation failure triggers a retry loop with the specific error signal injected into the Generator's next prompt.

**Source**: NL2GenSym (arxiv:2510.09355, preprint Oct 2025). In NL2GenSym, the Generator produces Soar production rules from natural language; the Critic is the Soar interpreter which executes the rules and returns a pass/fail signal. The feedback loop runs up to N retries until the output passes formal execution validation.

**What it is NOT**:
- Not "LLM-as-judge": the Critic does not call another LLM to evaluate quality in prose. The Critic is a formal execution or schema-parsing process.
- Not Self-Refine (Madaan et al. 2023, NeurIPS): Self-Refine uses an LLM to critique its own prior output in natural language. Generator-Critic uses external formal validation as ground truth. This distinction is load-bearing for the novelty claim.
- Not a reward model or RLHF signal.

**Measurable metric for validation**:
- Schema compliance rate: percentage of generator outputs that pass Critic validation on the first attempt, across N trials.
- NL2GenSym baseline: 86%+ first-pass success on the Water Jug Problem in Soar (preprint measured result).
- For Echelon: first-pass compliance rate of agent outputs against the Echelon artifact protocol schema (structured markdown sections).

---

## Belief Revision / AGM Postulates

**What it is**: A formal framework for updating a belief set K when a new belief p is incorporated and p contradicts something in K. The AGM postulates (Alchourrón, Gärdenfors, Makinson 1985) specify six properties that any rational revision operation must satisfy:
- K*2 (Success): p is always in the revised set K*p.
- K*3 (Inclusion): K*p ⊆ K + p (no beliefs added beyond what p entails).
- K*4 (Vacuity): If ¬p is not in K, K*p = K + p (no change to consistent beliefs).
- K*5 (Consistency): K*p is consistent if p is consistent.
- K*6 (Extensionality): Logically equivalent inputs produce logically equivalent revisions.

In NS-003, belief revision is triggered when the Critic detects a ConflictSignal: the new artifact assertion contradicts an existing BeliefNode in the property graph. The revision operation supersedes the lower-evidence node and propagates stale flags to dependent nodes.

**Source**: Kumiho (arxiv:2603.17244, March 2026). Kumiho operationalizes AGM revision in a property graph (Redis + Neo4j architecture). Measured result: 93.3% accuracy on LoCoMo-Plus vs 45.7% baseline. The improvement is attributed to prospective indexing (write-time implication generation) and AGM-compliant revision (not ad hoc overwrite).

**What it is NOT**:
- Not "overwrite last-write-wins": naive overwrite is not AGM-compliant (it violates K*3 and K*5).
- Not Bayesian updating: AGM revision is deductive (consistency-preserving), not probabilistic. The Kalman filter analog (NOVEL-005) is the Bayesian alternative.
- Not contradiction detection alone: belief revision is the resolution step that occurs after contradiction detection. Detection without revision is incomplete.

**Measurable metric for validation**:
- Contradiction catch rate: proportion of inter-artifact contradictions caught before commit (requires a labeled test set of contradictory artifact pairs).
- Revision correctness: after revision, the belief graph must satisfy all AGM postulates (formally verifiable for a given graph snapshot).
- Baseline comparison: Kumiho's 93.3% vs 45.7% establishes the benchmark for belief graph accuracy on a multi-turn conversation dataset. Echelon's equivalent is multi-stage artifact consistency.

---

## Predictive Coding Broadcast / Prediction Error

**What it is**: A communication architecture inspired by Rao & Ballard 1999 ("Predictive coding in the visual cortex," Nature Neuroscience) in which upstream agents produce not only their findings but also a forward prediction of what the downstream agent will find. The downstream agent performs a prediction check: if its actual analysis matches the prediction within tolerance ε, no LLM call is needed for that finding. If the check fails (prediction error > ε), the LLM is invoked and the error signal is propagated back to update the forward model.

The inter-agent message format is: `{finding, prediction, confidence}`. The routing layer computes: `error = distance(prediction, actual_check)`. LLM invocation is gated on: `error >= ε`.

**Analogy reference**: Speculative Decoding (Leviathan et al., arxiv:2211.17192, 2022), which achieves 2-3x token throughput by having a small model predict tokens and a large model verify. NOVEL-004 applies the same logical structure at the semantic abstraction level: agent findings instead of tokens. The analogy is acknowledged; it does not constitute Grade A evidence for the agent-level mechanism.

**What it is NOT**:
- Not the same as Speculative Decoding: Speculative Decoding operates at the token level within a single LLM call. NOVEL-004 operates at the agent-output level across pipeline stages. The mechanisms are analogous, not identical.
- Not a routing rule: prediction is upstream (before the downstream agent runs), not a post-hoc routing decision.
- Not proven for multi-agent pipelines: no published study applies predictive coding semantics to LLM agent pipelines. This is an open research claim.

**Measurable metric for validation**:
- Prediction accuracy: proportion of upstream predictions confirmed by downstream agents' actual analysis.
- LLM call reduction: count of downstream LLM calls eliminated by confirmed predictions vs baseline (all agents always called).
- Break-even prediction accuracy: approximately 40-50% correct predictions are needed for overhead costs to be offset (estimated from speculative decoding break-even analysis — not measured for this context).

---

## Proof vs Experimental Validation vs Speculation

**Proof** (Grade A — used in this spec): A claim is proven when a peer-reviewed study or preprint with measured results provides direct empirical evidence for the claimed effect on a directly comparable task, with explicit quantification. Example: NL2GenSym's 86%+ schema compliance is proof that the Generator-Critic mechanism achieves high first-pass compliance on structured rule generation tasks.

**Proven by design** (Grade B/C): A claim is supported by design when the mechanism design is logically consistent with the stated benefit, and analogous systems have demonstrated the benefit in adjacent domains, but no direct measurement exists for the specific Echelon context. Example: AC-3 constraint propagation is well-established for CSP problems; its benefit for pruning LLM agent output space is a logical extension, not a direct measurement.

**Experimental validation required** (Grade D): A claim that requires a prototype implementation and controlled measurement before a verdict is possible. The experiment design is defined; the measurement has not been performed. Example: the U-CA-004 gate experiment — three conditions, same LLM, same task class, measuring CA vs expert prompting — is defined but not executed.

**Speculation** (explicitly labeled): A claim that is directionally motivated by theory or analogy but has no measurement, no clear experiment design, or insufficient prior evidence to justify a specific quantitative range. The spec 014 original answer explicitly labeled the 40-70% token reduction claim as SPECULATION. This label means: do not use as a decision basis; treat as a research hypothesis requiring proof before any design commitment.

---

## Schema Compliance (as measurable metric)

**Definition**: The proportion of agent outputs that successfully parse against a formally defined schema for that agent's output type, on first attempt.

**Schema types applicable to Echelon**:
1. JSON Schema validation: required fields present, correct types, enum constraints satisfied.
2. Typed TypeScript interface equivalents (structural type check on output structure).
3. Structured markdown section validation: required section headers present, minimum content length per section met, no forbidden cross-section content (scope constraint).

**Measurement protocol**:
- Define the schema for each Echelon agent's output type (discovery, analysis, architecture, etc.).
- Run N agent invocations against a fixed codebase.
- Count first-pass compliance rate (no Critic retry needed).
- NL2GenSym baseline: 86%+ (preprint, measured). This is the benchmark to beat or match.

**What it is NOT**: Schema compliance is not the same as correctness. An agent output can be schema-compliant (all required fields populated) while being factually wrong. Schema compliance measures structural validity, not semantic accuracy. The belief revision layer addresses semantic consistency; the Critic addresses structural compliance.

---

## Token Efficiency (as measurable metric)

**Definition**: The ratio of useful information tokens (tokens in the agent output that represent novel findings, not repetition of prior context) to total tokens consumed (prompt tokens + completion tokens) per agent invocation.

**Operationalized as**:
- Tokens-per-run: total tokens consumed in a complete Echelon pipeline run.
- Redundancy ratio: proportion of output tokens that duplicate content already in the artifact store (measurable with cosine similarity or BM25 over artifact store).
- Context fill rate: proportion of injected context tokens that the model actually attends to (not directly measurable via black-box API; estimated by context ordering experiments).

**Baseline**: Currently no baseline measurement exists for Echelon token consumption per run. This is U-CA-009 (OPEN). Without a baseline, no efficiency claim can be validated.

**ACON ceiling**: ACON (arxiv context compression, Grade A) demonstrates 22-54% token reduction via managed context. This is the algorithmic ceiling for context compression, not a CA-specific result (ISS-003 in spec 014 issues register). Any CA mechanism must be compared against ACON's compression baseline, not just against naive full-context injection.

---

## Scope Violation (as observable event in Echelon)

**Definition**: An observable event in which an Echelon agent's output contains findings or assertions that fall outside the agent's declared scope, as defined by the Echelon artifact protocol for that agent's role.

**Examples of scope violations identified in spec 014**:
- ASSESS agent reproducing DISCOVER findings verbatim as if they were risk assessments.
- PLAN agent asserting causal claims that are WHY's scope.
- HOW agent producing requirements (CARTOGRAPHER's scope) instead of architecture designs.

**Current detection mechanism**: Manual human review of final artifacts. No automated detection exists.

**Measurable proxy**: Phi-proxy (NOVEL-002) provides an automated proxy: the proportion of an agent's output tokens that are near-verbatim duplicates of prior artifact store content. High duplication = probable scope violation (the agent is repeating rather than generating within scope). This proxy conflates reformulation with violation and requires calibration.

**Baseline rate**: Unknown. No historical measurement of scope violation frequency across Echelon runs exists. This is a prerequisite for measuring improvement from any CA mechanism.
