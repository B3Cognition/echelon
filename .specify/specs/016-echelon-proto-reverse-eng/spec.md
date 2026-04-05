# Spec: echelon-proto-reverse-engineering

**Type**: Reverse Engineering Analysis
**Run ID**: squad-1775164062
**Feature**: echelon-proto-reverse-eng
**Date**: 2026-04-02
**Status**: WHAT-phase — normative requirements

---

## 1. Overview

This specification defines the requirements for a comprehensive reverse-engineering analysis of echelon_proto, a 7-tier multi-agent cognitive pipeline for software specification and implementation. The analysis will produce four primary deliverables: (1) a complete architecture map documenting all 42 agents, tier structure, and state.json spine, (2) a validated novelty catalogue covering 12 mechanisms with patent defensibility rankings, (3) a patent defensibility analysis with claim abstracts and defensibility scores, and (4) an inter-process effectiveness report assessing all 8 pipeline phases against quality gates and bottleneck patterns.

This analysis is novel as a reverse-engineering artifact: it combines cognitive architecture discovery (what agents do and why), novelty confirmation (which mechanisms are defensible), and effectiveness measurement (do the mechanisms actually work). The deliverables will serve two audiences: internal stakeholders (to validate the architecture before production) and external reviewers (for patent filing and competitive positioning).

---

## 2. Scope

### In-Scope
- All 42 agents across 7 tiers: codename, functional name, responsibility, artifacts produced
- All 7 tiers with their inter-tier data flows and dependencies
- state.json spine with all fields documented and their purposes
- All 12 novelty mechanisms (NOVEL-001 through NOVEL-011 + NS-003) with evidence grading
- Patent defensibility rankings (HIGH / MEDIUM / LOW) for each novelty mechanism
- All 8 pipeline phases (DISCOVER → LEARN) with phase entry/exit conditions and bottleneck analysis
- Endocrine feedback loops: hormone state changes per agent dispatch
- Quality gates (SAGE Understanding metrics, GATEKEEPER feasibility, BUILD review gates)
- Token efficiency analysis comparing BANZAI unlimited config vs theoretical constrained scenarios
- Evidence compilation from all SCOUT, SYNTHESIZER, and GOLDDIGGER artifacts
- Constitution.md existence verification and governance gate effectiveness
- NS-003 systematic search record (U-015-002) and novelty confirmation from spec 015

