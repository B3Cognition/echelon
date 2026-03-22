---
description: "Execute the building phase — implement tasks with role-based agents and quality gates"
scripts:
  sh: ../../scripts/bash/detect-project.sh
---

## User Input

$ARGUMENTS

---

## COMMANDER Loading — MANDATORY FIRST STEP

**Read the file `agents/control/commander.md` for your complete decision-making framework.** You are the COMMANDER. The file contains your Evidence Hierarchy, EVOI analysis, Toulmin conflict resolution, meta-cognition checklist, token budget borrow rules, and build phase orchestration rules. These govern ALL routing, iteration, and escalation decisions throughout the build.

Then execute the build state machine below.

---

## Overview

This command runs **Phase B: Building** of the Cognitive Agent Squad. You are the **COMMANDER** — the orchestrator of 6 build-phase cognitive functions that execute the implementation plan produced by Phase A (Understanding).

The user provides:

- **A feature path** — The `specs/{NNN}-{feature}/` directory containing Phase A artifacts
- **Optional: specific tasks** — Task IDs to build (e.g., `T-001 T-002`). If omitted, builds all tasks in order.
- **Optional: phase filter** — A phase name (e.g., "foundation") to build only that phase's tasks.

Your job is to iterate through tasks, dispatch build agents for each, enforce quality gates, and deliver working, tested code.

**You must not skip quality gates.** Each gate exists because bugs caught in review cost 10x less than bugs caught in production.

**RADAR Monitoring:** See squad.run.md "RADAR Emitter Pattern" section for how to emit agent state changes.

## v0.4.0 Operator Flow

1. Run BUILD tasks with dependency-safe wave lanes.
2. Enforce light-gate checks for BUILD completion eligibility.
3. Generate BUILD handoff package.
4. Run batch QA reviewers and deterministic verification.
5. If QA fails, execute bounded rework loop (max 3 iterations) then re-verify.

## Spec-Kit Integration

For task execution, leverage spec-kit's implementation workflow:

1. Call `/speckit.implement` which handles:
   - Checklist verification (blocks if incomplete unless user confirms)
   - Project setup (ignore files, directory structure)
   - Task ordering and progress tracking
2. Squad adds quality gates after each task:
   - SPEC GUARD verifies code matches spec
   - CODE REVIEWER checks quality and ADR compliance
   - TEST GUARDIAN validates test coverage
3. On task completion, spec-kit marks it done in tasks.md

This gives us: spec-kit's proven task execution + squad's multi-agent quality gates.

---

## 1. Initialization (BUILD_INIT)

### 1.1 Validate Phase A Artifacts

Read and verify these files exist in `specs/{NNN}-{feature}/`:

**Required:**

- `tasks.md` — The implementation plan (task list with IDs, descriptions, acceptance criteria, dependencies)
- `spec.md` — The specification (for FR-* requirement references)
- `constitution.md` — Non-negotiable coding rules
- `research.md` — ADRs and architectural decisions
- `test-strategy.md` — Test approach per component type
- `coverage-map.md` — Requirement-to-test mappings

**Optional (used if present):**

- `data-model.md` — Entity shapes and relationships
- `contracts/` — API and component interface definitions
- `estimates.md` — Effort estimates per task
- `calibration-profile.yaml` — Historical accuracy data

If `tasks.md` or `spec.md` is missing, STOP with error: "Phase A artifacts not found. Run `/speckit.squad.run` first."

### 1.2 Parse Tasks

Read `tasks.md` and parse all tasks into a structured list:

- Task ID (e.g., `T-001`)
- Phase/group (e.g., "Foundation", "Core Features")
- Description
- File paths (where code goes)
- Acceptance criteria
- Dependencies (task IDs that must complete first)
- Referenced requirements (FR-* IDs)
- Estimated effort (from `estimates.md` if available)

### 1.3 Determine Build Order

Order tasks by:

1. Phase/group order (Foundation before Core before Polish)
2. Within a phase: dependency order (dependencies before dependents)
3. Within same dependency level: critical path first (from `critical-path.md` if available)

