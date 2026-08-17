# RE v2 Pinned Execution Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an additive, opt-in RE v2 execution kernel whose immutable source snapshot, append-only decisions, durable candidates, certified artifacts, independent budgets, deterministic recovery, publication roots, and status projection can be proven without changing any RE v1 run.

**Architecture:** Add a focused `harness.re_v2` package below the existing CLI. A small engine router sends runs with an immutable v2 manifest to the new controller and leaves all other runs on `ReLifecycleController`; the v2 controller derives work from a deterministic DAG, persists provider output before interpreting it, and accepts artifacts only through controller-owned certification. EGR-164 ships the kernel, deterministic inventory work, fake-executor live tests, and shadow planning; EGR-165 through EGR-169 register the real layered producers and policies.

**Tech Stack:** Python 3.11+, standard-library dataclasses/enums/hashlib/json/fcntl/subprocess/shutil/tempfile, Typer CLI, existing `harness.publication_transaction` durability helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-re-v2-execution-kernel-design.md`

## Global Constraints

- Existing v1 run directories, state transitions, CLI defaults, tests, and publication behavior remain byte-for-byte compatible unless a test explicitly exercises the new engine router.
- A run records `engine: re-v2` and `engine_protocol_version: "2.0"` once; continuation never upgrades either value.
- `runs/<run-id>/v2/run.json`, source snapshot identity, partition identity, and requested goals are immutable after creation.
- Providers read the frozen snapshot path, never the mutable source checkout.
- Provider output is an untrusted candidate; only a controller verifier can issue a certification and artifact-acceptance event.
- `events.jsonl`, `ledger.jsonl`, immutable object bytes, and `run.json` are authoritative; `projection.json` is rebuildable and must be byte-identical after replay.
- Global token/time authorization never increases provider attempts, artifact-generation attempts, semantic rounds, or result-contract retries.
- V2 uses no `--re-max-inner` coupling.
- `paused` is continuable; `complete`, `finalized_partial`, and `failed` are terminal.
- The initial dispatcher is single-work-item. Parallel scheduling is outside EGR-164.
- No new third-party runtime dependency is introduced.

## File Structure

Create one package whose modules each own a single durability or execution boundary:

```text
src/harness/re_v2/
  __init__.py       public protocol/version constants and exported controller API
  canonical.py      canonical JSON and content/tree hashing
  model.py          immutable manifests, keys, work items, receipts, and observations
  run_store.py      v2 layout, immutable run creation/loading, engine detection
  snapshot.py       clean-Git and copied content snapshot capture/validation
  events.py         locked hash-chained event append and replay
  projection.py     pure event-to-status projection
  ledger.py         immutable object store and artifact/certification receipts
  budget.py         independent usage/authorization accounting
  planner.py        deterministic DAG validation, ready queue, and explanations
  candidates.py     dispatch leases and atomic candidate persistence
  recovery.py       lease/candidate reconciliation after interruption
  publication.py    exact-root generation manifests and CAS workspace index
  controller.py     single-dispatch orchestration over the preceding interfaces
  status.py         human and machine-readable status summaries/final banner data
```

Modify only these existing integration files:

```text
src/harness/re_lifecycle.py
src/echelon/cli.py
src/echelon/cli_app.py
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
```

Mirror each new module with `tests/unit/test_re_v2_<name>.py`; add CLI compatibility cases to `tests/unit/test_cli_re_lifecycle.py` and `tests/unit/test_cli_typer_app.py`.

---

### Task 1: Canonical Values and Immutable Kernel Models

**Files:**
- Create: `src/harness/re_v2/__init__.py`
- Create: `src/harness/re_v2/canonical.py`
- Create: `src/harness/re_v2/model.py`
- Create: `tests/unit/test_re_v2_model.py`

**Interfaces:**
- Produces: `RE_V2_ENGINE = "re-v2"`, `RE_V2_PROTOCOL = "2.0"`.
- Produces: `canonical_json_bytes(value: object) -> bytes` and `content_digest(value: bytes | object) -> str`.
- Produces: frozen `RunManifest`, `ArtifactKey`, `CertificationKey`,
  `WorkTemplate`, `WorkItem`, `BudgetPolicy`, `ExecutionObservation`,
  `ArtifactReceipt`, and `CertificationReceipt` dataclasses with
  `to_json_dict()` and validating `from_json_dict()` constructors.
- Consumes: no v1 state types.

- [ ] **Step 1: Write failing canonicalization and identity tests**

```python
def test_artifact_identity_ignores_operational_budget() -> None:
    key = ArtifactKey(
        source_snapshot_id="sha256:" + "1" * 64,
        partition_manifest_id="sha256:" + "2" * 64,
        artifact_kind="source-inventory",
        layer="L0",
        producer_protocol_version="inventory-v1",
        layer_policy_hash="sha256:" + "3" * 64,
        dependency_hashes=(),
    )
    assert key.identity == ArtifactKey.from_json_dict(key.to_json_dict()).identity
    assert "budget" not in key.to_json_dict()


def test_run_manifest_rejects_unknown_engine() -> None:
    raw = valid_run_manifest_dict()
    raw["engine"] = "re-v3"
    with pytest.raises(ReV2ModelError, match="unsupported engine"):
        RunManifest.from_json_dict(raw)
