# RE v2 Polyrepo Source Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new RE v2 runs pin one atomic composite snapshot containing exactly the declared, clean Git source roots while preserving continuation of existing protocol `2.0` runs.

**Architecture:** A new `workspace_snapshot` module preflights declared sources, proves that every owning Git repository is clean, and materializes only the declared subtrees at pinned commits. The existing snapshot store gains a protocol-`2.1` composite manifest variant and retains its atomic marker/publication machinery; CLI creation binds the partition source set to that committed manifest before creating or activating a run.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, subprocess Git plumbing, canonical JSON/SHA-256, pytest, existing RE v2 append-only stores.

**Spec:** `docs/superpowers/specs/2026-08-17-re-v2-polyrepo-source-snapshot-design.md`

## File structure

- `src/harness/re_v2/model.py` owns immutable engine-protocol and run-manifest
  kind compatibility; it does not inspect filesystems.
- `src/harness/re_v2/snapshot.py` owns canonical snapshot/component manifests,
  immutable byte validation, pinned Git-tree materialization, and atomic
  bundle/marker publication.
- `src/harness/re_v2/workspace_snapshot.py` owns declared-source resolution,
  aggregate clean-Git preflight, composite-tree assembly, and partition
  identity derived from committed components.
- `src/echelon/cli.py` owns command ordering: discover, capture, bind partition,
  create run, activate run, then shadow or execute.
- `src/harness/re_v2/recovery.py` owns fail-closed validation order before any
  candidate/provider side effect. `status.py` remains an authority replay that
  does not read source bytes.
- `tests/unit/test_re_v2_workspace_snapshot.py` owns the new source-set and
  composite capture contract. Existing snapshot, CLI, recovery, status, and
  integration suites retain their narrower authority boundaries.

## Global Constraints

- New runs pin engine protocol `2.1` and snapshot kind `workspace-git-composite`.
- Existing protocol `2.0` manifests with `git-worktree` or `content-snapshot` remain readable and continuable without rewriting any authority.
- Every declared source for a new run must be owned by a Git repository inside the workspace and that repository must be clean.
- Clean means no staged, tracked, untracked non-ignored, conflicted, dirty-submodule, mismatched-submodule, or uninitialized-submodule state.
- Ignored paths do not make a source dirty and do not enter the snapshot.
- Dirty-source failure occurs before `runs/<run-id>` creation and before `runs/.current-re` mutation.
- The diagnostic names every offending source and recommends commit, stash including untracked files, or revert/remove.
- Snapshot paths, IDs, component order, manifest bytes, and partition binding are canonical and deterministic.
- Tracked symlinks, special files, escaping paths, duplicate IDs, and overlapping declared roots fail closed.
- Snapshot publication remains no-replace, commit-marker-gated, fsynced, crash-recoverable, and offline for recursive submodules.
- Providers receive one immutable snapshot root and never read the live checkout.
- RE v1 dispatch and all existing v1 run artifacts remain isolated from v2.

---

### Task 1: Protocol and snapshot-kind compatibility

**Files:**
- Modify: `src/harness/re_v2/model.py:14-16,443-510`
- Modify: `src/harness/re_v2/__init__.py:1-5`
- Modify: `src/harness/re_v2/run_store.py:8-15,163-169`
- Test: `tests/unit/test_re_v2_model.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces: `RE_V2_PROTOCOL = "2.1"` for new runs.
- Produces: `RE_V2_SUPPORTED_PROTOCOLS = ("2.0", "2.1")` for immutable-run loading.
- Produces: `SnapshotKind = Literal["git-worktree", "content-snapshot", "workspace-git-composite"]`.
- Enforces: protocol `2.0` pairs only with legacy kinds; protocol `2.1` pairs only with `workspace-git-composite`.

- [ ] **Step 1: Write failing model tests for protocol/kind pairing**

Add helpers that replace only the requested `RunManifest` fields, then add:

```python
@pytest.mark.unit
@pytest.mark.parametrize("kind", ("git-worktree", "content-snapshot"))
def test_protocol_20_accepts_only_legacy_snapshot_kinds(kind: str) -> None:
    manifest = replace(_manifest(), engine_protocol_version="2.0", source_snapshot_kind=kind)
    assert RunManifest.from_json_dict(manifest.to_json_dict()) == manifest


@pytest.mark.unit
def test_protocol_21_requires_composite_snapshot_kind() -> None:
    manifest = replace(
        _manifest(),
        engine_protocol_version="2.1",
        source_snapshot_kind="workspace-git-composite",
    )
    assert RunManifest.from_json_dict(manifest.to_json_dict()) == manifest
    with pytest.raises(ReV2ModelError, match="protocol 2.1 requires"):
        replace(manifest, source_snapshot_kind="git-worktree")


