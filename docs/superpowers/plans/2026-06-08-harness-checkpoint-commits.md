# Harness Checkpoint Commits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce recovery and cherry-pick risk by committing harness progress at deterministic checkpoints before the final publish commit.

**Architecture:** Stage 1 keeps the current default and SOAR execution engines intact. Ralph commits checkpoint slices at harness-observable boundaries when build progress advances and the worktree is dirty, recording task IDs when known and phase/wave metadata otherwise. Stage 2 will move Ralph to a full task-invocation orchestrator that owns task selection, gates, commits, and state updates per task.

**Tech Stack:** Python harness orchestration, git CLI through existing GitOpsManager, JSON harness state.

---

### Task 1: Add Checkpoint Metadata And Commit Primitive

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [x] **Step 1: Write failing tests**

Add tests covering:

```python
def test_checkpoint_commit_records_task_progress_delta(tmp_path):
    ...

def test_checkpoint_commit_uses_phase_when_task_ids_unknown(tmp_path):
    ...

def test_checkpoint_commit_skips_when_no_file_changes(tmp_path):
    ...
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env-status-fix uv run --project /Users/michalbachorik/work/echelon_r/echelon --extra dev python -m pytest /Users/michalbachorik/work/echelon_r/echelon/tests/unit/test_ralph_outer.py -k checkpoint_commit -q
```

Expected: FAIL because `_checkpoint_progress_commit` does not exist.

- [x] **Step 3: Implement minimal checkpoint primitive**

Add `_checkpoint_progress_commit()` and `_newly_completed_task_ids()` in `src/harness/ralph.py`. The primitive:

- checks `build.completed_tasks` progress or phase context,
- skips when the worktree is not dirty,
- commits with `harness-checkpoint: <spec>/<strategy> iter-<n> <phase> <phase_group> <task_ids|tasks-unknown>`,
- appends metadata to `state["checkpoint_commits"]`.

- [x] **Step 4: Run test to verify it passes**

Expected: PASS.

### Task 2: Wire Checkpoints Into Ralph Boundaries

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [x] **Step 1: Write failing loop test**

Add `test_run_loop_checkpoints_after_successful_build_progress()`.

- [x] **Step 2: Run test to verify it fails**

Expected: FAIL because Ralph does not call the checkpoint primitive after build.

- [x] **Step 3: Wire build/fix boundaries**

Capture state before build/fix invocations and call `_try_checkpoint_progress_commit()` after each invocation. The wrapper logs checkpoint failures and continues so checkpointing does not become a new build blocker.

- [x] **Step 4: Run test to verify it passes**

Expected: PASS.

### Task 3: Prefer Checkpoints During Recovery

**Files:**
- Modify: `src/harness/recovery.py`
- Test: `tests/unit/test_harness_recovery.py`

- [x] **Step 1: Write failing recovery test**

Add `test_recover_blocked_run_prefers_checkpoint_commit_over_salvage()`.

- [x] **Step 2: Run test to verify it fails**

Expected: FAIL because recovery currently chooses `salvage_commit`.

- [x] **Step 3: Implement checkpoint preference**

Update preserved-worktree recovery to choose the newest existing `state["checkpoint_commits"][].commit` before `salvage_commit`.

- [x] **Step 4: Run tests**

Expected focused harness tests pass.

### Stage 2 Follow-Up

Stage 2 should replace build-as-one-blob with Ralph-owned task invocation:

1. Select next task or wave deterministically from tasks/state.
2. Invoke the selected execution engine for only that scope.
3. Run gates.
4. Commit exactly that task/wave.
5. Update state.
6. Repeat.

This plan intentionally leaves Stage 2 out of scope.
