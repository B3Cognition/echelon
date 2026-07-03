# Phase: phase-exp-tasks-quality
# Agent: speckit-echelon-orchestrator (ORCHESTRATOR)
# Read by: speckit-echelon-commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair `tasks.md` so build agents receive self-contained, testable, requirement-linked work. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `spec.md`, `plan.md`, `tasks.md`, `requirements.lexicon.md` when present, `test-strategy.md` when present, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
Operate in experimental tasks-quality mode for EGR-063.

Audit tasks for missing requirement links, vague implementation instructions, missing test obligations, hidden dependencies, impossible sequencing, and task descriptions that require unstated context.

Run `lexicon validate "{spec_dir}/tasks.md" --type tasks --spec-ref "{spec_dir}/requirements.lexicon.md" --json` when `requirements.lexicon.md` exists. Treat parser or validation failures as quality findings and repair `tasks.md` using the normal ORCHESTRATOR task-authoring protocol.

Preserve existing task IDs when the task intent remains the same. Split tasks only when one task mixes independent work that cannot be implemented and tested together.

Write `tasks-quality-report.md` in `{spec_dir}/` with findings, repairs, and final verdict.
Return `echelon_result.state_updates.tasks_quality_pass`, `tasks_quality_attempts`, and `tasks_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    tasks_quality_pass: true
    tasks_quality_attempts: 1
    tasks_quality_findings: 0
  journal_entries: []
```
