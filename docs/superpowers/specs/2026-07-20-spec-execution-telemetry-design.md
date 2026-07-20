# Spec Execution Telemetry Design

## Goal

Add complete, content-free execution telemetry to `echelon spec`, expose a
hidden run analyzer, and project the results into the optional local operations
wiki. The implementation reuses the shared OpenTelemetry-aligned storage
introduced for reverse engineering.

## Scope

The first release includes telemetry capture, analysis, CLI access, and wiki
rendering. It covers normal phase agents, COMMANDER judgments, automated repair
dispatches, banzai escalation judgments, continuation, resume, and manual phase
replay. Existing runs without telemetry remain analyzable with explicit data
limitations.

Delivery telemetry is outside this change, but all new storage and aggregation
interfaces must remain workflow-neutral so Delivery can adopt them later.

## Architecture

### Instrumented provider boundary

Every provider call made for a Spec run passes through one telemetry-aware
provider wrapper. The wrapper delegates to the existing provider and appends
one `ExecutionSpan` after the call completes or raises. This central boundary
prevents individual executors from implementing incompatible accounting and
ensures nested COMMANDER and repair calls are not silently omitted.

The controller or executor supplies a small dispatch context immediately before
each call:

- workflow phase
- agent name
- dispatch kind (`phase`, `judgment`, `repair`, or `escalation`)
- attempt number
- run identifier and trace identifier

Context is run-local and must not leak between concurrent or subsequent
dispatches. A provider result supplies duration, status, token components,
provider name, model name, and verdict. Prompts, responses, source content, and
artifact bodies are never stored.

### Trace lifecycle

A fresh Spec run creates one trace identity and
`telemetry/manifest.json`. The identity is persisted in run state and reused by
`spec continue`, `spec resume`, and manual phase replay. Telemetry files remain
local run artifacts and are not published with canonical specifications.

Spans are appended to `telemetry/spans.jsonl` through the existing
`TelemetryStore`. Truncated final records and malformed historical records are
reported as diagnostics and do not make the run or analyzer fail.

### Spec analysis adapter

A new Spec adapter converts state plus spans into a workflow-neutral
`RunAnalysis`. Spec-specific metrics are represented in a dedicated extension
rather than adding more RE-named fields to the common model. The report
contains:

- total and unknown token usage
- active and wall-clock duration
- dispatches, time, and tokens by phase, agent, model, and dispatch kind
- retry and repair counts
- WHY, WHAT, and PLAN loop counts
- repeated blocker categories
- time and tokens to an accepted specification when determinable
- provenance and limitations for every inferred or unavailable measure

Existing Spec runs without span files fall back to state-level totals where
available. Missing provider/model/token data remains `unknown`; it is never
silently converted to zero.

## CLI

`echelon spec analyze` is hidden from normal help, consistent with
`echelon re analyze`. It accepts one optional path:

- a single Spec run directory, or
- a directory containing Spec runs (default `runs/`).

It does not accept a separate run ID and directory combination. `--format text`
and `--format json` use the shared renderers. Unsafe paths and non-Spec runs are
rejected with actionable errors.

## Wiki integration

`echelon wiki build --include-runs` discovers both RE and Spec run analyses.
Local operations pages include:

- one page per Spec run
- Spec performance and token tables
- repair-loop and repeated-blocker views
- model/provider cost breakdown when available

These pages stay explicitly local and ephemeral. Raw JSONL spans, prompt text,
and response content are not copied into the wiki.

## Error handling

Telemetry persistence is best-effort for historical analysis but strict during
new dispatch accounting: an append failure is surfaced and blocks the run
rather than allowing an unmeasured dispatch to continue. A provider exception
still emits an error span before the original exception propagates.

Analyzer input corruption is non-fatal. Valid spans are retained, invalid lines
produce diagnostics, and derived metrics state their limitations.

## Testing

Tests follow test-first development and cover:

- one span for a normal phase dispatch
- distinct COMMANDER judgment and escalation dispatch kinds
- repair dispatch attribution
- trace continuity across continue, resume, and manual phase replay
- provider and model-name propagation
- known component tokens and unknown token usage
- provider failures and telemetry write failures
- truncated and malformed JSONL analysis
- historical state-only fallback
- single-path CLI resolution and hidden command behavior
- Spec operations pages in `wiki build --include-runs`
- regression coverage for existing RE analysis and wiki pages

## Success criteria

- Every Spec provider dispatch emits exactly one content-free span.
- Continuations append to the original trace.
- The sum of known dispatch tokens matches the analyzer total.
- Unknown token usage remains distinguishable from zero usage.
- `echelon spec analyze` reports phase, agent, model, repair, and blocker costs.
- `echelon wiki build --include-runs` renders both RE and Spec operations views.
- Existing Spec runs and existing RE telemetry remain readable.