### Out-of-Scope
- Implementation of the 5 CA overlays (Goal Stack, ACT-R, LIDA, GWT, Episodic Memory) — GATE-BLOCKED per P-006
- Prototype runs for unproven mechanisms (U-005, U-CA-004, NS-003 Echelon-specific transfer) — these are blocking unknowns documented but not executed
- Token reduction measurement (NOVEL-004's 40-70% claim) — SPECULATION per P-005, requires N≥50 runs
- Ablation studies on agent count or phase sequencing — IS-006 finding, deferred to future work
- Deep dives into individual agent internals beyond scope documentation
- Recommendations for architectural changes to Echelon design itself (analysis only, no redesign)

---

## 3. Requirements

### REQ-RE-001: Architecture Map
**Statement**: Document all 42 agents across 7 tiers with their codenames, functional names, primary responsibilities, and key artifacts produced. Map all inter-tier data flows, phase sequencing, and state.json spine fields.

**Acceptance Criteria**:
- AC-001-001: Exactly 42 agents verified by file count (find agents/ -type f -name "*.md" | wc -l) and listed in structured table format (Tier, Codename, Functional Name, Responsibility, Key Artifacts)
- AC-001-002: All 7 tiers documented with clear responsibility boundaries: CONTROL (6 agents), EXPLORATION (6 agents), FEASIBILITY (2 agents), SOLUTION (3 agents), BUILD (11 agents), SPECIALISTS (6 agents), LEARNING (8 agents)
- AC-001-003: state.json spine documented with all fields: run_id, phase, dispatch_history, golddigger_artifacts, golddigger_requests, errors, escalations, calibration_data, constitution_violations, token_spent (minimum 10 fields)
- AC-001-004: Phase sequencing documented as strictly linear (DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN) with entry conditions and exit conditions for each phase
- AC-001-005: Data flow diagram showing DISCOVER outputs (glossary, mental-model, boundaries, assumptions, unknowns, contradictions) flowing to WHY, then WHAT, then downstream phases
- AC-001-006: Tier boundary enforcement rules explicitly stated (no cross-tier leakage rule + NEVER rules in each agent prompt)

**Evidence Sources**:
- glossary.md (agent directory, 42 agents listed in tables)
- mental-model.md (data flows, behavioral patterns)
- boundaries.md (tier responsibilities, data ownership)
- agents/ directory structure (CONTROL, EXPLORATION, FEASIBILITY, SOLUTION, BUILD, SPECIALISTS, LEARNING subdirectories)

---

### REQ-RE-002: Novelty Catalogue Validation
**Statement**: Cover all 12 mechanisms identified by SCOUT/SYNTHESIZER with mechanism description, prior art differential, code evidence (file:line), patent defensibility rating, and "what would constitute full proof" for each.

**Acceptance Criteria**:
- AC-002-001: All 12 mechanisms catalogued: NOVEL-001 (Endocrine), NOVEL-002 (Belief System), NOVEL-003 (NS-003 Generator-Critic + AGM), NOVEL-004 (Predictive Coding), NOVEL-005 (RADAR), NOVEL-006 (Constitutional Gate), NOVEL-007 (7-Tier Separation), NOVEL-008 (Calibration Injection), NOVEL-009 (Generator-Critic component), NOVEL-010 (CA Overlay Gates), NOVEL-011 (Constitution Authority)
- AC-002-002: Each mechanism has prior art differential documenting what existing frameworks (CrewAI, AutoGen, LangChain) do NOT have
- AC-002-003: Code evidence for each mechanism cites specific files and line numbers (e.g., "endocrine.sh line 1047", "squad-config.yml lines 444-532", "belief-parser.py line 547")
- AC-002-004: Patent defensibility ratings assigned (HIGH, MEDIUM, LOW) with justification per mechanism
- AC-002-005: "What would constitute full proof" documented for each mechanism (systematic search, benchmark study, prototype requirements, success criteria)
- AC-002-006: HIGH-rated mechanisms (NOVEL-001 Endocrine, NOVEL-003 NS-003, NOVEL-006 Constitutional Gate) have additional evidence citations and defensibility analysis (2+ paragraphs)
- AC-002-007: NS-003 novelty confirmation documented: systematic search U-015-002 found zero prior literature combining Generator-Critic + AGM for multi-agent artifact validation
- AC-002-008: Evidence grades assigned per SCOUT's taxonomy (Grade A: empirically proven, Grade B: design-validated, Grade C: theoretical)
- AC-002-009: P-004 compliance: every novelty claim cites specific evidence (no unsupported claims)
- AC-002-010: P-005 compliance: NOVEL-004 token reduction claim (40-70%) explicitly labeled as SPECULATION with notation "requires N≥50 prototype measurement before upgrade"

**Evidence Sources**:
- novelty-catalogue.md (all 12 mechanisms)
- synthesis-report.md (Section 2-3: genuine novelties ranked by confidence and defensibility)
- proof-status-table.md from spec 015 (novelty confirmation status per mechanism)
- U-015-002-novelty-search.md (systematic search record for NS-003 novelty)

---

### REQ-RE-003: Patent Defensibility Analysis
**Statement**: Rank all mechanisms by defensibility (HIGH > MEDIUM > LOW). For each HIGH/MEDIUM mechanism, provide a one-sentence claim suitable for patent abstract. Address IS-001 fix and NS-003 novelty confirmation from spec 015 search.

**Acceptance Criteria**:
- AC-003-001: Mechanisms ranked into three defensibility tiers: HIGH (3+ mechanisms), MEDIUM (4+ mechanisms), LOW (2+ mechanisms)
- AC-003-002: HIGH-defensibility mechanisms (NOVEL-003 NS-003, NOVEL-001 Endocrine, NOVEL-006 Constitutional Gate): one-sentence patent claim abstract per mechanism, ready for legal review
- AC-003-003: MEDIUM-defensibility mechanisms (NOVEL-002 Belief System, NOVEL-007 7-Tier Separation, NOVEL-008 Calibration Injection, NOVEL-005 RADAR): claim abstracts with noted vulnerabilities (substitution risks, implementation alternatives)
- AC-003-004: LOW-defensibility mechanisms (NOVEL-004 Predictive Coding, NOVEL-010 CA Overlay Gates): claims not recommended for filing until unproven status resolved
- AC-003-005: IS-001 fix documented: constitution.md existence verified (file created post-WHY1 on 2026-04-02) and pre-dispatch gate logic validated
- AC-003-006: NS-003 novelty confirmation from spec 015: systematic search results reference U-015-002 with zero-prior-literature finding
- AC-003-007: Each claim includes "Weakest Point" analysis (where competitor could substitute) and "Obviousness Risk" assessment per Graham v John Deere standards
- AC-003-008: Patent claim priority matrix created: FILE IMMEDIATELY (NS-003), FILE AFTER VALIDATION (Endocrine, Constitutional Gate, 7-Tier Separation), FILE AFTER PROTOTYPE (NOVEL-004), DO NOT FILE (40-70% token reduction)

**Evidence Sources**:
- synthesis-report.md (Section 3: Patent-Defensible Claims ranked by priority)
- novelty-catalogue.md (each mechanism's "Patent Defensibility" section)
- constitution.md (new artifact, validates NOVEL-006)
- proof-status-table.md from spec 015 (NS-003 novelty status CONFIRMED)

---

### REQ-RE-004: Inter-Process Effectiveness Report
**Statement**: Assess all 8 pipeline phases against patterns documented in patterns.yaml. Rate each bottleneck by severity (CRITICAL | HIGH | MEDIUM). Include endocrine feedback loops and token efficiency analysis.

**Acceptance Criteria**:
- AC-004-001: All 8 phases assessed: DISCOVER, WHY, WHAT, ASSESS, HOW, PLAN, BUILD, LEARN
- AC-004-002: Phase entry/exit conditions documented for each phase with quality gate checkpoints
- AC-004-003: Bottleneck severity ratings assigned per phase: DISCOVER (large-codebase scalability), WHY (amendment loop oscillation), WHAT (SAGE quality gate iterations), ASSESS (GATEKEEPER deferral loops), HOW (task dependency complexity), PLAN (task serialization), BUILD (code review throughput), LEARN (calibration data sparsity)
- AC-004-004: For each HIGH+ severity bottleneck, mitigation strategy documented
- AC-004-005: Token efficiency analysis shows: BANZAI tier allocation percentages (EXPLORE 50%, ASSESS 15%, SOLUTION 25%, BUILD unlimited, LEARN 10%)
- AC-004-006: Endocrine feedback loops documented: hormone state changes per agent dispatch, decay rates per hormone, circuit breaker thresholds (ceiling 1.0, floor 0.0, max change 0.4 per cycle)
- AC-004-007: Quality gate effectiveness assessed with empirical and estimated metrics: SAGE pass rate ~70% first pass, ~90% after amendment; GATEKEEPER kill rate 5-10%; BUILD gate block rates (CODE-REVIEWER ~15%, TEST-GUARDIAN ~20%, SPEC-GUARD ~10%, VERIFICATION ~5%)
- AC-004-008: Pattern analysis from spec runs included: PAT-001 through PAT-006 confidence scores (0.79-0.88) showing pipeline effectiveness
- AC-004-009: Critical path identified: BUILD phase is longest (40-60% of total time/tokens)
- AC-004-010: State.json corruption risks documented with mitigations (JSON validation, append-only reasoning journal, atomic re-writes)

**Evidence Sources**:
- inter-process-effectiveness.md (all data flows, bottlenecks, quality gates, token efficiency)
- synthesis-report.md (Section 4: Inter-Process Effectiveness assessment)
- patterns.yaml (from knowledge-base/, validated patterns PAT-001 through PAT-006)
- squad-config.yml (BANZAI configuration, hormone baselines, tier allocation percentages)

---

### REQ-RE-005: Evidence Compilation & Proof Status
**Statement**: Compile all Grade A evidence sources for P1-P2 claims. Verify U-015-002 search record in spec 015 artifacts. Document proof-status-table.md as authoritative claim registry. Include spec 015 build state (PASS_WITH_CONDITIONS, 12/12 tasks, 79% coverage).

**Acceptance Criteria**:
- AC-005-001: Grade A evidence identified and cited: components with empirical validation (NL2GenSym 86%+ compliance, Kumiho 93.3% contradiction detection), published papers (arxiv:2510.09355, arxiv:2603.17244), systematic searches (U-015-002)
- AC-005-002: Grade B evidence identified: design-validated claims (endocrine system design complete, contradiction scanner heuristics documented, RADAR implementation verified)
- AC-005-003: Grade C evidence identified: theoretical/speculative claims (token reduction 40-70%, agent count optimality, phase sequence optimality)
- AC-005-004: U-015-002 novelty search record verified in .specify/specs/015-ca-outcomes-validation/ with search queries, results, and zero-prior-literature finding for NS-003
- AC-005-005: proof-status-table.md (spec 015 artifact) documented as authoritative: rows 1-5 cover NS-003, NOVEL-004, and gate-conditioned mechanisms; rows 6-10 list CA overlays with GATE-CONDITIONED status; each row includes Evidence Grade, Status (PROVEN/PARTIAL/NOT PROVEN/SPECULATION/GATE-CONDITIONED), and "What Would Constitute Full Proof"
- AC-005-006: Spec 015 build state documented: 12 of 12 tasks completed (100%), coverage 79%, status PASS_WITH_CONDITIONS (some requirements pending U-CA-004 gate)
- AC-005-007: Constitution.md artifact verified as created post-WHY1 (resolves IS-001)
- AC-005-008: All blocking unknowns (U-CA-004, U-008 NS-003 transfer, U-003 SAGE validation) documented with timeline placeholders

**Evidence Sources**:
- .specify/specs/015-ca-outcomes-validation/ (spec 015 directory with proof-status-table.md, U-015-002-novelty-search.md, ns003-experiment-design.md)
- constitution.md (post-WHY1 artifact, validates IS-001 fix)
- assumptions.md, unknowns.md (evidence grades for all claims)
- synthesis-report.md (Section 5: Evidence Gaps with validation requirements)

---

## 4. Quality Standards

**Deliverable Quality Criteria:**

1. **Machine-Readability**: All data (agent counts, mechanism rankings, quality metrics) provided in structured JSON sections within Markdown for parsing. No ambiguous ranges ("about 40 agents"); exact numbers only ("exactly 42 agents verified").

2. **Traceability**: Every major claim cites specific file:line evidence. No claim stands unsupported. Claims are graded A/B/C per supporting evidence quality.

3. **Testability**: "What would constitute full proof" is concrete (not "investigate further"). Proof requires measurable criteria (N=10+ runs, ≥0.70 compliance, Spearman ρ ≥0.60, etc.).

4. **Consistency**: Novelty claims in this analysis align with novelty-catalogue.md. Patent defensibility rankings match synthesis-report.md priorities. No contradictions between sections.

5. **Completeness**: All 42 agents named. All 12 mechanisms covered. All 8 phases described. All blocking unknowns acknowledged. All quality gates documented.

6. **Evidence Hierarchy**: A-grade claims (empirically proven components, published papers) elevated in recommendations. B-grade (design-validated) supported but noted as pending validation. C-grade (speculative) flagged as such and excluded from patent filing recommendations (per P-004 and P-005).

7. **Constitutional Compliance**: Analysis adheres to all constitution.md principles, especially P-004 (evidence required), P-005 (NOVEL-004 speculation flag), P-006 (CA overlays gate-blocked).

---

## 5. Dependencies

- **SCOUT's Mental Model & Glossary**: Provides agent taxonomy and terminology
- **SYNTHESIZER's Cross-Document Validation**: Confirms no factual contradictions between discovery artifacts
- **Spec 015 Artifacts** (.specify/specs/015-ca-outcomes-validation/):
  - proof-status-table.md (authoritative claim status registry)
  - U-015-002-novelty-search.md (systematic search confirmation for NS-003)
  - ns003-experiment-design.md (prototype requirements for novelty validation)
- **Constitution.md** (post-WHY1, created 2026-04-02): Validates governance gate feasibility
- **Novelty-Catalogue.md** (SCOUT): Source of truth for all 12 mechanisms and their evidence
- **Inter-Process-Effectiveness.md** (SCOUT): Source for bottleneck analysis and token efficiency
- **Synthesis-Report.md** (SYNTHESIZER): Cross-document synthesis, patent priority matrix, evidence gap analysis
- **Issues.md** (SAGE): Documents blocking issues (IS-001 through IS-009) affecting scope

---

## Sizing Estimate

- **Total Specification**: 200-250 lines
- **REQ-RE-001 (Architecture Map)**: ~40 lines (agent tables, tier structure, state.json fields, phase sequencing)
- **REQ-RE-002 (Novelty Catalogue Validation)**: ~70 lines (12 mechanisms × 5 lines overview + evidence + proof criteria)
- **REQ-RE-003 (Patent Defensibility)**: ~50 lines (rank matrix, claim abstracts for HIGH/MEDIUM mechanisms, vulnerability analysis)
- **REQ-RE-004 (Inter-Process Effectiveness)**: ~60 lines (8 phases × 7 lines with bottleneck/gate data, endocrine loops, token analysis)
- **REQ-RE-005 (Evidence Compilation)**: ~40 lines (Grade A/B/C evidence, U-015-002 reference, proof-status table, blocking unknowns)

---

## Success Criteria

This spec is complete when:

1. All 42 agents verified and documented
2. All 12 novelty mechanisms catalogued with defensibility ratings and evidence grades
3. Patent claim abstracts drafted for HIGH-defensibility mechanisms
4. All 8 pipeline phases assessed with bottleneck severities and quality gate metrics
5. Endocrine feedback loops documented with hormone decay rates and circuit breakers
6. Constitution.md existence verified and IS-001 resolved
7. NS-003 novelty confirmation documented from U-015-002 search
8. Blocking unknowns (U-CA-004, U-008, U-003) acknowledged with validation requirements
9. No contradiction between this analysis and SCOUT/SYNTHESIZER discovery artifacts
10. All claims traceable to specific file:line evidence (per P-004 compliance)

---

*Specification for squad-1775164062 reverse-engineering analysis — WHAT-phase normative requirements complete.*
