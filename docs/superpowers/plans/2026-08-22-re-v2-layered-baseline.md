# RE v2 Layered Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship protocol 2.2 as an opt-in, bounded L0+L1 compact-baseline pipeline whose scoped artifact identities preserve unaffected lower-layer work and whose controller-certified outputs never claim semantic audit, synthesis, or full RE quality.

**Architecture:** Preserve protocol 2.0/2.1 classes and canonical bytes, and route schema-2 manifests into a focused `harness.re_v2.protocol_22` package. Protocol 2.2 reconstructs its graph from immutable catalogs, produces deterministic L0 and context artifacts in process, performs at most one initial plus one shared-retry tool-free API call per L1 item, and accepts artifacts only through protocol-specific receipts in the existing hash-chained event and ledger envelopes.

**Tech Stack:** Python 3.11+, standard-library dataclasses/Decimal/hashlib/json/fcntl/os/pathlib/urllib, existing PyYAML and jsonschema dependencies, Typer CLI, pytest, and existing RE v2 snapshot/object-store primitives.

**Spec:** `docs/superpowers/specs/2026-08-21-re-v2-layered-baseline-design.md`

## Global Constraints

- New runs use engine protocol `2.2` and run-manifest schema `2`; protocol `2.0` and `2.1` schema-1 manifests, model identities, event lines, ledger lines, recovery, status, and continuation remain byte-for-byte stable.
- Protocol `2.2` accepts only the existing clean-Git `workspace-git-composite` snapshot. It never reads provider evidence from a mutable checkout.
- `baseline` is the default v2 goal; `inventory` is the only other goal. EGR-165 accepts no source filter, domain filter, depth profile, cross-run adoption, semantic repair, workspace synthesis, selective deepening, or atomic repair.
- A baseline work item permits exactly `2` provider attempts, `2` generation attempts, `0` semantic rounds, `1` result-contract retry, `1` shared retry, and `1` artifact-contract retry. A deterministic work item permits `0`, `1`, `0`, `0`, `0`, and `0` in the same order.
- Source evidence packs are at most 48 KiB; domain evidence packs are at most 96 KiB. Domain context bundles are at most 128 KiB/131,072 conservative input tokens; source-overview bundles are at most 96 KiB/98,304 conservative input tokens.
- Domain-baseline canonical JSON is at most 32 KiB, source-overview canonical JSON is at most 48 KiB, derived Markdown is at most 96 KiB, retained stdout is at most the terminal 128 KiB, and one dispatch reserves at most 262,144 billable tokens.
- Run-wide token/time authorization may be null only by explicit operator choice. Every executor retains a positive active-time ceiling and every provider dispatch retains a hard completion and billable-token ceiling.
- Only `bounded-api-baseline-v1` is eligible for compact L1 in this increment. General Claude, Codex, Copilot, OpenCode, and existing agentic OpenAI-compatible CLI execution fail eligibility before run or active-pointer creation.
- Provider/model/resource changes are absent from artifact identity. Executor, renderer, tokenizer, calculator, normalizer, agent, response-schema, and verifier authority is immutable within a run and checked by exact digest before mutation or execution.
- Provider output is untrusted authorial input. It never writes events, ledger records, identity, dependencies, coverage, depth debt, materialization, or workspace output.
- EGR-165 writes nothing below workspace `re/`. Accepted object bytes and receipts are authority; `v2/materialized/L1` is a rebuildable run-local projection.
- The controller remains single-dispatch. Independent failed work does not discard accepted siblings; only a dependency closure or shared failed executor is blocked.
- A started external dispatch is never reissued under the same dispatch ID. The guarantee is at-most-once external execution per dispatch ID, not exactly-once logical execution.
- The success banner is exactly `L1 COMPACT BASELINE COMPLETE` and explicitly says semantic audit, workspace synthesis, selective deepening, and exhaustive RE were not performed. No surface says full RE or full quality.
- No new third-party runtime dependency is introduced.

## File Structure

Keep schema-1 implementation files as the legacy protocol implementation. Add protocol 2.2 below one package so no schema-1 class acquires inferred or optional schema-2 fields:

```text
src/harness/re_v2/
  model.py                    creation/supported protocol constants; legacy models unchanged
  run_store.py                schema/protocol manifest dispatch and manifest-last creation
  events.py                   durable event envelope plus pluggable protocol validator
  ledger.py                   object store plus durable ledger envelope/authority seam
  status.py                   protocol-selected read-only renderer
  protocol_22/
    __init__.py               protocol/schema constants and public context API
    schema.py                 strict canonical JSON decoding and scalar validators
    model.py                  schema-2 manifest, scope, key, work, execution, and receipt models
    policies.py               one exact built-in artifact-policy catalog
    response_schemas.py       deterministic strict domain/source authorial JSON Schemas
    inputs.py                 catalog references and manifest-last immutable input store
    partition.py              workspace/source/domain descriptors and scoped identity inputs
    authorities.py            implementation-closure digests and installed-authority checks
    executors.py              closed executor catalog and workspace-config resolution
    graph.py                  protocol-2.2 DAG construction, instantiation, and planning state
    artifacts.py              shared deterministic artifact/debt/evidence value models
    inventory.py              L0 source/domain inventory and source-partition producers
    evidence.py               provider-neutral evidence-pack selection and validation
    context.py                domain/source context bundles, projections, debt rollups, roots
    baseline.py               authorial parsing/normalization, certification, coverage, Markdown
    provider.py               stored request rendering, reservation, usage normalization, API call
    execution.py              execution-input, lease, capture, candidate, and commit durability
    events.py                 protocol-2.2 payload schemas and replay state machine
    budget.py                 reservation-aware attempt/resource accounting
    ledger.py                 protocol-2.2 receipt authority and graph-failure projection
    recovery.py               authority validation and four-case dispatch reconciliation
    controller.py             one-dispatch orchestration and fixed-point failure isolation
    materialization.py        immutable run-local JSON/Markdown/root projection and quarantine
    status.py                 protocol-2.2 JSON/human status and final banners
```

Modify integration surfaces only where authority is selected or configured:

```text
src/harness/config.py
src/echelon/cli.py
src/echelon/cli_app.py
runtime/config-template.yml
prosaic/subagents/echelon.re-baseliner.md
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
```

Mirror every protocol module with one focused unit test. Put reusable protocol-2.2 object builders in `tests/re_v2_protocol_22_fixtures.py`, HTTP conformance support in `tests/support/re_v2_bounded_api.py`, temporary clean-Git workspace builders in `tests/support/re_v2_layered_workspace.py`, and crash tests in `tests/integration/test_re_v2_protocol_22_recovery.py`.

This remains one implementation plan because these are not independently releasable subsystems: the manifest, catalogs, graph, execution capture, receipts, recovery, and status form one immutable authority chain. The checkpoints below keep intermediate commits testable without claiming an executable protocol before that chain is complete.

---

### Task 1: Freeze Legacy Canonical Bytes and Establish the Protocol Package Boundary

**Files:**
- Create: `tests/unit/test_re_v2_protocol_compatibility.py`
- Create: `src/harness/re_v2/protocol_22/__init__.py`
- Test: `tests/unit/test_re_v2_model.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces: package constants `PROTOCOL_VERSION = "2.2"` and `RUN_MANIFEST_SCHEMA_VERSION = 2` without changing the current creation protocol yet.
- Preserves: every existing schema-1 dataclass, constant, loader, and serializer without adding a field.
- Provides: hard compatibility assertions that every later task must continue to run.

- [ ] **Step 1: Pin the existing schema-1 identities before changing constants**

Create a regression whose literals come from the current implementation:

```python
@pytest.mark.parametrize(
    ("protocol", "snapshot_kind", "expected_manifest_digest"),
    (
        ("2.0", "git-worktree", "sha256:7ac95ce703b04cc139e51915d387b0ccaae74f26b0db0d6511a16557716d6f1b"),
        ("2.1", "workspace-git-composite", "sha256:85ada60ab484c4d5c62c67e51ee06b16ef27291fafd2640f954dfed29ba54907"),
    ),
)
def test_schema_1_manifest_bytes_remain_frozen(
    protocol: str, snapshot_kind: str, expected_manifest_digest: str
) -> None:
    raw = valid_run_manifest_dict()
    raw["engine_protocol_version"] = protocol
    raw["source_snapshot_kind"] = snapshot_kind
    payload = canonical_json_bytes(RunManifest.from_json_dict(raw).to_json_dict())
    assert content_digest(payload) == expected_manifest_digest


def test_schema_1_work_identities_remain_frozen() -> None:
    assert valid_work_template().template_id == (
        "sha256:1409b831e2e5f56dfa1e7ca55129a7a571a759eb811f1e6263441eabdf1f51a2"
    )
    assert valid_artifact_key().identity == (
        "sha256:8dbebbaa987d4fcc2e78bb3e7754877adc45d313c7957e2ee2a426f772a30fac"
    )
```

- [ ] **Step 2: Run the compatibility tests while `2.1` is still current**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_model.py`

Expected: PASS, proving the literals describe the shipped schema-1 bytes.

- [ ] **Step 3: Create the isolated protocol package boundary**

Create only these constants in `protocol_22/__init__.py`:

```python
PROTOCOL_VERSION = "2.2"
RUN_MANIFEST_SCHEMA_VERSION = 2
```

Add a test that imports and asserts only these package constants alongside the frozen schema-1 digest tests. Do not change the root creation constant in this task. This commit establishes isolation without leaving a loader branch that names a not-yet-implemented model.

- [ ] **Step 4: Prove schema-1 loading and engine routing are unchanged**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py tests/integration/test_re_v2_v1_isolation.py`

Expected: all tests pass; the compatibility digests remain identical.

- [ ] **Step 5: Commit the immutable protocol seam**

```bash
git add src/harness/re_v2/protocol_22/__init__.py \
  tests/unit/test_re_v2_model.py tests/unit/test_re_v2_run_store.py \
  tests/unit/test_re_v2_protocol_compatibility.py
git commit -m "test(re-v2): freeze legacy protocol authority"
```

---

### Task 2: Closed Protocol-2.2 Models and Strict Canonical Decoding

**Files:**
- Create: `src/harness/re_v2/protocol_22/schema.py`
- Create: `src/harness/re_v2/protocol_22/model.py`
- Create: `tests/re_v2_protocol_22_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_22_model.py`
- Modify: `src/harness/re_v2/protocol_22/__init__.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces: `load_canonical_object(payload: bytes, decoder: Callable[[object], T]) -> T` with duplicate-key, non-finite-number, invalid-Unicode, unknown-field, and noncanonical-byte rejection.
- Produces: frozen `CatalogReferenceV1`, `BudgetPolicyV2`, `ArtifactScope`, `ArtifactKeyV2`, `WorkTemplateV2`, `WorkItemV2`, `ProviderRequestEnvelopeV1`, `DeterministicInvocationV1`, `ExecutionInputV1`, `ExecutionCaptureV1`, `ExecutionCaptureCommitV1`, and `PersistedCandidateV2`.
- Produces: `RunManifestV2` with exactly the schema-2 fields in the design.
- Produces: `to_json_dict()`, strict `from_json_dict()`, and digest identities for every identity-bearing object.
- Produces: `RE_V2_PROTOCOL = "2.2"`, `RE_V2_SCHEMA_1_PROTOCOLS = ("2.0", "2.1")`, `RE_V2_SUPPORTED_PROTOCOLS = ("2.0", "2.1", "2.2")`, and exact manifest loading for only `(1, "2.0")`, `(1, "2.1")`, and `(2, "2.2")`.
- Reuses: `harness.re_v2.snapshot.FaultHook` for named durability-boundary injection; production callers pass null.
- Produces: shared test builders `digest()`, `manifest_v2_dict()`, `budget_policy_v2()`, `artifact_scope_v2()`, `artifact_key_v2()`, `work_template_v2()`, and `work_item_v2()`; later test files add only domain-specific wrappers around these valid bases.

