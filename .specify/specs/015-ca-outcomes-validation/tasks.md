# Tasks — Spec 015: Cognitive Architecture Outcomes Validation
**Agent**: ORCHESTRATOR | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02
**Phase**: plan

---

## Task List

### TASK-001: Produce Proof Status Table Artifact
**REQ**: REQ-015-001
**Scope**: A formatted, 17-row proof status verdict table covering every claim in mental-model.md Section 4. Each row carries: claim identifier, primary evidence source (DOI or arxiv ID or artifact path), evidence grade (A/B/C/D), proof category (P1-P5), proof status label, and a non-empty "What Would Constitute Full Proof" cell for every non-P1 row. The two P5 SPECULATION rows are labeled "SPECULATION: no empirical grounding." All five CA overlay rows carry "GATE-CONDITIONED on U-CA-004" with U-015-001 as the blocking reference. NS-003-A and NS-003-B carry "PROVEN (component level) / PARTIAL (Echelon-specific)" citing arxiv:2510.09355 and arxiv:2603.17244 respectively.
**Acceptance Criteria**: Table contains exactly 17 rows (AC-001-001); all six fields populated per row (AC-001-002); two P5 rows labeled "SPECULATION: no empirical grounding" (AC-001-003); five CA overlay rows labeled "GATE-CONDITIONED on U-CA-004" citing U-015-001 (AC-001-004); NS-003-A and NS-003-B carry component-level PROVEN / Echelon-specific PARTIAL labels with correct arxiv IDs (AC-001-005); no verdict cell uses "believed," "expected," or "likely" without a citation (AC-SPEC-001).
**Effort**: Quick
**Depends on**: None
**Priority**: MVP

---

### TASK-002: Produce Standalone NS-003 Novelty Search Record Artifact
**REQ**: REQ-015-002
**Scope**: A standalone artifact (separate from the proof status table) containing the reproducible NS-003 novelty search record. The artifact extracts and formalizes the search protocol, query strings, databases queried, date of execution, per-result disposition table, and hedged novelty verdict from the INVESTIGATOR's U-015-002-novelty-search.md into a self-contained document. No new research is conducted; the source is U-015-002-novelty-search.md.
**Acceptance Criteria**: Artifact contains the exact query string as executed, both databases queried (Semantic Scholar and Google Scholar), date of execution to the day, result count per database, and disposition for each result (AC-002-001, AC-002-002); novelty verdict uses hedged phrasing "no prior literature found in the reviewed corpus as of [date]" not "no prior literature exists" (AC-002-003); artifact is stored as a standalone document independent of the proof status table (AC-002-005); no result matching the full conjunction was found — if found, REQ is escalated per AC-002-004.
**Effort**: Quick
**Depends on**: None
**Priority**: MVP

---

### TASK-003: Write NS-003 Prototype Experiment Design Document
**REQ**: REQ-015-006
**Scope**: A complete, self-contained experiment design document for binary PASS/FAIL validation of NS-003 (Generator-Critic + Belief Revision) on Echelon's artifact protocol. The document names the fixed test codebase with rationale, specifies NS-003-A evaluation set (N≥30 agent invocations, first-pass compliance rate formula, ≥70% acceptance threshold, inconclusive and redesign zones), specifies NS-003-B evaluation set (N≥20 artificially contradicted artifact pairs, contradiction injection method, catch rate formula ≥80%, false positive rate ≤20%), states timeline in phases, and is written at a level of specificity sufficient for third-party execution without clarification.
**Acceptance Criteria**: Fixed test codebase named with rationale (AC-006-001); NS-003-A evaluation set size and first-pass compliance formula specified with ≥70% threshold and zone definitions (AC-006-002, AC-006-004); NS-003-B evaluation set of N≥20 contradicted pairs with injection method and catch rate formula at ≥80% threshold and ≤20% FPR stated (AC-006-003, AC-006-005); timeline in phases (AC-006-006); third-party executability confirmed by self-check — metric formulas, thresholds, evaluation set construction, codebase selection, and decision logic are all unambiguous (AC-006-007, AC-SPEC-005).
**Effort**: Medium
**Depends on**: None
**Priority**: MVP

---

