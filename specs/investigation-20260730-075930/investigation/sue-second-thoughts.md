# Investigation: SUE Second Thoughts

## Metadata

- **Topic:** Independent reappraisal of Socratic Understanding Engine (SUE) claims
- **Spec context:** `docs/socratic-understanding/` and `specs/030-build-sue-challenge-script/`
- **Investigator:** speckit-echelon-investigator (INVESTIGATOR)
- **Date:** 2026-07-30
- **Repository inspected at:** `01e5074ea28ed04875f93f883e1b25cb6fad20ff`
- **Source question:** After independently checking current primary literature, standards, patents, the two supplied research PDFs, and Echelon’s measured SRP evidence, which SUE claims remain supported, which should be weakened or rejected, and what is the smallest defensible next research step?
- **Scope boundary:** Technical research review only. Patent coverage is non-exhaustive and non-legal. No patentability, infringement, novelty, or freedom-to-operate conclusion is made.

## Executive finding

SUE’s strongest surviving idea is not that a multi-agent score reveals truth. It is that independently reconstructed, source-grounded interpretations can be compared at the level of behavioral consequences while preserving provenance and disagreement. Primary requirements research supports the existence of consequential interpretation variance, and also warns that many textual ambiguities are harmless; this combination supports SUE’s decision-relative objective.

The present evidence does **not** validate SUE’s detector, scalar semantic closure, numeric thresholds, “real fracture” labels, question-utility formula, or CI gating. Echelon’s SRP evidence demonstrates executable feasibility and one encouraging mutation localization, but A1 failed on every reported run. The larger checked-in sidecar is stale relative to its spec, lacks an input digest and complete pass identity, and derives a supposed “noise floor” from only two values per requirement. These defects make controller-owned, content-addressed evidence strongly supported as governance, while making current efficacy claims weaker.

The smallest defensible next step is a frozen, no-new-model-call retrospective extraction-validity audit against an exact historical spec snapshot. If complete raw pass outputs cannot be reconstructed, stop and record an evidence-lifecycle failure. Do not proceed to mutation benchmarking, semantic-closure fitting, or workflow gating until graph extraction and grounding have independent human validity evidence.

## 1. Question

- **Unknown:** Which of SUE’s nine mechanisms are supported as (a) a design invariant, (b) a testable research hypothesis, or (c) an empirically validated capability?
- **Decision depending on answer:** Whether ARCHITECT/humans should preserve, weaken, reject, or reopen SUE claims and what evidence program should run next.
- **Good-enough evidence:** Primary peer-reviewed research or standards for external claims; reproducible repository measurements for Echelon-specific claims; official patent publications only to establish that a disclosure exists; transparent separation of evidence from inference.
- **Cost of being wrong:** A false positive could turn correlated model error into an authoritative “specification defect,” spend model/human budget, or gate delivery incorrectly. A false negative could discard a useful method for surfacing materially different interpretations. An unsupported novelty claim creates separate legal and strategic risk.

### Claim-status vocabulary

- **Supported:** Evidence justifies retaining the mechanism for its stated, limited purpose.
- **Qualified:** The principle survives, but the current interpretation or implementation claim must be narrowed.
- **Research hypothesis only:** Plausible and falsifiable, but effectiveness is not established.
- **Rejected for present use:** Current evidence is insufficient or directly conflicting; it must not be used as a score, fact, or gate.

## 2. Research

The complete source register and grades are in [`evidence-grades.md`](../evidence-grades.md). The highest-impact sources are summarized here.

