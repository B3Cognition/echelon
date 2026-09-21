# Controlled Delivery Hard-Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python-controlled delivery the only supported Phase B implementation and delete the feature-off, raw-build, and legacy marker-driven execution paths.

**Architecture:** `StrategyCoordinator` always supplies controller context to `RalphController`, which always dispatches typed delivery slices and controller-owned repair/documentation/verification stages. The canonical `build_command: echelon build` value remains a validated strategy identifier, but no production code executes it or resolves the retired Prosaic build workflow.

**Tech Stack:** Python 3.11+, Typer, pytest, YAML runtime bundle, Markdown Prosaic assets.

**Spec:** `docs/superpowers/specs/2026-09-21-controlled-delivery-hard-cutover-design.md`

## Global Constraints

- Preserve controller-only durable state mutation and pending-operation recovery.
- Preserve assignment-bound typed provider results and authenticated input snapshots.
- Preserve deterministic planning, bounded repair, documentation, verification, and review re-entry.
- Preserve polyrepo target dispatch and standalone `echelon spec verify` behavior.
- Keep `build_command: echelon build` as a non-executable strategy identifier in S2.
- Do not decompose `StrategyCoordinator` or `RalphController`; that is S4.
- Historical specs, findings, plans, and changelog entries remain unchanged.
- Use `.venv/bin/python -m pytest`, not the system `pytest`.

---

### Task 1: Remove the feature switch and close raw build access

**Files:**

- Modify: `src/harness/config.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `runtime/config-template.yml`
- Modify: `tests/unit/test_cli_llm_tool_policy.py`
- Modify: `tests/unit/test_delivery_controller_integration.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**

- Consumes: generic `llm.features: dict[str, object]` parsing and the hidden Typer `build` compatibility command.
- Produces: unconditional exit code `2` for raw `echelon build`; no special configuration semantics for `delivery_gate_controller`.

- [x] **Step 1: Change the raw-build test from conditional to unconditional**

Replace `test_public_build_cannot_bypass_enabled_delivery_controller` with a parameterized test covering absent, `true`, and `false` legacy configuration values:

```python
@pytest.mark.parametrize("legacy_value", [None, True, False])
def test_public_build_always_routes_to_delivery_run(monkeypatch, tmp_path, legacy_value):
    config = HarnessConfig(llm=LlmConfig(cli="codex"))
    if legacy_value is not None:
        config.llm.features["delivery_gate_controller"] = legacy_value
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli.load_config", lambda *args, **kwargs: config)

    result = CliRunner().invoke(app, ["build", "001-demo"])

    assert result.exit_code == 2
    assert "echelon delivery run 001-demo" in result.output
```

Delete the test that expects raw Prosaic build dispatch. Change the config-specific validation test to prove arbitrary scalar feature values retain generic parsing without naming the removed key.

- [x] **Step 2: Run the focused tests and verify the new expectation fails**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_llm_tool_policy.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_config.py \
  tests/unit/test_cli_typer_app.py
```

Expected: the raw command still dispatches when the flag is absent or false, and the old flag still has special validation.

- [x] **Step 3: Make rejection unconditional and remove flag parsing**

In `_dispatch_skill_command`, reject `command == "build"` before looking up
`SKILL_MAP`. Include the concrete replacement `echelon delivery run <spec_id>`
and do not load configuration, inspect Prosaic, or construct a provider. Remove
`build` from `SKILL_MAP` and from `_skill_required_capability`; the Typer
compatibility command is the only caller allowed to pass that retired name.

Remove the `delivery_gate_controller` special case from `_parse_llm_features`. Remove the opt-in setting from `runtime/config-template.yml`. Keep the hidden Typer command only as a migration error surface; update its docstring to say it always redirects to controlled delivery.

- [x] **Step 4: Run the Task 1 focused tests**

Run the Step 2 command.

Expected: all pass.

- [x] **Step 5: Commit the closed public boundary**

```bash
git add src/harness/config.py src/echelon/cli.py src/echelon/cli_app.py \
  runtime/config-template.yml tests/unit/test_cli_llm_tool_policy.py \
  tests/unit/test_delivery_controller_integration.py tests/unit/test_config.py \
  tests/unit/test_cli_typer_app.py