@pytest.mark.unit
def test_protocol_20_rejects_composite_snapshot_kind() -> None:
    with pytest.raises(ReV2ModelError, match="protocol 2.0 requires"):
        replace(
            _manifest(),
            engine_protocol_version="2.0",
            source_snapshot_kind="workspace-git-composite",
        )
```

- [ ] **Step 2: Run the new model tests and verify RED**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q \
  tests/unit/test_re_v2_model.py::test_protocol_20_accepts_only_legacy_snapshot_kinds \
  tests/unit/test_re_v2_model.py::test_protocol_21_requires_composite_snapshot_kind \
  tests/unit/test_re_v2_model.py::test_protocol_20_rejects_composite_snapshot_kind
```

Expected: collection or construction fails because `workspace-git-composite` and protocol `2.1` are unsupported.

- [ ] **Step 3: Implement explicit creation and supported protocol constants**

Use these contracts in `model.py`:

```python
RE_V2_ENGINE = "re-v2"
RE_V2_PROTOCOL = "2.1"
RE_V2_SUPPORTED_PROTOCOLS = ("2.0", "2.1")
SnapshotKind = Literal[
    "git-worktree",
    "content-snapshot",
    "workspace-git-composite",
]
```

Change `RunManifest.source_snapshot_kind` to `SnapshotKind`. In
`RunManifest.__post_init__`, accept only supported protocols and enforce the
exact pairing:

```python
legacy_kinds = {"git-worktree", "content-snapshot"}
if self.engine_protocol_version == "2.0":
    if self.source_snapshot_kind not in legacy_kinds:
        _error("protocol 2.0 requires a legacy source snapshot kind")
elif self.engine_protocol_version == "2.1":
    if self.source_snapshot_kind != "workspace-git-composite":
        _error("protocol 2.1 requires workspace-git-composite")
else:
    _error("unsupported engine protocol version")
```

Export `RE_V2_SUPPORTED_PROTOCOLS` and `SnapshotKind` from `__init__.py`.
Change `run_store._validate_supported_manifest()` to membership in
`RE_V2_SUPPORTED_PROTOCOLS`, preserving the recorded engine/protocol in its
error. Change `test_re_v2_model.valid_run_manifest_dict()` to use the new
creation protocol with `workspace-git-composite`; keep
`test_re_v2_run_store._manifest()` explicitly pinned to `2.0`/`git-worktree`
so the existing run-store suite remains a legacy-continuation proof.

- [ ] **Step 4: Add run-store round-trip tests for both protocols**

```python
@pytest.mark.unit
@pytest.mark.parametrize(
    ("protocol", "kind"),
    (("2.0", "git-worktree"), ("2.0", "content-snapshot"),
     ("2.1", "workspace-git-composite")),
)
def test_run_store_round_trips_each_supported_protocol_kind(
    tmp_path: Path, protocol: str, kind: str
) -> None:
    run_dir = tmp_path / f"re-{protocol.replace('.', '')}"
    manifest = replace(
        _manifest(run_id=run_dir.name),
        engine_protocol_version=protocol,
        source_snapshot_kind=kind,
    )
    create_run_store(run_dir, manifest)
    assert load_run_manifest(run_dir) == manifest
```

- [ ] **Step 5: Run the model and run-store suites**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_model.py tests/unit/test_re_v2_run_store.py`

Expected: all tests pass.

- [ ] **Step 6: Commit protocol compatibility**

```bash
git add src/harness/re_v2/model.py src/harness/re_v2/__init__.py \
  src/harness/re_v2/run_store.py tests/unit/test_re_v2_model.py \
  tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): pin composite snapshot protocol"
```

---

### Task 2: Aggregate clean-source preflight

**Files:**
- Create: `src/harness/re_v2/workspace_snapshot.py`
- Create: `tests/unit/test_re_v2_workspace_snapshot.py`

**Interfaces:**
- Consumes: `echelon.workspace_model.WorkspaceManifest` and `SourceRoot`.
- Produces: `WorkspaceSourceProof(source_id, git_role, workspace_path, repository, repository_path, commit)`.
- Produces: `WorkspaceCapturePlan(workspace_root, sources, repositories)`.
- Produces: `plan_clean_workspace_sources(workspace_root: Path, sources: Iterable[object]) -> WorkspaceCapturePlan`.
- Raises: `ReV2WorkspaceSourceError`, a `ReV2SnapshotError` subclass, containing an aggregated actionable diagnostic.

- [ ] **Step 1: Create Git fixture helpers and failing clean/dirty tests**

The test helper must initialize commits without relying on global Git identity:

```python
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, text=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test"},
    ).stdout


def _clean_repo(path: Path, tracked: Mapping[str, str]) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    for relative, payload in tracked.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "fixture")
    return path
