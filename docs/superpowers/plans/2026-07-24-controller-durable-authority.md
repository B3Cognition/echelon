# Controller Durable Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require file-and-parent durability proof before controller state or phase-timing bytes authorize external effects, and reject active checkpoint preparation when Git `HEAD` is unavailable or invalid.

**Architecture:** `SquadStateStore` gains one exact under-lock durability confirmation primitive shared by save ambiguity, fresh recovery, and final cleanup. Phase timing keeps its existing API and locks but rewrites the complete validated JSONL stream atomically and confirms ambiguous tagged events against exact expected bytes. Checkpoint preparation removes the zero sentinel and fails before route authority is sealed.

**Tech Stack:** Python 3.11, `os`/`fcntl`/`tempfile`/`errno`/`json`, existing controller lock ranks and outboxes, pytest fault injection.

## Global Constraints

- Fsync retries only `EINTR`; every other file or directory error fails closed.
- File opens use `O_NOFOLLOW` where supported and require regular-file type.
- Directory opens use `O_DIRECTORY | O_NOFOLLOW` where supported and require directory type.
- Device/inode identity is checked before and after synchronization.
- A distinct post-replace parent-sync error is never converted into success by generic visible-postimage adoption in the same operation.
- Failed durable confirmation performs no diagnostic state write, external effect, marker advance, stage deletion, or orphan cleanup.
- Publication and completion stages are durably sealed before state can reference them.
- Telemetry preserves exact prior JSONL bytes and never truncates or repairs a malformed/torn tail.
- Active checkpoint preparation requires a lowercase 40- or 64-character Git commit ID; there is no all-zero sentinel.
- TDD RED evidence precedes every production edit.
- Each implementation task ends in a focused commit; no push or merge is permitted.

---

### Task 1: Exact Durable State Authority

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_state.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces:
  - `StateDurabilityError(StateAdvanceError)` with bounded `stage` in
    `{"directory_create", "pre_replace", "post_replace", "confirm"}`.
  - `_fsync_retry(descriptor: int) -> None`.
  - `_ensure_directory_durable(path: Path) -> None`.
  - `SquadStateStore.confirm_durable_state(expected: dict[str, Any]) -> dict[str, Any]`.
  - `SquadStateStore._confirm_durable_state_unlocked(expected: dict[str, Any]) -> dict[str, Any]`.
- Consumes: existing state lock, exact marker schemas, completion/publication stage load and discard APIs.

- [ ] **Step 1: Write directory and save-order RED tests**

Add tests that patch `os.fsync`, `os.replace`, and `os.open` without replacing
the real write. Record file descriptors and assert:

```python
def test_state_save_fsyncs_file_then_replaces_then_fsyncs_parent(tmp_path):
    store = SquadStateStore(tmp_path / "runs" / "r1")
    store.initialize("r1", "greenfield", "msg", 0, "init")
    calls = []
    real_fsync = os.fsync
    real_replace = os.replace

    def observed_fsync(fd):
        mode = os.fstat(fd).st_mode
        calls.append("dir_fsync" if stat.S_ISDIR(mode) else "file_fsync")
        return real_fsync(fd)

    def observed_replace(source, target):
        calls.append("replace")
        return real_replace(source, target)

    with patch("harness.squad_state.os.fsync", side_effect=observed_fsync), \
         patch("harness.squad_state.os.replace", side_effect=observed_replace):
        store.save(store.load())

    assert calls[-3:] == ["file_fsync", "replace", "dir_fsync"]
```

Cover initial `state.json` creation, replacement, nested squad-directory
creation, staging-directory creation, symlink/non-directory rejection, and
`EINTR` retry followed by success.

- [ ] **Step 2: Run the save-order tests and capture RED**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_squad_state.py \
  -k "state_save_fsyncs_file_then_replaces_then_fsyncs_parent or directory_creation_is_durable or fsync_retries_eintr"
```

Expected: failures show there is no parent-directory fsync, no durable
directory helper, and no `EINTR` retry.

- [ ] **Step 3: Implement durable directories and atomic save**

Add bounded durability errors and an `EINTR`-only fsync helper:

```python
class StateDurabilityError(StateAdvanceError):
    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(
            message,
            json_path="$.state",
            validator="durability",
        )
        self.stage = stage


def _fsync_retry(descriptor: int) -> None:
    while True:
        try:
            os.fsync(descriptor)
            return
        except OSError as exc:
            if exc.errno != errno.EINTR:
                raise