git commit -m "refactor: close legacy delivery entry points"
```

### Task 2: Make coordinator setup controller-only

**Files:**

- Create: `src/harness/delivery_errors.py`
- Modify: `src/harness/coordinator.py`
- Modify: `src/harness/visual_ralph.py`
- Create: `tests/unit/test_controlled_delivery_setup.py`
- Modify: `tests/unit/test_visual_ralph.py`
- Modify: `tests/unit/test_cli_harness_resume.py`

**Interfaces:**

- Produces: `DeliveryConfigurationError(RuntimeError)` for missing providers and invalid strategy identifiers.
- Produces: `get_build_prompt() -> str` returning controller context only; it never resolves Prosaic command prose.
- Consumes: `AICodingCliProvider` when `config.llm.enabled` is true and canonical `StrategySpec.build_command` data.

- [ ] **Step 1: Add failing setup-boundary tests**

Create `tests/unit/test_controlled_delivery_setup.py` with focused tests using the existing coordinator fixtures:

```python
def test_delivery_without_llm_provider_blocks_before_ralph(coordinator, intent, monkeypatch):
    coordinator._config.llm.enabled = False
    monkeypatch.setattr("harness.coordinator.RalphController.run_loop",
                        lambda *args, **kwargs: pytest.fail("Ralph must not start"))
    result = coordinator.run(intent)
    assert result.status == "blocked"
    assert result.termination_reason == "delivery_configuration_invalid"


def test_noncanonical_strategy_blocks_before_ralph(coordinator, intent, monkeypatch):
    coordinator._strategies["default"] = StrategySpec(build_command="custom build")
    monkeypatch.setattr("harness.coordinator.RalphController.run_loop",
                        lambda *args, **kwargs: pytest.fail("Ralph must not start"))
    result = coordinator.run(intent)
    assert result.status == "blocked"
    assert "echelon build" in coordinator.state_for("default")["diagnostic"]
```

Adapt fixture names to the existing coordinator helper API rather than introducing a second harness fixture.

- [ ] **Step 2: Run the setup tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_visual_ralph.py \
  tests/unit/test_cli_harness_resume.py
```

Expected: missing-provider delivery reaches legacy fallback, and the new error type does not exist.

- [ ] **Step 3: Add the explicit configuration error and simplify prompt setup**

Create:

```python
class DeliveryConfigurationError(RuntimeError):
    """Delivery cannot start or resume under the active controller contract."""
```

In `StrategyCoordinator`:

- require `llm_provider` before implementation work starts;
- require `spec.build_command.split() == ["echelon", "build"]`;
- make `get_build_prompt()` return the assembled `arguments`, plus review re-entry context when present;
- remove `resolve_delivery_build_prompt`, `prompt_error`, and every feature-flag token-accounting branch;
- catch `DeliveryConfigurationError` and persist `delivery_configuration_invalid` with its diagnostic.

Update `VisualRalphController` and its test to catch the new error type from a
controller callback. Remove its direct `echelon build --fix` fallback: when no
controller feedback callback is configured, return a
`delivery_configuration_invalid` result without invoking the sandbox provider.

- [ ] **Step 4: Run coordinator and continuation tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_visual_ralph.py \
  tests/unit/test_coordinator_review_reentry.py \
  tests/integration/test_controlled_review_reentry.py
```

Expected: all pass.

- [ ] **Step 5: Commit controller-only setup**

```bash
git add src/harness/delivery_errors.py src/harness/coordinator.py \
  src/harness/visual_ralph.py tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_visual_ralph.py tests/unit/test_cli_harness_resume.py
