# Issues — Spec 015 (CA Outcomes Validation)
**Agent**: SAGE | **Phase**: WHY1 | **Date**: 2026-04-02
**Run**: squad-1775154996

---

## ISS-001 [HIGH] — **RESOLVED** (2026-04-02, TASK-009): Architecture Ambiguity — Goal Stack and ACT-R Buffer Granularity

- **Location**: AC-006-005 (REQ-015-006), mental-model.md Proof Topology Table (NS-003-B row)
- **Original issue**: ISS-001 as filed by SAGE described a threshold conflict. **Note**: The ISS-001 identifier was also used for the architecture ambiguity flagged in the GATEKEEPER feasibility assessment (REQ-015-008: "ISS-001 architecture ambiguity on Goal Stack / ACT-R buffer tier-level vs agent-level granularity"). This resolution addresses the architecture ambiguity.
- **Resolution** (from U-015-007-architecture-clarification.md § Resolution Note — TASK-009):
  - **Goal Stack**: agent-level (up to 42 entries). COMMANDER dispatches individual named agents, not tiers. EVOI checks operate per-agent. Goal Stack entries must reference individual agent dispatch states.
  - **ACT-R Buffer**: tier-level for buffer type classification (7 buffer types = 7 cognitive functions); agent-dispatch level for buffer content and token budget tracking. No single agent may consume more than 40% of total budget — enforced per dispatch.
  - **Build tier**: requires separate overlay treatment. It is a conditionally-invoked sequential sub-pipeline (state machine), structurally distinct from the 6 EVOI-gated analysis tiers.
  - **Impact on U-CA-004 experiment spec**: CA overlay targeting should be specified at agent-dispatch level, not tier level.
- **Responsible agent**: IMPLEMENTER (TASK-009) | **Status**: RESOLVED

---

## ISS-002 [MEDIUM]: Section 7 self-contradiction on blocking relationships

- **Location**: Section 7 (Dependencies and Sequencing), final paragraph
- **What's wrong**: The final sentence reads "No requirement in this spec is blocked by another requirement's completion." The preceding sentence acknowledges the REQ-015-007 soft dependency on REQ-015-003. These two statements directly contradict each other. The absolute "no requirement is blocked" is false as written.
- **What fix is needed**: CARTOGRAPHER must delete or correct the contradicting sentence. The accurate formulation is that all requirements can proceed in parallel, with REQ-015-007 carrying a soft dependency on REQ-015-003 for break-even instantiation; if REQ-015-003 is not yet complete, REQ-015-007 proceeds symbolically per AC-007-004.
- **Responsible agent**: CARTOGRAPHER

---

## ISS-003 [MEDIUM]: REQ-015-007 "Blocked by" field is a circular reference

- **Location**: REQ-015-007 "Blocked by" field
- **What's wrong**: The "Blocked by" field lists "U-015-006 (Prediction Accuracy Not Calibrated — this REQ resolves it)." A requirement cannot be blocked by the unknown it is designed to resolve. The parenthetical "this REQ resolves it" confirms the circularity. The actual soft blocker is REQ-015-003, which is also mentioned in the same field but subordinated to the circular U-015-006 reference.
- **What fix is needed**: CARTOGRAPHER must remove U-015-006 from the "Blocked by" field. The field should state only the actual soft dependency: REQ-015-003 for break-even formula instantiation, with the note that symbolic form is used if REQ-015-003 is not yet complete. The statement that this REQ resolves U-015-006 belongs in the Rationale section.
- **Responsible agent**: CARTOGRAPHER

---

## ISS-004 [MEDIUM]: AC-007-002 lacks a scoring rubric for prediction accuracy assessment

- **Location**: AC-007-002 (REQ-015-007)
- **What's wrong**: AC-007-002 requires evaluators to score each DISCOVER→ASSESS artifact pair 0-100% on "what proportion of ASSESS's top-level assertions could have been predicted as 'present' or 'absent'." No rubric, anchor, or decision criterion is provided. Three evaluation method options are listed (human, LLM-as-evaluator, structured extraction) without a rubric for any. A third party cannot determine PASS/FAIL for a given pair without author clarification, violating AC-SPEC-005.
- **What fix is needed**: CARTOGRAPHER must add to AC-007-002: (a) the unit of scoring (per top-level assertion), (b) the condition under which an assertion is classified as "predictable" (stated as a rule, e.g., "an assertion is predictable if it re-states or directly follows from a finding already present in DISCOVER's output"), and (c) the aggregation formula (predicted assertions / total top-level ASSESS assertions × 100%). Without these three elements, the score is evaluator-dependent.
- **Responsible agent**: CARTOGRAPHER

---

## ISS-005 [LOW]: All 8 formal Statements exceed 25 words; none split into intro + bullets

- **Location**: All REQ Statements (REQ-015-001 through REQ-015-008)
- **What's wrong**: Every formal Statement runs 38-65 words as a single dense sentence. The readability rule requires statements to be under 25 words, or to be split into a short imperative sentence followed by a bulleted breakdown of parameters. The current format buries key constraints (table columns, evaluation set sizes, metric formulas) inside prose, reducing scannability.
- **What fix is needed**: CARTOGRAPHER must reformat each Statement as: one imperative sentence ≤ 25 words identifying the deliverable, followed by a bulleted list of the key parameters or constraints. Detail belongs in Rationale and ACs, not the Statement.
- **Responsible agent**: CARTOGRAPHER
