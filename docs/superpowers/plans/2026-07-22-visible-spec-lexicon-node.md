# Visible Spec Lexicon Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move spec Lexicon validation from hidden WHAT transition evaluation into a visible, provider-free `phase1-lexicon` workflow node.

**Architecture:** Add a `deterministic_lexicon` executor beside deterministic Understanding, route WHAT through a new graph node, and preserve the current report, repair, pending, and exhaustion contracts. Add a compatibility guard for runs that resume at Understanding without current passing Lexicon evidence.

**Tech Stack:** Python 3.10+, pytest, PyYAML, existing Echelon phase graph, squad controller, Lexicon parser and validators.

## Global Constraints

- Do not add a provider call to Lexicon validation.
- Preserve `spec.md`, `00-overview.md`, and derived-artifact ownership in CARTOGRAPHER.
- Preserve current `pending`, `passed`, `failed`, repair-attempt, iteration, warn, and block semantics.
- Do not migrate the tasks Lexicon gate in this change.
- Preserve active-run continuation through a controller evidence guard.
- Work with the uncommitted issue #176 changes already present on `main`.

---

### Task 1: Visible Graph Contract

**Files:**
- Modify: `extension/workflow/definition.yaml`
- Modify: `src/harness/phase_graph.py`
- Test: `tests/kernel/test_phase_graph.py`
- Test: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Produces node: `phase1-lexicon`, type `deterministic_lexicon`.
- Produces metadata: `lexicon_artifact: spec`.

- [x] Add failing graph tests for `phase1-what -> phase1-lexicon -> phase1-understanding` and repair edges.
- [x] Run focused graph tests and confirm the node is missing.
- [x] Add node metadata loading and the workflow definition entry.
- [x] Run focused graph and workflow validation tests.

### Task 2: Provider-Free Lexicon Executor

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces class: `DeterministicLexiconExecutor`.
- Consumes: resolved `lexicon_gate.artifacts.spec`, `state.spec_dir`, and persisted attempts.
- Produces: deterministic `SquadAgentResult` with the five controller-owned Lexicon fields.

- [x] Migrate the existing spec-gate tests to execute `phase1-lexicon` and add a provider non-invocation assertion.
- [x] Run focused tests and confirm the executor type is unknown.
- [x] Move report writing, validation, glossary loading, pending handling, and attempt accounting into the executor.
- [x] Register `deterministic_lexicon` and remove spec validation from `_evaluate_transitions`.
- [x] Run executor and controller gate tests.

### Task 3: Routing, Exhaustion, And Resume Compatibility

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `extension/agents/exploration/cartographer.md`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/kernel/test_prompt_references.py`

**Interfaces:**
- Produces guard: controller routes stale/missing spec Lexicon evidence through `phase1-lexicon` before Understanding.
- Preserves repair context injection on the next WHAT dispatch.

- [x] Add failing tests for pass, pending repair, failed repair, warn exhaustion, hard exhaustion, and old-run resume.
- [x] Run focused routing tests and confirm hidden-WHAT assumptions fail.
- [x] Move exhaustion ownership to `phase1-lexicon` and add the compatibility guard.
- [x] Update prose to name the visible post-dispatch node without adding operational commands.
- [x] Run routing, prompt, continuation, rewind, and roadmap tests.

### Task 4: Verification

**Files:**
- Modify tests only when a stale expectation contradicts the approved node contract.

**Interfaces:**
- Preserves all repository contracts outside the new visible node.

- [x] Run issue-focused graph, executor, controller, prompt, CLI, and static-contract suites.
- [x] Run Python compilation, forbidden-command scan, and `git diff --check`.
- [x] Run the complete pytest suite.
- [x] Review the final diff for hidden spec-gate execution or provider dispatches.
