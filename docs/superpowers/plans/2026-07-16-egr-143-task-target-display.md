# EGR-143 Task Target Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `echelon spec targets <spec_id>` command that displays every canonical task exactly once, grouped by inferred delivery target, and exposes invalid ownership clearly.

**Architecture:** Extend the existing deterministic `harness.task_targets` parser with task-title metadata, then add a legacy execution handler in `echelon.cli` and a typed Typer front door in `echelon.cli_app`. The command reads only published `tasks.md` and target metadata, renders single-target, unowned, and cross-target groups, and exits `2` after rendering when the mapping is invalid.

**Tech Stack:** Python 3.11+, dataclasses, Typer/Click, pytest, existing `harness.spec_frontmatter` and `harness.task_targets` modules.

## Global Constraints

- Infer task targets only from `sources/<source-id>/...` paths in each canonical task's `**Files:**` section.
- Display every canonical task exactly once.
- Keep `UNOWNED` and `CROSS-TARGET` tasks visible.
- Do not modify `tasks.md`, `targets.yml`, delivery state, or target repositories.
- Preserve existing delivery validation and single-target compatibility behavior.
- Do not stage or commit unrelated pre-existing worktree changes.

---

### Task 1: Preserve task titles in deterministic ownership analysis

**Files:**
- Modify: `src/harness/task_targets.py`
- Modify: `tests/unit/test_task_targets.py`

**Interfaces:**
- Consumes: canonical task blocks already returned by `_task_blocks(markdown)`.
- Produces: `TaskTargetAnalysis.task_titles: dict[str, str]` and `TaskTargetValidation.task_titles: dict[str, str]` for CLI rendering.

- [x] **Step 1: Write the failing title extraction test**

```python
assert analysis.task_titles == {
    "T-001": "Add dashboard API contract",
    "T-002": "Render dashboard view",
    "T-003": "",
}
```

- [x] **Step 2: Run the focused parser test and confirm the red state**

Run: `pytest tests/unit/test_task_targets.py -q`

Expected: FAIL because `TaskTargetAnalysis` has no `task_titles` field.

- [x] **Step 3: Add title extraction to the parser**

```python
@dataclass(frozen=True)
class TaskTargetAnalysis:
    target_tasks: dict[str, tuple[str, ...]]
    unowned_tasks: tuple[str, ...]
    cross_target_tasks: dict[str, tuple[str, ...]]
    all_task_ids: tuple[str, ...]
    task_titles: dict[str, str]


def _task_title(block: str) -> str:
    for line in block.splitlines():
        if line.strip().startswith("**Title:**"):
            return line.split("**Title:**", 1)[1].strip()
    return ""
```

Populate titles in canonical task order and pass the mapping through `validate_task_targets()` without changing its existing assignment rules.

- [x] **Step 4: Run parser tests and confirm green**

Run: `pytest tests/unit/test_task_targets.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the parser slice when explicitly authorized**

```bash
git add src/harness/task_targets.py tests/unit/test_task_targets.py
git commit -m "feat: expose task titles in target analysis"
```

### Task 2: Add the read-only grouped target report command

**Files:**
- Create: `tests/unit/test_cli_spec_targets.py`
- Modify: `src/echelon/cli.py`

**Interfaces:**
- Consumes: `find_spec_dir(spec_id, Path.cwd())`, `read_targets(spec_dir)`, and `analyze_task_targets(tasks_markdown)`.
- Produces: `_cmd_spec_targets(args: list[str]) -> None`, human-readable grouped output, exit `0` for a valid map, exit `2` for an invalid map, and exit `1` for usage/input errors.

- [x] **Step 1: Write failing valid and invalid report tests**

```python
def test_spec_targets_prints_every_task_once_grouped_by_target(...):
    _cmd_spec_targets(["001"])
    assert "sources/api [declared]" in output
    assert "sources/web [declared]" in output
    assert output.count("  T-001  Add dashboard API contract") == 1


def test_spec_targets_prints_invalid_groups_before_exit(...):
    with pytest.raises(SystemExit) as exc:
        _cmd_spec_targets(["001"])
    assert exc.value.code == 2
    assert "UNOWNED" in output
    assert "CROSS-TARGET" in output
    assert "Declared but unreferenced targets" in output
