# Phase: re-extract-7-constitute
# Agent: echelon-re-constituter

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-workspace-inputs.json`
- canonical source manifests/specs referenced by the workspace inputs
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`
- `{state.output_dir}/quality/{source-id}/coverage-report.md`
- `{state.output_dir}/quality/semantic-quality-review.json`
- `{state.output_dir}/workspace/overview.md`
- `{state.output_dir}/workspace/relationships.md`
- `{state.output_dir}/workspace/contracts.md`
- `{state.output_dir}/workspace/checklist.md`

## Dispatch Prompt

Instruct RE-CONSTITUTER to synthesize evidence-backed strategy from the complete workspace union, including current, refreshed, empty, unavailable retained, and removed sources. Mark undecidable target-state choices `[REQUIRES INPUT]`. Write only under workspace strategy staging.

If a strategy output already exists from a previous blocked or interrupted
attempt, RE-CONSTITUTER must read it before updating it. This phase is
rerunnable: never create backup, temporary, alternate, or non-canonical
strategy files to bypass write guards.

## Expected Outputs

- `{state.output_dir}/workspace/strategy/constitution.md`
- `{state.output_dir}/workspace/strategy/migration-strategy.md`
- `{state.output_dir}/workspace/strategy/risk-matrix.md`
- `{state.output_dir}/workspace/strategy/gap-analysis.md`
- `{state.output_dir}/workspace/strategy/adrs/ADR-NNN-*.md`

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-7-constitute
  state_updates: {}
  output_files:
    - "{state.output_dir}/workspace/strategy/constitution.md"
    - "{state.output_dir}/workspace/strategy/migration-strategy.md"
    - "{state.output_dir}/workspace/strategy/risk-matrix.md"
    - "{state.output_dir}/workspace/strategy/gap-analysis.md"
    - "{state.output_dir}/workspace/strategy/adrs/ADR-NNN-*.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-7-constitute
      data:
        summary: "Generated workspace strategy"
  blocked_reason: null
```

The RE controller owns the final `status: done` transition after this phase
passes. RE-CONSTITUTER must not return `status`, `phase`, counters, or other
controller-owned lifecycle fields in `state_updates`.
