# Phase: re-planning-1-plan
# Agent: echelon-re-planner

## Context Pack

- `re/index.json`
- `re/sources/{source-id}/manifest.json`
- `re/sources/{source-id}/overview.md`
- `re/sources/{source-id}/specs/{domain-id}/spec.md`
- `re/workspace/relationships.md`
- `re/workspace/contracts.md`
- `re/workspace/strategy/constitution.md`
- `re/workspace/strategy/migration-strategy.md`
- `re/workspace/strategy/risk-matrix.md`
- `re/workspace/strategy/gap-analysis.md`
- `{state.output_dir}/state.json`

## Dispatch Prompt

Instruct RE-PLANNER to iterate canonical source domains in workspace dependency order and write each implementation plan beside its source-owned spec. Plans retain source identity, cross-source contracts, 6R/7R evidence, risks, phases, tests, milestones, and effort estimates.

## Expected Outputs

- `re/sources/{source-id}/specs/{domain-id}/plan.md`

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-1-plan
  state_updates: {}
  output_files:
    - re/sources/{source-id}/specs/{domain-id}/plan.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-1-plan
      data:
        summary: "Generated source-owned implementation plans"
  blocked_reason: null
```
