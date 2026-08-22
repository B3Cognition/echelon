# Stack Context Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject incompatible deployed Phase A runtimes before side effects and give every provider prompt immutable selected-stack and clarification context.

**Architecture:** The public runtime guard validates a versioned workflow contract and every reachable Phase A checkpoint policy. Fresh runs create one stack contract from resolved definitions and store the semantic data and stack-guidance bytes in state; prompts render only that stored contract plus the controller-owned clarification receipt.

**Tech Stack:** Python, pytest, YAML workflow definitions, Echelon Phase A controller.

**Spec:** `docs/superpowers/specs/2026-08-22-stack-context-regression-design.md`

## Global Constraints

- Validate before target initialization, run-state creation, or provider construction.
- Continuations never reread mutable stack configuration or files as authority.
- Normal, staged-parallel, conditional, and judgment prompt paths receive identical controller-owned stack and clarification context.
- Persist only allowlisted diagnostic codes for invalid provider human-input payloads.

---

### Task 1: Runtime compatibility guard — completed

**Files:**
- Modify: `runtime/workflow/definition.yaml`, `src/harness/workflow_validator.py`, `src/echelon/cli.py`
- Test: `tests/kernel/test_phase_graph.py`, `tests/unit/test_cli_workspace.py`

**Interfaces:** `validate_workflow_definition(path: Path)` rejects absent compatibility metadata and missing checkpoint/rewind pairs. `_installed_phase_runtime_or_exit(project_root: Path)` validates before `_cmd_run`.

- [ ] **Step 1: Write failing tests**

```python
assert not validate_workflow_definition(path_without_policies).ok
monkeypatch.setattr(cli, "_prepare_spec_target_repo", fail_if_called)
with pytest.raises(SystemExit):
    cli._cmd_spec_run(["hello", "--target", "sources/demo", "--init"])
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/kernel/test_phase_graph.py tests/unit/test_cli_workspace.py -q`

Expected: the new assertions fail because the compatibility guard is missing.

- [ ] **Step 3: Implement the minimum guard**

```python
CONTROLLER_RUNTIME_COMPATIBILITY_VERSION = 1
if raw.get("controller_runtime_compatibility_version") != CONTROLLER_RUNTIME_COMPATIBILITY_VERSION:
    issues.append(WorkflowValidationIssue("unsupported controller runtime compatibility version", path=path))
for phase_id in phase_a_phase_ids(graph):
    validate_checkpoint_and_rewind(graph.get(phase_id), phase_id, issues, path)
```

Call the validator from `_installed_phase_runtime_or_exit`; its failure prints `echelon workspace migrate-to-prosaic`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/kernel/test_phase_graph.py tests/unit/test_cli_workspace.py -q`

Commit: `git commit -am "fix: reject incompatible phase runtime before spec run"`

### Task 2: Immutable semantic stack contract — completed

**Files:**
- Create: `src/harness/stack_contract.py`
- Modify: `src/echelon/cli.py`, `src/harness/squad.py`
- Test: `tests/unit/test_stack_contract.py`, `tests/integration/test_squad_controller.py`

**Interfaces:** `build_stack_contract(project_root: Path, definitions: Mapping[str, StackDefinition]) -> dict[str, object]` captures explicit/effective/resolved IDs, capabilities, tools, requirements, per-stack identity fields, and `{path, sha256, content}` context records. `render_stack_contract(state) -> str` reads no workspace files.

- [ ] **Step 1: Write failing contract and continuation tests**

```python
contract = build_stack_contract(tmp_path, definitions)
assert contract["resolved_ids"] == ["web", "ui"]
assert contract["context_files"][0]["content"] == "Use accessible components."
state_store.save({"stack_contract": {"resolved_ids": ["frozen"]}})
controller.initialize_if_needed()
assert state_store.load()["stack_contract"]["resolved_ids"] == ["frozen"]
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/unit/test_stack_contract.py tests/integration/test_squad_controller.py -q`

Expected: imports or missing state assertions fail.

- [ ] **Step 3: Implement and persist only for fresh runs**

```python
return {"schema_version": 1, "explicit_ids": selection.explicit,
        "effective_ids": selection.effective, "resolved_ids": resolved.resolved_ids,
        "context_files": frozen_context_files(resolved.context_files), ...}
