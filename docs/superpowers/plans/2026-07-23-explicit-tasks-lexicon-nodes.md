# Explicit Tasks Lexicon Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hidden post-dispatch tasks-Lexicon hook with two visible,
provider-free, independently checkpointed workflow nodes.

**Architecture:** Extract the existing tasks validation into a focused
`run_tasks_lexicon_gate()` service, dispatch it through the existing
`DeterministicLexiconExecutor`, and route both initial planning and post-PLAN2
output through explicit graph nodes. Remove the hidden controller hook in the
same implementation and retain the existing state fields, report schema,
configuration, repair owner, checkpoint subsystem, and spec-Lexicon behavior.

**Tech Stack:** Python 3.12, dataclasses, pathlib, PyYAML workflow definitions,
pytest, Git-backed Phase A checkpoints.

## Global Constraints

- Do not add a compatibility switch, shadow mode, or duplicate execution path.
- Do not create a generic gate framework or a new executor type.
- Do not split `phase3-consensus` or any agent role.
- Do not change TASKS grammar, finding codes, report schema version 1, Lexicon
  configuration keys, thresholds, or defaults.
- Preserve `tasks_lexicon_pass`, `tasks_lexicon_attempts`,
  `tasks_lexicon_findings`, and `tasks_lexicon_report`.
- Add only the controller-owned `tasks_lexicon_action` enum:
  `proceed`, `repair`, `proceed_with_warning`, or `block`.
- Provider agents must not write `tasks_lexicon_*` state.
- Both new nodes must use `type: deterministic_lexicon` and
  `lexicon_artifact: tasks`.
- Both new nodes must use normal state advancement, telemetry, manual phase
  execution, and the existing checkpoint mechanism.
- Hard exhaustion must transition normally to `terminal-blocked` so the final
  report and state are checkpointed.
- Keep the existing spec-Lexicon behavior and tests unchanged.
- Use `.venv/bin/pytest`; the system Python does not have the repository's
  PyYAML dependency.
- Commit only files owned by the current task. Preserve the existing untracked
  review file under `docs/findings/`.

---

## File Structure

### New files

- `src/harness/tasks_lexicon_gate.py` — deterministic tasks validation, report
  creation, attempt/exhaustion calculation, and immutable result.
- `src/harness/lexicon_gate_io.py` — the existing narrow atomic JSON report
  writer shared by spec and tasks Lexicon services.
- `tests/unit/test_tasks_lexicon_gate.py` — service-level behavior and report
  compatibility.

### Modified files

- `src/harness/spec_lexicon_gate.py` — import the shared atomic JSON writer;
  no behavior change.
- `src/harness/squad_executors.py` — dispatch `lexicon_artifact: tasks` through
  the new service.
- `src/harness/squad.py` — add iterative node IDs and remove the hidden tasks
  validation path.
- `extension/workflow/definition.yaml` — add the two nodes, rewire PLAN and
  consensus, and move certification state ownership.
- `extension/workflow/phases/phase3-plan.md` — describe the visible gate and
  remove agent-owned attempt reporting.
- `extension/workflow/phases/phase3-consensus.md` — describe the visible
  post-PLAN2 gate.
- `extension/agents/solution/orchestrator.md` — prohibit all tasks
  certification fields, including attempt count.
- `tests/kernel/test_phase_graph.py` — exact node and state ownership contracts.
- `tests/kernel/test_workflow_validator.py` — deterministic transition-field
  coverage.
- `tests/kernel/test_squad_executors_journal.py` — provider-free executor and
  prompt-contract coverage.
- `tests/integration/test_squad_controller.py` — pass, repair, warning, block,
  and consensus routing.
- `tests/unit/test_tasks_wiring.py` — visible-node wiring and prompt wording.
- `tests/unit/test_product_inputs.py` — retain report-driven repair context
  while removing provider attempt ownership.
- `tests/unit/test_squad_phase_checkpoints.py` — exact checkpoint destinations.
- `tests/unit/test_cli_phase.py` — manual execution of both provider-free nodes.
- `CHANGELOG.md` — operator-visible workflow change under `[Unreleased]`.

---

### Task 1: Extract the Deterministic Tasks Lexicon Service

**Files:**

- Create: `src/harness/lexicon_gate_io.py`
- Create: `src/harness/tasks_lexicon_gate.py`
- Create: `tests/unit/test_tasks_lexicon_gate.py`
- Modify: `src/harness/spec_lexicon_gate.py`

