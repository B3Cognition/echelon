# Phase: re-extract-7-constitute
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-CONSTITUTER
# Agent: speckit-echelon-re-constituter

## Context Pack

- `specs/NNN-re-*/spec.md`
- `specs/000-re-overview/checklist.md`
- `{state.output_dir}/analysis.json`
- `{state.output_dir}/state.json`

## Dispatch Prompt

Instruct RE-CONSTITUTER to: synthesize `constitution.md` (legacy analysis + target stack decisions with [REQUIRES INPUT] for unknowns), `migration-strategy.md` (6R/7R per domain), `risk-matrix.md`, `gap-analysis.md`, ADRs in `adrs/ADR-NNN-*.md`. Use preset templates if installed (check `.specify/presets/echelon-brownfield-*/`).

## Expected Outputs

- `constitution.md`
- `migration-strategy.md`
- `risk-matrix.md`
- `gap-analysis.md`
- `adrs/ADR-001-*.md` (at minimum one ADR)

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-7-constitute
  state_updates:
    status: done
  output_files:
    - constitution.md
    - migration-strategy.md
    - risk-matrix.md
    - gap-analysis.md
    - adrs/ADR-001-tech-debt-classification.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-7-constitute
      data:
        summary: "Strategic artifacts generated. {N} [REQUIRES INPUT] markers need human decisions."
  blocked_reason: null
```
