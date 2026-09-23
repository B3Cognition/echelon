# Single Delivery Controller Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Delivery strategy selection, multi-run coordination, and per-strategy state so every supported command operates one run through one `DeliveryController`.

**Architecture:** First introduce a mechanically equivalent single-run controller while the current `default` plumbing still exists, then collapse output/history, remove the public strategy surface, and finally convert all active state/evidence paths to run scope. This plan deliberately leaves Ralph’s large loop structurally unchanged; its checkpoint-led decomposition is the next S4 plan, written against the smaller interfaces produced here.

**Tech Stack:** Python 3.11+, Typer, pytest, JSON durable state, Git worktrees

**Spec:** `docs/superpowers/specs/2026-09-23-single-delivery-controller-design.md`

## Global Constraints

- Delivery has no strategy selection after this plan; `default` is not accepted as a user option or persisted as an identity.
- Historical `default.json` and multi-strategy runs are not discovered, migrated, summarized, or resumed.
- Preserve status values, transition order, retry ceilings, operation journals, checkpoint semantics, provider behavior, and controller-only state mutation.
- Do not alter unrelated uses of “strategy,” including landing merge/rebase and Spec-authoring concepts.
- Do not redesign Ralph’s loop in this plan; move the active single-run behavior mechanically.
- Follow strict RED/GREEN TDD for every production change.

---

### Task 1: Introduce the Single-Run Controller

**Files:**
- Create: `src/harness/delivery_controller.py`
- Modify: `src/harness/skills/run_skill.py:1-30,930-1035`
- Rename: `tests/unit/test_coordinator.py` to `tests/unit/test_delivery_controller.py`
- Rename: `tests/unit/test_coordinator_review_reentry.py` to `tests/unit/test_delivery_controller_review_reentry.py`
- Modify: `tests/unit/test_delivery_controller_integration.py`
- Modify: `tests/integration/test_controlled_review_reentry.py`
- Modify: `tests/integration/test_polyrepo_delivery_convergence.py`

**Interfaces:**
- Consumes: existing `RunIntent`, `DeliveryResult`, `StateStore`, `RalphController`, review, visual, repair, verification, and publication collaborators.
- Produces: a `DeliveryController` constructor with optional `fresh_branch_base` and `fresh_completed_task_ids`, `DeliveryController.run(intent: RunIntent) -> DeliveryResult`, `DeliveryController.state() -> dict[str, object]`, `_fresh_delivery_baseline(harness_root: Path, intent: Any, gitops: Any | None = None) -> str | None`, and `_fresh_delivery_completed_tasks(harness_root: Path, intent: Any, baseline: str | None, gitops: Any | None = None, *, spec_dir: Path | None = None) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing single-controller contract tests**

Add tests that import `DeliveryController`, prove `run()` returns one result,
and prove the public method delegates once to the single-run body. The migrated
controller tests in Step 4 retain the existing Ralph invocation assertions.
First rename `test_coordinator.py` and its existing `_make_coordinator` helper
to `test_delivery_controller.py` and `_make_controller`, then add:

```python
def test_delivery_controller_runs_one_delivery(monkeypatch, tmp_path):
    expected = DeliveryResult(
        status="blocked",
        termination_reason="outer_cap",
        outer_iterations=1,
        inner_iterations=0,
        pr_url=None,
        tokens_used=7,
        final_verify=None,
        blocked_phase="implementation",
    )
    controller = _make_controller(tmp_path)
    run_delivery = Mock(return_value=expected)
    monkeypatch.setattr(controller, "_run_delivery", run_delivery)
    result = controller.run(RunIntent("001", token_budget=100))

    assert result == expected
    run_delivery.assert_called_once()
```

Add a structural assertion in `tests/unit/test_delivery_controller_integration.py`:

```python
def test_delivery_controller_has_no_multi_run_api():
    from harness.delivery_controller import DeliveryController

    assert not hasattr(DeliveryController, "compare_results")
    assert not hasattr(DeliveryController, "_cancel_peers")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/integration/test_controlled_review_reentry.py
