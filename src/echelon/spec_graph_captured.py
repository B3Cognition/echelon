"""Inactive assembly of a derived identity graph from coherent captured values.

Selection and observation authentication belong to the caller. Matching captured
bytes is neither semantic acceptance nor authority to publish this graph.
"""

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath

from echelon.mempalace_requirements import PlannedRequirementDrawer
from echelon.spec_memory_miner import CanonicalRequirementDrawerPlan
from echelon.spec_graph import SpecArtifactGraph, SpecGraphError, render_spec_graph
from echelon.spec_graph_identity import project_identity_history
from echelon.spec_graph_memory import (
    GraphMemoryAudit, GraphMemorySource, build_memory_graph_contribution,
)
from echelon.spec_graph_re import (
    GraphReArtifact, GraphReSource, GraphReTopology, build_re_graph_contribution,
)
from echelon.spec_graph_structure import (
    _add_artifact_record, _artifact_required, _artifact_role, _validate_scope,
    build_spec_graph_structure,
)
from echelon.topology_registry import TopologyArtifactReceipt
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.re_artifacts import ReArtifactDescriptor
from harness.squad_source_manifest import SourceManifestSnapshot, snapshot_source_manifest
from harness.squad_source_projection import ProjectedPublicationSources
from harness.squad_source_snapshot import _source_path


@dataclass(frozen=True, slots=True)
class CapturedGraphMemory:
    domain: str
    sources: tuple[GraphMemorySource, ...]
    planned_rows: tuple[PlannedRequirementDrawer | CanonicalRequirementDrawerPlan, ...]
    audit: GraphMemoryAudit


_DOMAINS = ("canonical-spec", "spec-evidence", "published-re")


def _require(condition):
    if not condition:
        raise ValueError("invalid captured assembly value")


def _present(images, path):
    _require(type(path) is str and path in images)
    return images[path]


def build_captured_identity_graph(
    *, spec_id: str, lifecycle: str, generator_version: str,
    sources: ProjectedPublicationSources, policy_paths: tuple[str, ...],
    memory: tuple[CapturedGraphMemory, ...],
    re_artifacts: tuple[GraphReArtifact, ...], re_sources: tuple[GraphReSource, ...],
    history: IdentityHistorySnapshot,
) -> SpecArtifactGraph:
    """Compose native projections over one image table, with retained history last.

    No capture, planning, audit acquisition, registry admission or write occurs.
    Ordinary failures deliberately retain neither nested exceptions nor source
    documents; process-control exceptions remain the caller's responsibility.
    """
    try:
        return _build(spec_id, lifecycle, generator_version, sources, policy_paths,
                      memory, re_artifacts, re_sources, history)
    except Exception:
        pass
    raise SpecGraphError("invalid captured identity graph assembly")


