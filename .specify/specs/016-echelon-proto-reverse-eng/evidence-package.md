# Evidence Package — Echelon Proto Reverse Engineering (REQ-RE-005)

**Date**: 2026-04-02
**Run ID**: squad-1775164062
**Sources**: synthesis-report.md §2, unknowns.md, proof-status-table.md (015), spec015-verification.md (T-003)
**Constitution compliance**: P-004 (every claim cites evidence), P-005 (NOVEL-004 speculation never presented as proven)

---

## Section 1: Grade A Evidence (AC-005-001)

Peer-reviewed papers with measured results on a directly comparable task.

| Claim | Evidence | Source | Citation |
|-------|----------|--------|----------|
| NS-003-A: Generator-Critic achieves 86%+ schema compliance | NL2GenSym experiment — execution-grounded schema validation on Soar rule generation | Peer-reviewed preprint | arxiv:2510.09355 |
| NS-003-B: AGM belief revision achieves 93.3% contradiction catch accuracy | Kumiho experiment — doxastic logic revision for conversational belief tracking (LoCoMo dataset) | Peer-reviewed preprint | arxiv:2603.17244 |

**Note on scope**: Both NS-003-A and NS-003-B are proven at component level on their original tasks. Echelon-specific proof requires the NS-003 prototype experiment (REQ-015-006, target: ≥0.70 first-pass compliance, ≥0.80 catch rate on Echelon artifact pairs). Status: PARTIAL.

---

## Section 2: Grade B Evidence (AC-005-002)

Implemented code, systematic search records, or peer-reviewed frameworks with weak task match.

| Claim | Evidence | Source |
|-------|----------|--------|
| Endocrine system fully implemented with 6 hormones, phase-gating, and decay | 1047-line bash implementation; all 6 hormones confirmed active; decay rates in squad-config.yml lines 525–531 | scripts/bash/endocrine.sh |
| Belief annotation parser implemented with freshness classification | 547-line Python implementation producing config-belief-graph.json; @belief() annotation parser confirmed | scripts/belief-parser.py |
| NS-003-C: Generator-Critic + AGM belief revision combination has no prior literature | 8-query systematic search across Google Scholar proxy + Semantic Scholar, 2026-04-02; zero papers found combining execution-grounded Generator-Critic with AGM belief revision in multi-agent artifact store context | .specify/specs/015-ca-outcomes-validation/investigation/U-015-002-novelty-search.md (176 lines) |
| 42 agents across 7 tiers — count verified against codebase | `find agents -type f -name "*.md" | wc -l` = 42; tier distribution matches glossary.md exactly | synthesis-report.md §1 "Cross-Document Contradictions: Verified" |
| PAT-006: Deterministic scoring correction — heuristic overconfident 15–29% vs Understanding v3.4.0 | Single squad run observation (squad-1710950401); heuristic passed while deterministic tooling failed on structure/testability | knowledge-base/patterns.yaml PAT-006 (confidence: 0.88, Grade B) |
| GATEKEEPER estimation accuracy improves with calibration data; ≥5 runs needed for calibration | Historical correction factors injected into GATEKEEPER prompt; calibration-profile.yaml documented; N=5 recommended minimum | knowledge-base/calibration-profile.yaml, inter-process-effectiveness.md §Knowledge Base Feedback Loop |
| state.json has 30 documented fields with defined writers and readers | Complete field enumeration table (30 fields) against observed state.json 2026-04-02 | architecture-gaps.md Gap 1 |
| Pre-dispatch constitutional gate implemented (FLAG/CONSULT/BLOCK) | scripts/bash/pre-dispatch-gate.sh; COMMANDER dispatch flow documented; NEVER rules per tier in agent .md files | architecture-gaps.md Gap 2; agents/control/commander.md |

---

## Section 3: Grade C Evidence — SPECULATION (AC-005-003)

No direct measurement exists. Per P-005, these claims must never be presented as proven.

| Claim | Status | Why Grade C | Upgrade Path |
|-------|--------|-------------|-------------|
| 40–70% token reduction for repeated codebases (NOVEL-004) | SPECULATION (P-005) — proof-status-table.md row 5: "SPECULATION: no empirical grounding" | No measurement; no prototype run; token counters not instrumented | N≥50 instrumented runs with token-logger.py; break-even analysis vs prediction-generation overhead; minimum to upgrade label |
| Endocrine system measurably improves output quality (A-005) | UNVALIDATED (U-005) | No controlled experiment run; effect size unknown (could be 0% or 20%) | N=10 BANZAI runs with hormones active vs frozen baseline; measure Understanding metrics, consistency, token efficiency |
| SAGE quality gates correlate with implementation quality (A-009) | UNVALIDATED (U-003) | No human expert calibration done; correlation between high Understanding score and fewer bugs not measured | N=20 specs (N=10 high Understanding, N=10 low); measure implementation quality; success = ≥30% fewer bugs in high-Understanding specs |
| Contradiction scanner catches ≥60% of real contradictions (A-006) | UNVALIDATED (U-006) | Precision/recall unknown; 3 heuristics may have high false negative rate | Benchmark on labeled dataset N=20+ pairs with ground truth; target precision ≥0.70, recall ≥0.60 |
| NOVEL-004 mechanism (upstream prediction gating reduces dispatch cost) | NOT PROVEN (P3) — proof-status-table.md row 4 | Structural analog to Speculative Decoding (arxiv:2211.17192); no agent-level measurement; no prototype | Prototype: N=10+ Echelon runs; measure prediction accuracy ≥40% (break-even); net token reduction > prediction overhead |

