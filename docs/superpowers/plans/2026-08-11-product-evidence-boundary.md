# Product Evidence Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and consume a deterministic verify-spec product inventory that excludes Echelon's deployed control plane.

**Architecture:** A focused `harness.product_inventory` module inventories Git-deliverable files and writes JSON/Markdown evidence. The harness CLI owns artifact creation and state stamping; verify-spec phases and IMPLEMENTATION MAPPER consume the artifact for repository-wide existence and cardinality claims.

**Tech Stack:** Python 3.11, Git CLI, Markdown/YAML workflow prompts, pytest.

## Global Constraints

- Exclude the complete `.echelon/` and `.git/` control roots.
- Preserve other hidden product files.
- Use Git tracked plus non-ignored untracked files when Git is available.
- Do not treat inventory membership as behavioral fulfillment proof.
- Do not change Prosaic deployment locations.

---

### Task 1: Deterministic product inventory

**Files:**
- Create: `src/harness/product_inventory.py`
- Create: `tests/unit/test_product_inventory.py`

**Interfaces:**
- Produces: `write_product_inventory(project_root: Path, verify_run_dir: Path) -> ProductInventoryResult`.
- Produces: `{verify_run_dir}/product-inventory.json` and `{verify_run_dir}/product-inventory.md`.

- [x] Write failing tests for tracked, untracked, ignored, `.echelon`, `.git`, and non-Echelon hidden files.
- [x] Run `.venv/bin/pytest tests/unit/test_product_inventory.py -q` and confirm the module is missing.
- [x] Implement sorted Git-deliverable inventory, filesystem fallback, path containment, hashing, and both output formats.
- [x] Run `.venv/bin/pytest tests/unit/test_product_inventory.py -q` and confirm all tests pass.

### Task 2: Harness CLI ownership

**Files:**
- Modify: `src/harness/__main__.py`
- Modify: `tests/unit/test_product_inventory.py`

**Interfaces:**
- Produces: `python -m harness write-product-inventory <project-root> <verify-run-dir>`.
- Updates: existing verify state with `product_inventory: ready` and `product_inventory_count`.

- [x] Add a failing CLI test proving both artifacts and state stamps are written.
- [x] Run the CLI test and confirm `write-product-inventory` is unknown.
- [x] Add the subcommand, usage text, existing-state guard, writer call, and state stamp.
- [x] Rerun the focused tests and confirm they pass.

### Task 3: Verify-spec and Prosaic mapper contract

**Files:**
- Modify: `runtime/workflow/phases/verify-spec-3-audit.md`
- Modify: `runtime/workflow/phases/verify-spec-4-map.md`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `prosaic/subagents/echelon.implementation-mapper.md`
- Modify: `tests/kernel/test_prompt_references.py`

**Interfaces:**
- Consumes: `product-inventory.json` as the machine-readable product boundary.
- Consumes: `product-inventory.md` as the mapper-readable equivalent.

- [x] Add failing prompt/workflow assertions for the command, outputs, context pack, and cardinality boundary.
- [x] Run `.venv/bin/pytest tests/kernel/test_prompt_references.py -q` and confirm the new assertions fail.
- [x] Wire the deterministic command and artifact contract into runtime and Prosaic sources.
- [x] Rerun prompt-reference and workflow-validator tests.

### Task 4: Regression verification and commit

**Files:**
- Modify: `docs/findings/echelon-grounded-review-register.md` only after greenfield proof.

**Interfaces:**
- Verifies: product inventory, fulfillment cache behavior, canonical Prosaic/runtime workflow validation.

- [x] Run `.venv/bin/pytest tests/unit/test_product_inventory.py tests/unit/test_fulfillment_runner.py tests/kernel/test_prompt_references.py tests/kernel/test_workflow_validator.py -q`.
- [x] Run `python -m harness.bundle_validator .`.
- [ ] Run `git diff --check` and inspect the complete diff.
- [ ] Commit the EGR-153 implementation independently.
- [ ] Redeploy bundles to the preserved greenfield workspace and rerun delivery verification.
