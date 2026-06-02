# Phase: verify-spec-5-judge
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-guard

## Context Pack

Provide SPEC-GUARD with:
- fulfillment checklist
- implementation evidence map
- `spec.md`
- verification `state.json`

## Dispatch Prompt

Run SPEC-GUARD in fulfillment mode. Assign exactly one status per item:
`IMPLEMENTED`, `PARTIAL`, `UNVERIFIED`, `MISSING`, `DEVIATED`, or
`OBSOLETE_SPEC`.

## Expected Outputs

Write:
- `{spec_dir}/fulfillment-report.md`
- `{spec_dir}/fulfillment-gaps.md` only when actionable gaps exist

Return summary and recommended action.
