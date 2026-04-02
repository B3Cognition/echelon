# NOVEL-004 Prediction Accuracy Calibration — Spec 015
**Task**: TASK-008 | **Date**: 2026-04-02
**REQ**: REQ-015-007

---

## Available Pairs

3 pairs found (DISCOVER→ASSESS adjacent) across specs 008, 013, 014.

N < 9 — small-sample limitation applies per AC-007-001. Results are indicative only; no statistically robust conclusions can be drawn from N=3. All aggregate statistics are reported for protocol compliance but must be treated as directional signals, not confirmed measurements.

Specs 009, 010, 011, 012 were inspected and confirmed to lack either DISCOVER artifacts (glossary.md or assumptions.md) or ASSESS artifacts (feasibility.md), or both. These runs appear to be partial or abbreviated — only a 00-overview.md and spec.md are present in those directories.

---

## Scoring Protocol

For each pair, the DISCOVER artifact (assumptions.md in all three cases) is read first, then the ASSESS artifact (feasibility.md). Each major assertion or decision in feasibility.md is evaluated:

- **Predictable from DISCOVER**: The assertion is explicitly stated in assumptions.md, OR it is a direct logical consequence of an explicitly stated DISCOVER finding (one inferential step, no novel information required).
- **Not predictable from DISCOVER**: The assertion requires GATEKEEPER to introduce new information, domain expertise, or reasoning that was absent from DISCOVER output.
- **Borderline**: The assertion could be loosely inferred from DISCOVER but requires multiple inferential steps or relies on implicit background knowledge not stated in assumptions.md.

Score = (Predictable assertions) / (Total assertions in feasibility.md)

"Assertions" are counted at the level of named conclusions or verdicts in feasibility.md — each per-dimension verdict, each kill-gate conclusion, each risk flag, each scoping recommendation.

---

## Per-Pair Scores

### Pair 1: Spec 008 (`008-cognitive-squad-2year-vision`)

**DISCOVER artifact**: assumptions.md (10 assumptions, A-001–A-010)
**ASSESS artifact**: feasibility.md (3 phases × 3 dimensions + RICE scores + kill signals = 18 major assertion groups)

**Scoring**:

| ASSESS assertion | Predictable from DISCOVER? | Notes |
|---|---|---|
| Phase 1 technical feasibility: 5/5 — GitHub Action is straightforward | BORDERLINE | A-001 (LLM costs) and A-003 (deterministic tooling) support tooling viability, but GitHub Action packaging is GATEKEEPER domain knowledge |
| Phase 1 resource feasibility: 5/5 — solo achievable in 2 weeks | NOT PREDICTABLE | assumptions.md has no solo-capacity assumptions; A-009 discusses feedback loops, not build effort |
| Phase 1 time estimate: 20h (~2-3 weeks) | NOT PREDICTABLE | No hours data in assumptions.md |
| Phase 1 RICE = 8.10 | NOT PREDICTABLE | RICE formula application is GATEKEEPER's tool, not derived from DISCOVER |
| Phase 1 kill signal (fewer than 3 external installs) | PREDICTABLE | A-010 (ecosystem adoption) directly supports this kill criterion |
| Phase 2 technical feasibility: 3/5 — webhook, Jira integration complexity | BORDERLINE | A-004 (convergence), A-007 (endocrine) indirectly suggest complexity but don't predict specific integration challenges |
| Phase 2 resource: 3/5 — stretched solo | NOT PREDICTABLE | A-009 mentions feedback loop dependence, not solo capacity |
| Phase 2 time: 94-124h | NOT PREDICTABLE | No hours in DISCOVER |
| Phase 2 kill signal (correction factors oscillate) | PREDICTABLE | A-004 directly states: "If wrong: correction factors oscillate indefinitely and the system never develops reliable estimates" |
| Phase 2 RICE = 1.47 | NOT PREDICTABLE | RICE computation |
| Phase 3 technical: 3/5 — A/B testing, build phase complexity | BORDERLINE | A-007 (endocrine confidence 0.40) supports speculative feasibility, but A/B framework details are not predictable |
| Phase 3 solo: 2/5 — at limit of solo | NOT PREDICTABLE | |
| Phase 3 time: 60-100h | NOT PREDICTABLE | |
| Phase 3 RICE / kill signal | BORDERLINE | A-007 (confidence 0.40) supports endocrine-related kill criterion |
| Phase 4/5 "NO" solo verdict | PREDICTABLE | A-005 (42 agents overspecification, confidence 0.55), A-010 (ecosystem) both suggest scaling issues |
| Overall "Total to Phase 3: ~200-280h" | NOT PREDICTABLE | |
| RICE scores and prioritization ordering | NOT PREDICTABLE | |
| Kill criteria specificity (numeric thresholds) | NOT PREDICTABLE | |

