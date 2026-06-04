# Phase: re-extract-4-expand
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-EXPANDER
# Agent: speckit-echelon-re-expander

## Context Pack

- `specs/000-re-overview/coverage-report.md` — orphan file clusters
- `{state.output_dir}/analysis.json` — file metadata for orphan files
- `{state.output_dir}/state.json` — domain list, output_dir

## Dispatch Prompt

Instruct RE-EXPANDER to: read orphan clusters from coverage-report.md, create or expand domain specs to cover high-confidence clusters (≥3 related files), preserve existing spec content, write new/updated spec.md files.

## Expected Outputs

- `specs/NNN-re-{domain}/spec.md` — new or expanded domains

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-4-expand
  state_updates:
    domains: [auth, api, data-layer, utils]
  output_files:
    - specs/NNN-re-{domain}/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-4-expand
      summary: "Added {N} new domain(s), expanded {M} existing"
  blocked_reason: null
```
