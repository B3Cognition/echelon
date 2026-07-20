# Execution Telemetry and Bounded RE Profiles

**Date:** 2026-07-20
**Status:** Approved

## Problem

The RE run `re-20260718-063615-364321` for `md_distribution` demonstrates that
the current convergence controls bound individual loops without bounding the
whole run. The workspace contains four sources and nineteen domains, but the
default policy permits five domain repairs per domain, five source cycles, five
source reanalyses, and five global validation iterations. Prosaic alone reached
fifty-five domain repairs, while two sources terminated with explicit quality
debt.

The run state does not record a reliable start time, elapsed execution time, or
provider token usage. Echelon therefore cannot enforce an end-to-end resource
budget, explain the cost of a run, or compare quality improvements with the
time and tokens spent obtaining them. This affects RE now and will affect spec
and delivery tuning for the same reason.

## Goals

- Create reusable execution telemetry for every Echelon lifecycle.
- Establish a recoverable baseline from existing run directories without
  inventing unavailable measurements.
- Add an analyzer that attributes time, tokens, retries, repairs, findings, and
  outcomes to workflow phases and dispatches.
- Make `fast`, `balanced`, and `high` explicit execution goals.
- Make `balanced` the default RE profile with hard ceilings of 5,000,000 tokens
  and 180 minutes.
- Retain a 60-minute optimization target for balanced RE so the hard ceiling is
  a guardrail rather than the expected runtime.
- Require zero unresolved blocking findings for complete publication.
- Preserve safe continuation without resetting time, token, or convergence
  accounting.

## Non-Goals

- Do not send telemetry to a remote collector by default.
- Do not store prompts, responses, source code, or secrets in telemetry.
- Do not retroactively estimate token usage for legacy runs.
- Do not implement spec or delivery analyzers in this slice; this design makes
  the shared substrate reusable by those analyzers.
- Do not make quality scores from different workflow types directly
  interchangeable.
- Do not interrupt an in-flight provider dispatch solely because a budget is
  crossed during that dispatch.

## Decision

Build a deterministic execution-observability layer in Python and integrate RE
with it first. A run is a trace, a lifecycle phase or agent dispatch is a span,
and repair/retry attempts are child spans. Local append-only JSONL is the
durable source of truth. The record shape follows OpenTelemetry trace and GenAI
semantic conventions where they apply and uses an `echelon.*` namespace for
workflow-specific attributes.

The RE controller, not an agent prompt or external watchdog, owns profile
resolution, accounting, and budget enforcement. It checks remaining budget
before each new dispatch. A dispatch already in flight may finish so its result
can be checkpointed. The next routing decision either continues, records
non-blocking quality debt, or blocks publication when blocking findings remain.

## Standards-Aligned Telemetry

### Trace hierarchy

- One trace represents one Echelon lifecycle run.
- A workflow-phase span represents deterministic phase execution.
- An agent-dispatch span represents one logical provider call.
- A retry or repair is a child span linked to the phase, source, and domain that
  caused it.
- Span identifiers are generated before dispatch and remain stable when the
  completed event is appended.

### Standard attributes

Use current OpenTelemetry names when the provider exposes the corresponding
fact, including:

- `gen_ai.operation.name`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.reasoning.output_tokens`
- provider-cache token attributes supported by the current convention
- standard span start, end, duration, status, and error attributes

The implementation pins a documented semantic-convention version in each
ledger. Experimental upstream names are isolated behind a normalization module
so future convention changes do not alter controller logic or old records.

### Echelon attributes

Low-cardinality Echelon-specific attributes use the `echelon.*` namespace:

- `echelon.run.id`
- `echelon.workflow.name`: `re`, `spec`, or `delivery`
- `echelon.workflow.phase`
- `echelon.agent.name`
- `echelon.execution.profile`
- `echelon.source.id`
- `echelon.domain.id`
- `echelon.attempt.kind`: `initial`, `retry`, `repair`, or `reanalysis`
- `echelon.attempt.number`
- `echelon.result.verdict`
- `echelon.findings.blocking_count`
- `echelon.findings.non_blocking_count`
- `echelon.quality_debt.count`

High-cardinality IDs needed for correlation remain in the local ledger but are
not promoted to default metric labels.

### Data minimization

Telemetry records prompt and result byte counts and optional content hashes,
not content. Provider or model identifiers are retained. Environment variables,
arguments that may contain user text, repository contents, and raw exception
payloads are excluded or normalized. Writes are append-only and use the run
directory's existing ownership and permissions.

## Local Persistence

Each instrumented run contains:

```text
runs/<run-id>/telemetry/
  manifest.json
  spans.jsonl
