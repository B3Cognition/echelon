# Verify-Spec Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `echelon verify-spec <id> --reconcile [--dry-run]` so verify-spec can safely reconcile task progress from fresh fulfillment evidence.

**Architecture:** Normal verify-spec remains read-only. A new optional reconciliation phase asks the prompt to write candidate reconciliation artifacts, then Python applies only deterministic task-progress updates through harness task-progress helpers and validates afterward.

**Tech Stack:** Python 3.11, existing `harness.task_progress`, `harness.__main__`, Echelon workflow Markdown/YAML, pytest prompt/unit tests.

---

## File Structure

- Create `src/harness/progress_reconciliation.py`: parse candidate JSON, validate safe task IDs/dependencies, apply updates with `update_task_progress_markdown`, write plan/applied reports.
- Modify `src/harness/__main__.py`: add `apply-progress-reconciliation` command.
- Create `tests/unit/test_progress_reconciliation.py`: deterministic apply/dry-run behavior.
- Modify `extension/commands/echelon.verify-spec.md`: document read-only default and reconcile exception.
- Modify `extension/workflow/phases/verify-spec-1-init.md`: parse `--reconcile` and `--dry-run`.
- Modify `extension/workflow/definition.yaml`: add optional `verify-spec-6-reconcile` phase after judgment.
- Create `extension/workflow/phases/verify-spec-6-reconcile.md`: candidate plan + deterministic apply instructions.
- Modify/add prompt tests for verify-spec reconciliation contracts.
- Modify `README.md` and `src/echelon/cli.py` USAGE.

## Candidate JSON Contract

The prompt-authored candidate file must be:

```json
{
  "safe_task_updates": [
    {
      "task_id": "T-014",
      "status": "DONE",
      "evidence": "fulfillment-report.md#FR-003",
      "reason": "FR-003 is IMPLEMENTED and maps to task T-014"
    }
  ],
  "ambiguous_task_matches": [
    {
      "task_id": "T-021",
      "evidence": "implementation-map.md#FR-004",
      "reason": "Evidence is PARTIAL or dependency is open"
    }
  ],
  "fulfillment_gap_tasks": {
    "count": 55,
    "details": "specs/001-demo/reopen-1.md"
  },
  "manual_followups": [
    {
      "kind": "spec_plan_divergence",
      "details": "specs/001-demo/fulfillment-report.md#plan-spec-divergences"
    }
  ]
}
```

Python must treat this as untrusted input. It may apply only existing canonical task IDs with `status == "DONE"` and no open dependencies outside the same update set.

## Task 1: Deterministic Reconciliation Module

- [ ] **Step 1: Add failing unit tests**

Create `tests/unit/test_progress_reconciliation.py` with tests:

```python
def test_dry_run_writes_plan_without_mutating_tasks(tmp_path: Path) -> None: ...
def test_apply_marks_safe_tasks_done_and_validates(tmp_path: Path) -> None: ...
def test_apply_skips_unknown_task_ids(tmp_path: Path) -> None: ...
def test_apply_skips_task_with_open_dependency(tmp_path: Path) -> None: ...
def test_reports_ambiguous_and_manual_followup_paths(tmp_path: Path) -> None: ...
```

Use a tiny canonical `tasks.md` with `T-001`, `T-002 depends=T-001`, and `T-003 depends=none`. Assert applied output contains:

```python
assert "- [x] T-001" in tasks_text
assert "**Status:** DONE" in tasks_text
assert "- [ ] T-002" in tasks_text
assert "open dependency" in applied_md
assert "fulfillment-report.md#plan-spec-divergences" in plan_md
```

- [ ] **Step 2: Verify failure**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_progress_reconciliation.py -q
```

Expected: module import fails.

- [ ] **Step 3: Implement `src/harness/progress_reconciliation.py`**

Expose:

```python
def reconcile_progress(
    *,
    tasks_path: Path,
    candidate_path: Path,
    out_plan_json: Path,
    out_plan_md: Path,
    out_applied_json: Path | None = None,
    out_applied_md: Path | None = None,
    dry_run: bool,
) -> ReconciliationResult:
    ...
```

Rules:
- Load candidate JSON.
- Validate current `tasks.md` using `summarize_task_progress`.
- For each safe candidate, require `status == "DONE"` and known task ID.
- Skip if dependencies are open and not also applied in the same batch.
- In apply mode, call `update_task_progress_markdown(markdown, task_id, "DONE")`.
- After apply, call `summarize_task_progress` again and fail if invalid.
- Always write plan JSON/MD.
- Write applied JSON/MD only in apply mode.

- [ ] **Step 4: Verify pass and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_progress_reconciliation.py -q
git add src/harness/progress_reconciliation.py tests/unit/test_progress_reconciliation.py
git commit -m "feat: add progress reconciliation helper"
```

## Task 2: Harness CLI Subcommand

- [ ] **Step 1: Add failing CLI tests**

Add to `tests/unit/test_progress_reconciliation.py` or create `tests/unit/test_harness_main_progress_reconciliation.py`:

```python
def test_apply_progress_reconciliation_dry_run_cli_does_not_mutate(tmp_path: Path) -> None: ...
def test_apply_progress_reconciliation_cli_marks_done(tmp_path: Path) -> None: ...
```

Invoke:

```python
python -m harness apply-progress-reconciliation <tasks.md> <candidate.json> <out-dir> --dry-run
python -m harness apply-progress-reconciliation <tasks.md> <candidate.json> <out-dir>
```

