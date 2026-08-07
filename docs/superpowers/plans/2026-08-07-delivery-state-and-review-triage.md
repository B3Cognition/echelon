# Delivery State And Review Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the polyrepo delivery fix by giving every delivery phase an unambiguous result and durable restart state, separating convergence from landing, and safely publishing Claude-generated review tasks through validated staging.

**Architecture:** Phase controllers return phase-specific results and never declare overall convergence; `StrategyCoordinator` owns the immutable phase plan, durable checkpoints, finalization, and `DeliveryResult`. Review triage is a Claude-only execution profile: the controller supplies already-fetched comments and explicit read-only agents, Claude writes only to a build-scoped staging attempt, and a host-side publisher validates and journals canonical publication.

**Tech Stack:** Python 3.11+, dataclasses and `Literal`, pathlib, atomic JSON/file writes, Claude Code CLI, pytest, unittest.mock, existing Echelon state/GitOps/spec-frontmatter helpers.

## Global Constraints

- Preserve the three-root contract already implemented: orchestration workspace owns canonical specs; target harness root owns build/review state; the target worktree and target GitOps own implementation/Git operations.
- `converged` is terminal overall delivery state. Phase controllers must never return it, and no `converged -> blocked` transition may exist.
- Persist `enabled_phases` once per new delivery; continuation must not recalculate it from changed ambient configuration.
- Treat ordinary implementation, visual, review, Git, provider, and finalization failures as recoverable `blocked` outcomes with an exact `blocked_phase`. Reserve `failed` for invariant or persisted-state corruption.
- A Phase 2 source fix or Phase 3 queued fix must re-enter Phase 1 and obtain fresh verification.
- Single-target finalization writes verified provenance and `ready_to_land` before delivery convergence. Multi-target workers never mutate canonical lifecycle state.
- Auto-land is post-convergence. A landing failure leaves delivery `converged` and lifecycle `ready_to_land` and is reported independently.
- `review_triage_v1` is supported only by Claude. Every other backend fails closed before subprocess launch; never fall back to an unscoped run.
- Review triage has no Bash, network, MCP, background-agent, or permission-bypass capability.
- The provider has no canonical write permission. Invalid or partial staged output must not change canonical `tasks.md` or `review-fix-*.md`.
- Do not mutate or land the external dirty Prosaic checkout. Live validation remains read-only.
- Add no dependencies. Use test-driven development and one focused commit per task.

## File And Interface Map

- `src/harness/delivery_results.py`: phase-specific and delivery/run outcome dataclasses; the sole status vocabulary definition.
- `src/harness/state.py`: delivery state schema v2, transition graph, atomic transition-with-fields, and legacy migration.
- `src/harness/coordinator.py`: persisted phase plan, phase routing/re-entry, finalization, and construction of `DeliveryResult`.
- `src/harness/skills/run_skill.py`: `DeliveryRunOutcome` return and independent post-convergence `LandingOutcome`.
- `src/harness/review_artifacts.py`: canonical review lock, allocation, staged-manifest validation, publication journal, and crash recovery.
- `src/harness/review_loop.py`: normalized comment prompt, Claude profile metadata, staging session integration, and `ReviewResult`.
- `src/harness/ai_cli_backends/claude.py`: exact Claude CLI compilation for `review_triage_v1`.
- `src/harness/llm_provider.py`: fail-closed execution-profile dispatch.
- `extension/commands/echelon.review.md`: consume supplied comments and allocated staging contract; never fetch or write canonical paths directly.

---

### Task 1: Separate Phase Results From Delivery Results

**Files:**