| Source | Type | Date checked | Grade | Relevant finding |
|--------|------|--------------|-------|------------------|
| ISO/IEC/IEEE 29148:2018 | International standard | 2026-07-30 | A | Supports disciplined, traceable requirements work; does not validate SUE mechanisms or thresholds. |
| Femmer et al., requirements smells | Peer-reviewed empirical study | 2026-07-30 | A | Established automated requirements-quality baseline; reported precision/recall variation shows false-positive risk. |
| ClarifyGPT; AskBench; CLARITY | Peer-reviewed primary research | 2026-07-30 | A | Ambiguity detection, localization, and clarification-question policies have close prior art and benchmarkable outcomes. |
| ALICE; EARS | Peer-reviewed primary research | 2026-07-30 | A | Controlled/formal representations and typed constraints are essential baselines. |
| Ribeiro & Berry | Peer-reviewed empirical study | 2026-07-30 | A | Not every persistent ambiguity causes costly harm; supports decision-relative materiality and rejects “eliminate all ambiguity.” |
| Fischbach et al. | Peer-reviewed empirical study | 2026-07-30 | A | Practitioners assign different logical meanings to the same conditional requirements. |
| Semantic entropy; FActScore; Graph of Thoughts | Peer-reviewed primary research | 2026-07-30 | A | Semantic equivalence, atomic source grounding, and graph representations are established components, but not validation of SUE’s combination. |
| Multiagent Debate; Free-MAD | Peer-reviewed primary research | 2026-07-30 | A | Interaction can help on some tasks, but conformity/error propagation make pre-interaction independence worth preserving. |
| Six patent publications/grants | Published patent documents | 2026-07-30 | B | Disclose overlapping elements: graph-based disambiguation, Socratic context-driven questioning, AI requirements analysis, guided artifact completion, graph/provenance validation, and implementation-relative implicit-assumption conflicts with structured clarification. |
| SRP smoke run | Echelon single-spec measurement | 2026-07-30 | D | Feasibility shown; clean agreement 0.346, one mutation localized, one flawed mutation detected. |
| SRP two-pass sidecar and implementation | Echelon measured artifact + reproducible code inspection | 2026-07-30 | D/B | A1 still fails; artifact is stale and incomplete; two-pass score wobble is overstated as a noise floor/real fracture set. |
| Two supplied ChatGPT Deep Research PDFs | Unverified model-generated synthesis | 2026-07-30 | E | Useful leads only; semantic-closure, persona, novelty, patentability, and deployment claims lack independent validation. |

### Active disconfirmation and closer prior art

The search intentionally looked for work that would make SUE less distinctive or less useful:

1. Deterministic requirements smells, EARS, and ALICE are credible non-agent/formal baselines. A SUE evaluation that excludes them would overstate incremental value.
2. ClarifyGPT, AskBench, and CLARITY already address ambiguity detection, localization, and clarification policies tied to downstream tasks.
3. FActScore and semantic entropy already use atomic grounding and meaning-level equivalence, respectively.
4. Graph of Thoughts and knowledge-graph patent disclosures make graph representation/provenance broadly established.
5. Ribeiro and Berry’s case evidence is an important negative result: finding more ambiguity is not necessarily beneficial.
6. Free-MAD reports conformity and error propagation in consensus-oriented debate, weakening any claim that discussion or majority improves truth.
7. CN121918799A is especially close to implementation-relative uncertainty:
   it derives preconditions from candidate implementations, classifies implicit
   assumptions, detects mutually exclusive assumptions, quantifies uncertainty,
   and generates structured clarification items.

No searched source was found that validates SUE’s exact nine-part combination on software requirements. Absence from this time-boxed search is not evidence of novelty.

## 3. Evaluate

### 3.1 Nine mechanisms, assessed separately

