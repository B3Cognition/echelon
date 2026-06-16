# Cached Scoped Verify Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce repeated full `verify-spec` cost by making Ralph's fulfillment refresh policy cache-aware, mode-aware, visible, and safe for banzai intermediate slices.

**Architecture:** Keep true scoped verification out of Stage 1. Add a small structured refresh-decision layer inside `RalphController` that decides `cached`, `full`, `deferred`, or `failed`, records the decision in state, and only blocks convergence when full fulfillment evidence is required. Reuse the existing `FulfillmentRunner` full-report cache rather than adding a second cache.

**Tech Stack:** Python harness code, existing `ModeController`, `FulfillmentRunner`, `VerifyResult`, `StateStore`, pytest unit tests.

---

## File Structure

- Modify `src/harness/fulfillment_runner.py`
  - Extend `FulfillmentRefreshResult` with optional `scope`, `reason`, `cache_key`, and `report_path`.
  - Populate those fields for `cached`, `refreshed`, `missing_skill`, and `failed`.
- Modify `src/harness/ralph.py`
  - Replace boolean `_should_refresh_fulfillment()` with a structured decision helper.
  - Record `fulfillment_refresh` in state after every refresh/defer/cache decision.
  - For banzai + default `milestone`, defer full refresh while canonical tasks remain incomplete.
  - Preserve semi + `milestone` as conservative: attempt full refresh, still benefiting from `FulfillmentRunner` cache.
  - Ensure deferred refresh does not permit final convergence once tasks are complete.
- Modify `tests/unit/test_fulfillment_runner.py`
  - Assert cache/full result metadata is populated.
- Modify `tests/unit/test_ralph_outer.py`
  - Add behavior tests for banzai deferral, semi refresh, state visibility, and convergence-boundary refresh.

## Task 1: Add Refresh Result Metadata

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Test: `tests/unit/test_fulfillment_runner.py`

- [ ] **Step 1: Write failing tests for refresh metadata**

Add these assertions to existing fulfillment runner tests:

```python
def test_refresh_stamps_latest_fulfillment_report_on_success(self, tmp_path):
    ...
    assert result.status == "refreshed"
    assert result.scope == "full"
    assert result.reason == "full verify-spec completed"
    assert result.report_path == str(report)
    assert isinstance(result.cache_key, str)
```

Add these assertions to `test_refresh_uses_cached_full_report_when_commit_and_spec_hash_match`:

```python
assert second.status == "cached"
assert second.scope == "full"
assert second.reason == "full verify-spec cache hit"
assert second.report_path == str(report)
assert isinstance(second.cache_key, str)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py -q
```

Expected: FAIL because `FulfillmentRefreshResult` has no `scope`, `reason`, `cache_key`, or `report_path` attributes.

- [ ] **Step 3: Implement metadata fields**

Change the dataclass in `src/harness/fulfillment_runner.py` to:

```python
@dataclass(frozen=True)
class FulfillmentRefreshResult:
    """Result of a verify-spec fulfillment refresh attempt."""

    status: str
    exit_code: int
    used_cache: bool = False
    scope: str = "full"
    reason: str = ""
    cache_key: str | None = None
    report_path: str | None = None
```

In `FulfillmentRunner.refresh()`, compute `report_path` before cache check:

```python
report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
report_path = str(report) if report is not None else None
```

For the cache hit return, use:

```python
return FulfillmentRefreshResult(
    status="cached",
    exit_code=0,
    used_cache=True,
    scope="full",
    reason="full verify-spec cache hit",
    cache_key=cache_key,
    report_path=report_path,
)
```

For missing skill:

```python
return FulfillmentRefreshResult(
    status="missing_skill",
    exit_code=127,
    scope="full",
    reason="verify-spec skill missing",
    cache_key=cache_key,
    report_path=report_path,
)
```

After successful refresh, recompute report path because the provider may have just written it:

```python
report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
report_path = str(report) if report is not None else None
return FulfillmentRefreshResult(
    status="refreshed",
    exit_code=0,
    scope="full",
    reason="full verify-spec completed",
    cache_key=cache_key,
    report_path=report_path,
)
```

For failed returns, include:

```python
return FulfillmentRefreshResult(
    status="failed",
    exit_code=exit_code,
    scope="full",
    reason="full verify-spec failed",
    cache_key=cache_key,
    report_path=report_path,
)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py -q
```

