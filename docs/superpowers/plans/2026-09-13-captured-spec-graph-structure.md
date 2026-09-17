# Captured spec graph structure implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Derive the existing spec-local graph structure from one supplied captured or projected spec tree, without reading mutable files or inventing external observations.

**Architecture:** Extract the existing node/edge/input transformations into shared pure helpers, preserving the legacy Path readers as their adapters. A separate pure entry point produces a deliberately incomplete structure fragment from an exact supplied tree, mapping its physical root to the existing canonical logical spec path. Memory, attached RE and topology remain explicit external additions, not fabricated unavailable/pass observations.

**Tech Stack:** Existing ProjectTreeSnapshot and source-manifest validation, canonical supplied-text parsers, current GraphNode/GraphEdge/GraphInput types, Python and offline pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Existing graph keys remain valid.
- Historical evidence is retained, not relabeled as proof of the new content.
- No new allocation, lifecycle, graph publication, memory, provider, state or publication writer is activated.
- Captured/projected bytes and this structural fragment are caller-supplied observations, not source-selection completeness, semantic acceptance, namespace authentication or completion authority.
- Preserve legacy graph node/edge/input properties, hashes, ordering semantics, error behavior, memory/RE/topology integration and public imports; share transformations instead of introducing a second graph policy.

---

### Task 1: share spec-local graph transformations and expose captured structure

**Files:** Create `src/echelon/spec_graph_structure.py` and `tests/unit/test_spec_graph_structure.py`; modify `src/echelon/spec_graph.py` only to delegate the relevant pure transformations through existing reader adapters. Document in `docs/element-identity-storage.md`. Focused existing graph tests may gain compatibility assertions. No other production files, graph wire/version changes, source codecs/capture/guard, identity/state/controller/provider/CLI/memory/RE/topology implementations or prose changes. Root owns plan/ledger.

**Public interface in the new module:**

```python
@dataclass(frozen=True, slots=True)
class SpecGraphStructure:
    spec_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

def build_spec_graph_structure(
    *, spec_id: str, tree: ProjectTreeSnapshot, lifecycle: str,
) -> SpecGraphStructure:
    ...
```

Use the existing graph model classes from `echelon.spec_graph`; do not move/redefine them or change their import identity. The existing Path adapters can use local imports of the new pure helper functions to avoid a module initialization cycle. Do not create another generic graph engine or callback/input-provider abstraction.

The supplied tree is exactly one spec root, not a parent containing multiple specs. Validate its exact type, nested bytes/hash/mode/membership/layout with existing `snapshot_source_manifest(trees=(tree,), files=())`, without treating that metadata digest as acceptance. Validate `spec_id` as an exact nonempty UTF-8 string single path component: no leading/trailing whitespace, slash, backslash, NUL/control characters, `.` or `..`; preserve all otherwise valid characters and digits verbatim. Validate lifecycle as one of exact strings `phase_a`, `build`, `verified`, `landed`. This is an explicit caller observation, not a reread of frontmatter or lifecycle authority.

Strip the physical tree root component-wise and map all local graph paths to `specs/{spec_id}/...`. A run-local and canonical tree with identical relative membership/bytes must yield identical structural records, hashes and graph keys. Never leak the run-local/staging root into graph keys. No Path.resolve/stat, environment root, implicit current directory or lexical string-prefix containment. A valid missing or empty tree yields the Spec node and no file-derived nodes; this fragment does not certify that mandatory full-graph inputs exist.

Share the existing transformations for: the Spec node; spec-origin canonical requirements; local declared artifact policy plus the three product-input files; tasks/progress/IMPLEMENTS; product-input traceability/DERIVED_FROM; deferral nodes/DEFERRED_BY; numeric-named amendment directories and their five existing control artifact paths; verified-fulfillment artifact and VERIFIED_BY edges. Reuse `extract_canonical_requirements_from_texts`, `parse_deferred_scope_ledger`, `parse_verified_ledger`, `validate_tasks_markdown`, `summarize_task_progress` and `parse_task_rows`. Use the existing artifact registry rather than copying its list. Exact property values, source lines/text, category, node keys, unresolved IDs (including INFRA/UNMAPPED behavior), input-unit aggregation, status handling and original verification provenance fields remain unchanged.

The fragment includes only the local declared policy artifacts, product inputs, amendment controls and fulfillment artifact covered by those existing transformations. An existing local `re-context.json` can remain a policy artifact if the registry includes it; do not follow its links. Evidence-domain artifact discovery, supporting-memory additions, memory snapshots/planning/audit, attached RE, canonical workspace-source validation and topology are NOT represented by this fragment. Do not return a SpecArtifactGraph, generator version, memory receipts, complete-source digest or a fabricated empty/pass/unavailable external-domain observation. Document that the future complete graph owner must still supply those domains before sealing; no live builder is switched to this fragment.

The legacy `build_spec_graph` and its Path helpers keep the same capture/read behavior and external integrations, calling the extracted pure transformations after their existing reads/selection. Preserve helper signatures used by existing callers/tests. In particular: canonical requirements retain UTF-8 replacement decoding; task/JSON/ledger paths retain their strict decoding and missing-file rules; `_add_policy_artifacts` still adds existing evidence and attached RE artifacts; `_add_artifact` still handles later external additions and explicit role overrides; current memory and topology call order remains unchanged. Do not copy node/edge construction loops into both modules, move the whole large graph module, silently add secure-capture restrictions to the legacy reader, or replace real memory/RE observations with synthetic values.

