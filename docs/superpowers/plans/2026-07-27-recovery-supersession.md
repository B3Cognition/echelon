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

- [ ] Add an executor block regression starting with stale controller-contract metadata.
- [ ] Assert the newer block removes `controller_contract_error`, replaces `recovery_instruction`, and preserves `phase_output_recovery`.
- [ ] Add a legacy-state classifier regression with stale contract instruction plus valid missing-output evidence.
- [ ] Assert status and continue select `missing_phase_outputs` and `phase1-what`, not runtime sync or issue repair.
- [ ] Run focused tests and verify current failures.

### Task 2: Atomic Supersession and Typed Recovery

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/recovery_instruction.py`

**Interfaces:**
- Produces: `trusted_executor_block_recovery(phase, reason_code) -> RecoveryInstruction`.
- Consumes: existing snapshot-backed `_block_after_executor_failure`.

- [ ] Add the narrow trusted-executor recovery factory.
- [ ] Pass the typed instruction when consuming `ExecutorBlockedResult`.
- [ ] Remove stale controller diagnostics and replace recovery state before snapshot commit.
- [ ] Run controller-focused tests.

### Task 3: Consistent CLI Consumption

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_next_step_escalation.py`

**Interfaces:**
- Consumes: validated current instruction or read-only legacy evidence.
- Produces: one `_RunRecoveryAction` shared by status, next-step rendering, and continue.

- [ ] Reconcile known legacy missing-output evidence before stale instruction execution.
- [ ] Fail unknown instruction/reason mismatches closed.
- [ ] Prevent the issue-repair fast path from bypassing a current typed instruction.
- [ ] Run complete CLI recovery tests.

### Task 4: Verification and Installation

**Files:**
- No source additions.

**Interfaces:**
- Consumes: completed source and active `md_distribution` state.
- Produces: installed CLI that renders the active block as missing-output recovery.

- [ ] Run focused executor/controller and CLI suites.
- [ ] Run the full Python suite.
- [ ] Install from the feature worktree.
- [ ] Run read-only `echelon spec status` and confirm the active reason and phase.
- [ ] Commit and integrate through the normal branch workflow.
