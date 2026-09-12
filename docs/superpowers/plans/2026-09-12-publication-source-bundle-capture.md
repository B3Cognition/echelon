# Publication source-bundle capture implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Observe a sealed publication and its explicitly selected source trees/files inside one descriptor-associated publication lock, with joint before-yield and normal-exit validation.

**Architecture:** Compose the existing sealed-image inspector and complete tree reader on the same `_project_inspection_scope`. Extract their actual capture bodies into private connection-free helpers; preserve their existing public behavior. Return immutable publication, tree and individual-file observations without reading a source twice through separate public lock scopes or claiming freshness after exit.

**Tech Stack:** Existing POSIX descriptor pins, publication lock, immutable dataclasses and real-filesystem pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- IDs travel through interfaces as strings.
- No schema, identity allocation/lifecycle/binding persistence, provider, controller routing, publication promotion/discard behavior or activation changes in this task.

---

### Task 1: capture sealed publication and selected dependencies in one scope

**Files:** Modify `src/harness/squad_publication.py` and `src/harness/squad_source_snapshot.py`; create `tests/unit/test_squad_publication_sources.py`; document in `docs/element-identity-storage.md`. Existing publication snapshot types and existing tree snapshot public types retain their fields and meaning. Do not change manifest/marker formats, lock ordering, promotion/discard or database modules.

**Interfaces:** Add these immutable types in `harness.squad_source_snapshot` and this method on the existing prepared publication:

```python
@dataclass(frozen=True, slots=True)
class ProjectPathSnapshot:
    path: str
    image: PublicationImageDescriptor
    content: bytes | None

@dataclass(frozen=True, slots=True)
class PublicationSourcesSnapshot:
    publication: PublicationSnapshot
    trees: tuple[ProjectTreeSnapshot, ...]
    files: tuple[ProjectPathSnapshot, ...]

# PreparedSquadPublication
@contextmanager
def inspect_sources(
    self, *, tree_paths: Sequence[str] = (), file_paths: Sequence[str] = (),
) -> Iterator[PublicationSourcesSnapshot]:
    """Inspect sealed images and selected sources under one short lock scope."""
```

**Selection contract:** Validate and snapshot both sequences before opening descriptors/acquiring the publication lock. Accept the existing Sequence convention excluding str/bytes; validate every member as exact str, valid UTF-8 and the existing canonical nonempty project-relative path grammar. Empty batches are allowed, including both empty; empty str/bytes are not empty batches. Reject duplicate paths within or across batches and component-wise ancestor/descendant overlaps across the entire selection, including file/file overlaps. Prefix siblings such as `spec/a` and `spec/ab` remain distinct. Return trees and individual files in ascending path order independent of input order. This selection is controller supplied; no implicit workspace scan, extension filter, Markdown decoding, role inference or external-project traversal. A target can legitimately occur both among sealed operations and within the selected sources: that is required for baseline observation, not a selection overlap error.

**Shared capture:** Extract the existing inline iterative tree traversal into one private helper on caller-supplied `_InspectionPaths` and retained project fd; make both `inspect_project_tree` and `inspect_sources` use it. Extract the actual sealed inspection body so both `inspect` and `inspect_sources` use the same marker validation, `_load_prepared_pinned`, retained squad/stage directory binding, current/stage byte reads and global prefix calculation. Private helper names may follow local style, but there must be only one implementation of each capture/validation policy. These helpers do not open a second public scope, acquire a lock, publish, discard, or own a caller transaction. Keep resources in the one scope's ExitStack, including the pinned sealed transaction. Do not nest either public inspector or public tree reader inside another inspector.

`inspect_sources` acquires exactly one existing `_project_inspection_scope(self._project_root)`, bound to its retained project fd with the reviewed `expected_project_fd` lock association. It captures the sealed operation snapshot, every selected tree, and every selected individual file on those descriptors. Register all retained paths, missing ancestors/files, directory membership, and file identities with the shared paths owner. Immediately before yielding, jointly verify all source pins/memberships plus the sealed transaction. On normal context exit, jointly verify them again. A change to a source captured earlier while a later source is being read must fail before yield; a change during the body must fail normal exit. Verify the transaction even with no source selections. Existing root/capability/marker validation and path/lock cleanup behavior must not become weaker during extraction.

Each selected tree retains the exact existing semantics: complete regular-file bytes and modes, all directory membership/modes including empty directories, no hidden-file filtering, missing tree distinct from present empty tree, iterative traversal, and rejection of symlinks/special entries or detectable drift. Individual files use the existing `_InspectionPaths.current` and pinned byte reader: a missing path/ancestor yields `PublicationImageDescriptor("missing", None, None)` and content None; a present empty file yields kind file, its exact SHA/mode and `b""`. A directory, symlink or special file in a file selection rejects. Initially stable hard-linked regular files remain readable in both APIs; retain the existing nlink/content/identity checks and reject changes before yield or normal exit. Read-only capture is not provider write authorization through aliases. Do not create a missing selected source or ancestor. Resource exhaustion or unsupported capabilities fail closed, never truncate selection.

