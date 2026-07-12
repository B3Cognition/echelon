# Workspace Reverse Engineering Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the latest validated reverse-engineering knowledge as source-owned, directly reusable workspace context under `re/`, while preserving fingerprint/profile freshness controls, last-known-good rollback, empty-source success, and normal feature-branch Git behavior.

**Architecture:** Add a typed published registry at `re/index.json`, an ignored fingerprint cache at `re/.cache/`, and a deterministic single-writer publication transaction. RE agents write source-owned and workspace synthesis documents into run staging; Python binds them to planner fingerprints, validates them, atomically publishes them, and pins the resulting generation in squad state. Existing `re_policy` values and `ReFingerprintProfile(full/full/5000/2500)` remain unchanged.

**Tech Stack:** Python 3 dataclasses and filesystem APIs, Typer, pytest, Bash RE extraction scripts, Markdown agent/workflow contracts, Git CLI.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-07-12-workspace-re-publication-design.md`.
- `workspace.sources[].id` is the durable source identity; duplicate IDs block planning and publication.
- Durable authority is `re/index.json`, `re/sources/**`, and `re/workspace/**`.
- Heavy artifacts live only under ignored `re/.cache/**`; `runs/<run-id>/re/**` remains staging and provenance.
- Publication writes `re/index.json` last and increments `generation` exactly once.
- Failed validation, failed replacement, or failed workspace synthesis leaves the previous generation byte-identical.
- Automatic publication accepts only complete RE output; `--allow-partial` relaxes quality completeness, never structural integrity.
- Empty sources are successful; unavailable sources retain last-known-good published knowledge; explicit configured removal is transactional.
- Feature runs consume canonical `re/` paths without copying them into the run directory.
- A run pins `re_generation`; any external generation change blocks before the next phase dispatch.
- Publication never commits automatically. Normal feature finalization stages tracked `re/` changes; standalone `--commit` is explicit.
- Preserve the existing effective profile and its override path: `profile=full`, `depth=full`, `max_lines_per_file=5000`, `git_history_limit=2500` unless resolved workspace configuration overrides it.
- Preserve existing `re_policy` CLI values and GOLDDIGGER Mode 2 focused-domain behavior; mode cleanup is outside this plan.

---

## File Structure

### New modules

- `src/harness/re_registry.py`: published schema dataclasses, path safety, layout creation, strict readers, canonical artifact map.
- `src/harness/re_lock.py`: publication lock ownership, active-run detection, stale-lock recovery.
- `src/harness/re_publication.py`: run validation, staging, source/workspace assembly, atomic replacement, rollback, publication result.
- `src/harness/re_migration.py`: one-way import of legacy `.echelon/cache/re/` entries into `re/.cache/`.
- `tests/unit/test_re_registry.py`: schema, path, layout, canonical artifact tests.
- `tests/unit/test_re_lock.py`: live owner, active run, and stale recovery tests.
- `tests/unit/test_re_publication.py`: complete/partial validation, lifecycle, transaction, and rollback tests.
- `tests/integration/test_re_publication_flow.py`: first run, unchanged second run, one-source refresh, and generation guard flow.
- `tests/integration/test_re_git_flow.py`: finalization and explicit standalone commit behavior.

### Existing modules and contracts

- `src/harness/re_cache.py`: move active cache root to `re/.cache` and retain legacy import helpers only.
- `src/harness/re_planner.py`: classify against published source manifests, retain policy semantics, detect unavailable/removed sources.
- `src/harness/re_materializer.py`: write planning/provenance files and refresh-only analysis manifest; return canonical paths for current sources without copying.
- `src/harness/squad.py`: resolve effective profile, pin generation, and enforce the pre-dispatch generation guard.
- `src/harness/squad_executors.py`: publish validated GOLDDIGGER Mode 1 output and replace run-local artifact state with canonical paths.
- `src/echelon/cli_app.py` and `src/echelon/cli.py`: expose `echelon re publish` and deterministic commit behavior.
- `src/echelon/workspace_git_migration.py`: scaffold the RE ownership boundary and verify tracked/ignored rules.
- `extension/scripts/bash/re/run-analysis.sh` and `extension/scripts/bash/re/extract-cross-repo.sh`: emit selected analysis under `runs/<run-id>/re/sources/<source-id>/`.
- `extension/agents/re/{analyzer,specifier,verifier,expander,validator,checklister,constituter}.md`: use source-owned staging paths and separate workspace synthesis.
- `extension/agents/exploration/golddigger.md`: report staging output before publication and canonical output after publication.
- `extension/workflow/phases/re-extract-*.md` and `extension/workflow/definition.yaml`: align context packs and outputs with the new staging contract.
- `extension/scripts/bash/finalize-run.sh`: stage tracked RE documents with feature artifacts.
- Existing RE, squad, CLI, shell, and static-contract tests: update expected paths while preserving policy/profile assertions.

---

### Task 1: Published Registry And Workspace Layout

**Files:**
- Create: `src/harness/re_registry.py`
- Create: `tests/unit/test_re_registry.py`
- Modify: `src/echelon/workspace_git_migration.py`
- Modify: `tests/unit/test_workspace_git_migration.py`

**Interfaces:**
- Produces: `ReRegistryPaths.for_workspace(workspace_root: Path) -> ReRegistryPaths`
- Produces: `PublishedReIndex.from_path(path: Path) -> PublishedReIndex`
- Produces: `load_published_index(workspace_root: Path) -> PublishedReIndex | None`
- Produces: `ensure_re_layout(workspace_root: Path) -> ReRegistryPaths`
- Produces: `canonical_re_artifacts(workspace_root: Path, index: PublishedReIndex) -> dict[str, object]`

- [ ] **Step 1: Write failing registry and layout tests**

```python
def test_ensure_re_layout_tracks_docs_and_ignores_runtime_dirs(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    assert paths.root == tmp_path / "re"
    entries = set(paths.gitignore.read_text().splitlines())
    assert {".cache/", ".staging/", ".locks/"} <= entries
    assert paths.sources.is_dir()
    assert paths.workspace.is_dir()


def test_load_published_index_rejects_unsafe_source_paths(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    (tmp_path / "re/index.json").write_text(json.dumps({
        "schema_version": 1,
        "generation": 1,
        "publication_status": "complete",
        "published_at": "2026-07-12T12:00:00Z",
        "published_from_run": "spec-1",
        "sources": {"api": {
            "path": "sources/api",
            "published_path": "../outside",
            "fingerprint": "sha256:abc",
            "profile_hash": "sha256:def",
            "status": "complete",
            "manifest": "re/sources/api/manifest.json",
        }},
        "workspace": {
            "manifest": "re/workspace/manifest.json",
            "overview": "re/workspace/overview.md",
            "relationships": "re/workspace/relationships.md",
            "contracts": "re/workspace/contracts.md",
        },
        "warnings": [],
    }))
    with pytest.raises(ReRegistryError, match="published_path"):
        load_published_index(tmp_path)
```

- [ ] **Step 2: Run the focused tests and confirm missing interfaces**

Run: `pytest tests/unit/test_re_registry.py tests/unit/test_workspace_git_migration.py -q`

Expected: FAIL because `harness.re_registry` and RE scaffolding do not exist.

- [ ] **Step 3: Implement strict schema and layout primitives**

```python
RE_SCHEMA_VERSION = 1
VALID_PUBLICATION_STATUSES = frozenset({"complete", "partial", "empty"})


@dataclass(frozen=True)
class ReRegistryPaths:
    root: Path
    index: Path
    sources: Path
    workspace: Path
    cache: Path
    staging: Path
    locks: Path
    gitignore: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> "ReRegistryPaths":
        root = workspace_root.resolve() / "re"
        return cls(root, root / "index.json", root / "sources", root / "workspace",
                   root / ".cache", root / ".staging", root / ".locks", root / ".gitignore")


@dataclass(frozen=True)
class PublishedSource:
    source_id: str
    source_path: str
    published_path: str
    fingerprint: str
    profile_hash: str
    status: str
    manifest: str


@dataclass(frozen=True)
class PublishedReIndex:
    schema_version: int
    generation: int
    publication_status: str
    published_at: str
    published_from_run: str
    sources: dict[str, PublishedSource]
    workspace: dict[str, str]
    warnings: tuple[str, ...]

    @classmethod
    def from_path(cls, path: Path) -> "PublishedReIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        return _parse_published_index(data, workspace_root=path.parent.parent)


def ensure_re_layout(workspace_root: Path) -> ReRegistryPaths:
    paths = ReRegistryPaths.for_workspace(workspace_root)
    for directory in (paths.root, paths.sources, paths.workspace, paths.cache,
                      paths.staging, paths.locks):
        directory.mkdir(parents=True, exist_ok=True)
    existing = paths.gitignore.read_text(encoding="utf-8") if paths.gitignore.exists() else ""
    lines = existing.splitlines()
    for required in (".cache/", ".staging/", ".locks/"):
        if required not in lines:
            lines.append(required)
    paths.gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def load_published_index(workspace_root: Path) -> PublishedReIndex | None:
    path = ReRegistryPaths.for_workspace(workspace_root).index
    return PublishedReIndex.from_path(path) if path.is_file() else None
```

Implement `_parse_published_index` with exact type checks, `generation >= 1`, source ID validation using `^[A-Za-z0-9._-]+$`, and relative-path containment under the workspace root. `canonical_re_artifacts` must return `re/index.json`, `re/workspace/manifest.json`, all source manifest paths, all source overview/spec paths read from source manifests, and no `.cache`, `.staging`, or `.locks` paths.

- [ ] **Step 4: Extend workspace migration without committing an empty index**

Have `migrate_workspace(..., write=True)` call `ensure_re_layout`, add `re/.gitignore` to staged paths, and leave `re/index.json` absent until first publication. Extend doctor findings so ignored `re/` is an error, while ignored `re/.cache`, `re/.staging`, and `re/.locks` are required.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_re_registry.py tests/unit/test_workspace_git_migration.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_registry.py src/echelon/workspace_git_migration.py tests/unit/test_re_registry.py tests/unit/test_workspace_git_migration.py
git commit -m "feat: add workspace re registry layout"
```

### Task 2: Publication Lock, Active Runs, And Recovery

**Files:**
- Create: `src/harness/re_lock.py`
- Create: `tests/unit/test_re_lock.py`

**Interfaces:**
- Consumes: `ReRegistryPaths`
- Produces: `RePublishLock.acquire(workspace_root: Path, owner_run_id: str, owner_run_dir: Path | None) -> RePublishLock`
- Produces: `find_other_active_runs(workspace_root: Path, owner_run_dir: Path | None) -> tuple[Path, ...]`
- Produces: `recover_stale_publish_lock(workspace_root: Path, *, stale_after_seconds: int = 3600) -> bool`

- [ ] **Step 1: Write lock and active-run tests**

```python
def test_second_live_publisher_cannot_acquire(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    with RePublishLock.acquire(tmp_path, "run-a", None):
        with pytest.raises(RePublishLocked, match="run-a"):
            RePublishLock.acquire(tmp_path, "run-b", None)


def test_owner_run_is_excluded_but_another_running_run_blocks(tmp_path: Path) -> None:
    owner = _write_run(tmp_path, "run-a", "running")
    other = _write_run(tmp_path, "run-b", "in_progress")
    assert find_other_active_runs(tmp_path, owner) == (other,)


def test_stale_lock_recovery_requires_dead_owner_and_no_active_run(tmp_path: Path) -> None:
    lock_dir = _write_lock(tmp_path, pid=999_999_999, run_id="old-run", age_seconds=7200)
    assert recover_stale_publish_lock(tmp_path, stale_after_seconds=3600)
    assert not lock_dir.exists()
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest tests/unit/test_re_lock.py -q`

Expected: FAIL because `harness.re_lock` does not exist.

- [ ] **Step 3: Implement atomic directory locking**

```python
ACTIVE_RUN_STATUSES = frozenset({"running", "in_progress"})


@dataclass
class RePublishLock:
    path: Path
    owner_run_id: str

    @classmethod
    def acquire(cls, workspace_root: Path, owner_run_id: str,
                owner_run_dir: Path | None) -> "RePublishLock":
        paths = ensure_re_layout(workspace_root)
        other_runs = find_other_active_runs(workspace_root, owner_run_dir)
        if other_runs:
            raise RePublicationActiveRun(tuple(str(path) for path in other_runs))
        lock_path = paths.locks / "publish.lock"
        try:
            lock_path.mkdir()
        except FileExistsError as exc:
            owner = _read_owner(lock_path)
            raise RePublishLocked(owner.get("run_id", "unknown")) from exc
        try:
            _write_json_atomic(lock_path / "owner.json", {
                "run_id": owner_run_id,
                "run_dir": str(owner_run_dir.resolve()) if owner_run_dir else None,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            shutil.rmtree(lock_path)
            raise
        return cls(lock_path, owner_run_id)

    def release(self) -> None:
        owner = _read_owner(self.path)
        if owner.get("run_id") != self.owner_run_id:
            raise RePublishLocked("lock ownership changed")
        shutil.rmtree(self.path)

    def __enter__(self) -> "RePublishLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
```

Scan `runs/*/state.json` and legacy `squad/*/state.json`; count only `running` and `in_progress`; compare resolved directories when excluding the owner. Recovery must refuse when `rollback-journal.json` says `replacing`, when the owner PID is live on the current host, or when the owner run is active. A different-host lock becomes recoverable only after the stale threshold and inactive-run check.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_re_lock.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_lock.py tests/unit/test_re_lock.py
git commit -m "feat: serialize workspace re publication"
```

### Task 3: Validation And Atomic Publication Transaction

**Files:**
- Create: `src/harness/re_publication.py`
- Create: `tests/unit/test_re_publication.py`
- Modify: `src/harness/re_fingerprint.py`
- Modify: `src/harness/re_planner.py`
- Modify: `tests/unit/test_re_fingerprint.py`
- Modify: `tests/unit/test_re_planner.py`

**Interfaces:**
- Consumes: `PublishedReIndex`, `ReRegistryPaths`, `RePublishLock`, `ReExecutionPlan`
- Produces: `ReFingerprintProfile.from_json_dict(data: Mapping[str, object]) -> ReFingerprintProfile`
- Produces: `ReFingerprintProfile.profile_hash() -> str`
- Produces: `ReExecutionPlan.from_json_dict(data: Mapping[str, object]) -> ReExecutionPlan`
- Produces: serialized plan fields `classification`, `analysis_required`, `workspace_synthesis_required`, `publication_required`, and `removed_sources`.
- Produces: `validate_re_run(workspace_root: Path, run_dir: Path, *, allow_partial: bool, status_override: Literal["complete", "partial"] | None = None) -> RePublicationCandidate`
- Produces: `publish_re_run(workspace_root: Path, run_dir: Path, *, allow_partial: bool = False, status_override: Literal["complete", "partial"] | None = None, expected_generation: int | None = None, fault_hook: Callable[[str], None] | None = None) -> RePublicationResult`
- Produces: `recover_interrupted_publication(workspace_root: Path) -> bool`
- Produces: `RePublicationResult(generation: int, status: str, index_path: Path, changed_sources: tuple[str, ...], removed_sources: tuple[str, ...], warnings: tuple[str, ...])`

- [ ] **Step 1: Build synthetic run fixtures and failing gate tests**

```python
def test_complete_two_source_publish_creates_one_generation(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, sources=("web", "api"), status="complete")
    result = publish_re_run(tmp_path, run_dir)
    assert result.generation == 1
    assert json_at(tmp_path / "re/index.json")["generation"] == 1
    assert json_at(tmp_path / "re/sources/web/manifest.json")["source_id"] == "web"
    assert json_at(tmp_path / "re/sources/api/manifest.json")["source_id"] == "api"
    assert (tmp_path / "re/workspace/contracts.md").is_file()


def test_partial_requires_explicit_override(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, sources=("api",), status="partial")
    with pytest.raises(RePublicationValidationError, match="allow-partial"):
        publish_re_run(tmp_path, run_dir)
    result = publish_re_run(tmp_path, run_dir, allow_partial=True)
    assert result.status == "partial"


def test_failed_replacement_restores_previous_generation_byte_for_byte(tmp_path: Path) -> None:
    publish_re_run(tmp_path, write_valid_re_run(tmp_path, ("api",), run_id="run-1"))
    before = snapshot_tree(tmp_path / "re", excluded=(".cache", ".staging", ".locks"))
    changed = write_valid_re_run(tmp_path, ("api",), run_id="run-2", content="changed")
    with pytest.raises(OSError, match="injected"):
        publish_re_run(tmp_path, changed, expected_generation=1,
                       fault_hook=lambda step: (_ for _ in ()).throw(OSError("injected"))
                       if step == "before_index_replace" else None)
    assert snapshot_tree(tmp_path / "re", excluded=(".cache", ".staging", ".locks")) == before
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest tests/unit/test_re_publication.py -q`

Expected: FAIL because publication interfaces do not exist.

- [ ] **Step 3: Implement deterministic candidate validation**

```python
@dataclass(frozen=True)
class RePublicationCandidate:
    run_id: str
    run_dir: Path
    status: str
    plan: ReExecutionPlan
    refreshed_sources: tuple[str, ...]
    empty_sources: tuple[str, ...]
    removed_sources: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_re_run(workspace_root: Path, run_dir: Path, *,
                    allow_partial: bool,
                    status_override: Literal["complete", "partial"] | None = None) -> RePublicationCandidate:
    re_dir = run_dir.resolve() / "re"
    re_state = _read_json(re_dir / "state.json")
    run_state = _read_json(run_dir / "state.json")
    plan = ReExecutionPlan.from_json_dict(_read_json(re_dir / "re-execution-plan.json"))
    inferred = run_state.get("golddigger_status") or re_state.get("publication_status")
    if not inferred and re_state.get("status") == "done":
        inferred = "complete"
    status = status_override or str(inferred or "")
    if status == "failed":
        raise RePublicationValidationError("failed RE output is not publishable")
    if status != "complete" and not (allow_partial and status == "partial"):
        raise RePublicationValidationError("partial RE output requires --allow-partial")
    _validate_plan_fingerprints(plan, re_dir / "re-source-index.json")
    _validate_refreshed_source_docs(re_dir / "sources", plan)
    _validate_workspace_docs(re_dir / "workspace", re_dir / "re-workspace-inputs.json", plan)
    return _candidate_from_validated_state(run_dir, status, plan, run_state)
```

Validation must compare source ID, fingerprint value, profile hash, source path, and selected action against both planning JSON files. Every non-empty refreshed source requires `overview.md` and at least one `specs/*/spec.md`; every domain spec must contain `User Scenarios & Testing`, `Requirements (Functional)`, `Key Entities`, `Edge Cases`, and at least five concrete source references for full/logic depth. Empty sources require no specs. Workspace staging requires `overview.md`, `relationships.md`, and `contracts.md`. Python-generated `re-workspace-inputs.json` must list every current, refreshed, empty, unavailable-retained, and removed source decision and match the execution plan exactly.

- [ ] **Step 4: Add exact plan/profile deserialization before publication uses it**

Implement `to_json_dict` and `from_json_dict` on `ReFingerprintProfile`, `RePlanSource`, and `ReExecutionPlan`, plus `profile_hash()` as SHA-256 of `stable_json()`. Reject unknown schema versions, invalid actions/classifications, missing fingerprint fields, duplicate source IDs, and any serialized profile hash that differs from `ReFingerprintProfile.profile_hash()`. Round-trip tests must assert `from_json_dict(plan.to_json_dict()) == plan` and malformed JSON raises `ValueError` before filesystem staging starts.

- [ ] **Step 5: Implement source manifests and staged publication assembly**

```python
def _source_manifest(plan_source: RePlanSource, profile: ReFingerprintProfile, *, status: str,
                     cache_path: Path, specs: tuple[Path, ...],
                     workspace_root: Path) -> dict[str, object]:
    rel = lambda path: path.relative_to(workspace_root).as_posix()
    return {
        "schema_version": 1,
        "source_id": plan_source.id,
        "source_path": plan_source.path,
        "source_fingerprint": plan_source.fingerprint.value,
        "git_head": plan_source.fingerprint.git_head,
        "dirty": plan_source.fingerprint.dirty,
        "profile": profile.to_json_dict(),
        "profile_hash": plan_source.fingerprint.profile_hash,
        "publication_status": status,
        "cache_path": rel(cache_path),
        "overview": f"re/sources/{plan_source.id}/overview.md",
        "specs": [f"re/sources/{plan_source.id}/specs/{path.parent.name}/spec.md" for path in specs],
        "warnings": [],
    }
