"""Full assembly binds supplied domain observations to one captured byte table."""

from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from echelon.spec_graph import GraphEdge, GraphInput, GraphNode, MemoryReceipt, SpecArtifactGraph, SpecGraphError, render_spec_graph
from echelon.spec_graph_identity import project_identity_history
from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource, build_memory_graph_contribution
from echelon.spec_graph_structure import build_spec_graph_structure
from echelon.spec_memory_miner import plan_canonical_requirement_drawers
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_store import IdentityStore
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_source_projection import project_publication_source_images
from harness.squad_source_projection import ProjectedPublicationSources
from harness.squad_source_manifest import SourceManifestSnapshot, snapshot_source_manifest
from harness.squad_source_snapshot import ProjectPathSnapshot
from harness.squad_publication_snapshot import PublicationImageDescriptor
from harness.element_identity_snapshot import IdentityHistorySnapshot
from tests.unit.test_spec_graph_structure import _tree
from tests.unit.test_squad_source_projection_images import secure_posix


pytestmark = pytest.mark.unit


def _audit(**changes):
    return replace(GraphMemoryAudit(
        "returned", 1, "captured-test-wing", "pass", 1, 1, 1,
        (), (), (), (), (), (), (), (),
    ), **changes)


def test_captured_assembly_retains_projected_source_and_old_evidence(tmp_path, secure_posix):
    # Catch live rereads, identity replacement and evidence moved to the new revision.
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
    assert projected_sources.trees[0].files[0].content == content
    structure = build_spec_graph_structure(
        spec_id="demo", lifecycle="phase_a", tree=projected_sources.trees[0])
    rows = plan_canonical_requirement_drawers(
        content, source="specs/demo/spec.md", wing="captured-test-wing",
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + hashlib.sha256(content).hexdigest()},
    )
    memory_sources = (GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),)
    audit = _audit()
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
    requirement = next(n for n in expected.nodes if n.id == "req:demo:FR-000001")
    assert requirement.properties["identity"]["revision"] == "2"
    assert old.properties["content"] == "Original body"
    assert GraphEdge(claim.id, "ASSESSES_REVISION", old.id, {}) in expected.edges
    assert claim.properties["target_revision_matches_current"] is False
    module = importlib.import_module("echelon.spec_graph_captured")
    # Both disk and authority can advance after acquisition without changing this view.
    (spec_dir / "spec.md").write_bytes(b"FR-000001: Live drift.\n")
    store.apply_lifecycle(spec_id="demo", operation_id="later", changes=(
        ElementRevision(label, "2", "Requirement", "Later body"),))
    result = module.build_captured_identity_graph(
        spec_id="demo", lifecycle="phase_a", generator_version="captured-test",
        sources=projected_sources, policy_paths=(),
        memory=(module.CapturedGraphMemory("canonical-spec", memory_sources, tuple(rows), audit),),
        re_artifacts=(), re_sources=(), history=history,
    )
    assert render_spec_graph(result) == render_spec_graph(expected)


def _api():
    return importlib.import_module("echelon.spec_graph_captured")


