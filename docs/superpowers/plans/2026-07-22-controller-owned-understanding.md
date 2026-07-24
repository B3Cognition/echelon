# Controller-Owned Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move deterministic WHY2 and WHY3 Understanding analysis, scoring, evidence, and optional diagrams from SAGE into the Echelon harness.

**Architecture:** A public `understanding.service` API performs analysis without discovering project configuration. A provider-free harness executor resolves configuration, writes immutable evidence, appends certified scores, and then routes to SAGE for qualitative interpretation. The existing CLI delegates to the same service so CLI and harness calculations cannot drift.

**Tech Stack:** Python 3.10+, Typer, Rich, PyYAML, pytest, existing Echelon phase graph and squad harness.

## Global Constraints

- Work directly on `main` because the user explicitly approved that workflow.
- Preserve unrelated dirty work and stage only issue #175 files if a commit is requested.
- Follow red-green-refactor for every behavior change.
- Resolve all eight gates: `overall`, `structure`, `testability`, `semantic`, `cognitive`, `readability`, `depth`, and `behavioral`.
- Completed gate failure still dispatches SAGE; only operational analysis or evidence failures block before dispatch.
- SAGE may make a certified pass stricter, but may never supply or override certified scores.
- Automatic diagrams default to disabled and diagram failure is non-blocking.

---

## File Map

- Create `src/understanding/service.py`: provider-free analysis bundle and gate evaluation.
- Modify `src/understanding/cli.py`: delegate analysis and gate evaluation to the public service while preserving CLI output and exit codes.
- Create `src/harness/understanding_gate.py`: resolve spec/config, reuse or persist immutable evidence, and construct controller state updates.
- Modify `src/harness/squad_executors.py`: deterministic executor plus certified report prompt context.
- Modify `src/harness/squad.py`: register deterministic executor and preserve its controller-owned updates.
- Modify `src/harness/phase_graph.py`: parse deterministic-node metadata needed by the executor.
- Modify `extension/workflow/definition.yaml`: insert `phase1-understanding` and `phase3-understanding`, remove SAGE score ownership, and protect phase3 failure routing.
- Modify `extension/config-template.yml` and `extension/echelon-config.yml`: add `understanding.diagram.enabled: false`.
- Modify `extension/agents/exploration/sage.md`, its appendix, and WHY2/consensus phase prose: replace invocation instructions with certified-evidence interpretation.
- Add focused service, executor, workflow, prompt-contract, and integration tests under `tests/`.

---

### Task 1: Public Understanding Service

**Files:**
- Create: `src/understanding/service.py`
- Modify: `src/understanding/cli.py`
- Test: `tests/unit/test_understanding_service.py`
- Test: existing Understanding CLI tests located by `rg -l '_analyze_spec|_parse_requirements|_check_quality_gates' tests`

**Interfaces:**
- Produces: `analyze_spec_bundle(spec_path: Path, *, thresholds: Mapping[str, float], enhanced: bool = True, use_nlp: bool = True, use_energy: bool = False, diagrams_enabled: bool = False, diagram_output_dir: Path | None = None) -> UnderstandingBundle`.
- Produces: immutable `UnderstandingBundle.to_dict() -> dict[str, object]` containing analysis, scores, gates, pass, requirement count, per-requirement results, findings, entity/behavioral analysis, and diagrams.
- Preserves: CLI-private helper imports as compatibility aliases until callers migrate.

- [x] **Step 1: Write failing public-service tests**

Test that a minimal spec returns a serializable bundle, every configured gate is represented, a zero-requirement spec is a completed failure with `zero-requirements`, and disabled diagrams report `skipped`.

- [x] **Step 2: Verify the tests fail for the missing module**

Run: `uv run pytest -q tests/unit/test_understanding_service.py`

Expected: collection fails because `understanding.service` does not exist.

- [x] **Step 3: Implement the minimal public service**

Move reusable parsing and analysis logic from `cli.py` into `service.py`. Calculate category scores from `metrics.category_averages`, calculate `overall` from `overall_weighted_average`, create one gate object per supplied threshold, and set aggregate `pass` only when requirements exist and all gates pass. Keep configuration discovery outside this module.