- [ ] **Step 1: Write RED tests for closed objects and canonical input**

```python
def test_manifest_v2_rejects_schema_1_provider_maps() -> None:
    raw = manifest_v2_dict()
    raw["provider_contract"] = {"provider": "fake"}
    with pytest.raises(Protocol22SchemaError, match="unknown fields"):
        RunManifestV2.from_json_dict(raw)


def test_artifact_scope_enforces_domain_nullability() -> None:
    with pytest.raises(Protocol22SchemaError, match="domain_key"):
        ArtifactScope(source_id="api", domain_key=None, content_id=digest("1"), kind="domain")


def test_canonical_loader_rejects_duplicate_keys() -> None:
    with pytest.raises(Protocol22SchemaError, match="duplicate key"):
        load_canonical_object(b'{"schema_version":2,"schema_version":2}\n', RunManifestV2.from_json_dict)
```

Parameterize unknown/missing fields, booleans masquerading as integers, unsafe IDs, non-lowercase digests, unsorted/duplicate arrays, surrogate code points, non-finite values, wrong goal/budget combinations, wrong executor branch nullability, and mismatched template/item copies.

- [ ] **Step 2: Run the focused model tests and confirm RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_model.py`

Expected: collection fails because the protocol-2.2 model module does not exist.

- [ ] **Step 3: Implement reusable strict validators and frozen schema-2 values**

Use exact-field decoding rather than permissive dictionaries:

```python
def exact_object(value: object, fields: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise Protocol22SchemaError(f"{label} must be an object")
    present = frozenset(value)
    if present != fields:
        unknown = sorted(present - fields)
        missing = sorted(fields - present)
        raise Protocol22SchemaError(
            f"{label} has unknown fields {unknown} and missing fields {missing}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ArtifactScope:
    source_id: str
    domain_key: str | None
    content_id: str | None

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())
```

Represent scope kind through validation context, not a serialized extension field. `ArtifactKeyV2.identity_schema_version`, `WorkTemplateV2.identity_schema_version`, and `WorkItemV2.identity_schema_version` are literal `2`. Validate the six copied attempt fields and all producer/executor/verifier/result fields byte-for-byte in `instantiate_work_item_v2(template, output_key, dependency_hashes)`. Provide `BudgetPolicyV2.for_goal("baseline" | "inventory", token_limit, active_ms_limit)` with the exact goal-specific attempt values and reject a manifest whose policy differs from that selected goal.

- [ ] **Step 4: Add exact manifest dispatch after the schema-2 model exists**

Use an explicit selector in `run_store.py`:

```python
Manifest = RunManifest | RunManifestV2


def _decode_manifest(raw: object) -> Manifest:
    if not isinstance(raw, dict):
        raise ReV2RunStoreError("immutable v2 run manifest must be an object")
    pair = (raw.get("schema_version"), raw.get("engine_protocol_version"))
    if pair in {(1, "2.0"), (1, "2.1")}:
        return RunManifest.from_json_dict(raw)
    if pair == (2, "2.2"):
        return RunManifestV2.from_json_dict(raw)
    raise ReV2RunStoreError(f"unsupported pinned manifest schema/protocol {pair!r}")
```

Set the root creation constant to `2.2`, keep schema-1 `RunManifest` validation restricted to `RE_V2_SCHEMA_1_PROTOCOLS`, and keep schema-1 test helpers explicitly pinned to `2.1`. Reject `(1, "2.2")`, `(2, "2.1")`, and every unknown pair before canonical reserialization, including direct `RunManifest.from_json_dict()` rejection of protocol `2.2`.

- [ ] **Step 5: Add canonical round-trip/hash restart tests for every model**

For each fixture value, serialize, parse in a fresh decoder call, and assert identical bytes and identity. Mutate one field at a time and assert either a new identity or a schema error according to whether the field is legal.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass, including frozen schema-1 digests.

- [ ] **Step 6: Commit the closed model and manifest dispatch layer**

```bash
git add src/harness/re_v2/protocol_22/schema.py \
  src/harness/re_v2/protocol_22/model.py \
  src/harness/re_v2/protocol_22/__init__.py \
  src/harness/re_v2/model.py src/harness/re_v2/run_store.py \
  tests/re_v2_protocol_22_fixtures.py \
  tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): define and dispatch closed protocol 2.2 models"
```

---

### Task 3: Built-In Artifact Policies, Baseliner Contract, and Response Schemas

**Files:**
- Create: `src/harness/re_v2/protocol_22/policies.py`
- Create: `src/harness/re_v2/protocol_22/response_schemas.py`
- Create: `prosaic/subagents/echelon.re-baseliner.md`
- Create: `tests/unit/test_re_v2_protocol_22_policies.py`
- Create: `tests/unit/test_re_v2_protocol_22_response_schemas.py`
- Create: `tests/unit/test_prosaic_agent_authoring.py`

**Interfaces:**
- Produces: `ArtifactPolicyCatalogV1`, its four closed parameter unions, and `build_compact_v1_policy_catalog() -> ArtifactPolicyCatalogV1`.
- Produces: `policy_for(catalog, layer, artifact_kind) -> ArtifactPolicyEntryV1` and `layer_policy_hash(entry) -> str` over the complete entry.
- Produces: `authorial_response_schema(artifact_kind: Literal["domain-baseline", "source-overview"]) -> Mapping[str, object]` and canonical schema bytes/hash.
- Produces: neutral agent ID `echelon.re-baseliner` with the exact minimal trailing result block.

- [ ] **Step 1: Write RED policy and response-schema contract tests**

```python
EXPECTED_KINDS = {
    ("L0", "source-inventory"),
    ("L0", "source-partition"),
    ("L0", "domain-inventory"),
    ("L0", "source-evidence-pack"),
    ("L0", "domain-evidence-pack"),
    ("L1", "domain-context-bundle"),
    ("L1", "source-overview-context-bundle"),
    ("L1", "domain-baseline"),
    ("L1", "source-overview"),
    ("L1", "source-baseline-root"),
}


def test_builtin_catalog_has_one_policy_per_graph_slot() -> None:
    catalog = build_compact_v1_policy_catalog()
    assert {(entry.layer, entry.artifact_kind) for entry in catalog.entries} == EXPECTED_KINDS


def test_response_schema_excludes_controller_owned_fields() -> None:
    schema = authorial_response_schema("domain-baseline")
    properties = schema["properties"]
    assert set(properties) == {"schema_version", "surfaces", "unknowns"}
    assert schema["additionalProperties"] is False
```

Parameterize every policy-parameter branch, exact role order, exact surface order, mutated classifier pattern, unknown field, wrong literal, domain/source surface-map union, evidence cardinality, range direction, and `additionalProperties: false` at every object level.

- [ ] **Step 2: Run policy/schema/agent tests and confirm RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_policies.py tests/unit/test_re_v2_protocol_22_response_schemas.py tests/unit/test_prosaic_agent_authoring.py`

Expected: new module/agent assertions fail.

- [ ] **Step 3: Implement the one exact catalog and deterministic schema projection**

Build entries as immutable values, sort by `(layer, artifact_kind)`, and reject an unknown version rather than retaining an opaque mapping. Use literal caps from Global Constraints. `compact-v1` entries use the exact domain and source surface sequences from the design; evidence-pack entries use separate source/domain classifier branches so a source classifier change cannot re-key a domain pack.

Generate the response schema from the selected compact policy, then validate the generated schema itself:

```python
def canonical_response_schema_bytes(artifact_kind: BaselineKind) -> bytes:
    schema = authorial_response_schema(artifact_kind)
    Draft202012Validator.check_schema(schema)
    return canonical_json_bytes(schema)
```

- [ ] **Step 4: Author the invariant baseliner protocol**

The new agent must use paired ALWAYS/NEVER rules and require: consume only the supplied bounded context; preserve semantic claim order; cite every factual claim through an available evidence authority; use `not_established` honestly; write/return only the target authorial payload; and emit exactly:

```yaml
echelon_result:
  schema_version: 1
  outcome: candidate_ready
```

It must forbid filesystem discovery, tool calls, controller-state writes, identity/debt/coverage echoes, semantic-audit claims, synthesis, and full-quality claims.

- [ ] **Step 5: Prove every legal policy mutation changes only the expected hash**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_policies.py tests/unit/test_re_v2_protocol_22_response_schemas.py tests/unit/test_prosaic_agent_authoring.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass; schema-1 hashes remain frozen.

- [ ] **Step 6: Commit policies and the neutral agent contract**

```bash
git add src/harness/re_v2/protocol_22/policies.py \
  src/harness/re_v2/protocol_22/response_schemas.py \
  prosaic/subagents/echelon.re-baseliner.md \
  tests/unit/test_re_v2_protocol_22_policies.py \
  tests/unit/test_re_v2_protocol_22_response_schemas.py \
  tests/unit/test_prosaic_agent_authoring.py
git commit -m "feat(re-v2): pin compact baseline policy contracts"
```

---

### Task 4: Workspace Partition Catalog and Scoped Content/Partition Identities

**Files:**
- Create: `src/harness/re_v2/protocol_22/partition.py`
- Create: `tests/unit/test_re_v2_protocol_22_partition.py`
- Test: `tests/unit/test_re_v2_workspace_snapshot.py`
- Test: `tests/unit/test_re_domain_manifest.py`

**Interfaces:**
- Consumes: a validated composite `CapturedSnapshot`, declared workspace sources, `discover_source_domains()`, and pinned partitioner/ownership implementation authorities.
- Produces: closed `FileRecordV1`, `DomainDescriptorV1`, `SourceDescriptorV1`, and `WorkspacePartitionCatalogV1` values.
- Produces: `build_workspace_partition_catalog(snapshot, workspace_manifest, authorities) -> WorkspacePartitionCatalogV1`.
- Produces: `source_content_id()`, `source_partition_id()`, `domain_content_id()`, `domain_partition_id()`, and full `domain_key()` digests over the exact identity inputs.

- [ ] **Step 1: Write RED identity-locality and determinism tests**

```python
def test_domain_content_edit_does_not_change_partition_identity(fixture_workspace: Path) -> None:
    before = build_fixture_partition(fixture_workspace)
    rewrite_tracked_file(fixture_workspace, "sources/api/src/orders/handler.py", "changed\n")
    after = build_fixture_partition(fixture_workspace)
    old = domain_by_root(before, "src/orders")
    new = domain_by_root(after, "src/orders")
    assert old.domain_content_id != new.domain_content_id
    assert old.domain_partition_id == new.domain_partition_id
    assert source(before, "api").source_partition_id == source(after, "api").source_partition_id


def test_sibling_domain_insertion_preserves_stable_domain_key(fixture_workspace: Path) -> None:
    before = domain_by_root(build_fixture_partition(fixture_workspace), "src/orders")
    add_committed_sibling_domain(fixture_workspace, "src/accounts")
    after = domain_by_root(build_fixture_partition(fixture_workspace), "src/orders")
    assert before.domain_key == after.domain_key
    assert before.presentation_domain_id != after.presentation_domain_id
```

Cover input-order permutations, sibling-source edits, shared-support content edits, ownership/support/path-membership changes, CRLF/final-line counting, UTF-8/NUL/invalid UTF-8 status, and mode/kind pair rejection.

- [ ] **Step 2: Run the partition tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_partition.py`

Expected: collection fails because `protocol_22.partition` does not exist.

- [ ] **Step 3: Build descriptors only from committed snapshot bytes**

Create temporary `RePlanSource` adapters whose `absolute_path` points inside the validated snapshot component root, call the existing partitioner there, and then convert presentation domains into stable descriptors. Never call domain discovery on the workspace checkout.

Use separate canonical identity inputs:

```python
def domain_key(source_id: str, root: str, ownership_version: str) -> str:
    return content_digest({
        "ownership_policy_version": ownership_version,
        "source_id": source_id,
        "source_relative_root": root,
    })


