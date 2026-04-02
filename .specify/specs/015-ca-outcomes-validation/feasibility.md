# Feasibility Assessment — Spec 015
**Agent**: GATEKEEPER | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02

---

## REQ Feasibility Table

| REQ | Title | Feasibility | Effort Tier | Value | Priority Rank |
|-----|-------|-------------|-------------|-------|---------------|
| REQ-015-001 | Claim Proof Status Table | HIGH | Quick (hours) | Critical | 1 |
| REQ-015-002 | NS-003 Novelty Confirmation | HIGH | Quick (complete) | Critical | 2 |
| REQ-015-006 | NS-003 Prototype Experiment Design | HIGH | Medium (1-2 days) | High | 3 |
| REQ-015-008 | U-CA-004 Gate Experiment Specification | HIGH | Medium (1-2 days) | High | 4 |
| REQ-015-004 | Scope Violation Rate Baseline | HIGH | Medium (1-2 days) | High | 5 |
| REQ-015-005 | Contradiction Rate Baseline | HIGH | Medium (1-2 days) | High | 6 |
| REQ-015-007 | NOVEL-004 Prediction Accuracy Calibration | HIGH (soft dep on REQ-015-003) | Medium (1-2 days) | Medium | 7 |
| REQ-015-003 | Token Efficiency Baseline | MEDIUM | Medium (1-2 days) | Medium | 8 |

---

## Feasibility Verdicts

### REQ-015-001: Claim Proof Status Table

**Feasibility: HIGH.** All 17 rows from the Proof Topology Table in mental-model.md Section 4 are already populated with evidence grades, proof categories, proof status labels, evidence source IDs, and "What Would Constitute Full Proof" fields. The SCOUT discovery files (mental-model.md, boundaries.md) and INVESTIGATOR verification (U-015-002-novelty-search.md) supply every citation needed. This REQ requires assembly work — populating a structured output artifact from pre-assembled source material — not new research or code. The main risk is mechanical: ensuring all 17 rows are present, that AC-001-003 through AC-001-005 wording constraints are satisfied verbatim, and that the SPECULATION labels are not softened. Zero external dependencies.

### REQ-015-002: NS-003 Novelty Confirmation

**Feasibility: HIGH (effectively complete).** The INVESTIGATOR artifact U-015-002-novelty-search.md contains the full systematic search record: 8 query variants, databases queried (Google-indexed scholarly content and Semantic Scholar proxy), date of execution (2026-04-02), result count with disposition table for each result, paper verification of NL2GenSym and Kumiho, and a properly-hedged novelty verdict ("No prior literature found in the reviewed corpus as of 2026-04-02"). All AC-002-001 through AC-002-005 acceptance criteria can be verified against this artifact. The remaining work is producing the standalone search record artifact as a formatted deliverable that cites the investigation file as its source. This is under one hour of formatting work.

### REQ-015-003: Token Efficiency Baseline

**Feasibility: MEDIUM.** No prior token logging exists in the squad's reasoning-journal.json schema; squad-config.yml sets token_budget_k=999999 (unlimited), confirming the pipeline has never been instrumented for token measurement. Forward-looking instrumentation requires modifying agent invocation code to capture prompt + completion tokens per call. The plan.md Access Model confirms post-call token count introspection is available, so the instrumentation is technically straightforward. The blocking constraint is that at least 3 completed spec runs must be collected after instrumentation is in place — this is a pipeline execution dependency, not just a coding task. If the squad can run 3 new spec runs under the instrumented pipeline within the delivery window, this is achievable. If not, it is the only REQ that may require time-boxing. Risk: moderate. Value: medium (the baseline enables REQ-015-007's break-even formula but REQ-015-007 can proceed in symbolic form without it).

### REQ-015-004: Scope Violation Rate Baseline

