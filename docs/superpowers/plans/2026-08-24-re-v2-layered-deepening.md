# RE v2 Layered Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship protocol 2.4 as an opt-in `echelon re deepen --to L2` child-run workflow that adopts exact L0/L1 authority and generates only explicitly selected missing L2 work through Echelon's existing Prosaic/shared-provider execution path.

**Architecture:** Add schema-3 lineage and selection authority in a focused `harness.re_v2.protocol_24` package while retaining the protocol-2.2 artifact/work/receipt shapes and generic object, event, ledger, execution-capture, provider, budget, and materialization machinery. Generalize only non-pinned protocol-2.2 routing and validation seams; the installed protocol-2.3 executor/renderer/calculator/normalizer/verifier/partitioner/ownership source bytes remain unchanged.

**Tech Stack:** Python 3.11+, standard-library dataclasses/hashlib/json/fcntl/os/pathlib, existing PyYAML/jsonschema/Typer/pytest dependencies, Prosaic metadata loading, and Echelon's existing `SquadCliProvider` implementations.

**Spec:** `docs/superpowers/specs/2026-08-24-re-v2-layered-deepening-design.md`

## Global Constraints

- Protocol 2.4 uses manifest schema 3; protocols 2.0/2.1 retain schema 1 and protocols 2.2/2.3 retain schema 2 with identical canonical bytes and behavior.
- The layer chain is strictly additive `L0 -> L1 -> L2`; protocol 2.4 registers only `L2` and rejects L3/L4.
- Completed parents remain terminal. Deepening creates a self-contained child and imports the direct parent's complete accepted receipt/object closure.
- Source repositories must be clean and at the exact commits authenticated by the parent snapshot; dirty or changed sources fail before child creation.
- Exactly one selector form is required: `--all` or repeatable `--source`; repeatable `--domain` is valid only with one source and resolves `presentation_domain_id` through `WorkspacePartitionCatalogV1`.
- Every model call uses `ProsaicPromptLoader`, canonical Prosaic bytes, the existing shared CLI executor contract, `SquadCliProvider`, and configured `AICodingCliProvider`; no provider-specific protocol-2.4 branch exists.
- Provider-authored work allows at most two external dispatches: attempt tuple `(2, 2, 0, 1, 1, 1)`. Token/time authorization never raises attempt limits.
- L2 uses the existing compact claim/evidence response envelope and internal `baseline.json` candidate path.
- No semantic audit, workspace synthesis, exhaustive L4 work, semantic repair, whole-domain repair, or atomic repair is part of protocol 2.4.
- Accepted L2 is `semantic_status: unaudited`; completion means only the normalized selected L2 scope is complete.
- No new third-party runtime dependency is introduced.

## File Structure

Create focused protocol-2.4 authority modules and reuse protocol-2.2 substrate modules directly:

```text
src/harness/re_v2/protocol_24/
  __init__.py       protocol/schema constants
  model.py          schema-3 manifest, selection, lineage, parent bundle
  policies.py       combined exact L0/L1/L2 policy catalog builder
  graph.py          selected mixed-goal graph construction over shared work values
  events.py         adoption payload and replay extension over protocol-2.2 events
  adoption.py       parent validation, receipt/object import, provenance bundle
  inputs.py         schema-3 manifest-last input publication/loading
  artifacts.py      L2 evidence/context/root producers over existing value schemas
  status.py         protocol-2.4 status document/banner over shared replay
```

Modify shared, non-pinned seams only where schema/protocol dispatch or additive value validation requires it:

```text
src/harness/re_v2/model.py
src/harness/re_v2/run_store.py
src/harness/re_v2/status.py
src/harness/re_v2/protocol_22/model.py
src/harness/re_v2/protocol_22/policies.py
src/harness/re_v2/protocol_22/graph.py
src/harness/re_v2/protocol_22/inputs.py
src/harness/re_v2/protocol_22/events.py
src/harness/re_v2/protocol_22/budget.py
src/harness/re_v2/protocol_22/ledger.py
src/harness/re_v2/protocol_22/recovery.py
src/harness/re_v2/protocol_22/materialization.py
src/echelon/cli.py
src/echelon/cli_app.py
prosaic/subagents/echelon.re-deepener.md
CHANGELOG.md
docs/findings/echelon-grounded-review-register.md
```

