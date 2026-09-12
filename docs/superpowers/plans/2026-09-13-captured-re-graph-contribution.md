# Captured RE graph contribution implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Derive existing linked RE annotations, decisions, source roots and topology-receipt graph records from explicitly supplied captured observations, with no live reads.

**Architecture:** Extract pure transformations from the existing RE graph owner while keeping registry loading, selection and physical validation in that owner. The new function consumes selected descriptors, exact bytes, source observations and preceding artifact records; it returns only its contributed/replaced records. It does not certify acquisition, assemble a complete graph or activate publication.

**Tech Stack:** Existing graph, RE descriptor and topology receipt records; frozen supplied-value carriers; shared pure Python transformations; offline legacy/native-registry compatibility tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Existing graph keys remain valid.
- Historical evidence is retained, not relabeled as proof of the new content.
- No new allocation, lifecycle, graph publication, memory writer, provider, state or publication writer is activated.
- Preserve current deterministic drawer identities and MemPalaceContext ownership; do not derive another wing, run or palace path.
- Supplied observations are not proof of current registry/storage state, physical source ownership, semantic verification, accepted source ownership or complete graph derivation.
- Existing RE descriptor taxonomy, source/decision keys, graph properties, artifact roles and legacy acquisition/error ordering remain unchanged.

---

### Task 1: derive captured linked RE contributions through shared transformations

**Files:** Create `src/echelon/spec_graph_re.py` and `tests/unit/test_spec_graph_re.py`. Modify `src/echelon/spec_graph.py` only for pure RE/ADR transformation delegation; preserve its external reads, registry validation and mutation/error ordering. Create narrow `src/echelon/spec_graph_values.py` to hold the existing JSON property-tree copier from `spec_graph_identity.py`; retain `_copy_tree` there as a compatibility wrapper, with no changed accepted value types, detachment or error behavior. Document in `docs/element-identity-storage.md`. No other production changes: RE/topology registries, models, source selection/capture, memory, identity storage, runtime/controller/provider/state/CLI and prose remain untouched. Root owns plan/ledger.

**Public interfaces in spec_graph_re.py:**

```python
@dataclass(frozen=True, slots=True)
class GraphReArtifact:
    descriptor: ReArtifactDescriptor
    content: bytes

@dataclass(frozen=True, slots=True)
class GraphReTopology:
    source_id: str
    source_path: str
    generation: int
    fingerprint: str
    receipt: TopologyArtifactReceipt
    receipt_content: bytes

@dataclass(frozen=True, slots=True)
class GraphReSource:
    source_id: str
    workspace_path: str
    semantic_path: str
    publication_status: str
    semantic_generation: int
    semantic_fingerprint: str
    semantic_receipt_path: str
    topology: GraphReTopology | None

@dataclass(frozen=True, slots=True)
class ReGraphContribution:
    spec_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

def build_re_graph_contribution(
    *, spec_id: str, lifecycle: str,
    artifacts: tuple[GraphReArtifact, ...],
    sources: tuple[GraphReSource, ...],
    artifact_nodes: tuple[GraphNode, ...],
    stored_artifact_ids: tuple[str, ...],
) -> ReGraphContribution:
    ...
```

Reuse existing `ReArtifactDescriptor` from harness.re_artifacts and `TopologyArtifactReceipt` from echelon.topology_registry; no duplicate native types. Graph classes remain in spec_graph. Source DTOs deliberately contain only graph-consumed observed fields, not reconstructed registry objects, authenticated receipts or another workspace source model. No serialization protocol, timestamp, loader, writer, generic graph engine or acceptance receipt.

**Strict supplied-value boundary:**

