# RE v2 Deferred Workspace Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship protocol 2.7 as an explicit `echelon re synthesize --from-run <run-id>` child workflow that incrementally composes and atomically publishes workspace RE artifacts from accepted complete or source-specifically accepted partial inputs.

**Architecture:** Add a focused `harness.re_v2.protocol_27` package over protocol-2.6 accepted-root reconstruction and the existing canonical object, durable event/ledger, Prosaic/provider, accounting, materialization-safety, and publication primitives. Schema 6 freezes exact source outcomes, partial-acceptance receipts, granular synthesis work, independent resources, and publication CAS authority; source, workspace-domain, and workspace artifacts are independently accepted and adoptable before one controller-generated synthesis root and publication descriptor close the graph.

**Tech Stack:** Python 3.11+, standard-library dataclasses/json/fcntl/os/pathlib/tempfile, existing RE v2 canonical JSON/content digests/object stores/event chains/durable ledgers, existing Prosaic metadata and `SquadCliProvider` execution path, pytest, and Git-backed installed-workspace Codex tests.

**Spec:** `docs/superpowers/specs/2026-08-28-re-v2-deferred-workspace-synthesis-design.md`

## Global Constraints

- Protocol 2.7 uses run schema 6. Protocols 2.2/2.3 retain schema 2, protocol 2.4 retains schema 3, protocol 2.5 retains schema 4, and protocol 2.6 retains schema 5 with byte-identical canonical fixtures and continuation behavior.
- Do not modify implementation bodies under `src/harness/re_v2/protocol_22/`, `protocol_24/`, `protocol_25/`, or `protocol_26/`. Import their public helpers and compose new behavior under `protocol_27`.
- Synthesis is an explicit child. Baseline, L2, L3, and future L4 completion never dispatch synthesis automatically.
- Every selected source must have authenticated terminal accepted-root authority. Complete sources need no operator receipt; every partial source needs one exact `PartialSourceAcceptanceV1` bound to its source root and debt manifest.
- A global `--allow-partial` remains v1-only. V2 uses repeated `--accept-partial <source-id>` and fails before run creation when any acceptance is missing, extra, duplicate, stale, or mismatched.
- Accepted lower-layer source overviews are never regenerated. Their existing canonical layer materialization supplies public overview bytes.
- Synthesis artifacts use a protocol-2.7 synthesis namespace, not L3 or L4. Do not extend or reinterpret the L0-to-L4 analysis-layer chain.
- Source-local, workspace-domain, and workspace-wide artifacts have exact dependency-keyed identities. Run IDs, timestamps, origins, discovery order, and provider attempt IDs never enter reusable identity.
- Partial debt identities are controller authority. Model prose cannot remove, resolve, or downgrade them, and partial-input synthesis cannot claim full RE quality.
- Each missing synthesis work item permits one initial provider dispatch and at most one contract-repair dispatch. There is no broad synthesis rewrite or shared unbounded retry pool.
- Synthesis token and active-time limits are independent of lower-layer and semantic budgets. Adopted work consumes no attempt, retry, token, or active-time budget.
- All model work loads `echelon.re-synthesizer` through Prosaic and uses the existing shared provider resolution/model/effort/execution/telemetry path. Because the frozen baseline renderer accepts only protocol-2.2 `ContextBundleV1`, compose a protocol-2.7 synthesis request renderer using the established protocol-2.5 pattern; it validates synthesis context and delegates to `SquadCliProvider`. Add no provider adapter, direct API request, credential branch, model map, or provider-specific result contract.
- Provider context comes only from authenticated child objects and accepted projections. Live source repositories and mutable workspace publication are forbidden read roots.
- Publication occurs only after the required closure and materialization validate. It uses the existing immutable generation/index CAS primitive without modifying its schemas.
- `synthesis_status`, `input_quality`, and `publication_status` remain orthogonal. Complete synthesis over partial inputs is successful but never full quality.
- The child is self-contained before activation. Continuation and re-export must work after parent/origin runs and the disposable checkpoint cache are removed.
- Existing public paths under `re/sources/<source-id>/{overview,architecture,contracts,components}.md`, `re/workspace/{overview,relationships,contracts}.md`, and `re/workspace/domains/<domain-id>.md` remain the downstream compatibility contract.
- No new third-party runtime dependency is introduced.

## File Structure

Create one protocol-2.7 package with one authority boundary per file:

```text
src/harness/re_v2/protocol_27/
  __init__.py          protocol/schema constants and public exports
  model.py             schema-6, source outcome, acceptance, key, root, descriptor models
  authority.py         stable parent/source-root resolution and partial acceptance
  policies.py          synthesis work kinds, producer/executor/verifier/policy catalogs
  graph.py             deterministic topology and granular synthesis dependency graph
  inputs.py            manifest-last self-contained child publication and loading
  schemas.py           closed response schemas for each synthesis artifact kind
  context.py           bounded authenticated per-work-item evidence packs
  runtime.py           strict candidate normalization, validation, and certification
  ledger.py            synthesis receipts over the existing durable ledger envelope
  events.py            protocol-2.7 event validation and replay
  budget.py            independent synthesis resource and attempt accounting
  checkpoints.py       synthesis checkpoint reconstruction, selection, copy, and adoption
  execution.py         thin Prosaic/shared-provider capture composition
  controller.py        deterministic ready-work planner and bounded lifecycle
  recovery.py          durable-boundary reconciliation and no-duplicate-dispatch recovery
  materialization.py   run-local compatibility projections and deterministic rebuild
  publication.py       publication descriptor and existing generation CAS composition
  lifecycle.py         exact child reuse, creation, initialization, and execution entrypoint
  status.py            machine status, telemetry, banners, and exact next actions
```

Add neutral Prosaic authority:

```text
prosaic/subagents/echelon.re-synthesizer.md
```

Add tests at the same boundaries:

```text
tests/re_v2_protocol_27_fixtures.py
tests/unit/test_re_v2_protocol_27_model.py
tests/unit/test_re_v2_protocol_27_authority.py
tests/unit/test_re_v2_protocol_27_policies.py
tests/unit/test_re_v2_protocol_27_graph.py
tests/unit/test_re_v2_protocol_27_inputs.py
tests/unit/test_re_v2_protocol_27_schemas.py
tests/unit/test_re_v2_protocol_27_context.py
tests/unit/test_re_v2_protocol_27_runtime.py
tests/unit/test_re_v2_protocol_27_ledger.py
tests/unit/test_re_v2_protocol_27_events.py
tests/unit/test_re_v2_protocol_27_budget.py
tests/unit/test_re_v2_protocol_27_checkpoints.py
tests/unit/test_re_v2_protocol_27_execution.py
tests/unit/test_re_v2_protocol_27_controller.py
tests/unit/test_re_v2_protocol_27_materialization.py
tests/unit/test_re_v2_protocol_27_publication.py
tests/unit/test_re_v2_protocol_27_status.py
tests/unit/test_cli_re_v2_protocol_27.py
tests/integration/test_re_v2_protocol_27_recovery.py
tests/integration/test_re_v2_protocol_27_cli.py
tests/integration/test_re_v2_protocol_27_downstream.py
tests/integration/test_re_v2_protocol_27_live.py
```

Modify only additive routers, downstream schema-neutral seams, and release docs:

```text
src/harness/re_v2/model.py
src/harness/re_v2/run_store.py
src/harness/re_v2/status.py
src/harness/re_publication.py
src/harness/re_registry.py
src/echelon/cli.py
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
docs/superpowers/specs/2026-08-28-re-v2-deferred-workspace-synthesis-design.md
```

Before editing any shared file, run the installed-authority inventory in Task 1. If a planned shared file enters a frozen implementation digest, keep the extension entirely behind protocol-2.7 dispatch instead.

---

### Task 1: Freeze Compatibility and Register Closed Schema-6 Models

**Files:**
- Create: `src/harness/re_v2/protocol_27/__init__.py`
- Create: `src/harness/re_v2/protocol_27/model.py`
- Create: `tests/re_v2_protocol_27_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_27_model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces `AcceptedSourceOutcomeV1(source_id, source_root_key_id, source_root_hash, outcome, debt_manifest_hash, lower_authority_ids)` where `outcome` is exactly `complete` or `partial` and only partial outcomes carry debt.
- Produces `PartialSourceAcceptanceV1(schema_version, parent_run_id, parent_manifest_hash, source_id, source_root_key_id, source_root_hash, debt_manifest_hash, debt_summary_hash, operation_id)` with `.receipt_id` and canonical round-trip methods.
- Produces `AcceptedSourceOverviewProjectionV1(source_id, selected_layer, source_root_key_id, source_root_hash, materializer_protocol_version, materializer_authority_hash, content_hash, object_hash)` and `AcceptedSourceOverviewCatalogV1` so exact canonical Markdown bytes become child-owned authority.
- Produces `SynthesisRequestV1(parent_manifest_hash, accepted_source_outcome_ids, accepted_partial_source_ids, budget_policy_hash, expected_v2_index_hash, expected_compatibility_generation)` with deterministic `.request_id`; partial receipts use this ID as `operation_id` and repeated invocations do not mint a fresh identity.
- Produces `SynthesisScopeV1(kind, source_id, workspace_domain_id, participant_ids)` for exact `source`, `workspace-domain`, and `workspace` cardinalities.
- Produces `SynthesisArtifactKeyV1`, `SynthesisWorkTemplateV1`, and `SynthesisWorkItemV1` as closed canonical identities with exact sorted artifact and non-artifact dependencies.
- Produces `SynthesisBudgetPolicyV1(token_limit, active_ms_limit, provider_attempt_limit=2, generation_attempt_limit=2, result_contract_retry_limit=1, artifact_contract_retry_limit=1)` and rejects every other fixed attempt tuple.
- Produces `SynthesisRootV1` and `PublicationDescriptorV1` with authenticated `input_quality`; the descriptor binds the exact compatibility generation and staged index hash without the compatibility index referring back to the descriptor.
- Produces `RunManifestV6` pinned to schema 6, protocol 2.7, goal `workspace-synthesis`, exact parent/source/acceptance/catalog/policy/Prosaic/budget/checkpoint authority, expected v2 index hash, and expected compatibility generation.
- `RunManifestV6.input_authority_catalog_id` binds the exact closed-role object
  closure that was staged before manifest publication; later execution objects
  may coexist but cannot be mistaken for immutable creation inputs.
- Extends `run_store.Manifest`, `_decode_manifest()`, and `_validate_supported_manifest()` only for `(6, "2.7")`.

- [ ] **Step 1: Record frozen compatibility before editing**

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
git diff --exit-code -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24 src/harness/re_v2/protocol_25 src/harness/re_v2/protocol_26
rg -n "_re_schema2_installed_registry|_re_v22_implementation_digest|implementation_digest" src/echelon/cli.py src/harness/re_v2
```

Expected: tests pass; protocol directories are clean; planned router files are not part of a frozen implementation digest.

- [ ] **Step 2: Write failing canonical model and run-store tests**

