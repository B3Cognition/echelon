# Phase: verify-spec-5-judge
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-guard

## Context Pack

Provide SPEC-GUARD with:
- fulfillment checklist
- implementation evidence map
- `spec.md`
- `tasks.md`
- verification `state.json`

## Dispatch Prompt

Run SPEC-GUARD in fulfillment mode. Assign exactly one status per item:
`IMPLEMENTED`, `PARTIAL`, `UNVERIFIED`, `MISSING`, `DEVIATED`, or
`OBSOLETE_SPEC`.

Also judge task-progress integrity. If `tasks.md` canonical rows, recorded
`**Status:**` values, or `state.json.build` disagree, write a `TASK-PROGRESS`
row with status `PARTIAL` and include the mismatch in `{spec_dir}/fulfillment-gaps.md`.

## Expected Outputs

Write:
- `{spec_dir}/fulfillment-report.md`
- `{spec_dir}/fulfillment-gaps.md` only when actionable gaps exist

Return summary and recommended action.
