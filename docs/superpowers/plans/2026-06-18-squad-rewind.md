# Squad Rewind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe `echelon rewind <phase>` command that rewinds only vetted Phase 3 checkpoints and prepares the current squad run for `echelon continue`.

**Architecture:** Implement rewind as a pure Python CLI flow in `src/echelon/cli.py` with explicit per-phase preflight checks, canonical `spec_dir` normalization, target/downstream artifact cleanup, and minimal `state.json` rewrites. Keep v1 narrowly scoped to `phase3-how`, `phase3-sentinel`, and `phase3-plan`.

**Tech Stack:** Python CLI, existing squad state files, pytest unit tests

---

### Task 1: Add Rewind CLI Tests

**Files:**
- Create: `tests/unit/test_cli_rewind.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_rewind.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the rewind test file to verify the new tests fail**
- [ ] **Step 3: Implement minimal CLI rewind behavior**
- [ ] **Step 4: Re-run rewind tests and fix state/artifact edge cases**
- [ ] **Step 5: Commit**

### Task 2: Wire Command Help And Dispatch

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_rewind.py`

- [ ] **Step 1: Add `rewind` to CLI usage and command dispatch**
- [ ] **Step 2: Verify unsupported phases fail with a clear message**
- [ ] **Step 3: Verify missing inputs fail with phase-specific guidance**
- [ ] **Step 4: Commit**

### Task 3: Verify Rewind End To End

**Files:**
- Modify: `tests/unit/test_cli_rewind.py`
- Test: `tests/unit/test_cli_rewind.py`, `tests/unit/test_cli_continue.py`

- [ ] **Step 1: Run targeted CLI tests**
- [ ] **Step 2: Confirm rewind leaves `echelon continue` as the explicit next step**
- [ ] **Step 3: Commit**
