# Determinism Audit: 16 Internalization Metrics

For each metric: input type, NLP dependency, determinism guarantee, and known limitations.

## Category 1: Absorption (I-01 to I-04)

### I-01: Requirement Coverage
- **Input type:** Regex (pattern: `/FR-\d{3}/g` against agent output; set intersection with spec requirement IDs)
- **Requires NLP:** No
- **Deterministic:** Yes — regex extraction + set division produces identical output for identical input
- **Known limitation:** None. Pure set operation on regex-extracted identifiers.

### I-02: Constraint Extraction Rate
- **Input type:** Regex (extract numeric constraint patterns from agent output; set intersection with spec constraints)
- **Requires NLP:** No
- **Deterministic:** Yes — regex matching on known constraint patterns, then set ratio
- **Known limitation:** None. Constraints are defined as exact string patterns in the spec.

### I-03: Terminology Fidelity (Jaccard)
- **Input type:** Jaccard similarity (intersection of glossary terms found in output vs. glossary terms in spec, divided by union)
- **Requires NLP:** No — exact string matching on glossary term list, not semantic similarity
- **Deterministic:** Yes — Jaccard over finite term sets is a pure arithmetic operation
- **Known limitation:** None. Terms are matched literally, not semantically.

### I-04: Dependency Recognition
- **Input type:** Set operation (dependencies mentioned in output vs. dependencies listed in spec)
- **Requires NLP:** No
- **Deterministic:** Yes — substring/regex search for each dependency name, then set ratio
- **Known limitation:** None. Dependency names are proper nouns matched literally.

## Category 2: Accuracy (I-05 to I-08)

### I-05: Constraint Adherence Score
- **Input type:** Arithmetic (extract numeric values from output, compare against spec constraint bounds using operators <=, >=, =)
- **Requires NLP:** No
- **Deterministic:** Yes — numeric extraction via regex, arithmetic comparison, then proportion
- **Known limitation:** Proxy signal fidelity. Agent may state a value textually ("aim for ~200ms") that the regex parses as a specific number. Ambiguous phrasing like "around 200ms" may extract as 200 and pass, even if the agent's intent was approximate.

### I-06: Decision Traceability
- **Input type:** Regex (count decisions that contain an FR-* citation within N characters, divided by total decisions found)
- **Requires NLP:** No
- **Deterministic:** Yes — regex pattern matching for decision markers and nearby FR-* references
- **Known limitation:** Proxy signal fidelity. Relies on "Decision:" prefix pattern. An agent that phrases decisions differently ("We chose X because...") without using the marker pattern will score 0 even if decisions are well-traced.

### I-07: Cross-Reference Accuracy
- **Input type:** Set operation (FR-* IDs cited in output validated against actual FR-* IDs in spec; proportion that exist)
- **Requires NLP:** No
- **Deterministic:** Yes — set membership check, pure arithmetic
- **Known limitation:** None. Binary check: does the cited ID exist in the spec or not.

### I-08: Boundary Compliance
- **Input type:** Arithmetic (for each spec constraint, check if the agent's stated value satisfies the operator and bound)
- **Requires NLP:** No
- **Deterministic:** Yes — numeric comparison with defined operators
- **Known limitation:** Proxy signal fidelity. Same as I-05: relies on regex extraction of numeric values. If the agent omits a constraint entirely (neither compliant nor non-compliant), the metric must define a default (fail-open or fail-closed).

## Category 3: Calibration (I-09 to I-12)

### I-09: Confidence Calibration (Brier Score)
- **Input type:** Brier score (mean squared error between agent's stated confidence and binary correctness: Brier = mean((confidence - correct)^2))
- **Requires NLP:** No
- **Deterministic:** Yes — squared difference arithmetic over extracted confidence values and known correctness labels
- **Known limitation:** None. Brier score is a deterministic function of two numeric vectors.

### I-10: Priority Alignment (Spearman)
- **Input type:** Spearman rank correlation (agent's implied priority ordering of requirements vs. spec's defined priority ordering)
- **Requires NLP:** No — priority is inferred from mention order or explicit ranking, not semantic analysis
- **Deterministic:** Yes — rank correlation is a deterministic function of two ordinal vectors
- **Known limitation:** None. Spearman rho is fully determined by the rank vectors.

### I-11: Scope Boundary Precision
- **Input type:** Set operation (items agent marks as in-scope vs. spec's defined scope; precision = true positives / (true positives + false positives))
- **Requires NLP:** No
- **Deterministic:** Yes — set-based precision calculation
- **Known limitation:** None. Scope items are matched literally against the spec's scope definition.

### I-12: Assumption Validity Rate
- **Input type:** Set operation (assumptions stated by agent checked against spec's explicit statements; proportion that do not contradict spec)
- **Requires NLP:** No
- **Deterministic:** Yes — each assumption is pattern-matched against spec clauses for contradiction
- **Known limitation:** None. Assumptions are extracted by regex pattern ("Assumption:" prefix) and validated against spec text.

## Category 4: Transfer (I-13 to I-16)

### I-13: Requirement-to-Test Mapping Completeness
- **Input type:** Set operation (FR-* IDs that appear in test descriptions vs. all FR-* IDs in spec)
- **Requires NLP:** No
- **Deterministic:** Yes — set coverage ratio
- **Known limitation:** None. Pure set operation on regex-extracted identifiers.

### I-14: Edge Case Derivation Rate
- **Input type:** Arithmetic (count of edge cases derived from constraints divided by number of constraints; edge cases identified by "Edge case:" or "Boundary:" prefix patterns)
- **Requires NLP:** No
- **Deterministic:** Yes — regex count divided by known constraint count
- **Known limitation:** None. Relies on prefix patterns for edge case identification.

### I-15: Spec-to-Implementation Consistency
- **Input type:** Jaccard (set of spec terms/IDs appearing in implementation artifacts vs. set appearing in spec)
- **Requires NLP:** No
- **Deterministic:** Yes — Jaccard similarity over literal term sets
- **Known limitation:** None. Term matching is literal, not semantic.

### I-16: Regression Anchor Coverage
- **Input type:** Set operation (constraint values that appear as explicit assertion values in test code, divided by total constraints)
- **Requires NLP:** No
- **Deterministic:** Yes — regex search for constraint values in test artifacts, then set ratio
- **Known limitation:** None. Numeric values are matched literally.

---

## Summary

| Property           | Result |
|--------------------|--------|
| Metrics requiring NLP | 0 of 16 |
| Deterministic metrics  | 16 of 16 |
| Metrics with proxy fidelity limitations | 3 (I-05, I-06, I-08) |
| Input types used | Regex, Set operation, Arithmetic, Jaccard, Brier, Spearman |

All 16 metrics produce identical outputs given identical inputs. No metric relies on natural language processing, embedding models, or non-deterministic inference. The proxy-based design trades semantic precision for full determinism and reproducibility.