| # | Mechanism | Status | What remains supported | What must be weakened or rejected | Confidence and evidence |
|---|-----------|--------|------------------------|-----------------------------------|-------------------------|
| 1 | **Cold reconstruction** | **Supported, qualified** | Isolation is a sound contamination control. Preserving pre-aggregation readings is especially justified where debate can induce conformity. | “Independent agents” must not imply statistically independent evidence or truth: same-provider runs share training, prompts, schema, and failure modes. | 0.90; E1, E2, E22, E23 |
| 2 | **Typed, grounded interpretation graphs** | **Supported as representation; unvalidated as detector** | Atomic, typed, source-linked records are auditable and enable behavioral comparison and provenance checks. | Graph agreement cannot be interpreted until extraction precision/recall and grounding accuracy are measured against independent human annotations. Graphs/typed relations are not novel in the broad sense. | 0.92; E15, E18–E21, E25, E27, E29 |
| 3 | **Noise-relative comparison** | **Principle supported; current estimator rejected** | Repeatability and variance should be measured before treating differences as signal. | The current two-pass mean population SD is not an “extraction-noise floor,” a lower bound, or a variance decomposition. The claim “below this is noise” is unsupported. | 0.97; E5, E7, E8 |
| 4 | **Decision-relative behavioral compatibility** | **Supported research objective** | Requirements can induce different logical behavior, while other ambiguities may have no practical cost. Comparing effects on a named decision is better grounded than prose similarity or ambiguity count. | No current classifier or threshold has been validated. Decision contexts and behavioral equivalence rules remain hypotheses. | 0.91; E14, E16–E18 |
| 5 | **Semantic-closure score** | **Rejected for present scoring/gating** | Its components may remain separate diagnostic signals. | The supplied weighted formula, weights, monotonicity, construct validity, calibration, and relation to outcomes are unsupported. Convergence can reflect shared omission/error. No CI gate is defensible. | 0.98; E3–E5, E17, E30 |
| 6 | **Fracture localization** | **Research hypothesis only** | The smoke run’s M1 rank-1 result is encouraging and mutation testing is a legitimate validation strategy. | Two-pass “stable-low” is not a “real fracture.” M2 was not a clean single-operator mutation. Localization must be validated by realistic, blinded, human-approved mutants and clean controls. | 0.94; E4, E5, E8, E24 |
| 7 | **Question utility** | **Research hypothesis only** | Targeted clarification is established and can be tied to downstream improvement. | The proposed EIG/coverage/answerability/traceability/cost scalar and weights are unsupported. Questions need comparison against established clarification benchmarks and budget-matched baselines. | 0.93; E12–E14, E25, E28, E30 |
| 8 | **Bounded dialectic and aporia** | **Qualified, optional audit only** | Bounded post-aggregation critique may expose reasons for disagreement; aporia is a valid non-resolution state if its cause is preserved. | Philosopher personas, consensus, majority vote, and convergence-as-truth are rejected. There is no requirements-domain evidence that dialogue adds value beyond cold readings. | 0.88; E2, E22, E23, E31 |
| 9 | **Controller-owned evidence** | **Strongly supported governance invariant** | Run identity, provenance, immutable inputs, certified measurements, and invalidation on input change are necessary for auditable evidence. The repository’s stale sidecar is a direct demonstration. | Governance does not confer semantic correctness and should not be presented as research novelty. | 0.99; E6–E10, E29 |

### 3.2 Evidence-layer separation

#### We measured in this repository

- SRP v0 clean agreement was **0.346** on one clean spec with K=3.
- Mutation M1 agreement was **0.276** and the modified requirement ranked **#1**.
- Mutation M2 agreement was **0.407** and all **3/3** readers reported a conflict, but its construction was confounded.
- The larger checked-in self-run reports last-pass SR **0.4494248660**, two-pass mean **0.4225108300**, population SD **0.0269140360**, and **45** stable-low units.
- The sidecar was committed at `87b286b3`; the spec was changed afterward at `607e8ef6`.
- The stale dossier still reports a 4-vs-5 header contradiction, while current AC-002 states exactly five facts.
- The sidecar has no input digest, prompt/schema/tool version, decision context, or complete raw identity for both passes.

These observations establish execution and evidence-lifecycle failure. They do not establish ambiguity-detection validity.

#### External evidence establishes

- Readers can assign different logical meanings to requirements.
- Some ambiguities do not cause costly downstream harm.
- Formal/controlled requirements analysis, deterministic smells, atomic grounding, graph representations, semantic equivalence grouping, and targeted clarification are established.
- Multi-agent interaction can both help selected tasks and induce conformity.
- Multiple patent publications disclose overlapping individual mechanisms.

External sources do not establish SUE’s exact combined effectiveness.

#### Investigator inference