- Exact DTO/native record/container/string/bytes/integer types; bool is not a generation. Reuse `spec_graph_structure._validate_scope(spec_id, lifecycle)` unchanged. Text is valid UTF-8; identifiers, paths, fingerprints and publication status are nonempty. Generation is an exact positive integer. Status/fingerprint observations retain their strings rather than introducing a new status/fingerprint interpretation.
- All path values are canonical relative POSIX paths with no aliasing, absolute roots, traversal, backslashes or normalization changes. Reuse existing pure path validators plus exact string equality. No `Path.resolve`, directory existence or symlink inference in this function. Source IDs use the existing pure RE source-ID policy after exact-string validation.
- Exact descriptors require supported kind, existing scope/source ownership policy and SHA256 format. Reuse pure `_owner_prefix`, `_validate_path`, `_has_prefix` and `SUPPORTED_RE_ARTIFACT_KINDS`; do not call the physical `validate_re_artifact_descriptor`. Descriptor content hash must equal `sha256:<lowercase hex of supplied bytes>`. Artifact descriptor paths are unique. Selection is supplied: do not classify filenames, invent uncataloged descriptors, load an index or consult re-context.json.
- Source IDs are unique. `workspace_path == semantic_path` is required, and when topology exists its source_id/path must equal the source's ID/workspace path. Semantic receipt is beneath the matching `re/sources/<source_id>` owner component-wise. This checks observed-value consistency only; it does not establish that source directories exist or that the registry admitted them.
- Topology receipt is the exact native record with exact nonempty name/path/hash strings; use its existing pure artifact-name validation and require its path beneath `re/topology/sources/<source_storage_key(source_id)>` component-wise, reusing the existing pure `source_storage_key`. Validate exact SHA256 and supplied receipt bytes. Do not assume the storage key equals the display source ID. No parsing or validation of receipt/provider payloads here; actual registry loading retains that responsibility.
- artifact_nodes are unique exact GraphNode records with type `Artifact`, nonempty UTF-8 IDs and Mapping properties. Require canonical relative properties.path, ID exactly `artifact:<spec_id>:<path>` and well-formed properties.hash. Detach their full JSON property trees using the shared existing copier, preserving Mapping support, tuple/list distinction, exact scalar types, finite floats and invalid-key/UTF-8 rejection. For each supplied descriptor with an existing artifact node, the artifact's hash must equal the descriptor's supplied-byte hash. Extra artifact nodes are accepted but not returned unless actually replaced; missing descriptor nodes retain legacy skip behavior.
- stored_artifact_ids are unique nonempty UTF-8 strings. They are an observed set of preceding STORED_AS source IDs, not proof that storage is current. Do not infer them from presence flags, perform mining or require a complete preceding graph.
- Ordinary input failures raise one bounded SpecGraphError after leaving handlers, retaining no source-bearing cause/context. Process-control BaseExceptions propagate. Missing/damaged attributes, recursive/damaged property containers and invalid nested records cannot escape with unbounded source details. Pure cases must not inherit a POSIX skip.

**Shared construction and legacy compatibility:**

