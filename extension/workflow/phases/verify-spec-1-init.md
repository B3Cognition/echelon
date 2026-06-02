# Phase: verify-spec-1-init
# Read by: speckit-echelon-commander (COMMANDER) before verification dispatch
# Type: commander_internal

## Objective

Parse `spec_id` and optional `strict=true`. Locate `specs/{spec_id}-*/`.
Create a verification runtime directory:
- active run: `runs/<run-id>/verify-spec/{spec_id}/`
- no active run: `runs/verify-spec-{spec_id}-{timestamp}/`

## State

Write `state.json` in the verification runtime directory with:
- `spec_id`
- `spec_dir`
- `strict`
- `verify_run_dir`
- `status: in_progress`
- `structural_evidence: pending`

## Output

Proceed to `verify-spec-2-codegraph`.
