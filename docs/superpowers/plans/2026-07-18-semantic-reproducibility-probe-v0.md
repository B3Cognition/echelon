# Semantic Reproducibility Probe v0 — Experiment Specification

**Status:** draft for review — experiment spec only, not production architecture
**Parent concept:** Socratic Understanding Engine (SUE) — this probe validates SUE's core
scientific proposition before any commitment to recursive dialogue, reasoning-graph
convergence, or workflow integration.

## 1. Hypothesis

> **H-core:** Isolated LLM interpretations of a specification, converted to typed graphs and
> compared through anchor-based alignment, detect and localize controlled semantic defects
> better than Echelon's 34 deterministic Understanding metrics alone.

Falsification condition: if mutant-induced divergence is not statistically separable from
the clean-spec noise floor, or localization does not beat chance, SUE's premise fails and
the recursive/Socratic roadmap should not proceed.

Sub-hypotheses measured (mapped from H1–H6 of the research assessment):

- **P1 (detection):** injected defects raise interpretation divergence above the noise floor.
- **P2 (localization):** the divergent subgraph traces to the mutated requirement.
- **P3 (incremental value):** divergence signals add predictive value over the 34 metrics.
- **P4 (behavioural):** interpretations of defective specs imply incompatible behaviour.

Out of scope for v0: multi-round debate, graph edit distance, Neo4j/RDF, Minimal
Clarification Set search, model-family heterogeneity (single family, controlled variation
only), human studies, workflow (`phase3-consensus`) integration.

## 2. Pipeline

```text
Clean specification (lexicon-validated preferred)
        │
        ├── original                       (control)
        ├── M1 ambiguity mutant
        ├── M2 contradiction mutant
        ├── M3 missing-boundary mutant
        ├── M4 hidden-assumption mutant
        └── M5 undefined-term mutant
                 │
                 ▼
        K = 5 isolated interpretation runs per variant
                 │
                 ▼
        Typed interpretation graphs (schema §5) with full provenance
                 │
                 ▼
        Deterministic anchor graph + 6-step alignment (§6)
                 │
                 ▼
        Divergence measurement: typed-edge, assumption, behavioural (§7)
                 │
                 ▼
        Defect localization report (per-requirement divergence attribution)
```

## 3. Corpus

- **Source:** 10–15 specs from `specs/` history that (a) passed all deterministic
  Understanding gates and (b) have known downstream outcomes (review-fix counts,
  `RF{n}-T*` task counts) for the P3 incremental-value analysis.
- **Preference:** lexicon-validated specs (`src/lexicon/` grammar + resolved glossary);
  free-text specs admitted only with an `alignment_confidence` penalty recorded.
- **External anchor (optional, phase v0.5):** a 50-task sample from the Orchid benchmark
  for cross-checking detection rates against published ambiguity categories.

## 4. Mutation operators

Each operator produces exactly one localized edit; the mutated requirement ID is the
ground-truth label. One mutation per mutant document (no compounding in v0).

| ID | Operator | Definition | Generation rule | Example |
|----|----------|------------|-----------------|---------|
| M1 | Ambiguity | Replace a determinate term/quantifier with one admitting ≥2 readings | Swap lexicon term for undeclared near-synonym; or replace "all"/"each" with "the", "some", bare plural. **Sub-classify and report separately:** M1a *recoverable* (another requirement/error block still states the determinate form — tests disambiguation burden) vs M1b *unrecoverable* (no in-document resolution — tests true ambiguity) | "each pending order" → "pending orders" |
| M2 | Contradiction | Insert/modify a requirement conflicting with an existing constraint | Negate or bound-shift a constraint referencing the same anchor, **placed ≥ 5 requirements away or in a different block type (REQ vs ERROR vs CONSTRAINT)** — adjacent-block conflicts are rejected as trivially detectable. The conflicting pair must be binding-vs-binding under the §5 bindingness rules | REQ-09 "≤ 3 retries" + mutated REQ-17 "retries until success" |
| M3 | Missing boundary | Delete an edge-condition clause | Remove an `except_when`/limit/range clause, keep the sentence grammatical | drop "unless the order is already shipped" |
| M4 | Hidden assumption | Remove an explicitly stated precondition the rest of the spec silently relies on | Delete the declaration; keep all uses | delete "sessions expire after 30 min"; keep requirements that assume expiry |
| M5 | Undefined term | Introduce a domain term absent from the lexicon/glossary | Replace one governed term with an ungoverned synonym at one site only | "authenticated session" → "active login context" (undeclared) |

Mutation authoring: LLM-proposed, **human-approved** (or rule-generated where possible —
M3/M4/M5 are largely mechanical). Every mutant is re-run through the deterministic
Understanding metrics; record whether the 34 metrics already flag it (this is the P3
contingency table, not an exclusion criterion).

