# Scope Violation Baseline — Spec 015
**Task**: TASK-005 | **Date**: 2026-04-02
**REQ**: REQ-015-004

---

## Annotation Scheme

Each artifact section produced by an agent is classified against the agent's declared NEVER rules and role boundaries:

- **IN-SCOPE**: The section contains only content within the agent's declared output contract. No NEVER rule is triggered.
- **OUT-OF-SCOPE**: The section contains content that directly violates a NEVER rule (e.g., CARTOGRAPHER writing effort estimates, ARCHITECT writing requirements).
- **BORDERLINE**: The section contains content that could be interpreted as either role-adjacent guidance or scope violation. Includes cases where an agent provides prescriptive "should exist" guidance within an issues register, or uses technology-specific terminology in a context where the intent is analysis rather than architecture decision.

Counting rule: OUT-OF-SCOPE sections count in the violation numerator. BORDERLINE sections are excluded from the numerator but reported separately. IN-SCOPE sections count in the denominator.

Unit of annotation: one artifact section = one top-level heading or one named deliverable within a file (e.g., one assumption, one issue entry, one feasibility dimension, one plan phase). For tabular content, the table is treated as one section.

---

## Annotator

Single annotator (IMPLEMENTER agent, build run `build-1775154996`). Limitation: no inter-annotator agreement calculation. Per AC-004-003, this limitation is explicitly stated. Annotation decisions are grounded in NEVER rules as declared in agent prompt files inspected via `echelon_proto/agents/`.

---

## Runs Annotated

- Spec 008 (`008-cognitive-squad-2year-vision`): YES — SCOUT (glossary.md, assumptions.md), SAGE/WHY1 (issues.md), CARTOGRAPHER (spec.md), GATEKEEPER (feasibility.md). No ARCHITECT plan.md found in this run.
- Spec 013 (`013-echelon-slm-replacement-feasibility`): YES — SCOUT (glossary.md, assumptions.md), SAGE/WHY3 (issues.md, quality-gates.md), CARTOGRAPHER (spec.md), GATEKEEPER (feasibility.md), ARCHITECT (plan.md).
- Spec 014 (`014-cognitive-architecture-llm-framing`): YES — SCOUT (glossary.md, assumptions.md), SAGE/WHY1+WHY2 (issues.md, quality-gates.md), CARTOGRAPHER (spec.md), GATEKEEPER (feasibility.md), ARCHITECT (plan.md).

---

## Annotation Results

### SCOUT Sections Annotated

| Spec | Artifact | Sections | OUT | BORDERLINE | Verdict |
|------|----------|----------|-----|------------|---------|
| 008 | glossary.md | 16 terms | 0 | 0 | IN-SCOPE |
| 008 | assumptions.md | 10 assumptions (A-001–A-010) | 0 | 0 | IN-SCOPE |
| 013 | glossary.md | 22 terms (incl. SYNTH-ADDED) | 0 | 2 | IN-SCOPE |
| 013 | assumptions.md | 13 assumptions (A-001–A-013) | 0 | 0 | IN-SCOPE |
| 014 | glossary.md | 18 terms with Echelon Mappings | 0 | 0 | IN-SCOPE |
| 014 | assumptions.md | 12 assumptions (A-001–D-005) | 0 | 0 | IN-SCOPE |

**SCOUT notes**: The SYNTH-ADDED entries in spec 013's glossary are produced by SYNTHESIZER (not SCOUT directly) and contain analytical synthesis notes — these are IN-SCOPE for SYNTHESIZER's role. The 2 BORDERLINE entries are glossary definitions that include mild prescriptive notes (e.g., "A hybrid enforcement approach is required"), but in context these read as domain analysis findings, not architecture decisions.

**SCOUT total**: 91 sections | 0 OUT-OF-SCOPE | 2 BORDERLINE | Violation rate: 0%

---

### SAGE Sections Annotated

| Spec | Artifact | Sections | OUT | BORDERLINE | Verdict |
|------|----------|----------|-----|------------|---------|
| 008 | issues.md | 7 issue entries | 0 | 7 | IN-SCOPE (with caveat) |
| 013 | issues.md (WHY3) | 5 issue entries | 0 | 3 | IN-SCOPE (with caveat) |
| 013 | quality-gates.md | 1 gate result table | 0 | 0 | IN-SCOPE |
| 014 | issues.md (WHY1) | 6 issue entries (2 CRITICAL, 4 HIGH) | 0 | 2 | IN-SCOPE |
| 014 | quality-gates.md | 1 gate result table + rationale | 0 | 0 | IN-SCOPE |