Predictable: 3 | BORDERLINE (excluded from numerator): 4 | Not predictable: 11

**Prediction accuracy: 3/18 = 17%** (excluding borderline from numerator and denominator; borderline counted separately)

Alternatively, with borderline counted as 0.5 partial: (3 + 2) / 18 = 28%. Reporting strict count (17%) per protocol.

---

### Pair 2: Spec 013 (`013-echelon-slm-replacement-feasibility`)

**DISCOVER artifact**: assumptions.md (13 assumptions, A-001–A-013)
**ASSESS artifact**: feasibility.md (3 dimensions + kill gate + 4 flags = 12 major assertion groups)

**Scoring**:

| ASSESS assertion | Predictable from DISCOVER? | Notes |
|---|---|---|
| Technical dim: FEASIBLE_WITH_RISKS | PREDICTABLE | A-001 (unvalidated, risk if wrong), A-004 (FRAGILE), A-002 (primary bottleneck) all directly imply risks-present conclusion |
| Risk 1: U-001 may resolve negatively, closes Q1 track | PREDICTABLE | A-001 explicitly states: "Risk if wrong: SLM replacements produce lower-quality outputs... Quality gates may pass artifacts SAGE would have blocked" |
| Risk 2: REQ-S-001 constitution compliance is UNSOLVED | PREDICTABLE | A-004 explicitly states constitution enforcement cannot rely on fine-tuning alone; flagged FRAGILE |
| Risk 3: U-014 access dependency (Understanding CLI source) | NOT PREDICTABLE | Nothing in assumptions.md anticipates this access barrier |
| Resource dim: FEASIBLE_WITH_RISKS | PREDICTABLE | A-005 (cost motivation) + inference hardware needs are logically implied by A-001/A-003 |
| Hardware: 16-24 GB VRAM for 7B inference | NOT PREDICTABLE | DISCOVER identifies SLMs as the domain but doesn't specify hardware requirements |
| Hardware risk: CPU inference is slow but not infeasible | NOT PREDICTABLE | |
| Data requirements: API access assumed available | BORDERLINE | A-005 (API billing motivation) implies API access, but "access assumed" is a specific ASSESS decision |
| Domain dim: FEASIBLE | PREDICTABLE | A-001's "narrow, well-defined functions" framing and the two-track structure (Q1/Q2) are both derived directly from DISCOVER |
| Q1/Q2 two-track structure as correct research framing | PREDICTABLE | The Q1 (off-the-shelf) / Q2 (fine-tuned) distinction is a direct consequence of A-001 (whether fine-tuning is needed) and A-003 (whether distillation data is sufficient) |
| Kill gate PASS | PREDICTABLE | Given all three dimensions are FEASIBLE/FEASIBLE_WITH_RISKS, and DISCOVER flagged no show-stopper unknowns, PASS is logically derivable |
| Four critical flags for INVESTIGATOR | NOT PREDICTABLE | ROOT BLOCKER ordering, access verification, hardware baseline — these are GATEKEEPER judgment calls |

Predictable: 7 | BORDERLINE: 1 | Not predictable: 4

**Prediction accuracy: 7/12 = 58%** (borderline excluded)

---

### Pair 3: Spec 014 (`014-cognitive-architecture-llm-framing`)

