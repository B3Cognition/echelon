# Harness Salvage Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve useful harness build work automatically when COMMANDER exits without writing `.harness-build-status.json`, and make recovery/status point to the preserved commit.

**Architecture:** Add a small salvage helper near Ralph so build-loop failure handling can commit dirty harness worktrees before blocking. Store `salvage_commit`, `salvage_branch`, and `salvage_verified` in harness state, then have recovery and status consume those fields.

**Tech Stack:** Python 3.11, existing git CLI helper `_run_git`, pytest unit tests.

---

### Task 1: Auto-Commit Salvage On Build Incomplete

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [ ] Write a failing test where an LLM build returns `unknown`, the worktree has tracked/untracked changes, and state receives `salvage_commit`.
- [ ] Run focused pytest and confirm failure.
- [ ] Implement `_salvage_build_worktree()` using git status/add/commit on the harness worktree.
- [ ] Store salvage metadata through `_finalize()`.
- [ ] Run focused pytest and confirm pass.

### Task 2: Recovery Uses Salvage Commit

**Files:**
- Modify: `src/harness/recovery.py`
- Test: `tests/unit/test_harness_recovery.py`

- [ ] Write a failing test where state includes `salvage_commit` and recovery locates it from the preserved worktree.
- [ ] Run focused pytest and confirm failure.
- [ ] Use `state["salvage_commit"]` before scanning logs.
- [ ] Keep conservative dirty-main protection.
- [ ] Run focused pytest and confirm pass.

### Task 3: Status Shows Salvage State Clearly

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_status.py`

- [ ] Write a failing test that blocked harness state with `salvage_commit` prints the salvage commit and dirty-checkout prerequisite.
- [ ] Run focused pytest and confirm failure.
- [ ] Add salvage fields to `_print_next_steps()`.
- [ ] Run focused pytest and confirm pass.

### Task 4: Full Verification

**Files:**
- No new source files.

- [ ] Run `python -m pytest tests/unit -q`.
- [ ] Re-run `echelon status` in NavigationalPortal with the local checkout and confirm it reports the salvage commit and the dirty checkout blocker.
