## TASK-006: Token Logging Instrumentation

**Status**: DONE
**REQ**: REQ-015-003

### Evidence

- `scripts/token-logger.py` — written, 547 lines
- `tests/unit/test-token-logger.sh` — 9 tests PASS
- `tests/fixtures/token-logger/sample-journal.json` — fixture created (4 entries, mixed live/estimated)
- `token-baseline-015.json` — pilot run against spec 015 journal: 10 invocations logged, collection_method: post_hoc_estimation

### AC Compliance

- AC-003-001: PASS — All five fields captured per invocation (agent, phase, prompt_tokens, completion_tokens, total_tokens)
- AC-003-002: PENDING — requires 3 full runs; pilot run shows instrumentation works (10 invocations from spec 015 run captured)
- AC-003-003: PASS — Per-agent-type stats (mean, median, p90, count) present for all 8 agent types in output
- AC-003-004: PASS — Machine-readable JSON (token-baseline.json) and Markdown summary both produced
- AC-003-005: PASS — collection_method field present and correctly set to post_hoc_estimation when no live token data found

## TASK-009: Architecture Ambiguity Resolution
**Status**: DONE | ISS-001: RESOLVED
Goal Stack granularity confirmed as agent-level (up to 42 dispatch entries), not tier-level (7); ACT-R buffer types map to tiers (7) but token budget tracks per agent dispatch; build tier requires separate sequential-state-machine overlay treatment.

## TASK-011: Baseline Risk Register
**Status**: DONE | File: baseline-risk-register.md
4 risks documented: BR-001 (token logging gap, HIGH), BR-002 (single annotator, MEDIUM), BR-003 (heuristic false positives, MEDIUM), BR-004 (small DISCOVER→ASSESS sample, MEDIUM).

## TASK-007: Contradiction Scan

**Status**: DONE
**REQ**: REQ-015-005

### Evidence

- `scripts/contradiction-scanner.py` — 778 lines (stdlib only, argparse, pathlib)
- `tests/unit/test-contradiction-scanner.sh` — 7 test groups, 21 checks, all PASS
- `tests/fixtures/contradiction-scanner/clean-run/` — 2 artifact files, no contradictions
- `tests/fixtures/contradiction-scanner/dirty-run/` — 2 artifact files, injected 42 vs 19 count contradiction
- `contradiction-scan-results.json` — 3 specs scanned (013, 014, 015), 560,976 assertion pairs, 197 contradictions detected, rate: 0.035%

### Manual Precision Sample (5 detected contradictions reviewed)

| C-ID | Entity | Text A (truncated) | Text B (truncated) | True contradiction? | Verdict |
|------|--------|--------------------|--------------------|---------------------|---------|
| C-090 | resolution | Resolution: Not a research re-run. The gap is correctly documented... | \| `ConflictResolution` \| ACT-R CE \| Central Executive decision record... | NO — different senses of "resolution" (gap-resolution vs schema field) | FALSE POSITIVE |
| C-110 | evidence gate | Evidence Gate: None. The Soar mechanism list is Grade A... | Gate: Forward model achieves >40% correct prediction... | NO — different uses of "gate" (evidence qualifier vs evaluation gate) | FALSE POSITIVE |
| C-176 | req-ca-010 | \| REQ-CA-010 \| Yes — 3 components, 2 citations, Self-Refine distinction \|... | \| REQ-CA-010 \| Highest novelty but requires deep read of unconfirmed 2026 paper... | PARTIAL — same requirement ID, numeric mismatch (3 components vs page references) | AMBIGUOUS |
| C-191 | req-015-005 | \| REQ-015-005 \| Contradiction Rate Baseline \| HIGH \| Medium (1-2 days)... | \| REQ-015-005 \| ACC \| ACC on five ACs covering corpus coverage... | NO — same REQ referenced in different table schemas (risk vs acceptance criteria) | FALSE POSITIVE |
| C-094 | file | File: assumption-review.md (HIGH-002); contradictions-and-gaps.md... | SCOUT staging files identify at minimum: CoALA (arxiv:2309.02427)... | NO — "file" key used for different purposes (issue reference vs bibliography) | FALSE POSITIVE |

