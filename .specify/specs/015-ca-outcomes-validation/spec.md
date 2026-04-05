# Spec 015: Cognitive Architecture Outcomes Validation

**Type**: Research Validation
**Spec ID**: 015
**Feature**: ca-outcomes-validation
**Date**: 2026-04-02
**Status**: WHAT-phase — normative requirements
**Depends on**: Spec 014 (cognitive-architecture-llm-framing)

---

## 1. Overview

This spec delivers a claim-by-claim proof status verdict for every outcome asserted in spec 014 (Cognitive Architecture Mechanisms for Echelon). The question it answers is precise: which spec 014 claims are proven by existing Grade A evidence, which are supported by design or analogy but require a prototype to confirm, which are explicitly gated on an experiment that has not been run, and which are speculation with no current empirical grounding. The answer must be accompanied by citations — no verdict is accepted that rests on belief or expectation.

"Proof" in this context has a specific, tiered meaning established in the SCOUT discovery phase. Grade A evidence (peer-reviewed or preprint with measured results on a comparable task) constitutes the highest proof category (P1 — Proven by Paper). Logical derivation from well-established CS or formal methods constitutes P2 (Proven by Design). Theoretical motivation or structural analogy constitutes P3 (Requires Prototype). Claims blocked by a gate experiment not yet run are P4 (Gate-Conditioned). Directionally motivated but numerically ungrounded claims are P5 (Speculation). Every verdict in this spec must be assigned to one of these five categories with a stated evidence source.

This spec exists because spec 014's outcomes, while internally rigorous, span all five proof categories without making those categories explicit to a reader who asks "can you prove this?" The purpose here is to surface that stratification with full transparency: the Generator-Critic mechanism (NS-003-A) and belief revision mechanism (NS-003-B) have Grade A empirical support from NL2GenSym and Kumiho respectively; the five CA overlay claims (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) are explicitly gate-conditioned on the U-CA-004 experiment not yet run; and the 40-70% token reduction range for NOVEL-004 is explicitly labeled SPECULATION. All three of these verdicts must be reproducible by a third party using the evidence sources cited here.

---

## 2. Scope

### In-Scope

- Claim-by-claim proof status assessment covering all 17 rows in the Proof Topology Table from mental-model.md, including both NS-003 components, both NOVEL-004 sub-claims, all five CA overlays, AC-3, all six use case assertions, and the NS-003 novelty claim
- Quick-resolve baseline measurements: token counts per agent call and per pipeline run (U-015-003), scope violation rate from prior spec run artifacts (U-015-004), and inter-artifact contradiction frequency from prior spec run artifacts (U-015-005)
- Experiment designs for claims that require prototypes: NS-003 prototype for Echelon-specific validation (REQ-015-006), NOVEL-004 calibration via retrospective analysis (REQ-015-007), and the U-CA-004 three-condition gate experiment (REQ-015-008)
- Systematic literature search on Semantic Scholar and Google Scholar confirming the Generator-Critic plus AGM belief revision combination has no prior work (U-015-008)
- Resolution of U-015-007 (7-stage vs 42-agent architecture ambiguity) by inspection of the commander.md dispatch protocol

### Out-of-Scope

- The 40-70% token reduction claim for NOVEL-004 (P5 SPECULATION — explicitly beyond current evidence; any upgrade requires N=50+ prototype measurement)
- Production implementation of any mechanism described in spec 014 (NS-003, NOVEL-004, any CA overlay, AC-3)
- Full NS-003 prototype implementation as production-ready code (REQ-015-006 designs the experiment; running it is a post-spec engineering task)
- The U-CA-004 gate experiment execution itself (REQ-015-008 specifies the experiment design; the run is a post-spec task requiring 4-6 weeks)
- Any roadmap for deploying validated mechanisms to production Echelon runs
- Performance benchmarking of the current Echelon pipeline beyond what is needed for baseline measurements

---

## 3. Requirements

### REQ-015-001: Claim Proof Status Table