```

Add tests for two clean child repos, staged changes, tracked changes,
untracked files, ignored files, and a non-Git source. The aggregate assertion
must cover all dirty IDs and guidance:

```python
@pytest.mark.unit
def test_preflight_aggregates_dirty_sources_and_remediation(tmp_path: Path) -> None:
    first = _clean_repo(tmp_path / "sources" / "first", {"a.py": "a\n"})
    second = _clean_repo(tmp_path / "sources" / "second", {"b.py": "b\n"})
    (first / "a.py").write_text("changed\n", encoding="utf-8")
    (second / "new.py").write_text("new\n", encoding="utf-8")

    with pytest.raises(ReV2WorkspaceSourceError) as exc:
        plan_clean_workspace_sources(tmp_path, _sources(first, second))

    message = str(exc.value)
    assert "first" in message and "second" in message
    assert "modified" in message and "untracked" in message
    assert "commit" in message.lower()
    assert "stash" in message.lower() and "untracked" in message.lower()
    assert "revert" in message.lower()
```

- [ ] **Step 2: Run preflight tests and verify RED**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py -k preflight`

Expected: collection fails because `workspace_snapshot` does not exist.

- [ ] **Step 3: Implement canonical source resolution and cleanliness proof**

Define immutable operational proofs:

```python
@dataclass(frozen=True, slots=True)
class WorkspaceSourceProof:
    source_id: str
    git_role: str
    workspace_path: str
    repository: Path
    repository_path: str
    commit: str


@dataclass(frozen=True, slots=True)
class WorkspaceCapturePlan:
    workspace_root: Path
    sources: tuple[WorkspaceSourceProof, ...]
    repositories: tuple[Path, ...]
```

For each source, validate its safe ID and canonical relative path, reject
symlinked/missing roots, resolve `git rev-parse --show-toplevel`, require the
repository to remain inside the workspace, and compute the declared path
relative to the repository. Reject duplicate and ancestor/descendant declared
paths.

For every distinct repository run:

```bash
git rev-parse HEAD^{commit}
git status --porcelain=v1 -z --untracked-files=all --ignore-submodules=none
git submodule status --recursive
```

Parse porcelain status into bounded categories without dropping an offending
source. Treat a leading `-`, `+`, or `U` in recursive submodule status as a
failure. Sort source proofs by `(source_id, workspace_path)` and repositories by
canonical workspace-relative path.

- [ ] **Step 4: Add ignored-file and shared-repository tests**

```python
@pytest.mark.unit
def test_preflight_ignores_git_ignored_dependency_symlinks(tmp_path: Path) -> None:
    repo = _clean_repo(
        tmp_path / "repo",
        {".gitignore": "node_modules/\n", "src/app.py": "pass\n"},
    )
    binary = repo / "node_modules" / ".bin" / "tool"
    binary.parent.mkdir(parents=True)
    binary.symlink_to("../tool.js")
    plan = plan_clean_workspace_sources(tmp_path, _sources(repo))
    assert plan.sources[0].commit == _git(repo, "rev-parse", "HEAD").strip()


@pytest.mark.unit
def test_preflight_allows_nonoverlapping_subtrees_in_one_clean_repo(tmp_path: Path) -> None:
    repo = _clean_repo(tmp_path / "mono", {"apps/a/a.py": "a\n", "apps/b/b.py": "b\n"})
    sources = (_source("a", "mono/apps/a"), _source("b", "mono/apps/b"))
    plan = plan_clean_workspace_sources(tmp_path, sources)
    assert len(plan.repositories) == 1
    assert [proof.repository_path for proof in plan.sources] == ["apps/a", "apps/b"]
```

