---
name: speckit.echelon.status
description: "Show current Echelon spec run status through the Python harness"
behavior:
  invocation: explicit
---

## Role

You are a thin orchestrator for `echelon spec status`. Do not inspect run
directories, `state.json`, spec artifacts, or Echelon implementation files
yourself. The Python harness owns state discovery, artifact inventory, cost
summary, roadmap rendering, and next-step selection.

---

## Step 1: Run The Status Command

Run this command synchronously in the foreground using the Bash tool:

```bash
echelon spec status
```

Report the output verbatim. If the command exits non-zero, report the error and
stop.
