# Phase: re-planning-2-tasks
# Agent: echelon.re-tasker

## Context Pack

- `re/sources/{source-id}/specs/{domain-id}/spec.md`
- `re/sources/{source-id}/specs/{domain-id}/plan.md`
- `re/workspace/contracts.md`
- `re/workspace/relationships.md`
- `re/workspace/strategy/constitution.md`
- `extension/templates/tasks-template.md`
- `extension/templates/task-entry-fragment.md`
- `extension/templates/task-checkpoint-fragment.md`

## Dispatch Prompt

Instruct RE-TASKER to iterate canonical source domains, read each adjacent spec and plan plus workspace strategy, and write tasks beside them. Every executable task uses a canonical `T-###` row with `complexity=`, `phase=`, `req=`, and `depends=` metadata and retains cross-source dependency traceability.

## Expected Outputs

- `re/sources/{source-id}/specs/{domain-id}/tasks.md`

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-2-tasks
  state_updates:
    status: done
  output_files:
    - re/sources/{source-id}/specs/{domain-id}/tasks.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-2-tasks
      data:
        summary: "Generated source-owned implementation tasks"
  blocked_reason: null
```
