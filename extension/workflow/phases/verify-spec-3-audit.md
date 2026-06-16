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

## Deterministic Pre-audit

Before dispatching SPEC-FULFILLMENT-AUDITOR, run:

```bash
python -m harness write-canonical-requirements "{spec_dir}" "{verify_run_dir}"
```

This writes `{verify_run_dir}/canonical-requirements.json` and
`{verify_run_dir}/canonical-requirements.md`. These files are the Python-owned
canonical requirement inventory for this verify-spec run.

## Dispatch Prompt

Extract a canonical fulfillment checklist. Include requirements, acceptance
criteria, user stories, edge cases, and measurable non-functional requirements.
Use `plan.md` for intended architecture and phase commitments. Use
`progress-integrity.json` and `progress-integrity.md` as the authoritative
task-progress integrity evidence. Do not recalculate task progress by hand.
Preserve the row set from `{verify_run_dir}/canonical-requirements.json`; do not
invent, rename, or drop canonical item IDs in `requirement-audit.md`.
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
- `{verify_run_dir}/requirement-audit.md` with exactly the IDs from
  `{verify_run_dir}/canonical-requirements.json`.
- task-progress integrity notes with any mismatch that could make the spec look
  implemented when task tracking says otherwise.

Proceed to `verify-spec-4-map`.
