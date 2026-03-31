# Autonomous Feedback Loop & Post-Build Validation

**Date:** 2026-03-31
**Spec ID:** ECHELON-002
**Status:** Design
**Depends on:** PR #42 (Risk Acceptance Protocol), ECHELON-001 (Improvement Spec)

---

## Problem Statement

Two critical gaps in the current squad architecture:

1. **Feedback requires human** — `/speckit.echelon.feedback` asks a human 6 sections of questions (effort, architecture, requirements, risks, tests, recommendations). Most runs never get feedback → calibration stagnates → estimates don't improve.

2. **No automatic post-build validation** — after build completes, the squad prints a summary and stops. There's no automatic check that what was built actually matches what was specified. The user has to manually run `/speckit.echelon.verify` (which doesn't even exist yet).

---

## Design: Autonomous Feedback Loop

### Core Idea

Replace the human questionnaire with **agent-driven self-assessment**. After build completes, COMMANDER automatically dispatches a feedback pipeline that:

1. Compares spec predictions against build outcomes (deterministic)
2. Routes CRITICAL findings back to COMMANDER for expert agent investigation
3. Updates calibration data without human input
4. Only escalates to human when it finds something it genuinely cannot assess

### New Flow

```
BUILD_DONE
    │
    ▼
┌──────────────────────────────────────────────┐
│  PHASE 5: AUTO-FEEDBACK (new)                │
│                                              │
│  Step 1: VERIFICATION (backpropagation)      │
│    └→ gap-report.md, verification-summary.md │
│                                              │
│  Step 2: AUDITOR (self-assessment)           │
│    └→ Compare: estimates vs actual build     │
│    └→ Compare: risk predictions vs actuals   │
│    └→ Compare: test strategy vs actual tests │
│    └→ auto-feedback.yaml                     │
│                                              │
│  Step 3: COMMANDER triage                    │
│    └→ CRITICAL findings? → dispatch experts  │
│        └→ INVESTIGATOR for unknowns          │
│        └→ GUARDIAN for security gaps          │
│        └→ MAVERICK if architecture pivoted   │
│    └→ NON-CRITICAL? → auto-update KB         │
│                                              │
│  Step 4: KB update (automatic)               │
│    └→ calibration-profile.yaml               │
│    └→ estimates-log.yaml                     │
│    └→ patterns.yaml / pitfalls.yaml          │
│                                              │
│  Step 5: Final validation gate               │
│    └→ Understanding re-scan on final code    │
│    └→ SAGE final opinion                     │
│                                              │
│  OUTPUT: feedback-report.md                  │
│  OUTPUT: auto-feedback.yaml                  │
│  OUTPUT: post-build-validation.md            │
└──────────────────────────────────────────────┘
    │
    ▼
DONE (with full feedback + validation)
```

---

## Detailed Specification

### Step 1: Auto-VERIFICATION (after BUILD_DONE)

**Already exists** in build.md Section 8.1c. VERIFICATION agent runs full backpropagation against spec. This step doesn't change — it just becomes the entry point for the feedback pipeline instead of the exit.

**Output:** `verification-summary.md`, `gap-report.md`, `traceability-matrix.md`

### Step 2: AUDITOR Self-Assessment (new mode)

AUDITOR currently runs during FINALIZE to track accuracy. Add a new **post-build mode** where AUDITOR compares predictions against outcomes using build artifacts as ground truth.

**Dispatch:**

```markdown
prompt: Read agents/learning/auditor.md. You are AUDITOR in **post-build self-assessment mode**.

Compare squad predictions against build outcomes:

1. EFFORT: Read estimates.md (predicted). Read state.json build phase timing 
   and task completion data (actual). Compute accuracy ratio per task and overall.
   
2. ARCHITECTURE: Read plan.md (predicted stack/design). Read the actual implemented 
   code structure (git diff, file tree). Flag any architecture pivots — decisions 
   in plan.md that were abandoned or changed during build.
   
3. REQUIREMENTS: Read spec.md (predicted requirements). Read verification-summary.md 
   and gap-report.md (actual coverage). Compute: requirements implemented as-written, 
   requirements that needed clarification, requirements that were missing, 
   requirements that turned out unnecessary.
   
4. RISKS: Read risk-matrix.md (predicted risks). Read reasoning-journal.json for 
   any BLOCKED, DEGRADED, or rework entries during build. Cross-reference: which 
   predicted risks materialized? What unpredicted blockers appeared?
   
5. TESTS: Read test-strategy.md (predicted test plan). Read test-quality-report.md 
   (actual test coverage). Flag gaps and over-tested areas.

Produce auto-feedback.yaml with the same schema as the human feedback file.
Produce feedback-report.md with a human-readable summary.

For each finding, assign severity: CRITICAL / HIGH / MEDIUM / LOW / INFO.
CRITICAL findings must be flagged for COMMANDER triage.
```

