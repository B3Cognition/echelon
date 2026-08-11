# Cartographer Proportionality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make first-pass specifications proportional to discovered feature complexity without weakening Echelon's requirements-quality boundaries.

**Architecture:** The canonical Prosaic CARTOGRAPHER prose owns the authoring policy, while its specification template expresses the same policy structurally. The Phase 1 dispatch repeats only the critical proportionality boundary so runtime context cannot accidentally override it. Focused tests treat these three files as one prompt contract.

**Tech Stack:** Markdown Prosaic sources, YAML-backed Echelon workflow, pytest.

## Global Constraints

- Do not introduce requirement-count, scenario-count, acceptance-count, or line-count quotas.
- Preserve atomicity, independent testability, technology neutrality, evidence grounding, negative behavior, and explicit uncertainty.
- Acceptance criteria verify formal requirements; they do not create duplicate product obligations.
- Modify canonical Prosaic source prose and templates, not deployed workspace copies.

---

### Task 1: Proportional specification authoring contract

**Files:**
- Modify: `tests/unit/test_cartographer_templates.py`
- Modify: `prosaic/subagents/echelon.cartographer.md`
- Modify: `prosaic/agents/exploration/templates/cartographer-spec-template.md`
- Modify: `runtime/workflow/phases/phase1-what.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/findings/2026-08-11-prosaic-greenfield-delivery-findings.md`

**Interfaces:**
- Consumes: DISCOVER artifacts and the controller-provided Cartographer templates.
- Produces: a complexity-sensitive prose contract consumed by all Prosaic providers and a template that no longer implies mandatory document expansion.

- [ ] **Step 1: Write failing prompt-contract tests**

Add tests that require complexity classification before authoring, one canonical obligation per distinct behavior, verification-oriented acceptance criteria, evidence-backed NFRs, and preservation of negative behavior and uncertainty. Also reject the old `at least 2 acceptance criteria` quota.

- [ ] **Step 2: Run the focused tests and confirm the intended failure**

Run: `pytest -q tests/unit/test_cartographer_templates.py`

Expected: the new proportionality tests fail against the current prompt/template contract.

- [ ] **Step 3: Implement the canonical prose and template changes**

Add a pre-authoring complexity assessment to CARTOGRAPHER, replace multiplicative scenario/acceptance/NFR instructions with evidence-sensitive rules, and annotate optional template sections. Repeat the core boundary in `phase1-what.md` without duplicating the full policy.

- [ ] **Step 4: Run focused and adjacent Phase 1 tests**

Run: `pytest -q tests/unit/test_cartographer_templates.py tests/unit/test_phase1_what_contract.py tests/unit/test_workflow_agent_names.py`

If an adjacent filename does not exist, select the nearest Phase 1 workflow contract tests with `rg --files tests/unit | rg 'phase1|workflow'` and record the exact command in the finding.

Expected: all selected tests pass.

- [ ] **Step 5: Update the grounded finding with implementation evidence**

Mark EGR-155 fixed only after focused verification. Preserve the retained Hello World artifact counts as the before-state benchmark and state that a new live provider run remains the behavioral confirmation.

- [ ] **Step 6: Commit the implementation**

```bash
git add tests/unit/test_cartographer_templates.py \
  prosaic/subagents/echelon.cartographer.md \
  prosaic/agents/exploration/templates/cartographer-spec-template.md \
  runtime/workflow/phases/phase1-what.md \
  docs/findings/echelon-grounded-review-register.md \
  docs/findings/2026-08-11-prosaic-greenfield-delivery-findings.md
git commit -m "fix: make Cartographer output proportional"
```
