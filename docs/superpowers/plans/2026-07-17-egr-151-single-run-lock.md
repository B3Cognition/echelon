# EGR-151 Single-Run Execution Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permit exactly one Phase A controller execution against the shared
authoring checkout at a time, while preserving per-run duplicate protection and
allowing lifecycle operations once the active controller has stopped.

**Architecture:** Reuse EGR-151's atomic, PID-owned directory-lock semantics
for a workspace Phase A execution lease at `.echelon/runtime/` and a run-local
lease at `runs/<id>/.echelon/runtime/`. The controller acquires both before
reading or mutating state, holds them through every provider dispatch, and
returns a deterministic `busy` result when a live owner exists. New-spec and
existing-spec checkout transitions take the workspace execution lease while
holding the short-lived lifecycle mutation lock, so they cannot move the shared
checkout underneath a live controller.

**Tech Stack:** Python 3.11+, `pathlib`, atomic directory creation, pytest.

## Global Constraints

- The workspace execution lock serializes active controller ownership of the
  one shared checkout; it must not block delivery or inactive-run inspection.
- The run-local lease records and rejects duplicate execution for the exact run.
- A live lock owner fails closed before any state change or provider dispatch.
- A dead local PID is recoverable; a remote or malformed owner fails closed.
- Full and manual Phase A controller execution share the same lock.
- Tests use no LLM, Docker, or network access.

---

### Task 1: Run-local execution lease

**Files:**
- Modify: `src/echelon/spec_lifecycle.py`
- Test: `tests/unit/test_spec_lifecycle.py`

**Interfaces:**
- Produces `SpecRunExecutionLock.acquire(run_dir: Path, operation_id: str)`.
- Raises the existing `SpecLifecycleLocked` and
  `SpecLifecycleRecoveryRequired` errors with the same PID/hostname ownership
  rules as `SpecLifecycleLock`.

- [x] **Step 1: Write failing lock-scope tests**

```python
def test_run_execution_lock_refuses_second_live_owner(tmp_path: Path):
    run = tmp_path / "runs" / "run-a"
    first = SpecRunExecutionLock.acquire(run, "run-a-owner")
    with pytest.raises(SpecLifecycleLocked):
        SpecRunExecutionLock.acquire(run, "run-a-second")
    first.release()
```

Add a sibling-run test proving `run-a` and `run-b` can be locked together.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/test_spec_lifecycle.py -q`

Expected: import or attribute failure for `SpecRunExecutionLock`.

- [x] **Step 3: Implement the run-local lease**

Use the same atomic directory owner protocol as `SpecLifecycleLock`, but place
the lock at `<run_dir>/.echelon/runtime/execution.lock`. Validate the operation
id, recover only a dead local owner, and require the releasing owner id to
match.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/unit/test_spec_lifecycle.py -q`

Expected: PASS.

### Task 2: Guard all controller execution paths

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/unit/test_squad_execution_lock.py`

**Interfaces:**
- `SquadController.run(...)` and `SquadController.run_single_phase(...)` return
  `SquadResult(status="busy", phase=<current>, run_id=<id>)` when the run lease
  is live.
- Neither path dispatches a provider or modifies `state.json` when busy.

- [x] **Step 1: Write failing controller tests**

```python
def test_run_refuses_a_live_execution_owner(monkeypatch, controller, store):
    lock = SpecRunExecutionLock.acquire(store.squad_dir, "other-owner")
    result = controller.run(user_message="demo")
    assert result.status == "busy"
    controller._provider.exec_agent.assert_not_called()
    lock.release()
```

Repeat for `run_single_phase` and compare `state.json` before/after.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/test_squad_execution_lock.py -q`

Expected: controller dispatches or returns another status.

- [x] **Step 3: Implement a lock wrapper**

Keep the existing bodies as private locked methods. Each public entrypoint
acquires `SpecRunExecutionLock` before initialization/recovery, calls its
private body while the lease is held, and converts only a live-owner error into
the deterministic `busy` result. Other lifecycle failures must still surface.

- [x] **Step 4: Verify GREEN and lifecycle regression**

Run:

```bash
pytest tests/unit/test_squad_execution_lock.py \
  tests/unit/test_spec_lifecycle.py \
  tests/unit/test_phase_a_start.py \
  tests/unit/test_spec_switch.py \
  tests/integration/test_egr_151_lifecycle_flow.py -q
git diff --check
```

Expected: PASS with no whitespace errors.

### Task 3: Prevent active execution from changing the shared checkout

**Files:**
- Modify: `src/echelon/phase_a_start.py`
- Modify: `src/echelon/spec_switch.py`
- Test: `tests/unit/test_phase_a_start.py`
- Test: `tests/unit/test_spec_switch.py`

- [x] **Step 1: Write failing real-Git lifecycle tests**

Acquire the workspace Phase A execution lease, then prove a fresh start and an
existing-run switch both leave the active branch and `runs/.current` unchanged.

- [x] **Step 2: Implement the workspace execution lease**

Controllers acquire the workspace lease before their run-local lease. Fresh
starts and switches acquire it while holding the lifecycle mutation lock.

- [x] **Step 3: Verify lifecycle regression**

Run the lock, Phase A start, and spec switch unit suites against temporary Git
repositories. Result: `65 passed` on 2026-07-17.

### Task 4: Close the EGR evidence honestly

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Record the execution-lease guarantee and test evidence**

Mark EGR-151 `fixed` only after Tasks 1 and 2 pass. Replace stale remaining-work
text with the exact focused matrix result. Keep the landing-worktree item as a
separate future refinement, not an EGR-151 blocker.

- [x] **Step 2: Run the recorded EGR matrix and commit**

```bash
pytest tests/unit/test_speckit_git.py tests/unit/test_phase_a_git.py \
  tests/unit/test_phase_a_start.py tests/unit/test_spec_lifecycle.py \
  tests/unit/test_spec_switch.py tests/unit/test_spec_switch_cli.py \
  tests/unit/test_squad_execution_lock.py \
  tests/integration/test_egr_151_lifecycle_flow.py -q
git diff --check
```

The final no-LLM EGR matrix passed **222 tests** on 2026-07-17. Commit only the
EGR-151 implementation, tests, plan, and evidence with
`git commit -m "fix: serialize phase a run execution"`.

## Self-Review

- The workspace lease prevents a live controller from losing the shared
  checkout, while the run-local lease closes duplicate dispatch for the exact
  run.
- The controller guard covers both normal resume and manual replay.
- No automatic process termination, state reset, or pointer mutation occurs
  when a live owner is found.

## Execution Handoff

The user requested continued implementation, so execute this plan inline with
test-first checkpoints rather than pausing for an execution-mode choice.