If user specified task IDs, filter to only those tasks. Verify dependencies are met (either already built or included in the filter).

### 1.4 Initialize Build State

Update `.specify/squad/state.json`:

```json
{
  "status": "building",
  "phase": "build_init",
  "build": {
    "total_tasks": "{count}",
    "completed_tasks": 0,
    "current_task": null,
    "current_phase_group": null,
    "task_results": {},
    "phase_checkpoints": []
  },
  "updated_at": "{ISO-8601}"
}
```

### 1.4.1 Start RADAR (if enabled)

Read `radar.enabled` from squad-config.yml (default: true). If enabled:

```bash
# Extension path (where RADAR lives when installed)
RADAR_EXT=".specify/extensions/cognitive-squad"

# Install RADAR dependencies if needed
pip install -q -r ${RADAR_EXT}/radar/requirements.txt 2>/dev/null || true

# Read port from config (default 7891)
RADAR_PORT=$(grep -A2 "^radar:" squad-config.yml 2>/dev/null | grep "port:" | awk '{print $2}' || echo 7891)

# Start RADAR in background
PYTHONPATH=${RADAR_EXT} python3 -m radar.server --port ${RADAR_PORT:-7891} \
  >> .specify/squad/radar.log 2>&1 &
echo $! > .specify/squad/radar.pid

# Initialize emitter (creates/truncates agent-states files)
PYTHONPATH=${RADAR_EXT} python3 -c "from radar.emitter import init_run; init_run('${run_id}')"
```

**Note:** If RADAR fails to start, log a warning but continue the build. The squad executes without live monitoring.

### 1.5 Initialize Build Reports

Create empty report files (or clear prior content):

- `specs/{feature}/spec-compliance-report.md`
- `specs/{feature}/code-review-report.md`
- `specs/{feature}/test-quality-report.md`
- `specs/{feature}/progress-report.md`

**Transition:** Proceed to task iteration.

---

## 2. Task Iteration (BUILD_LOOP)

For each task in the build order:

### 2.0 v0.4.0 BUILD Lane Policy

For `002-build-qa-phase-split`, BUILD execution uses dependency-safe wave lanes:

1. Group tasks by dependency level (same level = same wave).
2. Execute tasks in each wave before moving to the next wave.
3. Within a wave, process up to 3 IMPLEMENTER lanes.
4. A failed task in a wave must not block unrelated tasks in that same wave.
5. A failed task must block only dependents in later waves.

### 2.1 Check Dependencies

Verify all dependency tasks have status DONE or DONE_WITH_CONCERNS. If a dependency is BLOCKED, skip this task and mark it as BLOCKED (dependency).

Before allowing QA entry, enforce blocked semantics:

1. Required tasks with `BLOCKED` status are forbidden.
2. Optional tasks may remain blocked only when marked `OUT_OF_SCOPE` with rationale.
3. If either rule is violated, keep phase in `BUILD_IN_PROGRESS` and emit handoff rejection reasons.

### 2.2 Update State

```json
{
  "build": {
    "current_task": "{task_id}",
    "current_phase_group": "{phase_group}"
  }
}
```

### 2.3 Dispatch IMPLEMENTER

Compile context pack:

- The specific task (from parsed task list)
- Referenced FR-* requirements (from `spec.md`)
- `constitution.md`
- Relevant ADRs from `research.md`
- Existing code from completed tasks (for integration context)
- Relevant section of `test-strategy.md`
- `data-model.md` (if present)
- Relevant `contracts/` files (if present)

Use the Agent tool:

- **prompt:** Read the file `agents/build/implementer.md` for your complete instructions. You are the IMPLEMENTER. Build task {task_id}: {task_description}. Here is your context pack: [include files]. Write code and tests. Append entries to `reasoning-journal.json`.
- **description:** "IMPLEMENTER: {task_id} — {task_title}"

### 2.4 Handle IMPLEMENTER Result

