# Requirement Preservation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent HOW, PLAN, and TASKS artifacts from reinterpreting behavior already fixed by `spec.md`.

**Architecture:** Add an explicit requirement-preservation obligation to the HOW phase, ARCHITECT prompt, plan template, and consensus review language. This first slice is prompt/template enforced and test-locked; a later slice can add a deterministic parser/gate once the artifact shape has settled.

**Tech Stack:** Markdown phase/agent templates, Python pytest template-contract tests.

## Global Constraints

- Keep `spec.md` as the product source of truth after WHY2 validates it.
- HOW may refine implementation mechanisms, but must prove those mechanisms preserve product behavior.
- PLAN/TASKS may sequence HOW, but must not treat agreement with `plan.md` as sufficient when `plan.md` conflicts with `spec.md`.
- Use existing pytest patterns under `tests/unit/`.

---

### Task 1: Lock Requirement Preservation Into HOW

**Files:**
- Modify: `extension/workflow/phases/phase3-how.md`
- Modify: `extension/agents/solution/architect.md`
- Modify: `extension/templates/plan-template.md`
- Test: `tests/unit/test_architect_templates.py`
- Test: `tests/unit/test_plan_templates.py`

**Interfaces:**
- Consumes: Existing ARCHITECT instructions and `plan.md` required-section validation.
- Produces: A required `## Requirement Preservation` plan section and ARCHITECT preservation rules.

- [ ] **Step 1: Write failing tests**

Add assertions that:

```python
assert "Requirement Preservation" in text
assert "HOW may refine implementation mechanisms" in text
assert "must not reinterpret product behavior" in text
assert "route back to WHAT" in text
```

Use `test_architect_prompt_references_all_templates`, `test_phase3_how_dispatch_includes_templates`, and `test_plan_template_contains_required_sections`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_architect_templates.py tests/unit/test_plan_templates.py -q
```

Expected: FAIL because preservation text and plan section do not exist yet.

- [ ] **Step 3: Update HOW prompt and architect protocol**

Add a hard ARCHITECT rule: validated `spec.md` owns product behavior; HOW may select mechanisms only when it can show preservation. If an architecture choice changes behavior, ARCHITECT must choose another mechanism or route back to WHAT/user with a proposed spec amendment.

- [ ] **Step 4: Update plan template**

Add required section `## Requirement Preservation` with a trace table:

```markdown
| Requirement | Product Invariant | Architecture Decision | Preserves? | Evidence |
| --- | --- | --- | --- | --- |
| FR-001 | {observable behavior that must remain true} | {mechanism or ADR} | {yes/no/escalated} | {why this preserves the invariant} |
```

Also update the plan section contract list so `validate_plan_markdown` requires the section.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_architect_templates.py tests/unit/test_plan_templates.py -q
```

Expected: PASS.

### Task 2: Make Consensus Catch WHAT-vs-HOW Drift

**Files:**
- Modify: `extension/agents/exploration/appendices/sage-contradiction-detection-reference.md`
- Modify: `extension/agents/exploration/sage.md`
- Modify: `extension/workflow/phases/phase3-consensus.md`
- Test: `tests/unit/test_sage_templates.py`

**Interfaces:**
- Consumes: WHY3 existing cross-artifact consistency sweep.
- Produces: Explicit contradiction category for architecture changing product behavior.

- [ ] **Step 1: Write failing tests**

Add assertions that SAGE/WHY3 references:

```python
assert "architecture_requirement_drift" in text
assert "plan.md, research.md, data-model.md, contracts/" in text
assert "validated `spec.md`" in text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_sage_templates.py -q
```

Expected: FAIL because the new contradiction type is absent.

- [ ] **Step 3: Extend contradiction reference**

Add `architecture_requirement_drift`: HOW/PLAN/TASKS introduce a mechanism, deferral, persistence, ordering, consistency, security, privacy, or lifecycle behavior that changes an invariant in validated `spec.md`.

- [ ] **Step 4: Update SAGE and consensus phase text**

Require WHY3 to compare HOW/PLAN/TASK artifacts against validated `spec.md`, not only against each other.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_sage_templates.py -q
```

Expected: PASS.

### Task 3: Validate The Combined Contract

**Files:**
- No new files.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: Verified prompt/template contract.

- [ ] **Step 1: Run focused unit suite**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_architect_templates.py tests/unit/test_plan_templates.py tests/unit/test_sage_templates.py -q
```

Expected: PASS.

- [ ] **Step 2: Inspect diff**

Run:

```bash
git diff -- extension/workflow/phases/phase3-how.md extension/agents/solution/architect.md extension/templates/plan-template.md extension/agents/exploration/appendices/sage-contradiction-detection-reference.md extension/agents/exploration/sage.md extension/workflow/phases/phase3-consensus.md tests/unit/test_architect_templates.py tests/unit/test_plan_templates.py tests/unit/test_sage_templates.py
```

Expected: Diff only changes preservation-contract prompt/template/test language.
