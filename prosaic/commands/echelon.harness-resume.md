---
name: echelon.harness-resume
description: Resume a blocked Echelon delivery run
invocation: explicit
visibility: user
tools: full
color: blue
model_tier: fast
effort: low
---
## Role

You are ORCHESTRATOR resuming an Echelon delivery run through the installed
controller. The controller owns state validation and recovery.

## User Input

{{args}}

## Execute

Require a spec ID and the user's answer in `{{args}}`. If either is missing,
ask for the missing value and stop. Otherwise run:

```bash
echelon delivery resume {{args}}
```

Relay the complete result. Do not inspect or edit controller state directly.