- Create: `src/harness/delivery_results.py`
- Delete after migration: `src/harness/loop_result.py`
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/visual_ralph.py`
- Modify: `src/harness/review_loop.py`
- Modify: `src/harness/coordinator.py`
- Modify: `src/harness/merge.py`
- Modify: `src/harness/harness_run_history.py`
- Modify: `tests/unit/test_loop_result.py` (rename to `tests/unit/test_delivery_results.py`)
- Modify: `tests/unit/test_ralph_outer.py`
- Modify: `tests/unit/test_visual_ralph.py`
- Modify: `tests/unit/test_review_loop.py`
- Modify: `tests/unit/test_coordinator.py`
- Modify: `tests/unit/test_coordinator_review_reentry.py`
- Modify: `tests/unit/test_merge.py`
- Modify: `tests/unit/test_harness_run_history.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_stack_context_prompt.py`
- Modify: `tests/e2e/test_constitution_blocking.py`
- Modify: `tests/e2e/test_multi_strategy.py`
- Modify: `tests/e2e/test_ralph_budget.py`
- Modify: `tests/e2e/test_ralph_convergence.py`
- Modify: `tests/e2e/test_ralph_escalation.py`
- Modify: `tests/e2e/test_ralph_resume.py`

**Interfaces:**

- Produces: `ImplementationResult`, `VisualResult`, `ReviewResult`, `DeliveryResult`, `LandingOutcome`, and `DeliveryRunOutcome` from `harness.delivery_results`.
- `RalphController.run_loop() -> ImplementationResult`.
- `VisualRalphController.run_loop() -> VisualResult`.
- `ReviewLoopController.run_loop() -> ReviewResult`.
- `StrategyCoordinator.start() -> list[DeliveryResult]`.

- [ ] **Step 1: Write failing result-contract tests**

Replace the old `LoopResult` tests with exact status validation and serialization tests:

```python
def test_phase_and_delivery_statuses_do_not_overlap() -> None:
    assert "converged" not in IMPLEMENTATION_STATUSES
    assert "converged" not in VISUAL_STATUSES
    assert "converged" not in REVIEW_STATUSES
    assert DELIVERY_STATUSES == {
        "converged", "blocked", "interrupted", "failed", "cancelled"
    }


def test_delivery_result_serializes_common_evidence() -> None:
    result = DeliveryResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=2,
        inner_iterations=3,
        pr_url="https://github.com/acme/api/pull/7",
        tokens_used=40,
        final_verify=None,
        branch="delivery/042",
    )
    assert result.to_dict()["status"] == "converged"
    assert result.to_dict()["branch"] == "delivery/042"
```

Add controller assertions that Phase 1 returns `verified`, visual success returns `passed`, merged review returns `completed`, and queued review returns `review_fix_queued`. Run:

```bash
pytest -q tests/unit/test_delivery_results.py tests/unit/test_ralph_outer.py -k 'verified or result'
pytest -q tests/unit/test_visual_ralph.py tests/unit/test_review_loop.py -k 'passed or completed or queued'
```

Expected: collection/import failures because the new result module and statuses do not exist.

- [ ] **Step 2: Add the result dataclasses**

Rename the test file with `git mv tests/unit/test_loop_result.py tests/unit/test_delivery_results.py`, then create frozen dataclasses with a shared private validator but separate public types:

```python
IMPLEMENTATION_STATUSES = {"verified", "blocked", "interrupted", "failed", "cancelled"}
VISUAL_STATUSES = {"passed", "fix_applied", "blocked"}
REVIEW_STATUSES = {"completed", "review_fix_queued", "blocked"}
DELIVERY_STATUSES = {"converged", "blocked", "interrupted", "failed", "cancelled"}
LANDING_STATUSES = {"not_requested", "landed", "blocked", "skipped"}

@dataclass(frozen=True)
class ImplementationResult:
    status: str
    termination_reason: str
    outer_iterations: int
    inner_iterations: int
    pr_url: str | None
    tokens_used: int
    final_verify: VerifyResult | None
    branch: str | None = None

@dataclass(frozen=True)
class VisualResult:
    status: str
    termination_reason: str
    iterations: int
    tokens_used: int
    final_verify: VerifyResult | None

@dataclass(frozen=True)
class ReviewResult:
    status: str
    termination_reason: str
    iterations: int
    pr_url: str
    tokens_used: int

@dataclass(frozen=True)
class DeliveryResult:
    status: str
    termination_reason: str
    outer_iterations: int
    inner_iterations: int
    pr_url: str | None
    tokens_used: int
    final_verify: VerifyResult | None
    branch: str | None = None

@dataclass(frozen=True)
class LandingOutcome:
    status: str
    reason: str = ""

@dataclass(frozen=True)
class DeliveryRunOutcome:
    results: tuple[DeliveryResult, ...]
    landing: LandingOutcome
