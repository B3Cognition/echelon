# Phase: verify-spec-2-progress-integrity
# Read by: echelon-commander (COMMANDER)

## Purpose

Write deterministic task progress integrity evidence before agent judgment.

## Required Command

Run:

```bash
python -m harness write-progress-integrity "{spec_dir}/tasks.md" "{verify_run_dir}/state.json" "{verify_run_dir}/progress-integrity.json" "{verify_run_dir}/progress-integrity.md"
```

The command writes `progress_integrity: valid` and deterministic progress counts
to `{verify_run_dir}/state.json` on success. If the command fails, it writes
`progress_integrity: invalid` with the validation errors in `state.json`; stop
verify-spec and report the exact validation error. Do not ask an LLM to infer or
repair progress integrity.

## Expected Outputs

- `{verify_run_dir}/progress-integrity.json`
- `{verify_run_dir}/progress-integrity.md`

Proceed to `verify-spec-3-audit`.
