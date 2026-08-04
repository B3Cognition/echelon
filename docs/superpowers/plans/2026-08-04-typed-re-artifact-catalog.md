# Typed RE Artifact Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish every durable reverse-engineering output with one canonical typed descriptor and make context, MemPalace, and graph consumers use that descriptor model.

**Architecture:** Add a focused `harness.re_artifacts` module that owns the descriptor schema, kind taxonomy, deterministic catalog construction, and validation. `re/index.json` types source/workspace manifests; each manifest types its child artifacts. Existing named fields and path inference remain legacy fallback, while current consumers receive normalized descriptors from `re_registry`.

**Tech Stack:** Python 3, dataclasses, `pathlib`, SHA-256, JSON, pytest, existing Echelon RE registry/publication and MemPalace adapters.

## Global Constraints

- `re/index.json` remains the trust root and is not self-described.
- Every other published artifact has exactly one canonical descriptor.
- Descriptor fields are `kind`, `path`, `sha256`, `scope`, and source-only `source_id`.
- Supported scopes are exactly `source` and `workspace`.
- Existing named manifest fields remain emitted and readable.
- Typed catalogs are authoritative when present; path inference is legacy fallback only.
- Large evidence such as `re-codegraph-analysis` is registered but remains excluded from prompt and memory policy by default.
- Canonical `re-context.json` remains an immutable path/hash snapshot.
- Historical specs without `re-context.json` are not retroactively attached to RE.

---

### Task 1: Define The Typed Descriptor Contract

**Files:**
- Create: `src/harness/re_artifacts.py`
- Create: `tests/unit/test_re_artifacts.py`

**Interfaces:**
- Produces: `ReArtifactDescriptor(kind: str, path: str, sha256: str, scope: str, source_id: str | None)`.
- Produces: `build_re_artifact_catalog(directory: Path, *, published_prefix: PurePosixPath, scope: str, source_id: str | None = None) -> tuple[ReArtifactDescriptor, ...]`.
- Produces: `validate_re_artifact_descriptor(raw: object, *, workspace_root: Path, owner_scope: str, owner_source_id: str | None = None) -> ReArtifactDescriptor`.
- Produces: `classify_re_artifact(relative_path: PurePosixPath, *, scope: str) -> str`.

- [ ] **Step 1: Write failing descriptor and catalog tests**

Cover deterministic path ordering, all kinds in the approved taxonomy, source/workspace ownership, lowercase `sha256:<hex>` output, nested ADRs/specs/checklists, and exclusion of `manifest.json` from its own child catalog.

```python
def test_build_source_catalog_types_every_child(tmp_path: Path) -> None:
    source = tmp_path / "published"
    _write_current_source_outputs(source)
    rows = build_re_artifact_catalog(
        source,
        published_prefix=PurePosixPath("re/sources/api"),
        scope="source",
        source_id="api",
    )
    assert [(row.kind, row.path) for row in rows] == [
        ("re-decision", "re/sources/api/adrs/ADR-001.md"),
        ("re-analysis", "re/sources/api/analysis.json"),
        ("re-architecture", "re/sources/api/architecture.md"),
        ("re-codegraph-analysis", "re/sources/api/codegraph-analysis.json"),
        ("re-codegraph-summary", "re/sources/api/codegraph-summary.json"),
        ("re-components", "re/sources/api/components.md"),
        ("re-configs", "re/sources/api/configs.json"),
        ("re-contracts", "re/sources/api/contracts.md"),
        ("re-dependencies", "re/sources/api/dependencies.json"),
        ("re-domain-manifest", "re/sources/api/domain-manifest.json"),
        ("re-overview", "re/sources/api/overview.md"),
        ("re-generated-checklist", "re/sources/api/specs/001-api/checklist.md"),
        ("re-generated-spec", "re/sources/api/specs/001-api/spec.md"),
        ("re-structure", "re/sources/api/structure.json"),
        ("re-supporting-artifacts", "re/sources/api/supporting-artifacts.md"),
    ]
    assert all(row.source_id == "api" for row in rows)
```

