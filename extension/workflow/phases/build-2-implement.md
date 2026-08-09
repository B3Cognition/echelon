# Phase: build-2-implement
# Source: echelon.build.md §2 — Task Iteration (BUILD_LOOP)
# Agent: echelon-implementer (IMPLEMENTER)
# Read by: echelon-commander (COMMANDER) before each echelon-implementer (IMPLEMENTER) dispatch

## 2. Task Iteration (BUILD_LOOP)

For each task in the build order:

### 2.0 v0.4.0 BUILD Lane Policy

For `002-build-qa-phase-split`, BUILD execution uses dependency-safe wave lanes:

1. Group tasks by dependency level (same level = same wave).
2. Execute tasks in each wave before moving to the next wave.
3. Within a wave, process up to 3 echelon-implementer (IMPLEMENTER) lanes.
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

### 2.3 Dispatch echelon-implementer (IMPLEMENTER)

Use the Ralph-owned context pack:

- Read `build_implementer_context_file` first; it is the prepared IMPLEMENTER
  context pack for the current task slice.
- Use `build_slice_context_index_file` only to inspect the machine-readable
  section map and `agent_context_files` entries.
- Do not compile a separate context pack by searching spec, task, ADR,
  constitution, test-strategy, data-model, contract, or source files.

Use the Agent tool:

- **subagent_type:** `echelon-implementer`
- **prompt:**

  ```xml
  <context>
  [include the Ralph-owned context pack from build_implementer_context_file]
  </context>

  <instructions>
  You are IMPLEMENTER. Read agents/build/implementer.md for your complete protocol.
  Build task {task_id}: {task_description}
  Write code and tests. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon-implementer (IMPLEMENTER): {task_id} — {task_title}"

### 2.4 Handle echelon-implementer (IMPLEMENTER) Result

- **DONE / DONE_WITH_CONCERNS** — Proceed to echelon-spec-guard (SPEC GUARD)
- **NEEDS_CONTEXT** — MANAGER reads the question, compiles additional context, re-dispatches echelon-implementer (IMPLEMENTER). Max 2 re-dispatches per task.
- **BLOCKED** — Log the blocker. Skip to next task. If 3 tasks are BLOCKED, pause and assess (MANAGER may need to re-order tasks or escalate).

**Inline execution mode:** If echelon-commander (COMMANDER) executes task work directly in the main conversation (without dispatching echelon-implementer (IMPLEMENTER) as a subagent), echelon-commander (COMMANDER) MUST still execute Sections 3 through 6.3 in sequence: run quality gate checks, track progress, and update `state.json` via Section 6.3. Skipping subagent dispatch does NOT skip state tracking. The `build.completed_tasks` counter must be incremented after every task regardless of execution mode.

**Quality gate sequence:** Quality gates are sequential hard gates, not a parallel batch. After implementation work completes, run SPEC GUARD first, then CODE REVIEWER, then TEST GUARDIAN, using the gate order provided by Ralph and this phase contract. NEVER dispatch SPEC GUARD, CODE REVIEWER, and TEST GUARDIAN in one parallel batch. NEVER skip CODE REVIEWER or TEST GUARDIAN by vacuity. A gate may be skipped only when Ralph's build context or this phase spec declares an explicit workflow-approved skip condition, and the skip rationale must be recorded in `echelon_result.journal_entries`.

### 2.5 Build Handoff Package

After BUILD wave completion, generate a handoff package for QA containing:

1. `tasks` snapshots with required/optional scope labels.
2. `gate_results` from light-gate checks (`build_valid`, `tests_passed`, `lint_clean`, `required_outputs_present`).
3. `artifact_index` paths produced in BUILD.
4. `required_task_summary` counts by status.
5. `blocked_optional_out_of_scope` entries with explicit rationale.
6. `scope_version` and `generated_at` timestamp.

If package invariants fail, emit `BUILD_QA_HANDOFF_REJECTED` and stop transition to QA.