```

Build all changed durable source directories, workspace synthesis, cache entries, source manifests, workspace manifest, and the next index under `re/.staging/<run-id>/new/`. Reuse unchanged published source directories as immutable inputs. Treat unavailable sources as unchanged. Remove only source IDs listed as `removed` by comparison with explicit workspace configuration. For an empty source, write a deterministic `overview.md` containing the source ID/path and `No analyzable source files were present for this generation.`; publish an empty specs list and never carry forward old specs.

- [ ] **Step 6: Implement index-last replacement and rollback**

Write `rollback-journal.json` before any move. For each affected final path, move the old path into `rollback/`, move the staged path into place, and record the completed operation atomically. Replace `re/index.json` only after all source, workspace, and cache operations succeed. On any exception, replay completed operations in reverse, restore the old index, validate the restored index, then re-raise. Delete rollback data only after the new index can be loaded and validated.

`recover_interrupted_publication` handles a stale lock with a `replacing` journal by taking recovery ownership, replaying completed moves in reverse, validating the restored index, marking the journal `rolled_back`, and only then removing the stale lock/staging directory. `recover_stale_publish_lock` must continue to refuse direct lock deletion while such a journal exists.

- [ ] **Step 7: Add source lifecycle tests**

Add named tests `test_one_source_refresh_preserves_unchanged_source_bytes`, `test_stable_id_changed_path_updates_same_source_directory`, `test_unavailable_source_retains_published_docs`, `test_explicit_removal_deletes_only_named_source`, `test_initial_empty_source_has_no_specs`, `test_populated_to_empty_removes_specs_only_after_success`, `test_profile_mismatch_is_rejected`, `test_workspace_inputs_must_match_plan`, and `test_expected_generation_conflict_does_not_stage`. Each test snapshots the durable tree before the attempted publication and asserts exact changed and unchanged paths after it.

- [ ] **Step 8: Run tests**

Run: `pytest tests/unit/test_re_registry.py tests/unit/test_re_lock.py tests/unit/test_re_fingerprint.py tests/unit/test_re_planner.py tests/unit/test_re_publication.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/harness/re_publication.py src/harness/re_fingerprint.py src/harness/re_planner.py tests/unit/test_re_publication.py tests/unit/test_re_fingerprint.py tests/unit/test_re_planner.py
git commit -m "feat: publish re generations atomically"
```

### Task 4: Published Freshness Planning And Direct Context

**Files:**
- Modify: `src/harness/re_cache.py`
- Modify: `src/harness/re_planner.py`
- Modify: `src/harness/re_materializer.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_re_cache.py`
- Modify: `tests/unit/test_re_planner.py`
- Modify: `tests/unit/test_re_materializer.py`
- Modify: `tests/unit/test_squad_re_context.py`

**Interfaces:**
- Consumes: `load_published_index`, `canonical_re_artifacts`, and the serialized plan fields introduced in Task 3.
- Produces: `RePlanSource.classification: Literal["current", "refresh", "empty", "unavailable"]`
- Produces: `ReExecutionPlan.removed_sources: tuple[str, ...]`
- Produces: `ReExecutionPlan.analysis_required: bool`
- Produces: `ReExecutionPlan.workspace_synthesis_required: bool`
- Produces: `ReExecutionPlan.publication_required: bool`
- Produces: `materialize_re_run_context(...) -> dict[str, object]`

- [ ] **Step 1: Change planner tests to assert published freshness**

```python
def test_matching_published_source_is_current_without_cache_copy(tmp_path: Path) -> None:
    source = create_git_source(tmp_path, "api")
    publish_matching_source(tmp_path, source_id="api", source_path="sources/api")
    plan = build_re_execution_plan(discover_workspace(tmp_path), policy="changed",
                                   target_source=None, published_index=load_published_index(tmp_path),
                                   profile=ReFingerprintProfile())
    assert plan.source("api").classification == "current"
    assert plan.source("api").action == "reuse"
    assert plan.refresh_sources == ()