def source_partition_id(value: SourcePartitionIdentityInputV1) -> str:
    return content_digest(value.to_json_dict())
```

The ownership implementation must emit explicit, sorted domain-owned and shared-supporting path sets; the catalog copies those sets verbatim into every partition identity. Content hashes, byte counts, line counts, and presentation ordering are excluded from partition-only identity inputs.

- [ ] **Step 4: Prove exact invalidation boundaries**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_partition.py tests/unit/test_re_v2_workspace_snapshot.py tests/unit/test_re_domain_manifest.py`

Expected: all tests pass, including clean-snapshot and existing partitioner tests.

- [ ] **Step 5: Commit deterministic partition inputs**

```bash
git add src/harness/re_v2/protocol_22/partition.py \
  tests/unit/test_re_v2_protocol_22_partition.py
git commit -m "feat(re-v2): add scoped partition identities"
```

---

### Task 5: Immutable Input Store and Manifest-Last Run Creation

**Files:**
- Create: `src/harness/re_v2/protocol_22/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_22_inputs.py`
- Modify: `src/harness/re_v2/run_store.py`
- Modify: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces: `Protocol22InputSet(workspace_partition, artifact_policy, executor_contract, immutable_objects)`.
- Produces: `create_protocol_22_run_store(run_dir: Path, manifest: RunManifestV2, inputs: Protocol22InputSet, fault_hook: FaultHook | None = None) -> ReV2Paths`.
- Produces: `load_protocol_22_inputs(paths: ReV2Paths, manifest: RunManifestV2) -> ValidatedProtocol22Inputs`.
- Enforces: catalogs live under normalized unique paths below `v2/inputs/`; all referenced objects and catalogs are fsynced before the manifest is hard-linked last.

- [ ] **Step 1: Write RED manifest-last and unsafe-reference tests**

```python
def test_protocol_22_manifest_is_published_after_every_input(tmp_path: Path) -> None:
    seen: list[str] = []
    create_protocol_22_run_store(
        tmp_path / "runs" / "re-demo",
        manifest_v2(),
        input_set(),
        fault_hook=seen.append,
    )
    assert seen[-1] == "manifest_published"


@pytest.mark.parametrize("relative", ("/absolute.json", "../escape.json", "nested/../x.json"))
def test_catalog_reference_rejects_unsafe_path(relative: str) -> None:
    with pytest.raises(Protocol22SchemaError, match="relative_path"):
        CatalogReferenceV1(object_hash=digest("1"), relative_path=relative)
```

Inject faults after each object, each catalog, input-directory fsync, manifest temporary fsync, manifest link, and run-directory fsync. Assert no active pointer is involved and a missing final manifest is detected as an incomplete v2 store.

- [ ] **Step 2: Run the input-store tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_inputs.py tests/unit/test_re_v2_run_store.py`

Expected: failures identify the missing schema-2 creation path.

- [ ] **Step 3: Implement no-clobber input publication and exact reload**

The creation function must:

1. create the unique `v2/`, `objects/`, and `inputs/` directories;
2. persist content-addressed agent/schema objects;
3. write each canonical catalog to its referenced input path with `O_EXCL|O_NOFOLLOW`;
4. verify the catalog digest and every nested referenced object;
5. fsync objects, catalogs, and directories; and
6. publish the canonical schema-2 manifest with the existing hard-link no-clobber marker.

`load_protocol_22_inputs()` must reopen paths without following symlinks, require canonical bytes and exact hashes, require three distinct references, and perform all validation before event/ledger replay.

- [ ] **Step 4: Prove crash states and schema-1 creation remain separate**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_inputs.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass; legacy `create_run_store()` continues to write schema-1 manifests exactly as before.

- [ ] **Step 5: Commit immutable input publication**

```bash
git add src/harness/re_v2/protocol_22/inputs.py src/harness/re_v2/run_store.py \
  tests/unit/test_re_v2_protocol_22_inputs.py tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): publish protocol 2.2 inputs before manifests"
```

---

### Task 6: Installed Authority Digests and Closed Executor Catalog Resolution

**Files:**
- Create: `src/harness/re_v2/protocol_22/authorities.py`
- Create: `src/harness/re_v2/protocol_22/executors.py`
- Create: `tests/unit/test_re_v2_protocol_22_authorities.py`
- Create: `tests/unit/test_re_v2_protocol_22_executors.py`
- Modify: `src/harness/config.py`
- Modify: `runtime/config-template.yml`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `implementation_closure_digest(files: Mapping[str, bytes]) -> str` over sorted logical path/content hashes.
- Produces: `InstalledAuthorityRegistry` for executor, renderer, tokenizer, calculator, normalizer, verifier, partitioner, ownership, agent, and response-schema authorities.
- Produces: typed `ReV2BaselineConfig` nested in `LlmConfig`, and `AuthorityMismatch(authority_kind, authority_id, expected_digest, installed_digest)`.
- Produces: `resolve_executor_catalog(config: HarnessConfig, goal: Literal["baseline", "inventory"], registry: InstalledAuthorityRegistry) -> ExecutorContractCatalogV1`.
- Produces: `validate_installed_authorities(catalog, registry) -> tuple[AuthorityMismatch, ...]` without mutation.

- [ ] **Step 1: Write RED digest, config, and eligibility tests**

```python
def test_closure_digest_ignores_install_path_but_not_bytes() -> None:
    first = implementation_closure_digest({"provider.py": b"one\n", "schema.py": b"two\n"})
    reordered = implementation_closure_digest({"schema.py": b"two\n", "provider.py": b"one\n"})
    changed = implementation_closure_digest({"provider.py": b"changed\n", "schema.py": b"two\n"})
    assert first == reordered
    assert first != changed


@pytest.mark.parametrize("cli", ("claude", "codex", "copilot", "opencode"))
def test_agentic_cli_is_ineligible_for_baseline(cli: str, harness_config: HarnessConfig) -> None:
    harness_config.llm.cli = cli
    with pytest.raises(Protocol22ExecutorError, match="bounded-api-baseline-v1"):
        resolve_executor_catalog(harness_config, "baseline", installed_registry())
```

Cover missing model revision, unresolved alias, missing context window, absent hard completion cap, non-HTTPS non-loopback URL, URL userinfo/query/fragment, credential header, duplicate header, over-precision sampling, invalid seed, zero deadline, wrong schema hash, and implementation drift.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_authorities.py tests/unit/test_re_v2_protocol_22_executors.py tests/unit/test_config.py`

Expected: new authority/config tests fail.

- [ ] **Step 3: Add typed baseline capability settings under the existing provider**

Add `llm.re_v2_baseline` as capability data, not a provider selector:

```yaml
llm:
  cli: openai-compatible
  re_v2_baseline:
    model_revision: gpt-example-2026-08-01
    revision_authority: provider_resolved_revision
    provider_context_tokens: 200000
    reasoning_effort: null
    top_p: "1.0"
    seed: null
    request_path: /chat/completions
    api_protocol_version: "1"
    non_secret_headers: []
    fixed_framing_byte_upper_bound: 4096
```

Parse temperature and top-p with `Decimal(str(value))`, require at most six fractional digits, and convert exactly to integer micros. Existing provider consumers retain `LlmConfig.temperature` compatibility; the resolver alone owns protocol-2.2 micros.

- [ ] **Step 4: Construct and validate exact executor entries**

Inventory goals include only deterministic entries. Baseline goals add one API entry with `max_internal_calls: 1`, zero follow-up/tool limits, a positive hard completion cap from `llm.max_tokens`, a positive active limit from `llm.timeout_ms`, and `max_billable_tokens_per_dispatch <= 262144`. API authority contains no credential values or credential-source paths.

At recovery, compare each pinned digest to the installed registry and return all mismatches as data. At creation, convert the same mismatch list to a pre-publication eligibility error.

- [ ] **Step 5: Run config and authority suites**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_authorities.py tests/unit/test_re_v2_protocol_22_executors.py tests/unit/test_config.py`

Expected: all tests pass.

- [ ] **Step 6: Commit executor authority resolution**

```bash
git add src/harness/re_v2/protocol_22/authorities.py \
  src/harness/re_v2/protocol_22/executors.py src/harness/config.py \
  runtime/config-template.yml tests/unit/test_re_v2_protocol_22_authorities.py \
  tests/unit/test_re_v2_protocol_22_executors.py tests/unit/test_config.py
git commit -m "feat(re-v2): pin bounded executor authority"
```

---

### Task 7: Complete Scoped Production Graph and Delta Planner

**Files:**
- Create: `src/harness/re_v2/protocol_22/graph.py`
- Create: `tests/unit/test_re_v2_protocol_22_graph.py`
- Test: `tests/unit/test_re_v2_planner.py`

**Interfaces:**
- Produces: `Protocol22Graph(templates, requested_goals, catalog_hashes)`.
- Produces: planning projections `AcceptedArtifactV2(artifact_key_id, artifact_hash)`, `WorkFailureStateV2(work_item_id, reason_code, failure_receipt_id)`, and `ExecutorFailureStateV2(executor_contract_hash, reason_code, executor_failure_receipt_id)`.
- Produces: structural `PlanningBudgetV2.item_attempt_available(work_item: WorkItemV2) -> bool`; Task 12's `BudgetDecisionV2` implements it.
- Produces: `build_protocol_22_graph(manifest, inputs) -> Protocol22Graph` with one logical output per `(scope, artifact_kind, layer)`.
- Produces: `instantiate_ready_item(template, accepted_dependencies, inputs) -> WorkItemV2`.
- Produces: `plan_next_v22(graph, authority: PlanningAuthorityV2, budget: PlanningBudgetV2) -> PlanDecisionV2`.
- Consumes: only immutable manifest/catalog values and replay-derived accepted/failed state.

- [ ] **Step 1: Write RED graph-shape and layer-isolation tests**

```python
def test_baseline_graph_has_exact_nodes_per_source_and_domain() -> None:
    graph = graph_for_sources({"api": ("orders", "users"), "web": ("ui",)})
    assert len(graph.templates) == (6 + 4 * 2) + (6 + 4 * 1)
    assert logical_slots(graph) == set(logical_slots(graph))


def test_l1_policy_change_preserves_every_l0_template_and_key() -> None:
    compact = graph_with_policy(build_compact_v1_policy_catalog())
    changed = graph_with_policy(replace_compact_statement_limit(900))
    assert l0_templates(compact) == l0_templates(changed)
    assert l1_template_ids(compact) != l1_template_ids(changed)


def test_provider_change_does_not_change_artifact_key() -> None:
    first = ready_domain_item(executor_contract_hash=digest("1"))
    second = ready_domain_item(executor_contract_hash=digest("2"))
    assert first.work_item_id != second.work_item_id
    assert first.output_key == second.output_key
```

Cover inventory versus baseline closure, stable domain keys despite presentation renumbering, duplicate logical output, missing dependency, cycle, mismatched policy/executor family, schema-1 work rejection, dependency-hash sorting, failed dependency closure, executor-blocked state, and independent sibling readiness.

- [ ] **Step 2: Run graph tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_graph.py`

Expected: collection fails because the graph builder does not exist.

- [ ] **Step 3: Build templates in stable scope/kind/layer order**

For each source with `D` domains, build the exact `6 + 4D` baseline nodes from the design. Inventory selects the `3 + 2D` L0 nodes. Put presentation IDs only in descriptor inputs for source-root materialization, never in domain scope or artifact keys.

Use a narrow planning authority so graph tests do not depend on ledger implementation order:

```python
class PlanningAuthorityV2(Protocol):
    def artifact_for_key(self, artifact_key_id: str) -> AcceptedArtifactV2 | None:
        raise NotImplementedError

    def work_failure(self, work_item_id: str) -> WorkFailureStateV2 | None:
        raise NotImplementedError

    def executor_failure(self, executor_contract_hash: str) -> ExecutorFailureStateV2 | None:
        raise NotImplementedError
```