```

Each `__post_init__` rejects unknown statuses and negative counters. Keep the existing `VerifyResult` dictionary representation in `DeliveryResult.to_dict()`.

- [ ] **Step 3: Migrate controllers and consumers minimally**

Change Ralph's successful `_finalize()` calls from `converged` to `verified`, remove both calls to `_mark_spec_ready_to_land()`, and make `_finalize()` update progress/evidence fields without transitioning delivery status. Change visual success/failure to `passed`/`blocked`; after one visual feedback edit return `fix_applied` immediately instead of accepting later visual evidence without Phase 1. Change review merge success/failure to `completed`/`blocked` and exhaustion/provider errors to `blocked`.

In the coordinator, convert phase results to one `DeliveryResult`; do not persist the new intermediate states yet (Task 2 owns that). Migrate history and merge type annotations to `DeliveryResult`, remove every import of `harness.loop_result`, then delete that module.

- [ ] **Step 4: Run focused and affected tests**

```bash
pytest -q tests/unit/test_delivery_results.py tests/unit/test_ralph_outer.py tests/unit/test_visual_ralph.py tests/unit/test_review_loop.py
pytest -q tests/unit/test_coordinator.py tests/unit/test_coordinator_review_reentry.py tests/unit/test_merge.py tests/unit/test_harness_run_history.py tests/unit/test_run_skill.py tests/unit/test_stack_context_prompt.py
pytest -q tests/e2e/test_constitution_blocking.py tests/e2e/test_multi_strategy.py tests/e2e/test_ralph_budget.py tests/e2e/test_ralph_convergence.py tests/e2e/test_ralph_escalation.py tests/e2e/test_ralph_resume.py
rg -n 'harness\.loop_result|\bLoopResult\b' src tests -g '*.py'
```

Expected: both pytest commands pass and `rg` returns no matches.

- [ ] **Step 5: Commit**

```bash
git rm src/harness/loop_result.py
git add src/harness/delivery_results.py src/harness/ralph.py src/harness/visual_ralph.py src/harness/review_loop.py src/harness/coordinator.py src/harness/merge.py src/harness/harness_run_history.py tests/unit/test_delivery_results.py tests/unit/test_ralph_outer.py tests/unit/test_visual_ralph.py tests/unit/test_review_loop.py tests/unit/test_coordinator.py tests/unit/test_coordinator_review_reentry.py tests/unit/test_merge.py tests/unit/test_harness_run_history.py tests/unit/test_run_skill.py tests/unit/test_stack_context_prompt.py tests/e2e/test_constitution_blocking.py tests/e2e/test_multi_strategy.py tests/e2e/test_ralph_budget.py tests/e2e/test_ralph_convergence.py tests/e2e/test_ralph_escalation.py tests/e2e/test_ralph_resume.py
git commit -m "refactor: separate delivery phase result contracts"
```

---

### Task 2: Add State Schema V2 And Deterministic Continuation

**Files:**

- Modify: `src/harness/state.py`
- Modify: `src/harness/coordinator.py`
- Modify: `tests/unit/test_state_machine.py`
- Modify: `tests/unit/test_state_store_logic.py`
- Modify: `tests/integration/test_state_store_atomicity.py`
- Modify: `tests/integration/test_state_store_lockfile.py`
- Modify: `tests/unit/test_coordinator.py`

**Interfaces:**

- Consumes: phase result types from Task 1.
- Produces: `DELIVERY_STATE_VERSION = 2`, `StateStore.transition(new_status, *, updates=None)`, and coordinator helpers `_enabled_phases()`, `_migrate_delivery_state()`, `_resume_phase()`.
- Produces: shared `harness.state.is_process_alive(pid: int) -> bool` for state and review locks.

- [ ] **Step 1: Write failing transition and migration tests**

Add the exact transition matrix, including the terminal convergence assertion:

```python
@pytest.mark.parametrize("path", [
    ["running", "verified", "finalizing", "converged"],
    ["running", "verified", "validating", "finalizing", "converged"],
    ["running", "verified", "reviewing", "finalizing", "converged"],
    ["running", "verified", "validating", "reviewing", "finalizing", "converged"],
])
def test_delivery_state_paths(tmp_path: Path, path: list[str]) -> None:
    store = StateStore(tmp_path, "042", "default")
    store.initialize("run-1", "semi")
    for status in path:
        store.transition(status)
    assert store.read()["status"] == "converged"


def test_converged_cannot_reopen(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "042", "default")
    store.initialize("run-1", "semi")
    for status in ("running", "verified", "finalizing", "converged"):
        store.transition(status)
    with pytest.raises(InvalidTransitionError):
        store.transition("blocked")
