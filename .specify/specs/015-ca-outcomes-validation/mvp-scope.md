# MVP Scope — Spec 015
**Agent**: GATEKEEPER | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02

---

## MVP Definition

The minimum scope that fully answers "can you prove this outcomes?" consists of five requirements:

### REQ-015-001 — Claim Proof Status Table (IN MVP)

This is the primary deliverable of the entire spec. It directly and completely answers "can you prove this outcomes?" for all 17 claims. Without it, no question is answered. Without everything else, at least one question is partially answered. It has no dependencies, the evidence is already assembled, and it is hours of assembly work. This is non-negotiable in the MVP.

### REQ-015-002 — NS-003 Novelty Confirmation (IN MVP)

The novelty claim is one of the two highest-value assertions in spec 014 (the other being the Grade A component evidence). It is the claim most vulnerable to being falsified by a single paper. INVESTIGATOR has already completed the search; the MVP deliverable is formalizing it into the standalone artifact required by AC-002-001 through AC-002-005. The cost is under one hour. The payoff is that the novelty claim becomes defensible with a reproducible search record. Not including this in the MVP would leave the most vulnerable claim undefended.

### REQ-015-006 — NS-003 Prototype Experiment Design (IN MVP)

NS-003 is the primary architecture recommendation from spec 014 and the one claim that is independent of the U-CA-004 gate. The component evidence is Grade A (proven at the component level). What is missing is a clear path to Echelon-specific validation. Without REQ-015-006, the answer to "what next?" for NS-003 is vague. With it, the squad has a self-contained specification that can be handed to an implementer immediately. This is 1-2 days of design writing with full parameter derivability from existing artifacts. It converts "partially proven" into "proven with a clear upgrade path."

### REQ-015-008 — U-CA-004 Gate Experiment Specification (IN MVP)

All five CA overlay claims are blocked by U-CA-004. The gate experiment has a 4-6 week execution timeline. Every day the specification is delayed, the squad's ability to make an explicit resource allocation decision is postponed. REQ-015-008 has zero dependencies — the specification does not require running the experiment. The question "can you prove the CA overlays?" cannot be answered "yes" or "no" until the experiment runs; but it can be answered "not yet, and here is the exact, pre-registered protocol for resolving it" — which is the honest and actionable answer a reader needs. Including this in the MVP means the squad can begin the resource allocation decision in parallel with the experiment design.

### REQ-015-004 — Scope Violation Rate Baseline (IN MVP)

This REQ is included in the MVP on the grounds that three spec 014 mechanisms (NS-003 Critic, AC-3, NOVEL-002 Phi-proxy) each claim a benefit that is unmeasurable without a baseline. A reader asking "how bad is the current scope violation problem?" receives no answer from REQ-015-001 alone; they receive a precise empirical answer from REQ-015-004. Because the annotation corpus already exists (spec runs 008-014) and the effort is 1-2 days, including this in the MVP is low-cost and addresses a direct gap in the proof topology. This also feeds the scoring rubric needed by REQ-015-008 (AC-008-005 specifies Scope Violation Rate as an acceptable primary metric).

---

## Deferred

### REQ-015-005 — Contradiction Rate Baseline (DEFERRED)

Condition for execution: immediately after MVP delivery. REQ-015-005 is deferred from the MVP not because it is unimportant, but because REQ-015-004 and REQ-015-005 address complementary dimensions of the same evidence gap (scope violations vs inter-artifact contradictions), and the MVP can be delivered with one of the two baselines populated. REQ-015-005 uses the same artifact corpus and a similar 1-2 day scan effort. It should be executed as the next task after MVP completion. It does not block the user from answering "can you prove this?" — but it would strengthen the NS-003-B motivation claim.

### REQ-015-003 — Token Efficiency Baseline (DEFERRED)

Condition for execution: requires 3 instrumented forward-looking runs, making it time-gated by pipeline execution. It is deferred from the MVP because (a) REQ-015-007's break-even formula can proceed in symbolic form without it, (b) it is the only REQ with a time-gate external to the writing/annotation workflow, and (c) its value is Medium relative to the Critical and High value of the MVP requirements. It should be scheduled as a background instrumentation task beginning immediately, so that results are available for REQ-015-007's break-even formula instantiation.

### REQ-015-007 — NOVEL-004 Prediction Accuracy Calibration (DEFERRED)

Condition for execution: after REQ-015-003 token baseline is complete (for break-even formula instantiation) OR independently with symbolic break-even form. This is deferred from the hard MVP because NOVEL-004 is labeled SPECULATION regardless of calibration outcome, and the go/no-go recommendation is explicitly marked as pending until token baseline data is available. The calibration is valuable but does not change the primary verdict on NOVEL-004 (which remains P3 / NOT PROVEN). It can be executed independently in 1-2 days using the existing artifact corpus.

---

## MVP Success Criterion

When REQ-015-001, REQ-015-002, REQ-015-006, REQ-015-008, and REQ-015-004 are complete, the user holds: (1) a complete cited proof-status verdict table covering all 17 claims with explicit SPECULATION and GATE-CONDITIONED labels, (2) a reproducible novelty search record that defends the NS-003 novelty claim, (3) a self-contained NS-003 prototype experiment design ready for immediate third-party execution, (4) a pre-registered U-CA-004 gate experiment specification enabling the resource allocation decision, and (5) a measured scope violation baseline establishing what the improvement mechanisms are actually improving against — constituting a complete, defensible answer to "can you prove this outcomes?" with explicit verdicts on what is proven, what is partially proven, what is gate-conditioned, and what is speculation.