Planner explanations must use stable reason codes for exact reuse, ready generation, missing dependency, failed dependency, failed executor, exhausted item attempts, run budget, and pinned-authority unavailability.

- [ ] **Step 4: Prove deterministic reconstruction and legacy planner isolation**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_graph.py tests/unit/test_re_v2_planner.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass; input permutations yield identical template bytes and IDs.

- [ ] **Step 5: Commit the production DAG**

```bash
git add src/harness/re_v2/protocol_22/graph.py \
  tests/unit/test_re_v2_protocol_22_graph.py
git commit -m "feat(re-v2): build scoped compact baseline graph"
```

---

### Task 8: Deterministic Artifact Values, L0 Inventories, and Source Partition

**Files:**
- Create: `src/harness/re_v2/protocol_22/artifacts.py`
- Create: `src/harness/re_v2/protocol_22/inventory.py`
- Create: `tests/unit/test_re_v2_protocol_22_artifacts.py`
- Create: `tests/unit/test_re_v2_protocol_22_inventory.py`
- Modify: `src/harness/re_v2/ledger.py`
- Test: `tests/unit/test_re_v2_ledger.py`

**Interfaces:**
- Produces: frozen `DepthDebtV1`, omission descriptors, `EvidenceExcerptV1`, `EvidencePackV1`, `ContextBundleV1`, and `SourceBaselineRootV1` models shared by later producers.
- Produces: `AcceptedDependencySetV2(by_role: Mapping[str, AcceptedArtifactV2])` and `DeterministicAssessmentInputV2(canonical_schema_valid, dependency_closure_valid, policy_conformance_valid, depth_debt, normalized_diagnostics)`.
- Produces: `ObjectStore.read_blob(object_hash: str) -> bytes`, rejecting tree objects and re-verifying the digest.
- Produces: `produce_source_inventory()`, `produce_domain_inventory()`, and `produce_source_partition()` returning canonical object bytes.
- Produces: `validate_deterministic_artifact(work_item: WorkItemV2, payload: bytes, inputs: ValidatedProtocol22Inputs, dependencies: AcceptedDependencySetV2) -> DeterministicAssessmentInputV2`.

- [ ] **Step 1: Write RED artifact-invariant and inventory-copy tests**

```python
def test_source_partition_copies_partition_catalog_without_content_fields() -> None:
    payload = decode(produce_source_partition(source_work_item(), validated_inputs()))
    assert payload["source_partition_id"] == source_descriptor().source_partition_id
    assert payload["domains"] == [domain.partition_projection() for domain in source_descriptor().domains]
    assert "domain_content_id" not in canonical_json_bytes(payload).decode("utf-8")


def test_domain_inventory_has_exact_owned_and_supporting_rows() -> None:
    payload = decode(produce_domain_inventory(domain_work_item(), validated_inputs()))
    assert [(row["source_relative_path"], row["ownership"]) for row in payload["files"]] == [
        ("shared/config.yml", "shared_supporting"),
        ("src/orders/handler.py", "owned"),
    ]
```

Parameterize all zero/null debt rules, count equations, mode/kind/text-status pairs, dependency mismatch, scope mismatch, wrong policy hash, altered catalog projection, unsorted rows, object corruption, and content-only edits preserving partition bytes.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_artifacts.py tests/unit/test_re_v2_protocol_22_inventory.py tests/unit/test_re_v2_ledger.py -k 'read_blob or inventory or partition'`

Expected: failures identify missing artifact values/producers and blob reader.

- [ ] **Step 3: Implement exact values and no-follow snapshot reads**

All model `from_json_dict()` methods use Task 2's exact-field validators. Inventory producers select rows from the validated partition catalog, not by rescanning ownership. Before copying a regular snapshot blob, reopen it relative to the validated component root without following links and require its content hash, byte count, line count, mode, and text status to match the catalog.

Expose immutable blobs safely:

```python
def read_blob(self, object_hash: str) -> bytes:
    payload = self._verify(object_hash, set())
    if _parse_tree_manifest(payload) is not None:
        raise ReV2LedgerError("object is a tree, not a blob")
    return payload
```

- [ ] **Step 4: Prove deterministic invocation role contracts**

Define exact roles per producer family: source inventory=`workspace_partition`; source partition=`workspace_partition`; domain inventory=`workspace_partition`; evidence and context roles are introduced in Tasks 9/10; source root=`source_overview` plus one `domain:<domain-key>` role per domain. Reject any missing, duplicate, or unknown role before producing bytes.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_artifacts.py tests/unit/test_re_v2_protocol_22_inventory.py tests/unit/test_re_v2_ledger.py`

Expected: all tests pass; existing object-store/tree tests remain unchanged.

- [ ] **Step 5: Commit deterministic inventory artifacts**

```bash
git add src/harness/re_v2/protocol_22/artifacts.py \
  src/harness/re_v2/protocol_22/inventory.py src/harness/re_v2/ledger.py \
  tests/unit/test_re_v2_protocol_22_artifacts.py \
  tests/unit/test_re_v2_protocol_22_inventory.py tests/unit/test_re_v2_ledger.py
git commit -m "feat(re-v2): produce canonical L0 inventories"
```

---

### Task 9: Provider-Neutral Bounded Evidence Packs

**Files:**
- Create: `src/harness/re_v2/protocol_22/evidence.py`
- Create: `tests/unit/test_re_v2_protocol_22_evidence.py`

**Interfaces:**
- Produces: `build_evidence_pack(work_item, inventory_bytes, snapshot_reader, policy) -> bytes`.
- Produces: `evidence_authority_id(descriptor: EvidenceAuthorityDescriptorV1) -> str`.
- Produces: deterministic omission descriptors and exact `DepthDebtV1` from every unselected file/range.
- Produces: `PinnedSnapshotReaderV1.read_file(source_id: str, source_relative_path: str, expected: FileRecordV1) -> bytes` using no-follow reads and catalog verification.
- Enforces: one UTF-8 byte reserves one conservative input token; allocation never consults a provider/model tokenizer.

- [ ] **Step 1: Write RED allocation, byte-rule, and debt tests**

```python
def test_evidence_pack_is_stable_across_inventory_order_and_provider() -> None:
    first = build_pack(shuffled=False, provider="one", exact_tokenizer=True)
    second = build_pack(shuffled=True, provider="two", exact_tokenizer=False)
    assert first == second


def test_crlf_excerpt_hashes_raw_bytes_but_exposes_lf_text() -> None:
    excerpt = only_excerpt(build_pack_for_blob(b"one\r\ntwo\r\n"))
    assert excerpt.text_lf == "one\ntwo\n"
    assert excerpt.raw_excerpt_hash == content_digest(b"one\r\ntwo\r\n")
    assert (excerpt.start_line, excerpt.end_line) == (1, 2)
```

Cover exact role priority, normalized-path tiebreak, empty files, final unterminated lines, lone CR preservation, invalid UTF-8, NUL, non-regular entries, a first line too large for an empty pack, partial prefixes, canonical serialization delta, equal-share allocation, round-robin redistribution, input-order restart stability, and exact 48/96 KiB boundaries.

- [ ] **Step 2: Run evidence tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_evidence.py`

Expected: collection fails because the evidence producer is absent.

- [ ] **Step 3: Implement the five-stage allocation protocol literally**

Classify every inventory record exactly once, create debt immediately for ineligible/non-text rows, allocate one whole line per candidate, distribute remaining serialized capacity evenly by canonical-byte delta, and redistribute unused capacity in normalized-path round-robin passes. Serialize the entire provisional pack after every proposed extension.

```python
def fits(policy: ArtifactPolicyEntryV1, candidate: EvidencePackV1) -> bool:
    size = len(canonical_json_bytes(candidate.to_json_dict()))
    return size <= policy.max_canonical_json_bytes and size <= policy.max_conservative_input_tokens
```

Never split a line, follow a link, normalize Unicode, infer omitted behavior, or use a path-only evidence identity.

- [ ] **Step 4: Prove pack validation reconstructs every excerpt**

Reopen the pinned blob, recompute original LF line boundaries, raw bytes/hash, CRLF-only normalized text, complete-file flag, authority descriptor, counts, omission descriptor set, and final canonical caps. A mismatch returns deterministic certification diagnostics; it never repairs bytes.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_evidence.py tests/unit/test_re_v2_protocol_22_inventory.py`

Expected: all tests pass.

- [ ] **Step 5: Commit bounded L0 evidence selection**

```bash
git add src/harness/re_v2/protocol_22/evidence.py \
  tests/unit/test_re_v2_protocol_22_evidence.py
git commit -m "feat(re-v2): build bounded deterministic evidence packs"
```

---

### Task 10: Domain/Source Context Bundles, Projections, Debt Rollups, and Roots

**Files:**
- Create: `src/harness/re_v2/protocol_22/context.py`
- Create: `tests/unit/test_re_v2_protocol_22_context.py`
- Test: `tests/unit/test_re_v2_protocol_22_artifacts.py`

**Interfaces:**
- Produces: `build_domain_context_bundle(work_item: WorkItemV2, accepted_inputs: AcceptedDependencySetV2, policies: ArtifactPolicyCatalogV1) -> bytes`.
- Produces: `build_source_overview_context_bundle(work_item: WorkItemV2, accepted_inputs: AcceptedDependencySetV2, policies: ArtifactPolicyCatalogV1) -> bytes`.
- Produces: `build_source_baseline_root(work_item: WorkItemV2, accepted_inputs: AcceptedDependencySetV2, partition: WorkspacePartitionCatalogV1) -> bytes`.
- Enforces: domain bundles contain no projections; source projections retain materiality order, exact evidence, and complete upstream debt under 2 KiB/domain and 32 KiB total projection caps.

- [ ] **Step 1: Write RED closure, projection-order, and rollup tests**

```python
def test_domain_bundle_has_only_exact_domain_dependencies() -> None:
    bundle = decode(build_domain_bundle_fixture())
    assert bundle["domain_projections"] == []
    assert dependency_kinds(bundle) == {"domain-inventory", "domain-evidence-pack"}


def test_source_projection_preserves_claim_materiality_order() -> None:
    bundle = decode(build_source_bundle_with_claims(["z-most-material", "a-second"]))
    claims = bundle["domain_projections"][0]["claims"]
    assert [entry["claim"]["statement"] for entry in claims] == ["z-most-material", "a-second"]
```

Cover authority rewrite from direct domain evidence to `domain_projection`, exact copied excerpts, uncitable claim omission, per-domain and total caps, whole-domain omission, original claim hash before rewrite, retained/omitted equations, zero/null rules, duplicate physical paths in multiple domains, complete domain-debt rollup, target-policy hash mismatch, unrelated dependency rejection, and source-root dependency completeness.

- [ ] **Step 2: Run context tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_context.py`

Expected: collection fails because context builders do not exist.

- [ ] **Step 3: Implement deterministic domain and source bundle construction**

Domain context copies the exact accepted domain evidence pack and inventory metadata. Source context includes its exact source evidence and projects accepted domain baselines by stable domain key, surfaces in `responsibilities`, `entry_points`, `external_contracts` priority, then original claim index. It carries only the evidence needed by retained claims.

Reject a retained claim unless every rewritten authority ID resolves to exactly one projected excerpt. Compute omission hashes from ordered descriptors and recompute all debt count equations before object-store publication.

- [ ] **Step 4: Implement the candidate-free, timestamp-free source root**

The root copies source scope/partition/policy, exact overview hash, and domain `(domain_key, presentation_domain_id, baseline_artifact_hash)` rows. Its dependency array contains the overview and all domains exactly once and no certification/candidate IDs.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_context.py tests/unit/test_re_v2_protocol_22_artifacts.py tests/unit/test_re_v2_protocol_22_graph.py`