def test_direct_context_points_to_re_not_run_copy(tmp_path: Path) -> None:
    plan = matching_published_plan(tmp_path)
    artifacts = materialize_re_run_context(project_root=tmp_path,
        run_re_dir=tmp_path / "runs/run-2/re", workspace_manifest=discover_workspace(tmp_path),
        plan=plan, published_index=load_published_index(tmp_path))
    assert artifacts["manifest"] == str(tmp_path / "re/index.json")
    assert artifacts["per_repo"] == [str(tmp_path / "re/sources/api")]
    assert not (tmp_path / "runs/run-2/re/api").exists()


def test_no_index_refreshes_every_non_empty_source(tmp_path: Path) -> None:
    manifest = workspace_with_sources(tmp_path, "web", "api")
    plan = build_re_execution_plan(manifest, policy="changed", target_source=None,
                                   published_index=None, profile=ReFingerprintProfile())
    assert plan.refresh_sources == ("api", "web")
    assert plan.analysis_required
    assert plan.workspace_synthesis_required
    assert plan.publication_required


def test_removal_only_requires_synthesis_but_not_analysis(tmp_path: Path) -> None:
    index = publish_two_sources_then_configure_one(tmp_path, removed="web")
    plan = plan_from_workspace(tmp_path, published_index=index)
    assert plan.removed_sources == ("web",)
    assert not plan.analysis_required
    assert plan.workspace_synthesis_required
    assert plan.publication_required
