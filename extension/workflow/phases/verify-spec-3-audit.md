# Phase: verify-spec-3-audit
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-fulfillment-auditor

## Context Pack

Provide SPEC-FULFILLMENT-AUDITOR with:
- `spec.md`
- `plan.md`
- `tasks.md`
- `coverage-map.md` if present
- verification `state.json`

## Dispatch Prompt

Extract a canonical fulfillment checklist. Include requirements, acceptance
criteria, user stories, edge cases, and measurable non-functional requirements.
Use `plan.md` for intended architecture and phase commitments. Use `tasks.md`
and verification `state.json` to include a task-progress integrity section:
canonical task rows, recorded `**Status:**` values, checked rows, and mismatches
between `tasks.md` and `state.json.build`.

## Expected Output

- checklist items with ID, source text, category, expected behavior, and
  acceptance signal.
- task-progress integrity notes with any mismatch that could make the spec look
  implemented when task tracking says otherwise.

Proceed to `verify-spec-4-map`.
