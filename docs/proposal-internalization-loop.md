# Proposal: Internalization Loop (Double-Loop Learning)

## Executive Summary

Transform the learning layer from **passive observation** to **active improvement**. The system should not just track what went wrong — it should propose and safely deploy fixes.

---

## Current State (v0.3.0)

```
Learning Layer (passive)
├── CALIBRATE (AUDITOR)
│   └── Tracks accuracy per domain, computes correction factors
├── EVOLVE (ADAPTIVE)
│   └── Detects stagnation/regression, flags confirmation bias
├── REFLECT (MIRROR)
│   └── Extracts patterns and pitfalls
├── MONITOR (METACOGNITION)
│   └── Watches process compliance
└── VETERAN (GLOBAL-MEMORY)
    └── Cross-project knowledge sync
```

**Problem:** Learning is captured but not applied. Agents make the same mistakes because prompts never improve.

### Current Flow

```
Run N completes
    ↓
CALIBRATE: "ARCHITECT accuracy is 0.52 for infrastructure"
    ↓
EVOLVE: "Stagnation detected — same pattern for 3 runs"
    ↓
REFLECT: "Added PIT-042: Missing database scaling consideration"
    ↓
Run N+1 starts
    ↓
ARCHITECT uses the SAME prompt — makes the SAME mistake
```

---

## Proposed State (v0.4.0)

```
Learning Layer (active)
├── CALIBRATE (enhanced)
│   ├── Tracks accuracy per domain
│   ├── Produces EVOLUTION SIGNALS when accuracy < threshold
│   └── Generates failure analysis with root cause
├── EVOLVE (transformed)
│   ├── Receives evolution signals from CALIBRATE
│   ├── PROPOSES prompt modifications (not just observes)
│   ├── Backtests proposals against historical runs
│   └── Submits to human approval queue
├── REFLECT (unchanged)
│   └── Extracts patterns and pitfalls
├── MONITOR (extended)
│   ├── Watches process compliance
│   └── Watches LEARNING LOOP health (is evolution working?)
├── VETERAN (extended)
│   ├── Cross-project knowledge sync
│   └── Promotes validated evolutions to global
└── NEW: Prompt Versioning Infrastructure
    ├── Versioned prompt files
    ├── Canary deployment capability
    └── Automatic rollback on regression
```

### Proposed Flow

```
Run N completes
    ↓
CALIBRATE: "ARCHITECT accuracy is 0.52 for infrastructure"
         + "Evolution signal: suggest_evolution=true"
         + "Failure pattern: Missing database scaling in 5/8 cases"
    ↓
EVOLVE: Analyzes failure pattern
      → Proposes: "Add 'Database Scaling Checklist' to ARCHITECT prompt"
      → Backtests on 5 historical runs: "Would have caught 4/5 failures"
      → Creates evolution proposal (not deployed)
    ↓
Human reviews proposal (weekly batch or on-demand)
    ↓
Approved → New prompt version created (agents/architect/v1.3.md)
    ↓
Canary: 20% of next runs use v1.3, 80% use v1.2
    ↓
MONITOR: Watches canary outcomes
       → If v1.3 improves accuracy: promote to 100%
       → If v1.3 regresses: auto-rollback to v1.2
    ↓
Run N+1 starts with improved ARCHITECT prompt
```

---

## Component Details

### 1. CALIBRATE Enhancement: Evolution Signals

**Current output:**
```yaml
domains:
  infrastructure:
    accuracy: 0.52
    sample_size: 8
    trend: declining
    correction_factor: 1.4
```

**Enhanced output:**
```yaml
domains:
  infrastructure:
    accuracy: 0.52
    sample_size: 8
    trend: declining
    correction_factor: 1.4
    # NEW: Evolution signals
    evolution_signal:
      suggest_evolution: true
      reason: "accuracy below 0.7 after 5+ samples with declining trend"
      affected_agents: [ARCHITECT, SENTINEL]
      failure_analysis:
        pattern: "Missing database scaling considerations"
        occurrences: 5
        examples:
          - run_id: squad-001
            decision: "Chose PostgreSQL without capacity analysis"
            outcome: "GROUND rejected — scaling unclear"
          - run_id: squad-003
            decision: "Single-instance database design"
            outcome: "FEEDBACK — production scaling issues"
        root_cause: "ARCHITECT prompt lacks explicit scaling checklist"
        suggested_fix: "Add 'Database Scaling Checklist' section"
```