Expected: all tests pass; re-certification inputs cannot change root bytes.

- [ ] **Step 5: Commit deterministic L1 composition**

```bash
git add src/harness/re_v2/protocol_22/context.py \
  tests/unit/test_re_v2_protocol_22_context.py \
  tests/unit/test_re_v2_protocol_22_artifacts.py
git commit -m "feat(re-v2): compose bounded L1 contexts and roots"
```

---

### Task 11: Compact Authorial Parsing, Coverage, Certification, and Markdown

**Files:**
- Create: `src/harness/re_v2/protocol_22/baseline.py`
- Create: `tests/unit/test_re_v2_protocol_22_baseline.py`
- Create: `tests/unit/test_re_v2_protocol_22_certification.py`

**Interfaces:**
- Produces: `parse_authorial_candidate(raw: bytes, artifact_kind, policy) -> NormalizedAuthorialPayloadV1`.
- Produces: `certify_compact_candidate(candidate, work_item, context, snapshot, verifier) -> CompactCertificationResultV2`.
- Produces: deterministic `CoverageAssessmentV1`, required-surface records, minimum-utility assessment, full artifact bytes, `CertificationReceiptV2`, and `CandidateAssessmentReceiptV1`.
- Produces: `certify_deterministic_artifact(work_item: WorkItemV2, artifact_hash: str, assessment: DeterministicAssessmentInputV2, verifier: VerifierAuthorityV1) -> CertificationReceiptV2`.
- Produces: `render_baseline_markdown(artifact_bytes: bytes) -> bytes`.
- Produces: `VerifierAuthorityV1(verifier_id, verifier_version, implementation_digest)` and `CompactCertificationResultV2(artifact_bytes, certification, candidate_assessment)`.
- Produces: exact `CertificationKeyV2`, `CertificationReceiptV2`, `CandidateAssessmentReceiptV1`, and `ArtifactAcceptanceReceiptV2` values used by Task 13's ledger.

- [ ] **Step 1: Write RED strict-authorial and normalization tests**

```python
def test_candidate_cannot_supply_controller_owned_fields() -> None:
    raw = valid_domain_candidate_dict()
    raw["artifact"] = {"layer": "L1"}
    with pytest.raises(CompactCandidateError, match="unknown fields"):
        parse_authorial_candidate(canonical_json_bytes(raw), "domain-baseline", domain_policy())


def test_normalization_preserves_claim_order_and_sorts_evidence() -> None:
    raw = candidate_with_claims(["second lexical", "first lexical"])
    normalized = parse_authorial_candidate(canonical_json_bytes(raw), "domain-baseline", domain_policy())
    assert [claim.statement for claim in normalized.surfaces.responsibilities.items] == [
        "second lexical", "first lexical"
    ]
    assert normalized.surfaces.responsibilities.items[0].evidence == tuple(
        sorted(normalized.surfaces.responsibilities.items[0].evidence, key=evidence_sort_key)
    )
```

Cover duplicate keys, non-finite values, invalid Unicode, mixed surface maps, empty/NFC-colliding statements/questions, all cardinalities, byte limits, control characters, reversed/out-of-excerpt ranges, authority/path mismatch, sibling source/domain evidence, undeclared shared support, unprojected evidence, raw/final byte bounds, and ambiguous duplicates after normalization.

- [ ] **Step 2: Write RED utility, coverage, and receipt-separation tests**

```python
def test_all_not_established_domain_fails_minimum_utility() -> None:
    result = certify_fixture(all_not_established_domain_candidate())
    assert result.certification.verdict == "rejected"
    assert result.certification.assessment.minimum_utility.diagnostic_codes == (
        "responsibilities_not_observed", "entry_or_behavior_not_observed", "no_regular_file_cited"
    )


def test_two_candidates_share_certification_but_keep_provenance() -> None:
    first = certify_fixture(candidate_bytes(order="pretty"), candidate_id="candidate-a")
    second = certify_fixture(candidate_bytes(order="compact"), candidate_id="candidate-b")
    assert first.artifact_bytes == second.artifact_bytes
    assert first.certification.identity == second.certification.identity
    assert first.candidate_assessment.identity != second.candidate_assessment.identity
```

Assert domain combined counts equal direct counts; source combined counts equal direct plus projected-domain counts for every integer; ratios repeat exact integers; zero denominators render not-applicable; referenced keys are selected; omitted domains contribute inventory but zero overview selection; and candidates cannot declare coverage/debt.

- [ ] **Step 3: Run baseline/certification tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_baseline.py tests/unit/test_re_v2_protocol_22_certification.py`

Expected: new imports fail.

- [ ] **Step 4: Implement normalization, envelope injection, and exact assessments**

Normalize provider prose with CRLF/lone-CR to LF, NFC, and Unicode-whitespace trim. Preserve claim/unknown semantic arrays; sort only evidence arrays. Resolve each evidence authority to exactly one context excerpt and reconstruct the entire cited original line range from the pinned blob.

Construct the artifact envelope only after authorial validation, inject WorkItem/context/debt fields, canonicalize, and enforce its kind-specific cap. Certification identity excludes candidate, work item, timestamp, transport, and provider data. Candidate assessment retains those candidate-specific links.

- [ ] **Step 5: Implement deterministic Markdown and certification variants**

Render sections in literal policy order, include observed claims with evidence ranges, render unknowns only as questions, and expose debt/unaudited status without implying completeness. Require byte stability and the 96 KiB cap. Deterministic artifacts use the deterministic assessment branch with null compact coverage.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_baseline.py tests/unit/test_re_v2_protocol_22_certification.py tests/unit/test_re_v2_protocol_22_context.py`

Expected: all tests pass.

- [ ] **Step 6: Commit controller-owned compact certification**

```bash
git add src/harness/re_v2/protocol_22/baseline.py \
  tests/unit/test_re_v2_protocol_22_baseline.py \
  tests/unit/test_re_v2_protocol_22_certification.py
git commit -m "feat(re-v2): certify compact baseline artifacts"
```

---

### Task 12: Protocol-Selected Event Replay and Reservation-Aware Budgets

**Files:**
- Create: `src/harness/re_v2/protocol_22/events.py`
- Create: `src/harness/re_v2/protocol_22/budget.py`
- Create: `tests/unit/test_re_v2_protocol_22_events.py`
- Create: `tests/unit/test_re_v2_protocol_22_budget.py`
- Modify: `src/harness/re_v2/events.py`
- Test: `tests/unit/test_re_v2_events.py`
- Test: `tests/unit/test_re_v2_budget.py`

**Interfaces:**
- Produces: `EventProtocol` seam with `canonical_payload()`, `new_state()`, and `consume()`; legacy remains the default.
- Produces: `PROTOCOL_22_EVENTS` with every closed payload and ordering rule from the design.
- Produces: `evaluate_budget_v22(policy, events, open_dispatches, now) -> BudgetDecisionV2`.
- Produces: per-item counters for provider, generation, semantic, result, shared, and artifact retries plus conservative token/active charges and reservations.

- [ ] **Step 1: Freeze a legacy event chain and write RED 2.2 schemas**

First construct the existing schema-1 `run_created -> work_planned` fixture from `tests/unit/test_re_v2_events.py` and pin its current hashes exactly:

```python
assert events[0].event_hash == "sha256:c0793338b9ad23b6664b9f0fbf93b7d59018f48bdadfa5e60221612c426855e4"
assert events[1].event_hash == "sha256:3fb132eaec952e1809d535ffe676cd9b51d77305843cf5d70bd59d5c7652894b"
assert content_digest(store.path.read_bytes()) == (
    "sha256:a6fb50282fc11ce5ce427623c7ebe98673a3185348a842b6c50ab678dd4f1494"
)
```

Then add:

```python
def test_protocol_22_dispatch_started_requires_execution_authority() -> None:
    with pytest.raises(ReV2EventError, match="execution_input_hash"):
        event_store_v22().append(
            "dispatch_started",
            {"dispatch_id": "d1", "work_item_id": digest("1"), "attempt_index": 1,
             "attempt_kind": "initial_generation"},
            occurred_at=NOW,
        )


def test_one_item_cannot_consume_both_retry_kinds() -> None:
    state = replay_v22(events_with_result_retry_then_artifact_retry())
    assert state is None
```

Cover reconstructed-result ordering, candidate events, deterministic no-candidate path, abandonment, work/executor failure receipt prerequisites, artifact acceptance prerequisites, pause/resume/terminal ordering, and exact rejection of protocol-2.2 fields by legacy replay.

- [ ] **Step 2: Run event tests and verify RED without changing legacy behavior**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_events.py tests/unit/test_re_v2_events.py`

Expected: protocol-2.2 imports fail; legacy tests pass.

- [ ] **Step 3: Add the narrow event-protocol seam**

```python
class EventProtocol(Protocol):
    def canonical_payload(self, event_type: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        raise NotImplementedError

    def new_state(self) -> "EventReplayState":
        raise NotImplementedError


class EventReplayState(Protocol):
    def consume(self, event: EventRecord) -> None:
        raise NotImplementedError


class EventStore:
    def __init__(self, path: Path | ReV2Paths, *, protocol: EventProtocol = LEGACY_EVENT_PROTOCOL):
        self.protocol = protocol
```

Route append and replay validation through that object. Do not change `EventRecord`, its schema version, field names, hash identity, LF framing, lock behavior, or the legacy default protocol.

- [ ] **Step 4: Implement exact 2.2 attempt/resource accounting**

Charge provider attempts only for API work, generation attempts for every execution, and shared plus kind-specific counters for a retry. For open/abandoned/untrusted dispatches charge the reservation; for trusted exact observations charge the exact value; for untrusted non-null values charge `max(value, reservation)`. Any observed value above reservation is a breach signal, not available budget.

```python
def conservative_charge(value: int | None, status: UsageStatus, reservation: int) -> int:
    if status == "trusted_exact":
        assert value is not None
        return value
    if status == "unavailable":
        assert value is None
        return reservation
    return max(reservation, 0 if value is None else value)
```

- [ ] **Step 5: Run legacy and 2.2 event/budget suites**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_events.py tests/unit/test_re_v2_protocol_22_budget.py tests/unit/test_re_v2_events.py tests/unit/test_re_v2_budget.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass; the frozen legacy chain is byte-identical.

- [ ] **Step 6: Commit protocol-aware replay and accounting**

```bash
git add src/harness/re_v2/events.py src/harness/re_v2/protocol_22/events.py \
  src/harness/re_v2/protocol_22/budget.py \
  tests/unit/test_re_v2_events.py tests/unit/test_re_v2_protocol_22_events.py \
  tests/unit/test_re_v2_protocol_22_budget.py
git commit -m "feat(re-v2): replay protocol 2.2 events and budgets"
```

---

### Task 13: Protocol-2.2 Ledger Receipts and Failure Authority

**Files:**
- Create: `src/harness/re_v2/protocol_22/ledger.py`
- Create: `tests/unit/test_re_v2_protocol_22_ledger.py`
- Modify: `src/harness/re_v2/ledger.py`
- Test: `tests/unit/test_re_v2_ledger.py`

**Interfaces:**
- Produces: a protocol-authority seam around the existing ledger envelope, lock, LF framing, sequence, previous hash, and record hash.
- Produces: `Protocol22Ledger` methods `record_certification`, `record_candidate_assessment`, `record_artifact_acceptance`, `record_work_item_failure`, `record_executor_failure`, and `replay`.
- Produces: `Protocol22LedgerView` implementing Task 7's `PlanningAuthorityV2`.
- Produces: exact `WorkItemFailureReceiptV1` and `ExecutorFailureReceiptV1` values plus the planning projections returned by that view.
- Preserves: legacy `Ledger` method signatures and default schema-1 authority.

- [ ] **Step 1: Freeze one legacy ledger chain and write RED receipt tests**

Construct the existing accepted certification/artifact fixture from `tests/unit/test_re_v2_ledger.py` and pin `record_hash` values `sha256:d86954da4a43b995d40aef519ff988a9f5a4e7745918c73bea372dc4dcb3c471` and `sha256:8602a4d48b19bc8cafdf769a0a74f803fd99926a5a0cc603a24d64789d180a2c`, plus complete ledger-file digest `sha256:9fa329fa18f07b1ab640e9c70fdd14fd719f15fd9dec2ebee953cf30d0d83aa5`.

```python
def test_artifact_acceptance_is_candidate_and_timestamp_independent() -> None:
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=artifact_key_v2(),
        artifact_hash=digest("a"),
        certification_receipt_id=digest("c"),
    )
    assert set(acceptance.to_json_dict()) == {
        "schema_version", "artifact_key", "artifact_hash", "certification_receipt_id"
    }


