# Sealed publication inspection implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the future identity-intent owner inspect exact sealed postimages and current target bytes under the existing publication lock, without promoting files or pretending a partially promoted target is its original preimage.

**Architecture:** Add a read-only context manager to `PreparedSquadPublication`, reusing its descriptor-safe stage loader, publication lock and pinned-file verification. Return immutable byte snapshots plus the recorded preimage descriptors. No manifest/schema change, new publisher, caller-aware prose or workflow activation.

**Tech Stack:** Existing POSIX descriptor-safe publication helpers, frozen dataclasses and real-filesystem pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Keep failed candidates as diagnostics; do not update canonical artifacts, graphs, or memory from rejected candidates.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- No identity schema, allocator, import, lifecycle, binding, provider, controller routing, publication promotion or activation changes in this task.

---

### Task 1: inspect immutable images through the existing publication owner

**Files:** Modify `src/harness/squad_publication.py`; create `src/harness/squad_publication_snapshot.py` for immutable snapshot value types and connection-free image assembly helpers, and `tests/unit/test_squad_publication_inspection.py`; document the integration boundary in `docs/element-identity-storage.md`. Reuse current private descriptor helpers rather than copying them into the new module. Keep snapshot types separate from the already-large publisher, with a local import in the publisher if needed to avoid an import cycle. No broad publisher refactor.

**Interfaces:**

```python
# harness.squad_publication_snapshot
@dataclass(frozen=True)
class PublicationImageDescriptor:
    kind: str
    sha256: str | None
    mode: int | None

@dataclass(frozen=True)
class PublicationOperationSnapshot:
    action: str
    target: str
    preimage: PublicationImageDescriptor
    postimage: PublicationImageDescriptor
    current: PublicationImageDescriptor
    current_bytes: bytes | None
    postimage_bytes: bytes | None

@dataclass(frozen=True)
class PublicationSnapshot:
    marker: PublicationMarker
    promoted_prefix: int
    operations: tuple[PublicationOperationSnapshot, ...]

# harness.squad_publication.PreparedSquadPublication
@contextmanager
def inspect(self) -> Iterator[PublicationSnapshot]:
    """Inspect exact sealed/current images under the existing publication lock."""
```

`PublicationMarker` is the existing frozen type. All returned objects are detached immutable values; no dictionaries, live descriptors, mutable prepared-manifest references, file paths that defer a read, or provider-owned values act as snapshot authority. `kind` is exactly file/missing; missing descriptors have `sha256=None, mode=None`, and missing bytes are None, distinct from a present empty file b"". Modes and SHA256 preserve the existing validated image descriptors without normalization.

The context manager must perform the same secure-POSIX capability gate, marker validation and expected transaction-root check as `publish`; take exactly the existing `_publication_exclusivity` lock; reload/pin the sealed manifest/stages with `_load_prepared_pinned`; and never trust the mutable `self._manifest`. Bind exact postimage bytes to the pinned stage hash and the manifest's desired postimage descriptor. Delete operations have `postimage_bytes=None`; write operations always expose the staged bytes even when the target is already promoted. A shared stage may serve several targets, but each snapshot operation keeps its own ordered target/descriptors.

Capture current targets via descriptor-relative no-follow traversal from a pinned project root, using existing directory/regular-file/hash/read/pin helpers. Do not introduce a `Path.read_bytes()` or check-then-follow path read. Correctly distinguish an absent target or absent parent from a symlink, directory, FIFO, inaccessible or changed path. Do not create absent target directories. Compare read bytes to their pinned digest and identity, and revalidate the project-root identity and target/stage bindings before yielding and again on successful context exit. Hold and close every required descriptor reliably on all failures and caller exceptions. A target absent at entry must still be absent on successful exit; replaced or mutated current files/stages must reject. Caller exceptions propagate without being converted to successful inspection, and lock/descriptor cleanup still runs.

Reuse the existing global preimage/postimage-prefix rule, including equal pre/post no-op ambiguity. `promoted_prefix` is its existing lower-bound result, not the count of operations that happen to equal postimages. If assembling prefix validation from already-captured immutable image descriptors requires extracting a pure helper, move the existing rule into that helper and keep `authenticate_publication_prefix` as its compatible filesystem adapter; do not maintain two copies of the rule. Every current descriptor must be either its recorded preimage or postimage and the complete operation list must admit one legal global promotion prefix. No partial snapshot may escape on drift/corruption.