```

Expected: collection fails because `harness.delivery_controller` and `DeliveryController` do not exist.

- [ ] **Step 3: Move the active single-run body into `DeliveryController`**

Copy the non-fan-out helpers and `_run_strategy` body from `coordinator.py` into `delivery_controller.py`, then expose this exact public shape:

```python
class DeliveryController:
    def __init__(
        self,
        provider: SandboxProvider,
        gitops: Any,
        config: HarnessConfig,
        base_dir: str = ".",
        build_id: str = "",
        orchestration_root: str | Path | None = None,
        fresh_branch_base: str | None = None,
        fresh_completed_task_ids: tuple[str, ...] = (),
    ) -> None:
        self._provider = provider
        self._gitops = gitops
        self._config = config
        self._base_dir = base_dir
        self._orchestration_root = (
            Path(orchestration_root).resolve()
            if orchestration_root is not None
            else None
        )
        self._build_id = build_id
        self._build_dir = build_dir(Path(base_dir), build_id)
        self._state_dir = self._build_dir / "state"
        self._escalation_dir = self._build_dir
        self._fresh_branch_base = fresh_branch_base
        self._fresh_completed_task_ids = tuple(fresh_completed_task_ids)
        self._state_store: StateStore | None = None

    def run(self, intent: RunIntent) -> DeliveryResult:
        return self._run_delivery(intent, budget=intent.token_budget)

    def state(self) -> dict[str, object]:
        return self._state_store.read() if self._state_store is not None else {}
```

For this mechanical step only, `_run_delivery` may instantiate
`StateStore(self._state_dir, intent.spec_id, "default")` and pass
`strategy_id="default"` to existing collaborators. Remove strategy-file loading,
strategy context, build-command validation, budget slicing, thread pools,
convergence events, peer cancellation, and comparison methods from the new
module. Preserve the order and conditions inside the old single-run body.

Change `run_skill._execute_delivery_run` to construct `DeliveryController` and
call `controller.run(intent)`. Keep a temporary one-entry result adapter only
inside `run_skill.py` so the current output tests remain green until Task 2.
Collapse `_fresh_delivery_baselines` to `_fresh_delivery_baseline` returning one
commit or `None`, and collapse `_fresh_delivery_completed_tasks` to one tuple.
Use those values directly in the controller constructor instead of maps keyed
by `default`.

- [ ] **Step 4: Migrate controller-focused tests to the new owner**

Rename the two controller test modules listed above. Change imports and
monkeypatch targets from `harness.coordinator` to
`harness.delivery_controller`. Rename the existing `_make_coordinator` fixture
to `_make_controller`. Replace calls shaped like:

```python
coordinator._run_strategy(intent, "default", 10000, StrategySpec())
```

with:

```python
controller.run(replace(intent, token_budget=10000))
```

Delete tests that assert fan-out, custom strategy files, budget division,
comparison, or peer cancellation. Retain and migrate every test covering phase
resume, verification, visual/review re-entry, publication, polyrepo routing,
escalation, and finalization.

- [ ] **Step 5: Run the controller regression partition and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_stack_context_prompt.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py
```

Expected: PASS with no import or patch target referring to
`harness.coordinator` in these files.

- [ ] **Step 6: Commit**

```bash
git add src/harness/delivery_controller.py src/harness/skills/run_skill.py \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_controlled_delivery_setup.py tests/unit/test_stack_context_prompt.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py
git commit -m "refactor: introduce single delivery controller"
```

### Task 2: Collapse Run Output and History to One Result

**Files:**
- Modify: `src/harness/skills/run_skill.py:360-1035`
- Modify: `src/harness/harness_run_history.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_run_skill_checkpoint_recovery.py`
- Modify: `tests/unit/test_harness_run_history.py`

**Interfaces:**
- Consumes: `DeliveryController.run(intent) -> DeliveryResult` and `DeliveryController.state()`.
- Produces: single-result `_print_delivery_summary` and `_append_harness_history` helpers, plus `append_run` without a strategy parameter.

- [ ] **Step 1: Write failing single-result output/history tests**

Add assertions that history rows contain no `strategy_id` and that summaries
describe one delivery rather than a strategy count:

```python
def test_append_run_writes_single_delivery_identity(tmp_path):
    result = DeliveryResult(
        status="blocked",
        termination_reason="outer_cap",
        outer_iterations=1,
        inner_iterations=0,
        pr_url=None,
        tokens_used=7,
        final_verify=None,
        blocked_phase="implementation",
    )
    append_run(
        tmp_path,
        spec_id="001",
        build_id="build-1",
        mode="semi",
        result=result,
        pr_url=None,
        started_at="2026-09-23T00:00:00+00:00",
    )

    [row] = read_history(tmp_path)["runs"]
    assert "strategy_id" not in row
    assert row["build_id"] == "build-1"
```

Update `test_run_skill.py` so its fake controller returns one
`DeliveryResult` from `run()` and one dict from `state()`; assert output omits
`strategies`, `default`, and “strategies reached provider limits”.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_harness_run_history.py \
  tests/unit/test_run_skill.py \
  tests/unit/test_run_skill_checkpoint_recovery.py
```

Expected: failures show the old required `strategy_id` argument and old
comparison-shaped summary calls.

- [ ] **Step 3: Replace comparison-shaped helpers with single-result helpers**

Change the core signatures to:

```python
def _delivery_summary_facts(
    result: DeliveryResult,
    state: Mapping[str, object],
) -> dict[str, object]:
    return {
        "status": result.status,
        "termination_reason": result.termination_reason,
        "outer_iterations": result.outer_iterations,
        "inner_iterations": result.inner_iterations,
        "tokens_used": result.tokens_used,
        "build_status": state.get("build_status"),
        "provider_limit_message": state.get("provider_limit_message"),
        "completed_task_ids": state.get("completed_task_ids") or [],
    }

def _append_harness_history(
    *,
    spec_dir: Path | None,
    spec_id: str,
    build_id: str,
    mode: str,
    result: DeliveryResult,
    state: Mapping[str, object],
) -> None:
    if spec_dir is None:
        return
    append_run(
        spec_dir,
        spec_id=spec_id,
        build_id=build_id,
        mode=mode,
        result=result,
        pr_url=str(state.get("pr_url") or result.pr_url or "") or None,
        started_at=str(state.get("started_at") or "") or None,
    )
```

Calculate converged, checkpointed, provider-limited, failed, token, next-step,
landing, and exception-summary behavior directly from `result` and `state`.
Until Task 4 changes the state filename, construct an exception summary from
the one known `state/default.json` path rather than scanning `*.json`. Task 4
changes that direct lookup to `state/delivery.json`. Render history labels with
the shortened build ID alone.

Remove `result_map`, `comparison`, strategy counts, and the one-entry adapter
from `_execute_delivery_run`. Change `harness_run_history.append_run` to remove
the `strategy_id` parameter and field.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_harness_run_history.py \
  tests/unit/test_run_skill.py \
  tests/unit/test_run_skill_checkpoint_recovery.py
```

Expected: PASS; output/history tests contain no strategy-shaped fixtures.

- [ ] **Step 5: Commit**

```bash
git add src/harness/skills/run_skill.py src/harness/harness_run_history.py \
  tests/unit/test_run_skill.py tests/unit/test_run_skill_checkpoint_recovery.py \
  tests/unit/test_harness_run_history.py
git commit -m "refactor: use one delivery result"
```

### Task 3: Remove Delivery Strategy Inputs

**Files:**
- Modify: `src/echelon/cli_app.py:45-70,225-285,4415-4690`
- Modify: `src/echelon/delivery_service.py:20-60,2340-2505,2825-2870,3430-3530,3660-4150`
- Modify: `src/echelon/delivery_status.py`
- Modify: `src/harness/run_intent.py`
- Modify: `src/harness/__main__.py`
- Modify: `src/harness/skills/resume_skill.py`
- Modify: `tests/unit/test_cli_delivery.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_delivery_service_boundary.py`
- Modify: `tests/unit/test_run_intent.py`
- Modify: `tests/unit/test_resume_skill.py`
- Modify: `tests/unit/test_harness_main_run_context.py`

