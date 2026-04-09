---
description: "Check current cognitive squad state and progress"
behavior:
  invocation: explicit
---

## Overview

Display the current state of the Echelon, including active run progress, quality trajectory, and artifact inventory. This is a read-only command -- it modifies nothing.

---

## Step 1: Load State

Read `.specify/squad/state.json`.

- If the file does not exist, report **"No active squad run."** and stop.
- Parse the JSON. If malformed, report the parse error and stop.

---

## Step 2: Display Run Header

Print:

```
============================================
  ECHELON STATUS
============================================

Run ID:      {run_id}
Status:      {status}
Phase:       {phase}
Mode:        {mode}
Iteration:   {iteration}
Created:     {created_at}
Updated:     {updated_at}
```

Also print workflow state if present:

```
Workflow:    {workflow_state or "n/a"}
```

Accepted split-phase workflow values:

- `BUILD_IN_PROGRESS`
- `BUILD_COMPLETE`
- `QA_IN_PROGRESS`
- `QA_COMPLETE`
- `QA_FAILED`
- `REWORK_PLANNED`
- `CHANGE_PENDING`
- `ESCALATED`

---

## Step 3: Quality Scores Trajectory

If `quality_scores` array is non-empty, print each pass:

```
QUALITY TRAJECTORY:
  Pass  Overall  Structure  Testability  Semantic  Cognitive  Readability
  1     0.52     0.60       0.45         0.48      0.55       0.62
  2     0.68     0.72       0.65         0.60      0.58       0.70
  ...
```

If no quality scores yet, print: `Quality: No WHY passes completed yet.`

---

## Step 4: Active Specialists

Print the `active_specialists` array. If empty, print: `Specialists: None summoned yet.`

---

## Step 5: Issues and Escalations

If `status` is `"blocked"`, prominently display:

```
!! BLOCKED — HUMAN INPUT REQUIRED !!
Question: {escalation_question}
Reason:   {blocked_reason}

Resume with: /speckit.echelon.resume {your answer}
```

Print all entries from `issues_log`:

```
ISSUES:
  {id}  [{severity}]  {source}: {description}  (x{occurrences}) {resolved ? "RESOLVED" : "OPEN"}
```

If no issues, print: `Issues: None logged.`

---

## Step 6: Artifact Inventory

Derive the spec directory from `state.json` fields: `.specify/specs/{spec_id}-*/`.

Scan the spec directory and list all files found, grouped by producer:

```
ARTIFACTS:
  DISCOVER:       glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md
  WHAT:           spec.md, 00-overview.md
  WHY:            issues.md, quality-gates.md, assumption-review.md
  ASSESS:         feasibility.md, prioritization.md, estimates.md, mvp-scope.md
  HOW:            plan.md, research.md, data-model.md, constitution.md, contracts/
  TEST ARCHITECT: test-strategy.md, test-architecture.md, coverage-map.md
  PLAN:           tasks.md, critical-path.md, risk-matrix.md, dependencies.md
  GROUND:         reality-check.md, cost-analysis.md, benchmark-data.md
  SCIENTIST:      investigation/*.md, evidence-grades.md, recommendations.md
  CALIBRATE:      confidence-flags.md
  EVOLVE:         evolution-report.md, improvement-metrics.md
  REFLECT:        (updates knowledge-base/)
  Journal:        reasoning-journal.json
```

Mark each as `OK` (exists) or `--` (not yet produced). Count total files.

---

## Step 7: Token Usage

Print estimated token usage from `state.json.token_usage`:

```
Token Usage: ~{token_usage} tokens ({percentage}% of {budget}k budget)
```

---

## Step 8: Prior Runs

Scan `.specify/squad/` for any files matching `state-*.json` or other state snapshots. Also scan `.specify/specs/` for directories to list prior completed runs:

```
PRIOR RUNS:
  001-real-time-chat    done      2026-03-15
  002-legacy-api        killed    2026-03-16
```

If no prior runs, print: `Prior Runs: None.`

---

## Step 9: Print Footer

```
============================================
  End of status report
============================================
```