- Decision-relative behavioral comparison is the most defensible distinctive research direction because it reconciles the existence of interpretation variance with the weak utility of ambiguity counts.
- Current low agreement may reflect extraction/alignment instability at least as plausibly as specification ambiguity.
- Content-addressed evidence would have prevented the stale dossier from presenting a resolved contradiction as current.

#### Unsupported novelty or efficacy claims

- “Semantic closure” is a valid scalar construct.
- Stable-low after two passes is a real specification fracture.
- Current SRP output is trustworthy because scores repeat.
- The .80/.70 A1 cutoffs, 4/5 operator rule, P@3/recall cutoffs, 10% FPR, ΔAUC .05, or Cohen’s d .8 are literature-derived domain thresholds.
- A bounded dialectic improves requirements understanding.
- The nine-part combination is novel, patentable, non-infringing, or free to operate.

### 3.3 Statistical and experimental audit

| Item | Finding | Required correction |
|------|---------|---------------------|
| **A1 mean ≥0.80, minimum ≥0.70** | Neither threshold was tied to a domain validation or decision cost. More importantly, high agreement can result from common omission or correlated model error. Current measured values are far below both. | Keep as provisional legacy secondary targets. Add a primary construct-validity gate: adjudicated edge precision/recall/F1, provenance accuracy, and repeatability with intervals. Separate validity from reliability. |
| **A2 detect ≥4 of 5 operators** | Coarse and arbitrary; hides easy/hard operators, equivalent mutants, and site leakage. M2 already demonstrates mutation-design confounding. | Report each operator separately with uncertainty, human approval, independent clean sites, and no pooled 4/5 success claim. |
| **A3 P@3 ≥0.60 and recall ≥0.70** | Depends on number of requirements, defect prevalence, ties, and mutation placement; current M1 is n=1. | Compare against chance and budget-matched baselines. Report MRR, rank percentile, top-k, and cluster-bootstrap intervals by source spec. |
| **A4 FPR ≤10%** | A 10–15 clean-spec sample cannot support the cap at 95% confidence even with zero false positives. Exact one-sided zero-event upper bound is `1 - 0.05^(1/n)`: **18.1% at n=15**. **n≥29** is required to get below 10% with zero events. | Use ≥29 independent clean specs for that claim, more if any false positive occurs or specs are clustered. Otherwise report an interval and make no cap claim. |
| **A5 ΔAUC ≥0.05** | The increment is not tied to power or decision utility. Mutants from the same source spec are correlated; random mutant splits leak style/content. Mutation classification is not historical-rework prediction. | Split/group by source spec; use held-out or leave-one-spec-out evaluation, cluster bootstrap/permutation, confidence interval for ΔAUC, PR-AUC/calibration/decision curves, and a separate historical-outcome study. |
| **Cohen’s d ≥0.8** | A conventional heuristic, not a SUE-specific scientific boundary; ordinary independent-sample d is wrong for paired/clustered designs. | Use paired standardized change or robust paired differences with intervals/permutation. Predefine a practical effect in decision units. |
| **“Nonzero significant coefficient”** | Tiny, confounded retrospective samples cannot support a stable coefficient or causal claim. | Pre-register outcomes/covariates, account for project clustering, report uncertainty, and avoid causal wording. |
| **Multiple comparisons** | Operators, channels, framings, baselines, thresholds, and outcomes create an endpoint family beyond a single test. | Pre-register primary/secondary endpoints and hierarchical families. Holm correction is acceptable within a declared family, but cannot repair post-hoc endpoint selection. |
| **Threshold selection** | Tuning on the evaluation corpus creates optimism. | Lock thresholds before the held-out test; use nested train/validation/test or leave-one-spec-out selection. |
| **A6 ≤15 minutes** | This is a product budget/SLO, not epistemic evidence. | Keep and report separately with calls, tokens, latency, failures, and human minutes. |

### 3.4 Required baselines and ablations

All model-based comparisons should use equal call/token budgets and locked prompts:

- deterministic 34-metric/requirements-smell analysis;
- EARS/ALICE-style controlled or formal analysis where applicable;
- direct single-reader extraction;
- repeated self-consistency/majority without roles;
- self-reflection;
- ClarifyGPT/AskBench-style clarification;
- multi-agent debate and a consensus-free variant;
- LLM-as-judge;
- raw-text/embedding similarity;
- untyped graph;
- SUE ablations without typing, provenance, decision context, glossary normalization, or noise calibration.

The comparison unit and resampling unit must be the **source specification**, not individual mutants derived from it.

## 4. Hypothesize

| ID | Hypothesis | Falsifier | Linked question |
|----|------------|-----------|-----------------|
| H1 | **If** cold runs are preserved before any interaction, **then** measured initial interpretation diversity will be less contaminated by conformity **because** readers cannot copy or defer to peers. | An equal-budget study finds no change in pre/post error correlation or cold runs perform worse on independently adjudicated validity without preserving unique correct readings. | Mechanism 1 |
| H2 | **If** typed, source-grounded graphs are valid intermediate records, **then** independent annotators and saved model runs will achieve useful edge/provenance precision and recall **because** the schema captures reconstructible relations. | Human-adjudicated edge/provenance scores are poor, unstable, or dominated by schema disagreement. | Mechanism 2 |
| H3 | **If** repeated disagreement reflects specification ambiguity rather than extraction bias, **then** stable-low units will be enriched for independently adjudicated behavioral incompatibility after controlling for extraction/alignment error. | Stable-low units are no more predictive than baselines or mainly map to extraction/vocabulary errors. | Mechanisms 3 and 6 |
| H4 | **If** decision-relative comparison is superior to ambiguity counts, **then** it will better predict adjudicated decision reversal, conflicting tests, or rework **because** it ignores wording differences without behavioral consequence. | Ambiguity counts or simpler baselines match/exceed performance and decision utility on held-out source specs. | Mechanism 4 |
| H5 | **If** a semantic-closure scalar is coherent, **then** prespecified component weights will be calibrated, monotonic, and predictive on held-out projects **because** the components measure one actionable latent construct. | Components have conflicting/non-monotonic relationships, weights fail transfer, or a vector performs better. | Mechanism 5 |
| H6 | **If** ranked clarification questions are useful, **then** answering top-ranked questions will reduce adjudicated decision uncertainty more per unit cost than baselines **because** the ranker targets material information gaps. | No downstream gain, worse gain/cost, low answerability, or redundant questions. | Mechanism 7 |
| H7 | **If** bounded dialectic adds value after cold aggregation, **then** it will find additional valid defects without erasing correct minority evidence under equal budget **because** structured critique exposes relation conflicts. | It adds only cost/conformity, degrades calibration, or loses correct minority interpretations. | Mechanism 8 |
| H8 | **If** controller-owned content-addressed evidence is necessary, **then** digest/version checks will prevent stale findings from being presented as current **because** changed inputs invalidate the evidence binding. | Stale/current attribution remains ambiguous despite complete manifests, or the mechanism cannot detect the demonstrated sidecar/spec mismatch. | Mechanism 9 |

## 5. Experiment

No new experiment was run.

- Live LLM experiments were explicitly out of scope.
- Producing an “independent human gold graph” by the same investigator who designed this review would not satisfy the required independent annotation.
- The checked-in two-pass artifact lacks enough identity and raw-pass provenance to support a valid retrospective accuracy calculation during this investigation.
- Repository inspection and exact-binomial arithmetic are audits/analyses of existing evidence, not new SUE efficacy experiments; therefore no `experiment-results.md` is created.

### Proposed smallest experiment (requires separate authorization)

| ID | Method | Success criteria declared before execution | Failure/stop criteria | Artifact |
|----|--------|--------------------------------------------|-----------------------|----------|
| P1 | Freeze one historical spec by SHA-256 and commit. Recover existing raw outputs only. Two independent annotators label typed edges and source spans for 20–30 stratified requirements, then adjudicate while retaining disagreement. Score each saved run. | Complete manifest; ≥95% parsable records; report edge precision/recall/F1, provenance accuracy, annotator agreement, pass repeatability, and cause taxonomy with confidence intervals. No efficacy threshold should be invented after seeing results. | Stop if exact input, raw outputs, pass/model/prompt/schema identities cannot be reconstructed. Stop expansion if extraction/provenance validity is inadequate or errors cannot be separated from ambiguity. | Content-addressed audit package; no model calls. |

