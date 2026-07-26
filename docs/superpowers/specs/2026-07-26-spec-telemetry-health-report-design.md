# Spec Telemetry Health Report Design

## Goal

Turn existing Spec execution telemetry into a deterministic, exception-oriented
health report so operators can identify workflow instability without reading
run-state or telemetry files manually.

The report is observational. It must not change workflow state, dispatch agents,
alter routing, enforce performance thresholds, or block a run.

## Existing Foundation

The implementation reuses the existing telemetry pipeline:

1. `InstrumentedProvider` records content-free execution spans and dispatch
   lifecycle events.
2. `TelemetryStore` owns versioned, append-only run-local storage.
3. `spec_adapter.analyze_spec_run()` converts one run into `RunAnalysis`.
4. The Spec analyzer CLI renders text or versioned JSON.

The health report consumes `RunAnalysis` values and their normalized workflow
metrics. It does not parse `spans.jsonl`, `events.jsonl`, or run state through a
second code path.

## Scope

This change adds:

- an explicit `--health` mode to `echelon spec analyze`;
- deterministic aggregation across compatible Spec runs;
- exception ranking by reliability impact;
- text and JSON renderers containing the same conclusions;
- telemetry coverage reporting;
- phase-level blocker, repair, replay, duration, and token observations;
- clear diagnostics when the sample cannot support a comparison.

This change does not add:

- a synthetic health score;
- dashboards or a telemetry service;
- automatic alerts, CI gates, or workflow gates;
- changes to Spec execution, checkpoints, rewind, or dispatch;
- new telemetry storage formats;
- RE or Delivery health aggregation;
- probabilistic root-cause claims.

## Compatibility Cohorts

Cross-run comparisons are only meaningful within compatible cohorts. A cohort
key consists of:

- telemetry schema version;
- workflow (`spec`);
- execution profile name;
- autonomy mode when available;
- provider and model when both are known.

Unknown provider or model values remain explicit. They are not treated as equal
to a known provider or model. Runs without enough identity data can still
receive an individual health summary, but they are excluded from regression
comparisons that require that identity.

The command analyzes all discovered Spec runs but selects the cohort containing
the most recent run as the primary report. It lists excluded-run counts and
reasons. Run recency is determined from a persisted run timestamp when
available, falling back to the run directory modification time with explicit
provenance.

## Health Model

Health is represented by deterministic findings rather than one aggregate
score.

Each finding has:

- stable code;
- severity: `critical`, `warning`, or `info`;
- scope: run, phase, provider/model, or telemetry;
- observed value and comparison value when applicable;
- affected and eligible run counts;
- concise evidence;
- recommended investigation target, never an asserted root cause.

Findings are sorted by:

1. severity;
2. number of affected runs, descending;
3. phase in workflow order, then lexical fallback;
4. stable finding code.

This ensures identical inputs produce identical output.

## Signals

### Reliability

- terminal blocked or failed runs;
- blocker frequency grouped by phase and blocker reason;
- repeated blocker categories;
- provider error dispatches;
- exhausted deterministic or semantic repair;
- manual phase replay frequency.

### Convergence

- total dispatches per phase;
- initial dispatches versus semantic repair, deterministic repair, provider
  retry, resume, and manual rerun;
- median and maximum attempts for each phase;
- phases repeatedly requiring more than one attempt.

The implementation must not label the first dispatch of a phase as a repair
loop. Existing `repair_loops` values remain readable for compatibility but are
not used as authoritative health evidence.

### Performance

- active provider duration;
- tokens;
- duration and tokens by phase;
- p50 and p95 for cohorts with at least five eligible observations;
- latest-run change relative to the cohort median.

Performance findings are informational until at least five eligible runs exist.
A regression is reported when the latest value is both:

- greater than the cohort median by at least 50%; and
- greater than the cohort p95 of preceding runs.

No performance signal is critical.

### Telemetry Quality

- runs with missing manifests;
- missing or partial token usage;
- malformed or truncated telemetry diagnostics;
- unknown provider/model identity;
- missing dispatch lifecycle events.

Telemetry limitations are findings about observability, not workflow failures.

## Required Normalization