**Key insight:** AUDITOR doesn't need a human to answer "what was the actual effort?" — it can read `state.json` build timing, task completion counts, rework cycles, and PROGRESS TRACKER drift data. The build phase itself generates all the ground truth data.

### Step 3: COMMANDER Triage of Critical Findings

After AUDITOR produces `auto-feedback.yaml`, COMMANDER reads it and triages:

```
For each CRITICAL finding in auto-feedback.yaml:

  IF type == "architecture_pivot":
    → Dispatch INVESTIGATOR: "Why did plan.md decision X get abandoned during build? 
       Read the git diff and reasoning-journal entries. Was the original decision wrong, 
       or did new information emerge? Grade the evidence."
    → Dispatch MAVERICK if multiple pivots: "The architecture shifted significantly 
       during build. Propose how the original analysis could have caught this earlier."
    → Update patterns.yaml with the pivot as a pitfall

  IF type == "unpredicted_risk":
    → Dispatch INVESTIGATOR: "Risk Y materialized but was not in risk-matrix.md. 
       Research: is this a known risk pattern for this domain? What should GATEKEEPER 
       have checked?"
    → Dispatch GUARDIAN if security-related
    → Update calibration-profile.yaml to lower confidence for that risk domain

  IF type == "effort_overrun" AND ratio > 2.0:
    → Dispatch REALIST: "Effort was {ratio}x the estimate for domain X. 
       Run reference class forecasting: what do similar projects actually take?"
    → Update calibration-profile.yaml correction factor

  IF type == "requirements_gap" AND missing_count > 3:
    → Dispatch SAGE: "Spec missed {N} requirements that were needed during build. 
       Analyze why: were they implicit? Were they edge cases? 
       What Understanding metric should have caught them?"
    → Update pitfalls.yaml

  IF type == "test_gap" AND production_gaps > 0:
    → Dispatch SENTINEL: "Test strategy missed gaps that appeared in production. 
       What coverage pattern would have caught them?"
    → Update patterns.yaml

NON-CRITICAL findings:
  → Auto-update KB directly (no expert dispatch needed)
  → Append to estimates-log.yaml, patterns.yaml, pitfalls.yaml
```

### Step 4: Automatic KB Update

After all expert investigations complete (or immediately for non-critical findings):

```yaml
# Auto-updates to knowledge-base/calibration-profile.yaml:
- Domain accuracy adjusted based on effort ratio
- Correction factors updated
- Confidence scores adjusted (up if accurate, down if off)
- access_count and last_accessed updated (IMP-006)

# Auto-updates to knowledge-base/estimates-log.yaml:
- New entry with predicted vs actual effort per task
- Domain tagged for future reference class forecasting

# Auto-updates to knowledge-base/patterns.yaml:
- Architecture decisions that held → reinforced
- Architecture decisions that broke → caveat added

# Auto-updates to knowledge-base/pitfalls.yaml:
- Unpredicted risks → new pitfall entries
- Missing requirements patterns → new pitfall entries

# Auto-saves feedback:
- knowledge-base/feedback/{spec-id}-{project-name}.yaml
```

### Step 5: Post-Build Validation Gate (new)

After feedback is processed, run a **final validation pass** automatically:

**5a. Understanding re-scan**

If the build produced or modified spec-related artifacts, run Understanding one more time against the final state to get a "post-build quality score" that can be compared against the pre-build WHY3 score.

```markdown
Dispatch SAGE in post-build-validation mode:
- Run /speckit.understanding.validate against the final spec.md
- Compare scores against the last WHY3 quality-gates.md
- If any category dropped > 0.05: flag as REGRESSION
- If overall improved: log as IMPROVEMENT
- Produce post-build-validation.md
```

