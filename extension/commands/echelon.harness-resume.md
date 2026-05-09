---
description: "Resume a blocked ralph-loop — provide the escalation answer and continue from current iteration"
behavior:
  invocation: explicit
---

## Role

You are ORCHESTRATOR resuming a blocked harness loop. Incorporate the user's escalation answer and continue from the current iteration — not from scratch.

---

## User Input

$ARGUMENTS

---

## Overview

Resume a loop that blocked waiting for human input. Incorporates the user's answer into the escalation file and re-launches from the current iteration (not from scratch).

---

## Step 1: Check Initialized

If `.specify/extensions/echelon/echelon-config.yml` does not exist, report:

**"Harness not initialized. Run `speckit.echelon.harness-init` first."** and stop.

---

## Step 2: Parse Input

Extract from `$ARGUMENTS`:
- `spec_id` — required; look for patterns like `spec 012`, `spec_id=012`, or a bare ID.
- `strategy_id` — optional, default `default`; look for `strategy aggressive` or `strategy_id=aggressive`.
- `answer` — everything else in `$ARGUMENTS` after the spec/strategy tokens.

If `spec_id` is missing, ask: **"Which spec? Provide a spec ID (e.g., `012`)."** and stop.

If `answer` is empty, ask: **"Please provide your answer to the escalation question."** and stop.

---

## Step 3: Validate State

Read `.specify/harness/state/{spec_id}/{strategy_id}.json`.

- If file does not exist: report **"No state found for spec `{spec_id}`, strategy `{strategy_id}`."** and stop.
- If `status` is not `blocked`: report **"Loop is not blocked. Current status: `{status}`."** Suggest `speckit.echelon.harness-status` and stop.
- If `escalation_file` is set: read it and display the escalation question to confirm the answer is relevant.

---

## Step 4: Resume

```bash
HARNESS_SPEC="{spec_id}" \
HARNESS_STRATEGY="{strategy_id}" \
HARNESS_ANSWER="{answer}" \
python -m harness resume
```

If the command exits non-zero, report the full error output and stop.

---

## Step 5: Display Result

```
Resume complete: {CONVERGED|status}
  PR: {pr_url}    ← only if present
```

If the loop blocked again on a new escalation, display the new question and prompt the user to run `speckit.echelon.harness-resume` again.