1. Process selected artifacts in the same sorted path order as legacy linked artifacts. For each whose Artifact node exists, preserve all existing properties, add `re_artifact_kind`, `re_scope`, and `re_source_id` when not None. mining_status becomes `mined` if its ID is in stored_artifact_ids; otherwise `eligible` for non-decision descriptors; unmined decisions retain their old status. Keep node type and key. No new artifact node/input is invented for a missing descriptor node.
2. Workspace decisions use `decision:workspace:<descriptor.path.removeprefix('re/workspace/')>`, properties scope/path/title, and exact INFORMED_BY_DECISION plus DOCUMENTED_BY edges in their existing order. Pure ADR title parsing uses strict UTF-8, first nonempty stripped heading after removing leading `#`, otherwise path stem; invalid UTF-8 also falls back to stem. Legacy `_adr_title(path)` retains its signature and catches the same OSError/UnicodeError around its actual read, delegating only the string-to-title transformation. Do not add reads or change which decision paths are read.
3. Group source-scope descriptors by source ID, including descriptors whose artifact node is absent as legacy does. Process source IDs sorted, selected descriptor order retained. Every selected source requires a supplied GraphReSource; extra supplied sources may be ignored after value validation. No source nodes are emitted if no source-scope descriptors exist. Missing source observation rejects rather than fabricating an empty source/index.
4. SourceRoot key `source:<source_id>` retains source_id/path/publication_status/semantic_generation/semantic_fingerprint/semantic_receipt_path. Optional topology adds topology_generation/topology_fingerprint/topology_receipt_path, and a topology-receipt Artifact/Input from exact supplied bytes using shared `_add_artifact_record` and `_artifact_required`. Emit source root, USES_SOURCE, optional HAS_TOPOLOGY_RECEIPT, then per-source descriptor relationships in existing order. Nondecisions with existing artifact nodes use DESCRIBED_BY; source decisions use `decision:<source_id>:<descriptor.path.removeprefix('re/sources/<source_id>/')>`, source_id/path/title, HAS_DECISION and DOCUMENTED_BY. Preserve no-artifact skip behavior and exact properties.
5. Return contributed/replaced nodes, edges and topology receipt inputs only, not unrelated artifact_nodes, Spec/Requirement/memory records, generator metadata, full graph or identity projection. Repeated result construction produces independently owned nested properties, not shared records; damaging input dataclasses or another output after return cannot change retained results.

Extract small shared transformations at the actual interleaving points rather than first collecting all live observations and projecting at the end. The legacy `_add_re_topology` must keep `_linked_re_artifacts`, context exclusion, early returns, load_published_index, canonical_re_artifact_descriptors, per-artifact updates/title reads, by-source grouping, `_canonical_workspace_sources`, load_topology_index, semantic/topology physical path checks and per-source receipt reads in their original order. Keep existing partial mutations before errors. In particular, source validation errors occur after earlier artifact/workspace-decision updates, and a later source failure must not erase earlier source contributions. Legacy acquisition values keep current duck typing; do not route legacy through new strict DTO validation. `_canonical_source_path` and registry loaders remain the physical validation owners, not replaced by canonical string equality.

Shared JSON property copying is narrowly factored from the existing `_copy_tree`; retain its current recursive accepted shapes, exact scalar rules, UTF-8/finite checks and ValueError behavior, with no generic callback/validation framework. Existing identity projection uses its retained wrapper; the RE public boundary uses the same copier. Existing legacy shallow record replacement stays compatible; deep ownership is required for the new supplied-value result.

**First actual RED before production:** Create a real workspace decision file with exact bytes, validate its descriptor through the existing physical `validate_re_artifact_descriptor`, supply a real Artifact GraphNode, and run existing `_add_re_topology` with deterministic fixtures only for selection/index/descriptor acquisition. Assert its full independent node properties and exact edges, including real `_adr_title` output. Only then import the absent new module and build the equivalent contribution. Example decisive portion:

```python
path = "re/workspace/notes/decision.md"
content = b"intro\n\n ## Captured decision\n"
digest = "sha256:" + hashlib.sha256(content).hexdigest()
descriptor = validate_re_artifact_descriptor(
    {"kind": "re-decision", "path": path, "sha256": digest, "scope": "workspace"},
    workspace_root=tmp_path, owner_scope="workspace",
)
artifact_id = "artifact:demo:" + path
node = GraphNode(artifact_id, "Artifact", {
    "path": path, "hash": digest, "role": "reverse-engineering",
    "mining_status": "not-mined-by-policy",
})
nodes, edges, inputs = {artifact_id: node}, [], {}
# Acquisition fixtures return the real validated descriptor and selected file.
spec_graph._add_re_topology(tmp_path, tmp_path / "specs/demo", nodes, edges, inputs)
assert nodes[artifact_id].properties == dict(node.properties, re_artifact_kind="re-decision", re_scope="workspace")
assert nodes["decision:workspace:notes/decision.md"] == GraphNode(
    "decision:workspace:notes/decision.md", "Decision",
    {"scope": "workspace", "path": path, "title": "Captured decision"},
)
assert edges == [
    GraphEdge("spec:demo", "INFORMED_BY_DECISION", "decision:workspace:notes/decision.md", {}),
    GraphEdge("decision:workspace:notes/decision.md", "DOCUMENTED_BY", artifact_id, {}),
]
assert inputs == {}
module = importlib.import_module("echelon.spec_graph_re")
```

