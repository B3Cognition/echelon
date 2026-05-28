---
name: speckit.echelon.re-retarget
description: "Phase 2 brownfield — guided prompts to fill target stack and strategic decisions"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield retargeting phase.

**Read `agents/control/commander.md` first.**

Then read `workflow/definition.yaml` `re_retarget:` section. Start at phase
`re-retarget-0-preflight`, read each phase node's `spec_file` before executing,
write all state to `.specify/echelon/re/state.json`.

**This command always elicits human decisions. It never generates code or specs.**

---

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress` and
`last_dispatch.phase_id` in `re_retarget:`, resume from `last_dispatch.phase_id`.
If `post_dispatch_complete: false`, re-run that phase before advancing.

---

## Execution Continuity

After each phase completes, immediately execute the next transition. Stop only on DONE.

---

## User Input

$ARGUMENTS