def test_executor_failure_is_unique_per_contract(tmp_path: Path) -> None:
    ledger = protocol_22_ledger(tmp_path)
    ledger.record_executor_failure(executor_failure(reason="reservation_mismatch"))
    with pytest.raises(ReV2LedgerError, match="conflicting executor-failure receipt"):
        ledger.record_executor_failure(executor_failure(reason="limit_unenforceable"))
```

Cover certification-key uniqueness, two candidates/one certification, candidate-assessment branch nullability, artifact receipt requiring preceding accepted certification, candidate acceptance requiring certified assessment, deterministic acceptance requiring null candidate assessment, work-item reason/failure-class pairing, indeterminate event versus capture mutual exclusion, executor reason/field pairing, diagnostics normalization, orphan receipt visibility, and object corruption.

- [ ] **Step 2: Run legacy and 2.2 ledger tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_ledger.py tests/unit/test_re_v2_ledger.py`

Expected: protocol-2.2 tests fail; legacy tests pass.

- [ ] **Step 3: Extract only protocol authority from durable ledger mechanics**

```python
LedgerViewT = TypeVar("LedgerViewT")


class LedgerReplayState(Protocol, Generic[LedgerViewT]):
    def consume(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        raise NotImplementedError

    def view(self) -> LedgerViewT:
        raise NotImplementedError

    def idempotent_record(self, history: tuple[LedgerRecord, ...],
                          record_type: str, payload: Mapping[str, object]) -> LedgerRecord | None:
        raise NotImplementedError


class LedgerProtocol(Protocol, Generic[LedgerViewT]):
    def new_state(self) -> LedgerReplayState[LedgerViewT]:
        raise NotImplementedError

    def canonical_payload(self, record_type: str, value: object) -> Mapping[str, object]:
        raise NotImplementedError
```

Keep the current implementation as `LEGACY_LEDGER_PROTOCOL`. Route raw append/replay through the selected protocol object. Existing `Ledger` remains a typed legacy facade; `Protocol22Ledger` is the typed schema-2 facade. Do not change `LedgerRecord` bytes or hash calculation.

- [ ] **Step 4: Implement graph failure derivation in the 2.2 view**

Replay accepted work first, then classify the executor trigger as `failed_executor_contract`, other unresolved items on that contract as `blocked_by_executor_failure`, their unaccepted downstream closure as `blocked_by_failed_dependency`, and explicit item failures as their receipt class. Do not create synthetic receipts for derived blocked nodes.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_ledger.py tests/unit/test_re_v2_ledger.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass and the frozen legacy ledger chain is unchanged.

- [ ] **Step 5: Commit protocol-specific receipt authority**

```bash
git add src/harness/re_v2/ledger.py src/harness/re_v2/protocol_22/ledger.py \
  tests/unit/test_re_v2_ledger.py tests/unit/test_re_v2_protocol_22_ledger.py
git commit -m "feat(re-v2): persist protocol 2.2 receipt authority"
```

---

### Task 14: Stored Provider Envelopes, Reservation Calculation, and Bounded API Adapter

**Files:**
- Create: `src/harness/re_v2/protocol_22/provider.py`
- Create: `tests/support/re_v2_bounded_api.py`
- Create: `tests/unit/test_re_v2_protocol_22_provider.py`
- Create: `tests/contract/test_re_v2_bounded_api.py`

**Interfaces:**
- Produces: `render_provider_request_envelope(work_item, dispatch_id, agent_bytes, context_bytes, executor, schema_hash) -> ProviderRequestEnvelopeV1`.
- Produces: `render_wire_request(envelope, response_schema_bytes) -> bytes`.
- Produces: `calculate_bounded_dispatch_reservation(envelope, schema_bytes, executor, tokenizer) -> DispatchReservationV1`.
- Produces: `normalize_openai_usage(raw_usage: object, contract) -> NormalizedUsageV1`.
- Produces: `BoundedApiBaselineExecutor.execute(execution_input, envelope, reservation, candidate_root, deadline) -> RawExecutionResultV1`.
- Produces: frozen `DispatchReservationV1(initial_input_tokens, billable_tokens, active_ms)`, `NormalizedUsageV1(status, billable_tokens, classes)`, and `RawExecutionResultV1(stdout, stderr, provider_usage, timing, outcome)`.
- Produces: test-only `ScriptedBoundedApi` with `base_url`, captured request list, per-work-item response scripts, and `for_scenario()` used by Task 20.

- [ ] **Step 1: Write RED envelope and reservation tests**

```python
def test_fallback_reservation_covers_complete_wire_request() -> None:
    wire = render_wire_request(provider_envelope(), response_schema_bytes())
    reservation = calculate_bounded_dispatch_reservation(
        provider_envelope(), response_schema_bytes(), api_executor_contract(), fallback_tokenizer()
    )
    expected_input = len(wire) + api_executor_contract().request_tokenizer.fixed_framing_byte_upper_bound
    assert reservation.initial_input_tokens == expected_input
    assert reservation.billable_tokens == expected_input + api_executor_contract().limits.max_completion_tokens_per_call


def test_mutable_provider_defaults_cannot_change_stored_envelope() -> None:
    stored = canonical_json_bytes(provider_envelope().to_json_dict())
    mutate_process_environment_and_user_config()
    assert canonical_json_bytes(load_envelope(stored).to_json_dict()) == stored
```

Cover literal two-message order/content, target/schema selection, executor/work IDs, model/revision/reasoning/sampling micros, null-seed omission on wire, tool-free fields, complete response schema expansion, provider context-window check, safety ceiling, calculator mismatch, and exact versus fallback tokenizer behavior.

- [ ] **Step 2: Write RED one-call HTTP conformance tests**

Use `ThreadingHTTPServer` bound to `127.0.0.1` and record every request. Assert one POST, normalized path, only pinned non-secret plus content/auth headers, strict JSON schema, hard `max_completion_tokens`, `tool_choice: none`, empty tools, no stream, deadline timeout, and no retry inside the adapter.

Parameterize multiple choices, non-string content, refusal, tool calls, mismatched response model revision, missing completion cap, timeout, HTTP error, invalid response JSON, missing usage, unclassifiable usage, and exact trusted usage. Each invalid authorial response leaves an empty candidate inventory rather than extracting prose.

- [ ] **Step 3: Run provider tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_provider.py tests/contract/test_re_v2_bounded_api.py`

Expected: collection fails because the provider implementation is absent.

- [ ] **Step 4: Implement deterministic request and usage normalization**

The system message is the exact pinned agent-contract text. The user message is the exact canonical context-bundle UTF-8 text. Expand the stored response-schema hash to the verified schema object only in `render_wire_request`; the reservation calculator tokenizes/counts those exact wire bytes plus the pinned framing bound.

For the initial OpenAI-compatible normalizer, require nonnegative `prompt_tokens`, `completion_tokens`, and equal `total_tokens`. Treat cached tokens as a subset of input and reasoning tokens as a subset of completion; compute disjoint classes whose sum equals total. An unknown or inconsistent class produces `untrusted`, never an exact zero.

- [ ] **Step 5: Implement exactly one deadline-bound API call**

Load credentials only at dispatch, add only the credential header, perform one non-streaming request, validate exactly one non-refusal assistant string and the resolved response model, write those UTF-8 bytes to `baseline.json` with no fence/prose repair, fsync the file/directory, and return the trusted minimal result block as stdout. Measure active duration from `time.monotonic_ns()` immediately around the request and local teardown; use RFC3339 wall time only as telemetry. Persist lossless canonical usage bytes in the raw execution result for Task 15.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_provider.py tests/contract/test_re_v2_bounded_api.py`

Expected: all tests pass; the HTTP server observes at most one request per adapter invocation.

- [ ] **Step 6: Commit the bounded API adapter**

```bash
git add src/harness/re_v2/protocol_22/provider.py \
  tests/support/re_v2_bounded_api.py \
  tests/unit/test_re_v2_protocol_22_provider.py \
  tests/contract/test_re_v2_bounded_api.py
git commit -m "feat(re-v2): add bounded compact baseline API adapter"
```

---

### Task 15: Durable Execution Inputs, Captures, Candidates, and Commit Authority

**Files:**
- Create: `src/harness/re_v2/protocol_22/execution.py`
- Create: `tests/unit/test_re_v2_protocol_22_execution.py`
- Test: `tests/unit/test_re_v2_candidates.py`

**Interfaces:**
- Produces: `Protocol22ExecutionStore(paths, object_store)`.
- Produces: `prepare_execution(work_item, attempt_kind, dependencies, fault_hook: FaultHook | None = None) -> PreparedExecutionV1` with durable envelope then execution input.
- Produces: `record_started_lease()`, `capture_provider_result()`, `capture_deterministic_result()`, `commit_capture()`, `persist_candidate()`, and read-only closure validators.
- Produces: `CaptureCommitState = Missing | StagingReady | Committed | Conflict` for Task 16.
- Produces: `PreparedExecutionV1(dispatch_id, execution_input_hash, provider_envelope_hash, reservation)` and the four concrete capture-state dataclasses carrying validated paths/hashes.

- [ ] **Step 1: Write RED exact-schema and ordering tests**

```python
def test_provider_input_persists_envelope_before_execution_input(store: Protocol22ExecutionStore) -> None:
    boundaries: list[str] = []
    prepared = store.prepare_execution(provider_item(), "initial_generation", provider_dependencies(), boundaries.append)
    assert boundaries.index("provider_envelope_fsynced") < boundaries.index("execution_input_fsynced")
    assert prepared.execution_input.provider_request_envelope_hash is not None
    assert prepared.execution_input.deterministic_invocation is None


def test_candidate_id_has_no_path_or_timestamp(store: Protocol22ExecutionStore) -> None:
    candidate = store.persist_candidate(committed_provider_capture())
    assert set(candidate.to_json_dict()) == {
        "schema_version", "dispatch_id", "work_item_id",
        "execution_capture_hash", "candidate_inventory_hash"
    }
```

Cover exact deterministic/provider branch nullability, invocation role sets, candidate entry mode/kind/hash pairs, empty API inventory, symlink/special entries, raw candidate cap, stdout complete/tail rules, missing stdout blob, usage blob hash, resolved revision, execution/capture ID mismatch, staging/commit conflicts, no-clobber publication, and fsync fault points.

- [ ] **Step 2: Run execution tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_execution.py`

Expected: collection fails because the execution store does not exist.

- [ ] **Step 3: Implement prepared execution and lease authority**

Store provider envelope, ExecutionInput, and deterministic invocation as content-addressed objects. Immediately before `dispatch_started`, reload them, verify embedded IDs/hashes and all installed authorities, recompute reservations, then publish one safe run-local lease under the exclusive run lock. A prepared input with no start event may be reused; its existence never implies execution.

- [ ] **Step 4: Implement capture closure and no-clobber commit**

Persist regular candidate blobs, canonical inventory, stdout blob/tail, usage blob, or deterministic result first; persist `ExecutionCapture`; write/fsync staging `ready.json`; then hard-link identical commit bytes at `captures/committed/<dispatch-id>.json` and fsync the directory. Validate every path through directory-relative no-follow operations.

Result parsing is not part of `ExecutionCapture`. `dispatch_observed` classification reads only the committed closure and retained stdout/candidate bytes.

- [ ] **Step 5: Run execution and legacy candidate suites**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_execution.py tests/unit/test_re_v2_candidates.py`