Do not modify source files included by `_re_schema2_installed_registry` implementation digests: `protocol_22/baseline.py`, `cli_provider.py`, `context.py`, `controller.py`, `evidence.py`, `execution.py`, `inventory.py`, `partition.py`, `provider.py`, `response_schemas.py`, or `runtime.py`.

---

### Task 1: Prove the Existing Shared Execution Seam

**Files:**
- Modify: `src/harness/re_v2/protocol_22/model.py`
- Test: `tests/unit/test_re_v2_protocol_22_execution.py`

**Interfaces:**
- Produces: additive `GoalV2` value `selective-deepening` and `LayerV2` value `L2`.
- Proves: an L2 `WorkItemV2` passes unchanged through `SquadCliBaselineExecutor`, `Protocol22ExecutionStore.prepare_execution`, capture, commit, and candidate persistence.

- [x] **Step 1: Write and run the failing L2 shared-execution test**
- [x] **Step 2: Add only the canonical goal/layer validation required by the test**
- [x] **Step 3: Run the seam and compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_protocol_22_execution.py tests/unit/test_re_v2_protocol_22_cli_provider.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: `86 passed` or more, including strict result-envelope and existing candidate-capture assertions.

- [x] **Step 4: Commit**

Commit: `473a1b57 test(re-v2): prove L2 reuses shared execution seam`

---

### Task 2: Schema-3 Manifest, Selection, Lineage, and Exact Dispatch

**Files:**
- Create: `src/harness/re_v2/protocol_24/__init__.py`
- Create: `src/harness/re_v2/protocol_24/model.py`
- Create: `tests/re_v2_protocol_24_fixtures.py`
- Create: `tests/unit/test_re_v2_protocol_24_model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`
- Test: `tests/unit/test_re_v2_run_store.py`

**Interfaces:**
- Produces: `SelectionScopeV1`, `ParentLineageV1`, `AdoptedArtifactAuthorityV1`, `ParentAuthorityBundleV1`, and `RunManifestV3` with strict `to_json_dict`, `from_json_dict`, and digest identity.
- Produces: exact manifest dispatch for `(schema_version=3, engine_protocol_version="2.4")` only.
- Preserves: old schema/protocol pairs and frozen fixture identities.

- [x] **Step 1: Write failing closed-model tests**

```python
def test_schema_3_manifest_round_trips_canonically() -> None:
    manifest = manifest_v3()
    payload = canonical_json_bytes(manifest.to_json_dict())
    assert load_canonical_object(payload, RunManifestV3.from_json_dict) == manifest


def test_selection_rejects_domain_without_exactly_one_source() -> None:
    with pytest.raises(Protocol24SchemaError, match="exactly one source"):
        SelectionScopeV1(1, False, ("api", "web"), ("orders",))


def test_manifest_loader_rejects_schema_3_protocol_23() -> None:
    raw = manifest_v3().to_json_dict()
    raw["engine_protocol_version"] = "2.3"
    with pytest.raises(ReV2RunStoreError, match="schema/protocol"):
        load_run_manifest_bytes(canonical_json_bytes(raw))
```

