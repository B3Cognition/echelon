# RE v2 L4 Authority Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the protocol-2.8/schema-7 authority, complete immutable source evidence, target-local L3 projection, deterministic exhaustive planning, and exact L4 roots required before provider execution is added.

**Architecture:** Add a focused `harness.re_v2.protocol_28` package whose closed models distinguish exhaustive evidence runs from zero-provider closure successors. Stage exact source bytes and target-local projections before manifest publication, derive a deterministic bounded plan, and permit roots only after exact plan and byte-range closure. This provider-free, CLI-inactive foundation is followed by separate execution/recovery and orchestration/CLI plans.

**Tech Stack:** Python 3.11+, frozen dataclasses, standard-library pathlib/json/os, existing RE v2 canonical JSON/content digests/object stores/schema helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-re-v2-l4-exhaustive-depth-design.md`

## Global Constraints

- Protocol 2.8 uses schema 7 and `target_layer: L4`; protocols 2.2 through 2.7 retain their current schemas, canonical bytes, and runtime routing.
- `RunManifestV7` is a discriminated union selected by `run_mode`; exhaustive and closure-successor manifests have disjoint closed field sets.
- Do not modify implementation bodies under `src/harness/re_v2/protocol_22/`, `protocol_24/`, `protocol_25/`, `protocol_26/`, or `protocol_27/`.
- L4 evidence covers every primary in-scope UTF-8 source byte exactly once. An L0 omission never counts as L4 coverage.
- Potentially behavioral non-text content is a pre-activation blocker. Empty files and proven non-behavioral records require explicit receipts.
- Reusable domain work binds target-local L3 and snapshot projections, never global selection, run ID, time, resources, or unrelated targets.
- The work set is deterministic and frozen before provider execution. Providers cannot add, remove, merge, or split entries.
- A root requires exact planned-entry acceptance and exact record/byte closure. Counts, percentages, and lower debt summaries cannot substitute.
- Closure-successor authority contains no executor, attempt, reservation, or budget field.
- No new third-party runtime dependency is introduced.

## Delivery Layers

1. This plan implements immutable authority, evidence, planning, and roots.
2. A second plan implements producer/verifier execution, bounded repair, V2 checkpoints, budget, events, controller, and recovery.
3. A third plan implements durable L3-to-L4 orchestration, synthesis-parent resolution, CLI, shadow, status, materialization, and real-workspace proof.

Later layers consume the canonical interfaces established here without changing their identities.

## File Structure

```text
src/harness/re_v2/protocol_28/
  __init__.py
  model.py
  authority.py
  evidence.py
  policies.py
  planning.py
  graph.py
  inputs.py

tests/re_v2_protocol_28_fixtures.py
tests/unit/test_re_v2_protocol_28_model.py
tests/unit/test_re_v2_protocol_28_authority.py
tests/unit/test_re_v2_protocol_28_evidence.py
tests/unit/test_re_v2_protocol_28_policies.py
tests/unit/test_re_v2_protocol_28_planning.py
tests/unit/test_re_v2_protocol_28_graph.py
tests/unit/test_re_v2_protocol_28_inputs.py
```

Add schema-7 routing only in `src/harness/re_v2/model.py`, `src/harness/re_v2/__init__.py`, and `src/harness/re_v2/run_store.py`.

---

### Task 1: Register Protocol 2.8 and Closed Schema-7 Manifests

**Files:**
- Create: `src/harness/re_v2/protocol_28/__init__.py`
- Create: `src/harness/re_v2/protocol_28/model.py`
- Create: `tests/re_v2_protocol_28_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_28_model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/__init__.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_run_store.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`

**Interfaces:**
- Produces `ExhaustiveBudgetPolicyV1` with optional positive token/time limits and fixed attempt tuple `(3, 0, 1)`.
- Produces `ExhaustiveRequestV1` whose `request_id` excludes resources.
- Produces `L4ClosureRequestV1` and `L4ClosureLineageV1`.
- Produces `ExhaustiveRunManifestV7` for `run_mode="exhaustive-depth"`.
- Produces `L4ClosureRunManifestV7` for `run_mode="l4-closure-successor"`.
- Exposes `RunManifestV7` and `decode_run_manifest_v7(value)`, dispatching by `run_mode` before exact decoding.
- Extends the run store only for `(7, "2.8")`.

- [x] **Step 1: Record the compatibility baseline**

```bash
pytest -q tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
git diff --exit-code -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24 src/harness/re_v2/protocol_25 src/harness/re_v2/protocol_26 src/harness/re_v2/protocol_27
```

Expected: tests pass and every frozen protocol directory is clean.

- [x] **Step 2: Write failing manifest tests**

```python
def test_manifest_v7_dispatches_closed_variants() -> None:
    exhaustive = exhaustive_manifest_v7()
    closure = closure_manifest_v7()
    assert decode_run_manifest_v7(exhaustive.to_json_dict()) == exhaustive
    assert decode_run_manifest_v7(closure.to_json_dict()) == closure

    wrong = closure.to_json_dict()
    wrong["budget_policy"] = exhaustive.budget_policy.to_json_dict()
    with pytest.raises(Protocol28SchemaError, match="extra fields"):
        decode_run_manifest_v7(wrong)


