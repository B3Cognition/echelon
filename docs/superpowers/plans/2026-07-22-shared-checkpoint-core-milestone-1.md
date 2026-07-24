# Shared Checkpoint Core Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract Phase A checkpoint mechanics into a reusable checkpoint core and Spec adapter without changing any observable `echelon spec checkpoint` or `echelon spec rewind` behavior.

**Architecture:** New `harness.checkpoints` modules own immutable models, ledger operations, Git storage, and adapter policy. `harness.phase_checkpoints` remains a compatibility façade exporting the exact current API and delegates Spec behavior through `SpecCheckpointAdapter`; RE and Delivery runtime behavior remain untouched.

**Tech Stack:** Python 3.11, dataclasses, pathlib, JSON, Git subprocess helpers, pytest.

## Global Constraints

- Existing Spec checkpoint and rewind behavior is the compatibility oracle.
- Do not change existing ledger JSON shape or path.
- Do not change dataclass field order or equality.
- Do not change public names or call signatures in `harness.phase_checkpoints`.
- Do not change checkpoint commit subjects or Echelon trailers.
- Do not consume unrelated staged, unstaged, or untracked files.
- Do not change RE or Delivery runtime behavior in this milestone.
- Existing expected-output fixtures remain unchanged.
- Work in an isolated worktree because `main` contains unrelated uncommitted changes.

---

### Task 1: Freeze the public compatibility surface

**Files:**
- Modify: `tests/unit/test_phase_checkpoints.py`
- Modify: `tests/unit/test_cli_checkpoint.py`
- Modify: `tests/unit/test_rewind.py`
- Modify: `tests/unit/test_spec_switch.py`

**Interfaces:**
- Consumes: current `harness.phase_checkpoints`, checkpoint CLI, rewind, and Spec-switch behavior.
- Produces: characterization tests that remain unchanged during extraction.

- [ ] **Step 1: Add a public symbol/signature characterization test**

Add a test that imports the public module and verifies the required exports and signatures:

```python
def test_phase_checkpoint_public_api_is_stable() -> None:
    import inspect
    import harness.phase_checkpoints as api

    expected = {
        "PhaseCheckpoint",
        "CheckpointLedger",
        "PhaseCheckpointError",
        "CHECKPOINT_LEDGER_REL",
        "checkpoint_ledger_path",
        "load_checkpoint_ledger",
        "write_checkpoint_ledger",
        "record_phase_checkpoint",
        "record_checkpoint_metadata",
        "resolve_checkpoint",
        "checkpoint_targets",
        "new_checkpoint_id",
        "create_phase_checkpoint",
        "accept_checkpoint_baseline",
        "commit_manual_checkpoint",
    }
    assert expected <= set(dir(api))
    assert list(inspect.signature(api.create_phase_checkpoint).parameters) == [
        "project_root", "spec_dir", "phase", "next_phase", "run_id",
        "spec_id", "additional_spec_dirs", "additional_owned_paths",
    ]
```

- [ ] **Step 2: Add model and JSON-shape characterization**

Construct a `PhaseCheckpoint`, assert `dataclasses.fields()` order, record it,
and assert the exact decoded JSON object:

```python
assert [field.name for field in fields(PhaseCheckpoint)] == [
    "id", "spec_id", "phase", "next_phase", "commit",
    "metadata_commit", "source", "run_id", "created_at",
]
assert json.loads(checkpoint_ledger_path(spec_dir).read_text()) == {
    "spec_id": "001-demo",
    "checkpoints": [asdict(checkpoint)],
}
```

- [ ] **Step 3: Characterize commit identity**

Extend the automatic-checkpoint test to assert the exact first subject and all
identity trailers:

```python
message = _git(repo, "show", "-s", "--format=%B", checkpoint.commit)
assert message.splitlines()[0] == "echelon-checkpoint: 001-demo phase3-plan"
for trailer in (
    "Echelon-Origin: phase-a",
    "Echelon-Action: checkpoint",
    "Echelon-Spec: 001-demo",
    "Echelon-Run: squad-1",
    "Echelon-Phase: phase3-plan",
    "Echelon-Checkpoint: phase3-plan",
):
    assert trailer in message
```

- [ ] **Step 4: Characterize CLI and rewind text**

Capture the existing checkpoint-list header and one rewind preview. Assert the
current strings exactly, including the backup-ref prefix and confirmation
command.

- [ ] **Step 5: Run characterization tests before production changes**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_rewind.py \
  tests/unit/test_spec_switch.py -q