**Statement**: The implementation must produce a complete proof-status verdict table covering all 17 rows from the Proof Topology Table (mental-model.md Section 4). This requires:
- Each row is assigned to a proof category (P1-P5).
- Each row carries a proof status label (PROVEN / PARTIAL / GATE-CONDITIONED / SPECULATION / NOT PROVEN).
- Each row includes at least one evidence citation in the form of a paper DOI, arxiv ID, or Echelon run artifact path.

**Rationale**: Spec 014 asserted 17 distinct outcome claims across six claim clusters (NS-003-A, NS-003-B, NS-003-C, NOVEL-004, five CA overlays, AC-3, and six use case assertions). No prior artifact has assembled these into a single, cited verdict table. Without this table, the question "can you prove this outcomes?" cannot be answered systematically — individual claims can be disputed in isolation without a shared reference.

**Acceptance Criteria**:
- AC-001-001: The table contains exactly 17 rows, one per claim in mental-model.md Section 4. No rows are omitted, including the two SPECULATION rows.
- AC-001-002: Each row contains: claim identifier, primary evidence source (DOI or arxiv ID or artifact path), evidence grade (A/B/C/D per the five-tier taxonomy in mental-model.md Section 2), proof category (P1-P5), proof status label, and a "What Would Constitute Full Proof" cell that is non-empty for every non-P1 row.
- AC-001-003: The two P5 (SPECULATION) rows — NOVEL-004 40-70% token reduction and the "40-70% token reduction for repeated codebases" use case — carry an explicit label "SPECULATION: no empirical grounding" in the proof status cell. They are not upgraded to "probable" or "supported."
- AC-001-004: All five CA overlay rows carry proof status "GATE-CONDITIONED on U-CA-004" and cite U-015-001 in their blocking reference cell.
- AC-001-005: The NS-003-A and NS-003-B rows carry proof status "PROVEN (component level) / PARTIAL (Echelon-specific)" and cite arxiv:2510.09355 and arxiv:2603.17244 respectively.

**Evidence Gate**: The 17-row table is the primary deliverable for REQ-015-001. It is satisfied when all 17 rows are populated per AC-001-001 through AC-001-005 and reviewed against the SCOUT discovery files (mental-model.md, boundaries.md) for consistency.

**Blocked by**: None (all evidence needed is already assembled in mental-model.md and the SCOUT discovery files).

---

### REQ-015-002: NS-003 Novelty Confirmation

**Statement**: A systematic literature search must be executed on Semantic Scholar and Google Scholar using the specified conjunction query. This requires:
- The search produces a zero-result confirmation or a full citation list if any results are found.
- The search record is accompanied by the search query string, databases queried, date of execution, and result count per database.

**Rationale**: The NS-003 novelty claim — "the combination of execution-grounded Generator-Critic with AGM belief revision applied to multi-agent artifact stores has no prior literature" — is one of the highest-value claims in spec 014. A single contradicting paper falsifies it. Spec 014's literature review covered 13+ sources but was not conducted as a formal systematic search with a reproducible query string. U-015-008 (Open-Literature) explicitly identifies this gap. The novelty claim motivates NS-003 as a research contribution; without a reproducible search record, that motivation is vulnerable.

**Acceptance Criteria**:
- AC-002-001: The search is executed on both Semantic Scholar (semanticscholar.org) and Google Scholar, with the exact query: `("Generator-Critic" OR "generation-validation loop") AND ("belief revision" OR "AGM postulates") AND ("multi-agent" OR "artifact store")`.
- AC-002-002: The search record states: date of execution (to the day), query string as run (verbatim, not paraphrased), result count per database, and disposition of each result (not matching the combination / matching / partial match).
- AC-002-003: If zero results are returned on the specified conjunction query, the novelty claim is stated as "no prior literature found in the reviewed corpus as of [date]" — not as "no prior literature exists." The phrasing acknowledges the search boundary.
- AC-002-004: If any result is returned that matches the combination (execution-grounded Generator-Critic AND AGM belief revision AND multi-agent context), REQ-015-002 is NOT satisfied. Instead, the finding is escalated: the NS-003 novelty claim is revised to "novel extension of [prior work]" with a specific differential analysis.
- AC-002-005: The search record is stored as a standalone artifact (not embedded in the proof status table) so it can be independently re-executed to verify reproducibility.

