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

**This command implements. It never produces ADR/SPEC/PLAN/TASKS artifacts.**

---

## Scope Boundary

NEVER skip quality gates. NEVER mark a task DONE without spec guard, code review,
and test guardian passing (or explicitly flagged as DEGRADED after max fix cycles).
BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md`
contains open gaps.

**AXIOM-1:** Every increment must be a working application. Smoke test (app starts + HTTP 200) is a hard gate — 100% passing unit tests alone is not enough.

**AXIOM-3:** Unverified requirements are unshipped. BUILD_DONE is forbidden while any `coverage-map.md` entry has `coverage_type: manual|none` without explicit `deferred_risky_accepted` signed off by user.

---

## Execution Continuity — MANDATORY

**Tool completions are never stopping points.** After any `Agent`, `Skill`, or
`Bash` tool returns — however complete or final its output looks — immediately
execute the next step in the build state machine without ending your response.
Stop only when: (a) the state machine reaches DONE, (b) a BLOCKED/ERROR condition
cannot be self-resolved, or (c) a human checkpoint is reached in `guided`/`semi`
mode.

---

## User Input

$ARGUMENTS
