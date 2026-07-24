# Controller Publication Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish controller-owned product-input and spec artifacts only after
their routing state is durable, recover interrupted file-level publication
idempotently, and make provider token increments atomic.

**Architecture:** A focused `harness.squad_publication` module stages exact
Echelon-owned files, seals a canonical manifest containing preimage and
postimage digests, and installs each operation only after state contains an
exact pending marker. `SquadStateStore` owns marker validation, failure
diagnostics, and durable marker clearance. `SquadController` recovers the
outbox under both existing execution locks before any normal or manual
phase/status logic.

**Tech Stack:** Python 3.11, pathlib/os/tempfile/shutil/hashlib/json, pytest,
Echelon `SquadController` and `SquadStateStore`.

## Global Constraints

- No visible target write occurs while staging or validating.
- The exact state marker is the sole authority to publish.
- Manifest operations enumerate only exact Echelon-owned files.
- Every operation records expected preimage existence/digest and exact
  postimage existence/digest.
- Unexpected target drift, unsafe paths, corrupt/missing stage, or manifest
  mismatch fails closed without clearing the marker.
- Recovery runs under both execution locks before all normal/manual
  phase/status handling.
- The immutable stage remains until marker-clear state saving is durable.
- Journal, timing, checkpoint, and context success work occurs only after
  durable marker clearance.
- Old state without the marker remains valid; there is no compatibility
  switch.
- Use TDD for every production change and commit small coherent slices.

---

### Task 1: Atomic Provider Usage

**Files:**
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `src/harness/squad.py:572-590`

**Interfaces:**
- Consumes: `SquadStateStore.increment_token_usage(tokens: int) -> None`
- Produces: non-deferred provider usage that performs exactly one locked state
  mutation and preserves all concurrent fields.

- [x] **Step 1: Write the failing race regression**

Add a test that wraps `store.load()` to inject one locked concurrent mutation
after returning the old snapshot, then calls `_record_provider_usage()`:

```python
def test_provider_usage_increment_preserves_concurrent_state_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "msg", 0, "init")
    original_load = store.load
    injected = False

    def racing_load() -> dict:
        nonlocal injected
        snapshot = original_load()
        if not injected:
            injected = True
            store._mutate(
                lambda live: live.__setitem__("concurrent_marker", "kept")
            )
        return snapshot

    monkeypatch.setattr(store, "load", racing_load)
    ctrl._record_provider_usage(
        SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
            token_usage=37,
        )
    )
    state = original_load()
    assert state["concurrent_marker"] == "kept"
    assert state["token_usage"] == 37
```

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_squad_controller.py \
  -k provider_usage_increment_preserves_concurrent_state_mutation
```

Expected: FAIL with stale-state save and `token_usage == 0`.

- [x] **Step 3: Implement the atomic increment**

Keep the existing concrete positive-integer and deferred-usage checks. Replace
only the non-deferred load/normalize/save sequence:

```python
with self._telemetry_usage_lock:
    if self._deferred_provider_usage is not None:
        self._deferred_provider_usage["tokens"] += raw
        return
    self._state_store.increment_token_usage(raw)
```

- [x] **Step 4: Verify GREEN and commit**

Run the focused test plus existing token state tests, then commit:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_state.py \
  -k "provider_usage or TokenMonotonicity"
git add src/harness/squad.py tests/integration/test_squad_controller.py
git commit -m "fix: increment provider usage atomically"
```

### Task 2: Exact Marker State Contract

**Files:**
- Modify: `src/harness/state_transaction_namespace.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`
- Modify: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces:
  - `PENDING_EXTERNAL_PUBLICATION_KEY`
  - `validate_pending_external_publication(value) -> dict[str, object]`
  - `SquadStateStore.record_external_publication_failure(marker, code)`
  - `SquadStateStore.complete_external_publication(marker)`
- Consumes: trusted routing-effect and store-owned transaction namespaces.

- [x] **Step 1: Write RED marker and ownership tests**

Cover:

```python
VALID_MARKER = {
    "schema_version": 1,
    "transaction_id": "a" * 32,
    "manifest_sha256": "b" * 64,
}
```

Assert exact types and fields are required, booleans/subclasses and extra keys
are rejected, provider/judgment updates cannot set or remove the key, trusted
routing effects can carry it, and old states without it still advance.

Add store tests proving failure recording:

```python
store.record_external_publication_failure(VALID_MARKER, "target_drift")
failed = store.load()
assert failed["status"] == "blocked"
assert failed["blocked_reason"] == "external_publication_pending"
assert failed["external_publication_failure"]["code"] == "target_drift"
assert failed["pending_external_publication"] == VALID_MARKER
```

