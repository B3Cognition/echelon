---
name: echelon.feedback
description: Post-implementation feedback intake
---
## Role

You are ORCHESTRATOR closing the learning loop by recording post-implementation feedback — either from automated assessment or human ground truth.

---

## User Input

{{args}}

---

## Overview

This command has two modes:

1. **Manual override mode** (default when called explicitly) — Human provides ground truth corrections on top of auto-feedback
2. **Standalone mode** (fallback when auto-feedback didn't run) — Full human questionnaire (legacy behavior)

Auto-feedback runs automatically after every build (see `echelon.build.md` Section 8.5). This manual command adds human ground truth that agents cannot self-assess: quality perception, business outcomes, team friction.

---

## Step 1: Validate Input

If `{{args}}` is empty, report **"Please provide the spec ID. Usage: echelon.feedback 001"** and stop.

Extract `{spec-id}` from `{{args}}` (first token, e.g., "001").

---

## Step 2: Locate Original Artifacts

Scan `specs/` for a directory matching `{spec-id}-*` (e.g., `001-real-time-chat`).

- If not found, report **"No spec directory found for ID '{spec-id}'. Check specs/ for available IDs."** and stop.
- Extract the full directory name as `{spec-dir}` and the feature name as `{project-name}`.

---

## Step 3: Check for Existing Auto-Feedback

Check if `knowledge-base/feedback/{spec-id}-{project-name}.yaml` exists AND has `feedback_source: "auto"`.

**If auto-feedback EXISTS → Manual Override Mode (Step 4a)**
**If auto-feedback MISSING → Standalone Mode (Step 4b)**

---

## Step 4a: Manual Override Mode

Auto-feedback already ran. Show the human what the squad self-assessed, and let them correct it.

### 4a.1 Present Auto-Assessment

Read `knowledge-base/feedback/{spec-id}-{project-name}.yaml`. For each section, show:

```
EFFORT (auto-assessed):
  Estimated: {N} hours → Actual build: {N} minutes
  Accuracy ratio: {ratio}x
  Auto-severity: {severity}
  
  → Do you agree? Any correction? (press Enter to accept, or type correction)
```

```
ARCHITECTURE (auto-assessed):
  Decision: "{decision}" → Held: {yes/no/partially}
  Evidence: {file reference}
  
  → Correct? (Enter to accept, or type what actually happened)
```

Repeat for: requirements, risks, tests.

### 4a.2 Additional Human-Only Questions

These are things agents CANNOT self-assess:

1. **Quality perception** — "How does the code feel? Clean? Hacky? Over-engineered?"
2. **Business outcome** — "Did users/stakeholders respond positively?"
3. **Team friction** — "Were task descriptions clear enough for the team?"
4. **Missed context** — "Was there domain knowledge the squad should have had but didn't?"

### 4a.3 Save Override

Update `knowledge-base/feedback/{spec-id}-{project-name}.yaml`:
- Set `feedback_source: "auto+human_override"`
- Override any corrected values
- Add `human_additions` section with quality perception, business outcome, team friction
- Preserve original auto-assessed values as `auto_original` for calibration comparison

### 4a.4 Re-Update KB with Corrections

If the human corrected any values that differ from auto-assessment:
- Re-run calibration-profile.yaml update with corrected values
- Log the auto-assessment error in `reasoning-journal.jsonl` so echelon.auditor (AUDITOR) can learn where its self-assessment was wrong

---

## Step 4b: Standalone Mode (Legacy — no auto-feedback exists)

Full human questionnaire. This is the original behavior, used when:
- Build was done manually (not via `echelon.build`)
- `feedback.auto_feedback` was disabled in config

Read the original artifacts:
- `estimates.md`, `research.md`, `risk-matrix.md`, `test-strategy.md`, `spec.md`
- `recommendations.md` (if exists), `reasoning-journal.jsonl`

### 4b.1 Effort Accuracy

Show the estimates from `estimates.md`. Ask:
- What was the actual effort (in days/hours)?
- What was over-estimated? What was under-estimated?
- Were there tasks not in the original plan?

### 4b.2 Architecture Decisions

List each major decision from `research.md`. For each, ask:
- Did this decision hold during implementation? (Yes / No / Partially)
- What happened? Any pivots?

### 4b.3 Requirements Quality

Reference `spec.md`. Ask:
- How many requirements were correct as-written?
- Which requirements needed clarification during implementation?
- What requirements were completely missing?
- What requirements turned out to be unnecessary?

### 4b.4 Risk Accuracy

List each risk from `risk-matrix.md`. For each, ask:
- Did this risk materialize? (Yes / No)
- What was the actual impact?
Then ask: Were there risks that materialized but were NOT predicted?

### 4b.5 Test Strategy Gaps

Reference `test-strategy.md`. Ask:
- What test gaps were found during implementation?
- What test gaps were found in production?
- What areas were over-tested?

### 4b.6 SCIENTIST Recommendations (if applicable)

If `recommendations.md` exists, list each recommendation. Ask:
- Was this recommendation correct? (Yes / No / Partially)
- Notes on what happened.

### 4b.7 Save Feedback

Save to `knowledge-base/feedback/{spec-id}-{project-name}.yaml` with `feedback_source: "human"`.

---

## Step 5: Update Knowledge Base

### 5.1 Calibration Profile

Read `knowledge-base/calibration-profile.yaml`. Update accuracy data:
- Adjust domain confidence based on effort accuracy ratio
- If estimates were off by >50%, reduce confidence for that domain
- If estimates were within 20%, increase confidence

### 5.2 Estimates Log

Append to `knowledge-base/estimates-log.yaml`:

```yaml
- spec_id: "{spec-id}"
  project: "{project-name}"
  date: "{ISO-8601}"
  estimated_days: {N}
  actual_days: {N}
  ratio: {N}
  domain: "{domain from calibration}"
  source: "{auto|human|auto+human_override}"
```

### 5.3 Patterns

Read `knowledge-base/patterns.yaml`. For architecture decisions that held, reinforce the pattern. For decisions that broke, add a counter-pattern or caveat.

### 5.4 Auto-Assessment Accuracy (Mode 4a only)

If this was a manual override that corrected auto-assessed values, log the discrepancy:

```yaml
# Append to knowledge-base/feedback/auto-assessment-accuracy.yaml
- spec_id: "{spec-id}"
  date: "{ISO-8601}"
  corrections:
    - field: "effort.accuracy_ratio"
      auto_value: 1.8
      human_value: 2.3
      delta: 0.5
    - field: "architecture_decisions[0].held"
      auto_value: "yes"
      human_value: "partially"
```

This data trains echelon.auditor (AUDITOR)'s self-assessment accuracy over time.

---

## Step 6: Report

Print summary:

```
============================================
  FEEDBACK RECORDED: {spec-id}-{project-name}
============================================

Mode:                {auto+human_override | human (standalone)}
Effort accuracy:     {ratio}x (estimated {N}d, actual {N}d)
Decisions held:      {count}/{total}
Requirements right:  {count}/{total}
Risks predicted:     {count}/{total materialized}
Unpredicted risks:   {count}

{If override mode:}
Auto-assessment corrections: {count} values overridden
Auto-assessment accuracy: {correct}/{total} self-assessed values were accurate

Knowledge base updated:
  - calibration-profile.yaml  (domain confidence adjusted)
  - estimates-log.yaml        (new entry added)
  - patterns.yaml             ({count} patterns reinforced/added)
  - feedback/{spec-id}-{project-name}.yaml (full feedback saved)

This data improves future squad runs. Thank you.
============================================
```