Public captured-input failures use bounded `SpecGraphError` without retaining source bytes/JSON documents in cause/context. Normalize ordinary parser/validation failures only at the new public boundary after leaving exception handlers; do not swallow BaseException/SystemExit/KeyboardInterrupt or alter legacy Path exception contracts. New results own their tuple records and all mutable nested graph property containers; subsequent forced mutation of input snapshot records must not alter the fragment, and separate calls must not share mutable output properties. The DTO itself is a value carrier, not a validator for caller-constructed fragments.

**First actual RED before production:** create a real spec file, verify the current canonical reader returns its complete expected record, and capture the real spec tree with existing `inspect_project_tree`. Only then import the absent new module and call the new entry point. The intended failure is ModuleNotFoundError for `echelon.spec_graph_structure`, after valid existing parsing and capture, not a broken fixture. Notify root before production edits.

```python
def test_captured_structure_retains_real_spec_after_file_change(tmp_path, secure_posix):
    import importlib
    from harness.canonical_requirements import extract_canonical_requirements
    from harness.squad_source_snapshot import inspect_project_tree
    spec_dir = tmp_path / "specs/demo"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "spec.md"
    original = b"# Game\n\n- FR-1000000: Keep question identity.\n"
    spec_file.write_bytes(original)
    rows = extract_canonical_requirements(spec_dir)
    assert [(row.id, row.source_kind, row.source_file, row.source_line, row.source_text) for row in rows] == [
        ("FR-1000000", "spec", "spec.md", 3, "- FR-1000000: Keep question identity.")
    ]
    with inspect_project_tree(tmp_path, "specs/demo") as tree:
        assert tree.files[0].content == original
    spec_file.write_bytes(b"# Changed\n\n- FR-000002: Different subject.\n")
    module = importlib.import_module("echelon.spec_graph_structure")
    result = module.build_spec_graph_structure(spec_id="demo", tree=tree, lifecycle="phase_a")
    assert {node.id for node in result.nodes if node.type == "Requirement"} == {"req:demo:FR-1000000"}
```

The current canonical parser stores the stripped complete original line, including its bullet and label, as asserted above. Use the existing secure capability guard only for physical capture/publication tests; pure cases run without a POSIX skip.

- [ ] Write/run the actual regression with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_captured_structure_retains_real_spec_after_file_change -q` in this worktree. Standalone Python uses PYTHONPATH=src. Notify root of the exact intended RED before production.
- [ ] Extract the smallest shared pure transformations and add the new public builder; obtain the named GREEN without changing legacy graph output. Legacy wrappers retain reads and external-domain ownership.
- [ ] Add independent complete expected GraphInput/GraphNode/GraphEdge records and deterministic rendered test-container bytes for a rich local fixture covering mixed legacy/six/seven-plus-digit IDs, wide task IDs in existing source-row order, spec-versus-plan/coverage/tasks precedence, CRLF/Unicode/source lines, task status/unresolved/INFRA behavior, multiple input units, all deferral statuses, numeric/empty/nonnumeric amendment directories, all control files, full verified provenance and multiple statuses. Test exact hashes/roles/required flags and all fields, not counts or shared-helper equality alone.
- [ ] Compare the complete local records at the actual legacy build_spec_graph pre-memory boundary with the new fragment for real fixture trees, while exercising existing real parsers. A read-only observing wrapper may capture those records before invoking the original external helper; do not mock core graph transformations. The later canonical-memory step re-adds supporting artifacts (including tasks.md) with role overrides, so independently assert those expected final overrides instead of forcing final full-graph equality or silently excluding them. External memory fixtures can retain the existing tests' deterministic adapter/audit stubs. Verify legacy full-graph memory/RE/topology tests unchanged in the covering set.
- [ ] Test same relative tree under canonical versus run-local roots gives exact identical fragment/rendered bytes; missing versus empty spec trees, missing versus empty/malformed task/JSON/ledger files, invalid UTF-8 per existing path policy, unsupported input types/subclasses/damaged snapshots and unsafe spec components reject or preserve legacy observations exactly as specified. Keep the DTO distinct from complete graph/capture types.
- [ ] Verify original frozen-input damage after result creation and mutable properties in a separate returned fragment cannot change an independently retained expected result. Assert original inputs unchanged by normal construction. Add strict no-file/read/stat/resolve/enumeration/write/process/env/clock/random/network/DB/provider/memory-authority tripwires after fixture creation/import.
- [ ] Compose a real sealed source publication with `project_publication_source_images`, feed its exact projected spec-root tree into this builder, publish through `publish_sources`, capture final actual tree and compare exact fragment bytes. Include a changed requirement and task/reference, hidden binary file, and an amendment control. This demonstrates deterministic local structure only, not complete graph sealing or semantic/evidence acceptance. No post-publication graph writer.
- [ ] Run once the covering modules under tests/unit: `test_spec_graph_structure.py`, `test_spec_graph.py`, `test_spec_graph_audit.py`, `test_graph_traversal.py`, `test_identity_graph_traversal.py`, `test_spec_graph_identity.py`, `test_graph_source_parsers.py`, `test_canonical_requirements.py`. No full-unit/capacity/live/provider/global install or unchanged postcommit repeat. Later amendments get named scoped coverage and exact chronology.
- [ ] Self-review import initialization in both orders, one shared transformation policy, compatibility/mutable ownership/bounded errors/no external observation fabrication; diff-check, commit scoped implementation and full report. Root supplies a fresh original-BASE review after DONE.

## Remaining integration

This completes only deterministic spec-local structure. Complete captured memory/RE/topology inputs, source-selection/logical mapping ownership, identity overlay, graph sealing and managed producer/runtime/semantic/completion/bounded repair integration remain required before activation.