```python
def test_manifest_v6_round_trips_exact_protocol() -> None:
    manifest = manifest_v6()
    payload = canonical_json_bytes(manifest.to_json_dict())
    assert RunManifestV6.from_json_dict(json.loads(payload)) == manifest
    assert manifest.run_manifest_id == content_digest(payload)


def test_partial_source_requires_exact_acceptance() -> None:
    raw = accepted_source_outcome_v1(outcome="partial").to_json_dict()
    raw["debt_manifest_hash"] = None
    with pytest.raises(Protocol27SchemaError, match="partial.*debt"):
        AcceptedSourceOutcomeV1.from_json_dict(raw)


def test_run_store_rejects_schema_6_with_protocol_2_6(tmp_path: Path) -> None:
    raw = manifest_v6().to_json_dict()
    raw["engine_protocol_version"] = "2.6"
    write_manifest(tmp_path, raw)
    with pytest.raises(ReV2RunStoreError, match="schema/protocol"):
        load_run_manifest(tmp_path)
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_model.py tests/unit/test_re_v2_run_store.py`

Expected: collection fails because `protocol_27` and `RunManifestV6` do not exist.

- [ ] **Step 4: Implement closed canonical models**

```python
@dataclass(frozen=True, slots=True)
class SynthesisArtifactKeyV1:
    identity_schema_version: int
    scope: SynthesisScopeV1
    artifact_kind: str
    producer_protocol_version: str
    synthesis_policy_hash: str
    response_schema_hash: str
    context_policy_hash: str
    artifact_dependencies: tuple[SynthesisArtifactDependencyV1, ...]
    non_artifact_dependency_hashes: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]

    @property
    def artifact_key_id(self) -> str:
        return content_digest(self.to_json_dict())


@dataclass(frozen=True, slots=True)
class RunManifestV6:
    schema_version: Literal[6]
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.7"]
    goal: Literal["workspace-synthesis"]
    run_id: str
    created_at: str
    request_id: str
    parent_run_id: str
    parent_manifest_hash: str
    source_snapshot_id: str
    partition_manifest_id: str
    accepted_sources: tuple[AcceptedSourceOutcomeV1, ...]
    source_overview_catalog_id: str
    partial_acceptances: tuple[PartialSourceAcceptanceV1, ...]
    synthesis_graph_id: str
    synthesis_policy_hash: str
    prosaic_authority_hash: str
    budget_policy: SynthesisBudgetPolicyV1
    checkpoint_selection_id: str
    expected_v2_index_hash: str
    expected_compatibility_generation: int
```

Use the existing protocol-2.2 schema helpers for safe IDs, digests, canonical ordering, exact fields, and content identity. Do not import or edit private validation tables in frozen protocol modules.

- [ ] **Step 5: Add schema-6 run-store dispatch and rejection matrix**

Add exact `(schema_version, engine_protocol_version)` routing and tests for wrong schema, protocol, engine, goal, duplicate source IDs, noncanonical ordering, extra fields, missing partial receipts, and extra complete-source receipts.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: PASS with all older canonical fixture hashes unchanged.

- [ ] **Step 6: Commit the schema boundary**

```bash
git add src/harness/re_v2/protocol_27 src/harness/re_v2/model.py src/harness/re_v2/run_store.py tests/re_v2_protocol_27_fixtures.py tests/unit/test_re_v2_protocol_27_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py
git commit -m "feat(re-v2): register protocol 2.7 synthesis authority"
```

---

### Task 2: Resolve Terminal Source Authority and Exact Partial Acceptance

**Files:**
- Create: `src/harness/re_v2/protocol_27/authority.py`
- Create: `src/harness/re_v2/protocol_27/lifecycle.py`
- Create: `tests/unit/test_re_v2_protocol_27_authority.py`
- Create: `tests/unit/test_cli_re_v2_protocol_27.py`
- Modify: `src/echelon/cli.py`

**Interfaces:**
- Produces `_ReSynthesizeV2Options(from_run, accepted_partial_sources, token_limit, active_ms_limit)` and `_parse_re_synthesize_v2_options(args)` using existing `--from-run`, `--token-limit`, and `--active-ms-limit` conventions.
- Produces `ResolvedSynthesisParentV1(parent_run_id, parent_manifest_hash, source_snapshot_id, partition_manifest_id, accepted_sources, authority_objects)`.
- `resolve_synthesis_parent(workspace_root: Path, from_run: str, accepted_partial_sources: tuple[str, ...]) -> ResolvedSynthesisParentV1` uses stable manifest/event/ledger replay and protocol-2.6 source authority, either directly from a protocol-2.6 child or from the embedded authority of a terminal protocol-2.7 child; it never reads mutable status banners or live source trees.
- `partial_acceptance_for(parent, source_id) -> PartialSourceAcceptanceV1` binds the exact debt-bearing outcome.
- `freeze_accepted_source_overviews(parent) -> AcceptedSourceOverviewCatalogV1` invokes the selected layer's existing public L1/L2/L3 materializer, verifies each source projection against accepted source-root authority, and returns exact bytes plus typed projection records for child staging.
- `find_exact_protocol_27_child(workspace_root, request_id) -> Path | None` enables exact zero-call request reuse.

- [ ] **Step 1: Write failing CLI and authority tests**

```python
def test_v2_synthesis_requires_every_partial_source_explicitly(tmp_path: Path) -> None:
    parent = completed_protocol_26_parent(tmp_path, partial_sources=("api", "web"))
    with pytest.raises(Protocol27AuthorityError, match="missing partial acceptance: web"):
        resolve_synthesis_parent(tmp_path, parent.name, ("api",))


def test_v2_synthesis_rejects_acceptance_for_complete_source(tmp_path: Path) -> None:
    parent = completed_protocol_26_parent(tmp_path, complete_sources=("api",))
    with pytest.raises(Protocol27AuthorityError, match="complete source.*api"):
        resolve_synthesis_parent(tmp_path, parent.name, ("api",))


def test_terminal_protocol_27_parent_reuses_embedded_source_authority(tmp_path: Path) -> None:
    parent = completed_protocol_27_parent(tmp_path, partial_sources=("api",))
    resolved = resolve_synthesis_parent(tmp_path, parent.name, ("api",))
    assert resolved.accepted_sources == embedded_parent_sources(parent)


def test_parse_v2_synthesis_uses_existing_resource_flag_names() -> None:
    options = _parse_re_synthesize_v2_options([
        "--from-run", "re-parent", "--accept-partial", "api",
        "--token-limit", "400000", "--active-ms-limit", "600000",
    ])
    assert options.accepted_partial_sources == ("api",)
    assert options.token_limit == 400000


def test_exact_request_identity_is_stable_and_budget_sensitive(tmp_path: Path) -> None:
    parent = completed_protocol_26_parent(tmp_path, complete_sources=("api",))
    first = synthesis_request(parent, token_limit=400000)
    assert synthesis_request(parent, token_limit=400000).request_id == first.request_id
    assert synthesis_request(parent, token_limit=500000).request_id != first.request_id
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_cli_re_v2_protocol_27.py`

Expected: collection fails because the parser and authority resolver do not exist.

- [ ] **Step 3: Implement strict option parsing and v1 routing isolation**

```python
@dataclass(frozen=True, slots=True)
class _ReSynthesizeV2Options:
    from_run: str
    accepted_partial_sources: tuple[str, ...]
    token_limit: int | None
    active_ms_limit: int | None


def _parse_re_synthesize_v2_options(args: list[str]) -> _ReSynthesizeV2Options:
    values: dict[str, object] = {
        "from_run": None,
        "accepted_partial_sources": [],
        "token_limit": None,
        "active_ms_limit": None,
    }
    scalar = {
        "--from-run": "from_run",
        "--token-limit": "token_limit",
        "--active-ms-limit": "active_ms_limit",
    }
    repeatable = {"--accept-partial": "accepted_partial_sources"}
    index = 0
    while index < len(args):
        option = args[index]
        name, separator, inline = option.partition("=")
        if name not in scalar and name not in repeatable:
            raise ValueError(f"unknown option {option!r}")
        if not separator:
            if index + 1 >= len(args):
                raise ValueError(f"{name} requires a value")
            inline = args[index + 1]
            index += 2
        else:
            index += 1
        value = inline.strip()
        if not value:
            raise ValueError(f"{name} requires a nonempty value")
        if name in repeatable:
            selected = values[repeatable[name]]
            assert isinstance(selected, list)
            if value in selected:
                raise ValueError(f"duplicate {name} selector {value!r}")
            selected.append(value)
            continue
        field = scalar[name]
        if values[field] is not None:
            raise ValueError(f"{name} may be supplied only once")
        if name in {"--token-limit", "--active-ms-limit"}:
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a positive integer") from exc
            if parsed <= 0:
                raise ValueError(f"{name} must be a positive integer")
            values[field] = parsed
        else:
            values[field] = value
    if not isinstance(values["from_run"], str):
        raise ValueError("--from-run is required for RE v2 synthesis")
    selected = values["accepted_partial_sources"]
    assert isinstance(selected, list)
    return _ReSynthesizeV2Options(
        from_run=values["from_run"],
        accepted_partial_sources=tuple(sorted(selected)),
        token_limit=values["token_limit"] if isinstance(values["token_limit"], int) else None,
        active_ms_limit=(
            values["active_ms_limit"]
            if isinstance(values["active_ms_limit"], int)
            else None
        ),
    )
```

Keep this scalar/repeatable loop aligned with `_parse_re_deepen_options`; do not introduce argparse or another CLI parser. Route legacy positional/`--allow-partial` forms to the unchanged v1 body and `--from-run` to protocol 2.7.

- [ ] **Step 4: Implement stable parent reconstruction and acceptance receipts**

Use `resolve_run_authority()`, protocol-2.6 stable reconstruction, protocol-2.7 embedded source authority, accepted source-root receipts, L3 source-root state when present, and the exact debt object referenced by parent authority. Select the highest accepted L1/L2/L3 overview per source, call `materialize_accepted_l1()`, `materialize_accepted_l2()`, or `materialize_accepted_l3()` through their public APIs, verify the returned projection's key/hash/source, and freeze its exact Markdown bytes and materializer authority. Reject running/blocked/missing roots, a nonterminal protocol-2.7 parent, changed manifests during read, unsafe paths, unknown sources, implicit partials, and debt hash mismatches before allocating a child run ID.

```python
def resolve_synthesis_parent(
    workspace_root: Path,
    from_run: str,
    accepted_partial_sources: tuple[str, ...],
) -> ResolvedSynthesisParentV1:
    stable = load_stable_parent(workspace_root, from_run)
    sources = reconstruct_terminal_source_roots(stable)
    validate_exact_partial_selection(sources, accepted_partial_sources)
    return freeze_synthesis_parent(stable, sources, accepted_partial_sources)
```

- [ ] **Step 5: Prove no live source reads and exact child reuse**

