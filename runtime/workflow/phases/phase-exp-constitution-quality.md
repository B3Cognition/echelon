# Phase: phase-exp-constitution-quality
# Agent: echelon.chief (CHIEF)
# Read by: echelon.commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair constitution clarity before build benchmarking. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `.echelon/constitution.md`, published `constitution.md`, `spec.md`, `plan.md` when present, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are CHIEF. Read subagents/echelon.chief.md for your complete protocol.
Operate in experimental constitution-quality mode for EGR-063.

Audit the active constitution for ambiguity, unresolved placeholders, unclear governance rules, contradictions with the current feature context, and guidance likely to confuse later LLM agents.

ALWAYS route any repair through the CHIEF constitution protocol.
NEVER directly mutate `.echelon/constitution.md` or the published `constitution.md` snapshot outside the constitution protocol, whether through shell redirection or provider-specific file mutation interfaces.

Write `constitution-quality-report.md` in `{spec_dir}/` with findings, attempted repair steps, and final verdict.
Return `echelon_result.state_updates.constitution_quality_pass`, `constitution_quality_attempts`, and `constitution_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    constitution_quality_pass: true
    constitution_quality_attempts: 1
    constitution_quality_findings: 0
  journal_entries: []
```
