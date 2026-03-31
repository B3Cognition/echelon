---
description: "Manually trigger INNOVATE specialist for fresh alternatives"
---

## User Input

$ARGUMENTS

---

## Overview

Manually dispatch the INNOVATE specialist to propose fundamentally different approaches to the current feature. Use this when you suspect the squad is stuck in a local optimum, or when you want creative alternatives before committing to architecture.

---

## Step 1: Validate Active Run

Read `.specify/squad/state.json`.

- If the file does not exist, report **"No active squad run. Run /speckit.echelon.run first."** and stop.
- If `status` is `"killed"` or `"done"`, report **"Squad run is already {status}. Start a new run first."** and stop.

Extract `spec_id` and locate the spec directory: `.specify/specs/{spec_id}-*/`.

---

## Step 2: Gather Context

Read all current artifacts from the spec directory:
- `spec.md` (requirements -- what to innovate on)
- `plan.md` (current architecture approach, if exists)
- `research.md` (current technology decisions, if exists)
- `assumptions.md` (assumptions to challenge)
- `reasoning-journal.json` (decision history)
- `evolution-report.md` (if exists -- prior run stagnation data)

If `$ARGUMENTS` is provided, use it as the focus area for innovation. Otherwise, INNOVATE will perform a broad sweep.

---

## Step 3: Dispatch INNOVATE

Read the INNOVATE agent prompt from `.specify/extensions/echelon/agents/specialists/maverick.md`.

Use the **Agent tool** to dispatch INNOVATE as a subagent:

- **prompt:** Read the file `.specify/extensions/echelon/agents/specialists/maverick.md` for your complete instructions. You are the INNOVATE specialist, triggered manually by the user. Your focus area: `{$ARGUMENTS or "broad sweep -- challenge all major decisions"}`. Apply TRIZ contradiction resolution, Design Thinking divergent exploration, and First Principles decomposition. Here is your context pack: [include all gathered artifacts]. Produce outputs in `.specify/specs/{spec_dir}/`. Append entries to `reasoning-journal.json`.
- **description:** "INNOVATE: manual trigger -- {$ARGUMENTS summary or 'broad alternative exploration'}"

---

## Step 4: Verify Outputs

After the subagent completes, verify these files were created or updated:

1. **`alternatives.md`** -- 2-3 fundamentally different approaches with trade-off analysis
2. **`risk-opportunities.md`** -- risks that could become opportunities with a different approach
3. **`challenge-assumptions.md`** -- assumptions from the current approach that may be wrong

If any are missing, log a warning but do not fail.

---

## Step 5: Update State and Journal

Update `.specify/squad/state.json`:
- Add `"INNOVATE"` to `active_specialists` if not already present
- Update `updated_at` timestamp

Verify that `reasoning-journal.json` has new entries from INNOVATE. If not, append a MANAGER entry:

```json
{
  "type": "note",
  "agent": "MANAGER",
  "timestamp": "{ISO-8601}",
  "content": "INNOVATE dispatched manually. Focus: {$ARGUMENTS or 'broad'}. Check alternatives.md for outputs."
}
```

---

## Step 6: Report

Print summary:

```
============================================
  INNOVATE Complete
============================================

Focus:        {$ARGUMENTS or 'broad sweep'}
Alternatives: {count from alternatives.md}
Files:        alternatives.md, risk-opportunities.md, challenge-assumptions.md

Review the alternatives and decide whether to incorporate
them into the current approach via a re-run of /speckit.echelon.run.
============================================
```