def _sha(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _history(labels=()):
    # An explicitly unassessed imported-history fixture, not a store acquisition.
    value = dict(version="1", workspace_uuid="11111111-1111-4111-8111-111111111111",
                 epoch_uuid="22222222-2222-4222-8222-222222222222", spec_id="demo",
                 entities=[], revisions=[], lineage=[], reference_claims=[], issue_occurrences=[])
    for label in labels:
        kind, suffix = label.split("-", 1)
        value["entities"].append(dict(spec_id="demo", element_id=label, kind=kind, subject=label,
                                      ordinal=suffix.lstrip("0") if suffix.isdecimal() else None,
                                      status="imported", revision=None))
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return IdentityHistorySnapshot(payload, hashlib.sha256(payload.encode()).hexdigest())


def _sources(trees=None, files=()):
    trees = (_tree(),) if trees is None else trees
    return ProjectedPublicationSources(trees, files, snapshot_source_manifest(trees=trees, files=files))


def _args(**changes):
    return dict(spec_id="demo", lifecycle="phase_a", generator_version="explicit-version",
                sources=_sources(), policy_paths=(),
                memory=(_api().CapturedGraphMemory("canonical-spec", (), (), _audit()),),
                re_artifacts=(), re_sources=(), history=_history()) | changes


def _expected_graph(history, nodes, edges, inputs, receipts, *, lifecycle="phase_a"):
    # Literal wire contract for empty retained history; no production projection oracle.
    inputs = [*inputs, GraphInput(
        "identity://11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/demo",
        "sha256:" + history.sha256, "identity_history", True)]
    nodes = [GraphNode("spec:demo", "Spec", {
        "spec_id": "demo", "path": "specs/demo", "lifecycle": lifecycle,
        "identity_projection": {"version": "1", "workspace_uuid": "11111111-1111-4111-8111-111111111111",
                                "epoch_uuid": "22222222-2222-4222-8222-222222222222", "history_sha256": history.sha256},
    }), *nodes]
    wire = dict(schema_version=1, node_projection_version=2, generator_version="explicit-version", spec_id="demo",
                source_set_digest=_digest([x.to_dict() for x in sorted(inputs, key=lambda x: (x.role, x.path)) if x.role != "memory_audit_report"]),
                memory_state_digest=_digest([x.to_dict() for x in sorted(receipts, key=lambda x: x.domain)]),
                inputs=[x.to_dict() for x in sorted(inputs, key=lambda x: (x.role, x.path))],
                nodes=[x.to_dict() for x in sorted(nodes, key=lambda x: x.id)],
                edges=[x.to_dict() for x in sorted(edges, key=lambda x: (x.source, x.type, x.target))])
    return wire, (json.dumps(wire, indent=2, sort_keys=True) + "\n").encode()


def _expected_receipt(domain, sources, *, row_count=None):
    source_digest = _digest([dict(path=s.path, hash=_sha(s.content), artifact_kind=s.artifact_kind, room=s.room)
                             for s in sorted(sources, key=lambda s: s.path)])
    normalized = dict(schema_version=1, wing="captured-test-wing", status="pass", artifact_count=1,
                      expected_count=1, present_current_count=1, missing=[], stale=[], wrong_wing=[], wrong_room=[],
                      duplicate=[], non_canonical=[], lifecycle_excluded=[], errors=[])
    if domain == "published-re":
        normalized.update(artifact_count=0, expected_count=row_count, present_current_count=row_count)
    audit_hash = _digest(normalized)
    virtual = "mempalace://published-re/audit" if domain == "published-re" else f"mempalace://{domain}/demo/audit"
    return (GraphInput(virtual, audit_hash, "memory_audit_report", domain == "canonical-spec", "pass", source_digest),
            MemoryReceipt(domain, source_digest, audit_hash, "pass"))


@pytest.mark.parametrize("exists", [False, True])
def test_complete_canonical_only_wire_for_missing_and_empty_selected_tree(exists):
    # Catch invented files, missing canonical receipts, implicit versions and manifest fields in graph wire.
    args = _args(sources=_sources((_tree(exists=exists),)))
    item, receipt = _expected_receipt("canonical-spec", ())
    wire, rendered = _expected_graph(args["history"], [], [], [item], [receipt])
    result = _api().build_captured_identity_graph(**args)
    assert result.to_dict() == wire
    assert render_spec_graph(result) == rendered
    assert result.memory_receipts == (receipt,)


def _three_domains():
    from echelon.mempalace_requirements import PlannedRequirementDrawer
    from echelon.spec_graph_re import GraphReArtifact, GraphReSource, GraphReTopology
    from echelon.topology_registry import TopologyArtifactReceipt
    from harness.re_artifacts import ReArtifactDescriptor
    paths = ("specs/demo/plan.md", "specs/demo/evidence/verify.md", "re/sources/api/architecture.md")
    groups = []
    for index, (domain, path, kind) in enumerate(zip(
        ("canonical-spec", "spec-evidence", "published-re"), paths,
        ("supporting-context", "spec-evidence", "re-architecture"),
    )):
        source = GraphMemorySource(path, b"captured", kind, "notes")
        row = PlannedRequirementDrawer(f"row-{index}", "context", "notes", path,
                                        _sha(b"captured"), _sha(b"captured")[7:], "c" * 64)
        groups.append(_api().CapturedGraphMemory(domain, (source,), (row,), _audit()))
    artifacts = tuple(GraphReArtifact(ReArtifactDescriptor(kind, path, _sha(content), scope, source), content)
                      for path, kind, content, scope, source in (
                          (paths[2], "re-architecture", b"captured", "source", "api"),
                          ("re/sources/api/decisions/a.md", "re-decision", b"# Source choice\n", "source", "api"),
                          ("re/workspace/decisions/b.md", "re-decision", b"# Workspace choice\n", "workspace", None)))
    receipt = TopologyArtifactReceipt("receipt", "re/topology/sources/api/receipt.json", _sha(b"receipt"))
    source = GraphReSource("api", ".", ".", "observed", 2, "semantic",
                           "re/sources/api/manifest.json", GraphReTopology("api", ".", 7, "topology", receipt, b"receipt"))
    re_files = {a.descriptor.path.removeprefix("re/"): a.content for a in artifacts}
    re_files.update({"sources/api/manifest.json": b"unparsed dependency", "topology/sources/api/receipt.json": b"receipt"})
    return _args(sources=_sources((_tree(re_files, root="re"), _tree({"plan.md": b"captured", "evidence/verify.md": b"captured"}))),
                 memory=tuple(reversed(groups)), re_artifacts=artifacts, re_sources=(source,),
                 policy_paths=tuple(a.descriptor.path for a in reversed(artifacts)))


def test_complete_three_domain_wire_decisions_topology_and_fixed_order():
    # Catch optional-domain omission, RE annotation order and cross-domain role loss.
    args = _three_domains()
    nodes, edges, inputs, receipts = [], [], [], []
    for index, (domain, role, mining) in enumerate((
        ("canonical-spec", "supporting-context", "mined"),
        ("spec-evidence", "verification-evidence", "mined"),
        ("published-re", "reverse-engineering", "mined"),
    )):
        group = next(x for x in args["memory"] if x.domain == domain)
        source, = group.sources
        artifact_id = "artifact:demo:" + source.path
        properties = dict(path=source.path, role=role, hash=_sha(b"captured"), mining_status=mining)
        if domain == "published-re":
            properties.update(re_artifact_kind="re-architecture", re_scope="source", re_source_id="api")
        nodes.extend([GraphNode(artifact_id, "Artifact", properties), GraphNode(f"drawer:demo:row-{index}", "MemPalaceDrawer", {
            "drawer_id": f"row-{index}", "source_path": source.path, "room": "notes", "artifact_kind": source.artifact_kind,
            "artifact_hash": _sha(b"captured"), "content_hash": "c" * 64, "presence": "present", "reconciliation_status": "pass", "issue_codes": [],
        })])
        edges.append(GraphEdge(artifact_id, "STORED_AS", f"drawer:demo:row-{index}", {"presence": "present", "reconciliation_status": "pass"}))
        inputs.append(GraphInput(source.path, _sha(b"captured"), role.replace("-", "_"), False))
        audit_input, receipt = _expected_receipt(domain, group.sources, row_count=1)
        inputs.append(audit_input)
        receipts.append(receipt)
    for artifact, key, title, source_id in (
        (args["re_artifacts"][1], "decision:api:decisions/a.md", "Source choice", "api"),
        (args["re_artifacts"][2], "decision:workspace:decisions/b.md", "Workspace choice", None),
    ):
        path = artifact.descriptor.path
        properties = dict(path=path, role="reverse-engineering", hash=_sha(artifact.content), mining_status="not-mined-by-policy",
                          re_artifact_kind="re-decision", re_scope="source" if source_id else "workspace")
        if source_id:
            properties["re_source_id"] = source_id
        nodes.extend([GraphNode("artifact:demo:" + path, "Artifact", properties),
                      GraphNode(key, "Decision", dict(path=path, title=title) | ({"source_id": "api"} if source_id else {"scope": "workspace"}))])
        inputs.append(GraphInput(path, _sha(artifact.content), "reverse_engineering", False))
        edges.extend([GraphEdge("source:api" if source_id else "spec:demo", "HAS_DECISION" if source_id else "INFORMED_BY_DECISION", key, {}),
                      GraphEdge(key, "DOCUMENTED_BY", "artifact:demo:" + path, {})])
    path = "re/topology/sources/api/receipt.json"
    nodes.extend([GraphNode("artifact:demo:" + path, "Artifact", dict(path=path, role="topology-receipt", hash=_sha(b"receipt"), mining_status="not-mined-by-policy")),
                  GraphNode("source:api", "SourceRoot", dict(source_id="api", path=".", publication_status="observed", semantic_generation=2,
                      semantic_fingerprint="semantic", semantic_receipt_path="re/sources/api/manifest.json", topology_generation=7,
                      topology_fingerprint="topology", topology_receipt_path=path))])
    inputs.append(GraphInput(path, _sha(b"receipt"), "topology_receipt", False))
    edges.extend([GraphEdge("spec:demo", "USES_SOURCE", "source:api", {}),
                  GraphEdge("source:api", "HAS_TOPOLOGY_RECEIPT", "artifact:demo:" + path, {}),
                  GraphEdge("source:api", "DESCRIBED_BY", "artifact:demo:re/sources/api/architecture.md", {})])
    wire, rendered = _expected_graph(args["history"], nodes, edges, inputs, receipts)
    result = _api().build_captured_identity_graph(**args)
    assert result.to_dict() == wire
    assert render_spec_graph(result) == rendered
    assert result.memory_receipts == tuple(receipts)


def _reject(args):
    with pytest.raises(SpecGraphError) as caught:
        _api().build_captured_identity_graph(**args)
    assert str(caught.value) == "invalid captured identity graph assembly"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("field,value", [
    ("spec_id", None), ("spec_id", "../demo"), ("spec_id", "demo\ud800"),
    ("lifecycle", "unknown"), ("lifecycle", []),
    ("generator_version", None), ("generator_version", ""), ("generator_version", "\ud800"),
    ("sources", None), ("sources", {}), ("policy_paths", []), ("policy_paths", ([],)),
    ("memory", []), ("memory", (None,)), ("memory", ()),
    ("re_artifacts", []), ("re_artifacts", (None,)), ("re_sources", []), ("re_sources", (None,)),
    ("history", None),
])
def test_outer_boundary_errors_are_bounded(field, value):
    _reject(_args(**{field: value}))


@pytest.mark.parametrize("mutation", [
    "stale-manifest", "tampered-payload", "tampered-sha", "manifest-subclass", "manifest-string-subclass",
    "source-subclass", "tree-subclass", "damaged-tree", "wrong-root", "broader-root", "no-root",
    "tree-list", "file-list", "overlap", "damaged-image", "hidden-bad-hash", "binary-bad-hash",
    "missing-with-bytes", "present-with-none", "duplicate-tree", "noncanonical-root",
])
def test_source_manifest_and_selected_root_validation(mutation):
    args = _args()
    sources = args["sources"]
    if mutation == "stale-manifest":
        sources = replace(sources, trees=(_tree({"spec.md": b"changed"}),))
    elif mutation == "tampered-payload":
        sources = replace(sources, manifest=replace(sources.manifest, payload="private document"))
    elif mutation == "tampered-sha":
        sources = replace(sources, manifest=replace(sources.manifest, sha256="0" * 64))
    elif mutation == "manifest-subclass":
        class Sub(SourceManifestSnapshot):
            pass
        sources = replace(sources, manifest=Sub(sources.manifest.payload, sources.manifest.sha256))
    elif mutation == "manifest-string-subclass":
        class Sub(str):
            pass
        sources = replace(sources, manifest=replace(sources.manifest, payload=Sub(sources.manifest.payload)))
    elif mutation == "source-subclass":
        class Sub(ProjectedPublicationSources):
            pass
        sources = Sub(sources.trees, sources.files, sources.manifest)
    elif mutation in {"wrong-root", "broader-root", "no-root"}:
        trees = () if mutation == "no-root" else (_tree(root="specs" if mutation == "broader-root" else "specs/other"),)
        sources = _sources(trees)
    elif mutation == "tree-subclass":
        class Sub(type(sources.trees[0])):
            pass
        sources = replace(sources, trees=(Sub("specs/demo", True, sources.trees[0].directories, ()),))
    elif mutation == "damaged-tree":
        object.__delattr__(sources.trees[0], "files")
    elif mutation == "tree-list":
        sources = replace(sources, trees=list(sources.trees))
    elif mutation == "file-list":
        sources = replace(sources, files=[])
    elif mutation == "overlap":
        sources = replace(sources, files=(ProjectPathSnapshot("specs/demo/spec.md", PublicationImageDescriptor("missing", None, None), None),))
    elif mutation in {"hidden-bad-hash", "binary-bad-hash", "damaged-image"}:
        sources = _sources((_tree({".hidden" if mutation == "hidden-bad-hash" else "unknown.bin": b"\xff\x00"}),))
        image = sources.trees[0].files[0].image
        if mutation == "damaged-image":
            object.__delattr__(image, "kind")
        else:
            object.__setattr__(image, "sha256", "0" * 64)
    elif mutation in {"missing-with-bytes", "present-with-none"}:
        item = ProjectPathSnapshot("external.bin", PublicationImageDescriptor("missing", None, None), None)
        sources = _sources(files=(item,))
        if mutation == "missing-with-bytes":
            object.__setattr__(item, "content", b"")
        else:
            object.__setattr__(item, "image", PublicationImageDescriptor("file", hashlib.sha256(b"").hexdigest(), 0o644))
    elif mutation == "duplicate-tree":
        sources = replace(sources, trees=sources.trees * 2)
    elif mutation == "noncanonical-root":
        sources = replace(sources, trees=(replace(sources.trees[0], path="specs//demo"),))
    _reject(args | {"sources": sources})


@pytest.mark.parametrize("path", ["specs/demo/absent", "specs/demo/../other", "specs/demo//plan.md", "./specs/demo/plan.md",
                                  "/specs/demo/plan.md", "specs/demolition/plan.md", "resources/a", "re", "specs/demo",
                                  "specs/demo/spec-artifact-graph.json", "specs/demo/\ud800"])
def test_policy_paths_are_explicit_canonical_present_and_scoped(path):
    args = _args(sources=_sources((_tree({"plan.md": b"x", "spec-artifact-graph.json": b"old"}),)))
    _reject(args | {"policy_paths": (path,)})


def test_selected_missing_file_is_distinct_from_present_empty_file():
    missing = ProjectPathSnapshot("re/empty.bin", PublicationImageDescriptor("missing", None, None), None)
    args = _args(sources=_sources(files=(missing,)), policy_paths=(missing.path,))
    _reject(args)
    present = replace(missing, image=PublicationImageDescriptor("file", hashlib.sha256(b"").hexdigest(), 0o644), content=b"")
    result = _api().build_captured_identity_graph(**(args | {"sources": _sources(files=(present,))}))
    assert next(x for x in result.inputs if x.path == present.path).hash == _sha(b"")


@pytest.mark.parametrize("mutation", [
    "duplicate-policy", "duplicate-domain", "no-canonical", "empty-evidence", "empty-re", "domain-subclass", "domain-list",
    "source-list", "source-subclass", "source-slot", "source-path-list", "source-content-bytearray", "source-mismatch",
    "source-uncaptured", "source-scope", "rows-list", "row-slot", "row-subclass", "row-hash", "row-duplicate",
    "audit-slot", "audit-subclass", "audit-recursive", "audit-origin", "audit-counter", "audit-issue",
    "descriptor-slot", "descriptor-subclass", "artifact-content", "artifact-uncaptured", "artifact-hash", "artifact-duplicate",
    "re-source-slot", "re-source-duplicate", "semantic-uncaptured", "topology-slot", "receipt-slot", "receipt-content", "receipt-uncaptured",
    "absent-preceding-artifact", "history-slot", "history-sha", "history-recursive",
])
def test_damaged_nested_records_and_cross_source_contradictions(mutation):
    args = _three_domains()
    groups = list(reversed(args["memory"]))
    group = groups[0]
    if mutation == "duplicate-policy":
        args["policy_paths"] *= 2
    elif mutation == "duplicate-domain":
        groups.append(group)
    elif mutation == "no-canonical":
        groups.pop(0)
    elif mutation in {"empty-evidence", "empty-re"}:
        index = 1 if mutation == "empty-evidence" else 2
        groups[index] = replace(groups[index], sources=())
    elif mutation == "domain-subclass":
        class Sub(type(group)):
            pass
        groups[0] = Sub(group.domain, group.sources, group.planned_rows, group.audit)
    elif mutation == "domain-list":
        groups[0] = replace(group, domain=[])
    elif mutation == "source-list":
        groups[0] = replace(group, sources=list(group.sources))
    elif mutation == "source-subclass":
        class Sub(GraphMemorySource):
            pass
        groups[0] = replace(group, sources=(Sub(**asdict(group.sources[0])),))
    elif mutation.startswith("source-"):
        source = group.sources[0]
        if mutation == "source-slot":
            object.__delattr__(source, "content")
        else:
            field, value = {
                "source-path-list": ("path", []), "source-content-bytearray": ("content", bytearray(b"captured")),
                "source-mismatch": ("content", b"valid elsewhere"), "source-uncaptured": ("path", "specs/demo/absent"),
                "source-scope": ("path", "re/sources/api/architecture.md"),
            }[mutation]
            object.__setattr__(source, field, value)
    elif mutation == "rows-list":
        groups[0] = replace(group, planned_rows=list(group.planned_rows))
    elif mutation == "row-slot":
        object.__delattr__(group.planned_rows[0], "drawer_id")
    elif mutation == "row-subclass":
        class Sub(type(group.planned_rows[0])):
            pass
        groups[0] = replace(group, planned_rows=(Sub(**asdict(group.planned_rows[0])),))
    elif mutation == "row-hash":
        groups[0] = replace(group, planned_rows=(replace(group.planned_rows[0], artifact_hash="sha256:" + "0" * 64),))
    elif mutation == "row-duplicate":
        groups[0] = replace(group, planned_rows=group.planned_rows * 2)
    elif mutation == "audit-slot":
        object.__delattr__(group.audit, "status")
    elif mutation == "audit-subclass":
        class Sub(GraphMemoryAudit):
            pass
        groups[0] = replace(group, audit=Sub(**asdict(group.audit)))
    elif mutation.startswith("audit-"):
        loop = []
        loop.append(loop)
        field, value = {"audit-recursive": ("errors", (loop,)), "audit-origin": ("origin", "inferred"),
                        "audit-counter": ("expected_count", True), "audit-issue": ("missing", ("\ud800",))}[mutation]
        groups[0] = replace(group, audit=replace(group.audit, **{field: value}))
    elif mutation == "descriptor-slot":
        object.__delattr__(args["re_artifacts"][0].descriptor, "path")
    elif mutation == "descriptor-subclass":
        artifact = args["re_artifacts"][0]
        class Sub(type(artifact.descriptor)):
            pass
        args["re_artifacts"] = (replace(artifact, descriptor=Sub(**asdict(artifact.descriptor))), *args["re_artifacts"][1:])
    elif mutation in {"artifact-content", "artifact-uncaptured", "artifact-hash"}:
        artifact = args["re_artifacts"][0]
        if mutation == "artifact-content":
            # Still individually valid to the lower RE builder, but wrong captured bytes.
            artifact = replace(artifact, content=b"other", descriptor=replace(artifact.descriptor, sha256=_sha(b"other")))
        else:
            artifact = replace(artifact, descriptor=replace(artifact.descriptor, **{
                "path" if mutation == "artifact-uncaptured" else "sha256": "re/sources/api/absent" if mutation == "artifact-uncaptured" else "sha256:" + "0" * 64}))
        args["re_artifacts"] = (artifact, *args["re_artifacts"][1:])
    elif mutation == "artifact-duplicate":
        args["re_artifacts"] *= 2
    elif mutation == "re-source-slot":
        object.__delattr__(args["re_sources"][0], "semantic_receipt_path")
    elif mutation == "re-source-duplicate":
        args["re_sources"] *= 2
    elif mutation == "semantic-uncaptured":
        args["re_sources"] = (replace(args["re_sources"][0], semantic_receipt_path="re/sources/api/absent"),)
    elif mutation == "topology-slot":
        object.__delattr__(args["re_sources"][0].topology, "receipt")
    elif mutation == "receipt-slot":
        object.__delattr__(args["re_sources"][0].topology.receipt, "path")
    elif mutation in {"receipt-content", "receipt-uncaptured"}:
        source = args["re_sources"][0]
        topology = source.topology
        if mutation == "receipt-content":
            topology = replace(topology, receipt_content=b"other", receipt=replace(topology.receipt, sha256=_sha(b"other")))
        else:
            topology = replace(topology, receipt=replace(topology.receipt, path="re/topology/sources/api/absent"))
        args["re_sources"] = (replace(source, topology=topology),)
    elif mutation == "absent-preceding-artifact":
        args["policy_paths"] = ()  # Architecture is contributed by memory, decisions are not.
    elif mutation == "history-slot":
        object.__delattr__(args["history"], "payload")
    elif mutation == "history-sha":
        args["history"] = replace(args["history"], sha256="0" * 64)
    elif mutation == "history-recursive":
        object.__setattr__(args["history"], "payload", args["history"])
    args["memory"] = tuple(groups)
    _reject(args)


def test_graph_bytes_are_retained_but_never_self_inputs():
    def arguments(content):
        return _args(sources=_sources((_tree({"spec-artifact-graph.json": content, ".hidden": b"\xff"}),)))
    first, second = arguments(b"old graph"), arguments(b"future graph")
    assert first["sources"].manifest != second["sources"].manifest
    assert render_spec_graph(_api().build_captured_identity_graph(**first)) == render_spec_graph(_api().build_captured_identity_graph(**second))
    path = "specs/demo/spec-artifact-graph.json"
    _reject(first | {"policy_paths": (path,)})
    group = first["memory"][0]
    _reject(first | {"memory": (replace(group, sources=(GraphMemorySource(path, b"old graph", "supporting-context", "notes"),)),)})


def test_policy_component_order_and_local_final_role_are_preserved():
    files = {"a.b": b"sibling", "a/b": b"child", "amendments/1/impact.md": b"control"}
    args = _args(sources=_sources((_tree(files),)), policy_paths=tuple("specs/demo/" + name for name in files))
    result = _api().build_captured_identity_graph(**args)
    extras = [item.path for item in result.inputs if item.path.endswith(("a.b", "a/b"))]
    assert extras == ["specs/demo/a/b", "specs/demo/a.b"]
    artifact = next(n for n in result.nodes if n.id == "artifact:demo:specs/demo/amendments/1/impact.md")
    assert artifact.properties["role"] == "amendment-control"
    assert sum(x.path == "specs/demo/amendments/1/impact.md" for x in result.inputs) == 1


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_process_control_propagates(exception, monkeypatch):
    args = _args()
    marker = exception("stop")
    def stop(**kwargs):
        raise marker
    monkeypatch.setattr(_api(), "snapshot_source_manifest", stop)
    with pytest.raises(exception) as caught:
        _api().build_captured_identity_graph(**args)
    assert caught.value is marker


@pytest.mark.parametrize("origin", ["returned", "exception"])
def test_partial_unavailable_audits_preserve_rows_and_origin_projection(origin):
    args = _three_domains()
    changed = []
    for group in args["memory"]:
        observation = _audit(origin=origin, status="unavailable", artifact_count=7,
            expected_count=9, present_current_count=2, errors=("outside observation", "row-2 warning"))
        if origin == "exception":
            observation = replace(observation, wing=None, artifact_count=0, expected_count=0,
                                  present_current_count=0, errors=("RuntimeError",))
        changed.append(replace(group, audit=observation))
    args["memory"] = tuple(changed)
    result = _api().build_captured_identity_graph(**args)
    drawers = [node for node in result.nodes if node.type == "MemPalaceDrawer"]
    assert len(drawers) == 3
    assert all(n.properties["presence"] == n.properties["reconciliation_status"] == "unavailable" for n in drawers)
    for receipt in result.memory_receipts:
        normalized = dict(schema_version=1, wing="captured-test-wing", status="unavailable", artifact_count=7,
                          expected_count=9, present_current_count=2, missing=[], stale=[], wrong_wing=[], wrong_room=[],
                          duplicate=[], non_canonical=[], lifecycle_excluded=[], errors=["outside observation", "row-2 warning"])
        if receipt.domain == "published-re" and origin == "returned":
            normalized.update(artifact_count=0, expected_count=1, present_current_count=1, errors=["row-2 warning"])
        if origin == "exception":
            normalized.update(wing=None, artifact_count=0, expected_count=0, present_current_count=0, errors=["RuntimeError"])
        assert receipt.audit_hash == _digest(normalized)


def test_duplicate_cross_domain_edges_reject_but_native_replacements_remain():
    args = _three_domains()
    canonical = args["memory"][2]
    evidence = args["memory"][1]
    # Same node key with another source retains native replacement behavior.
    evidence = replace(evidence, planned_rows=(replace(evidence.planned_rows[0], drawer_id="row-0"),))
    result = _api().build_captured_identity_graph(**(args | {"memory": (evidence, canonical, args["memory"][0])}))
    drawer = next(n for n in result.nodes if n.id == "drawer:demo:row-0")
    assert drawer.properties["source_path"] == evidence.sources[0].path
    assert sum(e.target == drawer.id and e.type == "STORED_AS" for e in result.edges) == 2
    # Repeating the same source-to-drawer assertion violates the existing graph model.
    evidence = replace(evidence, sources=canonical.sources, planned_rows=canonical.planned_rows)
    _reject(args | {"memory": (evidence, canonical, args["memory"][0])})


@pytest.mark.parametrize("source_path", [".", "sources/api"])
def test_full_render_matches_real_legacy_native_acquisition(tmp_path, monkeypatch, source_path, secure_posix):
    from echelon import spec_graph, artifact_index
    from echelon import mempalace_requirements as requirements
    from echelon import mempalace_spec_evidence as evidence
    from echelon import mempalace_re as re_memory
    from echelon import mempalace_audit as audits
    from harness.squad_source_snapshot import inspect_project_tree
    from tests.unit.test_spec_graph_structure import _rich_files
    from tests.unit.test_spec_graph_re import _native_fixture
    from tests.unit.test_spec_graph_memory import _NativeAdapter, _report

    spec_dir, artifacts, source = _native_fixture(tmp_path, source_path)
    files = _rich_files()
    files.pop("re-context.json")  # Preserve the actual typed-catalog attachment.
    files["run-history.json"] = b"{}"
    for name, content in files.items():
        path = spec_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (spec_dir / "amendments/10").mkdir()
    store = IdentityStore.initialize(tmp_path)
    labels = ("AC-000001", "FR-016b", "FR-1000000", "NFR-10000000", "T-10000000", "T-000001", "T-999999")
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple((label, label) for label in labels))
    history = store.identity_history(spec_id="demo")
    observed = _audit(wing="wing", status="warn", errors=("unrelated observation",))
    adapters = {domain: _NativeAdapter([]) for domain in ("canonical-spec", "spec-evidence", "published-re")}
    # External storage construction/audits are deterministic; all planning,
    # snapshot reads, source admission and graph/history transformations are real.
    monkeypatch.setattr(requirements, "create_requirement_memory_adapter", lambda *a, **kw: adapters["canonical-spec"])
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", lambda *a, **kw: adapters["spec-evidence"])
    monkeypatch.setattr(re_memory, "create_re_memory_adapter", lambda *a, **kw: adapters["published-re"])
    monkeypatch.setattr(audits, "audit_spec_memory", lambda *a, **kw: _report(observed))
    monkeypatch.setattr(evidence, "audit_spec_evidence_memory", lambda *a, **kw: _report(observed))
    monkeypatch.setattr(re_memory, "audit_re_memory", lambda *a, **kw: _report(observed))
    native = spec_graph.build_spec_graph(tmp_path, spec_dir)
    expected = project_identity_history(native, history)
    snapshots = {
        "canonical-spec": [requirements.load_canonical_spec_snapshot(tmp_path, spec_dir), *requirements.load_supporting_artifact_snapshots(tmp_path, spec_dir)],
        "spec-evidence": evidence.load_spec_evidence_artifact_snapshots(tmp_path, spec_dir, allow_unlanded=True),
        "published-re": [s for s in re_memory.load_re_artifact_snapshots(tmp_path) if s.source in {a.descriptor.path for a in artifacts}],
    }
    groups = tuple(_api().CapturedGraphMemory(domain, tuple(GraphMemorySource(
        s.source, s.content, s.artifact_metadata.get("artifact_kind", "requirement"), s.artifact_metadata.get("room", ""),
    ) for s in selected), tuple(adapters[domain].rows), observed) for domain, selected in snapshots.items())
    assert all(group.sources and group.planned_rows for group in groups)
    with inspect_project_tree(tmp_path, "re") as re_tree:
        pass
    with inspect_project_tree(tmp_path, "specs/demo") as spec_tree:
        pass
    args = _args(sources=_sources((re_tree, spec_tree)), memory=tuple(reversed(groups)), re_artifacts=artifacts, re_sources=(source,),
                 history=history, lifecycle=artifact_index.infer_lifecycle_stage(spec_dir), generator_version=native.generator_version,
                 policy_paths=tuple(a.descriptor.path for a in artifacts) + tuple(s.source for s in snapshots["spec-evidence"])
                 + ("re/sources/api/contracts.md",))  # Linked policy input, not admitted as a typed descriptor.
    before = render_spec_graph(expected)
    result = _api().build_captured_identity_graph(**args)
    assert render_spec_graph(result) == before
    assert result.to_dict() == expected.to_dict()
    assert result.memory_receipts == expected.memory_receipts
    assert any(e.type == "VERIFIED_BY" and e.properties["identity_assessment"] == "unassessed" for e in result.edges)
    assert all(n.properties["identity"]["revision"] is None for n in result.nodes if "identity" in n.properties)
    assert not any(n.type == "ElementRevision" for n in result.nodes)
    # A real file change after capture must not enter the captured build.
    (spec_dir / "spec.md").write_bytes(b"FR-999999: Changed after capture.\n")
    (tmp_path / artifacts[0].descriptor.path).write_bytes(b"changed descriptor bytes")
    assert render_spec_graph(_api().build_captured_identity_graph(**args)) == before
    assert not (spec_dir / "spec-artifact-graph.json").exists()