- **DONE / DONE_WITH_CONCERNS** — Proceed to SPEC GUARD
- **NEEDS_CONTEXT** — MANAGER reads the question, compiles additional context, re-dispatches IMPLEMENTER. Max 2 re-dispatches per task.
- **BLOCKED** — Log the blocker. Skip to next task. If 3 tasks are BLOCKED, pause and assess (MANAGER may need to re-order tasks or escalate).

### 2.5 Build Handoff Package

After BUILD wave completion, generate a handoff package for QA containing:

1. `tasks` snapshots with required/optional scope labels.
2. `gate_results` from light-gate checks (`build_valid`, `tests_passed`, `lint_clean`, `required_outputs_present`).
3. `artifact_index` paths produced in BUILD.
4. `required_task_summary` counts by status.
5. `blocked_optional_out_of_scope` entries with explicit rationale.
6. `scope_version` and `generated_at` timestamp.

If package invariants fail, emit `BUILD_QA_HANDOFF_REJECTED` and stop transition to QA.

---

## 3. Spec Guard Gate (SPEC_GUARD)

### 3.1 Dispatch SPEC GUARD

Compile context pack:

- Files changed by IMPLEMENTER
- The task definition (acceptance criteria, FR-* references)
- Referenced FR-* requirements from `spec.md`
- Full `spec.md` for cross-reference

Use the Agent tool:

- **prompt:** Read the file `agents/build/spec-guard.md` for your complete instructions. You are the SPEC GUARD. Verify task {task_id} implementation against spec requirements. Here is your context pack: [include files]. Append to `spec-compliance-report.md`. Append entries to `reasoning-journal.json`.
- **description:** "SPEC GUARD: {task_id} — spec compliance check"

### 3.2 Handle Result

- **PASS** — Proceed to CODE REVIEWER
- **FAIL** — Route back to IMPLEMENTER with the specific gaps. IMPLEMENTER fixes and re-submits. Max 2 fix cycles per gate. If still failing after 2 cycles, flag as DEGRADED and proceed.
- **WARN** — Proceed to CODE REVIEWER. Warnings are logged but do not block.

### On Non-Obvious FAIL

If SPEC GUARD or CODE REVIEWER returns FAIL and the issue is non-obvious (logic error, integration issue, not just missing test or style):

1. Dispatch DEBUGGER instead of sending directly back to IMPLEMENTER
2. DEBUGGER: reproduce → isolate → root cause → fix → verify
3. If root cause is within task scope → DEBUGGER fixes
4. If root cause requires architecture change → MANAGER routes to HOW
5. If root cause requires spec change → MANAGER routes to WHAT

---

## 4. Code Review Gate (CODE_REVIEW)

### 4.1 Dispatch CODE REVIEWER

Compile context pack:

- Files changed by IMPLEMENTER
- `constitution.md`
- Relevant ADRs from `research.md`
- Existing codebase patterns (files from prior tasks)

Use the Agent tool:

- **prompt:** Read the file `agents/build/code-reviewer.md` for your complete instructions. You are the CODE REVIEWER. Review task {task_id} implementation. Here is your context pack: [include files]. Append to `code-review-report.md`. Append entries to `reasoning-journal.json`.
- **description:** "CODE REVIEWER: {task_id} — quality review"

### 4.2 Handle Result

- **APPROVED** — Proceed to TEST GUARDIAN
- **CHANGES_REQUESTED** — Route back to IMPLEMENTER with the specific issues. IMPLEMENTER fixes and re-submits for review. Max 2 fix cycles. If still failing, flag as DEGRADED and proceed.
- **BLOCKED** — Fundamental architectural issue. MANAGER decides: skip task, amend ADR, or escalate to human.

---

## 5. Test Guardian Gate (TEST_GUARD)

### 5.1 Dispatch TEST GUARDIAN

Compile context pack:

- Test files from IMPLEMENTER
- Source files from IMPLEMENTER
- Task acceptance criteria
- Relevant section of `test-strategy.md`
- `coverage-map.md`

Use the Agent tool:

- **prompt:** Read the file `agents/build/test-guardian.md` for your complete instructions. You are the TEST GUARDIAN. Validate test quality for task {task_id}. Here is your context pack: [include files]. Append to `test-quality-report.md`. Update `coverage-map.md`. Append entries to `reasoning-journal.json`.
- **description:** "TEST GUARDIAN: {task_id} — test quality validation"

### 5.2 Handle Result

- **PASS** — Task complete. Proceed to PROGRESS TRACKER.
- **FAIL** — Route back to IMPLEMENTER to add missing tests. Max 2 fix cycles. If still failing, flag as DEGRADED and proceed.
- **WARN** — Task complete with noted improvements. Proceed to PROGRESS TRACKER.

---

## 6. Progress Tracking (PROGRESS)

### 6.1 Dispatch PROGRESS TRACKER

Compile context pack:

- Completed task ID and estimated effort
- Count of review cycles (how many times IMPLEMENTER was re-dispatched)
- `estimates.md`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- Current progress report

Use the Agent tool:

- **prompt:** Read the file `agents/build/progress-tracker.md` for your complete instructions. You are the PROGRESS TRACKER. Record completion of task {task_id}. Update running totals and check for drift. Here is your context pack: [include files]. Append to `progress-report.md`. Update `knowledge-base/estimates-log.yaml` and `knowledge-base/calibration-profile.yaml`.
- **description:** "PROGRESS TRACKER: {task_id} — effort tracking"

### 6.2 Handle Alerts

If PROGRESS TRACKER flags DRIFT WARNING or PHASE OVERRUN:

- Log the alert in `state.json`
- Print a warning to terminal
- Continue building (do not stop unless MANAGER decides to re-scope)

### 6.3 Update Task Result

Record in `state.json.build.task_results`:

```json
{
  "{task_id}": {
    "status": "DONE",
    "review_cycles": 1,
    "degraded": false,
    "spec_guard": "PASS",
    "code_review": "APPROVED",
    "test_guardian": "PASS"
  }
}
```

---

## 7. Phase Checkpoint (INTEGRATION)

### When

After all tasks in a phase group (e.g., "Foundation") are complete, run the INTEGRATOR before proceeding to the next phase group.

### 7.1 Dispatch INTEGRATOR

Compile context pack:

- All code produced in this phase group
- Build configuration files
- `contracts/`
- `data-model.md`
- Prior integration reports (if any)

Use the Agent tool:

- **prompt:** Read the file `agents/build/integrator.md` for your complete instructions. You are the INTEGRATOR. Verify system integration after phase "{phase_group}". Here is your context pack: [include files]. Write `integration-report.md`. Append entries to `reasoning-journal.json`.
- **description:** "INTEGRATOR: phase '{phase_group}' — system integration check"

### 7.2 Handle Result

- **PASS** — Record checkpoint. Proceed to next phase group.
- **FAIL** — Route integration failures back to the responsible task's IMPLEMENTER. Re-run INTEGRATOR after fixes. Max 2 fix cycles per phase checkpoint. If still failing, flag phase as DEGRADED and proceed.

### 7.3 Record Checkpoint

Append to `state.json.build.phase_checkpoints`:

```json
{
  "phase_group": "{name}",
  "status": "PASS",
  "tasks_completed": "{count}",
  "integration_issues": 0,
  "timestamp": "{ISO-8601}"
}
```

---

## 8. Build Complete (BUILD_DONE)

After all tasks are built and all phase checkpoints pass:

### 8.1 Final Integration

Run INTEGRATOR one last time against the complete codebase (all phases combined).

### 8.1b Engineering Manager Sign-Off

Before completion, dispatch ENGINEERING MANAGER with:

- `tasks.md`
- `spec.md`
- `traceability-matrix.md`
- `coverage-map.md`
- `process-metrics.md`
- `integration-report.md`
- `progress-report.md`
- all build gate reports
- `state.json`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read `agents/build/engineering-manager.md` for your complete instructions. You are the ENGINEERING MANAGER. Validate workflow compliance, report consistency, and readiness for final verification using the provided context pack.
- **description:** "ENGINEERING MANAGER: final pre-verification sign-off"

