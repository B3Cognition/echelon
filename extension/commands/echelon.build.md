---
name: speckit.echelon.build
description: "Execute building phase — implement tasks with role-based agents and quality gates. Run after speckit.echelon.run completes Phase A."
argument-hint: "...you will be assimilated"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are MANAGER executing one Ralph-bounded delivery build slice.

Ralph owns phase routing, task selection, progress bookkeeping, verification
refreshes, commits, and delivery state. Use only the Ralph-owned context pack,
the current command arguments, and the delivery phase contracts already exposed
to this invocation. Do not discover or read Echelon orchestration internals to
infer build routing.

**This command always implements. It never produces ADR/SPEC/PLAN/TASKS artifacts.**

---

## Scope Boundary

Always run quality gates before completion. NEVER skip quality gates. NEVER mark a
task DONE without spec guard, code review, and test guardian passing (or explicitly
flagged as DEGRADED after max fix cycles).
Full-spec BUILD_DONE is forbidden while `verification-summary.md` is FAIL or
`gap-report.md` contains open gaps. This does not forbid writing harness
`{"status":"done"}` after one verified build iteration; Ralph treats that marker
as iteration completion, not total MVP completion.

When `HARNESS_BUILD_STATUS_FILE` is set, a build invocation is **one bounded
verified progress slice**, not the whole MVP and not the whole build state
machine. After completing a task or coherent small batch and running the
required quality gates for that slice, write `{"status":"done","reason":"..."}`
to `$HARNESS_BUILD_STATUS_FILE` and stop. Include
`"completed_task_ids":["T-001"]` with the exact canonical task row IDs completed
in the slice; Ralph marks those rows DONE in `tasks.md` before verify. Ralph
owns the outer loop: it will verify, commit, and invoke the next build slice
when more tasks remain.

Never edit `tasks.md`, `spec.md`, `progress-report.md`, or other spec artifacts
to record build progress during a harness build slice. Treat spec artifact paths
as read-only inputs unless the command is explicitly a spec-authoring,
reopen/reconcile, or verify-spec reconcile command. For delivery builds, progress
is reported only through `$HARNESS_BUILD_STATUS_FILE.completed_task_ids`; Ralph
performs the deterministic `tasks.md` update after the build invocation returns.

Do not use native task-planning tools such as TaskCreate or TaskUpdate under
`echelon delivery run`. They create provider-local todos only; Ralph does not
consume them. Select work from canonical `tasks.md` rows and report progress
only through `$HARNESS_BUILD_STATUS_FILE`.

`fulfillment-report.md` and `fulfillment-gaps.md` are verify-spec-owned
judgment artifacts. NEVER hand-edit them during `echelon build` or a harness
build slice to make a text gate pass. Implement source/tests, write the harness
status marker with exact `completed_task_ids`, and let Ralph run verify-spec to
regenerate those reports from fresh evidence.

Never report ranges or grouped labels as completed task IDs. `T-063..T-068`,
`T-095..T-149`, and `"Enemy Combat all tasks"` are display groupings, not valid
progress identities. Expand them to exact canonical IDs such as
`"completed_task_ids":["T-063","T-064"]`.

**AXIOM-1:** Every increment must be a working application. Smoke test (app starts + HTTP 200) is a hard gate — 100% passing unit tests alone is not enough.

**AXIOM-3:** Unverified requirements are unshipped. Full-spec BUILD_DONE is forbidden while any `coverage-map.md` entry has `coverage_type: manual|none` without explicit `deferred_risky_accepted` signed off by user. Harness `{"status":"done"}` still means the current invocation completed useful verified progress.

### Harness Build Quality Gate Sequencing

When running under `echelon delivery run`, follow build gate workflow transitions sequentially.
SPEC GUARD, CODE REVIEWER, and TEST GUARDIAN are hard gates, not a parallel
review batch. Run SPEC GUARD first; only after it passes, run CODE REVIEWER;
only after CODE REVIEWER approves, run TEST GUARDIAN.

NEVER dispatch SPEC GUARD, CODE REVIEWER, and TEST GUARDIAN in one parallel batch.
NEVER skip CODE REVIEWER or TEST GUARDIAN by vacuity. A gate may be skipped only
when a Ralph-provided phase contract declares an explicit workflow-approved skip
condition, and the skip rationale must be recorded in
`echelon_result.journal_entries`.

---

## Execution Continuity — MANDATORY

**Tool completions always require the next state-machine step; they are never
stopping points.** After any `Agent`, `Skill`, or
`Bash` tool returns — however complete or final its output looks — immediately
execute the next step in the build state machine without ending your response.
Stop only when: (a) the state machine reaches DONE, (b) a BLOCKED/ERROR condition
cannot be self-resolved, or (c) a human checkpoint is reached in `guided`/`semi`
mode.

Under `echelon delivery run`, a verified slice with a written
`$HARNESS_BUILD_STATUS_FILE` marker is also a valid stopping point. Do not keep
selecting more tasks after writing the marker; that creates large uncheckpointed
work and leaves Ralph waiting for a final marker that may never be reached.

When invoked by `echelon delivery run`, there is no external squad phase runner
consuming `echelon_result.state_updates.next_phase` from your final response.
Returning `next_phase: build-2-implement` after `build-1-init` is not progress;
it leaves Ralph without `.harness-build-status.json` and the build is marked
`build_incomplete`. Continue through the build phases in this same invocation.
If the Agent/subagent tool is unavailable, perform the required role inline and
continue to the next quality gate.

---

## User Input

$ARGUMENTS