def _native_retained_args(tmp_path):
    args = _three_domains()
    content = b"FR-000001: Captured requirement.\n"
    rows = plan_canonical_requirement_drawers(content, source="specs/demo/spec.md", wing="captured-test-wing",
        artifact_metadata={"canonical": True, "artifact_hash": _sha(content)})
    source = GraphMemorySource("specs/demo/spec.md", content, "requirement", "")
    canonical = args["memory"][2]
    args["memory"] = (*args["memory"][:2], replace(canonical, sources=(source, *canonical.sources), planned_rows=(*rows, *canonical.planned_rows)))
    args["sources"] = _sources((args["sources"].trees[0], _tree({"spec.md": content, "plan.md": b"captured", "evidence/verify.md": b"captured"})))
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-000001", "Requirement"),))
    args["history"] = store.identity_history(spec_id="demo")
    return args


def test_every_output_record_is_detached_from_inputs_and_later_outputs(tmp_path, monkeypatch):
    args = _native_retained_args(tmp_path)
    retained_contributions = []
    for name in ("build_spec_graph_structure", "build_memory_graph_contribution", "build_re_graph_contribution"):
        original = getattr(_api(), name)
        def retain(*a, _original=original, **kw):
            value = _original(*a, **kw)
            retained_contributions.append((value, repr(value)))
            return value
        monkeypatch.setattr(_api(), name, retain)
    first = _api().build_captured_identity_graph(**args)
    before = render_spec_graph(first)
    second = _api().build_captured_identity_graph(**args)
    assert all(repr(value) == original for value, original in retained_contributions)
    next(n for n in second.nodes if n.type == "MemPalaceDrawer").properties["issue_codes"].append("later")
    next(n for n in second.nodes if "identity" in n.properties).properties["identity"]["status"] = "later"
    next(e for e in second.edges if e.type == "STORED_AS").properties["presence"] = "later"
    object.__setattr__(second.inputs[0], "hash", "later")
    object.__setattr__(second.memory_receipts[0], "status", "later")
    object.__setattr__(args["sources"].trees[0].files[0], "content", b"damaged")
    object.__setattr__(args["sources"].manifest, "payload", "damaged")
    object.__setattr__(args["memory"][2].sources[0], "content", b"damaged")
    object.__setattr__(args["memory"][2].planned_rows[0], "drawer_id", "damaged")
    object.__setattr__(args["memory"][2].audit, "status", "damaged")
    object.__setattr__(args["re_artifacts"][0].descriptor, "path", "damaged")
    object.__setattr__(args["re_sources"][0].topology.receipt, "path", "damaged")
    object.__setattr__(args["history"], "payload", "damaged")
    for value, _ in retained_contributions:
        for node in value.nodes:
            node.properties["damaged"] = ["contribution"]
    assert render_spec_graph(first) == before