**Trigger conditions for evolution signal:**
| Condition | Threshold | Signal |
|-----------|-----------|--------|
| Low accuracy | < 0.7 after 5+ samples | `suggest_evolution: true` |
| Declining trend | accuracy dropped > 0.1 over 3 runs | `suggest_evolution: true` |
| Recurring pitfall | same PIT-* triggered 3+ times | `suggest_evolution: true` |
| Repeated rejection | same agent rejected by WHY 3+ times for same reason | `suggest_evolution: true` |

---

### 2. EVOLVE Transformation: From Observer to Proposer

**Current role:** Detect stagnation, flag issues, report.

**New role:** Propose prompt modifications, backtest, submit for approval.

#### New Process

```
Step 1: Receive Evolution Signals
├── Read CALIBRATE output
├── Filter for suggest_evolution: true
└── Prioritize by: accuracy gap × sample size

Step 2: Analyze Failure Pattern
├── Read failure_analysis from CALIBRATE
├── Read relevant pitfalls from pitfalls.yaml
├── Read affected agent's current prompt
└── Identify what the prompt is missing

Step 3: Generate Proposal
├── Draft specific prompt modification
├── Keep modification minimal and targeted
└── Document rationale with evidence

Step 4: Backtest Proposal
├── Load 5 most recent runs for affected agent
├── Simulate: "Would this change have affected outcome?"
├── Score: failures_prevented - passes_broken
└── Require net_improvement > 0

Step 5: Submit for Approval
├── Write proposal to pending-evolutions/
├── Include: change, evidence, backtest results
└── Flag urgency based on accuracy gap
```

#### Evolution Proposal Format

```markdown
# Evolution Proposal: EVO-{NNN}

**Date:** {ISO-8601}
**Status:** PENDING_REVIEW
**Priority:** {CRITICAL | HIGH | MEDIUM | LOW}
**Affected Agent:** ARCHITECT
**Current Version:** v1.2

## Problem Statement

ARCHITECT accuracy for infrastructure domain is 0.52 (threshold: 0.70).
Declining trend over last 3 runs (0.61 → 0.55 → 0.52).

### Failure Pattern

"Missing database scaling considerations" — occurred in 5/8 infrastructure decisions.

### Root Cause

ARCHITECT prompt has no explicit checklist for database scaling. The agent considers scaling only when explicitly mentioned in requirements.

## Proposed Change

Add section to ARCHITECT prompt:

```diff
+ ### Database Scaling Checklist (Required for any database decision)
+
+ Before recommending any database, answer:
+ 1. What is the expected data volume at launch? At 10x growth?
+ 2. What is the expected query load (reads/writes per second)?
+ 3. Does the chosen database support horizontal scaling?
+ 4. What is the replication strategy for high availability?
+ 5. What is the backup and recovery plan?
+
+ If any answer is "unknown," flag for SCIENTIST investigation.
```

## Evidence

| Run | Decision | Outcome | Would Change Have Helped? |
|-----|----------|---------|---------------------------|
| squad-001 | PostgreSQL without capacity | GROUND rejected | YES — checklist would force analysis |
| squad-002 | MongoDB for relational data | WHY rejected | NO — different issue |
| squad-003 | Single-instance design | FEEDBACK: prod issues | YES — checklist Q3-Q4 |
| squad-005 | DynamoDB without cost model | GROUND rejected | YES — checklist Q1-Q2 |
| squad-007 | Correct scaling analysis | Passed | NO CHANGE — already correct |

## Backtest Results

- **Runs analyzed:** 5
- **Failures that would become passes:** 3
- **Passes that would become failures:** 0
- **Net improvement:** +3
- **Confidence:** HIGH

## Recommendation

**APPROVE** — Clear evidence of improvement with no risk of regression.

## Approval

- [ ] Human reviewed
- [ ] Approved for canary deployment
- [ ] Approved for full deployment
```

---

### 3. Prompt Versioning Infrastructure

#### Directory Structure

```
agents/
├── architect.md → agents/architect/current.md  # Symlink to active version
├── architect/
│   ├── v1.0.md          # Original
│   ├── v1.1.md          # Added ADR checklist
│   ├── v1.2.md          # Added security review section
│   ├── v1.3.md          # Added database scaling checklist (canary)
│   ├── current.md → v1.2.md  # Active version symlink
│   ├── canary.md → v1.3.md   # Canary version symlink (optional)
│   ├── changelog.yaml
│   └── validation-results.yaml
```

#### changelog.yaml

