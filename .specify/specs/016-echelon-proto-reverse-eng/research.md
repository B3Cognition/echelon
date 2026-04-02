# Research & Architectural Decisions
## echelon-proto Reverse Engineering Analysis

**Run ID**: squad-1775164062
**Date**: 2026-04-02
**Author**: ARCHITECT (HOW phase)
**Purpose**: Establish architectural foundations for final analysis report structure

---

## ADR-001: Primary Report Structure — Layered Traceability Model

**Decision**: 

The final analysis report follows a **four-layer pyramid structure**:
1. **Executive Layer** (1 page): 42 agents, 12 mechanisms, 8 phases, status summary
2. **Evidence Layer** (3-5 pages): Evidence grades (A/B/C) per claim, proof-status registry, blocking unknowns
3. **Detail Layer** (10-15 pages): Per-mechanism deep dives, patent abstracts, quality gate analysis, endocrine documentation
4. **Verification Layer** (2-3 pages): Spec 015 artifact cross-references, constitution.md validation, traceability matrix

**Rationale**: 

Reverse-engineering analysis serves two audiences (internal validation vs external patent review). Executive layer enables quick scanning; evidence layer provides citation scaffolding; detail layer supports patent legal review; verification layer enables testability and future audits. This structure aligns with spec.md Quality Standard #2 (Traceability) and #6 (Evidence Hierarchy) requirements.

**Consequences**: 

- All novelty claims must cite specific file:line evidence (P-004 compliance mandatory)
- Report sections are independently readable (enables selective review by patent counsel)
- Deliverable will be 80-120 pages minimum (substantial but defensible given 42 agents, 12 mechanisms, 5 requirement areas)
- Each section requires explicit "(est.)" notation for estimated vs measured metrics (IS-003 compliance)

---

## ADR-002: Evidence Citation Standard — Atomic Reference Units

**Decision**: 

Every major claim cites evidence using **atomic unit format**: `source-type:identifier:location`, where:
- `source-type` ∈ {arxiv, github, file, measurement, search}
- `identifier` = full identifier (arxiv:2510.09355, file:agents/control/commander.md, search:U-015-002)
- `location` = section or line number (optional; used for precision >2KB sources)

Examples:
- "NS-003 novelty confirmed via systematic search." → `search:U-015-002:Query 1 results, lines 23-36`
- "Generator-Critic achieves 86% compliance." → `arxiv:2510.09355:Abstract + Section 3.2, Table 2`
- "Endocrine decay rates documented." → `file:squad-config.yml:lines 54-67`

**Rationale**: 

Atomic references enable automated traceability verification (grep searches for evidence), support legal discovery (specific section locatable within seconds), and prevent vague claims like "per research." This enforces P-004 (evidence required) and enables spec.md Quality Standard #3 (Testability).

**Consequences**: 

- Report production requires evidence mapping pass (cross-check every claim against source)
- Patent counsel can verify claims mechanically (grep for arxiv IDs, github URLs, filenames)
- Redaction for confidentiality becomes straightforward (redact by source-type)
- Estimated metrics must be marked `(est.)` and include method (e.g., "SAGE pass rate 70% (est., based on inter-process-effectiveness.md configuration analysis)")

---

## ADR-003: Patent Claim Formatting — Narrow Claims with Obviousness Defense

**Decision**: 

Patent abstracts follow **narrow claim format** with explicit non-obviousness argument:

```
CLAIM: [Mechanism Name] — [One-sentence functional description]

CLAIM BODY: [2-3 sentence technical specification with implementation detail]

NON-OBVIOUS ELEMENT: [Why existing frameworks do not implement this; 
substitution difficulty; unexpected interaction with other components]

WEAKNESS: [Competitor alternative; most likely attack on novelty]

EVIDENCE GRADE: [A/B/C + source + "what would constitute upgrade"]
```

Example (NS-003):
```
CLAIM: Generator-Critic + AGM Belief Revision for Multi-Agent Artifact Validation

CLAIM BODY: A method combining execution-grounded schema validation (Critic) 
with Alchourrón-Gärdenfors-Makinson formal belief revision to detect and resolve 
contradictions in multi-stage LLM agent output pipelines.

NON-OBVIOUS ELEMENT: CrewAI, AutoGen, LangChain do not implement belief revision 
formalism for artifact stores. Contradiction detection in these frameworks is heuristic 
(string matching, value mismatches) not formally grounded. AGM application to LLM 
agent contradiction resolution is not found in literature per U-015-002 systematic search.

WEAKNESS: Competitor implements simpler heuristic contradiction detection (higher recall, 
lower precision) avoiding AGM formalism complexity. Claim novelty narrowly on the AGM component 
or on the *combination*; defend the combination's added value empirically.

EVIDENCE GRADE: A (components independently proven via arxiv:2510.09355, arxiv:2603.17244)
+ B (combination novelty confirmed via U-015-002 systematic search). Upgrade to A requires 
NS-003 prototype achieving ≥0.80 contradiction catch rate on Echelon artifact pairs (REQ-015-006).
```

