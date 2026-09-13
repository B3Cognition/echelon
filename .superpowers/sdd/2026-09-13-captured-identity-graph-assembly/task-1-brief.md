### Task 1: assemble byte-coherent captured domain records and retained history

**Files:** Create `src/echelon/spec_graph_captured.py` and `tests/unit/test_spec_graph_captured.py`; document in `docs/element-identity-storage.md`. No other production changes. In particular, do not change existing graph models/builders/readers, source snapshot/projection/manifest code, native memory planners/auditors, RE/topology registries, identity authority, runtime/controller/provider/state/CLI or prose. Root owns plan/ledger. New module imports existing values and pure functions; it has no live caller.

**Public interface:**

```python
@dataclass(frozen=True, slots=True)
class CapturedGraphMemory:
    domain: str
    sources: tuple[GraphMemorySource, ...]
    planned_rows: tuple[PlannedRequirementDrawer | CanonicalRequirementDrawerPlan, ...]
    audit: GraphMemoryAudit

def build_captured_identity_graph(
    *, spec_id: str, lifecycle: str, generator_version: str,
    sources: ProjectedPublicationSources,
    policy_paths: tuple[str, ...],
    memory: tuple[CapturedGraphMemory, ...],
    re_artifacts: tuple[GraphReArtifact, ...],
    re_sources: tuple[GraphReSource, ...],
    history: IdentityHistorySnapshot,
) -> SpecArtifactGraph:
    ...
```

Reuse existing type identities from spec_graph, spec_graph_memory, spec_graph_re, native plan modules, squad_source_projection and element_identity_snapshot. CapturedGraphMemory is a values-only grouping, not a new audit or receipt. Do not add another file-image/native model, registry format, graph schema, generator, timestamp, callback framework, authority method or serialization protocol.

**Validate shared images and scope:**

- Exact spec/generator/lifecycle/string/tuple/carrier types, valid UTF-8, nonempty generator_version. Reuse existing `_validate_scope` for spec/lifecycle. Require exact ProjectedPublicationSources and exact SourceManifestSnapshot, with exact string payload/sha fields. Recompute `snapshot_source_manifest(trees=sources.trees, files=sources.files)` and require full equality to the supplied manifest. This reuses all existing exact byte/hash/mode/membership/layout validation; do not implement another snapshot codec or interpret metadata equality as provenance.
- Require one selected tree whose path is exactly `specs/<spec_id>`; the existing selection validator rejects duplicates/overlap. This assembly entry point consumes canonical-path images, not arbitrary physical-to-logical aliases. Other selected trees/files can include external dependencies. A selected spec tree can be missing or empty under its existing snapshot rules, preserving those distinct observations; absence of that selected tree is invalid. Do not expand a broader selected tree, discover a spec or rewrite supplied roots.
- Build one path-to-present-bytes table from all validated tree files and present selected files. Preserve missing observations as missing; never coerce None to empty bytes. Do not drop hidden/binary/unreferenced images from manifest validation, but parse only graph-consumed inputs. No filesystem lookup or reread. Bytes themselves can be shared immutable values; all output graph records/nested properties must be independently owned.
- policy_paths is an exact tuple of unique exact canonical relative POSIX paths, each beneath this spec root or `re` component-wise and present in the image table. It is the supplied policy-artifact selection, not selection derived from every captured file. Reuse existing pure path validation plus exact normalization equality. Root graph output path `specs/<spec_id>/spec-artifact-graph.json` is forbidden as a policy or memory input; retaining its bytes in the captured source tree is allowed and must not create a self-hash dependency.

**Validate domain source coherence without inventing acquisition:**