def test_run_store_rejects_schema_7_with_protocol_2_7(tmp_path: Path) -> None:
    raw = exhaustive_manifest_v7().to_json_dict()
    raw["engine_protocol_version"] = "2.7"
    write_raw_manifest(tmp_path / "runs" / "re-l4", raw)
    with pytest.raises(ReV2RunStoreError, match="schema/protocol"):
        load_run_manifest(tmp_path / "runs" / "re-l4")
```

- [x] **Step 3: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_model.py tests/unit/test_re_v2_run_store.py`

Expected: collection fails because `protocol_28` and schema-7 routing do not exist.

- [x] **Step 4: Implement the closed union and additive router**

```python
def decode_run_manifest_v7(value: object) -> RunManifestV7:
    if not isinstance(value, dict):
        raise Protocol28SchemaError("RunManifestV7 must be an object")
    if value.get("run_mode") == "exhaustive-depth":
        return ExhaustiveRunManifestV7.from_json_dict(value)
    if value.get("run_mode") == "l4-closure-successor":
        return L4ClosureRunManifestV7.from_json_dict(value)
    raise Protocol28SchemaError("RunManifestV7.run_mode is unsupported")
```

The closure `FIELDS` tuple must exclude `budget_policy`, `executor_catalog_id`, `attempt_policy_id`, `exhaustive_plan_id`, and `snapshot_evidence_catalog_id`.

- [x] **Step 5: Run GREEN**

```bash
pytest -q tests/unit/test_re_v2_protocol_28_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py
```

Expected: PASS and schemas 2 through 6 retain their canonical fixtures.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_28 src/harness/re_v2/model.py src/harness/re_v2/__init__.py src/harness/re_v2/run_store.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py
git commit -m "feat(re): register protocol 2.8 authority"
```

### Task 2: Stage Complete Immutable Snapshot Evidence

**Files:**
- Create: `src/harness/re_v2/protocol_28/evidence.py`
- Create: `tests/unit/test_re_v2_protocol_28_evidence.py`
- Modify: `tests/re_v2_protocol_28_fixtures.py`

**Interfaces:**
- Produces `SnapshotEvidenceShardV1` with source/path/content identity, raw half-open offsets, line/column boundaries, raw bytes, and `shard_id`.
- Produces `EmptyFileCoverageReceiptV1` and `NonTextEvidenceDispositionV1`.
- Produces `TargetSnapshotEvidenceProjectionV1` and `SnapshotEvidenceCatalogV1`.
- Produces `stage_snapshot_evidence(snapshot, partition, selection, policy, object_store)`.
- Produces `validate_snapshot_evidence_closure(catalog, snapshot, partition, selection)`.

- [x] **Step 1: Write failing exact-byte tests**

```python
def test_utf8_shards_cover_exact_raw_bytes_without_gaps(tmp_path: Path) -> None:
    fixture = clean_snapshot_fixture(tmp_path, {"src/app.py": "a\nβ\nc\n"})
    catalog = stage_snapshot_evidence(
        fixture.snapshot, fixture.partition, fixture.selection,
        evidence_policy(shard_byte_limit=4), fixture.objects,
    )
    shards = catalog.projection_for(fixture.domain_key).primary_shards
    assert b"".join(shard.raw_bytes for shard in shards) == "a\nβ\nc\n".encode()
    assert [(item.byte_start, item.byte_end) for item in shards] == [(0, 2), (2, 5), (5, 7)]