- [ ] **Step 2: Run the tests and confirm the contract is absent**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_artifacts.py`

Expected: FAIL because `harness.re_artifacts` does not exist.

- [ ] **Step 3: Implement the descriptor module**

Use one explicit `SUPPORTED_RE_ARTIFACT_KINDS` set and deterministic path rules. Reject unknown suffixes instead of inventing a generic kind. Validate normalized `re/...` paths, file existence, digest equality, scope/path consistency, and exact source ownership. `ReArtifactDescriptor.to_json_dict()` omits `source_id` for workspace scope.

```python
@dataclass(frozen=True)
class ReArtifactDescriptor:
    kind: str
    path: str
    sha256: str
    scope: str
    source_id: str | None = None

    def to_json_dict(self) -> dict[str, str]:
        payload = {
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "scope": self.scope,
        }
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        return payload
```

- [ ] **Step 4: Add invalid-descriptor tests and make them pass**

Parametrize duplicate paths, traversal, absolute paths, wrong scope prefix, missing/extra `source_id`, unsupported kind, missing file, non-lowercase hash, and content hash mismatch. The catalog validator must raise `ReArtifactCatalogError` with a stable reason phrase for each case.

- [ ] **Step 5: Run focused tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_artifacts.py`

Expected: PASS.

- [ ] **Step 6: Commit the descriptor contract**

```bash
git add src/harness/re_artifacts.py tests/unit/test_re_artifacts.py
git commit -m "feat(re): define typed artifact descriptors"
```

### Task 2: Emit Typed Catalogs During Publication

**Files:**
- Modify: `src/harness/re_publication.py`
- Modify: `src/harness/re_registry.py`
- Modify: `tests/unit/test_re_publication.py`

**Interfaces:**
- Consumes: `build_re_artifact_catalog(...)` and `ReArtifactDescriptor.to_json_dict()` from Task 1.
- Produces: source/workspace manifest `artifacts` arrays.
- Produces: index `manifest_artifact` objects for every source and the workspace.
- Extends: `PublishedSource.manifest_artifact: ReArtifactDescriptor | None` and `PublishedWorkspace.manifest_artifact: ReArtifactDescriptor | None` for compatibility.

- [ ] **Step 1: Add a failing publication-shape test**

Publish the existing comprehensive fixture and assert:

```python
source_manifest = _read_json(root / "re/sources/api/manifest.json")
assert source_manifest["artifacts"] == sorted(
    source_manifest["artifacts"], key=lambda row: row["path"]
)
assert _descriptor(source_manifest, "re/sources/api/architecture.md")["kind"] == "re-architecture"
assert _descriptor(source_manifest, "re/sources/api/adrs/ADR-001-source-boundary.md")["kind"] == "re-decision"

index = _read_json(root / "re/index.json")
assert index["sources"]["api"]["manifest_artifact"]["kind"] == "re-source-manifest"
assert index["workspace"]["manifest_artifact"]["kind"] == "re-workspace-manifest"
```

Also assert the descriptor inventory equals every durable file below the owning directory except `manifest.json`.

- [ ] **Step 2: Run the publication test and confirm it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_publication.py -k typed_artifact_catalog`

Expected: FAIL because no `artifacts` or `manifest_artifact` fields are emitted.

- [ ] **Step 3: Build source catalogs before writing source manifests**

In `_prepare_transaction`, copy all durable source children first, call `build_re_artifact_catalog` on `durable_source`, pass `[row.to_json_dict() ...]` into `_source_manifest`, write the manifest, then calculate its descriptor for the index source record. Preserve reused source descriptors through `source_id_to_json`.

- [ ] **Step 4: Build the workspace catalog and manifest descriptor**

After workspace synthesis is copied, build the workspace child catalog excluding `manifest.json`, write `workspace/manifest.json`, compute its `re-workspace-manifest` descriptor, and include it in the index workspace object. Existing `manifest`, `overview`, `relationships`, `contracts`, and `codegraph_summary` strings remain unchanged.

- [ ] **Step 5: Validate publication-time catalog completeness**

Extend publication validation so refreshed, empty, reused, and partial sources all have exactly one descriptor per durable child. Verify every descriptor against staged bytes before transaction replacement. Add tests proving omitted files, duplicate paths, unsupported kinds, and modified bytes block publication atomically.

- [ ] **Step 6: Run publication and recovery tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_publication.py tests/unit/test_re_publication_lock.py tests/unit/test_re_publication_recovery.py`

Expected: PASS.

