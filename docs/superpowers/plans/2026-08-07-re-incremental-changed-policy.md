# Incremental RE Changed-Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `echelon re run --re-policy changed` refresh only stale sources and materialize current published sources as `reuse`.

**Architecture:** `build_re_execution_plan()` already computes the correct per-source actions from fingerprints and the published index. `ReLifecycleController.run()` must preserve that result for normal runs. The explicit `--no-reuse` escape hatch remains the sole lifecycle-level reason to convert reusable sources to fresh extraction work.

**Tech Stack:** Python 3.12, pytest, Typer CLI, JSON RE execution plans.

## Global Constraints

- Preserve `refresh-all`, `cached-only`, `none`, and `--no-reuse` semantics.
- Do not change source fingerprinting or published-index compatibility rules.
- `changed` with no stale sources must keep its existing no-provider-call behavior.
- Do not alter run-state or publication schemas.

---

## File Structure

- `src/harness/re_lifecycle.py` owns lifecycle policy application after the planner has selected source actions.
- `tests/unit/test_re_lifecycle.py` owns controller-level regressions that prove the lifecycle does not overwrite planner actions.
- `tests/unit/test_re_planner.py` remains the unit-level contract that `changed` computes `reuse` and `refresh` actions correctly.

### Task 1: Capture the lifecycle overwrite regression

**Files:**
- Modify: `tests/unit/test_re_lifecycle.py`
- Test: `tests/unit/test_re_lifecycle.py::test_changed_run_preserves_reuse_actions_from_planner`

**Interfaces:**
- Consumes: `ReLifecycleController.run(policy="changed", reset=False)` and a planner-produced `ReExecutionPlan`.
- Produces: a regression proving that the plan passed to `materialize_re_run_context()` contains `api.action == "reuse"` and `worker.action == "refresh"`.

- [ ] **Step 1: Add a reusable mixed-action plan fixture in the test module**

```python
def _changed_plan_with_reuse(root: Path, profile: ReFingerprintProfile) -> ReExecutionPlan:
    return ReExecutionPlan.from_json_dict(
        {
            "schema_version": 1,
            "policy": "changed",
            "requested_policy": "changed",
            "target_source": "",
            "forbidden_source_roots": [],
            "profile": profile.to_json_dict(),
            "sources": [
                {
                    "id": "api", "path": "sources/api",
                    "absolute_path": str(root / "sources/api"), "action": "reuse",
                    "fingerprint": {"value": "api-current", "kind": "file-tree", "dirty": False,
                                    "profile_hash": profile.profile_hash()},
                    "cache_path": str(root / "re/.cache/api"), "dirty": False,
                    "selected": True, "classification": "current",
                },
                {
                    "id": "worker", "path": "sources/worker",
                    "absolute_path": str(root / "sources/worker"), "action": "refresh",
                    "fingerprint": {"value": "worker-stale", "kind": "file-tree", "dirty": False,
                                    "profile_hash": profile.profile_hash()},
                    "cache_path": str(root / "re/.cache/worker"), "dirty": False,
                    "selected": True, "classification": "refresh",
                },
            ],
            "removed_sources": [], "analysis_required": True,
            "workspace_synthesis_required": True, "publication_required": True,
        }
    )
```

- [ ] **Step 2: Write the failing lifecycle test**

Monkeypatch `build_re_execution_plan` to return `_changed_plan_with_reuse`, `load_published_index` to return `SimpleNamespace(generation=1)`, and `materialize_re_run_context` to append its `plan` argument to a list. Use a fake `ReExtractionController` that returns `ReControllerResult(completed=True)`. Assert:

```python
assert {source.id: source.action for source in captured_plans[0].sources} == {
    "api": "reuse",
    "worker": "refresh",
}
```

- [ ] **Step 3: Run the regression and verify the current failure**

Run: `pytest tests/unit/test_re_lifecycle.py::test_changed_run_preserves_reuse_actions_from_planner -v`

Expected: FAIL because the captured `api` action is `"refresh"`.

- [ ] **Step 4: Add the explicit no-reuse companion test**

Call the same controller with `reuse_published=False` and assert both source actions are `"refresh"`. This prevents the fix from silently breaking the documented `--no-reuse` behavior.

- [ ] **Step 5: Commit the failing-test checkpoint**

```bash
git add tests/unit/test_re_lifecycle.py
git commit -m "test: expose RE changed-policy lifecycle refresh"
```

### Task 2: Preserve planner actions for ordinary changed runs

**Files:**
- Modify: `src/harness/re_lifecycle.py:158-171`
- Test: `tests/unit/test_re_lifecycle.py::test_changed_run_preserves_reuse_actions_from_planner`
- Test: `tests/unit/test_re_lifecycle.py::test_no_reuse_forces_reusable_sources_to_refresh`

**Interfaces:**
- Consumes: `ReExecutionPlan.sources` whose actions were decided by `build_re_execution_plan()`.
- Produces: unchanged actions for normal runs; `reuse -> refresh` conversion only when `reuse_published is False`.

- [ ] **Step 1: Replace the blanket conversion condition**

Replace the `if published is not None and plan.policy not in {"none", "cached-only"}:` block with a block that runs only for `not reuse_published`:

```python
if not reuse_published:
    plan = replace(
        plan,
        sources=tuple(
            replace(source, action="refresh", classification="refresh")
            if source.action == "reuse"
            else source
            for source in plan.sources
        ),
        analysis_required=True,
        workspace_synthesis_required=True,
        publication_required=True,
    )
```

Do not change the planner output for ordinary `changed`, `refresh-all`, `cached-only`, or `none` runs.

- [ ] **Step 2: Run the focused lifecycle tests**

Run: `pytest tests/unit/test_re_lifecycle.py -v`

Expected: PASS, including both new action-preservation tests.

- [ ] **Step 3: Run the planner contract tests**

Run: `pytest tests/unit/test_re_planner.py -v`

Expected: PASS; in particular, `test_changed_policy_reuses_published_sources_and_refreshes_new_source` remains green.

- [ ] **Step 4: Commit the implementation**

```bash
git add src/harness/re_lifecycle.py tests/unit/test_re_lifecycle.py
git commit -m "fix: preserve incremental RE changed-policy actions"
```

### Task 3: Verify the public lifecycle contract end to end

**Files:**
- Test: `tests/unit/test_re_lifecycle.py`
- Test: `tests/unit/test_re_planner.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Consumes: the unchanged CLI spelling `echelon re run --re-policy changed`.
- Produces: evidence that the CLI, lifecycle, and planner preserve incremental behavior.

- [ ] **Step 1: Run the combined targeted suite**

Run: `pytest tests/unit/test_re_lifecycle.py tests/unit/test_re_planner.py tests/unit/test_cli_re_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 2: Validate installed-extension wiring without an agent run**

Run: `bash scripts/bash/dry-run.sh`

Expected: exit code 0.

- [ ] **Step 3: Commit verification-only changes if any were required**

```bash
git status --short
git add tests/unit/test_re_lifecycle.py tests/unit/test_re_planner.py tests/unit/test_cli_re_lifecycle.py
git commit -m "test: verify incremental RE changed policy"
```

Only run the `git add` and commit commands when `git status --short` lists intended test changes.

## Self-Review

- Spec coverage: Task 1 proves the observed failure; Task 2 removes only the lifecycle overwrite while preserving `--no-reuse`; Task 3 verifies the public contract.
- Placeholder scan: no incomplete implementation markers or unnamed behavior remain.
- Type consistency: all tasks use existing `ReExecutionPlan`, `ReLifecycleController.run`, and `RePlanSource.action` interfaces.
