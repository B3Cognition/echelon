# Artifact Quality Benchmark Design

## Summary

Echelon currently applies Understanding primarily to `spec.md`, with Lexicon hard gates for the derived requirements artifact and optionally `tasks.md`. The proposed experiment measures whether cleansing other LLM-consumed artifacts helps the build finish faster and better, using build outcomes as the source of truth instead of artifact scores alone.

This design adds an opt-in benchmark path and experimental artifact-quality phases for:

- `constitution.md`
- `tasks.md`
- `adr/ADR-*.md`

The default Phase A and harness workflows remain unchanged.

## Goals

- Compare normal artifacts against cleansed artifacts using real build outcomes.
- Measure implementation efficiency through turns, retries, blocked states, verification failures, fulfillment gaps, review findings, elapsed time, and available token metadata.
- Add a small repeatable benchmark fixture that is simple enough to run often but complex enough to expose artifact ambiguity.
- Keep artifact cleansing opt-in and runnable through targeted phase execution.
- Start with constitution and tasks as the highest-value targets, while including ADRs as an experimental bundle.

## Non-Goals

- Do not make artifact cleansing part of the default workflow.
- Do not treat Understanding or Lexicon scores as the final benchmark result.
- Do not directly edit `.specify/memory/constitution.md` outside the CHIEF / `speckit.constitution` protocol.
- Do not replace existing Lexicon gates for `requirements.lexicon.md` or `tasks.md`.
- Do not introduce a broad new LLM workflow runner when `echelon phase run` already exists.

## Benchmark Fixture

The first fixture should be a tiny notes app rather than a pure hello-world app. It should include:

- create, list, and delete notes
- required text validation
- empty state
- local persistence
- minimal keyboard/accessibility expectation
- at least one automated test expectation

This is small enough for repeated runs but still sensitive to task clarity, governance quality, and architecture decisions.

## Benchmark Variants

The benchmark should support these initial variants:

- `baseline`: normal Phase A artifacts, then build.
- `constitution`: run constitution cleanse before build.
- `constitution-tasks`: run constitution and tasks cleanse before build.
- `constitution-tasks-adrs`: run constitution, tasks, and ADR cleanse before build.

Running variants separately preserves attribution. If `constitution` alone improves blocked states or review findings, that is a different signal than an improvement that only appears after tasks and ADRs are also cleansed.

## Command Shape

Add this benchmark command family:

```bash
echelon benchmark list
echelon benchmark run tiny-notes --variant baseline
echelon benchmark run tiny-notes --variant constitution
echelon benchmark run tiny-notes --variant constitution-tasks
echelon benchmark run tiny-notes --variant constitution-tasks-adrs
```

The benchmark command should orchestrate existing commands where possible:

- Phase A generation through existing Echelon flow.
- Experimental cleanse phases through `echelon phase run`.
- Build through the existing harness path.
- Result collection from existing run state, harness state, and generated reports.

## Experimental Phases

### Constitution Quality

Phase id: `phase-exp-constitution-quality`

Inputs:

- `.specify/memory/constitution.md`
- published `{spec_dir}/constitution.md`
- `{spec_dir}/spec.md`
- `{spec_dir}/plan.md`, if present
- reasoning journal context

Outputs:

- `{spec_dir}/constitution-quality-report.md`
- state keys:
  - `constitution_quality_pass`
  - `constitution_quality_attempts`
  - `constitution_quality_findings`

Repair rule:

The phase may not directly edit the constitution files. If repair is needed, it dispatches CHIEF with the findings and requires CHIEF to use the constitution protocol. The published snapshot is refreshed only through existing publication mechanics.

### Tasks Quality

Phase id: `phase-exp-tasks-quality`

Inputs:

- `{spec_dir}/spec.md`
- `{spec_dir}/plan.md`
- `{spec_dir}/tasks.md`
- `{spec_dir}/requirements.lexicon.md`, if present
- `{spec_dir}/test-strategy.md`, if present
- reasoning journal context

Outputs:

- updated `{spec_dir}/tasks.md`
- `{spec_dir}/tasks-quality-report.md`
- state keys:
  - `tasks_quality_pass`
  - `tasks_quality_attempts`
  - `tasks_quality_findings`

Repair rule:

The phase dispatches ORCHESTRATOR in a constrained tasks-quality repair mode. It should preserve existing task IDs where possible and make tasks more self-contained, testable, and traceable to requirements.

### ADR Quality

Phase id: `phase-exp-adr-quality`

Inputs:

- `{spec_dir}/plan.md`
- `{spec_dir}/architecture.md`, if present
- `{spec_dir}/adr/ADR-*.md`
- `{spec_dir}/tasks.md`
- reasoning journal context

Outputs:

- updated ADRs when repair is needed
- `{spec_dir}/adr-quality-report.md`
- state keys:
  - `adr_quality_pass`
  - `adr_quality_attempts`
  - `adr_quality_findings`

Repair rule:

The phase dispatches the architecture owner for ADR repairs. It checks for unclear decisions, missing consequences, contradictions between ADRs, and drift against `plan.md`.

## Data Flow

1. Benchmark runner creates or selects the fixture request.
2. Baseline variant runs normal Phase A and build.
3. Cleansed variants run normal Phase A, then the selected experimental phases through `echelon phase run`.
4. Each cleanse phase writes a report and state updates through normal COMMANDER/state/journal contracts.
5. Harness build runs normally.
6. Benchmark runner collects comparable metrics and writes a result report.

## Metrics

Primary metrics:

- build turns or dispatches
- harness retries
- blocked states and blocked reasons
- verification failures
- fulfillment gaps
- review-loop comments or blocking findings
- elapsed time

Secondary metrics:

- Understanding or Lexicon scores by artifact
- number of cleanse attempts
- number and severity of cleanse findings
- token metadata when available

The benchmark verdict should be based on build outcomes. Artifact scores explain the result; they do not replace it.

## Storage

Benchmark outputs are written under this deterministic benchmark results directory shape:

```text
runs/benchmarks/<timestamp>-tiny-notes/
  baseline/
  constitution/
  constitution-tasks/
  constitution-tasks-adrs/
  summary.json
  summary.md
```

Each variant directory should include enough pointers to reconstruct the associated Echelon run, harness run, spec id, branch, and artifact-quality reports.

## Error Handling

- If a cleanse phase cannot resolve a target spec directory, fail the variant and record the failure.
- If Understanding is unavailable, record the dependency failure and continue only when the variant does not require it.
- If Lexicon is unavailable or returns invalid output, mark the affected cleanse phase failed.
- If constitution repair would require bypassing CHIEF, block the phase instead.
- If the benchmark fixture cannot build due to environment setup, mark the run inconclusive rather than treating artifact quality as the cause.

## Testing

Unit tests should cover:

- benchmark variant parsing
- result aggregation
- experimental phase registration in `definition.yaml`
- allowed state update keys for each experimental phase
- constitution phase refusing direct constitution edits by contract text

Integration-style tests should cover:

- `echelon phase list` includes experimental phases
- `echelon phase run phase-exp-tasks-quality --spec <id>` records manual replay state
- benchmark summary generation from fake run/harness state

The first implementation can use fake provider responses for phase tests and synthetic harness state for benchmark aggregation.

## Rollout

1. Add the design and implementation plan.
2. Add benchmark result model and summary aggregation with fake data tests.
3. Register experimental phases without enabling them in the default workflow.
4. Add tasks cleanse first, then constitution, then ADRs.
5. Add the tiny-notes fixture and run baseline versus cleansed variants manually.
6. Use measured results to decide whether any cleanse phase should become a recommended optional step.
