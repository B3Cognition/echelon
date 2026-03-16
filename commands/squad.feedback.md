---
description: "Post-implementation feedback intake -- closes the learning loop"
---

## User Input

$ARGUMENTS

---

## Overview

Collect post-implementation feedback for a completed squad run. This closes the learning loop: comparing what the squad predicted against what actually happened. The feedback updates the knowledge base so future runs produce better estimates, better risk predictions, and better architecture decisions.

---

## Step 1: Validate Input

If `$ARGUMENTS` is empty, report **"Please provide the spec ID. Usage: /speckit.squad.feedback 001"** and stop.

Extract `{spec-id}` from `$ARGUMENTS` (first token, e.g., "001").

---

## Step 2: Locate Original Artifacts

Scan `.specify/specs/` for a directory matching `{spec-id}-*` (e.g., `001-real-time-chat`).

- If not found, report **"No spec directory found for ID '{spec-id}'. Check .specify/specs/ for available IDs."** and stop.
- Extract the full directory name as `{spec-dir}` and the feature name as `{project-name}`.

Read the original artifacts:
- `estimates.md` -- original effort estimates
- `research.md` -- architecture decisions made
- `risk-matrix.md` -- predicted risks
- `test-strategy.md` -- test plan
- `spec.md` -- requirements
- `recommendations.md` -- SCIENTIST recommendations (if exists)
- `reasoning-journal.json` -- full decision log

---

## Step 3: Load Feedback Template

Read `.specify/extensions/cognitive-squad/templates/feedback-questionnaire.md`.

---

## Step 4: Walk Through Questionnaire

Present each section of the questionnaire to the user interactively. For each section, show the original squad prediction and ask for the actual outcome.

### 4.1 Effort Accuracy

Show the estimates from `estimates.md`. Ask:
- What was the actual effort (in days/hours)?
- What was over-estimated? What was under-estimated?
- Were there tasks not in the original plan?

### 4.2 Architecture Decisions

List each major decision from `research.md`. For each, ask:
- Did this decision hold during implementation? (Yes / No / Partially)
- What happened? Any pivots?

### 4.3 Requirements Quality

Reference `spec.md`. Ask:
- How many requirements were correct as-written?
- Which requirements needed clarification during implementation?
- What requirements were completely missing?
- What requirements turned out to be unnecessary?

### 4.4 Risk Accuracy

List each risk from `risk-matrix.md`. For each, ask:
- Did this risk materialize? (Yes / No)
- What was the actual impact?

Then ask: Were there risks that materialized but were NOT predicted?

### 4.5 Test Strategy Gaps

Reference `test-strategy.md`. Ask:
- What test gaps were found during implementation?
- What test gaps were found in production?
- What areas were over-tested?

### 4.6 SCIENTIST Recommendations (if applicable)

If `recommendations.md` exists, list each recommendation. Ask:
- Was this recommendation correct? (Yes / No / Partially)
- Notes on what happened.

---

## Step 5: Save Feedback

Compile all answers into the feedback questionnaire format. Save to:

```
knowledge-base/feedback/{spec-id}-{project-name}.yaml
```

Structure as YAML:

```yaml
spec_id: "{spec-id}"
project_name: "{project-name}"
feedback_date: "{ISO-8601}"
effort:
  estimated_days: {N}
  actual_days: {N}
  accuracy_ratio: {actual/estimated}
  notes: "{notes}"
architecture_decisions:
  - decision: "{decision}"
    held: "{yes|no|partially}"
    notes: "{notes}"
requirements:
  correct_count: {N}
  needed_clarification: {N}
  missing: ["{list}"]
  unnecessary: ["{list}"]
risks:
  - risk: "{risk}"
    materialized: {true|false}
    actual_impact: "{description}"
  unpredicted: ["{list}"]
test_strategy:
  implementation_gaps: ["{list}"]
  production_gaps: ["{list}"]
  over_tested: ["{list}"]
scientist_recommendations:
  - recommendation: "{rec}"
    correct: "{yes|no|partially}"
    notes: "{notes}"
```

---

## Step 6: Update Knowledge Base

### 6.1 Calibration Profile

Read `knowledge-base/calibration-profile.yaml`. Update accuracy data:
- Adjust domain confidence based on effort accuracy ratio
- If estimates were off by >50%, reduce confidence for that domain
- If estimates were within 20%, increase confidence

### 6.2 Estimates Log

Append to `knowledge-base/estimates-log.yaml`:

```yaml
- spec_id: "{spec-id}"
  project: "{project-name}"
  date: "{ISO-8601}"
  estimated_days: {N}
  actual_days: {N}
  ratio: {N}
  domain: "{domain from calibration}"
```

### 6.3 Patterns

Read `knowledge-base/patterns.yaml`. For architecture decisions that held, reinforce the pattern. For decisions that broke, add a counter-pattern or caveat.

---

## Step 7: Report

Print summary:

```
============================================
  FEEDBACK RECORDED: {spec-id}-{project-name}
============================================

Effort accuracy:     {ratio}x (estimated {N}d, actual {N}d)
Decisions held:      {count}/{total}
Requirements right:  {count}/{total}
Risks predicted:     {count}/{total materialized}
Unpredicted risks:   {count}

Knowledge base updated:
  - calibration-profile.yaml  (domain confidence adjusted)
  - estimates-log.yaml        (new entry added)
  - patterns.yaml             ({count} patterns reinforced/added)
  - feedback/{spec-id}-{project-name}.yaml (full feedback saved)

This data improves future squad runs. Thank you.
============================================
```
