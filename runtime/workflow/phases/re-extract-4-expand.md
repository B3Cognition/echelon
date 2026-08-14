# Phase: re-extract-4-expand
# Agent: echelon.re-expander

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/quality/sources/{source-id}.json`
- `{state.output_dir}/sources/{source-id}/analysis.json`
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`

## Dispatch Prompt

Instruct RE-EXPANDER to expand only the source directory matching each failing coverage report. Preserve existing evidence and deep sections; create source-local domains for high-confidence orphan clusters. Do not edit workspace synthesis or deterministic JSON.

## Expected Outputs

- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md` for new or expanded source domains

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-4-expand
  state_updates:
    domains: [auth, api, data-layer, utils]
  output_files:
    - "{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-4-expand
      data:
        summary: "Expanded source-owned specs"
  blocked_reason: null
```
