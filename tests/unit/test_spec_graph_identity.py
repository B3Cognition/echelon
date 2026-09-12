from dataclasses import replace
import hashlib
import json
from types import MappingProxyType
from urllib.parse import quote

import pytest

from echelon.spec_graph import GraphEdge, GraphInput, GraphNode, MemoryReceipt, SpecArtifactGraph, SpecGraphError, render_spec_graph
from harness.element_identity_bindings import IssueOccurrence
from harness.element_identity_lifecycle import ElementTransition
from harness.element_identity_snapshot import IdentityHistorySnapshot

from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_lifecycle import ElementCreate, ElementRevision, ElementRetirement
from harness.element_identity_store import IdentityStore

pytestmark = pytest.mark.unit


def retained_history_fixture(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Scene", "Original body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim("evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Scene", "Revised body"),))
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(
        ElementRetirement(label, "2", "No longer an active obligation"),))
    return store, label


def test_retirement_keeps_published_key_old_revision_and_reference_edge(tmp_path):
    store, label = retained_history_fixture(tmp_path)
    from echelon.spec_graph import GraphNode, SpecArtifactGraph
    base = SpecArtifactGraph("demo", "test", (), (
        GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
        GraphNode(f"req:demo:{label}", "Requirement", {"requirement_id": label}),
    ), (), ())
    from echelon.spec_graph_identity import project_identity_history
    projected = project_identity_history(base, store.identity_history(spec_id="demo"))
    nodes = {node.id: node for node in projected.nodes}
    assert nodes[f"req:demo:{label}"].properties["identity"]["status"] == "retired"
    old = next(node for node in projected.nodes if node.type == "ElementRevision"
               and node.properties["revision"] == "1")
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    assert old.properties["content"] == "Original body"
    assert claim.properties["target_revision_matches_current"] is False
    assert any(edge.source == claim.id and edge.type == "ASSESSES_REVISION"
               and edge.target == old.id for edge in projected.edges)


def base_graph(*nodes, edges=(), inputs=()):
    return SpecArtifactGraph("demo", "test", inputs,
                             (GraphNode("spec:demo", "Spec", {"spec_id": "demo"}), *nodes), edges, ())