```

Create missing directory components individually, sync the new directory and
its parent, and revalidate the parent entry against the open descriptor. Change
`_save_unlocked()` to write and sync the sibling temp, call `os.replace()`, then
sync the squad directory. Raise `StateDurabilityError(stage="post_replace")`
when the final directory proof fails.

- [ ] **Step 4: Run save-order tests and capture GREEN**

Run the Step 2 command.

Expected: all selected tests pass.

- [ ] **Step 5: Write exact-confirmation and ambiguity RED tests**

Add tests for the wished-for public API:

```python
def test_confirm_durable_state_requires_exact_revision_and_marker(tmp_path):
    store = initialized_store(tmp_path)
    expected = store.load()
    assert store.confirm_durable_state(expected) == expected
    drifted = deepcopy(expected)
    drifted["state_revision"] += 1
    with pytest.raises(StateDurabilityError):
        store.confirm_durable_state(drifted)


def test_post_replace_parent_sync_failure_is_not_adopted(tmp_path):
    store = initialized_store(tmp_path)
    before = store.load()
    with fail_state_parent_fsync_once():
        with pytest.raises(StateDurabilityError) as raised:
            begin_bound_completion(store)
    assert raised.value.stage == "post_replace"
    assert no_effect_was_called()
    assert completion_stage_exists()
```

Cover:

- no-follow regular-file and directory type enforcement;
- identity change before and after fsync;
- content, marker, and revision mismatch;
- true outer save-then-raise after a fully successful save is adopted only
  after confirmation;
- internal `post_replace` failure is not adopted;
- old-state-survives outcome has no effects and a safe orphan;
- new-state-survives outcome retains the referenced stage for recovery.

- [ ] **Step 6: Run confirmation/ambiguity tests and capture RED**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_squad_state.py \
  -k "confirm_durable_state or post_replace_parent_sync or save_then_raise or power_loss"
```

Expected: confirmation API tests fail and existing save-then-raise adoption
does not perform a durability proof.

- [ ] **Step 7: Implement exact under-lock confirmation**

Implement `_confirm_durable_state_unlocked()` to:

```python
flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
state_fd = os.open(self._path, flags)
opened = os.fstat(state_fd)
named = os.lstat(self._path)
if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(named):
    raise StateDurabilityError("state identity changed", stage="confirm")
content = read_all_bounded(state_fd)
observed = json.loads(content)
if type(observed) is not dict or observed != expected:
    raise StateDurabilityError("state postimage changed", stage="confirm")
_fsync_retry(state_fd)
directory_fd = open_real_directory(self._squad_dir)
_fsync_retry(directory_fd)
revalidate_same_file_directory_bytes_and_state()
return deepcopy(observed)
```

The public method acquires the exclusive state lock. The routed-save ambiguity
handler and `_save_exact_completion_state_unlocked()` call the ordered helper
only for exceptions other than `StateDurabilityError(stage="post_replace")`.

- [ ] **Step 8: Write fresh-recovery and final-cleanup RED tests**

In controller integration tests, inject confirmation failure at each authority
boundary and assert:

```python
with patch.object(
    controller._state_store,
    "confirm_durable_state",
    side_effect=StateDurabilityError("injected", stage="confirm"),
):
    outcome = controller._drain_pending_controller_completion()

assert outcome.recovered is False
assert publication.publish.call_count == 0
assert effect.call_count == 0
assert state_path.read_bytes() == before_state
assert completion_stage.exists()
```

Cover pending external publication, pending completion, repeated failure, final
completion clear, final publication clear, and orphan cleanup. Model both
old/new power-loss states with fresh controller instances.

- [ ] **Step 9: Run recovery/cleanup tests and capture RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_state.py \
  -k "durable_authority or final_clear_stage or power_loss"
```

Expected: fresh recovery executes from a merely loaded marker and cleanup
deletes after a merely visible clear.

- [ ] **Step 10: Gate fresh authority and final cleanup**

At the entry of `_drain_pending_controller_completion()` and
`_recover_pending_external_publication()`, confirm the exact loaded state
before stage loading or effects. On failure, return without recording a
diagnostic.

Before publication/completion stage discard and orphan cleanup, confirm the
exact state snapshot that proves the marker is absent and the final receipt is
present. Confirmation failure retains the stage and returns a pending outcome.

- [ ] **Step 11: Run the complete state/controller focused suite**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_completion.py \
  tests/unit/test_controller_lock_order.py
```

Expected: all tests pass.

- [ ] **Step 12: Commit Task 1**

```bash
git add \
  src/harness/squad_state.py \
  src/harness/squad.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py
git commit -m "fix: require durable controller state authority"
```

---

