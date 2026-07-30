# Socratic Understanding research and novelty assessment

**Research date:** 2026-07-30
**Scope:** technical prior art relevant to the current design
**Caution:** this is not an exhaustive systematic review, patent search, or
claim of legal novelty.

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

## Potentially distinctive synthesis

Subject to a broader literature and patent search, the repository's distinctive
contribution may be the combination of:

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

The closest new adjacency found in this review is the July 2026 pragmatic
ambiguity preprint above. It strengthens the need to phrase novelty modestly and
to compare experimentally rather than rhetorically.

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