**Interfaces:**

- Consumes:
  `lexicon_gate` resolved configuration, `spec_dir`, previous tasks repair
  attempts, and workflow iteration limits.
- Produces:
  `TasksLexiconGateResult.state_updates() -> dict[str, object]` and the
  keyword-only `run_tasks_lexicon_gate` entry point described below.
- Later tasks rely on:

  ```python
  TASKS_LEXICON_ACTIONS: frozenset[str]

  @dataclass(frozen=True)
  class TasksLexiconGateResult:
      action: str
      passed: bool
      attempts: int
      findings: int
      report_path: Path | None
      blocked_reason: str | None
      detail: str

      def state_updates(self) -> dict[str, object]:
          updates: dict[str, object] = {
              "tasks_lexicon_action": self.action,
              "tasks_lexicon_pass": self.passed,
              "tasks_lexicon_attempts": self.attempts,
              "tasks_lexicon_findings": self.findings,
          }
          if self.report_path is not None:
              updates["tasks_lexicon_report"] = str(self.report_path)
          if self.blocked_reason:
              updates["blocked_reason"] = self.blocked_reason
          return updates
  ```

  `run_tasks_lexicon_gate` has keyword-only parameters
  `project_root: Path`, `spec_dir_ref: str`,
  `config: Mapping[str, object]`, `previous_attempts: object`,
  `workflow_iteration: object`, and `max_workflow_iterations: object`, and
  returns `TasksLexiconGateResult`.

  `write_json_atomic` accepts `path: Path` and
  `payload: Mapping[str, object]` and returns `None`.

- [ ] **Step 1: Write failing service tests**

Create `tests/unit/test_tasks_lexicon_gate.py` with helpers that write a valid
plan fixture and resolved configuration:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.tasks_lexicon_gate import run_tasks_lexicon_gate


def _config(*, enabled: bool = True, on_exhausted: str = "block") -> dict:
    return {
        "lexicon_gate": {
            "enabled": True,
            "max_repair_attempts": 3,
            "on_exhausted": on_exhausted,
            "glossary_file": "glossary.md",
            "artifacts": {
                "tasks": {
                    "enabled": enabled,
                    "path": "tasks.md",
                    "spec_ref": "requirements.lexicon.md",
                    "report": "tasks-lexicon-report.json",
                }
            },
        }
    }


def _write_valid_plan(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    (spec_dir / "requirements.lexicon.md").write_text(
        "ARTIFACT: SPEC\nTITLE: Demo\nREQ: FR-001\n"
        "GIVEN: input exists\nWHEN: processing starts\n"
        "THEN: The system SHALL return output\nOUTPUT: output\n"
        "DEPENDS: none\nEXAMPLE: none\n",
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(
        "TASK: T001\nPHASE: setup\nREQUIREMENTS: FR-001\n"
        "TARGET: sources/app\nDEPENDS: none\n"
        "FILES: sources/app/main.py\n"
        "TEST: tests/test_main.py::test_output\n"
        "DO: Implement output\nDONE: Test passes\n",
        encoding="utf-8",
    )
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "targets.yml").write_text(
        "targets:\n  - sources/app\n",
        encoding="utf-8",
    )


def test_valid_tasks_pass_and_reset_attempts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)

    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="specs/001-demo",
        config=_config(),
        previous_attempts=2,
        workflow_iteration=0,
        max_workflow_iterations=5,
    )

    assert result.action == "proceed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0
    assert json.loads(result.report_path.read_text())["schema_version"] == 1


def test_invalid_tasks_request_repair_and_increment_attempts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text("not TASKS grammar\n", encoding="utf-8")

    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref=str(spec_dir),
        config=_config(),
        previous_attempts=1,
        workflow_iteration=0,
        max_workflow_iterations=5,
    )

    assert result.action == "repair"
    assert result.passed is False
    assert result.attempts == 2
    report = json.loads(result.report_path.read_text())
    assert report["ok"] is False
    assert any(item["code"] == "parse-error" for item in report["findings"])


@pytest.mark.parametrize(
    ("on_exhausted", "expected"),
    [("warn", "proceed_with_warning"), ("block", "block")],
)
def test_exhaustion_policy_is_explicit(
    tmp_path: Path,
    on_exhausted: str,
    expected: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text("invalid\n", encoding="utf-8")

    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref=str(spec_dir),
        config=_config(on_exhausted=on_exhausted),
        previous_attempts=2,
        workflow_iteration=0,
        max_workflow_iterations=5,
    )

    assert result.action == expected
    assert result.attempts == 3
    assert result.passed is False