**Evidence Gate**: The search record artifact with all fields populated per AC-002-001 through AC-002-003 (or the escalation per AC-002-004 if results are found).

**Blocked by**: None.

---

### REQ-015-003: Token Efficiency Baseline

**Statement**: The Echelon pipeline must be instrumented to log total tokens consumed per agent invocation and per full pipeline run. This requires:
- Logging captures prompt tokens plus completion tokens for each agent invocation.
- A baseline measurement dataset is produced from at least 3 completed spec runs on distinct codebases.

**Rationale**: Every token efficiency claim in spec 014 — NOVEL-004's 40-70% reduction, the ACT-R typed buffer's 20%+ per-agent reduction, and the ACON 22-54% compression ceiling comparison — requires a measured baseline to define what "reduction" means. U-015-003 identifies that the current squad-config.yml sets `token_budget_k: 999999` (effectively unlimited), meaning the pipeline has never been constrained to produce a token efficiency measurement. Without a baseline, any efficiency improvement claim is undefined. U-015-002 (CA overhead cost not measured) similarly requires a baseline before net delta can be computed.

**Acceptance Criteria**:
- AC-003-001: Token logging captures: (a) prompt token count per agent invocation, (b) completion token count per agent invocation, (c) agent identifier, (d) spec run ID, (e) codebase identifier (so cross-run comparison is meaningful). All five fields must be present in every logged record.
- AC-003-002: Baseline data is collected from at least 3 completed spec runs. If prior run logs do not contain token counts, at minimum 3 new forward-looking runs must be instrumented.
- AC-003-003: The baseline dataset includes per-agent-type summary statistics: mean, median, and 90th-percentile token count (prompt + completion) for each agent type across the collected runs.
- AC-003-004: The baseline dataset is stored as a machine-readable artifact (structured JSON or CSV) alongside human-readable summary statistics.
- AC-003-005: The baseline measurement explicitly states whether it was obtained from post-hoc estimation of prior runs or from live instrumentation of new runs, as the two methods have different accuracy characteristics.

**Evidence Gate**: A structured baseline artifact containing token counts per agent invocation across at least 3 runs, with per-agent-type summary statistics, and the per-run total pipeline token cost.

**Blocked by**: None (instrumentation is achievable with current Echelon framework; plan.md Access Model confirms post-call token count introspection is available).

---

### REQ-015-004: Scope Violation Rate Baseline

**Statement**: An annotator must review 3-5 prior Echelon spec run artifacts and produce an aggregate scope violation rate per agent type and per run. This requires:
- Each agent output section is classified as in-scope, out-of-scope, or borderline relative to that agent's declared scope.
- Results are aggregated into violation rates per agent type and per run.

**Rationale**: Three spec 014 mechanisms claim to reduce scope violations: the NS-003 Critic consistency check, the AC-3 constraint certificate, and the NOVEL-002 Phi-proxy (out-of-scope). None of these can demonstrate "reduction" without a measured baseline violation rate. U-015-004 identifies that the only current evidence is qualitative: ISS-001 from spec 014 notes that ASSESS reproducing DISCOVER findings is a known violation mode but does not quantify its frequency. Without this baseline, "scope violation reduction" is a directional claim with no quantity attached.