The Spec adapter will expose generic lifecycle facts in
`RunAnalysis.workflow_metrics`:

```json
{
  "dispatches": {
    "total": 12,
    "by_reason": {
      "initial": 8,
      "deterministic_repair": 2,
      "manual_rerun": 2
    },
    "by_phase": {
      "phase1-what": {
        "total": 3,
        "by_reason": {
          "initial": 1,
          "deterministic_repair": 1,
          "manual_rerun": 1
        },
        "max_attempt": 2,
        "errors": 0
      }
    }
  },
  "blockers_by_phase": {
    "phase1-lexicon": {
      "lexicon_gate_exhausted": 1
    }
  }
}
```

All phase names are data-driven. The analyzer must not hardcode WHY, WHAT,
PLAN, Lexicon, or future workflow nodes.

## Command Interface

Existing per-run behavior remains unchanged:

```text
echelon spec analyze [PATH] [--format text|json]
```

Health aggregation is opt-in:

```text
echelon spec analyze [PATH] --health [--format text|json]
```

`PATH` may be one Spec run or a directory containing Spec runs. For one run,
the report produces individual findings and states that cross-run comparisons
are unavailable.

Text output is concise and exception-first. It includes:

1. cohort and telemetry coverage;
2. overall categorical state: `HEALTHY`, `DEGRADED`, or `INSUFFICIENT_DATA`;
3. reliability summary;
4. ranked findings;
5. phase observations;
6. excluded runs and data limitations.

`DEGRADED` means at least one critical or warning finding exists. `HEALTHY`
means the available deterministic signals contain no critical or warning
findings. `INSUFFICIENT_DATA` means no eligible run has usable dispatch
telemetry. This state is informational and does not change the process exit
code.

JSON output is schema-versioned and contains the same findings, ordering, cohort
metadata, summaries, and diagnostics as text output.

The command exits zero for every successfully generated report. Invalid paths,
unsupported formats, or unreadable command inputs retain existing nonzero CLI
behavior. Observe-only health conclusions never become CI gates implicitly.

## Architecture

### `spec_adapter.py`

Continue to own translation from Spec lifecycle data into normalized
`RunAnalysis`. Add generic dispatch and blocker facts without changing existing
fields.

### `health.py`

Add workflow-neutral report primitives and Spec-oriented aggregation:

- `HealthFinding`;
- `HealthReport`;
- compatible cohort selection;
- deterministic summaries and thresholds;
- percentile helpers with no new dependency.

This module consumes `RunAnalysis` only.

### `render.py`

Add stable text and JSON health renderers. Existing run-analysis rendering stays
unchanged.

### `cli_app.py`

Add the `--health` option and delegate to the health aggregator and renderers.
The CLI performs discovery and presentation only.

## Error Handling

- Missing telemetry produces diagnostics and coverage findings.
- A corrupt historical record does not abort analysis if the existing adapter
  can return a `RunAnalysis`.
- Runs that cannot participate in a cohort are counted and explained.
- Unknown token usage is never converted to zero.
- Empty run collections keep the existing “No Spec runs found” behavior.
- Health aggregation must not write to the project or run directories.

## Testing

Tests must be written before production changes and cover:

- generic per-phase dispatch normalization;
- initial dispatches not counted as repairs;
- blocker grouping by phase and reason;
- deterministic cohort selection and run ordering;
- insufficient-data behavior;
- stable finding severity and ordering;
- performance findings below five samples remaining informational;
- p50/p95 regression detection at five or more samples;
- partial telemetry coverage;
- identical text and JSON conclusions;
- CLI `--health` for one run and a runs directory;
- unchanged existing `spec analyze` output;
- proof that analysis does not modify run inputs.

## Success Criteria

- An operator can identify the dominant failing phase and blocker category from
  one command.
- The report never requires direct telemetry-file inspection.
- Existing analyzer consumers and output remain compatible without `--health`.
- Phase observations work for Lexicon and future workflow nodes without
  hardcoded phase lists.
- Re-running the report over unchanged inputs produces byte-identical output
  except for no generated timestamps, which are deliberately omitted.
- No execution, routing, checkpoint, or rewind code changes are required.