```

- [ ] **Step 2: Run focused tests and confirm old cache-copy expectations fail**

Run: `pytest tests/unit/test_re_cache.py tests/unit/test_re_planner.py tests/unit/test_re_materializer.py tests/unit/test_squad_re_context.py -q`

Expected: FAIL on `.echelon/cache/re`, copied source directories, and missing classifications.

- [ ] **Step 3: Preserve action compatibility while adding design classifications**

Use `classification=current` with `action=reuse`, `refresh` with `action=refresh`, `empty` with `action=skip-empty`, and `unavailable` with `action=missing`. A source is current only when the index record and source manifest match the new fingerprint/profile hash and every required durable file exists. Missing heavy cache alone does not invalidate durable RE context.

`analysis_required` is true only for non-empty refresh sources. `workspace_synthesis_required` is true for any new, changed, or moved source; populated-to-empty transition; publication-status change; or explicit removal. `publication_required` is true when either analysis or workspace synthesis is required. This distinction prevents source removal and empty transitions from becoming cache-hit no-ops.

- [ ] **Step 4: Move active cache paths and stop materializing current artifacts**

```python
class ReCacheStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.root = self.workspace_root / "re" / ".cache"
        self.legacy_root = self.workspace_root / ".echelon" / "cache" / "re"