**Rationale**: 

Narrow claims are defensible in post-grant review and litigation (weaker attacks from competitors). Non-obvious element addresses Graham v John Deere 3-point test. Weakness documentation preempts patent counsel's questions and strengthens application (honesty + proactivity = higher examiner confidence). Evidence grading (A/B/C) distinguishes proven from speculative claims, avoiding P-005 violation.

**Consequences**: 

- All 12 mechanisms require full ADR-003 format patent abstracts (workload: ~2 hours)
- Report will cite claim strengths AND explicit weaknesses (unusual but legally stronger)
- Claims are narrow enough to avoid obviousness objections but specific enough to be legally enforceable
- Each claim includes upgrade path (what additional proof would strengthen the grant)

---

## ADR-004: Novelty Defensibility Threshold — Three-Tier Ranking with Proof Boundary

**Decision**: 

Mechanisms ranked HIGH/MEDIUM/LOW defensibility using **proof-boundary model**:

| Tier | Definition | Conditions | Examples |
|------|-----------|-----------|----------|
| **HIGH** | Component-level proven by independent publication (Grade A) + novelty confirmed by systematic search (Grade B) OR design-validated in Echelon with no known prior art | NS-003: arxiv papers + U-015-002 search confirmed zero prior work | NOVEL-003 (NS-003), NOVEL-001 (Endocrine), NOVEL-006 (Constitutional Gate) |
| **MEDIUM** | Grade B evidence (framework documentation, peer-reviewed design) + implementation complete in Echelon + credible substitution alternative exists | NOVEL-002: belief-parser.py exists, annotations documented, but YAML metadata approach is implementable via alternative services | NOVEL-002 (Belief System), NOVEL-007 (7-Tier Separation), NOVEL-008 (Calibration), NOVEL-005 (RADAR) |
| **LOW** | Grade C evidence (theoretical motivation, structural analogy) OR no empirical grounding (SPECULATION per P-005) OR implementation incomplete | NOVEL-004: inspired by Speculative Decoding but no direct measurement in Echelon; 40-70% claim is directional not measured | NOVEL-004 (Predictive Coding), NOVEL-010 (CA Overlays — gate-blocked on U-CA-004) |

**Rationale**: 

Defensibility hinges on **proof boundary** — the line between published evidence and Echelon-specific unproven claims. HIGH mechanisms cross the proof boundary (independent publication + novelty confirmation). MEDIUM mechanisms have proven components but Echelon-specific integration unproven. LOW mechanisms are speculative or blocked. This structure directly maps to spec.md REQ-RE-003 (Patent Defensibility Analysis) with testable criteria per AC-003-001.

**Consequences**: 

- HIGH mechanisms can be filed immediately (patent application ready now)
- MEDIUM mechanisms require validation run before filing (N=5-10 runs, proof upgrade to B or A)
- LOW mechanisms require either prototype (NOVEL-004, NOVEL-010) or explicit blocking reason documentation (gate-conditioned on U-CA-004)
- P-005 requires NOVEL-004 to remain labeled SPECULATION in all reports until N≥50 empirical runs complete

---

## ADR-005: Spec 015 Integration — Cross-Reference Model without Duplication

**Decision**: 

Spec 015 (proof-status-table.md, U-015-002, ns003-experiment-design.md) are cited as **authoritative external sources**, not reproduced:

- **Referenced not reproduced**: Proof-status-table.md row 3 (NS-003-C novelty) is cited as "Proof Status Row 3: NOVELTY CONFIRMED as of 2026-04-02" with linked reference, not recopied
- **Search results summarized not detailed**: U-015-002 query results are summarized as "8 query variants returned zero prior papers combining Generator-Critic + AGM belief revision" with reference to investigation/U-015-002-novelty-search.md, not full search log republished
- **Design documents referenced**: ns003-experiment-design.md referenced for "NS-003 prototype requirements (REQ-015-006)" without duplicating REQ specifications
- **Blocking unknowns flagged**: U-CA-004 gate-blocked status (spec 015 AC-001-004) is documented with reference "Proof Status Table rows 6-10; see .specify/specs/015-ca-outcomes-validation/"