Add tests that chmod/remove declared source repositories after the parent is complete and retain only parent objects/events/ledger; overview freezing must rebuild through the selected public layer materializer without source reads. Mutate a parent projection before freezing and assert the public materializer quarantines/rebuilds it before the child copies bytes. Repeat the exact request and assert `find_exact_protocol_27_child()` returns the same run; change one debt hash, acceptance set, budget limit, or publication base and assert it does not. Assert every partial receipt's `operation_id` equals the frozen request ID.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_cli_re_v2_protocol_27.py tests/unit/test_cli_re_lifecycle.py`

Expected: PASS; v1 synthesis tests remain unchanged.

- [ ] **Step 6: Commit source authority and CLI parsing**

```bash
git add src/harness/re_v2/protocol_27/authority.py src/harness/re_v2/protocol_27/lifecycle.py src/echelon/cli.py tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_cli_re_v2_protocol_27.py tests/unit/test_cli_re_lifecycle.py
git commit -m "feat(re-v2): freeze synthesis source outcomes"
```

---

### Task 3: Build the Granular Synthesis Policy and Dependency Graph

**Files:**
- Create: `src/harness/re_v2/protocol_27/policies.py`
- Create: `src/harness/re_v2/protocol_27/graph.py`
- Create: `tests/unit/test_re_v2_protocol_27_policies.py`
- Create: `tests/unit/test_re_v2_protocol_27_graph.py`

**Interfaces:**
- Registers exact generated kinds `source-architecture`, `source-contracts`, `source-components`, `workspace-domain-summary`, `workspace-overview`, `workspace-relationships`, and `workspace-contracts`.
- Represents accepted lower overview projections as non-generated `source-overview-projection` dependencies.
- Produces `WorkspaceSynthesisTopologyV1` from authenticated partition/source/domain authority only.
- Produces `SynthesisGraphInputsV1(accepted_sources, topology, policy_catalog, response_schema_hashes, context_policy_hash)`.
- `build_synthesis_graph(inputs) -> SynthesisGraph` returns canonical templates/items, dependency order, public path mapping, and one controller-root specification.
- `SynthesisGraph.required_nodes`, `.ready_work_items(accepted_node_hashes)`,
  `.required_node_ids`, `.graph_id`, and `.affected_by_source(source_id)` are
  deterministic. The static graph freezes node identities and dependency edges;
  exact `SynthesisWorkItemV1` values are instantiated only when all generated
  dependency hashes are accepted, because downstream artifact keys bind those
  hashes and cannot truthfully exist beforehand.

- [ ] **Step 1: Write failing policy and graph shape tests**

```python
def test_graph_has_granular_source_domain_and_workspace_nodes() -> None:
    graph = build_synthesis_graph(graph_inputs(sources=("api", "web")))
    kinds = tuple(item.artifact_kind for item in graph.required_nodes)
    assert kinds.count("source-architecture") == 2
    assert kinds.count("source-contracts") == 2
    assert kinds.count("source-components") == 2
    assert "workspace-overview" in kinds
    assert "workspace-relationships" in kinds
    assert "workspace-contracts" in kinds


def test_one_source_change_preserves_unrelated_domain_key() -> None:
    before = build_synthesis_graph(
        graph_inputs(source_hashes={"api": digest("api-v1"), "web": digest("web-v1")})
    )
    after = build_synthesis_graph(
        graph_inputs(source_hashes={"api": digest("api-v2"), "web": digest("web-v1")})
    )
    assert key_for(before, "source-architecture", source="web") == key_for(
        after, "source-architecture", source="web"
    )
    assert key_for(before, "workspace-domain-summary", domain="web-only") == key_for(
        after, "workspace-domain-summary", domain="web-only"
    )
    assert key_for(before, "workspace-overview") != key_for(after, "workspace-overview")
```

- [ ] **Step 2: Run the graph tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_policies.py tests/unit/test_re_v2_protocol_27_graph.py`

Expected: collection fails because policy and graph modules do not exist.

- [ ] **Step 3: Implement closed policy catalogs with fixed attempts**

```python
SYNTHESIS_GENERATED_KINDS = frozenset({
    "source-architecture", "source-contracts", "source-components",
    "workspace-domain-summary", "workspace-overview",
    "workspace-relationships", "workspace-contracts",
})


def build_synthesis_policy_catalog(authority: ProsaicAuthorityV1) -> SynthesisPolicyCatalogV1:
    return SynthesisPolicyCatalogV1(
        goal="workspace-synthesis",
        producer_id="echelon.re-synthesizer",
        producer_protocol_version="2.7",
        verifier_id="re-v2-synthesis-verifier",
        verifier_version="1",
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_result_contract_retries=1,
        max_artifact_contract_retries=1,
    )
```

Pin executor, producer, verifier implementation, response schema, and context policy hashes. Reject any catalog that permits a third dispatch or semantic repair round.

- [ ] **Step 4: Implement deterministic topology and graph construction**

Derive workspace-domain IDs from canonical participating source/domain identities, not presentation prose. Build source nodes first, workspace-domain nodes second, then workspace overview/relationships/contracts. Include applicable debt hashes in each key. Validate acyclicity, exact closure, unique public paths, and canonical order at construction.

- [ ] **Step 5: Add invalidation, debt, and determinism matrices**

Test source add/remove/change, domain membership change, policy change, debt-only change, participant ordering, duplicate paths, cycles, no sources, and one source. Assert only dependency-descendant keys change and two constructions from shuffled inputs have byte-identical graph JSON.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_policies.py tests/unit/test_re_v2_protocol_27_graph.py`

Expected: PASS.

- [ ] **Step 6: Commit the closed synthesis graph**

```bash
git add src/harness/re_v2/protocol_27/policies.py src/harness/re_v2/protocol_27/graph.py tests/unit/test_re_v2_protocol_27_policies.py tests/unit/test_re_v2_protocol_27_graph.py
git commit -m "feat(re-v2): define granular synthesis graph"
```

---

### Task 4: Publish and Load a Self-Contained Schema-6 Child Manifest-Last

**Files:**
- Create: `src/harness/re_v2/protocol_27/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_27_inputs.py`
- Modify: `src/harness/re_v2/protocol_27/lifecycle.py`
- Test: `tests/unit/test_re_v2_protocol_27_authority.py`

**Interfaces:**
- Produces `Protocol27InputSet(run_id, created_at, parent, request, partial_acceptances, source_overview_catalog, source_overview_bytes, graph, prosaic_authority_bytes, budget_policy, checkpoint_selection_bytes, authority_objects)`. The exact publication bases live in the request, while topology, policies, response-schema hashes, and context-policy hash live in the graph.
- Produces `Protocol27InputAuthorityCatalogV1(object_hashes_by_role, object_hashes)` and binds its identity from `RunManifestV6.input_authority_catalog_id`, separating immutable creation inputs from later execution objects in the same store.
- Produces `ValidatedProtocol27Inputs(paths, manifest, request, parent_authority, input_authority_catalog, source_overview_catalog, source_overview_bytes, graph, prosaic_authority_bytes, checkpoint_selection_bytes, object_hashes)`.
- `create_protocol_27_run_store(run_dir, inputs, fault_hook=None) -> RunManifestV6` stages every referenced object before publishing `v2/run.json` with no-clobber semantics.
- `load_protocol_27_inputs(run_dir) -> ValidatedProtocol27Inputs` reconstructs only from manifest references and content-addressed bytes.
- `prepare_protocol_27_child(workspace_root: Path, run_id: str, inputs: Protocol27InputSet) -> PreparedProtocol27Creation` creates a hidden staged directory and does not mutate the active-run pointer.

- [ ] **Step 1: Write failing manifest-last and self-containment tests**

```python
def test_create_protocol_27_store_publishes_manifest_last(tmp_path: Path) -> None:
    observed: list[str] = []
    manifest = create_protocol_27_run_store(
        tmp_path / "re-child", input_set(), fault_hook=observed.append
    )
    assert observed[-1] == "after_manifest_publish"
    assert load_protocol_27_inputs(tmp_path / "re-child").manifest == manifest


def test_loaded_child_does_not_need_parent_or_cache(tmp_path: Path) -> None:
    child, parent, cache = create_child_parent_and_cache(tmp_path)
    shutil.rmtree(parent)
    shutil.rmtree(cache)
    loaded = load_protocol_27_inputs(child)
    assert loaded.graph.graph_id == loaded.manifest.synthesis_graph_id
    assert canonical_source_overview_bytes(loaded, "api") == expected_overview_bytes(child, "api")
```

- [ ] **Step 2: Run the input tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_inputs.py`

Expected: collection fails because protocol-2.7 input publication does not exist.

- [ ] **Step 3: Implement immutable object staging and exact reference catalogs**

Use `ReV2Paths`, `ObjectStore`, canonical JSON, safe directory creation, fsync, and the existing manifest-last/no-clobber pattern. Stage source outcomes, accepted-overview projection catalog and exact Markdown objects, acceptance receipts, aggregate topology plus each work-item-addressed source/domain topology component, graph, static graph nodes and work templates, policies, schemas, context manifests, Prosaic bytes, budget, checkpoint selection, and publication bases. Concrete work items are persisted when dependency-ready. Verify every supplied mapping key equals `content_digest(payload)` and every overview `content_hash`/`object_hash` matches the staged bytes.

```python
def create_protocol_27_run_store(
    run_dir: Path,
    inputs: Protocol27InputSet,
    fault_hook: Callable[[str], None] | None = None,
) -> RunManifestV6:
    paths = ReV2Paths.for_run(run_dir)
    ensure_closed_run_layout(paths)
    object_ids = stage_protocol_27_objects(paths, inputs, fault_hook)
    manifest = manifest_from_staged_inputs(inputs, object_ids)
    publish_manifest_no_clobber(paths.manifest, canonical_json_bytes(manifest.to_json_dict()))
    call_fault(fault_hook, "after_manifest_publish")
    return manifest
```

- [ ] **Step 4: Implement fail-closed loading**

Require exact schema/protocol, safe regular files, canonical bytes, matching hashes, graph closure, policy/schema/context references, exact acceptance coverage, and source/partition identity agreement. Reject unreferenced authority, symlinks, hardlinks where the existing run-store policy rejects them, manifest replacement, truncated files, and wrong object bytes.

- [ ] **Step 5: Add every staging fault boundary and no-clobber test**

Parameterize faults after object directories, source authority, each overview projection object, overview catalog, acceptance receipts, topology, graph, policies, schemas, Prosaic authority, budget, checkpoint selection, and immediately before/after manifest publish. Rerun creation after each crash; assert it either completes identically or fails a post-freeze conflict without replacing bytes.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_inputs.py tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_re_v2_run_store.py`

Expected: PASS.

- [ ] **Step 6: Commit the self-contained input boundary**

```bash
git add src/harness/re_v2/protocol_27/inputs.py src/harness/re_v2/protocol_27/lifecycle.py tests/unit/test_re_v2_protocol_27_inputs.py tests/unit/test_re_v2_protocol_27_authority.py
git commit -m "feat(re-v2): publish synthesis children manifest-last"
```

---

### Task 5: Add the Neutral Prosaic Role, Closed Schemas, and Bounded Contexts