def test_missing_controller_context_blocks_without_attempt(tmp_path: Path) -> None:
    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="",
        config=_config(),
        previous_attempts=2,
        workflow_iteration=0,
        max_workflow_iterations=5,
    )

    assert result.action == "block"
    assert result.attempts == 2
    assert result.report_path is None
    assert result.blocked_reason == "tasks_lexicon_spec_dir_missing"
```

Add parametrized cases for disabled gates, every required plan artifact,
configured paths, target ownership findings, validator exceptions, iteration
exhaustion, and report-write failure. Assert exact existing finding codes and
schema keys.

- [ ] **Step 2: Run the service tests to verify they fail**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_tasks_lexicon_gate.py
```

Expected: collection fails with
`ModuleNotFoundError: No module named 'harness.tasks_lexicon_gate'`.

- [ ] **Step 3: Extract the existing atomic writer**

Create `src/harness/lexicon_gate_io.py`:

```python
"""Narrow persistence helpers shared by deterministic Lexicon gates."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
```

In `src/harness/spec_lexicon_gate.py`, import this function, replace
`_write_json_atomic(report_path, report)` with
`write_json_atomic(report_path, report)`, and delete the private writer plus its
now-unused `json`, `os`, and `tempfile` imports only if they have no other
callers.

- [ ] **Step 4: Implement the tasks service**

Create `src/harness/tasks_lexicon_gate.py` with the result contract:

```python
"""Provider-free certification of the configured tasks Lexicon artifact."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from harness.lexicon_gate_io import write_json_atomic

TASKS_LEXICON_ACTIONS = frozenset(
    {"proceed", "repair", "proceed_with_warning", "block"}
)


@dataclass(frozen=True)
class TasksLexiconGateResult:
    action: str
    passed: bool
    attempts: int
    findings: int
    report_path: Path | None = None
    blocked_reason: str | None = None
    detail: str = ""

    def state_updates(self) -> dict[str, object]:
        updates: dict[str, object] = {
            "tasks_lexicon_action": self.action,
            "tasks_lexicon_pass": self.passed,
            "tasks_lexicon_attempts": self.attempts,
            "tasks_lexicon_findings": self.findings,
        }
        if self.report_path is not None:
            updates["tasks_lexicon_report"] = str(self.report_path)
        if self.blocked_reason:
            updates["blocked_reason"] = self.blocked_reason
        return updates
```

Implement `run_tasks_lexicon_gate()` by moving the body of
`SquadController._validate_tasks_gate_artifacts()` and its glossary parser into
this module. Preserve the existing report payload and finding dictionaries.
Use these exact action rules:

```python
if report["ok"]:
    action = "proceed"
    attempts = 0
else:
    attempts = _nonnegative_int(previous_attempts) + 1
    repair_cap = _nonnegative_int(gate.get("max_repair_attempts", 3))
    iteration = _nonnegative_int(workflow_iteration)
    iteration_cap = _nonnegative_int(max_workflow_iterations)
    exhausted = (
        (repair_cap > 0 and attempts >= repair_cap)
        or (iteration_cap > 0 and iteration >= iteration_cap)
    )
    if not exhausted:
        action = "repair"
    elif str(gate.get("on_exhausted", "block")).lower() == "warn":
        action = "proceed_with_warning"
    else:
        action = "block"
```

Return a passing bypass with attempts/findings zero when either gate is
disabled. Return `block` without incrementing attempts for missing `spec_dir`,
unsafe configured paths, or report persistence failures. Use
`blocked_reason="tasks_lexicon_evidence_write_failed"` for write failures and
include the exception in `detail`, not in the stable state code.

- [ ] **Step 5: Run service and spec-Lexicon regression tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_tasks_lexicon_gate.py \
  tests/unit/test_lexicon_gates.py
```

Expected: all tests pass and existing spec-Lexicon behavior is unchanged.

- [ ] **Step 6: Commit the service extraction**

```bash
git add \
  src/harness/lexicon_gate_io.py \
  src/harness/spec_lexicon_gate.py \
  src/harness/tasks_lexicon_gate.py \
  tests/unit/test_tasks_lexicon_gate.py
