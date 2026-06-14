# Phase: verify-spec-5-judge
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-guard

## Context Pack

Provide SPEC-GUARD with:
- fulfillment checklist
- implementation evidence map
- `spec.md`
- `tasks.md`
- `progress-integrity.json`
- `progress-integrity.md`
- verification `state.json`

## Dispatch Prompt

Run SPEC-GUARD in fulfillment mode. Assign exactly one status per item:
`IMPLEMENTED`, `PARTIAL`, `UNVERIFIED`, `MISSING`, `DEVIATED`, or
`OBSOLETE_SPEC`.

Judge item fulfillment from the implementation evidence map and the requirement's
acceptance signal. Task progress is bookkeeping integrity evidence only. SPEC-GUARD
MUST NOT downgrade an item from `IMPLEMENTED` to `PARTIAL`, `UNVERIFIED`, or
`MISSING` solely because `tasks.md` marks the related task pending, when source and executable test evidence satisfy the requirement and acceptance signal.

Also judge task-progress integrity from `progress-integrity.json` and
`progress-integrity.md`. If progress integrity is invalid or incomplete, write a
`TASK-PROGRESS` row with status `PARTIAL` and include the mismatch in
`{spec_dir}/fulfillment-gaps.md`.

## Expected Outputs

Write:
- `{spec_dir}/fulfillment-report.md`
- `{spec_dir}/fulfillment-gaps.md` only when actionable gaps exist

Before returning DONE, perform row-set integrity validation: every item ID in
`{verify_run_dir}/requirement-audit.md` must appear exactly once in
`{spec_dir}/fulfillment-report.md`, and the report must not invent extra item
IDs. `TASK-PROGRESS` is the only permitted synthetic report row. If validation
fails, hard stop with BLOCKED and do not summarize the run as complete.

Return summary and recommended action.
