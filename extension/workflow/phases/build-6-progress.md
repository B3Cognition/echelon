# Phase: build-6-progress
# Source: echelon.build.md §6 — Progress Tracking (PROGRESS)
# Agents: speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)), then speckit-echelon-modeler (MODELER) (speckit-echelon-commander (COMMANDER)-dispatched)
# Read by: speckit-echelon-commander (COMMANDER) after each task's quality gates complete

## 6. Progress Tracking (PROGRESS)

### 6.1 Dispatch speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER))

Use the Ralph-owned context pack:

- Read `build_slice_context_index_file` and use
  `agent_context_files.PROGRESS_TRACKER` as the prepared PROGRESS TRACKER
  context pack.
- Use only explicit review-cycle and completed-task outputs already provided by
  Ralph.
- Do not compile a separate context pack by searching estimates, calibration,
  progress report, or task history files.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-progress-tracker`
- **prompt:**

  ```xml
  <context>
  [include agent_context_files.PROGRESS_TRACKER from build_slice_context_index_file]
  </context>

  <instructions>
  You are PROGRESS TRACKER. Read agents/build/progress-tracker.md for your complete protocol.
  Record completion of task {task_id}. Update running totals and check for drift.
  Append to `{spec_dir}/progress-report.md`. Update `{spec_dir}/process-metrics.md`, `knowledge-base/estimates-log.yaml`, and `knowledge-base/calibration-profile.yaml`. Return drift or budget alerts in `echelon_result.journal_entries`; speckit-echelon-commander (COMMANDER) owns build counter state updates in Section 6.3.
  </instructions>
  ```

- **description:** "speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)): {task_id} — effort tracking"

### 6.2 Handle Alerts

If speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) flags DRIFT WARNING or PHASE OVERRUN:

- Return the alert in `echelon_result.journal_entries`
- Print a warning to terminal
- Always continue building unless MANAGER decides to re-scope; do not stop on the alert alone.

### 6.3 Update Task Result (speckit-echelon-commander (COMMANDER) — mandatory after every task)

**This is a speckit-echelon-commander (COMMANDER) action, not a speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) action.** speckit-echelon-commander (COMMANDER) performs this update after speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) returns, or after quality gates complete if speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) was skipped or if work was executed inline.

1. Load the current `build` object from state.
2. **Increment `build.completed_tasks` by 1.**
3. Record the task result in the copied `build.task_results` map:

```yaml
build:
  task_results:
    "{task_id}":
      status: DONE
      review_cycles: 1
      degraded: false
      spec_guard: PASS
      code_review: APPROVED
      test_guardian: PASS
```

**Recompute percentage:**

1. Recompute `build.tasks_completed_pct`:
`tasks_completed_pct = Math.round((build.completed_tasks / build.total_tasks) * 100)`
2. Return the full updated `build` object and `updated_at` in `echelon_result.state_updates`; the harness applies them to `state.json`.

```yaml
echelon_result:
  state_updates:
    build:
      total_tasks: <existing total_tasks>
      completed_tasks: <previous completed_tasks + 1>
      tasks_completed_pct: <computed percent>
      current_task: null
      current_phase_group: <existing phase group or null>
      task_results:
        <all previous task_results plus this task>
      phase_checkpoints: <existing phase_checkpoints>
    updated_at: "{ISO-8601}"
```

**This step MUST execute regardless of execution mode** — whether tasks were dispatched via subagents or executed inline by speckit-echelon-commander (COMMANDER). The `completed_tasks` counter is the authoritative progress indicator for speckit-echelon-engineering-manager (ENGINEERING MANAGER) and any external tooling reading state.json.

**speckit-echelon-modeler (MODELER) Update (mandatory after every task):**
Dispatch speckit-echelon-modeler (MODELER) with:

- Input: the file(s) written or modified by speckit-echelon-implementer (IMPLEMENTER) in this task (from speckit-echelon-implementer (IMPLEMENTER)'s output)
- Existing `${STAGING_DIR}/mental-model-code.md`
- Task description and spec FR-* references for this task

speckit-echelon-modeler (MODELER) incrementally updates `mental-model-code.md` to reflect the new code.

**Invariant alert gate:** After speckit-echelon-modeler (MODELER) returns, speckit-echelon-commander (COMMANDER) checks speckit-echelon-modeler (MODELER)'s output for any `invariant_violations` list. If non-empty:

- Log each violation as a journal entry with `type: "alert"` and `severity: "HIGH"`
- Emit warning in build log: `[speckit-echelon-modeler (MODELER) ALERT] Invariant violation detected: {violation}. Tests pass but contract may be broken — review before next phase.`
- Always track violations for speckit-echelon-integrator (INTEGRATOR) to resolve at phase boundaries. Do NOT block task progression.

### 6.4 Update tasks.md (standalone build only)

When `HARNESS_BUILD_STATUS_FILE` is set, **do not execute this section**. In
harness delivery runs, Ralph owns canonical `tasks.md` progress writes after
the build invocation returns. Report completed task rows only by writing exact
`completed_task_ids` to `$HARNESS_BUILD_STATUS_FILE`; never call
`python -m harness mark-task-progress` and never edit `{spec_dir}/tasks.md`
directly from the build agent.

When `HARNESS_BUILD_STATUS_FILE` is not set, this is a
speckit-echelon-commander (COMMANDER) action. After §6.3 state update, reflect
task completion in `tasks.md` so the file remains a human-readable source of
truth (not just state.json).

1. Derive the task's final status from `build.task_results.{task_id}.status`:
   - `DONE` or `DONE_WITH_CONCERNS` → `DONE`
   - `DEGRADED` (fix_cycle limit hit) → `DEGRADED`
   - `BLOCKED` → `BLOCKED`

2. Update `tasks.md` with the deterministic harness command:

```bash
python -m harness mark-task-progress "{spec_dir}/tasks.md" "{task_id}" "{status}"
```

This command owns canonical row checkbox updates, `**Status:**` insertion/replacement,
and nested verified checkbox updates. Do not hand-edit task rows unless the command
fails and the failure message identifies malformed input that must be corrected.

3. Validate progress integrity:

```bash
python -m harness validate-task-progress "{spec_dir}/tasks.md" "{state_json_path}"
```

If validation fails, fix `tasks.md` and the returned `build` state update before continuing.

**Always execute this step in standalone build mode.** In harness mode, the same
integrity requirement is enforced by Ralph after it applies `completed_task_ids`.
