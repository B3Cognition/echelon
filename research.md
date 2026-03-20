
# Triadic Agentic System — Experimental Design & Validation Framework

## Context

We are designing an agentic system based on a **triadic model**:

- **Understanding**
- **Reasoning**
- **Internalization**

The system currently defines **~39 specialized roles** operating across phases:

- Understand → Decide → Solution → Build

The goal is to validate and evolve this system using **evidence-based approaches** grounded in:

- Team Topologies (cognitive load, interaction modes)
- Transactive Memory Systems (knowledge ownership)
- Cognitive Load Theory
- Double-loop Learning

This document defines **testable experiments**, not theory.

---

# 1. Role Compression vs Full Specialization

## Hypothesis

The system is **over-specialized at runtime**.  
A compressed set of roles will achieve similar quality with lower cost.

## Experiment

### A: Full Topology

All roles active (e.g. SCOUT → SYNTHESIZER → SAGE → ...)

### B: Compressed Topology

Group roles into capability clusters:

- DISCOVERY = SCOUT + INVESTIGATOR + BENCHMARK
- SYNTHESIS = SYNTHESIZER + SAGE
- DECISION = GATEKEEPER + ADVOCATE
- DESIGN = ARCHITECT + CARTOGRAPHER
- VALIDATION = SENTINEL + GUARDIAN

## Metrics

- Output quality (human evaluation)
- Cycle time
- Token / compute cost
- Iterations to PASS

## Expected Outcome

- Similar quality
- Lower cost and latency

## Insight

Optimize for **cognitive load**, not maximum specialization.

---

# 2. Interaction Modes (Team Topologies)

## Hypothesis

Agent interactions should not always be sequential.

## Modes to Test

### Collaboration (Parallel)

- Multiple agents explore simultaneously
- SYNTHESIZER merges

### X-as-a-Service

- One agent produces outputs
- Others consume without discussion

### Facilitating

- One agent improves reasoning of others

## Metrics

- Convergence time
- Contradictions
- Rework loops

## Expected Outcome

- Collaboration: better discovery, more noise
- X-as-a-service: efficient execution
- Facilitating: higher reasoning quality

## Insight

Interaction mode should be **phase-dependent**:

- Understand → Collaboration
- Solution → X-as-a-service
- Build → Minimal interaction

---

# 3. Transactive Memory (Knowledge Ownership)

## Hypothesis

Lack of ownership leads to redundancy and hallucination.

## Experiment

### A: No ownership

All agents query all data

### B: Ownership enforced

- SCOUT → external knowledge
- ARCHITECT → system constraints
- SENTINEL → validation rules

Agents must query the owner

## Metrics

- Duplicate work
- Hallucination rate
- Token usage

## Expected Outcome

- Reduced duplication
- Improved consistency

## Insight

Agents should **route knowledge**, not recompute it.

---

# 4. Internalization Loop (Learning System)

## Hypothesis

Without learning, system remains static and brittle. Currently, learning is captured but never applied — CALIBRATE reports low accuracy but prompts never change.

## Experiment

Transform learning layer from **passive observation** to **active improvement**.

### A: Passive Learning (Current)

```
CALIBRATE: "ARCHITECT accuracy is 0.52"
    ↓
EVOLVE: "Stagnation detected"
    ↓
Next run: ARCHITECT uses SAME prompt → SAME mistakes
```

### B: Active Learning (Proposed)

```
CALIBRATE: "accuracy 0.52" + evolution_signal + failure_analysis
    ↓
EVOLVE: proposes prompt change, backtests on 5 runs
    ↓
Human approves → canary deployed (20%)
    ↓
MONITOR: canary improves → promote to 100%
    ↓
Next run: ARCHITECT uses IMPROVED prompt
```

## Components

### CALIBRATE Enhancement

Add evolution signals to output:

```yaml
evolution_signal:
  suggest_evolution: true
  reason: "accuracy below 0.7 after 5+ samples"
  failure_analysis:
    pattern: "Missing database scaling considerations"
    occurrences: 5
    root_cause: "ARCHITECT prompt lacks scaling checklist"
```

Trigger conditions:
- Accuracy < 0.7 after 5+ samples
- Declining trend > 0.1 over 3 runs
- Same pitfall triggered 3+ times

### EVOLVE Transformation

From observer to proposer:

1. Receive evolution signals from CALIBRATE
2. Analyze failure pattern
3. Generate minimal prompt modification
4. Backtest on 5 historical runs
5. Submit proposal if net_improvement > 0

### Prompt Versioning

```
agents/architect/
├── v1.0.md          # Original
├── v1.1.md          # Added ADR checklist
├── v1.2.md          # Current
├── v1.3.md          # Canary (proposed)
├── current.md → v1.2.md
├── changelog.yaml
└── validation-results.yaml
```

### Canary Deployment