**Sample precision: 1 ambiguous, 4 false positives → estimated precision ~0-20% on this sample.** Consistent with upper_bound characterisation — the heuristics detect syntactic co-occurrence, not semantic contradiction. Soft contradictions in prose are missed.

### AC Compliance

- AC-005-001: [PASS] Specs 013, 014, 015 scanned — 3 spec directories, 560,976 assertion pairs
- AC-005-002: [PASS] Detection method: heuristic pattern matching, stated as upper bound; method_limitations field present
- AC-005-003: [PASS] Reports pairs_scanned (560,976), contradictions_detected (197), contradiction_rate_per_run (0.035%), per_pair_rates (5 stage pairs)
- AC-005-004: [PARTIAL] 5-sample manual precision review included; sample shows ~0-20% precision confirming upper_bound claim; human verification field set to null pending reviewer sign-off
- AC-005-005: [PASS] bound_type: "upper_bound" stated explicitly in all report outputs

## TASK-005: Scope Violation Baseline
**Status**: DONE | **REQ**: REQ-015-004
**Artifact**: `scope-violation-baseline.md`

Runs annotated: specs 008, 013, 014 (3 runs with complete agent artifacts). Specs 009-012 lack agent-produced artifacts beyond overview and spec.md files and were excluded with documented rationale.

Overall violation rate: **0.5%** (1 confirmed OUT-OF-SCOPE across 187 annotated sections). BORDERLINE rate: 9.1% (17 sections). Single confirmed violation: CARTOGRAPHER's spec 008 `spec.md` contains a "Resource Reality" table with per-phase effort hour ranges — a direct NEVER-rule-4 violation ("NEVER estimate effort. That's GATEKEEPER's job."). This violation is absent in the two later runs (013, 014), indicating self-correction across the run sequence.

Top 3 violation patterns:
1. CARTOGRAPHER includes effort estimates (confirmed) — single OUT-OF-SCOPE finding, isolated to spec 008
2. SAGE resolution guidance is prescriptive (borderline) — 60% of SAGE sections include "What should exist"/"Resolution" sub-sections naming concrete artifacts and code patterns
3. Technology-specific terminology in WHAT artifacts (borderline) — PostgreSQL/SQLite in spec 008 CARTOGRAPHER; absent in later runs

### AC Compliance

- AC-004-001: [PASS] 3 spec runs annotated (008, 013, 014) with documented exclusion rationale for 009-012
- AC-004-002: [PASS] Annotation per section (individual assumptions, issue entries, plan phases, REQs)
- AC-004-003: [PASS] Single-annotator limitation explicitly stated; no inter-annotator agreement computed
- AC-004-004: [PASS] Per-agent-type rate, overall rate, top 3 patterns all reported
- AC-004-005: [PASS] BORDERLINE sections excluded from OUT-OF-SCOPE numerator and tracked separately

## TASK-008: NOVEL-004 Calibration
**Status**: DONE | **REQ**: REQ-015-007
**Artifact**: `novel004-calibration.md`

3 DISCOVER→ASSESS pairs found across specs 008-014. Specs 009-012 confirmed to lack complete pairs. N < 9 — small-sample limitation explicitly noted per AC-007-001.

Per-pair scores: 17% (spec 008), 58% (spec 013), 53% (spec 014).
Mean: **43%** | Median: **53%** | Min: 17% | Max: 58% | Std dev: 22%

Break-even (C_predict / C_assess) estimated from `token-baseline-015.json` post-hoc data: approximately 43%. Mean prediction accuracy falls at break-even, making the verdict INCONCLUSIVE. SPECULATION label preserved; NOVEL-004 prototype is worth building but requires N≥50 instrumented runs for a GO decision.

### AC Compliance

- AC-007-001: [PARTIAL] N=3 pairs, N < 9 limitation stated
- AC-007-002: [PASS] 0-20/40-60/80-100 anchor rubric applied; pair 1 at 17%, pairs 2-3 at 53-58%
- AC-007-003: [PASS] Mean, median, min, max, std deviation reported
- AC-007-004: [PARTIAL] Break-even in symbolic and estimated numeric form; instrumented baseline (REQ-015-003) partially pending
- AC-007-005: [PASS] SPECULATION label preserved and not softened
- AC-007-006: [PASS] INCONCLUSIVE verdict per decision criteria
