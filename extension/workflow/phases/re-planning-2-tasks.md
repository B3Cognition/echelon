# Phase: re-planning-2-tasks
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-TASKER
# Agent: speckit-echelon-re-tasker

## Context Pack

- `specs/NNN-re-{domain}/plan.md`
- `specs/NNN-re-{domain}/spec.md`
- `constitution.md`
- `extension/templates/tasks-template.md`
- `extension/templates/task-entry-fragment.md`
- `extension/templates/task-checkpoint-fragment.md`

## Dispatch Prompt

Instruct RE-TASKER to: iterate over all domains, for each read plan.md + spec.md + constitution, generate `specs/NNN-re-{domain}/tasks.md` from `extension/templates/tasks-template.md`. Every executable task must start with a canonical `T-###` row containing `complexity=`, `phase=`, `req=`, and `depends=` metadata. After all domains complete, optionally offer `speckit.analyze` for consistency analysis.

## Expected Outputs

- `specs/NNN-re-{domain}/tasks.md` — one per domain

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-2-tasks
  state_updates:
    status: done
  output_files:
    - specs/NNN-re-{domain}/tasks.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-2-tasks
      data:
        summary: "Generated tasks for {N} domains"
  blocked_reason: null
```
