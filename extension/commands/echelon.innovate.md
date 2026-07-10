---
description: "Manually trigger INNOVATE specialist for fresh alternatives"
behavior:
  invocation: automatic
---

## Role

You are COMMANDER dispatching MAVERICK to generate fundamentally different approaches to the current feature. Use this when the squad may be stuck in a local optimum.

---

## User Input

$ARGUMENTS

---

## Overview

Manually dispatch the INNOVATE specialist to propose fundamentally different approaches to the current feature. Use this when you suspect the squad is stuck in a local optimum, or when you want creative alternatives before committing to architecture.

---

## Execution Continuity — MANDATORY

**Tool completions always require the next command step; they are never stopping
points.** After the INNOVATE subagent returns — however final its "alternatives
created" output looks — immediately execute Steps 4 through 6 (verify outputs,
update state and journal, report) without ending your response. INNOVATE's
alternatives output is not the end of this command; the verification and state
update steps must follow.

---

## Step 1: Validate Active Run

Read `${SQUAD_DIR}/state.json`.

- If the file does not exist, report **"No active squad run. Run speckit.echelon.run first."** and stop.
- If `status` is `"killed"` or `"done"`, report **"Squad run is already {status}. Start a new run first."** and stop.

Extract `spec_id` and `spec_dir` from `state.json`.

Treat `state.json.spec_dir` as authoritative. Do not locate, glob, search, list, or infer `specs/{spec_id}-*/`. If `state.json.spec_dir` is absent, report **"Active squad state is missing spec_dir; continue through the Echelon CLI so Python refreshes the run state."** and stop.

---

## Step 2: Gather Context

Read all current artifacts from the spec directory:
- `spec.md` (requirements -- what to innovate on)
- `plan.md` (current architecture approach, if exists)
- `research.md` (current technology decisions, if exists)
- `assumptions.md` (assumptions to challenge)
- `reasoning-journal.jsonl` (decision history)
- `evolution-report.md` (if exists -- prior run stagnation data)

Read these output templates and include them in the MAVERICK context pack:
- `extension/templates/alternatives-template.md`
- `extension/templates/risk-opportunities-template.md`
- `extension/templates/challenge-assumptions-template.md`

If `$ARGUMENTS` is provided, use it as the focus area for innovation. Otherwise, INNOVATE will perform a broad sweep.

---

## Step 3: Dispatch speckit-echelon-maverick (MAVERICK)

Read the INNOVATE agent prompt from `.specify/extensions/echelon/agents/specialists/maverick.md`.

Use the **Agent tool** to dispatch speckit-echelon-maverick as a subagent:

- **subagent_type:** `speckit-echelon-maverick`
- **prompt:** Read the file `.specify/extensions/echelon/agents/specialists/maverick.md` for your complete instructions. You are the INNOVATE specialist, triggered manually by the user. Your focus area: `{$ARGUMENTS or "broad sweep -- challenge all major decisions"}`. Apply TRIZ contradiction resolution, Design Thinking divergent exploration, and First Principles decomposition. Here is your context pack: [include all gathered artifacts and maverick output templates]. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries` for `reasoning-journal.jsonl`.
- **description:** "speckit-echelon-maverick: manual trigger -- {$ARGUMENTS summary or 'broad alternative exploration'}"

> **After the subagent returns, always proceed immediately to Step 4. Do not end your response here.**

---

## Step 4: Verify Outputs

After the subagent completes, verify these files were created or updated:

1. **`alternatives.md`** -- 2-3 fundamentally different approaches with trade-off analysis
2. **`risk-opportunities.md`** -- risks that could become opportunities with a different approach
3. **`challenge-assumptions.md`** -- assumptions from the current approach that may be wrong

Always log a warning for missing outputs. Do not fail the command for missing outputs.

---

## Step 5: Return State and Journal Updates

Return these updates in `echelon_result`; the harness applies state and journal writes:
- Add `"INNOVATE"` to `active_specialists` if not already present
- Update `updated_at` timestamp

Verify that `reasoning-journal.jsonl` has new entries from INNOVATE. If not, include this MANAGER entry in `echelon_result.journal_entries`:

```yaml
echelon_result:
  state_updates:
    active_specialists: <existing active_specialists plus INNOVATE>
    updated_at: "{ISO-8601}"
  output_files: []
  journal_entries:
    - type: decision
      agent: speckit-echelon-commander (COMMANDER)
      timestamp: "{ISO-8601}"
      data:
        artifact: "alternatives.md"
        section: "Manual specialist dispatch"
        reasoning: "User explicitly requested INNOVATE divergent exploration."
        rationale: "Dispatch MAVERICK for focus: {$ARGUMENTS or 'broad'}."
        content: "INNOVATE dispatched manually. Focus: {$ARGUMENTS or 'broad'}. Check alternatives.md for outputs."
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
them into the current approach via a re-run of speckit.echelon.run.
============================================
```
