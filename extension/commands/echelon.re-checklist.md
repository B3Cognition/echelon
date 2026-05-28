---
name: speckit.echelon.re-checklist
description: "Generate quality checklists for specs (per-domain + summary)"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_extraction:` section. Execute **only** phase
`re-extract-6-checklist` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Always execute only this phase; do
not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = re-extract-6-checklist` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
