# Quality Gate Report — WHY1
**Agent**: SAGE | **Pass**: WHY1 | **Date**: 2026-04-02
**Run**: squad-1775154996 | **Spec**: 015

## Dimension Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Structure | 0.93 | All 8 REQs carry Statement, Rationale, ACs, Evidence Gate, Blocked-by. Minor: AC-001-002 "non-empty" is accepted given surrounding field list precision. |
| Testability | 0.82 | REQ-015-006 and REQ-015-008 both contain metric formulas (first-pass compliance, contradiction catch rate, break-even formula, AQS formula). Deduction: AC-007-002 prediction accuracy scoring relies on evaluator judgment ("could have been predicted") without a decision rubric anchoring the 0-100% score — a third party cannot determine PASS/FAIL without author clarification on scoring anchors. |
| Semantic | 0.78 | Claims consistent with SCOUT evidence map throughout. SPECULATION labels verified in 3 locations. 17-row count matches mental-model.md Section 4 (1+1+1+1+1+5+1+6=17). One inflation-risk discrepancy: AC-006-005 uses NS-003-B threshold of ≥ 0.75 (consistent with boundaries.md) but mental-model.md Proof Topology states the "What Would Constitute Full Proof" threshold for NS-003-B is ≥ 80%. A third party reading both files will encounter conflicting thresholds for NS-003-B acceptance. |
| Cognitive | 0.72 | REQ-015-007 dependency on REQ-015-003 is correctly described. However Section 7 contains a direct self-contradiction: "No requirement in this spec is blocked by another requirement's completion" immediately precedes acknowledgment of the REQ-015-007 soft dependency on REQ-015-003. Also, REQ-015-007's "Blocked by" field lists U-015-006 (the unknown this REQ resolves), not REQ-015-003 (the actual soft blocker) — a circular reference error. |
| Readability | 0.40 | All 8 formal Statements exceed 25 words. None are split into an intro line followed by a bulleted breakdown. REQ-015-001 Statement is 65 words; REQ-015-006 Statement is 62 words; REQ-015-008 Statement is 58 words. This is a consistent, spec-wide failure against the 25-word formal statement rule. |
| **Overall** | **0.78** | Structure×0.25(0.23) + Testability×0.30(0.25) + Semantic×0.25(0.20) + Cognitive×0.10(0.07) + Readability×0.10(0.04) = 0.78 |

## Gate Result: PASS

Overall score 0.78 exceeds the 0.72 gate threshold. The spec is sound enough to proceed, subject to the issues below being addressed by CARTOGRAPHER before implementation begins.

---

## Issues Found

### ISS-001 [HIGH]: NS-003-B acceptance threshold conflict between spec and mental-model

