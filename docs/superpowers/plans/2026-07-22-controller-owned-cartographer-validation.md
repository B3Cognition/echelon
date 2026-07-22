# Controller-Owned CARTOGRAPHER Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve issue #176 without changing Phase A routing by moving CARTOGRAPHER validation configuration, execution, evidence, and repair accounting into the harness.

> **Follow-up:** The approved visible-node design in `2026-07-22-visible-spec-lexicon-node.md` supersedes this plan's original no-routing-change constraint while preserving its provider-neutral prompt and report contracts.

**Architecture:** Extend the existing spec Lexicon controller boundary to persist a tasks-gate-style report and inject concise repair context. Then simplify the canonical agent and phase prompts so they describe artifacts and strict results, while the existing deterministic Understanding node and controller own operational checks.

**Tech Stack:** Python 3.10+, pytest, PyYAML, Markdown prompt contracts, existing Echelon squad harness and Lexicon validators.

## Global Constraints

- Preserve successful progression as `phase1-what -> phase1-lexicon -> phase1-understanding -> phase1-why2`.
- Preserve `pending`, failed redispatch, repair exhaustion, and disabled-gate behavior.
- Do not remove operational prose until equivalent harness behavior is covered by a failing test and implemented.
- Do not add provider-native tool names to canonical prompts.
- Keep dynamic controller data separate from instructions and preserve the strict `echelon_result` contract.
- Work directly on `main`, as previously approved, and do not disturb unrelated changes.

---

### Task 1: Controller Report And Attempt Accounting

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `<spec_dir>/spec-lexicon-report.json`.
- Produces state: `lexicon_report`, `lexicon_findings`, `lexicon_evaluation`, `lexicon_pass`, and controller-owned `lexicon_attempts`.

- [x] Add failing tests for complete findings, report persistence, failed-attempt increment, passing reset, pending semantics, and `.echelon/local.yml` configuration.
- [x] Run the focused tests and confirm failures identify missing report/attempt behavior.
- [x] Extract spec Lexicon validation into a structured report helper and persist the report atomically.
- [x] Update state only from controller evidence and increment attempts exactly once per failed dispatch.
- [x] Run the focused controller tests.

### Task 2: Phase-Specific Configuration And Repair Context

**Files:**
- Modify: `src/harness/squad_executors.py`
- Test: `tests/kernel/test_squad_executors_journal.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces prompt section: `# Controller Configuration` for `phase1-what`.
- Produces prompt section: `# Spec Lexicon Repair (Controller-Enforced)` only after a failed controller report.

- [x] Add failing tests for resolved gate values, disabled mode, failed-report injection, and absence from unrelated phases.
- [x] Run the focused tests and confirm the new sections are missing.
- [x] Render a concise configuration section from controller-supplied state/config, not from model-side discovery.
- [x] Render report-path repair context without embedding the full findings list.
- [x] Run executor and controller prompt tests.

### Task 3: Provider-Neutral Prompt Migration

**Files:**
- Modify: `extension/agents/exploration/cartographer.md`
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `tests/contract/static_contracts.py`
- Modify: `tests/unit/test_cartographer_templates.py`
- Modify: `tests/kernel/test_prompt_references.py`

**Interfaces:**
- Preserves: artifact grammar, source/hash traceability, amendment behavior, output paths, and strict `echelon_result` fields.
- Removes: Understanding CLI, Lexicon CLI, Python config probe, and shell post-dispatch checks.

- [x] Replace legacy positive command assertions with failing provider-neutral prompt assertions.
- [x] Run prompt/static tests and confirm they fail against current prose.
- [x] Rewrite validation sections as controller-input and artifact-repair responsibilities using clear headings and direct instructions.
- [x] Remove duplicate shell verification from `phase1-what`; retain explicit controller-owned preconditions and outcomes.
- [x] Run all prompt, template, and static-contract tests.

### Task 4: Flow Regression And Verification

**Files:**
- Modify focused workflow tests only if an uncovered controller contract requires it.

**Interfaces:**
- Preserves current graph edges and exhaustion policy.

- [x] Test successful transition through deterministic Understanding.
- [x] Test failed Lexicon validation redispatch with injected evidence and bounded attempts.
- [x] Run issue-focused integration, executor, prompt, graph, and static-contract suites.
- [x] Run `python -m py_compile` for modified Python modules and `git diff --check`.
- [x] Run the full pytest suite and report any residual issue #176 gap.
