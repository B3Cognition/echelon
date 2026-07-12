# Phase: re-extract-3-verify
# Agent: speckit-echelon-re-verifier

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-execution-plan.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/sources/{source-id}/analysis.json`
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`

## Dispatch Prompt

Instruct RE-VERIFIER to enumerate files and compute coverage independently for every non-empty refresh source, reject shallow summaries at deep profiles, identify source-local orphan clusters, and use the minimum source score as aggregate `coverage_pct`.

## Expected Outputs

- `{state.output_dir}/quality/{source-id}/coverage-report.md` for each non-empty refresh source

Empty sources require no report. An all-empty workspace returns `coverage_pct: 100`.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-3-verify
  state_updates:
    coverage_pct: 72
    source_coverage: {api: 72}
    verify_expand_iterations: 2
  output_files:
    - "{state.output_dir}/quality/{source-id}/coverage-report.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-3-verify
      data:
        summary: "Computed independent source coverage"
  blocked_reason: null
```
