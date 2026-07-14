# Spec Scope Deferral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, auditable `echelon spec defer` and `echelon spec plan` commands so fulfilled work can land while explicitly deferred scope remains visible.

**Architecture:** `harness.deferred_scope` owns the committed `deferred-scope.json` ledger, canonical-ID validation, direct task derivation, and atomic mutation. CLI commands call it without an LLM. Task progress and fulfillment consume the ledger: deferred tasks are terminal for scheduling and selected requirement rows render as `DEFERRED_SCOPE`.

**Tech Stack:** Python 3, Typer, pytest, existing `kernel.task_contract`, deterministic fulfillment assembly.

## Global Constraints

- Commands accept only `T-*`, `FR-*`, `NFR-*`, `AC-*`, and `SC-*` IDs.
- `defer` requires `--reason`; both commands support `--dry-run` and invoke no provider.
- Propagation is direct only: requirement/gate to directly mapped task. Never task to other requirements or tasks.
- `DEFERRED_SCOPE` is valid only with an active committed ledger entry. Ordinary unresolved rows still block.
- Keep `--allow-fulfillment-gaps` only as a compatibility override, never as the normal defer path.

---

### Task 1: Build The Committed Ledger

**Files:**
- Create: `src/harness/deferred_scope.py`
- Create: `tests/unit/test_deferred_scope.py`

**Interfaces:**
- `plan_defer(spec_dir: Path, ids: Sequence[str], *, reason: str) -> DeferredScopePlan`
- `apply_defer(spec_dir: Path, ids: Sequence[str], *, reason: str) -> DeferredScopePlan`
- `plan_restore(spec_dir: Path, ids: Sequence[str]) -> DeferredScopePlan`
- `apply_restore(spec_dir: Path, ids: Sequence[str]) -> DeferredScopePlan`
- `active_deferred_requirement_ids(spec_dir: Path) -> frozenset[str]`

- [ ] **Step 1: Write failing narrow-closure tests**

```python
def test_defer_requirement_derives_only_direct_mapped_tasks(tmp_path: Path) -> None:
    spec_dir = _spec(
        tmp_path,
        tasks=(
            "- [ ] T-001 complexity=standard phase=build req=NFR-008,FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=build req=FR-001 depends=T-001\n"
        ),
        requirements="FR-001\nNFR-008\n",
    )
    plan = plan_defer(spec_dir, ["NFR-008"], reason="contradictory contrast rule")
    assert plan.selected_ids == ("NFR-008",)
    assert plan.derived_task_ids == ("T-001",)
    assert plan.related_active_ids == ("FR-001",)

def test_plan_restores_history_without_deleting_reason(tmp_path: Path) -> None:
    spec_dir = _spec(tmp_path, tasks=_task("T-001", "NFR-008"), requirements="NFR-008\n")
    apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
    apply_restore(spec_dir, ["NFR-008"])
    entry = read_ledger(spec_dir).entries[0]
    assert entry.status == "planned"
    assert entry.reason == "owner decision"
    assert entry.planned_at is not None
```

- [ ] **Step 2: Verify the tests are red**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_deferred_scope.py`

Expected: import failure for `harness.deferred_scope`.

- [ ] **Step 3: Implement a schema-versioned atomic ledger**

```python
LEDGER_FILENAME = "deferred-scope.json"

@dataclass(frozen=True)
class DeferredScopePlan:
    selected_ids: tuple[str, ...]
    derived_task_ids: tuple[str, ...]
    related_active_ids: tuple[str, ...]

def apply_defer(spec_dir: Path, ids: Sequence[str], *, reason: str) -> DeferredScopePlan:
    plan = plan_defer(spec_dir, ids, reason=reason)
    ledger = read_ledger(spec_dir).with_deferred_entry(plan, reason=reason)
    _atomic_write(ledger_path(spec_dir), ledger.to_dict())
    return plan
