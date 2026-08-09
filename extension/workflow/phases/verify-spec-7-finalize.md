# Phase: verify-spec-7-finalize
# Read by: echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

Finalize a verify-spec run only after deterministic fulfillment validation and
optional progress reconciliation have completed.

Run exactly:

```bash
python -m harness complete-verify-spec-run "{verify_run_dir}"
```

The command durably writes `status: complete` and a timezone-aware
`completed_at` to `{verify_run_dir}/state.json`. No earlier phase owns either
completion field. If the command fails, hard stop with BLOCKED and report its
stderr. Do not hand-edit `state.json`.

## Output

Proceed to `DONE`.