**Files:**
- Create: `prosaic/subagents/echelon.re-synthesizer.md`
- Create: `src/harness/re_v2/protocol_27/schemas.py`
- Create: `src/harness/re_v2/protocol_27/context.py`
- Create: `src/harness/re_v2/protocol_27/runtime.py`
- Create: `tests/unit/test_re_v2_protocol_27_schemas.py`
- Create: `tests/unit/test_re_v2_protocol_27_context.py`
- Create: `tests/unit/test_re_v2_protocol_27_runtime.py`
- Test: `tests/unit/test_prosaic_agent_authoring.py`

**Interfaces:**
- Adds neutral `echelon.re-synthesizer` frontmatter with existing Prosaic `model_tier`, `effort`, and tool metadata; provider/model selection remains outside the role.
- `synthesis_response_schema(kind: str) -> dict[str, object]` returns one closed JSON schema per generated kind.
- Produces `SynthesisContextV1(work_item_id, artifact_key_id, authorized_objects, dependency_artifacts, source_outcomes, debt_refs, public_contract)` with canonical bytes and a hard size ceiling.
- `build_synthesis_context(inputs, work_item) -> SynthesisContextV1` includes only dependency-authorized evidence.
- Produces `SynthesisCandidateV1`, `SynthesisAssessmentV1`, `SynthesisCertificationV1`, and `SynthesisArtifactAcceptanceV1`.
- `Protocol27DeterministicRuntime.certify_candidate(work_item, context, payload) -> SynthesisCertificationResultV1` strictly parses, normalizes, validates claims/evidence/debt, stores canonical artifact bytes, and returns typed acceptance authority.

- [ ] **Step 1: Write failing role, schema, and context tests**

```python
def test_every_synthesis_kind_has_closed_schema() -> None:
    for kind in SYNTHESIS_GENERATED_KINDS:
        schema = synthesis_response_schema(kind)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) >= {"artifact_kind", "sections", "claims", "input_quality", "debt_refs"}


def test_context_excludes_unrelated_source_objects() -> None:
    item = source_work_item("api", kind="source-contracts")
    context = build_synthesis_context(validated_inputs(api_and_web=True), item)
    assert "api" in context.source_ids
    assert "web" not in context.source_ids


def test_partial_candidate_cannot_claim_full_quality() -> None:
    with pytest.raises(Protocol27RuntimeError, match="full quality"):
        runtime().certify_candidate(partial_work_item(), partial_context(), candidate(full_quality=True))
```

- [ ] **Step 2: Run the contract tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_schemas.py tests/unit/test_re_v2_protocol_27_context.py tests/unit/test_re_v2_protocol_27_runtime.py tests/unit/test_prosaic_agent_authoring.py`

Expected: failures because the role and protocol-2.7 runtime do not exist.

- [ ] **Step 3: Author the invariant Prosaic protocol**

The role must contain paired rules including:

```markdown
ALWAYS generate exactly the controller-authorized synthesis artifact as `synthesis.json` from the supplied bounded context.
NEVER inspect live source repositories, mutable workspace publication, sibling runs, or unrelated context.

ALWAYS preserve every controller-authorized partial source and debt reference in affected claims.
NEVER claim full RE quality, resolve debt, or omit partial authority from a debt-bearing artifact.

ALWAYS return the closed synthesis result contract with `state_updates: {}`.
NEVER write controller state, ledgers, receipts, roots, publication data, or files outside the one authorized candidate path.
```

Use `model_tier: strong`, `effort: high`, and the same neutral tool posture supported by shared coding providers. Do not name Claude, Codex, Copilot, OpenCode, or a concrete model.

- [ ] **Step 4: Implement closed schemas and context construction**

Require bounded section/claim/evidence arrays, exact artifact kind/scope, explicit input quality, exact sorted debt refs, and source/artifact citations authorized by the context manifest. Sections group claim IDs rather than carrying uncited free-form prose; every authorial factual statement therefore lives in an evidence-bearing claim. Context serialization contains object identities plus bounded rendered excerpts; it never embeds arbitrary run directories or live paths.

- [ ] **Step 5: Implement deterministic candidate validation and certification**

```python
class Protocol27DeterministicRuntime:
    def certify_candidate(
        self,
        work_item: SynthesisWorkItemV1,
        context: SynthesisContextV1,
        payload: bytes,
    ) -> SynthesisCertificationResultV1:
        raw = strict_json(payload)
        candidate = SynthesisCandidateV1.from_json_dict(raw)
        validate_scope_and_dependencies(candidate, work_item, context)
        validate_claim_evidence(candidate, context)
        validate_input_quality_and_debt(candidate, context)
        artifact_bytes = canonical_synthesis_artifact_bytes(candidate)
        return certify_and_accept(work_item, context, candidate, artifact_bytes)
```

Reject extra JSON fields, invalid UTF-8, duplicate claims, unknown citations, unauthorized source/domain IDs, omitted applicable debt, invented debt, wrong quality, empty required sections, and artifact-kind mismatch. Controller debt remains authoritative even if candidate prose differs.

- [ ] **Step 6: Run the complete contract matrix**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_schemas.py tests/unit/test_re_v2_protocol_27_context.py tests/unit/test_re_v2_protocol_27_runtime.py tests/unit/test_prosaic_agent_authoring.py`

Expected: PASS.

- [ ] **Step 7: Commit Prosaic synthesis contracts**

```bash
git add prosaic/subagents/echelon.re-synthesizer.md src/harness/re_v2/protocol_27/schemas.py src/harness/re_v2/protocol_27/context.py src/harness/re_v2/protocol_27/runtime.py tests/unit/test_re_v2_protocol_27_schemas.py tests/unit/test_re_v2_protocol_27_context.py tests/unit/test_re_v2_protocol_27_runtime.py tests/unit/test_prosaic_agent_authoring.py
git commit -m "feat(re-v2): define bounded synthesis contracts"
```

---

### Task 6: Record Typed Synthesis Receipts, Events, and Independent Budget

**Files:**
- Create: `src/harness/re_v2/protocol_27/ledger.py`
- Create: `src/harness/re_v2/protocol_27/events.py`
- Create: `src/harness/re_v2/protocol_27/budget.py`
- Create: `tests/unit/test_re_v2_protocol_27_ledger.py`
- Create: `tests/unit/test_re_v2_protocol_27_events.py`
- Create: `tests/unit/test_re_v2_protocol_27_budget.py`

**Interfaces:**
- `Protocol27Ledger` reuses `DurableLedger` envelopes and adds exact records for partial acceptance, candidate assessment, synthesis certification, synthesis artifact acceptance, checkpoint adoption, synthesis root, materialization manifest, and publication descriptor.
- `Protocol27LedgerView` exposes immutable maps keyed by work item/artifact key and rejects conflicting duplicate authority.
- `protocol_27_events() -> EventProtocol` composes base lifecycle/provider events with protocol-2.7 source acceptance, synthesis adoption/acceptance/root/materialization/publication events.
- `Protocol27ReplayState` enforces request-before-acceptance, dispatch-before-capture, certification-before-acceptance, dependencies-before-downstream acceptance, root-after-closure, materialization-after-root, and publication-after-materialization.
- `evaluate_synthesis_budget(manifest, events, ledger) -> SynthesisBudgetDecisionV1` accounts only synthesis work and uses trusted usage or conservative dispatch reservations.

- [ ] **Step 1: Write failing replay and accounting tests**

```python
def test_artifact_acceptance_requires_certification_and_dependencies() -> None:
    events = protocol_27_events()
    with pytest.raises(ReV2EventError, match="certification"):
        replay(events, [synthesis_artifact_accepted_event()])


def test_adopted_artifact_consumes_no_synthesis_budget() -> None:
    decision = evaluate_synthesis_budget(
        manifest_v6(token_limit=1),
        events=(checkpoint_adopted_event(), synthesis_artifact_accepted_event(adopted=True)),
        ledger=ledger_with_adopted_artifact(),
    )
    assert decision.known_tokens == 0
    assert decision.provider_attempts == 0


def test_contract_retry_cannot_stack_into_third_dispatch() -> None:
    with pytest.raises(Protocol27BudgetError, match="provider attempt limit"):
        evaluate_synthesis_budget(manifest_v6(), three_dispatch_events_for_one_item(), ledger())
```

- [ ] **Step 2: Run the durability tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_ledger.py tests/unit/test_re_v2_protocol_27_events.py tests/unit/test_re_v2_protocol_27_budget.py`

Expected: collection fails because protocol-2.7 ledger/events/budget do not exist.

- [ ] **Step 3: Implement closed ledger receipts and replay**

Reuse `LedgerRecord`, `DurableLedger`, `EventRecord`, `EventStore`, canonical payload validation, sequence/hash chaining, and duplicate-idempotence patterns. New receipts carry exact synthesis work/key/candidate/certification/artifact identities; they do not reinterpret `ArtifactAcceptanceReceiptV2`.

```python
class Protocol27Ledger(DurableLedger):
    def append_synthesis_acceptance(self, receipt: SynthesisArtifactAcceptanceV1) -> LedgerRecord:
        return self.append("synthesis_artifact_acceptance_v1", receipt.to_json_dict())


def protocol_27_events(parent_protocol: EventProtocol) -> EventProtocol:
    return ComposedEventProtocol(base=parent_protocol, extension=_PROTOCOL_27_EVENTS)
```

At load time, select `parent_protocol` from the exact embedded parent authority in `RunManifestV6`; valid parents may close at L1, L2, or L3.

- [ ] **Step 4: Implement independent accounting**

Count protocol-2.7 dispatch reservations, trusted normalized usage, active milliseconds, initial attempts, and one contract retry per synthesis work item. Reject negative/overflow values, duplicate charges, untrusted usage without reservation, lower-layer usage leakage, and policy mismatch.

- [ ] **Step 5: Add canonical corruption and replay-order matrices**

Test every event/receipt with missing, extra, wrong-type, wrong-hash, out-of-order, duplicate-identical, and duplicate-conflicting payloads. Assert exact idempotence for identical records and fail-closed behavior for conflicts.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_ledger.py tests/unit/test_re_v2_protocol_27_events.py tests/unit/test_re_v2_protocol_27_budget.py`

Expected: PASS.

- [ ] **Step 6: Commit synthesis durability and accounting**

```bash
git add src/harness/re_v2/protocol_27/ledger.py src/harness/re_v2/protocol_27/events.py src/harness/re_v2/protocol_27/budget.py tests/unit/test_re_v2_protocol_27_ledger.py tests/unit/test_re_v2_protocol_27_events.py tests/unit/test_re_v2_protocol_27_budget.py
git commit -m "feat(re-v2): account synthesis authority durably"
```

---

### Task 7: Reconstruct and Adopt Exact Synthesis Checkpoints

**Files:**
- Create: `src/harness/re_v2/protocol_27/checkpoints.py`
- Create: `tests/unit/test_re_v2_protocol_27_checkpoints.py`
- Modify: `src/harness/re_v2/protocol_27/model.py`
- Modify: `src/harness/re_v2/protocol_27/inputs.py`
- Modify: `src/harness/re_v2/protocol_27/ledger.py`
- Modify: `src/harness/re_v2/protocol_27/events.py`

