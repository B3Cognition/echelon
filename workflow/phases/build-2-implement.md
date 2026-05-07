# Phase: build-2-implement
# Source: echelon.build.md §2 — Task Iteration (BUILD_LOOP)
# Agent: IMPLEMENTER
# Read by: COMMANDER before each IMPLEMENTER dispatch

## 2. Task Iteration (BUILD_LOOP)

For each task in the build order:

### 2.0 v0.4.0 BUILD Lane Policy

For `002-build-qa-phase-split`, BUILD execution uses dependency-safe wave lanes:

1. Group tasks by dependency level (same level = same wave).
2. Execute tasks in each wave before moving to the next wave.
3. Within a wave, process up to 3 speckit-echelon-implementer (IMPLEMENTER) lanes.
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

### 2.3 Dispatch speckit-echelon-implementer (IMPLEMENTER)

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

- **subagent_type:** `speckit-echelon-implementer`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are IMPLEMENTER. Read agents/build/implementer.md for your complete protocol.
  Build task {task_id}: {task_description}
  Write code and tests. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-implementer (IMPLEMENTER): {task_id} — {task_title}"

### 2.4 Handle speckit-echelon-implementer (IMPLEMENTER) Result

- **DONE / DONE_WITH_CONCERNS** — Proceed to speckit-echelon-spec-guard (SPEC GUARD)
- **NEEDS_CONTEXT** — MANAGER reads the question, compiles additional context, re-dispatches speckit-echelon-implementer (IMPLEMENTER). Max 2 re-dispatches per task.
- **BLOCKED** — Log the blocker. Skip to next task. If 3 tasks are BLOCKED, pause and assess (MANAGER may need to re-order tasks or escalate).

**Inline execution mode:** If speckit-echelon-commander (COMMANDER) executes task work directly in the main conversation (without dispatching speckit-echelon-implementer (IMPLEMENTER) as a subagent), speckit-echelon-commander (COMMANDER) MUST still execute Sections 3 through 6.3 in sequence: run quality gate checks, track progress, and update `state.json` via Section 6.3. Skipping subagent dispatch does NOT skip state tracking. The `build.completed_tasks` counter must be incremented after every task regardless of execution mode.

### 2.5 Build Handoff Package

After BUILD wave completion, generate a handoff package for QA containing:

1. `tasks` snapshots with required/optional scope labels.
2. `gate_results` from light-gate checks (`build_valid`, `tests_passed`, `lint_clean`, `required_outputs_present`).
3. `artifact_index` paths produced in BUILD.
4. `required_task_summary` counts by status.
5. `blocked_optional_out_of_scope` entries with explicit rationale.
6. `scope_version` and `generated_at` timestamp.

If package invariants fail, emit `BUILD_QA_HANDOFF_REJECTED` and stop transition to QA.
