# Provider-Neutral Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase A and RE deterministic gates controller-owned, provider-neutral, configuration-correct, and fully covered by executable contracts.

**Architecture:** The standard resolved Echelon configuration determines whether each gate is active. Agents author artifacts only; the harness validates those artifacts after every mutation point, persists structured repair reports, and owns routing verdicts and exhaustion policy. Markdown prose describes artifact responsibilities without assuming provider-native shell tools.

**Tech Stack:** Python 3.11+, pytest, YAML workflow definitions, existing `lexicon` and `harness` validators.

## Global Constraints

- Work directly on the existing `main` checkout as previously approved; preserve all current uncommitted changes.
- Follow test-driven development for every behavioral correction.
- Models may author artifacts and report repair attempts, but may not certify deterministic gate verdicts.
- Every enabled structural gate must fail closed and honor explicit `warn` or `block` exhaustion policy.
- Disabled subgates must be routing-inert, including when stale state exists.
- Configuration must include the supported project/local/default merge cascade.
- Do not remove a prose-level command until equivalent harness behavior exists.

---

### Task 1: Configuration And Workflow Contract Foundation

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/kernel/test_workflow_validator.py`
- Test: `tests/kernel/test_phase_graph.py`

**Interfaces:**
- Consumes: `get_full_resolved_config(project_root, fallback_config_path=...)`.
- Produces: controller gate configuration with effective per-artifact activation and a valid phase graph contract.

- [ ] Add failing tests proving `.echelon/local.yml` gate overrides are resolved, disabled subgates are inert, and the real workflow definition validates.
- [ ] Run the focused tests and confirm failures describe the current direct-file loaders and invalid controller-owned type declaration.
- [ ] Replace direct gate YAML reads with the standard resolved configuration and correct the `phase3-plan` state type declaration.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Controller-Owned Tasks Gates

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/agents/solution/orchestrator.md`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_product_inputs.py`
- Test: `tests/unit/test_tasks_wiring.py`
- Test: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Produces: a controller-authored `tasks-lexicon-report.json` repair artifact, certified `tasks_lexicon_pass`, and deterministic post-PLAN2 revalidation.

- [ ] Add failing tests for structured findings, required output checks, target validation, disabled gates, and PLAN2 invalidating a previously certified task file.
- [ ] Run the tests and confirm each fails for the missing controller behavior.
- [ ] Implement one controller validation path used after `phase3-plan` and after PLAN2, persist its findings, and inject concise findings into repair prompts.
- [ ] Remove task-validation shell commands from prose only after the harness path is active.
- [ ] Run task, workflow, executor, and controller tests.

### Task 3: Controller-Owned Governance Gates

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/workflow/phases/phase2-decide.md`
- Modify: `extension/workflow/phases/phase2-tracker-alignment.md`
- Modify: `extension/agents/feasibility/gatekeeper.md`
- Modify: `extension/agents/control/tracker.md`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_structural_wiring.py`

**Interfaces:**
- Consumes: `lexicon.structural.validate_structural` and resolved governance artifact configuration.
- Produces: controller-owned structural pass verdicts, findings reports, attempt counters, and explicit exhaustion handling.

- [ ] Add failing tests showing stale model `true` cannot bypass invalid artifacts, omitted verdicts cannot pass at iteration exhaustion, and `warn`/`block` policies are explicit.
- [ ] Run the tests and confirm the controller currently fails them.
- [ ] Move structural verdict ownership into the controller and remove the verdict keys from agent allowlists.
- [ ] Persist validator findings and expose them to repair dispatches.
- [ ] Run structural, workflow, and convergence tests.

### Task 4: Complete RE Provider Neutrality And Result Contracts

**Files:**
- Modify: `src/harness/re_controller.py`
- Modify: `extension/agents/re/planner.md`
- Modify: `extension/workflow/phases/re-retarget-0-preflight.md`
- Modify: `extension/workflow/phases/re-retarget-1-input.md`
- Update: affected RE/static contract tests.

**Interfaces:**
- Produces: file-only result contracts for every file-only RE phase and controller-owned RE-retarget preflight evidence.

- [ ] Add failing tests that scan every RE phase family and reject provider-native tool names or shell snippets.
- [ ] Add a failing contract test for `re-extract-3-verify` rejecting state updates.
- [ ] Implement controller-owned retarget marker discovery and tighten RE result contracts.
- [ ] Replace stale prose assertions with harness behavior assertions.
- [ ] Run all RE, CodeGraph, PerlGraph, and static contract tests.

### Task 5: Bounded Human-Friendly Streaming

**Files:**
- Modify: `src/harness/ai_cli_backends/openai_compatible.py`
- Modify: `src/harness/ai_cli_backends/openai_compatible_progress.py`
- Modify: `extension/config-template.yml`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Produces: a bounded per-turn stream preview and exactly one full stdout response for downstream parsing.

- [ ] Add failing tests for total preview limits, truncation marker behavior, blank-line suppression, and no duplicate terminal replay.
- [ ] Run the focused provider tests and confirm failure.
- [ ] Add configurable preview ceilings and suppress final terminal replay only when content was previewed, while preserving captured stdout.
- [ ] Run the complete provider test file.

### Task 6: Contract Migration And Final Verification

**Files:**
- Update: legacy kernel, static-contract, and dry-run tests affected by Tasks 1-5.

**Interfaces:**
- Produces: a green workflow validator, dry run, focused suites, and full pytest suite.

- [ ] Replace assertions for removed commands with assertions for controller-owned execution and artifacts.
- [ ] Run `uv run python -m py_compile` over modified Python modules.
- [ ] Run `git diff --check` and the workflow dry run.
- [ ] Run all focused Phase A, RE, and provider suites.
- [ ] Run `uv run pytest -q` and require zero failures.