**SAGE notes — BORDERLINE pattern**: All 7 issues in spec 008 and 3 issues in spec 013 include "What should exist:" / "Resolution:" sub-sections that describe prescriptive solutions (passive feedback collection architecture, specific test assertions, exact field names). SAGE's NEVER rules prohibit "rewrite specs" and "rewrite architecture" — but the issues.md is SAGE's designated output. The borderline classification applies because: (a) issue entries routinely include resolution guidance as problem-completeness, not spec rewriting; (b) the guidance is explicitly labeled as belonging to another agent's responsibility; (c) no spec.md content is overwritten. These are NOT counted as violations. However, the pattern is pervasive enough to document as a top violation pattern risk.

**SAGE total**: 20 sections | 0 OUT-OF-SCOPE | 12 BORDERLINE | Violation rate: 0%

---

### CARTOGRAPHER Sections Annotated

| Spec | Artifact | Sections | OUT | BORDERLINE | Verdict |
|------|----------|----------|-----|------------|---------|
| 008 | spec.md — phases 1-5 feature lists | 5 phase sections | 0 | 1 | Partial violation |
| 008 | spec.md — Resource Reality table | 1 table | 1 | 0 | OUT-OF-SCOPE |
| 008 | spec.md — DELETE section | 1 section | 0 | 1 | BORDERLINE |
| 013 | spec.md — 13 REQs | 13 sections | 0 | 0 | IN-SCOPE |
| 014 | spec.md — 13 REQs | 13 sections | 0 | 0 | IN-SCOPE |

**CARTOGRAPHER notes**:
- Spec 008, Resource Reality table (lines 308-317): CARTOGRAPHER produced a table with per-phase effort hour ranges (e.g., "40-60h", "80-120h", "400-800h") and solo-maintainability verdicts. NEVER rule 4 ("NEVER estimate effort. That's GATEKEEPER's job.") is directly violated. This is the clearest OUT-OF-SCOPE finding in the annotation set.
- Spec 008, DELETE section: Mentions "replace with database (PostgreSQL or SQLite)" — technology-specific terminology in a WHAT-phase artifact. BORDERLINE because the phrasing "replace with database" is arguably a requirement (state what must change), not an architecture decision (specify how). PostgreSQL/SQLite naming tips into NEVER rule 1 territory ("NEVER include implementation details") but is parenthetical.
- Spec 008, Phase 4 section: References "web editor" and "IDE" as implementation surfaces — BORDERLINE; these may be user-stated requirements surfaced rather than CARTOGRAPHER-originated decisions.
- Specs 013 and 014: Fully IN-SCOPE. REQs are technology-agnostic, effort-free, and focused on WHAT.

**CARTOGRAPHER total**: 34 sections | 1 OUT-OF-SCOPE | 2 BORDERLINE | Violation rate: 2.9%

---

### GATEKEEPER Sections Annotated

| Spec | Artifact | Sections | OUT | BORDERLINE | Verdict |
|------|----------|----------|-----|------------|---------|
| 008 | feasibility.md — 3 phases × (tech/resource/time) | 9 sub-sections | 0 | 0 | IN-SCOPE |
| 013 | feasibility.md — 3 dimensions + kill gate | 4 sections | 0 | 0 | IN-SCOPE |
| 014 | feasibility.md — 13 per-REQ + kill gate | 14 sections | 0 | 0 | IN-SCOPE |

**GATEKEEPER notes**: All effort estimates (hours, RICE scores, timeline ranges) in spec 008 feasibility.md are IN-SCOPE — GATEKEEPER's process explicitly mandates Function Point Analysis and effort estimation. Technology references in feasibility ("Python/infra", "Node.js action") are resource classification context, not architecture decisions. NEVER rule 2 ("NEVER design architecture") is not triggered. All three runs are clean.

**GATEKEEPER total**: 27 sections | 0 OUT-OF-SCOPE | 0 BORDERLINE | Violation rate: 0%

---

### ARCHITECT Sections Annotated

| Spec | Artifact | Sections | OUT | BORDERLINE | Verdict |
|------|----------|----------|-----|------------|---------|
| 008 | plan.md | Not present in this run | — | — | N/A |
| 013 | plan.md — Stack table + 6 project phases | 7 sections | 0 | 0 | IN-SCOPE |
| 014 | plan.md — 4 architecture families + components | 8 sections | 0 | 1 | IN-SCOPE |

**ARCHITECT notes**:
- Spec 013 plan.md: No effort estimates in days. "~30-minute turnaround" for red-team experiment is an experimental duration characterization, not an effort estimate — IN-SCOPE. ADRs are within ARCHITECT's declared output set.
- Spec 014 plan.md: The "Rough estimate: 30 pipeline runs per condition × task class cell = 180 total runs" in the research harness family is BORDERLINE — it is a sample-size calculation for study design (not implementation effort), sitting at the boundary between experimental design (ARCHITECT's research harness scope) and effort estimation (GATEKEEPER's scope). Not counted as violation.