Return the entire sealed `PublicationSnapshot` unchanged, including operations outside selected source paths. Do not filter operations, synthesize original bytes from current bytes after partial promotion, or overlay staged bytes onto the source observations. Trees/files describe current canonical observations; operation postimages describe the sealed proposed bytes; promoted_prefix retains the existing lower-bound/no-op ambiguity. The future intent owner must authenticate declared dependency coverage, original preimages, semantic review and typed role/scope mappings. This task supplies no receipt, durable lease, graph permission, semantic assessment or post-exit freshness. Do not run providers or recursively inspect/publish/discard while the context is open. Success includes normal exit; a write committed by a caller inside the body is not undone by a later source drift exception and cannot be considered completed on yield alone.

**First regression before production edits:**

```python
def test_sealed_images_and_unchanged_dependencies_share_one_observation(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/game/investigation").mkdir(parents=True)
    (project / "specs/game/unknowns.md").write_bytes(b"before\r\n")
    (project / "specs/game/investigation/U-001.md").write_bytes(b"evidence\r\n")
    (project / ".echelon").mkdir(exist_ok=True)
    (project / ".echelon/constitution.md").write_bytes(b"rules\r\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"after\r\n")
    target = Path("specs/game/unknowns.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(
        tree_paths=("specs/game",), file_paths=(".echelon/constitution.md",),
    ) as snapshot:
        operation, = snapshot.publication.operations
        assert (operation.current_bytes, operation.postimage_bytes) == (b"before\r\n", b"after\r\n")
        assert [(item.path, item.content) for item in snapshot.trees[0].files] == [
            ("specs/game/investigation/U-001.md", b"evidence\r\n"),
            ("specs/game/unknowns.md", b"before\r\n"),
        ]
        assert snapshot.files[0].content == b"rules\r\n"
    assert (project / target).read_bytes() == b"before\r\n"
```

- [ ] Add the real sealed-fixture regression with `pytestmark = pytest.mark.unit` and the existing secure-POSIX skip. Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_squad_publication_sources.py -q`; retain actual missing-inspect_sources RED after successful seal, then implement and obtain GREEN.
- [ ] Cover multiple trees and external individual files; sorting, frozen detached tuples/bytes, binary/Unicode/CRLF content, exact file/directory modes, absent versus empty paths/trees, nested empty directories, stages shared by multiple operations, write/delete/no-op/mode-only operations, complete operation output outside selected paths and an interrupted prefix. Assert canonical sources, stages and authority remain unchanged; absence is not materialized. Existing `inspect` and `inspect_project_tree` retain outputs and public error behavior.
- [ ] Cover malformed Sequence/members, duplicate and component-overlapping selections, valid prefix siblings, noncanonical paths, non-UTF-8 members and rejection before any scope acquisition. Exercise missing/file/ancestor replacement, symlink/hardlink/special entries, additions/removals in an earlier tree while a later tree/file is captured, mode/content changes, and stage/manifest changes before yield and on normal exit. Use real filesystem changes with deterministic injection points, not sleeps or a fabricated successful snapshot.
- [ ] Prove one acquisition on a retained root descriptor, no public recursive inspectors, normal publisher exclusion with a bounded real spawned-process lock probe, and release on successful exit, caller exception and inspection failure. Preserve caller exceptions unchanged. Include concrete root replacement around lock acquisition and cleanup assertions for owned descriptors and controller lock rank; reuse established fault/IPC patterns without rerunning high-count loops.
- [ ] Run exactly `tests/unit/test_squad_publication_sources.py`, `tests/unit/test_squad_source_snapshot.py`, `tests/unit/test_squad_publication_inspection.py`, and `tests/unit/test_squad_publication.py` with the checkout virtualenv once on final code. No full repository, database capacity, provider or live run; no unchanged post-commit repeat.
- [ ] Document coherent bounded source observation versus dependency-coverage/promotion/semantic/durable-intent authority; self-review extraction against old inspector behavior; run `git diff --check`; commit only task files. Retain exact actual RED/GREEN commands/output in the report. Label counterfactual coverage reasoning separately from any empirical mutation testing. Root handles plans, ledgers, checkpoints and independent review.

## Remaining integration

This closes the sequential source/publication observation gap, not the durable intent. Intent preparation still needs a complete typed before/after bundle, authenticated semantic review and candidate checks on a single guarded ledger baseline. Pending-write protection, recovery/finalization, graph receipts, managed producers and bounded repair remain required. No new on-disk protocol or activation is selected by this task.