```

Add tests proving `transition("blocked", updates={"blocked_phase": "review"})` writes both fields atomically, a legacy block without phase migrates to implementation, legacy convergence remains terminal, and changing config after initialization does not change `enabled_phases`.

Run:

```bash
pytest -q tests/unit/test_state_machine.py tests/unit/test_state_store_logic.py -k 'delivery_state or migrate or enabled_phases or atomic_transition'
```

Expected: failures for missing statuses, schema fields, and transition updates.

- [ ] **Step 2: Implement schema v2 and atomic checkpoint writes**

Set the complete transition map:

```python
VALID_TRANSITIONS = {
    "initialized": {"running"},
    "running": {"verified", "blocked", "interrupted", "failed", "cancelled_by_coordinator"},
    "verified": {"validating", "reviewing", "finalizing", "blocked"},
    "validating": {"running", "reviewing", "finalizing", "blocked", "interrupted", "failed", "cancelled_by_coordinator"},
    "reviewing": {"running", "finalizing", "blocked", "interrupted", "failed", "cancelled_by_coordinator"},
    "finalizing": {"converged", "blocked"},
    "blocked": {"running", "validating", "reviewing", "finalizing"},
    "interrupted": {"running", "validating", "reviewing", "finalizing"},
    "converged": {}, "failed": {}, "cancelled_by_coordinator": {},
}
```

Add initialization fields `delivery_state_version`, `enabled_phases`, `last_completed_phase`, `blocked_phase`, `interrupted_phase`, and `verified_commit`. Extend `transition()` to merge `updates` before one `write()` call. Validate that `blocked_phase` and `interrupted_phase` are one of `implementation`, `visual`, `review`, `finalization` when their status requires it. When leaving `blocked` or `interrupted`, require the destination to equal `{implementation: running, visual: validating, review: reviewing, finalization: finalizing}[recorded_phase]`. Promote process liveness to `harness.state.is_process_alive(pid: int) -> bool` and make the existing StateStore lock handling use that helper; Task 4 consumes the same function.

- [ ] **Step 3: Persist the immutable phase plan and legacy migration**

At new-run initialization compute:

```python
phases = ["implementation"]
if config.visual_tests.enabled and llm_provider is None:
    phases.append("visual")
if config.review_loop.enabled and config.pr_host != "none":
    phases.append("review")
phases.append("finalization")
```

For an existing nonterminal v1 state, persist this snapshot once; map unqualified `blocked` and `interrupted` to implementation. Never migrate or reopen `converged`, `failed`, or `cancelled_by_coordinator`. Make resume routing read the persisted list rather than current configuration.

- [ ] **Step 4: Verify and commit**

```bash
pytest -q tests/unit/test_state_machine.py tests/unit/test_state_store_logic.py tests/integration/test_state_store_atomicity.py tests/integration/test_state_store_lockfile.py tests/unit/test_coordinator.py -k 'state or phase or resume or migrate or process_alive'
git add src/harness/state.py src/harness/coordinator.py tests/unit/test_state_machine.py tests/unit/test_state_store_logic.py tests/integration/test_state_store_atomicity.py tests/integration/test_state_store_lockfile.py tests/unit/test_coordinator.py
git commit -m "feat: persist delivery phase checkpoints"
```

---

### Task 3: Implement Phase Routing, Finalization, And Landing Outcomes

**Files:**

- Modify: `src/harness/coordinator.py`
- Modify: `src/harness/skills/run_skill.py`
- Modify: `src/harness/harness_run_history.py`
- Modify: `src/harness/run_history.py`
- Modify: `tests/unit/test_coordinator.py`
- Modify: `tests/unit/test_coordinator_review_reentry.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_harness_run_history.py`
- Modify: `tests/unit/test_run_history.py`

**Interfaces:**

- Consumes: result contracts and state schema from Tasks 1–2.
- Produces: coordinator `_run_enabled_phases()`, `_persist_phase_block()`, `_finalize_delivery()`, `_worktree_head()`, and `run_skill.run(...) -> DeliveryRunOutcome`.

- [ ] **Step 1: Write failing coordinator path and restart tests**

Cover all four phase plans and exact re-entry rules. Representative assertions:

```python
checkpoint_names = [call.args[0] for call in transition_mock.call_args_list]
assert checkpoint_names == ["running", "verified", "validating", "reviewing", "finalizing", "converged"]

visual.run_loop.return_value = VisualResult("fix_applied", "visual_fix_applied", 1, 10, None)
assert coordinator.start(intent)[0].status == "blocked" or ralph.run_loop.call_count == 2
assert statuses(store)[-3:] == ["validating", "running", "verified"]