- [x] **Step 2: Run the model tests and confirm missing protocol-2.4 types**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_model.py tests/unit/test_re_v2_run_store.py`

Expected: collection fails because `harness.re_v2.protocol_24.model` does not exist.

- [x] **Step 3: Implement strict schema-3 values**

Use protocol-2.2 scalar/canonical validators. `RunManifestV3` contains exact fields for the three inherited catalog references plus `parent_authority_bundle`, `parent_lineage`, `target_layer="L2"`, `selection`, `semantic_request_id`, and `initial_budget_policy`. `ParentAuthorityBundleV1.artifacts` is sorted uniquely by `artifact_key_id`; `ancestor_bundle_hashes` is sorted/unique; every hash is a lowercase SHA-256 digest.

- [x] **Step 4: Add exact root model/run-store dispatch**

Add `RE_V2_SCHEMA_3_PROTOCOLS = ("2.4",)` and include `2.4` in supported protocols without changing `RE_V2_SCHEMA_2_PROTOCOLS`. Route schema 3 only to `RunManifestV3.from_json_dict`.

- [x] **Step 5: Run model, run-store, and compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_model.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass and every pre-2.4 digest remains identical.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/model.py src/harness/re_v2/run_store.py \
  src/harness/re_v2/protocol_24 tests/re_v2_protocol_24_fixtures.py \
  tests/unit/test_re_v2_protocol_24_model.py \
  tests/unit/test_re_v2_protocol_compatibility.py tests/unit/test_re_v2_run_store.py
git commit -m "feat(re-v2): add protocol 2.4 manifest authority"
```

---

### Task 3: Combined Artifact Policies and Mixed-Goal Delta Graph

**Files:**
- Create: `src/harness/re_v2/protocol_24/policies.py`
- Create: `src/harness/re_v2/protocol_24/graph.py`
- Create: `tests/unit/test_re_v2_protocol_24_policies.py`
- Create: `tests/unit/test_re_v2_protocol_24_graph.py`
- Modify: `src/harness/re_v2/protocol_22/model.py`
- Modify: `src/harness/re_v2/protocol_22/policies.py`
- Modify: `src/harness/re_v2/protocol_22/graph.py`

**Interfaces:**
- Produces: `build_deepening_v1_policy_catalog() -> ArtifactPolicyCatalogV1` containing the exact inherited L0/L1 entries plus L2 domain-evidence, domain-context, domain-baseline, source-context, source-overview, and source-root entries.
- Produces: `Protocol24Graph` and `build_protocol_24_graph(manifest, inputs, accepted_parent) -> Protocol24Graph` using existing `ArtifactScope`, `WorkTemplateV2`, and `WorkItemV2` identities.
- Produces: `plan_next_v2(graph, authority, budget) -> PlanDecisionV2`; `plan_next_v22` remains a compatibility facade.

- [x] **Step 1: Write failing policy tests for exact L2 slots and limits**

Assert the combined catalog includes inherited hashes unchanged and L2 limits of 160 KiB/163,840 tokens for domain context, 128 KiB/131,072 tokens for source context, and 64 KiB authorial JSON for both provider artifacts.

- [x] **Step 2: Write failing graph tests for selected closure**

```python
def test_domain_selection_plans_only_selected_l2_delta() -> None:
    graph, authority, budget = deepening_graph_fixture(source="api", domains=("orders",))
    decision = plan_next_v2(graph, authority, budget)
    assert {item.output_key.layer for item in decision.ready} == {"L2"}
    assert {item.output_key.scope.domain_key for item in decision.ready} == {digest("orders-domain")}
```

Also assert imported L0/L1 template/work identities remain exact, unrelated domains are absent from required outputs, source roots are selection-relative, L3/L4 are rejected, and duplicate exact claims cannot be represented as new dependencies.

- [x] **Step 3: Run policy/graph tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_policies.py tests/unit/test_re_v2_protocol_24_graph.py`

Expected: failure because protocol-2.4 catalog/graph builders are absent.

- [x] **Step 4: Generalize shared value validation additively**

Permit L2 only for the registered artifact kinds. Refactor policy validation to key by `(layer, artifact_kind)` while preserving every L0/L1 entry byte. Extract the body of `plan_next_v22` into `plan_next_v2` against a structural graph interface; keep `plan_next_v22`'s existing type/error behavior before delegation.

- [x] **Step 5: Implement the combined catalog and selected graph**

The graph includes exact imported prerequisite templates with their original `inventory`/`baseline` goals and adds only selected L2 templates with `selective-deepening`. Dependencies bind accepted parent artifact hashes through `instantiate_work_item_v2`; accepted exact keys plan as `reuse`.

- [x] **Step 6: Run old and new policy/graph matrices**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_protocol_22_policies.py tests/unit/test_re_v2_protocol_22_graph.py tests/unit/test_re_v2_protocol_24_policies.py tests/unit/test_re_v2_protocol_24_graph.py`