```yaml
versions:
  - version: "1.0"
    date: "2026-01-15"
    author: "human"
    changes: "Initial version"

  - version: "1.1"
    date: "2026-02-01"
    author: "human"
    changes: "Added ADR compliance checklist"
    evidence: "Manual observation of ADR violations"

  - version: "1.2"
    date: "2026-02-20"
    author: "human"
    changes: "Added security review section"
    evidence: "GUARDIAN frequently summoned for basic security"

  - version: "1.3"
    date: "2026-03-19"
    author: "EVOLVE"
    evolution_id: "EVO-042"
    changes: "Added database scaling checklist"
    evidence: "5/8 infrastructure failures due to missing scaling analysis"
    backtest_score: "+3"
    status: "canary"  # pending | canary | active | rolled_back
```

#### validation-results.yaml

```yaml
versions:
  "1.2":
    status: active
    runs_on_version: 47
    accuracy_by_domain:
      infrastructure: 0.52
      api-design: 0.78
      frontend: 0.81
    quality_gate_pass_rate: 0.73

  "1.3":
    status: canary
    runs_on_version: 3
    canary_percentage: 20
    accuracy_by_domain:
      infrastructure: 0.67  # Improving!
      api-design: 0.80
      frontend: 0.79
    quality_gate_pass_rate: 0.81
    comparison_to_baseline:
      infrastructure: +0.15  # Significant improvement
      api-design: +0.02      # Within noise
      frontend: -0.02        # Within noise
```

---

### 4. Canary Deployment System

#### How It Works

```
New version approved for canary
    ↓
COMMANDER checks: is canary active for this agent?
    ↓
Yes → Random selection: 20% use canary, 80% use current
    ↓
Track outcomes separately in validation-results.yaml
    ↓
After N runs (configurable, default: 10):
    ↓
MONITOR evaluates canary performance:
  - Accuracy improved by > 0.05? → PROMOTE
  - Accuracy within ±0.03? → EXTEND canary (more data needed)
  - Accuracy dropped by > 0.03? → ROLLBACK
```

#### Configuration

```yaml
# squad-config.yml
evolution:
  enabled: true

  calibration:
    evolution_threshold: 0.7      # Suggest evolution below this accuracy
    min_sample_size: 5            # Minimum samples before suggesting

  backtest:
    min_runs: 5                   # Minimum historical runs for backtest
    min_net_improvement: 1        # Minimum improvement to propose

  canary:
    enabled: true
    percentage: 20                # % of runs on canary version
    min_runs: 10                  # Minimum canary runs before evaluation
    promote_threshold: 0.05       # Accuracy improvement to promote
    rollback_threshold: -0.03     # Accuracy drop to rollback

  approval:
    require_human: true           # Human must approve before canary
    auto_promote: false           # Auto-promote successful canaries?
    max_pending: 10               # Max pending proposals before alert
```

---

### 5. MONITOR Extension: Learning Loop Health

Add new check category to MONITOR:

#### Learning Loop Health Checks

```markdown
### 6. Learning Loop Health (NEW)

Every 10 runs, MONITOR asks:

**Calibration Health:**
- "Is CALIBRATE producing evolution signals for low-accuracy domains?"
- "Are evolution signals being acted on by EVOLVE?"
- "Are proposals being reviewed by humans in reasonable time?"

**Evolution Effectiveness:**
- "Are approved evolutions actually improving accuracy?"
- "Is any agent's accuracy declining despite evolution attempts?"
- "Are we seeing diminishing returns from evolutions?"

**Metric Gaming Detection:**
- "Is accuracy improving but user satisfaction declining?"
- "Are agents optimizing for metrics rather than outcomes?"
- "Are evolutions making prompts longer without clear benefit?"

**Knowledge Base Health:**
- "Are patterns.yaml entries being validated by feedback?"
- "Are stale patterns being archived?"
- "Is global memory being updated from local learnings?"
```

#### New Verdicts

| Verdict | Meaning | Action |
|---------|---------|--------|
| LEARNING_HEALTHY | Evolution loop working | Continue |
| LEARNING_STALLED | Signals produced but no proposals | Alert human |
| LEARNING_BACKLOGGED | Proposals pending > 2 weeks | Alert human |
| EVOLUTION_INEFFECTIVE | 3+ evolutions with no improvement | Review approach |
| METRIC_GAMING_SUSPECTED | Metrics up but outcomes down | Halt evolutions |

---

### 6. VETERAN Extension: Global Evolution Sharing

When an evolution is validated (canary promoted, accuracy improved):

```
Local evolution validated
    ↓
VETERAN checks: is this generalizable?
    ↓
Criteria for global promotion:
  - Improvement > 0.1 in accuracy
  - Not project-specific (no hardcoded values)
  - Pattern applies to domain, not just this codebase
    ↓
If generalizable → add to ~/.specify/squad-global/evolutions.yaml
    ↓
New projects inherit evolved prompts as starting point
```