- **Location**: AC-006-005 (REQ-015-006), mental-model.md Proof Topology Table row for NS-003-B
- **What's wrong**: AC-006-005 sets the NS-003-B contradiction catch rate acceptance threshold at ≥ 0.75. The mental-model.md Proof Topology Table states the "What Would Constitute Full Proof" threshold for NS-003-B is "Contradiction catch rate ≥ 80%." A third party running the experiment sees two different thresholds in the authoritative documents: 75% from the spec, 80% from the discovery evidence map. The SCOUT discovery was also aware of both: boundaries.md Section 2 states ≥ 75%, but the Proof Topology Table uses 80%. The spec must resolve this conflict explicitly, not leave it to implementer interpretation.
- **What fix is needed**: CARTOGRAPHER must pick one threshold and make it consistent across (a) AC-006-005 in REQ-015-006, (b) the Proof Topology Table "What Would Constitute Full Proof" cell for NS-003-B in mental-model.md (if that file is under CARTOGRAPHER's authority to update), and (c) any related evidence gate text. Whichever threshold is chosen, the rationale for the choice (e.g., "75% chosen as minimum viable acceptance; 80% as full-proof target") should be stated in AC-006-005 to prevent future re-emergence of the ambiguity.
- **Responsible agent**: CARTOGRAPHER

---

### ISS-002 [MEDIUM]: Section 7 self-contradiction on blocking relationships

- **Location**: Section 7 (Dependencies and Sequencing), final paragraph
- **What's wrong**: The final sentence states "No requirement in this spec is blocked by another requirement's completion." The immediately preceding sentence acknowledges "REQ-015-007 (NOVEL-004 calibration) depends on REQ-015-003 for break-even formula instantiation." These two sentences directly contradict each other. A third party reading Section 7 cannot determine whether the spec intends REQ-015-007 to be a dependent or fully independent requirement. The sentence "No requirement in this spec is blocked" is false as written.
- **What fix is needed**: CARTOGRAPHER must remove or correct the contradicting sentence. The accurate statement is: "All eight requirements can proceed in parallel, with REQ-015-007 carrying a soft dependency on REQ-015-003 for break-even instantiation; if REQ-015-003 is not yet complete, REQ-015-007 proceeds in symbolic form per AC-007-004." The false absolute ("No requirement is blocked") must be deleted.
- **Responsible agent**: CARTOGRAPHER

---

### ISS-003 [MEDIUM]: REQ-015-007 "Blocked by" field is a circular reference

- **Location**: REQ-015-007 "Blocked by" field
- **What's wrong**: The "Blocked by" field lists "U-015-006 (Prediction Accuracy Not Calibrated — this REQ resolves it)." A requirement cannot be blocked by the unknown it is designed to resolve — that is a circular reference. The note "this REQ resolves it" immediately reveals the circularity. The actual soft blocker for REQ-015-007 is REQ-015-003 (for break-even formula instantiation), which is correctly identified later in the same "Blocked by" paragraph. The U-015-006 listing is misleading and will cause a third party to believe REQ-015-007 cannot proceed until something external unblocks it — when in fact REQ-015-007 is the unblocking action.
- **What fix is needed**: CARTOGRAPHER must revise the "Blocked by" field for REQ-015-007 to remove U-015-006 as a blocker and state only the actual soft dependency: "Break-even formula instantiation is softly blocked by REQ-015-003 completion; proceed with symbolic form per AC-007-004 if REQ-015-003 is not yet available." The statement that this REQ resolves U-015-006 belongs in the Rationale, not the Blocked-by field.
- **Responsible agent**: CARTOGRAPHER

---

### ISS-004 [MEDIUM]: AC-007-002 lacks a scoring rubric for prediction accuracy assessment

- **Location**: AC-007-002 (REQ-015-007)
- **What's wrong**: AC-007-002 asks evaluators to score each DISCOVER→ASSESS artifact pair on "what proportion of ASSESS's top-level assertions could have been predicted as 'present' or 'absent'" and produce a score from 0-100%. No rubric, anchor, or decision procedure is provided for what constitutes a 60% vs 40% vs 80% score. The evaluation method is listed as three alternatives (human assessment, LLM-as-evaluator with stated rubric, or structured extraction) but no rubric is defined for any of them. A third party cannot determine PASS/FAIL for a given pair without requesting clarification from the authors. This violates AC-SPEC-005.
- **What fix is needed**: CARTOGRAPHER must add a scoring anchor to AC-007-002. At minimum, the AC should specify: the unit of scoring (per top-level assertion, not per artifact), the prediction classification method (a specific assertion is "predictable" if it meets a stated condition — e.g., "the assertion re-states or directly follows from a finding already present in DISCOVER's output"), and the aggregation formula (predicted assertions / total top-level ASSESS assertions). The current phrasing "how much of ASSESS's output could have been predicted" is evaluator-dependent and therefore not independently testable.
- **Responsible agent**: CARTOGRAPHER

---

### ISS-005 [LOW]: All 8 formal Statements exceed 25 words; none are split into intro + bullets

- **Location**: All REQ Statements (REQ-015-001 through REQ-015-008)
- **What's wrong**: The readability rule requires formal statements to be under 25 words or split into an intro line followed by a bulleted breakdown for longer ones. Every Statement in this spec runs 38-65 words as a single unpunctuated sentence. REQ-015-001 (65 words) and REQ-015-006 (62 words) are most severe. A reader scanning the spec cannot quickly extract what each requirement demands — the structural information (table columns, metric formulas, evaluation set sizes) is embedded in prose rather than visually separated.
- **What fix is needed**: CARTOGRAPHER must reformat each Statement as: one imperative sentence of ≤ 25 words establishing the deliverable, followed by a bulleted breakdown of the key parameters or constraints. The Rationale and ACs contain the supporting detail; the Statement should capture only the imperative and its primary scope qualifier.
- **Responsible agent**: CARTOGRAPHER

---

## Summary

Spec 015 is structurally sound, has well-formed ACs for its two experiment designs (REQ-015-006 and REQ-015-008), correctly propagates the SPECULATION label and the U-CA-004 gate condition throughout, and the 17-row count is verified against the discovery evidence map. The overall score of 0.78 clears the 0.72 gate.

Five issues are flagged for CARTOGRAPHER attention before implementation begins. ISS-001 (NS-003-B threshold conflict) and ISS-003 (circular "Blocked by" reference) should be resolved first as they create decision ambiguity for implementers. ISS-002 (Section 7 self-contradiction) is a prose fix. ISS-004 (missing scoring rubric in AC-007-002) is a testability gap that will cause friction at measurement time. ISS-005 (readability) is cosmetic but affects spec usability.

No critical blockers found. Gate: PASS.

---

## WHY2 Pass
**Date**: 2026-04-02

### Fix Verification

| Issue | Fix Applied? | Notes |
|-------|-------------|-------|
| ISS-001 | YES | AC-006-005 now reads "contradiction catch rate ≥ 0.80" — up from 0.75. Threshold conflict with mental-model.md Proof Topology resolved. |
| ISS-002 | YES | Section 7 final paragraph now reads: "One soft dependency exists: REQ-015-007's break-even formula instantiation is soft-blocked by REQ-015-003…". The contradicting absolute sentence "No requirement in this spec is blocked by another requirement's completion" has been deleted. |
| ISS-003 | YES | REQ-015-007 "Blocked by" field now reads: "Soft: REQ-015-003 (token baseline) for break-even formula instantiation; all other aspects are unblocked." U-015-006 circular reference removed. |
| ISS-004 | YES | AC-007-002 now includes explicit scoring anchors (0-20% / 40-60% / 80-100%), a definition of "predictable" as "(a) explicitly stated in the upstream output, or (b) a direct logical consequence of an explicitly stated upstream finding," and a borderline scoring rule (50% per assertion). AC-SPEC-005 compliance restored. |
| ISS-005 | YES | All 8 formal Statements are now split into a short imperative intro clause followed by "This requires:" + bulleted breakdown. Verified for REQ-015-001, REQ-015-003, and REQ-015-007 (and confirmed consistent across REQ-015-002, -004, -005, -006, -008). |

### WHY2 Scores

| Dimension | WHY1 | WHY2 | Delta |
|-----------|------|------|-------|
| Structure | 0.93 | 0.95 | +0.02 |
| Testability | 0.82 | 0.91 | +0.09 |
| Semantic | 0.78 | 0.88 | +0.10 |
| Cognitive | 0.72 | 0.90 | +0.18 |
| Readability | 0.40 | 0.88 | +0.48 |
| **Overall** | **0.78** | **0.91** | **+0.13** |

Overall computation: (0.95×0.25) + (0.91×0.30) + (0.88×0.25) + (0.90×0.10) + (0.88×0.10) = 0.2375 + 0.273 + 0.220 + 0.090 + 0.088 = 0.908 → rounded to **0.91**.

### WHY2 Gate: PASS

Overall score 0.91 exceeds the 0.75 WHY2 gate threshold.

### Remaining Issues

None. All 5 WHY1 issues are confirmed resolved. No new issues identified during WHY2 verification.