**Site pre-screening (added after the 2026-07-18 smoke run):** before accepting a
mutation site, verify the *clean* spec is defect-free at that site — no latent tension
involving the target requirement (human review plus the clean-control conflict channel).
Injecting into a site with a pre-existing seam contaminates ground truth in both
directions: it boosts mutant detectability and hides a control false negative. Latent
defects discovered during pre-screening are recorded as *found defects* (a probe result
in their own right), and the site is excluded from the mutation corpus.

## 5. Interpretation protocol and graph schema (v0)

### Isolation contract (hard requirement)

Each interpretation run receives ONLY: the spec variant, the lexicon/glossary, the
deterministic Understanding output, and its assigned question family.
It must NOT receive: other interpretations, aggregate graphs, divergence reports,
`reasoning-journal.jsonl`, or any squad state. **Implementation consequence:** runs go
through `ClaudeCliProvider` directly (`src/harness/llm_provider.py`), NOT through squad
dispatch — squad context packs include the reasoning journal and would contaminate runs.
Only the aggregator reads all outputs.

### Controlled variation (v0 axes)

K = 5 runs per variant varying: (a) requirement presentation order (3 permutations),
(b) question-family prompt (structural / behavioural / adversarial phrasing),
(c) sampling temperature. Same model family in v0 — cross-family heterogeneity is a v1
axis; v0 measures *replicated-sample* reproducibility and states so.

### Node types (v0 subset of the full SUE ontology)

`Requirement, Actor, Action, Object, Condition, Outcome, Assumption`
(deferred to v1: State, Event, Constraint, Exception, Invariant, Decision, ExternalDependency)

### Edge types (v0)

`performs, acts_on, applies_when, results_in, assumes, conflicts_with, except_when`

### Mandatory provenance on every node and edge

```yaml
requirement_id:        # REQ-nnn anchor, or null + reason
source_span:           # char offsets into the spec variant
canonical_lexicon_id:  # resolved via lexicon glossary, or "UNRESOLVED"
extractor_confidence:  # 0–1 self-reported
interpretation_run_id: # run UUID
```

A node without `source_span` grounding is excluded from convergence scoring and counted
in the `ungrounded_invention_rate` diagnostic instead.

### Bindingness rules (added after the 2026-07-18 smoke run)

`conflicts_with` edges require both sides to be **binding**. Binding constraint sources
are: REQ `THEN` clauses with MUST/MUST NOT, `CONSTRAINT` lines, `AC` blocks (acceptance
criteria are executable obligations), and `ERROR` blocks. SHOULD-level clauses are
non-binding on their own; a SHOULD requirement participates in a hard conflict only via
its binding AC or CONSTRAINT. Extraction prompts state this explicitly — the smoke run
showed agents otherwise decide AC bindingness themselves, an uncontrolled degree of
freedom.

### Extraction stabilization (precondition for the corpus run)

The smoke-run noise floor (0.346 vs the ≥ 0.80 A1 target) showed label variance
dominates before any mutation signal is measurable. Before the full corpus run:
anchor node labels with a shared few-shot exemplar block in the extraction prompt,
prefer glossary-resolved terms as labels where a lexicon glossary exists, and re-measure
A1 on 2–3 clean specs. The corpus run proceeds only once A1 is met — otherwise iterate
on extraction, not on the corpus.

### Behavioural layer (minimal v0 form)

Per interpretation, for each Requirement node: 1–3 acceptance assertions in
given/when/then form with anchors. Behavioural divergence = two interpretations whose
assertion sets are incompatible on the same anchor (one's `then` violates the other's).
v0 checks incompatibility symbolically (same given/when, contradictory then), not by
executing code.

## 6. Anchor graph and alignment

Anchor graph is built **deterministically** — no LLM: requirement IDs from spec structure,
`ACTOR-*` / `TERM-*` / `STATE-*` anchors from the lexicon glossary (`src/lexicon/resolver.py`),
actor/action/object skeleton from `src/understanding/entity_metrics.py`.

Alignment order (stop at first match; never force-merge):

1. Exact requirement / lexicon ID match.
2. Deterministic normalization (case, lemma, article stripping).
3. Lexicon aliases and declared synonyms.
4. Structural similarity constrained by node type (same type + shared anchored neighbours).
5. Embedding similarity, only for still-unresolved candidates, threshold ≥ 0.85 cosine.
6. Explicitly `UNMATCHED` — recorded, never merged.

Two divergence channels reported separately:

- **Interpretation divergence** — different semantics attached to the same anchors
  (different edges, conditions, outcomes). *Only this reduces semantic reproducibility.*
- **Vocabulary divergence** — equivalent semantics under different labels (resolved at
  steps 2–5). Reported as a diagnostic of extraction/lexicon quality.

## 7. Measurements

### Operator → detection-channel matrix (added after the 2026-07-18 smoke run)

Detection is scored **per channel**, not by one aggregate divergence number. The smoke
run demonstrated why: a contradiction made per-edge extraction *more* consistent
(individually clearer text, jointly unsatisfiable spec), so the divergence channel is
structurally blind to M2 while the conflict channel caught it 3/3.

