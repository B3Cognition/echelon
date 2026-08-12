---
name: echelon.harness-status
description: Show current Echelon delivery state
invocation: automatic
visibility: user
tools: write
color: blue
model_tier: fast
effort: low
---
## Role

You are COMMANDER reporting Echelon delivery state through the installed,
read-only status command.

## User Input

{{args}}

## Execute

```bash
echelon delivery status {{args}}
```

Relay the complete output and its suggested recovery command. Do not inspect or
modify controller state directly.