**5b. Code-spec alignment check**

```markdown
Dispatch VERIFICATION in final-check mode:
- Read all implemented code + all tests
- Verify every FR-*/AC-*/NFR-* in spec.md has:
  1. Implementing code (file + function)
  2. At least one test covering it
  3. No contradictions between code and spec
- Produce final-alignment-report.md
```

**5c. TRACKER final intent check**

```markdown
Dispatch TRACKER in post-build-alignment mode:
- Read user-intent.md (original user request)
- Read the build output (what was actually built)
- Answer: "Does what was built match what the user asked for?"
- If MISALIGNED: flag as CRITICAL in feedback-report.md
```

---

## Redesigned Validation Loop (End-to-End)

### Current: Linear with manual feedback

```
RUN → BUILD → DONE → (human runs /feedback manually, maybe)
```

### New: Closed loop with automatic validation

```
RUN → BUILD → AUTO-VERIFICATION → AUTO-FEEDBACK → EXPERT TRIAGE → KB UPDATE → FINAL VALIDATION → DONE
                                       │                                            │
                                       │ CRITICAL findings                          │
                                       ▼                                            │
                                  INVESTIGATOR                                      │
                                  GUARDIAN                                           │
                                  MAVERICK                                           │
                                  REALIST                                            │
                                  SAGE                                               │
                                  SENTINEL                                           │
                                       │                                            │
                                       └──── findings fed back ─────────────────────┘
```

### The validation chain at end of build becomes:

```
BUILD_DONE
  │
  ├─ 1. VERIFICATION (backpropagation — already exists)
  │     └→ gap-report.md, verification-summary.md
  │     └→ FAIL? → rework loop (already exists)
  │     └→ PASS? → continue
  │
  ├─ 2. AUDITOR self-assessment (NEW)
  │     └→ auto-feedback.yaml
  │     └→ CRITICAL findings → COMMANDER triage → expert dispatch
  │
  ├─ 3. Understanding re-scan (NEW)
  │     └→ post-build-validation.md
  │     └→ REGRESSION detected? → log warning
  │
  ├─ 4. TRACKER final intent check (NEW)
  │     └→ MISALIGNED? → flag CRITICAL
  │
  ├─ 5. KB auto-update (NEW)
  │     └→ calibration, estimates, patterns, pitfalls all updated
  │
  └─ 6. FINAL REPORT
        └→ feedback-report.md (comprehensive)
        └→ Everything the old human /feedback would have produced
           but generated automatically from build data
```

---

## Config

Add to `squad-config.yml`:

```yaml
feedback:
  # Automatic feedback after build (no human required)
  auto_feedback: true
  
  # Dispatch experts for CRITICAL findings
  expert_triage: true
  
  # Maximum expert dispatches during feedback (budget control)
  max_expert_dispatches: 3
  
  # Run Understanding re-scan after build
  post_build_validation: true
  
  # Run TRACKER intent alignment after build
  post_build_intent_check: true
  
  # Still allow manual /feedback override (adds human ground truth on top)
  allow_manual_override: true
```

---

## Changes to Existing Commands

### echelon.build.md

After Section 8 (BUILD_DONE), add new **Section 9: Auto-Feedback & Validation**:

```
After BUILD_DONE and before final summary:

1. Dispatch AUDITOR in post-build self-assessment mode
2. Read auto-feedback.yaml
3. For each CRITICAL finding: dispatch appropriate expert (max 3)
4. Wait for expert responses
5. Auto-update KB (calibration, estimates, patterns, pitfalls)
6. If post_build_validation enabled: dispatch SAGE + VERIFICATION + TRACKER
7. Produce feedback-report.md and post-build-validation.md
8. THEN print final summary (which now includes feedback data)
```

### echelon.feedback.md

**Keep it** but repurpose as **manual override**:

```
If auto_feedback already ran:
  → Show auto-feedback.yaml to human
  → Ask: "Do you agree with the auto-assessment? Any corrections?"
  → Human corrections override auto-assessment values
  → Re-update KB with corrected values

If auto_feedback did NOT run (e.g., build was manual):
  → Fall back to current human questionnaire (unchanged)
```