- [ ] **Step 7: Commit typed publication emission**

```bash
git add src/harness/re_publication.py src/harness/re_registry.py tests/unit/test_re_publication.py
git commit -m "feat(re): publish typed artifact catalogs"
```

### Task 3: Normalize Typed And Legacy Registry Reads

**Files:**
- Modify: `src/harness/re_registry.py`
- Modify: `tests/unit/test_re_registry.py`
- Modify: `tests/unit/test_published_re_context.py`

**Interfaces:**
- Consumes: `validate_re_artifact_descriptor(...)` from Task 1.
- Produces: `canonical_re_artifact_descriptors(workspace_root: Path, index: PublishedReIndex) -> tuple[ReArtifactDescriptor, ...]`.
- Preserves: `canonical_re_artifacts(...) -> dict[str, object]` as a compatibility projection.

- [ ] **Step 1: Add failing typed-registry tests**

Create a typed publication fixture and assert the normalized API returns every descriptor once, sorted by path. Corrupt each ownership layer and assert `ReRegistryError`: missing `manifest_artifact`, mixed typed/untyped child catalog, duplicate child path, manifest descriptor hash mismatch, and source ID mismatch.

- [ ] **Step 2: Add a legacy compatibility test**

Keep the current schema-version-1 fixture without descriptor fields and assert `canonical_re_artifact_descriptors` produces equivalent inferred descriptors while `canonical_re_artifacts` retains all current keys and briefing inputs.

- [ ] **Step 3: Run the registry tests and confirm failures**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_registry.py tests/unit/test_published_re_context.py`

Expected: FAIL on the new normalized API and strict typed-catalog cases.

- [ ] **Step 4: Implement normalized loading**

Treat a publication as typed only when the workspace and every source index entry contain `manifest_artifact`. For typed publications, validate manifest descriptors first and then require each manifest to contain an `artifacts` array. Do not mix inferred child rows into a typed owner. For legacy publications, run the current named-field/path discovery through `classify_re_artifact` and calculate hashes from durable bytes.

- [ ] **Step 5: Project normalized descriptors into the legacy artifact map**

Refactor `canonical_re_artifacts` to group normalized rows by kind and scope while preserving existing keys such as `re_contexts`, `re_specs`, `source_architecture`, `source_contracts`, `source_components`, `source_adrs`, and CodeGraph collections. Add `artifact_descriptors` as serialized descriptors for new consumers.

- [ ] **Step 6: Run registry and context tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_registry.py tests/unit/test_published_re_context.py tests/unit/test_squad_re_context.py tests/unit/test_spec_re_decoupling.py`

Expected: PASS, with existing bounded briefing assertions unchanged.

- [ ] **Step 7: Commit normalized registry consumption**

```bash
git add src/harness/re_registry.py tests/unit/test_re_registry.py tests/unit/test_published_re_context.py
git commit -m "feat(re): normalize typed artifact registry"
```

### Task 4: Drive Context Selection From Descriptor Policy

**Files:**
- Modify: `src/harness/published_re_context.py`
- Modify: `src/harness/re_materializer.py`
- Modify: `tests/unit/test_published_re_context.py`
- Modify: `tests/unit/test_re_materializer.py`

**Interfaces:**
- Consumes: `canonical_re_artifact_descriptors(...)` and existing selected source IDs.
- Preserves: canonical `re-context.json` row schema `{path, hash}`.
- Produces: run-local snapshots and rendered briefings selected by descriptor kind/scope.

- [ ] **Step 1: Add failing policy tests**

Build a typed fixture containing every kind. Assert target-selected source briefings include overview, architecture, contracts, components, ADRs, CodeGraph summary, domain manifest, and generated specs/checklists; workspace briefing policy includes current workspace context and decisions. Assert `re-codegraph-analysis`, raw analysis, structure, configs, dependencies, and quality evidence remain registered but are absent from rendered briefing files.