### Task 2: Atomic Phase-Timing Stream

**Files:**
- Modify: `src/echelon/telemetry/store.py`
- Modify: `src/echelon/telemetry/phase_timing.py`
- Modify: `src/harness/squad_completion.py`
- Modify: `tests/unit/test_phase_timing_telemetry.py`
- Modify: `tests/unit/test_squad_completion.py`

**Interfaces:**
- Produces:
  - `TelemetryDurabilityError(RuntimeError)` with bounded stage.
  - `TelemetryStore.append_phase_timing(event) -> PhaseTimingEvent`.
  - `TelemetryStore.confirm_phase_timing_stream(expected: bytes) -> bytes`.
  - Internal exact JSONL validation and atomic rewrite helpers.
- Preserves: `record_phase_start()`, `record_phase_finish()`,
  `PhaseTimingEvent.to_json_dict()`, legacy untagged records, mixed-event rank
  order, and the existing phase-timing lock rank.

- [ ] **Step 1: Write atomic-rewrite RED tests**

Create exact prior bytes containing a non-timing event and a legacy timing
event. Record a tagged event and assert the new file begins byte-for-byte with
the original stream and ends with one canonical record. Patch calls to assert
file fsync, replace, then parent fsync.

Add pre-replace failure tests proving the old stream remains byte-identical and
no sibling temp remains.

- [ ] **Step 2: Run atomic-rewrite tests and capture RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase_timing_telemetry.py \
  -k "atomic_rewrite or preserves_exact_prior_bytes or pre_replace"
```

Expected: direct append does not call replace or parent fsync.

- [ ] **Step 3: Implement validated whole-stream rewrite**

Under `phase_timing_transaction()`:

```python
prior = self.events_path.read_bytes() if self.events_path.exists() else b""
validate_complete_jsonl(prior)
record = json.dumps(
    event.to_json_dict(),
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8") + b"\n"
expected = prior + record
atomic_replace_bytes(self.events_path, expected)
```

`validate_complete_jsonl()` rejects a non-newline terminated tail, invalid
JSON, non-object records, and invalid phase-timing objects. The sibling temp is
opened with exclusive/no-follow flags, fully written, fsynced, replaced, and
the telemetry directory is fsynced. First directory and file creation are
durably synchronized.

- [ ] **Step 4: Run atomic-rewrite tests and capture GREEN**

Run the Step 2 command.

Expected: all selected tests pass.

- [ ] **Step 5: Write ambiguity/fresh-retry RED tests**

Cover:

- a distinct post-replace parent-sync failure is not adopted;
- a true outer save-then-raise is adopted only after exact stream
  confirmation;
- confirmation checks no-follow file/directory type, identity, exact bytes,
  file fsync, and parent fsync;
- a fresh controller confirms an already visible tagged completion event
  before returning an idempotent timing receipt;
- repeated confirmation failure applies no new event and writes no repair;
- first-create parent failure;
- malformed middle record and torn final record remain unchanged and fail
  closed.

- [ ] **Step 6: Run ambiguity/retry tests and capture RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_phase_timing_telemetry.py \
  tests/unit/test_squad_completion.py \
  -k "timing and (durability or ambiguity or malformed or torn or fresh)"
```

Expected: visible tagged events are currently adopted without exact stream
durability confirmation.

- [ ] **Step 7: Implement exact stream confirmation and adoption**

`confirm_phase_timing_stream(expected)` runs under the telemetry transaction
lock, no-follow opens the stream, checks regular-file/path identity, reads
exact bytes, validates JSONL, fsyncs file and telemetry directory, revalidates
identity and bytes, and returns the confirmed bytes.

`record_phase_start()` and `record_phase_finish()` retain the exact expected
stream bytes from the transaction. If `append_phase_timing()` raises after a
fully successful rewrite, they may return the exact tagged event only after
confirmation proves those bytes. They never adopt the store's own
`post_replace` durability error.

Completion timing receipt validation uses the same confirmation before
adopting an existing effect-tagged event in a fresh controller.

- [ ] **Step 8: Run the complete telemetry/completion focused suite**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_phase_timing_telemetry.py \
  tests/unit/test_squad_completion.py \
  tests/unit/test_controller_lock_order.py
```

Expected: all tests pass with legacy serialization and rank order unchanged.

- [ ] **Step 9: Commit Task 2**

```bash
git add \
  src/echelon/telemetry/store.py \
  src/echelon/telemetry/phase_timing.py \
  src/harness/squad_completion.py \
  tests/unit/test_phase_timing_telemetry.py \
  tests/unit/test_squad_completion.py
git commit -m "fix: atomically persist phase timing"
```

---

### Task 3: Fail-Closed Checkpoint Prestate

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_completion.py`

**Interfaces:**
- Changes: `SquadController._completion_checkpoint_prestate()` returns one
  validated `{"kind": "git_head", "head": <oid>}` or raises bounded
  `StateAdvanceError(validator="checkpoint_prestate")`.
- Preserves: `{"kind": "none"}` when the effect plan has no checkpoint.

- [ ] **Step 1: Write Git failure/invalid/unborn RED tests**

Patch `subprocess.run` separately to raise `OSError`, raise
`CalledProcessError`, and return invalid output. Create a real unborn Git
repository for the final case. For each active-checkpoint route, snapshot:

```python
before_state = state_path.read_bytes()
before_revision = store.load()["state_revision"]
before_artifacts = artifact_tree_digest(project_root)
before_outboxes = outbox_tree_digest(squad_dir)
```

Assert preparation raises `StateAdvanceError` with
`validator == "checkpoint_prestate"` and that phase, revision, dispatch,
artifacts, publication outbox, and completion outbox are unchanged.

- [ ] **Step 2: Run checkpoint-prestate tests and capture RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_completion.py \
  -k "checkpoint_prestate and (git_failure or invalid or unborn or inactive)"
```

Expected: active failures return an all-zero prestate and continue.

- [ ] **Step 3: Remove the sentinel and raise bounded preparation failure**

Implement:

```python
def _completion_checkpoint_prestate(self) -> dict[str, object]:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=self._project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StateAdvanceError(
            "checkpoint prestate is unavailable",
            json_path="$.checkpoint_prestate.head",
            validator="checkpoint_prestate",
        ) from exc
    head = completed.stdout.strip()
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head) is None:
        raise StateAdvanceError(
            "checkpoint prestate is invalid",
            json_path="$.checkpoint_prestate.head",
            validator="checkpoint_prestate",
        )
    return {"kind": "git_head", "head": head}