**Acceptance Criteria**:
- AC-004-001: At least 3 and at most 5 prior Echelon spec runs are selected for annotation. Selection criteria: distinct codebases, each run containing at least the DISCOVER and ASSESS agent outputs. Runs 008-014 are the available corpus.
- AC-004-002: Each agent output is annotated per section (not per artifact as a whole): a section is classified as IN-SCOPE if all assertions fall within the agent's declared scope (from its prompt definition), OUT-OF-SCOPE if one or more assertions fall outside that scope, or BORDERLINE if the scope boundary is ambiguous for that assertion.
- AC-004-003: The annotation scheme is applied by at least one annotator. Where a second annotator is available, inter-annotator agreement (Cohen's kappa or percentage agreement) is reported. Where only one annotator is available, this limitation is stated explicitly.
- AC-004-004: The output artifact reports: violation rate per agent type (number of OUT-OF-SCOPE sections / total sections for that agent type), overall violation rate across all annotated runs, and the three most frequent violation patterns by type.
- AC-004-005: BORDERLINE sections are excluded from the violation rate numerator and their count is reported separately.

**Evidence Gate**: An annotation artifact with per-run, per-agent-type violation rates and overall baseline, plus the annotation scheme used.

**Blocked by**: None.

---

### REQ-015-005: Contradiction Rate Baseline

**Statement**: An automated scan of prior Echelon spec run artifacts must measure the frequency of inter-artifact contradictions. This requires:
- Assertions in one agent's output that are logically inconsistent with assertions in another agent's output in the same run are identified.
- The scan produces a contradiction rate per run and per adjacent agent pair.

**Rationale**: NS-003's belief revision mechanism claims to catch contradictions at write-time before they propagate. Without a baseline contradiction rate in current runs, the severity of the problem (and thus the value of the mechanism) cannot be assessed. U-015-005 identifies this gap. A baseline contradiction rate below the noise threshold would weaken the motivation for NS-003-B; a high baseline rate strengthens it. The assessment must be evidence-based, not assumed.

**Acceptance Criteria**:
- AC-005-001: The scan covers all available prior spec runs (minimum: runs 008-014, or whichever subset have both DISCOVER and ASSESS artifacts present). Each run is treated as one observation.
- AC-005-002: The contradiction detection method is stated explicitly and applied consistently: the method must extract factual assertions from structured sections (not from prose paragraphs) using the existing section-header schema of Echelon artifacts, and compare assertions across agents within the same run for logical inconsistency. The comparison method (exact string match, semantic embedding similarity with threshold, or LLM classifier) is stated and its precision/recall characteristics are documented.
- AC-005-003: The output reports: total artifact pairs scanned, total contradictions detected, contradiction rate per run (contradictions / artifact pairs), and contradiction rate per adjacent agent pair (DISCOVER-ASSESS, ASSESS-ARCHITECT, etc.) where data is available.
- AC-005-004: A random sample of at least 5 detected contradictions is manually reviewed to verify the detection method's precision (false positive rate estimated). This review is included in the artifact.
- AC-005-005: The artifact explicitly notes whether the detected rate represents an upper bound (if the detection method has known false positives) or a lower bound (if the method misses soft contradictions in prose).

**Evidence Gate**: A contradiction scan artifact covering at least 3 spec runs with per-run and per-agent-pair rates, the detection method specification, and the 5-sample manual precision check.

**Blocked by**: None.

---

### REQ-015-006: NS-003 Prototype Experiment Design

**Statement**: A complete, self-contained experiment design document must be produced for binary PASS/FAIL validation of NS-003 on Echelon's artifact protocol. This requires:
- The document specifies the test codebase, evaluation set size, metrics with formulas, and acceptance thresholds.
- The document includes a timeline estimate sufficient for a third party to execute the experiment without requesting clarification.

**Rationale**: NS-003 (Self-Correcting Artifact Store) is the primary architecture recommendation from spec 014. The component-level evidence (NL2GenSym: 86%+ Generator-Critic compliance; Kumiho: 93.3% belief revision accuracy) is Grade A. However, both results are qualified: NL2GenSym operates on Soar rule generation (tightly constrained BNF grammar), and Kumiho operates on conversational fact tracking (LoCoMo-Plus). Echelon's artifact protocol uses structured markdown with soft constraints — a less formally constrained output type. The experiment design must establish what measurable outcome at what threshold would constitute validation of NS-003 on Echelon's specific task. REQ-015-006 does not implement NS-003; it specifies the experiment so that implementation can proceed with a clear success criterion.

**Acceptance Criteria**:
- AC-006-001: The experiment design specifies a fixed test codebase (one repository, named, with rationale for selection) to be used for all NS-003 prototype runs, ensuring reproducibility across runs.
- AC-006-002: The design specifies the evaluation set size for NS-003-A (Generator-Critic compliance): minimum N=30 agent invocations on the fixed test codebase, with rationale for this minimum.
- AC-006-003: The design specifies the evaluation set for NS-003-B (Belief Revision contradiction catching): a labeled test set of at least N=20 artificially contradicted artifact pairs, with the contradiction injection method stated (how contradictions are introduced: by rule, by LLM adversarial generation, or by manual injection with stated injection protocol).
- AC-006-004: The design specifies the success metric for NS-003-A with a formula: first-pass compliance rate = (number of agent invocations where the Critic accepts the output on the first attempt) / (total agent invocations). The acceptance threshold is: first-pass compliance rate ≥ 0.70. The design specifies what happens if the compliance rate falls between 0.50 and 0.70 (inconclusive zone requiring redesign of the schema specificity) versus below 0.50 (mechanism requires redesign for this task class).
- AC-006-005: The design specifies the success metric for NS-003-B with a formula: contradiction catch rate = (number of artificially injected contradictions correctly flagged as ConflictSignal) / (total injected contradictions). The acceptance threshold is: contradiction catch rate ≥ 0.80. False positive rate (ConflictSignal fires on non-contradictions) must be reported separately and must be ≤ 0.20.
- AC-006-006: The design includes a stated timeline for execution that covers: schema formalization (producing a machine-parseable schema for each Echelon agent output type), prototype implementation (Generator-Critic loop and belief graph), and measurement run. The timeline is expressed in phases, not in calendar days, since CARTOGRAPHER does not estimate effort.
- AC-006-007: The design is stated at a level of specificity such that a third party who has read spec 014 and spec 015 can execute the experiment without requesting clarification on metrics, thresholds, or evaluation set construction. "Measure quality" is not an acceptable metric formulation; the formula must be stated.

**Evidence Gate**: A self-contained experiment design document covering all six acceptance criteria above, reviewed against the boundaries.md "In-Scope" definitions for NS-003-A and NS-003-B.

**Blocked by**: None (experiment design does not require running the experiment; all parameters are derivable from SCOUT discovery files and spec 014 artifacts).

---

### REQ-015-007: NOVEL-004 Prediction Accuracy Calibration

**Statement**: A retrospective calibration must be performed using available Echelon spec run artifact pairs to estimate NOVEL-004 forward model prediction accuracy. This requires:
- The calibration covers adjacent agent pairs, specifically DISCOVER-to-ASSESS.
- The calibration determines whether estimated prediction accuracy exceeds the break-even threshold for net token reduction.

**Rationale**: NOVEL-004's mechanism (upstream predictions gate downstream LLM calls) is blocked on U-015-006 — the prediction accuracy of the forward model has no calibration data. The break-even threshold (estimated at 40-50% from the Speculative Decoding analogy, SRC-A5) has not been validated for agent-level prediction. Two open assumptions compound this: A-NV-001 (whether predictions can be generated without a full LLM call) and A-NV-002 (whether the 40-50% break-even is correct for this cost structure). A retrospective calibration using existing artifact pairs does not require a prototype — it uses available data to estimate what a prototype would need to achieve. If the retrospective estimate falls well below break-even, it advises against prototype investment. If it approaches or exceeds break-even, it motivates the prototype. The SPECULATION label on the 40-70% token reduction claim must be preserved regardless of calibration outcome until N=50+ prototype measurement exists.

**Acceptance Criteria**:
- AC-007-001: The calibration examines at least N=9 adjacent artifact pairs (DISCOVER output → ASSESS output) from available spec runs (runs 008-014 provide at most 7 such pairs; any additional pairs from other adjacent agent stages may be included to reach N=9). If fewer than 9 pairs are available, the artifact explicitly states N and notes the small-sample limitation.
- AC-007-002: Each artifact pair is evaluated with the following question: "Given only DISCOVER's output as the prediction input, what proportion of ASSESS's top-level assertions could have been predicted as 'present' or 'absent' before ASSESS was invoked?" The evaluation is scored 0-100% per pair. Scoring anchors: 0-20% = fewer than 1 in 5 downstream assertions were predictable from upstream output alone; 40-60% = roughly half of downstream assertions were predictable (borderline break-even zone); 80-100% = most downstream assertions were directly derivable from upstream output. An assertion is considered 'predictable' if the downstream agent's finding is either (a) explicitly stated in the upstream output, or (b) a direct logical consequence of an explicitly stated upstream finding. Borderline cases score 50% for that assertion. The evaluation method (human assessment, LLM-as-evaluator with stated rubric, or structured extraction plus rule matching) is stated and applied consistently.
- AC-007-003: The calibration output reports: mean prediction accuracy across all pairs, median, minimum, maximum, and standard deviation. These statistics form the empirical estimate of what a NOVEL-004 forward model would achieve on historical Echelon runs.
- AC-007-004: The calibration computes the break-even prediction accuracy for NOVEL-004 in this specific context, using the formula: break-even accuracy = (token cost of one forward model prediction call) / (token cost of one full downstream agent invocation). This formula must be instantiated with the baseline token counts from REQ-015-003. If REQ-015-003 is not yet complete, the break-even is stated in symbolic form and marked as pending.
- AC-007-005: The 40-70% token reduction claim carries the label "SPECULATION" in the calibration artifact, regardless of whether the empirical prediction accuracy estimate is above or below break-even. Upgrading this label to "probable" requires N=50+ prototype measurement runs, not a retrospective calibration alone.
- AC-007-006: The calibration artifact includes a go/no-go recommendation for proceeding to a NOVEL-004 prototype: GO if mean prediction accuracy ≥ break-even AND standard deviation < 30%; NO-GO if mean prediction accuracy < break-even; INCONCLUSIVE if mean is within 10 percentage points of break-even or standard deviation ≥ 30%.

**Evidence Gate**: A calibration artifact with per-pair prediction accuracy scores, aggregate statistics, break-even computation (or symbolic form with pending notation), the SPECULATION label on the 40-70% range, and a go/no-go recommendation per AC-007-006.

**Blocked by**: Soft: REQ-015-003 (token baseline) for break-even formula instantiation; all other aspects are unblocked.

---

### REQ-015-008: U-CA-004 Gate Experiment Specification

**Statement**: A complete, self-contained specification of the U-CA-004 three-condition gate experiment must be produced. This requires:
- The specification covers evaluation rubric with metric formulas, sample size with statistical power rationale, LLM version specification, task selection criteria, and decision rule.
- The level of specificity allows a third party to execute the experiment without requesting clarification.

**Rationale**: All five CA overlay claims (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) are in proof category P4 (Gate-Conditioned) and are explicitly blocked by U-CA-004. The MAP paper (Nature Communications 2025, SRC-A3) provides the closest Grade A evidence for CA-structured pipelines outperforming CoT-equivalent prompting, but its task class (graph traversal, Tower of Hanoi, PlanBench) differs from Echelon's multi-stage codebase analysis pipeline, and it benchmarks GPT-4 (2023) rather than Claude Opus 4.x. The gate experiment must close this gap: same task class (Echelon codebase analysis), same LLM, three conditions, with a predefined decision rule so the outcome is unambiguous. REQ-015-008 does not run the experiment; it specifies it so that the squad can make an explicit resource allocation decision before committing to a 4-6 week experiment.

**Acceptance Criteria**:
- AC-008-001: The experiment specifies exactly three conditions: (A) Naive Baseline — agents invoked with minimal prompting and no structured CA scaffolding; (B) Expert-Prompt Baseline — agents invoked with the current best-available engineered prompt (the existing Echelon agent prompts, with no CA additions); (C) CA-Structured Overlay — agents invoked with one CA overlay active (the overlay to be specified, with rationale for which overlay is tested first). The same LLM version is used across all three conditions in all runs.
- AC-008-002: The LLM version is stated as a specific version identifier (not "Claude Opus 4.x" as a class — the exact version string that was available at experiment design time, or the specification that the same model checkpoint is used across all three conditions within a single run batch). Version lock is required to prevent confound from model updates.
- AC-008-003: The sample size is N ≥ 10 runs per condition (minimum 30 total runs). The rationale states: with N=10 per condition and an expected effect size of 0.5 standard deviations (moderate), the experiment has approximately 50% power at alpha=0.05; N=20 per condition achieves approximately 80% power. The experiment design states whether N=10 (minimum viable) or N=20 (80% power) is the target.
- AC-008-004: The task selection criterion specifies how the test codebase is selected: (a) one fixed codebase used for all conditions and all runs (highest internal validity, lowest generalizability), or (b) a stratified sample of 5 codebases with N=6 runs per codebase across conditions (higher generalizability, higher cost). The design states which option is selected and why.
- AC-008-005: The evaluation rubric specifies at least two primary metrics with formulas. Acceptable primary metrics include: (i) Artifact Quality Score = (sum of rubric dimension scores across [coherence, completeness, scope compliance, internal consistency]) / (number of dimensions × maximum score per dimension), where each rubric dimension is defined with 0-3 scoring anchors stated explicitly; (ii) Scope Violation Rate per REQ-015-004 definition; (iii) Contradiction Rate per REQ-015-005 definition. "Quality" without a formula is not an acceptable metric. The rubric is stated at a level of specificity that allows a human evaluator who has not seen the experiment design before to score artifacts without asking for clarification.
- AC-008-006: The decision rule is stated in advance (pre-registration style) and covers three outcomes: (i) POSITIVE — CA-Structured (Condition C) Artifact Quality Score exceeds Expert-Prompt Baseline (Condition B) by ≥ 10 percentage points AND scope violation rate or contradiction rate decreases by ≥ 15%, with p < 0.05 by the stated statistical test; (ii) NEGATIVE — Condition C does not exceed Condition B on primary metrics at the stated threshold; (iii) INCONCLUSIVE — the effect is present but below the threshold. The decision rule maps each outcome to an action: POSITIVE unlocks CA overlay implementation; NEGATIVE terminates the overlay program and triggers an expert-prompt-only improvement plan; INCONCLUSIVE triggers a follow-up experiment with doubled N.
- AC-008-007: The experiment specification explicitly states that it applies to one CA overlay at a time. All five overlays cannot be tested simultaneously without a design that accounts for interaction effects. The specification states the recommended first overlay to test (with rationale) and the order for subsequent overlays contingent on a POSITIVE first result.

**Evidence Gate**: A self-contained gate experiment specification document covering all seven acceptance criteria, including evaluation rubric with stated scoring anchors, sample size with power rationale, pre-registered decision rule, and CA overlay testing order.

**Blocked by**: None for the specification itself. Execution is blocked by U-015-001 (4-6 week timeline for experiment run). The specification of the experiment is not blocked by anything and should proceed immediately to enable the resource allocation decision.

---

## 4. Spec-Level Acceptance Criteria

- **AC-SPEC-001**: Every proof verdict in REQ-015-001 cites a specific evidence source (paper DOI, arxiv ID, or Echelon run artifact path). No verdict cell contains the words "believed," "expected," or "likely" without a citation that supports that degree of confidence. Citations must be traceable — an arxiv ID must correspond to a real preprint, not a placeholder.

- **AC-SPEC-002**: All five CA overlay claims remain explicitly gate-conditioned on U-CA-004 (REQ-015-008) throughout every artifact produced under this spec. No CA overlay is stated as "proven," "supported," or "ready for implementation" before U-CA-004 resolves positively. The gate condition must appear in each overlay's proof status row in the verdict table (REQ-015-001), in the boundaries established for each overlay claim, and in any summary or recommendation section.

- **AC-SPEC-003**: The 40-70% token reduction claim for NOVEL-004 is explicitly labeled "SPECULATION: no empirical grounding" in the REQ-015-001 proof status table and in the REQ-015-007 calibration artifact. The label "SPECULATION" is not removed or softened to "probable," "likely," or "supported" based on the retrospective calibration result alone. Upgrading the label requires a minimum of N=50 prototype measurement runs with instrumented token counters.

- **AC-SPEC-004**: The NS-003 novelty claim verdict in REQ-015-002 is accompanied by a reproducible search record containing: the exact query string as executed, the databases queried, the date of execution, and the result count per database. The reproducibility requirement means the search record must be complete enough that a third party could re-execute the identical search within 30 days and verify the zero-result (or non-zero-result) finding.

- **AC-SPEC-005**: Experiment designs in REQ-015-006 and REQ-015-008 are stated at a level of specificity such that a third party who has read spec 014 and spec 015 can execute the experiments without requesting clarification on any of the following: metric formula, acceptance threshold, evaluation set construction method, test codebase selection criterion, or decision rule. "Measure quality," "assess coherence," and "evaluate completeness" are not acceptable formulations unless accompanied by a scoring rubric with stated anchors.

---

## 5. Non-Requirements (Explicitly Out of Scope)

- This spec does not require implementation of NS-003, NOVEL-004, AC-3, or any CA overlay mechanism. Experiment designs in REQ-015-006 and REQ-015-008 are specifications, not implementations.
- This spec does not require running the U-CA-004 gate experiment (REQ-015-008 produces the design; the execution decision is made post-spec by the squad).
- This spec does not produce a production roadmap, a deployment plan, a migration plan, or an architectural decision to adopt any mechanism.
- This spec does not upgrade any P5 SPECULATION claim to a higher proof category based on retrospective analysis alone.
- This spec does not resolve ISS-001 (7-stage vs 42-agent architecture discrepancy) beyond what is needed to correctly size the U-CA-004 experiment scope (ACT-R buffer token budget per tier vs per agent call). Resolving ISS-001 in full is a separate engineering task.
- This spec does not assess the commercial, legal, or operational risks of adopting any mechanism.

---

## 6. Constitution Compliance

- **R-I (Accuracy over Completeness)**: This spec produces a validation assessment, not a migration plan or a deployment recommendation. Every verdict is bounded by its evidence category. Partial verdicts are explicitly partial; speculation is explicitly speculation. The spec does not inflate confidence to achieve apparent completeness.
- **R-II (Gate Discipline)**: All five CA overlay claims are explicitly conditioned on U-CA-004 throughout this spec and in all artifacts it produces. No overlay is stated as ready for implementation before the gate resolves. This matches the gating discipline established in spec 014 and carried forward by the SCOUT discovery phase.
- **R-III (Separation of Concerns)**: The Q1/Q2 tracking established in spec 013 is a separate workstream. This spec is scoped exclusively to validating the proof status of spec 014's cognitive architecture mechanism claims. It does not assess spec 013 tracking targets, broader Echelon roadmap items, or any non-CA-mechanism outcomes.
- **R-V (Evidence Hierarchy)**: The five-category evidence grading system (Grade A through Grade D, mapped to proof categories P1 through P5) is applied strictly throughout this spec. Grade A peer-reviewed results (NL2GenSym, Kumiho, MAP, "Lost in the Middle") constitute the highest proof category. Theoretical neuroscience (Rao & Ballard, Friston) and classic CS (Mackworth, Bessiere) constitute Grade C — theoretical motivation but not empirical validation for LLM agent applications. The distinction between "proven by paper" and "proven by design" (P1 vs P2) is maintained throughout.

---

## 7. Dependencies and Sequencing

REQ-015-001 through REQ-015-002 have no external dependencies and can be executed immediately using assembled SCOUT evidence.

REQ-015-003 (token baseline) and REQ-015-004 (scope violation baseline) and REQ-015-005 (contradiction rate baseline) are independent of each other and can be executed in parallel. REQ-015-004 and REQ-015-005 can use the same artifact corpus (prior spec runs 008-014). REQ-015-003 may require forward-looking instrumentation if prior run logs lack token counts.

REQ-015-007 (NOVEL-004 calibration) depends on REQ-015-003 for break-even formula instantiation. If REQ-015-003 is delayed, REQ-015-007 proceeds with the symbolic form of the break-even formula and marks it as pending.

REQ-015-006 (NS-003 experiment design) and REQ-015-008 (U-CA-004 experiment design) are independent of all baseline measurements and can be executed in parallel with REQ-015-003 through REQ-015-005.

One soft dependency exists: REQ-015-007's break-even formula instantiation is soft-blocked by REQ-015-003; if REQ-015-003 is not yet complete, REQ-015-007 proceeds with the symbolic form of the break-even formula. All other requirements are independent.