review.run_loop.return_value = ReviewResult("review_fix_queued", "review_fix_queued", 1, pr_url, 10)
assert ralph.run_loop.call_count == 2
```

Add continuation fixtures for `verified`, `validating`, `reviewing`, `finalizing`, and each `blocked_phase`. Assert missing/mismatched recorded worktree or commit blocks the same phase and never silently starts Phase 1. Assert enabled review without a PR URL blocks review with `missing_pr_url`.

- [ ] **Step 2: Refactor coordinator into explicit phase helpers**

Replace the nested result-overwriting flow with a loop over persisted phases. Required decisions:

```python
if implementation.status == "verified": checkpoint("verified", last_completed_phase="implementation")
if visual.status == "fix_applied": checkpoint("running"); continue_from("implementation")
if visual.status == "passed": checkpoint(next_state, last_completed_phase="visual")
if review.status == "review_fix_queued": checkpoint("running"); continue_from("implementation")
if review.status == "completed": checkpoint("finalizing", last_completed_phase="review")
```

Map every recoverable phase failure through `_persist_phase_block(phase, reason)`. Preserve PR URL, verified commit, metrics, and registered worktree in every checkpoint. A `reviewing` resume reuses stored PR/seen IDs; a `validating` resume discards container runtime and restarts its first visual check.

- [ ] **Step 3: Move lifecycle ownership to finalization**

Delete Ralph's `_mark_spec_ready_to_land()`. In `_finalize_delivery()`:

```python
store.transition("finalizing", updates={"blocked_phase": None})
if len(declared_targets) == 1:
    recorded_worktree_commit = _worktree_head(Path(worktree_path))
    report = latest_fulfillment_report(spec_dir)
    metadata = read_fulfillment_metadata(report) if report is not None else {}
    verified_commit = str(metadata.get("verified_commit") or "")
    if not verified_commit or verified_commit != recorded_worktree_commit:
        return block_finalization("verified_provenance_mismatch")
    store.transition("finalizing", updates={"verified_commit": verified_commit})
    write_status(spec_dir, "ready_to_land")
    append_implementation_run(
        spec_dir,
        run_id=str(store.read()["run_id"]),
        spec_status="ready_to_land",
        verification_result="PASS",
    )
    write_artifact_index(spec_dir)
store.transition("converged", updates={"termination_reason": "converged"})
```

Implement `_worktree_head()` with `git -C <registered-worktree> rev-parse HEAD`; never run it from the harness root. Make each write idempotent: accept matching existing provenance/status, block finalization on conflicting commit/status, and retry only missing matching writes after a crash. Update `append_implementation_run()` to replace an existing Phase B row with the same `run_id` rather than append a duplicate. For multiple targets, write target-local convergence only and leave canonical lifecycle untouched.

- [ ] **Step 4: Return landing independently from delivery**

Make `run()` return `DeliveryRunOutcome`. Initialize `LandingOutcome("not_requested")`; use `skipped` for multi-target, `landed` for `land() is True`, and `blocked` for `False` or an exception. Do not change a `DeliveryResult(converged)` when landing blocks. Update the delivery summary to print separate `delivery` and `landing` fields and the next step `echelon delivery land <spec-id>` for blocked landing.

- [ ] **Step 5: Verify and commit**

```bash
pytest -q tests/unit/test_coordinator.py tests/unit/test_coordinator_review_reentry.py -k 'phase or resume or finaliz or missing_pr'
pytest -q tests/unit/test_run_skill.py tests/unit/test_harness_run_history.py tests/unit/test_run_history.py -k 'landing or converged or lifecycle or idempotent'
git add src/harness/coordinator.py src/harness/skills/run_skill.py src/harness/harness_run_history.py src/harness/run_history.py tests/unit/test_coordinator.py tests/unit/test_coordinator_review_reentry.py tests/unit/test_run_skill.py tests/unit/test_harness_run_history.py tests/unit/test_run_history.py
git commit -m "feat: coordinate delivery through final convergence"
```

---

### Task 4: Build Transactional Review Artifact Publication

**Files:**

- Create: `src/harness/review_artifacts.py`
- Create: `tests/unit/test_review_artifacts.py`

**Interfaces:**

- Produces: `ReviewArtifactPublisher`, `ReviewAllocation`, `PublishedReviewBatch`, and `ReviewArtifactError`.
- `ReviewArtifactPublisher` is a context manager holding `<spec-dir>/.echelon-review.lock` from allocation through validation/publication.
- `allocate(comment_ids: Sequence[str]) -> ReviewAllocation`.
- `accept_manifest(status_file: Path) -> PublishedReviewBatch`.
- `recover_publication(seen_ids: AbstractSet[str]) -> PublishedReviewBatch | None`.
- `mark_consumed(attempt_id: str) -> None`.

Use these exact immutable records:

```python
@dataclass(frozen=True)
class ReviewAllocation:
    attempt_id: str
    comment_ids: tuple[str, ...]
    attempt_dir: Path
    artifact_names: tuple[str, ...]
    task_ids: tuple[str, ...]
    status_file: Path
    journal_file: Path