Expected: all tests pass; protocol-2.2 records are isolated from the legacy candidate schema.

- [ ] **Step 6: Commit durable execution capture**

```bash
git add src/harness/re_v2/protocol_22/execution.py \
  tests/unit/test_re_v2_protocol_22_execution.py
git commit -m "feat(re-v2): commit durable execution captures"
```

---

### Task 16: Four-Case Recovery and Orphan-Authority Reconciliation

**Files:**
- Create: `src/harness/re_v2/protocol_22/recovery.py`
- Create: `tests/unit/test_re_v2_protocol_22_recovery.py`
- Create: `tests/integration/test_re_v2_protocol_22_recovery.py`
- Test: `tests/unit/test_re_v2_recovery.py`

**Interfaces:**
- Produces: `Protocol22RunContext` containing immutable inputs, graph, stores, installed authorities, executors, producers, and verifiers.
- Produces: `recover_protocol_22_run(context, fault_hook=None) -> Protocol22RecoveryResult`.
- Produces: non-mutating `PinnedAuthorityUnavailable` with every expected/installed digest mismatch.
- Produces: `Protocol22RecoveryResult(manifest, inputs, graph, events, ledger, budget, dispatch_actions, operational_state)`.
- Enforces: the four exact dispatch cases and receipt-before-event recovery from the design.

- [ ] **Step 1: Write RED tests for all four dispatch states**

```python
@pytest.mark.parametrize(
    ("started", "staging", "committed", "expected_action", "provider_calls"),
    (
        (False, False, False, "prepared", 0),
        (True, False, True, "adopt_committed", 0),
        (True, True, False, "finish_commit", 0),
        (True, False, False, "abandon", 0),
    ),
)
def test_recovery_never_reissues_started_dispatch(
    started: bool, staging: bool, committed: bool, expected_action: str, provider_calls: int
) -> None:
    fixture = interrupted_dispatch(started=started, staging=staging, committed=committed)
    result = recover_protocol_22_run(fixture.context)
    assert result.dispatch_actions[fixture.dispatch_id] == expected_action
    assert fixture.provider.calls == provider_calls
```

Cover a matching live owner, conflicting commit, corrupt capture/object/stdout/usage/candidate, incomplete staging, orphan certification/candidate assessment/acceptance/item-failure/executor-failure receipts, reconstruction event recovery, idempotent repeated recovery, and failure before any provider call.

- [ ] **Step 2: Write RED pinned-authority non-mutation tests**

Capture byte hashes of run manifest, inputs, events, ledger, candidates, captures, and materialization; mutate one installed digest; call recovery/status; assert an unavailable result, zero provider calls, and identical authority bytes. Restore the exact registry and assert the same run becomes ready without migration.

- [ ] **Step 3: Run recovery tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_recovery.py tests/integration/test_re_v2_protocol_22_recovery.py`

Expected: new imports fail.

- [ ] **Step 4: Implement authority-first recovery and the state table**

Validate manifest, catalogs, object references, snapshot, graph, installed authority, event chain, ledger chain, capture commits, candidates, and materialization in that order. Only then reconcile missing transitions. A started dispatch without complete capture authority and without a live owner gets exactly one `dispatch_abandoned`, full reservations charged, and a new dispatch ID only if provider result retry plus shared retry remain.

- [ ] **Step 5: Implement orphan receipt/event completion**

For each orphan receipt, validate it against immutable work/executor/capture/final-attempt facts before appending its one matching event. Reject premature or conflicting authority. Never infer a schema-2 field into schema-1 history, reopen a failed item, convert failure to budget pause, or treat unknown usage as zero.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_recovery.py tests/integration/test_re_v2_protocol_22_recovery.py tests/unit/test_re_v2_recovery.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass.

- [ ] **Step 6: Commit deterministic protocol-2.2 recovery**

```bash
git add src/harness/re_v2/protocol_22/recovery.py \
  tests/unit/test_re_v2_protocol_22_recovery.py \
  tests/integration/test_re_v2_protocol_22_recovery.py
git commit -m "feat(re-v2): recover protocol 2.2 dispatch authority"
```

---

### Task 17: Protocol-2.2 Controller, Retry Classification, and Fixed-Point Failure Isolation

**Files:**
- Create: `src/harness/re_v2/protocol_22/controller.py`
- Create: `tests/unit/test_re_v2_protocol_22_controller.py`
- Create: `tests/integration/test_re_v2_protocol_22_controller.py`
- Test: `tests/unit/test_re_v2_controller.py`

**Interfaces:**
- Produces: `Protocol22Controller(context, fault_hook: FaultHook | None = None).run_until_stopped() -> Protocol22ControllerResult`.
- Enforces: one ready item/dispatch at a time, durable ordering, result reconstruction, one shared retry, exact item/executor failure receipts, independent sibling progress, and terminal fixed point.
- Consumes: pure producers/certifiers and bounded provider adapter through registered protocol interfaces.

- [ ] **Step 1: Write RED deterministic/provider happy-path tests**

Use real stores and fake only the external API boundary. Assert every deterministic node follows `execution input -> dispatch_started -> committed capture -> dispatch_observed -> certification -> acceptance`; provider nodes additionally follow `candidate_persisted -> candidate assessment -> candidate outcome -> acceptance`.

```python
def test_valid_candidate_with_bad_result_is_reconstructed_without_retry(context: Protocol22RunContext) -> None:
    context.provider.script(candidate=valid_domain_candidate(), stdout=b"malformed\n")
    result = Protocol22Controller(context).run_until_stopped()
    assert event_count(result.events, "result_contract_reconstructed") == 1
    assert context.provider.calls == 1
    assert event_count(result.events, "artifact_accepted") == 1
```

- [ ] **Step 2: Write RED retry/failure isolation tests**

Parameterize: unrecoverable result then success; invalid artifact then success; two failures of either one retry kind; minimum utility twice; abandoned execution with/without retry; deterministic exception; deterministic invalid artifact; reservation mismatch; usage overflow; one bad domain with good sibling domains/sources; and one executor breach shared by multiple unresolved provider items.

Assert no item consumes both retry kinds, no item exceeds two provider calls, budget increases cannot reopen failed work, accepted siblings persist, executor failure blocks only its exact contract and downstream closure, and `run_failed` appears only at fixed point.

- [ ] **Step 3: Run controller tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_controller.py tests/integration/test_re_v2_protocol_22_controller.py`

Expected: protocol-2.2 controller imports fail.

- [ ] **Step 4: Implement the durable dispatch transaction**

Under the exclusive run lock: recover; plan; select the first stable ready item; verify authorities; prepare immutable input; compute and check both reservations; lease; append `dispatch_started`; execute once; durably capture; append observation; then classify/certify. Fsync every receipt before its event and every acceptance receipt before `artifact_accepted`.

For a valid one-file strict candidate plus invalid result block, persist `result_contract_reconstructed` and certify without a call. For invalid candidate after a valid/reconstructed result, issue only `artifact_contract_retry` with identical context plus normalized diagnostics. A safety breach persists forensic candidate/capture but never certifies it.

- [ ] **Step 5: Implement fixed-point continuation and terminal summary**

Continue independent ready items after item/executor failure. Pause only when an otherwise dispatchable item's exact token or active reservation exceeds remaining authorization. Emit `run_completed` only when every requested node is accepted; emit `run_failed` only when no safe ready or budget-paused work remains and required failure/blocked state exists.

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_controller.py tests/integration/test_re_v2_protocol_22_controller.py tests/unit/test_re_v2_controller.py`

Expected: all tests pass; schema-1 controller behavior remains unchanged.

- [ ] **Step 6: Commit the layered controller**

```bash
git add src/harness/re_v2/protocol_22/controller.py \
  tests/unit/test_re_v2_protocol_22_controller.py \
  tests/integration/test_re_v2_protocol_22_controller.py
git commit -m "feat(re-v2): execute bounded layered baseline graph"
```

---

### Task 18: Run-Local Materialization, Quarantine, Status, and Banners

**Files:**
- Create: `src/harness/re_v2/protocol_22/materialization.py`
- Create: `src/harness/re_v2/protocol_22/status.py`
- Create: `tests/unit/test_re_v2_protocol_22_materialization.py`
- Create: `tests/unit/test_re_v2_protocol_22_status.py`
- Modify: `src/harness/re_v2/status.py`
- Test: `tests/unit/test_re_v2_status.py`

**Interfaces:**
- Produces: `materialize_accepted_l1(context, fault_hook: FaultHook | None = None) -> MaterializationReportV1` with no-clobber JSON/Markdown/root projections.
- Produces: `validate_or_repair_materialization(context, fault_hook: FaultHook | None = None) -> MaterializationReportV1`, quarantining altered safe entries before rebuild.
- Produces: `render_protocol_22_status(run_dir, as_json=False) -> str` and `protocol_22_status_document() -> Mapping[str, object]`.
- Modifies: `render_v2_status()` to select legacy or 2.2 renderer from immutable manifest protocol.

- [ ] **Step 1: Write RED materialization integrity tests**

```python
def test_missing_materialization_rebuilds_from_object_authority(context: Protocol22RunContext) -> None:
    expected = materialize_accepted_l1(context)
    shutil.rmtree(expected.paths[0])
    repaired = validate_or_repair_materialization(context)
    assert repaired.rebuilt_count == 1
    assert hash_materialized(repaired.paths[0]) == expected.hashes[0]


def test_corrupt_projection_is_quarantined_before_rebuild(context: Protocol22RunContext) -> None:
    path = materialize_accepted_l1(context).paths[0]
    (path / "baseline.md").write_text("corrupt\n", encoding="utf-8")
    report = validate_or_repair_materialization(context)
    assert report.quarantined_count == 1
    assert report.rebuilt_count == 1
```

Cover domain presentation paths, hash-suffix paths, root file, immutable reuse, symlink/special/traversal failure, quarantine failure, fault after quarantine/before publish, and proof that workspace `re/` remains absent.

- [ ] **Step 2: Write RED status/banner tests**

Assert exact complete, budget pause, pinned-authority unavailable, and terminal-failure banners. JSON must expose required/accepted counts per kind/source/domain, all graph failure classes/receipt IDs, exact root hashes/paths, rational coverage, debt, surfaces, utility, context estimates, token/time authorization/charges/reservations, trusted/unknown telemetry, capture/staging/abandonment/reconstruction counts, and the four explicit not-run depth/audit/synthesis/full-RE statements.

- [ ] **Step 3: Run materialization/status tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_materialization.py tests/unit/test_re_v2_protocol_22_status.py`

Expected: new modules are missing.

- [ ] **Step 4: Implement safe immutable projection and read-only status**

Read accepted objects through the verified object store. Publish JSON and deterministic Markdown under the exact paths from the design using same-directory staging plus no-clobber rename/link and directory fsync. Validate with no-follow directory descriptors. Move altered safe entries to `v2/quarantine/materialized/<unique-id>`; never delete them.

Status may validate installed digests but must not require executing them. A terminal run retains its event outcome and reports authority drift as a warning. An unresolved authority mismatch returns unavailable without writing any event.

- [ ] **Step 5: Prove legacy renderer and wording remain isolated**

Run: `.venv/bin/pytest -q tests/unit/test_re_v2_protocol_22_materialization.py tests/unit/test_re_v2_protocol_22_status.py tests/unit/test_re_v2_status.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all tests pass; protocol 2.0/2.1 output tests are unchanged.

- [ ] **Step 6: Commit materialization and unambiguous status**

```bash
git add src/harness/re_v2/protocol_22/materialization.py \
  src/harness/re_v2/protocol_22/status.py src/harness/re_v2/status.py \
  tests/unit/test_re_v2_protocol_22_materialization.py \
  tests/unit/test_re_v2_protocol_22_status.py tests/unit/test_re_v2_status.py
