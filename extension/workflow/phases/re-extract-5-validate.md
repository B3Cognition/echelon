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

Instruct RE-VALIDATOR to audit every refreshed source-domain independently against its owned code and tests. It must apply the ambiguity, underspecification, consistency, source-evidence, error/recovery, FR, NFR, and acceptance-scenario taxonomy. It must return one complete `semantic_quality_review` record per refreshed domain: `PASS` with no findings, or `REPAIR` with every finding backed by valid owned-domain `path:line` evidence. It must not edit any spec; the controller routes repair domains to RE-SPECIFIER.

## Expected Outputs

- An `echelon_result.semantic_quality_review` object covering every refreshed domain exactly once.

The controller validates and persists the audit under `{state.output_dir}/quality/semantic-quality-review.json`. Empty sources have no record; an all-empty workspace returns an empty domain list.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE
  phase_id: re-extract-5-validate
  semantic_quality_review:
    schema_version: 1
    domains:
      - source_id: api
        domain_id: 001-re-api
        verdict: PASS
        findings: []
        source_evidence: []
  state_updates: {}
  journal_entries:
    - type: phase_complete
      phase: re-extract-5-validate
      data:
        summary: "Completed source-evidenced semantic audits for every refreshed domain"
```
