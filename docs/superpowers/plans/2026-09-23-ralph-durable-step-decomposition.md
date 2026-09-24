# Ralph Durable-Step Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the two thousand-line Delivery/Ralph orchestration methods to explicit checkpoint-led dispatchers without changing Delivery behavior or durable state.

**Architecture:** Extract existing behavior in place, one durable boundary at a time. `DeliveryController` remains the single run/phase owner, `RalphController` remains the implementation-loop owner, and narrow typed outcomes replace implicit local-variable coupling; no generic workflow framework or state migration is introduced.

**Tech Stack:** Python 3.11, dataclasses, existing Echelon Delivery/Ralph controllers, pytest, Git worktrees, repository merge-verification script.

**Spec:** `docs/superpowers/specs/2026-09-23-ralph-durable-step-decomposition-design.md`

## Global Constraints

- Preserve `delivery.json`, `delivery.lock`, and `delivery.json.bak` exactly.
- Do not add, remove, rename, or migrate durable state keys.
- Preserve status values, legal transitions, transition order, retry policy, token accounting, convergence accounting, escalation semantics, and error reasons.
- Preserve `delivery_slice_operation`, `checkpoint_commits`, registered-worktree provenance, `pending_review_reentry`, and `verified_publish_checkpoint` shapes.
- Python controllers remain the sole durable-state writers; provider output is evidence, not authority.
- Do not introduce a workflow engine, phase registry, asynchronous phase dispatch, or module split based only on line count.
- Add characterization coverage before moving each behavior boundary.
- Keep every task independently green and commit it before beginning the next task.

## Approved Execution Amendment

The user approved a characterization-first exception for this pure refactor.
For Tasks 1-9, this section supersedes each instruction to add a failing test
whose only failure is the absence of a new private method or result type:

1. name the existing observable state, result, or side effect protected by the
   extraction;
2. run its existing behavior/recovery tests green before editing production
   code;
3. add a behavior-level characterization test only when that observable
   contract is not already covered;
4. never assert that a private extraction method exists, and never assert on a
   mock merely to prove internal delegation;
5. extract the minimum code behind the planned typed seam;
6. rerun the same behavior/recovery partition after the extraction.

The code snippets for private-seam RED tests remain design examples for the
intended signatures, not tests to copy into the suite. All production behavior,
state-contract, focused-verification, commit, and repository-gate steps remain
mandatory.

---

### Task 1: Extract pending-slice recovery

**Files:**
- Modify: `src/harness/ralph.py:426-550`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_delivery_finalization.py`

**Interfaces:**
- Consumes: `RalphController._state_store`, persisted `delivery_slice_operation`, and current iteration accounting.
- Produces: `PendingSliceRecovery` and `RalphController._recover_pending_slice(...)` for Task 2.

- [x] **Step 1: Add failing seam tests**

Add direct characterization tests that require the new typed recovery boundary:

```python
def test_pending_slice_recovery_reuses_safe_persisted_worktree(tmp_path: Path) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    state = controller._state_store.read()
    state["delivery_slice_operation"] = {
        "id": "slice-1",
        "status": "dispatched",
        "worktree_path": str(worktree),
    }
    controller._state_store.write(state)

    outcome = controller._recover_pending_slice(
        outer_iter=1,
        total_inner_iterations=2,
        pr_url=None,
        tokens_used=10,
    )

    assert outcome.recovering is True
    assert outcome.worktree_path == str(worktree)
    assert outcome.blocked_result is None