Inspection never promotes/deletes/restores a target, writes state/identity/graph/checkpoint/receipt data, seals/discards a stage, or claims publication completion. Reuse of the existing publication lock may create its existing `.echelon/runtime/publication.lock` control path; that is the only permitted incidental filesystem effect. The context body is for short controller-owned validation/identity transactions, not provider work. It must not recursively call `publish`, `discard` or `inspect` while holding the non-reentrant publication lock. There is no new nested lock or independent lock hierarchy.

The snapshot deliberately does not contain original preimage bytes for an already-promoted target. Its `preimage` is the authenticated manifest descriptor, whereas `current_bytes` is explicitly current. A future durable intent must retain accepted before images before promotion and match their hashes/modes to this descriptor; it must never reinterpret current postimage bytes as the baseline. Snapshot scope is the manifest's operations, not every unchanged semantic/dependent input. This API does not authenticate semantic review, solve complete candidate capture, reserve an identity intent, or confer authority after the lock context exits.

Successful inspection includes successful context exit, not merely receiving the yielded value. A caller that persists a pending intent inside the body must keep that intent pending if exit validation fails; this reader cannot roll back a separately committed database transaction. Do not mark publication/graph/completion successful from inside the body or add such effects to this task.

**First regression before production edits:**

```python
def test_inspection_returns_original_and_sealed_bytes_without_publication(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs" / "spec-test"
    squad.mkdir(parents=True)
    target = project / "spec.md"
    target.write_bytes(b"before\r\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("spec-after.md")
    stage.write_bytes(b"after\r\n")
    transaction.add_write(Path("spec.md"), stage, owned_paths={Path("spec.md")})
    prepared = transaction.seal()
    with prepared.inspect() as snapshot:
        operation, = snapshot.operations
        assert operation.target == "spec.md"
        assert operation.current_bytes == b"before\r\n"
        assert operation.postimage_bytes == b"after\r\n"
        assert snapshot.marker == prepared.marker
        assert snapshot.promoted_prefix == 0
        assert target.read_bytes() == b"before\r\n"
    assert target.read_bytes() == b"before\r\n"
    assert stage.read_bytes() == b"after\r\n"
```

- [ ] Use `pytestmark = pytest.mark.unit` and the existing secure-POSIX test capability conventions. Run the new module with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_squad_publication_inspection.py -q`; retain real missing-method RED after successful existing stage preparation, not an import/fixture failure.
- [ ] Implement the context manager and immutable snapshots under the existing lock and descriptor ownership. Preserve existing `publish`, `discard`, marker and schema-1 manifest behavior. Keep any prefix-rule extraction strictly behavior-preserving with the original signature intact.
- [ ] Add real filesystem tests for write/delete/missing/empty/mode-only/no-op/shared-stage cases, sorted operations and exact hashes/modes; existing no-op prefix lower-bound semantics; a real interrupted publication followed by reloaded inspection showing current postimages and recorded original preimage descriptors; whole publication followed by inspection; legal and illegal mixed promotion prefixes; no target or stage mutation from inspection.
- [ ] Exercise prepared-object manifest tampering, marker/root mismatch, manifest/stage corruption or absence, leaf and ancestor symlinks, directory/FIFO targets, targets with absent parents, in-context target/stage replacement and same-size content mutation, missing target appearance, root/ancestor replacement, and caller exceptions. Assert fail-closed bounded existing PublicationError codes, descriptor/lock release and no publication/cleanup side effects. Use focused fault injection against real files/pins instead of mocking successful publication or claiming timing races from ordinary serial tests.
- [ ] Prove the inspection uses the existing publication lock and lock-rank checks; a separately spawned process using normal `publish` cannot promote while inspection holds it and can progress after exit. Use process events/pipes and bounded joins rather than sleeps to guess acquisition; clean up child processes. Do not perform recursive lock calls that would hang the test.
- [ ] Run exactly `tests/unit/test_squad_publication_inspection.py`, `tests/unit/test_squad_publication.py`, `tests/unit/test_squad_completion.py`, and `tests/unit/test_publication_transaction.py` with the checkout virtualenv. No repository-wide, capacity, provider or live-workspace run. Record pristine actual results; no duplicate unchanged suite after commit.
- [ ] Self-review descriptor and exception cleanup, immutable byte/hash correspondence, global prefix reuse and current-versus-original semantics; run `git diff --check`. Commit only task files and retain complete command/RED/GREEN evidence and concerns in the task report. Root handles the independent review.

## Following work

The identity publication owner still needs a complete authenticated before/after bundle, semantic assessment, durable intent/pending-write protection, lifecycle/binding finalization, graph receipts and integration at both run-local acceptance and final export. This reader is the existing sealed publisher's inspection boundary; it is not an alternative publisher or a claim that those integrations now exist.