```

The caller invokes it before completion-stage preparation, so no outbox or
state marker exists on failure.

- [ ] **Step 4: Run checkpoint-prestate and completion suites**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_completion.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_checkpoints.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add \
  src/harness/squad.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_completion.py
git commit -m "fix: reject unavailable checkpoint prestate"
```

---

### Task 4: Expanded Verification and Final Report

**Files:**
- Modify: `docs/superpowers/specs/2026-07-24-controller-durable-authority-design.md`
- Modify: `docs/superpowers/plans/2026-07-24-controller-durable-authority.md`
- Modify: `.superpowers/sdd/final-fix-report.md`
- Modify: `.superpowers/sdd/progress.md` (ignored working ledger only)

**Interfaces:**
- Produces: exact RED/GREEN ledger, commit ledger, verification totals,
  independent review verdict, and preserved branch status.

- [ ] **Step 1: Run the durability matrix**

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_state.py \
  tests/unit/test_phase_timing_telemetry.py \
  tests/unit/test_squad_completion.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_controller_lock_order.py
```

- [ ] **Step 2: Run the full suite**

```bash
.venv/bin/pytest -q
```

Record exact passed, skipped, deselected, failed, and duration totals.

- [ ] **Step 3: Run non-pytest verification**

```bash
bash scripts/bash/dry-run.sh
.venv/bin/python -m compileall -q src tests
git diff --check
```

Ruff is not configured in this repository; do not add it or claim a lint pass.

- [ ] **Step 4: Update the design, plan, final report, and progress**

Mark every completed checkbox, record exact commit hashes and test totals,
state the power-loss outcomes proved, and retain the statement that no push or
merge occurred.

- [ ] **Step 5: Commit the verification report**

```bash
git add -f \
  .superpowers/sdd/final-fix-report.md \
  docs/superpowers/specs/2026-07-24-controller-durable-authority-design.md \
  docs/superpowers/plans/2026-07-24-controller-durable-authority.md
git commit -m "docs: report durable authority verification"
```

- [ ] **Step 6: Request independent review**

Provide the reviewer the exact base before Task 1, final HEAD, this plan, this
design, and a generated diff. Require separate spec-compliance and code-quality
verdicts with Critical/Important/Minor counts. Resolve all Critical and
Important findings, rerun affected tests, and request focused re-review.

- [ ] **Step 7: Take a final clean-state snapshot**

```bash
git diff --check
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
git branch --show-current
```

Report the exact HEAD and clean status. Preserve the branch and worktree for
the parent whole-branch re-review; do not push or merge.