- [x] **Step 4: Delegate CLI analysis to the service**

Keep current flags, JSON list shape, human rendering, and validation exit semantics. Re-export `_parse_requirements`, `_analyze_text`, `_analyze_spec`, and `_check_quality_gates` where existing tests or integrations rely on them.

- [x] **Step 5: Verify service and CLI parity**

Run: `uv run pytest -q tests/unit/test_understanding_service.py $(rg -l '_analyze_spec|_parse_requirements|_check_quality_gates' tests)`

Expected: all selected tests pass.

---

### Task 2: Deterministic Evidence Runner

**Files:**
- Create: `src/harness/understanding_gate.py`
- Modify: `extension/config-template.yml`
- Modify: `extension/echelon-config.yml`
- Test: `tests/unit/test_understanding_gate.py`

**Interfaces:**
- Consumes: `analyze_spec_bundle(...) -> UnderstandingBundle`.
- Produces: `run_understanding_gate(*, project_root: Path, squad_dir: Path, phase: str, iteration: int, spec_dir: str, config: Mapping[str, object]) -> UnderstandingGateResult`.
- Produces: `UnderstandingGateResult.state_updates() -> dict[str, object]` with an appended controller-certified score, report path/digest/status, and failing-gate summary.

- [x] **Step 1: Write failing evidence-runner tests**

Cover all eight resolved thresholds, immutable filename and schema, SHA-256 digest, idempotent reuse for the same phase/iteration/spec digest, no duplicate score, completed metric failure, missing `spec.md`, evidence-write failure, diagram disabled, diagram success, and non-blocking diagram failure.

- [x] **Step 2: Verify the tests fail for the missing runner**

Run: `uv run pytest -q tests/unit/test_understanding_gate.py`

Expected: collection fails because `harness.understanding_gate` does not exist.

- [x] **Step 3: Implement evidence generation and reuse**

Write reports below `<squad_dir>/evidence/understanding/<phase>-iter-<N>.json` using atomic creation. If the existing report has the same spec digest and schema, reuse it. If the path contains different evidence, choose a digest-qualified immutable path rather than overwriting. Treat analysis and write exceptions as operational errors.

- [x] **Step 4: Implement controller-owned score projection**

Append one score with `source: harness:understanding`, evidence path, `pass_id`, and all eight values. Deduplicate by source, evidence digest, phase, and iteration while preserving historical model-authored entries as read-only history.

- [x] **Step 5: Add diagram configuration defaults**

Add exactly:

```yaml
understanding:
  diagram:
    enabled: false
```

to both distributed config files. The runner passes the resolved Boolean to the service.

- [x] **Step 6: Verify the evidence runner**

Run: `uv run pytest -q tests/unit/test_understanding_gate.py`

Expected: all tests pass.

---

### Task 3: Provider-Free Workflow Nodes

**Files:**
- Modify: `src/harness/phase_graph.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/kernel/test_phase_graph.py`
- Test: `tests/kernel/test_squad_executors_journal.py`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_consensus_routing.py`

**Interfaces:**
- Produces: phase type `deterministic_understanding` handled without constructing or invoking an AI provider.
- Produces: controller state updates from `UnderstandingGateResult`, followed by `DONE` on completed pass or completed fail.
- Produces: `BLOCKED` with exact operational evidence on analysis/evidence failure.

- [x] **Step 1: Write failing phase-graph and executor tests**

Assert `phase1-what -> phase1-understanding -> phase1-why2` and `phase3-plan -> phase3-understanding -> phase3-consensus`. Assert completed metric failure still reaches SAGE, operational failure does not dispatch a provider, and a retry resumes at the deterministic node.

- [x] **Step 2: Verify focused workflow tests fail**

Run: `uv run pytest -q tests/kernel/test_phase_graph.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py tests/unit/test_consensus_routing.py`

Expected: failures identify the missing node type and workflow edges.

- [x] **Step 3: Parse and register the node type**

Add only the phase metadata required to identify the target SAGE phase and spec source. Register `DeterministicUnderstandingExecutor` in the existing executor registry. The executor must never receive the provider dependency.

- [x] **Step 4: Wire transitions and legacy resume**

Insert both nodes in `definition.yaml`. Redirect runs at WHY2/consensus without matching certified evidence through the appropriate deterministic node before dispatch. Preserve operational retries at that node and do not consume authoring repair budget.

- [x] **Step 5: Protect phase3 routing**

Evaluate certified `quality_gates.fail` repair routing before ordinary success and `accept_with_risk`, except for the existing explicit iteration-cap convergence route.

- [x] **Step 6: Verify focused workflow behavior**

Run the Step 2 command again.

Expected: all selected tests pass.

---

### Task 4: SAGE Becomes an Evidence Interpreter

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/agents/exploration/sage.md`
- Modify: `extension/agents/exploration/appendices/sage-understanding-followup-reference.md`
- Modify: `extension/workflow/phases/phase1-why2.md`
- Modify: `extension/workflow/phases/phase3-consensus.md`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/kernel/test_prompt_references.py`
- Test: `tests/unit/test_structural_wiring.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: controller state keys identifying the certified report and concise summary.
- Produces: prompt section `# Certified Understanding Evidence` for SAGE in WHY2 and WHY3 only.
- Removes: SAGE permission to return `quality_scores`.