#### Global Evolutions File

```yaml
# ~/.specify/squad-global/evolutions.yaml
evolutions:
  - id: GEVO-001
    agent: ARCHITECT
    change: "Database Scaling Checklist"
    origin_project: "project-alpha"
    validated_in_projects: ["project-alpha", "project-beta"]
    accuracy_improvement: 0.15
    date_promoted: "2026-03-25"

  - id: GEVO-002
    agent: SENTINEL
    change: "API Error Response Validation"
    origin_project: "project-gamma"
    validated_in_projects: ["project-gamma"]
    accuracy_improvement: 0.12
    date_promoted: "2026-04-01"
```

---

## Safety Mechanisms

### 1. Human Approval Gate

**All prompt changes require human approval.**

```
EVOLVE proposes change
    ↓
Proposal written to pending-evolutions/{EVO-NNN}.md
    ↓
Human reviews via:
  - CLI: /speckit.cognitive-squad.evolutions review
  - Or: manual file review
    ↓
Human decision:
  - APPROVE → deploy to canary
  - REJECT → archive with reason
  - MODIFY → human edits, then approve
```

### 2. Immutable Sections

Some prompt sections cannot be evolved:

```markdown
## CRITICAL CONSTRAINTS (IMMUTABLE — DO NOT EVOLVE)

The following rules are foundational and must not be modified by EVOLVE:

1. All decisions must be explainable to a junior developer
2. Security considerations cannot be deprioritized for speed
3. User data privacy is non-negotiable
4. Constitution.md rules are absolute

---

## EVOLVABLE SECTIONS

The following may be modified based on calibration data:

- Checklists (can add items, reorder, clarify)
- Examples (can add, update, remove)
- Domain-specific heuristics
- Process steps (can add, clarify)
```

### 3. Automatic Rollback

```
Canary running
    ↓
MONITOR detects: accuracy dropped > rollback_threshold
    ↓
Automatic rollback:
  1. Switch symlink back to previous version
  2. Log rollback in changelog.yaml
  3. Archive failed evolution with analysis
  4. Alert human
```

### 4. Evolution Rate Limiting

Prevent runaway evolution:

```yaml
evolution:
  rate_limits:
    max_proposals_per_agent_per_week: 2
    max_active_canaries: 3
    min_runs_between_evolutions: 5  # Same agent
    cooldown_after_rollback: 10     # Runs before retry
```

---

## Implementation Phases

### Phase 1: Foundation (v0.4.0)

1. Add evolution signals to CALIBRATE output
2. Implement prompt versioning directory structure
3. Add changelog.yaml and validation-results.yaml
4. Create `/speckit.cognitive-squad.evolutions` command (view proposals)

**No actual evolution yet — just infrastructure.**

### Phase 2: Proposals (v0.4.1)

1. Transform EVOLVE to generate proposals
2. Implement backtest capability
3. Add pending-evolutions/ workflow
4. Human approval via CLI

**Evolution proposed, human deploys manually.**

### Phase 3: Canary (v0.5.0)

1. Implement canary deployment in COMMANDER
2. Track canary outcomes in validation-results.yaml
3. Add MONITOR learning loop health checks
4. Implement automatic rollback

**Full automated canary with safety.**

### Phase 4: Global (v0.5.1)

1. Extend VETERAN for global evolution promotion
2. New projects inherit evolved prompts
3. Cross-project learning complete

---

## Metrics

### Evolution Effectiveness

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Proposal acceptance rate | > 60% | approved / proposed |
| Canary promotion rate | > 70% | promoted / canary deployed |
| Accuracy improvement per evolution | > 0.05 | post - pre accuracy |
| Time to approval | < 7 days | proposal date to approval date |
| Rollback rate | < 10% | rolled back / canary deployed |

### Learning Loop Health

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Pending proposals | < 5 | 5-10 | > 10 |
| Avg accuracy trend | improving | flat | declining |
| Evolution coverage | > 80% agents evolved | 50-80% | < 50% |
| Stale proposal age | < 14 days | 14-30 days | > 30 days |

---

## Comparison: Before vs After

### Before (Passive Learning)

```
Run 1: ARCHITECT makes scaling mistake → accuracy 0.60
Run 2: Same mistake → accuracy 0.55
Run 3: Same mistake → accuracy 0.52
Run 4: Same mistake → accuracy 0.50
Run 5: Human notices, manually fixes prompt
Run 6: Improvement
```

