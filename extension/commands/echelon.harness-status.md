---
description: "Show current ralph-loop state — active strategies, iterations, token usage, PR URLs"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER checking harness state. This is read-only — display per-strategy status without modifying anything.

---

## User Input

$ARGUMENTS

---

## Overview

Read-only command. Displays per-strategy status for all running, blocked, or recently completed loops. Modifies nothing.
Canonical CLI equivalent: `echelon delivery status`.

---

## Step 1: Check Initialized

If neither `.echelon/config.yml` nor the legacy `.specify/extensions/echelon/echelon-config.yml` exists, report:

**"Delivery not initialized. Run `echelon delivery init` first."** and stop.

---

## Step 2: Run Status

```bash
PYTHONPATH=.specify/extensions/echelon python3 -c "from harness.skills.status_skill import show_status; show_status()"
```

---

## Step 3: Display Output

The command prints directly to stderr. Relay the output to the user.

If `$ARGUMENTS` contains a `spec_id`, filter displayed strategies to that spec only.

**Expected output shapes:**

No state directory or no strategies found:
```
No active loops.
```

Active loops found:
```
--- LOOP STATUS ({n} active) ---

  {strategy_id}: {status} | iter {outer}.{inner} | tokens: {used}{ (pct% of budget)}
    Branch: {feature_branch or harness_branch}  ← echelon feature branch if present
    PR: {pr_url}                                ← only if present
    Blocked: see {escalation_file}              ← only if status=blocked
```

Corrupted state file:
```
  {strategy_id}: STATE CORRUPTED -- run echelon delivery resume <spec_id> "<answer>" to recover
```

---

## Step 4: Suggest Next Action

Based on the status output:

| Observed state | Suggest |
|----------------|---------|
| `blocked` | `echelon delivery resume <spec_id> "<your answer>"` |
| `converged` with PR shown | Review the PR; merge when satisfied — that closes the feature branch into `main` |
| `converged` with no PR | Review `.specify/harness/state/{spec_id}/` for output; push manually if needed |
| `failed` | Check error details, then re-run with `echelon delivery run <spec_id>` |
| No active loops | `echelon delivery run <spec_id>` to start one |
