"""Captured RE values preserve graph semantics without live acquisition."""

import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from echelon import spec_graph
from echelon.spec_graph import GraphEdge, GraphNode
from harness.re_artifacts import validate_re_artifact_descriptor

pytestmark = pytest.mark.unit


def _api():
    return importlib.import_module("echelon.spec_graph_re")


def _sha(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _artifact(path="re/workspace/odd.bin", kind="re-decision", content=b"# Title\n", source=None):
    from harness.re_artifacts import ReArtifactDescriptor
    descriptor = ReArtifactDescriptor(kind, path, _sha(content), "source" if source else "workspace", source)
    return _api().GraphReArtifact(descriptor, content)


def _node(artifact, **extra):
    descriptor = artifact.descriptor
    return GraphNode("artifact:demo:" + descriptor.path, "Artifact", {
        "path": descriptor.path, "hash": descriptor.sha256, "role": "reverse-engineering",
        "mining_status": "not-mined-by-policy", **extra,
    })


def _source(source_id="api", **changes):
    return replace(_api().GraphReSource(
        source_id, "sources/" + source_id, "sources/" + source_id,
        "observed-status", 2, "semantic-observation", f"re/sources/{source_id}/manifest.json", None,
    ), **changes)


def _args():
    artifact = _artifact("re/sources/api/notes/odd.data", source="api")
    from echelon.topology_registry import TopologyArtifactReceipt
    receipt = TopologyArtifactReceipt("receipt", "re/topology/sources/api/receipt.json", _sha(b"receipt bytes"))
    topology = _api().GraphReTopology("api", "sources/api", 7, "topology observation", receipt, b"receipt bytes")
    return dict(spec_id="demo", lifecycle="build", artifacts=(artifact,),
                sources=(_source(topology=topology),), artifact_nodes=(_node(artifact),), stored_artifact_ids=())


def _native_fixture(root, source_path):
    from tests.unit.test_spec_graph import _write_json, _write_re_index, _write_workspace_source, _attach_re_context
    from tests.unit.test_topology_registry import build_topology
    build_topology(root, source_path=source_path)
    _write_workspace_source(root, source_path=source_path)
    topology_index_path = root / "re/topology/index.json"
    index_data = json.loads(topology_index_path.read_text())
    index_data["generation"] = 9  # Index generation deliberately differs from source receipt generation 3.
    _write_json(topology_index_path, index_data)
    artifacts = (
        _artifact("re/sources/api/notes/odd.data", source="api"),
        _artifact("re/workspace/notes/other.bin", content=b"\r\n # Native workspace\r\n"),
        _artifact("re/sources/api/arbitrary.xyz", "re-architecture", b"native architecture", "api"),
    )
    for artifact in artifacts:
        descriptor = artifact.descriptor
        path = root / descriptor.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.content)
        assert validate_re_artifact_descriptor(
            descriptor.to_json_dict(), workspace_root=root, owner_scope=descriptor.scope,
            owner_source_id=descriptor.source_id,
        ) == descriptor
    _write_json(root / "re/sources/api/manifest.json", {
        "schema_version": 1, "source_id": "api", "publication_status": "complete",
        "source_fingerprint": "source-fingerprint",
        "artifacts": [a.descriptor.to_json_dict() for a in sorted(artifacts, key=lambda a: a.descriptor.path) if a.descriptor.source_id],
    })
    _write_json(root / "re/workspace/manifest.json", {
        "schema_version": 1, "artifacts": [artifacts[1].descriptor.to_json_dict()],
    })
    _write_re_index(root, typed=True, source_path=source_path)
    spec_dir = root / "specs/demo"
    spec_dir.mkdir(parents=True)
    (root / "re/sources/api/contracts.md").write_text("# Uncataloged bait")
    _attach_re_context(spec_dir, root, [a.descriptor.path for a in artifacts] + ["re/sources/api/contracts.md"])
    from echelon.topology_registry import load_topology_index
    from harness.re_registry import load_published_index, canonical_re_artifact_descriptors
    semantic = load_published_index(root)
    native_descriptors = canonical_re_artifact_descriptors(root, semantic)
    assert all(a.descriptor in native_descriptors for a in artifacts)
    topology_index = load_topology_index(root)
    native = topology_index.sources["api"]
    assert topology_index.generation == 9 and native.generation == 3
    source = semantic.sources["api"]
    observation = _api().GraphReSource(
        "api", source_path, source.source_path, source.status, semantic.generation,
        source.fingerprint, source.manifest,
        _api().GraphReTopology("api", native.source_path, topology_index.generation,
                               native.source_fingerprint.value, native.receipt,
                               (root / native.receipt.path).read_bytes()),
    )
    return spec_dir, artifacts, observation


