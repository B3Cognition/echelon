# Quality Gates — WHY3

## Verdict: FAIL
## Mode: understanding-cli

Understanding CLI, 34 metrics, 83 requirements parsed. Machine output: `/tmp/u_validate.json` (validate, exit 0), `/tmp/u_perreq.json` (enhanced per-requirement). Thresholds below are the harness-injected Resolved Quality Gates.

**The FAIL verdict is NOT metric-driven** — all 8 document-level gates pass, with scores byte-identical to WHY2 because spec.md received zero amendments between WHY2 and WHY3. The verdict is driven by the issues ledger (see issues.md): 1 CRITICAL (escalated coverage rows SC-001/AC-023 have no `deferred_risky_accepted` record in state.json — WHY3 automation coverage check) and 3 HIGH issues escalated from unaddressed WHY2 MEDIUMs per the iteration-awareness rule. Blocking Rule 1 (any CRITICAL → FAIL) and Rule 6 (required CARTOGRAPHER/DISCOVER amendments remain) both apply.

## Quality Scores

| Metric | Score | Threshold | Status | Notes |
|--------|-------|-----------|--------|-------|
| Overall | 0.7719 | 0.75 | PASS | Margin +0.0219 — borderline (< 0.05); all metric improvements remain advisory |
| Structure | 0.8342 | 0.75 | PASS | |
| Testability | 0.7886 | 0.75 | PASS | Margin +0.0386 — borderline; negative_space_coverage 0.356 (see sub-metrics) |
| Semantic | 0.8534 | 0.65 | PASS | Strongest category; 0/83 per-requirement failures |
| Cognitive | 0.6852 | 0.65 | PASS | Margin +0.0352 — borderline; concept_density 0.2158 remains the drag |
| Readability | 0.6853 | 0.55 | PASS | |
| Depth | 0.872 | 0.4 | PASS | Understanding v3.6+ |
| Behavioral | 0.6215 | 0.55 | PASS | transition_completeness_score 0.2789 and observability_score 0.536 remain the drags |

## Metric Improvement Recommendations

No metric is below its document-level threshold. The WHY2 advisory recommendations for the three borderline categories (cognitive parenthetical density in AC-017/AC-023/SC-001/FR-010; behavioral trigger phrasing for FR-015/FR-022/FR-035/FR-039/NFR-003; testability negative-space concentration) remain valid verbatim and remain advisory — none was applied, and none is a required amendment. When CARTOGRAPHER touches spec.md for the required ISS-302/ISS-303 rewordings (issues.md), applying the WHY2 cognitive/behavioral one-liners at the same time would lift the two thinnest margins at near-zero cost.

## Testability Sub-Metrics (for speckit-echelon-sentinel (SENTINEL) consumption)

| Sub-Metric | Score | Interpretation |
|-----------|-------|---------------|
| hard_constraint_ratio | 0.9894 | Proportion of requirements with numeric/quantitative thresholds — near-total; the "exactly N" spec style pays off |
| constraint_density | 0.7778 | Average measurable constraints per requirement — strong |
| negative_space_coverage | 0.356 | Proportion of requirements specifying error/edge/boundary cases — low as a ratio because error behavior is concentrated in FR-005..FR-031 and ERR-001..ERR-005. SENTINEL's test-strategy.md already responds correctly: negative-test matrix derived from the concentrated error blocks plus the Edge Cases section, ~45% negative-path weighting (SNT-007 deficiency handled) |

## Behavioral Transitions (for speckit-echelon-sentinel (SENTINEL) consumption)

Understanding extracted 147 transitions; 41 are complete (guard+action+outcome all present) — identical to WHY2 (the spec text is unchanged). The deduplicated complete-transition table in WHY2's quality-gates revision remains the accurate handoff record; SENTINEL has already consumed it (test-strategy.md, coverage-map.md exist and honour the handoff warning).

**Standing SENTINEL handoff warning (unchanged):** 106 of 147 extracted transitions are incomplete (`transition_completeness_score` 0.2789). Do NOT treat the extracted transitions as complete behavioral coverage. The test matrix is correctly derived from the 23 Given/When/Then acceptance scenarios (AC-001..AC-023), the exit-code state machine (ERR-001..ERR-005, SC-003), and the FR "exactly N" constraints; the transitions are corroborating evidence only. Verified at WHY3: coverage-map.md maps every FR/AC/NFR/ERR/SC row to enumerated test cases, so the incomplete-transition risk did not propagate into the test design.

## EARS Pattern Gaps

None — all 83 requirements match an EARS pattern (event_driven 71, ubiquitous 8, unwanted 3, optional 1, unclassified 0; Mavin et al., 2009).

## WHY3-Only Gate Checks

| Check | Result | Evidence |
|-------|--------|----------|
| coverage-map.md exists | PASS | Produced by SENTINEL; all 83 requirement rows mapped |
| Rows with coverage_type `manual` or `none` | PASS (0 rows) | Every requirement is `automated` except SC-001/AC-023 |
| Rows with coverage_type `deferred-automation` | PASS (0 rows) | No deferred-automation debt |
| Escalated rows have `deferred_risky_accepted` in state.json | FAIL | SC-001 and AC-023 carry coverage_type `escalate`; state.json has NO `deferred_risky_accepted` entry (verified: key absent). CRITICAL ISS-301 raised — SAGE cannot issue a WHY3 PASS until the acceptance is recorded |
| Flakiness Management section (test-strategy.md) | PASS | All 5 mandated concerns present with concrete values: detection protocol (5 consecutive full runs pre-merge), quarantine process (`skip` marker + linked tracking issue, blocking-debt status), root-cause taxonomy (timing-margin and state-leak classes with fixes), stability targets (< 5% suite flaky rate, 100% critical-journey pass), review cadence (weekly; > 2-week quarantine escalates to COMMANDER; 10-run revalidation). Rendered as a labelled table rather than 5 subsection headings — substance complete, format deviation not material |
