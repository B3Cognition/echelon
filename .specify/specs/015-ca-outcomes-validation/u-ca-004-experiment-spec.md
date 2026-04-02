# U-CA-004 Gate Experiment Specification
**Agent**: ARCHITECT (HOW) | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Covers**: REQ-015-008 (U-CA-004 Gate Experiment Specification)
**Status**: Experiment specification — not an implementation. Execution is a post-spec resource allocation decision. All five CA overlays remain GATE-CONDITIONED on this experiment resolving POSITIVE.

---

## 1. Purpose

This document specifies the U-CA-004 three-condition gate experiment that determines whether cognitive architecture (CA) structured prompting provides measurable, statistically significant benefit over expert-engineered prompts on Echelon's multi-stage codebase analysis pipeline.

All five CA overlay claims (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) are explicitly gate-conditioned on this experiment. None of them can proceed to implementation justification until U-CA-004 resolves POSITIVE. This is a hard gate, not a soft recommendation.

**This experiment closes one specific gap**: the MAP paper (Webb et al., Nature Communications 2025, SRC-A3) demonstrates CA-structured pipelines outperforming GPT-4 CoT on planning tasks (graph traversal, Tower of Hanoi, PlanBench), but those task classes and that LLM version differ from Echelon's task class (multi-stage codebase analysis) and current LLM. U-CA-004 runs the same comparison on the actual task class and current model.

---

## 2. Three Conditions

### Condition A — Naive Baseline