git commit -m "refactor: make delivery setup controller only"
```

### Task 3: Remove Ralph's legacy build and repair branches

**Files:**

- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_ralph_outer.py`
- Modify: `tests/unit/test_ralph_inner.py`
- Modify: `tests/unit/test_delivery_controller_integration.py`
- Modify: `tests/unit/test_delivery_source_feedback.py`
- Modify: `tests/unit/test_controlled_fulfillment_delivery.py`
- Modify: `tests/unit/test_delivery_documentation_integration.py`
- Test: `tests/integration/test_polyrepo_delivery_convergence.py`

**Interfaces:**

- Consumes: `DeliverySliceRunner`, `DeliveryDocumentationRunner`, `FulfillmentRunner(controlled=True)`, and the existing `BuildResult` adapter boundary.
- Produces: `_exec_build(...)` and `_exec_feedback(...)` that always return controlled slice results.
- Removes: constructor injection and state for `LlmBuildRunner`, metadata-only task recovery, shell build/fix fallback, and feature-off gate behavior.

- [ ] **Step 1: Replace feature-off assertions with sole-path assertions**

Delete `test_feature_off_keeps_legacy_feedback_contract` and tests whose only subject is marker-based `LlmBuildRunner` behavior. Add this assertion through the existing slice fixture:

```python
def test_build_and_feedback_never_execute_strategy_shell(slice_project, tmp_path):
    controller, provider = make_controller(slice_project, tmp_path)
    provider.exec.side_effect = AssertionError("strategy shell execution is retired")

    build = controller._exec_build(None, "echelon build", "", str(slice_project), "context")
    feedback = controller._exec_feedback(
        None, failing_verify_result(), "echelon build", "", str(slice_project), "context"
    )

    assert build["completion_marker_explicit"] is True
    assert feedback["completion_marker_explicit"] is True
    provider.exec.assert_not_called()
```

Use the existing fixture/helper names in each test module. Remove assignments that enable or disable `delivery_gate_controller`; controlled behavior is now the fixture default.

- [ ] **Step 2: Run the focused Ralph tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_source_feedback.py \
  tests/unit/test_controlled_fulfillment_delivery.py \
  tests/unit/test_delivery_documentation_integration.py
```

Expected: flag-free fixtures still enter legacy branches or fail to create controlled fulfillment.

- [ ] **Step 3: Make every Ralph gate controlled**

In `RalphController`:

- remove the `llm_build_runner` constructor parameter, import, attribute, and construction;
- construct `FulfillmentRunner(llm_provider, controlled=True)` whenever a provider exists;
- validate pending controlled worktrees without consulting a feature switch;
- remove the switch guard in `_exec_controlled_slice`;
- make `_exec_build` directly call `_exec_controlled_slice(..., repair=False)`;
- make `_exec_feedback` always construct typed source-repair or documentation evidence and call `_exec_controlled_slice(..., repair=True)`;
- remove `_recover_missing_task_ids`, `_with_harness_context`, and `_llm_build_prompt_metadata` when their final callers disappear;
- select host verification using `_llm_provider is not None` and pass `allow_legacy_structured=False`;
- make controlled runnability, documentation, progress, and fulfillment accounting unconditional;
- retain `_make_feedback_prompt` only where it builds controller context, not a completion recipe.

Do not remove shared `BuildResult` constants or recovery cleanup while controlled delivery still imports them.

- [ ] **Step 4: Convert or delete legacy-only Ralph tests**

In `test_ralph_outer.py` and `test_ralph_inner.py`, delete cases that inject `LlmBuildRunner`, synthesize `.harness-build-status.json`, recover `echelon_result.json`, or expect sandbox execution of `echelon build --fix`. Preserve tests for loop limits, dirty-worktree adjudication, verification, progress, recovery, and finalization by routing their build result through the controlled slice seam.

- [ ] **Step 5: Run the full Ralph and controlled-delivery group**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_source_feedback.py \
  tests/unit/test_controlled_fulfillment_delivery.py \
  tests/unit/test_delivery_documentation_integration.py \
  tests/unit/test_fulfillment_runner.py \
  tests/integration/test_polyrepo_delivery_convergence.py
```