Then prove exact-marker mismatch cannot record or clear, and successful
completion restores the preserved status/blocked reason and removes both
internal keys in one locked save.

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  -k "external_publication or pending_publication"
```

Expected: FAIL because the marker key and store methods do not exist.

- [x] **Step 3: Implement exact validation and store CAS methods**

Reserve the marker and bounded diagnostic keys in the central namespace; only
the marker is a trusted routing effect. Validate with exact dict/string/int
types and anchored lowercase-hex regular expressions.

Implement failure recording so the first failure preserves:

```python
{
    "schema_version": 1,
    "code": code,
    "resume_status": state.get("status", "running"),
    "resume_blocked_reason": state.get("blocked_reason"),
}
```

Allowed codes are exactly:

```python
{
    "manifest_invalid",
    "manifest_mismatch",
    "publish_io",
    "stage_corrupt",
    "stage_missing",
    "state_finalize",
    "target_drift",
}
```

Repeated failures update only the bounded code. Completion requires marker
equality, restores the saved lifecycle values when a diagnostic exists, removes
both keys, and calls `_save_unlocked()` once.

- [x] **Step 4: Verify GREEN and commit**

Run the focused suites and commit:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  -k "external_publication or pending_publication or ownership"
git add src/harness/state_transaction_namespace.py \
  src/harness/squad_state.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py
git commit -m "fix: reserve durable publication marker state"
```

### Task 3: Durable File-Level Publication Engine

**Files:**
- Create: `src/harness/squad_publication.py`
- Create: `tests/unit/test_squad_publication.py`

**Interfaces:**
- Produces:
  - `PublicationError(code: str)`
  - `PublicationMarker`
  - `SquadPublicationTransaction.begin(project_root, squad_dir, transaction_id)`
  - `transaction.build_path(name) -> Path`
  - `transaction.add_write(target, staged, *, owned_paths)`
  - `transaction.add_delete(target, *, owned_paths)`
  - `transaction.seal() -> PreparedSquadPublication`
  - `load_prepared_publication(project_root, squad_dir, marker)`
  - `PreparedSquadPublication.publish(fault_hook=None)`
  - `PreparedSquadPublication.discard()`
- Consumes: no controller or state-store objects.

- [x] **Step 1: Write RED manifest/ownership/durability tests**

Use real temporary files. Cover canonical sorted operations, exact preimage and
postimage digests, workspace-relative targets, duplicate and overlapping target
rejection, absolute/`..`/symlink/special-file rejection, and refusal to add a
target absent from the explicit `owned_paths` set.

Assert `seal()` rereads and digest-checks every staged file and the manifest.
After sealing, mutate a staged byte and prove loading fails with
`stage_corrupt`; delete the stage and prove `stage_missing`; alter manifest
bytes and prove `manifest_mismatch`.

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_squad_publication.py
```

Expected: collection error because `harness.squad_publication` does not exist.

- [x] **Step 3: Implement canonical stage and manifest sealing**

Use canonical JSON (`sort_keys=True`, compact separators, UTF-8 plus newline),
SHA-256, exact schema validation, `Path.resolve()` containment checks, and
`os.lstat()` to reject symlinks/special files. Durable writes follow:

```python
with os.fdopen(fd, "wb") as handle:
    handle.write(content)
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temp_path, final_path)
_fsync_directory(final_path.parent)
```

The marker contains only schema version, validated transaction ID, and
canonical manifest digest. Do not expose raw paths in `PublicationError`.

- [x] **Step 4: Write RED publish/recovery fault tests**

For each operation position, inject a fault after preceding operations. Assert:

- target matching postimage is skipped on retry;
- target matching preimage is installed/deleted;
- unexpected creation, deletion, content, or type drift yields
  `target_drift`;
- unrelated files remain byte-identical;
- missing/corrupt stage never touches targets;
- postimage verification failure retains the stage;
- stage is not removed by `publish()`.

- [x] **Step 5: Implement idempotent publication**

For writes, copy immutable staged bytes to a sibling temp, fsync, recheck the
target preimage, `os.replace`, fsync the parent, then verify the postimage.
For deletes, recheck preimage, unlink the exact owned file, fsync the parent,
and verify absence. At entry and exit, verify the manifest digest and all stage
digests. Skip only an exact postimage. Never accept any other current state.

- [x] **Step 6: Verify GREEN and commit**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_squad_publication.py
.venv/bin/python -m compileall -q src/harness/squad_publication.py
git add src/harness/squad_publication.py tests/unit/test_squad_publication.py
git commit -m "feat: add durable squad publication outbox"
```