```

Rename `materialize_re_run_view` to `materialize_re_run_context`. It still writes `workspace-manifest.json`, `re-execution-plan.json`, `re-source-index.json`, a refresh-only `re-analysis-manifest.json`, and deterministic `re-workspace-inputs.json`; it does not copy current source artifacts. Workspace inputs list canonical current/unavailable-retained manifests, staged refresh/empty paths, and removed IDs. Its returned artifact map uses canonical registry paths for current sources and run staging paths only for refresh sources.

- [ ] **Step 5: Resolve the effective profile once in squad initialization**

Add `_resolve_re_fingerprint_profile(project_root)` in `src/harness/squad.py`. Read the resolved config with the existing config loader, prefer `re.profile`, `re.depth.level`, `re.depth.max_lines_per_file`, and `re.sources.git_history_limit`, then fall back to `discovery.max_lines_per_file` and `discovery.git_history_limit`, finally to `full/full/5000/2500`. Store the exact profile JSON and profile hash in state.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/test_re_cache.py tests/unit/test_re_fingerprint.py tests/unit/test_re_planner.py tests/unit/test_re_materializer.py tests/unit/test_squad_re_context.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_cache.py src/harness/re_planner.py src/harness/re_materializer.py src/harness/squad.py tests/unit/test_re_cache.py tests/unit/test_re_planner.py tests/unit/test_re_materializer.py tests/unit/test_squad_re_context.py
git commit -m "feat: plan re from published workspace context"
```

### Task 5: Source-Scoped Analysis Staging

**Files:**
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `extension/scripts/bash/re/extract-cross-repo.sh`
- Modify: `extension/agents/re/analyzer.md`
- Modify: `extension/workflow/phases/re-extract-1-analyze.md`
- Modify: `tests/integration/re/test-run-analysis-polyrepo.sh`
- Modify: `tests/integration/re/test-extract-cross-repo.sh`
- Modify: `tests/unit/test_re_materializer.py`

**Interfaces:**
- Consumes: `runs/<run-id>/re/re-analysis-manifest.json`
- Produces: `run-analysis.sh --source-output-root <dir>`
- Produces: per-source heavy artifacts at `runs/<run-id>/re/sources/<source-id>/`

- [ ] **Step 1: Add failing shell assertions for source output root and refresh selection**

Create a two-source fixture whose analysis manifest selects only `api`. Run:

```bash
extension/scripts/bash/re/run-analysis.sh \
  --output "$RUN_RE" \
  --manifest "$RUN_RE/re-analysis-manifest.json" \
  --source-output-root "$RUN_RE/sources" \
  --profile full --depth full --max-lines-per-file 5000 --git-history-limit 2500
```

Assert `sources/api/analysis.json` exists, `sources/web/analysis.json` does not exist, aggregate `analysis.json.repo_analyses[0].path` is `sources/api/analysis.json`, and the full `workspace-manifest.json` remains unchanged.

- [ ] **Step 2: Run shell tests and confirm the new option is rejected**

Run: `bash tests/integration/re/test-run-analysis-polyrepo.sh`

Expected: FAIL with `unknown argument: --source-output-root`.

- [ ] **Step 3: Implement source output root without changing legacy positional behavior**

Add `SOURCE_OUTPUT_ROOT="$OUTPUT_DIR"` by default. Parse `--source-output-root`, resolve it after `OUTPUT_DIR`, and use `REPO_OUTPUT="$SOURCE_OUTPUT_ROOT/$REPO_NAME"`. Every aggregate relative path must be computed relative to `OUTPUT_DIR`, yielding `sources/<id>/...` for harness runs and the existing `<id>/...` for legacy calls. Pass the same base to `extract-cross-repo.sh` so it reads selected source analyses from the correct directories.

- [ ] **Step 4: Update analyzer dispatch contract**

Replace single/polyrepo path prose with workspace-source prose. The analyzer must prefer `re-analysis-manifest.json`, pass `--source-output-root "$RE_OUTPUT_DIR/sources"`, and report the exact explicit profile values it used. Standalone fallback discovery still works, but its output is also source-scoped.