def encoded(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return IdentityHistorySnapshot(payload, hashlib.sha256(payload.encode("ascii")).hexdigest())


def project(base, snapshot):
    from echelon.spec_graph_identity import project_identity_history
    return project_identity_history(base, snapshot)


def by_type(graph, kind):
    return [node for node in graph.nodes if node.type == kind]


def test_exact_context_keys_history_rows_edges_and_detached_graph(tmp_path):
    store, label = retained_history_fixture(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    value = json.loads(snapshot.payload)
    nested = {"items": [MappingProxyType({"source_line": 9, "tuple": (1, 2)})]}
    base = base_graph(
        GraphNode(f"req:demo:{label}", "Requirement", MappingProxyType({
            "requirement_id": label, "source_text": "Markdown", "source_path": "spec.md", "source_line": 8,
            "nested": nested})),
        GraphNode("evidence", "Artifact", {"nested": {"list": [1, False, None, 2.5]}}),
        edges=(GraphEdge(f"req:demo:{label}", "VERIFIED_BY", "evidence", {"complete": True, "nested": nested}),
               GraphEdge(f"req:demo:{label}", "STORED_AS", "evidence", {"original": [4]})),
        inputs=(GraphInput("spec.md", "sha256:" + "b" * 64, "source", True),))
    base = replace(base, memory_receipts=(MemoryReceipt("requirements", "d", "a", "complete"),))
    result = project(base, snapshot)
    assert result.generator_version == base.generator_version
    assert result.memory_receipts == base.memory_receipts
    assert result.inputs[:-1] == base.inputs
    assert result.inputs[-1] == GraphInput(
        f'identity://{value["workspace_uuid"]}/{value["epoch_uuid"]}/{quote("demo", safe="")}',
        "sha256:" + snapshot.sha256, "identity_history", True)
    assert result.nodes[0].properties == {"spec_id": "demo", "identity_projection": {
        "version": "1", "workspace_uuid": value["workspace_uuid"], "epoch_uuid": value["epoch_uuid"],
        "history_sha256": snapshot.sha256}}
    entity = result.nodes[1]
    assert entity.id == f"req:demo:{label}"
    assert entity.properties["identity"] == {
        "workspace_uuid": value["workspace_uuid"], "epoch_uuid": value["epoch_uuid"],
        "kind": "FR", "ordinal": "1", "subject": "Scene", "status": "retired", "revision": "3", "rendered": True}
    assert entity.properties["source_line"] == 8
    assert entity.properties["source_text"] == "Markdown"
    assert entity.properties["source_path"] == "spec.md"
    assert [n.properties for n in by_type(result, "ElementRevision")] == value["revisions"]
    namespace = [value[k] for k in ("workspace_uuid", "epoch_uuid", "spec_id")]
    for node, row in zip(by_type(result, "ElementRevision"), value["revisions"]):
        assert node.id == "identity-revision:" + hashlib.sha256(json.dumps(
            namespace + [label, row["revision"]], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert by_type(result, "IdentitySource")[0].properties == {
        "spec_id": "demo", "source_path": "evidence.md", "source_sha256": "a" * 64}
    assert {e.type for e in result.edges} == {
        "VERIFIED_BY", "STORED_AS", "HAS_IDENTITY", "HAS_REVISION", "CURRENT_REVISION",
        "REFERENCES_IDENTITY", "ASSESSES_REVISION", "HAS_SOURCE"}
    assert result.edges[0].properties["complete"] is True
    assert all(e.properties["identity_assessment"] == "unassessed" for e in result.edges[:2])
    result.nodes[1].properties["nested"]["items"].append("changed")
    assert len(nested["items"]) == 1
    nested["items"].append("source changed")
    assert result.edges[0].properties["nested"]["items"] == [{"source_line": 9, "tuple": (1, 2)}]
    assert "identity" not in base.nodes[1].properties


def test_all_kinds_imported_heads_wide_labels_and_task_progress(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    labels = ["FR-001", "NFR-composite.1", "AC-999999", "U-1000000", "A-" + "9" * 5000, "ISS-old", "T-S01"]
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple((label, "Legacy") for label in labels))
    base = base_graph(GraphNode("task:demo:T-S01", "Task", {"task_id": "T-S01", "status": "done", "source_line": 42}))
    result = project(base, store.identity_history(spec_id="demo"))
    assert [n.type for n in result.nodes if "identity" in n.properties].count("Requirement") == 3
    assert {n.type for n in result.nodes if "identity" in n.properties} == {"Requirement", "Unknown", "Assumption", "Issue", "Task"}
    for node in result.nodes:
        if "identity" in node.properties:
            assert node.properties["identity"]["revision"] is None
            assert node.properties["identity"]["status"] == "imported"
            assert node.properties["identity"]["rendered"] == (node.type == "Task")
            if node.type != "Task":
                assert len(node.properties) == 2
    assert result.nodes[1].properties["status"] == "done"
    assert result.nodes[1].properties["source_line"] == 42
    assert len([e for e in result.edges if e.type == "HAS_IDENTITY"]) == 7


def test_history_keys_survive_new_revision_claims_and_old_occurrences(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(label, "Issue", "Old body", "reserve"),))
    for op in ("one", "two"):
        store.record_reference_claims(spec_id="demo", operation_id="ref-" + op, claims=(
            ReferenceClaim("evidence.md", "a" * 64, op, label, "1", "evidence"),
            ReferenceClaim("evidence.md", "a" * 64, op + "-null", label, None, "reference")))
        store.record_issue_occurrences(spec_id="demo", operation_id="occ-" + op, occurrences=(
            IssueOccurrence(label, "1", "report", "b" * 64, "ISS-display", "Issue", "Old body"),))
    old_snapshot = store.identity_history(spec_id="demo")
    old = project(base_graph(), old_snapshot)
    assert len(by_type(old, "IdentitySource")) == len(by_type(old, "IdentityReport")) == 1
    assert len(by_type(old, "IssueOccurrence")) == 2
    decoded = json.loads(old_snapshot.payload)
    namespace = [decoded[k] for k in ("workspace_uuid", "epoch_uuid", "spec_id")]
    formats = {
        "ReferenceClaim": ("identity-reference:", ["operation_id", "entry_index"]),
        "IssueOccurrence": ("identity-occurrence:", ["operation_id", "entry_index"]),
        "IdentitySource": ("identity-source:", ["source_path", "source_sha256"]),
        "IdentityReport": ("identity-report:", ["report_id", "report_sha256"]),
    }
    for node in old.nodes:
        if node.type in formats:
            prefix, keys = formats[node.type]
            expected = hashlib.sha256(json.dumps(namespace + [node.properties[k] for k in keys],
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            assert node.id == prefix + expected
    assert by_type(old, "IdentityReport")[0].properties == {"spec_id": "demo", "report_id": "report", "report_sha256": "b" * 64}
    first_claim = by_type(old, "ReferenceClaim")[0]
    assert first_claim.properties == decoded["reference_claims"][0] | {"target_revision_matches_current": True}
    for occurrence in by_type(old, "IssueOccurrence"):
        outgoing = [e for e in old.edges if e.source == occurrence.id]
        assert {e.type for e in outgoing} == {"OCCURRENCE_OF", "OBSERVES_REVISION", "HAS_REPORT"}
        assert all(e.properties == {} for e in outgoing)
    duplicate = json.loads(old_snapshot.payload)
    duplicate["issue_occurrences"].append(duplicate["issue_occurrences"][0].copy())
    with pytest.raises(SpecGraphError):
        project(base_graph(), encoded(duplicate))
    assert [n.properties["target_revision_matches_current"] for n in by_type(old, "ReferenceClaim")] == [True, False, True, False]
    assert len([e for e in old.edges if e.type == "ASSESSES_REVISION"]) == 2
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(ElementRevision(label, "1", "Issue", "New body"),))
    store.record_reference_claims(spec_id="demo", operation_id="ref-new", claims=(ReferenceClaim("evidence.md", "a" * 64, "new", label, "2", "evidence"),))
    store.record_issue_occurrences(spec_id="demo", operation_id="occ-new", occurrences=(IssueOccurrence(label, "2", "report", "b" * 64, "ISS-display", "Issue", "New body"),))
    store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(ElementRetirement(label, "2", "Resolved"),))
    new_snapshot = store.identity_history(spec_id="demo")
    new = project(base_graph(), new_snapshot)
    assert render_spec_graph(old) != render_spec_graph(new)
    later = {n.id: n for n in new.nodes}
    for node in old.nodes:
        if node.type in {"ElementRevision", "IssueOccurrence", "IdentitySource", "IdentityReport"}:
            assert later[node.id] == node
        if node.type == "ReferenceClaim":
            assert later[node.id].properties == dict(node.properties) | {"target_revision_matches_current": False}
    assert set((e.source, e.type, e.target) for e in old.edges if e.type != "CURRENT_REVISION") <= set((e.source, e.type, e.target) for e in new.edges)
    assert [n.properties for n in by_type(new, "IssueOccurrence")] == json.loads(new_snapshot.payload)["issue_occurrences"]
    store.reserve(spec_id="demo", kind="FR", operation_id="unused", count=1)
    assert store.identity_history(spec_id="demo") == new_snapshot


def test_replace_split_merge_keep_original_lineage_rows(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    labels = store.reserve(spec_id="demo", kind="AC", operation_id="reserve", count=5)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(labels[0], "Root", "body", "reserve"),))
    for kind, predecessors, successors in (("replace", labels[:1], labels[1:2]), ("split", labels[1:2], labels[2:4]), ("merge", labels[2:4], labels[4:])):
        store.apply_lifecycle(spec_id="demo", operation_id=kind, changes=(ElementTransition(kind, tuple((p, "1") for p in predecessors), tuple(ElementCreate(s, s, "body", "reserve") for s in successors), kind + " reason"),))
    snapshot = store.identity_history(spec_id="demo")
    result = project(base_graph(), snapshot)
    nodes = {n.id: n for n in result.nodes}
    links = [e for e in result.edges if e.type == "SUCCESSOR_REVISION"]
    assert len(links) == 5
    assert [e.properties for e in links] == json.loads(snapshot.payload)["lineage"]
    assert all(nodes[e.source].properties["status"] == nodes[e.target].properties["status"] == "active" for e in links)
    assert len(by_type(result, "ElementRevision")) == 9


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(version="2"), lambda v: v.update(extra="no"),
    lambda v: v.update(workspace_uuid="bad"), lambda v: v.update(epoch_uuid=v["epoch_uuid"].upper()),
    lambda v: v.update(spec_id="other"), lambda v: v.update(entities={}),
    lambda v: v["entities"][0].update(spec_id="other"), lambda v: v["entities"][0].update(ordinal="2"),
    lambda v: v["entities"][0].update(subject=None), lambda v: v["entities"][0].update(revision="2"),
    lambda v: v["entities"][0].update(status="active"), lambda v: v["entities"].append(v["entities"][0].copy()),
    lambda v: v["entities"].append(v["entities"][0] | {"element_id": "FR-000001"}),
    lambda v: v["revisions"][0].update(content_sha256="b" * 64),
    lambda v: v["revisions"][0].update(revision="01"), lambda v: v["revisions"][0].update(reason="bad"),
    lambda v: v["revisions"][0].update(element_id="FR-404"), lambda v: v["revisions"].append(v["revisions"][0].copy()),
    lambda v: v["revisions"][0].pop("subject"), lambda v: v["reference_claims"][0].update(payload_sha256="b" * 64),
    lambda v: v["reference_claims"][0].update(target_revision="99"), lambda v: v["reference_claims"][0].update(target_id="FR-404"),
    lambda v: v["reference_claims"].append(v["reference_claims"][0].copy()),
    lambda v: v["reference_claims"][0].update(entry_index="0"), lambda v: v["entities"][0].update(ordinal=1),
    lambda v: v["entities"][0].update(ordinal=True), lambda v: v["revisions"][0].update(content="\ud800"),
])
def test_rejects_malformed_retained_rows_without_mutating_base(tmp_path, mutation):
    store, _ = retained_history_fixture(tmp_path)
    value = json.loads(store.identity_history(spec_id="demo").payload)
    mutation(value)
    base = base_graph(GraphNode("artifact", "Artifact", {"nested": [1, {"line": 2}]}))
    before = render_spec_graph(base)
    with pytest.raises(SpecGraphError) as error:
        project(base, encoded(value))
    assert len(str(error.value)) < 200
    assert render_spec_graph(base) == before


