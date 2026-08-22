# Feature-Scoped Harness Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist generated, per-feature clarification policy and enforce it through safe CLI parsing, Phase A context/routing, reconciliation, and quality evaluation.

**Architecture:** A small `echelon.feature_policy` module owns deterministic policy derivation, immutable persistence, rendering, reconciliation, and effective quality-gate projection. CLI resume creates the decision; `SquadController` refreshes and routes from its evidence; quality helpers consume only the projected gates.

**Tech Stack:** Python 3.11, PyYAML, pytest, existing Phase A controller and workflow YAML.

**Spec:** `docs/superpowers/specs/2026-08-21-feature-scoped-harness-policy-design.md`

## Global Constraints

- Policy is run-local and must not mutate `.echelon/config.yml`.
- Preserve user answer provenance and superseded assumptions.
- Unknown `spec run` options fail before dispatch; no source root must never resolve to `.`.
- Use TDD: each behavior is observed failing before its implementation.

---

### Task 1: Safe `spec run` target parsing

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_spec_run_targets.py`

**Interfaces:**
- Produces: `_resolve_spec_run_implementation_targets(project_root, requested_targets, allow_missing) -> list[str]` that either returns declared/resolved targets or exits before dispatch.

- [ ] **Step 1: Write failing CLI/target tests** for `--source` and an empty workspace with no `--target`.
- [ ] **Step 2: Run** `pytest tests/unit/test_cli_spec_run_targets.py -q` and confirm failures identify fallback/unknown-option behavior.
- [ ] **Step 3: Implement** strict option rejection and no-source target failure.
- [ ] **Step 4: Re-run** the target tests and confirm pass.

### Task 2: Canonical decision policy

**Files:**
- Create: `src/echelon/feature_policy.py`
- Modify: `src/echelon/cli.py`, `src/echelon/context_builder.py`
- Test: `tests/unit/test_feature_policy.py`, `tests/unit/test_context_builder.py`

**Interfaces:**
- Produces: `derive_feature_policy(answer, decision_id) -> dict`, `persist_feature_policy(staging_dir, policy) -> Path`, and `render_feature_policy(policy) -> str`.

- [ ] **Step 1: Write failing tests** for minimal-app policy derivation, immutable persistence, and context rendering.
- [ ] **Step 2: Run** `pytest tests/unit/test_feature_policy.py tests/unit/test_context_builder.py -q` and confirm failures.
- [ ] **Step 3: Implement** versioned policy derivation/persistence plus context inclusion.
- [ ] **Step 4: Re-run** the focused tests and confirm pass.

### Task 3: Reconciliation and bounded repair routing

**Files:**
- Modify: `src/echelon/feature_policy.py`, `src/echelon/cli.py`, `src/harness/squad.py`
- Test: `tests/unit/test_feature_policy.py`, `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `reconcile_feature_artifacts(spec_dir, policy) -> report` and a resume route to WHAT only when report findings require repair.

- [ ] **Step 1: Write failing tests** for stale production inference findings and narrow repair selection.
- [ ] **Step 2: Run** focused policy/controller tests and confirm expected failures.
- [ ] **Step 3: Implement** deterministic report creation and repair state/route updates.
- [ ] **Step 4: Re-run** focused tests and confirm pass.

### Task 4: Feature-scoped quality waivers

**Files:**
- Modify: `src/harness/quality_scores.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`
- Test: `tests/unit/test_quality_scores.py`, `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `effective_quality_gate_thresholds(project_root, feature_policy) -> dict[str, float]`.

- [ ] **Step 1: Write failing tests** showing a waived behavioral gate is omitted while workspace defaults remain unchanged.
- [ ] **Step 2: Run** the quality tests and confirm failure.
- [ ] **Step 3: Implement** effective threshold projection in both WHY execution paths.
- [ ] **Step 4: Re-run** the tests and confirm pass.

### Task 5: Workflow contract and complete verification

**Files:**
- Modify: `runtime/workflow/definition.yaml`
- Test: relevant workflow/context/controller tests

- [ ] **Step 1: Add failing contract tests** requiring feature policy context for post-clarification phases.
- [ ] **Step 2: Implement** context-pack policy inclusion and explicit WHY1 instructions to route only unresolved issues.
- [ ] **Step 3: Run** focused tests, then `pytest tests/unit/test_feature_policy.py tests/unit/test_cli_spec_run_targets.py tests/unit/test_context_builder.py tests/unit/test_quality_scores.py -q`.
- [ ] **Step 4: Run** the complete relevant controller integration suite and inspect `git diff`.
