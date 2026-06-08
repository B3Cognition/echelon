# Phase: verify-spec-3-audit
# Read by: speckit-echelon-commander (COMMANDER)
# Agent: speckit-echelon-spec-fulfillment-auditor

## Context Pack

Provide SPEC-FULFILLMENT-AUDITOR with:
- `spec.md`
- `plan.md`
- `tasks.md`
- `progress-integrity.json`
- `progress-integrity.md`
- `coverage-map.md` if present
- verification `state.json`

## Dispatch Prompt

Extract a canonical fulfillment checklist. Include requirements, acceptance
criteria, user stories, edge cases, and measurable non-functional requirements.
Use `plan.md` for intended architecture and phase commitments. Use
`progress-integrity.json` and `progress-integrity.md` as the authoritative
task-progress integrity evidence. Do not recalculate task progress by hand.
Task-progress integrity is bookkeeping evidence, not implementation evidence:
it can reveal stale or inconsistent task tracking, but it does not decide
whether source code fulfills a requirement.

NEVER instruct downstream agents to downgrade source-backed implementation
evidence solely because the corresponding task checkbox is still pending.
If task progress and code evidence disagree, preserve the requirement checklist
as extracted from the spec and record the disagreement as a task-progress
integrity note.

## Expected Output

- checklist items with ID, source text, category, expected behavior, and
  acceptance signal.
- task-progress integrity notes with any mismatch that could make the spec look
  implemented when task tracking says otherwise.

Proceed to `verify-spec-4-map`.
