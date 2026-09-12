# Pinned spec-tree capture implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Capture a complete explicitly selected spec directory as immutable exact bytes and directory membership under the existing publication lock, for before-provider baselines and before-publication revalidation.

**Architecture:** Reuse the reviewed project-root/lock descriptor association, `_InspectionPaths`, and pinned regular-file helpers. A focused tree-reader module returns detached file/directory snapshots; it neither copies an authoring candidate nor decides artifact roles or publication authority. Share root acquisition with the sealed inspector rather than duplicate its safety protocol.

**Tech Stack:** Existing POSIX descriptor-safe publication helpers, frozen dataclasses, standard-library filesystem operations and real-filesystem pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Keep failed candidates as diagnostics; do not update canonical artifacts, graphs, or memory from rejected candidates.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- No identity schema, allocation, lifecycle, binding, provider, controller routing, publication promotion or activation changes in this task.

---

### Task 1: capture complete directory membership and exact file images

**Files:** Create `src/harness/squad_source_snapshot.py` and `tests/unit/test_squad_source_snapshot.py`; modify `src/harness/squad_publication.py` only to share the reviewed root-inspection scope and extend its existing path bindings with directory-membership verification; document the boundary in `docs/element-identity-storage.md`. Do not create another filesystem-safety library or refactor publication promotion.

**Interfaces:**

```python
# harness.squad_source_snapshot
@dataclass(frozen=True, slots=True)
class ProjectDirectorySnapshot:
    path: str
    mode: int

@dataclass(frozen=True, slots=True)
class ProjectFileSnapshot:
    path: str
    image: PublicationImageDescriptor
    content: bytes

@dataclass(frozen=True, slots=True)
class ProjectTreeSnapshot:
    path: str
    exists: bool
    directories: tuple[ProjectDirectorySnapshot, ...]
    files: tuple[ProjectFileSnapshot, ...]

@contextmanager
def inspect_project_tree(project_root: Path, tree_path: str) -> Iterator[ProjectTreeSnapshot]:
    """Inspect one complete project-relative tree under the existing lock."""
```

`PublicationImageDescriptor` is the existing frozen file/missing descriptor from `harness.squad_publication_snapshot`; captured files always use kind `file` with exact lowercase hash/mode, and content is always bytes (including b""). Missing tree is `exists=False, directories=(), files=()`; a present empty directory is `exists=True`, exactly one root directory descriptor, and `files=()`. Every file/directory path is canonical project-relative POSIX syntax, including the selected tree prefix, sorted by the exact path string. Include the tree root and empty nested directories in `directories`; files appear exactly once. Directory modes are exact `stat.S_IMODE` values from retained descriptors so later snapshot comparison also sees permission changes. A present tree root must be a real directory, not a regular file, symlink or special file. No filtering by extension or hidden-name convention: all directories and regular files in this explicitly selected tree are captured. Caller owns choosing the spec tree; this helper does not search the workspace or infer a canonical spec from a run name.

Validate `tree_path` as an exact nonempty str through the existing publication relative-path grammar; reject absolute paths, workspace-root aliases, dot/dot-dot components, backslashes, invalid encodings and other normalization aliases rather than normalize them. Use the same validated absolute project-root rules/capability gate as sealed inspection. Do not resolve symlinks to grant access. The API cannot capture the entire workspace root via an empty string or `.`.

Extract the existing sealed inspector's retained project-root acquisition, existing publication lock with borrowed expected-project descriptor, immediate post-acquisition root validation and owned resource cleanup into one private shared context in `squad_publication.py`. Keep that context internal and preserve `PreparedSquadPublication.inspect()`'s public API, normal-exit validations, exception propagation, error codes and stage/prefix rules. Both readers must use the same owner and root/lock descriptor association; do not copy root pinning/lock validation into the new module. No extra lock, rank, state field, manifest marker or schema change. Default publish/discard behavior remains unchanged.

Traverse the selected subtree descriptor-relatively, using existing `_InspectionPaths.directory/current`, regular pin/read/verify and root helpers. Retain a sorted directory-entry-name snapshot for every traversed directory, including empty directories; compare membership before yielding and on normal context exit along with directory/file/absence bindings. Use descriptor-based directory listing (`os.listdir(fd)`) and no-follow metadata/open operations, not Path.rglob, Path.read_bytes, copytree or check-then-follow reads. Every directory and regular file must remain bound to the opened identity; byte reads must match pinned hashes/metadata. Reject symlink leaves/ancestors, FIFOs, sockets, other special files, permission/listing failures and invalid child path names with bounded existing PublicationError codes. Do not skip unreadable/unsupported entries. An iterative traversal is preferred so valid deep trees do not depend on Python recursion depth.

Reject additions, removals, renames, replacements, mode/content changes, and previously absent tree appearance before yield or successful exit. Rechecking only already-seen files is insufficient: new sibling files and empty directory changes must invalidate the snapshot too. Directory membership ordering from the filesystem must not affect snapshot ordering. Reuse the existing regular identity checks, including nlink and same-size writes; do not invent weaker integrity descriptors or synthesize content after failure. Preserve exact binary bytes, UTF-8 bytes, CRLF, whitespace, empty files and desired mode values without text decoding or line normalization. File content size is not silently truncated.

