# Effort Estimates — Spec 015
**Agent**: GATEKEEPER | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02

---

## Effort Tier Definitions

| Tier | Label | Meaning |
|------|-------|---------|
| Q | Quick | Hours of work; can be completed within a single agent session |
| M | Medium | 1-3 days; requires sustained focused effort or multiple sessions |
| L | Long | 1-4 weeks; requires prototype implementation, data collection, or experiment execution |
| B | Blocked | External dependency that cannot be resolved by agent effort alone |

---

## REQ Estimates

### REQ-015-001 — Claim Proof Status Table
**Tier: Q (Quick — hours)**

The Proof Topology Table in mental-model.md Section 4 already contains 17 rows with primary evidence, evidence grade, proof category, proof status, and "What Would Constitute Full Proof" — the exact fields required by AC-001-002. The INVESTIGATOR artifacts confirm paper identities and arxiv IDs. The task is: (1) copy the 17-row structure to a formatted deliverable, (2) verify AC-001-003 SPECULATION labeling for the two P5 rows, (3) verify AC-001-004 GATE-CONDITIONED labeling for the five CA overlay rows with U-015-001 blocking references, (4) verify AC-001-005 PROVEN (component level) / PARTIAL (Echelon-specific) labeling for NS-003-A and NS-003-B citing arxiv:2510.09355 and arxiv:2603.17244, and (5) add a "What Would Constitute Full Proof" non-empty cell for every non-P1 row (these are already present in mental-model.md). Total: 2-4 hours for a careful, citation-verified pass.

---

### REQ-015-002 — NS-003 Novelty Confirmation
**Tier: Q (Quick — under 1 hour; effectively complete)**

The investigation artifact U-015-002-novelty-search.md contains: 8 query strings verbatim, databases queried (Google-indexed scholarly content + Semantic Scholar proxy), date of execution (2026-04-02), per-result disposition tables, paper verification for NL2GenSym and Kumiho, full novelty verdict with AC-002-003 hedging language, and limitations section. The task is producing the standalone search record artifact as required by AC-002-005. This means extracting the protocol, results, and verdict from the investigation file into a self-contained document — approximately 30-60 minutes of formatting and extraction work. No new research is needed.

---

### REQ-015-003 — Token Efficiency Baseline
**Tier: M (Medium — 1-2 days instrumentation + run-collection gate)**

The instrumentation code change is Quick (add token logging per agent invocation — post-call introspection is available per plan.md). The gating constraint is time: at minimum 3 completed spec runs must be collected after instrumentation is deployed. This is the only REQ where the effort estimate has a pipeline execution dependency. Decomposed: (a) Instrumentation code: Q (hours), (b) Run collection: L-constrained (depends on how quickly 3 spec runs can be executed — if runs are scheduled, this could be 1-3 days of wall time), (c) Data aggregation and summary statistics: Q (hours). The aggregate estimate is M assuming runs can be started promptly, but the effective delivery time depends on when run collection completes.

**Note**: The instrumentation itself should begin immediately (it is a Quick task) so that the run-collection clock starts as early as possible. REQ-015-007's break-even formula will use symbolic form until REQ-015-003 is complete.

---

### REQ-015-004 — Scope Violation Rate Baseline
**Tier: M (Medium — 1-2 days)**

Annotation of 3-5 prior spec runs (runs 008-014) against each agent's declared scope. Decomposed: (a) Annotation scheme formalization: Q (1-2 hours — scheme is defined in AC-004-001 through AC-004-005; primarily writing the annotation guide), (b) Annotation of 3-5 runs across DISCOVER, ASSESS, and other agent outputs: M (5-8 hours total, assuming ~1 hour per run for 2-4 agents per run), (c) Aggregation into violation rates per agent type and identification of the three most frequent violation patterns: Q (1-2 hours). Single-annotator run is sufficient; the limitation is disclosed explicitly per AC-004-003. Total: 1 full day for a 3-run annotation, 2 days for a 5-run annotation.

---

### REQ-015-005 — Contradiction Rate Baseline
**Tier: M (Medium — 1-2 days)**