@pytest.mark.parametrize("payload", ['{"version":"1","version":"1"}', '{"n":1}', '{"n":NaN}', '[]', '[', '[' * 2000 + ']' * 2000], ids=["duplicate", "numeric", "nonfinite", "root-list", "syntax", "deep"])
def test_rejects_bad_wire_json(payload):
    snapshot = IdentityHistorySnapshot(payload, hashlib.sha256(payload.encode()).hexdigest())
    with pytest.raises(SpecGraphError):
        project(base_graph(), snapshot)


def test_rejects_corrupt_hash_noncanonical_json_and_modified_frozen_fields(tmp_path):
    store, _ = retained_history_fixture(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    bad = [replace(snapshot, sha256="b" * 64), replace(snapshot, sha256=snapshot.sha256.upper()),
           replace(snapshot, payload=snapshot.payload + " ", sha256=hashlib.sha256((snapshot.payload + " ").encode()).hexdigest()),
           replace(snapshot, payload=None), object()]
    missing = replace(snapshot)
    object.__delattr__(missing, "payload")
    bad.append(missing)
    for item in bad:
        with pytest.raises(SpecGraphError):
            project(base_graph(), item)


def test_rejects_unallocated_conflicting_and_already_projected_graphs(tmp_path):
    store, label = retained_history_fixture(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    good = project(base_graph(), snapshot)
    cases = [good, base_graph(GraphNode("req:demo:FR-404", "Requirement", {"requirement_id": "FR-404"})),
        base_graph(GraphNode(f"req:demo:{label}", "Task", {"task_id": label})),
        base_graph(GraphNode(f"req:demo:{label}", "Requirement", {"requirement_id": "FR-other"})),
        base_graph(GraphNode(f"req:demo:{label}", "Requirement", {"requirement_id": label, "identity": {}})),
        base_graph(GraphNode("identity-collision", "Artifact", {})),
        base_graph(GraphNode("spec:extra", "Spec", {})),
        base_graph(GraphNode("spec:demo", "Artifact", {})),
        base_graph(edges=(GraphEdge("spec:demo", "X", "missing", {}),)),
        base_graph(edges=(GraphEdge("spec:demo", "HAS_IDENTITY", "spec:demo", {}),)),
        base_graph(inputs=(replace(good.inputs[-1], role="other"),)),
        base_graph(inputs=(GraphInput("elsewhere", "hash", "identity_history", True),)),
        replace(base_graph(), spec_id=None), replace(base_graph(), nodes=()),
        replace(base_graph(), inputs=(object(),)), replace(base_graph(), memory_receipts=(object(),)),
        base_graph(GraphNode("artifact", "Artifact", {"bad": object()})),
        base_graph(GraphNode("artifact", "Artifact", {"bad": float("nan")})),
        base_graph(GraphNode("artifact", "Artifact", {"bad": "\ud800"})),
    ]
    for base in cases:
        with pytest.raises(SpecGraphError):
            project(base, snapshot)


def test_wide_revision_strings_and_foreign_namespace_are_values_not_authority(tmp_path):
    store, label = retained_history_fixture(tmp_path)
    value = json.loads(store.identity_history(spec_id="demo").payload)
    # Synthetic wire values test width, not store authentication or original operations.
    wide = "9" * 5000
    value["revisions"] = [value["revisions"][0] | {"revision": wide}]
    value["entities"][0].update(revision=wide, status="active")
    claim = value["reference_claims"][0]
    claim.update(target_revision=wide, entry_index=wide)
    resign_binding("reference_claims", claim)
    value["workspace_uuid"] = "00000000-0000-4000-8000-000000000001"
    value["epoch_uuid"] = "00000000-0000-4000-8000-000000000002"
    result = project(base_graph(), encoded(value))
    assert by_type(result, "ElementRevision")[0].properties["revision"] == wide
    assert by_type(result, "ReferenceClaim")[0].properties["target_revision_matches_current"] is True
    assert result.nodes[1].id == f"req:demo:{label}"


def resign_binding(table, row):
    row.pop("payload_sha256", None)
    row["payload_sha256"] = hashlib.sha256(json.dumps(
        [table, row], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


@pytest.mark.parametrize("field,value", [
    ("issue_id", "ISS-missing"), ("issue_revision", "99"), ("title", "Wrong title"),
    ("body", "Wrong body"), ("issue_fingerprint", "b" * 64), ("report_sha256", "BAD"),
    ("display_id", "FR-1"), ("issue_revision", None), ("entry_index", "00"),
])
def test_rejects_resigned_occurrence_corruption(tmp_path, field, value):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(label, "Issue", "body", "reserve"),))
    store.record_issue_occurrences(spec_id="demo", operation_id="occ", occurrences=(IssueOccurrence(label, "1", "report", "a" * 64, "ISS-display", "Issue", "body"),))
    decoded = json.loads(store.identity_history(spec_id="demo").payload)
    decoded["issue_occurrences"][0][field] = value
    resign_binding("issue_occurrences", decoded["issue_occurrences"][0])
    with pytest.raises(SpecGraphError):
        project(base_graph(), encoded(decoded))


@pytest.mark.parametrize("field,value", [
    ("predecessor_id", "AC-missing"), ("successor_id", "AC-missing"),
    ("predecessor_revision", "2"), ("successor_revision", "2"),
    ("reason", "wrong reason"), ("operation_id", "wrong operation"), ("kind", "wrong kind"),
])
def test_rejects_lineage_with_wrong_historical_associations(tmp_path, field, value):
    store = IdentityStore.initialize(tmp_path)
    labels = store.reserve(spec_id="demo", kind="AC", operation_id="reserve", count=2)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(labels[0], "Root", "body", "reserve"),))
    store.apply_lifecycle(spec_id="demo", operation_id="replace", changes=(ElementTransition("replace", ((labels[0], "1"),), (ElementCreate(labels[1], "New", "body", "reserve"),), "reason"),))
    decoded = json.loads(store.identity_history(spec_id="demo").payload)
    decoded["lineage"][0][field] = value
    with pytest.raises(SpecGraphError):
        project(base_graph(), encoded(decoded))