git commit -m "refactor: extract deterministic tasks lexicon service"
```

---

### Task 2: Reuse the Existing Deterministic Lexicon Executor

**Files:**

- Modify: `src/harness/squad_executors.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**

- Consumes:
  `PhaseNode.lexicon_artifact`, resolved config, and state values.
- Produces:
  the existing `SquadAgentResult` envelope with controller-owned updates.
- Preserves:
  `lexicon_artifact: spec` behavior exactly.

- [ ] **Step 1: Write failing executor tests**

Add a helper node and test to
`tests/kernel/test_squad_executors_journal.py`:

```python
def test_deterministic_tasks_lexicon_executor_is_provider_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = PhaseNode(
        id="phase3-tasks-lexicon",
        type="deterministic_lexicon",
        lexicon_artifact="tasks",
        allowed_state_updates=[],
        controller_state_updates=[
            "tasks_lexicon_action",
            "tasks_lexicon_pass",
            "tasks_lexicon_attempts",
            "tasks_lexicon_findings",
            "tasks_lexicon_report",
            "blocked_reason",
        ],
    )
    store = SquadStateStore(tmp_path / "runs" / "run-test")
    store.initialize("run-test", "brownfield", "demo", 0, node.id)
    observed = {}

    def fake_gate(**kwargs):
        observed.update(kwargs)
        return TasksLexiconGateResult(
            action="proceed",
            passed=True,
            attempts=0,
            findings=0,
            detail="tasks gate disabled",
        )

    monkeypatch.setattr(
        "harness.squad_executors.run_tasks_lexicon_gate",
        fake_gate,
    )
    executor = DeterministicLexiconExecutor(
        graph,
        EXT_ROOT,
        tmp_path,
        store.squad_dir,
    )

    result = executor.execute(node, store)

    assert result.verdict == "DONE"
    assert result.state_updates["tasks_lexicon_action"] == "proceed"
    assert observed["project_root"] == tmp_path
```

Keep the existing unsupported-artifact test, proving malformed node contracts
still return `BLOCKED`.

- [ ] **Step 2: Run the executor test to verify it fails**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  -k "deterministic_tasks_lexicon or deterministic_lexicon"
```

Expected: failure because `run_tasks_lexicon_gate` is not dispatched.

- [ ] **Step 3: Implement artifact dispatch**

Import:

```python
from harness.tasks_lexicon_gate import run_tasks_lexicon_gate
```

Refactor `DeterministicLexiconExecutor.execute()` to resolve config once and
branch explicitly:

```python
artifact = str(getattr(node, "lexicon_artifact", "") or "")
state = state_store.load()
config = get_full_resolved_config(
    self._project_root,
    fallback_config_path=self._ext_dir / "echelon-config.yml",
)

if artifact == "spec":
    gate = run_spec_lexicon_gate(
        project_root=self._project_root,
        spec_dir_ref=str(state.get("spec_dir") or ""),
        config=config,
        previous_attempts=state.get("lexicon_attempts", 0),
    )
    updates = gate.state_updates()
    label = f"spec Lexicon {gate.evaluation}: {gate.detail}"
    marker = "✓" if gate.passed is True else "~" if gate.passed is None else "✗"
elif artifact == "tasks":
    gate = run_tasks_lexicon_gate(
        project_root=self._project_root,
        spec_dir_ref=str(state.get("spec_dir") or ""),
        config=config,
        previous_attempts=state.get("tasks_lexicon_attempts", 0),
        workflow_iteration=state.get("iteration", 0),
        max_workflow_iterations=state.get("max_iterations", 0),
    )
    updates = gate.state_updates()
    label = f"tasks Lexicon {gate.action}: {gate.detail}"
    marker = "✓" if gate.action == "proceed" else "~" if gate.action in {
        "repair", "proceed_with_warning"
    } else "✗"
else:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "blocked_reason": (
                    f"deterministic Lexicon node {node.id!r} "
                    f"has unsupported artifact {artifact!r}"
                )
            },
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
```

Retain the existing spec pending-state cleanup. Print `label`, then return
`verdict: DONE` for every supported tasks action, including `block`, so graph
transition and checkpoint behavior remain normal.

- [ ] **Step 4: Run executor regressions**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py \
  -k "lexicon"
```

Expected: executor tests pass; existing controller tests may still exercise the
legacy hidden tasks hook until Task 4.