- [ ] **Step 2: Run focused tests and confirm path-driven behavior fails the new assertions**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_published_re_context.py tests/unit/test_re_materializer.py`

- [ ] **Step 3: Implement explicit context policy sets**

Define named immutable sets such as `SOURCE_BRIEFING_KINDS`, `WORKSPACE_BRIEFING_KINDS`, and `REGISTERED_ONLY_KINDS`. Select artifacts by descriptor scope/kind and selected source IDs. Snapshot only policy-selected context artifacts plus the manifests required for provenance. Continue writing only path/hash rows to canonical `re-context.json`.

- [ ] **Step 4: Preserve materialized compatibility output**

Expose serialized `artifact_descriptors` in the run materializer while retaining all existing artifact-map keys. Ensure prompts still receive rendered briefing contents, never the descriptor JSON as a substitute for content.

- [ ] **Step 5: Run context and prompt tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_published_re_context.py tests/unit/test_re_materializer.py tests/unit/test_squad_re_context.py tests/unit/test_spec_re_decoupling.py tests/unit/test_structural_wiring.py`

Expected: PASS.

- [ ] **Step 6: Commit descriptor-driven context selection**

```bash
git add src/harness/published_re_context.py src/harness/re_materializer.py tests/unit/test_published_re_context.py tests/unit/test_re_materializer.py
git commit -m "feat(re): select context from artifact descriptors"
```

### Task 5: Drive MemPalace Mining From Descriptor Kinds

**Files:**
- Modify: `src/echelon/mempalace_re.py`
- Modify: `src/echelon/spec_memory_miner.py`
- Modify: `tests/unit/test_mempalace_re.py`

**Interfaces:**
- Consumes: `canonical_re_artifact_descriptors(...)`.
- Preserves: `load_re_artifact_snapshots(project_root: Path) -> list[ReArtifactSnapshot]`.
- Produces: kind/room metadata from descriptors, with explicit mining policy separate from registration.

- [ ] **Step 1: Add failing descriptor-driven mining tests**

Use misleading filenames with valid typed descriptors to prove mining follows `kind`, not basename. Assert architecture/contracts/components/source and workspace decisions/CodeGraph summaries receive their current typed rooms. Assert registered heavy evidence (`re-codegraph-analysis`, `re-analysis`, `re-structure`, `re-configs`, `re-dependencies`) is not mined.

- [ ] **Step 2: Run the MemPalace tests and confirm failure**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_mempalace_re.py`

- [ ] **Step 3: Replace current curated path selection with descriptor policy**

Define `MINED_RE_ARTIFACT_KINDS` and a `(kind, scope) -> room` mapping. Load normalized descriptors, filter by policy, read exactly the descriptor path, verify the descriptor hash through the registry loader, and place descriptor `kind` into snapshot metadata. Retain the legacy loader path only when no publication index exists and the operational direct `re/` layout is used by existing tests/tools.

- [ ] **Step 4: Align cleanup and audits**

Delete drawers by reverse-engineering provenance/scope and supported typed kinds. Audit each planned row against the snapshot descriptor kind. Keep future `re-*` parser compatibility while ensuring only registry-supported kinds enter canonical publication.

- [ ] **Step 5: Run memory suites**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_mempalace_re.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_spec_evidence.py`

Expected: PASS.

- [ ] **Step 6: Commit descriptor-driven memory mining**

```bash
git add src/echelon/mempalace_re.py src/echelon/spec_memory_miner.py tests/unit/test_mempalace_re.py
git commit -m "feat(re): mine typed artifact descriptors"
```

### Task 6: Drive Graph Topology From Descriptor Kinds

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Modify: `tests/unit/test_spec_graph.py`
- Modify: `tests/unit/test_workspace_graph.py`

**Interfaces:**
- Consumes: normalized descriptor lookup keyed by workspace-relative path.
- Preserves: attached-context integrity filtering from `_linked_re_artifacts`.
- Produces: existing `ReverseEngineeringSource`, `Decision`, typed Artifact, and semantic edge model without filename classification for typed publications.

- [ ] **Step 1: Add failing graph descriptor tests**

Create typed artifacts whose filenames do not reveal their semantics, attach their path/hash rows through `re-context.json`, and assert descriptor kinds produce `DESCRIBED_BY`, `DECLARES_CONTRACTS_IN`, `CATALOGS_COMPONENTS_IN`, `SUMMARIZED_BY`, source `HAS_DECISION`, and spec `INFORMED_BY_DECISION` edges. Assert an attached path absent from a typed catalog remains generic evidence and cannot acquire inferred semantic topology.

