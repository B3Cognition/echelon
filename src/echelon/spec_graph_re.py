"""Pure contributions from selected, captured RE values; no registry admission.

Live acquisition delegates only the small transformations below. The strict
public boundary is inactive and does not authenticate its supplied observations.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

from echelon.spec_graph import GraphEdge, GraphInput, GraphNode, SpecGraphError
from echelon.spec_graph_structure import _add_artifact_record, _artifact_required, _validate_scope
from echelon.spec_graph_values import copy_tree
from echelon.topology_model import normalize_source_path, normalize_source_root_path, source_storage_key
from echelon.topology_registry import TopologyArtifactReceipt, _artifact_name
from harness.re_artifacts import (
    ReArtifactDescriptor, SUPPORTED_RE_ARTIFACT_KINDS, _has_prefix, _owner_prefix,
    _validate_path, _validate_source_id,
)


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


def _annotate_artifact(artifact_id, artifact_node, descriptor, stored_artifacts):
    properties = dict(artifact_node.properties)
    properties.update(re_artifact_kind=descriptor.kind, re_scope=descriptor.scope)
    if descriptor.source_id is not None:
        properties["re_source_id"] = descriptor.source_id
    if artifact_id in stored_artifacts:
        properties["mining_status"] = "mined"
    elif descriptor.kind != "re-decision":
        properties["mining_status"] = "eligible"
    return GraphNode(artifact_id, artifact_node.type, properties)


def _title_from_text(text, stem):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return stem


def _captured_title(artifact):
    stem = PurePosixPath(artifact.descriptor.path).stem
    try:
        text = artifact.content.decode("utf-8")
    except UnicodeError:
        return stem
    return _title_from_text(text, stem)


def _decision_id(source_id, path):
    if source_id is None:
        return "decision:workspace:" + path.removeprefix("re/workspace/")
    return f"decision:{source_id}:" + path.removeprefix(f"re/sources/{source_id}/")


def _add_decision(spec_id, source_id, decision_id, path, title, artifact_id, nodes, edges):
    if source_id is None:
        properties = {"scope": "workspace", "path": path, "title": title}
        parent, relation = f"spec:{spec_id}", "INFORMED_BY_DECISION"
    else:
        properties = {"source_id": source_id, "path": path, "title": title}
        parent, relation = f"source:{source_id}", "HAS_DECISION"
    nodes[decision_id] = GraphNode(decision_id, "Decision", properties)
    edges.append(GraphEdge(parent, relation, decision_id, {}))
    edges.append(GraphEdge(decision_id, "DOCUMENTED_BY", artifact_id, {}))


def _source_properties(source_id, path, status, generation, fingerprint, receipt_path):
    return {
        "source_id": source_id, "path": path, "publication_status": status,
        "semantic_generation": generation, "semantic_fingerprint": fingerprint,
        "semantic_receipt_path": receipt_path,
    }


def _topology_properties(generation, fingerprint, receipt_path):
    return {
        "topology_generation": generation, "topology_fingerprint": fingerprint,
        "topology_receipt_path": receipt_path,
    }


def _add_source(spec_id, source_id, properties, receipt_id, nodes, edges):
    node_id = f"source:{source_id}"
    nodes[node_id] = GraphNode(node_id, "SourceRoot", properties)
    edges.append(GraphEdge(f"spec:{spec_id}", "USES_SOURCE", node_id, {}))
    if receipt_id is not None:
        edges.append(GraphEdge(node_id, "HAS_TOPOLOGY_RECEIPT", receipt_id, {}))


def _add_described_by(source_id, artifact_id, edges):
    edges.append(GraphEdge(f"source:{source_id}", "DESCRIBED_BY", artifact_id, {}))


def _require(condition):
    if not condition:
        raise ValueError("invalid captured RE value")


def _text(value):
    _require(type(value) is str and bool(value))
    value.encode("utf-8")
    return value


def _path(value):
    _text(value)
    _require(normalize_source_path(value) == value)
    return PurePosixPath(value)


def _source_id(value):
    _validate_source_id(_text(value))


def _source_path(value):
    _require(normalize_source_root_path(_text(value)) == value)


def _generation(value):
    _require(type(value) is int and value > 0)


def _hash(value):
    _require(re.fullmatch(r"sha256:[0-9a-f]{64}", _text(value)) is not None)


def _hashed_bytes(content, digest):
    _require(type(content) is bytes)
    _hash(digest)
    _require(digest == "sha256:" + hashlib.sha256(content).hexdigest())


def _validate_artifact(artifact):
    _require(type(artifact) is GraphReArtifact)
    descriptor = artifact.descriptor
    _require(type(descriptor) is ReArtifactDescriptor)
    _require(_text(descriptor.kind) in SUPPORTED_RE_ARTIFACT_KINDS)
    _text(descriptor.scope)
    if descriptor.source_id is not None:
        _source_id(descriptor.source_id)
    path = _validate_path(_text(descriptor.path))
    _require(path == _path(descriptor.path))
    _require(_has_prefix(path, _owner_prefix(descriptor.scope, descriptor.source_id)))
    _hashed_bytes(artifact.content, descriptor.sha256)


def _validate_source(source):
    _require(type(source) is GraphReSource)
    _source_id(source.source_id)
    _source_path(source.workspace_path)
    _source_path(source.semantic_path)
    _require(source.workspace_path == source.semantic_path)
    _text(source.publication_status)
    _generation(source.semantic_generation)
    _text(source.semantic_fingerprint)
    _require(_has_prefix(_path(source.semantic_receipt_path), _owner_prefix("source", source.source_id)))
    topology = source.topology
    if topology is None:
        return
    _require(type(topology) is GraphReTopology)
    _source_id(topology.source_id)
    _source_path(topology.source_path)
    _require(topology.source_id == source.source_id and topology.source_path == source.workspace_path)
    _generation(topology.generation)
    _text(topology.fingerprint)
    receipt = topology.receipt
    _require(type(receipt) is TopologyArtifactReceipt)
    _artifact_name(_text(receipt.name))
    prefix = PurePosixPath("re/topology/sources") / source_storage_key(source.source_id)
    _require(_has_prefix(_path(receipt.path), prefix))
    _hashed_bytes(topology.receipt_content, receipt.sha256)


def build_re_graph_contribution(
    *, spec_id: str, lifecycle: str, artifacts: tuple[GraphReArtifact, ...],
    sources: tuple[GraphReSource, ...], artifact_nodes: tuple[GraphNode, ...],
    stored_artifact_ids: tuple[str, ...],
) -> ReGraphContribution:
    """Validate observed values and return detached additions/replacements only."""
    try:
        return _build(spec_id, lifecycle, artifacts, sources, artifact_nodes, stored_artifact_ids)
    except Exception:
        # Raise outside the handler: even suppressed exceptions retain context.
        pass
    raise SpecGraphError("invalid captured RE graph contribution")


def _build(spec_id, lifecycle, artifacts, sources, artifact_nodes, stored_artifact_ids):
    spec_path = _validate_scope(spec_id, lifecycle)
    for collection in (artifacts, sources, artifact_nodes, stored_artifact_ids):
        _require(type(collection) is tuple)
    for artifact in artifacts:
        _validate_artifact(artifact)
    _require(len({a.descriptor.path for a in artifacts}) == len(artifacts))
    for source in sources:
        _validate_source(source)
    source_lookup = {s.source_id: s for s in sources}
    _require(len(source_lookup) == len(sources))
    original = {}
    for node in artifact_nodes:
        _require(type(node) is GraphNode and type(node.type) is str and node.type == "Artifact")
        _text(node.id)
        _require(isinstance(node.properties, Mapping))
        properties = copy_tree(node.properties)
        path = _path(properties["path"])
        _require(node.id == f"artifact:{spec_id}:{path}")
        _hash(properties["hash"])
        _require(node.id not in original)
        original[node.id] = GraphNode(node.id, node.type, properties)
    for stored in stored_artifact_ids:
        _text(stored)
    stored = set(stored_artifact_ids)
    _require(len(stored) == len(stored_artifact_ids))
    nodes, edges, inputs, by_source = {}, [], {}, {}
    for artifact in sorted(artifacts, key=lambda a: a.descriptor.path):
        descriptor = artifact.descriptor
        artifact_id = f"artifact:{spec_id}:{descriptor.path}"
        node = original.get(artifact_id)
        if node is not None:
            _require(node.properties["hash"] == descriptor.sha256)
            nodes[artifact_id] = _annotate_artifact(artifact_id, node, descriptor, stored)
            if descriptor.scope == "workspace" and descriptor.kind == "re-decision":
                _add_decision(spec_id, None, _decision_id(None, descriptor.path),
                              descriptor.path, _captured_title(artifact), artifact_id, nodes, edges)
        if descriptor.scope == "source":
            by_source.setdefault(descriptor.source_id, []).append(artifact)
    for source_id, selected in sorted(by_source.items()):
        source = source_lookup[source_id]
        properties = _source_properties(
            source_id, source.workspace_path, source.publication_status,
            source.semantic_generation, source.semantic_fingerprint, source.semantic_receipt_path,
        )
        receipt_id = None
        if source.topology is not None:
            topology = source.topology
            receipt = topology.receipt
            path = PurePosixPath(receipt.path)
            properties.update(_topology_properties(topology.generation, topology.fingerprint, receipt.path))
            receipt_id = _add_artifact_record(
                spec_id, receipt.path, path.name, receipt.sha256, "topology-receipt",
                _artifact_required(spec_path, path, lifecycle), nodes, inputs,
            )
        _add_source(spec_id, source_id, properties, receipt_id, nodes, edges)
        for artifact in selected:
            descriptor = artifact.descriptor
            artifact_id = f"artifact:{spec_id}:{descriptor.path}"
            if artifact_id not in nodes:
                continue
            if descriptor.kind != "re-decision":
                _add_described_by(source_id, artifact_id, edges)
            else:
                _add_decision(spec_id, source_id, _decision_id(source_id, descriptor.path),
                              descriptor.path, _captured_title(artifact), artifact_id, nodes, edges)
    return ReGraphContribution(spec_id, tuple(inputs.values()), tuple(nodes.values()), tuple(edges))