def test_behavioral_binary_blocks_before_publication(tmp_path: Path) -> None:
    fixture = clean_snapshot_fixture(tmp_path, {"src/plugin.bin": b"\x00\x01"})
    with pytest.raises(Protocol28EvidenceError, match="unsupported_behavioral_content"):
        stage_snapshot_evidence(
            fixture.snapshot, fixture.partition, fixture.selection,
            evidence_policy(), fixture.objects,
        )
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_evidence.py`

Expected: FAIL because evidence authority is absent.

- [x] **Step 3: Implement deterministic sharding and dispositions**

```python
def split_utf8_ranges(payload: bytes, byte_limit: int) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(payload):
        end = min(start + byte_limit, len(payload))
        while end > start:
            try:
                payload[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        if end == start:
            raise Protocol28EvidenceError("UTF-8 shard boundary cannot advance")
        lf = payload.rfind(b"\n", start, end)
        if lf >= start:
            end = lf + 1
        ranges.append((start, end))
        start = end
    return tuple(ranges)
```

Validate mode, byte count, content digest, ownership, no gaps/overlaps, unique primary assignment, empty-file receipts, and exact round trips.

- [x] **Step 4: Add selection and changed-source tests**

Prove domain selection includes selected-domain plus source-unowned records, unselected supporting paths never count as primary, `--all` assigns every record exactly once, and source mutation raises `source_snapshot_changed`.

- [x] **Step 5: Run GREEN**

```bash
pytest -q tests/unit/test_re_v2_protocol_28_evidence.py tests/unit/test_re_v2_workspace_snapshot.py tests/unit/test_re_v2_snapshot.py
```

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_28/evidence.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_evidence.py
git commit -m "feat(re): stage complete L4 snapshot evidence"
```

### Task 3: Freeze Target-Local L3 and Parent Authority

**Files:**
- Create: `src/harness/re_v2/protocol_28/authority.py`
- Create: `tests/unit/test_re_v2_protocol_28_authority.py`
- Modify: `tests/re_v2_protocol_28_fixtures.py`

**Interfaces:**
- Produces `L3TargetAuthorityProjectionV1`, `L3TargetEpochMembershipV1`, and `L3TargetProjectionCatalogV1`.
- Produces `ParentAuthorityBundleV3` and zero-provider `L4ClosureParentBundleV1`.
- Produces `build_l3_target_projections(validated_l3_parent, selection)`.

- [x] **Step 1: Write failing local-identity tests**

```python
def test_target_projection_survives_unrelated_selection_expansion() -> None:
    first = l3_parent_fixture(selected_domains=("api",))
    expanded = l3_parent_fixture(selected_domains=("api", "search"))
    assert (
        build_l3_target_projections(first.parent, first.selection).for_domain("api").identity
        == build_l3_target_projections(expanded.parent, expanded.selection).for_domain("api").identity
    )


def test_projection_rejects_mixed_epoch_authority() -> None:
    fixture = l3_parent_fixture(selected_domains=("api", "search"))
    fixture.replace_target_epoch("search", digest("other-epoch"))
    with pytest.raises(Protocol28AuthorityError, match="mixed.*epoch"):
        build_l3_target_projections(fixture.parent, fixture.selection)
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_authority.py`

- [x] **Step 3: Implement projections and bundles**

Projection identity includes only target candidate authority, findings, overlays, closure state, relevant L2 roots, and audit/executor policies. Epoch membership lives outside that identity:

```python
@dataclass(frozen=True, slots=True)
class L3TargetEpochMembershipV1:
    target_projection_id: str
    frozen_epoch_id: str
    epoch_target_entry_hash: str
```

Reject unfinished targets, mixed epochs, mismatched snapshots/partitions, unsupported blocker classes, and missing source projections.

- [x] **Step 4: Add closure-bundle negative tests**

Reject incomplete L4 roots, mismatched selection/terminal hashes, checkpoint provenance, executor authority, and resource policy.

- [x] **Step 5: Run GREEN**

```bash
pytest -q tests/unit/test_re_v2_protocol_28_authority.py tests/unit/test_re_v2_protocol_25_model.py tests/unit/test_re_v2_protocol_25_findings.py
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_28/authority.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_authority.py
git commit -m "feat(re): freeze target-local L3 authority"
```

### Task 4: Build Deterministic Exhaustive Policy and Plans

**Files:**
- Create: `src/harness/re_v2/protocol_28/policies.py`
- Create: `src/harness/re_v2/protocol_28/planning.py`
- Create: `tests/unit/test_re_v2_protocol_28_policies.py`
- Create: `tests/unit/test_re_v2_protocol_28_planning.py`
- Modify: `tests/re_v2_protocol_28_fixtures.py`

**Interfaces:**
- Produces `ExhaustivePolicyV1` with the design's fixed category and size bounds.
- Produces `CategoryVacancyReceiptV1`, `SlicePlanEntryV1`, `SliceSpecV1`, `TargetCoverageLedgerV1`, domain/source plans, and `ExhaustivePlanV1`.
- Produces `build_exhaustive_plan(parent_bundle, l3_projections, evidence_catalog, policy, selection)`.
- Produces `realize_slice(plan_entry, accepted_dependencies)`.

- [ ] **Step 1: Write failing deterministic coverage tests**

```python
def test_plan_assigns_every_primary_shard_once() -> None:
    fixture = planning_fixture()
    plan = build_exhaustive_plan(*fixture.inputs)
    expected = set(fixture.evidence.primary_shard_ids)
    assigned = [
        shard_id
        for target in plan.target_plans
        for entry in target.entries
        for shard_id in entry.primary_snapshot_evidence_ids
    ]
    assert set(assigned) == expected
    assert len(assigned) == len(set(assigned))


def test_plan_is_independent_of_input_iteration_order() -> None:
    forward = build_exhaustive_plan(*planning_fixture(order="forward").inputs)
    reverse = build_exhaustive_plan(*planning_fixture(order="reverse").inputs)
    assert forward.identity == reverse.identity
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_policies.py tests/unit/test_re_v2_protocol_28_planning.py`

- [ ] **Step 3: Implement fixed categories and canonical bin packing**

```python
DOMAIN_CATEGORIES = (
    "public-surfaces",
    "state-models-transformations-invariants",
    "boundaries-integrations-protocols-dependencies",
    "failure-retry-recovery-degraded-behavior",
    "configuration-controls-security-permissions",
    "observability-operations-lifecycle",
    "negative-space",
)
SOURCE_CATEGORIES = (
    "source-composition",
    "cross-domain-boundaries",
    "source-configuration-security",
    "source-operations-lifecycle",
    "source-negative-space",
)
```

Sort target/category/subject/shard/record tuples by UTF-8 identity. Greedily stop before 16 primary subjects, 32 supporting subjects, 64 primary records, 128 supporting records, 128 KiB canonical context, or 131,072 conservative tokens. Reject over 512 entries per target or 16,384 per run.

- [ ] **Step 4: Add blocker, vacancy, and deferred-realization tests**

Test missing/repeated shards, unsupported content, unassigned findings, unsplittable context, caps, literal category vacancy, semantic inapplicability requiring work, and source-composition realization waiting for named domain roots.

- [ ] **Step 5: Run GREEN**

```bash
pytest -q tests/unit/test_re_v2_protocol_28_policies.py tests/unit/test_re_v2_protocol_28_planning.py tests/unit/test_re_v2_protocol_24_graph.py tests/unit/test_re_v2_protocol_25_graph.py
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_28/policies.py src/harness/re_v2/protocol_28/planning.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_policies.py tests/unit/test_re_v2_protocol_28_planning.py
git commit -m "feat(re): freeze deterministic L4 plans"
```

### Task 5: Enforce Exact L4 Roots and Semantic Closure

**Files:**
- Create: `src/harness/re_v2/protocol_28/graph.py`
- Create: `tests/unit/test_re_v2_protocol_28_graph.py`
- Modify: `tests/re_v2_protocol_28_fixtures.py`

**Interfaces:**
- Produces `AcceptedExhaustiveSliceV1`, target/source-composition/source/run roots.
- Produces `L4FindingClosureReceiptV1` and `L4SemanticClosureRootV1`.
- Produces `build_target_root`, `build_source_root`, `build_run_root`, and `build_l4_semantic_closure`.

- [ ] **Step 1: Write failing exact-root tests**

```python
def test_target_root_rejects_one_missing_plan_entry() -> None:
    fixture = accepted_graph_fixture()
    with pytest.raises(Protocol28GraphError, match="exact plan closure"):
        build_target_root(fixture.target_plan, fixture.accepted_slices[:-1])


def test_closure_missing_verifier_is_integrity_failure() -> None:
    fixture = closure_graph_fixture()
    with pytest.raises(Protocol28ClosureIntegrityError) as raised:
        build_l4_semantic_closure(
            fixture.parent_bundle, fixture.run_root,
            fixture.accepted_slices, verifier_receipts=(),
        )
    assert raised.value.reason_code == "closure_verifier_receipt_missing"
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_graph.py`

- [ ] **Step 3: Implement exact constructors**

Compare exact planned and accepted key sets, authenticate candidate/verifier/certification/acceptance hashes, re-run coverage closure, and reject extras. The run root stores only `selected-scope` or `all-scope`.

Closure maps each finding to one primary accepted slice plus supporting slices, requires source-composition authority for source/cross-domain findings, and returns authority-ID diagnostics on mismatch.

- [ ] **Step 4: Add mutation tests**

Mutate one shard, L3 projection, verifier receipt, slice key, selected-domain root, composition root, finding assignment, and selection mode. Each mutation blocks the narrowest constructor without returning a partial root.

- [ ] **Step 5: Run GREEN**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_graph.py tests/unit/test_re_v2_protocol_28_planning.py`

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_28/graph.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_graph.py
git commit -m "feat(re): enforce exact L4 root closure"
```

### Task 6: Publish Self-Contained Inputs Manifest-Last

**Files:**
- Create: `src/harness/re_v2/protocol_28/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_28_inputs.py`
- Modify: `tests/re_v2_protocol_28_fixtures.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces `Protocol28CreationInputs` and `Protocol28ClosureInputs`.
- Produces `stage_exhaustive_inputs(private_stage, inputs)`.
- Produces `publish_protocol_28_run(private_stage, final_run_dir, manifest)`.
- Produces `load_protocol_28_inputs(run_dir)` using run-local objects only.

- [ ] **Step 1: Write failing publication tests**

```python
def test_failed_private_staging_publishes_no_run_or_pointer(tmp_path: Path) -> None:
    fixture = protocol28_creation_fixture(tmp_path)
    fixture.remove_required_shard()
    with pytest.raises(Protocol28InputError, match="snapshot evidence"):
        stage_exhaustive_inputs(fixture.private_stage, fixture.inputs)
    assert not fixture.final_run.exists()
    assert not fixture.active_pointer.exists()


def test_loaded_inputs_need_no_source_or_parent(tmp_path: Path) -> None:
    fixture = publish_protocol28_fixture(tmp_path)
    fixture.remove_source_checkout_and_parent()
    loaded = load_protocol_28_inputs(fixture.run_dir)
    assert loaded.exhaustive_plan.identity == fixture.plan.identity
    assert loaded.snapshot_evidence_catalog.identity == fixture.evidence.identity
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_28_inputs.py`

- [ ] **Step 3: Implement staging and publication**

Write every canonical object through the existing object store, authenticate the transitive closure, write the schema-7 manifest last, fsync files/directories, atomically rename the private directory, and only then permit active-pointer update. Reject symlinks, missing objects, hash mismatches, cross-mode fields, unsafe paths, and changed manifests.

- [ ] **Step 4: Add crash and corruption tests**

Inject failure after each authority group and before manifest publication. Delete source and parent after success and reconstruct. Remove/mutate one shard, projection, plan, parent bundle, or closure object and require corruption rather than source reread.

- [ ] **Step 5: Run the foundation gate**

```bash
pytest -q   tests/unit/test_re_v2_protocol_28_model.py   tests/unit/test_re_v2_protocol_28_authority.py   tests/unit/test_re_v2_protocol_28_evidence.py   tests/unit/test_re_v2_protocol_28_policies.py   tests/unit/test_re_v2_protocol_28_planning.py   tests/unit/test_re_v2_protocol_28_graph.py   tests/unit/test_re_v2_protocol_28_inputs.py   tests/unit/test_re_v2_protocol_compatibility.py   tests/unit/test_re_v2_run_store.py
```

- [ ] **Step 6: Verify frozen code and commit**

```bash
git diff --exit-code -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24 src/harness/re_v2/protocol_25 src/harness/re_v2/protocol_26 src/harness/re_v2/protocol_27
git add src/harness/re_v2/protocol_28/inputs.py tests/re_v2_protocol_28_fixtures.py tests/unit/test_re_v2_protocol_28_inputs.py tests/unit/test_re_v2_run_store.py
git commit -m "feat(re): publish self-contained L4 inputs"
```

## Foundation Completion Gate

```bash
pytest -q tests/unit/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
git diff --check
bash scripts/bash/dry-run.sh
```

The foundation is complete only when schema-7 variants are closed, selected source bytes reconstruct from the run-local store, target-local identities survive unrelated selection expansion, plans reproduce byte-for-byte, incomplete plan/byte closure cannot create a root, zero-provider closure mismatches are integrity failures, and protocol-2.2-through-2.7 compatibility remains green.