### TASK-004: Write U-CA-004 Gate Experiment Specification
**REQ**: REQ-015-008
**Scope**: A complete, self-contained specification of the U-CA-004 three-condition gate experiment covering: three conditions (Naive Baseline, Expert-Prompt Baseline, CA-Structured Overlay) with a specific LLM version lock; sample size with statistical power rationale (N=10 minimum viable / N=20 for 80% power); test codebase selection strategy (fixed single or stratified five-codebase) with rationale; Artifact Quality Score rubric with four dimensions (coherence, completeness, scope compliance, internal consistency) each with 0-3 scoring anchors stated explicitly; pre-registered decision rule (POSITIVE / NEGATIVE / INCONCLUSIVE) with quantitative thresholds, statistical test, and action mapping; CA overlay testing order with rationale for first overlay selection.
**Acceptance Criteria**: Three conditions specified with same LLM version across all runs (AC-008-001, AC-008-002); N≥10 per condition with power rationale stated (AC-008-003); codebase selection strategy chosen and justified (AC-008-004); at least two primary metrics with formulas including Artifact Quality Score rubric with 0-3 anchors per dimension (AC-008-005); pre-registered POSITIVE/NEGATIVE/INCONCLUSIVE decision rule with ≥10pp quality delta and ≥15% violation/contradiction reduction thresholds and action mappings (AC-008-006); single-overlay-at-a-time constraint stated, first overlay identified with rationale, subsequent order contingent on POSITIVE result stated (AC-008-007); all CA overlay claims remain GATE-CONDITIONED throughout (AC-SPEC-002).
**Effort**: Medium
**Depends on**: None
**Priority**: MVP

---

### TASK-005: Annotate Prior Spec Runs for Scope Violations
**REQ**: REQ-015-004
**Scope**: Annotation of 3-5 prior Echelon spec runs (corpus: runs 008-014) to produce a scope violation rate baseline per agent type and per run. Each agent output section is classified as IN-SCOPE, OUT-OF-SCOPE, or BORDERLINE relative to that agent's declared scope from its prompt definition. The artifact reports: violation rate per agent type (OUT-OF-SCOPE sections / total sections for that agent type), overall violation rate, and the three most frequent violation patterns. BORDERLINE sections are excluded from the violation rate numerator and counted separately.
**Acceptance Criteria**: 3 to 5 prior spec runs selected from runs 008-014, each containing at least DISCOVER and ASSESS outputs (AC-004-001); annotation applied per section not per artifact (AC-004-002); single-annotator limitation explicitly stated per AC-004-003; artifact reports per-agent-type violation rate, overall rate, and top three violation patterns (AC-004-004); BORDERLINE sections excluded from numerator and counted separately (AC-004-005).
**Effort**: Medium
**Depends on**: None
**Priority**: MVP

---

### TASK-006: Start Token Logging Instrumentation
**REQ**: REQ-015-003
**Scope**: Instrumentation of the Echelon pipeline to log per-agent-invocation token counts. The instrumentation captures: prompt token count, completion token count, agent identifier, spec run ID, and codebase identifier. The instrumented pipeline is deployed and at least 3 completed spec runs are collected. The baseline dataset is produced as a structured JSON or CSV artifact with per-agent-type summary statistics (mean, median, 90th-percentile) and per-run pipeline totals.
**Acceptance Criteria**: All five fields captured per invocation (AC-003-001); baseline data from at least 3 completed spec runs (AC-003-002); per-agent-type summary statistics (mean, median, 90th-percentile) reported (AC-003-003); machine-readable structured artifact produced alongside human-readable summary (AC-003-004); artifact states whether data is from post-hoc estimation or live instrumentation (AC-003-005).
**Effort**: Medium
**Depends on**: None
**Priority**: High

---