- memory is an exact tuple of exact CapturedGraphMemory records. Its domains are unique and from the existing three domain names; canonical-spec is required, evidence and RE are optional. Optional spec-evidence/published-re observations require nonempty source tuples, matching legacy domain entry-point early returns. Caller tuple order is not execution order: always compose canonical-spec, spec-evidence, published-re. Preserve returned/exception origin and partial planned-row semantics through the existing builder; never manufacture an unavailable audit or infer origin.
- Every GraphMemorySource's exact path/content must match a present image-table entry before transformation. Existing memory builder remains responsible for strict nested types, domain scope, row/source hashes, duplicates, report shape and endpoint validation. Avoid relying on caller dataclass annotations before checking/accessing damaged values safely. Canonical main spec/support sources are looked up by canonical paths in the selected spec tree, not an alternate caller image. Reject the root graph output path in any supplied memory source.
- re_artifacts/re_sources are exact tuples of the existing exact records. Every supplied RE artifact content must match its present captured descriptor path. Every supplied GraphReSource semantic_receipt_path must be present in the captured table; this is dependency presence only, not parsing/authentication of its contents. For every supplied topology observation, receipt_content must match its captured receipt path exactly. Existing RE builder owns strict descriptor/type/path/source/generation/receipt hash validation and `.` source-root compatibility. Source root directories and registry/index admission are not authenticated by this table check.
- After local/policy/memory assembly, each explicitly supplied RE artifact must have its exact Artifact key in the assembled records before RE annotation. Do not silently drop an explicitly selected descriptor due to a missing preceding artifact. This is a full-assembly consistency check; keep the existing lower-level contribution's missing-node compatibility behavior unchanged.
- Use the existing `project_identity_history(graph, history)` last. It owns exact history/scope/digest/record validation and provenance projection; do not reinterpret revisions, allocate, adopt, query a store, relabel evidence, or reconstruct the history snapshot. Identity snapshot consistency is not authentication of the selected ledger or semantic authorization.
- All ordinary failures leave one bounded SpecGraphError raised after handlers, without source-bearing cause/context; process-control BaseExceptions propagate. Missing/damaged nested attributes, malformed/recursive values and source hash contradictions must not leak input bytes or decoder source documents. Pure cases have no POSIX skip.

**Assembly order and output:**

1. `build_spec_graph_structure(spec_id=..., tree=selected_spec_tree, lifecycle=...)` produces local nodes/edges/inputs. Own fresh dict/list containers; do not mutate a retained lower-level contribution or caller input.
2. Add supplied policy paths not already represented by local inputs, in pure component-wise path order. Use `_artifact_role`, `_artifact_required` and `_add_artifact_record` from spec_graph_structure with PurePosixPath canonical paths and SHA256 of the shared image bytes. For an already represented local path, require its input hash matches the table and retain its existing local/final role, rather than overwriting later local-ledger/amendment semantics. This composes equivalent final wire records; raw tuple insertion order relative to the legacy live builder is not an API promise. Do not duplicate policy nodes/inputs, invent unknown missing artifacts or classify unrelated captured files.
3. For each supplied memory domain in the fixed order, call `build_memory_graph_contribution` using current known node IDs. Merge contributed/replaced nodes/inputs by key/path, append its edges and receipt once. Preserve canonical support/task overrides, evidence roles, partial/unavailable audit semantics and native drawer keys. Do not re-run planning or normalize audits outside their existing owner.
4. Call `build_re_graph_contribution` with current Artifact records and the unique set of current STORED_AS source IDs. Merge its nodes/inputs/edges. Preserve existing annotation, source and decision semantics; no provider/registry loading or memory receipt fabrication. An empty RE contribution still uses the existing public validation path for supplied observations.
5. Construct existing SpecArtifactGraph with the explicitly supplied generator_version and composed records, then apply existing retained-history projection. Validate/renderability through existing graph/model validation before returning; do not invoke package-version discovery, write a graph or return another wrapper. For stable observations, existing `render_spec_graph` must produce deterministic, native-equivalent bytes after the same identity projection. Do not add source capture/manifest/acceptance fields to the existing graph wire.