**DISCOVER artifact**: assumptions.md (12 assumptions across Categories A-D)
**ASSESS artifact**: feasibility.md (13 per-REQ verdicts + overall kill gate + confidence ratings = 15 major assertion groups)

**Scoring**:

| ASSESS assertion | Predictable from DISCOVER? | Notes |
|---|---|---|
| REQ-CA-001 (CA survey): PASS | PREDICTABLE | A-001 (LLM-as-production-system) is validated in DISCOVER; five CA families exist in literature — ASSESS confirms feasibility of literature survey |
| REQ-CA-002 (Soar matrix): PASS with "partial" classification judgment caveat | PREDICTABLE | A-004 (NL2GenSym, 86%+ success) confirms Soar engagement is tractable; matrix is classification task |
| REQ-CA-003 (token comparison): PASS, "none found" is valid output | PREDICTABLE | B-001 (B-001 explicitly states no CA-specific token measurement exists) — ASSESS conclusion is a direct consequence |
| REQ-CA-004 (Sun metaphor): PASS, lowest risk | BORDERLINE | A-001/C-001 suggest the metaphor framing is warranted, but lowest-risk assessment requires GATEKEEPER judgment on deliverable complexity |
| REQ-CA-005 (goal stack design): PASS with caveat on U-CA-016 | PREDICTABLE | B-002 (routing failures from lack of goal-state tracking) is exactly the motivation; caveat traces to U-CA-016 which appears in DISCOVER unknowns |
| REQ-CA-006 (ACT-R buffer): PASS, API-level only | PREDICTABLE | A-002 (LLMs have addressable structured memory) + explicit statement that LLM-ACTR is blocked (residual stream access) — both in DISCOVER |
| REQ-CA-007 (LIDA codelet): PASS, 42-agent table is high effort | NOT PREDICTABLE | DISCOVER does not characterize relative effort of deliverables |
| REQ-CA-008 (GWT broadcast): PASS with worked example dependency | BORDERLINE | B-004 (artifact protocol compatible with CA memory) supports feasibility; "worked example requires artifact access" is GATEKEEPER's scope check |
| REQ-CA-009 (episodic memory): PASS, RAG-based | PREDICTABLE | A-005 (Echelon is stateless, no episodic memory) directly implies RAG retrieval as the solution path |
| REQ-CA-010 (NS-003 Generator-Critic): CONDITIONAL PASS on arxiv:2603.17244 | NOT PREDICTABLE | The paper-verification dependency is not predictable from DISCOVER assumptions |
| REQ-CA-011 (study design): PASS, highest research value | PREDICTABLE | D-003 (CA vs expert prompt engineering, Grade D) directly motivates the 3-condition experiment; A-003 (frontier LLM CA benefit may be marginal) supports study design necessity |
| REQ-CA-012 (novelty assessment): PASS with retrieval dependency | BORDERLINE | Novelty assessment need is implied by B-001/B-002/C-001 (all speculative), but specific retrieval access risk is GATEKEEPER domain knowledge |
| REQ-CA-013 (missing 9 roadmap): PASS | PREDICTABLE | B-003 (Soar operator mapping) and B-002 (gap in goal-state) point toward mechanism gap analysis; H/M/L relative ordering is tractable |
| Overall kill gate: NOT KILLED, PASS | PREDICTABLE | Given majority of REQs are PASS and no show-stopper unknowns in DISCOVER, kill gate PASS is derivable |
| Confidence ratings (8/10 overall, 6/10 positive finding) | NOT PREDICTABLE | Numeric confidence is GATEKEEPER's calibrated judgment, not derivable from DISCOVER |

Predictable: 8 | BORDERLINE: 3 | Not predictable: 4

**Prediction accuracy: 8/15 = 53%** (borderline excluded)

---

## Aggregate Statistics

- N: 3 (small-sample limitation applies — AC-007-001)
- Scores: 17%, 58%, 53%
- Mean: **43%**
- Median: **53%**
- Min / Max: **17%** / **58%**
- Std deviation: **22%** (approximate; sample std dev)