- [ ] **Step 5: Commit executor reuse**

```bash
git add \
  src/harness/squad_executors.py \
  tests/kernel/test_squad_executors_journal.py
git commit -m "feat: execute tasks lexicon through deterministic node"
```

---

### Task 3: Add and Validate the Two Workflow Nodes

**Files:**

- Modify: `extension/workflow/definition.yaml`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`
- Modify: `tests/unit/test_tasks_wiring.py`

**Interfaces:**

- Produces workflow IDs:
  `phase3-tasks-lexicon` and `phase3-consensus-tasks-lexicon`.
- Preserves consensus result fields:
  `why3-verdict`, `assess2-verdict`, `gate_decision`, and
  `phase_recommendation`.
- Both nodes produce the controller-owned tasks Lexicon state contract.

- [ ] **Step 1: Replace old graph tests with failing visible-node contracts**

In `tests/kernel/test_phase_graph.py`, replace
`test_phase3_plan_reserves_tasks_lexicon_verdict_for_the_controller()` with:

```python
def test_tasks_lexicon_runs_in_two_visible_provider_free_nodes():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    first = graph.get("phase3-tasks-lexicon")
    second = graph.get("phase3-consensus-tasks-lexicon")

    assert graph.get("phase3-plan").transitions == [
        {"to": first.id, "condition": "always"}
    ]
    assert graph.get("phase3-consensus").transitions == [
        {"to": second.id, "condition": "always"}
    ]
    for node in (first, second):
        assert node.type == "deterministic_lexicon"
        assert node.lexicon_artifact == "tasks"
        assert node.allowed_state_updates == []
        assert set(node.controller_state_updates) == {
            "tasks_lexicon_action",
            "tasks_lexicon_pass",
            "tasks_lexicon_attempts",
            "tasks_lexicon_findings",
            "tasks_lexicon_report",
            "blocked_reason",
        }


def test_provider_nodes_do_not_own_tasks_lexicon_state():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    plan = graph.get("phase3-plan")
    consensus = graph.get("phase3-consensus")

    assert not {
        key
        for key in (plan.allowed_state_updates or [])
        if key.startswith("tasks_lexicon_")
    }
    assert not {
        key
        for key in consensus.controller_state_updates
        if key.startswith("tasks_lexicon_")
    }
    plan2 = next(entry for entry in consensus.agents if entry["mode"] == "PLAN2")
    assert not {
        key
        for key in plan2["allowed_state_updates"]
        if key.startswith("tasks_lexicon_")
    }
```

Update `tests/unit/test_tasks_wiring.py` to assert the two exact node IDs and
the direct forward edges rather than old self-loop conditions.

- [ ] **Step 2: Run graph tests to verify they fail**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/unit/test_tasks_wiring.py
```

Expected: failures because the new nodes do not exist and provider nodes still
own tasks state.

- [ ] **Step 3: Add the first visible gate and rewire PLAN**

In `extension/workflow/definition.yaml`:

1. Remove tasks certification outputs and controller state from `phase3-plan`.
2. Remove `tasks_lexicon_attempts` from its `allowed_state_updates` and type
   declarations.
3. Replace its transitions with the unconditional edge to
   `phase3-tasks-lexicon`.
4. Insert `phase3-tasks-lexicon` before `phase3-understanding` using the node
   contract from the design.

Order transitions:

```yaml
transitions:
  - to: phase3-plan
    condition: "tasks_lexicon_action = repair"
    action: increment_iteration
  - to: terminal-blocked
    condition: "tasks_lexicon_action = block"
  - to: phase3-understanding
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning]"
```

- [ ] **Step 4: Add the post-consensus gate and move routing**

In the same workflow file:

1. Remove `tasks_lexicon_attempts` from PLAN2 and consensus contracts.
2. Remove tasks certification controller state from `phase3-consensus`.
3. Replace consensus transitions with the unconditional edge to
   `phase3-consensus-tasks-lexicon`.
4. Add the second gate after consensus.

Use this exact ordered transition structure:

```yaml
transitions:
  - to: phase3-plan
    condition: "tasks_lexicon_action = repair"
    action: increment_iteration
  - to: terminal-blocked
    condition: "tasks_lexicon_action = block"
  - to: phase1-what
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND quality_gates.fail AND iteration < max_iterations"
    action: increment_iteration
  - to: phase1-what
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND why3-verdict = FAIL AND iteration < max_iterations"
    action: increment_iteration
  - to: checkpoint-plan
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND why3-verdict = PASS AND assess2-verdict = PASS"
  - to: checkpoint-plan
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND gate_decision = accept_with_risk"
  - to: checkpoint-plan
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND phase_recommendation = advance_past_consensus_to_delivery"
  - to: phase3-how
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND assess2-verdict = REJECTED AND iteration < max_iterations"
    action: increment_iteration
  - to: checkpoint-plan
    condition: "tasks_lexicon_action in [proceed, proceed_with_warning] AND iteration >= max_iterations"
    action: force_convergence_warning
```

Splitting the existing accepted-risk OR condition into two equivalent ordered
transitions avoids adding parentheses or changing condition precedence.

- [ ] **Step 5: Register iterative dispatch behavior**

In `src/harness/squad.py`, add both node IDs to `ITERATIVE_PHASES`:

```python
"phase3-tasks-lexicon",
"phase3-consensus-tasks-lexicon",
```

Do not change checkpoint code.

- [ ] **Step 6: Run workflow validation**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_condition_evaluator.py \
  tests/unit/test_tasks_wiring.py
bash scripts/bash/dry-run.sh
```

Expected: all tests pass; dry-run reports a valid workflow and includes both
new phase IDs in graph-derived checks.

- [ ] **Step 7: Commit workflow nodes**

```bash
git add \
  extension/workflow/definition.yaml \
  src/harness/squad.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/unit/test_tasks_wiring.py
git commit -m "feat: add explicit tasks lexicon workflow nodes"
```

---

### Task 4: Remove the Hidden Gate and Preserve Repair Routing

**Files:**

- Modify: `src/harness/squad.py`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/workflow/phases/phase3-consensus.md`
- Modify: `extension/agents/solution/orchestrator.md`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/unit/test_product_inputs.py`
- Modify: `tests/unit/test_tasks_wiring.py`

**Interfaces:**

- Removes all implicit tasks validation from `_evaluate_transitions()`.
- Keeps `_render_task_requirement_mapping_context()` report-driven repair
  behavior.
- Routes solely through `tasks_lexicon_action`.

- [ ] **Step 1: Rewrite controller integration tests around visible nodes**

Replace tests that call `_evaluate_transitions(phase3-plan, result)` and expect
the controller to mutate `result.state_updates`. Execute the deterministic node
instead:

```python
def _run_tasks_gate(ctrl, store, phase_id):
    node = ctrl._graph.get(phase_id)
    result = ctrl._executors["deterministic_lexicon"].execute(node, store)
    next_phase = ctrl._evaluate_transitions(node, result)
    return node, result, next_phase