def test_duplicate_lineage_and_changed_terminal_content_fail(tmp_path):
    store, _ = retained_history_fixture(tmp_path)
    decoded = json.loads(store.identity_history(spec_id="demo").payload)
    decoded["revisions"][-1]["content"] = "Changed terminal body"
    decoded["revisions"][-1]["content_sha256"] = hashlib.sha256(b"Changed terminal body").hexdigest()
    with pytest.raises(SpecGraphError):
        project(base_graph(), encoded(decoded))
    # Duplicate records are forbidden even with an otherwise valid outer hash.
    decoded = json.loads(store.identity_history(spec_id="demo").payload)
    decoded["lineage"] = [{"spec_id": "demo", "predecessor_id": "FR-1", "predecessor_revision": "1", "successor_id": "FR-2", "successor_revision": "1", "kind": "replace", "reason": "reason", "operation_id": "op"}] * 2
    with pytest.raises(SpecGraphError):
        project(base_graph(), encoded(decoded))


def test_generated_hash_collision_fails_without_graph_mutation(tmp_path, monkeypatch):
    import echelon.spec_graph_identity as projection
    store, _ = retained_history_fixture(tmp_path)
    decoded = json.loads(store.identity_history(spec_id="demo").payload)
    decoded["reference_claims"] = []
    base = base_graph()
    before = render_spec_graph(base)
    # Actual fault injection: distinct revision meanings deliberately collide.
    monkeypatch.setattr(projection, "_canonical_digest", lambda _: "sha256:" + "a" * 64)
    with pytest.raises(SpecGraphError):
        project(base, encoded(decoded))
    assert render_spec_graph(base) == before


