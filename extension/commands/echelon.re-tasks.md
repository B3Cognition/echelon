---
name: speckit.echelon.re-tasks
description: "Generate per-domain tasks.md files"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_planning:` section. Execute **only** phase
`re-planning-2-tasks` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Do not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = re-planning-2-tasks` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
