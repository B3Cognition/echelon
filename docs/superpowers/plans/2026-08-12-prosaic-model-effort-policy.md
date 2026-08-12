# Prosaic Model Tier and Effort Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved explicit `model_tier` and `effort` assignment to all 97 executable Echelon Prosaic artifacts.

**Architecture:** A single unit-test policy map is the executable inventory and expected metadata contract. Subagent and command frontmatter are updated without changing their prose bodies, workflow routing, or provider implementations.

**Tech Stack:** Markdown with YAML frontmatter, Python 3.11, pytest, PyYAML, Prosaic CLI.

## Global Constraints

- Cover exactly 56 top-level `prosaic/subagents/*.md` files and 41 top-level `prosaic/commands/*.md` files.
- Use only `fast`, `balanced`, or `strong` for `model_tier`.
- Use only `low`, `medium`, or `high` for `effort`.
- Do not edit support prose under `prosaic/agents/`.
- Do not alter prose bodies, tools, colors, execution types, workflow routing, or provider mappings.

---

### Task 1: Enforce and Apply Subagent Metadata

**Files:**
- Create: `tests/unit/test_prosaic_execution_policy.py`
- Modify: `prosaic/subagents/*.md`

**Interfaces:**
- Consumes: the approved assignment list in `docs/superpowers/specs/2026-08-12-prosaic-model-effort-policy-design.md`.
- Produces: explicit `model_tier` and `effort` on every canonical subagent.

- [ ] **Step 1: Write the failing policy test**

Create a test that parses every subagent frontmatter document with
`yaml.safe_load`, asserts exact file-set equality with the expected policy map,
and compares `(model_tier, effort)` for every file.

- [ ] **Step 2: Run the subagent policy test and verify failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_prosaic_execution_policy.py`

Expected: failure because all 56 subagents currently omit `effort` and several
approved tiers differ from the existing value.

- [ ] **Step 3: Update subagent frontmatter**

Add `effort` directly after `model_tier` and change only the approved tier
values. Leave all remaining frontmatter and Markdown body bytes unchanged.

- [ ] **Step 4: Run the policy and existing prose tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_prosaic_execution_policy.py tests/unit/test_cartographer_templates.py tests/unit/test_prosaic_prompt_loader.py`

Expected: all pass.

### Task 2: Enforce and Apply Command Metadata

**Files:**
- Modify: `tests/unit/test_prosaic_execution_policy.py`
- Modify: `prosaic/commands/*.md`

**Interfaces:**
- Consumes: the command assignment list in the approved design.
- Produces: explicit `model_tier` and `effort` on every canonical command.

- [ ] **Step 1: Extend the policy test to commands**

Add all 41 command assignments, require exact file-set equality, and compare
both metadata fields.

- [ ] **Step 2: Run the command policy test and verify failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_prosaic_execution_policy.py`

Expected: failure because 27 commands omit both fields and other commands omit
or disagree on one field.

- [ ] **Step 3: Update command frontmatter**

Add or update only `model_tier` and `effort`. Retain command execution and
invocation metadata exactly as-is.

- [ ] **Step 4: Run command and deployment tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_prosaic_execution_policy.py tests/unit/test_prosaic_package_install.py tests/unit/test_prosaic_provider_deployment.py tests/unit/test_cli_workspace.py`

Expected: all pass.

### Task 3: Verify the Complete Migration

**Files:**
- Verify: `prosaic/commands/*.md`
- Verify: `prosaic/subagents/*.md`

**Interfaces:**
- Consumes: complete metadata migration from Tasks 1 and 2.
- Produces: verified source metadata suitable for Prosaic inspection and Echelon dispatch.

- [ ] **Step 1: Run focused Python tests**

Run the policy, prompt loader, workflow graph, package installation, provider
deployment, and workspace initialization suites.

- [ ] **Step 2: Inspect representative artifacts through Prosaic**

Inspect one fast/low command, one balanced/medium agent, and one strong/high
agent. Confirm Prosaic returns the exact source metadata.

- [ ] **Step 3: Run diff and repository checks**

Run `git diff --check`, inspect `git diff --stat`, and confirm no prose body or
runtime-provider implementation changed.

- [ ] **Step 4: Commit**

Commit the policy documentation, test, and frontmatter migration together with
message `feat: assign Prosaic model tiers and effort`.