- [ ] Write/run `test_captured_re_retains_actual_workspace_decision_after_file_change` with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_captured_re_retains_actual_workspace_decision_after_file_change -q` from this worktree. Complete actual validation/helper assertions first; missing new module is the intended RED. Notify root before production. After implementation obtain GREEN, including changing/removing the physical file after capture while pure output retains original title/hash and has no reads.
- [ ] Extract shared transformations, exact scope/value validation and detached contribution. Keep existing native import identities and legacy wrappers; add both import-order subprocess tests without live actions. Add independent complete-record and deterministic rendered-byte expectations for mixed workspace/source decisions, nondecisions, multiple sources, topology receipts and preceding memory annotations.
- [ ] Cover empty inputs, no source groups, extra/missing observations, missing Artifact nodes, ignored uncataloged paths at legacy selection, source and workspace decision keys, nonconventional descriptor filenames, existing arbitrary nested properties, mined/non-mined decisions, root lifecycle values, strict and invalid UTF-8/empty/heading-less/CRLF titles, six/seven-plus and legacy labels in retained input properties without renaming.
- [ ] Cover every public type/path/source-coherence/hash/generation/duplicate rule, receipt source_storage_key ownership, damaged records and nested containers, exception-chain removal and process-control propagation. Add input/output damage after return, independently mutated subsequent results and no file/stat/resolve/enumeration/environment/process/clock/random/network/DB/memory/registry/identity/writer/lock tripwires after real fixture acquisition/imports. Do not mock pure transformations or assert only helper calls.
- [ ] Compare complete new contribution with actual existing `_add_re_topology` on real typed registry/catalog files and workspace config; use native descriptor validation and real topology registry fixtures for at least one topology receipt. No real memory collection. Explicitly record which external acquisitions are fixture-provided versus physically validated. Legacy tests must preserve exact acquisition order/early returns and partial mutations when a later semantic source conflicts or a topology receipt read fails; no broad mocks replacing graph construction.
- [ ] Compose real spec-local structure, captured memory and this RE contribution in existing order, then actual retained-history projection in an offline fixture; assert full deterministic container records, stable req/task/decision/source keys and original historical evidence/unassessed STORED_AS. This does not certify complete source selection, fresh audit, graph publication or semantic acceptance.
- [ ] Run once the eight covering modules: `tests/unit/test_spec_graph_re.py`, `tests/unit/test_spec_graph.py`, `tests/unit/test_spec_graph_structure.py`, `tests/unit/test_spec_graph_memory.py`, `tests/unit/test_spec_graph_identity.py`, `tests/unit/test_spec_graph_audit.py`, `tests/unit/test_re_artifacts.py`, `tests/unit/test_topology_registry.py`. No full-unit/capacity/live/provider/global-install or unchanged postcommit repeats. Later amendments receive named scoped covering verification and explicit tree/chronology accounting.
- [ ] Self-review all shared transformation/data ownership and legacy read/mutation ordering, diff-check, commit scoped files and full report. Report actual RED/GREEN, every run including fixture failures, exact executable/workdir, covering tree and post-covering changes, tests' actual native versus fixture boundaries, unchanged behavior and remaining integration. Root performs independent original-BASE review after DONE.

## Remaining integration

Complete authenticated dependency discovery and joint capture, memory planning/audit acquisition against exact images, full graph composition/sealing, managed source/runtime/producer/semantic/completion enforcement and bounded repair still require integration. A coherent supplied descriptor, source tuple or receipt hash is not accepted registry provenance. No live caller uses this new entry point.
