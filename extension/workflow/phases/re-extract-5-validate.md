# Phase: re-extract-5-validate
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-VALIDATOR
# Agent: speckit-echelon-re-validator

## Context Pack

- `specs/NNN-re-*/spec.md` — all domain specs
- `{state.output_dir}/analysis.json` — source code for ambiguity resolution
- `{state.output_dir}/state.json` — resolution_pct, validate_iterations, max_validate_iterations

## Dispatch Prompt

Instruct RE-VALIDATOR to: apply quality checks (Basic strategy first, then Deep if resolution_pct < threshold and iterations < max, then Extended), auto-resolve ambiguities by reading source code, write validation-report.md with per-domain resolution scores, update resolution_pct and increment validate_iterations.

## Expected Outputs

- `specs/000-re-overview/validation-report.md`

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-5-validate
  state_updates:
    resolution_pct: 85
    validate_iterations: 1
  output_files:
    - specs/000-re-overview/validation-report.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-5-validate
      summary: "Resolution: {resolution_pct}% (iteration {validate_iterations})"
  blocked_reason: null
```
