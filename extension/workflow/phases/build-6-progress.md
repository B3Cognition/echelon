# Phase: build-6-progress
# Source: echelon.build.md §6 — Progress Tracking (PROGRESS)
# Agents: speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)), then speckit-echelon-modeler (MODELER) (speckit-echelon-commander (COMMANDER)-dispatched)
# Read by: speckit-echelon-commander (COMMANDER) after each task's quality gates complete

## 6. Progress Tracking (PROGRESS)

### 6.1 Dispatch speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER))

Compile context pack:

- Completed task ID and estimated effort
- Count of review cycles (how many times speckit-echelon-implementer (IMPLEMENTER) was re-dispatched)
- `estimates.md`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- Current progress report

Use the Agent tool:

- **subagent_type:** `speckit-echelon-progress-tracker`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are PROGRESS TRACKER. Read agents/build/progress-tracker.md for your complete protocol.
  Record completion of task {task_id}. Update running totals and check for drift.
  Append to `progress-report.md`. Update `knowledge-base/estimates-log.yaml` and `knowledge-base/calibration-profile.yaml`. Also update `state.json.build.completed_tasks` (increment by 1) and `state.json.build.task_results` with the task's gate results.
  </instructions>
  ```

- **description:** "speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)): {task_id} — effort tracking"

### 6.2 Handle Alerts

If speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) flags DRIFT WARNING or PHASE OVERRUN:

- Log the alert in `state.json`
- Print a warning to terminal
- Continue building (do not stop unless MANAGER decides to re-scope)

### 6.3 Update Task Result (speckit-echelon-commander (COMMANDER) — mandatory after every task)

**This is a speckit-echelon-commander (COMMANDER) action, not a speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) action.** speckit-echelon-commander (COMMANDER) performs this update after speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) returns, or after quality gates complete if speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) was skipped or if work was executed inline.

1. **Increment `build.completed_tasks` by 1.**
2. Record the task result in `state.json.build.task_results`:

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

**Recompute percentage:**

1. Recompute `state.json.build.tasks_completed_pct`:
`tasks_completed_pct = Math.round((build.completed_tasks / build.total_tasks) * 100)`
Write the new value to `state.json.build.tasks_completed_pct`.
2. Update `state.json.updated_at` to current timestamp.

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
- Do NOT block task progression — violations are tracked for speckit-echelon-integrator (INTEGRATOR) to resolve at phase boundaries.
