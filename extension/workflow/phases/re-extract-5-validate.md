# Phase: re-extract-5-validate
# Agent: speckit-echelon-re-validator

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/workspace/contracts.md`
- `{state.output_dir}/workspace/relationships.md`
- `{state.output_dir}/sources/{source-id}/analysis.json`
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`
- `{state.output_dir}/quality/{source-id}/coverage-report.md`

## Dispatch Prompt

Instruct RE-VALIDATOR to validate each non-empty refresh source independently, resolve ambiguity only from matching source evidence, validate cross-source claims against workspace contracts, and use the minimum source score as aggregate `resolution_pct`.

## Expected Outputs

- `{state.output_dir}/quality/{source-id}/validation-report.md` for each non-empty refresh source

Empty sources require no report. An all-empty workspace returns `resolution_pct: 100`.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-5-validate
  state_updates:
    resolution_pct: 85
    source_resolution: {api: 85}
    validate_iterations: 1
  output_files:
    - "{state.output_dir}/quality/{source-id}/validation-report.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-5-validate
      data:
        summary: "Validated source-owned specs independently"
  blocked_reason: null
```