| Operator | Primary channel | Secondary channel |
|----------|----------------|-------------------|
| M1 ambiguity (a/b) | typed-edge divergence + localization | assumption load |
| M2 contradiction | `conflicts_with` reports (consensus across runs) | — |
| M3 missing boundary | boundary/`except_when` edge absence divergence | behavioural divergence |
| M4 hidden assumption | assumption load delta | behavioural divergence |
| M5 undefined term | `UNRESOLVED` lexicon-id rate + vocabulary divergence | typed-edge divergence |

A mutant counts as detected only if its **primary** channel fires; secondary-channel
hits are reported but scored separately.

| # | Measurement | Definition | Establishes |
|---|-------------|------------|-------------|
| 1 | Clean-spec stability (noise floor) | mean pairwise typed-edge agreement (per-type Jaccard over aligned edges) across K runs on unmutated specs | extraction + model variance baseline |
| 2 | Mutant detection rate | fraction of mutants where divergence exceeds noise floor by the detection threshold | P1 |
| 3 | Localization precision | mutated REQ in top-3 divergence-ranked requirements; per-requirement agreement drops are **normalized by that requirement's clean-floor variance** (raw drops over-rank requirements that are noisy even on clean specs) | P2 |
| 4 | Localization recall | fraction of mutants localized at all | P2 |
| 5 | False-positive rate | clean specs flagged as divergent | operational viability |
| 6 | Behavioural divergence rate | incompatible assertion pairs per anchor, mutants vs clean | P4 |
| 7 | Incremental value | Δ in predicting (a) mutant presence, (b) historical rework counts, using divergence features vs 34 metrics alone | P3 |
| 8 | Cost per spec | tokens + wall-clock per variant at K=5 | tiering design input |

Variance decomposition (the load-bearing baseline):

```text
observed divergence = specification divergence + extraction variance + model variance
```

Extraction + model variance are estimated on clean controls FIRST (measurement 1);
detection (measurement 2) is always reported relative to that floor, never absolutely.

## 8. Baselines

1. 34 deterministic Understanding metrics alone (`understanding` CLI).
2. Text-similarity baseline: pairwise embedding similarity of raw interpretation prose
   (no graphs) — proves graphs add value beyond "answers sound different".
3. Untyped-graph baseline: node-set overlap without edge types — proves typing matters.

## 9. Thresholds and acceptance criteria

v0 **passes** (proceed to v1: heterogeneous models, Justification Graph, WHY3 feed) iff:

- **A1 noise floor:** clean-spec typed-edge agreement ≥ 0.80 mean, ≥ 0.70 min per spec.
  Below this, fix extraction before drawing any conclusion (probe is *inconclusive*, not failed).
- **A2 detection:** ≥ 4/5 operators fire on their **primary channel** (§7 matrix):
  divergence-channel operators need mutant divergence > noise floor with Cohen's d ≥ 0.8
  (paired per source spec); report-channel operators (M2 conflicts, M5 unresolved-term
  rate) need majority-of-runs consensus with 0 false positives on paired clean controls.
- **A3 localization:** precision@3 ≥ 0.6 and recall ≥ 0.7 over all detected mutants.
- **A4 false positives:** ≤ 10% of clean specs flagged at the chosen detection threshold.
- **A5 incremental value:** divergence features improve mutant classification AUC by
  ≥ 0.05 over the 34-metric baseline, and add nonzero coefficient significance on the
  historical rework regression.
- **A6 cost:** ≤ 15 min wall-clock and a recorded token cost per spec variant at K=5
  (no pass/fail — an input to Lite/Deep/Forensic tiering).

v0 **fails** (revisit SUE premise) if A2 and A3 both miss after A1 is satisfied.

## 10. Deliverables

1. `probe/` experiment harness (standalone; imports `understanding`, `lexicon`,
   `harness.llm_provider` — writes nothing to squad state or journals).
2. Mutation corpus with ground-truth labels (checked in, human-approved).
3. Results report: all 8 measurements, variance decomposition, per-operator breakdown,
   acceptance-criteria scorecard.
4. Decision memo: proceed / fix-extraction / halt, with the evidence.

## 11. Notes for the eventual integration (recorded, not built)

- SUE feeds `phase3-consensus` as WHY3 evidence (divergence witnesses → critical issues
  routing back to WHAT); extraction instability alone must not block a spec.
- Any state keys SUE introduces (e.g. `sue_findings`) must be declared in
  `extension/workflow/definition.yaml` `allowed_state_updates` — per the standing lesson
  that contract keys added only in Python code get stripped on the agent path.
- New journal entry types belong in `extension/workflow/journal-entry-types.yaml`.
- Justification Graph (claims / evidence / assumptions / behavioural consequence records)
  is the v1 representation; v0's assumption nodes + acceptance assertions are its seed.