- [ ] **Step 2: Implement subcommand**

Modify `src/harness/__main__.py`:

```text
apply-progress-reconciliation — apply verify-spec task-progress reconciliation
```

Usage:

```text
python -m harness apply-progress-reconciliation <tasks.md> <candidate.json> <out-dir> [--dry-run]
```

It should call `reconcile_progress(...)` and print:

```text
OK: progress reconciliation dry-run wrote <out-dir>/progress-reconciliation-plan.md
OK: progress reconciliation applied <N> task updates
```

- [ ] **Step 3: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_progress_reconciliation.py tests/unit/test_harness_main_progress_reconciliation.py -q
git add src/harness/__main__.py tests/unit/test_harness_main_progress_reconciliation.py
git commit -m "feat: add progress reconciliation command"
```

## Task 3: Verify-Spec Workflow Wiring

- [ ] **Step 1: Add failing prompt tests**

Create or update `tests/unit/test_verify_spec_reconcile_templates.py`:

```python
def test_verify_spec_command_documents_reconcile_exception() -> None: ...
def test_verify_spec_init_parses_reconcile_flags() -> None: ...
def test_verify_spec_workflow_has_optional_reconcile_phase() -> None: ...
def test_reconcile_phase_requires_harness_apply_command() -> None: ...
def test_reconcile_phase_forbids_direct_tasks_editing() -> None: ...
```

Assert:

```python
assert "--reconcile" in text
assert "--dry-run" in text
assert "apply-progress-reconciliation" in text
assert "NEVER edit task checkboxes" in text
assert "python -m harness mark-task-progress" in text
```

- [ ] **Step 2: Update command and init phase**

Modify `extension/commands/echelon.verify-spec.md`:
- Default is read-only.
- Source code is always read-only.
- `tasks.md` may change only when `--reconcile` is present and only through harness helpers.

Modify `extension/workflow/phases/verify-spec-1-init.md`:
- Parse `--reconcile`, `--dry-run`, and existing `strict=true`.
- Write `reconcile` and `dry_run` booleans to `state.json`.

- [ ] **Step 3: Add reconcile phase**

Create `extension/workflow/phases/verify-spec-6-reconcile.md`.

It must:
- Run only when `state.json.reconcile == true`.
- Write candidate JSON to `{verify_run_dir}/progress-reconciliation-candidates.json`.
- Call:

```bash
python -m harness apply-progress-reconciliation \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/progress-reconciliation-candidates.json" \
  "{verify_run_dir}" \
  {--dry-run when state.json.dry_run is true}
```

- Include summary lines with details paths for safe updates, ambiguous matches, existing reopen files, and spec/plan divergences.
- NEVER edit task checkboxes or status lines directly.
- ALWAYS use harness task-progress helpers.

Modify `extension/workflow/definition.yaml`:
- `verify-spec-5-judge` transitions to `verify-spec-6-reconcile` when `reconcile = true`.
- Otherwise transitions to `DONE`.
- Add outputs for candidate, plan, and applied reports.

- [ ] **Step 4: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_verify_spec_reconcile_templates.py -q
git add extension/commands/echelon.verify-spec.md extension/workflow/phases/verify-spec-1-init.md extension/workflow/phases/verify-spec-6-reconcile.md extension/workflow/definition.yaml tests/unit/test_verify_spec_reconcile_templates.py
git commit -m "feat: wire verify-spec reconciliation phase"
```

## Task 4: CLI/README Documentation

- [ ] **Step 1: Add failing docs tests**

Update `tests/unit/test_cli_fulfillment_commands.py` and add README assertions:

```python
assert "verify-spec <spec_id> [strict=true] [--reconcile] [--dry-run]" in cli.USAGE
assert "--reconcile" in README
assert "--reconcile --dry-run" in README
```

- [ ] **Step 2: Update docs**

Modify `src/echelon/cli.py` USAGE:

```text
verify-spec <spec_id> [strict=true] [--reconcile] [--dry-run]
```

Modify README command table to mention:

```text
Audit fulfillment; with --reconcile, apply deterministic task-progress bookkeeping fixes through harness helpers.
```

- [ ] **Step 3: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_fulfillment_commands.py tests/unit/test_verify_spec_reconcile_templates.py -q
git add src/echelon/cli.py README.md tests/unit/test_cli_fulfillment_commands.py
git commit -m "docs: document verify-spec reconciliation"
```

## Task 5: Full Verification

- [ ] **Step 1: Focused tests**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest \
  tests/unit/test_progress_reconciliation.py \
  tests/unit/test_harness_main_progress_reconciliation.py \
  tests/unit/test_verify_spec_reconcile_templates.py \
  tests/unit/test_cli_fulfillment_commands.py \
  -q
```

- [ ] **Step 2: Full unit suite**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit
```

- [ ] **Step 3: Status**

```bash
git status --short --branch
```

Expected: only intentional commits, with the pre-existing untracked
`tests/unit/test_verify_detection.py` left untouched unless the user says it is ours.

## Self-Review

- Spec coverage: CLI UX, dry-run/apply behavior, harness-owned mutation, prompt wiring, output reports, and documentation are covered.
- Placeholder scan: No deferred markers; each task has concrete file paths and commands.
- Type consistency: `reconcile_progress`, `apply-progress-reconciliation`, and report filenames are consistent throughout.
- Scope: This implements task-progress reconciliation only; source deviations and spec/plan divergences remain report/reopen/manual work.