### TASK-007: Run Automated Contradiction Scan of Prior Spec Runs
**REQ**: REQ-015-005
**Scope**: An automated scan of prior Echelon spec run artifacts (minimum: runs 008-014 with both DISCOVER and ASSESS artifacts) to measure inter-artifact contradiction frequency. The detection method is selected and applied consistently (exact string match, semantic embedding similarity with stated threshold, or LLM classifier). The artifact reports: total artifact pairs scanned, total contradictions detected, contradiction rate per run, contradiction rate per adjacent agent pair. A manual precision check of at least 5 detected contradictions is included. The artifact explicitly states whether the detected rate is an upper or lower bound.
**Acceptance Criteria**: Scan covers minimum runs 008-014 (AC-005-001); detection method stated explicitly and applied consistently with precision/recall characteristics documented (AC-005-002); output reports total pairs scanned, total contradictions, rate per run, and rate per adjacent agent pair (AC-005-003); 5-sample manual precision review included (AC-005-004); upper/lower bound characterization of the detected rate stated (AC-005-005).
**Effort**: Medium
**Depends on**: TASK-005 (shares the same artifact corpus; selection of the 3-5 run subset from TASK-005 determines which runs are available for the scan)
**Priority**: High

---

### TASK-008: Perform NOVEL-004 Retrospective Calibration
**REQ**: REQ-015-007
**Scope**: A retrospective calibration of NOVEL-004 forward model prediction accuracy using available adjacent artifact pairs (DISCOVER→ASSESS) from spec runs 008-014. Each pair is scored 0-100% on the question of what proportion of ASSESS's top-level assertions were predictable from DISCOVER's output alone, using the AC-007-002 scoring anchors (0-20% / 40-60% / 80-100% with 50% for borderline assertions). The artifact reports: N pairs evaluated, mean/median/min/max/std deviation of prediction accuracy, break-even computation (symbolic if TASK-006 is incomplete, numeric if complete), SPECULATION label on 40-70% token reduction claim, and a go/no-go recommendation per AC-007-006.
**Acceptance Criteria**: At least N=9 adjacent artifact pairs evaluated or N explicitly stated with small-sample limitation (AC-007-001); per-pair scoring follows AC-007-002 rubric with stated evaluation method (AC-007-002); aggregate statistics (mean, median, min, max, std deviation) reported (AC-007-003); break-even formula instantiated numerically or in symbolic form with pending notation (AC-007-004); 40-70% token reduction claim labeled "SPECULATION" regardless of calibration outcome (AC-007-005, AC-SPEC-003); go/no-go recommendation states GO / NO-GO / INCONCLUSIVE per the AC-007-006 decision criteria (AC-007-006).
**Effort**: Medium
**Depends on**: TASK-006 (soft — for numeric break-even; proceeds with symbolic break-even if TASK-006 is incomplete)
**Priority**: Medium

---

### TASK-009: Resolve ISS-001 Architecture Ambiguity for Goal Stack Granularity
**REQ**: U-015-007 (architecture clarification)
**Scope**: A targeted inspection of commander.md dispatch protocol to confirm whether Goal Stack and ACT-R Typed Buffer CA overlays apply at the tier level (7 tiers) or the agent level (42 agents), and whether the Build tier's 11-agent sequential sub-pipeline requires separate overlay treatment. The output is a one-page resolution note appended to the U-015-007-architecture-clarification.md investigation artifact, stating the confirmed granularity for each of the five CA overlays and its implication for TASK-004's experiment scope.
**Acceptance Criteria**: Commander.md inspected and dispatch protocol documented; granularity ambiguity (tier vs agent level) resolved for Goal Stack and ACT-R Typed Buffer with specific citation to the dispatch protocol; resolution note states the overlay targeting scope that TASK-004's experiment specification should assume; ISS-001 marked RESOLVED in issues.md.
**Effort**: Quick
**Depends on**: None
**Priority**: High

---

### TASK-010: Final Proof Status Review Against Source Files
**REQ**: REQ-015-001
**Scope**: A cross-reference review confirming that all 17 rows in the proof status table (TASK-001 output) are cited correctly against the SCOUT discovery files (mental-model.md, boundaries.md) and the INVESTIGATOR artifacts (U-015-002-novelty-search.md, U-015-007-architecture-clarification.md). Verifies: all 17 rows present, no row omitted, no verdict cell softened, SPECULATION labels intact on two P5 rows, GATE-CONDITIONED labels intact on five CA overlay rows, NS-003-A and NS-003-B arxiv IDs traceable to verified preprints. Any discrepancies are corrected in the proof status table artifact before delivery.
**Acceptance Criteria**: All 17 rows confirmed against mental-model.md Section 4 — count verified, no omissions; all arxiv IDs (2510.09355, 2603.17244) verified as corresponding to the cited papers (NL2GenSym, Kumiho) from INVESTIGATOR verification; no verdict cell contains "believed," "expected," or "likely" without a supporting citation (AC-SPEC-001); SPECULATION labels on P5 rows not softened (AC-SPEC-003); CA overlay gate conditions present in proof table (AC-SPEC-002).
**Effort**: Quick
**Depends on**: TASK-001
**Priority**: MVP