```

Bound each trusted context file explicitly; refuse initialization rather than truncating semantic guidance. Build the contract in CLI only when the selected run is fresh, pass it into `SquadController`, and preserve an existing state value on continuation.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/unit/test_stack_contract.py tests/integration/test_squad_controller.py -q`

Commit: `git commit -am "fix: persist immutable stack contract for spec runs"`

### Task 3: Shared provider context — completed

**Files:**
- Modify: `src/harness/squad_executors.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:** `_render_controller_owned_prompt_context(state) -> str` composes `render_stack_contract(state)` and a read of the controller-owned clarification receipt. It is called by `AgentExecutor`, `StagedParallelExecutor`, and `ConditionalSequentialExecutor`; any judgment prompt builder is covered explicitly.

- [ ] **Step 1: Write failing prompt-path tests**

```python
prompt = build_prompt_for_dispatch(state_with_stack_and_receipt)
assert "Selected Stack Contract" in prompt
assert "Use accessible components." in prompt
assert "Provide a web page" in prompt
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/integration/test_squad_controller.py -q -k 'stack_contract or clarification_receipt'`

Expected: the stack or clarification assertions fail.

- [ ] **Step 3: Implement shared rendering and use it at every provider dispatch**

```python
def _render_controller_owned_prompt_context(state):
    return _render_stack_contract_context(state) + _render_clarification_receipt_context(state)
```

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/integration/test_squad_controller.py -q -k 'stack_contract or clarification_receipt'`

Commit: `git commit -am "fix: provide stack and clarification context to all agents"`

### Task 4: Safe human-input diagnostic — completed

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_human_input_routing.py`

**Interfaces:** `_human_input_policy_error_code(error: HumanInputPolicyError) -> str` returns a fixed allowlisted code.

- [ ] **Step 1: Write failing diagnostic test**

```python
registry.prepare.side_effect = HumanInputPolicyError("untrusted answer: secret")
controller.advance(...)
assert state["controller_diagnostic"]["reason_code"] == "human_input_policy_invalid"
assert "secret" not in json.dumps(state["controller_diagnostic"])
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/integration/test_human_input_routing.py -q -k 'provider_human_input and diagnostic'`

Expected: the generic diagnostic has no allowlisted policy code.

- [ ] **Step 3: Implement fixed-code mapping**

```python
def _human_input_policy_error_code(error):
    return "human_input_policy_invalid"
```

Pass that value only through the existing controller diagnostic machinery.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/integration/test_human_input_routing.py -q -k 'provider_human_input and diagnostic'`

Commit: `git commit -am "fix: retain safe human input policy diagnostics"`

### Task 5: Regression verification

**Files:**
- Modify: `docs/superpowers/plans/2026-08-22-stack-context-regression.md`

- [ ] **Step 1: Run the full focused regression suite**

Run: `pytest tests/kernel/test_phase_graph.py tests/unit/test_cli_workspace.py tests/unit/test_stack_contract.py tests/integration/test_squad_controller.py tests/integration/test_human_input_routing.py -q`

Expected: exit code 0.

- [ ] **Step 2: Run static checks**

Run: `uv run ruff check src/harness/stack_contract.py src/harness/squad.py src/harness/squad_executors.py src/echelon/cli.py`

Expected: exit code 0.

- [ ] **Step 3: Mark the verified steps and commit the record**

Commit: `git add docs/superpowers/plans/2026-08-22-stack-context-regression.md && git commit -m "docs: record stack context regression verification"`
