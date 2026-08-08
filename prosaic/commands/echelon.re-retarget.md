---
name: echelon.re-retarget
description: Phase 2 brownfield — guided prompts to fill target stack and strategic
  decisions
---
## Role

You are COMMANDER executing the brownfield retargeting phase.

Use this command's declared `re_retarget` phase sequence as the authoritative
routing contract. Do not read `agents/control/commander.md` or
`workflow/definition.yaml` to rediscover governance, routing, or outputs.

Start at phase `re-retarget-0-preflight`, read each named phase contract before executing,
write all state to the resolved RE output directory (`runs/<run-id>/re/state.json`
during an active `echelon spec run`, otherwise `.echelon/re/state.json`).

**This command always elicits human decisions. It never generates code or specs.**

## Phase Sequence

1. `re-retarget-0-preflight` — `workflow/phases/re-retarget-0-preflight.md`
2. `re-retarget-1-input` — `workflow/phases/re-retarget-1-input.md`
3. DONE

---

## Resumption

If the resolved RE `state.json` exists with `status: in_progress` and
`last_dispatch.phase_id` in `re_retarget:`, resume from `last_dispatch.phase_id`.
If `post_dispatch_complete: false`, re-run that phase before advancing.

---

## Execution Continuity

After each phase completes, immediately execute the next transition. Stop only on DONE.

---

## User Input

{{args}}
