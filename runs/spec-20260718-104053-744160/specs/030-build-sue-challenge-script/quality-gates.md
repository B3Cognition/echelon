# Quality Gates — WHY2

## Verdict: PASS
## Mode: understanding-cli

Understanding CLI v3.7.0, 34 metrics, 83 requirements parsed. Machine output: `/tmp/u_validate.json` (validate), `/tmp/u_perreq.json` (enhanced per-requirement). Thresholds below are the harness-injected Resolved Quality Gates.

## Quality Scores

| Metric | Score | Threshold | Status | Notes |
|--------|-------|-----------|--------|-------|
| Overall | 0.7719 | 0.75 | PASS | Margin +0.0219 — borderline (< 0.05); all improvement items are advisory |
| Structure | 0.8342 | 0.75 | PASS | |
| Testability | 0.7886 | 0.75 | PASS | Margin +0.0386 — borderline; see sub-metrics: negative_space_coverage 0.356 |
| Semantic | 0.8534 | 0.65 | PASS | Strongest category; 0 requirements below gate |
| Cognitive | 0.6852 | 0.65 | PASS | Margin +0.0352 — borderline; concept_density 0.2158 and sentence_length 0.4684 are the drags |
| Readability | 0.6853 | 0.55 | PASS | |
| Depth | 0.872 | 0.4 | PASS | Understanding v3.6+ |
| Behavioral | 0.6215 | 0.55 | PASS | transition_completeness_score 0.2789 and observability_score 0.536 are the drags |

## Metric Improvement Recommendations

No metric is below threshold; the items below are advisory improvements for the three borderline categories (within 0.05 of gate). None is a required amendment.

### Cognitive (0.6852 → comfortable margin above 0.65)
- **Problem sections:** dense cross-reference parentheticals in AC-017, AC-023, SC-001, FR-010 (the 4 requirements below the per-requirement cognitive gate); `concept_density` 0.2158 is the weakest cognitive sub-metric across the document.
- **Specific fixes:**
  - Before: "Given a model call exceeds its timeout budget of at most 300 seconds by default, when the timeout expires…" (AC-017)
  - After: "Given a model call exceeds its timeout budget (default 300 seconds), when the timeout expires…"

### Behavioral (0.6215 → comfortable margin above 0.55)
- **Problem sections:** FR-015, FR-022, FR-035, FR-039, NFR-003 score behavioral 0.0 — they are constraint/content requirements phrased without a trigger→action→outcome shape. FR-022 and FR-035 are prohibitions/format contracts where this is inherent; FR-015 and FR-023 could gain explicit "When building the round-N instruction…" triggers.
- **Specific fixes:**
  - Before: "The round-1 instruction MUST request at most N Socratic challenge questions…" (FR-015)
  - After: "When composing the round-1 instruction, the challenge script MUST request at most N Socratic challenge questions…"

### Testability (0.7886, document gate PASS)
- **Problem sections:** 8 requirements score per-requirement testability 0.0 (see Per-Requirement Failures in issues.md); `negative_space_coverage` 0.356 indicates roughly one-third of requirements specify error/edge behavior — acceptable for this spec because a dedicated error-handling block (FR-005/006/011/012/017/025/027-031, ERR-001..005) concentrates the negative space.

## Testability Sub-Metrics (for speckit-echelon-sentinel (SENTINEL) consumption)

| Sub-Metric | Score | Interpretation |
|-----------|-------|---------------|
| hard_constraint_ratio | 0.9894 | Proportion of requirements with numeric/quantitative thresholds — near-total; the "exactly N" spec style pays off here |
| constraint_density | 0.7778 | Average measurable constraints per requirement — strong |
| negative_space_coverage | 0.356 | Proportion of requirements specifying error/edge/boundary cases — low as a ratio; error behavior is concentrated in the FR-005..FR-031 and ERR-001..ERR-005 blocks rather than spread across every requirement. SENTINEL should derive negative tests primarily from those blocks plus the Edge Cases section |

## Behavioral Transitions (for speckit-echelon-sentinel (SENTINEL) consumption)

Understanding extracted 147 transitions; 41 are complete (guard+action+outcome all present). Deduplicated complete transitions:

| # | Guard | Action | Outcome | Complete | Requirement |
|---|-------|--------|---------|----------|-------------|
| 1 | when | record | return | true | requirement_index: 5 |
| 2 | when | produce | code | true | requirement_index: 6 |
| 3 | when | render | render | true | requirement_index: 7 |
| 4 | when | render | render | true | requirement_index: 8 |
| 5 | when | change | write | true | requirement_index: 9 |
| 6 | when | record | record | true | requirement_index: 10 |
| 7 | when | create | record | true | requirement_index: 11 |
| 8 | when | save | output | true | requirement_index: 14 |
| 9 | on | save | output | true | requirement_index: 14 |
| 10 | when | process | output | true | requirement_index: 15 |
| 11 | when | get | code | true | requirement_index: 16 |
| 12 | when | execute | log | true | requirement_index: 37 |
| 13 | after | render | render | true | requirement_index: 38 |
| 14 | when | create | set | true | requirement_index: 39 |
| 15 | when | validate | output | true | requirement_index: 45 |
| 16 | if | record | return | true | requirement_index: 48 |
| 17 | if | record | output | true | requirement_index: 49 |
| 18 | when | validate | output | true | requirement_index: 53 |
| 19 | when | render | render | true | requirement_index: 67/68/74 |
| 20 | when | produce | code | true | requirement_index: 71/93 |
| 21 | - | modify | write | true | requirement_index: 72 |
| 22 | on | record | record | true | requirement_index: 88 |
| 23 | - | process | return | true | requirement_index: 89 |
| 24 | - | save | output | true | requirement_index: 90 |
| 25 | - | present | present | true | requirement_index: 108 |
| 26 | before | validate | active | true | requirement_index: 112 |

**SENTINEL handoff warning:** 106 of 147 extracted transitions are incomplete (missing guard, action, or outcome cell — `transition_completeness_score` 0.2789), and several complete rows above carry a `-` guard. Do NOT treat this table as complete behavioral coverage. SENTINEL must derive the test matrix primarily from the 23 Given/When/Then acceptance scenarios (AC-001..AC-023), the exit-code state machine (ERR-001..ERR-005, SC-003), and the FR "exactly N" constraints; the transitions above are corroborating evidence only.

## EARS Pattern Gaps

None — all 83 requirements match an EARS pattern (event_driven 71, ubiquitous 8, unwanted 3, optional 1, unclassified 0; Mavin et al., 2009).
