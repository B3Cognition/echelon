### Task 1: project one captured memory domain through shared graph transformations

**Files:** Create `src/echelon/spec_graph_memory.py` and `tests/unit/test_spec_graph_memory.py`; modify `src/echelon/spec_graph.py` only for shared memory transformation delegation. In `src/echelon/spec_graph_structure.py`, extract its existing spec-id/lifecycle validation verbatim into a narrow `_validate_scope(spec_id, lifecycle) -> PurePosixPath` helper and reuse it from both pure entry points, with no changed validation policy. Document in `docs/element-identity-storage.md`. No model/wire/schema changes or production edits to live memory planners/auditors/context/reconciliation, identity, RE/topology, source capture/guard/codec, runtime/state/controller/provider/CLI or prose. Root owns plan/ledger.

**New public interface in spec_graph_memory.py:**

```python
@dataclass(frozen=True, slots=True)
class GraphMemorySource:
    path: str
    content: bytes
    artifact_kind: str
    room: str

@dataclass(frozen=True, slots=True)
class GraphMemoryAudit:
    origin: str
    schema_version: int
    wing: str | None
    status: str
    artifact_count: int
    expected_count: int
    present_current_count: int
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    wrong_wing: tuple[str, ...]
    wrong_room: tuple[str, ...]
    duplicate: tuple[str, ...]
    non_canonical: tuple[str, ...]
    lifecycle_excluded: tuple[str, ...]
    errors: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class MemoryGraphContribution:
    spec_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    receipt: MemoryReceipt

def build_memory_graph_contribution(
    *, spec_id: str, lifecycle: str, domain: str,
    sources: tuple[GraphMemorySource, ...],
    planned_rows: tuple[PlannedRequirementDrawer | CanonicalRequirementDrawerPlan, ...],
    audit: GraphMemoryAudit,
    known_node_ids: tuple[str, ...],
) -> MemoryGraphContribution:
    ...
```

Use the existing graph models and the existing two seven-field drawer-plan types from mempalace_requirements and spec_memory_miner, preserving their import identities. Sources and audit are detached value carriers, not self-validating acceptance receipts. Do not add serialization, timestamps, DB registration, a generic plugin/callback engine or another memory context. Use local helper imports in legacy graph adapters where required to avoid a module cycle, as in the preceding structural extraction.

Validate exact outer record/container/string/bytes/integer types (reject subclasses and bool counters). Shared scope validation retains the preceding spec component/lifecycle rules. Domain is exactly `canonical-spec`, `spec-evidence` or `published-re`. Source paths are canonical relative POSIX paths with no aliasing, `.`/`..`, absolute paths, backslashes or traversal; use existing pure path validation and require its normalized string to equal the input. Canonical/evidence sources are beneath `specs/{spec_id}` component-wise; published-RE sources are beneath `re`. Sources have unique paths; their artifact_kind is nonempty UTF-8 text and room may be empty UTF-8 text. Content is exact bytes. Known node IDs are unique nonempty UTF-8 strings. Audit schema_version and counts are nonnegative exact integers, wing is None or UTF-8 text, status is nonempty UTF-8 text, and all issue/error collections are exact tuples of UTF-8 strings. Preserve report observation values rather than inventing a new pass/fail policy. Do not require counts to equal row count: existing unavailable observations can retain partial planned rows, and published RE projects a global report to selected drawers.

Audit origin is an exact mandatory string, either `returned` or `exception`; never infer it from status. Returned means a supplied returned audit observation, including a returned unavailable report. Exception means the existing legacy `_UnavailableMemoryReport` fallback, which bypasses RE projection. For exception origin require exactly that fallback shape: schema_version=1, wing=None, status=unavailable, all three counts=0, all seven issue collections empty, and errors a singleton nonempty UTF-8 string tuple containing the observed exception class name. Do not infer or fabricate that origin, exception or report in the pure function. Origin is not added to the existing normalized audit payload/graph wire and does not authenticate acquisition.

Require each exact supported planned row to have its existing seven string fields, nonempty IDs/source/room, correct SHA formats and an exact supplied source. Its artifact_hash and canonical_spec_sha256 must match the supplied source bytes. requirement_content_sha256 is a well-formed retained claim, not proof that the planner derived it. Do not re-run a native planner or perform semantic/content-secret processing in this function. Duplicate planned drawer IDs reject at the new public boundary; existing trusted legacy helper behavior remains unchanged.

Use shared existing construction semantics:

- Domain source-set digest is the existing sorted canonical list of path/hash/artifact_kind/room; source hash is computed from exact supplied bytes. Legacy `_memory_source_set_digest` continues extracting the same defaults/coercions from its actual snapshots, then uses the shared canonical record transformation.
- Canonical-spec uses virtual path `mempalace://canonical-spec/{spec_id}/audit`, required=True. Spec-evidence uses `mempalace://spec-evidence/{spec_id}/audit`, required=False. Published-re uses `mempalace://published-re/audit`, required=False. One existing MemoryReceipt and one memory_audit_report GraphInput retain the current normalized audit hash, status and source_set_digest.
- Published-re applies `_project_memory_audit` on the selected planned drawer IDs only for returned-origin observations, then normalizes. Exception-origin fallback bypasses this projection exactly as the existing legacy exception branch does. Canonical/evidence do not apply that projection. Share current projection/normalization helpers and their exact status/error rules; do not reinterpret warn/pass/unavailable or count semantics.
- Canonical-spec's root spec.md is already represented by local structure and is not re-added by the existing canonical-memory helper. Other canonical sources are added with supporting-context role; evidence sources with verification-evidence; RE sources with reverse-engineering. Reuse `_add_artifact_record` and `_artifact_required` from the structural module for new captured additions. Existing root-task required flags depend on supplied lifecycle; no filesystem lifecycle inference in this new path. Source `artifact_kind` still controls the drawer metadata/requirement-versus-artifact source decision, just as existing source_artifact_kind does.
- Preserve drawer IDs `drawer:{spec_id}:{drawer_id}`, all drawer property fields and STORED_AS properties. Source selects `req:{spec_id}:{requirement_id}` only when that node exists and artifact_kind is requirement, otherwise `artifact:{spec_id}:{source}`. Available nodes are the explicit known_node_ids plus this contribution's artifact additions. Missing source endpoint raises the existing structural error internally; the public boundary normalizes it.
- Return only contributed/replaced artifact and drawer records, edges, inputs and one receipt. Do not copy unrelated known nodes, emit a complete graph/generator, add identity metadata or claim endpoint/source-set completeness. The complete owner must compose in the legacy domain order, authenticate observations and apply the separate retained-history projection before sealing.

Extract one shared drawer-record transformation accepting known node IDs, not fake placeholder GraphNodes. The legacy `_add_drawer_rows` wrapper keeps its signature and updates its existing dictionaries/lists from those records. Preserve legacy list-only issue handling, status defaults and string coercions; the strict new audit DTO may be converted into an internal ordinary report with lists to reuse that exact behavior. Do not normalize legacy report fields earlier if doing so changes drawer interpretation. Likewise keep legacy `_normalized_memory_audit`, `_project_memory_audit` and `_memory_source_set_digest` helper signatures available through wrappers as necessary.

Legacy `_add_canonical_memory` and `_add_artifact_memory_domain` must retain their actual source/artifact reads and overrides, adapter construction, native planning, actual audit calls, exception capture, partial-row behavior and published-RE report projection order. They delegate only pure receipt/drawer transformations after acquisition; do not route them through the stricter new public input validation or silently fix their existing observation limitations. Do not mutate live collections, recompute drawer IDs or replace real observations with synthetic unavailable/pass values.

New public ordinary-input failures raise bounded SpecGraphError after leaving exception handlers, with no retained cause/context containing source bytes, metadata or JSON. Process-control BaseExceptions propagate. All returned frozen records and nested property containers are newly owned; later input damage or mutations to another result cannot alter retained results. Pure calls use no file/stat/resolve/enumeration, environment, process, clock/random/network, DB, memory adapter/auditor, writer, source capture, identity authority or lock calls. Pure cases do not inherit a POSIX skip.

**Actual RED before production:** use real `plan_canonical_requirement_drawers` on supplied canonical bytes/metadata with explicit test wing, and feed those real rows to the existing `_add_drawer_rows` with a known requirement node and a fixed ordinary audit report. Assert the resulting real drawer's exact source path, artifact/content hashes, room, presence and edge. Only then import the absent new module, expecting ModuleNotFoundError for echelon.spec_graph_memory. Notify root before production. Example setup:

```python
content = b"# Requirements\n\nFR-1000000: Preserve the question identity.\n"
source = "specs/demo/spec.md"
digest = hashlib.sha256(content).hexdigest()
rows = plan_canonical_requirement_drawers(
    content, source=source,
    artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest},
    wing="graph-test-wing",
)
assert [row.requirement_id for row in rows] == ["FR-1000000"]
nodes = {"req:demo:FR-1000000": GraphNode("req:demo:FR-1000000", "Requirement", {})}
edges = []
spec_graph._add_drawer_rows(
    Path("specs/demo"), rows, SimpleNamespace(status="pass"), nodes, edges,
    source_artifact_kind={source: "requirement"},
)
assert edges == [GraphEdge("req:demo:FR-1000000", "STORED_AS", "drawer:demo:" + rows[0].drawer_id,
                           {"presence": "present", "reconciliation_status": "pass"})]
assert nodes["drawer:demo:" + rows[0].drawer_id].properties == {
    "drawer_id": rows[0].drawer_id,
    "source_path": source,
    "room": "functional-requirements",
    "artifact_kind": "requirement",
    "artifact_hash": "sha256:" + digest,
    "content_hash": hashlib.sha256(b"FR-1000000: Preserve the question identity.").hexdigest(),
    "presence": "present",
    "reconciliation_status": "pass",
    "issue_codes": [],
}
module = importlib.import_module("echelon.spec_graph_memory")
```

- [ ] Write/run the complete native-planner/existing-helper first regression `test_captured_memory_retains_native_plan_after_input_damage` using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_captured_memory_retains_native_plan_after_input_damage -q` from this worktree. Standalone Python uses PYTHONPATH=src. Notify root of actual RED, then implement the shared extraction and obtain GREEN.
- [ ] Add independent complete contribution records and literal normalized audit/source-set payload/hash expectations for all three domains. Cover pass/fail/warn/unavailable, every issue field, partial planned rows after unavailability, empty sources/rows, global RE audit projection with unrelated errors/drawers, root task role/required overrides, canonical main spec no re-add, requirement-versus-artifact fallback, missing endpoints and original source kinds/rooms. Regression first: an actual legacy RE exception fallback with retained planned rows keeps zero counts and the global exception class error, whereas a returned unavailable report still undergoes selected-drawer projection. Assert both exact contributions/hashes and reject invalid/missing origin or an exception origin paired with non-fallback fields; do not conflate the two cases.
- [ ] Use real native requirement/support/evidence/RE planners and existing graph domain helpers with deterministic external adapter/audit fixtures, observing full contributions and comparing every record/receipt and deterministic rendered test-container bytes. Preserve actual helper continuation; no mock projection/normalization. Include six/seven-plus/legacy labels and unchanged deterministic drawer keys, old body hashes, content change and revised source hash; no relabeling of old memory as current evidence.
- [ ] Test exact record/type/path/hash validation, damaged nested fields, missing source rows, duplicate paths/drawers/node IDs, control-flow propagation, bounded error context, all output ownership and import identity/order. Verify legacy helper defaults/list-only coercion behavior independently from the stricter public API.
- [ ] Compose the new local structure with captured memory contribution and the existing real identity history projection in an offline fixture; retain original stable req/task keys and historical evidence edges, with legacy STORED_AS explicitly unassessed under identity projection. Render and compare independent key/assessment assertions. This is graph composition only, not a publication or semantic proof.
- [ ] Add pure tripwires after native fixture planning/import; mutate original bytes/record attributes and audit/plan inputs after result creation, and independently mutate another result's nested properties. Assert no later source/collection/context reread or shared mutable output.
- [ ] Run once the eight covering modules: `tests/unit/test_spec_graph_memory.py`, `tests/unit/test_spec_graph.py`, `tests/unit/test_spec_graph_structure.py`, `tests/unit/test_spec_graph_audit.py`, `tests/unit/test_spec_graph_identity.py`, `tests/unit/test_mempalace_audit.py`, `tests/unit/test_mempalace_re.py`, `tests/unit/test_mempalace_spec_evidence.py`. No full-unit/capacity/live/provider/global install or unchanged postcommit repeats. Later amendments receive named scoped verification and explicit chronology.
- [ ] Self-review shared transformation policy, strict-public-versus-compatible-legacy boundaries, read/planning/audit order, captured source/row coherence and honest contribution limits; diff-check, commit scoped files, full report. Root supplies fresh original-BASE review after DONE.

## Remaining integration

Actual captured memory acquisition/reconciliation, complete RE/topology and evidence selection, full graph composition/sealing, managed source/runtime/producer/semantic/completion and bounded repair integration remain required. This function never creates or refreshes an audit and does not authorize using caller-provided observations as current storage proof.