```

Validate the reason, schema, duplicate active entries, tasks from `parse_task_rows`, and requirements from `extract_canonical_requirements`. Persist selected IDs, direct derived task IDs, prior task states, reason, timestamps, and stable entry ID. Write with a temporary sibling and `Path.replace()`.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_deferred_scope.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/harness/deferred_scope.py tests/unit/test_deferred_scope.py && git commit -m "feat: add deferred scope ledger"`

### Task 2: Add Deferred Task Progress

**Files:**
- Modify: `src/harness/task_progress.py`
- Modify: `src/kernel/task_contract.py`
- Modify: `tests/unit/test_task_progress.py`
- Modify: `tests/unit/test_deferred_scope.py`

**Interfaces:** Add `DEFERRED` task status and `deferred_tasks`/`terminal_tasks` fields to `TaskProgressSummary`.

- [ ] **Step 1: Write failing terminal-status tests**

```python
def test_deferred_task_is_terminal_but_not_completed() -> None:
    markdown = update_task_progress_markdown(_task("T-001", "FR-001"), "T-001", "DEFERRED")
    summary = summarize_task_progress(markdown)
    assert summary.task_statuses["T-001"] == "DEFERRED"
    assert summary.completed_tasks == 0
    assert summary.deferred_tasks == 1
    assert summary.terminal_tasks == 1
```

- [ ] **Step 2: Verify red**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_task_progress.py`

Expected: `unsupported task status: DEFERRED`.

- [ ] **Step 3: Implement terminal-but-not-completed accounting**

```python
_COMPLETED_STATUSES = {"DONE", "DONE_WITH_CONCERNS", "DEGRADED"}
_DEFERRED_STATUSES = {"DEFERRED"}
_TERMINAL_STATUSES = _COMPLETED_STATUSES | _DEFERRED_STATUSES
_ALLOWED_STATUSES = _TERMINAL_STATUSES | {"BLOCKED", "PENDING"}
```

Keep a deferred task checkbox unchecked so completed metrics stay honest. `apply_defer` changes only non-completed direct tasks and captures their prior state; `apply_restore` restores only the states changed by its matching ledger entry.

- [ ] **Step 4: Verify green with dependent tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_task_progress.py tests/unit/test_deferred_scope.py tests/unit/test_progress_reconciliation.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/harness/task_progress.py src/kernel/task_contract.py tests/unit/test_task_progress.py tests/unit/test_deferred_scope.py && git commit -m "feat: represent deferred tasks in progress"`

### Task 3: Apply A Deterministic Fulfillment Overlay

**Files:**
- Modify: `src/kernel/fulfillment.py`
- Modify: `src/harness/judgment_prepass.py`
- Modify: `src/harness/__main__.py`
- Modify: `extension/workflow/phases/verify-spec-5-judge.md`
- Modify: `tests/unit/test_fulfillment.py`
- Modify: `tests/unit/test_judgment_prepass.py`
- Modify: `tests/unit/test_harness_main_inspect_fulfillment.py`

**Interfaces:**
- `apply_deferred_scope_to_report(report_path: Path, spec_dir: Path) -> tuple[str, ...]`
- `validate_deferred_scope_rows(report_path: Path, spec_dir: Path) -> list[str]`
- Add `DEFERRED_SCOPE` to `FULFILLMENT_STATUSES` and report status parsing.

- [ ] **Step 1: Write failing report tests**

```python
def test_deferred_scope_replaces_only_supported_selected_rows(tmp_path: Path) -> None:
    spec_dir = _deferred_spec(tmp_path, ["NFR-008"])
    report = _report(spec_dir, "NFR-008", "DEVIATED")
    changed = apply_deferred_scope_to_report(report, spec_dir)
    assert changed == ("NFR-008",)
    assert "| NFR-008 | DEFERRED_SCOPE | defer:defer-001:" in report.read_text()
    assert fulfillment_has_blocking_gaps(report) is False

def test_unsupported_deferred_scope_row_is_rejected(tmp_path: Path) -> None:
    report = _report(tmp_path, "NFR-008", "DEFERRED_SCOPE")
    assert validate_deferred_scope_rows(report, tmp_path) == ["NFR-008 has no active defer entry"]
```

