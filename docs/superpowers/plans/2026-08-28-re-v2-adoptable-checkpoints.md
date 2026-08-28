# RE v2 Adoptable Certified Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship protocol 2.6 so new L1, L2, and L3 runs automatically adopt exact-compatible, dependency-closed artifacts accepted by any sibling run without redispatching their provider work.

**Architecture:** Add a focused `harness.re_v2.protocol_26` authority layer over the existing protocol-2.2, protocol-2.4, and protocol-2.5 graphs, controllers, receipts, ledgers, object stores, provider execution, and materialization. Schema 5 pins an exact layer-execution contract plus a frozen checkpoint-selection bundle; a disposable workspace index accelerates discovery, but every selected byte is revalidated and copied into the staged child before activation. Shared recovery gains only an additive manifest-authority resolver so existing controllers can execute a schema-5 run while authenticating `run_created` against the outer schema-5 manifest.

**Tech Stack:** Python 3.11+, standard-library dataclasses/json/fcntl/os/pathlib/tempfile, existing canonical JSON/content-digest utilities, existing RE v2 object/event/typed-ledger stores, existing Prosaic metadata and shared coding-provider path, pytest, and Git-backed real-workspace tests.

**Spec:** `docs/superpowers/specs/2026-08-28-re-v2-adoptable-checkpoints-design.md`

## Global Constraints

- Protocol 2.6 uses run schema 5. Protocols 2.0/2.1 retain schema 1, 2.2/2.3 retain schema 2, 2.4 retains schema 3, and 2.5 retains schema 4 with unchanged canonical bytes and continuation behavior.
- Every durably accepted L0, L1, L2, or L3 artifact is eligible regardless of whether its origin is active, paused, blocked, failed for unrelated work, or complete.
- Compatibility is exact work-item and artifact-key identity. Names, paths, source IDs, profile names, timestamps, run IDs, and discovery order are not compatibility or winner criteria.
- Selection precedence is exact direct-parent authority, then exact workspace checkpoints, then normal generation.
- Workspace selection is dependency-closed and acyclic. A downstream artifact is not adopted unless all accepted-artifact and immutable-object dependencies are locally available and exact.
- Ranking uses only existing certified data and a pinned rank-policy hash. Equal vectors select the lexicographically smallest artifact hash.
- `.echelon/re-v2/checkpoints/` is disposable cache state, excluded from snapshots and Git. Run manifests, events, typed ledger records, and immutable objects remain authority.
- The child contains the frozen bundle and every selected object before schema-5 manifest publication and active-run pointer mutation. Recovery never consults the cache or origin.
- Imported checkpoint events and typed ledger records precede every lease or dispatch for their work item and consume no provider, retry, semantic-round, token, or active-time budget.
- Do not add a controller, provider adapter, credential path, model override, prompt, Prosaic agent, result protocol, or provider-specific branch. Unadopted work uses the existing layer controller and shared provider path.
- Do not modify files included in `_re_schema2_installed_registry()` or L2/L3 implementation digests. In particular, keep protocol-2.2 `baseline.py`, `cli_provider.py`, `context.py`, `controller.py`, `evidence.py`, `execution.py`, `inventory.py`, `partition.py`, `provider.py`, `response_schemas.py`, and `runtime.py` byte-identical.
- Existing direct-parent bundle bytes and `artifact_adopted` event bytes remain unchanged.
- Source repositories must be clean before discovery. The existing operator guidance to commit, stash including untracked files, or revert remains the failure path.
- This plan does not implement workspace synthesis, publication, L4, atomic repair, remote exchange, checkpoint garbage collection, or a checkpoint maintenance command.
- No new third-party runtime dependency is introduced.

## File Structure

Create one protocol-2.6 package whose files each own one authority boundary:

```text
src/harness/re_v2/protocol_26/
  __init__.py       protocol constants and public exports
  model.py          schema-5, layer-contract, checkpoint, rank, and selection models
  reconstruction.py stable origin replay and per-artifact manifest reconstruction
  cache.py          disposable workspace index, lock, manifests, and quarantine
  selection.py      exact compatibility, precedence, rank, and dependency closure
  inputs.py         staged self-contained schema-5 publication and loading
  adoption.py       frozen checkpoint ledger/object/event import and recovery
  events.py         protocol-2.6 event validation over the selected layer protocol
  authority.py      schema-5 to existing L1/L2/L3 execution-authority bridge
  status.py         checkpoint status/telemetry decoration
```

Add tests at the same boundaries:

```text
tests/re_v2_protocol_26_fixtures.py
tests/unit/test_re_v2_protocol_26_model.py
tests/unit/test_re_v2_protocol_26_reconstruction.py
tests/unit/test_re_v2_protocol_26_cache.py
tests/unit/test_re_v2_protocol_26_selection.py
tests/unit/test_re_v2_protocol_26_inputs.py
tests/unit/test_re_v2_protocol_26_adoption.py
tests/unit/test_re_v2_protocol_26_events.py
tests/unit/test_re_v2_protocol_26_authority.py
tests/unit/test_re_v2_protocol_26_status.py
tests/unit/test_cli_re_v2_protocol_26.py
tests/integration/test_re_v2_protocol_26_recovery.py
tests/integration/test_re_v2_protocol_26_cli.py
tests/integration/test_re_v2_protocol_26_live.py
```

Modify only additive routers or non-pinned durability seams:

```text
src/harness/re_v2/model.py
src/harness/re_v2/run_store.py
src/harness/re_v2/status.py
src/harness/re_v2/workspace_snapshot.py
src/harness/re_v2/protocol_22/recovery.py
src/harness/re_v2/protocol_24/adoption.py
src/harness/re_v2/protocol_25/recovery.py
src/echelon/cli.py
.gitignore
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
```

Before editing a shared file, run the installed-authority inventory test added in Task 1. If that test shows a file is digest-pinned, move the protocol-2.6 behavior behind `protocol_26` composition instead of changing the pinned file.

---

### Task 1: Freeze Existing Authorities and Register Closed Schema-5 Models

**Files:**
- Create: `src/harness/re_v2/protocol_26/__init__.py`
- Create: `src/harness/re_v2/protocol_26/model.py`
- Create: `tests/re_v2_protocol_26_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_26_model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces `LayerExecutionContractV1(schema_version, target_layer, layer_manifest)` and `LayerExecutionContractV1.from_layer_manifest(layer_manifest)`; `layer_manifest` strictly decodes to `RunManifestV2` for L1, `RunManifestV3` for L2, or `RunManifestV4` for L3 and must repeat the schema-5 run ID, creation timestamp, snapshot, partition, and target layer.
- Produces `CheckpointRankV1(policy_id, policy_hash, vector)` and `CheckpointArtifactDependencyV1(artifact_key_id, artifact_hash)` as closed canonical values.
- `CheckpointManifestV1` pins origin run/manifest/protocol/schema, acceptance event and ledger-record hashes, exact work-item bytes/ID, artifact key/hash, certification and optional assessment bytes/IDs, acceptance bytes/ID, `AdoptedArtifactAuthorityV1`, accepted-artifact dependencies, non-artifact object IDs, compatibility identities, rank, and rank-policy hash.
- `CheckpointSelectionEntryV1` pins expected work-item ID, source kind (`direct_parent` or `workspace_checkpoint`), checkpoint manifest ID when applicable, exact adopted authority, dependency IDs, copied object IDs and byte count, rank, origin, and controlled selection reason. Its `to_event_payload(selection_bundle_id)` method emits the exact event fields from Task 7.
- `CheckpointSelectionBundleV1` pins target snapshot/partition/layer/graph/selection IDs, dependency-ordered selected entries, origin manifest/event/ledger prefix hashes, copied receipt/work-item/object inventories, all ranked alternatives, controlled rejection/quarantine records, and cache generation identity.
- Produces `RunManifestV5` with exact fields `schema_version`, `engine`, `engine_protocol_version`, `run_id`, `created_at`, `source_snapshot_id`, `source_snapshot_kind`, `partition_manifest_id`, `target_layer`, `layer_execution_contract`, and `checkpoint_selection`.
- Extends `run_store.Manifest`, `_decode_manifest()`, and `_validate_supported_manifest()` only for the exact pair `(5, "2.6")`.

- [x] **Step 1: Record the compatibility baseline and prove planned shared seams are not implementation-digest inputs**

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
rg -n "recovery_module|run_store_module|protocol_24.adoption|workspace_snapshot" src/echelon/cli.py
git diff --exit-code -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24 src/harness/re_v2/protocol_25
```

Expected: tests pass; the `rg` result does not place `recovery.py`, `run_store.py`, `workspace_snapshot.py`, or protocol-2.4 `adoption.py` in an installed implementation digest; existing protocol source trees are clean.

- [x] **Step 2: Write failing model and run-store tests**