def _build(spec_id, lifecycle, generator_version, sources, policy_paths,
           memory, re_artifacts, re_sources, history):
    spec_path = _validate_scope(spec_id, lifecycle)
    _require(type(generator_version) is str and bool(generator_version))
    generator_version.encode("utf-8")
    _require(type(sources) is ProjectedPublicationSources)
    _require(type(sources.manifest) is SourceManifestSnapshot)
    _require(type(sources.manifest.payload) is str and type(sources.manifest.sha256) is str)
    _require(snapshot_source_manifest(trees=sources.trees, files=sources.files) == sources.manifest)
    selected = [tree for tree in sources.trees if tree.path == spec_path.as_posix()]
    _require(len(selected) == 1)
    images = {item.path: item.content for tree in sources.trees for item in tree.files}
    images.update((item.path, item.content) for item in sources.files if item.content is not None)
    output_path = (spec_path / "spec-artifact-graph.json").as_posix()

    for collection in (policy_paths, memory, re_artifacts, re_sources):
        _require(type(collection) is tuple)
    policies = []
    for path in policy_paths:
        canonical = PurePosixPath(_source_path(path).as_posix())
        _require(canonical.as_posix() == path and path != output_path)
        _require(spec_path in canonical.parents or PurePosixPath("re") in canonical.parents)
        _present(images, path)
        policies.append(canonical)
    _require(len(set(policies)) == len(policies))

    domains = {}
    for observation in memory:
        _require(type(observation) is CapturedGraphMemory)
        _require(type(observation.domain) is str and observation.domain in _DOMAINS)
        _require(observation.domain not in domains)
        _require(type(observation.sources) is tuple)
        _require(observation.domain == "canonical-spec" or bool(observation.sources))
        for source in observation.sources:
            _require(type(source) is GraphMemorySource)
            _require(type(source.path) is str and source.path != output_path)
            _require(type(source.content) is bytes and source.content == _present(images, source.path))
        domains[observation.domain] = observation
    _require("canonical-spec" in domains)
    for artifact in re_artifacts:
        _require(type(artifact) is GraphReArtifact and type(artifact.descriptor) is ReArtifactDescriptor)
        _require(type(artifact.content) is bytes)
        _require(artifact.content == _present(images, artifact.descriptor.path))
    for source in re_sources:
        _require(type(source) is GraphReSource)
        _present(images, source.semantic_receipt_path)
        if source.topology is not None:
            topology = source.topology
            _require(type(topology) is GraphReTopology and type(topology.receipt) is TopologyArtifactReceipt)
            _require(type(topology.receipt_content) is bytes)
            _require(topology.receipt_content == _present(images, topology.receipt.path))

    structure = build_spec_graph_structure(spec_id=spec_id, tree=selected[0], lifecycle=lifecycle)
    nodes = {node.id: node for node in structure.nodes}
    inputs = {item.path: item for item in structure.inputs}
    edges, receipts = list(structure.edges), []
    for path in sorted(policies):
        name = path.as_posix()
        digest = "sha256:" + hashlib.sha256(images[name]).hexdigest()
        if name in inputs:
            _require(inputs[name].hash == digest)
            continue
        _add_artifact_record(spec_id, name, path.name, digest, _artifact_role(spec_path, path),
                             _artifact_required(spec_path, path, lifecycle), nodes, inputs)
    for domain in _DOMAINS:
        if domain not in domains:
            continue
        observation = domains[domain]
        contribution = build_memory_graph_contribution(
            spec_id=spec_id, lifecycle=lifecycle, domain=domain, sources=observation.sources,
            planned_rows=observation.planned_rows, audit=observation.audit,
            known_node_ids=tuple(nodes),
        )
        nodes.update((node.id, node) for node in contribution.nodes)
        inputs.update((item.path, item) for item in contribution.inputs)
        edges.extend(contribution.edges)
        receipts.append(contribution.receipt)

    # A selected descriptor must already be represented in a full assembly. The
    # lower-level RE contribution still permits missing artifact nodes.
    for artifact in re_artifacts:
        node = nodes.get(f"artifact:{spec_id}:{artifact.descriptor.path}")
        _require(node is not None and node.type == "Artifact")
    re_contribution = build_re_graph_contribution(
        spec_id=spec_id, lifecycle=lifecycle, artifacts=re_artifacts, sources=re_sources,
        artifact_nodes=tuple(node for node in nodes.values() if node.type == "Artifact"),
        stored_artifact_ids=tuple(sorted({edge.source for edge in edges if edge.type == "STORED_AS"})),
    )
    nodes.update((node.id, node) for node in re_contribution.nodes)
    inputs.update((item.path, item) for item in re_contribution.inputs)
    edges.extend(re_contribution.edges)
    graph = SpecArtifactGraph(spec_id, generator_version, tuple(inputs.values()),
                              tuple(nodes.values()), tuple(edges), tuple(receipts))
    # This existing owner reconstructs every record and nested property tree.
    result = project_identity_history(graph, history)
    render_spec_graph(result)
    return result