```

Expected: PASS. If a new assertion exposes a mistaken assumption, correct the
test to the observed existing behavior before continuing; do not change
production code.

- [ ] **Step 6: Commit characterization tests**

```bash
git add tests/unit/test_phase_checkpoints.py tests/unit/test_cli_checkpoint.py tests/unit/test_rewind.py tests/unit/test_spec_switch.py
git commit -m "test: freeze spec checkpoint compatibility"
```

---

### Task 2: Extract immutable models and ledger operations

**Files:**
- Create: `src/harness/checkpoints/__init__.py`
- Create: `src/harness/checkpoints/model.py`
- Create: `src/harness/checkpoints/ledger.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Produces: `PhaseCheckpoint`, `CheckpointLedger`, and generic ledger functions.
- Preserves: all corresponding imports through `harness.phase_checkpoints`.

- [ ] **Step 1: Write a failing façade-identity test**

```python
def test_phase_checkpoint_facade_reexports_core_models() -> None:
    from harness.checkpoints.model import CheckpointLedger as CoreLedger
    from harness.checkpoints.model import PhaseCheckpoint as CoreCheckpoint
    from harness.phase_checkpoints import CheckpointLedger, PhaseCheckpoint

    assert PhaseCheckpoint is CoreCheckpoint
    assert CheckpointLedger is CoreLedger
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/unit/test_phase_checkpoints.py::test_phase_checkpoint_facade_reexports_core_models -q`

Expected: FAIL because `harness.checkpoints.model` does not exist.

- [ ] **Step 3: Create the model module**

Move the existing dataclasses without alteration:

```python
@dataclass(frozen=True)
class PhaseCheckpoint:
    id: str
    spec_id: str
    phase: str
    next_phase: str
    commit: str
    metadata_commit: str
    source: str
    run_id: str
    created_at: str

@dataclass(frozen=True)
class CheckpointLedger:
    spec_id: str
    checkpoints: list[PhaseCheckpoint]
```

- [ ] **Step 4: Create generic ledger functions**

Move JSON load/write, record, resolve, target listing, and ID generation into
`ledger.py`. Parameterize the ledger path and expected Spec identity where
necessary; do not embed workflow-specific owned-path logic.

- [ ] **Step 5: Re-export models and wrap ledger behavior**

`phase_checkpoints.py` imports the core models and delegates its existing
functions while preserving exact signatures and exceptions.

- [ ] **Step 6: Run checkpoint, CLI, rewind, and Spec-switch tests**

Run the four-file command from Task 1.

Expected: PASS without changing expected fixtures.

- [ ] **Step 7: Commit model and ledger extraction**

```bash
git add src/harness/checkpoints src/harness/phase_checkpoints.py tests/unit/test_phase_checkpoints.py
git commit -m "refactor: extract checkpoint models and ledger"
```

---

### Task 3: Extract owned-path Git storage

**Files:**
- Create: `src/harness/checkpoints/git_store.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Produces: `OwnedPaths`, `commit_owned_changes()`, `current_head()`, and `require_clean_baseline()`.
- Consumes: explicit owned directories/files and the existing `run_git()` helper.

- [ ] **Step 1: Write failing direct Git-store isolation tests**

Test the new API directly with one owned Spec directory, one unrelated staged
file, one unrelated unstaged file, and one untracked file:

```python
owned = OwnedPaths(
    directories=(spec_dir,),
    files=(),
    excluded_relative_paths=(Path(".echelon/checkpoints.json"),),
)
commit = commit_owned_changes(repo, owned, "checkpoint")
assert _git(repo, "show", "--format=", "--name-only", commit) == "specs/001/tasks.md"
assert _git(repo, "diff", "--cached", "--name-only") == "src/staged.txt"
```

- [ ] **Step 2: Run the direct test and verify RED**

Expected: import failure because `git_store.py` does not exist.

- [ ] **Step 3: Implement the Git-store primitives**

```python
@dataclass(frozen=True)
class OwnedPaths:
    directories: tuple[Path, ...] = ()
    files: tuple[Path, ...] = ()
    excluded_relative_paths: tuple[Path, ...] = ()

def commit_owned_changes(
    project_root: Path,
    owned: OwnedPaths,
    message: str,
) -> str | None: ...

def current_head(project_root: Path) -> str: ...

def require_clean_baseline(project_root: Path) -> None: ...
```

Preserve the existing use of `git add -f -A`, `git diff --cached --quiet`, and
`git commit --only` with explicit pathspecs.

- [ ] **Step 4: Route existing private Git helpers through the store**

Keep `_owned_pathspecs()`, `_commit_spec_changes()`, and
`_has_staged_or_unstaged_changes()` as façade-private wrappers if tests or
downstream imports rely on them; otherwise remove them only after repository
search proves they are internal.

- [ ] **Step 5: Run isolation and compatibility suites**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_rewind.py \
  tests/unit/test_spec_switch.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Git-store extraction**

```bash
git add src/harness/checkpoints/git_store.py src/harness/phase_checkpoints.py tests/unit/test_phase_checkpoints.py
git commit -m "refactor: extract checkpoint git storage"
```

---

### Task 4: Add the adapter boundary and Spec adapter

**Files:**
- Create: `src/harness/checkpoints/adapter.py`
- Create: `src/harness/checkpoints/adapters/__init__.py`
- Create: `src/harness/checkpoints/adapters/spec.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Produces: `CheckpointContext`, `CheckpointAdapter`, and `SpecCheckpointAdapter`.
- Preserves: current automatic, accepted, and manual Spec checkpoint API.