git commit -m "feat(re-v2): expose compact baseline status and projections"
```

---

### Task 19: CLI Goal Selection, Atomic Creation, Shadow Costing, and Continuation

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Create: `tests/support/re_v2_cli_workspace.py`
- Create: `tests/unit/test_cli_re_v2_protocol_22.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Produces: `echelon re run --engine v2 [--goal baseline|inventory] [--shadow]` with baseline as the v2 default.
- Produces: protocol-selected `_re_v2_context()` returning legacy `ReV2RunContext` for 2.0/2.1 or `Protocol22RunContext` for 2.2.
- Produces: test-only `CliWorkspaceProbe` and `create_cli_workspace(tmp_path, llm_cli)` for clean-Git CLI mutation assertions.
- Preserves: v1 option parsing/defaults and existing 2.0/2.1 continuation.
- Enforces: `re continue` may raise only run-wide token/active-time authorization for an existing 2.2 run.

- [ ] **Step 1: Write RED CLI option and pre-publication failure tests**

```python
def test_v2_defaults_to_baseline_and_inventory_is_explicit(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    goals: list[str] = []

    def fake_create(project_root: Path, *, token_limit: int | None,
                    time_limit_minutes: int | None, shadow: bool, goal: str) -> None:
        goals.append(goal)

    monkeypatch.setattr(legacy_cli, "_run_re_v2_create", fake_create)
    assert runner.invoke(app, ["re", "run", "--engine", "v2", "--shadow"]).exit_code == 0
    assert runner.invoke(app, ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"]).exit_code == 0
    assert goals == ["baseline", "inventory"]


def test_ineligible_provider_changes_neither_run_nor_active_pointer(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.chdir(probe.root)
    before = probe.active_pointer_bytes()
    result = runner.invoke(app, ["re", "run", "--engine", "v2"])
    assert result.exit_code == 2
    assert "bounded-api-baseline-v1" in result.stderr
    assert probe.active_pointer_bytes() == before
    assert probe.run_directories() == ()
```

Cover `--goal` with v1, duplicate/unknown goal, goal on continue, v1-only policy/reset/reuse/profile/max-inner options with v2, inventory without provider config, baseline unsupported CLI, missing agent/schema authority, dirty source, catalog failure, shadow zero calls, and active pointer only after durable manifest.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py`

Expected: new goal/context assertions fail.

- [ ] **Step 3: Implement creation in the required authority order**

For protocol 2.2:

1. discover workspace and preflight all declared Git sources;
2. capture/validate the composite snapshot;
3. build the partition and artifact-policy catalogs;
4. load the exact neutral agent and response schemas;
5. resolve/validate executor contracts and all installed digests;
6. build/validate the complete graph and selected budget policy;
7. persist objects/catalogs and publish the manifest last; and
8. atomically update `.current-re` only after durable creation.

Any failure through step 6 creates no run directory or active-pointer change. A storage crash after unique `v2/` creation remains an explicit incomplete store and is never routed to v1.

- [ ] **Step 4: Implement protocol-selected execution and continuation**

Load the immutable manifest first. Schema 1 follows the existing context/controller unchanged. Schema 2 loads validated inputs, graph, stores, registry, deterministic producers, certifiers, and the bounded adapter. Continuation rejects executor/policy/goal changes and terminal budget authorization; a paused run accepts only strictly higher token/time ceilings.

- [ ] **Step 5: Implement exact shadow counts and worst-case reservations**

Shadow must show deterministic/provider initial counts, maximum shared retries, each constructible context size/conservative estimate, worst-case overview bounds, per-dispatch hard limits, whole-run initial/retry token and active reservations, authorized ceilings, and an explicit insufficient-authorization warning. It must issue zero provider requests.

Run: `.venv/bin/pytest -q tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py tests/integration/test_re_v2_v1_isolation.py`

Expected: all tests pass and v1 CLI isolation remains intact.

- [ ] **Step 6: Commit the protocol-2.2 CLI path**

```bash
git add src/echelon/cli.py src/echelon/cli_app.py \
  tests/support/re_v2_cli_workspace.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_typer_app.py
git commit -m "feat(re-v2): expose bounded baseline goal"
```

---

### Task 20: Live Fixtures, Crash Matrix, Compatibility Gate, and Finding Closure

**Files:**
- Create: `tests/support/re_v2_layered_workspace.py`
- Create: `tests/integration/test_re_v2_protocol_22_live.py`
- Create: `tests/integration/test_re_v2_protocol_22_failures.py`
- Create: `tests/integration/test_re_v2_protocol_22_large_source.py`
- Modify: `tests/integration/test_re_v2_protocol_22_recovery.py`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: clean temporary Git workspaces for multi-source success, one permanently invalid domain, executor breach, and large/pathological evidence.
- Produces: a loopback bounded-API fixture with scripted per-work-item responses and exact call telemetry.
- Produces: `build_and_commit_fixture(tmp_path: Path, scenario: str) -> LayeredWorkspaceFixture`, implemented in `tests/support/re_v2_layered_workspace.py` with one concrete builder for each accepted scenario.
- Verifies: all 46 acceptance-matrix items and the EGR-165 completion criteria before marking the finding fixed.

- [ ] **Step 1: Build real clean-Git fixture workspaces at test runtime**

The support builder must initialize repositories with local fixture identity, write/commit source files, configure the bounded loopback API, and return source/domain expectations. Generate binary, invalid-UTF-8, NUL, CRLF, unterminated, and pathological long-line bytes inside the temporary repository so no checked-in binary fixture or mutable external workspace is required.

```python
@dataclass(frozen=True)
class LayeredWorkspaceFixture:
    root: Path
    source_domains: Mapping[str, tuple[str, ...]]
    api: ScriptedBoundedApi


def create_layered_workspace(tmp_path: Path, scenario: str) -> LayeredWorkspaceFixture:
    if scenario not in {"complete", "invalid-domain", "executor-breach", "large-source"}:
        raise ValueError(f"unknown fixture scenario: {scenario}")
    return build_and_commit_fixture(tmp_path, scenario)
```

- [ ] **Step 2: Add the live multi-source completion proof**

Run `echelon re run --engine v2` through the real CLI/controller against the loopback server. Assert independently accepted minimum-utility domain baselines, source overviews, exact source roots, materialized JSON/Markdown, `L1 COMPACT BASELINE COMPLETE`, one initial call per provider work item, no `re/` writes, and explicit not-run audit/synthesis/deepening/exhaustive statements.

- [ ] **Step 3: Add terminal failure and executor fan-out proofs**

For one permanently invalid domain, assert every independent domain/source completes, its overview/root closure is dependency-blocked, and final counts/reasons/receipt IDs are exact. For an executor usage breach, assert the trigger is failed, unresolved same-contract work is executor-blocked, deterministic independent work completes, no breaching candidate is accepted, and budget continuation cannot reopen any failed/blocked item.

- [ ] **Step 4: Add large-source cost/debt and retry-bound proof**

Assert deterministic evidence/debt across restart, source/domain/context/request caps, direct/projected/combined rational coverage, shadow initial/retry maximums, unknown usage reservation charging, malformed-result reconstruction without another call, and at most two calls for every provider work item.

- [ ] **Step 5: Expand fault injection across every durable boundary**

Parameterize faults after: catalog object; catalog file; manifest temporary; manifest link; provider envelope; execution input; dispatch start; candidate blob; candidate inventory; stdout blob; usage blob; execution capture; staging ready; capture commit; observed event; reconstruction event; deterministic certification; candidate assessment; certification event; artifact acceptance receipt; artifact event; item failure receipt; executor failure receipt; failure event; quarantine move; materialized JSON; and materialized Markdown. Restart twice after each fault and assert byte-identical converged authority, no duplicate counters/events/receipts, and no reissue of a started dispatch.

- [ ] **Step 6: Run the focused protocol-2.2 acceptance gate**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_re_v2_protocol_22_*.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/contract/test_re_v2_bounded_api.py \
  tests/integration/test_re_v2_protocol_22_*.py
```

Expected: all tests pass with zero external provider/network dependency.

- [ ] **Step 7: Run legacy isolation and the complete repository gate**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_re_v2_*.py \
  tests/integration/test_re_v2_kernel_recovery.py \
  tests/integration/test_re_v2_v1_isolation.py
bash scripts/bash/dry-run.sh
.venv/bin/pytest -q
git diff --check
```

Expected: every command exits zero. Protocol 2.0/2.1 golden identities, events, ledger, continuation, status, and v1 dispatch/publication remain unchanged.

- [ ] **Step 8: Install and smoke the packaged CLI/bundle**

Run:

```bash
bash scripts/install.sh
echelon version
```

Create a fresh temporary fixture with the support builder, migrate/install its Echelon bundle through the normal workspace command, run v2 inventory shadow and the bounded loopback baseline, and assert the installed CLI sees `echelon.re-baseliner` plus the same complete banner/status as the source-tree tests.

- [ ] **Step 9: Record only the capability actually completed**

Update `CHANGELOG.md` under Unreleased with protocol 2.2 scoped L0/L1, bounded adapter, recovery, materialization, and compatibility. Mark EGR-165 fixed with test/commit evidence while stating v2 remains opt-in and EGR-166 through EGR-170 are still required for adoption, semantic audit, synthesis, selective depth, and atomic repair/full-quality cutover.

- [ ] **Step 10: Commit the completion gate and finding closure**

```bash
git add tests/support/re_v2_layered_workspace.py \
  tests/integration/test_re_v2_protocol_22_live.py \
  tests/integration/test_re_v2_protocol_22_failures.py \
  tests/integration/test_re_v2_protocol_22_large_source.py \
  tests/integration/test_re_v2_protocol_22_recovery.py \
  docs/findings/echelon-grounded-review-register.md CHANGELOG.md
git commit -m "test(re-v2): prove layered compact baseline completion"
```

## Acceptance-Matrix Coverage Map

| Design checks | Owning tasks |
|---|---|
| 1, legacy byte compatibility | 1, 12, 13, 18, 19, 20 |
| 2-11, scoped/content/partition identity and invalidation | 2, 3, 4, 7, 8 |
| 12, closed schemas and canonical restart stability | 2, 3, 5, 8-16 |
| 13-16, evidence selection/context projection/debt | 8, 9, 10 |
| 17-19, stable roots/acceptance and execution-independent keys | 7, 10, 11, 13 |
| 20-22, pinned executor, default goal, shadow and preflight bounds | 5, 6, 7, 14, 19, 20 |
| 23-30, authorial contract/evidence/coverage/Markdown | 9, 10, 11, 18 |
| 31-33, retry exhaustion and item/executor failure isolation | 12, 13, 16, 17 |
| 34-37, reservations, deadlines, capture and crash semantics | 12, 14, 15, 16, 17 |
| 38-39, quarantine, status and banners | 18, 19 |
| 40-43, live multi-source/invalid/large/v1 fixtures | 20 |
| 44, policy branch closure and hash sensitivity | 3 |
| 45, stdout/capture commit authority | 15, 16 |
| 46, shared certification with distinct candidate provenance | 11, 13, 20 |

## Implementation Checkpoints

- After Task 6, schema-2 manifests/catalogs can be built and rejected safely, but no 2.2 run is executable.
- After Task 11, every deterministic/provider artifact byte and certification decision is pure and testable without a live controller.
- After Task 15, a bounded external call has complete immutable request/capture authority, but interruption semantics are not claimed until Task 16.
- After Task 18, the kernel can execute, recover, materialize, and explain protocol 2.2 through internal APIs.
- EGR-165 is not complete until Tasks 19 and 20 pass through the installed CLI and the finding register is updated with evidence.
