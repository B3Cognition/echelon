# Socratic Understanding research and novelty assessment

**Research date:** 2026-07-30
**Scope:** technical prior art relevant to the current design
**Caution:** this is not an exhaustive systematic review, patent search, or
claim of legal novelty.

## Second-pass reassessment

The independent second-thoughts review lowers the confidence of the first
assessment. The broad direction remains worth testing, but neither supplied
PDF is evidence that the proposed mechanisms work or are novel. Both PDFs are
AI-generated research/design memos. The English memo combines useful ideas with
strong novelty and patentability inferences from a non-exhaustive search; the
Czech memo is primarily a philosophical genealogy and design vocabulary.

The revised position is:

| Proposition | Second-pass status | Consequence |
|---|---|---|
| Cold, non-communicating runs reduce cross-run contamination. | Retain as an engineering safeguard, not proof of epistemic independence. | Measure common-mode provider/model errors and keep run conditions explicit. |
| Behavioural consequences are more useful than prose similarity. | Retain as a research hypothesis with strong conceptual support. | Operationalize a human-adjudicable compatibility construct before scoring it automatically. |
| Decision-relative behavioural compatibility is the central candidate contribution. | Plausibly distinctive as a synthesis, but not established as novel or valid. | Test construct validity and incremental value; make no publication or patent claim yet. |
| `QScore`, Semantic Closure Score, and Fracture Localization Index are validated measures. | Reject. They are proposed formulas with no demonstrated construct validity, calibrated weights, uncertainty estimates, or external validation. | Report their components separately until a validation study justifies aggregation. |
| Philosopher-labelled agent roles improve epistemic performance. | Unsupported. Historical schools can inspire deterministic challenge operators but do not validate personas. | Keep structured operators; do not infer reliability from the names. |
| Automatic rewriting and a deterministic CI block are ready. | Reject at the current evidence level and conflict with the diagnose-only decision. | Preserve human authority and keep SUE advisory until the measurement and false-positive gates pass. |
| The integrated architecture has medium-to-high or high patent novelty. | Withdraw. The search found materially closer literature and patent documents omitted by the PDF. | Treat all patent conclusions as non-legal and incomplete; use qualified counsel before claim drafting or freedom-to-operate decisions. |

The full evidence-graded challenge is recorded in
[`specs/investigation-20260730-075930`](../../specs/investigation-20260730-075930/).

## Research question

What prior work supports or overlaps a system that:

1. samples independent interpretations of a natural-language software
   specification;
2. turns them into grounded structured representations;
3. measures reproducibility relative to extraction/model noise;
4. detects decision-relevant behavioural incompatibility;
5. preserves disagreement and provenance; and
6. uses bounded Socratic operators to investigate selected fractures?

## Prior-art map