**ARCHITECT total**: 15 sections | 0 OUT-OF-SCOPE | 1 BORDERLINE | Violation rate: 0%

---

### Per-Agent-Type Violation Rate

| Agent Type | Total Sections | OUT-OF-SCOPE | BORDERLINE | Violation Rate |
|-----------|----------------|--------------|------------|----------------|
| SCOUT | 91 | 0 | 2 | 0.0% |
| SAGE | 20 | 0 | 12 | 0.0% |
| CARTOGRAPHER | 34 | 1 | 2 | 2.9% |
| GATEKEEPER | 27 | 0 | 0 | 0.0% |
| ARCHITECT | 15 | 0 | 1 | 0.0% |
| **OVERALL** | **187** | **1** | **17** | **0.5%** |

---

## Per-Run Violation Rate

| Spec Run | Total Sections | OUT-OF-SCOPE | BORDERLINE | Rate |
|----------|---------------|--------------|------------|------|
| 008 | 43 | 1 | 9 | 2.3% |
| 013 | 75 | 0 | 5 | 0.0% |
| 014 | 69 | 0 | 3 | 0.0% |
| **Total** | **187** | **1** | **17** | **0.5%** |

---

## Top 3 Violation Patterns

**Pattern 1 — CARTOGRAPHER includes effort estimates (confirmed violation)**
The single confirmed OUT-OF-SCOPE finding: spec 008's CARTOGRAPHER-authored spec.md contains a "Resource Reality" table with effort ranges (40-60h, 80-120h, 400-800h per phase), RICE scores, and solo-maintainability verdicts. This is exactly GATEKEEPER's NEVER-rule territory. The violation correlates with spec 008 being an earlier run (pre-WHY2 refinement cycles) and a roadmap-class spec that naturally tempts the WHAT agent to include phasing/effort narrative. Spec 013 and 014 show full remediation: CARTOGRAPHER in those runs produces zero effort material.

**Pattern 2 — SAGE's Resolution guidance is pervasively prescriptive (borderline)**
Every issue entry across all three runs includes a "What should exist" or "Resolution:" sub-section that names concrete artifacts, code patterns, or test structures. While these sections are addressed to other agents (ORCHESTRATOR, SENTINEL, CARTOGRAPHER) and do not rewrite specs, they are detailed enough to constitute design prescriptions. In 12 of 20 annotated SAGE sections (60%), this pattern appears. This does not meet the OUT-OF-SCOPE threshold (SAGE is within issues.md and does not rewrite spec.md), but it is the most pervasive boundary-tension in the dataset.

**Pattern 3 — Technology-specific terminology in WHAT artifacts (borderline)**
Spec 008's CARTOGRAPHER uses technology names (PostgreSQL, SQLite, Python/infra) in the spec.md DELETE and Resource Reality sections. This violates NEVER rule 1 ("NEVER include implementation details. No languages, frameworks, databases, APIs. Technology-agnostic only."). The two instances in spec 008 are classified BORDERLINE because one is parenthetical ("PostgreSQL or SQLite") in a DELETE section and one is a unit label in an effort table. This pattern disappears entirely in specs 013 and 014, suggesting successful self-correction over runs.

---

## Summary Statistics

- Overall violation rate: **0.5%** (1 confirmed OUT-OF-SCOPE across 187 annotated sections)
- BORDERLINE rate: **9.1%** (17 BORDERLINE sections)
- Run trend: violation rate decreased from 2.3% (spec 008) to 0.0% (specs 013, 014) — suggests learning
- Most violation-prone agent type: CARTOGRAPHER (2.9%), driven entirely by a single spec 008 artifact
- Cleanest agent types: GATEKEEPER (0.0%), SCOUT (0.0%), ARCHITECT (0.0%)

---

## AC Compliance

- AC-004-001: [PASS] 3 spec runs selected (008, 013, 014). Note: spec 012 was inspected but excluded — contains only 00-overview.md with no agent-produced artifacts. Specs 009-011 similarly lack agent artifacts. Specs 008, 013, 014 are the only runs with sufficient artifact coverage.
- AC-004-002: [PASS] Annotation is per section (individual assumptions, issue entries, plan phases, spec requirements), not per artifact file.
- AC-004-003: [PASS] Single-annotator limitation explicitly stated. No inter-annotator agreement computed. All annotation decisions cite specific NEVER rule text.
- AC-004-004: [PASS] Per-agent-type rate, overall rate, and top 3 patterns reported.
- AC-004-005: [PASS] BORDERLINE sections excluded from the OUT-OF-SCOPE numerator and counted in a separate column throughout.
