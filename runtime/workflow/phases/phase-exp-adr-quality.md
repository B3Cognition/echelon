# Phase: phase-exp-adr-quality
# Agent: echelon.architect (ARCHITECT)
# Read by: echelon.commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair ADRs so implementation agents receive coherent decision context. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `plan.md`, `architecture.md` when present, `adr/ADR-*.md`, `tasks.md`, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are ARCHITECT. Read subagents/echelon.architect.md for your complete protocol.
Operate in experimental ADR-quality mode for EGR-063.

Audit ADRs for unclear decisions, missing status, missing consequences, contradictions between ADRs, drift from `plan.md`, and missing links from important task or architecture choices.

Repair ADRs using the existing ADR style in the spec directory. Do not create ADRs for trivial implementation details.

Write `adr-quality-report.md` in `{spec_dir}/` with findings, repairs, and final verdict.
Return `echelon_result.state_updates.adr_quality_pass`, `adr_quality_attempts`, and `adr_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    adr_quality_pass: true
    adr_quality_attempts: 1
    adr_quality_findings: 0
  journal_entries: []
```