- 20% of runs use canary version
- MONITOR evaluates after 10 runs
- Accuracy improved > 0.05 → PROMOTE
- Accuracy dropped > 0.03 → ROLLBACK

### Safety Mechanisms

1. **Human approval required** — EVOLVE proposes, human decides
2. **Immutable sections** — core principles can't be evolved
3. **Automatic rollback** — canary regression triggers instant revert
4. **Rate limiting** — max 2 proposals/agent/week

## Metrics

| Metric | Target |
|--------|--------|
| Proposal acceptance rate | > 60% |
| Canary promotion rate | > 70% |
| Accuracy improvement per evolution | > 0.05 |
| Time to approval | < 7 days |
| Rollback rate | < 10% |

## Implementation Phases

| Phase | Version | Content |
|-------|---------|---------|
| Foundation | v0.4.0 | Versioning infrastructure, evolution signals |
| Proposals | v0.4.1 | EVOLVE generates proposals, backtest |
| Canary | v0.5.0 | Canary deployment, auto-rollback |
| Global | v0.5.1 | Cross-project evolution sharing via VETERAN |

## Expected Outcome

- Time to fix recurring issues: 5 runs → 2 runs + approval
- Agent accuracy improvement: measurable via calibration
- Prompt quality: systematic improvement vs ad-hoc fixes

## Insight

Implements **double-loop learning** with safety rails. The system questions and modifies its own rules, not just outputs.

## Reference

Full proposal: [docs/proposal-internalization-loop.md](docs/proposal-internalization-loop.md)

---

# 5. Gatekeeper Strictness (Kill Rate)

## Hypothesis

System is too permissive and allows low-quality work to continue.

## Experiment

- Lenient Gatekeeper
- Balanced Gatekeeper
- Strict Gatekeeper

## Metrics

- Downstream wasted effort
- Final quality
- % killed early

## Expected Outcome

Balanced strictness is optimal.

## Insight

Gatekeeper becomes a **portfolio control mechanism**.

---

# 6. Parallel vs Sequential Pipeline

## Hypothesis

Sequential pipeline limits speed.

## Experiment

### A: Sequential

Linear pipeline

### B: Parallel clusters

- Discovery agents run in parallel
- Reasoning agents run in parallel
- Voting selects output

## Metrics

- Time to first solution
- Output quality variance
- Cost

## Expected Outcome

- Parallel faster but noisier
- Sequential slower but stable

## Insight

Use:

- Parallel → exploration
- Sequential → exploitation

---

# 7. Artifact-Centric vs Agent-Centric

## Hypothesis

System is too agent-driven and lacks traceability.

## Experiment

### A: Agent-driven

Agents pass outputs directly

### B: Artifact-driven

All outputs written to:

- spec.md
- plan.md
- contracts/
- test-strategy.md

Agents only read/write artifacts

## Metrics

- Traceability
- Rework
- Human usability

## Expected Outcome

Artifact-driven improves coordination and auditability.

## Insight

Artifacts act as **boundary objects**.

---

# 8. Failure Injection

## Hypothesis

System is fragile under partial failure.

## Experiment

Simulate:

- Missing agent (e.g. SAGE)
- Corrupted input
- Delayed execution

## Metrics

- Output degradation
- Recovery ability

## Expected Outcome

Robust systems degrade gracefully.

## Insight

Requires:

- Redundancy
- Fallback roles

---

# 9. Human-in-the-Loop Placement

## Hypothesis

Human intervention point is suboptimal.

## Experiment

Compare human input at:

1. After UNDERSTAND
2. After SYNTHESIS
3. After ARCHITECT
4. No human

## Metrics

- Rework
- Time to delivery
- Output quality

## Expected Outcome

Earlier input reduces rework.

---

# 10. BUILD/QA Phase Split

## Hypothesis

Phase 4 (BUILD) is overloaded with 10 agents running sequential per-task reviews. Splitting into BUILD (fast, parallel) and QA (thorough, batched) will improve speed without sacrificing quality.

## Current State

```text
Phase 4: BUILD (monolithic)
├── Per Task (sequential, blocking)
│   ├── IMPLEMENTER → writes code
│   ├── SPEC GUARD → spec compliance
│   ├── CODE REVIEWER → code quality
│   └── TEST GUARDIAN → test quality
└── Per Phase
    ├── ENGINEERING MANAGER
    ├── INTEGRATOR
    └── VERIFICATION (backpropagation)
```

**Problem:** Task T-005 waits for T-004's full 4-agent review chain.

## Experiment

### A: Monolithic BUILD (Current)

- 4 sequential agents per task
- Each task fully reviewed before next starts
- ~18h for 10 tasks (sequential)

### B: Split BUILD + QA

**Phase 4: BUILD** (fast)

- IMPLEMENTER per task (parallelizable)
- Light gate only: compiles, tests pass, lint clean
- 3 parallel workers possible

