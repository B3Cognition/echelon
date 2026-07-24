# Python-Owned Lifecycle Telemetry Design

## Goal

Prevent Spec lifecycle telemetry from being overwritten by controller state
saves, while retaining phase duration and over-budget diagnostics.

## Decision

`state.json` is mutable controller state and is not a telemetry destination.
Lifecycle telemetry is append-only JSONL under `run_dir/telemetry/`, written by
the Python telemetry package.  The existing phase-timing shell command becomes
a compatibility shim only: it invokes the Python lifecycle command and never
reads or writes `state.json`.

## Event shape

The first lifecycle event type is `phase_timing`.  It includes the telemetry
schema version, trace identity, run identity, workflow, phase, event time,
budget, elapsed time when known, and the over-budget outcome.  Start and finish
records are independent immutable events; a missing start record cannot corrupt
controller state.

Telemetry persistence is best-effort at the provider/controller boundary:
the original provider or controller exception remains the primary outcome and a
write failure is surfaced as a diagnostic.

## Compatibility

The shell command keeps its argument contract during migration, but requires
the run directory or uses the existing active-run pointer.  It must fail rather
than create a fallback `.specify/squad/state.json` location.  Existing run state
is not migrated because it is not authoritative telemetry.

## Verification

Tests demonstrate that lifecycle events survive a later full replacement of
`state.json`, verify start and finish event fields, and prove the shell shim does
not mutate state.  Existing execution-span tests remain green.
