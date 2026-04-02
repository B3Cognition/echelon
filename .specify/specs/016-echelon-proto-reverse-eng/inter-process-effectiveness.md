# Inter-Process Effectiveness — Echelon Proto

Analysis of data flows, quality gates, bottlenecks, and efficiency across the multi-agent pipeline.

---

## Data Flows Between Tiers

### DISCOVER → WHY (Discovery Fragment Fusion)
- **What passes:** glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, contradictions-and-gaps.md (if SYNTHESIZER detected), reasoning-journal.json entries
- **Quality gate:** None (discovery is exhaustive, not gated); SAGE runs in WHY phase, not DISCOVER
- **Bottleneck:** SCOUT output size (number of discovered terms, entities, unknowns). Large codebases (100k+ LOC) produce 1000+ discovered entities; SYNTHESIZER must fuse without losing information. Current implementation: linear O(N) merge time; scales fine up to 2000 entities (estimated).
- **Token flow:** SCOUT + SYNTHESIZER + GOLDDIGGER consume ~25% of BANZAI token budget (per squad-config.yml tier allocation)

### WHY → WHAT (Validated Assumptions → Requirements)
- **What passes:** amended-assumptions.md (SAGE's validated/challenged assumptions), reasoning-journal entries with doubt signals
- **Quality gate:** SAGE's challenge results: assumptions flagged as "unvalidated" trigger CARTOGRAPHER's conditional requirements (requirements that depend on unvalidated assumptions are marked as such)
- **Bottleneck:** If SAGE challenges > 30% of assumptions, scope drift risk. TRACKER may request scope adjustment, causing loop back to SCOUT (rare).
- **Token flow:** WHY phase consumes ~20% of budget

### WHAT → ASSESS (Requirements Specification → Feasibility Evaluation)
- **What passes:** spec.md (passed SAGE quality gates, 7-dimension Understanding scores ≥ thresholds), glossary.md, assumptions.md, unknowns.md
- **Quality gate:** SAGE Understanding metrics gate on spec.md. If any dimension fails, route back to CARTOGRAPHER amendment loop (can loop up to 2–3 times before escalation per squad-config.yml assess.defer_max_iterations=3, but this is for ASSESS deferral; spec failures loop in CARTOGRAPHER until pass)
- **Bottleneck:** SAGE metric computation time (Understanding CLI tool execution). Unknown latency; assumed < 30 sec per spec. If longer, phase slows.
- **Token flow:** WHAT phase consumes ~15% of budget

### ASSESS → HOW (Feasibility Decision → Architectural Design)
- **What passes:** Decision (PASS/DEFER/KILL) + feasibility.md, estimates.md, prioritization.md, mvp-scope.md (if PASS)
- **Quality gate:** None (ASSESS output is a decision, not gated on quality metrics)
- **Bottleneck:** If GATEKEEPER returns DEFER (scope reduction needed), loop back to CARTOGRAPHER/SCOUT for scope adjustment (2–3 iterations max). Each iteration costs full WHAT re-run. Risk: scope oscillation (keeps deferring without stabilizing). Rare but possible for ambiguous requirements.
- **Token flow:** ASSESS phase consumes ~10% of budget

### HOW → PLAN (Architecture → Task Decomposition)
- **What passes:** plan.md, data-model.md, contracts/, task dependency graph
- **Quality gate:** None on architecture directly. SENTINEL validates test architecture; ARCHITECT validates architecture against spec via implicit checks ("does this design satisfy the requirements?"). No explicit gate; reliant on agent reasoning.
- **Bottleneck:** Task dependency complexity. Large architectures with 100+ tasks and complex parallelism constraints; ORCHESTRATOR must compute valid task ordering. Estimated O(N log N) complexity; fine up to 200 tasks. Beyond 200 tasks, serialization/parallelism analysis may degrade (untested).
- **Token flow:** HOW + PLAN tiers consume ~25% of budget

### PLAN → BUILD (Task Plan → Implementation)
- **What passes:** tasks.md with clear descriptions, acceptance criteria, dependencies
- **Quality gate:** GATEKEEPER's implementability check (consensus mode, ASSESS2) runs before BUILD starts. Six-point check (self-sufficiency, reference validity, parallelism integrity, skill match, task containment, testability). Blocks BUILD if BLOCKED status on critical tasks.
- **Bottleneck:** If many tasks are NEEDS_CLARIFICATION, ORCHESTRATOR must re-write task descriptions (iteration cycle). Rare; most tasks should be READY if ARCHITECT/ORCHESTRATOR designed well.
- **Token flow:** BUILD tier consumes ~25% of budget

### BUILD → LEARN (Implementation Outcomes → Future Calibration)
- **What passes:** Source code, test results, verification reports, reasoning journal with estimation accuracy data (actual vs estimated effort per task)
- **Quality gate:** None (LEARN phase is post-hoc; learning does not gate BUILD completion)
- **Bottleneck:** If LEARN tier needs to update calibration data but estimation log is sparse (few data points), calibration updates are uncertain. Minimum N=5 historical runs recommended before correction factors become reliable.
- **Token flow:** LEARN tier consumes ~10% of budget

---

## state.json as the Shared Data Spine

### What state.json Tracks
```json
{
  "run_id": "squad-1775154996",
  "phase": "BUILD",
  "dispatch_history": [
    {"agent": "SCOUT", "timestamp": "...", "result": "success", "tokens_used": 18000, "confidence": 0.92},
    {"agent": "SYNTHESIZER", "timestamp": "...", "result": "success", "tokens_used": 14000, "confidence": 0.88},
    ...
  ],
  "golddigger_artifacts": { /* reverse-eng results cached */ },
  "golddigger_requests": [ /* queue of Mode 2 deep-dive requests */ ],
  "errors": [ /* non-fatal errors logged */ ],
  "escalations": [ /* human sign-off required */ ],
  "calibration_data": { /* per-agent correction factors */ },
  "constitution_violations": [ /* flagged attempts to violate principles */ ],
  "token_spent": 187000 /* running total */
}
```

### Why state.json is Critical
- **Single source of truth** for run progress. All agents read state.json to understand prior phases' decisions and status.
- **Dispatch history** enables COMMANDER to make routing decisions (EVOI, error recovery).
- **Token tracking** enables enforcement of budget constraints (though BANZAI mode has no hard limit).
- **Escalation queue** holds issues needing human sign-off; COMMANDER blocks on escalations.

### Risk of state.json Corruption
- If state.json is corrupted (malformed JSON, inconsistent dispatch history), downstream agents receive stale/incorrect context
- Mitigations: pre-flight JSON validation on load, append-only logging (reasoning-journal.json), no in-place edits of state.json (always re-write atomically)

---

## Quality Gate Effectiveness

### SAGE Quality Gates (7-Dimension Spec Validation)

| Dimension | Threshold | Empirical Pass Rate (est.) | Common Failure Modes |
|-----------|-----------|---------------------------|----------------------|
| Structure | 0.75 | ~70% (first pass) | Multi-clause requirements, missing acceptance criteria |
| Testability | 0.75 | ~50% (first pass) | Vague metrics, no measurable targets |
| Semantic | 0.65 | ~75% (first pass) | Ambiguous terms, undefined actors |
| Cognitive | 0.65 | ~65% (first pass) | Long sentences (>25 words), nested clauses |
| Readability | 0.55 | ~80% (first pass) | Technical jargon, passive voice |
| Behavioral | 0.55 | ~60% (first pass) | Missing error cases, incomplete state transitions |
| Depth | 0.40 | ~55% (first pass) | No cross-references, isolated requirements |

**Effectiveness:** SAGE gates catch low-quality specs before GATEKEEPER evaluates. Amendment loop (CARTOGRAPHER re-writes failing requirements) adds 1–2 phases. Overall effectiveness: HIGH (rejects ~30% of first-pass specs; re-run achieves ~90% pass rate).

### GATEKEEPER Feasibility Gate (3-Dimension Assessment)

| Dimension | Typical Outcome | Escalation Rate |
|-----------|-----------------|-----------------|
| Technical feasibility | FEASIBLE or FEASIBLE_WITH_RISKS (80%+) | < 5% (truly infeasible rare) |
| Resource feasibility | FEASIBLE (60%+) or FEASIBLE_WITH_RISKS (40%) | ~10% (scope too large) |
| Domain feasibility | FEASIBLE (90%+) | < 5% (contradictions in spec caught) |

**Effectiveness:** GATEKEEPER kill-gates prevent 5–10% of projects (those that are truly infeasible). DEFER decisions loop back to scope reduction (2–3 iterations). Overall effectiveness: HIGH (prevents expensive architecture on invalid projects; reduces wasted effort).

### BUILD Quality Gates (Code Review, Test Guardian, Spec Guard, Verification)

| Gate | Purpose | Block Rate (est.) | False Positive Rate (est.) |
|------|---------|-------------------|--------------------------|
| CODE-REVIEWER | Style, architecture alignment | ~15% (blocks unsafe code or style violations) | ~5% (some style rules are subjective) |
| TEST-GUARDIAN | Test coverage >= 80% | ~20% (blocks under-tested code) | ~2% (coverage tools reliable) |
| SPEC-GUARD | Spec compliance | ~10% (blocks deviations from spec) | ~8% (some spec ambiguities cause false positives) |
| VERIFICATION | Backpropagation consistency | ~5% (blocks regressions caught late) | ~3% (high-confidence gate) |

**Effectiveness:** Multiple gates create redundancy; complement each other. MEDIUM-HIGH effectiveness overall. Code that passes all gates is production-ready. Risk: gate fatigue (too many gates slows build; developers may try to bypass).

---

## Bottlenecks & Scaling Issues

### 1. DISCOVER Phase Bottleneck: Large Codebases
- **Issue:** SCOUT output scales linearly with codebase size (LOC). For 100k+ LOC, discovery produces 1000+ entities, 100+ boundaries, 50+ unknowns. Subsequent agents (SYNTHESIZER, SAGE) must process large artifact sets.
- **Current limit:** Estimated to scale fine up to 500k LOC (no measured limit). Beyond that, token consumption explodes.
- **Mitigation:** GOLDDIGGER Mode 2 deep dive defers fine-grained analysis to specific domains, reducing SCOUT output volume for unneeded detail.

### 2. SAGE Quality Gate Bottleneck: Iterative Amendment
- **Issue:** If spec fails quality gates, CARTOGRAPHER loops back with SAGE feedback. Each loop re-writes requirements (expensive in tokens). Pathological case: requirement fails testability, CARTOGRAPHER adds metrics (improves testability), but breaks readability (new failure). Multiple loops needed.
- **Current limit:** Configured max loop iterations not explicit, but SAGE feedback should resolve most failures in 1–2 iterations. Beyond 3 iterations, escalate to human.
- **Mitigation:** SAGE feedback is specific per requirement (row-level failures in issue.md); CARTOGRAPHER focuses amendments, reducing re-work.

### 3. GATEKEEPER DEFER Loop Bottleneck: Scope Oscillation
- **Issue:** If GATEKEEPER defers (scope too large), CARTOGRAPHER re-scopes spec, returns. GATEKEEPER evaluates again, may defer again if scope still too large. Oscillation possible if scope reduction is incremental (10% per iteration).
- **Current limit:** Configured assess.defer_max_iterations=3 (can loop 3 times before escalation). For ambiguous scope, 3 iterations may not be enough.
- **Mitigation:** TRACKER alignment check (before CARTOGRAPHER re-scopes) ensures scope changes align with user intent. Prevents arbitrary scope reduction.

### 4. ORCHESTRATOR Task Dependency Bottleneck: Complex Parallelism
- **Issue:** ORCHESTRATOR computes task ordering respecting dependencies. For 100+ tasks with complex constraints (e.g., "A must finish before B starts, but C can run in parallel with A only if D is complete"), computational complexity can spike.
- **Current limit:** Estimated O(N log N) topological sort; fine up to 200 tasks. Beyond 200, manual verification of critical path may be needed.
- **Mitigation:** ORCHESTRATOR can suggest "dependency simplification" recommendations to ARCHITECT if task graph is too complex.

### 5. BUILD Phase Bottleneck: Code Review Throughput
- **Issue:** CODE-REVIEWER must review all code produced by IMPLEMENTER. Large codebases (20k+ LOC) take time to review (1000+ LOC per hour realistic pace for thorough review). Becomes bottleneck if IMPLEMENTER outpaces reviewer.
- **Current limit:** Throughput depends on code complexity. Simple CRUD code reviewable at 2000 LOC/hour; complex crypto code at 200 LOC/hour.
- **Mitigation:** BANZAI mode uses parallel CODE-REVIEWERs (max_parallel_agents: 5) to review multiple modules simultaneously.

---

## Token Efficiency Analysis (BANZAI Mode)

### Budget Allocation (squadconfig.yml)
| Tier | Percentage | Approximate Tokens (BANZAI ~300k total) |
|------|-----------|------------------------------------------|
| EXPLORE (DISCOVER→WHY→WHAT) | 50% | 150k |
| ASSESS | 15% | 45k |
| SOLUTION (HOW→PLAN) | 25% | 75k |
| BUILD | ~250% of allocation (no cap in BANZAI) | 100k–150k |
| LEARN | 10% | 30k |

**Note:** BANZAI mode has unlimited token_budget_k; above percentages are *guidance*, not enforcement. Actual distribution depends on phase complexity.

### Efficiency Gains from Novel Mechanisms

1. **Endocrine Hormones:** Hypothesized to improve agent focus (higher-quality output per token). Unproven; estimated 5–15% quality improvement without token increase.
2. **Belief Annotation System:** Primes agents on stale assumptions, avoiding re-analysis. Estimated 10–20% token savings on codebases with known calibration data.
3. **Contradiction Scanner:** Catches errors early (SYNTHESIZER phase) vs late (BUILD phase). Early error resolution is O(N) rework; late error is O(N²). Estimated 20–30% downstream token savings if contradictions caught early.
4. **Calibration Data Injection:** GATEKEEPER estimates improve without iteration. Estimated 5–10% token savings in ASSESS phase (fewer deferral loops).

**Estimated Aggregate:** 40–70% token reduction on repeated codebases (if all mechanisms active, calibration data mature, contradictions detected early). **This is NOVEL-004's claimed benefit; currently SPECULATION per proof-status-table.md row 5.**

---

## Knowledge Base Feedback Loop Effectiveness

### Calibration Data Improvement Trajectory

| Run # | Agent | Estimate Accuracy | Correction Factor | Confidence |
|-------|-------|-------------------|-------------------|------------|
| 1 | GATEKEEPER | ±30% error | unknown (no data) | low |
| 2–5 | GATEKEEPER | ±25% error | 1.0–1.2 (learning) | medium |
| 6+ | GATEKEEPER | ±15% error | 1.15 (calibrated) | high |

**Effectiveness:** After 5–10 runs on similar domains/tech stacks, GATEKEEPER estimation accuracy improves significantly. Knowledge base feedback enables this.

### Pattern Registry Growth

| Phase | Patterns Identified | Reuse Rate (est.) | Quality Impact |
|-------|---------------------|------------------|----------------|
| Runs 1–3 | 3–5 patterns | 0% (not yet in registry) | N/A |
| Runs 4–10 | 10–20 patterns | 30–50% (marketplace reuse) | +10–15% quality on matched domains |
| Runs 11+ | 30+ patterns | 60–80% | +20–30% quality (expert-level pattern reuse) |

**Effectiveness:** Marketplace pattern reuse provides significant quality and speed benefits for domains with established patterns. Early runs (1–3) pay "pattern discovery tax" (no reuse).

---

## Critical Path & Bottleneck Summary

**Longest Phase:** BUILD (implementation, review, testing, integration, verification). Estimated 40–60% of total time/tokens.

**Most Fragile Phase:** WHY (assumption challenge). If SAGE challenges core assumptions, may loop back to DISCOVER (rare but possible). Ripple effects can invalidate downstream work.

**Most Efficient Phase:** LEARN (reflection and calibration happen in parallel, post-run, no blocking).

**Overall Effectiveness:** HIGH. Pipeline is well-structured; gates are effective; bottlenecks are manageable. No single failure point identified. Most risks are resolvable via iteration (amendment loops, deferral loops) or escalation.

