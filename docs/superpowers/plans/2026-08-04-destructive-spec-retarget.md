# Destructive Spec Retarget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `echelon spec retarget` so an active, unimplemented spec can keep its identity and original request while destructively replacing its complete target set and rebuilding all Phase A outputs behind a mandatory recoverable checkpoint.

**Architecture:** A new retarget coordinator performs deterministic preflight, creates a Git-backed revision, bootstraps a same-spec/same-branch replacement run, and invalidates target-sensitive artifacts, memory, and graphs. The existing squad controller remains the completion authority: its durable completion intent gains one retarget effect that refreshes memory and graphs, writes exact receipts, completes the retarget revision, and commits the replacement result before readiness becomes visible. The existing checkpoint rewind command gains a retarget-specific recovery finalizer that restores baseline run state, memory, and graphs and creates a recovery commit.

**Tech Stack:** Python 3, Typer, pytest, JSON Schema, Git, existing Echelon squad/checkpoint/publication lifecycle, MemPalace/Chroma, and persisted spec/workspace artifact graphs.

## Global Constraints

- The selected spec must already be active, and `runs/.current`, active state, current branch, and canonical spec identity must agree.
- Retarget is allowed only when deterministic evidence proves Phase B has never started; ambiguous lifecycle evidence rejects the command and recommends a new spec run.
- `--target` is repeatable and is the complete replacement set; it uses existing `echelon spec run` target resolution, preserves order, rejects duplicates after normalization, rejects an empty set, and rejects an unchanged set.
- Preview is read-only. Confirmation creates the mandatory `retarget-preflight` checkpoint before canonical file deletion or external memory mutation.
- Retarget keeps the spec ID, feature branch, original prompt, autonomy mode, immutable product inputs, ignore-RE policy, and explicit RE selections. It creates a new Phase A run ID and does not rerun reverse engineering.
- Old `spec.md`, `plan.md`, `tasks.md`, and `targets.yml` are bounded, non-authoritative coverage context read from the checkpoint Git object, never the mutable working tree.
- Once the destructive boundary is crossed, the spec remains non-buildable until replacement finalization succeeds or the operator runs the printed checkpoint rewind command.
- MemPalace purge is exact-spec-only and fail-closed when configured storage cannot be scanned completely; no configured MemPalace records `not_applicable`.
- Graph handling composes from persisted member graph bytes and never calls broad workspace refresh or mutates unrelated specs.
- The replacement result has exactly one controller-owned completion commit. Recovery has exactly one recovery commit. Revision IDs are append-only while the latest revision status advances atomically.
- A common per-spec mutation lock serializes amendment, retarget, rewind, drop-target, and delivery preparation before existing ranked controller locks are acquired.
- Git staging is limited to the selected spec and explicitly owned lifecycle paths. Unrelated dirty files must remain byte-identical and unstaged.
- The current checkout contains unrelated uncommitted memory/graph work. Before editing `mempalace_memory_audit.py`, `mempalace_re.py`, `spec_graph.py`, `spec_memory_miner.py`, `re_*`, or their tests, inspect the current diff and apply additive patches without discarding or staging those changes.
- Do not create an isolated worktree from `HEAD` while those overlapping changes are uncommitted; it would omit the working baseline this feature must preserve.

---

### Task 1: Public Artifact Policy and Retarget Eligibility Classifier

**Files:**
- Create: `src/echelon/spec_retarget.py`
- Modify: `src/echelon/artifact_index.py`
- Create: `tests/unit/test_spec_retarget.py`
- Modify: `tests/unit/test_artifact_index.py`

**Interfaces:**
- Consumes: canonical `targets.yml` via `harness.spec_frontmatter.read_target_entries`, active `SpecRun` identity, canonical status/frontmatter, task target analysis, run histories, delivery state paths, and selected-spec Git status.
- Produces: `RetargetEvidence`, `RetargetEligibility`, `RetargetArtifactPlan`, `collect_retarget_evidence(project_root: Path, spec_id: str) -> RetargetEvidence`, `classify_retarget(evidence: RetargetEvidence) -> RetargetEligibility`, and `plan_retarget_artifacts(spec_dir: Path) -> RetargetArtifactPlan`.

- [ ] **Step 1: Write failing pure-classifier tests**

```python
from dataclasses import replace
from pathlib import Path

from echelon.spec_retarget import RetargetEvidence, classify_retarget


def eligible_evidence(tmp_path: Path) -> RetargetEvidence:
    return RetargetEvidence(
        spec_id="001-demo",
        run_id="squad-base",
        run_dir=tmp_path / "runs/squad-base",
        spec_dir=tmp_path / "specs/001-demo",
        feature_branch="001-demo",
        current_branch="001-demo",
        active_run_id="squad-base",
        canonical_targets=("services/api",),
        state_targets=("services/api",),
        replacement_targets=("apps/web",),
        lifecycle_status="planned",
        phase_b_history=(),
        delivery_state_paths=(),
        completed_task_ids=(),
        post_phase_a_artifacts=(),
        selected_spec_dirty_paths=(),
        original_user_message="Build account search",
        autonomy_mode="semi",
        product_inputs_recoverable=True,
        published_re_recoverable=True,
    )


def test_classifier_accepts_ready_phase_a_without_using_artifact_stage(tmp_path: Path) -> None:
    result = classify_retarget(eligible_evidence(tmp_path))
    assert result.eligible is True
    assert result.reason_codes == ()


def test_classifier_rejects_any_delivery_evidence(tmp_path: Path) -> None:
    evidence = replace(
        eligible_evidence(tmp_path),
        phase_b_history=("run-history.json:r-2",),
        delivery_state_paths=("runs/build-001/state.json",),
    )
    result = classify_retarget(evidence)
    assert result.eligible is False
    assert "retarget_delivery_already_started" in result.reason_codes
    assert result.next_command == "echelon spec run 'Build account search' --target apps/web"


def test_classifier_rejects_active_pointer_or_target_drift(tmp_path: Path) -> None:
    evidence = replace(
        eligible_evidence(tmp_path),
        active_run_id="squad-other",
        state_targets=("apps/web",),
    )
    result = classify_retarget(evidence)
    assert set(result.reason_codes) == {
        "retarget_active_spec_mismatch",
        "retarget_target_contract_mismatch",
    }
    assert result.next_command == "echelon spec switch 001-demo"
```

- [ ] **Step 2: Run the classifier tests and confirm the module is absent**

Run: `pytest -q tests/unit/test_spec_retarget.py -k classifier`

Expected: collection fails with `ModuleNotFoundError: No module named 'echelon.spec_retarget'`.

- [ ] **Step 3: Implement immutable evidence and deterministic classification**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex


class RetargetError(RuntimeError):
    """Base error for deterministic spec retarget operations."""


class RetargetEligibilityError(RetargetError):
    pass


class RetargetArtifactError(RetargetError):
    pass


class RetargetCheckpointError(RetargetError):
    pass


class RetargetRebuildError(RetargetError):
    pass


@dataclass(frozen=True)
class RetargetEvidence:
    spec_id: str
    run_id: str
    run_dir: Path
    spec_dir: Path
    feature_branch: str
    current_branch: str
    active_run_id: str
    canonical_targets: tuple[str, ...]
    state_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    lifecycle_status: str
    phase_b_history: tuple[str, ...]
    delivery_state_paths: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    post_phase_a_artifacts: tuple[str, ...]
    selected_spec_dirty_paths: tuple[str, ...]
    original_user_message: str
    autonomy_mode: str
    product_inputs_recoverable: bool
    published_re_recoverable: bool


@dataclass(frozen=True)
class RetargetEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]
    next_command: str


_POST_PHASE_A_STATUSES = frozenset(
    {"in-progress", "implemented", "ready_to_land", "landed"}
)


def classify_retarget(evidence: RetargetEvidence) -> RetargetEligibility:
    reasons: list[str] = []
    active_matches = (
        evidence.active_run_id == evidence.run_id
        and evidence.current_branch == evidence.feature_branch
    )
    if not active_matches:
        reasons.append("retarget_active_spec_mismatch")
    if evidence.state_targets != evidence.canonical_targets:
        reasons.append("retarget_target_contract_mismatch")
    if not evidence.replacement_targets:
        reasons.append("retarget_target_set_empty")
    elif evidence.replacement_targets == evidence.canonical_targets:
        reasons.append("retarget_target_set_unchanged")
    if (
        evidence.phase_b_history
        or evidence.delivery_state_paths
        or evidence.completed_task_ids
        or evidence.post_phase_a_artifacts
        or evidence.lifecycle_status in _POST_PHASE_A_STATUSES
    ):
        reasons.append("retarget_delivery_already_started")
    if evidence.selected_spec_dirty_paths:
        reasons.append("retarget_selected_spec_dirty")
    if not evidence.original_user_message or not evidence.product_inputs_recoverable:
        reasons.append("retarget_original_intent_missing")
    if not evidence.published_re_recoverable:
        reasons.append("retarget_re_context_missing")
    new_spec_command = shlex.join(
        [
            "echelon",
            "spec",
            "run",
            evidence.original_user_message,
            *(
                token
                for target in evidence.replacement_targets
                for token in ("--target", target)
            ),
        ]
    )
    next_command = (
        f"echelon spec switch {evidence.spec_id}"
        if "retarget_active_spec_mismatch" in reasons
        else new_spec_command
    )
    return RetargetEligibility(not reasons, tuple(dict.fromkeys(reasons)), next_command)
```

Keep evidence collection separate from classification. Collect Phase B entries from both history files, inspect build-state locations by exact `spec_id`, parse completed task checkboxes, and enumerate verification/build artifacts explicitly. Do not call `artifact_index.infer_lifecycle_stage()`.

- [ ] **Step 4: Write failing artifact-disposition tests**

```python
from echelon.artifact_index import plan_retarget_artifacts


