# Learnings — Spec 015
**Agent**: FINALIZE | **Run**: squad-1775154996 | **Date**: 2026-04-02

---

## L-001: Evidence Stratification Pattern (P1-P5) is Reusable

The five-tier proof category framework established by SCOUT and applied throughout this run is a reusable pattern for any research validation spec. The taxonomy — P1 (Proven by Paper), P2 (Proven by Design), P3 (Requires Prototype), P4 (Gate-Conditioned), P5 (Speculation) — can be applied to any spec that asserts outcomes based on prior literature, design logic, or experimental design. The key discipline is that each tier requires a stated evidence source: P1 requires a DOI or arxiv ID with measured results on a comparable task; P2 requires a formal CS/formal methods foundation with logical derivation; P3 requires a structural analog and a prototype specification; P4 requires a named gate experiment with a pre-registered decision rule; P5 requires an explicit "SPECULATION: no empirical grounding" label. This pattern prevented inflation (no P5 claim was upgraded to P3 based on analogy alone) and produced a 17-row table that a third party can audit without author clarification.

**When to apply**: Any spec that (a) asserts outcomes using cited prior work, (b) has claims at different proof maturity levels, or (c) needs to answer the question "what is actually proven versus what requires further work" at the end of a research phase.

---

## L-002: Systematic Novelty Search Methodology

The 8-query novelty search protocol executed in U-015-002 is a reusable methodology for confirming novelty claims in future research specs. The protocol elements that make it reproducible are: (a) state each query string verbatim as executed — not paraphrased; (b) record the date of execution to the day; (c) record result count per database; (d) for each result, record its disposition (not matching the conjunction / matching / partial match) with a brief differential analysis; (e) explicitly acknowledge search tool limitations (JavaScript-rendered interfaces, API rate limits, non-English literature not covered); (f) use the AC-002-003 phrasing boundary — "no prior literature found in the reviewed corpus as of [date]," not "no prior literature exists."

The specific AC-002-004 escalation rule is important: if any result matches the full conjunction, the novelty claim must be revised to "novel extension of [prior work]" with a differential analysis — not suppressed. This prevents novelty claim inflation and forces honest comparative positioning.

**When to apply**: Any spec that makes a novelty claim as a key value driver. The search record must be a standalone artifact (not embedded in the proof status table) to enable independent re-execution.

---

## L-003: Gate-Conditioned Claims Require Pre-Registered Experiment Specifications

The pattern of labeling claims as "GATE-CONDITIONED on [experiment name]" and producing a pre-registered experiment specification document (u-ca-004-experiment-spec.md) in the same spec run is more valuable than deferring the specification to the gate execution phase. Without the pre-registered decision rule, an experiment can produce ambiguous results that are interpreted opportunistically. The pre-registration must cover: three conditions with the same LLM version locked across conditions; sample size with power rationale; evaluation rubric with metric formulas and scoring anchors; and a decision rule that maps POSITIVE / NEGATIVE / INCONCLUSIVE outcomes to concrete actions (unlock implementation / terminate program / follow-up with doubled N).

The additional insight from this run: gate conditions should specify one overlay at a time. Testing all five CA overlays simultaneously without accounting for interaction effects is a confound — the U-CA-004 spec explicitly states this and names the recommended first overlay (with rationale) and the contingent order for subsequent overlays.

**When to apply**: Any claim that is conditioned on an experiment not yet run. The experiment specification must be produced in the same spec run as the gate-conditioned claim — not deferred.

---

## L-004: Speculation Labels Have Permanence Rules

The AC-SPEC-003 pattern — "the SPECULATION label cannot be removed or softened based on retrospective analysis alone; upgrading requires N=50+ prototype measurement runs" — is a precedent for future research specs that need to prevent premature claim promotion. The key elements: (a) the minimum measurement count (N=50) is stated explicitly and is non-negotiable via analogy or calibration alone; (b) the label "SPECULATION: no empirical grounding" is not softened to "probable," "likely," or "supported" even if a retrospective calibration shows favorable results; (c) the label appears in multiple locations (proof status table, calibration artifact, any summary section) so it cannot be removed from one location while remaining in another.

The structural insight is that REQ-015-007 (NOVEL-004 calibration) can provide a go/no-go recommendation for prototype investment without removing the SPECULATION label — the calibration informs resource allocation, not claim status. These are two separate decisions that must not be conflated.

**When to apply**: Any quantitative prediction claim with no direct measurement. The SPECULATION label and its upgrade criteria must be stated in the spec before any retrospective analysis is conducted.

---

## L-005: WHY1/WHY2 Iteration Fixed All Issues — The Threshold Conflict Pattern

This run demonstrated that a two-pass SAGE validation (WHY1 + WHY2) is effective for catching and resolving conflicting thresholds across documents produced by different agents in the same run. ISS-001 in this run — the NS-003-B acceptance threshold was 0.75 in AC-006-005 but 0.80 in mental-model.md's Proof Topology Table — is a specific class of error that arises when CARTOGRAPHER writes spec ACs using one number and SCOUT's discovery document uses another. This type of cross-document inconsistency is invisible to a single-pass review but becomes detectable when SAGE explicitly cross-references ACs against the SCOUT discovery evidence map.

The resolution pattern (WHY1 flags → CARTOGRAPHER fixes → WHY2 verifies all 5 fixed, 0 remaining) worked cleanly in this run. The WHY1→WHY2 delta of +0.13 overall (0.78 → 0.91) was driven primarily by Readability (+0.48, from 0.40 to 0.88), which reflects the Statement reformatting from 38-65 word dense prose to short imperative + bulleted breakdown. The readability fix had the largest individual delta because it was a spec-wide structural problem, not a localized one. Future specs should format Statements in the short-imperative + bulleted breakdown form from the first draft to avoid this systematic deduction.

**When to apply**: Always run two SAGE passes. The first pass finds issues; the second pass verifies they are resolved, not merely acknowledged. A WHY2 score should be the final quality signal for gate decisions.
