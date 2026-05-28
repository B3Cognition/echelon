---
name: speckit.echelon.re-plan
description: "Generate per-domain plan.md files"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_planning:` section. Execute **only** phase
`re-planning-1-plan` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Always execute only this phase; do
not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = re-planning-1-plan` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