- [ ] **Step 5: Run preflight tests**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py -k preflight`

Expected: all preflight tests pass.

- [ ] **Step 6: Commit clean-source preflight**

```bash
git add src/harness/re_v2/workspace_snapshot.py tests/unit/test_re_v2_workspace_snapshot.py
git commit -m "feat(re-v2): require clean declared sources"
```

---

### Task 3: Composite manifest schema and strict validation

**Files:**
- Modify: `src/harness/re_v2/snapshot.py:48-75,118-194,1079-1082,1370-1465`
- Modify: `src/harness/re_v2/workspace_snapshot.py`
- Test: `tests/unit/test_re_v2_snapshot.py`
- Test: `tests/unit/test_re_v2_workspace_snapshot.py`

**Interfaces:**
- Produces: `SnapshotComponent(source_id, git_role, workspace_path, repository_path, commit, submodules, tree_digest)`.
- Extends: `SnapshotManifest.components: tuple[SnapshotComponent, ...] | None` and `selection_policy: str | None` without changing legacy manifest bytes.
- Produces: `publish_workspace_snapshot_tree(prepared_root, destination_root, components, fault_hook=None) -> CapturedSnapshot`.
- Produces: `load_snapshot_manifest(snapshot: CapturedSnapshot) -> SnapshotManifest` for partition binding and validation.

- [ ] **Step 1: Write failing canonical composite-manifest tests**

```python
@pytest.mark.unit
def test_composite_manifest_identity_includes_canonical_components(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared"
    (prepared / "sources" / "api").mkdir(parents=True)
    (prepared / "sources" / "api" / "app.py").write_text("pass\n", encoding="utf-8")
    component = SnapshotComponent(
        source_id="api",
        git_role="source",
        workspace_path="sources/api",
        repository_path=".",
        commit="a" * 40,
        submodules=(),
        tree_digest=content_digest([
            {
                "digest": content_digest(b"pass\n"),
                "mode": 0o644,
                "path": "app.py",
                "size": 5,
            }
        ]),
    )
    snapshot = publish_workspace_snapshot_tree(
        prepared, tmp_path / "snapshots", (component,)
    )
    manifest = load_snapshot_manifest(snapshot)
    assert manifest.kind == "workspace-git-composite"
    assert manifest.capture_version == 2
    assert manifest.components == (component,)
    validate_source_snapshot(snapshot)
```

Add parameterized tamper cases for missing/extra component fields, duplicate or
unsorted source IDs, unsafe workspace/repository paths, malformed commit,
noncanonical submodules, mismatched component tree digest, and composite kind
with `git` not null.

- [ ] **Step 2: Run composite schema tests and verify RED**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_snapshot.py -k composite_manifest`

Expected: import or construction fails because the component schema and
composite publisher are absent.

- [ ] **Step 3: Add a backward-compatible manifest variant**

Keep legacy `identity_dict()` and JSON fields byte-for-byte unchanged when
`components is None`. For the composite variant require:

```python
{
    "capture_version": 2,
    "components": [component.to_json_dict() for component in components],
    "entries": [entry.to_json_dict() for entry in entries],
    "exclusions": [],
    "git": None,
    "kind": "workspace-git-composite",
    "selection_policy": "declared-clean-git-tree-v1",
}
```

`SnapshotComponent.submodules` is a sorted tuple of `(path, commit)` pairs.
`SnapshotComponent.to_json_dict()` must emit exactly:

```python
{
    "commit": self.commit,
    "git_role": self.git_role,
    "repository_path": self.repository_path,
    "source_id": self.source_id,
    "submodules": [{"commit": commit, "path": path} for path, commit in self.submodules],
    "tree_digest": self.tree_digest,
    "workspace_path": self.workspace_path,
}
```

Strictly parse fields and types using `_exact_json_object`, `_json_string`, and
the existing nonfinite rejection path. Require the exact selection policy for
composite manifests and omit the field entirely for legacy manifests. Update
`_marker_payload()` to read the manifest capture version so legacy markers
remain version `1` and composite markers use version `2`.

- [ ] **Step 4: Implement prepared-tree publication and component validation**

`publish_workspace_snapshot_tree()` must inventory only regular files, verify
each component path selects exactly its own inventory subset, recompute the
component tree digest from paths relative to that component, and reject files
outside all components. It then copies the prepared tree into a private
snapshot stage, re-inventories source and stage, writes the exact owner and
manifest, normalizes permissions, fsyncs, and calls the existing
`_publish_staged_bundle(..., source_repo=None)` path.

Validation recomputes component subsets and digests from the committed flat
inventory in addition to the existing byte/mode/size checks.

- [ ] **Step 5: Prove legacy manifest and marker bytes remain valid**

Add a test that captures a legacy clean Git snapshot and a legacy copied
snapshot, records their manifest/marker canonical structures, validates both,
and asserts neither contains `components`. Retain all existing strict schema
and transient-I/O taxonomy tests.

- [ ] **Step 6: Run snapshot suites**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_snapshot.py \
  tests/unit/test_re_v2_workspace_snapshot.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit composite manifest storage**

```bash
git add src/harness/re_v2/snapshot.py src/harness/re_v2/workspace_snapshot.py \
  tests/unit/test_re_v2_snapshot.py tests/unit/test_re_v2_workspace_snapshot.py
git commit -m "feat(re-v2): store composite source snapshots"
```

---

### Task 4: Pinned multi-repository materialization

**Files:**
- Modify: `src/harness/re_v2/snapshot.py:1200-1368`
- Modify: `src/harness/re_v2/workspace_snapshot.py`
- Test: `tests/unit/test_re_v2_workspace_snapshot.py`

**Interfaces:**
- Consumes: `WorkspaceCapturePlan` from Task 2.
- Produces: `capture_workspace_snapshot(workspace_root, sources, destination_root, fault_hook=None) -> CapturedSnapshot`.
- Uses: `publish_workspace_snapshot_tree()` from Task 3.

- [ ] **Step 1: Write the production-shape failing test**

```python
@pytest.mark.unit
def test_composite_capture_uses_declared_repositories_not_orchestration_root(
    tmp_path: Path,
) -> None:
    workspace = _clean_repo(
        tmp_path / "workspace",
        {".gitignore": "/sources/*\n!/sources/README.md\n", "sources/README.md": "repos\n"},
    )
    tooling_link = workspace / ".claude" / "skills" / "tool" / "SKILL.md"
    tooling_link.parent.mkdir(parents=True)
    tooling_link.symlink_to("../../../../outside-skill.md")
    first = _clean_repo(workspace / "sources" / "first", {"src/a.py": "a\n"})
    second = _clean_repo(workspace / "sources" / "second", {"src/b.py": "b\n"})
    ignored_link = second / "node_modules" / ".bin" / "tool"
    (second / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _git(second, "add", ".gitignore")
    _git(second, "commit", "-m", "ignore dependencies")
    ignored_link.parent.mkdir(parents=True)
    ignored_link.symlink_to("../tool.js")

    snapshot = capture_workspace_snapshot(
        workspace,
        (_source("first", "sources/first"), _source("second", "sources/second")),
        tmp_path / "snapshots",
    )

    assert (snapshot.read_root / "sources/first/src/a.py").read_text() == "a\n"
    assert (snapshot.read_root / "sources/second/src/b.py").read_text() == "b\n"
    assert not (snapshot.read_root / ".claude").exists()
    assert not (snapshot.read_root / "sources/README.md").exists()
    assert not (snapshot.read_root / "sources/second/node_modules").exists()
```

- [ ] **Step 2: Run the production-shape test and verify RED**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py::test_composite_capture_uses_declared_repositories_not_orchestration_root`

Expected: fails because `capture_workspace_snapshot()` is absent.

- [ ] **Step 3: Extract reusable pinned-worktree materialization**

In `snapshot.py`, expose
`materialize_pinned_git_tree(repository: Path, commit: str, staging_parent: Path, *, fault_hook: FaultHook | None = None) -> ContextManager[tuple[Path, tuple[dict[str, str], ...]]]`.

It must use the existing detached-worktree, local recursive submodule,
worktree-repair, forced deregistration, and failure cleanup logic. The yielded
path is private and writable; the returned submodule identities are sorted
`{"commit", "path"}` dictionaries. Cleanup runs on normal exit and every
exception, leaving no registered worktree.

- [ ] **Step 4: Implement composite capture around the preflight proof**

`capture_workspace_snapshot()` must:

1. call `plan_clean_workspace_sources()` before creating a snapshot stage;
2. acquire one source lock per distinct repository in canonical order;
3. rerun preflight and compare exact proofs;
4. materialize each distinct repository once at its pinned commit;
5. inventory and copy each declared repository-relative subtree to its
   workspace-relative destination in a private prepared tree;
6. reject a missing subtree, any collision, tracked symlink, or special file;
7. derive component tree digests and recursive submodule paths relative to each
   declared subtree;
8. rerun preflight and reject any changed proof; and
9. publish through `publish_workspace_snapshot_tree()`.

The function removes temporary worktrees and prepared trees on every exit.

- [ ] **Step 5: Add subtree, shared-repo, submodule, and mutation tests**

Add exact tests showing:

- two non-overlapping declared subtrees from one repository are materialized
  once and appear under their workspace paths;
- recursive submodule bytes and identities are present without network calls;
- an uninitialized submodule fails before publication;
- a tracked symlink fails closed;
- changing repository `HEAD` or creating an untracked file at the
  `before_publish` fault hook rejects the capture; and
- no temporary Git worktree remains registered after each failure.

For mutation, use a real hook:

```python
def mutate(point: str) -> None:
    if point == "before_publish":
        (repo / "late.py").write_text("late\n", encoding="utf-8")

with pytest.raises(ReV2WorkspaceSourceError, match="changed during capture"):
    capture_workspace_snapshot(workspace, sources, destination, fault_hook=mutate)
assert "snapshot-stage" not in _git(repo, "worktree", "list", "--porcelain")
```

- [ ] **Step 6: Run workspace and legacy snapshot tests**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py \
  tests/unit/test_re_v2_snapshot.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit multi-repository capture**

```bash
git add src/harness/re_v2/snapshot.py src/harness/re_v2/workspace_snapshot.py \
  tests/unit/test_re_v2_snapshot.py tests/unit/test_re_v2_workspace_snapshot.py
git commit -m "feat(re-v2): capture clean workspace source sets"
```

---

### Task 5: CLI creation and exact partition binding

**Files:**
- Modify: `src/echelon/cli.py:10228-10284,10430-10583`
- Modify: `tests/unit/test_cli_re_lifecycle.py:1008-1094`
- Test: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Consumes: `capture_workspace_snapshot()` and `load_snapshot_manifest()`.
- Changes: `_re_v2_partition_manifest_id(workspace_manifest, snapshot)` validates exact `(source_id, git_role, workspace_path)` equality before hashing.
- Produces: `composite_partition_manifest_id(snapshot_manifest) -> str`, using partition protocol `re-v2-partition-v2`, for creation and recovery.
- Guarantees: source preflight/capture and partition validation precede `_new_re_v2_run_id()`, `create_run_store()`, and `_activate_re_v2_run()`.

- [ ] **Step 1: Add a reusable clean-Git CLI fixture**

Replace non-Git v2 creation fixtures with:

```python
def _init_clean_v2_source(project: Path) -> None:
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\nversion = '0.1.0'\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "add", "pyproject.toml"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.test", "commit", "-m", "fixture"],
        check=True, capture_output=True,
    )