Expected: all pass without `LlmBuildRunner` imports or flag mutation.

- [ ] **Step 6: Commit the sole Ralph path**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py \
  tests/unit/test_ralph_inner.py tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_source_feedback.py \
  tests/unit/test_controlled_fulfillment_delivery.py \
  tests/unit/test_delivery_documentation_integration.py \
  tests/integration/test_polyrepo_delivery_convergence.py
git commit -m "refactor: make Ralph delivery controller only"
```

### Task 4: Delete the unreachable legacy delivery implementation

**Files:**

- Delete: `src/harness/llm_build_runner.py`
- Delete: `src/harness/delivery_prompt.py`
- Delete: `tests/unit/test_llm_build_runner.py`
- Delete: `tests/unit/test_delivery_prompt.py`
- Delete: `prosaic/commands/echelon.build.md`
- Delete: `runtime/workflow/phases/build-1-init.md`
- Delete: `runtime/workflow/phases/build-2-implement.md`
- Delete: `runtime/workflow/phases/build-3-spec-guard.md`
- Delete: `runtime/workflow/phases/build-4-code-review.md`
- Delete: `runtime/workflow/phases/build-5-test-guard.md`
- Delete: `runtime/workflow/phases/build-6-progress.md`
- Delete: `runtime/workflow/phases/build-7-integration.md`
- Delete: `runtime/workflow/phases/build-8-documentation.md`
- Delete: `runtime/workflow/phases/build-8-verify-docs.md`
- Delete: `runtime/workflow/phases/build-8-finalize.md`
- Delete: `runtime/workflow/phases/appendices/build-8-feedback-reference.md`
- Delete: `runtime/workflow/phases/appendices/build-8-summary-reference.md`
- Delete: `runtime/workflow/phases/appendices/build-8-verify-gates.md`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `src/harness/skill_loader.py`
- Create: `tests/unit/test_controlled_delivery_boundary.py`
- Modify/Delete: prompt- and build-graph-only tests under `tests/kernel/`, `tests/contract/`, `tests/echelon-validation/`, and `tests/unit/`

**Interfaces:**

- Produces: a static boundary proving the legacy modules, raw prompt, and command-driven build phase graph are absent.
- Preserves: the six `echelon.delivery-*` role bodies and every Python-controlled delivery contract.

- [ ] **Step 1: Add the static deletion test**

Create:

```python
def test_legacy_delivery_execution_is_absent():
    root = Path(__file__).resolve().parents[2]
    retired = [
        "src/harness/llm_build_runner.py",
        "src/harness/delivery_prompt.py",
        "prosaic/commands/echelon.build.md",
        "runtime/workflow/phases/build-1-init.md",
        "runtime/workflow/phases/build-8-finalize.md",
    ]
    assert [path for path in retired if (root / path).exists()] == []

    production = "\n".join(
        path.read_text(encoding="utf-8")
        for base in (root / "src", root / "runtime")
        for path in base.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml"}
    )
    assert "delivery_gate_controller" not in production
    assert "LlmBuildRunner" not in production
    assert "resolve_delivery_build_prompt" not in production