Return only frozen detached values and tuples—no dict/list containers, retained FDs or lazy path-backed data escape. The context remains short and controller-owned; no provider work or recursive publish/discard/inspect inside it. A caller exception propagates unchanged even if the tree also drifts, and all resources/locks close on entry/listing/read/validation/exit failures. The reader never creates the absent selected directory, writes/removes/restores source files, stages a transaction, or writes ledger/graph/state/receipt data. Initialization of the existing `.echelon/runtime/publication.lock` control path is the sole permitted incidental filesystem effect.

Snapshot success includes normal context exit. These are observations of exact bytes during a bounded lock lifetime, not standalone proof of historical source provenance, semantic approval, a reserved baseline across provider execution, or canonical acceptance. A future caller must retain the successful before image in controller-owned storage, recapture/compare the complete tree before promotion, and bind the exact image set/scope/review to a durable intent. Do not hold this lock during provider work or claim freshness after exit.

**First regression before production edits:**

```python
def test_complete_tree_capture_preserves_bytes_and_empty_directories(tmp_path):
    project = tmp_path.resolve()
    tree = project / "runs/spec-test/specs/001-game"
    (tree / "investigation").mkdir(parents=True)
    (tree / "empty").mkdir()
    (tree / "unknowns.md").write_bytes(b"### U-001: Subject\r\nExact body.\r\n")
    (tree / "investigation/U-001.md").write_bytes(b"Evidence\r\n")
    from harness.squad_source_snapshot import inspect_project_tree
    root = "runs/spec-test/specs/001-game"
    with inspect_project_tree(project, root) as snapshot:
        assert snapshot.path == root and snapshot.exists is True
        assert tuple(item.path for item in snapshot.directories) == (
            root, root + "/empty", root + "/investigation",
        )
        assert [(item.path, item.content) for item in snapshot.files] == [
            (root + "/investigation/U-001.md", b"Evidence\r\n"),
            (root + "/unknowns.md", b"### U-001: Subject\r\nExact body.\r\n"),
        ]
```

- [ ] Add the real-files regression with `pytestmark = pytest.mark.unit` and existing secure-POSIX capability conventions. Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_squad_source_snapshot.py -q`; retain actual missing-reader RED after the complete source fixture exists, not a broken fixture.
- [ ] Implement the immutable reader and one shared root-inspection context, extending existing path binding verification for complete directory membership. Preserve all sealed inspection behavior, including acquisition ABA rejection and borrowed descriptor ownership. No broad publisher cleanup.
- [ ] Test absent tree versus empty tree, absent ancestors, empty nested directories, hidden and non-Markdown files, empty/binary/Unicode/CRLF content, exact modes/hashes, deterministic order under reversed listing, detached frozen values, and invalid path/root/child names. Verify all files are retained without truncation or extension-based skipping.
- [ ] Test initial symlink leaf/ancestor/tree root, special files, inaccessible paths and listing failures; before-yield and exit membership additions/removals/renames including empty directories, file/directory/root replacement, same-size writes, mode changes and absent-tree appearance. Use focused fault injection around real descriptors/listing rather than mocking successful snapshots.
- [ ] Test caller exception plus concurrent drift preserves the original exception, owned descriptor closure and subsequent lock use after each entry/read/list/exit failure. Assert no source mutation or implicit missing-tree creation; inventory all incidental paths. Retain original root swap and transient ABA safety tests through the shared scope.
- [ ] Prove a separately spawned normal publisher is blocked by the existing lock while tree inspection is held and progresses after exit; use pipes/events with actual lock contention, bounded joins and reliable child cleanup, not sleep guesses or recursive same-process locking. Follow the reviewed inspection test's actual flock observation pattern.
- [ ] Run exactly `tests/unit/test_squad_source_snapshot.py`, `tests/unit/test_squad_publication_inspection.py`, and `tests/unit/test_squad_publication.py` with the checkout virtualenv once on final code. No full repository, capacity, provider or live run; no unchanged post-commit repeat.
- [ ] Document lifetime/completeness versus absent publication authority; self-review descriptor ownership, membership stability and root-lock binding; run `git diff --check`, commit only task files and retain full commands/actual RED/GREEN evidence in the task report. Root owns plans/ledgers and independent review.

## Remaining integration

This supplies complete observations of the selected source tree, not a claim that every semantic dependency lives inside it. External constitution/glossary/product inputs must also be bound by the eventual complete-bundle owner under one coherent validation scope; sequential snapshots do not create an atomic cross-tree read set. Candidate creation, lifecycle proposals, edit-scope authority, semantic assessment, projected binding validation and durable intent/recovery remain separate integrations. The existing completion owners must integrate run-local/manual acceptance and final export; provider write scope, history/graph retention, all managed producers, bounded repair and final verification remain required.