@pytest.mark.parametrize("source_path", [".", "sources/api"])
def test_native_registry_and_legacy_source_root_match_captured_values(tmp_path, source_path):
    spec_dir, artifacts, source = _native_fixture(tmp_path, source_path)
    artifact_nodes = tuple(_node(a) for a in artifacts)
    nodes, edges, inputs = {n.id: n for n in artifact_nodes}, [], {}
    spec_graph._add_re_topology(tmp_path, spec_dir, nodes, edges, inputs)
    assert nodes["source:api"] == GraphNode("source:api", "SourceRoot", {
        "source_id": "api", "path": source_path, "publication_status": "complete",
        "semantic_generation": 2, "semantic_fingerprint": "source-fingerprint",
        "semantic_receipt_path": "re/sources/api/manifest.json", "topology_generation": 9,
        "topology_fingerprint": "0" * 64, "topology_receipt_path": "re/topology/sources/api/receipt.json",
    })
    assert nodes["decision:workspace:notes/other.bin"].properties == {
        "scope": "workspace", "path": "re/workspace/notes/other.bin", "title": "Native workspace",
    }
    assert nodes["decision:api:notes/odd.data"].properties == {
        "source_id": "api", "path": "re/sources/api/notes/odd.data", "title": "Title",
    }
    assert GraphEdge("source:api", "HAS_TOPOLOGY_RECEIPT", "artifact:demo:re/topology/sources/api/receipt.json", {}) in edges
    assert not any("contracts.md" in n for n in nodes)
    result = _api().build_re_graph_contribution(
        spec_id="demo", lifecycle="build", artifacts=artifacts, sources=(source,),
        artifact_nodes=artifact_nodes, stored_artifact_ids=(),
    )
    assert {n.id: n for n in result.nodes} == nodes
    assert result.edges == tuple(edges)
    assert result.inputs == tuple(inputs.values())


def test_captured_re_retains_actual_workspace_decision_after_file_change(tmp_path, monkeypatch):
    path = "re/workspace/notes/decision.md"
    content = b"intro\n\n ## Captured decision\n"
    physical = tmp_path / path
    physical.parent.mkdir(parents=True)
    physical.write_bytes(content)
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
    monkeypatch.setattr(spec_graph, "_linked_re_artifacts", lambda root, spec: [physical])
    monkeypatch.setattr(spec_graph, "load_published_index", lambda root: SimpleNamespace(sources={}))
    monkeypatch.setattr(spec_graph, "canonical_re_artifact_descriptors", lambda root, index: [descriptor])
    nodes, edges, inputs = {artifact_id: node}, [], {}
    spec_graph._add_re_topology(tmp_path, tmp_path / "specs/demo", nodes, edges, inputs)
    expected_nodes = (
        GraphNode(artifact_id, "Artifact", dict(node.properties, re_artifact_kind="re-decision", re_scope="workspace")),
        GraphNode("decision:workspace:notes/decision.md", "Decision", {
            "scope": "workspace", "path": path, "title": "Captured decision",
        }),
    )
    expected_edges = (
        GraphEdge("spec:demo", "INFORMED_BY_DECISION", "decision:workspace:notes/decision.md", {}),
        GraphEdge("decision:workspace:notes/decision.md", "DOCUMENTED_BY", artifact_id, {}),
    )
    assert tuple(nodes.values()) == expected_nodes
    assert tuple(edges) == expected_edges
    assert inputs == {}
    module = importlib.import_module("echelon.spec_graph_re")
    captured = module.GraphReArtifact(descriptor, content)
    physical.write_text("# Changed title\n")
    physical.unlink()
    result = module.build_re_graph_contribution(
        spec_id="demo", lifecycle="build", artifacts=(captured,), sources=(),
        artifact_nodes=(node,), stored_artifact_ids=(),
    )
    assert result == module.ReGraphContribution("demo", (), expected_nodes, expected_edges)


def _render(result):
    return (json.dumps({
        "spec_id": result.spec_id, "inputs": [i.to_dict() for i in result.inputs],
        "nodes": [n.to_dict() for n in result.nodes], "edges": [e.to_dict() for e in result.edges],
    }, sort_keys=True, indent=2) + "\n").encode()