Only after P1 succeeds should a separately approved, bounded live A1 pilot use one to three frozen clean specs, at least three passes, locked prompts, and human gold. Mutation evaluation remains out of scope until extraction validity is established.

## 6. Measure

### Existing quantitative results

| Metric | Value | Sample size | Environment | Interpretation |
|--------|-------|-------------|-------------|----------------|
| SRP clean agreement | 0.346 | 1 spec, K=3 | v0 smoke | A1 failure; no external validity. |
| M1 agreement | 0.276 | 1 mutation, K=3 | v0 smoke | Modified requirement ranked #1; encouraging anecdote. |
| M2 agreement | 0.407 | 1 mutation, K=3 | v0 smoke | Conflict found by 3/3, but mutation/control confounded. |
| Self-run last-pass SR | 0.4494248660 | 1 spec, 3 saved readers | checked-in sidecar | A1 failure; saved artifact represents only last pass readers. |
| Two-pass SR mean | 0.4225108300 | 1 spec, 2 passes | checked-in stability summary | Too few independent units for a reliable distribution. |
| Two-pass population SD | 0.0269140360 | 2 pass-level scores | same | Descriptive only. |
| Reported extraction “floor” | 0.0943085849 | mean of per-unit SDs, 2 values/unit | same | Observed wobble, not a floor or decomposition. |
| Stable-low units | 45 | 1 spec, 2 passes | same | Candidate repeated disagreement, not validated fractures. |
| Evidence-line overlap | 0.9294871795 | 1 spec | same | Line co-location, not semantic correctness. |
| A4 zero-FP 95% upper bound at n=15 | 18.1% | 15 independent clean specs assumed | exact binomial | Cannot claim ≤10%. |
| Minimum zero-FP n for upper bound <10% | 29 | independent clean specs assumed | exact binomial | Minimum only; clustering/FPs increase n. |

### Provenance/staleness measurements

| Item | Observed value |
|------|----------------|
| Sidecar-producing commit | `87b286b38d6efd7365f7ebf31a41944489c30a57` |
| Later spec-fix commit | `607e8ef615fbc7b6517797bfc114eda46179e216` |
| Current spec SHA-256 | `c28365fd2710d37e8afaba4af87886b4eaa5b2177d01988890f8e295c90a719b` |
| Current sidecar SHA-256 | `cd544710a979d7eb97aab4edfebb6a56d389deca43d0210da42441dee1911772` |
| Sidecar input digest | absent |
| Saved reader records | 3 |
| Pass identity in reader records | absent |
| Demonstrated stale finding | sidecar/dossier says AC-002 has four facts; current spec has five |

## 7. Synthesize

### What we know

1. The SRP executes and can produce localized candidates.
2. Reported A1 agreement is far below the proposed gate.
3. The present stability/noise interpretation is not statistically justified.
4. At least one checked-in high-confidence diagnosis became stale after the spec changed and was not invalidated.
5. External research establishes both genuine interpretation variance and the non-materiality of some ambiguities.
6. Each broad component has substantial prior art; no end-to-end SUE validity study was found.
7. The supplied PDFs are model-generated secondary syntheses and conflict in places with current authoritative decisions.

### What we believe, with qualifications

- Decision-relative behavioral compatibility is a worthwhile research objective (0.91), not yet an achieved capability.
- Cold isolation, structured grounding, and controller ownership are good safeguards (0.90–0.99), but none makes interpretations true.
- Fracture localization and question utility deserve controlled experiments (0.93–0.94), but current labels/formulas should be weakened.
- Scalar semantic closure and CI gating should be rejected now (0.98) and reopened only after channel-level validity and outcome calibration.