- [ ] **Step 5: Run shell and materializer tests**

Run: `bash tests/integration/re/test-run-analysis-polyrepo.sh && bash tests/integration/re/test-extract-cross-repo.sh && pytest tests/unit/test_re_materializer.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add extension/scripts/bash/re/run-analysis.sh extension/scripts/bash/re/extract-cross-repo.sh extension/agents/re/analyzer.md extension/workflow/phases/re-extract-1-analyze.md tests/integration/re/test-run-analysis-polyrepo.sh tests/integration/re/test-extract-cross-repo.sh tests/unit/test_re_materializer.py
git commit -m "feat: stage re analysis by workspace source"
```

### Task 6: Source-Owned Specs And Workspace Synthesis Contracts

**Files:**
- Modify: `extension/agents/re/specifier.md`
- Modify: `extension/agents/re/verifier.md`
- Modify: `extension/agents/re/expander.md`
- Modify: `extension/agents/re/validator.md`
- Modify: `extension/agents/re/checklister.md`
- Modify: `extension/agents/re/constituter.md`
- Modify: `extension/workflow/phases/re-extract-2-specify.md`
- Modify: `extension/workflow/phases/re-extract-3-verify.md`
- Modify: `extension/workflow/phases/re-extract-4-expand.md`
- Modify: `extension/workflow/phases/re-extract-5-validate.md`
- Modify: `extension/workflow/phases/re-extract-6-checklist.md`
- Modify: `extension/workflow/phases/re-extract-7-constitute.md`
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/commands/echelon.re-extract.md`
- Modify: `extension/agents/exploration/golddigger.md`
- Modify: `tests/unit/test_golddigger_templates.py`
- Modify: `tests/contract/static_contracts.py`

**Interfaces:**
- Consumes: staged heavy artifacts plus canonical current source manifests.
- Produces: `runs/<run-id>/re/sources/<id>/overview.md`
- Produces: `runs/<run-id>/re/sources/<id>/specs/<domain-id>/{spec.md,checklist.md}`
- Produces: `runs/<run-id>/re/workspace/{overview.md,relationships.md,contracts.md,domains/*.md}`

- [ ] **Step 1: Add static contract tests for exact output paths**

```python
def test_re_agents_use_source_owned_and_workspace_paths() -> None:
    specifier = read_agent("re/specifier.md")
    assert "$RE_OUTPUT_DIR/sources/{source-id}/overview.md" in specifier
    assert "$RE_OUTPUT_DIR/sources/{source-id}/specs/{domain-id}/spec.md" in specifier
    assert "$RE_OUTPUT_DIR/workspace/contracts.md" in specifier
    assert "specs/000-re-overview" not in specifier
```

Also assert GOLDDIGGER Mode 1 no longer requires project-root or aggregate run-local `specs/000-re-overview`, and that all seven phase contracts reference the new staging paths. Keep Mode 2 focused-domain cache behavior covered separately.

- [ ] **Step 2: Run static tests and confirm old paths fail**

Run: `pytest tests/unit/test_golddigger_templates.py tests/contract/static_contracts.py -q`

Expected: FAIL on aggregate `specs/NNN-re-*` paths.

- [ ] **Step 3: Rewrite RE-SPECIFIER as source ownership plus synthesis**

Use this exact output contract in the agent and phase file:

```text
For each source whose re-source-index action is refresh:
  $RE_OUTPUT_DIR/sources/{source-id}/overview.md
  $RE_OUTPUT_DIR/sources/{source-id}/specs/{NNN-re-domain}/spec.md

For the workspace union of current published sources, refreshed staged sources,
empty sources, unavailable retained sources, and explicit removals:
  $RE_OUTPUT_DIR/workspace/overview.md
  $RE_OUTPUT_DIR/workspace/relationships.md
  $RE_OUTPUT_DIR/workspace/contracts.md
  $RE_OUTPUT_DIR/workspace/domains/{domain-id}.md
```

Source specs may cite only files within their source root. Cross-source dependencies, APIs, events, shared schemas, and migration ordering belong only in workspace synthesis. Numbering is local to each source directory. Agents read Python-generated `$RE_OUTPUT_DIR/re-workspace-inputs.json`; they never create or edit fingerprint, profile, source mapping, manifest, or generation JSON.

- [ ] **Step 4: Move quality loops to source scope**

Verifier writes `quality/<source-id>/coverage-report.md`, computes coverage independently for each refreshed source, and blocks shallow summaries. Expander edits only the matching staged source directory. Validator writes `quality/<source-id>/validation-report.md`. Checklister writes each domain checklist beside its source spec and a workspace checklist under `workspace/`. Constituter writes strategic workspace documents under `workspace/strategy/` and reads all source manifests/specs plus workspace contracts.

- [ ] **Step 5: Preserve deep profile acceptance tests**

Extend `tests/unit/test_golddigger_templates.py` to assert the source-scoped contract still contains full/full/5000/2500 defaults, at least five stories, required deep sections, and concrete source evidence. Do not weaken the recently introduced shallow-summary gate.

For an all-empty declared workspace, the completion gate requires workspace overview/relationships/contracts and empty source decisions, but no source domain spec. For every non-empty refreshed source, the existing deep-spec gate remains mandatory.

- [ ] **Step 6: Run tests and dry-run wiring**

Run: `pytest tests/unit/test_golddigger_templates.py tests/contract/static_contracts.py -q && bash scripts/bash/dry-run.sh`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add extension/agents/re extension/agents/exploration/golddigger.md extension/workflow/phases/re-extract-*.md extension/workflow/definition.yaml extension/commands/echelon.re-extract.md tests/unit/test_golddigger_templates.py tests/contract/static_contracts.py
git commit -m "feat: make re outputs source owned"
```

### Task 7: Automatic Complete Publication

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/integration/test_squad_controller.py`
- Create: `tests/integration/test_re_publication_flow.py`

**Interfaces:**
- Consumes: `publish_re_run(... allow_partial=False, status_override="complete", expected_generation=...)`
- Produces: state fields `re_generation`, `re_index`, `re_sources`, `re_workspace`, and canonical `re_artifacts`.

- [ ] **Step 1: Write failing executor tests**

```python
def test_complete_golddigger_publishes_before_state_update(tmp_path: Path, monkeypatch) -> None:
    published = RePublicationResult(2, "complete", tmp_path / "re/index.json", ("api",), (), ())
    monkeypatch.setattr("harness.squad_executors.publish_re_run", lambda *_a, **_k: published)
    result = execute_golddigger_mode1_complete(tmp_path)
    state = result.state_store.load()
    assert state["re_generation"] == 2
    assert state["re_artifacts"]["manifest"] == str(tmp_path / "re/index.json")


def test_publication_failure_blocks_and_preserves_old_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("harness.squad_executors.publish_re_run",
                        Mock(side_effect=RePublicationValidationError("workspace mismatch")))
    result = execute_golddigger_mode1_complete(tmp_path)
    assert result.verdict == "BLOCKED"
    assert result.blocked_reason == "re_publication_failed"
```

- [ ] **Step 2: Run focused tests and confirm no publication call**

Run: `pytest tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py -q`

Expected: FAIL on missing publication and canonical state fields.

- [ ] **Step 3: Publish at the deterministic pre-dispatch seam**

In `_run_pre_dispatch`, after GOLDDIGGER Mode 1 result parsing and plan-aware complete-output validation, call publication with `status_override="complete"` before applying agent state updates. Exclude the owner run from active-run detection. On success, replace agent-provided RE paths with `canonical_re_artifacts`; update expected generation. On publication lock, active-run, generation conflict, or validation failure, return a blocked executor result and retain the old published generation.

An unchanged current plan skips GOLDDIGGER and reads `re/`. A zero-source workspace succeeds without publication. A plan with only empty transitions or explicit removals still dispatches workspace synthesis because `publication_required` is true even though `analysis_required` is false. An all-empty declared workspace publishes empty source manifests plus workspace documents without inventing source specs.

- [ ] **Step 4: Add the two-run integration test**

The test must execute a synthetic first complete GOLDDIGGER result, assert generation 1 and distinct source directories, initialize a second unchanged run, assert `re_refresh_sources == []`, assert GOLDDIGGER was not invoked, and assert all context paths are canonical `re/` paths.

- [ ] **Step 5: Run tests**

Run: `pytest tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py tests/integration/test_re_publication_flow.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad_executors.py src/harness/squad.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py tests/integration/test_re_publication_flow.py
git commit -m "feat: publish complete golddigger output"
```

### Task 8: Generation Guard Across Normal And Manual Phase Dispatch

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_re_context.py`

**Interfaces:**
- Produces: `assert_re_generation(workspace_root: Path, expected_generation: int) -> None`
- Produces: blocked reason `re_generation_mismatch`.

- [ ] **Step 1: Add failing normal-loop and manual-phase tests**

```python
def test_generation_change_blocks_before_executor_dispatch(tmp_path: Path) -> None:
    controller, executor = initialized_controller(tmp_path, re_generation=1)
    rewrite_index_generation(tmp_path, 2)
    result = controller.run("continue")
    assert result.status == "blocked"
    assert controller.state()["blocked_reason"] == "re_generation_mismatch"
    assert executor.calls == []
```

Repeat the assertion through `run_single_phase` so manual replay cannot bypass the guard.

- [ ] **Step 2: Run tests and confirm dispatch still occurs**

Run: `pytest tests/integration/test_squad_controller.py -k generation -q`

Expected: FAIL because generation is not checked.

- [ ] **Step 3: Implement and call the guard before dispatch counting**

```python
def assert_re_generation(workspace_root: Path, expected_generation: int) -> None:
    index = load_published_index(workspace_root)
    actual = index.generation if index else 0
    if actual != expected_generation:
        raise ReGenerationMismatch(expected_generation, actual)
```

Call it after condition-based phase skip and before `increment_phase_dispatch_count` in both `run` and `run_single_phase`. Runs with no published index pin generation 0. The owner run updates its pinned generation immediately after successful automatic publication.

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_squad_controller.py tests/unit/test_squad_re_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py tests/unit/test_squad_re_context.py
git commit -m "feat: guard pinned re generations"
```

### Task 9: Manual Publish, Partial Override, Legacy Cache Import, And Explicit Commit

**Files:**
- Create: `src/harness/re_migration.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Create: `tests/unit/test_cli_re_publish.py`
- Create: `tests/unit/test_re_migration.py`

**Interfaces:**
- Produces: `echelon re publish <run-id> [--allow-partial] [--commit]`
- Produces: `import_legacy_re_cache(workspace_root: Path) -> tuple[Path, ...]`

- [ ] **Step 1: Add failing Typer routing and CLI behavior tests**

```python
def test_re_publish_routes_explicit_flags(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("echelon.cli._cmd_re_publish", lambda args: calls.append(args))
    run(["re", "publish", "spec-123", "--allow-partial", "--commit"])
    assert calls == [["spec-123", "--allow-partial", "--commit"]]


def test_publish_without_commit_leaves_re_changes_uncommitted(git_workspace: Path) -> None:
    run_id = write_valid_re_run(git_workspace, ("api",)).parent.name
    _cmd_re_publish([run_id])
    assert git(git_workspace, "status", "--short", "re").stdout
    assert git(git_workspace, "log", "-1", "--format=%s").stdout.strip() == "initial"
```

- [ ] **Step 2: Run tests and confirm command is absent**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_re_publish.py tests/unit/test_re_migration.py -q`

Expected: FAIL because the `re` command and migration helper do not exist.

- [ ] **Step 3: Add the Typer command and deterministic handler**

```python
re_app = typer.Typer(add_completion=False,
                     help="Publish and inspect workspace reverse engineering.",
                     no_args_is_help=True)
app.add_typer(re_app, name="re")


@re_app.command("publish")
def re_publish(run_id: str,
               allow_partial: bool = typer.Option(False, "--allow-partial"),
               commit: bool = typer.Option(False, "--commit")) -> None:
    args = [run_id]
    if allow_partial:
        args.append("--allow-partial")
    if commit:
        args.append("--commit")
    _legacy_cli()._cmd_re_publish(args)
```

`_cmd_re_publish` resolves only `runs/<run-id>` or legacy `squad/<run-id>`, rejects traversal, calls `publish_re_run`, prints generation/status/changed sources, and exits nonzero on structural failure. Status resolution reads `state.json.golddigger_status`, then `re/state.json.publication_status`, and maps a completed standalone RE state (`re/state.json.status == done`) to `complete`. Add the command to `USAGE`.

- [ ] **Step 4: Implement explicit tracked-path commit**

With `--commit`, run `git add -- re/.gitignore re/index.json re/sources re/workspace`, verify `git diff --cached --name-only` contains no `re/.cache`, `re/.staging`, or `re/.locks`, and commit with `docs(re): publish workspace reverse engineering generation <N>`. Without `--commit`, do not invoke Git.

- [ ] **Step 5: Implement one-way legacy cache import**

Read valid cache manifests under `.echelon/cache/re/sources/<id>/<fingerprint>/`, copy them into `re/.cache/sources/<id>/<fingerprint>/` only when the destination is absent, and never create `re/index.json`. Invoke import during manual publication before assembling new cache entries. Invalid entries are skipped with warnings; source publication still depends on structurally valid run output.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_re_publish.py tests/unit/test_re_migration.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_migration.py src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_cli_typer_app.py tests/unit/test_cli_re_publish.py tests/unit/test_re_migration.py
git commit -m "feat: add manual re publication command"
```

### Task 10: Feature Finalization And Branch-Safe Git Behavior

**Files:**
- Modify: `extension/scripts/bash/finalize-run.sh`
- Modify: `tests/contract/static_contracts.py`
- Create: `tests/integration/test_re_git_flow.py`

**Interfaces:**
- Consumes: tracked `re/` publication files.
- Produces: one feature artifact commit containing spec and changed durable RE files only.

- [ ] **Step 1: Write failing finalization tests**

Create a Git fixture with different `re/index.json` generations on `main` and a feature branch plus ignored files under all three runtime directories. Run `finalize-run.sh`; assert the feature commit contains `re/index.json`, `re/sources/api/overview.md`, and the spec, but no runtime paths. Assert checkout of `main` restores main's index content.

- [ ] **Step 2: Run tests and confirm RE is not staged**

Run: `pytest tests/integration/test_re_git_flow.py tests/contract/static_contracts.py -q`

Expected: FAIL because finalization stages only specs and knowledge base.

- [ ] **Step 3: Stage the tracked RE surface explicitly**

```bash
if [ -f "${PROJECT_ROOT}/re/index.json" ]; then
  git -C "${PROJECT_ROOT}" add -- \
    "re/.gitignore" \
    "re/index.json" \
    "re/sources" \
    "re/workspace"
fi
```

Immediately fail if `git diff --cached --name-only` contains `re/.cache/`, `re/.staging/`, or `re/.locks/`. Keep existing feature branch push and default-branch checkout behavior unchanged.

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_re_git_flow.py tests/contract/static_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/scripts/bash/finalize-run.sh tests/integration/test_re_git_flow.py tests/contract/static_contracts.py
git commit -m "feat: finalize published re with feature specs"
```

### Task 11: End-To-End Regression, Documentation, And Rollout Gate

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/integration/test_re_publication_flow.py`

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: documented workspace RE lifecycle and a complete regression gate.

- [ ] **Step 1: Extend the integration matrix**

Add cases for zero sources, empty source, unavailable source retention, one changed source out of two, explicit removal, partial manual override, automatic partial rejection, concurrent publisher rejection, stale-lock recovery, injected rollback, and changed profile hash. Each case must assert generation, selected refresh sources, canonical paths, and unchanged bytes where publication is rejected.

- [ ] **Step 2: Document the operator contract**

Add a concise README section showing the `re/` tree, source ID mapping, automatic publication, direct consumption, refresh triggers, `echelon re publish`, `--allow-partial`, `--commit`, and the fact that publication does not push. Add a changelog entry that `.echelon/cache/re` is migration input only and that profile defaults/policies are unchanged.

- [ ] **Step 3: Run focused RE suites**

Run:

```bash
pytest tests/unit/test_re_cache.py \
       tests/unit/test_re_fingerprint.py \
       tests/unit/test_re_registry.py \
       tests/unit/test_re_lock.py \
       tests/unit/test_re_planner.py \
       tests/unit/test_re_materializer.py \
       tests/unit/test_re_publication.py \
       tests/unit/test_re_migration.py \
       tests/unit/test_squad_re_context.py \
       tests/unit/test_cli_re_publish.py \
       tests/kernel/test_squad_executors_journal.py \
       tests/integration/test_squad_controller.py \
       tests/integration/test_re_publication_flow.py \
       tests/integration/test_re_git_flow.py -q
```

Expected: PASS.

- [ ] **Step 4: Run RE shell and extension wiring tests**

Run:

```bash
bash tests/integration/re/test-discover-repos.sh
bash tests/integration/re/test-run-analysis-polyrepo.sh
bash tests/integration/re/test-extract-cross-repo.sh
bash scripts/bash/dry-run.sh
```

Expected: all commands exit 0.

- [ ] **Step 5: Run the full Python regression suite**

Run: `pytest -q`

Expected: PASS with no new failures.

- [ ] **Step 6: Inspect the complete diff for authority leaks**

Run:

```bash
rg -n "\.echelon/cache/re|run-local cached artifacts reused|specs/000-re-overview" src/harness extension/agents extension/workflow
git diff --check
git status --short
```

Expected: `.echelon/cache/re` appears only in migration code/docs/tests; old aggregate spec paths appear only in explicit legacy-import compatibility; `git diff --check` is clean; no generated runtime artifacts are staged.

- [ ] **Step 7: Commit**

```bash
git add README.md CHANGELOG.md tests/integration/test_re_publication_flow.py
git commit -m "docs: describe workspace re publication"
```

---

## Final Review Gate

Before merging, compare every design requirement with a passing test:

- Initial and incremental source publication.
- Direct unchanged-run reuse without GOLDDIGGER dispatch.
- Full profile and profile-hash freshness.
- Source-owned specs and separate workspace synthesis.
- Empty, unavailable, moved, and explicitly removed source behavior.
- Complete-only automatic publication and structural partial override.
- Single writer, active-run exclusion, stale recovery, and generation guard.
- Index-last transaction and byte-identical rollback.
- Feature-branch staging and explicit standalone commit behavior.
- Legacy cache import without legacy authority.

Do not enable automatic publication until Tasks 1-6 pass together. Do not switch finalization until the Git integration test proves default-branch RE restoration.
