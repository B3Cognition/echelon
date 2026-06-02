---
name: speckit.echelon.reopen
description: "Reopen a spec from fulfillment gaps and append harness-ready tasks"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER reopening a spec from verified fulfillment gaps.

Read `agents/control/commander.md` first. Then read `workflow/definition.yaml`
`reopen:` section. Start at `reopen-1-apply-gaps`.

ALWAYS mutate only the spec artifacts needed to resume implementation.
NEVER modify application source code.

Allowed writes:
- `{spec_dir}/spec.md` frontmatter/status
- `{spec_dir}/tasks.md`
- `{spec_dir}/reopen-{n}.md`

## User Input

$ARGUMENTS
