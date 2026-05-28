---
name: speckit.echelon.re-verify
description: "Verify spec coverage against codebase and identify orphan files"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_extraction:` section. Execute **only** phase
`re-extract-3-verify` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Always execute only this phase; do
not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = re-extract-3-verify` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