- [ ] **Step 2: Verify red**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_fulfillment.py tests/unit/test_judgment_prepass.py`

Expected: import/status assertion failure for `DEFERRED_SCOPE`.

- [ ] **Step 3: Implement overlay, validation, and verify-spec wiring**

```python
DEFERRED_SCOPE = "DEFERRED_SCOPE"
_KNOWN_STATUSES = STRICT_BLOCKING | {"IMPLEMENTED", "OBSOLETE_SPEC", DEFERRED_SCOPE}

def validate_deferred_scope_rows(report_path: Path, spec_dir: Path) -> list[str]:
    active = active_deferred_requirement_ids(spec_dir)
    return [f"{item_id} has no active defer entry" for item_id in _deferred_row_ids(report_path) if item_id not in active]
```

The overlay changes only active selected requirement/gate rows, preserves row IDs/order, and writes `defer:<entry-id>: <reason>` evidence. Extend fallback allowed statuses and summary validation. Add `python -m harness apply-deferred-scope <spec-dir> <fulfillment-report.md> [state.json]`, then run it after both report assemblies in `verify-spec-5-judge.md` and before artifact validation.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_fulfillment.py tests/unit/test_judgment_prepass.py tests/unit/test_harness_main_inspect_fulfillment.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/kernel/fulfillment.py src/harness/judgment_prepass.py src/harness/__main__.py extension/workflow/phases/verify-spec-5-judge.md tests/unit/test_fulfillment.py tests/unit/test_judgment_prepass.py tests/unit/test_harness_main_inspect_fulfillment.py && git commit -m "feat: honor deferred scope in fulfillment reports"`

### Task 4: Expose No-LLM CLI Commands

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Create: `tests/unit/test_cli_spec_scope.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- `echelon spec defer <spec-id> <ids...> --reason <text> [--dry-run]`
- `echelon spec plan <spec-id> <ids...> [--dry-run]`

- [ ] **Step 1: Write failing CLI dry-run tests**

```python
def test_spec_defer_dry_run_lists_direct_and_related_effects(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["spec", "defer", "906", "NFR-008", "--reason", "contradictory", "--dry-run"])
    assert result.exit_code == 0
    assert "direct IDs: NFR-008" in result.output
    assert "deferred tasks: T-016" in result.output
    assert "FR-001 remains active" in result.output
    assert not (tmp_path / "specs" / "906-demo" / "deferred-scope.json").exists()
```

- [ ] **Step 2: Verify red**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_cli_spec_scope.py tests/unit/test_cli_typer_app.py`

Expected: unknown `defer` and `plan` subcommands.

- [ ] **Step 3: Implement Typer and compatibility dispatch**

```python
@spec_app.command("defer")
def spec_defer(spec_id: str, ids: list[str], reason: str = typer.Option(..., "--reason"), dry_run: bool = False) -> None:
    _run_scope_change(spec_id, ids, action="defer", reason=reason, dry_run=dry_run)

@spec_app.command("plan")
def spec_plan(spec_id: str, ids: list[str], dry_run: bool = False) -> None:
    _run_scope_change(spec_id, ids, action="plan", dry_run=dry_run)
```

Resolve via `find_spec_dir`. Print selected IDs, direct tasks, related active IDs, ledger path, and dry-run/applied state. Exit nonzero on bad ID, missing reason, malformed ledger, duplicate deferral, or no matching active entry.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_cli_spec_scope.py tests/unit/test_cli_typer_app.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_cli_spec_scope.py tests/unit/test_cli_typer_app.py && git commit -m "feat: add spec defer and plan commands"`

### Task 5: Enforce Ledger-Backed Delivery And Landing

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_ralph_outer.py`
- Modify: `tests/unit/test_land.py`
- Modify: `tests/unit/test_cli_status.py`