```python
def test_manifest_v5_round_trips_and_pins_2_6() -> None:
    manifest = manifest_v5(target_layer="L2")
    encoded = canonical_json_bytes(manifest.to_json_dict())
    assert RunManifestV5.from_json_dict(json.loads(encoded)) == manifest
    assert manifest.run_manifest_id == content_digest(encoded)


def test_layer_contract_rejects_mismatched_run_identity() -> None:
    raw = layer_execution_contract_v1(target_layer="L1").to_json_dict()
    raw["layer_manifest"]["run_id"] = "re-different"
    with pytest.raises(Protocol26SchemaError, match="run_id"):
        LayerExecutionContractV1.from_json_dict(raw)


def test_run_store_rejects_schema_5_with_old_protocol(tmp_path: Path) -> None:
    raw = manifest_v5(target_layer="L1").to_json_dict()
    raw["engine_protocol_version"] = "2.5"
    write_canonical_manifest(tmp_path, raw)
    with pytest.raises(ReV2RunStoreError, match="schema/protocol"):
        load_run_manifest(tmp_path)
```

- [x] **Step 3: Run the focused tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: collection fails because `protocol_26` and `RunManifestV5` do not exist.

- [x] **Step 4: Implement the closed models and exact schema router**

Use this public shape and the existing `exact_object`, `safe_id`, `digest_value`, `sorted_unique_digests`, `canonical_json_bytes`, and `content_digest` helpers:

```python
TargetLayerV1 = Literal["L1", "L2", "L3"]


@dataclass(frozen=True, slots=True)
class LayerExecutionContractV1:
    schema_version: int
    target_layer: TargetLayerV1
    layer_manifest: RunManifestV2 | RunManifestV3 | RunManifestV4

    @property
    def identity(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))

    @classmethod
    def from_layer_manifest(
        cls,
        layer_manifest: RunManifestV2 | RunManifestV3 | RunManifestV4,
    ) -> "LayerExecutionContractV1":
        target_layer = _target_layer_for_manifest(layer_manifest)
        return cls(schema_version=1, target_layer=target_layer, layer_manifest=layer_manifest)


@dataclass(frozen=True, slots=True)
class RunManifestV5:
    schema_version: int
    engine: str
    engine_protocol_version: str
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: str
    partition_manifest_id: str
    target_layer: TargetLayerV1
    layer_execution_contract: CatalogReferenceV1
    checkpoint_selection: CatalogReferenceV1

    @property
    def run_manifest_id(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))
```

Validate every nested layer manifest against its declared target and against the repeated schema-5 identity fields. Validate sorted/unique model arrays at construction and decode; reject unknown fields.

- [x] **Step 5: Run canonical, mutation, and compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass and old schema fixture digests remain exact.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/model.py src/harness/re_v2/run_store.py \
  src/harness/re_v2/protocol_26/__init__.py \
  src/harness/re_v2/protocol_26/model.py \
  tests/re_v2_protocol_26_fixtures.py \
  tests/unit/test_re_v2_protocol_26_model.py \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): register protocol 2.6 checkpoint authority"