def test_tasks_gate_failure_redispatches_without_commander(tmp_path):
    ctrl, store = _controller(tmp_path)
    spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "requirements.lexicon.md").write_text(
        _valid_lexicon_spec(),
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
    state = store.load()
    state.update({
        "iteration": 0,
        "max_iterations": 3,
        "spec_dir": str(spec_dir.relative_to(tmp_path)),
    })
    store.save(state)

    with patch.object(
        ctrl,
        "_judgment_dispatch",
        side_effect=AssertionError("tasks gate must remain deterministic"),
    ):
        _, result, next_phase = _run_tasks_gate(
            ctrl,
            store,
            "phase3-tasks-lexicon",
        )

    assert next_phase == "phase3-plan"
    assert result.state_updates["tasks_lexicon_action"] == "repair"
    assert result.state_updates["tasks_lexicon_pass"] is False
    assert Path(result.state_updates["tasks_lexicon_report"]).is_file()
```

Add matching cases for:

- first gate pass;
- first gate warning;
- first gate hard block;
- second gate pass to `checkpoint-plan`;
- second gate repair to PLAN;
- second gate pass plus WHY3 failure to WHAT;
- second gate pass plus ASSESS2 rejection to HOW;
- second gate warning plus existing consensus routing;
- disabled tasks gate.

Every case patches `_judgment_dispatch` to raise.

- [ ] **Step 2: Run integration tests to verify the legacy implementation conflicts**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  -k "tasks_gate or tasks_lexicon or consensus_revalidates_tasks"
```

Expected: failures until the hidden hook is removed and all tests use visible
node outcomes.

- [ ] **Step 3: Delete the hidden controller path**

From `src/harness/squad.py`, delete:

```text
_enforce_tasks_lexicon_gate_result
_validate_tasks_gate_artifacts
_mark_tasks_lexicon_uncertified
_load_lexicon_glossary_terms
```

Remove:

```python
self._enforce_tasks_lexicon_gate_result(node, state, result)
```

from `_evaluate_transitions()`.

Remove `phase3-plan` and `phase3-consensus` from
`_lexicon_gate_must_block_on_exhaustion()`. Retain only the existing
`phase1-lexicon` entry and behavior. Remove `json` or other imports only when
repository search confirms no remaining caller.

- [ ] **Step 4: Update provider contracts and repair prompts**

In `extension/agents/solution/orchestrator.md`, replace the existing permission
for the agent to report `tasks_lexicon_attempts` while withholding
`tasks_lexicon_pass`.

with:

```text
ALWAYS let the provider-free tasks Lexicon node certify planning artifacts and
own all `tasks_lexicon_*` state.
NEVER report `tasks_lexicon_pass`, `tasks_lexicon_attempts`,
`tasks_lexicon_findings`, `tasks_lexicon_report`, or
`tasks_lexicon_action`.
```

In `phase3-plan.md`, state that PLAN always advances to
`phase3-tasks-lexicon`; remove the example `echelon_result` attempt update.

In `phase3-consensus.md`, state that completed PLAN2 advances to
`phase3-consensus-tasks-lexicon`, which certifies before consensus routing.

Keep `_render_task_requirement_mapping_context()` instructions to read the
controller report and repair tasks. Update tests to assert agents are told not
to report any tasks certification field.

- [ ] **Step 5: Add a static absence assertion**

In `tests/unit/test_tasks_wiring.py`:

```python
def test_tasks_lexicon_has_no_hidden_transition_hook():
    source = (ROOT / "src/harness/squad.py").read_text(encoding="utf-8")
    assert "_enforce_tasks_lexicon_gate_result" not in source
    assert "_validate_tasks_gate_artifacts" not in source
    assert "_mark_tasks_lexicon_uncertified" not in source
```

- [ ] **Step 6: Run controller and prompt-contract tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_product_inputs.py \
  tests/unit/test_tasks_wiring.py
```

Expected: all pass; no tasks certification is produced by a provider node or
hidden transition hook.

- [ ] **Step 7: Commit direct replacement**

```bash
git add \
  src/harness/squad.py \
  extension/agents/solution/orchestrator.md \
  extension/workflow/phases/phase3-plan.md \
  extension/workflow/phases/phase3-consensus.md \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_product_inputs.py \
  tests/unit/test_tasks_wiring.py
git commit -m "refactor: remove hidden tasks lexicon hook"
```

---

### Task 5: Prove Checkpoint, Recovery, and Release Behavior

**Files:**

- Modify: `tests/unit/test_squad_phase_checkpoints.py`
- Modify: `tests/unit/test_cli_phase.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Uses existing:
  `_checkpoint_successful_phase(phase, next_phase)`.
- Produces:
  checkpoint ledger entries keyed by each new phase ID.
- No new checkpoint API or state migration.

- [ ] **Step 1: Write failing checkpoint destination tests**

Add to `tests/unit/test_squad_phase_checkpoints.py`:

```python
import pytest


@pytest.mark.parametrize(
    ("phase", "next_phase"),
    [
        ("phase3-plan", "phase3-tasks-lexicon"),
        ("phase3-tasks-lexicon", "phase3-understanding"),
        ("phase3-tasks-lexicon", "phase3-plan"),
        ("phase3-consensus", "phase3-consensus-tasks-lexicon"),
        ("phase3-consensus-tasks-lexicon", "checkpoint-plan"),
        ("phase3-consensus-tasks-lexicon", "phase3-plan"),
        ("phase3-consensus-tasks-lexicon", "terminal-blocked"),
    ],
)
def test_tasks_lexicon_nodes_use_normal_phase_checkpoints(
    monkeypatch,
    tmp_path: Path,
    phase: str,
    next_phase: str,
) -> None:
    calls = []
    monkeypatch.setattr(
        "harness.squad.create_phase_checkpoint",
        lambda **kwargs: calls.append(kwargs),
    )
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    controller._squad_dir = tmp_path / "runs" / "run-test"
    controller._state_store = MagicMock()
    controller._state_store.load.return_value = {
        "run_id": "run-test",
        "spec_id": "001-demo",
        "spec_dir": "specs/001-demo",
    }
    (tmp_path / "specs" / "001-demo").mkdir(parents=True)

    assert controller._checkpoint_successful_phase(phase, next_phase) is True
    assert calls == [{
        "project_root": tmp_path,
        "spec_dir": tmp_path / "specs" / "001-demo",
        "phase": phase,
        "next_phase": next_phase,
        "run_id": "run-test",
        "spec_id": "001-demo",
        "additional_spec_dirs": (),
        "additional_owned_paths": (),
    }]
```

Add a real-Git integration test that:

1. writes `tasks.md` and a tasks report;
2. calls `_checkpoint_successful_phase("phase3-tasks-lexicon", "phase3-plan")`;
3. loads `.echelon/checkpoints.json`;
4. asserts phase, next phase, and commit;
5. uses `git show <commit>:<spec-path>/tasks-lexicon-report.json` to prove the
   report is in the commit.

- [ ] **Step 2: Write failing recovery and manual-phase tests**

In `tests/integration/test_squad_controller.py`, initialize state at each new
node and assert `run()` dispatches `deterministic_lexicon` without invoking the
provider.

In `tests/unit/test_cli_phase.py`, assert both IDs appear in phase listing and
manual execution routes through the existing single-phase controller path.

- [ ] **Step 3: Run checkpoint and recovery tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_phase.py \
  tests/integration/test_squad_controller.py \
  -k "checkpoint or tasks_lexicon or deterministic_tasks"
```

Expected: all checkpoint, resume, and manual phase cases pass.

- [ ] **Step 4: Add the changelog entry**

Under `CHANGELOG.md` `[Unreleased]`, add:

```markdown
- Replaced hidden tasks-Lexicon checks after planning and PLAN2 with two
  provider-free workflow nodes. Each certification is now visible, resumable,
  deterministically routed, and covered by the normal Phase A checkpoint
  ledger without changing TASKS grammar or Lexicon configuration.
```

- [ ] **Step 5: Run focused verification**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_tasks_lexicon_gate.py \
  tests/unit/test_lexicon_gates.py \
  tests/unit/test_tasks_wiring.py \
  tests/unit/test_product_inputs.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_phase.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_condition_evaluator.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Run repository verification**

Run:

```bash
.venv/bin/pytest -q
for test_file in tests/unit/*.sh; do
  bash "$test_file"
done
bash scripts/bash/dry-run.sh
git diff --check
```

Expected:

- full pytest suite passes;
- every legacy unit shell contract passes;
- dry-run reports zero failures and includes both new nodes in current workflow
  checks;
- `git diff --check` prints no output.

- [ ] **Step 7: Inspect final source ownership**

Run:

```bash
rg -n \
  "_enforce_tasks_lexicon_gate_result|_validate_tasks_gate_artifacts|_mark_tasks_lexicon_uncertified" \
  src extension tests
rg -n "tasks_lexicon_attempts" \
  extension/agents extension/workflow/phases extension/workflow/definition.yaml
git status --short
```

Expected:

- no hidden hook definitions or calls;
- no provider prompt permits reporting `tasks_lexicon_attempts`;
- only the new deterministic nodes own tasks certification fields;
- the pre-existing untracked review document remains untouched.

- [ ] **Step 8: Commit verification and release documentation**

```bash
git add \
  CHANGELOG.md \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_cli_phase.py \
  tests/integration/test_squad_controller.py
git commit -m "test: verify tasks lexicon node recovery"
```

---

## Final Review Checklist

- [ ] The new service owns validation but not state mutation or routing.
- [ ] The existing executor owns dispatch but does not invoke a provider.
- [ ] Workflow nodes own routing and certification state.
- [ ] Provider nodes own only authored planning artifacts.
- [ ] The hidden transition hook is deleted.
- [ ] Initial planning and post-PLAN2 output are both certified.
- [ ] Hard exhaustion checkpoints before terminal block.
- [ ] Warning exhaustion preserves the report and existing consensus routing.
- [ ] Every new condition is statically validated and never needs COMMANDER.
- [ ] Exact-node resume and manual phase execution pass.
- [ ] Existing spec-Lexicon behavior is unchanged.
- [ ] No compatibility mode, generic framework, or checkpoint subsystem was
  added.
