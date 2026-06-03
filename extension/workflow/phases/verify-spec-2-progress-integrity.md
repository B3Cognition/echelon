# Phase: verify-spec-2-progress-integrity
# Read by: speckit-echelon-commander (COMMANDER)

## Purpose

Write deterministic task progress integrity evidence before agent judgment.

## Required Command

Run:

```bash
python -m harness write-progress-integrity "{spec_dir}/tasks.md" "{verify_run_dir}/state.json" "{verify_run_dir}/progress-integrity.json" "{verify_run_dir}/progress-integrity.md"
```

If the command fails, stop verify-spec and report the exact validation error.
Do not ask an LLM to infer or repair progress integrity.

## Expected Outputs

- `{verify_run_dir}/progress-integrity.json`
- `{verify_run_dir}/progress-integrity.md`

Proceed to `verify-spec-3-audit`.