```

`manifest.json` records schema version, semantic-convention version, run and
workflow identity, resolved profile, trace ID, and creation time.
`spans.jsonl` contains immutable completed-span records. State stores only
controller checkpoints and cumulative budget counters; the analyzer can
reconcile those counters from the ledger and report disagreement.

Appending a span uses an atomic single-record write guarded by the run's writer
discipline. A truncated final line is ignored with a diagnostic. Invalid earlier
records degrade analysis but do not prevent the controller from using its
checkpointed cumulative counters.

## Execution Profiles

Profiles combine performance goals, hard resource ceilings, and convergence
limits:

| Profile | Performance target | Hard elapsed ceiling | Hard token ceiling | Domain repairs | Source cycles | Source reanalysis |
|---|---:|---:|---:|---:|---:|---:|
| `fast` | 30 minutes | 60 minutes | 1,000,000 | 1 | 1 | 1 |
| `balanced` | 60 minutes | 180 minutes | 5,000,000 | 3 | 2 | 2 |
| `high` | 180 minutes | 720 minutes | 15,000,000 | 5 | 5 | 5 |

`balanced` is the default for new RE runs. Users may select a profile or
explicitly override individual ceilings. The fully resolved values—not merely
the profile name—are frozen into initial run state.

Elapsed budget counts active command execution across `run`, `continue`, and
`resume`, not wall time while the process is stopped. Each invocation records
an execution interval. Token budget is cumulative provider-reported input plus
output, reasoning, and provider-cache tokens where reported. Missing usage is
recorded as unknown. A run with unknown usage does not claim token-budget
compliance; elapsed and convergence ceilings still apply.

Continuation preserves consumed counters and resolved limits. It may accept an
explicit increase through the existing budget-raising model, but never lowers a
limit below consumption and never resets usage or elapsed execution time.

## Budget and Publication Semantics

Before every dispatch, the controller evaluates hard time, token, and
convergence ceilings. Because the exact cost of a future provider call is
unknown, a dispatch may begin only when the corresponding observed cumulative
value remains below its ceiling. A dispatch that crosses a ceiling completes
and checkpoints, but no subsequent dispatch starts.

When a ceiling or convergence limit stops work:

- unresolved blocking findings produce a typed budget block and prevent
  complete publication;
- unresolved non-blocking findings become structured quality debt;
- no unresolved findings permits normal completion and publication;
- the console summary identifies the controlling limit and gives the exact
  continuation command when an explicit increase is supported.

Finding severity is controller-validated structured data. Agents cannot relabel
controller-recognized blocking categories as non-blocking merely to satisfy a
profile.

## Analyzer

The shared analyzer reads telemetry and lifecycle-specific state through a
small adapter interface. The RE adapter adds domain repair, validation, source
cycle, repeated-finding, and quality-debt analysis. Future spec and delivery
adapters reuse trace loading, duration/token aggregation, profile comparison,
and output formatting.

The RE command is:

```text
echelon re analyze [RUNS_DIR] [--run-id ID] [--format text|json]
```

It is callable directly and has command-specific help, but is hidden from the
ordinary `echelon re --help` listing. A hidden `echelon admin commands` command
prints the diagnostic command catalog when explicitly requested. No persistent
admin or god-mode state is introduced.

Analyzer output includes:

- elapsed active execution and end-to-end wall-clock span;
- provider-reported token totals and unknown-usage dispatch counts;
- tokens and duration by workflow phase, agent, source, and domain;
- repair, retry, and reanalysis counts;
- repeated or substantially identical finding identifiers;
- findings resolved per repair and repairs that did not improve the verdict;
- final blocking and non-blocking quality debt;
- selected profile, targets, ceilings, and compliance;
- explicit data-quality limitations.

Text output is concise and actionable. JSON output is versioned and contains the
same facts for benchmark automation. Analysis never mutates the target runs.

## Legacy Baseline

Existing runs without telemetry are analyzed from their state, journals,
quality reports, execution plans, and filesystem timestamps. Every derived
field records its provenance and confidence. File timestamps may establish an
approximate wall-clock window and phase ordering, but not active execution
duration. Missing provider usage is `unknown`, not zero.

The initial `md_distribution` baseline must at least report:

- four sources and nineteen domains;
- current five/five/five convergence defaults;
- fifty-five Prosaic domain repairs;
- two sources in `partial_quality_debt` at the observed snapshot;
- absence of reliable token and active-duration telemetry;
- failure to demonstrate the balanced 60-minute performance target;
- indeterminate token-ceiling compliance.

## CLI and Configuration

New RE runs accept `--profile fast|balanced|high`. Explicit time, token, and
convergence overrides use clear RE-prefixed options and are persisted as the
resolved profile. Configuration provides the same values under `re.profiles`
with shipped defaults matching this specification.

`continue` and `resume` do not silently resolve configuration again. They use
the frozen run values. Existing pre-profile active runs are migrated lazily to a
named `legacy` resolved profile using their stored convergence values; missing
time and token ceilings remain unknown unless the operator explicitly adopts a
new profile.

## Error Handling

- Unsupported or malformed telemetry records are skipped and reported.
- A provider with no usage data increments unknown-usage counts and cannot be
  described as token-compliant.
- A ledger write failure blocks before the next dispatch so unobserved work
  cannot accumulate silently.
- Counter/ledger disagreement is reported and the higher defensible consumed
  value controls budget enforcement.
- Invalid profile or override combinations fail before run creation.
- A budget crossing never corrupts the last-dispatch continuation sentinel.

## Testing

Tests must prove:

1. Provider results from Claude, Codex, OpenAI-compatible, Copilot, and OpenCode
   normalize available usage without inventing missing fields.
2. Telemetry records contain required trace, GenAI, and Echelon attributes and
   exclude prompt/response content.
3. A controller reconstructed by `continue` preserves trace identity, active
   elapsed time, cumulative tokens, and resolved profile.
4. Fast, balanced, and high resolve to the exact table values.
5. Balanced is the default for new RE runs.
6. No new dispatch starts at or above a hard ceiling.
7. An in-flight dispatch may finish, checkpoint, and cross the ceiling once.
8. Blocking findings prevent publication at a ceiling; non-blocking findings
   become quality debt.
9. Hidden analyzer commands remain callable but do not appear in ordinary help.
10. The analyzer produces stable text and JSON for complete, partial, corrupt,
    and legacy runs.
11. The `md_distribution` fixture/baseline reports the known facts above and
    marks token usage and active duration unknown.
12. Existing RE continuation, granular validation, publication, and explicit
    budget-increase tests continue to pass.

## Rollout

Implement the shared telemetry schema and analyzer core first, then instrument
RE provider dispatches and add profile enforcement. Generate the legacy
`md_distribution` baseline as a checked, reproducible report or fixture. Spec
and delivery integration remain follow-up slices using the same schema and
adapter boundary.

