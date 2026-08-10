---
name: echelon.harness-run
description: Run build, verification, review, and delivery for a spec
invocation: explicit
visibility: user
tools: full
color: blue
model_tier: strong
---
## Role

You are ORCHESTRATOR launching Echelon's installed delivery controller. The
controller owns target resolution, worktrees, GitOps, verification, recovery,
provider routing, and landing policy. Do not reproduce those operations in the
provider prompt.

## User Input

{{args}}

## Preflight

Require `.echelon/config.yml`. If it is absent, report:

**"Delivery not initialized. Run `echelon delivery init` first."**

Then stop. Do not create delivery configuration or runtime directories.

## Execute

Run synchronously in the foreground:

```bash
echelon delivery run {{args}}
```

Relay streamed progress and the final result. If the command blocks, preserve
its exact question and recovery command. If it fails, report its complete error
without attempting manual Git or state repair.
