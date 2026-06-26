# Phase: re-planning-1-plan
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-PLANNER
# Agent: speckit-echelon-re-planner

## Context Pack

- `specs/NNN-re-{domain}/spec.md` — domain spec (one per iteration)
- `constitution.md` — non-negotiable coding rules and target decisions
- `migration-strategy.md` — 6R/7R per domain
- `{state.output_dir}/state.json` — domain list

## Dispatch Prompt

Instruct RE-PLANNER to: iterate over all domains in `state.json.domains`, for each read the domain spec + constitution + migration strategy, generate `specs/NNN-re-{domain}/plan.md` with implementation phases, milestones, dependencies, and effort estimates.

## Expected Outputs

- `specs/NNN-re-{domain}/plan.md` — one per domain

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-1-plan
  state_updates: {}
  output_files:
    - specs/NNN-re-{domain}/plan.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-1-plan
      data:
        summary: "Generated plans for {N} domains"
  blocked_reason: null
```