```

- [ ] **Step 2: Run the boundary test and verify it fails**

Run: `.venv/bin/python -m pytest -q tests/unit/test_controlled_delivery_boundary.py`

Expected: the retired files and identifiers are reported.

- [ ] **Step 3: Delete the legacy modules, raw command, and build graph**

Delete every file listed above. Remove the legacy build phase nodes from `runtime/workflow/definition.yaml`, but retain the Python-owned delivery-role registration comments and rewrite them as the sole delivery sequence. Remove build-command skill mapping helpers from `src/harness/skill_loader.py` once no production caller remains.

- [ ] **Step 4: Remove tests that exclusively validate the deleted graph**

Delete `test_llm_build_runner.py`, `test_delivery_prompt.py`, `test_build_prompt.py`, `test_build_quality_gate_sequence.py`, and the build-only Echelon-validation modules. In mixed suites such as `test_prompt_references.py`, `test_prompt_tool_contracts.py`, `test_phase_graph.py`, `test_cli_polyrepo_runtime_extension.py`, `test_gitops_worktree.py`, and `test_squad_controller.py`, remove only cases and fixtures whose subject is the retired `echelon.build` command or `build-*` phase graph. Keep tests for active spec, RE, controlled delivery, and workspace-copy behavior.

Update `tests/contract/static_contracts.py` so the active contract inventory no longer opens the deleted build prompt or phases.

- [ ] **Step 5: Run structural and controlled-delivery tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_controlled_delivery_boundary.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_prompt_references.py \
  tests/unit/test_prompt_tool_contracts.py \
  tests/unit/test_cli_polyrepo_runtime_extension.py \
  tests/unit/test_gitops_worktree.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_delivery_controller_integration.py
```

Expected: all pass; repository search finds no active import or runtime reference to the retired modules or feature flag.

- [ ] **Step 6: Commit the legacy deletion**

```bash
git add -A src/harness runtime/workflow prosaic/commands tests
git commit -m "refactor: delete legacy delivery execution"
```

### Task 5: Align current guidance and close S2

**Files:**

- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `prosaic/commands/echelon.change.md`
- Modify: `prosaic/commands/echelon.feedback.md`
- Modify: `prosaic/subagents/echelon.engineering-manager.md`
- Modify: `prosaic/subagents/echelon.sentinel.md`
- Modify: `docs/element-identity-convergence-boundary.md`
- Modify: `docs/simplification-control.md`

**Interfaces:**

- Produces: current user and maintainer guidance naming `echelon delivery run` as the only delivery entry point.
- Produces: S2 completion evidence and activates S3 only after verification passes.

- [ ] **Step 1: Rewrite current guidance**

Describe controlled delivery without a feature flag. Replace raw `echelon build` instructions with `echelon delivery run <id>`, remove the command-driven build phase description, and distinguish the retained internal strategy identifier from a CLI invocation. Leave dated findings/specs/plans and changelog history unchanged.

- [ ] **Step 2: Run active-surface searches**

Run:

```bash
rg -n 'delivery_gate_controller|LlmBuildRunner|resolve_delivery_build_prompt' \
  src runtime AGENTS.md CLAUDE.md README.md prosaic
rg -n 'echelon build' AGENTS.md CLAUDE.md README.md prosaic src runtime
```

Expected: first command has no matches. The second contains only the documented internal strategy identifier or explicit migration error, never an executable instruction.

- [ ] **Step 3: Run the focused S2 suite**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_llm_tool_policy.py \
  tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_controlled_delivery_boundary.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_source_feedback.py \
  tests/unit/test_controlled_fulfillment_delivery.py \
  tests/unit/test_delivery_documentation_integration.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_visual_ralph.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py
```

Expected: all pass.

- [ ] **Step 4: Run repository merge verification**

Run:

```bash
.venv/bin/python scripts/merge_verification.py plan --base 42497d25
.venv/bin/python scripts/merge_verification.py run --base 42497d25
```

Expected: the planned repository gate passes and writes a receipt under `tests/reports/merge-verification/`.

- [ ] **Step 5: Record evidence and advance the control sheet**

In `docs/simplification-control.md`, mark every S2 work item complete, record focused counts and the merge-verification receipt, change S2 to `DONE`, and change S3 to `ACTIVE` with its next inventory action. Do not activate S3 if verification fails.

- [ ] **Step 6: Commit the verified milestone**

```bash
git add AGENTS.md CLAUDE.md README.md prosaic docs/simplification-control.md \
  docs/element-identity-convergence-boundary.md tests/reports/merge-verification
git commit -m "docs: close controlled delivery cutover"
```
