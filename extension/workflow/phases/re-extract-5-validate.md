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

Instruct RE-VALIDATOR to audit only the source-domain requested by the controller against its owned code and tests. It must apply the ambiguity, underspecification, consistency, source-evidence, error/recovery, FR, NFR, and acceptance-scenario taxonomy. It must return exactly one complete `semantic_quality_review` record for that domain: `PASS` with no findings, or `REPAIR` with at least one valid owned-domain backticked `path:line` or `path:start-end` citation per finding. It must not edit any spec or audit sibling domains; the controller persists completed audits and routes repair domains to RE-SPECIFIER. Path-only prose, unverifiable locations, generated spec paths, quality reports, run artifacts, and evidence from another domain are invalid as `source_evidence`.

## Expected Outputs

- An `echelon_result.semantic_quality_review` object covering the requested domain exactly once.

The controller validates and persists the domain audit in run state, then assembles `{state.output_dir}/quality/semantic-quality-review.json` after every domain has a current audit.

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
        summary: "Completed the requested source-evidenced semantic domain audit"
```
