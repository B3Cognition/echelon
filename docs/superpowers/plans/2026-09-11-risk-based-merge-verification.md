# Risk-Based Merge Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avoid redundant post-fast-forward full-suite runs while preserving a conservative, auditable verification gate for Echelon changes.

**Architecture:** A repository-local Python helper derives a verification plan from the Git diff, executes only explicitly approved focused suites or the existing full-unit suite, and stores a local ignored receipt bound to the tested commit and tree. After a fast-forward merge, the helper validates that same receipt against `HEAD`; any changed tree, missing receipt, non-fast-forward integration, or unknown path fails closed to the existing full-unit command.

**Tech Stack:** Python 3.11+, pytest, Git, existing `tests/reports/` ignored output directory.

**Spec:** User-approved test-suite audit, 2026-09-11.

## Global Constraints

- Preserve `pytest -q -m unit` as the conservative fallback.
- Do not make test selection depend on Python import tracing or ambient coverage state.
- Do not create tracked or untracked working-tree noise; receipts belong in ignored `tests/reports/`.
- A receipt proves one exact Git tree only; it cannot authorize a merge commit or changed candidate.

---

### Task 1: Deterministic verification planning and receipt model

**Files:**
- Create: `scripts/merge_verification.py`
- Test: `tests/unit/test_merge_verification.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `git diff --name-only <base>...<head>`.
- Produces: JSON plan with `scope`, `commands`, `base_commit`, `candidate_commit`, `candidate_tree`, and changed paths.

- [x] **Step 1: Write failing tests** for a CLI-only changed surface selecting focused CLI tests, and an unknown/shared surface selecting the full unit command.
- [x] **Step 2: Run those tests** and confirm the helper module is absent.
- [x] **Step 3: Implement the smallest immutable plan/receipt types and conservative classifier.**
- [x] **Step 4: Re-run focused tests.**

### Task 2: Execute and validate merge evidence

**Files:**
- Modify: `scripts/merge_verification.py`
- Modify: `tests/unit/test_merge_verification.py`

**Interfaces:**
- `run --base <sha> [--head <sha>]` writes one receipt beneath `tests/reports/merge-verification/`.
- `confirm-fast-forward --receipt <path>` succeeds only when `HEAD` and its tree match the receipt’s candidate commit and tree.

- [x] **Step 1: Write failing tests** for a successful bound receipt and rejection after a changed `HEAD`.
- [x] **Step 2: Run those tests** and confirm receipt validation is unavailable.
- [x] **Step 3: Ignore `tests/reports/merge-verification/` while retaining the tracked report placeholder, then implement atomic receipt writing and exact Git identity validation.**
- [x] **Step 4: Re-run focused tests.**

### Task 3: Document the merge workflow

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Test: `tests/unit/test_merge_verification.py`

- [x] **Step 1: Add a test that documents the plan’s full-suite fallback command.**
- [x] **Step 2: Add concise contributor commands for plan, run, and fast-forward confirmation.**
- [x] **Step 3: Re-run focused verification and `bash scripts/bash/dry-run.sh`.**

### Task 4: Verify the integration boundary

**Files:**
- Test: `tests/unit/test_merge_verification.py`

- [x] **Step 1: Run the focused helper tests and the affected CLI/wiring tests.**
- [x] **Step 2: Run the full unit suite once before merging, if the host baseline is healthy; otherwise record exact environmental failures separately.**
- [x] **Step 3: Verify fast-forward receipt confirmation through an exact commit/tree unit contract rather than repeating the full suite.**
