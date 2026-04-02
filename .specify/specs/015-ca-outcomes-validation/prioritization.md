# Prioritization — Spec 015
**Agent**: GATEKEEPER | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02

---

## Scoring Method

Each REQ is scored on three dimensions: **Value** (Critical=4, High=3, Medium=2, Low=1), **Feasibility** (High=3, Medium=2, Blocked=0), and **Urgency** (now=3, after-MVP=2, time-gated=1). Score = Value × Feasibility × Urgency. Rankings are then adjusted for dependency — a REQ that unblocks others receives a one-rank bonus.

---

## Ranked Requirements

### Rank 1: REQ-015-001 — Claim Proof Status Table
**Score: 36 (4 × 3 × 3)**

This is the spec's primary deliverable. It directly answers the user's question for all 17 claims simultaneously. It has no dependencies, all evidence is assembled, and SCOUT and INVESTIGATOR have pre-staged everything needed. REQ-015-001 should be the first artifact produced. A BUILDER agent can populate this table in hours using mental-model.md Section 4 as the source structure. Every other REQ either feeds into or builds upon the proof status categories established here.

**Rationale for Rank 1**: Highest value, highest feasibility, highest urgency. Nothing else can be called "done" until the 17-row verdict table exists.

---

### Rank 2: REQ-015-002 — NS-003 Novelty Confirmation
**Score: 36 (4 × 3 × 3)**

INVESTIGATOR has completed all the work; the remaining step is producing the formatted standalone artifact. This REQ ties with REQ-015-001 on score. It is ranked second because REQ-015-001's proof status table cites the novelty claim result, so the table should reference a completed artifact — logical ordering puts REQ-015-002 as a simultaneous or immediate follow-on to REQ-015-001, not after.

**Rationale for Rank 2**: Effectively complete; one hour to formalize. Novelty claim is the most falsifiable claim in spec 014 and its defensibility depends on this artifact existing as a standalone, reproducible record.

---

### Rank 3: REQ-015-006 — NS-003 Prototype Experiment Design
**Score: 27 (3 × 3 × 3)**

NS-003 is the only claim that (a) has Grade A component evidence, (b) is independent of U-CA-004, and (c) does not require a 4-6 week experiment to reach the next decision point. REQ-015-006 converts the partially-proven NS-003 claim into an "actionable next step" with a fully specified experiment. Its urgency is high because the squad cannot commit to NS-003 prototype implementation without it. All parameters are derivable from existing artifacts; no new research is needed.

**Rationale for Rank 3**: Highest-ROI design task. NS-003 is the primary architecture recommendation; specifying how to validate it on Echelon's actual artifact protocol is the critical enabler for follow-on engineering work.

---

### Rank 4: REQ-015-008 — U-CA-004 Gate Experiment Specification
**Score: 27 (3 × 3 × 3)**

The U-CA-004 gate blocks 5 of the 17 proof topology rows plus their 4 associated use case claims. That gate has a 4-6 week execution timeline. Every day the specification is not complete, the clock on that 4-6 week commitment has not started. REQ-015-008 is rated urgent because the resource allocation decision (commit ~6 weeks of squad capacity to the gate experiment) cannot be made until the experiment specification exists as a pre-registered design artifact. The specification itself has zero dependencies.

**Rationale for Rank 4**: Ties with REQ-015-006 on score. Ranked below it because NS-003 is the primary architecture (independent of the gate) while the CA overlays are all gate-conditioned. However, the 4-6 week lead time on U-CA-004 execution makes the specification timing-critical — the sooner it is written, the sooner execution can begin.

---

### Rank 5: REQ-015-004 — Scope Violation Rate Baseline
**Score: 18 (3 × 3 × 2)**

This baseline measurement is required before the improvement claims of NS-003 Critic, AC-3, and NOVEL-002 Phi-proxy have a quantity to improve on. It is also a prerequisite for the Artifact Quality Score rubric in REQ-015-008 (AC-008-005 lists Scope Violation Rate as an acceptable primary metric). The artifact corpus is available; annotation is feasible within 1-2 days. Urgency is rated "after-MVP" rather than "now" because REQ-015-001 through REQ-015-002 must be produced first, but REQ-015-004 should follow immediately. Within the MVP set, this is the last element needed to complete the full answer.