| Area | Established idea | Relation to SUE |
|---|---|---|
| Requirements ambiguity | Natural-language requirements can admit multiple interpretations, and empirical evaluation of ambiguity techniques has historically been limited. See [Addressing the challenges of requirements ambiguity](https://doi.org/10.1109/EmpiRE.2015.7431303). | SUE operationalizes “multiple interpretations” as independently sampled, requirement-anchored graphs and asks whether their behavioural consequences conflict. |
| Requirements smells | Lightweight static checks can detect recurring quality symptoms and supplement reviews, but categories are imperfect. See Femmer et al., [Rapid Quality Assurance with Requirements Smells](https://arxiv.org/abs/1611.08847). | Echelon's deterministic `understanding` metrics are the static baseline. SUE is intended to add semantic/behavioural evidence, not replace that baseline. |
| Controlled natural language | EARS constrains natural-language requirements into recurring patterns; NASA FRET adds formal semantics and analysis to structured requirements. See Mavin et al., [Easy Approach to Requirements Syntax (EARS)](https://doi.org/10.1109/RE.2009.9) and NASA's [Formal Requirements Elicitation with FRET](https://ntrs.nasa.gov/api/citations/20200001989/downloads/20200001989.pdf). | SUE uses controlled GIVEN/WHEN situations when available, while retaining a fallback for ordinary Markdown specs. |
| Self-consistency | Sampling multiple reasoning paths and selecting a consistent answer can improve benchmark accuracy. See Wang et al., [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171). | SUE deliberately does not promote the majority answer to truth. It uses convergence as a reproducibility measurement and preserves minority/unmatched interpretations. |
| Multi-agent debate | Multiple model instances can exchange answers and converge; debate can improve reasoning/factuality, but the authors also show examples that converge incorrectly. See Du et al., [Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/abs/2305.14325). | SUE's primary sample is cold and non-communicating. Cross-examination occurs only after aggregation, reducing premature social convergence and making contamination observable. |
| AI debate for oversight | Debate has been proposed as a way to make complex evidence judgeable by a weaker evaluator. See Irving, Christiano, and Amodei, [AI Safety via Debate](https://arxiv.org/abs/1805.00899). | SUE's bounded dialectic and evidence packages are closer to audit support than to adversarial winner selection; aporia is allowed. |
| Semantic uncertainty | Different strings can be semantically equivalent, so uncertainty estimation should account for linguistic invariance. See Kuhn, Gal, and Farquhar, [Semantic Uncertainty](https://arxiv.org/abs/2302.09664). | SUE similarly avoids raw string variance, but uses requirement-local typed relations, controlled situations, and provenance rather than semantic clustering of final answers alone. |
| Design diversity / N-version programming | Independently developed versions were proposed to reduce common-mode design faults. See Avizienis, [The N-Version Approach to Fault-Tolerant Software](https://doi.org/10.1109/TSE.1985.231893). | SUE applies the design-diversity intuition to interpretation. It must still measure common-mode model/extractor errors instead of assuming independence. |
| Differential testing | Multiple implementations can serve as mutual oracles when their outputs differ. See McKeeman, [Differential Testing for Software](https://dblp.org/rec/journals/dtj/McKeeman98.html). | SUE treats independently reconstructed semantic/behavioural artifacts as differential outputs, then localizes the disagreement to source anchors. |
| Mutation testing | Deliberately seeded faults test whether an analysis or test suite can detect meaningful changes. See Jia and Harman, [An Analysis and Survey of the Development of Mutation Testing](https://doi.org/10.1109/TSE.2010.62). | SRP v0 uses human-approved ambiguity, contradiction, boundary, assumption, and term mutations to test SUE itself rather than relying on compelling examples. |
| Pragmatic ambiguity via simulated expertise | A July 2026 preprint uses novice/intermediate/expert domain knowledge bases and multiple LLMs to detect discrepant requirement interpretations. See Nair and Anish, [A Retrieval-Augmented Framework for Detecting and Resolving Pragmatic Ambiguities in Natural Language Requirements](https://arxiv.org/abs/2607.04436). | This is close emerging work. SUE currently varies framing/provider and emphasizes cold reconstruction, typed provenance, measured extraction noise, and decision-relative behavioural compatibility rather than candidate rewriting. |
| Ambiguity through divergent implementations | ClarifyGPT infers ambiguity from functionally different generated programs and asks clarification questions; SpecFix repairs descriptions by changing the induced distribution of programs. See [ClarifyGPT](https://doi.org/10.1145/3660810) and Jia et al., [Automated Repair of Ambiguous Problem Descriptions](https://arxiv.org/abs/2505.07270). | Sampling behavioural consequences of a requirement is established prior art. SUE must show that its typed interpretation layer adds reliable localization or predictive value beyond implementation sampling. |
| Value-of-information clarification | Structured Uncertainty guided Clarification separates specification from model uncertainty and uses expected value of perfect information, cost, and redundancy to choose questions. See Suri et al., [Structured Uncertainty guided Clarification for LLM Agents](https://aclanthology.org/2026.findings-acl.2028/). | The PDF's information-gain/cost/answerability question score is not distinctive by itself. Any SUE question policy needs a direct baseline against this family of methods. |
| Requirements quality as downstream impact | Requirements quality research has been criticized for proposing normative metrics without showing their impact on later engineering activities. See Frattini et al., [Requirements quality research: a harmonized theory, evaluation, and roadmap](https://link.springer.com/article/10.1007/s00766-023-00405-y). | This supports SUE's decision-relative emphasis, but also raises the bar: a closure score is not a quality measure until it predicts or improves a specified downstream activity. |
| Multi-agent debate limitations | Recent controlled work reports that vanilla debate can underperform majority vote and that diversity and confidence affect outcomes. See Zhu et al., [Demystifying Multi-Agent Debate](https://aclanthology.org/2026.findings-acl.1694/). | Cold sampling and preserved disagreement are sensible safeguards. They still do not establish truth, independence, or improvement over simpler ensembles. |
| Socratic elenchus | Socratic questioning tests definitions, criteria, consequences, counterexamples, and revision, often ending in unresolved impasse. | SUE compiles these moves into deterministic transition policies. The philosophical vocabulary supplies operator shapes; it is not evidence that a model persona is epistemically reliable. |

## What is not novel

No global novelty claim should be made for:

- multiple sampled model outputs;
- majority/self-consistency voting;
- multi-agent debate;
- static requirements smells;
- controlled-natural-language requirements;
- graph extraction from text;
- provenance annotations;
- mutation-based validation;
- differential comparison; or
- Socratic prompting.

Each has substantial prior art.

## Candidate synthesis, not a novelty claim

The repository's most interesting research candidate remains the combination
below. The second pass found no basis for calling the combination legally novel,
and several elements have closer prior art than the first pass recorded:

1. **Cold, non-communicating reconstruction** before any aggregation.
2. **Requirement-local typed graphs and behavioural assertions** with source
   lines and run identity.
3. **Noise-floor-relative interpretation comparison** that explicitly separates
   specification divergence from extraction/model variance.
4. **Decision-relative compatibility**, where only material behavioural
   consequences can block a specific engineering decision.
5. **Preserved minority and unmatched interpretations**, avoiding forced
   consensus.
6. **Aporia as a first-class diagnostic state**, rather than mandatory answer or
   rewrite.
7. **Controller-owned evidence integration** into a spec-authoring workflow,
   distinct from qualitative agent judgment.
8. **Mutation-validated promotion gates**, so an attractive multi-agent
   narrative does not become a workflow gate before it demonstrates incremental
   value over deterministic analysis.

The closest technical adjacencies now include pragmatic-ambiguity comparison,
ClarifyGPT's divergent implementations, SpecFix's induced-program
distributions, and value-of-information clarification. A particularly close
pending Chinese patent application,
[CN121918799A](https://patents.google.com/patent/CN121918799A/en), describes
deriving preconditions from candidate implementations, extracting and
classifying implicit assumptions, detecting mutually exclusive assumptions,
quantifying uncertainty, and generating structured clarification items.
[US20260119847A1](https://patents.google.com/patent/US20260119847A1/en) also
describes task-specific ambiguity detection and clarification-question
generation. These documents do not decide patent scope or validity, but they
make the PDF's high-novelty conclusion unsafe.

## Measurement and experimental-design audit

The current A1–A6 gates are useful provisional engineering targets, not
literature-derived or validated cutoffs.

1. **Agreement is not accuracy.** High edge agreement can reflect a shared
   extraction error; low agreement can reflect equivalent labels. A1 therefore
   needs an adjudicated reference subset and negative/no-relation cases in
   addition to run-to-run Jaccard.
2. **The proposed variance components are confounded.** The current `K=5`
   design changes presentation order, prompt family, and sampling temperature
   together. It cannot separately estimate extraction, sampling, framing, and
   provider effects. Use a crossed, replicated design and report each changed
   condition. NIST distinguishes same-condition
   [repeatability from changed-condition reproducibility](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-d1-terminology).
3. **Pairwise reader scores are dependent observations.** Reader pairs share
   runs, mutants share a source specification, and multiple mutants share an
   operator. Analyze at the specification/mutation-site level with clustered or
   hierarchical uncertainty; do not treat every pair as an independent sample.
4. **Thresholds and effect sizes need uncertainty.** `0.80/0.70`, four of five
   operators, Precision@3 `0.60`, recall `0.70`, 10% false positives, Cohen's
   `d ≥ 0.8`, and AUC uplift `0.05` are policy choices. Pre-register them as
   provisional, report confidence intervals, and lock them before validation.
5. **A5 is underpowered as written.** Ten to fifteen source specs cannot support
   a stable model containing the 34 deterministic metrics plus semantic
   features and historical covariates. Split mutant detection from historical
   outcome prediction, hold out whole specifications, and avoid coefficient
   significance as a promotion rule.
6. **A single weighted closure score can hide fatal components.** Compensation
   between unresolved claims, contradictions, omissions, and provenance is not
   justified. Keep disaggregated gates until weights and monotonicity are
   validated against human decisions and downstream outcomes.

These changes follow the
[ACM SIGSOFT empirical standards](https://www2.sigsoft.org/EmpiricalStandards/),
which explicitly call for construct, conclusion, internal-validity,
reliability, objectivity, and reproducibility analysis.

## Proposed P0 retrospective preflight — unapproved

The following frozen, no-new-model-call audit is a proposed evidence-lifecycle
and construct-validity preflight. It is not the authoritative next experiment
and does not supersede SU-D012 or the handoff: A1 extraction stability remains
the next experimental gate. Making this preflight mandatory before A1 requires
an explicit amendment to `DECISIONS.md`, `HANDOFF.md`, and the SRP experiment
plan.

If separately approved, the preflight would:

1. bind one saved run to its exact historical spec snapshot;
2. recover the raw outputs, prompts, schema/tool/model identity, and pass
   identity;
3. have two independent human reviewers annotate 20–30 stratified requirements
   and adjudicate while retaining disagreement; and
4. report typed-edge precision/recall/F1, provenance accuracy, run agreement,
   and disagreement causes.

If the evidence package cannot be reconstructed, stop and record an
evidence-lifecycle failure. If it can be reconstructed but extraction validity
is inadequate, stop before mutation work.

This preflight tests historical evidence recoverability and extraction
accuracy; A1 tests clean-run extraction stability. If the preflight is later
approved, its result should inform a separately approved calibration study using
three to five unmutated specifications stratified by style and domain, locked
schema/canonicalization/prompt rules, and controlled repeatability versus
reproducibility perturbations. Keep the existing two-spec glossary experiment
as an engineering smoke test, not instrument validation. Mutation sites in any
later study must be human-reviewed for realism and equivalence, and whole source
specifications—not individual reader pairs or mutants—must define data splits.

This order is especially important because the checked-in
`semantic-reproducibility.json` was generated before a later correction to its
source specification, contains no input digest, and still reports the resolved
four-versus-five-header-facts contradiction. Current “trustworthy scores” and
“real fracture set” wording therefore describes historical candidate evidence,
not current validated findings.

## Research hypotheses already encoded in the repository

The SRP v0 plan defines:

- **P1 detection:** injected defects raise the relevant divergence/conflict
  channel above clean controls;
- **P2 localization:** the detector ranks the mutated requirement near the top;
- **P3 incremental value:** semantic features add predictive value over the
  deterministic 34-metric baseline; and
- **P4 behavioural value:** defective specifications cause incompatible
  acceptance assertions.

Source:
[`2026-07-18-semantic-reproducibility-probe-v0.md`](../superpowers/plans/2026-07-18-semantic-reproducibility-probe-v0.md).

## Current evidence assessment

### Supported at smoke scale

- The smoke run localized an M1 ambiguity at rank 1.
- Its explicit conflict channel found the injected M2 contradiction 3/3.
- Deterministic Understanding and Lexicon scores barely moved for the two
  mutations.

### Not established

- Clean extraction stability: A1 failed badly in the first smoke.
- General detection/localization rates across a corpus.
- Low false-positive rate across diverse clean specs.
- Incremental predictive value for historical rework.
- Exhibited behavioural incompatibility beyond heuristic candidates.
- Independence across model families/providers.
- Blind auditability of the justification graph.
- Operational cost at full-corpus scale.

### Consequence

SUE is a promising diagnostic instrument with working implementations and
useful anecdotal/smoke evidence. It is not yet scientifically justified as an
automatic blocking quality gate. The next research action is the A1
extraction-stability experiment, not broader workflow authority.

## Citation and evidence policy

- Prefer primary papers, official technical reports, and repository measurements.
- Label preprints as preprints.
- Do not cite consensus among model runs as external factual evidence.
- Separate measured repository results from design hypotheses.
- Record tool/schema version, models/providers, prompts/framings, raw sidecars,
  and negative results.
- Re-run searches before making a publication, patent, or novelty claim; this
  file is a scoped engineering review.
