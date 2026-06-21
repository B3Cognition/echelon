# Executable Escalation Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make escalation recommendations executable by validating structured resume options, then reconcile status so stale blockers do not override current state.

**Architecture:** Store machine-readable escalation options in squad state, resolve `echelon resume` answers against those options, and force every routed option through the phase graph before continuing. Reject text-only escalations because they are not executable. Update next-step selection to prefer active blocked state over stale artifact blockers.

**Tech Stack:** Python CLI, pytest unit tests, existing `echelon.cli`, `harness.phase_graph`, and squad state JSON.

---

### Task 1: Resume Structured Escalation Options

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_resume_escalation_options.py`

- [ ] **Step 1: Write failing tests**

Create tests that set up a blocked squad run with `escalation_options`, call `_cmd_resume(["A"], ...)`, and assert the state phase becomes `phase1-what`. Add a second test where `next_phase` is invalid and assert the run remains blocked.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/test_cli_resume_escalation_options.py -q`

Expected: tests fail because `_cmd_resume` ignores `escalation_options`.

- [ ] **Step 3: Implement option resolution**

Add helpers in `src/echelon/cli.py`:

- `_resolve_escalation_option(answer, options)`
- `_apply_resume_option(state, selected, graph)`

Support A/B/C positions, exact option ids, and exact labels. Validate `next_phase` against `PhaseGraph.all_phase_ids()`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/unit/test_cli_resume_escalation_options.py -q`

Expected: pass.

### Task 2: Status Current-State Precedence

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_next_step_escalation.py`

- [ ] **Step 1: Write failing test**

Add a test with stale failing `quality-gates.md`, completed planning artifacts, and `state.json` marked `done` at `DONE`. Assert `_print_next_steps(..., "done")` does not print the stale “WHY2 quality gates FAIL -> echelon continue” blocker.

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/unit/test_cli_next_step_escalation.py::test_done_run_does_not_surface_stale_why2_blockers -q`

Expected: fail until next-step selection prioritizes current state.

- [ ] **Step 3: Implement current-state guard**

Update next-step logic so stale quality-gate blockers are suppressible when the latest squad state is `done` and the current phase is terminal or beyond the WHY phase that produced the blocker.

- [ ] **Step 4: Run targeted tests**

Run: `pytest tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_next_step_escalation.py -q`

Expected: pass.

### Task 3: Focused Regression Suite

**Files:**
- Test: existing unit tests touched above.

- [ ] **Step 1: Run related tests**

Run: `pytest tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_resume_spec_context.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_cli_status.py -q`

Expected: pass.

- [ ] **Step 2: Inspect diff**

Run: `git diff -- src/echelon/cli.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_next_step_escalation.py docs/superpowers`

Expected: only scoped changes for executable escalation options and status reconciliation.