**Interfaces:**
- Produces `SynthesisCheckpointManifestV1` from one stable protocol-2.7 origin's exact work item, candidate assessment, certification, artifact acceptance, dependencies, artifact bytes, and origin event/ledger prefix hashes.
- Produces `SynthesisCheckpointSelectionV1(entries, dispositions, copied_object_ids, origin_prefixes, selection_id)` in dependency order.
- `reconstruct_synthesis_checkpoints(workspace_root) -> SynthesisCheckpointInventoryV1` scans stable sibling protocol-2.7 runs only and returns controlled rejection records for malformed origins.
- `select_synthesis_checkpoints(graph, direct_parent, inventory) -> SynthesisCheckpointSelectionV1` applies direct-parent precedence, exact key compatibility, deterministic certified-rank/artifact-hash tie break, and maximal acyclic dependency closure.
- `stage_synthesis_checkpoint_selection(run_dir, selection)` copies and verifies all objects/receipts before manifest publication.
- `adopt_synthesis_checkpoints(context) -> SynthesisCheckpointAdoptionReportV1` imports typed receipts/events before any lease or dispatch.

- [ ] **Step 1: Write failing reconstruction and closure tests**

```python
def test_nonterminal_origin_artifact_is_immediately_eligible(tmp_path: Path) -> None:
    origin = protocol_27_origin(tmp_path, terminal=False, accepted=("source-architecture",))
    inventory = reconstruct_synthesis_checkpoints(tmp_path)
    assert inventory.by_origin[origin.name][0].artifact_kind == "source-architecture"


def test_selection_prefers_direct_parent_then_maximal_closure(tmp_path: Path) -> None:
    graph = synthesis_graph_with_chain()
    inventory = sibling_inventory_with_competing_chain()
    selection = select_synthesis_checkpoints(graph, direct_parent_bundle(), inventory)
    assert selection.entries[0].source_kind == "direct_parent"
    assert tuple(entry.artifact_kind for entry in selection.entries) == graph.topological_kinds


def test_corrupt_checkpoint_never_falls_back_to_generation_after_freeze(tmp_path: Path) -> None:
    child = staged_child_with_selected_checkpoint(tmp_path)
    corrupt_selected_object(child)
    with pytest.raises(Protocol27CheckpointError, match="post-freeze"):
        adopt_synthesis_checkpoints(load_context(child))
```

- [ ] **Step 2: Run checkpoint tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_checkpoints.py`

Expected: collection fails because synthesis checkpoint support does not exist.

- [ ] **Step 3: Implement stable origin reconstruction**

Use the safe sibling enumeration, stable manifest/event/ledger pair reads, canonical-prefix hashing, confined paths, and controlled-reason vocabulary established by protocol 2.6. Decode only schema-6/protocol-2.7 origins. Reconstruct acceptance from durable receipts and object bytes; ignore terminal state and mutable materialization.

- [ ] **Step 4: Implement deterministic exact selection**

```python
def select_synthesis_checkpoints(
    graph: SynthesisGraph,
    direct_parent: SynthesisCheckpointInventoryV1,
    workspace_inventory: SynthesisCheckpointInventoryV1,
) -> SynthesisCheckpointSelectionV1:
    candidates = compatible_candidates_by_key(graph, direct_parent, workspace_inventory)
    ranked = rank_with_direct_parent_precedence(candidates)
    selected = maximal_dependency_closed_selection(graph, ranked)
    return freeze_selection(graph, ranked, selected)
```

Rank only existing certified assessment fields; equal rank selects the lexicographically smallest artifact hash. Preserve origin-coherent fallback when independent per-key winners would shrink the maximal closure. Record every incompatible, lower-ranked, dependency-pruned, cyclic, corrupt, and quarantined disposition.

- [ ] **Step 5: Implement staged copy and typed adoption**

Copy exact artifact, work item, candidate, assessment, certification, acceptance, dependency, event-prefix, and ledger-prefix bytes into child objects before manifest publish. On activation, append typed ledger records then adoption/acceptance events in graph order. Identical recovery is idempotent; any conflicting byte or identity is a terminal authority conflict.

- [ ] **Step 6: Prove origin/cache independence and zero budget charge**

After child activation, remove all origins and `.echelon/re-v2/checkpoints`; reload, adopt, and continue from child bytes only. Assert no provider attempt/retry/resource event and no changed canonical event bytes. Create a sibling with only the adopted child visible and assert it re-exports the same closure.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_checkpoints.py tests/unit/test_re_v2_protocol_27_ledger.py tests/unit/test_re_v2_protocol_27_events.py tests/unit/test_re_v2_protocol_27_budget.py`

Expected: PASS.

- [ ] **Step 7: Commit synthesis checkpoint adoption**

```bash
git add src/harness/re_v2/protocol_27/model.py src/harness/re_v2/protocol_27/checkpoints.py src/harness/re_v2/protocol_27/inputs.py src/harness/re_v2/protocol_27/ledger.py src/harness/re_v2/protocol_27/events.py tests/unit/test_re_v2_protocol_27_checkpoints.py tests/unit/test_re_v2_protocol_27_ledger.py tests/unit/test_re_v2_protocol_27_events.py tests/unit/test_re_v2_protocol_27_budget.py
git commit -m "feat(re-v2): adopt granular synthesis checkpoints"
```

---

### Task 8: Execute Only Missing Work Through Prosaic and the Shared Provider

**Files:**
- Create: `src/harness/re_v2/protocol_27/execution.py`
- Create: `src/harness/re_v2/protocol_27/controller.py`
- Create: `tests/unit/test_re_v2_protocol_27_execution.py`
- Create: `tests/unit/test_re_v2_protocol_27_controller.py`
- Modify: `src/harness/re_v2/protocol_27/context.py`
- Modify: `src/harness/re_v2/protocol_27/runtime.py`

**Interfaces:**
- `Protocol27ExecutionStore` reuses `Protocol22ExecutionStore`, `ExecutionInputV1`, `ExecutionCaptureV1`, provider usage normalization, reservation calculation, candidate-root confinement, and capture commit while validating protocol-2.7 executor/content authority like `Protocol25ExecutionStore` does for L3.
- `SquadCliSynthesisRenderer` mirrors the established `SquadCliSemanticRenderer` composition boundary: validate synthesis executor/context/schema authority, render one neutral Prosaic request for `synthesis.json`, and delegate to the existing shared `SquadCliProvider` factory/result contract/normalization path. It is not registered as a provider adapter and contains no provider/model/credential branch.
- `build_synthesis_provider_dependencies(inputs, work_item, retry_diagnostics) -> ProviderExecutionDependenciesV1` loads exact Prosaic bytes, context bytes, response schema, and executor contract from child objects.
- `SynthesisControllerStateV1` is reconstructed from graph, ledger, events, budget, accepted artifacts, failures, and pending durable capture.
- `plan_next_synthesis(state) -> SynthesisControllerActionV1` returns exactly one of `adopt`, `dispatch`, `recover_capture`, `accept_candidate`, `create_root`, or terminal `closure_complete`/`incomplete` in this task; Tasks 10 and 11 add `materialize` and `publish` only after those implementations exist.
- `Protocol27Controller.run_to_closure() -> Protocol27ControllerResult` applies one idempotent action at a time until the synthesis root is complete or the bounded work is terminally incomplete.

- [ ] **Step 1: Write failing shared-provider and planner tests**

```python
def test_execution_resolves_frontmatter_through_existing_provider(tmp_path: Path) -> None:
    dependencies = build_synthesis_provider_dependencies(inputs(tmp_path), work_item(), ())
    artifact = decode_prosaic_agent_bytes(dependencies.agent_bytes)
    assert artifact.frontmatter["model_tier"] == "strong"
    assert artifact.frontmatter["effort"] == "high"
    factory = recording_provider_factory()
    renderer = synthesis_renderer(dependencies, factory)
    execute_synthesis(renderer, prepared_execution(dependencies, tmp_path))
    assert factory.provider.last_prompt_metadata == dict(artifact.frontmatter)


def test_controller_dispatches_only_ready_missing_work() -> None:
    source_arch = work_item(artifact_kind="source-architecture", source_id="api")
    source_contracts = work_item(artifact_kind="source-contracts", source_id="api")
    workspace_contracts = work_item(artifact_kind="workspace-contracts")
    state = controller_state(
        accepted=(source_arch,),
        missing=(source_contracts, workspace_contracts),
    )
    action = plan_next_synthesis(state)
    assert action.kind == "dispatch"
    assert action.work_item_id == source_contracts.work_item_id


def test_malformed_candidate_gets_exactly_one_contract_retry() -> None:
    result = run_scripted_controller(results=(malformed_result(), valid_result()))
    assert result.synthesis_closure_complete
    assert result.provider_attempts == 2
    assert result.contract_retries == 1
```

- [ ] **Step 2: Run execution/controller tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_execution.py tests/unit/test_re_v2_protocol_27_controller.py`

Expected: collection fails because execution and controller modules do not exist.

- [ ] **Step 3: Compose the established protocol-scoped renderer over the shared provider**

Build generic `ExecutionInputV1` with the synthesis work-item ID, exact executor/agent/context/envelope hashes, and `initial_generation` or `artifact_contract_retry`. Follow `Protocol25ExecutionStore` and `SquadCliSemanticRenderer`: reuse `calculate_shared_cli_dispatch_reservation()`, `_validate_empty_candidate_root`, the shared `EchelonResultContract`, `normalize_shared_provider_usage()`, `RawExecutionResultV1`, and the injected `SquadCliProvider` factory, while validating `SynthesisContextV1` and the synthesis executor catalog under protocol 2.7. The renderer writes/accepts exactly `synthesis.json`; capture stdout/stderr/usage/timing/provider/model through the existing execution-capture format. Do not alter protocol-2.2 or protocol-2.5 code and do not create/register another provider adapter.

```python
def prepare_synthesis_execution(
    store: Protocol27ExecutionStore,
    work_item: SynthesisWorkItemV1,
    dependencies: ProviderExecutionDependenciesV1,
    attempt_kind: str,
) -> PreparedExecutionV1:
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id=dispatch_id_for(work_item.work_item_id, attempt_kind),
        work_item_id=work_item.work_item_id,
        attempt_kind=attempt_kind,
        executor_contract_hash=work_item.executor_contract_hash,
        agent_contract_hash=content_digest(dependencies.agent_bytes),
        context_bundle_hash=content_digest(dependencies.context_bytes),
        provider_request_envelope_hash=None,
        deterministic_invocation=None,
    )
    return store.prepare(execution_input, dependencies)
