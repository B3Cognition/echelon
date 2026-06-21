# Echelon Result Template Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `echelon_result` prompt output from a hardcoded convention to a template-owned harness contract.

**Architecture:** Add one canonical template under `extension/templates/` and have the harness append that template to every squad prompt. Phase routing contracts remain generated from workflow transitions, but the wrapper and final-output rules come from the template.

**Tech Stack:** Python harness, pytest, Markdown/YAML prompt templates.

---

### Task 1: Template-backed prompt contract

**Files:**
- Create: `extension/templates/echelon-result-template.yaml`
- Modify: `src/harness/squad_executors.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`

- [ ] **Step 1: Write failing tests**

Add tests that create a fake extension directory with `templates/echelon-result-template.yaml` containing a unique marker, then assert both normal agent prompts and staged prompts include that marker at the final output contract.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_uses_echelon_result_template tests/kernel/test_squad_executors_journal.py::test_staged_prompt_uses_echelon_result_template -q`
Expected: FAIL because the harness still uses a hardcoded tail.

- [ ] **Step 3: Implement template loading**

Refactor `_canonical_echelon_result_contract()` to accept `ext_dir: Path`, read `ext_dir/templates/echelon-result-template.yaml`, and append its exact text. Keep a small explanatory heading in Python; put the actual output shape and rules in the template.

- [ ] **Step 4: Add production template**

Create `extension/templates/echelon-result-template.yaml` with the canonical unfenced YAML block, required keys, and forbidden XML/fence/prose-after rules.

- [ ] **Step 5: Run focused tests and full suite**

Run focused prompt/parser tests, then `python -m pytest -q`.