Expected: all pass.

- [x] **Step 7: Commit**

```bash
git add src/harness/re_v2/protocol_22/model.py \
  src/harness/re_v2/protocol_22/policies.py src/harness/re_v2/protocol_22/graph.py \
  src/harness/re_v2/protocol_24/policies.py src/harness/re_v2/protocol_24/graph.py \
  tests/unit/test_re_v2_protocol_22_model.py \
  tests/unit/test_re_v2_protocol_22_policies.py \
  tests/unit/test_re_v2_protocol_22_graph.py \
  tests/unit/test_re_v2_protocol_24_policies.py \
  tests/unit/test_re_v2_protocol_24_graph.py
git commit -m "feat(re-v2): plan selected L2 deltas"
```

---

### Task 4: Parent Validation and Self-Contained Receipt Adoption

**Files:**
- Create: `src/harness/re_v2/protocol_24/adoption.py`
- Create: `tests/unit/test_re_v2_protocol_24_adoption.py`
- Modify: `src/harness/re_v2/protocol_22/ledger.py`

**Interfaces:**
- Produces: `validate_parent_for_deepening(parent_run: Path, workspace: Path) -> ValidatedParentV1`.
- Produces: `build_parent_authority_bundle(parent: ValidatedParentV1) -> tuple[ParentAuthorityBundleV1, Mapping[str, bytes]]`.
- Produces: `import_parent_acceptance_closure(parent, child_objects, child_ledger) -> AdoptionReportV1` using existing certification, candidate-assessment, and artifact-acceptance append methods.

- [x] **Step 1: Write failing parent and adoption tests**

Cover complete schema-2 parent success; nonterminal/failed/partial rejection; dirty Git rejection with commit/stash/revert guidance; commit mismatch; symlink/path escape; corrupt event/ledger chains; missing receipt/object/dependency; cyclic schema-3 lineage; and successful replay after deleting the parent.

- [x] **Step 2: Run adoption tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_adoption.py`

Expected: collection fails because the adopter is absent.

- [ ] **Step 3: Implement stable parent reads and bundle construction**

Resolve beneath `runs/`, load exact manifest/events/ledger, require exactly one `run_completed`, verify current clean-Git composite commits against the snapshot, copy direct parent manifest/event/ledger bytes once, and recursively copy schema-3 ancestor bundle objects. Use stable-stat/no-follow helpers already used by snapshot and object stores.

- [x] **Step 4: Import exact typed receipt closure**

For each accepted artifact in sorted key order, copy every schema-aware referenced object, then append its existing certification/work item, optional candidate assessment, and artifact acceptance receipt through `Protocol22Ledger`. Add a read-only ledger-history accessor rather than parsing ledger JSON independently.

- [x] **Step 5: Run adoption and ledger regression tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_adoption.py tests/unit/test_re_v2_protocol_22_ledger.py`

Expected: all pass and nested receipt identities match the parent.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_24/adoption.py \
  src/harness/re_v2/protocol_22/ledger.py \
  tests/unit/test_re_v2_protocol_24_adoption.py \
  tests/unit/test_re_v2_protocol_22_ledger.py