def test_pure_assembly_has_no_external_state_access_or_writes(tmp_path, monkeypatch):
    import builtins
    import io
    import os
    import random
    import secrets
    import socket
    import sqlite3
    import subprocess
    import time
    import uuid
    from echelon import mempalace_requirements as requirements, mempalace_audit as audits
    from echelon import mempalace_re as re_memory, mempalace_spec_evidence as evidence, spec_memory_miner as miner
    from echelon import spec_graph, topology_registry
    from harness import re_registry, squad_publication, squad_source_snapshot, squad_source_projection
    args = _native_retained_args(tmp_path)
    before = render_spec_graph(_api().build_captured_identity_graph(**args))
    physical_before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    def forbidden(*a, **kw):
        raise AssertionError("external access")
    targets = [
        (builtins, "open"), (io, "open"), (os, "open"), (os, "stat"), (os, "lstat"),
        (os, "scandir"), (os, "listdir"), (os, "getcwd"), (os, "getenv"), (os, "urandom"),
        (type(os.environ), "__getitem__"), (type(os.environ), "get"),
        (Path, "read_bytes"), (Path, "read_text"), (Path, "write_bytes"), (Path, "write_text"),
        (Path, "stat"), (Path, "resolve"), (Path, "iterdir"), (Path, "glob"), (Path, "rglob"), (Path, "exists"),
        (subprocess, "Popen"), (subprocess, "run"), (socket, "socket"), (sqlite3, "connect"),
        (time, "time"), (time, "monotonic"), (time, "perf_counter"), (random, "random"), (secrets, "token_hex"), (uuid, "uuid4"),
        (IdentityStore, "initialize"), (IdentityStore, "reserve"), (IdentityStore, "identity_history"),
        (IdentityStore, "apply_lifecycle"), (IdentityStore, "import_identities"), (IdentityStore, "record_reference_claims"),
        (requirements, "create_requirement_memory_adapter"), (requirements, "load_canonical_spec_snapshot"),
        (requirements, "load_supporting_artifact_snapshots"), (audits, "audit_spec_memory"),
        (re_memory, "create_re_memory_adapter"), (re_memory, "load_re_artifact_snapshots"), (re_memory, "audit_re_memory"),
        (evidence, "create_spec_evidence_memory_adapter"), (evidence, "load_spec_evidence_artifact_snapshots"), (evidence, "audit_spec_evidence_memory"),
        (miner, "plan_canonical_requirement_drawers"), (miner, "plan_canonical_support_drawers"),
        (miner, "plan_re_artifact_drawers"), (miner, "plan_spec_evidence_artifact_drawers"),
        (re_registry, "load_published_index"), (re_registry, "canonical_re_artifact_descriptors"),
        (topology_registry, "load_topology_index"), (spec_graph, "build_spec_graph"), (spec_graph, "write_spec_graph"),
        (spec_graph, "_generator_version"), (spec_graph, "_write_spec_graph_bytes"),
        (squad_source_snapshot, "inspect_project_tree"), (squad_source_projection, "project_publication_source_images"),
        (squad_publication.SquadPublicationTransaction, "begin"), (squad_publication.SquadPublicationTransaction, "seal"),
        (squad_publication.PreparedSquadPublication, "inspect_sources"),
        (squad_publication.PreparedSquadPublication, "publish_sources"),
        (squad_publication.PreparedSquadPublication, "publish"),
        (squad_publication, "controller_lock_order"),
    ]
    with monkeypatch.context() as guard:
        for owner, name in targets:
            guard.setattr(owner, name, forbidden)
        result = _api().build_captured_identity_graph(**args)
        rendered = render_spec_graph(result)
    assert rendered == before
    physical_after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert physical_after == physical_before