@pytest.mark.parametrize("lifecycle", ["phase_a", "build", "verified", "landed"])
def test_complete_mixed_records_order_and_detached_json_properties(lifecycle):
    args = _args()
    source_decision = args["artifacts"][0]
    architecture = _artifact("re/sources/zeta/strange.bin", "re-architecture", b"architecture", "zeta")
    workspace_decision = _artifact()
    nested = MappingProxyType({"items": [MappingProxyType({
        "labels": ("FR-999999", "FR-1000000", "FR-12345678", "NFR-legacy.x", "T-S01"),
        "scalars": [None, False, True, 2, 3.5],
    })]})
    source_node = _node(source_decision, arbitrary=nested)
    args.update(lifecycle=lifecycle, artifacts=(architecture, workspace_decision, source_decision),
                sources=(_source("zeta"), args["sources"][0], _source("unused")),
                artifact_nodes=(_node(architecture), source_node, _node(workspace_decision), _node(_artifact("re/workspace/extra"))),
                stored_artifact_ids=(source_node.id, "prior-unrelated-observation"))
    result = _api().build_re_graph_contribution(**args)
    from echelon.spec_graph import GraphInput
    sd = "artifact:demo:re/sources/api/notes/odd.data"
    ar = "artifact:demo:re/sources/zeta/strange.bin"
    wd = "artifact:demo:re/workspace/odd.bin"
    tr = "artifact:demo:re/topology/sources/api/receipt.json"
    expected = _api().ReGraphContribution("demo", (
        GraphInput("re/topology/sources/api/receipt.json", _sha(b"receipt bytes"), "topology_receipt", False),
    ), (
        GraphNode(sd, "Artifact", {
            "path": "re/sources/api/notes/odd.data", "hash": _sha(b"# Title\n"),
            "role": "reverse-engineering", "mining_status": "mined", "re_artifact_kind": "re-decision",
            "re_scope": "source", "re_source_id": "api", "arbitrary": {"items": [{
                "labels": ("FR-999999", "FR-1000000", "FR-12345678", "NFR-legacy.x", "T-S01"),
                "scalars": [None, False, True, 2, 3.5],
            }]},
        }),
        GraphNode(ar, "Artifact", {"path": "re/sources/zeta/strange.bin", "hash": _sha(b"architecture"),
            "role": "reverse-engineering", "mining_status": "eligible", "re_artifact_kind": "re-architecture",
            "re_scope": "source", "re_source_id": "zeta"}),
        GraphNode(wd, "Artifact", {"path": "re/workspace/odd.bin", "hash": _sha(b"# Title\n"),
            "role": "reverse-engineering", "mining_status": "not-mined-by-policy",
            "re_artifact_kind": "re-decision", "re_scope": "workspace"}),
        GraphNode("decision:workspace:odd.bin", "Decision", {"scope": "workspace", "path": "re/workspace/odd.bin", "title": "Title"}),
        GraphNode(tr, "Artifact", {"path": "re/topology/sources/api/receipt.json", "hash": _sha(b"receipt bytes"),
            "role": "topology-receipt", "mining_status": "not-mined-by-policy"}),
        GraphNode("source:api", "SourceRoot", {"source_id": "api", "path": "sources/api",
            "publication_status": "observed-status", "semantic_generation": 2, "semantic_fingerprint": "semantic-observation",
            "semantic_receipt_path": "re/sources/api/manifest.json", "topology_generation": 7,
            "topology_fingerprint": "topology observation", "topology_receipt_path": "re/topology/sources/api/receipt.json"}),
        GraphNode("decision:api:notes/odd.data", "Decision", {"source_id": "api", "path": "re/sources/api/notes/odd.data", "title": "Title"}),
        GraphNode("source:zeta", "SourceRoot", {"source_id": "zeta", "path": "sources/zeta",
            "publication_status": "observed-status", "semantic_generation": 2, "semantic_fingerprint": "semantic-observation",
            "semantic_receipt_path": "re/sources/zeta/manifest.json"}),
    ), (
        GraphEdge("spec:demo", "INFORMED_BY_DECISION", "decision:workspace:odd.bin", {}),
        GraphEdge("decision:workspace:odd.bin", "DOCUMENTED_BY", wd, {}),
        GraphEdge("spec:demo", "USES_SOURCE", "source:api", {}),
        GraphEdge("source:api", "HAS_TOPOLOGY_RECEIPT", tr, {}),
        GraphEdge("source:api", "HAS_DECISION", "decision:api:notes/odd.data", {}),
        GraphEdge("decision:api:notes/odd.data", "DOCUMENTED_BY", sd, {}),
        GraphEdge("spec:demo", "USES_SOURCE", "source:zeta", {}),
        GraphEdge("source:zeta", "DESCRIBED_BY", ar, {}),
    ))
    assert result == expected
    assert _render(result) == _render(expected)
    second = _api().build_re_graph_contribution(**args)
    second.nodes[0].properties["arbitrary"]["items"][0]["scalars"].append("mutated second")
    object.__setattr__(second.nodes[-1], "id", "damaged result")
    nested["items"].append("mutated input")
    object.__setattr__(source_node, "properties", {})
    object.__setattr__(source_decision.descriptor, "path", "damaged")
    object.__setattr__(args["sources"][1].topology.receipt, "path", "damaged")
    object.__setattr__(args["sources"][1], "source_id", "damaged")
    assert result == expected


@pytest.mark.parametrize("content,title", [
    (b"", "odd"), (b"plain text", "odd"), (b"\xff\n# Broken", "odd"),
    (b"#\n ## \n### First\n# Later", "First"), (b"intro\r\n  ## CRLF\r\n", "CRLF"),
    ("# Žluťoučký".encode(), "Žluťoučký"), (b"#\tTabbed\n", "Tabbed"),
])
def test_titles_use_captured_utf8_heading_or_path_stem(content, title):
    artifact = _artifact(content=content)
    result = _api().build_re_graph_contribution(spec_id="demo", lifecycle="build", artifacts=(artifact,),
        sources=(), artifact_nodes=(_node(artifact),), stored_artifact_ids=())
    assert result.nodes[-1] == GraphNode("decision:workspace:odd.bin", "Decision", {
        "scope": "workspace", "path": "re/workspace/odd.bin", "title": title,
    })


def test_empty_and_missing_artifact_nodes_do_not_invent_artifacts():
    args = _args()
    args.update(artifacts=(), artifact_nodes=())
    assert _api().build_re_graph_contribution(**args) == _api().ReGraphContribution("demo", (), (), ())
    workspace = _artifact()
    args.update(artifacts=(workspace,))
    assert _api().build_re_graph_contribution(**args) == _api().ReGraphContribution("demo", (), (), ())
    args = _args()
    args.update(artifact_nodes=(), sources=(_source(),))
    result = _api().build_re_graph_contribution(**args)
    assert result.inputs == ()
    assert result.nodes == (GraphNode("source:api", "SourceRoot", {
        "source_id": "api", "path": "sources/api", "publication_status": "observed-status",
        "semantic_generation": 2, "semantic_fingerprint": "semantic-observation",
        "semantic_receipt_path": "re/sources/api/manifest.json",
    }),)
    assert result.edges == (GraphEdge("spec:demo", "USES_SOURCE", "source:api", {}),)
    args["sources"] = ()
    _reject(args)


def _reject(args):
    from echelon.spec_graph import SpecGraphError
    with pytest.raises(SpecGraphError) as raised:
        _api().build_re_graph_contribution(**args)
    assert str(raised.value) == "invalid captured RE graph contribution"
    assert raised.value.__cause__ is None and raised.value.__context__ is None