**Time to fix: 5 runs + human intervention**

### After (Active Learning)

```
Run 1: ARCHITECT makes scaling mistake → accuracy 0.60
Run 2: Same mistake → accuracy 0.55
       CALIBRATE: evolution_signal triggered
       EVOLVE: proposal generated, backtest positive
Run 3: Human approves → canary deployed (20%)
Run 4: Canary shows improvement (0.55 → 0.70)
Run 5: MONITOR promotes canary to 100%
Run 6: Full improvement
```

**Time to fix: 2 runs + 1 approval + 2 canary runs = faster, safer**

---

## Open Questions

1. **Backtest fidelity**: Can we accurately simulate "would this prompt change have affected this historical run"? May need to re-run with new prompt on cached inputs.

2. **Prompt drift**: Over many evolutions, prompts may become bloated. Need a "simplification evolution" that removes unnecessary sections.

3. **Conflicting evolutions**: Two evolutions proposed for same agent. Priority? Merge? Sequential canary?

4. **Cross-agent evolutions**: Some improvements require coordinated changes to multiple agents. How to handle?

5. **Negative evolutions**: Sometimes the right fix is to REMOVE prompt text. How to propose and validate removals?

---

## Appendix: Learning Loop Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         HUMAN APPROVAL GATE                             │
│                   (Reviews proposals, approves/rejects)                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ Proposals
┌───────────────────────────────────┴───────────────────────────────────┐
│                              EVOLVE                                    │
│                                                                        │
│   Inputs:                        Outputs:                              │
│   - Evolution signals            - Evolution proposals                 │
│   - Failure patterns             - Backtest results                    │
│   - Historical runs              - Prompt diffs                        │
│                                                                        │
│   Process:                                                             │
│   1. Receive signal from CALIBRATE                                     │
│   2. Analyze failure pattern                                           │
│   3. Generate minimal prompt change                                    │
│   4. Backtest on historical runs                                       │
│   5. Submit proposal if net_improvement > 0                            │
└───────────────────────────────────┬───────────────────────────────────┘
                                    ▲
                                    │ Evolution signals
┌───────────────────────────────────┴───────────────────────────────────┐
│                             CALIBRATE                                  │
│                                                                        │
│   Inputs:                        Outputs:                              │
│   - Reasoning journal            - Accuracy per domain                 │
│   - Quality gate scores          - Correction factors                  │
│   - Feedback outcomes            - Evolution signals (NEW)             │
│                                  - Failure analysis (NEW)              │
│                                                                        │
│   Signal triggers:                                                     │
│   - Accuracy < 0.7 after 5+ samples                                    │
│   - Declining trend (> 0.1 drop over 3 runs)                           │
│   - Recurring pitfall (3+ occurrences)                                 │
└───────────────────────────────────┬───────────────────────────────────┘
                                    ▲
                                    │ Outcomes
┌───────────────────────────────────┴───────────────────────────────────┐
│                          AGENT EXECUTION                               │
│                                                                        │
│   COMMANDER dispatches agents using:                                   │
│   - Current prompt version (80%)                                       │
│   - Canary prompt version (20%) if active                              │
│                                                                        │
│   Outcomes tracked:                                                    │
│   - Quality gate pass/fail                                             │
│   - Domain accuracy                                                    │
│   - Which prompt version was used                                      │
└───────────────────────────────────┬───────────────────────────────────┘
                                    ▲
                                    │ Monitoring
┌───────────────────────────────────┴───────────────────────────────────┐
│                             MONITOR                                    │
│                                                                        │
│   Existing checks:               New checks:                           │
│   - Process compliance           - Learning loop health                │
│   - Direction alignment          - Canary evaluation                   │
│   - Progress sanity              - Metric gaming detection             │
│                                                                        │
│   Actions:                                                             │
│   - Promote successful canary                                          │
│   - Rollback failing canary                                            │
│   - Alert on learning loop stall                                       │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Validated evolutions
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                             VETERAN                                    │
│                                                                        │
│   Promotes validated evolutions to global:                             │
│   - ~/.specify/squad-global/evolutions.yaml                            │
│   - New projects inherit improved prompts                              │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Recommendation

Start with **Phase 1** (infrastructure) immediately. It's low-risk and enables measurement.

**Phase 2** (proposals) is the critical unlock — once EVOLVE can propose, the human can start improving prompts systematically instead of ad-hoc.

**Phase 3** (canary) is where the real automation happens, but requires Phase 1+2 working reliably.

**Phase 4** (global) is the long-term multiplier — learning from one project benefits all projects.