Expected: all tests in `test_fulfillment_runner.py` pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/fulfillment_runner.py tests/unit/test_fulfillment_runner.py
git commit -m "feat: expose fulfillment refresh metadata"
```

## Task 2: Add Mode-Aware Refresh Decisions

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Write failing banzai deferral test**

Add a test near the existing fulfillment refresh tests:

```python
def test_banzai_milestone_defers_full_fulfillment_until_tasks_complete(
    self, tmp_path: Path
) -> None:
    from harness.build_result import BuildResult
    from harness.llm_build_runner import LlmBuildRunner

    worktree = tmp_path / "worktree"
    spec_dir = worktree / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
        "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
        encoding="utf-8",
    )
    (worktree / "Package.swift").write_text(
        "// swift-tools-version: 5.10\nimport PackageDescription\n"
        "let package = Package(name: \"Demo\")\n",
        encoding="utf-8",
    )

    build_runner = MagicMock(spec=LlmBuildRunner)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0,
        status="done",
        impasse_file=None,
        stdout="",
        stderr="",
        duration_ms=100,
        task_ids=["T-001"],
    )
    fulfillment_runner = MagicMock()
    controller, _provider, gitops, state_store = _make_controller(
        tmp_path,
        mode="banzai",
        llm_build_runner=build_runner,
        fulfillment_runner=fulfillment_runner,
    )
    controller._config.verify_command = f"{sys.executable} -c pass"
    gitops.create_worktree.return_value = str(worktree)

    result = controller.run_loop(max_outer=1, max_inner=0, build_prompt="build")

    assert result.status == "blocked"
    assert result.termination_reason == "outer_cap"
    fulfillment_runner.refresh.assert_not_called()
    refresh = state_store.read()["fulfillment_refresh"]
    assert refresh["status"] == "deferred"
    assert refresh["reason"] == "banzai milestone defers full verify until task completion"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "banzai_milestone_defers" -q
```

Expected: FAIL because banzai `milestone` currently refreshes every time.

- [ ] **Step 3: Implement refresh decision helper**

In `src/harness/ralph.py`, add a small helper near `_should_refresh_fulfillment`:

```python
def _task_progress_counts(self) -> tuple[int, int]:
    state = self._state_store.read()
    build = state.get("build")
    if not isinstance(build, dict):
        return (0, 0)
    try:
        total = int(build.get("total_tasks") or 0)
        completed = int(build.get("completed_tasks") or 0)
    except (TypeError, ValueError):
        return (0, 0)
    return (total, completed)

def _fulfillment_refresh_decision(self, worktree_path: str) -> dict[str, object]:
    policy = self._config.fulfillment.refresh_policy
    total, completed = self._task_progress_counts()
    tasks_complete = total > 0 and completed >= total

    if policy == "every_slice":
        return {"action": "full", "reason": "fulfillment.refresh_policy=every_slice"}
    if policy == "convergence_only":
        if tasks_complete or total <= 0:
            return {"action": "full", "reason": "convergence boundary reached"}
        return {
            "action": "defer",
            "reason": "fulfillment.refresh_policy=convergence_only",
        }
    if policy == "milestone" and self._mode.mode == "banzai" and total > 0 and not tasks_complete:
        return {
            "action": "defer",
            "reason": "banzai milestone defers full verify until task completion",
        }
    return {"action": "full", "reason": f"fulfillment.refresh_policy={policy}"}
```

Replace `_should_refresh_fulfillment()` use in `_refresh_fulfillment_report()` with this decision. For deferred decisions, write refresh state and return a failed `VerifyResult` with `id="fulfillment-refresh-deferred"` as current behavior does.

- [ ] **Step 4: Add state recording helper**

Add:

```python
def _record_fulfillment_refresh(self, data: dict[str, object]) -> None:
    state = self._state_store.read()
    state["fulfillment_refresh"] = {
        "status": str(data.get("status") or ""),
        "reason": str(data.get("reason") or ""),
        "scope": str(data.get("scope") or "full"),
        "cache_key": data.get("cache_key"),
        "report_path": data.get("report_path"),
    }
    self._state_store.write(state)
```

Call it for deferred decisions:

```python
self._record_fulfillment_refresh({
    "status": "deferred",
    "reason": str(decision["reason"]),
    "scope": "full",
})
```

- [ ] **Step 5: Run banzai test to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "banzai_milestone_defers" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: defer banzai fulfillment refreshes"
```

## Task 3: Keep Semi Conservative and Record Full/Cached Decisions

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Write failing semi refresh visibility test**

Add:

```python
def test_semi_milestone_runs_full_fulfillment_and_records_decision(
    self, tmp_path: Path
) -> None:
    from harness.build_result import BuildResult
    from harness.llm_build_runner import LlmBuildRunner

    worktree = tmp_path / "worktree"
    spec_dir = worktree / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
        "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
        encoding="utf-8",
    )

    build_runner = MagicMock(spec=LlmBuildRunner)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0,
        status="done",
        impasse_file=None,
        stdout="",
        stderr="",
        duration_ms=100,
        task_ids=["T-001"],
    )
    fulfillment_runner = MagicMock()
    fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
        status="cached",
        exit_code=0,
        used_cache=True,
        scope="full",
        reason="full verify-spec cache hit",
        cache_key="cache123",
        report_path=str(spec_dir / "fulfillment-report.md"),
    )
    controller, _provider, gitops, state_store = _make_controller(
        tmp_path,
        mode="semi",
        llm_build_runner=build_runner,
        fulfillment_runner=fulfillment_runner,
    )
    controller._config.verify_command = f"{sys.executable} -c pass"
    gitops.create_worktree.return_value = str(worktree)

    controller.run_loop(max_outer=1, max_inner=0, build_prompt="build")

    fulfillment_runner.refresh.assert_called_once()
    refresh = state_store.read()["fulfillment_refresh"]
    assert refresh["status"] == "cached"
    assert refresh["reason"] == "full verify-spec cache hit"
    assert refresh["scope"] == "full"
    assert refresh["cache_key"] == "cache123"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "semi_milestone_runs_full" -q
```

Expected: FAIL because refresh metadata is not recorded in state.

- [ ] **Step 3: Record refresh result metadata after provider/cache result**

In `_refresh_fulfillment_report()`, after `refresh_result = self._fulfillment_runner.refresh(...)`, call:

```python
self._record_fulfillment_refresh({
    "status": getattr(refresh_result, "status", "refreshed" if exit_code == 0 else "failed"),
    "reason": getattr(refresh_result, "reason", ""),
    "scope": getattr(refresh_result, "scope", "full"),
    "cache_key": getattr(refresh_result, "cache_key", None),
    "report_path": getattr(refresh_result, "report_path", None),
})
```

Make sure `exit_code` is computed before this block:

```python
exit_code = getattr(refresh_result, "exit_code", refresh_result)
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "semi_milestone_runs_full" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: record fulfillment refresh decisions"
```

## Task 4: Add User-Facing Refresh Decision Output

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [ ] **Step 1: Write failing output tests**

Extend the banzai deferral test:

```python
captured = capsys.readouterr()
assert "fulfillment refresh: deferred" in captured.err
assert "banzai milestone defers full verify until task completion" in captured.err
```

Extend the semi refresh test:

```python
captured = capsys.readouterr()
assert "fulfillment refresh: cached" in captured.err
assert "full verify-spec cache hit" in captured.err
```

Add `capsys: pytest.CaptureFixture[str]` to both test signatures.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "fulfillment and (banzai_milestone_defers or semi_milestone_runs_full)" -q
```

Expected: FAIL because Ralph does not print refresh decisions yet.

- [ ] **Step 3: Implement compact stderr output**

Add:

```python
def _print_fulfillment_refresh_decision(self, *, status: str, reason: str) -> None:
    print(f"fulfillment refresh: {status} ({reason})", file=sys.stderr)
```

Call it from `_record_fulfillment_refresh()` after state write:

```python
self._print_fulfillment_refresh_decision(
    status=str(state["fulfillment_refresh"]["status"]),
    reason=str(state["fulfillment_refresh"]["reason"]),
)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py -k "fulfillment and (banzai_milestone_defers or semi_milestone_runs_full)" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: print fulfillment refresh decisions"
```

## Task 5: Verify Regression Suite

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused fulfillment and Ralph suites**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py tests/unit/test_ralph_outer.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run broader harness suite**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_harness_recovery.py tests/unit/test_cli_harness_resume.py tests/unit/test_ralph_outer.py tests/unit/test_ralph_commit_push.py tests/unit/test_run_skill.py tests/unit/test_land.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Confirm git status**

Run:

```bash
git status --short --branch
```

Expected: branch ahead by the Stage 1 commits, no unstaged changes.

## Self-Review

- Spec coverage: Stage 1 cache/defer policy, visible refresh decisions, and conservative semi/aggressive banzai behavior are covered. Stage 2 dirty-artifact containment, Stage 3 canonical inventory, and Stage 4 true scoped verify are intentionally not implemented here.
- Placeholder scan: no `TBD`, `TODO`, or "implement later" steps remain.
- Type consistency: `FulfillmentRefreshResult.scope/reason/cache_key/report_path`, `RalphController._record_fulfillment_refresh()`, and `fulfillment_refresh` state keys are used consistently across tasks.