```

Update shadow/live tests to assert protocol `2.1`, kind
`workspace-git-composite`, and the component source set.

- [ ] **Step 2: Write failing no-side-effect and source-set tests**

```python
@pytest.mark.unit
def test_re_v2_dirty_polyrepo_fails_before_run_or_pointer_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, sources = _polyrepo_workspace(tmp_path)
    old_pointer = workspace / "runs" / ".current-re"
    old_pointer.parent.mkdir()
    old_pointer.write_text("re-existing\n", encoding="utf-8")
    (sources[1] / "dirty.py").write_text("dirty\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as exc:
        _cmd_re_run(["--engine", "v2", "--shadow"])

    assert exc.value.code == 2
    assert old_pointer.read_text() == "re-existing\n"
    assert sorted(path.name for path in (workspace / "runs").iterdir()) == [".current-re"]
    error = capsys.readouterr().err
    assert "dirty" in error and "stash" in error and "commit" in error
```

Add a test that passes a forged workspace manifest/source component mismatch
and asserts no run/pointer mutation.

- [ ] **Step 3: Run the new CLI tests and verify RED**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_cli_re_lifecycle.py -k 'v2 and (dirty_polyrepo or source_set or shadow_creation or live_creation)'`

Expected: old root snapshot behavior either rejects tooling symlinks or creates
a protocol `2.0` run instead of the required result.

- [ ] **Step 4: Route new creation through the composite capture**

In `_run_re_v2_create()`:

```python
workspace_manifest = discover_workspace(workspace_root)
snapshot = capture_workspace_snapshot(
    workspace_root,
    workspace_manifest.sources,
    _re_v2_snapshot_root(workspace_root),
)
partition_manifest_id = _re_v2_partition_manifest_id(
    workspace_manifest, snapshot
)
```

Only after those calls allocate the run ID, construct the protocol `2.1`
manifest, persist it, and activate it.

`_re_v2_partition_manifest_id()` must load the committed composite manifest,
compare its sorted `(source_id, git_role, workspace_path)` triples with the
validated live workspace manifest, then call
`composite_partition_manifest_id()`. That function hashes partition protocol
`re-v2-partition-v2`, the composite snapshot ID, and the component-backed
triples. It must never re-read source bytes.

- [ ] **Step 5: Preserve protocol `2.0` continuation routing**

Keep `_load_re_v2_snapshot()` kind-driven. Add one test that creates a legacy
protocol `2.0` copied snapshot/run, changes the live project after capture, and
asserts `_cmd_re_continue([])` reads the pinned legacy snapshot and completes.

- [ ] **Step 6: Run CLI lifecycle tests**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py`

Expected: all tests pass.

- [ ] **Step 7: Commit CLI integration**

```bash
git add src/echelon/cli.py tests/unit/test_cli_re_lifecycle.py \
  tests/unit/test_cli_typer_app.py
git commit -m "fix(re-v2): bind runs to declared source snapshots"
```

---

### Task 6: Recovery and tamper-proof composite authority

**Files:**
- Modify: `src/harness/re_v2/recovery.py`
- Verify unchanged boundary: `src/harness/re_v2/status.py`
- Modify: `tests/unit/test_re_v2_recovery.py`
- Modify: `tests/unit/test_re_v2_status.py`
- Modify: `tests/integration/test_re_v2_kernel_recovery.py`

**Interfaces:**
- Consumes: protocol/kind-paired `RunManifest` and strict composite snapshot validation.
- Guarantees: recovery validates committed composite components before leases, candidates, provider processes, ledger repair, or publication.
- Preserves: status replay remains source-byte-independent and legacy protocol `2.0` status remains supported.

- [ ] **Step 1: Write failing recovery-order and tamper tests**

Build a protocol `2.1` run around a committed composite fixture, tamper one
component commit/tree digest/source path at a time, recanonicalize the manifest
and marker to isolate semantic validation, then assert:

```python
with pytest.raises(ReV2SnapshotIntegrityError):
    recover_run(context)
assert not context.paths.candidates.exists()
assert not context.paths.ledger.exists()
assert executor_calls == []
```

Add a source-set mismatch case where run partition identity was derived from a
different component set and assert recovery fails before execution.

- [ ] **Step 2: Run recovery tests and verify RED**

Run: `/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_recovery.py -k composite tests/integration/test_re_v2_kernel_recovery.py -k composite`

Expected: fails because component and partition authority are not understood.

- [ ] **Step 3: Enforce protocol-aware snapshot authority before side effects**

At recovery bootstrap, validate the protocol/kind pair, snapshot marker,
canonical composite manifest, component subsets/digests, and require
`manifest.partition_manifest_id == composite_partition_manifest_id(snapshot_manifest)`
before inspecting or mutating leases and candidates. Do not make status read
snapshot bytes; status continues replaying manifest/events/ledger only.

- [ ] **Step 4: Add explicit legacy recovery coverage**

Run the same recovery fixture once as protocol `2.0`/`git-worktree` and once as
protocol `2.0`/`content-snapshot`. Assert both reach their prior deterministic
event/ledger result with no manifest rewrite.

- [ ] **Step 5: Run recovery and status suites**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_recovery.py \
  tests/unit/test_re_v2_status.py \
  tests/integration/test_re_v2_kernel_recovery.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit recovery authority**

```bash
git add src/harness/re_v2/recovery.py tests/unit/test_re_v2_recovery.py \
  tests/unit/test_re_v2_status.py \
  tests/integration/test_re_v2_kernel_recovery.py
git commit -m "fix(re-v2): validate composite authority on recovery"
```

---

### Task 7: Composite crash, concurrency, and engine-isolation matrix

**Files:**
- Modify: `tests/unit/test_re_v2_workspace_snapshot.py`
- Modify: `tests/integration/test_re_v2_kernel_recovery.py`
- Modify: `tests/integration/test_re_v2_v1_isolation.py`
- Modify: `tests/unit/test_dry_run_script.py`
- Modify: `scripts/bash/dry-run.sh`

**Interfaces:**
- Exercises the production functions from Tasks 1-6 without replacing snapshot, planner, controller, recovery, or run-store internals.
- Produces release evidence for every composite publication boundary and v1 isolation.

- [ ] **Step 1: Add composite publication fault-prefix tests**

Parameterize every durable boundary used by composite publication:

```python
COMPOSITE_FAULTS = (
    "source_worktree_added",
    "source_tree_copied",
    "before_publish",
    "source_installed",
    "manifest_installed",
    "permissions_normalized",
    "bundle_fsynced",
    "final_promoted",
    "marker_linked",
    "marker_root_fsynced",
    "marker_destination_fsynced",
    "marker_temporary_cleaned",
    "final_validated",
)
```

For each boundary crash once, recreate the capture object from disk, retry, and
assert one committed marker/bundle pair, strict validation success, exact
component inventory, no stale stage, and no registered temporary worktree.

- [ ] **Step 2: Add same-source-set concurrency coverage**

Launch two subprocesses against the same clean two-repository fixture and
destination. Both must return the same snapshot ID; exactly one committed
bundle and marker may exist; each repository's `git worktree list --porcelain`
must contain no temporary capture path.

- [ ] **Step 3: Extend v1/v2 isolation**

Add a case where an existing v1 run is active, v2 composite preflight fails on
a dirty source, and v1 state/events/artifacts plus `.current-re` remain
byte-identical. Add a successful composite v2 case and assert it never invokes
the v1 controller or reads v1 `re/state.json` as authority.

- [ ] **Step 4: Extend dry-run static contracts**

Require the v2 creation route to import/call `capture_workspace_snapshot`,
require capture to precede `create_run_store` and `_activate_re_v2_run`, and
mutation-test removal/reordering of those calls. Keep all existing command and
bundle checks.

- [ ] **Step 5: Run the fault and isolation matrix**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py \
  tests/unit/test_dry_run_script.py
bash scripts/bash/dry-run.sh
```

Expected: all pytest cases pass; dry run imports every RE v2 module and reports
all bundle checks passed.

- [ ] **Step 6: Commit release-proof tests**

```bash
git add tests/unit/test_re_v2_workspace_snapshot.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py tests/unit/test_dry_run_script.py \
  scripts/bash/dry-run.sh
git commit -m "test(re-v2): prove polyrepo snapshot recovery"
```

---

### Task 8: Operator documentation and compatibility record

**Files:**
- Modify: `docs/runbooks/re-v2-kernel-pilot.md`
- Modify: `docs/superpowers/specs/2026-08-14-re-v2-execution-kernel-design.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `CHANGELOG.md`
- Test: `tests/unit/test_re_v2_workspace_snapshot.py`

**Interfaces:**
- Documents exact creation preconditions, protocol compatibility, failure remediation, and snapshot contents.
- Does not claim L1-L4, synthesis, semantic audit, cross-run reuse, or partial operation.

- [ ] **Step 1: Write a diagnostic contract test**

Assert the final dirty-source error contains this semantic content without
requiring color or line wrapping:

```python
for phrase in (
    "RE v2 requires clean Git sources",
    "commit",
    "stash",
    "including untracked files",
    "revert or remove",
    "echelon re run --engine v2",
):
    assert phrase in message
```

- [ ] **Step 2: Update the pilot runbook**

Replace dirty/non-Git content-copy creation guidance with:

- new runs use protocol `2.1` composite declared-source snapshots;
- every declared source must be clean and Git-backed;
- ignored dependencies and orchestration tooling are outside the snapshot;
- the exact commit/stash/revert remediation command guidance;
- preflight failure does not create/activate a run;
- existing `2.0` runs continue against their pinned legacy snapshot; and
- changing source declarations or commits requires a new run.

- [ ] **Step 3: Update design, EGR, and changelog records**

Record the production-workspace finding and correction without marking later
EGR-165 through EGR-170 work complete. State that EGR-164 now supports the
clean-Git polyrepo L0 pilot and that dirty/non-Git inputs are intentionally
blocked.

- [ ] **Step 4: Run documentation-adjacent validation**

Run:

```bash
/Users/michalbachorik/work/echelon/.venv/bin/pytest -q tests/unit/test_re_v2_workspace_snapshot.py \
  tests/unit/test_dry_run_script.py
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 5: Commit operator documentation**

```bash
git add docs/runbooks/re-v2-kernel-pilot.md \
  docs/superpowers/specs/2026-08-14-re-v2-execution-kernel-design.md \
  docs/findings/echelon-grounded-review-register.md CHANGELOG.md \
  tests/unit/test_re_v2_workspace_snapshot.py
git commit -m "docs: require clean sources for RE v2"
```

---

### Task 9: Final verification and real OptaSearch preflight

**Files:**
- No production files unless verification exposes a regression.

**Interfaces:**
- Verifies the committed branch, installed CLI, actual workspace failure mode,
  and absence of unintended workspace mutations.

- [ ] **Step 1: Run the complete RE v2 acceptance matrix**

Run:

```bash
COLUMNS=200 /Users/michalbachorik/work/echelon/.venv/bin/pytest -q \
  tests/unit/test_re_v2_*.py \
  tests/unit/test_re_lifecycle.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_re_lock.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py \
  tests/unit/test_dry_run_script.py
```

Expected: zero failures.

- [ ] **Step 2: Run bundle and repository integrity checks**

Run:

```bash
bash scripts/bash/dry-run.sh
git diff --check
git status --short
```

Expected: dry run passes all checks, diff check emits nothing, and status is
clean.

- [ ] **Step 3: Install the committed CLI**

Run: `bash scripts/install.sh`

Expected: installer exits zero and reports `echelon 4.0.2` from the branch.

- [ ] **Step 4: Test preflight on the real OptaSearch workspace**

From `/Users/michalbachorik/work/optasearch`, record the active pointer and
existing run directories, then run:

```bash
echelon re run --engine v2 --shadow
```

Expected while declared sources remain dirty: exit code `2`; one aggregated
clean-source diagnostic naming every dirty/non-Git source; no symlink error;
no new `runs/<run-id>`; and byte-identical `runs/.current-re`.

Do not commit, stash, revert, remove, or otherwise alter source worktrees during
this verification.

- [ ] **Step 5: Run a clean representative polyrepo end to end**

Create a temporary orchestration repository with ignored `sources/*`, two clean
real Git child repositories, an orchestration tooling symlink, and ignored
dependency symlinks. With a temporary `ECHELON_HOME`, run:

```bash
echelon re run --engine v2 --shadow
echelon re continue
echelon re status --json
```

Expected: protocol `2.1`, snapshot kind `workspace-git-composite`, L0 `2/2`
accepted, two generated/certified artifacts, zero unknown token dispatches,
terminal `complete`, strict snapshot validation success, and byte-identical
projection replay.

- [ ] **Step 6: Record final evidence and commit any verification-only test correction**

If no correction is necessary, leave the verified commit unchanged. If a test
fixture—not production semantics—requires correction, rerun Steps 1-5 before
committing that correction with:

```bash
git add tests/unit/test_re_v2_workspace_snapshot.py \
  tests/unit/test_re_v2_snapshot.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py
git commit -m "test(re-v2): correct polyrepo verification fixture"
```