---

## Section 4: Proof-Status-Table as Authoritative Registry (AC-005-005)

**Location**: `.specify/specs/015-ca-outcomes-validation/proof-status-table.md`
**Produced by**: ARCHITECT (HOW), run squad-1775154996, 2026-04-02
**Verified by**: spec015-verification.md (T-003), build-1775167332

### Structure

The table contains 17 rows organized as follows:

| Row Range | Content | Proof Category |
|-----------|---------|---------------|
| Rows 1–2 | NS-003-A (Generator-Critic 86%+) and NS-003-B (AGM 93.3%) | P1 — Proven by paper (Grade A empirical support) |
| Row 3 | NS-003-C — novelty of combination confirmed via systematic search | P2 — Proven by design / systematic search |
| Rows 4–5 | NOVEL-004 mechanism (P3: NOT PROVEN) and NOVEL-004 40–70% token reduction (P5: SPECULATION) | P3 / P5 — Requires prototype / Speculation |
| Rows 6–10 | CA Overlays: Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory | P4 — GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) |
| Rows 11–17 | Use case assertions: AC-3 constraint propagation, contradiction detection, token reduction use cases, CA overlay use cases | P2 / P4 / P5 |

### Key Status Values

- **Rows 1–2**: PROVEN (component level, NL2GenSym / Kumiho) / PARTIAL (Echelon-specific) — dual status per AC-001-005
- **Row 3**: NOVELTY CONFIRMED as of 2026-04-02 systematic search (U-015-002) — boundary: "no prior work found in reviewed corpus," not a universal no-existence claim
- **Rows 5 and 13**: SPECULATION: no empirical grounding — verbatim per P-005, not softened
- **Rows 6–10**: GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) — all five CA overlays; constitution P-006 compliant
- **Rows 14–17**: GATE-CONDITIONED on U-CA-004 — CA overlay use case rows also blocked

---

## Section 5: Spec 015 Build State (AC-005-006)

Source: spec015-verification.md (T-003), build-1775167332; progress-report.md build-1775162749.

| Item | Value |
|------|-------|
| Primary build run | build-1775154996 |
| Validation run | build-1775162749 |
| Tasks completed | 12/12 — all task artifacts present (Engineering Manager sign-off) |
| Code tests | 9/9 token-logger, 21/21 contradiction-scanner — PASS |
| CA overlay gate violations | Zero detected |
| Unauthorized CA overlay code | None detected |
| Engineering Manager verdict | READY_WITH_CONDITIONS |
| Open conditions (all non-blocking) | CONDITION-001: test-quality-report.md empty; CONDITION-002: AC-003-002 PENDING (<3 instrumented runs); CONDITION-003: progress-report.md sparse; CONDITION-004: ISS-002 through ISS-005 open |
| Coverage | 12/12 task artifact presence constitutes measurable completion indicator; explicit percentage not stated in retrieved artifacts |

**Constitution compliance verified** (spec015-verification.md):
- P-005: NOVEL-004 SPECULATION label present verbatim in rows 5 and 13
- P-006: CA overlays GATE-CONDITIONED with U-015-001 blocking reference in rows 6–10 and 14–17
- P-019: NS-003 NOVELTY CONFIRMED (row 3) via U-015-002 systematic search

---

## Section 6: Blocking Unknowns (AC-005-008)

Source: unknowns.md, proof-status-table.md rows 6–10, synthesis-report.md §2 Genuine Risks.

| ID | Description | What It Blocks | Resolution Criteria |
|----|-------------|---------------|---------------------|
| U-CA-004 | CA overlay gate experiment not run — does cognitive architecture outperform expert prompts on Echelon tasks? | 5 CA overlays (rows 6–10) + 4 use case rows (14–17) — all 9 rows remain GATE-CONDITIONED | AQS(CA) > AQS(baseline) + 10 pp, p < 0.05, N≥20 codebases per condition (u-ca-004-experiment-spec.md) |
| U-008 | NS-003 prototype not built — NL2GenSym (86%) and Kumiho (93.3%) component proofs may not transfer to Echelon artifact store | NS-003 proof upgrade from PARTIAL to PROVEN (Echelon-specific); PRIMARY architecture validity | First-pass compliance ≥0.70 on Echelon artifact protocol schema (N=30 agent invocations); contradiction catch rate ≥0.80, FP rate ≤0.20 on N=20 labeled artifact pairs (REQ-015-006) |
| U-003 | SAGE quality gate not calibrated against human expert judgment | Quality gate validity claim; "SAGE gates are effective" remains assumption A-009 UNVALIDATED | Cohen's κ ≥0.60 between SAGE Understanding scores and human expert quality ratings across N=20 specs; N=10 high Understanding → measure implementation bug rate |
| U-005 | Endocrine system efficacy not measured | Endocrine patent claim (Claim B in synthesis-report.md §3); complexity justified only if effect > 0 | N=10 BANZAI runs with hormones active vs frozen baseline; measure Understanding metrics, consistency, token efficiency; hypothesis: BANZAI ≥ baseline on ≥2 of 3 metrics |

**Blocking unknowns per unknowns.md summary table**: U-007 (U-CA-004 resolution) and U-008 (NS-003 transfer) must both resolve before Echelon can be considered production-ready. Both are addressed by experiments in spec 015.