**Interfaces:** Delivery and landing call `validate_deferred_scope_rows()` before accepting a report; landing prints active defer entry IDs, selected IDs, reasons, and ledger path.

- [ ] **Step 1: Write failing delivery and land tests**

```python
def test_land_accepts_ledger_backed_deferred_scope_without_override(tmp_path: Path) -> None:
    spec_dir = _deferred_spec(tmp_path, ["NFR-008"])
    _report(spec_dir, "NFR-008", "DEFERRED_SCOPE")
    assert land("042", project_dir=tmp_path, gitops=_gitops()) is True

def test_ralph_rejects_unsupported_deferred_scope_row(tmp_path: Path) -> None:
    _report(tmp_path / "specs" / "001-demo", "NFR-008", "DEFERRED_SCOPE")
    result = _controller(tmp_path)._apply_fulfillment_gate(VerifyResult(passed=True), str(tmp_path))
    assert result.failures[0].id == "fulfillment-deferred-scope-invalid"
```

- [ ] **Step 2: Verify red**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_land.py tests/unit/test_ralph_outer.py tests/unit/test_cli_status.py`

Expected: current gates do not validate a deferred-scope row.

- [ ] **Step 3: Implement validation and visible landing summary**

```python
issues = validate_deferred_scope_rows(report, spec_dir)
if issues:
    return VerifyResult(
        passed=False,
        failures=[FailureEntry(FailureCategory.OTHER, "fulfillment-deferred-scope-invalid", "; ".join(issues))],
    )
```

Run the validation before gap checks in Ralph and landing. For active entries, add a `LAND — DEFERRED SCOPE` banner. Never set `allow_fulfillment_gaps`; unsupported deferred rows and ordinary gaps remain blocking.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_land.py tests/unit/test_ralph_outer.py tests/unit/test_cli_status.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/harness/ralph.py src/harness/land.py tests/unit/test_land.py tests/unit/test_ralph_outer.py tests/unit/test_cli_status.py && git commit -m "feat: allow ledger-backed deferred scope to land"`

### Task 6: Verify The Workflow And Document It

**Files:**
- Modify: `tests/unit/test_deferred_scope.py`
- Modify: `tests/unit/test_land_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write the end-to-end regression**

```python
def test_plan_reactivates_the_original_fulfillment_gap(tmp_path: Path) -> None:
    spec_dir = _deferred_spec(tmp_path, ["NFR-008"])
    report = _report(spec_dir, "NFR-008", "DEVIATED")
    apply_deferred_scope_to_report(report, spec_dir)
    assert fulfillment_has_blocking_gaps(report) is False
    apply_restore(spec_dir, ["NFR-008"])
    _report(spec_dir, "NFR-008", "DEVIATED")
    assert fulfillment_has_blocking_gaps(report) is True
```

- [ ] **Step 2: Document exact no-LLM commands**

```bash
echelon spec defer 906 NFR-008 --reason "Contradictory contrast rule" --dry-run
echelon spec defer 906 NFR-008 --reason "Contradictory contrast rule"
echelon spec continue
echelon spec plan 906 NFR-008
```

State that the ledger is committed/auditable and unrelated gaps are never suppressed.

- [ ] **Step 3: Run the complete deterministic regression suite**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_deferred_scope.py tests/unit/test_task_progress.py tests/unit/test_fulfillment.py tests/unit/test_judgment_prepass.py tests/unit/test_harness_main_inspect_fulfillment.py tests/unit/test_cli_spec_scope.py tests/unit/test_cli_typer_app.py tests/unit/test_land.py tests/unit/test_land_cli.py tests/unit/test_ralph_outer.py tests/unit/test_cli_status.py`

Expected: PASS without a provider/LLM call.

- [ ] **Step 4: Commit**

Run: `git add README.md tests/unit/test_deferred_scope.py tests/unit/test_land_cli.py && git commit -m "docs: explain spec scope deferral workflow"`