```

---

### Task 2: Reconstruct Eligible Per-Artifact Checkpoints from Durable Origins

**Files:**
- Create: `src/harness/re_v2/protocol_26/reconstruction.py`
- Create: `tests/unit/test_re_v2_protocol_26_reconstruction.py`
- Modify: `tests/re_v2_protocol_26_fixtures.py`

**Interfaces:**
- Produces `OriginCheckpointResultV1(origin_run_id, manifests, rejected)`, its `unstable(origin_run_id)` constructor, and `reconstruct_origin_checkpoints(workspace_root: Path, run_dir: Path, *, max_stability_attempts: int = 2) -> OriginCheckpointResultV1`.
- Reuses `load_run_manifest`, `EventStore.replay()`, `Protocol22Ledger.replay_with_history()`, `ObjectStore.read_blob()`, and protocol-2.5 ledger/event facades; it does not require a terminal event.
- A reconstructed manifest identifies the exact acceptance event and ledger record, embeds exact work-item/receipt bytes, classifies accepted-artifact versus non-artifact dependencies, and includes the immutable object inventory needed for later self-contained import.
- Controlled rejections use the spec reason codes and never mutate the origin.

- [x] **Step 1: Write failing eligibility and torn-prefix tests**

```python
@pytest.mark.parametrize("origin_state", ["active", "paused", "blocked", "complete"])
def test_durably_accepted_artifact_is_eligible_before_terminalization(
    checkpoint_workspace: CheckpointWorkspace,
    origin_state: str,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain(origin_state)
    result = reconstruct_origin_checkpoints(checkpoint_workspace.root, origin)
    assert len(result.manifests) == 1
    assert result.manifests[0].artifact_key_id == origin.accepted_key_id


def test_certified_but_not_accepted_artifact_is_ineligible(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_certification_only()
    result = reconstruct_origin_checkpoints(checkpoint_workspace.root, origin)
    assert result.manifests == ()


def test_origin_append_during_read_is_bounded_and_skipped(
    checkpoint_workspace: CheckpointWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    monkeypatch.setattr(reconstruction, "_stable_chain_pair", always_changes)
    result = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, origin, max_stability_attempts=2
    )
    assert result.rejected[0].reason == "checkpoint_origin_unstable"
```

- [x] **Step 2: Run the reconstruction tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_reconstruction.py`

Expected: FAIL because the reconstruction API is absent.

- [x] **Step 3: Implement stable origin replay and exact acceptance joins**

Implement the bounded sequence exactly:

```python
for attempt in range(max_stability_attempts):
    manifest_before = _safe_regular_read(paths.manifest)
    events_before = _safe_optional_regular_read(paths.events)
    ledger_before = _safe_regular_read(paths.ledger)
    manifest = load_run_manifest(run_dir)
    events = EventStore(paths, protocol=event_protocol_for(manifest)).replay()
    history, ledger = ledger_for(manifest, paths).replay_with_history()
    manifest_after = _safe_regular_read(paths.manifest)
    events_after = _safe_optional_regular_read(paths.events)
    ledger_after = _safe_regular_read(paths.ledger)
    if (manifest_before, events_before, ledger_before) == (
        manifest_after,
        events_after,
        ledger_after,
    ):
        return _reconstruct_accepted_artifacts(manifest, events, history, ledger)
return OriginCheckpointResultV1.unstable(run_dir.name)
```

For each accepted artifact, require exactly one matching `artifact_accepted`, `artifact_adopted`, or `checkpoint_artifact_adopted` event; require its certification, optional certified assessment, work item, acceptance receipt, and ledger record; verify every referenced object by digest. Hash the authenticated event prefix ending at that acceptance event and the ledger prefix ending at that acceptance record, rather than the mutable later chain tail. Resolve artifact dependencies by exact accepted artifact hash and reject ambiguity, cycles, or missing objects.

- [x] **Step 4: Add unsafe path, symlink, corrupted object, and L3 epoch tests**

```python
def test_reconstruction_rejects_symlinked_origin(checkpoint_workspace: CheckpointWorkspace) -> None:
    origin = checkpoint_workspace.symlinked_origin()
    result = reconstruct_origin_checkpoints(checkpoint_workspace.root, origin)
    assert result.rejected[0].reason == "checkpoint_manifest_invalid"


def test_l3_checkpoint_preserves_exact_epoch_authority(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_l3_acceptance()
    manifest = reconstruct_origin_checkpoints(checkpoint_workspace.root, origin).manifests[0]
    assert manifest.audit_epoch_id == origin.audit_epoch_id
    assert manifest.semantic_authority_ids == origin.semantic_authority_ids
```

- [x] **Step 5: Run tests and verify GREEN**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_reconstruction.py`

Expected: all eligibility, integrity, stable-read, and path-safety cases pass.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_26/reconstruction.py \
  tests/re_v2_protocol_26_fixtures.py \
  tests/unit/test_re_v2_protocol_26_reconstruction.py
git commit -m "feat(re-v2): reconstruct accepted artifact checkpoints"
```

---

### Task 3: Build the Disposable Workspace Checkpoint Cache

**Files:**
- Create: `src/harness/re_v2/protocol_26/cache.py`
- Create: `tests/unit/test_re_v2_protocol_26_cache.py`
- Modify: `src/harness/re_v2/workspace_snapshot.py`
- Modify: `tests/unit/test_re_v2_workspace_snapshot.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces `CheckpointCachePaths.for_workspace(workspace_root: Path)`, `CheckpointCacheGenerationV1(paths, index, manifests, quarantine, reconstructed_manifest_ids)`, and `rebuild_checkpoint_cache(workspace_root: Path) -> CheckpointCacheGenerationV1`.
- Cache layout is exactly `.echelon/re-v2/checkpoints/index-v1.json`, `index-v1.lock`, `manifests/<identity>.json`, and `quarantine-v1.json`.
- Index entries reference canonical manifest IDs and contain projection-only query fields. Consumers must load and revalidate the canonical manifest projection before selection.
- Writes use an `fcntl.flock` regular-file lock, private staging directory, fsync, and atomic `os.replace`; malformed cache state is discarded and rebuilt from runs.

- [x] **Step 1: Write failing cache replacement and snapshot-exclusion tests**

```python
def test_cache_rebuild_is_deterministic_and_disposable(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.origin_with_one_accepted_domain("active")
    first = rebuild_checkpoint_cache(checkpoint_workspace.root)
    shutil.rmtree(first.paths.root)
    second = rebuild_checkpoint_cache(checkpoint_workspace.root)
    assert second.index.identity == first.index.identity


def test_malformed_cache_is_rebuilt_not_authorized(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.write_cache_index(b'{"selected":true}')
    generation = rebuild_checkpoint_cache(checkpoint_workspace.root)
    assert generation.index.manifest_ids == generation.reconstructed_manifest_ids


def test_workspace_snapshot_excludes_checkpoint_cache(tmp_path: Path) -> None:
    workspace = workspace_with_checkpoint_cache(tmp_path)
    snapshot = capture_workspace_source_snapshot(workspace)
    assert ".echelon/re-v2/checkpoints/index-v1.json" not in snapshot_paths(snapshot)
```

- [x] **Step 2: Run cache and snapshot tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_cache.py tests/unit/test_re_v2_workspace_snapshot.py`

Expected: checkpoint cache API and exclusion assertion fail.

- [x] **Step 3: Implement confined enumeration, locking, quarantine, and atomic replacement**

Use direct-child discovery and reject symlinks:

```python
runs_root = workspace_root.resolve() / "runs"
origins = tuple(
    path
    for path in sorted(runs_root.glob("re-*"), key=lambda value: value.name)
    if path.parent == runs_root and path.is_dir() and not path.is_symlink()
)
with checkpoint_cache_lock(paths.lock):
    generation = reconstruct_all(origins)
    _publish_generation_atomically(paths, generation)
return load_checkpoint_cache(workspace_root)
```

Keep `index-v1.lock` in the persistent cache root; never replace or unlink the directory containing the held lock. Write canonical manifests into a staged `manifests` generation, publish every referenced manifest and quarantine file first, and publish `index-v1.json` last with `os.replace` plus directory fsync. Retire unreferenced projection files only after the new index is durable. Put invalid-origin diagnostics in `quarantine-v1.json`, and ensure a cache file alone never constructs a checkpoint absent successful origin reconstruction during that generation.

- [x] **Step 4: Add `.gitignore` and snapshot exclusion for the exact cache root**

Add this repository pattern and the equivalent deterministic workspace-snapshot exclusion:

```gitignore
.echelon/re-v2/checkpoints/
```

- [x] **Step 5: Run cache, concurrency, path, and snapshot tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_cache.py tests/unit/test_re_v2_workspace_snapshot.py`

Expected: deterministic rebuild, malformed recovery, concurrent lock, symlink rejection, quarantine, and exclusion cases pass.

- [x] **Step 6: Commit**

```bash
git add .gitignore src/harness/re_v2/workspace_snapshot.py \
  src/harness/re_v2/protocol_26/cache.py \
  tests/unit/test_re_v2_protocol_26_cache.py \
  tests/unit/test_re_v2_workspace_snapshot.py
git commit -m "feat(re-v2): add reconstructable checkpoint cache"
```

---

### Task 4: Select an Exact Dependency-Closed Checkpoint Set

**Files:**
- Create: `src/harness/re_v2/protocol_26/selection.py`
- Create: `tests/unit/test_re_v2_protocol_26_selection.py`
- Modify: `src/harness/re_v2/protocol_26/model.py`
- Modify: `tests/re_v2_protocol_26_fixtures.py`

**Interfaces:**
- Produces `RankPolicyRegistryV1`, `compatibility_mismatches(expected: WorkItemV2, candidate: CheckpointManifestV1) -> Sequence[str]`, and `select_checkpoints(graph, candidates, direct_parent) -> CheckpointSelectionBundleV1`.
- Rank extractors are explicitly registered for every installed `(layer, artifact_kind)` and return `CheckpointRankV1`; deterministic pass-only kinds may share the `(1,)` extractor, compact baselines use existing policy-declared established-surface and coverage values, and L3 uses only comparable existing semantic certification fields. An unregistered kind is `checkpoint_rank_invalid`, never an implicit default.
- Selection evaluates direct-parent coverage first, then computes the maximal workspace dependency closure, then orders selected imports topologically by artifact-key identity.
- Every valid loser, incompatibility, quarantine, dependency miss, and tie-break is recorded with a controlled reason code.

- [x] **Step 1: Write failing exact-compatibility and ranking tests**

```python
def test_candidate_must_equal_expected_work_item_bytes() -> None:
    expected, candidate = exact_checkpoint_pair()
    mutated = replace(candidate, verifier_implementation_digest=digest("different"))
    assert compatibility_mismatches(expected, mutated) == (
        "verifier_implementation_digest",
    )


def test_quality_vector_wins_then_smallest_hash_breaks_tie() -> None:
    graph, low, high, equal_small = ranked_checkpoint_graph()
    bundle = select_checkpoints(graph, (low, high, equal_small), direct_parent=())
    assert bundle.selected[0].artifact_hash == min(
        high.artifact_hash, equal_small.artifact_hash
    )
    assert bundle.selected[0].selection_reason == "checkpoint_rank_hash_tiebreak"


def test_direct_parent_precedes_stronger_sibling() -> None:
    graph, parent, stronger_sibling = parent_precedence_graph()
    bundle = select_checkpoints(graph, (stronger_sibling,), direct_parent=(parent,))
    assert bundle.selected[0].source_kind == "direct_parent"
```

- [x] **Step 2: Run selection tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_selection.py`

Expected: FAIL because compatibility, rank registry, and selector are absent.

- [x] **Step 3: Implement exact candidate filtering and deterministic rank extraction**

Implement registration and winner ordering explicitly:

```python
RankExtractor = Callable[[CheckpointManifestV1], CheckpointRankV1]


def _winner_key(candidate: CheckpointManifestV1) -> tuple[Sequence[int], str]:
    rank = RANK_POLICIES.extract(candidate)
    # Extractors normalize every component so larger is always better.
    inverted = tuple(-value for value in rank.vector)
    return inverted, candidate.artifact_hash


def _choose(candidates: Iterable[CheckpointManifestV1]) -> CheckpointManifestV1:
    return min(candidates, key=_winner_key)
```

Do not derive any component from timestamps, run IDs, file ordering, prose, unknown-count guesses, or observed token use. Unknown counts enter a vector only when the frozen artifact policy explicitly registers their ordering. Persist the rank-policy ID/hash and the complete comparable vector.

- [x] **Step 4: Implement dependency closure, topological ordering, and cycles**

Use exact artifact key/hash edges and fixed-point pruning:

```python
selected = _best_candidate_per_expected_key(compatible)
while True:
    invalid = {
        key
        for key, candidate in selected.items()
        if not _all_dependencies_satisfied(candidate, selected, direct_parent, object_ids)
    }
    if not invalid:
        break
    for key in sorted(invalid):
        del selected[key]
ordered = _topological_artifact_order(selected, direct_parent)
```

Reject cycles rather than pruning an arbitrary node. Re-evaluate the next-ranked candidate for a key when the current candidate loses dependency closure, so the result is the maximal valid set rather than a first-choice-only set.

- [x] **Step 5: Add closure, incompatible policy, missing object, cycle, and L3 non-remapping tests**

```python
def test_downstream_checkpoint_is_dropped_when_dependency_is_missing() -> None:
    graph, upstream, downstream = dependency_graph()
    bundle = select_checkpoints(graph, (downstream,), direct_parent=())
    assert bundle.selected == ()
    assert bundle.rejected[0].reason == "checkpoint_dependency_missing"


def test_l3_epoch_is_never_remapped() -> None:
    graph, candidate = l3_epoch_mismatch_graph()
    bundle = select_checkpoints(graph, (candidate,), direct_parent=())
    assert bundle.selected == ()
    assert bundle.rejected[0].reason == "checkpoint_incompatible"
```

- [x] **Step 6: Run tests and verify GREEN**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_selection.py tests/unit/test_re_v2_protocol_26_model.py`

Expected: all ordering, maximal-closure, precedence, and compatibility matrices pass deterministically under randomized input ordering.

- [x] **Step 7: Commit**

```bash
git add src/harness/re_v2/protocol_26/model.py \
  src/harness/re_v2/protocol_26/selection.py \
  tests/re_v2_protocol_26_fixtures.py \
  tests/unit/test_re_v2_protocol_26_selection.py
git commit -m "feat(re-v2): select dependency-closed checkpoints"
```

---

### Task 5: Publish a Self-Contained Schema-5 Run Manifest-Last

**Files:**
- Create: `src/harness/re_v2/protocol_26/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_26_inputs.py`
- Modify: `src/harness/re_v2/run_store.py`
- Modify: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces `Protocol26InputSet(manifest, layer_execution_contract, layer_inputs, checkpoint_selection, authority_objects)`, `ValidatedProtocol26Inputs`, `create_protocol_26_run_store(run_dir, manifest, inputs, *, fault_hook=None) -> ReV2Paths`, and `load_protocol_26_inputs(paths, manifest) -> ValidatedProtocol26Inputs`.
- `authority_objects` maps every selected object digest to its bytes, including work item, certification, assessment, acceptance, execution capture, normalized provider payload, artifact, dependency objects, and origin manifest/event/ledger-prefix evidence named by the frozen bundle.
- Creation stages `v2` as a private sibling, writes the existing layer catalogs plus protocol-2.6 catalogs and all objects, validates the complete staged store, publishes `run.json` last, then atomically renames the staged root into place.
- Existing `create_run_store` semantics for schemas 1–4 remain unchanged.

- [x] **Step 1: Write failing self-contained and manifest-last tests**

```python
def test_schema5_store_contains_every_selected_object_before_manifest(
    tmp_path: Path,
    protocol26_input_set: Protocol26InputSet,
) -> None:
    paths = create_protocol_26_run_store(
        tmp_path / protocol26_input_set.manifest.run_id,
        protocol26_input_set.manifest,
        protocol26_input_set,
    )
    loaded = load_protocol_26_inputs(paths, protocol26_input_set.manifest)
    assert set(loaded.checkpoint_selection.copied_object_ids) <= set(
        ObjectStore(paths.objects).iter_hashes()
    )


def test_fault_before_manifest_publication_leaves_no_active_run(
    tmp_path: Path,
    protocol26_input_set: Protocol26InputSet,
) -> None:
    with pytest.raises(InjectedFault):
        create_protocol_26_run_store(
            tmp_path / protocol26_input_set.manifest.run_id,
            protocol26_input_set.manifest,
            protocol26_input_set,
            fault_hook=fail_at("before_manifest_publish"),
        )
    assert not ReV2Paths.for_run(tmp_path / protocol26_input_set.manifest.run_id).manifest.exists()
```

- [x] **Step 2: Run input-store tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_inputs.py tests/unit/test_re_v2_run_store.py`

Expected: FAIL because schema-5 staged creation is absent.

- [x] **Step 3: Implement canonical catalog persistence and staged publication**

Use the existing protocol-2.2/2.4/2.5 catalog writers based on `target_layer`, then add the two schema-5 catalogs:

```python
stage = _private_stage_for(run_dir)
paths = ReV2Paths.for_run(stage)
_create_layer_inputs(paths, inputs.layer_execution_contract.layer_manifest, inputs)
_write_catalog_object(paths, manifest.layer_execution_contract, inputs.layer_execution_contract)
_write_catalog_object(paths, manifest.checkpoint_selection, inputs.checkpoint_selection)
for object_hash, payload in sorted(inputs.authority_objects.items()):
    if ObjectStore(paths.objects).put_blob(payload) != object_hash:
        raise Protocol26InputStoreError("staged object identity changed")
_validate_staged_protocol_26_store(paths, manifest)
_publish_manifest_no_clobber(paths, manifest)
_publish_stage_no_clobber(paths.root, run_dir / "v2")
```

The layer writer must persist the inner manifest's referenced catalogs without publishing the inner manifest as `run.json`. Validate that all IDs and bytes in the frozen selection bundle are local before outer publication.

- [x] **Step 4: Add crash-seam, no-clobber, missing-object, and origin-deletion tests**

```python
@pytest.mark.parametrize(
    "seam",
    ["catalogs_written", "authority_object_written", "selection_written", "before_manifest_publish"],
)
def test_schema5_creation_is_retryable_at_every_prepublication_seam(
    tmp_path: Path,
    protocol26_input_set: Protocol26InputSet,
    seam: str,
) -> None:
    assert_retry_creates_one_exact_store(tmp_path, protocol26_input_set, seam)


def test_loaded_child_does_not_require_origin_or_cache(protocol26_store: Protocol26Store) -> None:
    protocol26_store.delete_origins_and_cache()
    loaded = load_protocol_26_inputs(protocol26_store.paths, protocol26_store.manifest)
    assert loaded.checkpoint_selection == protocol26_store.selection
```

- [x] **Step 5: Run store tests and verify GREEN**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_inputs.py tests/unit/test_re_v2_run_store.py`

Expected: all staged-publication, retry, no-clobber, and self-containment cases pass.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/run_store.py \
  src/harness/re_v2/protocol_26/inputs.py \
  tests/unit/test_re_v2_protocol_26_inputs.py \
  tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): publish self-contained checkpoint runs"
```

---

### Task 6: Share Typed Acceptance Import Without Changing Parent Semantics

**Files:**
- Create: `src/harness/re_v2/protocol_26/adoption.py`
- Create: `tests/unit/test_re_v2_protocol_26_adoption.py`
- Modify: `src/harness/re_v2/protocol_24/adoption.py`
- Test: `tests/unit/test_re_v2_protocol_24_adoption.py`
- Test: `tests/unit/test_re_v2_protocol_25_adoption.py`

**Interfaces:**
- Produces `FrozenAcceptancePackageV1(work_item, certification, candidate_assessment, acceptance, required_objects)`, `ImportedAcceptanceV1(artifact_key_id, work_item_id, receipt_ids, object_ids)`, `ImportedAcceptanceV1.from_package(package)`, and `CheckpointAdoptionReportV1`.
- Extracts `import_typed_acceptance(package: FrozenAcceptancePackageV1, destination_objects: ObjectStore, destination_ledger: Protocol22Ledger) -> ImportedAcceptanceV1` as the one low-level copy/append primitive used by both direct-parent and checkpoint adoption.
- Produces `import_frozen_checkpoint_closure(inputs: ValidatedProtocol26Inputs, objects: ObjectStore, ledger: Protocol22Ledger) -> CheckpointAdoptionReportV1`.
- The primitive imports one certification/work-item pair, optional candidate assessment and capture/payload objects, artifact object, and artifact acceptance receipt idempotently, then verifies exact replay equality.
- `import_parent_acceptance_closure()` keeps its public signature, result bytes, ordering, and error semantics.

- [x] **Step 1: Strengthen parent byte-compatibility and write failing checkpoint import tests**

```python
def test_parent_import_report_and_ledger_bytes_are_unchanged(parent_fixture: ParentFixture) -> None:
    before = parent_fixture.expected_import_bytes
    report = import_parent_acceptance_closure(
        parent_fixture.validated,
        parent_fixture.child_objects,
        parent_fixture.child_ledger,
    )
    assert parent_fixture.child_ledger.path.read_bytes() == before.ledger
    assert canonical_json_bytes(report.to_json_dict()) == before.report


def test_checkpoint_import_uses_only_child_copied_objects(
    protocol26_store: Protocol26Store,
) -> None:
    protocol26_store.delete_origins_and_cache()
    report = import_frozen_checkpoint_closure(
        protocol26_store.inputs,
        protocol26_store.objects,
        protocol26_store.ledger,
    )
    assert report.artifact_key_ids == protocol26_store.selection.selected_key_ids
```

- [x] **Step 2: Run adoption tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_adoption.py tests/unit/test_re_v2_protocol_25_adoption.py tests/unit/test_re_v2_protocol_26_adoption.py`

Expected: parent tests pass and checkpoint tests fail because the shared primitive/importer is absent.

- [x] **Step 3: Extract and reuse the one-artifact typed import primitive**

Implement the exact operation order:

```python
def import_typed_acceptance(
    package: FrozenAcceptancePackageV1,
    destination_objects: ObjectStore,
    destination_ledger: Protocol22Ledger,
) -> ImportedAcceptanceV1:
    _put_verified_objects(package.required_objects, destination_objects)
    destination_ledger.record_certification(package.certification, package.work_item)
    if package.candidate_assessment is not None:
        destination_ledger.record_candidate_assessment(package.candidate_assessment)
    destination_ledger.record_artifact_acceptance(package.acceptance)
    _verify_imported_acceptance(package, destination_ledger.replay())
    return ImportedAcceptanceV1.from_package(package)
```

Refactor direct-parent adoption to construct `FrozenAcceptancePackageV1` from its already validated parent state and call this primitive in the same sorted artifact-key order. Construct checkpoint packages only from the child's frozen selection and copied object store.

- [x] **Step 4: Add idempotence and conflict tests**

```python
def test_checkpoint_import_is_idempotent(protocol26_store: Protocol26Store) -> None:
    first = import_frozen_checkpoint_closure(
        protocol26_store.inputs, protocol26_store.objects, protocol26_store.ledger
    )
    bytes_after_first = protocol26_store.ledger.path.read_bytes()
    second = import_frozen_checkpoint_closure(
        protocol26_store.inputs, protocol26_store.objects, protocol26_store.ledger
    )
    assert second == first
    assert protocol26_store.ledger.path.read_bytes() == bytes_after_first


def test_frozen_checkpoint_conflict_blocks_without_fallback(protocol26_store: Protocol26Store) -> None:
    protocol26_store.seed_conflicting_acceptance()
    with pytest.raises(Protocol26AdoptionError, match="conflict"):
        import_frozen_checkpoint_closure(
            protocol26_store.inputs, protocol26_store.objects, protocol26_store.ledger
        )
```

- [x] **Step 5: Run all adoption tests and verify GREEN**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_adoption.py tests/unit/test_re_v2_protocol_25_adoption.py tests/unit/test_re_v2_protocol_26_adoption.py`

Expected: all pass and direct-parent ledger/report fixtures remain byte-identical.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_24/adoption.py \
  src/harness/re_v2/protocol_26/adoption.py \
  tests/unit/test_re_v2_protocol_24_adoption.py \
  tests/unit/test_re_v2_protocol_25_adoption.py \
  tests/unit/test_re_v2_protocol_26_adoption.py
git commit -m "refactor(re-v2): share typed acceptance import"
```

---

### Task 7: Add Protocol-2.6 Adoption Events and Replay Ordering

**Files:**
- Create: `src/harness/re_v2/protocol_26/events.py`
- Create: `tests/unit/test_re_v2_protocol_26_events.py`
- Modify: `src/harness/re_v2/protocol_26/adoption.py`

**Interfaces:**
- Produces `protocol_26_events_for(target_layer: Literal["L1", "L2", "L3"]) -> EventProtocol`; its delegate is `PROTOCOL_22_EVENTS`, `PROTOCOL_24_EVENTS`, or `PROTOCOL_25_EVENTS` respectively.
- Produces `Protocol26ReplayState(delegate, dispatched_work_items, adopted_work_items, artifact_keys, acceptance_receipts)`.
- Canonical `checkpoint_artifact_adopted` fields are exactly `checkpoint_selection_bundle_id`, `checkpoint_manifest_id`, `adopted_artifact_authority`, `origin_run_id`, `work_item_id`, and `selection_reason`.
- `append_missing_checkpoint_events(inputs: ValidatedProtocol26Inputs, event_store: EventStore, ledger: Protocol22Ledger, clock: Callable[[], str]) -> CheckpointAdoptionReportV1` appends in the frozen dependency order after the matching typed receipt exists and is idempotent across crashes.

- [x] **Step 1: Write failing event-schema and ordering tests**

```python
@pytest.mark.parametrize("target_layer", ["L1", "L2", "L3"])
def test_checkpoint_event_delegates_existing_layer_events(target_layer: str) -> None:
    protocol = protocol_26_events_for(target_layer)
    store = event_store(protocol)
    store.append("run_created", {"run_manifest_id": digest("manifest")})
    assert store.replay()[0].type == "run_created"


def test_checkpoint_adoption_must_precede_dispatch() -> None:
    state = protocol26_state("L1")
    state.consume(dispatch_leased_event("work-1"))
    with pytest.raises(ReV2EventError, match="precede"):
        state.consume(checkpoint_adopted_event("work-1"))


def test_checkpoint_adoption_rejects_duplicate_receipt() -> None:
    state = protocol26_state("L2")
    state.consume(checkpoint_adopted_event("work-1", receipt_id=digest("receipt")))
    with pytest.raises(ReV2EventError, match="duplicate acceptance receipt"):
        state.consume(checkpoint_adopted_event("work-2", receipt_id=digest("receipt")))


def test_checkpoint_adoption_is_invalid_during_any_active_dispatch() -> None:
    state = protocol26_state("L3")
    state.consume(dispatch_started_event("work-other"))
    with pytest.raises(ReV2EventError, match="active dispatch"):
        state.consume(checkpoint_adopted_event("work-1"))
```

- [x] **Step 2: Run event tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_events.py`

Expected: FAIL because protocol-2.6 event composition is absent.

- [x] **Step 3: Implement event delegation and checkpoint replay state**

Use composition, not copies of the layer schemas:

```python
def protocol_26_events_for(target_layer: TargetLayerV1) -> EventProtocol:
    delegate = {
        "L1": PROTOCOL_22_EVENTS,
        "L2": PROTOCOL_24_EVENTS,
        "L3": PROTOCOL_25_EVENTS,
    }[target_layer]
    return _Protocol26Events(target_layer=target_layer, delegate=delegate)


def consume(self, event: EventRecord) -> None:
    if event.type != "checkpoint_artifact_adopted":
        self.delegate_state.consume(event)
        self._observe_dispatch(event)
        return
    payload = _checkpoint_adoption_payload(event.payload)
    self._require_pre_dispatch_unique(payload)
    self.adopted_work_items.add(payload.work_item_id)
    self._mark_shared_accepted(payload.work_item_id, event.type)
```

The shared-accepted update must follow the existing `artifact_adopted` transition semantics for each delegated replay state; expose a narrow helper rather than mutating private nested state from adoption callers.

- [x] **Step 4: Implement idempotent event append after ledger import**

```python
for selected in inputs.checkpoint_selection.selected:
    if selected.source_kind != "workspace_checkpoint":
        continue
    _require_receipt_in_target_ledger(selected, ledger.replay())
    if selected.work_item_id in replay.adopted_work_items:
        _verify_existing_event(selected, events)
        continue
    event_store.append(
        "checkpoint_artifact_adopted",
        selected.to_event_payload(inputs.checkpoint_selection.identity),
        occurred_at=clock(),
    )
```

- [x] **Step 5: Run event and adoption tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_events.py tests/unit/test_re_v2_protocol_26_adoption.py`

Expected: all delegated-layer, pre-dispatch, duplicate, pause/terminal, and idempotence cases pass.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_26/events.py \
  src/harness/re_v2/protocol_26/adoption.py \
  tests/unit/test_re_v2_protocol_26_events.py \
  tests/unit/test_re_v2_protocol_26_adoption.py
git commit -m "feat(re-v2): authenticate checkpoint adoption events"
```

---

### Task 8: Bridge Schema 5 into Existing Recovery and Controllers

**Files:**
- Create: `src/harness/re_v2/protocol_26/authority.py`
- Create: `tests/unit/test_re_v2_protocol_26_authority.py`
- Modify: `src/harness/re_v2/protocol_22/recovery.py`
- Modify: `src/harness/re_v2/protocol_25/recovery.py`
- Test: `tests/unit/test_re_v2_protocol_22_recovery.py`
- Test: `tests/integration/test_re_v2_protocol_24_recovery.py`
- Test: `tests/integration/test_re_v2_protocol_25_recovery.py`

**Interfaces:**
- Produces `ResolvedRunAuthorityV1(active_manifest, layer_manifest, shared_inputs, shared_graph, semantic_inputs, semantic_graph)` and `resolve_run_authority(context: Protocol22RunContext) -> ResolvedRunAuthorityV1`. `semantic_inputs` and `semantic_graph` are non-null only for L3; `shared_inputs` and `shared_graph` are always the existing prerequisite authority consumed by `Protocol22RunContext`.
- For schemas 2–4, resolution returns the exact existing manifest/input/graph values. For schema 5, it loads `ValidatedProtocol26Inputs`, validates the outer/inner identity agreement, and reconstructs the existing layer input and graph from the pinned layer contract.
- Shared recovery authenticates `run_created` against `active_manifest.run_manifest_id`, but budget, planning, graph, and controller execution consume `layer_manifest` and existing layer inputs.
- Protocol-2.5 semantic recovery uses the same authority result and still requires `Protocol25RunContext`; no controller API changes.

- [x] **Step 1: Write failing authority and old-run non-regression tests**

```python
@pytest.mark.parametrize("target_layer", ["L1", "L2", "L3"])
def test_schema5_resolves_existing_layer_graph(protocol26_context, target_layer: str) -> None:
    context = protocol26_context(target_layer)
    authority = resolve_run_authority(context)
    assert authority.active_manifest.schema_version == 5
    assert authority.layer_manifest.target_layer == target_layer
    assert authority.shared_graph == context.graph
    assert (authority.semantic_graph is not None) == (target_layer == "L3")


def test_run_created_uses_outer_schema5_identity(protocol26_context) -> None:
    context = protocol26_context("L1")
    recover_protocol_22_run(context)
    event = context.event_store.replay()[0]
    assert event.payload["run_manifest_id"] == load_run_manifest(
        context.paths.root.parent
    ).run_manifest_id


def test_schema2_recovery_result_is_unchanged(protocol22_context) -> None:
    assert recover_protocol_22_run(protocol22_context) == protocol22_context.expected_recovery
```

- [x] **Step 2: Run authority and recovery tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_authority.py tests/unit/test_re_v2_protocol_22_recovery.py tests/integration/test_re_v2_protocol_24_recovery.py tests/integration/test_re_v2_protocol_25_recovery.py`

Expected: schema-5 cases fail at immutable manifest validation; old recovery tests pass.

- [x] **Step 3: Implement the additive authority resolver**

Use this result instead of teaching controllers about schema 5:

```python
@dataclass(frozen=True, slots=True)
class ResolvedRunAuthorityV1:
    active_manifest: Manifest
    layer_manifest: RunManifestV2 | RunManifestV3 | RunManifestV4
    shared_inputs: ValidatedProtocol22Inputs | ValidatedProtocol24Inputs
    shared_graph: Protocol22Graph | Protocol24Graph
    semantic_inputs: ValidatedProtocol25Inputs | None
    semantic_graph: Protocol25Graph | None

    @property
    def run_manifest_id(self) -> str:
        return self.active_manifest.run_manifest_id


def resolve_run_authority(context: Protocol22RunContext) -> ResolvedRunAuthorityV1:
    manifest = load_run_manifest(context.paths.root.parent)
    if isinstance(manifest, RunManifestV5):
        return _resolve_protocol_26_authority(context, manifest)
    return _resolve_legacy_authority(context, manifest)
```

Keep the legacy branch's loaders, errors, graph comparisons, return data, and mutation order byte-for-byte equivalent. Change recovery internals to read `authority.layer_manifest.initial_budget_policy` and `authority.active_manifest.created_at`, and validate `run_created` with `authority.run_manifest_id`.

- [x] **Step 4: Add protocol-2.6 event protocol to the existing supported-protocol guard**

```python
if isinstance(manifest, RunManifestV5):
    expected_protocol = protocol_26_events_for(manifest.target_layer)
    if context.event_store.protocol != expected_protocol:
        raise Protocol22RecoveryError("schema-5 event protocol does not match target layer")
```

Define value equality for `_Protocol26Events` by target layer or return cached singleton instances so context validation is deterministic.

- [x] **Step 5: Run old and new recovery tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_recovery.py tests/integration/test_re_v2_protocol_24_recovery.py tests/integration/test_re_v2_protocol_25_recovery.py tests/unit/test_re_v2_protocol_26_authority.py`

Expected: all pass; schemas 2–4 produce their previous events/results and schema 5 authenticates the outer identity while using the old layer graph.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_22/recovery.py \
  src/harness/re_v2/protocol_25/recovery.py \
  src/harness/re_v2/protocol_26/authority.py \
  tests/unit/test_re_v2_protocol_22_recovery.py \
  tests/integration/test_re_v2_protocol_24_recovery.py \
  tests/integration/test_re_v2_protocol_25_recovery.py \
  tests/unit/test_re_v2_protocol_26_authority.py
git commit -m "feat(re-v2): bridge checkpoint authority into layer recovery"
```

---

### Task 9: Create and Recover Checkpoint-Aware Runs Before Dispatch

**Files:**
- Create: `tests/integration/test_re_v2_protocol_26_recovery.py`
- Modify: `src/harness/re_v2/protocol_26/adoption.py`
- Modify: `src/harness/re_v2/protocol_26/authority.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_26.py`

**Interfaces:**
- Produces `_LayerCreationAuthorityV1(snapshot, layer_manifest, layer_inputs, graph, direct_parent_authority, authority_objects)` as the normalized result of current L1/L2/L3 preparation.
- Produces `_Protocol26Creation(snapshot, manifest, inputs, graph, direct_parent)` as the complete unpublished creation value.
- Defines `LayerParentV1 = ValidatedParentV1 | ValidatedProtocol25ParentV1 | ValidatedProtocol26ParentV1`.
- Produces `_build_protocol_26_creation(layer_creation: _LayerCreationAuthorityV1, contract: LayerExecutionContractV1, bundle: CheckpointSelectionBundleV1, direct_parent: LayerParentV1 | None) -> _Protocol26Creation`, which creates the two catalog references, `Protocol26InputSet`, and matching `RunManifestV5` in one place.
- Produces `_prepare_re_v26_creation(workspace_root: Path, *, target_layer: Literal["L1", "L2", "L3"], parent_run: Path | None, goal: Literal["baseline", "inventory"], deepen_options: _ReDeepenOptions | None, token_limit: int | None, time_limit_minutes: int | None) -> _Protocol26Creation` in `src/echelon/cli.py`. It calls the existing L1 pure preparation directly and extracted pure L2/L3 preparation seams to obtain an exact layer contract, then performs cache reconstruction and selection.
- Produces `validate_layer_parent(workspace_root: Path, parent_run: Path) -> LayerParentV1`. It dispatches schema-2/3/4 parents to their current exact validators and resolves a schema-5 parent's frozen layer contract and accepted self-contained authority through `validate_protocol_26_parent`. New L2/L3 children therefore accept schema-5 direct parents without weakening old parent validation.
- Produces `initialize_protocol_26_run(context) -> CheckpointAdoptionReportV1`, ordered as `run_created`, existing direct-parent import/events, workspace checkpoint typed imports/events, then normal planning.
- `_activate_re_v2_run()` is called only after schema-5 staged publication and successful initialization.
- Exact frozen-import conflicts block the child without calling the provider; ordinary discovery misses leave work ready for normal generation.

- [x] **Step 1: Write failing zero-dispatch, partial-adoption, and conflict tests**

```python
def test_fully_adopted_l1_run_completes_without_provider_call(
    checkpoint_cli_workspace: CheckpointCliWorkspace,
) -> None:
    checkpoint_cli_workspace.seed_complete_l1_origin()
    result = checkpoint_cli_workspace.run_re_v2(provider=FailIfCalledProvider())
    assert result.status == "complete"
    assert result.provider_calls == 0
    assert result.checkpoint_adopted == result.graph_work_items


def test_partial_adoption_dispatches_only_missing_work(
    checkpoint_cli_workspace: CheckpointCliWorkspace,
) -> None:
    checkpoint_cli_workspace.seed_one_domain_origin()
    provider = RecordingProvider.successful()
    result = checkpoint_cli_workspace.run_re_v2(provider=provider)
    assert result.checkpoint_adopted == 1
    assert set(provider.work_item_ids).isdisjoint(result.adopted_work_item_ids)


def test_postfreeze_conflict_never_falls_back_to_provider(protocol26_context) -> None:
    provider = FailIfCalledProvider()
    context = protocol26_context.with_conflicting_import(provider=provider)
    with pytest.raises(Protocol26AdoptionError):
        initialize_protocol_26_run(context)


def test_adoption_consumes_no_execution_or_semantic_budget(protocol26_context) -> None:
    context = protocol26_context("L3")
    before = context.budget_without_checkpoint_events()
    initialize_protocol_26_run(context)
    after = context.replayed_budget()
    assert after.provider_tokens == before.provider_tokens
    assert after.provider_active_seconds == before.provider_active_seconds
    assert after.retry_counts == before.retry_counts
    assert after.semantic_rounds == before.semantic_rounds
```

- [x] **Step 2: Run the integration tests and confirm RED**

Run: `pytest -q tests/integration/test_re_v2_protocol_26_recovery.py tests/unit/test_cli_re_v2_protocol_26.py`

Expected: FAIL because creation and initialization are not routed.

- [x] **Step 3: Implement schema-5 preparation by composing current builders**

Use existing preparation results as immutable input, not copied policy logic:

```python
validated_parent = (
    None
    if parent_run is None
    else validate_layer_parent(workspace_root, parent_run)
)
layer_creation = {
    "L1": lambda: _prepare_re_v22_creation(workspace_root, goal=goal, token_limit=token_limit, time_limit_minutes=time_limit),
    "L2": lambda: _prepare_re_v24_layer_contract(workspace_root, parent=validated_parent, options=deepen_options),
    "L3": lambda: _prepare_re_v25_layer_contract(workspace_root, parent=validated_parent, options=deepen_options),
}[target_layer]()
contract = LayerExecutionContractV1.from_layer_manifest(layer_creation.layer_manifest)
cache = rebuild_checkpoint_cache(workspace_root)
bundle = select_checkpoints(layer_creation.graph, cache.manifests, layer_creation.parent_authority)
return _build_protocol_26_creation(layer_creation, contract, bundle, validated_parent)
```

Extract `_prepare_re_v24_layer_contract` from the current `_prepare_re_v24_creation` body and the corresponding pure L3 preparation seam from the current protocol-2.5 lifecycle helper. Their existing schema-3/schema-4 wrappers continue calling those seams with the old validated-parent types and must retain exact output. The protocol-2.6 parent adapter exposes the same accepted-authority inputs from its self-contained child store and enforces the current completed-parent/complete-closure gate; partial schema-5 authority remains a workspace-checkpoint candidate, not a direct parent. Do not duplicate L2/L3 policy or graph construction.

- [x] **Step 4: Implement idempotent initialization before normal recovery**

```python
with protocol_22_run_lock(context.paths):
    manifest = load_run_manifest(context.paths.root.parent)
    if not isinstance(manifest, RunManifestV5):
        raise Protocol26AdoptionError("checkpoint initialization requires schema 5")
    inputs = load_protocol_26_inputs(context.paths, manifest)
    _ensure_run_created_for_outer_manifest(context)
    _initialize_existing_direct_parent(context)
    report = import_frozen_checkpoint_closure(
        inputs, context.object_store, context.ledger
    )
    append_missing_checkpoint_events(
        inputs, context.event_store, context.ledger, context.clock
    )
    _verify_all_selected_items_are_accepted_pre_dispatch(context)
return report
```

After initialization, pass the existing `Protocol22RunContext` or `Protocol25RunContext` to its existing controller. Do not wrap provider execution or intercept provider results.

- [x] **Step 5: Add crash recovery at every import boundary**

```python
@pytest.mark.parametrize(
    "seam",
    ["run_created", "parent_imported", "checkpoint_receipt_imported", "checkpoint_event_appended", "first_plan"],
)
def test_checkpoint_initialization_recovers_without_redispatch(
    protocol26_context,
    seam: str,
) -> None:
    context = protocol26_context.with_fault(seam)
    assert_retry_finishes_with_same_ledger_events_and_zero_adopted_dispatches(context)


@pytest.mark.parametrize("to_layer", ["L2", "L3"])
def test_schema5_parent_is_valid_direct_parent(protocol26_parent_workspace, to_layer: str) -> None:
    child = protocol26_parent_workspace.deepen_schema5_parent(to_layer)
    assert child.direct_parent_adopted_count > 0
    assert child.workspace_checkpoint_count_for_parent_keys == 0
```

- [x] **Step 6: Run recovery and CLI unit tests**

Run: `pytest -q tests/integration/test_re_v2_protocol_26_recovery.py tests/unit/test_cli_re_v2_protocol_26.py`

Expected: full adoption is zero-call, partial adoption calls only missing work, fault retries are exact, and post-freeze conflicts do not dispatch.

- [x] **Step 7: Commit**

```bash
git add src/echelon/cli.py \
  src/harness/re_v2/protocol_26/adoption.py \
  src/harness/re_v2/protocol_26/authority.py \
  tests/unit/test_cli_re_v2_protocol_26.py \
  tests/integration/test_re_v2_protocol_26_recovery.py
git commit -m "feat(re-v2): initialize checkpoint runs before dispatch"
```

---

### Task 10: Cut New L1, L2, and L3 Creation Over to Protocol 2.6

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_22.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_24.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_25.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_26.py`
- Create: `tests/integration/test_re_v2_protocol_26_cli.py`
- Modify: `tests/support/re_v2_layered_workspace.py`

**Interfaces:**
- New `echelon re run --engine v2` L1 creation and new `echelon re deepen --to L2|L3` child creation publish protocol 2.6/schema 5.
- `echelon re continue`, `status`, `pause`, `stop`, and exact child reuse route schemas 2–4 exactly as recorded and schema 5 through `protocol_26` authority resolution.
- Direct-parent precedence is frozen before workspace candidates and remains visible as existing `artifact_adopted` events; sibling reuse uses `checkpoint_artifact_adopted`.
- No new user flag is added. Adoption is automatic.

- [x] **Step 1: Write failing CLI routing and old-run continuation tests**

```python
def test_new_v2_l1_run_uses_protocol_2_6(cli_workspace) -> None:
    result = cli_workspace.run("re", "run", "--engine", "v2")
    manifest = load_run_manifest(result.run_dir)
    assert (manifest.schema_version, manifest.engine_protocol_version) == (5, "2.6")


@pytest.mark.parametrize("to_layer", ["L2", "L3"])
def test_new_deepening_child_uses_protocol_2_6(layered_workspace, to_layer: str) -> None:
    child = layered_workspace.deepen(to_layer)
    manifest = load_run_manifest(child)
    assert manifest.target_layer == to_layer
    assert manifest.engine_protocol_version == "2.6"


@pytest.mark.parametrize("schema", [2, 3, 4])
def test_existing_run_continues_with_recorded_protocol(cli_workspace, schema: int) -> None:
    run = cli_workspace.install_frozen_run(schema)
    cli_workspace.continue_run(run)
    assert run.manifest_bytes == cli_workspace.frozen_manifest_bytes(schema)
```

- [x] **Step 2: Run CLI tests and confirm RED**

Run: `pytest -q tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_v2_protocol_24.py tests/unit/test_cli_re_v2_protocol_25.py tests/unit/test_cli_re_v2_protocol_26.py tests/integration/test_re_v2_protocol_26_cli.py`

Expected: new-run schema expectations fail; old-run cases pass.

- [x] **Step 3: Route creation, context, live execution, and continuation by pinned manifest**

Add exact dispatch without changing CLI syntax:

```python
if isinstance(manifest, RunManifestV5):
    context = _re_v26_context(project_root, run_dir, manifest)
elif isinstance(manifest, RunManifestV4):
    context = _re_v25_context(project_root, run_dir)
elif isinstance(manifest, RunManifestV3):
    context = _re_v24_context(project_root, run_dir)
elif isinstance(manifest, RunManifestV2):
    context = _re_v22_context(project_root, run_dir)
else:
    raise ValueError("unsupported RE v2 manifest")
```

For schema 5, `_run_re_v2_live()` chooses the existing controller from `manifest.target_layer` and the resolved existing context type. Existing schemas never run discovery.

After the clean-source check but before checkpoint-cache reconstruction, run the existing exact-request lookup over both legacy manifests and schema-5 inner layer contracts. If an exact terminal schema-5 child exists, return it immediately without rebuilding the cache, appending events, or dispatching; if an exact paused child exists, retain the existing continuation/resource-authorization semantics.

- [x] **Step 4: Enforce clean source preflight before cache discovery**

```python
source_plan = plan_clean_workspace_sources(project_root, workspace_manifest.sources)
validate_source_plan_matches_snapshot(source_plan, snapshot)
creation = _prepare_re_v26_creation(project_root, target_layer=target_layer, request=request)
```

Map `ReV2WorkspaceSourceError` to the existing message: `Commit, stash (including untracked files), or revert the source changes, then retry.` Confirm no cache directory or run directory is created on dirty-source failure.

- [x] **Step 5: Add direct-parent precedence and exact-reuse integration cases**

```python
def test_direct_parent_event_wins_over_stronger_workspace_candidate(layered_workspace) -> None:
    child = layered_workspace.deepen_with_parent_and_stronger_sibling()
    events = child.events()
    assert any(event.type == "artifact_adopted" for event in events)
    assert not child.checkpoint_event_for(child.parent_artifact_key)


def test_exact_terminal_request_adds_no_events_or_dispatches(layered_workspace) -> None:
    child = layered_workspace.complete_protocol26_child()
    before = child.snapshot_activity()
    reused = layered_workspace.repeat_exact_request()
    assert reused.run_id == child.run_id
    assert reused.snapshot_activity() == before
```

- [x] **Step 6: Run full CLI routing matrix**

Run: `pytest -q tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_v2_protocol_24.py tests/unit/test_cli_re_v2_protocol_25.py tests/unit/test_cli_re_v2_protocol_26.py tests/integration/test_re_v2_protocol_26_cli.py`

Expected: new L1/L2/L3 runs pin 2.6, old runs retain recorded routing, source dirt blocks before discovery, parent precedence is exact, and terminal reuse is no-call.

- [x] **Step 7: Commit**

```bash
git add src/echelon/cli.py tests/support/re_v2_layered_workspace.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/unit/test_cli_re_v2_protocol_26.py \
  tests/integration/test_re_v2_protocol_26_cli.py
git commit -m "feat(re-v2): adopt checkpoints in new layered runs"
```

---

### Task 11: Surface Truthful Checkpoint Status and Telemetry

**Files:**
- Create: `src/harness/re_v2/protocol_26/status.py`
- Create: `tests/unit/test_re_v2_protocol_26_status.py`
- Modify: `src/harness/re_v2/status.py`
- Modify: `src/harness/re_v2/protocol_22/status.py`
- Modify: `src/harness/re_v2/protocol_24/status.py`
- Modify: `src/harness/re_v2/protocol_25/status.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_26.py`

**Interfaces:**
- Produces `CheckpointStatusV1.from_authority(selection, adopted_events, reservation_for)` with cache generation/reconstruction state; discovered, compatible, selected, adopted, rejected, and quarantined counts; grouped counts/bytes; origin and manifest IDs; precedence and reasons; avoided dispatches; avoided token/active-time reservations; and zero-dispatch reuse.
- Produces `protocol_22_status_from_authority`, `protocol_24_status_from_authority`, and `protocol_25_status_from_authority` as pure seams beneath the existing public status functions. Existing schema-specific status functions resolve their current authority and call the seam unchanged; protocol 2.6 supplies its resolved inner layer authority and protocol-2.6 event store to the same seam.
- Produces `decorate_protocol_26_status(base_status, manifest, inputs, events) -> Mapping[str, object]` and a final banner that states adopted versus generated authority without claiming synthesis, publication, L4, repair, or partial completeness.
- Avoided resources come from existing conservative reservation calculations and are labeled `avoided_*_reservation`, never observed usage.
- `echelon re status --json` returns the same data as human status without reading origins or cache.

- [x] **Step 1: Write failing JSON and banner tests**

```python
def test_status_reports_checkpoint_origins_and_avoided_reservations(protocol26_status_fixture) -> None:
    status = protocol26_status_fixture.json_status()
    assert status["checkpoints"]["adopted_count"] == 2
    assert status["checkpoints"]["avoided_dispatch_count"] == 2
    assert status["checkpoints"]["avoided_token_reservation"] > 0
    assert "observed_tokens" not in status["checkpoints"]


def test_banner_does_not_overclaim_partial_authority(protocol26_status_fixture) -> None:
    banner = protocol26_status_fixture.partial_banner()
    assert "adopted 2" in banner
    assert "generated 1" in banner
    for forbidden in ("workspace synthesis complete", "published", "L4 complete", "repair complete"):
        assert forbidden not in banner
```

- [x] **Step 2: Run status tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_26_status.py tests/unit/test_cli_re_v2_protocol_26.py`

Expected: FAIL because status decoration is absent.

- [x] **Step 3: Implement status entirely from frozen child authority**

```python
def decorate_protocol_26_status(base, manifest, inputs, events):
    adopted = checkpoint_events(events)
    checkpoint = CheckpointStatusV1.from_authority(
        selection=inputs.checkpoint_selection,
        adopted_events=adopted,
        reservation_for=reservation_for_layer_work_item,
    )
    return {**base, "engine_protocol_version": "2.6", "checkpoints": checkpoint.to_json_dict()}
```

Resolve the active schema-5 manifest once, call the pure status seam selected by `target_layer` with the inner manifest/input/graph and schema-5 event protocol, then decorate the resulting document. Use selection rejection/quarantine records frozen in the child, not the current cache. Group deterministically by source/domain/layer/artifact kind and redact raw provider output/guidance.

- [x] **Step 4: Add cache-deleted, origin-deleted, zero-dispatch, and partial-generation cases**

```python
def test_status_survives_deleted_cache_and_origin(protocol26_status_fixture) -> None:
    protocol26_status_fixture.delete_cache_and_origins()
    assert protocol26_status_fixture.json_status()["checkpoints"]["adopted_count"] == 2


def test_zero_dispatch_completion_is_explicit(protocol26_status_fixture) -> None:
    status = protocol26_status_fixture.zero_dispatch_status()
    assert status["checkpoints"]["zero_dispatch_reuse"] is True
```

- [x] **Step 5: Run status and legacy status tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_status.py tests/unit/test_re_v2_protocol_24_status.py tests/unit/test_re_v2_protocol_25_status.py tests/unit/test_re_v2_protocol_26_status.py tests/unit/test_cli_re_v2_protocol_26.py`

Expected: all pass and old human/JSON status fixtures remain exact.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/status.py src/echelon/cli.py \
  src/harness/re_v2/protocol_22/status.py \
  src/harness/re_v2/protocol_24/status.py \
  src/harness/re_v2/protocol_25/status.py \
  src/harness/re_v2/protocol_26/status.py \
  tests/unit/test_re_v2_protocol_26_status.py \
  tests/unit/test_cli_re_v2_protocol_26.py
git commit -m "feat(re-v2): report checkpoint adoption and savings"
```

---

### Task 12: Complete Fault-Injection, Compatibility, and Live Provider Gates

**Files:**
- Create: `tests/integration/test_re_v2_protocol_26_live.py`
- Modify: `tests/integration/test_re_v2_protocol_26_recovery.py`
- Modify: `tests/contract/test_re_v2_bounded_api.py`
- Modify: `tests/unit/test_re_v2_protocol_compatibility.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-08-28-re-v2-adoptable-checkpoints-design.md`

**Interfaces:**
- Proves origin states active/paused/blocked/failed-unrelated/complete, concurrent append, corrupted candidate with sibling fallback, no valid candidate generation, all creation/import crash seams, origin/cache deletion, exact terminal reuse, and clean Git.
- Proves schemas 1–4 and v1 routing are unchanged and provider execution remains the existing Prosaic/shared-provider path.
- Marks EGR-166 fixed only after a real Codex sibling-run pilot demonstrates automatic partial adoption and zero calls for adopted work.

- [x] **Step 1: Add the complete fault and compatibility matrices**

```python
@pytest.mark.parametrize("origin_state", ["active", "paused", "blocked", "failed_unrelated", "complete"])
def test_origin_terminal_state_is_irrelevant(real_git_checkpoint_workspace, origin_state: str) -> None:
    result = real_git_checkpoint_workspace.adopt_from(origin_state)
    assert result.adopted_count == 1
    assert result.provider_calls_for_adopted == 0


def test_corrupt_best_candidate_quarantines_and_uses_valid_sibling(real_git_checkpoint_workspace) -> None:
    result = real_git_checkpoint_workspace.run_with_corrupt_and_valid_siblings()
    assert result.selected_origin == "valid-sibling"
    assert result.rejection_counts["checkpoint_object_hash_mismatch"] == 1


def test_protocol_2_2_through_2_5_fixtures_remain_exact(frozen_protocol_fixtures) -> None:
    for fixture in frozen_protocol_fixtures:
        assert load_run_manifest(fixture.run_dir).to_json_dict() == fixture.manifest_json
        assert fixture.continue_without_changes().activity == fixture.expected_activity
```

- [x] **Step 2: Run the offline protocol-2.6 and compatibility suite**

Run:

```bash
pytest -q \
  tests/unit/test_re_v2_protocol_26_model.py \
  tests/unit/test_re_v2_protocol_26_reconstruction.py \
  tests/unit/test_re_v2_protocol_26_cache.py \
  tests/unit/test_re_v2_protocol_26_selection.py \
  tests/unit/test_re_v2_protocol_26_inputs.py \
  tests/unit/test_re_v2_protocol_26_adoption.py \
  tests/unit/test_re_v2_protocol_26_events.py \
  tests/unit/test_re_v2_protocol_26_authority.py \
  tests/unit/test_re_v2_protocol_26_status.py \
  tests/unit/test_cli_re_v2_protocol_26.py \
  tests/integration/test_re_v2_protocol_26_recovery.py \
  tests/integration/test_re_v2_protocol_26_cli.py \
  tests/contract/test_re_v2_bounded_api.py \
  tests/unit/test_re_v2_protocol_compatibility.py
```

Expected: all pass without network or provider access.

- [x] **Step 3: Run the existing L0-through-L3 regression matrix**

Run:

```bash
pytest -q \
  tests/unit/test_re_v2_protocol_22_*.py \
  tests/unit/test_re_v2_protocol_24_*.py \
  tests/unit/test_re_v2_protocol_25_*.py \
  tests/integration/test_re_v2_protocol_22_*.py \
  tests/integration/test_re_v2_protocol_24_*.py \
  tests/integration/test_re_v2_protocol_25_*.py \
  tests/integration/test_re_v2_v1_isolation.py
```

Expected: all pass; provider/runtime authority digests and legacy canonical fixture bytes remain unchanged.

- [x] **Step 4: Install the checkout and create a clean real Codex pilot workspace**

Run:

```bash
bash scripts/install.sh
git status --short
```

Expected: installation succeeds and the Echelon repository is clean. In a temporary clean Git workspace configured with the normal Codex provider and Prosaic metadata, create an origin that accepts one domain and pauses before an independent sibling.

- [x] **Step 5: Execute and verify the real sibling-run pilot**

Run from the pilot workspace:

```bash
echelon re run --engine v2
echelon re status --json
```

Expected: the sibling schema-5 run automatically adopts the origin domain and exact dependency closure; status reports zero provider calls for adopted work and normal calls only for missing work. Then move the origin and `.echelon/re-v2/checkpoints/` aside, continue the child, repeat the exact terminal request, and verify no new events or provider invocations.

- [x] **Step 6: Record the exact pilot evidence and close EGR-166**

Update the design status to `Implemented`, add a `[Unreleased]` changelog entry naming EGR-166, and update the register row with exact source/test evidence and pilot run IDs. Use wording with this factual shape:

```markdown
| EGR-166 | P1 | fixed | Accepted RE v2 artifacts were stranded outside direct-parent terminal lineage. | Protocol 2.6 reconstructs, selects, stages, and adopts exact dependency-closed sibling checkpoints; cite the recorded Codex status count, its zero-call evidence for adopted items, and successful continuation after origin/cache removal. | Fixed: new L1/L2/L3 runs adopt automatically; schemas 2-4 continue unchanged. |
```

Copy the observed integer from `echelon re status --json` into the final register prose and include exact verification commands/results in the review note; do not estimate or invent telemetry.

- [x] **Step 7: Run the final documentation and focused gates**

Run:

```bash
pytest -q tests/unit/test_documentation_gate.py tests/unit/test_re_v2_protocol_compatibility.py tests/integration/test_re_v2_protocol_26_live.py
git diff --check
git status --short
```

Expected: all pass; diff check is clean; only the intended implementation/doc changes are present.

- [x] **Step 8: Commit**

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md \
  docs/superpowers/specs/2026-08-28-re-v2-adoptable-checkpoints-design.md \
  tests/contract/test_re_v2_bounded_api.py \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/integration/test_re_v2_protocol_26_recovery.py \
  tests/integration/test_re_v2_protocol_26_live.py
git commit -m "test(re-v2): verify adoptable checkpoints end to end"
```

---

## Completion Gate

Do not declare EGR-166 complete until all of these are true:

- A nonterminal sibling's accepted artifact is discovered and selected automatically.
- The selected set is exact-compatible, quality-ranked, deterministic, acyclic, and dependency-closed.
- Direct-parent authority wins over every workspace checkpoint candidate.
- The child can recover and continue after both origin and cache removal.
- Fully adopted work has zero provider dispatches and zero retry/semantic-budget increments.
- Post-freeze authority conflicts block without generation fallback.
- Dirty sources fail before cache discovery or run creation with commit/stash/revert guidance.
- `echelon re status --json` explains adoption, rejection, quarantine, origins, and avoided reservations from frozen child authority.
- Protocols 2.2 through 2.5 and v1 routing retain exact fixture bytes and behavior.
- The real Codex pilot passes through the existing Prosaic/shared-provider path with clean Git.
- `CHANGELOG.md`, EGR-166, and the design status contain exact tested evidence.