```

The invalid fixture must include an inferred-but-undeclared target, a declared-but-unreferenced target, an unowned task, and a cross-target task. Assert that the number of rendered task lines equals the canonical task count.

- [x] **Step 2: Run the focused CLI tests and confirm the red state**

Run: `pytest tests/unit/test_cli_spec_targets.py -q`

Expected: FAIL because `_cmd_spec_targets` does not exist.

- [x] **Step 3: Implement minimal grouped rendering**

```python
def _cmd_spec_targets(args: list[str]) -> None:
    if len(args) != 1:
        print("echelon spec targets: usage: echelon spec targets <spec_id>", file=sys.stderr)
        raise SystemExit(1)

    spec_dir = find_spec_dir(args[0], Path.cwd())
    # Read tasks.md and declared targets, render sorted target groups first,
    # then UNOWNED and CROSS-TARGET. Compute mismatch sets from raw analysis
    # so inspection never inherits single-target implicit assignment.
```

Use a small local formatter that prints `T-ID  Title` when a title exists and only `T-ID` otherwise. Print a final task-count line and `Result: valid` or `Result: invalid — ...`. Raise `SystemExit(2)` only after all groups and diagnostics have been printed.

- [x] **Step 4: Run the focused CLI and parser tests**

Run: `pytest tests/unit/test_cli_spec_targets.py tests/unit/test_task_targets.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the command slice when explicitly authorized**

```bash
git add src/echelon/cli.py src/harness/task_targets.py tests/unit/test_cli_spec_targets.py tests/unit/test_task_targets.py
git commit -m "feat: display tasks grouped by delivery target"
```

### Task 3: Expose the command through Typer help and documentation

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `_cmd_spec_targets([spec_id])` from Task 2.
- Produces: typed `echelon spec targets SPEC_ID` routing, discoverable help, legacy usage documentation, and README operator guidance.

- [x] **Step 1: Write the failing Typer route/help test**

```python
def test_spec_targets_declares_argument_and_routes(monkeypatch):
    result = invoke_help("spec", "targets")
    assert result.exit_code == 0
    assert "SPEC_ID" in result.output

    calls = []
    monkeypatch.setattr("echelon.cli._cmd_spec_targets", lambda args: calls.append(args))
    run(["spec", "targets", "001"])
    assert calls == [["001"]]
```

- [x] **Step 2: Run the focused Typer test and confirm the red state**

Run: `pytest tests/unit/test_cli_typer_app.py -q -k spec_targets`

Expected: FAIL because the `targets` command is not registered.

- [x] **Step 3: Add typed routing and help text**

```python
@spec_app.command("targets")
def spec_targets(
    spec_id: str = typer.Argument(..., help="Spec id to inspect."),
) -> None:
    """Display every task grouped by delivery target."""
    _legacy_cli()._cmd_spec_targets([spec_id])
```

Add `targets <spec_id>` to the spec common forms, the legacy `USAGE` string, the README workflow example, and the CLI reference table. Keep singular `spec target` documented as the mutating setter.

- [x] **Step 4: Run focused CLI/documentation tests**

Run: `pytest tests/unit/test_cli_spec_targets.py tests/unit/test_cli_typer_app.py tests/unit/test_task_targets.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the operator surface when explicitly authorized**

```bash
git add src/echelon/cli.py src/echelon/cli_app.py README.md tests/unit/test_cli_typer_app.py
git commit -m "docs: expose task target inspection command"
```

### Task 4: Verify and install EGR-143

**Files:**
- Verify all files modified in Tasks 1-3.

**Interfaces:**
- Consumes: the completed source tree.
- Produces: fresh test evidence and an installed CLI exercised against OptaSearch.

- [x] **Step 1: Run focused tests**

Run: `pytest tests/unit/test_task_targets.py tests/unit/test_cli_spec_targets.py tests/unit/test_cli_typer_app.py tests/unit/test_cli_harness_run.py tests/unit/test_orchestrator.py -q`

Expected: all tests pass.

- [x] **Step 2: Run repository diff validation**

Run: `git diff --check`

Expected: exit `0` with no output.

- [x] **Step 3: Reinstall the Python CLI**

Run: `bash scripts/install.sh`

Expected: installer exits `0` and reports the installed Echelon CLI path.

- [x] **Step 4: Exercise the installed command on the incident spec**

Run from `/Users/michalbachorik/work/optasearch`: `echelon spec targets 001`

Expected: all 34 tasks are printed exactly once; backend and frontend task groups are shown; T-029 through T-034 are shown under `UNOWNED`; the result is invalid and the process exits `2`.

- [x] **Step 5: Record implementation status without committing unrelated work**

Update EGR-143 from `open` to `fixed` only after the verification above passes. Preserve EGR-142 and all other pre-existing changes in the shared register.
