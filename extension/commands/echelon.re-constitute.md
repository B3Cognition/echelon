---
name: speckit.echelon.re-constitute
description: "Generate strategic artifacts (constitution, strategy, risks, gaps, ADRs)"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_extraction:` section. Execute **only** phase
`re-extract-7-constitute` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Always execute only this phase; do
not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = re-extract-7-constitute` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
