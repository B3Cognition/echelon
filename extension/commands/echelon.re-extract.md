---
name: speckit.echelon.re-extract
description: "Phase 1 brownfield extraction — analyze codebase and generate domain specs + strategic artifacts"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield extraction pipeline.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, and all NEVER rules.

Then read `workflow/definition.yaml` `re_extraction:` section. Start at phase
`re-extract-0-preflight`, read each phase node's `spec_file` before dispatching,
write all state to `.specify/echelon/re/state.json`.

**This command always extracts and specifies. It never writes implementation code.**

---

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress`, resume from
`last_dispatch.phase_id`. If `post_dispatch_complete: false`, re-run that phase
before advancing.

---

## Execution Continuity

**Tool completions always require the next graph transition; they are never
stopping points.** After any Agent or Skill tool returns, immediately execute the
next transition in the graph without ending your response.
Stop only when: (a) the graph reaches DONE, (b) a BLOCKED condition cannot be
self-resolved.

---

## User Input

$ARGUMENTS
