# Phase: verify-spec-3-audit
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-fulfillment-auditor

## Context Pack

Provide SPEC-FULFILLMENT-AUDITOR with:
- `spec.md`
- `tasks.md`
- `coverage-map.md` if present
- verification `state.json`

## Dispatch Prompt

Extract a canonical fulfillment checklist. Include requirements, acceptance
criteria, user stories, edge cases, and measurable non-functional requirements.

## Expected Output

- checklist items with ID, source text, category, expected behavior, and
  acceptance signal.

Proceed to `verify-spec-4-map`.