**Interfaces:**
- Consumes: single `DeliveryController` and fixed single-result adapters.
- Produces: `DeliveryRunRequest` and `DeliveryRecoveryRequest` without strategy fields; `RunIntent` without `strategies` or `kill_losers`.

- [ ] **Step 1: Write failing CLI and intent absence tests**

Add tests for the public contract:

```python
def test_delivery_run_help_has_no_execution_strategy(runner):
    result = runner.invoke(app, ["delivery", "run", "--help"])
    assert result.exit_code == 0
    assert "--strategy" not in result.output
    assert "--kill-losers" not in result.output


def test_run_intent_has_no_strategy_dimension():
    fields = RunIntent.__dataclass_fields__
    assert "strategies" not in fields
    assert "kill_losers" not in fields
```

Add CLI tests proving `delivery run/resume/continue/checkpoint list --strategy`
and `delivery run --kill-losers` fail as unknown options. Keep a separate
assertion that `delivery land --strategy merge` remains accepted.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_delivery_service_boundary.py \
  tests/unit/test_run_intent.py \
  tests/unit/test_resume_skill.py \
  tests/unit/test_harness_main_run_context.py
```

Expected: the removed options still appear and the dataclass still exposes both
fields.

- [ ] **Step 3: Remove the typed and Typer option surface**

Make the request types exactly:

```python
@dataclass(frozen=True)
class DeliveryRunRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    mode: str | None = None
    max_outer: int | None = None
    max_inner: int | None = None
    token_budget: int | None = None
    auto_merge: bool | None = None
    reset: bool = False


@dataclass(frozen=True)
class DeliveryRecoveryRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    answer: str | None = None
    mode: str | None = None
```

Remove execution-strategy options from `delivery run`, `resume`, `continue`,
`status`, and `checkpoint list`, plus their hidden `harness` forwarding calls.
Keep `DeliveryLandRequest.strategy` and `delivery land --strategy` unchanged.
Use Typer’s ordinary unknown-option failure for the removed flags; do not accept
or translate them.

- [ ] **Step 4: Remove natural-language and environment parsing**

Delete `_STRATEGIES_PATTERN`, `_KILL_LOSERS_PATTERN`, their parsing branches,
validation, and fields from `RunIntent`. Build the run message without a
strategy token:

```python
parts = [f"spec {spec_id}", f"{mode} mode"]
```

Remove `HARNESS_STRATEGIES`, `HARNESS_STRATEGY`, and `HARNESS_KILL_LOSERS` from
`harness.__main__`. Change resume parsing to return `(spec_id, answer)` and
construct `f"spec {spec_id} mode={mode} resume\n\ntask: {answer}"`.

In `delivery_service`, remove strategy key parsing and status/checkpoint labels.
An extra positional token such as `strategy=foo` has no control meaning and is
treated by the existing free-text rules; only the removed `--strategy` option
must be rejected by Typer.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2.

Expected: PASS, including the preserved `delivery land --strategy merge`
coverage.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli_app.py src/echelon/delivery_service.py \
  src/echelon/delivery_status.py \
  src/harness/run_intent.py src/harness/__main__.py \
  src/harness/skills/resume_skill.py tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_typer_app.py tests/unit/test_delivery_service_boundary.py \
  tests/unit/test_run_intent.py tests/unit/test_resume_skill.py \
  tests/unit/test_harness_main_run_context.py
git commit -m "feat: remove delivery strategy options"
```

### Task 4: Convert Durable State to One Run-Scoped File