```

- [ ] **Step 4: Implement deterministic planning and bounded retry**

Order actions by recovery first, then checkpoint adoption, dependency-ready work in canonical graph order, and root creation. Before dispatch, evaluate the immutable budget. A malformed/missing candidate records controlled diagnostics and permits one artifact-contract retry; transport timeout/error consumes its attempt and permits only the same fixed second attempt. A third call is impossible by construction. Return `closure_complete` after root creation; later tasks extend the same planner beyond that boundary.

- [ ] **Step 5: Test all provider result envelopes and isolation**

Cover valid DONE, invalid `echelon_result`, state updates, wrong verdict, missing `synthesis.json`, multiple candidate files, symlink/hardlink/path escape, timeout, transport error, untrusted usage, trusted usage, output truncation, provider/model observation, frontmatter forwarding, shared-provider instance reuse, and exact retry diagnostics. Assert no raw prompt/response enters telemetry and all configured provider families traverse `SquadCliProvider` rather than a protocol-specific adapter.

- [ ] **Step 6: Test partial success and retained siblings**

Script one artifact to exhaust both attempts while unrelated work succeeds. Assert terminal `incomplete`, accepted sibling receipts remain, downstream dependents do not dispatch, and an identical continuation makes no call for accepted siblings.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_execution.py tests/unit/test_re_v2_protocol_27_controller.py tests/unit/test_re_v2_protocol_27_runtime.py tests/unit/test_re_v2_protocol_27_budget.py`

Expected: PASS.

- [ ] **Step 7: Commit shared-provider synthesis execution**

```bash
git add src/harness/re_v2/protocol_27/execution.py src/harness/re_v2/protocol_27/controller.py src/harness/re_v2/protocol_27/context.py src/harness/re_v2/protocol_27/runtime.py tests/unit/test_re_v2_protocol_27_execution.py tests/unit/test_re_v2_protocol_27_controller.py tests/unit/test_re_v2_protocol_27_runtime.py tests/unit/test_re_v2_protocol_27_budget.py
git commit -m "feat(re-v2): execute missing synthesis work"
```

---

### Task 9: Recover Every Durable Boundary Without Duplicate Dispatch

**Files:**
- Create: `src/harness/re_v2/protocol_27/recovery.py`
- Create: `tests/integration/test_re_v2_protocol_27_recovery.py`
- Modify: `src/harness/re_v2/protocol_27/controller.py`
- Modify: `src/harness/re_v2/protocol_27/lifecycle.py`
- Test: `tests/unit/test_re_v2_protocol_27_controller.py`

**Interfaces:**
- Produces `Protocol27RunContext(paths, inputs, object_store, events, ledger, execution_store, runtime)` from authenticated child state.
- Produces `Protocol27RecoveryResult(state, accepted_artifact_hashes, pending_action, repaired_boundaries)`.
- `recover_protocol_27_run(context) -> Protocol27RecoveryResult` initially reconciles manifest, objects, adoption, dispatch/capture/commit, candidate/certification/acceptance, and root without consulting origins; Tasks 10 and 11 extend it for materialization and publication.
- `run_protocol_27_synthesis(run_dir, provider_factory, fault_hook=None) -> Protocol27ControllerResult` always recovers before planning.

- [ ] **Step 1: Write the failing recovery boundary matrix**

```python
@pytest.mark.parametrize("boundary", (
    "after_dispatch_reserved", "after_provider_capture", "after_capture_commit",
    "after_candidate_staged", "after_assessment", "after_certification",
    "after_acceptance_ledger", "after_acceptance_event", "after_root",
))
def test_recovery_is_idempotent_at_every_boundary(tmp_path: Path, boundary: str) -> None:
    run_dir, provider = crash_once_at(tmp_path, boundary)
    before_calls = provider.call_count
    result = resume_protocol_27(run_dir, provider)
    assert result.synthesis_closure_complete
    assert provider.call_count <= before_calls + expected_new_calls_after(boundary)
    assert replay_protocol_27(run_dir).is_consistent
```

- [ ] **Step 2: Run recovery tests and confirm RED**

Run: `pytest -q tests/integration/test_re_v2_protocol_27_recovery.py`

Expected: failures because protocol-2.7 recovery does not exist.

- [ ] **Step 3: Implement authenticated context and replay-first recovery**

Load schema-6 inputs, compose the embedded parent event authority, replay protocol-2.7 events/ledger, validate object references, reconstruct accepted artifacts, and identify exactly one pending durable operation. Never infer success from candidate files or projections without matching receipts.

- [ ] **Step 4: Reconcile provider completion without re-dispatch**

If a durable `ExecutionCaptureV1` or capture commit exists, complete candidate inventory/assessment/certification/acceptance from it. If dispatch reservation exists without a durable result, apply the existing provider lease/child-liveness contract before retry authorization. Unknown process state fails closed; it never issues an overlapping call.

- [ ] **Step 5: Reconcile the synthesis root idempotently**

Recreate the deterministic synthesis root when absent, accept a byte-identical existing object, and reject identity collisions. Return the exact `closure_complete` boundary without importing or simulating the not-yet-created materialization/publication modules.

- [ ] **Step 6: Add actual process-death and origin-removal cases**

Use a child process for one provider dispatch, kill the controller after capture, resume, and assert no second provider process. Repeat after deleting parent/origins/cache. Hash events and ledgers before terminal continuation and assert byte identity afterward.

Run: `pytest -q tests/integration/test_re_v2_protocol_27_recovery.py tests/unit/test_re_v2_protocol_27_controller.py tests/unit/test_re_v2_protocol_27_checkpoints.py`

Expected: PASS.

- [ ] **Step 7: Commit synthesis recovery**

```bash
git add src/harness/re_v2/protocol_27/recovery.py src/harness/re_v2/protocol_27/controller.py src/harness/re_v2/protocol_27/lifecycle.py tests/integration/test_re_v2_protocol_27_recovery.py tests/unit/test_re_v2_protocol_27_controller.py tests/unit/test_re_v2_protocol_27_checkpoints.py
git commit -m "feat(re-v2): recover synthesis without duplicate work"
```

---

### Task 10: Materialize Exact Run-Local Compatibility Projections

**Files:**
- Create: `src/harness/re_v2/protocol_27/materialization.py`
- Create: `tests/unit/test_re_v2_protocol_27_materialization.py`
- Modify: `src/harness/re_v2/protocol_27/model.py`
- Modify: `src/harness/re_v2/protocol_27/controller.py`
- Modify: `src/harness/re_v2/protocol_27/recovery.py`

**Interfaces:**
- Produces `SynthesisMaterializationEntryV1(artifact_key_id, artifact_hash, authority_id, relative_path, content_hash)` and `SynthesisMaterializationManifestV1(entries, source_outcomes, input_quality)`.
- `materialize_synthesis_closure(context, fault_hook=None) -> SynthesisMaterializationManifestV1` writes only beneath `run_dir/re/published/` and maps every file to accepted authority.
- `validate_or_repair_synthesis_materialization(context) -> SynthesisMaterializationManifestV1` quarantines altered safe projections and rebuilds exact bytes from child objects.
- `canonical_source_overview_bytes(context, source_id) -> bytes` reads the child-owned object named by `AcceptedSourceOverviewProjectionV1` and verifies its content/object hashes; it never reads the parent or renders a new overview.
- Extends `plan_next_synthesis()` with `materialize` after `closure_complete` and `materialization_complete` after a validated manifest; extends `recover_protocol_27_run()` only for materialization boundaries.

- [ ] **Step 1: Write failing path and rebuild tests**

```python
def test_materialization_preserves_existing_public_paths(tmp_path: Path) -> None:
    manifest = materialize_synthesis_closure(completed_context(tmp_path))
    paths = {entry.relative_path for entry in manifest.entries}
    assert "sources/api/overview.md" in paths
    assert "sources/api/architecture.md" in paths
    assert "workspace/overview.md" in paths
    assert "workspace/relationships.md" in paths
    assert "workspace/contracts.md" in paths


def test_source_overview_is_exact_lower_layer_projection(tmp_path: Path) -> None:
    context = completed_context(tmp_path)
    expected = canonical_parent_overview_bytes(context, "api")
    materialize_synthesis_closure(context)
    assert (context.paths.root / "published/sources/api/overview.md").read_bytes() == expected


def test_deleted_projection_rebuilds_byte_identically(tmp_path: Path) -> None:
    context = completed_context(tmp_path)
    first = materialize_synthesis_closure(context)
    before = tree_digest(context.paths.root / "published")
    shutil.rmtree(context.paths.root / "published")
    assert validate_or_repair_synthesis_materialization(context) == first
    assert tree_digest(context.paths.root / "published") == before
```

- [ ] **Step 2: Run materialization tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_materialization.py`

Expected: collection fails because protocol-2.7 materialization does not exist.

- [ ] **Step 3: Implement the exact accepted-artifact mapping**

Map source overview/architecture/contracts/components, workspace overview/relationships/contracts, and workspace-domain summaries to closed relative paths. Use canonical IDs for path components and reject collisions, traversal, backslashes, absolute paths, duplicate finals, missing accepted keys, and unaccepted artifacts.

- [ ] **Step 4: Implement safe projection and deterministic rendering**

Use directory FDs/no-follow checks and atomic file writes. Generated structured synthesis artifacts render through one deterministic Markdown renderer per kind; output headings/order come from schema fields, not model-provided filenames. Source overview bytes come from the exact accepted lower-layer projection embedded in child inputs.

- [ ] **Step 5: Implement validation, quarantine, and repair**

Validate manifest identity, file type/mode/hash, exact file set, safe directories, and authority mapping. Quarantine altered regular files under run-local quarantine before rebuilding; fail closed on symlink, hardlink, directory-type, or path-containment attacks.

- [ ] **Step 6: Add crash boundaries and unexpected-file tests**

Crash before/after every projected file and manifest publication. Resume and assert byte identity, no provider call, and no accepted-authority mutation. Add missing, modified, extra, symlink, hardlink, wrong mode, and nested path-escape cases.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_materialization.py tests/integration/test_re_v2_protocol_27_recovery.py`

Expected: PASS.

- [ ] **Step 7: Commit compatibility materialization**

```bash
git add src/harness/re_v2/protocol_27/model.py src/harness/re_v2/protocol_27/materialization.py src/harness/re_v2/protocol_27/controller.py src/harness/re_v2/protocol_27/recovery.py tests/unit/test_re_v2_protocol_27_materialization.py tests/integration/test_re_v2_protocol_27_recovery.py
git commit -m "feat(re-v2): materialize synthesis compatibility views"
```

---

### Task 11: Publish Physical Compatibility Files and V2 Authority Recoverably

**Files:**
- Create: `src/harness/re_v2/protocol_27/publication.py`
- Create: `tests/unit/test_re_v2_protocol_27_publication.py`
- Modify: `src/harness/re_v2/protocol_27/model.py`
- Modify: `src/harness/re_v2/protocol_27/controller.py`
- Modify: `src/harness/re_v2/protocol_27/recovery.py`
- Modify: `src/harness/re_publication.py`
- Modify: `src/harness/re_registry.py`
- Test: `tests/unit/test_re_v2_publication.py`
- Test: `tests/unit/test_re_registry.py`
- Test: `tests/integration/test_re_publication_flow.py`

