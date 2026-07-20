# Spec Execution Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture every Spec provider dispatch in shared content-free telemetry, analyze Spec runs from one hidden CLI command, and render Spec operations in the optional run wiki.

**Architecture:** Add a contextual provider decorator at the shared Spec dispatch boundary and persist one trace identity in Spec run state. Add a Spec analysis adapter with a workflow-neutral metrics extension, then route both RE and Spec reports through CLI and wiki rendering without changing canonical publication artifacts.

**Tech Stack:** Python 3.11+, dataclasses, JSON/JSONL, existing `TelemetryStore`, Typer, pytest.

## Global Constraints

- Store no prompts, responses, source content, or artifact bodies.
- Every provider dispatch produces exactly one span, including exceptions.
- Continue, resume, and manual phase replay reuse the original trace.
- Unknown token usage remains unknown rather than zero.
- Existing Spec and RE runs remain analyzable.
- `echelon spec analyze` accepts one path locator, not path plus run ID.
- Telemetry is local and never part of canonical Spec publication.

---

### Task 1: Contextual Spec telemetry provider

**Files:**
- Create: `src/echelon/telemetry/provider.py`
- Test: `tests/unit/test_spec_telemetry_provider.py`

**Interfaces:**
- Produces: `DispatchContext(phase, agent, kind, attempt)`.
- Produces: `InstrumentedProvider(provider, store)` with `dispatch(context)` context manager and `exec_agent(project_root, prompt)`.

- [ ] Write failing tests proving one successful call emits one content-free span with provider/model/tokens and a raised call emits one error span.
- [ ] Run `.venv/bin/pytest -q tests/unit/test_spec_telemetry_provider.py` and confirm failure because the module is absent.
- [ ] Implement the minimal decorator using `contextvars.ContextVar`, `ExecutionSpan`, and `TelemetryStore`.
- [ ] Verify the focused tests pass and commit.

### Task 2: Persist trace identity and instrument all Spec dispatch paths

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/state.py`
- Test: `tests/unit/test_squad_spec_telemetry.py`

**Interfaces:**
- Consumes: `InstrumentedProvider.dispatch(context)`.
- Produces: `telemetry_trace_id` in run state and append-only `telemetry/spans.jsonl`.

- [ ] Write failing tests for normal phase, COMMANDER judgment, escalation, repair attribution, and trace reuse after controller reconstruction.
- [ ] Run the tests and confirm no Spec spans are emitted.
- [ ] Initialize a UUID trace once, decorate the provider once, and put dispatch contexts around every controller/executor provider call.
- [ ] Ensure nested paths do not double-wrap or double-count.
- [ ] Verify focused Squad tests and commit.

### Task 3: Spec analysis adapter and metrics

**Files:**
- Modify: `src/echelon/telemetry/analyzer.py`
- Create: `src/echelon/telemetry/spec_adapter.py`
- Modify: `src/echelon/telemetry/render.py`
- Test: `tests/unit/test_spec_run_analyzer.py`

**Interfaces:**
- Produces: `WorkflowMetrics` extension on `RunAnalysis`.
- Produces: `analyze_spec_run(path)` and `analyze_spec_runs(path)`.

- [ ] Write failing fixtures covering phase/agent/model aggregation, unknown tokens, repair loops, repeated blockers, acceptance cost, malformed JSONL, and state-only fallback.
- [ ] Run focused tests and confirm imports/fields fail.
- [ ] Implement aggregation without interpreting missing data as zero.
- [ ] Extend text and JSON rendering while preserving RE output compatibility.
- [ ] Verify analyzer and existing RE analyzer tests and commit.

### Task 4: Hidden `echelon spec analyze`

**Files:**
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_spec_analyze.py`

**Interfaces:**
- Consumes: `analyze_spec_run`, `analyze_spec_runs`, shared renderers.
- Produces: hidden `spec analyze [PATH] [--format text|json]`.

- [ ] Write failing CLI tests for hidden help, one run, a runs directory, JSON output, and unsafe/non-Spec paths.
- [ ] Run tests and confirm the command is absent.
- [ ] Implement one-path resolution with no second run-ID parameter.
- [ ] Verify CLI tests and commit.

### Task 5: Spec operations wiki

**Files:**
- Modify: `src/echelon/wiki/operations.py`
- Modify: `src/echelon/wiki/service.py`
- Test: `tests/unit/test_wiki_operations.py`

**Interfaces:**
- Consumes: both workflow adapters.
- Produces: Spec run pages plus performance, tokens, repair loops, blockers, and model views.

- [ ] Write failing wiki tests with one RE run and one Spec run, asserting local pages and no raw span content.
- [ ] Run tests and confirm only RE is rendered.
- [ ] Generalize operations rendering by workflow and add Spec views.
- [ ] Verify wiki and RE regression tests and commit.

### Task 6: End-to-end verification and installation

**Files:**
- Modify: `docs/reference/cli.md` or the repository's existing CLI reference if present.

**Interfaces:**
- Verifies all earlier interfaces together.

- [ ] Document hidden analysis invocation, stored fields, privacy boundary, and wiki opt-in.
- [ ] Run `git diff --check` and all focused telemetry, Squad, CLI, wiki, and RE regression tests.
- [ ] Run the full pytest suite and distinguish pre-existing failures from regressions.
- [ ] Install the local CLI with `bash scripts/install.sh` and smoke-test `echelon spec analyze --help` through direct command invocation.
- [ ] Commit documentation and any final integration corrections.