### Task 4: Stage Product, Phase A, and Manual Effects

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_product_inputs.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/integration/test_squad_context_memory.py`

**Interfaces:**
- Produces:
  - `_prepare_external_phase_effects(...) -> PreparedSquadPublication | None`
  - staged-path overrides for product updates
  - staged Phase A/manual publication that returns owned file operations
- Consumes: the transaction engine from Task 3.

- [x] **Step 1: Write RED product staging tests**

Inject faults at structural repair JSON/Markdown, requirement-context refresh,
candidate update JSON/Markdown, and final task validation. Snapshot visible
product files before each call and assert byte-for-byte equality after failure.
On success, assert only the staged copies change until `publish()` is called.

- [x] **Step 2: Write RED Phase A/manual staging tests**

For Phase A, inject failures during active-spec overlay, product evidence,
constitution, KB outputs, run history, report, artifact index, metadata, and
readiness. Assert the published spec is byte-identical and no marker is
committed. Prove the manifest enumerates only active Echelon spec files and the
documented generated/evidence files, preserves a destination-only manual note,
and never lists that note.

For manual runs, inject constitution and artifact-index failures and assert the
visible spec remains unchanged. Confirm manual phase4 takes the full Phase A
path.

- [x] **Step 3: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_product_inputs.py \
  tests/integration/test_squad_controller.py \
  tests/integration/test_squad_context_memory.py \
  -k "publication_staging or product_effect_staging or manual_publication"
```

Expected: FAIL because current helpers write visible paths.

- [x] **Step 4: Implement staged controller adapters**

Create a virtual target tree under `transaction.build_path(...)`, seeded from
the current published spec for correct index/history behavior. Rewrite product
metadata paths to staged files, run existing product helpers there, and use the
staged input evidence when constructing Phase A output.

Build the owned relative-path set from:

```python
active_spec_files
| published_input_files
| {
    Path("constitution.md"),
    Path("targets.yml"),
    Path("run-history.json"),
    Path("squad-report.md"),
    Path("ARTIFACTS.md"),
    Path("feature-metadata.yml"),
}
| published_kb_files
```

Diff only those exact files against visible preimages to add write/delete
operations. Keep destination-only files solely as virtual-tree context. Split
metadata writing from MemPalace mining; mining occurs only after durable
publication completion.

- [x] **Step 5: Verify GREEN and commit**

Run the three focused suites, inspect the manifest assertions, and commit:

```bash
.venv/bin/pytest -q \
  tests/unit/test_product_inputs.py \
  tests/integration/test_squad_controller.py \
  tests/integration/test_squad_context_memory.py \
  -k "publication or product_input or context_metadata"
git add src/harness/squad.py \
  tests/unit/test_product_inputs.py \
  tests/integration/test_squad_controller.py \
  tests/integration/test_squad_context_memory.py
git commit -m "fix: stage controller-owned phase publications"
```

### Task 5: Durable Recovery and Terminal Reconciliation — Completed by Replacement Plan

**Status:** Superseded and complete.

The publication-only recovery implementation landed in `0553ae2c`
(`fix: recover controller publications before phase work`). Its independent
review established that a publication marker alone cannot preserve bounded
post-dispatch work across a real process restart.

The executable successor is
[`2026-07-23-controller-completion-outbox.md`](2026-07-23-controller-completion-outbox.md).
That plan retains the exact publication marker and adds a durable completion
intent, intrinsic effect receipts, terminal provenance, fresh-controller
recovery, and the global lock hierarchy. Completion-plan Tasks 1–7, commits
`0a9a93f1` through `908a9b8f`, replace every former Task 5 implementation
step. The original one-marker pseudocode and commit recipe are intentionally
removed so they cannot be mistaken for current executable guidance.

### Task 6: Expanded Verification and Report — Completed by Replacement Plan

**Status:** Superseded and complete.

The publication boundary suite remains part of the release evidence, but the
authoritative expanded gate and final report are completion-plan Task 8. It
verifies both outboxes together, the fresh-controller crash matrix, exact
effect receipts, lock ordering, the shell hook, repository dry-run, full test
suite, static checks, and synchronized version metadata.

See:

- [completion outbox Task 8](2026-07-23-controller-completion-outbox.md#task-8-expanded-verification-and-final-report);
- [controller publication/completion design](../specs/2026-07-23-controller-publication-outbox-design.md);
- `.superpowers/sdd/final-fix-report.md` for the exact final evidence.

No publication-only implementation or report task remains outstanding.