**Interfaces:**
- `build_compatibility_candidate(context, materialization, generation) -> CompatibilityPublicationCandidateV1` produces canonical source/workspace manifests and index bytes without referring to a publication descriptor.
- `build_publication_descriptor(context, materialization, candidate) -> PublicationDescriptorV1` binds synthesis root, input quality, source outcomes, debt/acceptance receipts, materialization manifest, the candidate's exact compatibility generation/index hash, run, and synthesis policy.
- `prepare_compatibility_transaction(registry, context, candidate) -> PublicationTransaction` uses `registry.root` as the transaction root and stages `sources/<source-id>`, `workspace`, and `index.json` operations, with index replacement last; those operation paths install the public `re/sources/<source-id>`, `re/workspace`, and `re/index.json` files without an accidental `re/re` prefix.
- `publish_protocol_27_generation(context, fault_hook=None) -> Protocol27PublicationResult` acquires `RePublishLock`, validates both creation bases, builds the compatibility candidate and descriptor, applies the compatibility transaction, then calls existing `publish_generation()` with `(descriptor.descriptor_id,)` and the frozen policy.
- Produces publication states `published_complete`, `published_partial`, and `conflict` without changing existing v1 or v2 index schemas.
- `recover_protocol_27_publication(context) -> Protocol27PublicationResult` completes the valid second CAS, recognizes an already-installed matching pair, or rolls back compatibility files before releasing a stale/owned lock.
- Extends `plan_next_synthesis()` with `publish` after `materialization_complete` and terminal `complete` after a durable publication receipt; extends `recover_protocol_27_run()` for every marked dual-publication boundary.
- The existing `recover_interrupted_publication()` entrypoint detects a canonical protocol-2.7 publication marker and delegates only that marked journal to protocol-2.7 recovery; unmarked legacy journals retain their exact recovery behavior.
- `PublishedReIndex.synthesis_quality` exposes the existing index `quality.workspace_synthesis` object as a closed optional `PublishedReSynthesisQualityV1`; v1 indexes decode to `None` and the registry schema version remains 1.

- [ ] **Step 1: Write failing dual-publication and conflict tests**

```python
def test_partial_descriptor_publishes_existing_paths_and_labels(tmp_path: Path) -> None:
    context = complete_synthesis_context(tmp_path, input_quality="partial")
    result = publish_protocol_27_generation(context)
    assert result.status == "published_partial"
    assert (tmp_path / "re/sources/api/overview.md").is_file()
    assert load_published_index(tmp_path).publication_status == "partial"
    assert load_published_v2_index(tmp_path).run_id == context.paths.root.parent.name


def test_v2_cas_conflict_rolls_back_compatibility_projection(tmp_path: Path) -> None:
    previous = publish_previous_generation(tmp_path)
    context = complete_synthesis_context(tmp_path)
    publish_competing_v2_generation(tmp_path)
    result = publish_protocol_27_generation(context)
    assert result.status == "conflict"
    assert load_published_index(tmp_path) == previous


def test_descriptor_binds_staged_compatibility_index_without_cycle(tmp_path: Path) -> None:
    context = complete_synthesis_context(tmp_path)
    projection = materialization(context)
    candidate = build_compatibility_candidate(context, projection, 1)
    descriptor = build_publication_descriptor(context, projection, candidate)
    assert descriptor.compatibility_generation == 1
    assert descriptor.compatibility_index_hash == content_digest(candidate.index_bytes)
    assert descriptor.descriptor_id.encode() not in candidate.index_bytes


def test_crash_between_indexes_recovers_without_invalid_projection(tmp_path: Path) -> None:
    context = complete_synthesis_context(tmp_path)
    crash_publication_at(context, "after_compatibility_index")
    result = recover_protocol_27_publication(context)
    assert result.status == "published_complete"
    assert validate_published_projection(tmp_path)
```

- [ ] **Step 2: Run publication tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_publication.py tests/unit/test_re_v2_publication.py tests/unit/test_re_registry.py`

Expected: collection fails because protocol-2.7 publication composition does not exist.

- [ ] **Step 3: Build the acyclic compatibility candidate, descriptor, and transaction**

Generate existing typed source manifests, workspace manifest, and `PublishedReIndex` fields from materialization authority before creating the descriptor. Use the next compatibility generation, explicit `complete`/`partial` status, exact file hashes, source outcome/debt metadata under the existing `quality.workspace_synthesis` extension point, and `published_from_run`. Hash the canonical candidate index, create the descriptor from that hash/generation, then instantiate `PublicationTransaction` with `workspace_root=registry.root`, the protocol-2.7 staging root and journal, the canonical operation tuple, and `expected_generation=generation`. The candidate must not contain the descriptor ID. Do not call private v1 preparation functions or copy mutable run files directly.

- [ ] **Step 4: Compose both publication commit points under `RePublishLock`**

```python
def publish_protocol_27_generation(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
) -> Protocol27PublicationResult:
    registry = ensure_re_layout(context.workspace_root)
    with RePublishLock.acquire(
        context.workspace_root, context.run_id, context.paths.root.parent
    ):
        try:
            require_creation_bases(context.manifest)
        except Protocol27PublicationConflict:
            return Protocol27PublicationResult.conflict(
                current_publication(context.workspace_root)
            )
        generation = context.manifest.expected_compatibility_generation + 1
        candidate = build_compatibility_candidate(
            context, require_materialization(context), generation
        )
        descriptor = build_publication_descriptor(
            context, require_materialization(context), candidate
        )
        transaction = prepare_compatibility_transaction(
            registry, context, candidate
        )
        write_protocol_27_publication_marker(transaction, descriptor, candidate)
        apply_publication_transaction(transaction, fault_hook=fault_hook)
        retain_transaction_for_protocol_27_commit(transaction)
        try:
            index = publish_generation(
                context.workspace_root,
                context.run_id,
                (descriptor.descriptor_id,),
                context.manifest.synthesis_policy_hash,
                expected_index_hash=context.manifest.expected_v2_index_hash,
                fault_hook=fault_hook,
            )
        except ReV2PublicationConflict:
            rollback_publication_transaction(transaction)
            cleanup_rolled_back_transaction(transaction)
            return Protocol27PublicationResult.conflict(current_publication(context.workspace_root))
        record_protocol_27_publication(context, descriptor, candidate, index)
        finalize_protocol_27_publication(transaction, descriptor, index)
        return Protocol27PublicationResult.published(descriptor, index)
```

`retain_transaction_for_protocol_27_commit()` rewrites the already-installed transaction journal to the valid nonterminal `replacing` status, preserving its installed phases and backups. The canonical protocol-2.7 marker contains the descriptor/candidate identities needed for recovery. The concrete implementation retains those journal/rollback bytes until both indexes and the durable protocol-2.7 publication receipt validate, then marks the journal complete and removes staging before releasing the lock.

- [ ] **Step 5: Implement crash recovery for every transaction/CAS boundary**

Cover marker staging, every `PublicationTransaction` backup/install boundary, compatibility index, retained-journal rewrite, v2 generation temporary/promote, v2 index temporary/replace, publication receipt, journal finalization, and cleanup. On recovery, verify installed bytes against staged digests before completing or rolling back. If both indexes already match, record the missing receipt idempotently and finalize; if the compatibility index matches and the frozen v2 base is still current, finish the v2 CAS; otherwise roll back. Never delete or replace bytes not owned by the journal. Invoke `recover_interrupted_publication()` on marked and unmarked fixtures to prove correct dispatch.

- [ ] **Step 6: Prove old publication contracts remain unchanged**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_publication.py tests/unit/test_re_v2_publication.py tests/unit/test_re_registry.py tests/integration/test_re_publication_flow.py tests/integration/test_re_v2_protocol_27_recovery.py`

Expected: PASS; existing v1 and metadata-only v2 publication fixtures remain byte-identical.

- [ ] **Step 7: Commit recoverable dual publication**

```bash
git add src/harness/re_v2/protocol_27/model.py src/harness/re_v2/protocol_27/publication.py src/harness/re_v2/protocol_27/controller.py src/harness/re_v2/protocol_27/recovery.py src/harness/re_publication.py src/harness/re_registry.py tests/unit/test_re_v2_protocol_27_publication.py tests/unit/test_re_v2_publication.py tests/unit/test_re_registry.py tests/integration/test_re_publication_flow.py tests/integration/test_re_v2_protocol_27_recovery.py
git commit -m "feat(re-v2): publish synthesis generations atomically"
```

---

### Task 12: Wire Lifecycle, Status, Telemetry, and Downstream Consumers

**Files:**
- Create: `src/harness/re_v2/protocol_27/status.py`
- Create: `tests/unit/test_re_v2_protocol_27_status.py`
- Create: `tests/integration/test_re_v2_protocol_27_cli.py`
- Create: `tests/integration/test_re_v2_protocol_27_downstream.py`
- Modify: `src/harness/re_v2/status.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_27/lifecycle.py`
- Test: `tests/unit/test_cli_re_v2_protocol_27.py`

**Interfaces:**
- `protocol_27_status_document(run_dir) -> dict[str, object]` reports exact authority, source/debt/acceptance, artifact/adoption/attempt/resource, synthesis/input/publication states, conflicts, and next action.
- `render_protocol_27_status(run_dir, as_json=False) -> str` renders a prominent terminal banner without conflating partial input with blocked synthesis.
- `execute_protocol_27_request(workspace_root, options, provider_factory) -> Protocol27ControllerResult` finds exact child reuse or creates/initializes/runs one child.
- `echelon re synthesize --from-run <parent-run-id>`, `echelon re continue [run-id]`, and `echelon re status [run-id] [--json]` route schema 6 to protocol 2.7.
- Existing registry/spec/delivery/MemPalace readers consume the same physical paths and explicit complete/partial metadata without special provider behavior.

- [x] **Step 1: Write failing status and CLI lifecycle tests**

```python
def test_partial_input_complete_synthesis_is_not_blocked(tmp_path: Path) -> None:
    run_dir = terminal_protocol_27_run(tmp_path, input_quality="partial")
    document = protocol_27_status_document(run_dir)
    assert document["synthesis_status"] == "complete"
    assert document["input_quality"] == "partial"
    assert document["publication_status"] == "published_partial"
    assert document["full_quality_claim"] == "unavailable"


def test_exact_terminal_continuation_is_byte_stable(tmp_path: Path) -> None:
    run_dir, provider = terminal_protocol_27_run_with_provider(tmp_path)
    before = canonical_run_digests(run_dir)
    invoke_cli(tmp_path, "re", "continue", run_dir.name)
    assert canonical_run_digests(run_dir) == before
    assert provider.call_count == 0


def test_cli_prints_source_specific_partial_command_on_conflict(tmp_path: Path) -> None:
    result = invoke_cli(tmp_path, "re", "status", conflict_run(tmp_path).name)
    assert "--from-run" in result.stdout
    assert "--accept-partial api" in result.stdout
```

