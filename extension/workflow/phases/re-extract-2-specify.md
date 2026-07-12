# Phase: re-extract-2-specify
# Agent: speckit-echelon-re-specifier

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-execution-plan.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/re-workspace-inputs.json`
- `{state.output_dir}/analysis.json`
- `{state.output_dir}/cross-repo.json` when produced
- `{state.output_dir}/sources/{source-id}/analysis.json` and related staged extraction artifacts for every refresh source
- canonical source manifests/specs referenced by `re-workspace-inputs.json`

## Dispatch Prompt

Instruct RE-SPECIFIER to produce deep source-owned specs for each non-empty refresh source, then synthesize the complete workspace union. Number domains locally per source. Source specs may cite only their own source root. Cross-source APIs, events, schemas, dependencies, and migration ordering belong in workspace synthesis. Treat all planner/publication JSON as read-only.

## Expected Outputs

- `{state.output_dir}/sources/{source-id}/overview.md` for each non-empty refresh source
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md` for each discovered source domain
- `{state.output_dir}/workspace/overview.md`
- `{state.output_dir}/workspace/relationships.md`
- `{state.output_dir}/workspace/contracts.md`
- `{state.output_dir}/workspace/domains/{domain-id}.md` when workspace domains exist

An all-empty declared workspace requires the three workspace documents and empty decisions, but no source domain spec.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-2-specify
  state_updates:
    domains: [auth, api, data-layer]
  output_files:
    - "{state.output_dir}/sources/{source-id}/overview.md"
    - "{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md"
    - "{state.output_dir}/workspace/overview.md"
    - "{state.output_dir}/workspace/relationships.md"
    - "{state.output_dir}/workspace/contracts.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      data:
        summary: "Generated source-owned specs and workspace synthesis"
  blocked_reason: null
```
