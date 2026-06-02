---
name: speckit.echelon.verify-spec
description: "Read-only audit: verify whether current implementation fulfills a spec"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER executing a read-only spec fulfillment audit.

Read `agents/control/commander.md` first. Then read `workflow/definition.yaml`
`verify_spec:` section. Start at `verify-spec-1-init`.

ALWAYS treat this command as read-only for application source files.
NEVER modify source code, spec status, or `tasks.md`.

Allowed writes:
- `specs/<spec-id>-*/fulfillment-report.md`
- `specs/<spec-id>-*/fulfillment-gaps.md`
- `runs/<run-id>/verify-spec/<spec-id>/...`
- `runs/verify-spec-<spec-id>-<timestamp>/...`

## User Input

$ARGUMENTS