- [x] **Step 2: Run lifecycle/status tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_27_status.py tests/unit/test_cli_re_v2_protocol_27.py tests/integration/test_re_v2_protocol_27_cli.py`

Expected: failures because schema-6 status and lifecycle routing do not exist.

- [x] **Step 3: Implement status from authenticated replay only**

Report parent/protocol/schema, accepted complete/partial sources, debt/receipt IDs, required/generated/adopted/failed/unresolved artifacts by scope, origins/dispositions, attempts/retries, known/unknown usage, reservations, active time, avoided calls/reservations, synthesis root, materialization, both publication indexes, and full-quality availability. Derive no count from mutable projections.

- [x] **Step 4: Implement prominent terminal banners and exact actions**

Render exact titles:

```text
RE WORKSPACE SYNTHESIS — COMPLETE
RE WORKSPACE SYNTHESIS — COMPLETE OVER ACCEPTED PARTIAL INPUTS
RE WORKSPACE SYNTHESIS — INCOMPLETE
RE WORKSPACE SYNTHESIS — COMPLETE, PUBLICATION CONFLICT
```

Incomplete names exact unresolved artifacts and `echelon re continue <run-id>`. Conflict names the current run and prints a complete successor `echelon re synthesize --from-run <current-run>` command with every required `--accept-partial` flag. Terminal complete continuation says no action is required.

- [x] **Step 5: Wire CLI creation, exact reuse, continuation, and status**

Keep the v1 `_cmd_re_synthesize` body byte-for-byte where feasible; branch before it only when `--from-run` is present. Load installed Prosaic/runtime through `_installed_re_runtime_or_exit`, instantiate `SquadCliProvider` through the existing config path, and pass a factory into protocol 2.7. Route manifest schema 6 in continue/status without changing old schema routes.

- [x] **Step 6: Prove downstream compatibility**

Publish complete and partial protocol-2.7 generations, then load them through `load_published_index`, published RE context, spec graph, Phase A readiness, delivery context, and MemPalace RE indexing tests. Assert existing paths resolve and explicit partial quality/debt remains visible; no consumer treats partial synthesis as full quality.

Run: `pytest -q tests/unit/test_re_v2_protocol_27_status.py tests/unit/test_cli_re_v2_protocol_27.py tests/integration/test_re_v2_protocol_27_cli.py tests/integration/test_re_v2_protocol_27_downstream.py tests/unit/test_published_re_context.py tests/unit/test_spec_graph.py tests/unit/test_phase_a_readiness.py tests/unit/test_mempalace_re.py`

Expected: PASS.

- [x] **Step 7: Commit lifecycle and downstream integration**

```bash
git add src/harness/re_v2/protocol_27/status.py src/harness/re_v2/protocol_27/lifecycle.py src/harness/re_v2/status.py src/echelon/cli.py tests/unit/test_re_v2_protocol_27_status.py tests/unit/test_cli_re_v2_protocol_27.py tests/integration/test_re_v2_protocol_27_cli.py tests/integration/test_re_v2_protocol_27_downstream.py tests/unit/test_published_re_context.py tests/unit/test_spec_graph.py tests/unit/test_phase_a_readiness.py tests/unit/test_mempalace_re.py
git commit -m "feat(re-v2): expose deferred synthesis lifecycle"
```

---

### Task 13: Complete Fault, Compatibility, Installed Codex, and Documentation Gates

**Files:**
- Create: `tests/fixtures/create_re_v2_protocol_27_pilot.py`
- Create: `tests/integration/test_re_v2_protocol_27_live.py`
- Modify: `tests/unit/test_re_v2_protocol_compatibility.py`
- Modify: `tests/unit/test_re_v2_protocol_26_model.py`
- Modify: `tests/unit/test_re_v2_protocol_26_status.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-08-28-re-v2-deferred-workspace-synthesis-design.md`

**Interfaces:**
- Freezes protocol-2.7 canonical fixtures and proves protocols 2.2 through 2.6 unchanged.
- Adds a deterministic pilot-workspace creator that writes the accepted parent run ID to `<pilot-root>/parent-run-id`.
- Adds an opt-in installed Codex live pilot with recorded run IDs, provider/model/effort observations, generated/adopted counts, trusted/reserved usage, timing, clean-Git evidence, zero-call replay, origin/cache removal, sibling re-export, and one-source incremental recomposition.
- Marks EGR-168 fixed only after every completion criterion has concrete evidence.

- [x] **Step 1: Run the complete focused protocol-2.7 matrix**

Run:

```bash
pytest -q \
  tests/unit/test_re_v2_protocol_27_*.py \
  tests/unit/test_cli_re_v2_protocol_27.py \
  tests/integration/test_re_v2_protocol_27_recovery.py \
  tests/integration/test_re_v2_protocol_27_cli.py \
  tests/integration/test_re_v2_protocol_27_downstream.py
```

Expected: all focused tests pass with the live test excluded by its opt-in condition.

- [x] **Step 2: Run frozen-protocol and v1 compatibility gates**

Run:

```bash
pytest -q \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/unit/test_re_v2_protocol_22_*.py \
  tests/unit/test_re_v2_protocol_24_*.py \
  tests/unit/test_re_v2_protocol_25_*.py \
  tests/unit/test_re_v2_protocol_26_*.py \
  tests/integration/test_re_v2_protocol_22_*.py \
  tests/integration/test_re_v2_protocol_24_*.py \
  tests/integration/test_re_v2_protocol_25_*.py \
  tests/integration/test_re_v2_protocol_26_*.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/integration/test_re_publication_flow.py
git diff --exit-code $(git merge-base HEAD main) -- src/harness/re_v2/protocol_22 src/harness/re_v2/protocol_24 src/harness/re_v2/protocol_25 src/harness/re_v2/protocol_26
```

Expected: all tests pass and frozen protocol directories have no diff.

- [x] **Step 3: Install Echelon and prepare a disposable clean multi-source workspace**

Run:

```bash
bash scripts/install.sh
pilot_root=$(mktemp -d /tmp/echelon-re27-pilot.XXXXXX)
python tests/fixtures/create_re_v2_protocol_27_pilot.py "$pilot_root"
git -C "$pilot_root/source-a" status --short
git -C "$pilot_root/source-b" status --short
```

Expected: the installed version equals the version in `pyproject.toml`; both source status outputs are empty; the fixture records one complete and one explicitly partial accepted parent source and writes its run ID to `$pilot_root/parent-run-id`.

- [x] **Step 4: Run the real Codex synthesis and capture evidence**

Run from the disposable workspace using its configured Codex provider:

```bash
parent_run_id=$(sed -n '1p' "$pilot_root/parent-run-id")
cd "$pilot_root"
echelon re synthesize --from-run "$parent_run_id" \
  --accept-partial source-b \
  --token-limit 2000000 \
  --active-ms-limit 1800000
echelon re status --json > /tmp/re27-first-status.json
```

Expected: synthesis completes, publication is partial, source-a is complete, source-b is explicitly partial, every required artifact is accepted, provider/model/effort observations resolve through Prosaic, and both source repositories remain clean.

Observed: the 2,000,000-token child stopped before the next conservative
reservation with seven accepted artifacts retained and six unresolved. A
5,000,000-token sibling adopted those seven artifacts, generated only the six
missing artifacts, completed, and published the truthful partial result. This
is stronger bounded-exhaustion and sibling-reuse evidence than an unbroken
first-child completion.

- [x] **Step 5: Prove zero-call continuation, sibling adoption, and origin/cache removal**

Record provider dispatch count and event/ledger hashes. Continue the terminal child and assert all remain unchanged. Create an artifact-compatible successor synthesis request against the now-current publication bases and assert every synthesis artifact is adopted with zero charge. Hide the generating origin and `.echelon/re-v2/checkpoints`, continue the adopted child, create another artifact-compatible successor, and assert it reconstructs/re-exports the complete closure with zero calls.

- [x] **Step 6: Prove one-source incremental recomposition**

Create a successor accepted parent in the fixture where only source-a authority changes. Run synthesis again, then compare artifact keys/status: source-b local artifacts and source-b-only workspace-domain summaries are adopted; source-a local artifacts, participating domains, and all workspace-wide artifacts regenerate. Source repositories remain clean.

- [x] **Step 7: Run the full locked-environment suite**

Run: `uv run --extra dev pytest -q`

Expected: all tests pass; only documented opt-in/environment skips and existing warnings remain.

- [x] **Step 8: Record exact evidence and close EGR-168**

Update the design to `Status: Implemented`, add exact focused/compatibility/full test counts, pilot workspace/run IDs, provider/model/effort, generated/adopted/avoided dispatch counts, charged/reserved tokens and active time, replay hashes, publication generations, origin/cache removal result, incremental reuse result, and clean-Git proof. Update `CHANGELOG.md` and mark EGR-168 fixed while leaving EGR-169 L4, EGR-170 atomic repair, and default cutover open.

- [x] **Step 9: Commit final evidence**

```bash
git add tests/fixtures/create_re_v2_protocol_27_pilot.py tests/integration/test_re_v2_protocol_27_live.py tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_protocol_26_model.py tests/unit/test_re_v2_protocol_26_status.py CHANGELOG.md docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-08-28-re-v2-deferred-workspace-synthesis-design.md
git commit -m "test(re-v2): verify deferred workspace synthesis"
```

---

## Completion Gate

Do not declare EGR-168 complete until all of these are true:

- Every selected source has authenticated terminal accepted-root authority before child creation.
- Every partial source has one exact durable source-specific acceptance receipt; no global v2 partial override exists.
- Schema 6 freezes source, debt, synthesis, Prosaic, budget, checkpoint, and both publication-base authorities.
- Source overview bytes are reused from accepted lower-layer materialization without a provider call.
- Source-local, workspace-domain, and workspace artifacts are independently keyed, accepted, and dependency closed.
- Exact sibling checkpoints are adopted before dispatch and consume no attempt or resource budget.
- Missing work uses only the existing Prosaic/shared-provider path with one initial plus one contract-repair attempt maximum.
- Accepted siblings survive artifact failure, exhaustion, crash, continuation, origin removal, and cache removal.
- Run-local materialization reproduces the existing public paths byte-identically from immutable child authority.
- Compatibility files/index and the v2 descriptor/index publish recoverably under the existing lock/transaction/CAS primitives.
- Complete synthesis over partial inputs reports success, retained debt, partial publication, and unavailable full-quality claim.
- Publication conflicts roll back owned compatibility changes and never overwrite newer authority.
- Terminal continuation and fully adopted siblings issue zero provider calls and leave canonical events/ledgers unchanged.
- Existing spec, delivery, MemPalace, registry, and publication consumers resolve the compatibility paths and quality metadata.
- Protocols 2.2 through 2.6 and v1 routing retain exact fixture bytes and behavior.
- The real installed Codex pilot proves generation, adoption, zero-call replay, origin/cache independence, incremental recomposition, truthful telemetry, and clean source Git.
- Focused, compatibility, and full locked-environment test gates pass.
- EGR-169 L4, EGR-170 atomic repair, and default-engine cutover remain explicitly open.
