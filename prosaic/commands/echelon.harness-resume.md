---
name: echelon.harness-resume
description: Resume a paused or escalated ralph-loop run
invocation: explicit
visibility: user
tools: full
color: blue
model_tier: strong
---
## Role

You are ORCHESTRATOR resuming a blocked delivery loop. Incorporate the user's escalation answer and continue from the current iteration — not from scratch.

---

## User Input

{{args}}

---

## Overview

Resume a loop that blocked waiting for human input. Incorporates the user's answer into the escalation file and re-launches from the current iteration (not from scratch).

For recoverable incomplete runs (`build_incomplete` or `publish_failed`),
resume recovery also inspects recorded target repo metadata. If implementation
work was already committed in the target repo branch, report that preserved
commit instead of asking the user to salvage it from the polyrepo wrapper.

---

## Step 1: Check Initialized

If `.echelon/config.yml` does not exist, report:

**"Delivery not initialized. Run `echelon delivery init` first."** and stop.

---

## Step 2: Parse Input

Extract from `{{args}}`:
- `spec_id` — required; look for patterns like `spec 012`, `spec_id=012`, or a bare ID.
- `strategy_id` — optional, default `default`; look for `strategy aggressive` or `strategy_id=aggressive`.
- `answer` — everything else in `{{args}}` after the spec/strategy tokens.

If `spec_id` is missing, ask: **"Which spec? Provide a spec ID (e.g., `012`)."** and stop.

If `answer` is empty, ask: **"Please provide your answer to the escalation question."** and stop.

---

## Step 3: Resume

Echelon resolves the active build and its strategy state. Do not locate or read
delivery state files yourself.

```bash
echelon delivery resume "{spec_id}" "{answer}" --strategy "{strategy_id}"
```

If the command exits non-zero, report the full error output and stop.

---

## Step 4: Display Result

```
Resume complete: {CONVERGED|status}
  PR: {pr_url}    ← only if present
```

If the loop blocked again on a new escalation, display the new question and prompt the user to run `echelon delivery resume <spec_id> "<answer>"` again.