git commit -m "feat(re-v2): adopt certified parent authority"
```

---

### Task 5: Schema-3 Input Publication and Child Creation

**Files:**
- Create: `src/harness/re_v2/protocol_24/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_24_inputs.py`
- Modify: `src/harness/re_v2/protocol_22/inputs.py`
- Test: `tests/unit/test_re_v2_protocol_22_inputs.py`

**Interfaces:**
- Produces: `Protocol24InputSet`, `ValidatedProtocol24Inputs`, `create_protocol_24_run_store`, and `load_protocol_24_inputs`.
- Reuses: one extracted manifest-last publication primitive shared with `create_protocol_22_run_store`.

- [x] **Step 1: Write failing manifest-last and fault-boundary tests**

Assert objects/catalogs precede the manifest, existing files are no-clobber, incomplete stores are detected, symlinks are rejected, and every fault hook leaves either no manifest or a fully loadable immutable input set.

- [x] **Step 2: Run input tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_inputs.py`

Expected: collection fails because schema-3 input publication is absent.

- [x] **Step 3: Extract the schema-neutral publication helper**

Keep protocol-2.2 public APIs and fault labels stable. The helper accepts prepared named catalog payloads, immutable blobs, and canonical manifest bytes, and performs the existing directory creation, object publication, new-file writes, fsyncs, and manifest-last link.

- [x] **Step 4: Implement schema-3 publication/loading**

Publish workspace partition, combined artifact policy, executor contract, and parent authority bundle references. Authenticate all four before graph construction or dispatch.

- [x] **Step 5: Run old/new input tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_inputs.py tests/unit/test_re_v2_protocol_24_inputs.py`

Expected: all pass with unchanged protocol-2.2 fixtures.

- [x] **Step 6: Commit**

```bash
git add src/harness/re_v2/protocol_22/inputs.py \
  src/harness/re_v2/protocol_24/inputs.py \
  tests/unit/test_re_v2_protocol_22_inputs.py \
  tests/unit/test_re_v2_protocol_24_inputs.py
git commit -m "feat(re-v2): publish schema 3 child runs"
```

---

### Task 6: Protocol-2.4 Events, Budget Replay, and Shared Controller Composition

**Files:**
- Create: `src/harness/re_v2/protocol_24/events.py`
- Create: `tests/unit/test_re_v2_protocol_24_events.py`
- Create: `tests/integration/test_re_v2_protocol_24_controller.py`
- Modify: `src/harness/re_v2/protocol_22/budget.py`
- Modify: `src/harness/re_v2/protocol_22/recovery.py`

**Interfaces:**
- Produces: `PROTOCOL_24_EVENTS`, accepting `artifact_adopted` only after `run_created` and before provider dispatch for that imported work item.
- Produces: protocol-selectable budget replay that ignores deterministic adoption events and preserves existing accounting.
- Produces: a protocol-2.4 run context accepted by unchanged `Protocol22Controller` and unchanged `Protocol22ExecutionStore`.

- [ ] **Step 1: Write failing adoption-event replay tests**

Assert exact payload fields, canonical bytes, duplicate adoption rejection, adoption-after-dispatch rejection, terminal immutability, and protocol-2.2 rejection of protocol-2.4 event history.

- [ ] **Step 2: Write a failing controller-composition test**

Create a child with imported L0/L1 receipts and one L2 provider item, execute through unchanged `Protocol22Controller`, and assert the shared executor receives exactly one dispatch and the run reaches `run_completed`.

- [ ] **Step 3: Run event/controller tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_events.py tests/integration/test_re_v2_protocol_24_controller.py`

Expected: failure because protocol-2.4 replay/context routing is absent.

- [ ] **Step 4: Implement event delegation without copying schemas**

Delegate common payload canonicalization and replay transitions to `PROTOCOL_22_EVENTS`; handle only `artifact_adopted` in the protocol-2.4 wrapper. Generalize budget/recovery functions to accept the context's selected event protocol while keeping protocol-2.2 defaults exact.

- [ ] **Step 5: Compose the unchanged controller/execution path**

Broaden non-pinned recovery/context nominal checks to the authenticated schema-3 inputs and mixed-goal graph. Do not edit `protocol_22/controller.py` or `protocol_22/execution.py`.