Automated scan of spec runs 008-014. Decomposed: (a) Detection method selection and specification (exact string match, semantic embedding, or LLM classifier — per AC-005-002, the choice is the implementer's but must be stated and applied consistently): Q (1-2 hours), (b) Running the scan across available runs: Q-M (1-4 hours depending on tooling — LLM classifier approach adds overhead but is more precise), (c) Manual precision check of 5 detected contradictions per AC-005-004: Q (1-2 hours), (d) Report generation per AC-005-003 and AC-005-005: Q (1-2 hours). Total: 1-2 days, with the lower end achievable if the detection method is implemented as a simple LLM classifier call over structured section headers.

---

### REQ-015-006 — NS-003 Prototype Experiment Design
**Tier: M (Medium — 1-2 days)**

Pure design work — no implementation. Decomposed: (a) Test codebase selection and rationale (AC-006-001): Q (1-2 hours — one well-understood repository with a clear spec 014 artifact history), (b) NS-003-A evaluation set specification (N=30 agent invocations, first-pass compliance rate formula and ≥70% threshold, inconclusive/redesign zones): Q (1-2 hours — parameters are defined in AC-006-004), (c) NS-003-B evaluation set specification (N=20 artificially contradicted artifact pairs, contradiction catch rate formula and ≥80% threshold, ≤20% false positive rate, contradiction injection method): M (2-4 hours — injection method requires design judgment on rule-based vs LLM adversarial vs manual injection), (d) Timeline phases (AC-006-006, expressed as phases not calendar days): Q (1 hour), (e) AC-006-007 self-check: verifying third-party executability at the specified level of detail: Q (1-2 hours). Total: 1 day for initial draft, 1 additional day for AC-006-007 self-check pass.

---

### REQ-015-007 — NOVEL-004 Prediction Accuracy Calibration
**Tier: M (Medium — 1-2 days)**

Retrospective calibration of adjacent artifact pairs from spec runs 008-014. Decomposed: (a) Identification and extraction of adjacent artifact pairs (DISCOVER→ASSESS, plus any additional adjacent pairs to reach N=9): Q (1-2 hours), (b) Per-pair predictability scoring using AC-007-002 rubric (0-20%/40-60%/80-100% bands, with 50% scoring for borderline assertions): M (4-8 hours depending on N pairs — approximately 30-60 minutes per artifact pair for careful human evaluation or 1-2 hours per pair for LLM-as-evaluator with stated rubric), (c) Aggregate statistics (mean, median, min, max, std deviation per AC-007-003): Q (30 minutes), (d) Break-even formula instantiation (symbolic if REQ-015-003 incomplete, numeric if complete per AC-007-004): Q (30 minutes), (e) Go/no-go recommendation per AC-007-006: Q (30 minutes once statistics are available). Total: 1-2 days. If N < 9 pairs are available, the effort is on the lower end; the N disclosure is part of the deliverable.

---

### REQ-015-008 — U-CA-004 Gate Experiment Specification
**Tier: M (Medium — 1-2 days)**

Pure specification work — no implementation, no experiment execution. Decomposed: (a) Three-condition design and LLM version lock specification (AC-008-001 and AC-008-002): Q (1-2 hours — the conditions are defined in the spec; the version lock requires identifying the exact model version string available at spec design time), (b) Sample size rationale (AC-008-003, N=10 minimum vs N=20 for 80% power): Q (30 minutes — rationale is stated in the spec), (c) Test codebase selection strategy (AC-008-004, fixed single codebase vs stratified 5-codebase sample): Q (1-2 hours — requires a judgment call with stated rationale), (d) Evaluation rubric with four dimensions and 0-3 scoring anchors per dimension (AC-008-005): M (3-5 hours — the rubric must be specific enough for a new human evaluator to apply without clarification, which requires careful anchor definition for each of the four dimensions: coherence, completeness, scope compliance, internal consistency), (e) Pre-registered decision rule covering POSITIVE / NEGATIVE / INCONCLUSIVE outcomes with quantitative thresholds and action mappings (AC-008-006): Q (1-2 hours), (f) CA overlay testing order with rationale for first-tested overlay (AC-008-007): Q (1-2 hours — ACT-R Typed Buffer is the recommended first overlay given Grade A problem evidence from "Lost in the Middle" and no API constraint issues). Total: 1 day for initial draft, 1 additional day for AC-008-005 rubric precision refinement and AC-SPEC-005 self-check.

---

## Total Effort Summary

| REQ | Effort Tier | Key Constraint | Sequential or Parallel? |
|-----|-------------|----------------|------------------------|
| REQ-015-001 | Q — hours | None | Start immediately; Rank 1 |
| REQ-015-002 | Q — <1 hour | None | Can run in parallel with REQ-015-001 |
| REQ-015-003 | M + run-gate | 3 instrumented runs required | Start instrumentation immediately; run in background |
| REQ-015-004 | M — 1-2 days | Annotator availability | After REQ-015-001 and REQ-015-002 |
| REQ-015-005 | M — 1-2 days | Detection method choice | Can run in parallel with REQ-015-004 |
| REQ-015-006 | M — 1-2 days | Writing precision (AC-006-007) | After REQ-015-001; can run in parallel with REQ-015-004 |
| REQ-015-007 | M — 1-2 days | N pairs available; soft on REQ-015-003 | After REQ-015-003 starts; run symbolically if needed |
| REQ-015-008 | M — 1-2 days | Rubric anchor precision (AC-008-005) | After REQ-015-001; can run in parallel with REQ-015-006 |

**Parallelization opportunity**: REQ-015-003 instrumentation, REQ-015-006, and REQ-015-008 can all begin in parallel immediately after REQ-015-001 is complete. REQ-015-004 and REQ-015-005 can run in parallel against the same artifact corpus. Total MVP delivery (REQ-015-001, -002, -006, -008, -004) is achievable within 3-4 days of focused work if REQ-015-006 and REQ-015-008 are executed in parallel by separate agents.