The exact selected source manifest can include the old or future graph file; that file is excluded from graph inputs by the existing local policy and the explicit self-input check. Changing only those retained graph bytes may change the selected-source manifest but must not change newly derived graph bytes. This is not permission to exclude graph publication from later sealed operations or source guarding.

**Actual first RED before production:** Build a real IdentityStore fixture, reserve FR-000001, create/revise its history with an older evidence claim, and obtain the real immutable history snapshot. Build a real sealed temporary publication with a changed spec file, inspect its selected canonical spec tree and project exact final source images. Use the real native canonical memory planner, existing local/memory contribution APIs and existing identity projection to construct the expected graph. Assert stable requirement key/current revision and the old evidence edge targeting the original revision before importing the absent new module. Core identity setup:

```python
store = IdentityStore.initialize(tmp_path)
label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
assert label == "FR-000001"
store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
    ElementCreate(label, "Requirement", "Original body", "reserve"),))
store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
    ReferenceClaim("old-evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
    ElementRevision(label, "1", "Requirement", "Revised body"),))
history = store.identity_history(spec_id="demo")
spec_dir = tmp_path / "specs/demo"
spec_dir.mkdir(parents=True)
(spec_dir / "spec.md").write_bytes(b"FR-000001: Original body.\n")
squad = tmp_path / "runs/spec-test"
squad.mkdir(parents=True)
transaction = SquadPublicationTransaction.begin(tmp_path, squad, "2" * 32)
stage = transaction.build_path("after.md")
content = b"FR-000001: Revised body.\n"
stage.write_bytes(content)
target = Path("specs/demo/spec.md")
transaction.add_write(target, stage, owned_paths={target})
prepared = transaction.seal()
with prepared.inspect_sources(tree_paths=("specs/demo",)) as initial:
    projected_sources = project_publication_source_images(initial)
structure = build_spec_graph_structure(
    spec_id="demo", lifecycle="phase_a", tree=projected_sources.trees[0])
rows = plan_canonical_requirement_drawers(
    content, source="specs/demo/spec.md", wing="captured-test-wing",
    artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + hashlib.sha256(content).hexdigest()},
)
audit = GraphMemoryAudit(
    origin="returned", schema_version=1, wing="captured-test-wing", status="pass",
    artifact_count=1, expected_count=1, present_current_count=1,
    missing=(), stale=(), wrong_wing=(), wrong_room=(), duplicate=(),
    non_canonical=(), lifecycle_excluded=(), errors=(),
)
memory_sources = (GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),)
contribution = build_memory_graph_contribution(
    spec_id="demo", lifecycle="phase_a", domain="canonical-spec",
    sources=memory_sources, planned_rows=tuple(rows), audit=audit,
    known_node_ids=tuple(node.id for node in structure.nodes),
)
nodes = {node.id: node for node in (*structure.nodes, *contribution.nodes)}
inputs = {item.path: item for item in (*structure.inputs, *contribution.inputs)}
existing_composed_graph = SpecArtifactGraph(
    "demo", "captured-test", tuple(inputs.values()), tuple(nodes.values()),
    structure.edges + contribution.edges, (contribution.receipt,),
)
expected = project_identity_history(existing_composed_graph, history)
old = next(n for n in expected.nodes if n.type == "ElementRevision" and n.properties["revision"] == "1")
claim = next(n for n in expected.nodes if n.type == "ReferenceClaim")
assert old.properties["content"] == "Original body"
assert GraphEdge(claim.id, "ASSESSES_REVISION", old.id, {}) in expected.edges
assert claim.properties["target_revision_matches_current"] is False
module = importlib.import_module("echelon.spec_graph_captured")
```

Do not mock publication capture, source projection, native planning, graph construction or identity projection. Audit is a deterministic supplied observation, not an actual collection audit. This first physical fixture may explicitly request the existing secure-POSIX fixture; the independent pure suite must remain portable. Existing helpers in tests.unit.test_squad_source_projection_images and tests.unit.test_spec_graph_memory show native setup shapes; reuse fixture setup where appropriate, not their expectations as an oracle.

