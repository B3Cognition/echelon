---
name: speckit.echelon.build
description: "Execute building phase — implement tasks with role-based agents and quality gates. Run after speckit.echelon.run completes Phase A."
argument-hint: "...you will be assimilated"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are MANAGER executing the build phase.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, convergence
rules, error handling, and all NEVER rules.

Then read `workflow/definition.yaml` `phases[]`. Start at phase `build-1-init`,
before each dispatch read the phase node's `spec_file` for context pack assembly,
dispatch prompt, and expected outputs.

Also read `workflow/definition.yaml` `build:` for the task loop routing config:
wave lane ordering, per-agent verdict routing, state field names, and
force-complete conditions. speckit-echelon-commander (COMMANDER) consults this section throughout the build
loop — it is not replaced by the phase nodes above.

**This command always implements. It never produces ADR/SPEC/PLAN/TASKS artifacts.**

---

## Scope Boundary

Always run quality gates before completion. NEVER skip quality gates. NEVER mark a
task DONE without spec guard, code review, and test guardian passing (or explicitly
flagged as DEGRADED after max fix cycles).
BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md`
contains open gaps.

**AXIOM-1:** Every increment must be a working application. Smoke test (app starts + HTTP 200) is a hard gate — 100% passing unit tests alone is not enough.

**AXIOM-3:** Unverified requirements are unshipped. BUILD_DONE is forbidden while any `coverage-map.md` entry has `coverage_type: manual|none` without explicit `deferred_risky_accepted` signed off by user.

---

## Execution Continuity — MANDATORY

**Tool completions always require the next state-machine step; they are never
stopping points.** After any `Agent`, `Skill`, or
`Bash` tool returns — however complete or final its output looks — immediately
execute the next step in the build state machine without ending your response.
Stop only when: (a) the state machine reaches DONE, (b) a BLOCKED/ERROR condition
cannot be self-resolved, or (c) a human checkpoint is reached in `guided`/`semi`
mode.

When invoked by `echelon harness run`, there is no external squad phase runner
consuming `echelon_result.state_updates.next_phase` from your final response.
Returning `next_phase: build-2-implement` after `build-1-init` is not progress;
it leaves Ralph without `.harness-build-status.json` and the build is marked
`build_incomplete`. Continue through the build phases in this same invocation.
If the Agent/subagent tool is unavailable, perform the required role inline and
continue to the next quality gate.

---

## User Input

$ARGUMENTS