**Rationale**: 

Spec 015 is a parallel specification (CA overlays validation) sharing some claims with this reverse-engineering analysis (NS-003 novelty, NOVEL-004 token reduction). Reproducing spec 015 content creates maintenance burden and versioning conflicts. Cross-referencing establishes evidence chain without duplication: this report cites spec 015 findings; spec 015 is independently validated. Supports spec.md Quality Standard #4 (Consistency) and #5 (Completeness).

**Consequences**: 

- Final report includes 5-7 hyperlinked references to spec 015 artifacts (enables bidirectional traceability)
- Spec 015 must remain stable during this analysis phase (changes to proof-status-table.md will cascade here)
- Constitution.md P-019 declares "NS-003 Generator-Critic + AGM combination is the primary IP asset" — spec 015 proof status is critical validation
- Deliverable includes appendix listing all external spec references with verification checksums (md5 or git SHAsin readable form)

---

## ADR-006: Architecture Gap Filling Strategy — Targeted Augmentation of Partial Coverage

**Decision**: 

Three NEEDS_WORK gaps (AC-001-003, AC-001-006, AC-004-010) and two PARTIAL gaps (AC-004-002, AC-004-009) are filled in separate architecture-gaps.md artifact following this structure:

**Gap 1 (AC-001-003 — state.json Spine)**: Complete enumeration of all fields with type, purpose, writer, readers
**Gap 2 (AC-001-006 — Tier Boundary Enforcement)**: COMMANDER's pre-dispatch gate logic + NEVER rules per tier
**Gap 3 (AC-004-010 — Corruption Risks)**: Documented risks (concurrent writes, partial writes, schema drift, stale reads) with mitigations from state-backup.sh and kb-lock.sh
**Gap 4 (AC-004-002 — Phase Entry/Exit)**: 8×4 table (Phase, Agent, Entry, Exit, Outputs) synthesized from mental-model.md
**Gap 5 (AC-004-009 — Critical Path)**: Estimated BUILD phase 40-60% of total time with notation "(est., based on token allocation percentages from squad-config.yml)"

**Rationale**: 

Coverage-map.md shows 84.2% baseline (28 COVERED + 4 PARTIAL = 32/38 effective). Filling these 5 gaps adds 13.2 percentage points (~5 items × 2.6 pp each = 50 additional pp of coverage density, capped at net +X% from gap filling estimate). Gaps are incremental (documentation not discovery), enabling fast turnaround.

**Consequences**: 

- architecture-gaps.md becomes the source of truth for state.json field definitions (replaces implicit squad-config.yml documentation)
- Tier enforcement becomes mechanically verifiable (pre-dispatch gate script can be validated against documented NEVER rules)
- Risk mitigation strategy is explicit (enables future hardening, e.g., atomic state.json re-writes via rename + move)
- Phase entry/exit conditions are now testable (can write assertions for phase transitions)
- Critical path documentation enables bottleneck analysis for future optimization (BUILD phase is longest, implies parallelism gains focus there)

---

## Summary: ADRs Support Spec.md Delivery

| ADR | Supports Requirement | Impact |
|-----|-------------------|--------|
| ADR-001 | REQ-RE-001, REQ-RE-005 | Report structure enables 42-agent documentation in readable, testable format |
| ADR-002 | P-004 (Evidence required), REQ-RE-002, REQ-RE-003 | All claims citable via atomic references; enables automated verification |
| ADR-003 | REQ-RE-003 (Patent claims) | Narrow claims reduce obviousness risk; weakness documentation strengthens application |
| ADR-004 | REQ-RE-003 (Defensibility ranking) | Proof-boundary model distinguishes proven (filed now) from speculative (blocked) |
| ADR-005 | Spec 015 integration, AC-002-007, AC-003-006 | Cross-reference model prevents duplication; enables parallel validation |
| ADR-006 | Coverage-map.md gap filling | 5 gaps filled with targeted documentation; coverage → ~90% effective |

**Effective Coverage After ADRs**: 
- Base: 84.2% (28 COVERED + 8 PARTIAL at 50% = 32 effective)
- Gap filling: +5 items = +13.2 pp
- **Target**: ~97% effective coverage (all gaps addressed or documented as deferred)

---

*Architecture decisions REQ-RE-001 through REQ-RE-005 complete. ARCHITECT verdicts prepared for evidence layer.*
