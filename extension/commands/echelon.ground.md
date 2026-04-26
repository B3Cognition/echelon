---
description: "Trigger reality check on all current artifacts"
behavior:
  invocation: automatic
---

## Role

You are COMMANDER triggering a reality check. Dispatch REALIST to connect squad artifacts to real-world data, costs, and historical outcomes.

---

## User Input

$ARGUMENTS

---

## Overview

Dispatch the GROUND agent to perform a reality check on all current squad artifacts. GROUND connects plans to real-world data: infrastructure costs, production benchmarks, team capacity, and historical project outcomes. Use this when you want an honest assessment before committing to implementation.

---

## Execution Continuity — MANDATORY

**Tool completions are never stopping points.** After the GROUND subagent returns — however complete its reality-check output looks — immediately execute Steps 4 through 6 (verify outputs, update state and journal, report) without ending your response. GROUND's report is not the end of this command; the state update and report steps must follow.

---

## Step 1: Validate Active Run

Read `.specify/squad/state.json`.

- If the file does not exist, report **"No active squad run. Run speckit.echelon.run first."** and stop.
- If `status` is `"killed"`, report **"Squad run was killed. Start a new run."** and stop.

Extract `spec_id` and locate the spec directory: `.specify/specs/{spec_id}-*/`.

---

## Step 2: Gather Context

Read all current artifacts from the spec directory:
- `spec.md` -- requirements to reality-check
- `plan.md` -- architecture to validate against real-world constraints
- `research.md` -- technology decisions to benchmark
- `estimates.md` -- effort estimates to compare against historical data
- `data-model.md` -- data design to check for operational feasibility
- `tasks.md` -- task breakdown to validate durations
- `risk-matrix.md` -- risks to check against real-world occurrence rates
- `test-strategy.md` -- test plan to check against real-world coverage norms
- `reasoning-journal.json` -- decision history

Read knowledge base files:
- `knowledge-base/estimates-log.yaml` -- past project estimates vs actuals
- `knowledge-base/calibration-profile.yaml` -- AI confidence per domain
- `knowledge-base/feedback/` -- past project outcomes (scan directory for all .yaml files)

If `$ARGUMENTS` is provided, use it to focus the reality check on a specific area (e.g., "cost estimates", "performance claims", "timeline feasibility").

---

## Step 3: Dispatch GROUND

Read the GROUND agent prompt from `.specify/extensions/echelon/agents/learning/realist.md`.

Use the **Agent tool** to dispatch GROUND as a subagent:

- **prompt:** Read the file `.specify/extensions/echelon/agents/learning/realist.md` for your complete instructions. You are the GROUND agent. Perform a comprehensive reality check on all current artifacts. Focus area: `{$ARGUMENTS or "full sweep"}`. Connect plans to real-world data: check infrastructure costs against actual cloud pricing, validate performance claims against published benchmarks, compare effort estimates to historical data in estimates-log.yaml, check architectural decisions against production operational constraints. Apply reference class forecasting where applicable. Here is your context pack: [include all gathered artifacts and knowledge base files]. Produce outputs in `.specify/specs/{spec_dir}/`. Append entries to `reasoning-journal.json`.
- **description:** "GROUND: reality check -- {$ARGUMENTS summary or 'full artifact sweep'}"

> **After the subagent returns, proceed immediately to Step 4. Do not end your response here.**

---

## Step 4: Verify Outputs

After the subagent completes, verify these files were created or updated:

1. **`reality-check.md`** -- findings organized by artifact, with severity ratings
2. **`cost-analysis.md`** -- infrastructure and operational cost estimates grounded in real pricing
3. **`benchmark-data.md`** -- real-world benchmarks for performance claims in the spec

If any are missing, log a warning but do not fail.

---

## Step 5: Update State and Journal

Update `.specify/squad/state.json`:
- Update `updated_at` timestamp

Verify that `reasoning-journal.json` has new GROUND entries. If not, append a MANAGER entry:

```json
{
  "type": "reality-check",
  "agent": "MANAGER",
  "timestamp": "{ISO-8601}",
  "content": "GROUND dispatched manually. Focus: {$ARGUMENTS or 'full sweep'}. Check reality-check.md for findings."
}
```

---

## Step 6: Report

Print summary:

```
============================================
  GROUND Reality Check Complete
============================================

Focus:            {$ARGUMENTS or 'full sweep'}
Findings:         {count from reality-check.md by severity}
Cost estimate:    {summary from cost-analysis.md}
Benchmark gaps:   {count of claims without supporting benchmarks}

Key disconnects:  {1-3 bullet summary of biggest reality gaps}

Full report:      .specify/specs/{spec_dir}/reality-check.md
============================================
```
