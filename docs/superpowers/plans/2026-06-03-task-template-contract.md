# Task Template Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tasks.md` generation template-backed and machine-parseable.

**Architecture:** Add external markdown templates/fragments under `extension/templates/`, add a small Python validator/parser for canonical task rows, and update workflow/agent prompts so generated and appended task sections preserve the contract. Build parsing can then count canonical task rows instead of arbitrary checkboxes.

**Tech Stack:** Markdown templates, Python parser utilities, pytest.

---

### Task 1: Canonical Task Parser And Validator

**Files:**
- Create: `src/kernel/task_contract.py`
- Test: `tests/unit/test_task_contract.py`

- [ ] Write failing tests for canonical task rows, dependency parsing, and rejection of acceptance-checkbox-only documents.
- [ ] Implement minimal parser/validator functions.
- [ ] Run focused tests and confirm green.

### Task 2: External Templates And Fragments

**Files:**
- Create: `extension/templates/tasks-template.md`
- Create: `extension/templates/task-entry-fragment.md`
- Create: `extension/templates/task-checkpoint-fragment.md`
- Create: `extension/templates/bugfix-task-fragment.md`
- Create: `extension/templates/review-fix-task-fragment.md`
- Create: `extension/templates/fulfillment-gap-task-fragment.md`
- Test: `tests/unit/test_task_templates.py`

- [ ] Write failing tests that templates contain canonical task rows and fragment IDs.
- [ ] Add compact templates/fragments.
- [ ] Run focused tests and confirm green.

### Task 3: Prompt Wiring

**Files:**
- Modify: `extension/agents/solution/orchestrator.md`
- Modify: `extension/agents/re/tasker.md`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/workflow/phases/re-planning-2-tasks.md`
- Modify: `extension/workflow/phases/build-1-init.md`
- Modify: `extension/workflow/phases/bugfix-5-finalize.md`
- Modify: `extension/commands/echelon.review.md`
- Modify: `extension/workflow/phases/reopen-1-apply-gaps.md`

- [ ] Update prompts to require `extension/templates/tasks-template.md` and fragments.
- [ ] Update build-init task counting guidance to canonical task rows.
- [ ] Run prompt/template tests and full unit suite.
