# Phase: re-planning-2-tasks
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-TASKER
# Agent: speckit-echelon-re-tasker

## Context Pack

- `specs/NNN-re-{domain}/plan.md`
- `specs/NNN-re-{domain}/spec.md`
- `constitution.md`

## Dispatch Prompt

Instruct RE-TASKER to: iterate over all domains, for each read plan.md + spec.md + constitution, generate `specs/NNN-re-{domain}/tasks.md` with actionable task items (IDs, descriptions, acceptance criteria, dependencies). After all domains complete, optionally offer `speckit.analyze` for consistency analysis.

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
    - specs/001-re-auth/tasks.md
    - specs/002-re-api/tasks.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-2-tasks
      summary: "Generated tasks for {N} domains"
  blocked_reason: null
```