**Files:**
- Modify: `src/harness/state.py:130-470`
- Modify: `src/harness/delivery_controller.py`
- Modify: `src/echelon/delivery_service.py:340-390,2340-2410,3230-3320,3660-4150`
- Modify: `src/echelon/delivery_status.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/skills/status_skill.py`
- Modify: `src/harness/skills/resume_skill.py`
- Modify: `src/harness/gc.py`
- Modify: `tests/unit/test_state_machine.py`
- Modify: `tests/unit/test_state_store_logic.py`
- Modify: `tests/unit/test_cli_delivery_status.py`
- Modify: `tests/unit/test_cli_harness_run.py`
- Modify: `tests/unit/test_cli_harness_resume.py`
- Modify: `tests/unit/test_gc_logic.py`
- Modify: `tests/unit/test_controlled_delivery_setup.py`
- Modify: `tests/unit/test_delivery_controller.py`
- Modify: `tests/unit/test_delivery_controller_review_reentry.py`
- Modify: `tests/unit/test_delivery_controller_integration.py`
- Modify: `tests/unit/test_ralph_commit_push.py`
- Modify: `tests/unit/test_ralph_inner.py`
- Modify: `tests/unit/test_ralph_outer.py`
- Modify: `tests/integration/test_controlled_review_reentry.py`

**Interfaces:**
- Consumes: build-scoped `state_dir` and `spec_id`.
- Produces: `StateStore(state_dir: Path, spec_id: str)` using `delivery.json`, `delivery.lock`, and `delivery.json.bak` with no `strategy_id` state field.

- [ ] **Step 1: Write failing fixed-path tests**

Add this contract to `test_state_machine.py`:

```python
def test_state_store_has_one_delivery_identity(tmp_path):
    store = StateStore(tmp_path, "001")
    store.initialize(run_id="run-1", mode="semi")

    assert store.state_file == tmp_path / "delivery.json"
    assert store.lock_file == tmp_path / "delivery.lock"
    assert "strategy_id" not in store.read()
    assert not (tmp_path / "default.json").exists()
```

Add a compatibility refusal test:

```python
def test_state_store_ignores_historical_default_state(tmp_path):
    (tmp_path / "default.json").write_text('{"status":"blocked"}')

    assert StateStore(tmp_path, "001").read() == {}
```

- [ ] **Step 2: Run state/status tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_state_machine.py tests/unit/test_state_store_logic.py \
  tests/unit/test_cli_delivery_status.py tests/unit/test_cli_harness_run.py \
  tests/unit/test_cli_harness_resume.py tests/unit/test_gc_logic.py
```

Expected: constructor arity and path assertions fail against per-strategy state.

- [ ] **Step 3: Implement the fixed StateStore contract**

Change initialization to:

```python
def __init__(self, state_dir: Path, spec_id: str) -> None:
    self.state_dir = Path(state_dir)
    self.spec_id = spec_id
    self.state_file = self.state_dir / "delivery.json"
    self.lock_file = self.state_dir / "delivery.lock"
    self._data: dict[str, Any] | None = None
```

Remove `strategy_id` from `initialize()`. Preserve atomic temporary writes,
`.json.bak`, lock ownership, stale-lock behavior, state transitions, mode
immutability, monotonic counters, and append-only logs unchanged.

- [ ] **Step 4: Convert active state readers to the fixed path**

Replace every active `StateStore(state_dir, spec_id, strategy)` construction
with `StateStore(state_dir, spec_id)`. Status, checkpoints, exception summaries,
resume, continuation, GC, and current-build discovery must read only
`state/delivery.json`; remove `glob("*.json")` state discovery and all fallback
to `default.json`.

Return one status object shaped as:

```python
{
    "active_loops": 0 or 1,
    "delivery": {
        "status": state.get("status", "unknown"),
        "outer_iter": state.get("outer_iter", 0),
        "inner_iter": state.get("inner_iter", 0),
        "tokens_used": state.get("tokens_used", 0),
        "token_budget": state.get("token_budget"),
        "pr_url": state.get("pr_url"),
        "termination_reason": state.get("termination_reason"),
    },
}
```

- [ ] **Step 5: Update fixtures and verify GREEN**

Mechanically change test construction from
`StateStore(path, spec_id, "default")` to `StateStore(path, spec_id)`, then run
the command from Step 2 and:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_ralph_commit_push.py tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/integration/test_controlled_review_reentry.py
```

Expected: PASS and no tested command discovers `default.json`.

- [ ] **Step 6: Commit**

