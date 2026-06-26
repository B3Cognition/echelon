# Phase: re-extract-3-verify
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-VERIFIER
# Agent: speckit-echelon-re-verifier

## Context Pack

- `specs/NNN-re-*/spec.md` — all current domain specs
- `{state.output_dir}/analysis.json` — full file list for coverage computation
- `{state.output_dir}/state.json` — current coverage_pct, verify_expand_iterations

## Dispatch Prompt

Instruct RE-VERIFIER to: compute coverage % (source files covered by specs / total source files), identify orphan files (not covered by any spec), cluster orphans by similarity, write `coverage-report.md`, update `coverage_pct` and increment `verify_expand_iterations` in echelon_result.

## Expected Outputs

- `specs/000-re-overview/coverage-report.md`

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-3-verify
  state_updates:
    coverage_pct: 72
    verify_expand_iterations: 2  # COMMANDER checks this against max_verify_expand_iterations for loop exit
  output_files:
    - specs/000-re-overview/coverage-report.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-3-verify
      data:
        summary: "Coverage: {coverage_pct}% ({orphan_count} orphan files)"
  blocked_reason: null
```