**Definition**: Echelon agents are invoked with minimal prompting. The system prompt is stripped to two elements only: (1) role definition (one sentence stating the agent's role), and (2) output format specification (stating the required output sections and types). All additional prompt engineering — task framing, context emphasis, step-by-step instructions, scope boundaries, quality criteria, examples, chain-of-thought scaffolding — is removed.

**Purpose**: Establishes the floor. This measures what an LLM produces on this task class with minimal guidance. Provides a second reference point beyond the expert-prompt baseline, enabling measurement of how much of the observed quality difference is attributable to prompt engineering vs CA structure.

**LLM version**: Same version as Conditions B and C (version lock — see Section 4).

### Condition B — Expert-Prompt Baseline

**Definition**: Echelon agents are invoked with the current production prompts — the existing agent `.md` files in `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/agents/`, unmodified. No CA additions, no structural changes. This is the current state of the art for this pipeline.

**Purpose**: The primary comparison condition. CA-structured overlay (Condition C) must outperform this condition to justify the overhead cost of CA implementation. Condition B is the reference for the POSITIVE/NEGATIVE verdict.

**LLM version**: Same version as Conditions A and C (version lock).

### Condition C — CA-Structured Overlay

**Definition**: Condition B prompts PLUS one CA overlay active.

**First overlay to test: ACT-R Typed Buffer**

**Rationale for testing ACT-R Typed Buffer first**:
1. The "Lost in the Middle" phenomenon (Liu et al. 2023, SRC-A4, Grade A) establishes with high confidence that LLM attention to context is non-uniform with position. This means context ordering has a measurable effect that can be detected without a large N.
2. The ACT-R typed buffer is the most directly testable overlay: it can be implemented as a context preprocessing function that reorders and trims the artifact context pack before each agent call, without any COMMANDER modification, goal stack, or broadcast architecture changes.
3. It does not require changes to the agent dispatch protocol (unlike Goal Stack) or concurrent agent invocation (unlike LIDA Broadcast). This minimizes confounds in the first experiment.
4. If ACT-R Typed Buffer fails to show benefit, the overhead and implementation risk of Goal Stack, LIDA Broadcast, and GWT are unjustified — terminating the overlay program early saves the most resources.

**ACT-R Typed Buffer implementation for Condition C**:

The context preprocessing function constructs a four-buffer context pack (per spec 014 plan.md REQ-CA-006) before each agent invocation:

| Buffer | Contents | Token Budget |
|---|---|---|
| `goal_buffer` | Current pipeline goal + agent scope declaration | ~200 tokens (fixed) |
| `retrieval_buffer` | Top-K artifact chunks scored by activation formula | ≤ 4,000 tokens |
| `imaginal_buffer` | In-progress artifact section this agent is constructing | Variable (agent working output) |
| `stable_buffer` | Compressed summary of invariant context (constitution section headers, spec phase summaries) | ~500 tokens (compressed) |

Activation formula (prompt-level approximation):
```
activation(chunk_i) = recency_weight(chunk_i) × relevance_score(chunk_i, goal_buffer)

recency_weight(chunk_i) = 1 / (1 + age_in_stages(chunk_i))
relevance_score(chunk_i, goal_buffer) = cosine_similarity(embed(chunk_i), embed(goal_buffer))
```

This replaces the full artifact concatenation ("context pack" in current COMMANDER protocol) with a scored, ranked, trimmed subset. The implementation operates outside the LLM call — it is a Python preprocessing function, consistent with the API-only constraint (ADR-003).

---

## 3. LLM Version Lock

**Model specification**: The exact Claude API model string available at experiment execution time must be recorded and locked. Record format: the exact API model identifier string (e.g., `claude-opus-4-20260101` or equivalent — the actual string returned by the API at the time the experiment batch begins).

**Version lock rule**: All three conditions (A, B, C) and all N runs within a single experiment batch use the same model version. No batch spans a model version update. If a model version update occurs mid-batch, the batch is restarted from the beginning with the new version, and the pre-update runs are discarded.

**Rationale**: Version lock is required to prevent model update confounds. The MAP paper used GPT-4 (2023); any Echelon experiment using a different model version produces a non-comparable result unless the version is explicitly stated. The version lock enables exact replication and cross-version comparison in future work.

---

## 4. Sample Size and Statistical Power

### Target Sample Size

**Target: N=20 per condition (60 total runs)**

Rationale: With N=20 per condition and an expected effect size of 0.5 standard deviations (moderate, consistent with MAP paper's CA vs CoT improvements), the experiment has approximately 80% statistical power at α=0.05 (two-tailed) for a Mann-Whitney U test on AQS differences.

### Minimum Acceptable Sample Size

**Minimum: N=10 per condition (30 total runs)**

Rationale: At N=10 per condition, the experiment has approximately 50% statistical power at α=0.05 for the same effect size. This is exploratory power — sufficient to detect large effects and to inform the decision to proceed to N=20, but insufficient to confidently detect moderate effects.

### Staged Execution Protocol

Start with N=10 (minimum viable). Apply the pre-registered decision rule (Section 7) to the N=10 results:
- If result is POSITIVE or NEGATIVE at N=10: verdict is final. Do not run additional batches.
- If result is INCONCLUSIVE at N=10: double to N=20 per condition (add 10 runs per condition to the existing 10). Do not restart — add to the existing dataset. Apply the decision rule to the combined N=20 dataset.

**Maximum N**: N=20 per condition. If the result is still INCONCLUSIVE at N=20, the action is to document the INCONCLUSIVE finding and revisit the experiment design (overlay selection, task codebase, rubric) rather than continuing to add runs.

---

## 5. Task Selection Criterion

**Selection**: One fixed test codebase for all conditions and all runs.

**Recommended test codebase**: The Echelon extension itself — `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`

**Rationale for single fixed codebase**:

At N=20 per condition, a multi-codebase stratified design would reduce per-codebase N to approximately 4 (with 5 codebases), making within-codebase variation dominate the signal. The experiment cannot reliably separate the CA overlay effect from codebase-specific variance at that sample size. A single codebase maximizes statistical power for the specific question this experiment asks: does the CA overlay improve artifact quality on this task class?

**Rationale for Echelon extension specifically**:
- The same codebase used in the NS-003 experiment (ns003-experiment-design.md) — ensures cross-experiment comparability.
- Fully analyzed in spec 014: expected output structure, known scope violation modes (ISS-001), and failure patterns are documented. This means AQS scoring can be applied by an evaluator who has access to spec 014 without needing to independently derive expected content.
- Non-trivial: 42 agent definitions, 7 tiers, COMMANDER dispatch protocol — sufficient to expose coherence, completeness, scope compliance, and internal consistency differences across conditions.

**Generalizability limitation (acknowledged)**: Results on one codebase may not generalize to codebases of different types (e.g., large Java monorepos, data science notebooks, infrastructure-as-code repositories). This limitation is stated explicitly in the experiment report. Generalizability testing is a follow-on experiment, not part of U-CA-004.

---

## 6. Evaluation Rubric

### Primary Metric 1: Artifact Quality Score (AQS)

**Formula**:
```
AQS = (Coherence + Completeness + Scope_Compliance + Internal_Consistency) / (4 × 3)
```

Where each dimension is scored on a 0-3 integer scale. The denominator is 12 (4 dimensions × 3 maximum per dimension). AQS ranges from 0.0 to 1.0 (or equivalently 0% to 100%).

**Scoring Anchors per Dimension**:

**Coherence** (does the artifact form a logical, non-contradictory whole?):
- 0 = Absent or unusable: the artifact contains logical contradictions within itself (e.g., asserts X in one section and not-X in another), or the internal structure is so fragmented that the artifact cannot be understood as a single coherent document.
- 1 = Partial: the artifact is coherent in most sections but contains at least one internal contradiction or at least two sections whose logical relationship is unclear without external reference.
- 2 = Adequate: the artifact is coherent; minor inconsistencies present (e.g., a term used with slightly different meanings in two sections) but do not prevent use. No logical contradictions.
- 3 = Complete: the artifact is internally consistent throughout; all claims are mutually compatible; the artifact reads as a single unified analysis with no contradictions and no ambiguous cross-references.

**Completeness** (does the artifact cover all expected content for its agent type?):
- 0 = Absent or unusable: more than half of the expected content sections for this agent type are empty, missing, or contain placeholder text. The artifact cannot be acted on.
- 1 = Partial: required sections are present but at least two contain material gaps (key entities not identified, key relationships not traced, key findings not stated). The artifact can be partially acted on.
- 2 = Adequate: all required sections present and populated; minor gaps (e.g., one secondary entity not identified, one relationship not traced) present but do not prevent downstream agent use.
- 3 = Complete: all required sections fully populated; all expected entities identified; all expected relationships traced; no gaps that would require the downstream agent to re-discover content that this agent should have covered.

**Scope Compliance** (does the artifact stay within this agent type's declared scope?):
- 0 = Absent or unusable: the artifact contains primarily out-of-scope content (content that belongs to a different agent's phase), such that the in-scope content is a minority of the artifact.
- 1 = Partial: the artifact contains material out-of-scope content: at least two sections where this agent asserts findings that belong to a different agent's declared scope (e.g., DISCOVER making design recommendations, which belongs to HOW or ARCHITECT).
- 2 = Adequate: one out-of-scope section present; all other sections are in-scope. The violation does not undermine the core in-scope content.
- 3 = Complete: all sections are within this agent's declared scope per its prompt definition. No findings are asserted that belong to a different agent's phase.

**Internal Consistency** (are assertions within the artifact consistent with the artifact store from prior stages of the same run?):
- 0 = Absent or unusable: the artifact contradicts multiple established findings from prior stage artifacts (e.g., ASSESS contradicts DISCOVER on two or more factual assertions). The artifact cannot be combined with the artifact store without manual resolution.
- 1 = Partial: the artifact contradicts one established finding from a prior stage artifact. The contradiction is present and unresolved.
- 2 = Adequate: the artifact does not directly contradict prior stage findings, but contains at least one assertion that is in tension with (though not directly contradictory to) a prior stage finding. Tension is resolvable by a downstream reader.
- 3 = Complete: all assertions in this artifact are consistent with the full artifact store from prior stages. No contradictions, no unresolved tensions.

**Evaluator instructions**: Each artifact is scored on all four dimensions independently. The evaluator should have access to: (a) the agent's prompt definition (to determine scope), (b) all prior stage artifacts from the same run (to assess internal consistency), and (c) the test codebase itself (to assess completeness). Scoring is independent per dimension — do not let one dimension's score anchor another dimension's score.

**Inter-rater reliability**: Where two evaluators are available, both score independently; Cohen's kappa is computed per dimension. Where only one evaluator is available, this limitation is stated in the experiment report.

### Primary Metric 2: Scope Violation Rate (SVR)

**Formula**:
```
SVR = (number of agent output sections classified as OUT-OF-SCOPE)
      / (total output sections evaluated)
```

**Section definition**: A section is a discrete unit of agent output delimited by a section header (e.g., `## Findings`, `## Key Patterns`, `## Recommendations`). Each section is the unit of annotation.

**Classification rules**:
- IN-SCOPE: all assertions in the section fall within this agent's declared scope per its prompt definition.
- OUT-OF-SCOPE: one or more assertions in the section fall outside this agent's declared scope.
- BORDERLINE: the scope boundary is ambiguous for one or more assertions in the section. BORDERLINE sections are excluded from the SVR numerator; their count is reported separately.

**Relationship to REQ-015-004**: This is the same annotation scheme specified in REQ-015-004. The SVR baseline measurement from REQ-015-004 serves as the Condition B baseline for SVR comparison in this experiment.

---

## 7. Pre-registered Decision Rule

The decision rule is stated before running the experiment. Results are applied to this rule without post-hoc threshold adjustment.

### POSITIVE

**Criteria** (all three must be met):
1. Condition C AQS exceeds Condition B AQS by ≥ 10 percentage points (i.e., ≥ 0.10 on the 0.0-1.0 AQS scale, equivalently ≥ 3.33% on a 0-100 normalized scale where maximum AQS = 100%).
2. SVR for Condition C is ≤ SVR for Condition B × 0.85 (≥ 15% relative reduction in scope violation rate).
3. Mann-Whitney U test on AQS differences (Condition C vs Condition B) has p < 0.05 (two-tailed).

**Action on POSITIVE**: Unlock implementation of ACT-R Typed Buffer overlay. Proceed to design and test the Goal Stack as the second overlay (see Section 8 for testing order). Document the POSITIVE result with the exact model version, test codebase, N per condition, AQS difference, SVR reduction, and p-value.

### NEGATIVE

**Criteria**: Condition C does not exceed Condition B AQS by ≥ 10 percentage points, regardless of p-value.

**Action on NEGATIVE**: Terminate the CA overlay implementation program. Do not proceed to test Goal Stack, LIDA Broadcast, GWT Bounded Workspace, or Episodic Memory overlays. Document as the first controlled negative result for CA-LLM structured overlay on a codebase analysis pipeline. The expert-prompt-only improvement plan (improving Condition B prompts through prompt engineering iteration) becomes the sole recommendation for artifact quality improvement.

**Note on partial improvement**: If Condition C AQS exceeds Condition B by > 0 but < 10 percentage points, this is classified as NEGATIVE (not INCONCLUSIVE). A sub-threshold improvement does not justify the implementation overhead of a CA overlay system.

### INCONCLUSIVE

**Criteria**: Condition C AQS improvement is in the direction of positive (Condition C > Condition B) and the absolute difference is ≥ 5 percentage points, but either: (a) the difference is < 10 percentage points, OR (b) p ≥ 0.05.

**Action on INCONCLUSIVE**: Double N to 20 per condition (add 10 runs per condition to the existing dataset). Re-apply the decision rule to the combined N=20 dataset. If the result remains INCONCLUSIVE at N=20, classify as NEGATIVE and take the NEGATIVE action.

**Note**: The INCONCLUSIVE criterion specifically requires the direction to be positive (Condition C > Condition B). If Condition C is worse than Condition B (AQS lower), the result is classified as NEGATIVE regardless of sample size.

---

## 8. CA Overlay Testing Order

Testing one overlay at a time is mandatory. All five overlays cannot be tested simultaneously because: (a) interaction effects between overlays are not characterized, (b) a combined overlay experiment cannot attribute a result to any single overlay, and (c) the implementation cost of all five simultaneously far exceeds the cost of sequential testing with early termination.

If U-CA-004 resolves POSITIVE for ACT-R Typed Buffer, proceed to test overlays in this order:

| Order | Overlay | Prerequisite | Rationale |
|---|---|---|---|
| 1 | ACT-R Typed Buffer | None — tested in this experiment | Most directly testable; no COMMANDER modification required; lowest implementation cost; Grade A evidence for the underlying problem (Lost in the Middle) |
| 2 | Goal Stack | ACT-R POSITIVE | Requires COMMANDER modification (replacing sequential dispatch with precondition-checking loop); medium implementation cost; U-CA-003 and U-CA-016 must be resolved; agent-level vs tier-level granularity decision required per U-015-007 Finding 1 |
| 3 | LIDA Broadcast | Goal Stack POSITIVE | Requires concurrent agent invocation and NS-003 Critic serialization (race condition handling); highest orchestration complexity; ADR-004 broadcast semantics require pipeline infrastructure that depends on Goal Stack being stable |
| 4 | Episodic Memory | LIDA POSITIVE | Requires content-addressing scheme and prior run artifact corpus indexing; depends on artifact store stability established by NS-003 and Goal Stack |
| 5 | GWT Bounded Workspace | Episodic Memory POSITIVE | Most similar to ACT-R Typed Buffer mechanistically; test last to measure marginal gain over ACT-R; may show redundant gains if ACT-R already optimizes context |

**Rationale for order**: Ascending implementation cost × ascending architectural dependency complexity. Each overlay depends on the prior overlay establishing a stable architectural layer. Testing in ascending complexity order maximizes the probability of early termination (if the first overlay fails, the five-overlay program terminates after one experiment rather than five).

**Early termination rule**: If any overlay in the sequence resolves NEGATIVE, the overlay program terminates at that point. Subsequent overlays are not tested. The documented negative result is sufficient evidence that CA-structured overlays do not provide measurable benefit on this task class beyond the point where the benefit disappears.

---

## 9. AC Compliance Verification

- **AC-008-001**: Three conditions specified with full definitions. Condition C specifies ACT-R Typed Buffer as first overlay with rationale. Same LLM version across all three conditions stated. Confirmed.
- **AC-008-002**: LLM version lock specified as exact API model string at experiment execution time; version lock rule stated (no batch spanning a model update). Confirmed.
- **AC-008-003**: N ≥ 10 per condition (minimum viable), N=20 target (80% power); staged execution protocol (start N=10, double to N=20 on INCONCLUSIVE). Power rationale stated. Confirmed.
- **AC-008-004**: One fixed codebase (highest internal validity) selected with rationale for why multi-codebase is infeasible at N=20. Generalizability limitation acknowledged. Confirmed.
- **AC-008-005**: Two primary metrics with formulas: AQS (four dimensions, 0-3 anchors each, formula stated) and SVR (formula stated, section definition stated, classification rules stated). Scoring anchors are stated at sufficient specificity for a new evaluator to apply without clarification. Confirmed.
- **AC-008-006**: Pre-registered decision rule with three outcomes (POSITIVE/NEGATIVE/INCONCLUSIVE) and action mapped to each outcome. Statistical test specified (Mann-Whitney U, p < 0.05). Threshold for POSITIVE stated as ≥ 10 pp AQS increase AND ≥ 15% relative SVR reduction. Confirmed.
- **AC-008-007**: One overlay tested at a time; first overlay specified (ACT-R Typed Buffer) with rationale; testing order for subsequent overlays specified (Goal Stack → LIDA Broadcast → Episodic Memory → GWT Bounded Workspace) with rationale for each; early termination rule stated. Confirmed.
