# Prosaic Runtime Dry Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken extension-based dry run with a deterministic validator for Echelon's canonical Prosaic and runtime bundles.

**Architecture:** Keep `scripts/bash/dry-run.sh` as a thin public wrapper. Put bundle discovery and validation in `harness.bundle_validator`, using the existing prompt parser and workflow validator rather than reproducing YAML and graph rules in shell.

**Tech Stack:** Bash, Python 3, PyYAML, pytest, existing Echelon harness validators.

## Global Constraints

- The validator must pass when the repository view has no `extension/` tree.
- Accepted inputs are repository root, `prosaic/`, and `runtime/`.
- Validation must cover neutral command/subagent metadata, companion references, workflow structure, workflow agent registration, runtime YAML, and executable runtime shell scripts.
- The public script must contain no operational Spec-Kit or extension dependency.

---

### Task 1: Canonical bundle validator

**Files:**
- Create: `src/harness/bundle_validator.py`
- Modify: `scripts/bash/dry-run.sh`
- Modify: `tests/unit/test_dry_run_script.py`

**Interfaces:**
- Consumes: `validate_workflow_definition(definition_path=Path)`, `read_prompt_markdown(path)`.
- Produces: `validate_bundle(input_root: Path) -> BundleValidationReport` and `python -m harness.bundle_validator [root]`.

- [ ] **Step 1: Write the failing canonical-only behavior tests**

Assert that the wrapper succeeds from repository, Prosaic, and runtime roots and from a repository view that omits `extension/`; assert output names canonical roots.

- [ ] **Step 2: Run the tests to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_dry_run_script.py -q`

Expected: FAIL because the current script requires `extension.yml` and calls the obsolete workflow-validator signature.

- [ ] **Step 3: Implement the validator and thin wrapper**

Use structured Python parsing for frontmatter and YAML. Return every finding in one report and exit nonzero when any error exists.

- [ ] **Step 4: Run focused and neighboring verification**

Run: `.venv/bin/python -m pytest tests/unit/test_dry_run_script.py tests/kernel/test_workflow_validator.py tests/unit/test_prosaic_package_install.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-10-prosaic-runtime-dry-run.md scripts/bash/dry-run.sh src/harness/bundle_validator.py tests/unit/test_dry_run_script.py
git commit -m "refactor: validate canonical prosaic runtime bundle"
```