**Rationale for Rank 5**: In MVP. Enables quantification of the scope violation problem that NS-003 and AC-3 are designed to solve. Direct input to REQ-015-008's evaluation rubric.

---

### Rank 6: REQ-015-005 — Contradiction Rate Baseline
**Score: 18 (3 × 3 × 2)**

REQ-015-005 uses the same artifact corpus and similar effort as REQ-015-004. Its value is High because NS-003-B's motivation depends on demonstrating that the current contradiction rate is non-trivial. If the baseline contradiction rate is near zero, NS-003-B's urgency is weakened; if high, it is strengthened. Either outcome is evidence-based rather than assumed. Ranked below REQ-015-004 because REQ-015-004 feeds REQ-015-008 directly (Scope Violation Rate is a named primary metric in AC-008-005), while REQ-015-005 feeds NS-003-B motivation without blocking any other acceptance criterion.

**Rationale for Rank 6**: Strong second-day deliverable after MVP. Same corpus as REQ-015-004; natural pair to execute together. Deferred from hard MVP but should follow immediately.

---

### Rank 7: REQ-015-007 — NOVEL-004 Prediction Accuracy Calibration
**Score: 12 (2 × 2 × 3)**

REQ-015-007 is technically feasible (artifact pairs exist) but has a soft dependency on REQ-015-003 for the break-even formula instantiation. The SPECULATION label on NOVEL-004 is preserved regardless of outcome, which limits the value of the calibration for the primary proof status question. The go/no-go recommendation for prototype investment is genuinely useful — it prevents wasted engineering effort on NOVEL-004 if the retrospective prediction accuracy falls well below break-even. Urgency is rated high because if the calibration returns a GO signal, it accelerates the NOVEL-004 prototype decision; if it returns NO-GO, it saves weeks of engineering effort. However, value is Medium because the primary spec 014 verdict on NOVEL-004 does not change.

**Rationale for Rank 7**: Feasibility receives a Medium score because it depends on REQ-015-003 for full break-even instantiation (though it can proceed in symbolic form). Schedule after REQ-015-003 is underway; begin symbolic form immediately if token baseline instrumentation has started but not completed.

---

### Rank 8: REQ-015-003 — Token Efficiency Baseline
**Score: 8 (2 × 2 × 2)**

REQ-015-003 is ranked last because it is the only REQ with a time-gate external to the writing and annotation workflow. It requires forward-looking instrumentation plus at least 3 completed spec runs — the run time is a hard floor that cannot be shortened by effort. Its direct value is Medium: it enables REQ-015-007's break-even formula but REQ-015-007 proceeds without it. Its indirect value is higher (all token efficiency claims become measurable baseline once this exists), but the indirect value does not unblock any MVP acceptance criterion. Begin immediately as a background instrumentation task — the code changes are small, but the run collection time is the constraint.

**Rationale for Rank 8**: No other REQ is blocked by this except REQ-015-007's break-even instantiation. Feasibility is Medium due to the forward-looking run requirement. Start the instrumentation work now but do not hold MVP delivery for it.

---

## Priority Summary Table

| Rank | REQ | Score | MVP? | Dependency Direction |
|------|-----|-------|------|----------------------|
| 1 | REQ-015-001 | 36 | YES | Blocks nothing; referenced by all |
| 2 | REQ-015-002 | 36 | YES | Supplies citation for REQ-015-001 Row 3 |
| 3 | REQ-015-006 | 27 | YES | Enables NS-003 prototype execution |
| 4 | REQ-015-008 | 27 | YES | Enables U-CA-004 resource allocation decision |
| 5 | REQ-015-004 | 18 | YES | Feeds REQ-015-008 evaluation rubric |
| 6 | REQ-015-005 | 18 | NO | Strengthens NS-003-B motivation |
| 7 | REQ-015-007 | 12 | NO | Soft-blocked by REQ-015-003 |
| 8 | REQ-015-003 | 8 | NO | Enables REQ-015-007 break-even formula |
