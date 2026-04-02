# Excess Report — Spec 015: CA Outcomes Validation

**Date**: 2026-04-02
**Verification Pass**: 1
**Build Run**: build-1775162749 (verifying build-1775154996)
**Verifier**: VERIFICATION agent

---

## Purpose

This report identifies any implementation artifacts delivered beyond what spec.md requires. Excess implementation is not a failure condition unless it introduces risk (e.g., unauthorized CA overlay code, out-of-scope production code, spec drift).

---

## Excess Artifacts Identified

### EXCESS-001: Secondary Metric in NS-003 Experiment Design (Non-blocking)

**Artifact**: `ns003-experiment-design.md` Section 4 — Retry Resolution Rate (RRR)

**Spec requires**: Metrics with formulas for NS-003-A (first-pass compliance rate) and NS-003-B (contradiction catch rate + false positive rate). AC-006-004 specifies the FPCR formula and threshold. AC-006-005 specifies the CCR formula and FPR threshold.

**What was delivered**: The document additionally defines a Retry Resolution Rate (RRR) metric — `(invocations where Critic rejected attempt 1 but accepted attempt 2) / (invocations where Critic rejected attempt 1)` — which is not specified in AC-006-004 or AC-006-005.

**Assessment**: The RRR is a diagnostic metric marked "no acceptance threshold (secondary metric; informational)." It does not replace or conflict with any required metric. It adds value by characterizing retry prompt effectiveness. This is harmless excess that improves the experiment design's diagnostic power without violating scope. **No action required.**

---

### EXCESS-002: Baseline Comparison Section in NS-003 Experiment Design (Non-blocking)

**Artifact**: `ns003-experiment-design.md` Section 5 — Baseline Comparison (Raw Compliance Rate)

**Spec requires**: The experiment design covers fixed test codebase, evaluation set sizes, metrics with formulas, acceptance thresholds, timeline, and third-party executability (AC-006-001 through AC-006-007). No baseline comparison condition is specified.

**What was delivered**: A baseline condition is defined — 30 agent invocations without the Generator-Critic layer active, evaluated post-hoc against the same schemas to measure Raw Compliance Rate (RCR). This enables comparison between "with Critic" and "without Critic" to measure compliance lift.

**Assessment**: The baseline comparison is architecturally sound and improves the experiment's scientific validity. It does not implement any prohibited mechanism and does not claim to prove CA overlays work. **No action required.**

---

### EXCESS-003: Staged Execution Protocol in U-CA-004 Experiment Spec (Non-blocking)

**Artifact**: `u-ca-004-experiment-spec.md` Section 4 — Staged Execution Protocol

**Spec requires**: Sample size with statistical power rationale, N ≥ 10 per condition (AC-008-003). The spec does not explicitly require a staged execution protocol.

**What was delivered**: A staged protocol is specified: start with N=10 (minimum viable), apply the decision rule, double to N=20 if INCONCLUSIVE. This is an operational execution procedure not strictly required by the spec.

**Assessment**: The staged protocol implements the N=10 minimum and N=20 target requirement, and maps INCONCLUSIVE outcomes to additional N. This is compliant with AC-008-003 and adds operational clarity. **No action required.**

---

### EXCESS-004: Inter-rater Reliability Guidance in U-CA-004 Rubric (Non-blocking)

**Artifact**: `u-ca-004-experiment-spec.md` Section 6 — Cohen's kappa inter-rater guidance

**Spec requires**: Evaluation rubric with at least two primary metrics with formulas and scoring anchors. No inter-rater requirement is mandated in AC-008-005.

**What was delivered**: The rubric includes guidance on inter-rater reliability (Cohen's kappa per dimension where two evaluators are available; single-evaluator limitation statement otherwise).

**Assessment**: This matches the annotation limitation language in REQ-015-004 (AC-004-003) and extends good scientific practice to the U-CA-004 rubric. No conflict with any requirement. **No action required.**

---

## Excess Artifacts Not Found

The following were specifically checked and confirmed **not present** as excess:

- **CA overlay implementation code**: No Goal Stack, ACT-R Buffer, LIDA Broadcast, GWT Bounded Workspace, or Episodic Memory implementation code found in `scripts/`, `agents/`, or any other directory. All five overlays remain specification-only (GATE_BLOCKED).
- **Production NS-003 implementation**: No Generator-Critic loop or belief graph implementation code found. `ns003-experiment-design.md` is specification only.
- **NOVEL-004 prototype**: No forward-model prediction prototype found. `novel004-calibration.md` is retrospective analysis only.
- **Roadmap or deployment artifacts**: No production roadmap, migration plan, or deployment specification found beyond what is required by REQ-015-006 and REQ-015-008.
- **Upgraded SPECULATION labels**: No artifact was found that upgrades the NOVEL-004 40-70% token reduction claim from SPECULATION to any higher confidence category.

---

## Summary

| Excess Item | Type | Risk | Action |
|------------|------|------|--------|
| EXCESS-001: RRR secondary metric | Additional metric (informational) | None | None |
| EXCESS-002: Baseline comparison condition | Additional scientific rigor | None | None |
| EXCESS-003: Staged execution protocol | Operational detail | None | None |
| EXCESS-004: Inter-rater reliability guidance | Scientific best practice | None | None |

**Verdict**: No excess implementation poses a risk or violates spec constraints. All excess items improve the quality or executability of the deliverables without expanding scope into prohibited territory.