```

- [ ] **Step 2: Run the model tests and confirm the missing package failure**

Run: `pytest -q tests/unit/test_re_v2_model.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'harness.re_v2'`.

- [ ] **Step 3: Implement canonical JSON and validated frozen dataclasses**

```python
def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"


def content_digest(value: bytes | object) -> str:
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactKey:
    source_snapshot_id: str
    partition_manifest_id: str
    artifact_kind: str
    layer: str
    producer_protocol_version: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())
```

Validate lowercase `sha256:<64 hex>` digests, safe IDs, lifecycle states,
nonnegative counters, unique sorted dependency hashes, and canonical round
trips. `WorkTemplate` names logical prerequisite template IDs; a `WorkItem` is
created only after those prerequisites are certified and contains their exact
artifact object hashes in its output `ArtifactKey.dependency_hashes`. Keep model
constructors free of filesystem access.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/unit/test_re_v2_model.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the model boundary**

```bash
git add src/harness/re_v2/__init__.py src/harness/re_v2/canonical.py src/harness/re_v2/model.py tests/unit/test_re_v2_model.py
git commit -m "feat(re-v2): define canonical kernel models"
```

### Task 2: Immutable Run Store and Engine Detection

**Files:**
- Create: `src/harness/re_v2/run_store.py`
- Create: `tests/unit/test_re_v2_run_store.py`
- Modify: `src/harness/re_lifecycle.py`
- Test: `tests/unit/test_re_lifecycle.py`

**Interfaces:**
- Consumes: `RunManifest`, `canonical_json_bytes()`, `RE_V2_ENGINE`, and `RE_V2_PROTOCOL` from Task 1.
- Produces: `ReV2Paths.for_run(run_dir: Path) -> ReV2Paths`.
- Produces: `create_run_store(run_dir: Path, manifest: RunManifest) -> ReV2Paths`.
- Produces: `load_run_manifest(run_dir: Path) -> RunManifest`.
- Produces: `detect_re_engine(run_dir: Path) -> Literal["v1", "v2"]`.

- [ ] **Step 1: Write failing immutable-create and engine-detection tests**

```python
def test_run_manifest_is_create_once(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/re-1"
    first = run_manifest(run_id="re-1")
    create_run_store(run_dir, first)
    with pytest.raises(ReV2RunStoreError, match="already exists"):
        create_run_store(run_dir, first)
    assert load_run_manifest(run_dir) == first


def test_engine_detection_never_guesses_from_outer_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/re-legacy"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text('{"engine":"re-v2"}')
    assert detect_re_engine(run_dir) == "v1"
```

- [ ] **Step 2: Run tests and verify missing run-store symbols**

Run: `pytest -q tests/unit/test_re_v2_run_store.py tests/unit/test_re_lifecycle.py -k 'engine or manifest_is_create_once'`

Expected: new tests fail because `run_store.py` and `detect_re_engine()` do not exist.

- [ ] **Step 3: Implement path-safe create-once storage**

```python
@dataclass(frozen=True, slots=True)
class ReV2Paths:
    root: Path
    manifest: Path
    events: Path
    projection: Path
    ledger: Path
    candidates: Path

    @classmethod
    def for_run(cls, run_dir: Path) -> "ReV2Paths":
        root = run_dir.resolve() / "v2"
        return cls(root, root / "run.json", root / "events.jsonl",
                   root / "projection.json", root / "ledger.jsonl",
                   root / "candidates")


def detect_re_engine(run_dir: Path) -> Literal["v1", "v2"]:
    paths = ReV2Paths.for_run(run_dir)
    if paths.root.exists() and not paths.manifest.exists():
        raise ReV2RunStoreError("incomplete v2 run store has no immutable manifest")
    if not paths.manifest.exists():
        return "v1"
    manifest = load_run_manifest(run_dir)
    if manifest.engine != RE_V2_ENGINE or manifest.engine_protocol_version != RE_V2_PROTOCOL:
        raise ReV2RunStoreError("unsupported pinned RE engine/protocol")
    return "v2"
```

Write `run.json` through a same-directory temporary file using exclusive create,
`fsync`, and rename. Refuse symlinked run/v2 paths, an existing manifest, a
manifest whose `run_id` differs from the directory, and unsupported schema or
protocol versions. A present `v2/` directory without `run.json` is an incomplete
v2 creation and fails closed; it is never routed to v1.

- [ ] **Step 4: Prove v1 remains the default**

Add a regression asserting a run without `v2/run.json` is detected as v1 and
the existing lifecycle controller path is unchanged.

Run: `pytest -q tests/unit/test_re_v2_run_store.py tests/unit/test_re_lifecycle.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the run-store boundary**

```bash
git add src/harness/re_v2/run_store.py src/harness/re_lifecycle.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_lifecycle.py
git commit -m "feat(re-v2): pin immutable run manifests"
```

### Task 3: Frozen Source Snapshots

**Files:**
- Create: `src/harness/re_v2/snapshot.py`
- Create: `tests/unit/test_re_v2_snapshot.py`

**Interfaces:**
- Consumes: canonical hashing from Task 1.
- Produces: `SnapshotEntry`, `SnapshotManifest`, and `CapturedSnapshot`.
- Produces: `capture_source_snapshot(source_root: Path, destination_root: Path, *, exclusions: tuple[str, ...]) -> CapturedSnapshot`.
- Produces: `validate_source_snapshot(snapshot: CapturedSnapshot) -> None`.

- [ ] **Step 1: Write failing copy, mutation, Git, and symlink tests**

```python
def test_dirty_source_is_copied_and_pinned(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n")
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    (source / "api.py").write_text("VALUE = 2\n")
    assert (captured.read_root / "api.py").read_text() == "VALUE = 1\n"
    validate_source_snapshot(captured)


def test_snapshot_validation_rejects_changed_bytes(tmp_path: Path) -> None:
    captured = copied_snapshot(tmp_path)
    make_writable(captured.read_root / "api.py")
    (captured.read_root / "api.py").write_text("tampered\n")
    with pytest.raises(ReV2SnapshotError, match="hash mismatch"):
        validate_source_snapshot(captured)
```

- [ ] **Step 2: Run snapshot tests and verify they fail**

Run: `pytest -q tests/unit/test_re_v2_snapshot.py`

Expected: collection fails because the snapshot module is absent.

- [ ] **Step 3: Implement deterministic copied snapshots**

```python
@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    read_root: Path
    manifest_path: Path
```

For dirty and non-Git sources, copy files into a unique temporary directory,
reject symlinks and special files, write the canonical entry manifest, rename
to `<snapshot-id>/`, then make files read-only. Do not implement reflink or
hard-link optimization in this milestone.

- [ ] **Step 4: Add the clean-Git detached-worktree path**

Resolve `HEAD^{commit}`, verify `git status --porcelain --untracked-files=all`
is empty, run `git worktree add --detach <temporary> <commit>`, record commit and
submodule identities in the manifest, use `git worktree move` to place it at the
snapshot-ID path without breaking Git administrative metadata, and then make
its contents read-only. Inject `run_git(args: list[str])` so unit tests avoid
global Git configuration.

- [ ] **Step 5: Run snapshot tests**

Run: `pytest -q tests/unit/test_re_v2_snapshot.py`

Expected: all tests pass.

- [ ] **Step 6: Commit snapshot capture**

```bash
git add src/harness/re_v2/snapshot.py tests/unit/test_re_v2_snapshot.py
git commit -m "feat(re-v2): freeze source snapshots"
```

### Task 4: Hash-chained Event Log and Byte-identical Projection

**Files:**
- Create: `src/harness/re_v2/events.py`
- Create: `src/harness/re_v2/projection.py`
- Create: `tests/unit/test_re_v2_events.py`
- Create: `tests/unit/test_re_v2_projection.py`

**Interfaces:**
- Consumes: canonical hashing and `ReV2Paths`.
- Produces: `EventRecord`, `EventStore.append()`, and `EventStore.replay()`.
- Produces: `project_run(manifest, events, ledger) -> dict[str, object]` and `rebuild_projection(paths) -> dict[str, object]`.

- [ ] **Step 1: Write failing chain, corruption, and replay tests**

```python
def test_event_chain_rejects_a_modified_middle_record(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append("work_planned", {"work_item_ids": [digest("work")]}, occurred_at=NOW)
    replace_jsonl_record(store.path, index=0, field="type", value="tampered")
    with pytest.raises(ReV2EventError, match="event hash"):
        store.replay()


def test_projection_rebuild_is_byte_identical(tmp_path: Path) -> None:
    paths = populated_run(tmp_path)
    first = canonical_json_bytes(rebuild_projection(paths))
    paths.projection.unlink()
    second = canonical_json_bytes(rebuild_projection(paths))
    assert first == second
```

- [ ] **Step 2: Run tests and verify missing modules**

Run: `pytest -q tests/unit/test_re_v2_events.py tests/unit/test_re_v2_projection.py`

Expected: collection fails for missing modules.

- [ ] **Step 3: Implement locked append and strict replay**

```python
@dataclass(frozen=True, slots=True)
class EventRecord:
    schema_version: int
    seq: int
    previous_event_hash: str | None
    occurred_at: str
    type: str
    payload: Mapping[str, object]
    event_hash: str
```

Use a sibling `events.lock` with `fcntl.flock`. Write one canonical line with
`O_APPEND`, then `fsync`. Replay rejects a partial last line, invalid JSON,
unknown schema/type, nonconsecutive sequence, wrong previous/event hash, or an
event after `complete`, `finalized_partial`, or `failed`. `paused` may only be
followed by an authorization/operator event and `run_resumed`. Compute
`event_hash` over the canonical record fields excluding `event_hash` itself.

- [ ] **Step 4: Implement the pure projection reducer**

Derive state, current work, usage totals, budget authorizations, candidate and
certification counts, accepted roots, and reason fields only from manifest,
events, and ledger. `rebuild_projection()` writes canonical JSON atomically and
never reads an existing projection.

- [ ] **Step 5: Run focused tests**

Run: `pytest -q tests/unit/test_re_v2_events.py tests/unit/test_re_v2_projection.py`

Expected: all tests pass.

- [ ] **Step 6: Commit event sourcing and projection**

```bash
git add src/harness/re_v2/events.py src/harness/re_v2/projection.py tests/unit/test_re_v2_events.py tests/unit/test_re_v2_projection.py
git commit -m "feat(re-v2): persist replayable execution events"
```

### Task 5: Immutable Object Store and Certification Ledger

**Files:**
- Create: `src/harness/re_v2/ledger.py`
- Create: `tests/unit/test_re_v2_ledger.py`

**Interfaces:**
- Consumes: artifact/certification models from Task 1.
- Produces: `ObjectStore.put_blob()`, `put_tree()`, and `verify()`.
- Produces: `Ledger.record_artifact()`, `record_certification()`, and `replay() -> LedgerView`.
- Produces: `Certifier.certify(candidate, work_item) -> CertificationDecision` protocol.

- [ ] **Step 1: Write failing object, receipt, and authority tests**

```python
def test_provider_verdict_cannot_accept_an_artifact(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    candidate = candidate_with_provider_verdict("PASS")
    assert ledger.replay().accepted_artifacts == {}
    decision = DeterministicFixtureCertifier().certify(candidate, work_item())
    ledger.record_certification(decision.certification_receipt)
    ledger.record_artifact(decision.artifact_receipt)
    assert work_item().output_key.identity in ledger.replay().accepted_artifacts


def test_tree_object_rejects_symlinks(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "escape").symlink_to(tmp_path)
    with pytest.raises(ReV2LedgerError, match="symlink"):
        ObjectStore(tmp_path / "objects").put_tree(tree)
```

- [ ] **Step 2: Run ledger tests and verify failure**

Run: `pytest -q tests/unit/test_re_v2_ledger.py`

Expected: collection fails for the missing ledger module.

- [ ] **Step 3: Implement immutable content objects**

Blobs live below `objects/sha256/<first-two>/<remaining>`. Trees use a canonical
manifest of safe relative paths, modes, sizes, and blob hashes; the tree hash is
the manifest hash. Write with exclusive temporary paths, `fsync`, and rename.
Accept an existing object only after validating its bytes/hash.

- [ ] **Step 4: Implement the hash-chained ledger and certifier boundary**

Use the event-store append/replay discipline with record types `artifact` and
`certification`. Reject duplicate artifact-key ownership with different object
hashes, source-snapshot mismatch, unsupported verifier versions, and acceptance
without an accepted controller certification.

```python
class Certifier(Protocol):
    @property
    def verifier_id(self) -> str: ...
    @property
    def verifier_version(self) -> str: ...
    def certify(self, candidate: "PersistedCandidate", work_item: WorkItem) -> "CertificationDecision": ...
```

- [ ] **Step 5: Run ledger tests**

Run: `pytest -q tests/unit/test_re_v2_ledger.py`

Expected: all tests pass.

- [ ] **Step 6: Commit object and certification storage**

```bash
git add src/harness/re_v2/ledger.py tests/unit/test_re_v2_ledger.py
git commit -m "feat(re-v2): certify immutable artifact objects"
```

### Task 6: Independent Budget Accounting

**Files:**
- Create: `src/harness/re_v2/budget.py`
- Create: `tests/unit/test_re_v2_budget.py`

**Interfaces:**
- Consumes: `BudgetPolicy`, `ExecutionObservation`, and budget events.
- Produces: `BudgetDimension`, `BudgetDecision`, `evaluate_budget()`, and `authorize_resource_increase()`.

- [ ] **Step 1: Write failing independence and unknown-token tests**

```python
def test_token_increase_does_not_raise_attempt_limits() -> None:
    before = evaluate_budget(policy(), events_with_attempts(provider=2, semantic=1), now=NOW)
    after = evaluate_budget(policy(), events_with_token_authorization(20_000), now=NOW)
    assert after.token_limit == 20_000
    assert after.provider_attempt_limit == before.provider_attempt_limit
    assert after.semantic_round_limit == before.semantic_round_limit


def test_unknown_usage_is_not_reported_as_exact_zero() -> None:
    decision = evaluate_budget(policy(), [dispatch_observed(token_usage=None)], now=NOW)
    assert decision.known_tokens == 0
    assert decision.unknown_token_dispatches == 1
    assert decision.token_coverage_complete is False
```

- [ ] **Step 2: Run budget tests and verify missing implementation**

Run: `pytest -q tests/unit/test_re_v2_budget.py`

Expected: collection fails for the missing budget module.

- [ ] **Step 3: Implement dimension-specific accounting**

```python
@dataclass(frozen=True, slots=True)
class BudgetDecision:
    known_tokens: int
    unknown_token_dispatches: int
    active_ms: int
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempts: Mapping[str, int]
    generation_attempts: Mapping[str, int]
    semantic_rounds: Mapping[str, int]
    result_contract_retries: Mapping[str, int]
    exhausted_dimensions: tuple[str, ...]
```

Only `tokens` and `active_ms` accept authorization increases in EGR-164. Reject
decreases, empty actor/reason, attempt-limit authorization through this API,
negative observations, and overflow. A global resource exhaustion returns a
continuable pause decision.

- [ ] **Step 4: Run budget tests**

Run: `pytest -q tests/unit/test_re_v2_budget.py`

Expected: all tests pass.

- [ ] **Step 5: Commit budget primitives**

```bash
git add src/harness/re_v2/budget.py tests/unit/test_re_v2_budget.py
git commit -m "feat(re-v2): separate execution budget dimensions"
```

### Task 7: Deterministic DAG Planner and Shadow Explanations

**Files:**
- Create: `src/harness/re_v2/planner.py`
- Create: `tests/unit/test_re_v2_planner.py`

**Interfaces:**
- Consumes: `WorkTemplate`, `WorkItem`, `LedgerView`, `BudgetDecision`, and
  requested goals.
- Produces: `WorkGraph`, `PlanDecision`, `PlanExplanation`, `validate_work_graph()`, `plan_next()`, and `build_initial_inventory_graph()`.

- [ ] **Step 1: Write failing DAG, reuse, and invalidation tests**

```python
def test_planner_reuses_certified_nodes_and_schedules_only_delta() -> None:
    inventory, api_depth, worker_depth = three_node_graph()
    ledger = certified_view(inventory, worker_depth)
    decision = plan_next(
        validate_work_graph((inventory, api_depth, worker_depth)), ledger, open_budget()
    )
    assert tuple(item.template_id for item in decision.ready) == (api_depth.template_id,)
    assert decision.explanations[inventory.template_id].action == "reuse"
    assert decision.explanations[worker_depth.template_id].action == "reuse"


def test_planner_rejects_cycles() -> None:
    with pytest.raises(ReV2PlanError, match="cycle"):
        validate_work_graph(cyclic_items())
```

- [ ] **Step 2: Run planner tests and verify missing implementation**

Run: `pytest -q tests/unit/test_re_v2_planner.py`

Expected: collection fails for the missing planner module.

- [ ] **Step 3: Implement stable IDs and topological planning**

Validate the template DAG using stable `template_id` and
`required_template_ids`. When every prerequisite is certified, instantiate one
immutable `WorkItem` whose output `ArtifactKey.dependency_hashes` contains the
accepted prerequisite object hashes. Work-item IDs hash requested goal, those
exact dependency hashes, output key, producer protocol, verifier
identity/version, and item-specific attempt policy; they exclude global
token/time ceilings. Validate unique logical outputs, dependency existence,
acyclicity, and lexicographic ready ordering.

- [ ] **Step 4: Implement shadow explanations and deterministic L0 work**

Each item has exactly one action: `reuse`, `generate`, `blocked_dependency`,
`blocked_budget`, or `reject_incompatible`, plus a stable reason code and prose.
The EGR-164 production graph contains deterministic snapshot/partition inventory
nodes only; provider-backed L1-L4 producers are registered by later EGRs.

```python
@dataclass(frozen=True, slots=True)
class PlanExplanation:
    work_item_id: str
    action: Literal["reuse", "generate", "blocked_dependency", "blocked_budget", "reject_incompatible"]
    reason_code: str
    reason: str
```

- [ ] **Step 5: Run planner tests**

Run: `pytest -q tests/unit/test_re_v2_planner.py`

Expected: all tests pass, including zero unrelated-domain work in the synthetic
layer graph.

- [ ] **Step 6: Commit deterministic planning**

```bash
git add src/harness/re_v2/planner.py tests/unit/test_re_v2_planner.py
git commit -m "feat(re-v2): plan deterministic artifact work"
```

### Task 8: Durable Dispatch Leases and Candidates

**Files:**
- Create: `src/harness/re_v2/candidates.py`
- Create: `tests/unit/test_re_v2_candidates.py`

**Interfaces:**
- Consumes: `WorkItem`, `ExecutionObservation`, and `ReV2Paths`.
- Produces: `ProcessIdentity`, `DispatchLease`, `PersistedCandidate`, and `CandidateStore`.
- Produces: `CandidateStore.begin()`, `persist()`, and `discover()`.

- [ ] **Step 1: Write failing crash-boundary and traversal tests**

```python
def test_complete_candidate_survives_missing_result_object(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    output = fixture_output(tmp_path, result_object=None)
    candidate = store.persist(
        lease, output, observation(exit_code=0, result_contract_valid=False)
    )
    assert store.discover() == (candidate,)
    assert candidate.observation.result_contract_valid is False


def test_candidate_store_rejects_symlink_payload(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "escape").symlink_to(tmp_path)
    with pytest.raises(ReV2CandidateError, match="symlink"):
        candidate_store(tmp_path).persist(active_lease(), output, observation())
```

- [ ] **Step 2: Run candidate tests and verify missing implementation**

Run: `pytest -q tests/unit/test_re_v2_candidates.py`

Expected: collection fails for the missing candidate module.

- [ ] **Step 3: Implement leases and atomic candidate persistence**

Lease metadata includes work-item ID, dispatch ID, PID, process-start identity,
command hash, provider identity, and timestamps. Persistence copies safe files
into `candidates/.<dispatch>.tmp`, writes canonical metadata/observation, flushes
files and directories, and renames to `candidates/<dispatch>/`. A persisted
candidate is immutable.

- [ ] **Step 4: Add explicit fault hooks**

Accept `fault_hook: Callable[[str], None] | None`; invoke it after
`lease_written`, `payload_copied`, `metadata_fsynced`, and `candidate_renamed`.
At every injected exception, discovery returns either no candidate or one fully
valid candidate, never a partial one.

- [ ] **Step 5: Run candidate tests**

Run: `pytest -q tests/unit/test_re_v2_candidates.py`

Expected: all tests pass.

- [ ] **Step 6: Commit candidate durability**

```bash
git add src/harness/re_v2/candidates.py tests/unit/test_re_v2_candidates.py
git commit -m "feat(re-v2): persist dispatch candidates durably"
```

### Task 9: Recovery and Single-dispatch Controller

**Files:**
- Create: `src/harness/re_v2/recovery.py`
- Create: `src/harness/re_v2/controller.py`
- Create: `tests/unit/test_re_v2_recovery.py`
- Create: `tests/unit/test_re_v2_controller.py`

**Interfaces:**
- Consumes: run store, snapshot validator, events, projection, ledger, budgets, planner, candidate store, and `Certifier`.
- Produces: `ProcessInspector`, `WorkExecutor`, `recover_run()`, `ReV2Controller.run_once()`, and `run_until_stopped()`.

- [ ] **Step 1: Write failing recovery-before-redispatch tests**

```python
def test_recovery_certifies_orphan_candidate_before_redispatch(tmp_path: Path) -> None:
    context = interrupted_after_candidate_rename(tmp_path)
    executor = RecordingExecutor()
    result = controller(context, executor=executor).run_until_stopped()
    assert result.status == "complete"
    assert executor.calls == []
    assert replay(context).count("artifact_accepted") == 1


def test_live_or_ambiguous_lease_fails_closed(tmp_path: Path) -> None:
    context = context_with_outstanding_lease(tmp_path)
    with pytest.raises(ReV2RecoveryError, match="still running|ambiguous"):
        recover_run(context, process_inspector=AmbiguousInspector())
```

- [ ] **Step 2: Run controller/recovery tests and verify missing modules**

Run: `pytest -q tests/unit/test_re_v2_recovery.py tests/unit/test_re_v2_controller.py`

Expected: collection fails for missing modules.

- [ ] **Step 3: Implement deterministic recovery ordering**

Validate manifest, snapshot, events, objects, ledger, and projection inputs;
check outstanding process identities; certify/reject persisted unhandled
candidates; append resulting events; rebuild projection. Never kill a process.
A live or PID-reuse-ambiguous lease pauses instead of redispatching.

- [ ] **Step 4: Implement the injected controller loop**

```python
class WorkExecutor(Protocol):
    def execute(
        self, snapshot_root: Path, work_item: WorkItem, lease: DispatchLease
    ) -> tuple[Path, ExecutionObservation]: ...


class ReV2Controller:
    def run_once(self) -> ReV2ControllerResult:
        self._recover()
        decision = self._plan()
        if decision.pause_reason:
            return self._pause(decision.pause_reason)
        if not decision.ready:
            return self._complete_if_goals_satisfied()
        return self._dispatch_persist_certify_accept(decision.ready[0])
```

Append lease/start/observation/candidate/certification/acceptance events in that
order, then append `checkpoint_recorded` for the run-local certified receipt.
Persist candidate bytes for timeout, nonzero exit, length stop, or missing
result. Certification—not transport status—decides acceptance. EGR-166 later
makes these receipts adoptable across runs; EGR-164 recovery uses them only
inside the pinned run.

- [ ] **Step 5: Add deterministic inventory and fake-provider executors**

The production EGR-164 executor handles only L0 inventory without an LLM. Tests
use `FakeProviderExecutor` to prove timeout/missing-result recovery. Unknown
L1-L4 producer protocols pause with `producer_not_registered`; they never fall
through to v1.

- [ ] **Step 6: Run controller and recovery tests**

Run: `pytest -q tests/unit/test_re_v2_recovery.py tests/unit/test_re_v2_controller.py`

Expected: all tests pass, including no duplicate dispatch after persisted
candidate checkpoints.

- [ ] **Step 7: Commit recovery and orchestration**

```bash
git add src/harness/re_v2/recovery.py src/harness/re_v2/controller.py tests/unit/test_re_v2_recovery.py tests/unit/test_re_v2_controller.py
git commit -m "feat(re-v2): recover and execute certified work"
```

### Task 10: Exact-root Generation Publication

**Files:**
- Create: `src/harness/re_v2/publication.py`
- Create: `tests/unit/test_re_v2_publication.py`

**Interfaces:**
- Consumes: certified roots from `LedgerView`, canonical writing, and existing publication locking conventions.
- Produces: `GenerationManifest`, `PublishedV2Index`, and `publish_generation(workspace_root, run_id, accepted_root_hashes, synthesis_policy_hash, *, expected_index_hash)`.

- [ ] **Step 1: Write failing idempotency and CAS tests**

```python
def test_same_root_set_publishes_at_most_one_generation(tmp_path: Path) -> None:
    first = publish_fixture(tmp_path, roots=(digest("a"), digest("b")))
    second = publish_fixture(
        tmp_path, roots=(digest("b"), digest("a")), expected_index_hash=first.index_hash
    )
    assert second.generation_id == first.generation_id
    assert len(list((tmp_path / "re/v2/generations").iterdir())) == 1


def test_index_cas_preserves_competing_publication(tmp_path: Path) -> None:
    stale = current_index_hash(tmp_path)
    publish_fixture(tmp_path, roots=(digest("newer"),), expected_index_hash=stale)
    with pytest.raises(ReV2PublicationConflict):
        publish_fixture(tmp_path, roots=(digest("stale"),), expected_index_hash=stale)
```

- [ ] **Step 2: Run publication tests and verify missing implementation**

Run: `pytest -q tests/unit/test_re_v2_publication.py`

Expected: collection fails for the missing publication module.

- [ ] **Step 3: Implement generation identity and last-pointer publication**

Sort/deduplicate root hashes and hash them with synthesis policy/schema to form
`generation_id`. Write immutable `re/v2/generations/<id>/manifest.json`, flush
it, then replace `re/v2/index.json` only when its observed canonical hash equals
`expected_index_hash`. Reuse an identical existing generation after validation;
fail closed on conflicting content.

- [ ] **Step 4: Add publication fault injection**

Invoke hooks after generation temporary write, generation rename, index
temporary write, and index replacement. After each injected crash, validation
exposes either the previous index or the complete new index, never partial data.

- [ ] **Step 5: Run publication tests**

Run: `pytest -q tests/unit/test_re_v2_publication.py tests/unit/test_re_lock.py`

Expected: all tests pass.

- [ ] **Step 6: Commit publication primitives**

```bash
git add src/harness/re_v2/publication.py tests/unit/test_re_v2_publication.py
git commit -m "feat(re-v2): publish exact certified root sets"
```

### Task 11: V2 Status, Engine Routing, and CLI Compatibility

**Files:**
- Create: `src/harness/re_v2/status.py`
- Create: `tests/unit/test_re_v2_status.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_re_lifecycle.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: engine detection, controller, projection, explanations, and budgets.
- Produces: `render_v2_status(run_dir: Path, *, as_json: bool = False) -> str`.
- Produces: `echelon re run --engine {v1,v2} [--shadow]` and automatic routing for status/continue.

- [ ] **Step 1: Write failing routing and final-banner tests**

```python
def test_continue_routes_from_pinned_manifest_not_default(monkeypatch, tmp_path: Path) -> None:
    create_v2_run(tmp_path)
    called = []
    monkeypatch.setattr("echelon.cli._run_re_v2_continue", lambda *a, **k: called.append("v2"))
    monkeypatch.setattr("echelon.cli._re_lifecycle_controller", lambda *_: pytest.fail("v1 invoked"))
    invoke_cli(tmp_path, ["re", "continue"])
    assert called == ["v2"]


def test_v2_paused_banner_names_budget_and_next_action(tmp_path: Path) -> None:
    run_dir = paused_v2_run(tmp_path, reason="token_limit", used=100, limit=100)
    output = render_v2_status(run_dir)
    assert "RE V2 — PAUSED" in output
    assert "token_limit: 100 / 100" in output
    assert "echelon re continue --re-token-limit" in output
```

- [ ] **Step 2: Run CLI/status tests and verify failure**

Run: `pytest -q tests/unit/test_re_v2_status.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py -k 'v2 or engine or pinned'`

Expected: tests fail because routing and status do not exist.

- [ ] **Step 3: Add explicit creation and shadow options**

Add `--engine` choices `v1`/`v2`, default `v1` during rollout, and `--shadow`,
valid only with v2. V2 creation captures the snapshot, writes its manifest,
builds deterministic L0 work, then either prints explanations without dispatch
or runs registered work. Do not put engine identity under the mutable profile.

- [ ] **Step 4: Route continuation and status by pinned manifest**

Call `detect_re_engine(run_dir)` before engine-specific parsing. V1 preserves
`--re-max-inner`. V2 rejects it with `v2 has independent attempt budgets; this
option is valid only for v1`, but accepts token/time authorization events.
Unsupported protocol errors name the recorded protocol.

- [ ] **Step 5: Render operator state and terminal banners**

Include engine/protocol, snapshot/partition IDs, goals/layers, current work,
known tokens and unknown count, independent budgets, reuse/generate/reject
counts, audit/synthesis as `not registered`, generation, and exact reason. JSON
returns the same fields. Print `ACTIVE`, `PAUSED`, `COMPLETE`, `FINALIZED
PARTIAL`, or `FAILED` from the authoritative projection.

- [ ] **Step 6: Prove v1 CLI output remains unchanged**

Assert representative v1 stdout/stderr/exit codes are unchanged without
`--engine v2`, and a v1 run never constructs `ReV2Controller`.

Run: `pytest -q tests/unit/test_re_v2_status.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py`

Expected: all tests pass.

- [ ] **Step 7: Commit CLI routing and status**

```bash
git add src/harness/re_v2/status.py tests/unit/test_re_v2_status.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py
git commit -m "feat(re-v2): route pinned runs and explain status"
```

### Task 12: Integrated Fault Matrix and V1 Isolation Gate

**Files:**
- Create: `tests/integration/test_re_v2_kernel_recovery.py`
- Create: `tests/integration/test_re_v2_v1_isolation.py`
- Modify: `scripts/bash/dry-run.sh`

**Interfaces:**
- Consumes: all kernel interfaces.
- Produces: no runtime API; establishes the EGR-164 release gate.

- [ ] **Step 1: Add the parameterized fault matrix**

```python
@pytest.mark.parametrize("fault_point", [
    "snapshot_created", "dispatch_started", "provider_terminated",
    "candidate_renamed", "certification_written", "checkpoint_recorded",
    "generation_promoted", "index_replaced",
])
def test_restart_preserves_certified_work_without_duplicate_dispatch(
    tmp_path: Path, fault_point: str
) -> None:
    harness = FaultHarness(tmp_path, fail_once_at=fault_point)
    harness.start_and_crash()
    recovered = harness.restart()
    assert recovered.certified_work_ids == {harness.work_item_id}
    assert recovered.dispatch_count(harness.work_item_id) == harness.expected_dispatches
```

Before a durable candidate exists, `expected_dispatches` is two (the interrupted
attempt and one replacement). At candidate rename or later, it is one. Encode
that boundary explicitly in the fixture.

- [ ] **Step 2: Add v1 isolation integration tests**

Create legacy fresh/running/blocked/partial/published fixtures. Exercise
run/continue/status/publish and assert no v2 files are created, v1 state remains
valid, and malformed/unsupported v2 manifests fail before provider construction.

- [ ] **Step 3: Extend dry-run validation**

Import every `harness.re_v2` module and verify CLI exposes `--engine`/`--shadow`
while retaining all existing RE commands. Static validation must not create a
snapshot or invoke a provider.

- [ ] **Step 4: Run the complete EGR-164 matrix**

```bash
pytest -q \
  tests/unit/test_re_v2_*.py \
  tests/unit/test_re_lifecycle.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_re_lock.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py
bash scripts/bash/dry-run.sh
```

Expected: all pytest cases and bundle validation checks pass.

- [ ] **Step 5: Commit the release gate**

```bash
git add tests/integration/test_re_v2_kernel_recovery.py tests/integration/test_re_v2_v1_isolation.py scripts/bash/dry-run.sh
git commit -m "test(re-v2): prove recovery and v1 isolation"
```

### Task 13: Documentation, EGR Evidence, and Opt-in Release Note

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-08-14-re-v2-execution-kernel-design.md`
- Create: `docs/runbooks/re-v2-kernel-pilot.md`

**Interfaces:**
- Consumes: actual commands, fields, tests, and measurements from Tasks 1-12.
- Produces: pilot/recovery runbook and EGR-164 completion evidence.

- [ ] **Step 1: Write the pilot runbook with exact commands**

```bash
echelon re run --engine v2 --shadow
echelon re run --engine v2
echelon re status
echelon re continue --re-token-limit <new-total>
```

Explain deterministic L0-only production scope, pinned identities, continuable
pause versus terminal states, projection rebuild/validation, and explicit v1
fallback. State that L1-L4 producers arrive only through later EGRs.

- [ ] **Step 2: Update design status and EGR evidence**

Change design status to implemented only after the matrix passes. Record exact
commit, test counts, dry-run result, shadow fixture, recovery guarantees, and
remaining dependencies. Mark EGR-164 `fixed` only with that evidence; otherwise
keep `in-progress` and name the failing gate.

- [ ] **Step 3: Add the changelog entry**

Describe the opt-in v2 kernel, immutable snapshot/protocol, candidate recovery,
independent budgets, status banner, and unchanged v1 default. Do not claim
layered reuse, audit epochs, deferred synthesis, or selective deepening.

- [ ] **Step 4: Run final verification from a clean process**

```bash
pytest -q \
  tests/unit/test_re_v2_*.py \
  tests/unit/test_re_lifecycle.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_re_lock.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: zero pytest failures, bundle validation passes, and `git diff
--check` produces no output.

- [ ] **Step 5: Commit EGR-164 documentation**

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-08-14-re-v2-execution-kernel-design.md docs/runbooks/re-v2-kernel-pilot.md
git commit -m "docs(re-v2): document the pinned kernel pilot"
```

## Completion Checklist

- [ ] Every v2 identity is canonical and excludes operational token/time ceilings.
- [ ] A v2 run continues only with its pinned engine/protocol and source snapshot.
- [ ] Replay produces byte-identical `projection.json`.
- [ ] A durable valid candidate can be certified after timeout, missing result, or restart without redispatch.
- [ ] Raising token/time authorization changes no attempt or semantic limit.
- [ ] One accepted root set and policy maps to one idempotent generation.
- [ ] Status reports known/unknown token coverage and an unambiguous banner.
- [ ] V1 fixtures remain unchanged and never invoke v2 code.
- [ ] The integrated fault matrix and bundle dry-run pass.
- [ ] EGR-165 through EGR-170 remain explicit follow-on work.
