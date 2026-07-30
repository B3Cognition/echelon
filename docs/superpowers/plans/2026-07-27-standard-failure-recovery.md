# Standard Failure Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and consume one typed recovery instruction for blocked controller failures so status and continue agree without guessing from prose reasons.

**Architecture:** A focused `harness.recovery_instruction` module owns the versioned recovery vocabulary and validation, separate from the existing delivery/build salvage module. Controller failure transactions persist an instruction beside their diagnostic; the CLI consumes that instruction first and uses its existing heuristics only as a legacy adapter.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing Echelon state transaction and extension-drift APIs.

## Global Constraints

- Provider results cannot write `recovery_instruction`.
- Unknown recovery state defaults to `manual_diagnosis`.
- Runtime reconciliation must not rewind artifacts or dispatch while required extension files differ.
- Existing blocked runs without an instruction remain recoverable.

---

### Task 1: Typed Recovery Instruction

**Files:**
- Create: `src/harness/recovery_instruction.py`
- Modify: `src/harness/state_transaction_namespace.py`
- Test: `tests/unit/test_recovery.py`

**Interfaces:**
- Produces: `RecoveryInstruction`, `RecoveryKind`, `validate_recovery_instruction(value)`, and `controller_contract_recovery(phase)`.
- Consumes: no controller or CLI modules; it does not depend on the existing
  `harness.recovery` delivery/build salvage module.

- [x] **Step 1: Write failing tests for valid, malformed, and controller-contract recovery instructions**

Assert literal canonical dictionaries and rejection of unknown kinds, empty
phases, and human-input mismatches.

- [x] **Step 2: Run the focused tests and verify they fail because `harness.recovery_instruction` does not exist**

Run: `python -m pytest tests/unit/test_recovery.py -q`

- [x] **Step 3: Implement the minimal enum, immutable instruction, serializer, and validator**

The controller-contract factory returns schema version 1,
`sync_runtime_then_retry`, the rejected phase, and
`requires_human_input=False`.

- [x] **Step 4: Mark `recovery_instruction` transaction-owned and run focused tests**

Run: `python -m pytest tests/unit/test_recovery.py -q`

### Task 2: Atomic Controller Failure Recovery

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: `controller_contract_recovery(phase).to_dict()`.
- Produces: blocked controller failures with an atomic
  `recovery_instruction`; successful state advances remove stale instructions.

- [x] **Step 1: Extend the existing controller-contract failure test to require the typed instruction**

The assertion must inspect persisted real state, not a mock.

- [x] **Step 2: Run the test and verify the missing instruction failure**

Run: `python -m pytest tests/integration/test_squad_controller.py -q -k 'controller_contract and recovery_instruction'`

- [x] **Step 3: Persist the instruction in `_block_after_state_advance_failure` and clear it on successful advance**

Only controller contract validation failures receive the runtime-sync action;
other producers retain legacy behavior until they emit their own typed action.

- [x] **Step 4: Run the controller-focused tests**

Run: `python -m pytest tests/integration/test_squad_controller.py -q -k 'controller_contract or recovery_instruction'`

### Task 3: Unified CLI Consumption

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_continue.py`
- Test: `tests/unit/test_cli_next_step_escalation.py`

**Interfaces:**
- Consumes: validated `recovery_instruction` or a read-only legacy adapter.
- Produces: `_RunRecoveryAction` with `sync_runtime_then_retry` semantics;
  `status` and `continue` render the same action.

- [x] **Step 1: Write failing classification and continue tests**

Use the real active-state shape: current phase `phase1-why2`, stale
`last_dispatch.phase_id=phase1-understanding`, and no escalation question.
Assert that the retry phase is `phase1-why2`, `continue` is shown, and rewind
and resume are absent.

- [x] **Step 2: Run focused tests and verify the action is currently `manual_recovery`**

Run: `python -m pytest tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py -q -k 'controller_contract_recovery'`

- [x] **Step 3: Add typed-instruction consumption and legacy adaptation**

Prefer the persisted instruction. For legacy controller-contract blocks,
synthesize `sync_runtime_then_retry` from the current phase. Keep unknown
reasons as `manual_diagnosis`.

- [x] **Step 4: Add runtime compatibility eligibility**

Use the existing extension drift report. Changed or missing source files block
with the exact extension-update command; extra files do not block. Compatible
runtime converts the action to a phase retry.

- [x] **Step 5: Run focused CLI tests**

Run: `python -m pytest tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py -q`

### Task 4: Installation and Active-Run Verification

**Files:**
- No source additions.

**Interfaces:**
- Consumes: completed implementation and active `md_distribution` state.
- Produces: installed CLI whose read-only recovery classification selects
  `phase1-why2`.

- [x] **Step 1: Run the combined regression suite**

Run: `python -m pytest tests/unit/test_recovery.py tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py tests/integration/test_squad_controller.py -q`

- [x] **Step 2: Install the worktree build**

Run: `bash scripts/install.sh`

- [x] **Step 3: Verify active status without provider dispatch**

Run `echelon spec status` in `md_distribution` and confirm its next command is
`echelon spec continue`, phase is `phase1-why2`, and neither resume nor rewind
is suggested.

- [x] **Step 4: Commit the implementation**

Commit the design, plan, source, and tests as one reviewed recovery protocol
change.