```bash
git add src/harness/state.py src/harness/delivery_controller.py \
  src/echelon/delivery_service.py src/echelon/delivery_status.py src/echelon/cli.py \
  src/harness/skills/status_skill.py src/harness/skills/resume_skill.py \
  src/harness/gc.py tests/unit/test_state_machine.py \
  tests/unit/test_state_store_logic.py tests/unit/test_cli_delivery_status.py \
  tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py \
  tests/unit/test_gc_logic.py tests/unit/test_controlled_delivery_setup.py \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_ralph_commit_push.py tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py tests/integration/test_controlled_review_reentry.py
git commit -m "refactor: use one delivery state file"
```

### Task 5: Remove Strategy Identity from Active Delivery Artifacts

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/gitops.py`
- Modify: `src/harness/recovery.py`
- Modify: `src/harness/escalation.py`
- Modify: `src/harness/review_loop.py`
- Modify: `src/harness/visual_ralph.py`
- Modify: `src/harness/candidate_evidence.py`
- Modify: `src/harness/verification_evidence.py`
- Modify: `src/harness/visual_evidence.py`
- Modify: `src/harness/runnability_evidence.py`
- Modify: `src/harness/runnability_runner.py`
- Modify: `src/harness/verification_stack_runtime.py`
- Modify: `src/harness/coverage_observer_runner.py`
- Modify: `src/harness/authoritative_spec_verifier.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_authoritative_spec_verifier.py`
- Modify: `tests/unit/test_cli_spec_verify.py`
- Modify: `tests/unit/test_controlled_fulfillment_delivery.py`
- Modify: `tests/unit/test_gitops_skill.py`
- Modify: `tests/unit/test_gitops_worktree.py`
- Modify: `tests/unit/test_land.py`
- Modify: `tests/unit/test_verification_stack_runtime.py`
- Modify: relevant focused unit/integration tests already listed for the other files above

**Interfaces:**
- Consumes: `spec_id`, `build_id`, fixed `StateStore`, and existing typed result/evidence objects.
- Produces: active Delivery constructors and receipt schemas with no `strategy_id`; branch/worktree/artifact identity derives from `spec_id` plus `build_id` where uniqueness is required.

- [ ] **Step 1: Write failing artifact identity tests**

Add structural and behavioral assertions:

```python
def test_verification_receipt_has_no_strategy_identity(tmp_path):
    ref = _write_fixture_receipt(tmp_path)
    payload = json.loads(ref.path.read_text())
    assert "strategy_id" not in payload
    assert payload["build_id"] == "build-1"


def test_get_latest_worktree_is_build_scoped(tmp_path):
    gitops = _make_gitops(tmp_path)
    expected = tmp_path / "runs/build-1/worktrees/iter-2"
    expected.mkdir(parents=True)

    assert gitops.get_latest_worktree("001", build_id="build-1") == str(expected)
```

Add matching tests for visual/runnability receipts, review state paths
(`review.json`, `review-status.json`), visual evidence paths
(`evidence/visual/attempts` with no strategy segment), escalation metadata, recovery,
and branch naming (`harness/001/build-1/iter-2`).

- [ ] **Step 2: Run the artifact/recovery partition and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_commit_push.py tests/unit/test_harness_recovery.py \
  tests/unit/test_escalation.py tests/unit/test_review_loop.py \
  tests/unit/test_visual_evidence.py tests/unit/test_visual_ralph.py \
  tests/unit/test_verification_evidence.py \
  tests/unit/test_runnability_evidence.py tests/unit/test_runnability_runner.py \
  tests/unit/test_coverage_observer_runner.py \
  tests/unit/test_authoritative_spec_verifier.py \
  tests/unit/test_cli_spec_verify.py \
  tests/unit/test_controlled_fulfillment_delivery.py \
  tests/unit/test_gitops_skill.py tests/unit/test_gitops_worktree.py \
  tests/unit/test_land.py \
  tests/unit/test_verification_stack_runtime.py
```

Expected: constructor/signature, path, and receipt-schema failures expose the
remaining strategy identity.

- [ ] **Step 3: Change Git/recovery identity to spec plus build**

Remove the strategy parameter from these public signatures:

```python
def create_worktree(
    self,
    spec_id: str,
    outer_iter: int,
    *,
    build_id: str,
    base_branch: str | None = None,
    prepare_codegraph: bool = False,
    fresh_branch: bool = False,
    fresh_branch_base: str | None = None,
) -> str:
    # Keep the existing validation, checkout, and rollback body. Replace its
    # two identity calculations with these values.
    worktree_path = (
        _build_dir_fn(self._base_dir, build_id)
        / "worktrees"
        / f"iter-{outer_iter}"
    )
    branch_name = f"harness/{spec_id}/{build_id}/iter-{outer_iter}"

def get_latest_worktree(self, spec_id: str, *, build_id: str) -> str | None:
    root = _build_dir_fn(self._base_dir, build_id) / "worktrees"
    candidates = sorted(root.glob("iter-*"), reverse=True)
    return str(candidates[0]) if candidates else None
```

Create worktrees under `runs/<build_id>/worktrees/iter-<N>` and branches under
`harness/<spec_id>/<build_id>/iter-<N>`. Remove “Strategy:” from PR bodies and
strategy-based commit detection; use the exact spec/build branch prefix during
recovery.

- [ ] **Step 4: Remove strategy fields and path segments from collaborators**

Remove `strategy_id` parameters, attributes, JSON fields, validator requirements,
status text, and path components from Ralph, escalation, review, visual,
candidate, verification, runnability, coverage, and verification-stack code.
Where a receipt already contains `build_id`, use it as the run binding. Where a
filename only needs one run-local owner, use a fixed descriptive name such as
`review.json`, `review-status.json`, or `delivery-escalation-<timestamp>.md`.

Change Ralph’s constructor from:

```python
RalphController(provider=provider, gitops=gitops, state_store=state_store,
                mode_controller=mode_controller, escalation_handler=escalation_handler,
                spec_id=spec_id, strategy_id=strategy_id, config=config,
                build_id=build_id)
```

to:

```python
RalphController(provider=provider, gitops=gitops, state_store=state_store,
                mode_controller=mode_controller, escalation_handler=escalation_handler,
                spec_id=spec_id, config=config, build_id=build_id)
```

Do not alter slice dispatch, journal ordering, retries, verification, or
publication logic while removing the identity parameter.

- [ ] **Step 5: Run the artifact/recovery partition and verify GREEN**

Run the command from Step 2, plus:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/integration/test_ralph_controller.py
```

Expected: PASS with receipt validation and interruption recovery unchanged apart
from the removed identity field.

- [ ] **Step 6: Commit**

```bash
git add src/harness/ralph.py src/harness/gitops.py src/harness/recovery.py \
  src/harness/escalation.py src/harness/review_loop.py \
  src/harness/visual_ralph.py src/harness/candidate_evidence.py \
  src/harness/verification_evidence.py src/harness/visual_evidence.py \
  src/harness/runnability_evidence.py src/harness/runnability_runner.py \
  src/harness/verification_stack_runtime.py \
  src/harness/coverage_observer_runner.py \
  src/harness/authoritative_spec_verifier.py src/harness/land.py tests
git commit -m "refactor: remove delivery strategy identity"
```

### Task 6: Delete the Multi-Strategy Implementation and Close the Cutover

**Files:**
- Delete: `src/harness/coordinator.py`
- Delete: `src/harness/strategy_loader.py`
- Delete: `src/harness/budget.py`
- Delete: `tests/unit/test_strategy_loader.py`
- Delete: `tests/unit/test_budget.py`
- Delete: `tests/e2e/test_multi_strategy.py`
- Modify: `tests/e2e/conftest.py`
- Modify: `src/harness/review_loop.py`
- Modify: `src/harness/ralph.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/simplification-control.md`
- Create: `tests/unit/test_single_delivery_structure.py`

**Interfaces:**
- Consumes: the completed single-run controller/state/artifact contracts.
- Produces: a deletion guard proving the retired architecture cannot re-enter production.

- [ ] **Step 1: Write the structural deletion guard and verify RED**

Create `tests/unit/test_single_delivery_structure.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_retired_delivery_strategy_modules_are_absent():
    for relative in (
        "src/harness/coordinator.py",
        "src/harness/strategy_loader.py",
        "src/harness/budget.py",
    ):
        assert not (ROOT / relative).exists(), relative