def test_retarget_artifact_policy_preserves_inputs_and_invalidates_outputs(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs/001-demo"
    (spec_dir / "inputs").mkdir(parents=True)
    (spec_dir / "inputs/manifest.json").write_text("{}\n")
    (spec_dir / "inputs.yml").write_text("inputs: []\n")
    (spec_dir / "run-history.json").write_text('{"runs": []}\n')
    (spec_dir / "amendments/001/inputs").mkdir(parents=True)
    (spec_dir / "amendments/001/inputs/manifest.json").write_text("{}\n")
    (spec_dir / "spec.md").write_text("# Old spec\n")
    (spec_dir / "contracts").mkdir()
    (spec_dir / "contracts/api.yaml").write_text("openapi: 3.1.0\n")
    (spec_dir / "unknown-phase-a-report.md").write_text("old\n")

    plan = plan_retarget_artifacts(spec_dir)

    assert set(plan.preserve) >= {
        "amendments",
        "inputs",
        "inputs.yml",
        "run-history.json",
    }
    assert set(plan.invalidate) >= {
        "spec.md",
        "contracts",
        "unknown-phase-a-report.md",
    }
    assert not set(plan.preserve) & set(plan.invalidate)
```

- [ ] **Step 5: Extend the artifact registry with one public disposition plan**

```python
from dataclasses import dataclass
from enum import Enum


class RetargetDisposition(str, Enum):
    PRESERVE = "preserve"
    INVALIDATE = "invalidate"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RetargetArtifactPlan:
    preserve: tuple[str, ...]
    invalidate: tuple[str, ...]
    not_applicable: tuple[str, ...]


_RETARGET_PRESERVE_ROOTS = frozenset(
    {
        ".echelon",
        "amendments",
        "inputs",
        "inputs.yml",
        "retarget-history.json",
        "run-history.json",
    }
)


def plan_retarget_artifacts(spec_dir: Path) -> RetargetArtifactPlan:
    existing = tuple(sorted(path.name for path in spec_dir.iterdir()))
    preserve = tuple(name for name in existing if name in _RETARGET_PRESERVE_ROOTS)
    invalidate = tuple(name for name in existing if name not in _RETARGET_PRESERVE_ROOTS)
    declared = tuple(definition.path for definition in artifact_definitions())
    not_applicable = tuple(
        name for name in declared if not (spec_dir / name).exists()
    )
    return RetargetArtifactPlan(preserve, invalidate, not_applicable)
```

Expose `artifact_definitions()` as the read-only public view of the existing registry. Add explicit registry rows for retarget history, target contract, memory receipts, graph receipts, and currently generated Phase A reports so the preview and controller consume this policy instead of `_PHASE_A_GENERATED_FILES` or rewind cleanup lists. Preserve `.specify/memory/constitution.md` by never including workspace-global paths in a spec-local plan.

- [ ] **Step 6: Run focused tests**

Run: `pytest -q tests/unit/test_spec_retarget.py tests/unit/test_artifact_index.py`

Expected: all classifier and disposition tests pass, including existing artifact-map rendering tests.

- [ ] **Step 7: Commit classifier and policy**

```bash
git add src/echelon/spec_retarget.py src/echelon/artifact_index.py tests/unit/test_spec_retarget.py tests/unit/test_artifact_index.py
git commit -m "feat: classify safe spec retargets"
```

---

### Task 2: Common Per-Spec Mutation Lock

**Files:**
- Modify: `src/echelon/spec_lifecycle.py`
- Modify: `src/echelon/spec_amendment.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_spec_lifecycle.py`
- Modify: `tests/unit/test_spec_amendment.py`
- Modify: `tests/unit/test_cli_spec_targets.py`
- Modify: `tests/unit/test_cli_delivery_preflight.py`

**Interfaces:**
- Consumes: existing `SpecLifecycleLock._acquire_path(...)` and existing Phase A/controller lock ranks.
- Produces: `SpecMutationLock.acquire(project_root: Path, spec_id: str, operation_id: str) -> SpecMutationLock`; amendment, rewind, drop-target, retarget, and delivery preparation acquire it before `PhaseAExecutionLock`.

- [ ] **Step 1: Write the failing contention and isolation tests**

```python
from echelon.spec_lifecycle import SpecLifecycleLocked, SpecMutationLock


def test_spec_mutation_lock_serializes_one_spec_but_not_siblings(tmp_path: Path) -> None:
    first = SpecMutationLock.acquire(tmp_path, "001-demo", "retarget-a")
    try:
        with pytest.raises(SpecLifecycleLocked):
            SpecMutationLock.acquire(tmp_path, "001-demo", "delivery-b")
        sibling = SpecMutationLock.acquire(tmp_path, "002-other", "amend-c")
        sibling.release()
    finally:
        first.release()


def test_spec_mutation_lock_rejects_unsafe_spec_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe spec identity"):
        SpecMutationLock.acquire(tmp_path, "../outside", "retarget-a")
```

- [ ] **Step 2: Run the lock tests and confirm the class is missing**

Run: `pytest -q tests/unit/test_spec_lifecycle.py -k mutation_lock`

Expected: collection fails because `SpecMutationLock` is not exported.

- [ ] **Step 3: Implement the unranked outer lock**

```python
_SAFE_SPEC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SpecMutationLock(SpecLifecycleLock):
    """Outer serialization lease for one spec's lifecycle mutations."""

    @classmethod
    def acquire(
        cls,
        project_root: Path,
        spec_id: str,
        operation_id: str,
    ) -> "SpecMutationLock":
        if not _SAFE_SPEC_ID.fullmatch(spec_id):
            raise ValueError(f"unsafe spec identity: {spec_id!r}")
        return cls._acquire_path(
            _runtime_dir(project_root) / "spec-mutations" / f"{spec_id}.lock",
            operation_id,
            owner_label=f"spec mutation lock owner for {spec_id}",
        )
```

Do not assign this lock a controller rank. Its caller must acquire it before the existing `phase_a`, `spec_run`, `publication`, `completion`, and `checkpoint` ranks.

- [ ] **Step 4: Write failing operation-adoption tests**

```python
def test_drop_target_refuses_while_same_spec_mutation_is_locked(cli_workspace: Path) -> None:
    lock = SpecMutationLock.acquire(cli_workspace, "001-demo", "retarget-held")
    try:
        result = run_cli(cli_workspace, "spec", "drop-target", "001-demo", "api", "--confirm")
    finally:
        lock.release()
    assert result.exit_code == 1
    assert "retarget-held" in result.stderr


def test_delivery_preparation_refuses_active_retarget_lock(delivery_workspace: Path) -> None:
    lock = SpecMutationLock.acquire(delivery_workspace, "001-demo", "retarget-held")
    try:
        result = run_cli(delivery_workspace, "delivery", "run", "001-demo")
    finally:
        lock.release()
    assert result.exit_code == 1
    assert "spec mutation" in result.stderr.lower()
    assert not list((delivery_workspace / "runs").glob("build-*"))
```

- [ ] **Step 5: Adopt the lock at existing mutation boundaries**

Wrap amendment preparation, rewind mutation, drop-target confirmation, and the delivery preflight/build-state creation section with:

```python
operation_id = f"{operation}-{os.getpid()}"
with SpecMutationLock.acquire(project_root, spec_id, operation_id):
    with PhaseAExecutionLock.acquire(project_root, operation_id):
        perform_existing_preflight_and_state_transition()
```

Replace `AmendmentLock` acquisition with `SpecMutationLock` for canonical-spec mutation serialization while retaining amendment-specific state validation. For delivery, release the lock only after a Phase B run marker exists, so a concurrent retarget sees positive delivery evidence after acquiring the lock.

- [ ] **Step 6: Run lock-order and operation tests**

Run: `pytest -q tests/unit/test_spec_lifecycle.py tests/unit/test_spec_amendment.py tests/unit/test_cli_spec_targets.py tests/unit/test_cli_delivery_preflight.py`

Expected: all tests pass with no controller lock-order diagnostics.

- [ ] **Step 7: Commit shared serialization**

```bash
git add src/echelon/spec_lifecycle.py src/echelon/spec_amendment.py src/echelon/cli.py tests/unit/test_spec_lifecycle.py tests/unit/test_spec_amendment.py tests/unit/test_cli_spec_targets.py tests/unit/test_cli_delivery_preflight.py
git commit -m "feat: serialize per-spec lifecycle mutations"
```

---

### Task 3: Retarget Revision Ledger and Mandatory Checkpoint

**Files:**
- Create: `src/echelon/spec_retarget_history.py`
- Modify: `src/echelon/commit_messages.py`
- Modify: `src/harness/phase_checkpoints.py`
- Create: `tests/unit/test_spec_retarget_history.py`
- Modify: `tests/unit/test_commit_messages.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Consumes: `PhaseCheckpoint`, checkpoint ledger locking, Echelon commit trailers, and selected-spec path-limited commit helpers.
- Produces: `RetargetRevision`, `RetargetHistory`, `load_retarget_history(spec_dir: Path) -> RetargetHistory`, `append_prepared_revision(...) -> RetargetRevision`, `advance_retarget_revision(...) -> RetargetRevision`, and `commit_retarget_checkpoint(...) -> PhaseCheckpoint`.

- [ ] **Step 1: Write failing ledger transition tests**

```python
from echelon.spec_retarget_history import (
    RetargetRecoveryProjection,
    advance_retarget_revision,
    append_prepared_revision,
    load_retarget_history,
)


def test_retarget_revision_identity_is_append_only_and_status_advances(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    projection = RetargetRecoveryProjection(
        run_id="squad-base",
        status="done",
        phase="done",
        spec_status="planned",
        completed_phases=("phase1-requirements", "phase3-plan", "phase4-document"),
        implementation_targets=("services/api",),
        ready_to_build=True,
    )
    prepared = append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=projection,
    )
    completed = advance_retarget_revision(
        spec_dir,
        prepared.revision_id,
        expected_status="prepared",
        status="complete",
        updates={"replacement_commit": "b" * 40},
    )
    history = load_retarget_history(spec_dir)
    assert completed.revision_id == prepared.revision_id
    assert len(history.revisions) == 1
    assert history.revisions[0].status == "complete"


def test_retarget_history_rejects_skipped_transition(tmp_path: Path) -> None:
    spec_dir, revision = prepared_revision(tmp_path)
    with pytest.raises(ValueError, match="invalid retarget transition"):
        advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="prepared",
            status="recovered",
            updates={},
        )
```

- [ ] **Step 2: Run the history tests and confirm the module is absent**

Run: `pytest -q tests/unit/test_spec_retarget_history.py`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement validated atomic history persistence**

```python
RETARGET_HISTORY_FILENAME = "retarget-history.json"
_TRANSITIONS = {
    "prepared": frozenset({"invalidating", "failed"}),
    "invalidating": frozenset({"rebuilding", "failed"}),
    "rebuilding": frozenset({"finalizing", "failed"}),
    "finalizing": frozenset({"complete", "failed"}),
    "failed": frozenset({"recovered"}),
    "complete": frozenset(),
    "recovered": frozenset(),
}


@dataclass(frozen=True)
class RetargetRecoveryProjection:
    run_id: str
    status: str
    phase: str
    spec_status: str
    completed_phases: tuple[str, ...]
    implementation_targets: tuple[str, ...]
    ready_to_build: bool


@dataclass(frozen=True)
class RetargetRevision:
    revision_id: str
    operation_id: str
    status: str
    created_at: str
    updated_at: str
    baseline_run_id: str
    replacement_run_id: str
    old_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    original_prompt_digest: str
    recovery: RetargetRecoveryProjection
    checkpoint_id: str | None = None
    checkpoint_commit: str | None = None
    artifact_inventory: tuple[Mapping[str, object], ...] = ()
    memory_purge: Mapping[str, object] | None = None
    graph_invalidation: Mapping[str, object] | None = None
    memory_finalization: Mapping[str, object] | None = None
    graph_finalization: Mapping[str, object] | None = None
    replacement_commit: str | None = None
    recovery_commit: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class RetargetHistory:
    schema_version: int
    spec_id: str
    revisions: tuple[RetargetRevision, ...]


def advance_retarget_revision(
    spec_dir: Path,
    revision_id: str,
    *,
    expected_status: str,
    status: str,
    updates: Mapping[str, object],
) -> RetargetRevision:
    history = load_retarget_history(spec_dir)
    latest = history.revisions[-1]
    if latest.revision_id != revision_id or latest.status != expected_status:
        raise ValueError("retarget revision precondition changed")
    if status not in _TRANSITIONS[expected_status]:
        raise ValueError(f"invalid retarget transition: {expected_status} -> {status}")
    replacement = replace(latest, status=status, updated_at=_now(), **dict(updates))
    _write_history_atomic(spec_dir, replace(history, revisions=(*history.revisions[:-1], replacement)))
    return replacement
```

Use a temporary regular file in the spec directory, `fsync` it, `os.replace` it, and `fsync` the parent directory. Validate exact keys, bounded list/string sizes, SHA-256 values, Git object IDs, revision uniqueness, and that only the latest revision is mutable.

- [ ] **Step 4: Write a failing real-Git checkpoint test**

```python
def test_retarget_checkpoint_commits_prepared_ledger_and_trailers(git_spec: GitSpec) -> None:
    revision = write_prepared_revision(git_spec)
    checkpoint = commit_retarget_checkpoint(
        project_root=git_spec.root,
        spec_dir=git_spec.spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    message = git(git_spec.root, "show", "-s", "--format=%B", checkpoint.commit)
    ledger = git(git_spec.root, "show", f"{checkpoint.commit}:specs/001-demo/retarget-history.json")
    assert checkpoint.source == "retarget-preflight"
    assert "Echelon-Action: retarget-preflight" in message
    assert f"Echelon-Checkpoint: {checkpoint.id}" in message
    assert '"status": "prepared"' in ledger
```

Extend `EchelonCommitMetadata` with optional `retarget_revision`,
`baseline_run_id`, and `replacement_run_id` fields, rendered as
`Echelon-Retarget-Revision`, `Echelon-Baseline-Run`, and
`Echelon-Replacement-Run`. Add a commit-message unit test asserting empty
fields emit no trailers and populated fields emit each trailer exactly once.

- [ ] **Step 5: Add the retarget checkpoint constructor**

```python
def commit_retarget_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    run_id: str,
    revision_id: str,
) -> PhaseCheckpoint:
    checkpoint_id = new_checkpoint_id("retarget", "retarget-preflight")
    message = build_echelon_commit_message(
        f"checkpoint: prepare retarget {revision_id}",
        EchelonCommitMetadata(
            origin="phase-a",
            action="retarget-preflight",
            spec_id=_spec_id_from_dir(spec_dir),
            run_id=run_id,
            phase="retarget",
            next_phase="phase0-constitution",
            checkpoint_id=checkpoint_id,
            retarget_revision=revision_id,
            baseline_run_id=run_id,
        ),
    )
    commit = _commit_spec_changes(project_root, (spec_dir,), message)
    if commit is None:
        raise PhaseCheckpointError("retarget checkpoint produced no selected-spec change")
    checkpoint = PhaseCheckpoint(
        id=checkpoint_id,
        spec_id=_spec_id_from_dir(spec_dir),
        phase="retarget",
        next_phase="phase0-constitution",
        commit=commit,
        metadata_commit="",
        source="retarget-preflight",
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record_phase_checkpoint(spec_dir, checkpoint)
    return checkpoint
```

- [ ] **Step 6: Run history and checkpoint tests**

Run: `pytest -q tests/unit/test_spec_retarget_history.py tests/unit/test_commit_messages.py tests/unit/test_phase_checkpoints.py`

Expected: all tests pass and existing automatic/manual checkpoint behavior remains unchanged.

- [ ] **Step 7: Commit durable change control**

```bash
git add src/echelon/spec_retarget_history.py src/echelon/commit_messages.py src/harness/phase_checkpoints.py tests/unit/test_spec_retarget_history.py tests/unit/test_commit_messages.py tests/unit/test_phase_checkpoints.py
git commit -m "feat: checkpoint spec retarget revisions"
```

---

### Task 4: Same-Identity Replacement Run Bootstrap

**Files:**
- Modify: `src/echelon/phase_a_start.py`
- Modify: `src/echelon/product_inputs.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/published_re_context.py`
- Modify: `tests/unit/test_phase_a_start.py`
- Modify: `tests/unit/test_product_inputs.py`
- Modify: `tests/unit/test_published_re_context.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: baseline `SpecRun`, checkpoint object ID, replacement targets, persisted original state, `begin_spec_switch`/`mark_spec_switch_checked_out`/`commit_spec_switch_pointer`, and immutable product input bytes.
- Produces: `RetargetPhaseAStartOutcome`, `start_retarget_phase_a_spec(...) -> RetargetPhaseAStartOutcome`, and `clone_product_input_contract(project_root: Path, source_state: Mapping[str, object], replacement_run_dir: Path) -> dict[str, object]`.

- [ ] **Step 1: Write the failing same-identity bootstrap test**

```python
def test_retarget_bootstrap_keeps_spec_and_branch_but_creates_new_run(active_spec_repo: ActiveSpecRepo) -> None:
    before_branches = set(git_lines(active_spec_repo.root, "branch", "--format=%(refname:short)"))
    outcome = start_retarget_phase_a_spec(
        active_spec_repo.root,
        replacement_run_id="squad-retarget-1",
        baseline=active_spec_repo.run,
        checkpoint_commit=active_spec_repo.checkpoint_commit,
        replacement_targets=("apps/web", "services/api"),
        retarget_state=active_spec_repo.retarget_state,
    )
    state = json.loads((outcome.run_dir / "state.json").read_text())
    assert outcome.run.spec_id == active_spec_repo.run.spec_id
    assert outcome.run.feature_branch == active_spec_repo.run.feature_branch
    assert set(git_lines(active_spec_repo.root, "branch", "--format=%(refname:short)")) == before_branches
    assert (active_spec_repo.root / "runs/.current").read_text().strip() == "squad-retarget-1"
    assert state["implementation_targets"] == ["apps/web", "services/api"]
    assert state["retarget"]["baseline_run_id"] == active_spec_repo.run.run_id
```

- [ ] **Step 2: Run the bootstrap test and confirm the API is missing**

Run: `pytest -q tests/unit/test_phase_a_start.py -k retarget_bootstrap`

Expected: import or attribute failure for `start_retarget_phase_a_spec`.

- [ ] **Step 3: Add immutable product-input cloning with pointer rebasing**

```python
_PRODUCT_INPUT_POINTERS = (
    "inputs_dir",
    "manifest",
    "catalog",
    "input_context",
    "requirement_context",
    "reference_context",
    "traceability",
    "traceability_markdown",
)


def clone_product_input_contract(
    project_root: Path,
    source_state: Mapping[str, object],
    replacement_run_dir: Path,
) -> dict[str, object]:
    raw = source_state.get("product_inputs")
    if not isinstance(raw, Mapping) or not raw:
        return {}
    source = _resolve_project_path(project_root, str(raw["inputs_dir"]))
    destination = replacement_run_dir / "inputs"
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    cloned = dict(raw)
    source_root = source.resolve()
    for key in _PRODUCT_INPUT_POINTERS:
        value = cloned.get(key)
        if isinstance(value, str) and value:
            old_path = _resolve_project_path(project_root, value)
            cloned[key] = _portable(destination / old_path.relative_to(source_root), project_root)
    validate_immutable_product_input_package(destination, cloned)
    return cloned
```

Reject symlinks, non-regular input files, source paths outside the baseline run, hash drift, and destination collisions. Copy the complete aggregate package, including attachments, rather than resolving original external declarations again.

- [ ] **Step 4: Implement the same-branch pointer transaction**

```python
@dataclass(frozen=True)
class RetargetPhaseAStartOutcome:
    run_dir: Path
    run: SpecRun
    baseline: SpecRun


def start_retarget_phase_a_spec(
    project_root: Path,
    *,
    replacement_run_id: str,
    baseline: SpecRun,
    checkpoint_commit: str,
    replacement_targets: tuple[str, ...],
    retarget_state: Mapping[str, object],
) -> RetargetPhaseAStartOutcome:
    root = Path(project_root).resolve()
    run_dir = root / "runs" / replacement_run_id
    product_inputs = clone_product_input_contract(root, _load_state(baseline.run_dir), run_dir)
    _write_retarget_prepared_state(
        run_dir,
        baseline=baseline,
        replacement_run_id=replacement_run_id,
        checkpoint_commit=checkpoint_commit,
        replacement_targets=replacement_targets,
        retarget_state=retarget_state,
        product_inputs=product_inputs,
    )
    target = resolve_spec_run(root, replacement_run_id)
    operation_id = str(retarget_state["operation_id"])
    observed = current_branch(root)
    begin_spec_switch(root, baseline, target, observed_branch=observed, operation_id=operation_id)
    mark_spec_switch_checked_out(root, operation_id, observed_branch=observed)
    selected = commit_spec_switch_pointer(root, operation_id, observed_branch=observed)
    return RetargetPhaseAStartOutcome(run_dir=run_dir, run=selected, baseline=baseline)
```

The prepared state carries the original `user_message`, `autonomy_mode`, exact replacement targets, cloned product inputs, original ignore-RE policy, explicit RE source IDs, `phase0-constitution` entry, and `retarget.status = "checkpointed"`. It binds the existing canonical and run-local spec paths without calling `plan_phase_a_spec` or creating a Git ref.

- [ ] **Step 5: Preserve retarget state through normal squad initialization**

Extend the controller's prepared identity copy to include `retarget`, `product_inputs`, and persisted RE policy fields:

```python
prepared_identity = {
    key: existing[key]
    for key in (
        "run_id",
        "spec_id",
        "spec_number",
        "spec_dir",
        "published_spec_dir",
        "feature_branch",
        "phase_a_default_branch",
        "phase_a_base_commit",
        "specify_feature_directory",
        "retarget",
        "product_inputs",
        "ignore_re",
        "requested_re_sources",
    )
    if key in existing
}
```

When prepared product inputs exist, pass their dict to `SquadStateStore.initialize` instead of replacing it with `{}`. Ensure initialization leaves baseline run state untouched.

- [ ] **Step 6: Test and implement RE selection preservation**

```python
def test_retarget_reuses_explicit_sources_and_recomputes_automatic_sources(published_re_workspace: Path) -> None:
    prior = {
        "status": "attached",
        "selected_sources": ["api", "legacy"],
        "selection_reason": {
            "api": "explicit --re-source",
            "legacy": "target matched published source path",
        },
    }
    assert explicit_re_sources(prior) == ("api",)
    context = attach_published_re_context(
        published_re_workspace,
        published_re_workspace / "runs/squad-retarget",
        ignore=False,
        implementation_targets=["apps/web"],
        re_sources=list(explicit_re_sources(prior)),
    )
    assert context["selected_sources"] == ["api", "web"]
```

```python
def explicit_re_sources(context: Mapping[str, object]) -> tuple[str, ...]:
    selected = context.get("selected_sources")
    reasons = context.get("selection_reason")
    if not isinstance(selected, list) or not isinstance(reasons, Mapping):
        return ()
    return tuple(
        source
        for source in selected
        if isinstance(source, str) and reasons.get(source) == "explicit --re-source"
    )
```

- [ ] **Step 7: Run bootstrap, input, RE, and initialization tests**

Run: `pytest -q tests/unit/test_phase_a_start.py tests/unit/test_product_inputs.py tests/unit/test_published_re_context.py tests/integration/test_squad_controller.py -k 'retarget or product_input or published_re or prepared_identity'`

Expected: all selected tests pass; no new branch or spec directory is created.

- [ ] **Step 8: Commit the replacement bootstrap**

```bash
git add src/echelon/phase_a_start.py src/echelon/product_inputs.py src/harness/squad.py src/harness/squad_state.py src/harness/published_re_context.py tests/unit/test_phase_a_start.py tests/unit/test_product_inputs.py tests/unit/test_published_re_context.py tests/integration/test_squad_controller.py
git commit -m "feat: bootstrap same-identity retarget runs"
```

---

### Task 5: Exact MemPalace Retarget Purge and Refresh

**Files:**
- Create: `src/echelon/mempalace_retarget.py`
- Modify: `src/echelon/mempalace_audit.py`
- Modify: `src/harness/squad.py`
- Create: `tests/unit/test_mempalace_retarget.py`
- Modify: `tests/unit/test_mempalace_audit.py`
- Modify: `tests/integration/test_squad_context_memory.py`

**Interfaces:**
- Consumes: configured requirement-memory adapter, Chroma collection `get`/`delete`, `mine_spec_requirements`, `cleanup_stale_spec_memory`, and `audit_spec_memory`.
- Produces: `RetargetMemoryReceipt`, `purge_retarget_spec_memory(project_root: Path, spec_id: str) -> RetargetMemoryReceipt`, and `refresh_retarget_spec_memory(project_root: Path, spec_dir: Path) -> RetargetMemoryReceipt`.

- [ ] **Step 1: Write failing ownership and complete-scan tests**

```python
def test_retarget_purge_deletes_only_exact_spec_owned_drawers(memory_workspace: MemoryWorkspace) -> None:
    memory_workspace.collection.rows = {
        "owned-canonical": ("old", {"wing": "demo", "canonical": True, "artifact_path": "specs/001-demo/spec.md", "spec_id": "001-demo"}),
        "owned-support": ("old plan", {"wing": "demo", "artifact_path": "specs/001-demo/plan.md", "spec_id": "001-demo"}),
        "workspace-re": ("re", {"wing": "demo", "artifact_path": "re/sources/api/overview.md"}),
        "other-spec": ("other", {"wing": "demo", "artifact_path": "specs/002-other/spec.md", "spec_id": "002-other"}),
    }
    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")
    assert receipt.status == "pass"
    assert receipt.deleted_ids == ("owned-canonical", "owned-support")
    assert set(memory_workspace.collection.rows) == {"workspace-re", "other-spec"}


def test_retarget_purge_fails_before_delete_when_scan_is_truncated(memory_workspace: MemoryWorkspace) -> None:
    memory_workspace.collection.force_truncated = True
    with pytest.raises(RetargetMemoryError, match="complete scan"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")
    assert memory_workspace.collection.deleted_batches == []


def test_retarget_memory_is_not_applicable_without_configuration(tmp_path: Path) -> None:
    receipt = purge_retarget_spec_memory(tmp_path, "001-demo")
    assert receipt.status == "not_applicable"
    assert receipt.deleted_ids == ()
```

- [ ] **Step 2: Run the purge tests and confirm the module is absent**

Run: `pytest -q tests/unit/test_mempalace_retarget.py -k purge`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Add a complete paginated scanner without disturbing audit behavior**

```python
def scan_wing_rows_complete(
    collection: object,
    *,
    wing: str,
    page_size: int = 512,
    maximum_rows: int = MAX_AUDIT_SCAN_ROWS,
) -> dict[str, tuple[str, dict[str, object]]]:
    rows: dict[str, tuple[str, dict[str, object]]] = {}
    offset = 0
    while offset < maximum_rows:
        raw = collection.get(
            where={"wing": wing},
            include=["documents", "metadatas"],
            limit=min(page_size, maximum_rows - offset),
            offset=offset,
        )
        page = _as_collection_rows(raw)
        overlap = set(rows).intersection(page.rows)
        if overlap:
            raise SpecMemoryError("MemPalace pagination returned duplicate drawer IDs")
        rows.update(page.rows)
        count = len(page.rows)
        if count < page_size:
            return rows
        offset += count
    probe = collection.get(
        where={"wing": wing},
        include=["metadatas"],
        limit=1,
        offset=offset,
    )
    if _as_collection_rows(probe).rows:
        raise SpecMemoryError("MemPalace complete scan exceeded the bounded row limit")
    return rows
```

Export this helper from `mempalace_audit.py`; retain current ordinary audit/cleanup semantics and tests. The new retarget module alone applies the strict fail-closed policy.

- [ ] **Step 4: Implement exact ownership classification and purge receipts**

```python
class RetargetMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetargetMemoryReceipt:
    status: str
    spec_id: str
    deleted_count: int
    deleted_ids: tuple[str, ...]
    drawer_set_digest: str
    mine_status: str | None = None
    audit_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "spec_id": self.spec_id,
            "deleted_count": self.deleted_count,
            "deleted_ids": list(self.deleted_ids),
            "drawer_set_digest": self.drawer_set_digest,
            "mine_status": self.mine_status,
            "audit_status": self.audit_status,
        }


def _owned_by_spec(metadata: Mapping[str, object], spec_id: str) -> bool:
    declared = str(metadata.get("spec_id") or "")
    path = str(metadata.get("artifact_path") or metadata.get("source_file") or "")
    under_spec = PurePosixPath(path).parts[:2] == ("specs", spec_id)
    if declared and declared != spec_id and under_spec:
        raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
    return declared == spec_id or under_spec


def purge_retarget_spec_memory(project_root: Path, spec_id: str) -> RetargetMemoryReceipt:
    if not configured_mempalace_wing(project_root):
        return RetargetMemoryReceipt("not_applicable", spec_id, 0, (), _digest_ids(()))
    adapter = create_requirement_memory_adapter(project_root, run_id="retarget-purge")
    rows = scan_wing_rows_complete(
        _collection_from_requirement_adapter(adapter),
        wing=str(adapter.wing),
    )
    owned = tuple(sorted(drawer_id for drawer_id, (_, metadata) in rows.items() if _owned_by_spec(metadata, spec_id)))
    if owned:
        _collection_from_requirement_adapter(adapter).delete(ids=list(owned))
    return RetargetMemoryReceipt("pass", spec_id, len(owned), owned, _digest_ids(owned))
```

Receipt serialization stores IDs and digests but never deleted document text. Treat configured-but-unavailable adapter creation, ambiguous ownership, unsupported pagination, scan overflow, and partial deletion as `RetargetMemoryError`.

- [ ] **Step 5: Write and implement replacement refresh tests**

```python
def test_retarget_refresh_requires_acceptable_mine_and_audit(memory_workspace: MemoryWorkspace) -> None:
    receipt = refresh_retarget_spec_memory(memory_workspace.root, memory_workspace.spec_dir)
    assert receipt.status == "pass"
    assert receipt.mine_status == "complete"
    assert receipt.audit_status in {"pass", "warn"}
    assert (memory_workspace.spec_dir / "mempalace-mine.json").is_file()
    assert (memory_workspace.spec_dir / "mempalace-audit.json").is_file()


def test_retarget_refresh_rejects_unavailable_configured_memory(memory_workspace: MemoryWorkspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("echelon.mempalace_retarget.audit_spec_memory", lambda *_args, **_kwargs: unavailable_audit())
    with pytest.raises(RetargetMemoryError, match="audit"):
        refresh_retarget_spec_memory(memory_workspace.root, memory_workspace.spec_dir)
```

```python
def refresh_retarget_spec_memory(project_root: Path, spec_dir: Path) -> RetargetMemoryReceipt:
    if not configured_mempalace_wing(project_root):
        return RetargetMemoryReceipt("not_applicable", spec_dir.name, 0, (), _digest_ids(()), "not_applicable", "not_applicable")
    mine = mine_spec_requirements(project_root, spec_dir, run_id="retarget-finalize")
    cleanup = cleanup_stale_spec_memory(project_root, spec_dir)
    audit = audit_spec_memory(project_root, spec_dir, probe_retrieval=True)
    if mine.status != "complete" or audit.status not in {"pass", "warn"}:
        raise RetargetMemoryError(f"replacement memory audit is {audit.status}")
    (spec_dir / "mempalace-mine.json").write_text(
        json.dumps(mine.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_audit_reports(audit, spec_dir)
    ids = tuple(sorted(set(mine.drawer_ids)))
    return RetargetMemoryReceipt("pass", spec_dir.name, cleanup.deleted_count, tuple(cleanup.deleted_ids), _digest_ids(ids), mine.status, audit.status)
```

After deleting the selected IDs, perform the same complete scan again and fail
if any owned ID remains. During the replacement run, filter retrieved context
drawers with `exclude_retarget_spec_drawers(drawers, spec_id)`: omit a drawer
when its metadata has exact `spec_id` ownership or an artifact path under
`specs/<id>/`, preserve workspace RE and other-spec drawers, and reject
contradictory ownership metadata. `SquadController._retrieve_mempalace_context_drawers`
applies this filter whenever `state.retarget.memory_excluded` is true.

- [ ] **Step 6: Run memory tests, including the pre-existing dirty-file suite**

Run: `pytest -q tests/unit/test_mempalace_retarget.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_re.py tests/unit/test_spec_memory_miner.py tests/integration/test_squad_context_memory.py`

Expected: all tests pass; the existing uncommitted memory-enrichment behavior is preserved.

- [ ] **Step 7: Commit only retarget memory changes**

Before staging, run `git diff -- src/echelon/mempalace_audit.py tests/unit/test_mempalace_audit.py` and separate pre-existing hunks from retarget hunks with `git add -p`.

```bash
git add src/echelon/mempalace_retarget.py src/harness/squad.py tests/unit/test_mempalace_retarget.py tests/integration/test_squad_context_memory.py
git add -p src/echelon/mempalace_audit.py tests/unit/test_mempalace_audit.py
git commit -m "feat: purge retargeted spec memory safely"
```

---

### Task 6: Selected-Spec Graph Invalidation and Composition

**Files:**
- Create: `src/echelon/spec_retarget_graph.py`
- Modify: `src/echelon/workspace_graph.py`
- Create: `tests/unit/test_spec_retarget_graph.py`
- Modify: `tests/unit/test_workspace_graph.py`
- Modify: `tests/unit/test_spec_graph.py`

**Interfaces:**
- Consumes: persisted spec graph/audit bytes, `build_spec_graph`, `audit_spec_graph`, `build_workspace_graph`, `audit_workspace_graph`, and their atomic writers.
- Produces: `RetargetGraphReceipt`, `invalidate_retarget_graphs(project_root: Path, spec_dir: Path) -> RetargetGraphReceipt`, and `finalize_retarget_graphs(project_root: Path, spec_dir: Path, baseline: RetargetGraphReceipt) -> RetargetGraphReceipt`.

- [ ] **Step 1: Write failing invalidation tests for one- and multi-spec workspaces**

```python
def test_single_spec_invalidation_removes_workspace_graph_and_audit(graph_workspace: GraphWorkspace) -> None:
    (graph_workspace.selected_spec / "spec.md").unlink()
    receipt = invalidate_retarget_graphs(graph_workspace.root, graph_workspace.selected_spec)
    assert receipt.workspace_status == "not_applicable_empty_workspace"
    assert not (graph_workspace.selected_spec / "spec-artifact-graph.json").exists()
    assert not workspace_graph_path(graph_workspace.root).exists()
    assert not workspace_graph_path(graph_workspace.root).with_name("workspace-artifact-graph-audit.json").exists()


def test_multi_spec_invalidation_composes_from_other_persisted_members(graph_workspace_two_specs: GraphWorkspace) -> None:
    other_before = (graph_workspace_two_specs.other_spec / "spec-artifact-graph.json").read_bytes()
    (graph_workspace_two_specs.selected_spec / "spec.md").unlink()
    receipt = invalidate_retarget_graphs(graph_workspace_two_specs.root, graph_workspace_two_specs.selected_spec)
    document = json.loads(workspace_graph_path(graph_workspace_two_specs.root).read_text())
    assert [member["spec_id"] for member in document["members"]] == [graph_workspace_two_specs.other_spec.name]
    assert (graph_workspace_two_specs.other_spec / "spec-artifact-graph.json").read_bytes() == other_before
    assert receipt.workspace_status in {"pass", "warn"}
```

- [ ] **Step 2: Run graph invalidation tests and confirm the module is absent**

Run: `pytest -q tests/unit/test_spec_retarget_graph.py -k invalidation`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement invalidation without broad refresh**

```python
class RetargetGraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetargetGraphReceipt:
    spec_id: str
    spec_status: str
    spec_graph_hash: str | None
    workspace_status: str
    workspace_graph_hash: str | None
    workspace_finding_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_id": self.spec_id,
            "spec_status": self.spec_status,
            "spec_graph_hash": self.spec_graph_hash,
            "workspace_status": self.workspace_status,
            "workspace_graph_hash": self.workspace_graph_hash,
            "workspace_finding_codes": list(self.workspace_finding_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RetargetGraphReceipt":
        return cls(
            spec_id=str(value["spec_id"]),
            spec_status=str(value["spec_status"]),
            spec_graph_hash=(
                str(value["spec_graph_hash"])
                if value.get("spec_graph_hash") is not None
                else None
            ),
            workspace_status=str(value["workspace_status"]),
            workspace_graph_hash=(
                str(value["workspace_graph_hash"])
                if value.get("workspace_graph_hash") is not None
                else None
            ),
            workspace_finding_codes=tuple(
                str(item) for item in value.get("workspace_finding_codes", [])
            ),
        )


def invalidate_retarget_graphs(project_root: Path, spec_dir: Path) -> RetargetGraphReceipt:
    (spec_dir / GRAPH_FILENAME).unlink(missing_ok=True)
    (spec_dir / GRAPH_AUDIT_FILENAME).unlink(missing_ok=True)
    remaining = discover_canonical_spec_dirs(project_root)
    if not remaining:
        workspace_graph_path(project_root).unlink(missing_ok=True)
        workspace_graph_path(project_root).with_name(WORKSPACE_GRAPH_AUDIT_FILENAME).unlink(missing_ok=True)
        return RetargetGraphReceipt(spec_dir.name, "invalidated", None, "not_applicable_empty_workspace", None, ())
    built = build_workspace_graph(project_root)
    path = write_workspace_graph(built.graph, project_root)
    audit = audit_workspace_graph(project_root, candidate=built)
    write_workspace_graph_audit(audit, project_root)
    return _workspace_receipt(spec_dir.name, "invalidated", None, path, audit)
```

Call this only after `spec.md` is in the artifact invalidation set, so canonical discovery excludes the retargeting spec. Do not import or call `workspace_graph_refresh.refresh_workspace_graph`.

- [ ] **Step 4: Write failing selected-spec finalization tests**

```python
def test_graph_finalization_requires_selected_spec_current_but_tolerates_old_other_warning(graph_workspace_two_specs: GraphWorkspace) -> None:
    baseline = graph_workspace_two_specs.invalidation_receipt(
        workspace_finding_codes=("workspace_member_audit_warning:002-other",)
    )
    receipt = finalize_retarget_graphs(
        graph_workspace_two_specs.root,
        graph_workspace_two_specs.selected_spec,
        baseline,
    )
    assert receipt.spec_status in {"pass", "warn"}
    assert receipt.workspace_status in {"pass", "warn"}
    members = json.loads(workspace_graph_path(graph_workspace_two_specs.root).read_text())["members"]
    assert any(member["spec_id"] == "001-demo" and member["included"] for member in members)


def test_graph_finalization_rejects_new_selected_spec_error(graph_workspace: GraphWorkspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("echelon.spec_retarget_graph.audit_spec_graph", lambda *_args: failing_spec_audit("graph_source_set_stale"))
    with pytest.raises(RetargetGraphError, match="selected spec graph"):
        finalize_retarget_graphs(graph_workspace.root, graph_workspace.selected_spec, graph_workspace.baseline)
```

- [ ] **Step 5: Implement memory-first final composition and attribution**

```python
def finalize_retarget_graphs(
    project_root: Path,
    spec_dir: Path,
    baseline: RetargetGraphReceipt,
) -> RetargetGraphReceipt:
    graph = build_spec_graph(project_root, spec_dir)
    spec_path = write_spec_graph(graph, spec_dir)
    spec_audit = audit_spec_graph(project_root, spec_dir)
    write_spec_graph_audit(spec_audit, spec_dir)
    if spec_audit.status not in {"pass", "warn"}:
        raise RetargetGraphError("selected spec graph audit failed")
    built = build_workspace_graph(project_root)
    selected = next((member for member in built.graph.members if member.spec_id == spec_dir.name), None)
    if selected is None or not selected.included:
        raise RetargetGraphError("selected spec is not a current workspace member")
    workspace_path = write_workspace_graph(built.graph, project_root)
    workspace_audit = audit_workspace_graph(project_root, candidate=built)
    write_workspace_graph_audit(workspace_audit, project_root)
    _reject_new_retarget_attributable_findings(workspace_audit, baseline, spec_dir.name)
    return _complete_graph_receipt(spec_dir, spec_path, spec_audit, workspace_path, workspace_audit)
```

Compare stable finding identities against the invalidation receipt. Ignore unchanged findings attributed to other specs; reject any selected-spec error and any newly introduced workspace error.

- [ ] **Step 6: Run focused and pre-existing graph suites**

Run: `pytest -q tests/unit/test_spec_retarget_graph.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_refresh.py tests/integration/test_spec_graph_workflow.py tests/integration/test_workspace_graph_workflow.py`

Expected: all tests pass; unrelated persisted member bytes are unchanged.

- [ ] **Step 7: Commit only retarget graph changes**

Inspect and interactively stage overlapping `spec_graph.py` and graph tests if they required edits. Prefer keeping retarget orchestration in the new module.

```bash
git add src/echelon/spec_retarget_graph.py src/echelon/workspace_graph.py tests/unit/test_spec_retarget_graph.py
git add -p tests/unit/test_workspace_graph.py tests/unit/test_spec_graph.py
git commit -m "feat: invalidate and compose retarget graphs"
```

---

### Task 7: Destructive Retarget Coordinator and CLI

**Files:**
- Modify: `src/echelon/spec_retarget.py`
- Create: `src/echelon/spec_retarget_cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Create: `tests/unit/test_cli_spec_retarget.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: Tasks 1-6, existing target resolver, common mutation/Phase A/spec-run locks, `commit_retarget_checkpoint`, and the existing `_cmd_run` Phase A entry.
- Produces: `RetargetCommandResult`, `prepare_spec_retarget(project_root: Path, spec_id: str, replacement_targets: tuple[str, ...], *, confirm: bool, checkpoint_created: Callable[[PhaseCheckpoint], None] | None = None) -> RetargetCommandResult`, `run_spec_retarget_command(args: list[str], project_root: Path) -> RetargetCommandResult`, and the public Typer command.

- [ ] **Step 1: Write failing preview tests**

```python
def test_retarget_preview_is_read_only(retarget_cli_workspace: Path) -> None:
    before = workspace_snapshot(retarget_cli_workspace)
    result = run_cli(
        retarget_cli_workspace,
        "spec",
        "retarget",
        "001-demo",
        "--target",
        "apps/web",
    )
    assert result.exit_code == 0
    assert "RETARGET PREVIEW" in result.stdout
    assert "DESTRUCTIVE" in result.stdout
    assert "non-buildable" in result.stdout
    assert "echelon spec rewind checkpoint:retarget-preflight-" in result.stdout
    assert workspace_snapshot(retarget_cli_workspace) == before


def test_retarget_preview_rejects_missing_active_selection(retarget_cli_workspace: Path) -> None:
    (retarget_cli_workspace / "runs/.current").write_text("squad-other\n")
    result = run_cli(retarget_cli_workspace, "spec", "retarget", "001-demo", "--target", "apps/web")
    assert result.exit_code == 1
    assert "echelon spec switch 001-demo" in result.stderr
```

- [ ] **Step 2: Run preview tests and confirm the command is absent**

Run: `pytest -q tests/unit/test_cli_spec_retarget.py -k preview`

Expected: CLI exits with unknown command `retarget`.

- [ ] **Step 3: Add the Typer and legacy dispatch surfaces**

```python
@spec_app.command("retarget")
def spec_retarget(
    spec_id: str = typer.Argument(..., help="Active unimplemented spec id."),
    target: list[str] = typer.Option(
        ...,
        "--target",
        help="Complete replacement implementation target set; repeat as needed.",
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Create the checkpoint and rebuild Phase A."),
) -> None:
    from echelon import cli as legacy_cli

    args = [spec_id]
    _extend_repeated_option(args, "--target", target)
    if confirm:
        args.append("--confirm")
    legacy_cli._cmd_spec_retarget(args)
```

Add `retarget` to `_cmd_spec` help/dispatch and root usage. Parse exactly one spec selector, one or more `--target` values, and at most one `--confirm`; reject `--init`, positional targets, and unknown flags with exit code 2.

- [ ] **Step 4: Implement deterministic preview rendering**

```python
@dataclass(frozen=True)
class RetargetPreview:
    project_root: Path
    spec_id: str
    baseline: SpecRun
    spec_dir: Path
    old_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    artifact_plan: RetargetArtifactPlan
    operation_id: str
    original_user_message: str
    autonomy_mode: str
    ignore_re: bool
    explicit_re_sources: tuple[str, ...]


@dataclass(frozen=True)
class RetargetCommandResult:
    applied: bool
    resume_existing: bool
    spec_id: str
    baseline_run_id: str
    replacement_run_id: str | None
    replacement_targets: tuple[str, ...]
    checkpoint_id: str | None
    checkpoint_commit: str | None
    recovery_command: str
    invalidated_paths: tuple[str, ...]
    original_user_message: str
    autonomy_mode: str
    ignore_re: bool
    explicit_re_sources: tuple[str, ...]


def preview_recovery_command(prospective_checkpoint_id: str) -> str:
    return f"echelon spec rewind checkpoint:{prospective_checkpoint_id} --confirm"
```

Resolve targets through the existing Phase A resolver with `allow_missing=False`. The coordinator receives normalized values and rejects empty/unchanged sets. Preview collects all eligibility, artifact, memory-domain, and graph information but creates no run ID, lock directory, checkpoint ID file, state, ledger, or Git object.

- [ ] **Step 5: Write failing confirmation and failure-path tests**

```python
def test_retarget_confirm_checkpoints_then_invalidates_and_starts_phase_a(retarget_cli_workspace: Path, fake_squad: FakeSquad) -> None:
    unrelated = retarget_cli_workspace / "notes/private.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("keep\n")
    result = run_cli(retarget_cli_workspace, "spec", "retarget", "001-demo", "--target", "apps/web", "--confirm")
    state = active_state(retarget_cli_workspace)
    assert result.exit_code == 0
    assert state["run_id"] != "squad-base"
    assert state["spec_id"] == "001-demo"
    assert state["implementation_targets"] == ["apps/web"]
    assert state["retarget"]["status"] in {"rebuilding", "finalizing", "complete"}
    assert not (retarget_cli_workspace / "specs/001-demo/spec.md").read_text().startswith("# Old")
    assert unrelated.read_text() == "keep\n"
    assert "echelon spec rewind checkpoint:" in result.stdout


def test_retarget_purge_failure_keeps_spec_blocked_and_prints_recovery(retarget_cli_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("echelon.spec_retarget.purge_retarget_spec_memory", raise_memory_failure)
    result = run_cli(retarget_cli_workspace, "spec", "retarget", "001-demo", "--target", "apps/web", "--confirm")
    assert result.exit_code == 1
    assert active_state(retarget_cli_workspace)["retarget"]["status"] == "failed"
    assert "echelon spec rewind checkpoint:" in result.stderr
    assert not list((retarget_cli_workspace / "runs").glob("build-*"))


def test_repeated_confirm_resumes_same_revision(retarget_cli_workspace: Path, fake_squad: FakeSquad) -> None:
    first = run_cli(retarget_cli_workspace, "spec", "retarget", "001-demo", "--target", "apps/web", "--confirm")
    fake_squad.interrupt_after_invalidation()
    second = run_cli(retarget_cli_workspace, "spec", "retarget", "001-demo", "--target", "apps/web", "--confirm")
    assert first.exit_code == second.exit_code == 0
    assert len(load_retarget_history(retarget_cli_workspace / "specs/001-demo").revisions) == 1
```

- [ ] **Step 6: Implement the ordered destructive transaction**

```python
def _apply_retarget(
    preview: RetargetPreview,
    *,
    checkpoint_created: Callable[[PhaseCheckpoint], None] | None,
) -> RetargetCommandResult:
    operation_id = preview.operation_id
    with SpecMutationLock.acquire(preview.project_root, preview.spec_id, operation_id):
        with PhaseAExecutionLock.acquire(preview.project_root, operation_id):
            with SpecRunExecutionLock.acquire(preview.baseline.run_dir, operation_id):
                rechecked = require_same_retarget_preflight(preview)
                revision = append_prepared_revision_from_preview(rechecked)
                checkpoint = commit_retarget_checkpoint(
                    project_root=preview.project_root,
                    spec_dir=preview.spec_dir,
                    run_id=preview.baseline.run_id,
                    revision_id=revision.revision_id,
                )
                if checkpoint_created is not None:
                    checkpoint_created(checkpoint)
                replacement = start_retarget_phase_a_spec_from_preview(rechecked, revision, checkpoint)
                try:
                    memory = purge_retarget_spec_memory(preview.project_root, preview.spec_id)
                    persist_retarget_memory_exclusion(replacement.run_dir, memory)
                    invalidate_retarget_artifacts(preview.spec_dir, preview.artifact_plan)
                    graph = invalidate_retarget_graphs(preview.project_root, preview.spec_dir)
                    write_checkpoint_coverage_context(preview, replacement.run_dir, checkpoint.commit)
                    mark_retarget_rebuilding(replacement.run_dir, preview.spec_dir, memory, graph)
                except Exception as exc:
                    mark_retarget_failed(replacement.run_dir, preview.spec_dir, bounded_failure_code(exc))
                    raise RetargetDestructiveError(checkpoint, exc) from exc
    return command_result_from_replacement(preview, replacement, checkpoint)
```

The CLI passes a callback that prints the exact recovery command and calls
`sys.stdout.flush()` before returning. The callback therefore completes before
the replacement bootstrap and first purge call. `invalidate_retarget_artifacts`
validates every planned path under `spec_dir`, rejects symlinks, removes
directories with controller-owned traversal, writes replacement `targets.yml`,
and never uses a glob or broad workspace root.

Before ordinary canonical preflight, detect an active non-terminal retarget in
the selected replacement run. If its spec ID and normalized replacement targets
match, return `resume_existing=True` and the recorded checkpoint/revision instead
of allocating another run or checkpoint. If they differ, reject the retry and
print the recorded recovery command. A durable `failed` state is recoverable
only through rewind; only `checkpointed`, `invalidating`, `rebuilding`, and
`finalizing` operations can resume in place.

Define and test the stable exception-to-code map in `spec_retarget.py`:

```python
_RETARGET_FAILURE_CODES = {
    RetargetEligibilityError: "retarget_delivery_already_started",
    RetargetCheckpointError: "retarget_checkpoint_failed",
    RetargetMemoryError: "retarget_memory_purge_failed",
    RetargetArtifactError: "retarget_artifact_invalidation_failed",
    RetargetGraphError: "retarget_graph_refresh_failed",
    RetargetRebuildError: "retarget_rebuild_blocked",
}


def bounded_failure_code(error: BaseException) -> str:
    for error_type, code in _RETARGET_FAILURE_CODES.items():
        if isinstance(error, error_type):
            return code
    return "retarget_rebuild_blocked"
```

Preflight uses the more specific reason codes from `RetargetEligibility` for
original-intent, target-set, active-spec, and delivery-started rejection.
Finalization maps memory refresh, graph refresh, and recovery refresh failures
to `retarget_memory_refresh_failed`, `retarget_graph_refresh_failed`, and
`retarget_recovery_refresh_failed` respectively.

- [ ] **Step 7: Read bounded old coverage context from Git**

```python
_RETARGET_CONTEXT_PATHS = ("spec.md", "plan.md", "tasks.md", "targets.yml")
_RETARGET_CONTEXT_FILE_CAP = 256 * 1024
_RETARGET_CONTEXT_TOTAL_CAP = 768 * 1024


def checkpoint_artifact_bytes(project_root: Path, commit: str, spec_id: str, name: str) -> bytes:
    result = run_git(project_root, "show", f"{commit}:specs/{spec_id}/{name}", check=False)
    if result.returncode != 0:
        return b""
    data = result.stdout.encode("utf-8")
    if len(data) > _RETARGET_CONTEXT_FILE_CAP:
        raise RetargetError(f"checkpoint context file exceeds cap: {name}")
    return data
```

Write files under `runs/<replacement>/context/retarget-baseline/` with an exact path/hash manifest and a banner stating `NON-AUTHORITATIVE RETARGET COVERAGE CONTEXT`. Enforce the total cap before writing any context file.

- [ ] **Step 8: Dispatch the prepared replacement through normal Phase A**

After `prepare_spec_retarget` returns an applied result, `_cmd_spec_retarget` calls `_cmd_run` with the preserved prompt and explicit flags:

```python
run_args = [result.original_user_message, "--mode", result.autonomy_mode]
for target in result.replacement_targets:
    run_args.extend(("--target", target))
for source in result.explicit_re_sources:
    run_args.extend(("--re-source", source))
if result.ignore_re:
    run_args.append("--ignore-re")
_cmd_run(run_args, project_root=project_root, ext_dir=ext_dir)
```

- [ ] **Step 9: Run CLI/coordinator tests**

Run: `pytest -q tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py tests/unit/test_spec_retarget.py`

Expected: preview, confirmation, rejection, destructive failure, retry, and same-run dispatch tests pass.

- [ ] **Step 10: Commit the destructive command**

```bash
git add src/echelon/spec_retarget.py src/echelon/spec_retarget_cli.py src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py
git commit -m "feat: add destructive spec retarget command"
```

---

### Task 8: Controller-Owned Retarget Finalization and Readiness

**Files:**
- Create: `src/echelon/spec_retarget_finalization.py`
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/phase_a_readiness.py`
- Modify: `src/harness/run_history.py`
- Modify: `templates/state-schema.json`
- Modify: `templates/run-history-schema.json`
- Create: `tests/unit/test_spec_retarget_finalization.py`
- Modify: `tests/unit/test_squad_completion.py`
- Modify: `tests/unit/test_phase_a_readiness.py`
- Modify: `tests/unit/test_run_history.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: controller completion effect/receipt machinery, staged Phase A publication, replacement memory/graph helpers, and retarget history.
- Produces: completion effect `retarget`, `apply_or_verify_retarget_finalization(...) -> dict[str, object]`, retarget-aware readiness, optional Phase A history fields, and one Git completion commit.

- [ ] **Step 1: Write failing readiness interlock tests**

```python
def test_active_retarget_blocks_public_readiness(ready_state: dict, ready_spec_dir: Path) -> None:
    ready_state["retarget"] = {
        "revision_id": "rt-1",
        "status": "finalizing",
        "replacement_targets": ["apps/web"],
    }
    result = validate_phase_a_readiness(ready_state, [ready_spec_dir])
    assert result.ready is False
    assert "retarget revision rt-1 is finalizing" in result.blockers


def test_controller_staging_can_validate_artifacts_before_retarget_effect(ready_state: dict, ready_spec_dir: Path) -> None:
    ready_state["retarget"] = {
        "revision_id": "rt-1",
        "status": "finalizing",
        "replacement_targets": ["apps/web"],
    }
    result = validate_phase_a_readiness(
        ready_state,
        [ready_spec_dir],
        allow_pending_retarget_finalization=True,
    )
    assert result.ready is True


def test_retarget_readiness_requires_replacement_targets_and_one_target_per_task(ready_state: dict, ready_spec_dir: Path) -> None:
    ready_state["implementation_targets"] = ["apps/web"]
    ready_state["retarget"] = {
        "revision_id": "rt-1",
        "status": "complete",
        "replacement_targets": ["apps/web"],
    }
    (ready_spec_dir / "targets.yml").write_text("targets:\n  - services/api\n")
    (ready_spec_dir / "tasks.md").write_text("- [ ] T001 [target:apps/web] [target:services/api] Build UI\n")
    result = validate_phase_a_readiness(ready_state, [ready_spec_dir])
    assert result.ready is False
    assert any("replacement target" in blocker for blocker in result.blockers)
    assert any("exactly one target" in blocker for blocker in result.blockers)
```

- [ ] **Step 2: Implement the explicit internal readiness bypass**

```python
def validate_phase_a_readiness(
    state: dict[str, object],
    candidate_dirs: list[Path],
    *,
    allow_pending_retarget_finalization: bool = False,
) -> PhaseAReadinessResult:
    retarget = state.get("retarget")
    if isinstance(retarget, Mapping):
        status = str(retarget.get("status") or "")
        if status not in {"complete", "recovered"} and not (
            allow_pending_retarget_finalization and status == "finalizing"
        ):
            return PhaseAReadinessResult(
                ready=False,
                blockers=[f"retarget revision {retarget.get('revision_id')} is {status}"],
                missing={},
                ready_spec_dir=None,
            )
    return _validate_phase_a_artifacts(state, candidate_dirs)
```

Only `_stage_phase_a_effects` passes `allow_pending_retarget_finalization=True`. Terminal/public readiness and every delivery entry use the default.
For a retarget state, also require authoritative `targets.yml` to equal both
`implementation_targets` and `retarget.replacement_targets`, and use
`analyze_task_targets` to require exactly one declared replacement target on
every canonical task.

- [ ] **Step 3: Write failing completion-plan tests**

```python
def test_phase_a_retarget_completion_orders_retarget_after_mining(retarget_controller: SquadController) -> None:
    prepared = retarget_controller.prepare_terminal_completion_for_test()
    assert prepared.intent.effect_plan[-2:] == ("mining", "retarget")


def test_retarget_finalization_resume_adopts_existing_receipts(retarget_controller: SquadController, fault_hook: FaultHook) -> None:
    fault_hook.raise_once("after_retarget_memory")
    first = retarget_controller.run(user_message="Build account search", mode="semi")
    assert first.status == "blocked"
    revision_id = active_state(retarget_controller)["retarget"]["revision_id"]
    second = retarget_controller.run(user_message="Build account search", mode="semi")
    assert second.status == "done"
    assert active_state(retarget_controller)["retarget"]["revision_id"] == revision_id
    assert len(load_retarget_history(retarget_controller.spec_dir).revisions) == 1


def test_phase4_publication_durably_enters_finalizing_before_staged_readiness(retarget_controller: SquadController) -> None:
    retarget_controller.prepare_phase4_publication_for_test()
    state = retarget_controller.state_store.load()
    revision = load_retarget_history(retarget_controller.spec_dir).revisions[-1]
    assert state["retarget"]["status"] == "finalizing"
    assert revision.status == "finalizing"
```

- [ ] **Step 4: Extend the sealed effect order and receipt validation**

```python
_EFFECT_ORDER = ("journal", "timing", "checkpoint", "context", "mining", "retarget")
```

Add a bounded retarget receipt validator requiring revision ID, checkpoint commit, replacement targets, memory receipt digest, spec/workspace graph hashes/statuses, completion commit, and status `complete`. `persist_completion_effect_receipt` remains the sole writer to the prepared completion stage.

- [ ] **Step 5: Add the retarget effect only for an active replacement run**

```python
if from_phase == "phase4-document" and _active_retarget(snapshot.state):
    effects.append("retarget")
```

For terminal reconciliation, use `("mining", "retarget")` when `state.retarget.status == "finalizing"`; do not add the effect to ordinary Phase A runs or recovered baseline runs.

Before `_prepare_external_phase_effects` stages `phase4-document`, atomically
advance the matching state and canonical revision from `rebuilding` to
`finalizing`, then capture the routing snapshot. If publication staging fails,
leave the revision `finalizing` and the spec blocked so terminal reconciliation
can replay the same revision; do not move it back to `rebuilding`.

- [ ] **Step 6: Implement idempotent finalization and the exact completion commit**

```python
def apply_or_verify_retarget_finalization(
    prepared: PreparedControllerCompletion,
    *,
    project_root: Path,
    state: Mapping[str, object],
    expected_receipt: object,
) -> dict[str, object]:
    if expected_receipt is not None:
        return verify_retarget_finalization_receipt(project_root, state, expected_receipt)
    retarget = require_finalizing_retarget(state)
    spec_dir = resolve_published_retarget_spec_dir(project_root, state)
    memory = refresh_retarget_spec_memory(project_root, spec_dir)
    persist_retarget_effect_progress(prepared, "memory", memory.to_dict())
    graph = finalize_retarget_graphs(project_root, spec_dir, graph_baseline(retarget))
    persist_retarget_effect_progress(prepared, "graph", graph.to_dict())
    revision = advance_retarget_revision(
        spec_dir,
        str(retarget["revision_id"]),
        expected_status="finalizing",
        status="complete",
        updates=final_revision_updates(memory, graph),
    )
    commit = commit_retarget_completion(project_root, spec_dir, revision)
    receipt = finalization_receipt(revision, memory, graph, commit)
    persist_completion_effect_receipt(prepared, "retarget", receipt)
    return receipt
```

Progress receipts are completion-stage files keyed by the sealed completion ID, not mutable ad-hoc state. Replay verifies existing memory drawer IDs/digests, graph bytes/audits, history status, and Git commit before adopting them. The commit stages `specs/<id>/` only and includes Echelon action `retarget-complete`, checkpoint, revision, baseline run, and replacement run trailers.

- [ ] **Step 7: Advance active state only after the effect receipt is durable**

When `complete_controller_completion` consumes a terminal completion whose effect plan contains `retarget`, copy the validated receipt identity into `state.retarget.finalization_receipt`, set `state.retarget.status = "complete"`, clear the memory exclusion marker, and only then remove the pending completion marker. The terminal inventory digest must include final retarget files.

- [ ] **Step 8: Extend Phase A run history without changing Phase B entries**

```python
def append_phase_a_run(
    spec_dir: Path,
    *,
    run_id: str,
    spec_status: str,
    constitution_hash: str,
    retarget_revision: str | None = None,
    supersedes_run_id: str | None = None,
    baseline_checkpoint: str | None = None,
) -> None:
    entry = phase_a_entry(run_id, spec_status, constitution_hash)
    if retarget_revision is not None:
        entry.update(
            retarget_revision=retarget_revision,
            supersedes_run_id=supersedes_run_id,
            baseline_checkpoint=baseline_checkpoint,
        )
    upsert_phase_a_entry(spec_dir, entry)
```

Update JSON Schema so these three fields are optional together on Phase A entries. Add `retarget` state schema fields with bounded IDs, status enum `checkpointed|invalidating|rebuilding|finalizing|complete|failed|recovered`, target arrays, commits, receipts, and failure code. Preserve compatibility for states without `retarget`.

- [ ] **Step 9: Print the authoritative comparison command on success**

After the controller returns a completed retarget, print:

```python
print(
    f"Compare old and replacement artifacts:\n"
    f"  git diff {retarget['checkpoint_commit']}..{retarget['replacement_commit']} "
    f"-- specs/{state['spec_id']}"
)
```

- [ ] **Step 10: Run completion, readiness, state, history, and controller tests**

Run: `pytest -q tests/unit/test_spec_retarget_finalization.py tests/unit/test_squad_completion.py tests/unit/test_phase_a_readiness.py tests/unit/test_run_history.py tests/integration/test_squad_controller.py tests/echelon-validation/test_spec_completion.py tests/echelon-validation/test_run_continuity.py`

Expected: retarget effects replay exactly, public readiness remains blocked until completion, and ordinary Phase A completion is unchanged.

- [ ] **Step 11: Commit controller finalization**

```bash
git add src/echelon/spec_retarget_finalization.py src/harness/squad_completion.py src/harness/squad.py src/harness/squad_state.py src/harness/phase_a_readiness.py src/harness/run_history.py templates/state-schema.json templates/run-history-schema.json tests/unit/test_spec_retarget_finalization.py tests/unit/test_squad_completion.py tests/unit/test_phase_a_readiness.py tests/unit/test_run_history.py tests/integration/test_squad_controller.py
git commit -m "feat: finalize retargets through squad completion"
```

---

### Task 9: Checkpoint-Only Retarget Recovery

**Files:**
- Create: `src/echelon/spec_retarget_recovery.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/spec_lifecycle.py`
- Create: `tests/unit/test_spec_retarget_recovery.py`
- Modify: `tests/unit/test_cli_rewind.py`

**Interfaces:**
- Consumes: `PhaseCheckpoint.source == "retarget-preflight"`, checkpoint Git reset/backup result, committed recovery projection, baseline/replacement run directories, memory purge/refresh, graph finalization, and retarget history transitions.
- Produces: `RetargetRecoveryResult` and `recover_retarget_checkpoint(project_root: Path, checkpoint: PhaseCheckpoint, replacement_state: Mapping[str, object]) -> RetargetRecoveryResult`.

- [ ] **Step 1: Write failing recovery tests with and without runtime cache**

```python
def test_retarget_checkpoint_recovery_restores_baseline_state_memory_and_graphs(failed_retarget_repo: FailedRetargetRepo) -> None:
    result = run_cli(
        failed_retarget_repo.root,
        "spec",
        "rewind",
        f"checkpoint:{failed_retarget_repo.checkpoint.id}",
        "--confirm",
    )
    state = active_state(failed_retarget_repo.root)
    revision = load_retarget_history(failed_retarget_repo.spec_dir).revisions[-1]
    assert result.exit_code == 0
    assert state["run_id"] == "squad-base"
    assert state["implementation_targets"] == ["services/api"]
    assert state["status"] == "done"
    assert revision.status == "recovered"
    assert revision.recovery_commit == git(failed_retarget_repo.root, "rev-parse", "HEAD")
    assert (failed_retarget_repo.spec_dir / "spec-artifact-graph.json").is_file()


def test_recovery_uses_committed_projection_after_runtime_cache_loss(failed_retarget_repo: FailedRetargetRepo) -> None:
    shutil.rmtree(failed_retarget_repo.root / ".echelon/runtime/retarget", ignore_errors=True)
    (failed_retarget_repo.root / "runs/squad-base/state.json").unlink()
    result = run_cli(failed_retarget_repo.root, "spec", "rewind", f"checkpoint:{failed_retarget_repo.checkpoint.id}", "--confirm")
    assert result.exit_code == 0
    assert active_state(failed_retarget_repo.root)["completed_phases"] == [
        "phase1-requirements",
        "phase3-plan",
        "phase4-document",
    ]
```

- [ ] **Step 2: Run recovery tests and confirm the module is absent**

Run: `pytest -q tests/unit/test_spec_retarget_recovery.py`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Add same-branch baseline pointer restoration**

```python
class RetargetRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetargetRecoveryResult:
    baseline_run_id: str
    revision_id: str
    recovery_commit: str
    memory: RetargetMemoryReceipt
    graph: RetargetGraphReceipt


def activate_recovered_spec_run(
    project_root: Path,
    baseline: SpecRun,
    replacement: SpecRun,
    *,
    operation_id: str,
) -> SpecRun:
    observed = current_branch(project_root)
    begin_spec_switch(
        project_root,
        replacement,
        baseline,
        observed_branch=observed,
        operation_id=operation_id,
    )
    mark_spec_switch_checked_out(project_root, operation_id, observed_branch=observed)
    return commit_spec_switch_pointer(project_root, operation_id, observed_branch=observed)
```

- [ ] **Step 4: Implement memory-first recovery finalization**

```python
def recover_retarget_checkpoint(
    project_root: Path,
    checkpoint: PhaseCheckpoint,
    replacement_state: Mapping[str, object],
) -> RetargetRecoveryResult:
    spec_dir = resolve_retarget_spec_dir(project_root, checkpoint.spec_id)
    revision = load_retarget_history(spec_dir).revisions[-1]
    projection = revision.recovery
    baseline = restore_or_recreate_baseline_state(project_root, projection, revision)
    replacement = resolve_spec_run(project_root, str(replacement_state["run_id"]))
    activate_recovered_spec_run(project_root, baseline, replacement, operation_id=f"recover-{revision.operation_id}")
    purge_retarget_spec_memory(project_root, checkpoint.spec_id)
    memory = refresh_retarget_spec_memory(project_root, spec_dir)
    if revision.graph_invalidation is None:
        raise RetargetRecoveryError("checkpoint revision lacks graph baseline")
    graph = finalize_retarget_graphs(
        project_root,
        spec_dir,
        RetargetGraphReceipt.from_dict(revision.graph_invalidation),
    )
    recovered = advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="failed",
        status="recovered",
        updates=recovery_updates(memory, graph),
    )
    commit = commit_retarget_recovery(project_root, spec_dir, recovered)
    persist_recovered_baseline_state(baseline.run_dir, projection, revision, commit)
    return RetargetRecoveryResult(baseline.run_id, revision.revision_id, commit, memory, graph)
```

Allow recovery from any non-terminal destructive status by first advancing it to `failed` with a bounded recovery reason. A failed memory or graph recovery leaves the baseline state blocked with `retarget_recovery_refresh_failed`; rerunning the same rewind resumes the same revision and never creates another recovery commit.

- [ ] **Step 5: Route retarget checkpoints before generic rewind state cleanup**

In `_cmd_rewind`, capture replacement state before `prepare_rewind`. After Git reset and retained-ledger write:

```python
if checkpoint.source == "retarget-preflight":
    recovery = recover_retarget_checkpoint(project_root, checkpoint, state)
    removed = ()
else:
    removed = _cleanup_rewind_outputs(spec_dir, checkpoint.phase, squad_dir)
    rewound = _reset_rewind_state(
        state,
        checkpoint.phase,
        spec_dir_ref,
        checkpoint_phases_before_target=checkpoint_phases_before_target,
    )
    store.save(rewound)
```

Hold `SpecMutationLock`, `PhaseAExecutionLock`, and replacement `SpecRunExecutionLock` for the complete rewind/reset/recovery transaction.

- [ ] **Step 6: Create and verify the recovery commit**

The recovery commit stages only `specs/<id>/` and uses Echelon action `retarget-recovered`, checkpoint, revision, baseline run, and replacement run trailers. Before treating an existing commit as replay success, verify its tree contains `retarget-history.json` with the same recovered revision and hashes.

- [ ] **Step 7: Run rewind and recovery tests**

Run: `pytest -q tests/unit/test_spec_retarget_recovery.py tests/unit/test_cli_rewind.py tests/unit/test_spec_switch.py tests/unit/test_spec_lifecycle.py`

Expected: ordinary rewind remains unchanged; retarget rewind restores baseline state even after runtime-cache loss.

- [ ] **Step 8: Commit checkpoint recovery**

```bash
git add src/echelon/spec_retarget_recovery.py src/echelon/cli.py src/echelon/spec_lifecycle.py tests/unit/test_spec_retarget_recovery.py tests/unit/test_cli_rewind.py
git commit -m "feat: recover retargets from checkpoints"
```

---

### Task 10: End-to-End Contracts, Documentation, and Full Verification

**Files:**
- Create: `tests/integration/test_spec_retarget_workflow.py`
- Modify: `tests/contract/static_contracts.py`
- Modify: `README.md`
- Modify: `docs/workspace-model.md`
- Modify: command/lifecycle documentation discovered by `tests/contract/static_contracts.py`

**Interfaces:**
- Consumes: complete command, state/history schemas, checkpoint recovery, MemPalace and graph test fakes, and real temporary Git repositories.
- Produces: executable lifecycle coverage, installed-surface contracts, and operator documentation.

- [ ] **Step 1: Add the ready-to-build replacement integration test**

```python
def test_ready_spec_retargets_in_place_and_records_old_to_new_diff(retarget_workspace: RetargetWorkspace) -> None:
    baseline_spec_id = retarget_workspace.spec_id
    outcome = retarget_workspace.run_retarget(("apps/web",))
    state = retarget_workspace.active_state()
    history = load_retarget_history(retarget_workspace.spec_dir)
    assert outcome.exit_code == 0
    assert state["spec_id"] == baseline_spec_id
    assert state["retarget"]["status"] == "complete"
    assert state["implementation_targets"] == ["apps/web"]
    assert history.revisions[-1].replacement_commit == retarget_workspace.git_head()
    assert retarget_workspace.git_diff_names(
        history.revisions[-1].checkpoint_commit,
        history.revisions[-1].replacement_commit,
        f"specs/{baseline_spec_id}",
    ) >= {"spec.md", "plan.md", "tasks.md", "targets.yml", "retarget-history.json"}
```

- [ ] **Step 2: Add the failure/recovery and safety integration matrix**

```python
@pytest.mark.parametrize(
    "delivery_evidence",
    ("phase_b_history", "build_state", "completed_task", "verification_artifact"),
)
def test_any_delivery_evidence_rejects_retarget(retarget_workspace: RetargetWorkspace, delivery_evidence: str) -> None:
    retarget_workspace.add_delivery_evidence(delivery_evidence)
    before = retarget_workspace.snapshot()
    outcome = retarget_workspace.preview_retarget(("apps/web",))
    assert outcome.exit_code == 1
    assert "create a new spec" in outcome.stderr.lower()
    assert retarget_workspace.snapshot() == before


def test_failed_retarget_recovers_only_through_checkpoint(retarget_workspace: RetargetWorkspace) -> None:
    failed = retarget_workspace.run_retarget(("apps/web",), fail_after="artifact_invalidation")
    assert failed.exit_code == 1
    assert retarget_workspace.delivery_preflight().exit_code == 1
    recovered = retarget_workspace.rewind_printed_checkpoint(failed)
    assert recovered.exit_code == 0
    assert retarget_workspace.active_state()["implementation_targets"] == ["services/api"]


def test_retarget_preserves_unrelated_dirty_bytes_and_staging(retarget_workspace: RetargetWorkspace) -> None:
    dirty = retarget_workspace.root / "notes/private.txt"
    dirty.parent.mkdir()
    dirty.write_bytes(b"private\n")
    retarget_workspace.run_retarget(("apps/web",))
    assert dirty.read_bytes() == b"private\n"
    assert "notes/private.txt" not in retarget_workspace.git_staged_names()
```

Add these explicit cases to the same integration file:

```python
def test_pre_ready_spec_rebuilds_with_complete_multi_target_set(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.park_before_ready()
    outcome = retarget_workspace.run_retarget(("apps/web", "services/api"))
    assert outcome.exit_code == 0
    assert retarget_workspace.active_state()["implementation_targets"] == ["apps/web", "services/api"]


def test_owned_memory_is_absent_before_first_replacement_dispatch(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.run_retarget(("apps/web",), stop_before_first_dispatch=True)
    assert retarget_workspace.owned_memory_ids("001-demo") == ()


def test_invalidation_removes_old_graph_edges_and_single_spec_workspace_graph(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.run_retarget(("apps/web",), stop_after_invalidation=True)
    assert not (retarget_workspace.spec_dir / "spec-artifact-graph.json").exists()
    assert not workspace_graph_path(retarget_workspace.root).exists()


def test_finalization_crash_replays_one_revision(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.run_retarget(("apps/web",), crash_after="retarget_memory_receipt")
    resumed = retarget_workspace.continue_spec()
    assert resumed.exit_code == 0
    assert len(load_retarget_history(retarget_workspace.spec_dir).revisions) == 1


def test_active_branch_mismatch_is_read_only(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.checkout_default_branch()
    before = retarget_workspace.snapshot()
    result = retarget_workspace.preview_retarget(("apps/web",))
    assert result.exit_code == 1
    assert "echelon spec switch" in result.stderr
    assert retarget_workspace.snapshot() == before


def test_unrelated_workspace_warning_does_not_block_selected_spec(retarget_workspace: RetargetWorkspace) -> None:
    retarget_workspace.add_other_spec_warning("002-other")
    assert retarget_workspace.run_retarget(("apps/web",)).exit_code == 0


def test_drop_target_stays_available_for_unused_target(retarget_workspace: RetargetWorkspace) -> None:
    result = retarget_workspace.run_drop_target("unused")
    assert result.exit_code == 0
    assert len(load_retarget_history(retarget_workspace.spec_dir).revisions) == 0


def test_retarget_does_not_mutate_target_repositories(retarget_workspace: RetargetWorkspace) -> None:
    before = retarget_workspace.target_repository_snapshots()
    result = retarget_workspace.run_retarget(("apps/web", "services/api"))
    assert result.exit_code == 0
    assert retarget_workspace.target_repository_snapshots() == before
```

- [ ] **Step 3: Run integration tests and fix only evidenced failures**

Run: `pytest -q tests/integration/test_spec_retarget_workflow.py tests/integration/test_squad_controller.py tests/integration/test_spec_graph_workflow.py tests/integration/test_workspace_graph_workflow.py`

Expected: all retarget lifecycle and neighboring integration tests pass.

- [ ] **Step 4: Add installed CLI/schema contract assertions**

```python
def check_spec_retarget_contract(root: Path) -> None:
    cli_app = (root / "src/echelon/cli_app.py").read_text()
    legacy = (root / "src/echelon/cli.py").read_text()
    state_schema = json.loads((root / "templates/state-schema.json").read_text())
    history_schema = json.loads((root / "templates/run-history-schema.json").read_text())
    assert '@spec_app.command("retarget")' in cli_app
    assert "spec retarget <spec-id> --target" in legacy
    assert "retarget" in state_schema["properties"]
    phase_a = history_schema["properties"]["runs"]["items"]["properties"]
    assert {"retarget_revision", "supersedes_run_id", "baseline_checkpoint"} <= set(phase_a)
```

Wire this check into the existing static contract runner and test both Typer and legacy help output.

- [ ] **Step 5: Document the destructive lifecycle and recovery command**

Add this operator example to README and the workspace model:

```markdown
Preview the complete target replacement first:

    echelon spec retarget 001-demo --target apps/web

Confirmation creates a mandatory Git checkpoint, removes the current Phase A
result from the buildable surface, purges spec-owned memory, and rebuilds the
spec on the same feature branch:

    echelon spec retarget 001-demo --target apps/web --confirm

Retarget is allowed only before delivery starts. After the checkpoint, the
only rollback is the exact command printed by Echelon:

    echelon spec rewind checkpoint:<retarget-checkpoint-id> --confirm

Use `echelon spec drop-target` only for an unused target that owns no task.
Adding or replacing targets requires `echelon spec retarget`.
```

Document that reverse engineering is not rerun, automatic RE source selection is recalculated, configured MemPalace is fail-closed, and the success banner prints the Git diff command.

- [ ] **Step 6: Run contract and focused regression suites**

Run: `pytest -q tests/contract tests/echelon-validation tests/unit/test_cli_spec_retarget.py tests/unit/test_spec_retarget.py tests/unit/test_spec_retarget_history.py tests/unit/test_spec_retarget_recovery.py tests/unit/test_mempalace_retarget.py tests/unit/test_spec_retarget_graph.py`

Expected: all commands exit zero.

- [ ] **Step 7: Run the complete repository verification**

Run: `pytest -q`

Expected: the complete test suite passes. If environment-dependent E2E tests are skipped by their existing markers, record their exact skip reasons; do not convert failures into skips.

- [ ] **Step 8: Inspect final scope and whitespace**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; only intentional retarget changes and the user's preserved pre-existing dirty files are present.

- [ ] **Step 9: Commit contracts and documentation**

```bash
git add tests/integration/test_spec_retarget_workflow.py tests/contract/static_contracts.py README.md docs/workspace-model.md
git add -p
git commit -m "docs: document destructive spec retarget"
```

- [ ] **Step 10: Record final verification evidence**

Run: `git log --oneline --decorate -12`

Run: `git status --short`

Expected: the retarget commits are present in task order, the implementation worktree has no newly introduced unstaged retarget changes, and all pre-existing unrelated modifications remain preserved.