- [ ] **Step 6: Run old/new event, budget, recovery, and controller tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_events.py tests/unit/test_re_v2_protocol_22_budget.py tests/unit/test_re_v2_protocol_22_recovery.py tests/unit/test_re_v2_protocol_24_events.py tests/integration/test_re_v2_protocol_22_controller.py tests/integration/test_re_v2_protocol_24_controller.py`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/harness/re_v2/protocol_24/events.py \
  src/harness/re_v2/protocol_22/budget.py \
  src/harness/re_v2/protocol_22/recovery.py \
  tests/unit/test_re_v2_protocol_24_events.py \
  tests/integration/test_re_v2_protocol_24_controller.py
git commit -m "feat(re-v2): compose L2 with shared controller"
```

---

### Task 7: L2 Deterministic Context, Roots, Policy Certification, and Prosaic Role

**Files:**
- Create: `prosaic/subagents/echelon.re-deepener.md`
- Create: `src/harness/re_v2/protocol_24/artifacts.py`
- Create: `tests/unit/test_re_v2_protocol_24_artifacts.py`
- Create: `tests/unit/test_re_v2_protocol_24_prosaic.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_re_v2_protocol_22_baseline.py`
- Test: `tests/unit/test_re_v2_protocol_22_context.py`

**Interfaces:**
- Produces: deterministic L2 targeted domain evidence/context and selection-relative source context/root using existing artifact value schemas.
- Produces: installed authority entry for `echelon.re-deepener` loaded by `ProsaicPromptLoader.load_subagent` and canonicalized by `canonical_prosaic_agent_bytes`.
- Reuses: existing compact response schema, candidate parser, certification receipts, renderer, CLI adapter, reservation calculator, and usage normalizer.

- [ ] **Step 1: Write failing L2 artifact/policy tests**

Assert selected evidence comes only from the immutable snapshot; omitted/debt descriptors are exact; domain/source context bounds are enforced; source roots bind exact selected domains; exact L1 claim/evidence duplicates are rejected; insufficient evidence becomes unknown; accepted L2 remains unaudited.

- [ ] **Step 2: Write failing Prosaic authority tests**

Assert frontmatter includes `model_tier: strong`, `effort: high`, write-only tools, neutral provider metadata, and that the exact inspected bytes enter the executor catalog without provider-name branching.

- [ ] **Step 3: Run artifact/Prosaic tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_artifacts.py tests/unit/test_re_v2_protocol_24_prosaic.py`

Expected: failures for missing L2 policy/role integration.

- [ ] **Step 4: Implement L2 using existing producers and certifier contracts**

Add additive layer-policy branches and producer registry entries outside pinned authority files. Supply L2 context/policy to the unchanged provider executor. Reuse `CompactCertificationAssessmentV2`, `CertificationReceiptV2`, `CandidateAssessmentReceiptV1`, and `ArtifactAcceptanceReceiptV2`.

- [ ] **Step 5: Add and load the neutral deepener role**

The prose accepts only the pinned context and writes only `baseline.json`; it never discovers source files, invokes tools outside the candidate workspace, emits provider-specific controls, performs semantic audit, or requests repair.

- [ ] **Step 6: Run old/new artifact, baseline, provider, and Prosaic tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_22_context.py tests/unit/test_re_v2_protocol_22_baseline.py tests/unit/test_re_v2_protocol_22_cli_provider.py tests/unit/test_re_v2_protocol_24_artifacts.py tests/unit/test_re_v2_protocol_24_prosaic.py`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add prosaic/subagents/echelon.re-deepener.md \
  src/harness/re_v2/protocol_24/artifacts.py src/echelon/cli.py \
  tests/unit/test_re_v2_protocol_24_artifacts.py \
  tests/unit/test_re_v2_protocol_24_prosaic.py \
  tests/unit/test_re_v2_protocol_22_baseline.py \
  tests/unit/test_re_v2_protocol_22_context.py
