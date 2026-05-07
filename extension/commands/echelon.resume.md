---
description: "Provide answer to human escalation -- resumes blocked squad run"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER resuming a blocked squad run after a human escalation has been answered. Incorporate the answer and continue the MANAGER flow.

---

## User Input

$ARGUMENTS

---

## Overview

Resume a blocked squad run by providing the human's answer to the escalation question. The squad blocked because it encountered an issue it could not resolve autonomously (see Section 16 of the design doc). This command incorporates the human's answer and continues the MANAGER flow.

---

## Execution Continuity — MANDATORY

**Tool completions are never stopping points.** After re-dispatching the agent in Step 7 — however complete the re-dispatched agent's output looks — immediately execute Step 8 (continue MANAGER flow) without ending your response. The re-dispatched agent's success is not the end of this command; MANAGER must continue driving through all remaining phases until DONE or a new BLOCKED condition is set.

---

## Step 1: Validate Input

If `$ARGUMENTS` is empty, report **"Please provide your answer. Usage: speckit.echelon.resume <your answer to the escalation question>"** and stop.

---

## Step 2: Load State

Read `.specify/squad/state.json`.

- If the file does not exist, report **"No squad run found. Nothing to resume."** and stop.
- If `status` is NOT `"blocked"`, report **"Squad run is not blocked (status: {status}). No escalation to resolve."** and stop.

Extract:
- `run_id`
- `phase` -- the phase where the squad blocked
- `blocked_reason`
- `escalation_question`
- `spec_id` and locate the spec directory: `.specify/specs/{spec_id}-*/`

---

## Step 3: Display Context

Print the escalation context so the user can confirm their answer:

```
============================================
  RESUMING SQUAD RUN
============================================

Run ID:    {run_id}
Phase:     {phase}
Question:  {escalation_question}
Reason:    {blocked_reason}

Your answer: {$ARGUMENTS}
============================================
```

---

## Step 4: Update State

Update `.specify/squad/state.json`:

```json
{
  "status": "running",
  "blocked_reason": null,
  "escalation_question": null,
  "updated_at": "{ISO-8601}"
}
```

---

## Step 5: Record Decision in Reasoning Journal

Read `.specify/specs/{spec_dir}/reasoning-journal.json`.

Append a new entry:

```json
{
  "type": "decision",
  "agent": "HUMAN",
  "timestamp": "{ISO-8601}",
  "content": "{$ARGUMENTS}",
  "context": {
    "escalation_question": "{escalation_question}",
    "blocked_reason": "{blocked_reason}",
    "phase": "{phase}"
  }
}
```

Write the updated journal back.

---

## Step 6: Determine Resume Point

Map the blocked `phase` to the appropriate agent to re-dispatch:

| Blocked Phase | Resume Action |
|---------------|---------------|
| `discover`    | Re-dispatch DISCOVER with human answer as additional context |
| `why1`        | Re-dispatch WHY1 with human answer incorporated |
| `what`        | Re-dispatch WHAT with human answer as constraint/clarification |
| `why2`        | Re-dispatch WHY2 or route to WHAT if answer changes requirements |
| `assess`      | Re-dispatch ASSESS with human answer (scope/feasibility input) |
| `specialists` | Re-dispatch the blocked specialist with human answer |
| `how`         | Re-dispatch HOW with human answer as architectural constraint |
| `test-architect` | Re-dispatch TEST speckit-echelon-architect (ARCHITECT) with human clarification |
| `plan`        | Re-dispatch PLAN with human answer |
| `consensus`   | Re-dispatch the blocked consensus agent (WHY3/ASSESS2/PLAN2) |
| `finalize`    | Re-dispatch the blocked finalize agent (GROUND/CALIBRATE) |

---

## Step 7: Re-dispatch Agent

Read the appropriate agent prompt file based on the blocked phase.

Assemble the context pack for that phase (follow the same context pack rules as `echelon.run.md` for that phase). Add the human's answer prominently:

```
## Human Escalation Response

The squad was blocked with this question: "{escalation_question}"

The human answered: "{$ARGUMENTS}"

Incorporate this answer as a binding constraint and continue your analysis.
```

Use the **Agent tool** to dispatch the subagent with the appropriate prompt, context pack, and the human's answer woven in.

- **description:** "Resuming {phase} with human input: {$ARGUMENTS truncated to 50 chars}"

> **After the subagent returns, proceed immediately to Step 8. Do not end your response here.**

---

## Step 8: Continue MANAGER Flow

After the re-dispatched agent completes:

1. Verify its expected outputs (per `echelon.run.md` phase definitions)
2. Run the gate check for that phase
3. Transition to the next phase as normal
4. Continue executing the MANAGER state machine from `echelon.run.md` through to FINALIZE

The run proceeds exactly as if the escalation never happened -- the human's answer is now part of the context and the normal flow resumes.

---

## Step 9: Report Continuation

Print:

```
============================================
  SQUAD RESUMED
============================================

Phase resumed:  {phase}
Human input:    {$ARGUMENTS truncated}
Next phase:     {next phase after gate check}

The squad is continuing autonomously.
============================================
```