### Conflicts resolved

- **PDF implementation enthusiasm vs authoritative caution:** higher-grade repository authority and failed measurements win. No deployment gate.
- **Repeated low agreement as “real fracture” vs no gold standard:** reproducible code inspection shows only repeated score behavior; label is downgraded to candidate.
- **Find-all-ambiguity objective vs decision-relative value:** peer-reviewed empirical evidence that persistent ambiguity may be harmless supports the current decision-relative approach.
- **Philosopher personas vs structured operators:** current Decisions outrank a Grade-E historical PDF; personas remain historical labels only.
- **Novelty narrative vs closer prior art:** official publications and primary literature establish overlapping components; no novelty inference is permitted.

### Remaining uncertainty

The largest unresolved issue is construct validity: whether the graph edges and grounded spans are correct. Without that, neither higher agreement nor lower agreement has a reliable interpretation. Full gaps and resolution paths are in [`knowledge-gaps.md`](../knowledge-gaps.md).

## 8. Recommend

The detailed confidence-scored recommendations are in [`recommendations.md`](../recommendations.md). In priority order:

1. **Do not promote SUE or semantic closure to a workflow gate.**
2. **Downgrade current “real fracture”/“trustworthy” wording to candidate observations and mark checked-in results stale/historical.**
3. **Preserve cold runs, typed grounding, decision relativity, and controller-owned evidence as qualified invariants.**
4. **Add construct validity before A1 and relabel A1–A5 numeric cutoffs as provisional preregistered targets; keep A6 as a product SLO.**
5. **Run the frozen no-call extraction-validity audit; stop if the evidence package is unreconstructable.**
6. **Keep both PDFs as research/history only; do not amend Specification or Decisions from them. Add explicit OPEN-QUESTIONS entries for construct validity, evidence staleness, statistical design/power, and scoped prior art.**
7. **Make no IP conclusion.**

### Recommended status of authoritative artifacts

| Artifact | Recommendation |
|----------|----------------|
| `SPECIFICATION.md` | No direct rewrite from this investigation. Ask ARCHITECT/humans to propose a narrowly scoped amendment adding extraction/grounding construct validity before A1 and marking exact numeric thresholds as provisional until powered. |
| `DECISIONS.md` | Retain cold isolation, structured operators, diagnosis-only behavior, preserved disagreement, and controller-owned evidence. Consider a decision amendment only to require content-addressed evidence invalidation and forbid “real fracture” labels without adjudicated validity. |
| `OPEN-QUESTIONS.md` | Add construct-validity/gold-graph design, stale-artifact invalidation, variance decomposition, clean-corpus sample size/power, endpoint multiplicity, and scope/owner of any professional prior-art review. |
| English supplied PDF | `research/history; unverified`. Extract primary citations only. Mark semantic-closure formula, weights, CI gating, novelty, patentability, and technical-effect claims unsupported. |
| Czech supplied PDF | `history/inspiration; superseded where conflicting`. Do not adopt philosopher personas or patch-writing workflow; current structured-operator and diagnosis-only decisions prevail. |

### Conclusion

**Recommendation:** Continue SUE only as a measured research program centered on extraction validity and decision-relative behavioral compatibility. Preserve its evidence safeguards; reject its present scalar/gating and “real fracture” claims.

**Confidence:** 0.96.

**Evidence:** Grade A primary requirements/LLM research and standards (E9, E11–E24), Grade B reproducible repository/patent inspection (E6–E8, E25–E29, E33), and Grade D direct but underpowered SRP measurements (E4–E5). Grade-E PDFs were used only as search leads.

**Caveats:** The patent search was time-boxed, non-exhaustive, and non-legal. No live models or independent human annotations were run. The exact SUE combination may still prove useful, but that remains an empirical question.

**Alternative if the no-call audit is blocked:** Record the missing evidence package as a negative result, then seek separate approval for a preregistered one-spec extraction-validity pilot with exact digests, ≥3 passes, two independent human annotators, and no semantic-closure or mutation claim.