- [x] **Step 1: Write failing prompt and result-contract tests**

Assert WHY1 receives no certified section; WHY2 and WHY3 receive exactly one section with report path, digest, status, pass, and failing gates; SAGE-authored `quality_scores` is quarantined; canonical SAGE prose contains no Skill, CLI, shell, `jq`, temporary-file, or diagram-execution instructions.

- [x] **Step 2: Verify prompt-contract tests fail**

Run: `uv run pytest -q tests/kernel/test_prompt_references.py tests/unit/test_structural_wiring.py tests/integration/test_squad_controller.py`

Expected: failures expose legacy execution prose and score ownership.

- [x] **Step 3: Inject certified evidence context**

Use one shared renderer from both `AgentExecutor` and `StagedParallelExecutor`. Render only concise state plus the immutable report path; do not duplicate the full per-requirement report into prompts.

- [x] **Step 4: Clean SAGE and phase prose**

Describe SAGE's qualitative duties and certified-evidence inputs. Keep contradiction analysis, amendments, pre-mortem, cross-artifact checks, `quality-gates.md`, `issues.md`, journal evidence, and qualitative verdict. Remove all instructions to execute Understanding or calculate certified values.

- [x] **Step 5: Remove SAGE score permissions**

Remove `quality_scores` from WHY2 and WHY3 SAGE `allowed_state_updates`. Keep the controller-owned key available only to the deterministic executor/controller merge path.

- [x] **Step 6: Verify prompt and contract behavior**

Run the Step 2 command again.

Expected: all selected tests pass.

---

### Task 5: Migration and Full Verification

**Files:**
- Modify focused status/migration tests only when required by established controller behavior.

- [x] **Step 1: Test existing-run migration explicitly**

Create fixtures for a run paused at `phase1-why2` and another at `phase3-consensus` with only legacy model-authored score history. Verify each is redirected through the deterministic node and receives one new `source: harness:understanding` score.

- [x] **Step 2: Run issue-focused tests**

Run: `uv run pytest -q tests/unit/test_understanding_service.py tests/unit/test_understanding_gate.py tests/kernel/test_phase_graph.py tests/kernel/test_squad_executors_journal.py tests/kernel/test_prompt_references.py tests/unit/test_structural_wiring.py tests/unit/test_consensus_routing.py tests/integration/test_squad_controller.py`

Expected: all tests pass.

- [x] **Step 3: Run static verification**

Run: `uv run python -m py_compile src/understanding/service.py src/understanding/cli.py src/harness/understanding_gate.py src/harness/squad_executors.py src/harness/squad.py src/harness/phase_graph.py`

Run: `git diff --check`

Expected: both commands exit zero.

- [x] **Step 4: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [x] **Step 5: Review issue #175 acceptance criteria**

Confirm deterministic ownership, immutable evidence, no provider dispatch in either new node, no SAGE score authority, safe phase3 failure order, default-off diagrams, operational-error blocking, and legacy-run redirection. Report any residual gap instead of closing the issue prematurely.