git commit -m "feat(re-v2): add Prosaic L2 deepening artifacts"
```

---

### Task 8: `echelon re deepen` CLI, Clean Preflight, and Idempotent Child Resolution

**Files:**
- Create: `tests/unit/test_cli_re_v2_protocol_24.py`
- Create: `tests/integration/test_re_v2_protocol_24_cli.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Produces: CLI grammar `echelon re deepen --to L2 (--all | --source ID...) [--domain ID...] [--from-run ID] [--token-limit N] [--active-ms-limit N]`.
- Produces: `semantic_request_id_for(lineage_root, snapshot, selection, target, policy_hash) -> str`.
- Reuses: `resolve_current_re_run`, `_new_re_v2_run_id`, `_activate_re_v2_run`, workspace configuration, and partition descriptors.

- [ ] **Step 1: Write failing parser/validation tests**

Cover required target/selection; mutual exclusions; duplicate selectors; unknown source/domain; multi-source domain rejection; `presentation_domain_id` resolution; `--all`; unregistered L3/L4; V1 flag rejection; positive resource values; explicit/current parent resolution.

- [ ] **Step 2: Write failing creation/idempotency tests**

Assert preflight creates no run/pointer on dirty/changed/nonterminal parents; same semantic request returns complete/running/paused child; token/time changes authorize the same child; concurrent creation yields one child; active pointer updates last.

- [ ] **Step 3: Run CLI tests and confirm RED**

Run: `pytest -q tests/unit/test_cli_re_v2_protocol_24.py tests/integration/test_re_v2_protocol_24_cli.py`

Expected: parser rejects unknown `deepen` command.

- [ ] **Step 4: Implement parser and deterministic selection**

Resolve source/domain values solely through `WorkspacePartitionCatalogV1`. Use one no-follow `flock` creation lock around semantic-child scan, ID allocation, child publication, and pointer activation.

- [ ] **Step 5: Implement child creation and execution routing**

Validate/adopt parent, build immutable inputs/manifest, publish manifest last, append `run_created` and adoption events/imported receipts, validate projection, activate last, then invoke the shared controller.

- [ ] **Step 6: Run old/new lifecycle and CLI tests**

Run: `pytest -q tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_v2_protocol_24.py tests/integration/test_re_v2_protocol_24_cli.py`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/cli.py src/echelon/cli_app.py \
  tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_v2_protocol_24.py \
  tests/integration/test_re_v2_protocol_24_cli.py
git commit -m "feat(cli): add selective RE v2 deepening"
```

---

### Task 9: L2 Materialization, Status, Banners, and Telemetry

**Files:**
- Create: `src/harness/re_v2/protocol_24/status.py`
- Create: `tests/unit/test_re_v2_protocol_24_status.py`
- Modify: `src/harness/re_v2/status.py`
- Modify: `src/harness/re_v2/protocol_22/materialization.py`
- Test: `tests/unit/test_re_v2_protocol_22_materialization.py`

**Interfaces:**
- Produces: protocol-2.4 routing from `render_v2_status`.
- Produces: exact human banners `L2 SELECTED SCOPE COMPLETE`, `L2 PAUSED - CONTINUABLE`, and `L2 BLOCKED - REQUESTED OUTPUTS INCOMPLETE`.
- Produces: additive L2 materialized paths below `materialized/L2` using existing locks/quarantine/publication.

- [ ] **Step 1: Write failing status/materialization tests**

Assert lineage, selection, adopted/generated/reused counts, per-domain state, intentionally unselected counts, selected-domain coverage, attempts/resources, trusted usage, exact next action, no full-quality claim, and byte-identical rebuild/quarantine behavior.

- [ ] **Step 2: Run status/materialization tests and confirm RED**

Run: `pytest -q tests/unit/test_re_v2_protocol_24_status.py tests/unit/test_re_v2_protocol_22_materialization.py`

Expected: protocol-2.4 status is unsupported.

- [ ] **Step 3: Extend materialization cases without a second framework**

Parameterize registered layer/kind path specifications while retaining exact L1 paths/bytes. Materialize L2 deltas and selection-relative roots only from accepted objects/receipts.

- [ ] **Step 4: Implement protocol-routed status and telemetry**

Replay immutable manifest/inputs, protocol-2.4 events, ledger, budget, graph, and materialization. Derive all counts; do not persist a status cache.

- [ ] **Step 5: Run old/new status/materialization suites**

Run: `pytest -q tests/unit/test_re_v2_status.py tests/unit/test_re_v2_protocol_22_status.py tests/unit/test_re_v2_protocol_22_materialization.py tests/unit/test_re_v2_protocol_24_status.py`

Expected: all pass and old banners remain exact.

- [ ] **Step 6: Commit**

```bash
git add src/harness/re_v2/status.py \
  src/harness/re_v2/protocol_22/materialization.py \
  src/harness/re_v2/protocol_24/status.py \
  tests/unit/test_re_v2_protocol_22_materialization.py \
  tests/unit/test_re_v2_protocol_24_status.py