Note: std deviation of 22% exceeds the 30% GO threshold — technically this is a RISK signal for the GO criteria, though the mean is below break-even making the GO/NO-GO determination moot from the mean alone.

---

## Break-Even Computation

Break-even accuracy = (token cost of one prediction call) / (token cost of one full ASSESS call)

Break-even = C_predict / C_assess

From `token-baseline-015.json` (10 invocations, `collection_method: post_hoc_estimation`, `estimated: true`):

- C_assess (GATEKEEPER/ASSESS invocation): **152 tokens** (total, single invocation, spec 015 run)
- C_predict (DISCOVER prediction call): Not separately instrumented. SCOUT costs 218 tokens total in the spec 015 run, which includes all DISCOVER output — not just the prediction-relevant prediction generation step. If the prediction step is modeled as a fraction of SCOUT output generation (~30%), C_predict ≈ 65 tokens.

Symbolic form: Break-even = C_predict / C_assess = 65 / 152 ≈ **43%**

**Important caveat**: Both values are post-hoc estimates from a single run with `estimated: true` flag. These are not instrumented measurements. REQ-015-003 (token baseline, 3-run instrumented series) is partially complete (AC-003-002 pending). The break-even computation is therefore approximate. The 43% figure happens to lie very close to the observed mean prediction accuracy (43%), which makes the GO/NO-GO determination genuinely inconclusive.

---

## SPECULATION Label (mandatory)

> **SPECULATION**: The 40-70% token reduction claim for NOVEL-004 is labeled SPECULATION. This label is NOT removed or softened based on this retrospective calibration alone. Upgrading requires N=50+ prototype measurement runs with instrumented token counters. The current N=3 retrospective calibration, with post-hoc token estimates and a single-annotator scoring pass, does not constitute the instrumented evidence needed to confirm or refute this claim. The mean prediction accuracy of 43% is consistent with break-even but cannot be treated as confirming break-even performance.

---

## Go/No-Go Recommendation

Per AC-007-006:
- GO if mean ≥ break-even AND std < 30%
- NO-GO if mean < break-even
- INCONCLUSIVE if mean within 10pp of break-even OR std ≥ 30%

Evaluation:
- Mean (43%) is approximately equal to break-even estimate (43%) — within 10pp (delta = 0pp)
- Std deviation (22%) is below 30% threshold
- However, break-even itself is estimated from post-hoc data — the symbolic 43% is not a measured value

**Recommendation**: **INCONCLUSIVE** — The observed mean prediction accuracy (43%) lies at the estimated break-even point (43%), but both values are approximate: mean from N=3 pairs scored by a single annotator, break-even from a single post-hoc estimated run. The INCONCLUSIVE verdict reflects the combination of (a) small sample, (b) approximated break-even, and (c) high variance driven by spec 008 (17%), which appears to be an earlier-style run with less structured DISCOVER output than specs 013-014. The NOVEL-004 prototype is worth building but must be evaluated against N≥50 instrumented runs before a GO decision.

---

## AC Compliance

- AC-007-001: [PARTIAL] 3 pairs evaluated. N < 9 — small-sample limitation explicitly stated throughout. All 7 candidate specs (008-014) were checked; only 3 have complete DISCOVER→ASSESS pairs.
- AC-007-002: [PASS] Scoring applied per AC-007-002 rubric with 0-20/40-60/80-100 anchors. Pair 1 falls in the 0-20 band (17%), Pair 2 falls in the 40-60 band (58%), Pair 3 falls in the 40-60 band (53%).
- AC-007-003: [PASS] Mean (43%), median (53%), min (17%), max (58%), std deviation (22%) all reported.
- AC-007-004: [PARTIAL] Break-even computed symbolically (C_predict / C_assess) and numerically from post-hoc estimates (43%). REQ-015-003 instrumented baseline is partially complete; full 3-run instrumentation pending.
- AC-007-005: [PASS] SPECULATION label preserved and not softened.
- AC-007-006: [PASS] INCONCLUSIVE verdict per decision criteria with explicit rationale.