@pytest.mark.parametrize("field,value", [
    ("spec_id", ""), ("spec_id", "../demo"), ("spec_id", " demo"), ("spec_id", "demo\ud800"),
    ("spec_id", True), ("lifecycle", "unknown"), ("lifecycle", None),
    ("artifacts", []), ("sources", []), ("artifact_nodes", []), ("stored_artifact_ids", []),
    ("artifacts", (None,)), ("sources", (None,)), ("artifact_nodes", (None,)),
    ("stored_artifact_ids", (None,)), ("stored_artifact_ids", ("",)),
    ("stored_artifact_ids", ("\ud800",)), ("stored_artifact_ids", ("same", "same")),
])
def test_public_scope_and_exact_container_rules(field, value):
    args = _args()
    args[field] = value
    _reject(args)


@pytest.mark.parametrize("target,field,values", [
    ("artifact", "descriptor", [None, {}]), ("artifact", "content", [None, "text", bytearray(b"x"), b"wrong"]),
    ("descriptor", "kind", ["", None, "uncataloged", "\ud800"]),
    ("descriptor", "scope", ["", None, "other", "workspace"]),
    ("descriptor", "source_id", [None, ".", "..", "bad/id", "other", "", "\ud800", 1]),
    ("descriptor", "sha256", ["", "a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 64, None]),
    ("source", "source_id", ["", ".", "..", "other", "bad/id", None]),
    ("source", "workspace_path", ["other", "./sources/api", "sources//api", "/sources/api", "a/../api", "C:/api", "a\\api", "", None]),
    ("source", "semantic_path", ["other", "", None, "sources/api/"]),
    ("source", "semantic_generation", [True, 0, -1, 1.0, "1", None]),
    ("source", "publication_status", ["", None, "\ud800"]),
    ("source", "semantic_fingerprint", ["", None, "\ud800"]),
    ("source", "semantic_receipt_path", ["re/sources/other/a", "re/sources/api", "re/sources/api2/a", "re/sources/api/../a", ".", "", None]),
    ("source", "topology", [{}, False]),
    ("topology", "source_id", ["other", "", None, "."]),
    ("topology", "source_path", ["other", "", None, "sources/api/."]),
    ("topology", "generation", [True, 0, -1, 1.0, "1", None]),
    ("topology", "fingerprint", ["", None, "\ud800"]),
    ("topology", "receipt", [None, {}]),
    ("topology", "receipt_content", ["text", None, bytearray(b"x"), b"wrong"]),
    ("receipt", "name", ["", None, "bad/name", "\ud800"]),
    ("receipt", "path", ["re/topology/sources/other/a", "re/topology/sources/api", "re/topology/sources/api2/a", "re/topology/sources/api/../a", ".", "", None]),
    ("receipt", "sha256", ["", None, "sha256:" + "A" * 64, "sha256:" + "0" * 64]),
    ("node", "id", ["", None, "\ud800", "artifact:other:re/sources/api/notes/odd.data"]),
    ("node", "type", [None, "Decision", "", 1]), ("node", "properties", [None, [], "properties"]),
])
def test_invalid_and_damaged_records_are_bounded(target, field, values):
    for value in values:
        args = _args()
        objects = {"artifact": args["artifacts"][0], "descriptor": args["artifacts"][0].descriptor,
                   "source": args["sources"][0], "topology": args["sources"][0].topology,
                   "receipt": args["sources"][0].topology.receipt, "node": args["artifact_nodes"][0]}
        object.__setattr__(objects[target], field, value)
        _reject(args)
    args = _args()
    objects = {"artifact": args["artifacts"][0], "descriptor": args["artifacts"][0].descriptor,
               "source": args["sources"][0], "topology": args["sources"][0].topology,
               "receipt": args["sources"][0].topology.receipt, "node": args["artifact_nodes"][0]}
    object.__delattr__(objects[target], field)
    _reject(args)


@pytest.mark.parametrize("path", ["re/sources/api", "re/sources/api2/a", "re/workspace/a", "/re/sources/api/a",
    "re/sources/api/../a", "re/sources/api/./a", "re/sources/api//a", "re/sources/api/a/", "re\\sources/api/a",
    "", ".", "C:/re/sources/api/a", "re/sources/api/\ud800"])
def test_descriptor_paths_are_canonical_and_component_owned(path):
    args = _args()
    object.__setattr__(args["artifacts"][0].descriptor, "path", path)
    _reject(args)


@pytest.mark.parametrize("field", ["artifacts", "sources", "artifact_nodes"])
def test_duplicate_observations_reject(field):
    args = _args()
    args[field] = args[field] * 2
    _reject(args)


class _Text(str):
    pass


@pytest.mark.parametrize("target,field", [("descriptor", "kind"), ("descriptor", "path"), ("descriptor", "source_id"),
    ("descriptor", "scope"), ("descriptor", "sha256"), ("source", "publication_status"), ("source", "semantic_fingerprint"),
    ("source", "workspace_path"), ("source", "semantic_receipt_path"), ("topology", "fingerprint"), ("receipt", "name"),
    ("receipt", "path"), ("receipt", "sha256"), ("node", "id"), ("node", "type")])
def test_string_subclasses_do_not_cross_boundary(target, field):
    args = _args()
    objects = {"descriptor": args["artifacts"][0].descriptor, "source": args["sources"][0],
               "topology": args["sources"][0].topology, "receipt": args["sources"][0].topology.receipt,
               "node": args["artifact_nodes"][0]}
    object.__setattr__(objects[target], field, _Text(getattr(objects[target], field)))
    _reject(args)


def test_bad_property_trees_and_artifact_hashes_reject():
    recursive = []
    recursive.append(recursive)
    class Damaged(dict):
        def items(self):
            raise RuntimeError("private source " * 10000)
    for value in [object(), {1: "bad key"}, {"\ud800": "bad key"}, {"bad": "\ud800"},
                  _Text("subclass"), float("nan"), float("inf"), recursive, Damaged(a=1)]:
        args = _args()
        args["artifact_nodes"][0].properties["arbitrary"] = value
        _reject(args)
    for key, value in [("path", "re/sources/api/./notes/odd.data"), ("path", "."),
                       ("hash", "sha256:" + "0" * 64), ("hash", "malformed")]:
        args = _args()
        args["artifact_nodes"][0].properties[key] = value
        _reject(args)


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_property_process_control_propagates(error):
    class Interrupting(dict):
        def items(self):
            raise error()
    args = _args()
    args["artifact_nodes"] = (replace(args["artifact_nodes"][0], properties=Interrupting(a=1)),)
    with pytest.raises(error):
        _api().build_re_graph_contribution(**args)


@pytest.mark.parametrize("target", ["artifact", "descriptor", "source", "topology", "receipt", "node"])
def test_native_and_dto_record_subclasses_are_not_observations(target):
    from dataclasses import fields
    args = _args()
    objects = {"artifact": args["artifacts"][0], "descriptor": args["artifacts"][0].descriptor,
               "source": args["sources"][0], "topology": args["sources"][0].topology,
               "receipt": args["sources"][0].topology.receipt, "node": args["artifact_nodes"][0]}
    value = objects[target]
    subclass = type("Subclass", (type(value),), {})
    replacement = subclass(**{f.name: getattr(value, f.name) for f in fields(value)})
    if target in {"artifact", "source", "node"}:
        args[{"artifact": "artifacts", "source": "sources", "node": "artifact_nodes"}[target]] = (replacement,)
    else:
        parent, field = {"descriptor": (objects["artifact"], "descriptor"),
                         "topology": (objects["source"], "topology"), "receipt": (objects["topology"], "receipt")}[target]
        object.__setattr__(parent, field, replacement)
    _reject(args)


def test_workspace_ownership_extra_observations_and_stored_nondecisions():
    args = _args()
    unused = _source("unused", publication_status="")
    args["sources"] += (unused,)
    _reject(args)
    workspace = _artifact()
    object.__setattr__(workspace.descriptor, "source_id", "api")
    args.update(artifacts=(workspace,), artifact_nodes=(), sources=())
    _reject(args)
    architecture = _artifact(kind="re-architecture")
    node = _node(architecture)
    args.update(artifacts=(architecture,), artifact_nodes=(node,), stored_artifact_ids=(node.id,))
    result = _api().build_re_graph_contribution(**args)
    assert result.nodes == (GraphNode(node.id, "Artifact", {
        **node.properties, "mining_status": "mined", "re_artifact_kind": "re-architecture", "re_scope": "workspace",
    }),)
    assert result.inputs == result.edges == ()


@pytest.mark.parametrize("first", ["echelon.spec_graph_re", "echelon.spec_graph"])
def test_import_orders_preserve_native_model_identities(first):
    import os
    import subprocess
    import sys
    code = """
import importlib
importlib.import_module(FIRST)
from echelon import spec_graph as graph, spec_graph_re as captured
from echelon.topology_registry import TopologyArtifactReceipt
from harness.re_artifacts import ReArtifactDescriptor
assert captured.GraphInput is graph.GraphInput
assert captured.GraphNode is graph.GraphNode
assert captured.GraphEdge is graph.GraphEdge
assert captured.ReArtifactDescriptor is ReArtifactDescriptor
assert captured.TopologyArtifactReceipt is TopologyArtifactReceipt
"""
    completed = subprocess.run([sys.executable, "-c", code.replace("FIRST", repr(first))],
        env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == completed.stderr == ""


def test_native_capture_has_no_ambient_access_during_contribution(tmp_path, monkeypatch):
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
    import echelon.mempalace_requirements as memory
    import echelon.spec_graph_identity as identity
    import echelon.topology_registry as topology
    import harness.re_registry as registry
    import harness.re_artifacts as catalog
    import harness.element_identity_store as identity_store
    import harness.squad_source_snapshot as capture
    spec_dir, artifacts, source = _native_fixture(tmp_path, "sources/api")
    args = dict(spec_id="demo", lifecycle="build", artifacts=artifacts, sources=(source,),
                artifact_nodes=tuple(_node(a) for a in artifacts), stored_artifact_ids=())
    nodes, edges, inputs = {n.id: n for n in args["artifact_nodes"]}, [], {}
    spec_graph._add_re_topology(tmp_path, spec_dir, nodes, edges, inputs)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("ambient access")
        raise AssertionError("ambient access")
    with monkeypatch.context() as patch:
        for owner, names in (
            (builtins, ("open",)), (io, ("open",)),
            (Path, ("open", "read_bytes", "read_text", "write_bytes", "write_text", "stat", "lstat", "resolve", "absolute", "cwd", "home", "iterdir", "glob", "rglob", "exists", "is_file", "is_dir", "mkdir", "unlink", "rename", "replace")),
            (os, ("open", "read", "write", "stat", "lstat", "fstat", "listdir", "scandir", "getcwd", "getenv", "system", "popen", "urandom")),
            (type(os.environ), ("__getitem__", "__iter__", "get", "__setitem__")),
            (subprocess, ("Popen", "run", "check_output", "check_call", "call")),
            (time, ("time", "monotonic", "perf_counter", "sleep")),
            (random, ("random", "randint", "getrandbits", "choice")),
            (secrets, ("token_bytes", "token_hex", "token_urlsafe")), (uuid, ("uuid4",)),
            (socket, ("socket", "create_connection", "getaddrinfo")), (sqlite3, ("connect",)),
            (memory, ("create_requirement_memory_adapter", "load_canonical_spec_snapshot", "load_supporting_artifact_snapshots")),
            (topology, ("load_topology_index",)),
            (registry, ("load_published_index", "canonical_re_artifact_descriptors")),
            (catalog, ("validate_re_artifact_descriptor",)),
            (identity, ("project_identity_history",)), (identity_store.IdentityStore, ("open", "initialize")),
            (capture, ("inspect_project_tree",)),
            (spec_graph, ("build_spec_graph", "write_spec_graph", "_add_canonical_memory", "_add_evidence_memory", "_add_re_memory", "_add_re_topology", "_linked_re_artifacts", "_generator_version", "_canonical_source_path", "_canonical_workspace_sources", "load_published_index", "load_topology_index")),
        ):
            for name in names:
                patch.setattr(owner, name, forbidden)
        result = _api().build_re_graph_contribution(**args)
    assert calls == []
    assert {n.id: n for n in result.nodes} == nodes
    assert result.edges == tuple(edges) and result.inputs == tuple(inputs.values())


@pytest.mark.parametrize("failure", ["semantic", "receipt"])
def test_legacy_acquisition_order_keeps_earlier_partial_mutations(tmp_path, monkeypatch, failure):
    artifacts = (
        _artifact("re/workspace/a", content=b"# Workspace"),
        _artifact("re/sources/api/a", source="api", content=b"# API"),
        _artifact("re/sources/zeta/a", source="zeta", content=b"# Zeta"),
    )
    for artifact in artifacts:
        path = tmp_path / artifact.descriptor.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.content)
    for name in ("api", "zeta"):
        (tmp_path / "sources" / name).mkdir(parents=True)
        receipt = tmp_path / f"re/topology/sources/{name}/receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(name.encode())
    events = []
    def acquired(label, value):
        def read(*args):
            events.append(label)
            return value
        return read
    semantic = SimpleNamespace(generation=2, sources={name: SimpleNamespace(
        source_path="sources/" + name, status="complete", fingerprint=name, manifest=f"re/sources/{name}/manifest.json",
    ) for name in ("api", "zeta")})
    topology = SimpleNamespace(generation=7, sources={name: SimpleNamespace(
        source_id=name, source_path="sources/" + name, source_fingerprint=SimpleNamespace(value=name),
        receipt=SimpleNamespace(path=f"re/topology/sources/{name}/receipt.json"),
    ) for name in ("api", "zeta")})
    if failure == "semantic":
        semantic.sources["zeta"].source_path = "sources/api"
    monkeypatch.setattr(spec_graph, "_linked_re_artifacts", acquired("selection", [tmp_path / a.descriptor.path for a in artifacts]))
    monkeypatch.setattr(spec_graph, "load_published_index", acquired("semantic-index", semantic))
    monkeypatch.setattr(spec_graph, "canonical_re_artifact_descriptors", acquired("catalog", [a.descriptor for a in artifacts]))
    monkeypatch.setattr(spec_graph, "_canonical_workspace_sources", acquired("workspace", {"api": "sources/api", "zeta": "sources/zeta"}))
    monkeypatch.setattr(spec_graph, "load_topology_index", acquired("topology-index", topology))
    original_canonical, original_title, original_read = spec_graph._canonical_source_path, spec_graph._adr_title, Path.read_bytes
    def canonical(root, value, subject):
        events.append("canonical:" + subject + ":" + value)
        return original_canonical(root, value, subject)
    def title(path):
        events.append("title:" + path.relative_to(tmp_path).as_posix())
        return original_title(path)
    def read(path):
        events.append("receipt:" + path.relative_to(tmp_path).as_posix())
        if failure == "receipt" and "zeta" in path.parts:
            raise OSError("receipt unavailable")
        return original_read(path)
    monkeypatch.setattr(spec_graph, "_canonical_source_path", canonical)
    monkeypatch.setattr(spec_graph, "_adr_title", title)
    monkeypatch.setattr(Path, "read_bytes", read)
    nodes, edges, inputs = {_node(a).id: _node(a) for a in artifacts}, [], {}
    with pytest.raises(spec_graph.SpecGraphError if failure == "semantic" else OSError):
        spec_graph._add_re_topology(tmp_path, tmp_path / "specs/demo", nodes, edges, inputs)
    expected_events = ["selection", "semantic-index", "catalog", "title:re/workspace/a", "workspace", "topology-index",
        "canonical:source:api:sources/api", "canonical:source:api:sources/api", "receipt:re/topology/sources/api/receipt.json",
        "title:re/sources/api/a", "canonical:source:zeta:sources/" + ("api" if failure == "semantic" else "zeta")]
    if failure == "receipt":
        expected_events += ["canonical:source:zeta:sources/zeta", "receipt:re/topology/sources/zeta/receipt.json"]
    assert events == expected_events
    assert all(nodes[_node(a).id].properties["re_artifact_kind"] == "re-decision" for a in artifacts)
    assert nodes["decision:workspace:a"] == GraphNode("decision:workspace:a", "Decision", {
        "scope": "workspace", "path": "re/workspace/a", "title": "Workspace"})
    assert nodes["decision:api:a"] == GraphNode("decision:api:a", "Decision", {
        "source_id": "api", "path": "re/sources/api/a", "title": "API"})
    assert nodes["source:api"].properties["topology_generation"] == 7
    assert "source:zeta" not in nodes and "decision:zeta:a" not in nodes
    assert list(inputs) == ["re/topology/sources/api/receipt.json"]
    assert edges == [
        GraphEdge("spec:demo", "INFORMED_BY_DECISION", "decision:workspace:a", {}),
        GraphEdge("decision:workspace:a", "DOCUMENTED_BY", "artifact:demo:re/workspace/a", {}),
        GraphEdge("spec:demo", "USES_SOURCE", "source:api", {}),
        GraphEdge("source:api", "HAS_TOPOLOGY_RECEIPT", "artifact:demo:re/topology/sources/api/receipt.json", {}),
        GraphEdge("source:api", "HAS_DECISION", "decision:api:a", {}),
        GraphEdge("decision:api:a", "DOCUMENTED_BY", "artifact:demo:re/sources/api/a", {}),
    ]


@pytest.mark.parametrize("case,want", [("no-selection", ["selection"]), ("context-only", ["selection"]),
    ("no-index", ["selection", "index"]), ("uncataloged", ["selection", "index", "catalog"]),
    ("workspace-only", ["selection", "index", "catalog"])])
def test_legacy_early_returns_do_not_acquire_source_registries(tmp_path, monkeypatch, case, want):
    events = []
    spec_dir = tmp_path / "specs/demo"
    artifact = _artifact(kind="re-architecture")
    selection = [] if case == "no-selection" else [spec_dir / "re-context.json"] if case == "context-only" else [tmp_path / artifact.descriptor.path]
    def selected(*args):
        events.append("selection")
        return selection
    def index(*args):
        events.append("index")
        return None if case == "no-index" else SimpleNamespace(sources={})
    def catalog(*args):
        events.append("catalog")
        return [] if case == "uncataloged" else [artifact.descriptor]
    def forbidden(*args):
        pytest.fail("unexpected source acquisition")
    monkeypatch.setattr(spec_graph, "_linked_re_artifacts", selected)
    monkeypatch.setattr(spec_graph, "load_published_index", index)
    monkeypatch.setattr(spec_graph, "canonical_re_artifact_descriptors", catalog)
    monkeypatch.setattr(spec_graph, "_canonical_workspace_sources", forbidden)
    monkeypatch.setattr(spec_graph, "load_topology_index", forbidden)
    nodes = {_node(artifact).id: _node(artifact)}
    spec_graph._add_re_topology(tmp_path, spec_dir, nodes, [], {})
    assert events == want
    assert ("re_artifact_kind" in nodes[_node(artifact).id].properties) == (case == "workspace-only")


def test_legacy_replacement_keeps_lookup_key_and_shallow_properties(tmp_path, monkeypatch):
    artifact = _artifact(kind="re-architecture")
    node = _node(artifact, nested={"list": []})
    node_id = node.id
    object.__setattr__(node, "id", "duck-typed-other-id")
    monkeypatch.setattr(spec_graph, "_linked_re_artifacts", lambda *args: [tmp_path / artifact.descriptor.path])
    monkeypatch.setattr(spec_graph, "load_published_index", lambda *args: SimpleNamespace(sources={}))
    monkeypatch.setattr(spec_graph, "canonical_re_artifact_descriptors", lambda *args: [artifact.descriptor])
    nodes = {node_id: node}
    edges = [GraphEdge(node_id, "STORED_AS", "previous", {})]
    spec_graph._add_re_topology(tmp_path, tmp_path / "specs/demo", nodes, edges, {})
    assert nodes[node_id].id == node_id
    assert nodes[node_id].properties["mining_status"] == "mined"
    assert nodes[node_id].properties["nested"] is node.properties["nested"]


def test_legacy_decision_key_errors_precede_actual_title_read(tmp_path, monkeypatch):
    class BrokenPath(str):
        def removeprefix(self, prefix):
            raise ValueError("decision key unavailable")
    artifact = _artifact()
    object.__setattr__(artifact.descriptor, "path", BrokenPath(artifact.descriptor.path))
    monkeypatch.setattr(spec_graph, "_linked_re_artifacts", lambda *args: [tmp_path / artifact.descriptor.path])
    monkeypatch.setattr(spec_graph, "load_published_index", lambda *args: SimpleNamespace(sources={}))
    monkeypatch.setattr(spec_graph, "canonical_re_artifact_descriptors", lambda *args: [artifact.descriptor])
    reads = []
    def title(path):
        reads.append(path)
        return "title"
    monkeypatch.setattr(spec_graph, "_adr_title", title)
    nodes = {_node(artifact).id: _node(artifact)}
    with pytest.raises(ValueError, match="decision key unavailable"):
        spec_graph._add_re_topology(tmp_path, tmp_path / "specs/demo", nodes, [], {})
    assert reads == []
    assert nodes[_node(artifact).id].properties["re_artifact_kind"] == "re-decision"


def test_structure_memory_re_and_retained_history_preserve_offline_evidence(tmp_path):
    from tests.unit.test_spec_graph_structure import _tree
    from echelon.spec_graph_structure import build_spec_graph_structure
    from echelon.spec_graph_identity import project_identity_history
    from echelon.spec_graph_memory import GraphMemorySource, GraphMemoryAudit, build_memory_graph_contribution
    from echelon.spec_memory_miner import plan_canonical_requirement_drawers, plan_re_artifact_drawers
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_bindings import ReferenceClaim
    from echelon.spec_graph import SpecArtifactGraph, render_spec_graph
    # Native registry and identity-history acquisition is local to this fixture.
    _, artifacts, source = _native_fixture(tmp_path, "sources/api")
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000001"
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Requirement", "Original body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim("old-evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Requirement", "Revised body"),))
    store.import_identities(spec_id="demo", operation_id="task", definitions=(("T-1000000", "Build"),))
    history = store.identity_history(spec_id="demo")
    content = b"FR-000001: Revised body.\n"
    files = {
        "spec.md": content,
        "tasks.md": b"- [x] T-1000000 complexity=trivial phase=build req=FR-000001 depends=none\n",
        "verified-fulfillment-ledger.json": json.dumps({"schema_version": 1, "rows": [{
            "requirement_id": "FR-000001", "status": "implemented", "evidence_refs": ["old-evidence.md"],
            "spec_input_hash": "old-spec", "verified_commit": "old-commit", "verified_at": "2026-09-01",
        }]}).encode(),
    }
    structure = build_spec_graph_structure(spec_id="demo", lifecycle="build", tree=_tree(files))
    rows = plan_canonical_requirement_drawers(content, source="specs/demo/spec.md",
        artifact_metadata={"canonical": True, "artifact_hash": _sha(content)}, wing="wing")
    audit = GraphMemoryAudit("returned", 1, "wing", "warn", 1, 1, 1, (), (), (), (), (), (), (), ("old memory observation",))
    memory = build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain="canonical-spec",
        sources=(GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),),
        planned_rows=tuple(rows), audit=audit, known_node_ids=tuple(n.id for n in structure.nodes),
    )
    architecture = artifacts[2]
    re_rows = plan_re_artifact_drawers(architecture.content, source=architecture.descriptor.path,
        artifact_metadata={"canonical": True, "scope": "reverse-engineering", "artifact_kind": "re-architecture",
                           "artifact_hash": architecture.descriptor.sha256, "room": "architecture"}, wing="wing")
    assert len(re_rows) == 1
    re_memory = build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain="published-re",
        sources=(GraphMemorySource(architecture.descriptor.path, architecture.content, "re-architecture", "architecture"),),
        planned_rows=tuple(re_rows), audit=replace(audit, status="pass", errors=()), known_node_ids=(),
    )
    preceding = {n.id: n for n in (*structure.nodes, *memory.nodes, *(_node(a) for a in artifacts), *re_memory.nodes)}
    preceding_edges = structure.edges + memory.edges + re_memory.edges
    re_result = _api().build_re_graph_contribution(
        spec_id="demo", lifecycle="build", artifacts=artifacts, sources=(source,),
        artifact_nodes=tuple(n for n in preceding.values() if n.type == "Artifact"),
        stored_artifact_ids=tuple(e.source for e in preceding_edges if e.type == "STORED_AS"),
    )
    combined_nodes = {**preceding, **{n.id: n for n in re_result.nodes}}
    combined_inputs = {i.path: i for i in (*structure.inputs, *memory.inputs, *re_memory.inputs, *re_result.inputs)}
    graph = SpecArtifactGraph("demo", "offline-test-container", tuple(combined_inputs.values()),
        tuple(combined_nodes.values()), preceding_edges + re_result.edges, (memory.receipt, re_memory.receipt))
    projected = project_identity_history(graph, history)
    rendered = render_spec_graph(projected)
    assert rendered == render_spec_graph(project_identity_history(graph, history))
    payload = json.loads(rendered)
    # Independently serialize every projected record and compute both container digests.
    inputs = sorted((i.to_dict() for i in projected.inputs), key=lambda i: (i["role"], i["path"]))
    receipts = sorted((i.to_dict() for i in (memory.receipt, re_memory.receipt)), key=lambda i: i["domain"])
    canonical_hash = lambda value: _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    assert payload == {
        "schema_version": 1, "node_projection_version": 2, "generator_version": "offline-test-container", "spec_id": "demo",
        "source_set_digest": canonical_hash([i for i in inputs if i["role"] != "memory_audit_report"]),
        "memory_state_digest": canonical_hash(receipts), "inputs": inputs,
        "nodes": sorted((n.to_dict() for n in projected.nodes), key=lambda n: n["id"]),
        "edges": sorted((e.to_dict() for e in projected.edges), key=lambda e: (e["source"], e["type"], e["target"])),
    }
    by_id = {n.id: n for n in projected.nodes}
    assert by_id["req:demo:FR-000001"].properties["identity"]["revision"] == "2"
    assert by_id["task:demo:T-1000000"].properties["task_id"] == "T-1000000"
    for node_id in ("source:api", "decision:api:notes/odd.data", "decision:workspace:notes/other.bin",
                    "artifact:demo:re/sources/api/arbitrary.xyz"):
        assert by_id[node_id] == combined_nodes[node_id]
    assert by_id["artifact:demo:re/sources/api/arbitrary.xyz"].properties["mining_status"] == "mined"
    old = next(n for n in projected.nodes if n.type == "ElementRevision" and n.properties["revision"] == "1")
    assert old.properties["content"] == "Original body"
    assert old.properties["content_sha256"] == hashlib.sha256(b"Original body").hexdigest()
    claim = next(n for n in projected.nodes if n.type == "ReferenceClaim")
    assert claim.properties["target_revision_matches_current"] is False
    assert GraphEdge(claim.id, "ASSESSES_REVISION", old.id, {}) in projected.edges
    retained = [e for e in projected.edges if e.type in {"VERIFIED_BY", "STORED_AS"}]
    assert len(retained) == 3
    for before in (e for e in preceding_edges if e.type in {"VERIFIED_BY", "STORED_AS"}):
        expected = (replace(before, properties={**before.properties, "identity_assessment": "unassessed"})
                    if before.source == "req:demo:FR-000001" else before)
        assert expected in retained
    verified = next(e for e in retained if e.type == "VERIFIED_BY")
    assert verified.properties["evidence_refs"] == ["old-evidence.md"]
    assert verified.properties["verified_commit"] == "old-commit"
    assert projected.memory_receipts == (memory.receipt, re_memory.receipt)
    assert all("identity_assessment" not in e.properties for e in preceding_edges)
