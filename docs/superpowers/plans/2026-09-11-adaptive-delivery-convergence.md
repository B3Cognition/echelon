# Adaptive Delivery Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw outer-index exhaustion with a persisted, evidence-based convergence lease that continues productive delivery and stops verified churn.

**Architecture:** A focused `harness.convergence` module owns serializable progress snapshots and lease transitions. `RalphController` observes only completed authoritative outer verification, persists the lease, and uses meaningful attempts for the hard ceiling while retaining `outer_iter` as execution provenance. Existing mode, inner-loop, infrastructure, token, and publication behavior remains in place.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing Echelon state/CLI/UI helpers.

**Spec:** `docs/superpowers/specs/2026-09-11-adaptive-delivery-convergence-design.md`

## Global Constraints

- Default meaningful outer ceiling is 12; explicit `--max-outer` remains authoritative.
- Default `max_inner` remains 3.
- Stall termination requires at least 3 meaningful observations and 2 consecutive non-improving observations.
- Only authoritative verification observations consume the meaningful-attempt allowance.
- Provider, sandbox, guided-pause, cancellation, and publication outcomes do not consume it.
- Modes retain their existing boundary and escalation semantics.
- Raw failure content must not be copied into convergence telemetry.

---

### Task 1: Deterministic convergence policy

**Files:**
- Create: `src/harness/convergence.py`
- Create: `tests/unit/test_convergence.py`

**Interfaces:**
- Produces: `ProgressSnapshot.from_verify_result(...)`, `ConvergenceLease.from_state(...)`, `ConvergenceLease.observe(...)`, and JSON-safe `to_state()` values.
- Consumes: `VerifyResult`, canonical task counts, product fingerprint, and checkpoint commit supplied by Ralph.

- [ ] **Step 1: Write failing snapshot and comparison tests**

Cover literal fixtures for initial baseline, task progress, fulfillment debt reduction, stable failure reduction, later-gate progress, fingerprint-only churn, regression, patience exhaustion, and legacy empty state. Each test must name the incorrect classifier mutation it catches.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `../../.venv/bin/pytest -q tests/unit/test_convergence.py`

Expected: collection fails because `harness.convergence` does not exist.

- [ ] **Step 3: Implement the minimal pure policy module**

Use immutable snapshots, stable JSON serialization, explicit status weights, and a `LeaseObservation` result containing `outcome`, `reason`, `should_stop`, and the updated lease. Do not inspect the filesystem or mutate controller state in this module.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `../../.venv/bin/pytest -q tests/unit/test_convergence.py`

Expected: all policy tests pass.

- [ ] **Step 5: Commit the policy unit**

```bash
git add src/harness/convergence.py tests/unit/test_convergence.py
git commit -m "feat: add delivery convergence lease policy"
```