- [ ] Write/run `test_captured_assembly_retains_projected_source_and_old_evidence` with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py::test_captured_assembly_retains_projected_source_and_old_evidence -q` from this worktree. Real capture/native/history assertions must succeed before missing-module RED. Notify root before production; implement and obtain GREEN including physical files changing after capture while retained projected bytes/history remain the graph source.
- [ ] Add independent complete expected records/digests/rendered-byte fixtures covering canonical-only and all three memory domains plus source/workspace RE decisions/topology, local tasks/traceability/deferrals/amendment controls/verified evidence, policy extras and role overrides, empty/missing selected spec trees, partial unavailable audits and returned/exception RE distinction. Cover component-order sibling paths, explicit generator version, duplicate/cross-domain claims, and source/receipt bytes conflicting with otherwise individually valid contributions.
- [ ] Compare full rendered output with real legacy build_spec_graph followed by real retained-history projection on stable actual canonical files, typed RE catalogs, workspace config and topology fixtures. Use real native planners and deterministic external memory adapters/audits; document those acquisition boundaries. Compare every rendered record/field/hash, not just key subsets. Confirm no data is borrowed from live files after capture. Normal rendering order is the comparison contract, not internal tuple insertion order.
- [ ] Validate strict outer/nested type and source-table failures, stale/tampered manifests, wrong/missing selected spec root, None versus empty files, duplicate policy/domain keys, missing canonical domain, empty optional domains, uncaptured/mismatched memory/RE/semantic/topology paths, absent preceding RE artifacts, graph self-input and source scope violations. Include record/subclass/damaged-slot/recursive property cases, process-control propagation and bounded exception chains. Imported unassessed history stays unassessed; this function does not repair or adopt it.
- [ ] Add deep ownership and purity tests after native fixture acquisition/imports: damage original source/descriptors/audits/history records and a later output's nested properties; retain the earlier rendered bytes. Block file/stat/resolve/enumeration, environment/process/clock/random/network, DB/identity authority, memory/registry/planning, capture and writer/lock entry points. Observe no graph, canonical, registry or memory writes. Verify both import orders retain model identities.
- [ ] Test source-image/graph integration using actual guarded publication of the fixture's non-graph source operations and a final source capture matching the projected manifest; derive the same graph from retained projected images and actual final images. Separately prove changing only retained root graph-file bytes changes the image manifest but not graph rendering, while graph-as-policy/memory-input rejects. These fixtures do not claim the graph itself is sealed or atomically published; that owner remains required.
- [ ] Run once the eight covering modules: `tests/unit/test_spec_graph_captured.py`, `tests/unit/test_spec_graph.py`, `tests/unit/test_spec_graph_structure.py`, `tests/unit/test_spec_graph_memory.py`, `tests/unit/test_spec_graph_re.py`, `tests/unit/test_spec_graph_identity.py`, `tests/unit/test_squad_source_projection_images.py`, `tests/unit/test_squad_source_manifest.py`. No full-unit/capacity/live/provider/global-install or unchanged postcommit repeats. Later amendments receive named scoped verification and exact tested-tree chronology.
- [ ] Self-review byte-table coherence, composition order/overrides, no silently lost selected descriptors, existing transformation reuse, output ownership and honest authority limits; diff-check and commit scoped module/tests/docs. Write full report with every actual test run/fixture failure/RED/GREEN, commands/output, tested tree and later amendments, native-versus-fixture boundaries and remaining integration. Root performs original-BASE independent review after DONE.

## Remaining integration

This assembly function does not authenticate registry/memory observation acquisition or complete dependency selection; bind a semantic review; seal the graph as an operation; prepare/apply a durable identity/source publication; manage run enrollment/transitions; allocate for producers; enforce runtime/manual/CLI routes; or implement bounded repair. Those integrations remain required before live activation. A graph generated from coherent supplied values is still a derived view, not publication authority.