- [ ] **Step 2: Run graph suites and confirm failure**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py`

- [ ] **Step 3: Join attached artifacts with normalized descriptors**

Load one descriptor lookup per graph build. Keep `_linked_re_artifacts` responsible only for immutable context hash verification. Replace `_describe_re_artifact` filename semantics with descriptor kind/scope/source ownership. Legacy publications continue through normalized inferred descriptors from the registry, so graph code itself has one path.

- [ ] **Step 4: Preserve deterministic IDs and workspace deduplication**

Keep `re-source:<source-id>`, `decision:<source-id>:<relative-path>`, and `decision:workspace:<relative-path>` IDs. Retain artifact path identity and `STORED_AS` reconciliation. Add descriptor kind and scope to artifact properties.

- [ ] **Step 5: Run graph suites**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py tests/unit/test_graph_cli.py`

Expected: PASS.

- [ ] **Step 6: Commit descriptor-driven graph topology**

```bash
git add src/echelon/spec_graph.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py
git commit -m "feat(re): build graphs from artifact descriptors"
```

### Task 7: Republish And Verify OptaSearch

**Files:**
- Modify through canonical CLI publication: `/Users/michalbachorik/work/optasearch/re/**`
- Modify through graph refresh when content changes: `/Users/michalbachorik/work/optasearch/specs/*/spec-artifact-graph*.json`
- Modify through graph refresh: `/Users/michalbachorik/work/optasearch/.echelon/runtime/graph/workspace-artifact-graph.json`
- Modify through graph refresh: `/Users/michalbachorik/work/optasearch/.echelon/runtime/graph/workspace-artifact-graph-audit.json`

**Interfaces:**
- Consumes: the validated completed/partial RE run already referenced by OptaSearch `re/index.json`.
- Produces: typed generation of OptaSearch RE publication and refreshed local MemPalace wing.

- [ ] **Step 1: Run all focused Echelon tests**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_re_artifacts.py tests/unit/test_re_publication.py tests/unit/test_re_registry.py tests/unit/test_published_re_context.py tests/unit/test_re_materializer.py tests/unit/test_mempalace_re.py tests/unit/test_spec_graph.py tests/unit/test_workspace_graph.py`

Expected: PASS.

- [ ] **Step 2: Run the complete Echelon suite**

Run: `tests/run-all.sh`

Expected: all suites pass with zero failures.

- [ ] **Step 3: Republish OptaSearch through the CLI**

From `/Users/michalbachorik/work/optasearch`, identify the published run from `re/index.json`, validate it is still present, and execute:

```bash
/Users/michalbachorik/.echelon/venv/bin/echelon re publish <published-run-id>
```

Do not hand-edit `re/index.json` or manifests. If the CLI requires a publication-state override already established by the earlier refresh, use only the existing supported flag and record it.

- [ ] **Step 4: Validate descriptor coverage**

Run a read-only script using `canonical_re_artifact_descriptors` and assert that every durable non-index file under `re/sources` and `re/workspace` has exactly one descriptor. Print counts by kind/scope and explicitly verify the three workspace ADRs plus representative source architecture, contracts, components, CodeGraph summary/analysis, generated spec, and checklist.

- [ ] **Step 5: Refresh and audit OptaSearch memory**

```bash
/Users/michalbachorik/.echelon/venv/bin/echelon re memory refresh
/Users/michalbachorik/.echelon/venv/bin/echelon re memory audit --json
```

Expected: memory status `pass` with zero missing, stale, duplicate, non-canonical, wrong-room, and wrong-wing rows.

- [ ] **Step 6: Refresh OptaSearch graphs**

Refresh each current spec graph with `--write`, recording legacy requirement/task or evidence-memory findings separately. Refresh the workspace graph with `--write`. Verify specs without `re-context.json` do not gain retroactive RE edges.

- [ ] **Step 7: Run final hygiene checks**

Run `git diff --check` in Echelon and OptaSearch. Review `git status --short`, descriptor counts, memory audit summary, graph audit findings, and ensure no `.cache`, `.staging`, MemPalace database, or run-local snapshot entered either repository.

- [ ] **Step 8: Commit implementation and publication separately when requested**

Use one Echelon implementation commit series from Tasks 1-6 and one OptaSearch generated-publication commit. Never combine the two repositories in one commit operation.