---

### TASK-011: Risk Register for Baseline Measurement Tasks
**REQ**: REQ-015-003, REQ-015-004, REQ-015-005
**Scope**: A concise risk register documenting the specific risks for the three baseline measurement tasks and their mitigations, covering: (1) prior run logs lacking token count data for REQ-015-003 — mitigation: forward-looking instrumentation and symbolic break-even in TASK-008; (2) single-annotator availability for REQ-015-004 — mitigation: explicit limitation statement per AC-004-003; (3) contradiction detection method precision for REQ-015-005 — mitigation: 5-sample manual precision review and upper/lower bound characterization; (4) fewer than 9 adjacent artifact pairs available for REQ-015-007 — mitigation: explicit N disclosure and small-sample limitation statement. The register maps each risk to severity, affected REQ, mitigation action, and residual risk after mitigation.
**Acceptance Criteria**: All four identified risks documented with severity rating, affected REQ, mitigation action, and residual risk; mitigations align with the explicit disclosure obligations in the relevant AC (AC-003-005, AC-004-003, AC-005-004, AC-005-005, AC-007-001); register is attached as an appendix to feasibility.md or issued as a standalone risk artifact.
**Effort**: Quick
**Depends on**: None
**Priority**: Medium

---

### TASK-012: Finalization and Delivery
**REQ**: All REQs
**Scope**: Final delivery package assembly confirming all MVP artifacts are complete and consistent. Covers: (1) proof status table (TASK-001 + TASK-010 review), (2) novelty search record (TASK-002), (3) NS-003 experiment design (TASK-003), (4) U-CA-004 experiment specification (TASK-004), (5) scope violation baseline (TASK-005). Verifies that AC-SPEC-001 through AC-SPEC-005 are satisfied across all artifacts in combination — specifically that CA overlay gate conditions are consistent across the proof table, experiment designs, and any summary sections; SPECULATION labels are not softened in any artifact; and the novelty search record is reproducible as a standalone document. Post-MVP deferred artifacts (TASK-006 through TASK-008) are noted as in-progress with their current status.
**Acceptance Criteria**: All five MVP artifacts present and internally consistent; CA overlay GATE-CONDITIONED label consistent across proof table, TASK-003 design, and TASK-004 specification (AC-SPEC-002); SPECULATION label on NOVEL-004 40-70% claim present in proof table and in any summary (AC-SPEC-003); novelty search record standalone and reproducible (AC-SPEC-004); experiment designs (TASK-003, TASK-004) pass third-party executability check — no metric formula, threshold, evaluation set method, codebase selection criterion, or decision rule requires external clarification (AC-SPEC-005).
**Effort**: Quick
**Depends on**: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-010
**Priority**: MVP

---

## Priority Summary

| Task | REQ | Priority | Effort | Depends On |
|------|-----|----------|--------|-----------|
| TASK-001 | REQ-015-001 | MVP | Quick | None |
| TASK-002 | REQ-015-002 | MVP | Quick | None |
| TASK-003 | REQ-015-006 | MVP | Medium | None |
| TASK-004 | REQ-015-008 | MVP | Medium | None |
| TASK-005 | REQ-015-004 | MVP | Medium | None |
| TASK-006 | REQ-015-003 | High | Medium | None |
| TASK-007 | REQ-015-005 | High | Medium | TASK-005 (corpus) |
| TASK-008 | REQ-015-007 | Medium | Medium | TASK-006 (soft) |
| TASK-009 | U-015-007 | High | Quick | None |
| TASK-010 | REQ-015-001 | MVP | Quick | TASK-001 |
| TASK-011 | REQ-015-003/004/005 | Medium | Quick | None |
| TASK-012 | All REQs | MVP | Quick | TASK-001,002,003,004,005,010 |