This means `/speckit.echelon.feedback` becomes optional but still valuable — human ground truth corrects any auto-assessment errors.

---

## Schema: auto-feedback.yaml

```yaml
spec_id: "{spec-id}"
project_name: "{project-name}"
feedback_date: "{ISO-8601}"
feedback_source: "auto"  # "auto" or "human" or "auto+human_override"
run_id: "{run_id}"

effort:
  estimated_total_hours: {N}
  actual_build_duration_minutes: {N}
  tasks_completed: {N}
  tasks_blocked: {N}
  tasks_degraded: {N}
  rework_cycles: {N}
  accuracy_ratio: {actual/estimated}
  severity: "{INFO|MEDIUM|HIGH|CRITICAL}"
  notes: "{auto-generated explanation}"

architecture_decisions:
  - decision: "{from plan.md}"
    held: "{yes|no|partially}"
    evidence: "{file path or git diff reference}"
    severity: "{INFO|MEDIUM|HIGH|CRITICAL}"

requirements:
  total_in_spec: {N}
  implemented_as_written: {N}
  needed_clarification: {N}
  missing_discovered_during_build: {N}
  unnecessary: {N}
  severity: "{INFO|MEDIUM|HIGH|CRITICAL}"

risks:
  predicted_count: {N}
  materialized_count: {N}
  unpredicted_blockers: {N}
  - risk: "{from risk-matrix.md}"
    materialized: {true|false}
    actual_impact: "{description}"
  unpredicted:
    - description: "{what happened}"
      source: "{reasoning-journal entry ID}"
      severity: "{MEDIUM|HIGH|CRITICAL}"

tests:
  strategy_coverage: {0.0-1.0}
  actual_coverage: {0.0-1.0}
  gaps_found: ["{list}"]
  over_tested: ["{list}"]

critical_findings:
  - id: "CF-001"
    type: "{architecture_pivot|unpredicted_risk|effort_overrun|requirements_gap|test_gap}"
    description: "{what happened}"
    severity: "CRITICAL"
    expert_dispatched: "{INVESTIGATOR|GUARDIAN|MAVERICK|REALIST|SAGE|SENTINEL|null}"
    expert_finding: "{result of expert investigation}"
    kb_action: "{what was updated in knowledge-base}"
```

---

## Impact on Existing Agents

| Agent | Change |
|-------|--------|
| AUDITOR | Add **post-build self-assessment mode** — compares predictions vs build outcomes |
| COMMANDER | Add **feedback triage** after BUILD_DONE — routes CRITICAL findings to experts |
| VERIFICATION | Already exists — becomes entry point of feedback pipeline |
| SAGE | Add **post-build-validation mode** — Understanding re-scan on final state |
| TRACKER | Add **post-build-alignment mode** — checks build output vs user intent |
| INVESTIGATOR | Unchanged — dispatched for CRITICAL unknowns during feedback triage |
| GUARDIAN | Unchanged — dispatched for CRITICAL security findings during feedback triage |
| MAVERICK | Unchanged — dispatched if architecture pivoted significantly |
| REALIST | Unchanged — dispatched for CRITICAL effort overruns |
| SENTINEL | Unchanged — dispatched for CRITICAL test gaps |

---

## What This Eliminates

| Before | After |
|--------|-------|
| Human must run `/feedback` manually | Auto-runs after every build |
| Human answers 6 sections of questions | AUDITOR self-assesses from build data |
| Calibration stagnates if no feedback | Calibration updates every build |
| No post-build validation | Understanding re-scan + TRACKER intent check + VERIFICATION |
| CRITICAL issues discovered post-build have no path back | COMMANDER dispatches experts for CRITICAL findings |
| Learning loop broken most of the time | Learning loop closed automatically every time |

---

## What Human Feedback Still Adds (optional)

Even with auto-feedback, human `/feedback` adds value for things agents can't assess:

1. **Quality perception** — "the code works but feels hacky"
2. **Business outcome** — "users loved it" or "users hated it"
3. **Team friction** — "the task descriptions confused the junior developer"
4. **Correction of auto-assessment** — "AUDITOR said architecture held, but we actually pivoted the auth system in week 2"

The system is designed so auto-feedback always runs, and human feedback optionally overrides/supplements it.