- [ ] **Step 1: Write failing Spec-adapter policy tests**

```python
def test_spec_adapter_preserves_ledger_and_origin_policy(tmp_path: Path) -> None:
    adapter = SpecCheckpointAdapter()
    context = CheckpointContext(
        project_root=tmp_path,
        spec_dir=tmp_path / "specs/001-demo",
        spec_id="001-demo",
        run_id="run-1",
    )
    assert adapter.ledger_path(context) == context.spec_dir / ".echelon/checkpoints.json"
    assert adapter.commit_origin() == "phase-a"
```

Add tests for normal Spec-ID validation, the existing staging/external exception,
active/published Spec ownership, and accepted KB file ownership.

- [ ] **Step 2: Run adapter tests and verify RED**

Expected: import failure because adapter modules do not exist.

- [ ] **Step 3: Implement the protocol and context**

```python
@dataclass(frozen=True)
class CheckpointContext:
    project_root: Path
    spec_dir: Path
    spec_id: str
    run_id: str
    additional_spec_dirs: tuple[Path, ...] = ()
    additional_owned_paths: tuple[Path, ...] = ()

class CheckpointAdapter(Protocol):
    def ledger_path(self, context: CheckpointContext) -> Path: ...
    def owned_paths(self, context: CheckpointContext) -> OwnedPaths: ...
    def validate(self, context: CheckpointContext) -> None: ...
    def commit_origin(self) -> str: ...
```

- [ ] **Step 4: Implement Spec policy without behavior changes**

Move only Spec-specific path selection and identity validation into
`SpecCheckpointAdapter`. Keep commit-message construction in the façade until
the adapter is proven by tests, then use `adapter.commit_origin()` in the
existing metadata construction.

- [ ] **Step 5: Route all Spec creation paths through the adapter**

Update `create_phase_checkpoint()`, `accept_checkpoint_baseline()`, and
`commit_manual_checkpoint()` to instantiate a Spec context and adapter. Keep
their signatures, error types, IDs, subjects, and trailers unchanged.

- [ ] **Step 6: Run all Spec checkpoint consumers**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_rewind.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_spec_switch.py \
  tests/unit/test_cli_spec_switch.py \
  tests/unit/test_spec_switch_cli.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/integration/test_squad_controller.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the Spec adapter**

```bash
git add src/harness/checkpoints src/harness/phase_checkpoints.py tests/unit/test_phase_checkpoints.py
git commit -m "refactor: route spec checkpoints through adapter"
```

---

### Task 5: Compatibility and full verification

**Files:**
- Modify only if test evidence requires a compatibility correction: files from Tasks 1–4.

**Interfaces:**
- Consumes: extracted core, façade, and Spec adapter.
- Produces: evidence that the extraction is behavior-preserving.

- [ ] **Step 1: Verify the façade module contains no duplicated policy**

Use `rg` and review to confirm model definitions, JSON algorithms, and raw Git
pathspec construction live in the new core. The façade may retain compatibility
constants, wrappers, message construction, and public orchestration functions.

- [ ] **Step 2: Run the complete checkpoint compatibility matrix**

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_rewind.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_spec_switch.py \
  tests/unit/test_cli_spec_switch.py \
  tests/unit/test_spec_switch_cli.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/integration/test_squad_controller.py -q
```

Expected: PASS with zero fixture modifications.

- [ ] **Step 3: Run the full unit suite**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -m unit -q`

Expected: PASS.

- [ ] **Step 4: Run workflow wiring validation**

Run: `bash scripts/bash/dry-run.sh`

Expected: zero failures.

- [ ] **Step 5: Verify no RE or Delivery files changed**

Run:

```bash
git diff --name-only "$(git merge-base HEAD main)"..HEAD
```

Expected: only checkpoint-core, façade, characterization-test, design, and plan
paths; no `re_controller.py`, `ralph.py`, `recovery.py`, or RE/Delivery workflow
files.

- [ ] **Step 6: Verify diff hygiene**

Run: `git diff --check "$(git merge-base HEAD main)"..HEAD` and `git status --short`.

Expected: no whitespace errors and no uncommitted task-owned paths.