**Feasibility: HIGH.** The artifact corpus exists: spec runs 008-014 are available for annotation. The annotation scheme is clearly defined in AC-004-001 through AC-004-005 (IN-SCOPE / OUT-OF-SCOPE / BORDERLINE per section, against each agent's declared scope from its prompt definition). The principal risk is annotator availability — the spec requires at least one annotator and reports inter-annotator agreement where a second is available. A single-annotator run with explicit limitation statement satisfies the acceptance criteria. The ISS-001 evidence from spec 014 (ASSESS reproducing DISCOVER findings) gives a concrete starting hypothesis to test. No external dependencies. Estimated as 1-2 days of focused annotation effort.

### REQ-015-005: Contradiction Rate Baseline

**Feasibility: HIGH.** The artifact corpus (spec runs 008-014) is available. The detection method selection (exact string match, semantic embedding similarity, or LLM classifier) is at the implementer's discretion as long as it is stated and applied consistently. A lightweight LLM-classifier approach against structured sections is well within current tooling. The requirement to manually review 5 detected contradictions for precision estimation (AC-005-004) is achievable with the same artifact corpus. The main risk is that the detection method has poor recall on soft contradictions in prose — but AC-005-005 explicitly permits acknowledging this as a lower bound, which is an honest and sufficient result. No external dependencies.

### REQ-015-006: NS-003 Prototype Experiment Design

**Feasibility: HIGH.** This is design-only work — no prototype needs to be built. All input parameters are derivable from spec 014 artifacts and spec 015: the acceptance thresholds (≥70% first-pass compliance for NS-003-A, ≥80% contradiction catch rate for NS-003-B), evaluation set sizes (N=30 for NS-003-A, N=20 for NS-003-B), contradiction injection method choices, timeline phases, and third-party executability criterion. The main risk is precision of formulation: AC-006-007 requires the design be specific enough that a third party needs no clarification on metrics, thresholds, or evaluation set construction. This is a writing discipline risk, not a knowledge gap — all parameters are already defined in the spec. Estimated 1-2 days to write and self-check against all 7 acceptance criteria.

### REQ-015-007: NOVEL-004 Prediction Accuracy Calibration

**Feasibility: HIGH (with soft dependency acknowledged).** The artifact pairs for retrospective calibration exist (spec runs 008-014 provide up to 7 DISCOVER→ASSESS pairs; additional adjacent pairs may bring the count to N=9+). AC-007-002's scoring rubric (0-20% / 40-60% / 80-100% anchor bands for predictability) is fully specified. The break-even formula can be stated symbolically if REQ-015-003 token baseline is not yet complete — AC-007-004 explicitly permits this. The go/no-go recommendation logic (AC-007-006) is deterministic once the mean and standard deviation are computed. Risk: if fewer than 9 adjacent pairs are available from the existing corpus, the artifact must explicitly state N and the small-sample limitation — this is a disclosure obligation, not a blocking failure. The SPECULATION label on the 40-70% range is preserved regardless of outcome, per AC-007-005 and AC-SPEC-003. No hard external dependencies.

### REQ-015-008: U-CA-004 Gate Experiment Specification

**Feasibility: HIGH.** This is specification-only work — the gate experiment itself is a post-spec execution task estimated at 4-6 weeks. All parameters needed for the specification are derivable from current artifacts: the three-condition design (Naive / Expert-Prompt / CA-Structured), LLM version locking, sample size power rationale (N=10 minimum viable vs N=20 for 80% power), codebase selection strategy options, Artifact Quality Score rubric with four dimensions, and pre-registered decision rule. The INVESTIGATOR's architecture clarification (42 agents, 7 tiers, per-EVOI agent dispatch) resolves the granularity question for CA overlay targeting. The ISS-001 architecture ambiguity on Goal Stack / ACT-R buffer tier-level vs agent-level granularity is flagged in the INVESTIGATOR report and should be explicitly noted as an open design decision in the experiment spec. The main risk is the recommendation on which CA overlay to test first — this requires a judgment call that is well-supported by the evidence hierarchy (ACT-R Typed Buffer has Grade A problem evidence via "Lost in the Middle" and is most directly testable without full system redesign). Estimated 1-2 days of writing and self-check against all 7 acceptance criteria.

---

## Risk Summary

| Risk | Affects | Severity | Mitigation |
|------|---------|----------|-----------|
| Token logging requires 3 new forward-looking runs | REQ-015-003 | Medium | Proceed with symbolic break-even in REQ-015-007; REQ-015-003 is MVP-deferred |
| Single-annotator for REQ-015-004 | REQ-015-004 | Low | Explicitly state single-annotator limitation per AC-004-003 |
| Semantic Scholar JS rendering limits native search API | REQ-015-002 | Low | Already mitigated in U-015-002 by proxy search; limitation explicitly stated |
| N < 9 adjacent pairs from available runs | REQ-015-007 | Low | Disclose N and small-sample limitation per AC-007-001 |
