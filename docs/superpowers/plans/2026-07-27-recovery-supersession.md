# Recovery Supersession Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure each new blocked state atomically supersedes stale diagnostics and routes through one matching typed recovery instruction.

**Architecture:** Trusted executor recovery writes a typed `retry_phase` instruction in the same snapshot-backed transaction as `blocked_reason` and phase-output context. CLI readers validate that instruction and reason belong to the same generation; a narrow legacy adapter reconstructs missing-output recovery from persisted controller evidence when an older stale instruction remains.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing recovery instruction and routing snapshot APIs.

## Global Constraints

- Provider allowlists remain unchanged.
- Background issue-resolution state cannot override a newer typed recovery.
- Legacy reconciliation is read-only.
- Unknown mismatches fail closed as manual diagnosis.

---

### Task 1: Recovery Generation Regressions

**Files:**
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_next_step_escalation.py`

**Interfaces:**
- Consumes: `_block_after_executor_failure`, `_classify_run_recovery`, and `_cmd_continue`.
- Produces: exact durable and rendered recovery-generation assertions.

- [x] Add an executor block regression starting with stale controller-contract metadata.
- [x] Assert the newer block removes `controller_contract_error`, replaces `recovery_instruction`, and preserves `phase_output_recovery`.
- [x] Add a legacy-state classifier regression with stale contract instruction plus valid missing-output evidence.
- [x] Assert status and continue select `missing_phase_outputs` and `phase1-what`, not runtime sync or issue repair.
- [x] Run focused tests and verify current failures.

### Task 2: Atomic Supersession and Typed Recovery

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/recovery_instruction.py`

**Interfaces:**
- Produces: `trusted_executor_block_recovery(phase, reason_code) -> RecoveryInstruction`.
- Consumes: existing snapshot-backed `_block_after_executor_failure`.

- [x] Add the narrow trusted-executor recovery factory.
- [x] Pass the typed instruction when consuming `ExecutorBlockedResult`.
- [x] Remove stale controller diagnostics and replace recovery state before snapshot commit.
- [x] Run controller-focused tests.

### Task 3: Consistent CLI Consumption

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_next_step_escalation.py`

**Interfaces:**
- Consumes: validated current instruction or read-only legacy evidence.
- Produces: one `_RunRecoveryAction` shared by status, next-step rendering, and continue.

- [x] Reconcile known legacy missing-output evidence before stale instruction execution.
- [x] Fail unknown instruction/reason mismatches closed.
- [x] Prevent the issue-repair fast path from bypassing a current typed instruction.
- [x] Run complete CLI recovery tests.

### Task 4: Verification and Installation

**Files:**
- No source additions.

**Interfaces:**
- Consumes: completed source and active `md_distribution` state.
- Produces: installed CLI that renders the active block as missing-output recovery.

- [x] Run focused executor/controller and CLI suites.
- [x] Run the full Python suite.
- [x] Install from the feature worktree.
- [x] Confirm the installed classifier repairs the legacy state, then run
  read-only `echelon spec status` against the active workspace.
- [x] Commit through the normal branch workflow.
- [x] Integrate using the selected branch-completion option.