### Task 2: Ralph accounting and termination

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/state.py`
- Modify: `tests/unit/test_ralph_outer.py`
- Modify: `tests/e2e/test_ralph_resume.py`

**Interfaces:**
- Consumes: Task 1 policy types.
- Produces: persisted `convergence_lease`, meaningful-attempt loop ceiling, `convergence_stalled` termination, and high-water context for the next repair prompt.

- [ ] **Step 1: Write failing controller tests**

Add tests proving infrastructure-only exits do not charge the lease, equivalent authoritative outer results stop after patience, a later improvement resets patience and proceeds beyond raw outer index five, and resume preserves lease state. Exercise real state serialization and the controller loop; mock only provider/external execution.

- [ ] **Step 2: Run each new test and verify RED**

Run each new node with `../../.venv/bin/pytest -q <node-id>` and confirm it fails because the lease is absent or the old raw-index cap stops delivery.

- [ ] **Step 3: Integrate observation at the outer verification boundary**

Build snapshots from `VerifyResult.details`, `_task_progress_counts()`, `_safe_product_evidence_fingerprint()`, and the latest checkpoint. Persist after each comparable failed outer result. Replace `range(start_outer, max_outer)` with a loop bounded by `meaningful_attempts`, retaining monotonically increasing execution ordinals.

- [ ] **Step 4: Add deterministic stall finalization and high-water prompt context**

Return `convergence_stalled` after patience is exhausted, without invoking human clarification in banzai. Render the best snapshot/checkpoint as bounded controller context for the next repair; do not reset or rewrite branch history.

- [ ] **Step 5: Run controller and resume tests and verify GREEN**

Run: `../../.venv/bin/pytest -q tests/unit/test_ralph_outer.py tests/e2e/test_ralph_resume.py`

Expected: all tests pass.

- [ ] **Step 6: Commit controller integration**

```bash
git add src/harness/ralph.py src/harness/state.py tests/unit/test_ralph_outer.py tests/e2e/test_ralph_resume.py
git commit -m "feat: drive delivery by meaningful convergence attempts"
```

### Task 3: Defaults, status, summaries, and telemetry

**Files:**
- Modify: `src/harness/run_intent.py`
- Modify: `src/harness/state.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/harness/skills/run_skill.py`
- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_run_intent.py`
- Modify: `tests/unit/test_cli_delivery_status.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: persisted Task 2 state contract.
- Produces: public default ceiling 12 and concise convergence reporting/telemetry.

- [ ] **Step 1: Write failing public-contract tests**

Assert default intent/state behavior rather than constants, status output fields, stalled-run next action, summary reason, and content-free telemetry event fields.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `../../.venv/bin/pytest -q tests/unit/test_run_intent.py tests/unit/test_cli_delivery_status.py tests/unit/test_run_skill.py`

Expected: new assertions fail against default 5 and absent convergence presentation.

- [ ] **Step 3: Implement defaults and presentation**

Use one shared default constant. Render meaningful attempts, patience, outcome, excluded infrastructure attempts, and best checkpoint when present. Emit only counts, hashes, outcome, and reason code in telemetry.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `../../.venv/bin/pytest -q tests/unit/test_run_intent.py tests/unit/test_cli_delivery_status.py tests/unit/test_run_skill.py tests/unit/test_ralph_outer.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the public contract**

```bash
git add src/harness/run_intent.py src/harness/state.py src/echelon/cli_app.py src/harness/skills/run_skill.py src/harness/ralph.py tests/unit/test_run_intent.py tests/unit/test_cli_delivery_status.py tests/unit/test_run_skill.py tests/unit/test_ralph_outer.py
git commit -m "feat: report adaptive delivery convergence"
```

### Task 4: Compatibility and regression verification

**Files:**
- Modify only files required by failures discovered in this task.
- Update: `CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1-3 complete behavior.
- Produces: verified compatibility across modes, explicit caps, legacy state, and delivery lifecycle.

- [ ] **Step 1: Run focused loop regression suites**

Run: `../../.venv/bin/pytest -q tests/unit/test_convergence.py tests/unit/test_run_intent.py tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py tests/unit/test_cli_delivery_status.py tests/unit/test_run_skill.py tests/e2e/test_ralph_budget.py tests/e2e/test_ralph_convergence.py tests/e2e/test_ralph_escalation.py tests/e2e/test_ralph_resume.py`

- [ ] **Step 2: Fix regressions test-first**

For each actual regression, isolate the consumer-visible behavior in a failing test before modifying production code. Do not update expectations merely to match the new implementation.

- [ ] **Step 3: Update the changelog**

Document the adaptive lease, default ceiling change, infrastructure exclusion, persisted resume behavior, and new stall reason.

- [ ] **Step 4: Run the complete non-SOAR unit suite**

Run: `../../.venv/bin/pytest -q -m unit`

Expected: zero failures. SOAR execution remains disabled per repository policy.

- [ ] **Step 5: Run install/dry-run validation**

Run: `bash scripts/bash/dry-run.sh`

Expected: exit 0 with valid command/runtime wiring.

- [ ] **Step 6: Commit final compatibility work**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-09-11-adaptive-delivery-convergence-design.md docs/superpowers/plans/2026-09-11-adaptive-delivery-convergence.md
git add <only implementation/test files changed by verified regressions>
git commit -m "docs: document adaptive delivery convergence"
```

## Self-review

- Spec coverage: policy, persistence, loop accounting, resume, modes, reporting, telemetry, defaults, and regression verification each map to a task.
- Placeholder scan: no deferred implementation steps or unspecified error-handling instructions remain.
- Type consistency: `ProgressSnapshot`, `ConvergenceLease`, and `LeaseObservation` names are identical across producing and consuming tasks.