def test_active_delivery_source_has_no_strategy_execution_vocabulary():
    paths = (
        ROOT / "src/harness/delivery_controller.py",
        ROOT / "src/harness/run_intent.py",
        ROOT / "src/harness/state.py",
        ROOT / "src/harness/skills/run_skill.py",
    )
    forbidden = (
        "StrategyCoordinator",
        "strategy_id",
        "kill_losers",
        "load_strategies",
        "slice_budget",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for token in forbidden:
        assert token not in combined
```

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_single_delivery_structure.py
```

Expected: FAIL because the three retired modules still exist.

- [ ] **Step 2: Delete dead modules/tests and stale references**

Delete the three production modules and their strategy-only tests. Remove
multi-strategy factories from `tests/e2e/conftest.py` and stale coordinator
wording from active module docstrings. Do not edit historical specs, findings,
plans, changelog entries, or receipts merely because they record the old design.

- [ ] **Step 3: Update current documentation and milestone tracking**

Document only:

```text
echelon delivery run <spec_id>
echelon delivery continue <spec_id>
echelon delivery resume <spec_id> "<answer>"
```

Keep `delivery land --strategy merge|rebase` documented as an unrelated landing
choice. In `docs/simplification-control.md`, check off the cutover items, record
focused evidence, and set the next S4 action to writing the Ralph durable-step
decomposition plan. Do not mark S4 complete yet.

- [ ] **Step 4: Run static absence checks**

Run:

```bash
test ! -e src/harness/coordinator.py
test ! -e src/harness/strategy_loader.py
test ! -e src/harness/budget.py
! rg -n "StrategyCoordinator|kill_losers|HARNESS_STRATEGIES|HARNESS_STRATEGY|strategies=" src --glob '!src/harness/re_v2/**'
! rg -n 'strategy_id' src/harness/delivery_controller.py src/harness/run_intent.py src/harness/state.py src/harness/ralph.py src/harness/skills/run_skill.py
```

Expected: every command exits zero. Review remaining `strategy` matches manually
and confirm they belong to landing, Spec authoring, discovery, or historical
documents.

- [ ] **Step 5: Run focused Delivery verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_single_delivery_structure.py \
  tests/unit/test_run_intent.py tests/unit/test_state_machine.py \
  tests/unit/test_state_store_logic.py tests/unit/test_run_skill.py \
  tests/unit/test_run_skill_checkpoint_recovery.py \
  tests/unit/test_delivery_controller_integration.py \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_status.py \
  tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py \
  tests/unit/test_harness_run_history.py tests/unit/test_harness_recovery.py \
  tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py \
  tests/unit/test_review_loop.py tests/unit/test_visual_ralph.py \
  tests/unit/test_verification_evidence.py tests/unit/test_runnability_evidence.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py \
  tests/integration/test_ralph_controller.py
```

Expected: PASS.

- [ ] **Step 6: Commit the completed cutover**

```bash
git add -A
git commit -m "refactor: retire multi-strategy delivery"
```

- [ ] **Step 7: Run the repository verification gate**

Run the repository gate against the approved S4 design commit:

```bash
.venv/bin/python scripts/merge_verification.py plan --base 52f30d16
.venv/bin/python scripts/merge_verification.py run --base 52f30d16
```

Record the tested commit, tree, pass/fail/deselected counts, elapsed time, and
receipt path in `docs/simplification-control.md`.

Expected: zero failures. Commit only the generated receipt and evidence update:

```bash
git add docs/simplification-control.md tests/reports/merge-verification
git commit -m "docs: record single delivery cutover verification"
```

### Follow-on Plan Boundary

After this plan is merged and the repository gate is green, inspect the now
single-run `DeliveryController` and `RalphController` again. Write a second S4
plan that extracts, in order, pending-operation recovery, one controlled slice,
progress checkpointing, candidate verification, review re-entry, verified
publication, and terminal finalization. That plan must preserve the fixed
`delivery.json` contract produced here and must use characterization tests at
every extraction boundary.