**Phase 5: QA** (thorough)

- SPEC GUARD, CODE REVIEWER, TEST GUARDIAN run in batch
- See all tasks together — catch cross-task issues
- VERIFICATION backpropagation loop

```text
BUILD (3 parallel workers): 4h wall clock
QA (batch review):          3h45m
Total:                      7h45m (vs 18h20m)
```

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| Parallelization | Blocked per task | 3 workers parallel |
| Cross-task issues | Caught late | Caught in batch review |
| Duplicate code detection | Often missed | Detected holistically |
| Speedup | 1x | ~2.4x |

## Light Gate (BUILD)

Automated, non-blocking between tasks:

- `tsc --noEmit` passes
- `vitest run` passes
- `eslint` passes
- Output files exist

Does NOT check spec compliance, code quality, test quality — QA does that.

## Batch Review Benefits

CODE REVIEWER sees all BUILD output:

- Detects inconsistent patterns across tasks
- Detects duplication across tasks
- Suggests cross-task refactoring

SPEC GUARD reviews all tasks against full spec:

- Cross-task issues visible
- Split implementations detected
- Full traceability matrix at once

## Configuration

```yaml
phases:
  build:
    parallel_workers: 3
    light_gate:
      require_build: true
      require_tests: true
      require_lint: true

  qa:
    batch_review: true
    holistic_code_review: true
    verification_max_iterations: 3
```

## Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Wall-clock time (10 tasks) | 18h | 8h |
| Cross-task issues caught | Late | Early |
| Rework cycles | Per-task | Batched |

## Implementation Phases

| Phase | Content |
|-------|---------|
| v0.4.0 | Add QA phase, keep current gates as "light" |
| v0.4.1 | Enable parallel IMPLEMENTER execution |
| v0.5.0 | Add cross-task analysis to batch reviewers |

## Open Questions

1. **Rework routing:** Full BUILD→QA or just BUILD→VERIFICATION?
2. **Partial QA:** Re-run all tasks or just changed ones?
3. **Human checkpoint:** Gate between BUILD and QA?
4. **Specialists:** Trigger in BUILD or QA?

## Expected Outcome

- ~2.4x speedup on build phase
- Better cross-task issue detection
- Same or higher final quality

## Reference

Full proposal: [docs/proposal-build-qa-split.md](docs/proposal-build-qa-split.md)

---

# 11. Metrics Framework (Critical)

## Efficiency

- Cycle time
- Token cost
- Active agents per task

## Quality

- Spec completeness
- Defect rate
- Human rating

## Coordination

- Number of interactions
- Rework loops

## Learning

- Improvement across iterations

---

# Recommended Initial Experiments

**Priority 1 — Concrete proposals ready:**

- **BUILD/QA Phase Split** (#10) — Full proposal ready, ~2.4x speedup potential
- **Internalization Loop** (#4) — Full proposal ready, enables systematic improvement

**Priority 2 — High value, needs design:**

- **Transactive Memory** (#3) — Knowledge ownership reduces hallucination
- **Artifact-driven workflow** (#7) — Improves traceability and auditability

**Priority 3 — Worth testing:**

- Gatekeeper strictness tuning (#5)
- Human-in-the-loop placement (#9)

**Deprioritized:**

- Role Compression (#1) — Current phase structure already has ~10 agents max per phase
- Parallel vs Sequential (#6) — BUILD/QA split addresses this more concretely

---

# Key Strategic Insight

The current system is:
> Well-architected but over-orchestrated

The optimal system will likely have:

- **Phase-tuned orchestration** — BUILD/QA split enables parallelism without sacrificing quality
- **Active learning loop** — Prompts evolve based on calibration, not just observation
- Strong artifact-driven coordination
- Clear knowledge ownership
- Dynamic interaction modes

**Next concrete steps:**

1. Implement BUILD/QA split (v0.4.0) — infrastructure for phase separation
2. Add evolution signals to CALIBRATE (v0.4.0) — foundation for active learning
3. Transform EVOLVE to proposer (v0.4.1) — close the learning loop

---

# Next Steps

**Immediate (v0.4.0):**

- Implement prompt versioning infrastructure
- Add evolution signals to CALIBRATE output
- Add QA phase after BUILD
- Enable light gate for BUILD phase

**Short-term (v0.4.1):**

- Transform EVOLVE to generate proposals with backtest
- Enable parallel IMPLEMENTER execution
- Add human approval workflow for evolutions

**Medium-term (v0.5.0):**

- Implement canary deployment for prompts
- Add MONITOR learning loop health checks
- Add cross-task analysis to batch reviewers

**Reference Documents:**

- [BUILD/QA Split Proposal](docs/proposal-build-qa-split.md)
- [Internalization Loop Proposal](docs/proposal-internalization-loop.md)

---
