# Executor Block Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve controller-generated executor recovery blocks without revalidating them as provider-owned state updates.

**Architecture:** `AgentExecutor` and other internal executors return an immutable `ExecutorBlockedResult` only after provider validation when controller recovery metadata is required. `SquadController` consumes that typed envelope before normal phase-result preparation and persists it through the existing snapshot-backed blocked-state transaction.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing `SquadStateStore` routing snapshots.

## Global Constraints

- Do not broaden provider `allowed_state_updates`.
- Do not persist state directly from an executor.
- Preserve provider contract validation for ordinary and provider-blocked results.
- Internal recovery must remain snapshot-backed and deterministic.

---

### Task 1: Reproduce the Executor-to-Controller Failure

**Files:**
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: real `SquadController.run`, `AgentExecutor`, and `SquadStateStore`.
- Produces: a regression asserting the durable `missing_phase_outputs` recovery state.

- [ ] **Step 1: Add an end-to-end missing-output regression**

Create a `phase1-what` controller run whose provider returns valid
`spec_status` and `evidence_resolution_status` updates while only `spec.md`
exists. Assert that the desired durable reason is `missing_phase_outputs`, the
missing list contains `requirements-overview.md`, and no controller contract
diagnostic is present.

- [ ] **Step 2: Run the regression and verify the current ownership failure**

Run:

```bash
python -m pytest tests/integration/test_squad_controller.py -q -k executor_missing_output_uses_recovery_block
```

Expected: FAIL because the durable reason is
`controller_state_contract_validation_failed`.

### Task 2: Add Typed Executor Block Provenance

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `ExecutorBlockedResult(reason: str, result: SquadAgentResult)`.
- Consumes: `_block_after_executor_failure(phase, reason, result, snapshot=...)`.

- [ ] **Step 1: Define the immutable envelope**

Add a frozen dataclass whose constructor validates a non-empty supported reason
and a concrete `SquadAgentResult`.

- [ ] **Step 2: Wrap controller-generated executor blocks**

Return the envelope for `missing_phase_outputs`,
`invalid_evidence_inventory`, and `missing_consensus_prerequisite` after the
provider result has already passed its phase contract.

- [ ] **Step 3: Consume the envelope before provider preparation**

In both normal squad execution and manual phase replay, capture a routing
snapshot and call `_block_after_executor_failure` directly for the envelope.
Ordinary results must retain the existing preparation path.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py -q
```

Expected: PASS.

### Task 3: Verify Installation and Active Recovery

**Files:**
- No source additions.

**Interfaces:**
- Consumes: merged implementation and active `md_distribution` state.
- Produces: an installed CLI that classifies the next missing-output block
  correctly.

- [ ] **Step 1: Run the full Python suite**

Run:

```bash
python -m pytest -q
```

- [ ] **Step 2: Install from the feature worktree**

Run:

```bash
bash scripts/install.sh
```

- [ ] **Step 3: Verify recovery without dispatch**

Use an isolated copy of the active run state and recorded provider result to
verify the controller persists `missing_phase_outputs`. Do not launch the real
provider during verification.

- [ ] **Step 4: Commit and integrate**

Commit the design, implementation, and regression tests. Merge only after the
merged-result suite passes.
