---
name: speckit.echelon.re-plan-all
description: "Phase 3 brownfield — generate per-domain plans and tasks after strategic decisions are filled"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield planning phase.

Use this command's declared `re_planning` phase sequence as the authoritative
routing contract. Do not read `agents/control/commander.md` or
`workflow/definition.yaml` to rediscover governance, routing, or outputs.

Start at phase `re-planning-0-preflight`, read each named phase contract before dispatching,
write all state to the resolved RE output directory (`runs/<run-id>/re/state.json`
during an active `echelon spec run`, otherwise `.specify/echelon/re/state.json`).

**This command always generates plans and tasks. It never writes implementation code.**

## Phase Sequence

1. `re-planning-0-preflight` — `workflow/phases/re-planning-0-preflight.md`
2. `re-planning-1-plan` — `workflow/phases/re-planning-1-plan.md`
3. `re-planning-2-tasks` — `workflow/phases/re-planning-2-tasks.md`
4. DONE

---

## Resumption

If the resolved RE `state.json` exists with `status: in_progress` and
`last_dispatch.phase_id` in `re_planning:`, resume from there. If
`post_dispatch_complete: false`, re-run that phase before advancing.

---

## Execution Continuity

After any Agent tool returns, immediately execute the next transition. Stop only on DONE
or unresolvable BLOCKED.

---

## User Input

$ARGUMENTS
