# Python-Owned Lifecycle Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lifecycle timing append-only Python telemetry so controller state writes cannot delete it.

**Architecture:** Add a lifecycle-event writer beside `TelemetryStore` and use it for phase start/finish records. Convert the compatibility phase-timing entry point to invoke Python without mutating `state.json`.

**Tech Stack:** Python 3.11+, JSON/JSONL, Typer/standard library CLI, Bash compatibility shim, pytest.

## Global Constraints

- `state.json` remains controller lifecycle state only.
- Telemetry is content-free and append-only under `run_dir/telemetry/`.
- Preserve existing user worktree modifications outside this scope.

---

### Task 1: Add append-only lifecycle events

**Files:**
- Create: `src/echelon/telemetry/lifecycle.py`
- Modify: `src/echelon/telemetry/store.py`
- Test: `tests/unit/test_execution_telemetry.py`

**Produces:** `TelemetryStore.append_lifecycle_event(...)` and a typed,
validated phase-timing event.

- [ ] Write a test that appends phase-start and phase-finish events, replaces
  `state.json` afterwards, and asserts both events remain under `telemetry/`.
- [ ] Run the focused test and confirm it fails before lifecycle support exists.
- [ ] Add the minimal Python event writer and event validation.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Migrate phase-timing compatibility entry point

**Files:**
- Modify: `.specify/extensions/echelon/scripts/bash/phase-timing.sh`
- Modify: `.specify/extensions/echelon/workflow/phases/*.md`
- Test: `tests/unit/test-phase-timing.sh`

**Produces:** Phase timing that records append-only lifecycle events and does
not read or write `state.json`.

- [ ] Write a failing shell regression test proving phase timing leaves a
  sentinel `state.json` byte-for-byte unchanged.
- [ ] Run it and confirm the existing script fails that assertion.
- [ ] Replace state mutation with a Python lifecycle invocation; preserve the
  phase and budget command contract.
- [ ] Re-run the shell test and confirm it passes.

### Task 3: Preserve primary errors and verify migration

**Files:**
- Modify: `src/echelon/telemetry/provider.py`
- Test: `tests/unit/test_spec_telemetry_provider.py`

**Produces:** Provider failures that remain primary if telemetry append fails.

- [ ] Write a failing test using a store whose append raises while the provider
  also raises; assert the provider exception is propagated.
- [ ] Run it and confirm the current `finally` behavior masks the provider
  exception.
- [ ] Guard telemetry persistence and record a secondary diagnostic.
- [ ] Run focused telemetry tests and the full relevant suite.
