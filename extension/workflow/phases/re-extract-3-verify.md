# Phase: re-extract-3-verify
# Agent: echelon-re-verifier

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-execution-plan.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/sources/{source-id}/analysis.json`
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`

## Dispatch Prompt

The harness enumerates files, validates citations, and writes the authoritative source-local quality reports. Instruct RE-VERIFIER only to explain an already written report when diagnostic prose is explicitly needed; it must not compute routing metrics.

## Expected Outputs

- `{state.output_dir}/quality/sources/{source-id}.json` is controller-owned output for each non-empty refresh source

Empty sources require no report. An all-empty workspace is controller-complete.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-3-verify
  state_updates: {}
  output_files:
    - "{state.output_dir}/quality/{source-id}/coverage-report.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-3-verify
      data:
        summary: "Explained controller-measured source coverage"
  blocked_reason: null
```