git commit -m "feat(re-v2): report and materialize selected L2"
```

---

### Task 10: Crash Matrix, Compatibility Gate, Documentation, and Installed Pilot

**Files:**
- Create: `tests/integration/test_re_v2_protocol_24_recovery.py`
- Create: `tests/integration/test_re_v2_protocol_24_live.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/plans/2026-08-24-re-v2-layered-deepening.md`

**Interfaces:**
- Proves: every adoption/dispatch/capture/certification/acceptance/terminal fault boundary converges without duplicate external execution.
- Proves: repeated and unrelated deepening performs zero unnecessary provider calls.
- Proves: installed Codex-provider execution leaves all source repositories clean.

- [ ] **Step 1: Write the recovery fault matrix**

Inject faults after object/bundle/receipt/event publication, lease/start/observation/candidate/commit/certification/acceptance, terminal event, and pointer activation. Resume twice and assert one provider call per dispatch ID and exact accepted receipt identities.

- [ ] **Step 2: Run focused protocol-2.4 and compatibility tests**

Run: `pytest -q tests/unit/test_re_v2_protocol_24*.py tests/unit/test_cli_re_v2_protocol_24.py tests/integration/test_re_v2_protocol_24*.py tests/unit/test_re_v2_protocol_compatibility.py`

Expected: all pass.

- [ ] **Step 3: Run the complete RE v2 matrix**

Run: `pytest -q tests/unit/test_re_v2*.py tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_cli_re_v2_protocol_24.py tests/integration/test_re_v2*.py tests/contract/test_re_v2_bounded_api.py`

Expected: all pass.

- [ ] **Step 4: Run the complete repository suite**

Run: `pytest`

Expected: zero failures.

- [ ] **Step 5: Install and migrate a disposable real workspace**

Run: `bash scripts/install.sh`, then run normal workspace Prosaic migration before the pilot. Verify installed `echelon.re-deepener` bytes equal the repository source.

- [ ] **Step 6: Run the real Codex pilot**

On a disposable clean real workspace with `harness.llm.cli: codex`, create/reuse L0/L1, deepen one source/domain, repeat it for zero dispatch, deepen a second scope, and verify the first L2 artifact is adopted. Capture status, events, ledger, parent bundle, provider observations, token/active usage, and `git status --short` for every source.

- [ ] **Step 7: Update docs and finding state from evidence**

Record the shipped command, supported protocol/schema, truthful completion semantics, test counts, pilot run IDs, provider/model observations, usage, zero-dispatch reuse, and any remaining EGR-169 limits. Mark EGR-169 resolved only if every completion criterion is proven.

- [ ] **Step 8: Commit**

```bash
git add tests/integration/test_re_v2_protocol_24_recovery.py \
  tests/integration/test_re_v2_protocol_24_live.py CHANGELOG.md \
  docs/findings/echelon-grounded-review-register.md \
  docs/superpowers/plans/2026-08-24-re-v2-layered-deepening.md
git commit -m "feat(re-v2): complete selective L2 deepening"
```