@pytest.mark.parametrize("kind", ["recursive", "runtime-error", "decoder"])
def test_source_bearing_failures_leave_no_nested_exception(kind, monkeypatch):
    args = _args()
    if kind == "recursive":
        from echelon.spec_graph_structure import SpecGraphStructure
        loop = {}
        loop["private-source"] = loop
        value = SpecGraphStructure("demo", (), (GraphNode("spec:demo", "Spec", loop),), ())
        monkeypatch.setattr(_api(), "build_spec_graph_structure", lambda **kw: value)
    elif kind == "runtime-error":
        def fail(**kw):
            raise RuntimeError("private-source")
        monkeypatch.setattr(_api(), "build_spec_graph_structure", fail)
    else:
        args["sources"] = _sources((_tree({"inputs/catalog.json": b"{}", "inputs/traceability.json": b"private-source {"}),))
    _reject(args)


@pytest.mark.parametrize("order", ["captured-first", "models-first"])
def test_import_orders_keep_existing_model_identities(order):
    import os
    import subprocess
    import sys
    # Fresh processes are limited to import identity checks, outside the purity guard.
    modules = ["echelon.spec_graph_captured", "echelon.spec_graph", "echelon.spec_graph_memory", "echelon.spec_graph_re"]
    if order == "models-first":
        modules.reverse()
    script = "import importlib\n" + "\n".join(f"importlib.import_module({name!r})" for name in modules) + """
from echelon import spec_graph_captured as captured, spec_graph as graph, spec_graph_memory as memory, spec_graph_re as re
from echelon.mempalace_requirements import PlannedRequirementDrawer
from echelon.spec_memory_miner import CanonicalRequirementDrawerPlan
from harness.squad_source_projection import ProjectedPublicationSources
from harness.element_identity_snapshot import IdentityHistorySnapshot
assert captured.SpecArtifactGraph is graph.SpecArtifactGraph
assert captured.GraphMemorySource is memory.GraphMemorySource
assert captured.GraphReArtifact is re.GraphReArtifact
assert captured.PlannedRequirementDrawer is PlannedRequirementDrawer
assert captured.CanonicalRequirementDrawerPlan is CanonicalRequirementDrawerPlan
assert captured.ProjectedPublicationSources is ProjectedPublicationSources
assert captured.IdentityHistorySnapshot is IdentityHistorySnapshot
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                            env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_unused_re_observations_still_validate_without_creating_sources():
    args = _three_domains()
    source = args["re_sources"][0]
    args.update(re_artifacts=(), policy_paths=(), memory=(args["memory"][2],))
    result = _api().build_captured_identity_graph(**args)
    assert not any(n.type == "SourceRoot" for n in result.nodes)
    assert not any("receipt.json" in x.path for x in result.inputs)
    _reject(args | {"re_sources": (replace(source, semantic_generation=True),)})


def test_individually_valid_memory_bytes_cannot_replace_captured_source():
    args = _three_domains()
    original = args["memory"][2]
    content = b"another valid observation"
    source = replace(original.sources[0], content=content)
    row = replace(original.planned_rows[0], artifact_hash=_sha(content), canonical_spec_sha256=_sha(content)[7:])
    group = replace(original, sources=(source,), planned_rows=(row,))
    contribution = build_memory_graph_contribution(spec_id="demo", lifecycle="phase_a", domain=group.domain,
        sources=group.sources, planned_rows=group.planned_rows, audit=group.audit, known_node_ids=())
    assert next(x for x in contribution.inputs if x.path == source.path).hash == _sha(content)
    _reject(args | {"memory": (*args["memory"][:2], group)})


def test_full_assembly_requires_selected_artifact_without_changing_lower_level_skip():
    from echelon.spec_graph_re import build_re_graph_contribution
    args = _three_domains()
    contribution = build_re_graph_contribution(spec_id="demo", lifecycle="phase_a", artifacts=args["re_artifacts"],
        sources=args["re_sources"], artifact_nodes=(), stored_artifact_ids=())
    assert any(n.id == "source:api" for n in contribution.nodes)
    assert not any(n.type == "Decision" for n in contribution.nodes)
    _reject(args | {"policy_paths": ()})


def test_guarded_source_publication_matches_retained_derived_graph(tmp_path, secure_posix):
    spec_dir = tmp_path / "specs/demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_bytes(b"# Before\n")
    squad = tmp_path / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(tmp_path, squad, "4" * 32)
    stage = transaction.build_path("after.md")
    content = b"# Final\n"
    stage.write_bytes(content)
    target = Path("specs/demo/spec.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",)) as initial:
        projected = project_publication_source_images(initial)
    group = _api().CapturedGraphMemory("canonical-spec", (GraphMemorySource(target.as_posix(), content, "requirement", ""),), (), _audit())
    args = _args(sources=projected, memory=(group,))
    expected = render_spec_graph(_api().build_captured_identity_graph(**args))
    final = prepared.publish_sources(initial)
    final_sources = _sources(final.trees, final.files)
    assert final_sources.manifest == projected.manifest
    assert render_spec_graph(_api().build_captured_identity_graph(**(args | {"sources": final_sources}))) == expected
    assert (spec_dir / "spec.md").read_bytes() == content
    assert not (spec_dir / "spec-artifact-graph.json").exists()