def test_legacy_assessment_conflict_and_duplicate_edges_fail(tmp_path):
    store, label = retained_history_fixture(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    for relationship in ("VERIFIED_BY", "STORED_AS"):
        edge = GraphEdge("artifact", relationship, f"req:demo:{label}", {"complete": True, "identity_assessment": "verified"})
        base = base_graph(GraphNode(f"req:demo:{label}", "Requirement", {"requirement_id": label}), GraphNode("artifact", "Artifact", {}), edges=(edge,))
        before = render_spec_graph(base)
        with pytest.raises(SpecGraphError):
            project(base, snapshot)
        assert render_spec_graph(base) == before
        plain_edge = replace(edge, properties={})
        with pytest.raises(SpecGraphError):
            project(replace(base, edges=(plain_edge, plain_edge)), snapshot)


def test_projection_never_reads_or_changes_files_and_publication_release_is_irrelevant(tmp_path, monkeypatch):
    from pathlib import Path
    import sqlite3
    from harness.element_identity_publication import PublicationIntentRequest
    store, _ = retained_history_fixture(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    original = project(base_graph(), snapshot)
    store.prepare_identity_publication(spec_id="demo", operation_id="publication", request=PublicationIntentRequest("a" * 64, "recovery", ()))
    store.apply_identity_publication(spec_id="demo", operation_id="publication")
    store.release_identity_publication(spec_id="demo", operation_id="publication", completion_payload="complete")
    assert project(base_graph(), store.identity_history(spec_id="demo")).inputs == original.inputs
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("projection accessed external state")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        assert project(base_graph(), snapshot) == original
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_virtual_path_quotes_spec_id_and_empty_snapshot_is_projectable(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    spec = "folder/demo ü?#"
    base = SpecArtifactGraph(spec, "test", (), (GraphNode("spec:" + spec, "Spec", {"spec_id": spec}),), (), ())
    result = project(base, store.identity_history(spec_id=spec))
    assert result.inputs[0].path.endswith("/folder%2Fdemo%20%C3%BC%3F%23")
    assert len(result.nodes) == 1 and not result.edges


def test_missing_frozen_graph_fields_subclasses_and_cyclic_properties_fail(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    snapshot = store.identity_history(spec_id="demo")
    missing = base_graph()
    object.__delattr__(missing, "nodes")
    cycle = []
    cycle.append(cycle)
    class DerivedGraph(SpecArtifactGraph):
        pass
    class DerivedSnapshot(IdentityHistorySnapshot):
        pass
    for base in (missing, DerivedGraph("demo", "test", (), (), (), ()),
                 base_graph(GraphNode("artifact", "Artifact", {"cycle": cycle}))):
        with pytest.raises(SpecGraphError):
            project(base, snapshot)
    with pytest.raises(SpecGraphError):
        project(base_graph(), DerivedSnapshot(snapshot.payload, snapshot.sha256))
