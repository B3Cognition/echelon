# Phase: re-extract-6-checklist
# Agent: echelon.re-checklister

## Context Pack

- `{state.output_dir}/re-workspace-inputs.json`
- `{state.output_dir}/workspace/overview.md`
- `{state.output_dir}/workspace/relationships.md`
- `{state.output_dir}/workspace/contracts.md`
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md`
- `{state.output_dir}/quality/{source-id}/coverage-report.md`
- `{state.output_dir}/quality/semantic-quality-review.json`

## Dispatch Prompt

Instruct RE-CHECKLISTER to write each domain checklist beside its source spec and one workspace checklist for cross-source contracts, relationships, compatibility, removals, and migration ordering. An all-empty workspace gets only the workspace checklist.

## Expected Outputs

- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/checklist.md`
- `{state.output_dir}/workspace/checklist.md`

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-6-checklist
  state_updates: {}
  output_files:
    - "{state.output_dir}/sources/{source-id}/specs/{domain-id}/checklist.md"
    - "{state.output_dir}/workspace/checklist.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-6-checklist
      data:
        summary: "Generated source-domain and workspace checklists"
  blocked_reason: null
```
