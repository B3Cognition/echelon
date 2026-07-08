---
description: "Provide answer to human escalation — resumes blocked squad run"
behavior:
  invocation: explicit
---

## Role

You are a thin orchestrator for `echelon spec resume`. Your only job is to pass the user's
answer to the harness CLI and report the result. Always let the Python harness own
agent dispatch, phase specs, and gate checks. Do not re-dispatch agents, read phase
specs, or run gate checks.

---

## User Input

$ARGUMENTS

---

## Step 1: Validate input

If `$ARGUMENTS` is empty:

```
Usage: echelon spec resume "<your answers>"

Answer the escalation questions shown when the run printed
"blocked — human input required".

Example:
  echelon spec resume "Q1: yes, I own the IP  Q2: 13+  Q3: short 5-15 min missions"
```

Stop.

---

## Step 2: Run the harness resume command

```bash
echelon spec resume "$ARGUMENTS"
```

This single command:

1. Finds the active blocked run via `squad/.current`
2. Verifies `status == "blocked"` and `escalation_question` is present
3. Displays a `RESUMING SQUAD RUN` context block (Run ID, Phase, Question, Answer)
4. Writes the answer to `staging/user-clarifications.md`
5. Clears the blocked state (`escalation_question`, `blocked_reason`, `status`)
6. Re-dispatches the squad from the blocked phase
7. Displays a `SQUAD RESUMED` summary block on completion

Report the output verbatim. If the command exits non-zero, report the error and stop.