def test_pending_slice_recovery_blocks_unsafe_worktree_without_dispatch(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._exec_build = MagicMock()
    state = controller._state_store.read()
    state["delivery_slice_operation"] = {
        "id": "slice-1",
        "status": "dispatched",
        "worktree_path": "relative/candidate",
    }
    controller._state_store.write(state)

    outcome = controller._recover_pending_slice(
        outer_iter=1,
        total_inner_iterations=0,
        pr_url=None,
        tokens_used=0,
    )

    assert outcome.blocked_result is not None
    assert outcome.blocked_result.termination_reason == "delivery_reconciliation_required"
    controller._exec_build.assert_not_called()
```

- [x] **Step 2: Run the seam tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'pending_slice_recovery' \
  tests/unit/test_delivery_finalization.py -x
```

Expected: FAIL because `PendingSliceRecovery` and `_recover_pending_slice` do not exist.

- [x] **Step 3: Add the typed recovery result and extract existing behavior**

Add beside the existing Ralph result dataclasses:

```python
@dataclass(frozen=True)
class PendingSliceRecovery:
    recovering: bool
    worktree_path: str | None = None
    blocked_result: ImplementationResult | None = None
```

Add the exact method seam:

```python
def _recover_pending_slice(
    self,
    *,
    outer_iter: int,
    total_inner_iterations: int,
    pr_url: str | None,
    tokens_used: int,
) -> PendingSliceRecovery:
    """Reconcile a persisted slice before any fresh provider dispatch."""
```

Move the current `delivery_slice_operation` lookup and safe-worktree validation
from `_run_loop_inner` into this method. Preserve the existing
`delivery_reconciliation_required` finalization payload verbatim. Replace the
inline block with one call and an immediate return when `blocked_result` is set.

- [x] **Step 4: Run focused recovery verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_delivery_finalization.py \
  tests/unit/test_run_skill_checkpoint_recovery.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py tests/unit/test_delivery_finalization.py
git commit -m "refactor: extract pending delivery slice recovery"
```

### Task 2: Extract iteration worktree preparation

**Files:**
- Modify: `src/harness/ralph.py:490-610`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/integration/test_ralph_controller.py`

**Interfaces:**
- Consumes: `PendingSliceRecovery` from Task 1, feature branch, iteration counters, and current resume worktree.
- Produces: `PreparedIteration` and `RalphController._prepare_iteration(...)` for Tasks 3 and 6.

- [x] **Step 1: Add failing worktree-preparation tests**

Add tests that directly cover all three current paths: recovered operation,
downstream-reentry worktree, and new worktree creation.

```python
def test_prepare_iteration_consumes_registered_reentry_once(tmp_path: Path) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    controller._resume_worktree_path = str(worktree)
    state = controller._state_store.read()
    state["downstream_reentry"] = {"reason": "candidate_changed_after_checkpoint"}
    controller._state_store.write(state)

    prepared = controller._prepare_iteration(
        recovery=PendingSliceRecovery(recovering=False),
        feature_branch=None,
        outer_iter=1,
        start_outer=1,
        total_inner_iterations=0,
        pr_url=None,
        tokens_used=0,
    )

    assert prepared.worktree_path == str(worktree)
    assert prepared.blocked_result is None
    assert controller._state_store.read()["downstream_reentry"]["consumed"] is True


def test_prepare_iteration_creates_build_scoped_worktree(tmp_path: Path) -> None:
    controller, *_ = _make_controller(tmp_path)
    controller._gitops.create_worktree.return_value = "/tmp/candidate"

    prepared = controller._prepare_iteration(
        recovery=PendingSliceRecovery(recovering=False),
        feature_branch="spec/001",
        outer_iter=2,
        start_outer=1,
        total_inner_iterations=0,
        pr_url=None,
        tokens_used=0,
    )

    controller._gitops.create_worktree.assert_called_once_with(
        controller._spec_id,
        2,
        build_id=controller._build_id,
        base_branch="spec/001",
        prepare_codegraph=True,
        fresh_branch=False,
        fresh_branch_base=None,
    )
    assert prepared.worktree_path == "/tmp/candidate"
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'prepare_iteration' -x
```

Expected: FAIL because `PreparedIteration` and `_prepare_iteration` do not exist.

- [x] **Step 3: Extract worktree selection and Phase A synchronization**

Add:

```python
@dataclass(frozen=True)
class PreparedIteration:
    worktree_path: str | None = None
    recovering_slice: bool = False
    preserve_worktree: bool = False
    blocked_result: ImplementationResult | None = None
```

Add:

```python
def _prepare_iteration(
    self,
    *,
    recovery: PendingSliceRecovery,
    feature_branch: str | None,
    outer_iter: int,
    start_outer: int,
    total_inner_iterations: int,
    pr_url: str | None,
    tokens_used: int,
) -> PreparedIteration:
    """Select and prepare exactly one candidate worktree."""
```

Move only existing worktree selection, downstream-reentry consumption, and
Phase A input synchronization into this method. Preserve current fresh-branch
arguments and the `build_incomplete`/`verified_provenance_unavailable` block
payloads. Keep cleanup in `_run_loop_inner`'s existing `finally` path.

- [x] **Step 4: Run worktree and resume verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_gitops_worktree.py \
  tests/integration/test_ralph_controller.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py tests/integration/test_ralph_controller.py
git commit -m "refactor: extract Ralph iteration preparation"
```

### Task 3: Extract one controlled-slice dispatch

**Files:**
- Modify: `src/harness/ralph.py:600-720`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_delivery_source_feedback.py`

**Interfaces:**
- Consumes: a `PreparedIteration`, prompt/context inputs, and current token accounting.
- Produces: `ControlledSliceDispatch` and `RalphController._dispatch_controlled_slice(...)` for Task 4.

- [x] **Step 1: Add failing dispatch-boundary tests**

```python
def test_dispatch_controlled_slice_returns_evidence_without_applying_progress(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    controller._exec_build = MagicMock(
        return_value={"passed": True, "tokens": 7, "task_ids": ["T-001"]}
    )
    controller._apply_build_task_progress = MagicMock()

    outcome = controller._dispatch_controlled_slice(
        worktree_path=str(worktree),
        outer_iter=1,
        build_command="echelon build",
        delivery_context="context",
        build_prompt="prompt",
        last_verify_failures_text="",
        tokens_used=3,
        token_budget=100,
        total_inner_iterations=0,
        pr_url=None,
    )

    assert outcome.build_result is not None
    assert outcome.tokens_used == 10
    assert outcome.terminal_result is None
    controller._apply_build_task_progress.assert_not_called()
```

Add a second case that returns the unchanged `containment_violation` terminal
result and asserts no progress mutation occurs.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'dispatch_controlled_slice' -x
```

Expected: FAIL because the typed dispatch seam does not exist.

- [x] **Step 3: Extract provider dispatch and containment checks**

Add:

```python
@dataclass(frozen=True)
class ControlledSliceDispatch:
    before_state: dict[str, Any]
    before_head: str
    after_head: str
    build_result: dict[str, Any] | None
    tokens_used: int
    terminal_result: ImplementationResult | None = None
```

Add:

```python
def _dispatch_controlled_slice(
    self,
    *,
    worktree_path: str,
    outer_iter: int,
    build_command: str,
    delivery_context: str,
    build_prompt: str,
    last_verify_failures_text: str,
    tokens_used: int,
    token_budget: int | None,
    total_inner_iterations: int,
    pr_url: str | None,
) -> ControlledSliceDispatch:
    """Dispatch one controlled slice and validate its immediate evidence."""
```

Move the stale-status clear, prompt construction, containment snapshots,
`_exec_build` call, source/harness/filesystem containment checks, known-token
accounting, completed-task-ID validation, and build iteration log into this
method. Do not apply canonical task progress or commit a checkpoint here.

- [x] **Step 4: Run dispatch and containment verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_delivery_source_feedback.py \
  tests/unit/test_stack_context_prompt.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py tests/unit/test_delivery_source_feedback.py
git commit -m "refactor: extract controlled slice dispatch"
```

### Task 4: Extract accepted-progress checkpointing

**Files:**
- Modify: `src/harness/ralph.py:700-840`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_run_skill_checkpoint_recovery.py`

**Interfaces:**
- Consumes: `ControlledSliceDispatch` from Task 3 and the prepared worktree.
- Produces: `ProgressCheckpointOutcome` and `RalphController._checkpoint_slice_progress(...)` for Task 5.

- [x] **Step 1: Add failing progress-boundary tests**

```python
def test_checkpoint_slice_progress_binds_canonical_task_completion(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    dispatch = ControlledSliceDispatch(
        before_state=controller._state_store.read(),
        before_head="before",
        after_head="after",
        build_result={
            "passed": True,
            "task_ids": ["T-001"],
            "build_status": "done",
            "completion_marker_explicit": True,
        },
        tokens_used=5,
    )
    controller._apply_build_task_progress = MagicMock(return_value=["T-001"])
    controller._try_checkpoint_progress_commit = MagicMock(return_value="checkpoint")

    outcome = controller._checkpoint_slice_progress(
        dispatch=dispatch,
        worktree_path=str(worktree),
        outer_iter=1,
    )

    assert outcome.checkpoint_commit == "checkpoint"
    assert outcome.build_result["passed"] is True
```

Add a mismatch case asserting that missing canonical task IDs convert the build
to `task_progress_update_failed` exactly as today.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'checkpoint_slice_progress' -x
```

Expected: FAIL because `ProgressCheckpointOutcome` and the method do not exist.

- [x] **Step 3: Extract progress application and checkpoint invocation**

Add:

```python
@dataclass(frozen=True)
class ProgressCheckpointOutcome:
    build_result: dict[str, Any]
    checkpoint_commit: str | None
    changed_files: tuple[str, ...]
```

Add:

```python
def _checkpoint_slice_progress(
    self,
    *,
    dispatch: ControlledSliceDispatch,
    worktree_path: str,
    outer_iter: int,
) -> ProgressCheckpointOutcome:
    """Apply accepted task progress and record its durable checkpoint."""
```

Move `_apply_build_task_progress`, completion-set mismatch handling,
`_changed_files_since_head`, and `_try_checkpoint_progress_commit` into this
method. Keep `_checkpoint_progress_commit` unchanged as the Git/evidence
primitive. Preserve verification-deferred checkpoint behavior and operation
receipt clearing exactly.

- [x] **Step 4: Run progress/recovery verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_run_skill_checkpoint_recovery.py \
  tests/unit/test_harness_recovery.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py tests/unit/test_run_skill_checkpoint_recovery.py
git commit -m "refactor: extract delivery progress checkpoint"
```

### Task 5: Extract candidate verification

**Files:**
- Modify: `src/harness/ralph.py:780-1240`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_verification_evidence.py`
- Test: `tests/unit/test_runnability_evidence.py`

**Interfaces:**
- Consumes: prepared worktree, `ProgressCheckpointOutcome`, iteration accounting, and configured gate helpers.
- Produces: `CandidateCheckpointOutcome` and `RalphController._verify_candidate_checkpoint(...)` for Task 6.

**Execution note:** The live controller also requires the current loop state and
outer convergence ceiling. Verification returns `VERIFIED` without publishing;
the caller retains the existing commit/merge/PR sequence and creates the final
`ImplementationResult`. This corrects the illustrative signature below without
changing runtime ordering.

- [x] **Step 1: Add failing candidate-checkpoint tests**

```python
def test_verify_candidate_checkpoint_returns_verified_without_publishing(
    tmp_path: Path,
) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    controller._exec_verify = MagicMock(return_value=VerifyResult(passed=True))
    controller._apply_post_verify_gates = MagicMock(
        return_value=VerifyResult(passed=True)
    )
    controller._merge_verified_branch = MagicMock()

    outcome = controller._verify_candidate_checkpoint(
        worktree_path=str(worktree),
        branch="harness/001/build-1/iter-1",
        outer_iter=1,
        total_inner_iterations=0,
        pr_url=None,
        tokens_used=0,
        max_inner=3,
        token_budget=None,
        build_command="echelon build",
        delivery_context="",
        build_prompt="prompt",
        changed_files=(),
    )

    assert outcome.decision == CandidateDecision.VERIFIED
    assert outcome.result is not None
    controller._merge_verified_branch.assert_not_called()
```

Add cases for a repairable verifier failure and an existing blocking gate,
asserting unchanged `termination_reason` and inner-iteration accounting.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'verify_candidate_checkpoint' -x
```

Expected: FAIL because the candidate outcome types and method do not exist.

- [x] **Step 3: Extract the ordered verification decision**

Add:

```python
class CandidateDecision(str, Enum):
    CONTINUE = "continue"
    VERIFIED = "verified"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class CandidateCheckpointOutcome:
    decision: CandidateDecision
    result: ImplementationResult | None
    final_verify: VerifyResult | None
    total_inner_iterations: int
    tokens_used: int
    pr_url: str | None
    last_verify_failures_text: str = ""
```

Add:

```python
def _verify_candidate_checkpoint(
    self,
    *,
    worktree_path: str,
    branch: str,
    outer_iter: int,
    total_inner_iterations: int,
    pr_url: str | None,
    tokens_used: int,
    max_inner: int,
    token_budget: int | None,
    build_command: str,
    delivery_context: str,
    build_prompt: str,
    changed_files: tuple[str, ...],
) -> CandidateCheckpointOutcome:
    """Run the existing ordered candidate gates and classify the next action."""
```

Move verification plus current task-progress, fulfillment, documentation,
runnability, coverage, evidence, diagnosis, and inner-repair decisions without
reordering helpers. Preserve deferred-target behavior: this method may bind the
verified candidate but must not publish when downstream visual/review phases are
enabled.

- [x] **Step 4: Run the focused verification stack**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_verification_evidence.py \
  tests/unit/test_runnability_evidence.py \
  tests/unit/test_coverage_observation.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py tests/unit/test_verification_evidence.py tests/unit/test_runnability_evidence.py
git commit -m "refactor: extract candidate verification checkpoint"
```

### Task 6: Flatten the Ralph outer loop

**Files:**
- Modify: `src/harness/ralph.py:426-1417`
- Test: `tests/unit/test_ralph_inner.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/integration/test_ralph_controller.py`

**Interfaces:**
- Consumes: Tasks 1-5 typed boundaries.
- Produces: `OuterIterationOutcome`, `_run_outer_iteration(...)`, and a dispatcher-only `_run_loop_inner` for Delivery.

- [x] **Step 1: Add failing composition tests**

```python
def test_run_loop_inner_dispatches_one_named_outer_iteration(tmp_path: Path) -> None:
    controller, *_ = _make_controller(tmp_path)
    verified = ImplementationResult(
        "verified", "verified", 1, 0, None, 0, VerifyResult(passed=True)
    )
    controller._run_outer_iteration = MagicMock(
        return_value=OuterIterationOutcome(
            decision=CandidateDecision.VERIFIED,
            result=verified,
            outer_iter=1,
            total_inner_iterations=0,
            tokens_used=0,
            pr_url=None,
            final_verify=verified.final_verify,
        )
    )

    result = controller._run_loop_inner(
        max_outer=3,
        max_inner=2,
        token_budget=None,
        build_command="echelon build",
        delivery_context="",
        build_prompt="prompt",
    )

    assert result is verified
    controller._run_outer_iteration.assert_called_once()
```

Add a continue case proving counters from `OuterIterationOutcome` feed the next
call and a terminal case proving no second iteration is dispatched.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_outer.py -k 'named_outer_iteration' -x
```

Expected: FAIL because the composition seam does not exist.

- [x] **Step 3: Compose one outer iteration from extracted boundaries**

Add:

```python
@dataclass(frozen=True)
class OuterIterationOutcome:
    decision: CandidateDecision
    result: ImplementationResult | None
    outer_iter: int
    total_inner_iterations: int
    tokens_used: int
    pr_url: str | None
    final_verify: VerifyResult | None
    last_verify_failures_text: str = ""
```

Add `_run_outer_iteration(...) -> OuterIterationOutcome` and compose Tasks 1-5
in the existing order. Keep the existing worktree-preservation and cleanup
`finally` semantics inside this method.

Rewrite `_run_loop_inner` so it only:

1. validates/opens Ralph state;
2. handles blocked/interrupted entry;
3. resolves the feature branch;
4. checks loop termination;
5. calls `_run_outer_iteration`;
6. continues or returns based on its typed decision;
7. applies the existing outer-cap finalization.

- [x] **Step 4: Run all Ralph characterization tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_ralph_commit_push.py \
  tests/unit/test_delivery_finalization.py \
  tests/integration/test_ralph_controller.py -x
```

Expected: PASS.

- [x] **Step 5: Check orchestration size and commit**

Run:

```bash
.venv/bin/python - <<'PY'
import ast
from pathlib import Path
tree = ast.parse(Path("src/harness/ralph.py").read_text())
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RalphController")
method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "_run_loop_inner")
assert method.end_lineno - method.lineno + 1 <= 220
print(method.end_lineno - method.lineno + 1)
PY
git add src/harness/ralph.py tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py tests/integration/test_ralph_controller.py
git commit -m "refactor: flatten Ralph outer loop"
```

### Task 7: Extract Delivery open/resume planning

**Files:**
- Modify: `src/harness/delivery_controller.py:881-1235`
- Test: `tests/unit/test_delivery_controller.py`
- Test: `tests/unit/test_cli_harness_resume.py`

**Interfaces:**
- Consumes: `RunIntent`, current `StateStore`, environment/source roots, and persisted phase state.
- Produces: `DeliveryRunContext`, `DeliveryResumePlan`, `_resolve_run_context(...)`, and `_plan_delivery_resume(...)` for Tasks 8-9.

- [x] **Step 1: Add failing context and resume-plan tests**

```python
def test_plan_delivery_resume_returns_exact_persisted_phase(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    store = StateStore(tmp_path / "state", "001")
    store.initialize(
        "run-1",
        "semi",
        enabled_phases=["implementation", "visual", "review", "finalization"],
    )
    store.transition("running")
    store.transition("verified", updates={"last_completed_phase": "implementation"})
    store.transition("reviewing")

    plan = controller._plan_delivery_resume(
        RunIntent(spec_id="001", resume=True),
        store,
        store.read(),
    )

    assert plan.resume is True
    assert plan.phase == "review"
    assert plan.status == "reviewing"


def test_resolve_run_context_uses_explicit_orchestration_root(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    controller._orchestration_root = tmp_path
    context = controller._resolve_run_context(RunIntent(spec_id="001"))
    assert context.workspace_root == str(tmp_path)
    assert context.spec_search_root == tmp_path
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  -k 'plan_delivery_resume or resolve_run_context' -x
```

Expected: FAIL because the typed context/plan seams do not exist.

- [x] **Step 3: Add immutable Delivery context and resume types**

Add module-level dataclasses with explicit fields:

```python
@dataclass(frozen=True)
class DeliveryRunContext:
    spec_search_root: Path
    workspace_root: str
    source_root: str
    source_id: str
    workspace_git_role: str
    source_git_role: str
    implementation_target: str | None
    declared_targets: tuple[str, ...]
    target_task_ids: tuple[str, ...]
    spec_dir: Path | None
    spec_file: Path | None
    tasks_file: Path | None


@dataclass(frozen=True)
class DeliveryResumePlan:
    resume: bool
    phase: str
    status: str
    pending_effects_only: bool
    resume_verified_publication: bool
```

Add:

```python
def _resolve_run_context(self, intent: RunIntent) -> DeliveryRunContext:
    """Resolve immutable workspace/source/spec context for one run."""

def _plan_delivery_resume(
    self,
    intent: RunIntent,
    state_store: StateStore,
    existing: dict[str, Any],
) -> DeliveryResumePlan:
    """Validate persisted phase state and select the exact resume point."""
```

Move only current environment/root resolution, target/task derivation, resume
classification, downstream-candidate-change handling, and phase transition
planning. Preserve existing migration and error payloads. `_run_delivery`
continues acquiring/releasing the state lock in its outer `try/finally`.

- [x] **Step 4: Run Delivery resume/state verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_state_machine.py \
  tests/unit/test_state_store_logic.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/delivery_controller.py tests/unit/test_delivery_controller.py tests/unit/test_cli_harness_resume.py
git commit -m "refactor: extract Delivery resume planning"
```

### Task 8: Extract bounded review re-entry

**Files:**
- Modify: `src/harness/delivery_controller.py:1235-1690`
- Test: `tests/unit/test_delivery_controller_review_reentry.py`
- Test: `tests/integration/test_controlled_review_reentry.py`

**Interfaces:**
- Consumes: `DeliveryRunContext`, `DeliveryResumePlan`, persisted `pending_review_reentry`, and existing review helpers.
- Produces: `ReviewReentryOutcome` and `_process_review_reentry(...)` for Task 9.

- [x] **Step 1: Add failing review-reentry boundary tests**

```python
def test_process_review_reentry_completes_effects_without_ralph_dispatch(
    tmp_path: Path,
) -> None:
    controller = DeliveryController(
        provider=MagicMock(),
        gitops=MagicMock(),
        config=_config(tmp_path),
        base_dir=str(tmp_path),
    )
    state_store = StateStore(tmp_path / "state", "001")
    state_store.initialize("run-1", "semi")
    pending_reentry = {
        "phase1_verified": True,
        "artifact_paths": [],
        "task_ids": ["T-001"],
    }
    controller._complete_verified_review_reentry = MagicMock(return_value=True)
    ralph = MagicMock(spec=RalphController)

    outcome = controller._process_review_reentry(
        state_store=state_store,
        pending_reentry=pending_reentry,
        effects_only=True,
        ralph=ralph,
        spec_dir=None,
    )

    assert outcome.pending_reentry is None
    assert outcome.blocked_result is None
    ralph.run_loop.assert_not_called()
```

Add tests for invalid payload, bounded repair dispatch, and side-effects-pending
block. Assert exact existing reasons: `invalid_pending_review_reentry` and
`review_side_effects_pending`.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller_review_reentry.py \
  -k 'process_review_reentry' -x
```

Expected: FAIL because `ReviewReentryOutcome` and the method do not exist.

- [x] **Step 3: Extract review re-entry orchestration**

Add:

```python
@dataclass(frozen=True)
class ReviewReentryOutcome:
    pending_reentry: dict[str, object] | None
    initial_artifacts: tuple[Path, ...]
    implementation: ImplementationResult | None = None
    blocked_result: DeliveryResult | None = None
```

Add `_process_review_reentry(...) -> ReviewReentryOutcome` and move current
payload validation, effects-only completion, exact artifact ordering, repair
prompt setup, phase-1 verification marking, and side-effect completion behind
the method. Preserve current retry ceilings and do not create a second repair
loop.

- [x] **Step 4: Run review re-entry verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_review_loop.py \
  tests/integration/test_controlled_review_reentry.py -x
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/harness/delivery_controller.py tests/unit/test_delivery_controller_review_reentry.py tests/integration/test_controlled_review_reentry.py
git commit -m "refactor: extract bounded review reentry"
```

### Task 9: Extract verified publication dispatch and flatten Delivery control

**Files:**
- Modify: `src/harness/delivery_controller.py:1180-1908`
- Modify: `src/harness/ralph.py:6630-6875`
- Test: `tests/unit/test_delivery_controller.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/integration/test_polyrepo_delivery_convergence.py`

**Interfaces:**
- Consumes: Tasks 7-8 context/plan/outcome types, existing `resume_verified_publication`, and `_finalize_delivery`.
- Produces: `_dispatch_verified_publication(...)`, `_run_delivery_phases(...)`, and a dispatcher-only `_run_delivery`.

- [x] **Step 1: Add failing publication-dispatch tests**

```python
def test_dispatch_verified_publication_resumes_only_checkpointed_effects(
    tmp_path: Path,
) -> None:
    controller = _make_controller(tmp_path)
    state_store = StateStore(tmp_path / "state", "001")
    state_store.initialize("run-1", "semi")
    ralph = MagicMock(spec=RalphController)
    recovered = ImplementationResult(
        "verified", "verified", 1, 0, None, 0, VerifyResult(passed=True)
    )
    ralph.resume_verified_publication.return_value = recovered

    result = controller._dispatch_verified_publication(
        state_store=state_store,
        ralph=ralph,
        resume=True,
    )

    assert result is recovered
    ralph.resume_verified_publication.assert_called_once_with()
    ralph.run_loop.assert_not_called()
```

Add a no-checkpoint case returning `None` and retain existing tests for invalid
worktree/commit/evidence/branch publication checkpoints.

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  -k 'dispatch_verified_publication' -x
```

Expected: FAIL because the explicit dispatch method does not exist.

- [x] **Step 3: Extract publication dispatch and phase composition**

Add:

```python
def _dispatch_verified_publication(
    self,
    *,
    state_store: StateStore,
    ralph: RalphController,
    resume: bool,
) -> ImplementationResult | None:
    """Resume a proven publication checkpoint without implementation dispatch."""
```

Keep `RalphController.resume_verified_publication` and its validation logic
unchanged except for signature tightening required by earlier typed outcomes.

Add `_run_delivery_phases(...) -> DeliveryResult` to compose implementation,
visual, review, and finalization using Tasks 7-8. Rewrite `_run_delivery` so it
only:

1. constructs `StateStore` and acquires the lock;
2. resolves context and migration;
3. returns an existing terminal result when applicable;
4. obtains the resume plan;
5. calls `_run_delivery_phases`;
6. translates `DeliveryConfigurationError` at the existing phase boundary;
7. releases the lock in `finally`.

Keep `_finalize_delivery` as the only converged terminal writer.

- [x] **Step 4: Run full focused Delivery/Ralph verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_delivery_finalization.py \
  tests/unit/test_harness_recovery.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py \
  tests/integration/test_ralph_controller.py -x
```

Expected: PASS.

- [x] **Step 5: Check both orchestration sizes and commit**

Run:

```bash
.venv/bin/python - <<'PY'
import ast
from pathlib import Path
checks = [
    ("src/harness/ralph.py", "RalphController", "_run_loop_inner", 220),
    ("src/harness/delivery_controller.py", "DeliveryController", "_run_delivery", 220),
]
for path, class_name, method_name, maximum in checks:
    tree = ast.parse(Path(path).read_text())
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    lines = method.end_lineno - method.lineno + 1
    assert lines <= maximum, (path, method_name, lines)
    print(path, method_name, lines)
PY
git add src/harness/delivery_controller.py src/harness/ralph.py \
  tests/unit/test_delivery_controller.py tests/unit/test_ralph_outer.py \
  tests/integration/test_polyrepo_delivery_convergence.py
git commit -m "refactor: flatten single Delivery controller"
```

### Task 10: Update S4 evidence and run repository verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/simplification-control.md`
- Modify: `docs/superpowers/plans/2026-09-23-ralph-durable-step-decomposition.md`
- Create: the single receipt path printed by `scripts/merge_verification.py run`
- Test: focused Delivery/Ralph partitions and repository merge-verification.

**Interfaces:**
- Consumes: completed Tasks 1-9 and the fixed S4 design.
- Produces: current architecture guidance, completed S4 work queue, and repository-bound verification evidence.

- [x] **Step 1: Update current architecture documentation**

Document the final control flow without claiming a new framework:

```text
DeliveryController
  open/resume run
  dispatch persisted phase
  process review re-entry/publication
  finalize once

RalphController
  recover pending slice
  prepare iteration
  dispatch controlled slice
  checkpoint progress
  verify candidate
```

In `docs/simplification-control.md`, record focused counts and leave S4 `ACTIVE`
until the repository gate passes. Do not edit historical findings or receipts.

- [x] **Step 2: Run static contract checks**

Run:

```bash
git diff --check
.venv/bin/python -m compileall -q src
! rg -n 'delivery_slice_operation_v2|pending_review_reentry_v2|verified_publish_checkpoint_v2' src
! rg -n 'WorkflowEngine|PhaseRegistry|GenericStep' src/harness/delivery_controller.py src/harness/ralph.py
```

Expected: every command exits zero.

- [x] **Step 3: Run focused verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_controller.py \
  tests/unit/test_delivery_controller_review_reentry.py \
  tests/unit/test_ralph_inner.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_run_skill_checkpoint_recovery.py \
  tests/unit/test_harness_recovery.py \
  tests/unit/test_delivery_finalization.py \
  tests/unit/test_verification_evidence.py \
  tests/unit/test_runnability_evidence.py \
  tests/integration/test_controlled_review_reentry.py \
  tests/integration/test_polyrepo_delivery_convergence.py \
  tests/integration/test_ralph_controller.py
```

Expected: PASS.

- [x] **Step 4: Commit the completed decomposition**

```bash
git add AGENTS.md README.md docs/simplification-control.md \
  docs/superpowers/plans/2026-09-23-ralph-durable-step-decomposition.md
git commit -m "docs: document durable Delivery step decomposition"
```

- [ ] **Step 5: Run the repository gate**

Use the committed design as the approved base and preserve the gate-reported
receipt path for the evidence commit:

```bash
.venv/bin/python scripts/merge_verification.py plan --base 7af823a9
set -o pipefail
gate_log=$(mktemp)
.venv/bin/python scripts/merge_verification.py run --base 7af823a9 | tee "$gate_log"
receipt_path=$(sed -n 's/^receipt: //p' "$gate_log")
test -n "$receipt_path"
printf '%s\n' "$receipt_path" > "$(git rev-parse --git-dir)/last-s4-receipt"
```

Expected: zero failures. Record tested commit, tree, passed/deselected counts,
elapsed time, and receipt path in `docs/simplification-control.md`. Mark S4
`DONE` only after this gate is green; set S5 as the sole `ACTIVE` milestone.

- [ ] **Step 6: Commit verification evidence**

```bash
receipt_path=$(cat "$(git rev-parse --git-dir)/last-s4-receipt")
test -f "$receipt_path"
git add docs/simplification-control.md \
  docs/superpowers/plans/2026-09-23-ralph-durable-step-decomposition.md
git add -f "$receipt_path"
git commit -m "docs: record durable Delivery decomposition verification"
```
