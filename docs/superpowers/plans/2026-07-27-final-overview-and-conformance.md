# Final Overview And Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make early requirements orientation distinct from the final developer/PM overview, and require conformance artifacts before Phase A is build-ready.

**Architecture:** CARTOGRAPHER will produce `requirements-overview.md` during WHAT; finalization will own final `00-overview.md` after planning and conformance. Deterministic readiness and wiki surfaces will treat `00-overview.md` as the final entry point and `requirements-overview.md` as historical orientation.

**Tech Stack:** Python CLI/runtime, YAML workflow definitions, Markdown phase contracts, pytest.

## Global Constraints

- Preserve legacy published specs enough for wiki rendering; do not break old `00-overview.md` projections when `requirements-overview.md` is absent.
- New Phase A build readiness requires `00-overview.md`, `plan-conformance.md`, and `plan-conformance.json`.
- `delivery-brief`/PM guidance must be derived from conformance-approved plan/tasks; it must not invent scope or sequencing.
- Manual edits use `apply_patch`; tests are written before production changes.

---

### Task 1: Rename Early Overview Contract

**Files:**
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `extension/workflow/phases/phase2-decide.md`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/unit/test_phase_output_paths.py`

**Interfaces:**
- Consumes: existing workflow output declarations.
- Produces: workflow contracts that require `requirements-overview.md` from CARTOGRAPHER instead of early `00-overview.md`.

- [ ] **Step 1: Write failing tests**

Assert Phase 1 WHAT outputs mention `requirements-overview.md` and do not require `00-overview.md`; assert downstream early phases read `requirements-overview.md`.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_phase_output_paths.py -q`
Expected: FAIL because current contracts still require `00-overview.md`.

- [ ] **Step 3: Update workflow docs and definition**

Replace early `00-overview.md` references with `requirements-overview.md` in WHAT/ASSESS/HOW context where the early orientation is intended.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_phase_output_paths.py -q`
Expected: PASS.

### Task 2: Require Final Overview And Conformance For Readiness

**Files:**
- Modify: `src/harness/phase_a_readiness.py`
- Test: `tests/unit/test_phase_a_readiness.py`

**Interfaces:**
- Consumes: `validate_phase_a_readiness(state, candidate_spec_dirs)`.
- Produces: readiness blockers for missing final `00-overview.md`, `plan-conformance.md`, and `plan-conformance.json`.

- [ ] **Step 1: Write failing tests**

Add tests showing a spec with old Phase A inputs but no final overview/conformance is not ready, and a spec with those artifacts is ready.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_phase_a_readiness.py -q`
Expected: FAIL because readiness does not yet require final overview/conformance.

- [ ] **Step 3: Update readiness contract**

Add the three final artifacts to `REQUIRED_PHASE_A_BUILD_INPUTS`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_phase_a_readiness.py -q`
Expected: PASS.

### Task 3: Make Wiki Reading Path Prefer Final Overview

**Files:**
- Modify: `src/echelon/wiki/render.py`
- Test: `tests/unit/test_wiki_render.py`

**Interfaces:**
- Consumes: wiki model artifact list.
- Produces: spec wiki `Overview.md` with `Final overview` first, then `Requirements orientation`, then spec/plan/tasks.

- [ ] **Step 1: Write failing tests**

Assert rendered spec overview links `00-overview.md` before `requirements-overview.md`, and labels them distinctly.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_wiki_render.py -q`
Expected: FAIL because reading path currently starts at `spec.md`.

- [ ] **Step 3: Update renderer**

Add final overview and requirements orientation to the reading path, while keeping missing labels explicit.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_wiki_render.py -q`
Expected: PASS.

### Task 4: Surface New Artifacts In Artifact Index

**Files:**
- Modify: `src/echelon/artifact_index.py`
- Test: `tests/unit/test_artifact_index.py`

**Interfaces:**
- Consumes: deterministic artifact definitions.
- Produces: definitions for `00-overview.md`, `requirements-overview.md`, `plan-conformance.md`, and `plan-conformance.json`.

- [ ] **Step 1: Write failing tests**

Assert the artifact index contains the four artifacts with distinct titles/purposes.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_artifact_index.py -q`
Expected: FAIL because the new definitions are absent.

- [ ] **Step 3: Update artifact definitions**

Add concise definitions that make `00-overview.md` the final PM/developer brief and `requirements-overview.md` the early orientation.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_artifact_index.py -q`
Expected: PASS.

### Task 5: Verify Focused Suite

**Files:**
- No new files.

**Interfaces:**
- Consumes: all modified tests.
- Produces: confidence that the contract changes are wired.

- [ ] **Step 1: Run focused pytest suite**

Run: `pytest tests/unit/test_phase_output_paths.py tests/unit/test_phase_a_readiness.py tests/unit/test_wiki_render.py tests/unit/test_artifact_index.py -q`
Expected: PASS.

- [ ] **Step 2: Inspect git diff**

Run: `git diff --stat` and `git diff --check`
Expected: scoped changes and no whitespace errors.
