# Tasks — echelon-proto Reverse Engineering Analysis

**Run ID**: squad-1775164062
**Total Tasks**: 11
**Date**: 2026-04-02
**Coverage Baseline**: 84.2% → Target 97.4% after completion

---

## Phase 1: Foundation (T-001 to T-003)

### T-001: Consolidate Staging Artifacts into Spec Directory

**Phase**: Foundation
**Description**: Verify all 18 staging artifacts are complete and catalogued. Establish cross-references. Link investigation/ specialist reports.
**Acceptance Criteria**:
- [ ] All 18 staging artifacts present and non-empty
- [ ] investigation/ subdirectory accessible with INV-001, INV-002, INV-003
- [ ] constitution.md verified at .specify/memory/constitution.md
- [ ] P-007 pre-dispatch gate logic documented
**Dependencies**: None
**Estimated Effort**: LOW (0.5h)

### T-002: Integrate Specialist Findings

**Phase**: Foundation
**Description**: Incorporate INVESTIGATOR findings (INV-001 endocrine challenge, INV-003 NS-003 confirmation) into novelty-catalogue.md evidence sections. Incorporate ORACLE and MAVERICK outputs when available.
**Acceptance Criteria**:
- [ ] INV-001 endocrine challenge findings cross-referenced in NOVEL-001 section
- [ ] INV-003 NS-003 confirmation findings cross-referenced in NOVEL-003 section
- [ ] patent-analysis.md and maverick-report.md incorporated if present
- [ ] All evidence grades (A/B/C) assigned per SCOUT taxonomy
**Dependencies**: T-001
**Estimated Effort**: LOW (0.5h)

### T-003: Verify Spec 015 Cross-References

**Phase**: Foundation
**Description**: Confirm spec 015 artifacts (proof-status-table.md, U-015-002, ns003-experiment-design.md) exist and match novelty-catalogue.md claims.
**Acceptance Criteria**:
- [ ] proof-status-table.md rows 1-10 verified (NS-003 rows 1-5, CA overlay rows 6-10)
- [ ] U-015-002-novelty-search.md confirmed with zero prior literature finding
- [ ] Spec 015 build state documented: 12/12 tasks, 79% coverage, PASS_WITH_CONDITIONS
- [ ] NS-003 novelty confirmation verified from systematic search record
**Dependencies**: T-001, T-002
**Estimated Effort**: LOW (0.5h)

---

## Phase 2: Analysis Assembly (T-004 to T-008)

### T-004: Produce Final Architecture Report (REQ-RE-001)

**Phase**: Assembly
**Description**: Synthesize all agent and tier documentation into a comprehensive architecture report. Fill NEEDS_WORK gaps (AC-001-003 state.json fields, AC-001-006 tier boundary enforcement).
**Acceptance Criteria**:
- [ ] AC-001-001: 42 agents listed in table (Tier | Codename | Functional Name | Key Artifact)
- [ ] AC-001-002: 7 tiers with data ownership and phase assignments
- [ ] AC-001-003: state.json spine documented — all 30 fields (type, purpose, writer, readers)
- [ ] AC-001-004: Phase sequencing documented (DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN)
- [ ] AC-001-005: Data flow diagram showing artifact handoffs between phases
- [ ] AC-001-006: Tier boundary enforcement rules — NEVER rules per tier, pre-dispatch gate logic
**Dependencies**: T-001, T-002, T-003
**Estimated Effort**: MEDIUM (1.5h)
**Files**: architecture-gaps.md (state.json + NEVER rules), glossary.md, mental-model.md, boundaries.md

### T-005: Finalize Novelty Catalogue (REQ-RE-002)

**Phase**: Assembly
**Description**: Verify all 12 novelty mechanisms have complete evidence grades, proof criteria, and P-004/P-005/P-006 compliance. Integrate INVESTIGATOR findings.
**Acceptance Criteria**:
- [ ] AC-002-001: All 12 mechanisms catalogued with complete sections
- [ ] AC-002-002: Prior art differential for each mechanism (vs. LangChain, AutoGen, CrewAI)
- [ ] AC-002-003: Code evidence with file:line for every mechanism
- [ ] AC-002-004: Defensibility ratings with justification
- [ ] AC-002-005: "What would constitute full proof" — concrete criteria per mechanism
- [ ] AC-002-006: HIGH mechanisms (NOVEL-001, NOVEL-003, NOVEL-006) have 2+ evidence paragraphs
- [ ] AC-002-007: NS-003 novelty confirmed via U-015-002 systematic search
- [ ] AC-002-008: Evidence grades assigned (A/B/C)
- [ ] AC-002-009: P-004 compliance — every claim cites evidence
- [ ] AC-002-010: P-005 compliance — NOVEL-004 labeled SPECULATION (no N≥50 measurement)
**Dependencies**: T-001, T-002, T-003
**Estimated Effort**: MEDIUM (1.5h)

### T-006: Produce Patent Analysis Report (REQ-RE-003)