ENGINEERING MANAGER must confirm:

1. Spec-kit task workflow was actually followed.
2. Task status, state tracking, and reports are internally consistent.
3. The build is ready for full VERIFICATION.

If any of these fail, do not proceed to BUILD_DONE. Route to rework first.

### 8.1c Final Verification

Dispatch VERIFICATION after final integration and EM pre-check.

Use the Agent tool:

- **prompt:** Read `agents/build/verification.md` for your complete instructions. You are the VERIFICATION agent. Run full backpropagation verification against spec requirements using the provided context pack. Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.
- **description:** "VERIFICATION: final backpropagation check"

VERIFICATION must:

1. Check every FR-*, AC-*, and NFR-* in `spec.md`.
2. Verify code, tests, integration evidence, and gate evidence.
3. Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.

Handle result:

- **PASS** — continue to BUILD_DONE
- **FAIL** — create RW-* tasks, route through IMPLEMENTER and quality gates, then re-run VERIFICATION

BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md` contains open gaps.

### 8.2 Collect Reports

Verify all report files are populated:

- `spec-compliance-report.md` — One section per task
- `code-review-report.md` — One section per task
- `test-quality-report.md` — One section per task
- `integration-report.md` — One section per phase checkpoint + final
- `progress-report.md` — One section per task + summary
- `gap-report.md` — Verification coverage and gaps
- `verification-summary.md` — Final PASS / FAIL completion verdict

### 8.3 Update State

```json
{
  "status": "build_done",
  "phase": "build_done",
  "build": {
    "completed_tasks": "{total}",
    "verification_verdict": "PASS",
    "coverage_score": "100%",
    "current_task": null
  },
  "updated_at": "{ISO-8601}"
}
```

### 8.3.1 Stop RADAR

```bash
if [ -f .specify/squad/radar.pid ]; then
  kill $(cat .specify/squad/radar.pid) 2>/dev/null || true
  rm -f .specify/squad/radar.pid
fi
```

### 8.4 Run SCOREKEEPER

After all build tasks complete, dispatch SCOREKEEPER to produce the build phase scorecard:

Use the Agent tool:

- **prompt:** Read `agents/control/scorekeeper.md`. Score all build agents: IMPLEMENTER (first-pass approvals vs rework), SPEC GUARD (gaps caught vs missed by VERIFICATION), CODE REVIEWER (issues found), TEST GUARDIAN (coverage improvements). Collect peer appreciation from reasoning-journal.json. Check badge criteria. Produce `agent-scorecard.md`. Update `knowledge-base/agent-scores.yaml`.
- **description:** "SCOREKEEPER: build phase scoring and badges"

Build-specific scoring:

```
Per task completed:
  IMPLEMENTER first-pass approval: +3
  IMPLEMENTER rework required: -1
  IMPLEMENTER third rework: -3
  SPEC GUARD caught gap: +3
  CODE REVIEWER found issue: +2
  TEST GUARDIAN improved coverage: +2

Per phase gate:
  INTEGRATOR pass: +2
  VISUAL VALIDATOR caught visual issue: +4

End of build:
  VERIFICATION 100% coverage: SPEC GUARD gets +5 (Guardian Angel badge candidate)
  VERIFICATION found gaps: SPEC GUARD gets -2 per gap (Blind Spot badge candidate)
```

### 8.5 Print Summary

```
============================================
  COGNITIVE SQUAD BUILD COMPLETE
============================================

Feature:    {NNN}-{feature}
Tasks:      {completed}/{total} ({degraded} degraded, {blocked} blocked)

QUALITY GATES:
  Spec Guard:     {passed}/{total} PASS
  Code Review:    {approved}/{total} APPROVED
  Test Guardian:  {passed}/{total} PASS
  Integration:    {checkpoints_passed}/{total_checkpoints} PASS
  Verification:   PASS ({coverage_score} coverage, {gap_count} gaps)

EFFORT:
  Estimated total: {sum}
  Actual total:    {sum}
  Burn rate:       {ratio}x
  Drift status:    {ON_TRACK | DRIFT_WARNING | OVERRUN}