@dataclass(frozen=True)
class PublishedReviewBatch:
    attempt_id: str
    status: Literal["no_blocking_comments", "review_fix_queued"]
    artifact_paths: tuple[Path, ...]
    task_ids: tuple[str, ...]
    comment_ids: tuple[str, ...]
```

- [ ] **Step 1: Write failing allocation and validation tests**

Create tests for numeric max allocation (not file count), three canonical task IDs per possible group, zero-group output, malformed/escaping paths, duplicate IDs, missing staged files, and lock contention/stale PID behavior. Example:

```python
with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
    allocation = publisher.allocate(comment_ids=("c1", "c2"))
assert allocation.artifact_names == ("review-fix-8.md", "review-fix-9.md")
assert allocation.task_ids == ("T-41", "T-42", "T-43", "T-44", "T-45", "T-46")
assert allocation.attempt_dir.parent == state_dir / "review-staging"
```

Run `pytest -q tests/unit/test_review_artifacts.py`; expect import failure.

- [ ] **Step 2: Implement lock and fresh allocation**

Use an exclusive lock file containing `pid`, `created_at`, and strategy. Reuse `harness.state.is_process_alive()` rather than copying platform logic. Ignore nonmatching filenames; choose `max(review suffix)+1` and `max(canonical T number)+1`. Create the attempt with `tempfile.mkdtemp(prefix=f"{strategy}-", dir=staging_root)` and return only exact candidate paths. Remove the prior status file before provider launch, but never discard an incomplete publication journal; recover it first.

- [ ] **Step 3: Implement manifest validation**

Parse the approved schema from the design. Resolve every reported path against the attempt directory and reject absolute paths, `..`, symlinks, directories, unknown files, non-contiguous allocated prefixes, non-unique IDs, or task rows not in one-to-one correspondence with manifest entries. `no_blocking_comments` requires an empty attempt. A queued group requires exactly three task entries per artifact.

- [ ] **Step 4: Implement journaled publication and recovery**

Before canonical writes, atomically create `<state-dir>/<strategy>-review-publication.json` with pre-state and staged SHA-256 digests plus `published_artifacts`, `tasks_published`, and `complete`. Publish each canonical artifact with a temp file in `spec_dir` plus `os.replace`; then atomically replace `tasks.md` with the captured bytes plus the validated append payload. Fsync file and parent directory at each atomic boundary.

Recovery accepts an existing canonical file only when its digest matches the journal, completes remaining writes exactly once, and blocks on any conflict. Mark `complete` only after post-publication digest/task validation. The journal includes the source comment IDs. If a complete journal's IDs are already in `seen_ids`, mark it consumed without returning the batch; otherwise return the completed batch so review side effects can finish. `mark_consumed()` atomically records consumption, after which the next allocation may rotate the old journal. Never delete or overwrite a conflicting canonical path.

- [ ] **Step 5: Verify crash points and commit**

```bash
pytest -q tests/unit/test_review_artifacts.py
git add src/harness/review_artifacts.py tests/unit/test_review_artifacts.py
git commit -m "feat: publish review tasks transactionally"
```

Expected: tests stop after every journal/artifact/tasks write boundary and prove recovery neither duplicates task rows nor overwrites conflicts.

---

### Task 5: Add The Claude-Only Review Triage Profile

**Files:**

- Modify: `src/harness/llm_provider.py`
- Modify: `src/harness/ai_cli_backends/claude.py`
- Modify: `tests/unit/test_ai_cli_backend.py`
- Modify: `tests/unit/test_llm_provider.py`

**Interfaces:**

- Consumes request metadata `execution_profile="review_triage_v1"` and nested `prompt_metadata` containing read roots, exact write paths, and `review_agents`.
- Produces fail-closed `CliRunResult(exit_code=125, metadata={"unsupported_execution_profile": "review_triage_v1"})` for every non-Claude backend.

- [ ] **Step 1: Write failing provider-dispatch tests**

Parameterize `codex`, `copilot`, `opencode`, `openai-compatible`, and plain backends. Assert the backend mock is never called and stderr is:

```text
execution profile review_triage_v1 requires claude; configured provider is <provider>
```

Add a Claude command-capture test with two read roots, three staged write files, and three agents. Assert `--bare`, empty setting sources, strict MCP, disabled slash commands, `--tools Read,Write,Edit,Agent`, exact absolute rules, and `--agents` JSON. Assert the flattened command contains none of `Bash`, `WebFetch`, `WebSearch`, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, or background-agent flags.

- [ ] **Step 2: Implement facade rejection**

Before containment and backend invocation in both `run_prompt_result()` and `run_agent_result()`, reject a nonempty execution profile unless it is supported by the selected backend. For this change the only entry is:

```python
SUPPORTED_EXECUTION_PROFILES = {"claude": frozenset({"review_triage_v1"})}
```

Unknown profiles also fail closed with exit 125; never treat them as ordinary metadata.

- [ ] **Step 3: Compile the exact Claude profile**

Branch before `_prompt_file_scope_args()`. Validate three exact agent keys and serialize:

```python
cmd.extend([
    "--bare", "--setting-sources", "", "--strict-mcp-config",
    "--disable-slash-commands",
    "--tools", "Read,Write,Edit,Agent",
    "--allowedTools", ",".join(file_rules + agent_rules),
    "--agents", json.dumps(review_agents, sort_keys=True),
])
```

Each agent definition must contain `description`, full `prompt`, and `tools: ["Read"]`; `agent_rules` contains only the three exact `Agent(name)` entries. Do not combine this with the generic `--safe-mode` file-scope path.

- [ ] **Step 4: Verify and commit**

```bash
pytest -q tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py -k 'review_triage or execution_profile'
git add src/harness/llm_provider.py src/harness/ai_cli_backends/claude.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py
git commit -m "feat: scope Claude review triage execution"
```

---

### Task 6: Integrate Supplied Comments, Agents, And Staged Publication

**Files:**

- Modify: `src/harness/review_loop.py`
- Modify: `src/harness/coordinator.py`
- Modify: `extension/commands/echelon.review.md`
- Modify: `tests/unit/test_review_loop.py`
- Modify: `tests/unit/test_coordinator_review_reentry.py`
- Modify: `tests/unit/test_manual_command_contracts.py`

**Interfaces:**

- Consumes: `ReviewArtifactPublisher` and `review_triage_v1` from Tasks 4–5.
- Produces: `_normalized_review_input()`, `_load_review_agents(worktree)`, and `_invoke_review_skill(...) -> _ReviewSkillResult` with `tokens_used: int`, `queued: bool`, `queued_task_ids: tuple[str, ...]`, and `published_artifacts: tuple[Path, ...]`.

- [ ] **Step 1: Write failing integration-contract tests**

Capture the provider call and assert:

```python
assert request_metadata["execution_profile"] == "review_triage_v1"
assert prompt_metadata["tool_read_roots"] == [str(worktree), str(spec_dir)]
assert all(str(attempt_dir) in path for path in prompt_metadata["tool_write_paths"][:-1])
assert str(spec_dir / "tasks.md") not in prompt_metadata["tool_write_paths"]
assert set(prompt_metadata["review_agents"]) == {
    "speckit-echelon-debugger",
    "speckit-echelon-sentinel",
    "speckit-echelon-spec-guard",
}
assert '"comment_id":"c1"' in prompt.replace(" ", "")
```

Assert provider success with invalid/missing staged evidence returns blocked, does not mark comments seen, and changes no canonical file. Assert a completed journal returns the canonical `T-<n>` IDs, marks only supplied comments seen, and causes Phase 1 re-entry with only those task IDs.

- [ ] **Step 2: Supply normalized comments and explicit agents**

Serialize comment ID, reviewer, body, path, line, timestamp, and `adjacent_line_threshold` into a fenced `Harness Review Input` JSON block. Load the three scaffolded agent files from `<worktree>/.claude/agents/<name>.md`; missing or symlinked agent files block review before provider launch. Build each CLI agent definition with `tools: ["Read"]`.

- [ ] **Step 3: Replace canonical writes in the review command**

Rewrite Step 2 of `echelon.review.md` to consume only the supplied JSON and remove every `gh`, `glab`, and Bash instruction. Replace index discovery with the supplied allocation. Write proposed `review-fix-<n>.md`, `tasks-append.md`, and the manifest only to the exact staging/status paths. Emit `no_blocking_comments` for zero groups and the full `tasks` mapping for queued work.

- [ ] **Step 4: Publish before mutating review state**

Wrap provider invocation in `ReviewArtifactPublisher`. Call `recover_publication(self._seen_ids)` before starting a new attempt. Only after `accept_manifest()` returns a completed batch may the loop mark comments seen, resolve threads, request review, or return `ReviewResult(review_fix_queued)`. Persist seen IDs, perform idempotent thread/review side effects, then call `mark_consumed(batch.attempt_id)`. Before Phase 1 re-entry, atomically extend the strategy state's `target_task_ids` with the published canonical task IDs, preserving order and removing duplicates. Restrict `_build_reentry_prompt()` to the batch's published artifact paths rather than every historical review-fix file.

- [ ] **Step 5: Verify and commit**

```bash
pytest -q tests/unit/test_review_loop.py tests/unit/test_coordinator_review_reentry.py tests/unit/test_manual_command_contracts.py
rg -n 'gh api|glab api|ls .*review-fix' extension/commands/echelon.review.md
git add src/harness/review_loop.py src/harness/coordinator.py extension/commands/echelon.review.md tests/unit/test_review_loop.py tests/unit/test_coordinator_review_reentry.py tests/unit/test_manual_command_contracts.py
git commit -m "feat: stage and validate review triage outputs"
```

Expected: pytest passes and `rg` returns no matches.

---

### Task 7: Run Integrated Regression, Document, Install, And Smoke-Test

**Files:**

- Modify: `CHANGELOG.md`
- Create: `tests/integration/test_polyrepo_delivery_convergence.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_coordinator.py`
- Modify: `tests/unit/test_review_loop.py`
- Modify: `tests/unit/test_land.py`

**Interfaces:**

- Consumes every prior task; produces no new runtime interface.

- [ ] **Step 1: Add the final three-root regression**

In `tests/integration/test_polyrepo_delivery_convergence.py`, create a temporary workspace with canonical spec, nested target harness, and separate target repository. Use deterministic fake phase controllers and GitOps while retaining real `StateStore`, finalization, review publication, and `run_skill` outcome wiring. Exercise `running -> verified -> validating -> reviewing -> finalizing -> converged`, then a blocked auto-land. Assert canonical lifecycle remains `ready_to_land`, delivery remains `converged`, landing outcome is `blocked`, all review provider writes were staged under target harness state, and no Git command used the harness root as the implementation repository.

- [ ] **Step 2: Update the changelog**

Add under the unreleased Fixed section:

```markdown
- Clarified delivery phase checkpoints and recovery, kept landing failures separate from convergence, and restricted automated Claude review triage to validated build-scoped staging before canonical task publication.
```

- [ ] **Step 3: Run focused verification**

```bash
pytest -q \
  tests/unit/test_delivery_results.py \
  tests/unit/test_state_machine.py \
  tests/unit/test_state_store_logic.py \
  tests/unit/test_coordinator.py \
  tests/unit/test_coordinator_review_reentry.py \
  tests/unit/test_visual_ralph.py \
  tests/unit/test_review_artifacts.py \
  tests/unit/test_review_loop.py \
  tests/unit/test_ai_cli_backend.py \
  tests/unit/test_llm_provider.py \
  tests/unit/test_run_skill.py \
  tests/unit/test_land.py \
  tests/integration/test_polyrepo_delivery_convergence.py
```

Expected: all selected tests pass.

- [ ] **Step 4: Run static and full verification**

```bash
python -m compileall -q src/harness
git diff --check
pytest
```

Expected: compilation and whitespace checks exit 0 and the full suite passes.

- [ ] **Step 5: Install and perform the existing read-only Prosaic smoke test**

Run `bash scripts/install.sh`, then repeat the exact installed-environment `_resolve_run_roots()`, `find_spec_dir("911", workspace)`, and `read_frontmatter()` smoke check from `docs/superpowers/plans/2026-08-06-polyrepo-auto-land-spec-discovery.md`. Capture target checkout HEAD, porcelain status, staged diff hash, and unstaged diff hash before and after; all four values must match. Do not invoke delivery, review, or land against the live Prosaic workspace.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md tests/integration/test_polyrepo_delivery_convergence.py tests/unit/test_run_skill.py tests/unit/test_coordinator.py tests/unit/test_review_loop.py tests/unit/test_land.py
git commit -m "test: cover recoverable polyrepo delivery convergence"
git status --short
```

Expected: the worktree is clean. Report automated results and read-only smoke evidence separately; do not claim live landing was exercised.
