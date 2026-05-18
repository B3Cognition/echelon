# Phase: re-extract-6-checklist
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-CHECKLISTER
# Agent: speckit-echelon-re-checklister

## Context Pack

- `specs/NNN-re-*/spec.md` — all domain specs
- `specs/000-re-overview/coverage-report.md`
- `specs/000-re-overview/validation-report.md`

## Dispatch Prompt

Instruct RE-CHECKLISTER to: generate per-domain checklists (`NNN-re-{domain}/checklist.md`) with domain-specific quality items (completeness, clarity, consistency, implementability), generate summary checklist (`000-re-overview/checklist.md`) covering cross-domain migration concerns.

## Expected Outputs

- `specs/NNN-re-{domain}/checklist.md` — one per domain
- `specs/000-re-overview/checklist.md`

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-6-checklist
  state_updates: {}
  output_files:
    - specs/000-re-overview/checklist.md
    - specs/001-re-auth/checklist.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-6-checklist
      summary: "Generated checklists for {N} domains"
  blocked_reason: null
```
