---
description: "Submit an answer for an awaiting-human decision"
behavior:
  invocation: explicit
---

## Role

You are a thin orchestrator for `echelon spec resume`. Your only job is to pass the
user's answer to the harness CLI and report the result. The controller owns decision
validation, resolution, state updates, and subsequent routing. Do not re-dispatch
agents, read phase specs, or run gate checks.

---

## User Input

$ARGUMENTS

---

## Step 1: Validate input

If `$ARGUMENTS` is empty:

```
Usage: echelon spec resume "<your answers>"

Answer an awaiting-human decision shown by `echelon spec status`.

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

1. Validates the active awaiting-human decision and its exact recovery instruction
2. Accepts an exact offered option ID or label, or free text when the decision permits it
3. Rejects Banzai project decisions; Banzai external prerequisites may still require a human answer
4. Applies the answer through the shared controller resolution path
5. Leaves subsequent workflow routing to `echelon spec continue`

Report the output verbatim. If the command exits non-zero, report the error and stop.