**Phase**: Assembly
**Description**: Finalize IP priority matrix, draft narrow defensible claim abstracts for HIGH/MEDIUM mechanisms. Integrate ORACLE findings.
**Acceptance Criteria**:
- [ ] AC-003-001: Mechanisms ranked into HIGH/MEDIUM/LOW tiers
- [ ] AC-003-002: HIGH mechanisms — one-sentence patent abstracts (CLAIM + CLAIM BODY + NON-OBVIOUS ELEMENT)
- [ ] AC-003-003: MEDIUM mechanisms — claim abstracts with "Weakest Point" analysis
- [ ] AC-003-004: LOW mechanisms — explicitly not recommended for filing with rationale
- [ ] AC-003-005: IS-001 resolved — constitution.md exists, P-007 gate logic documented
- [ ] AC-003-006: NS-003 novelty confirmed from U-015-002 search
- [ ] AC-003-007: Each claim has "Obviousness Risk" per Graham v John Deere standards
- [ ] AC-003-008: Priority matrix (FILE IMMEDIATELY | FILE AFTER VALIDATION | FILE AFTER PROTOTYPE | DO NOT FILE)
**Dependencies**: T-001, T-002, T-003, T-005
**Estimated Effort**: MEDIUM (1.5h)

### T-007: Finalize Inter-Process Effectiveness (REQ-RE-004)

**Phase**: Assembly
**Description**: Fill all PARTIAL effectiveness gaps using architecture-gaps.md content. Produce complete 8-phase assessment with bottleneck mitigations.
**Acceptance Criteria**:
- [ ] AC-004-001: All 8 phases assessed
- [ ] AC-004-002: Phase entry/exit conditions table (8 phases × 4 columns)
- [ ] AC-004-003: Bottleneck severity ratings (CRITICAL/HIGH/MEDIUM) per phase
- [ ] AC-004-004: Mitigation strategy per HIGH+ bottleneck
- [ ] AC-004-005: Token efficiency analysis with BANZAI tier allocation percentages
- [ ] AC-004-006: Endocrine feedback loops with decay rates and circuit breakers
- [ ] AC-004-007: Quality gate effectiveness with "(est.)" notation per IS-003
- [ ] AC-004-008: PAT-001 through PAT-006 with confidence scores (0.79-0.88)
- [ ] AC-004-009: Critical path — BUILD phase = 37-42% of total pipeline time (est.)
- [ ] AC-004-010: state.json corruption risks (5 risks) + mitigations from architecture-gaps.md
**Dependencies**: T-001, T-002, T-003
**Estimated Effort**: MEDIUM (2h)
**Files**: architecture-gaps.md (phase table, corruption risks), inter-process-effectiveness.md, squad-config.yml

### T-008: Compile Evidence Package (REQ-RE-005)

**Phase**: Assembly
**Description**: Assemble Grade A/B/C evidence inventory, cross-reference spec 015 proof topology, document blocking unknowns.
**Acceptance Criteria**:
- [ ] AC-005-001: Grade A evidence cited (NL2GenSym 86%+, Kumiho 93.3%, arxiv:2510.09355, arxiv:2603.17244)
- [ ] AC-005-002: Grade B evidence identified (endocrine design, contradiction scanner, RADAR, 7-tier separation)
- [ ] AC-005-003: Grade C evidence identified (token reduction SPECULATION per P-005)
- [ ] AC-005-004: U-015-002 search record verified in spec 015
- [ ] AC-005-005: proof-status-table.md documented as authoritative claim registry
- [ ] AC-005-006: Spec 015 build state — 12/12, 79%, PASS_WITH_CONDITIONS
- [ ] AC-005-007: constitution.md existence verified (IS-001 resolved)
- [ ] AC-005-008: Blocking unknowns (U-CA-004, U-008, U-003) documented with resolution criteria
**Dependencies**: T-001, T-002, T-003
**Estimated Effort**: LOW (1h)

---

## Phase 3: Verification (T-009 to T-011)

### T-009: Contradiction Scan Over Assembled Artifacts

**Phase**: Verification
**Description**: Run contradiction-scanner.py over assembled report sections. Triage output per P-009 (advisory).
**Acceptance Criteria**:
- [ ] Scanner executed over assembled artifacts
- [ ] Output triaged — hard contradictions vs. heuristic false positives distinguished
- [ ] No contradictions between novelty-catalogue and synthesis-report rankings
- [ ] No contradictions between architecture-gaps and squad-config.yml
**Dependencies**: T-004, T-005, T-006, T-007, T-008
**Estimated Effort**: LOW (0.5h)

### T-010: Final Coverage Verification

**Phase**: Verification
**Description**: Walk all 38 ACs and verify each is addressed. Calculate final coverage score.
**Acceptance Criteria**:
- [ ] All 38 ACs reviewed and mapped to tasks T-004 through T-008
- [ ] All 2 NEEDS_WORK items resolved (AC-001-003, AC-001-006, AC-004-010)
- [ ] Final coverage score ≥ 97%
- [ ] Quality thresholds met per P-008 (overall ≥ 0.70)
**Dependencies**: T-009
**Estimated Effort**: MEDIUM (1h)

### T-011: Finalize State and Reasoning Journal

**Phase**: Verification
**Description**: Record final quality scores, task completions, and P-004/P-005/P-006 compliance status in state.json and reasoning-journal.json.
**Acceptance Criteria**:
- [ ] state.json: completed_tasks updated, quality_scores recorded
- [ ] reasoning-journal.json: final run entry appended
- [ ] Constitution compliance verified across all artifacts
- [ ] All 3 blocking unknowns documented with status
**Dependencies**: T-010
**Estimated Effort**: LOW (0.5h)

---

## Critical Path

```
T-001 → T-002 → T-003 → T-004 ─┐
                              T-005 ─┼─► T-009 → T-010 → T-011
                              T-006 ─┤
                              T-007 ─┤
                              T-008 ─┘
```

T-004, T-005, T-006, T-007, T-008 can all run in parallel after T-003.
T-006 has soft dependency on T-005 (patent claims reference novelty catalogue).

**Estimated Total**: 5.5h (parallel) | 7-10h (sequential)