REPORTS:
  spec-compliance-report.md
  code-review-report.md
  test-quality-report.md
  integration-report.md
  progress-report.md
  gap-report.md
  verification-summary.md

AGENT SCORECARD:
  Top performer: {agent} (+{score}) — {highlight}
  Badges earned: {list}
  Self-healing: {recommendations}

WARNINGS:
  {any DEGRADED tasks}
  {any BLOCKED tasks}
  {any drift alerts}

============================================
```

---

## 9. Error Handling

### Task-Level Failures

| Situation | Action |
|-----------|--------|
| IMPLEMENTER timeout (> 5 min) | Retry once. If still timeout, skip task as BLOCKED. |
| Review agent timeout | Retry once. If still timeout, skip gate (flag as UNVALIDATED). |
| IMPLEMENTER produces no files | Flag as BLOCKED. Move to next task. |
| 3+ tasks BLOCKED | Pause. MANAGER assesses whether build can continue or needs re-planning. |

### Phase-Level Failures

| Situation | Action |
|-----------|--------|
| INTEGRATOR finds > 5 failures | Pause phase. Assess whether tasks need re-ordering or re-specification. |
| Build command fails completely | Check if `package.json` has the expected scripts. Flag as BLOCKED if not. |
| All tasks in a phase BLOCKED | Skip phase. Flag as PHASE_SKIPPED. Continue to next phase (may also fail). |

### Degraded Mode

Tasks or gates flagged as DEGRADED must have this banner in their report section:

```markdown
> **DEGRADED** — This task passed with known issues after maximum fix cycles ({N} cycles). The following gates were not fully satisfied: {list}. Review before deployment.
```

---

## 10. Convergence Rules

- **Max fix cycles per gate:** 2 (IMPLEMENTER gets 2 chances to fix issues per quality gate)
- **Max total IMPLEMENTER dispatches per task:** 7 (1 initial + 2 per gate for 3 gates)
- **Max BLOCKED tasks before pause:** 3
- **Max DEGRADED tasks before warning:** 30% of total tasks
- **Token budget for build phase:** Configurable in `squad-config.yml`. Default: 2M tokens.
- **Wall-clock time limit:** 60 minutes. Force complete with whatever is done.

---

## 11. Quick Reference: Build Flow

```
BUILD_INIT
  │ validate Phase A artifacts, parse tasks, order by dependencies
  │
  ▼
FOR EACH task (ordered by phase, then dependencies):
  │
  IMPLEMENTER → writes code + tests
    │
    ├─ DONE → continue
    ├─ NEEDS_CONTEXT → MANAGER provides, re-dispatch (max 2)
    └─ BLOCKED → skip task, log
    │
  SPEC GUARD → verifies code vs FR-* requirements
    │
    ├─ PASS → continue
    └─ FAIL → IMPLEMENTER fixes (max 2 cycles)
    │
  CODE REVIEWER → checks quality + ADR + constitution
    │
    ├─ APPROVED → continue
    └─ CHANGES_REQUESTED → IMPLEMENTER fixes (max 2 cycles)
    │
  TEST GUARDIAN → validates test quality + coverage
    │
    ├─ PASS → continue
    └─ FAIL → IMPLEMENTER adds tests (max 2 cycles)
    │
  PROGRESS TRACKER → records effort, checks drift
  │
END FOR
  │
INTEGRATOR → runs after each phase checkpoint
  │
  ├─ PASS → next phase
  └─ FAIL → IMPLEMENTER fixes integration issues
  │
FINAL INTEGRATION → whole-system integration pass
  │
ENGINEERING MANAGER → workflow compliance + readiness sign-off
  │
VERIFICATION → full backpropagation check against spec
  │
  ├─ PASS → BUILD_DONE
  └─ FAIL → RW-* tasks + rework loop

Before BUILD_DONE can succeed:
  ENGINEERING MANAGER → verifies workflow compliance and readiness
  VERIFICATION → proves 100% implemented coverage with zero open gaps
```
