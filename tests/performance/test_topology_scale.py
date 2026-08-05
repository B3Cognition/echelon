from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.spec_graph import GraphEdge, GraphNode, SpecArtifactGraph, render_spec_graph
from echelon.topology_model import TopologySymbol, canonical_symbol_key
from echelon.workspace_graph import build_workspace_graph
from harness.re_fingerprint import fingerprint_source, resolve_re_fingerprint_profile
from harness.topology_publication import (
    TopologyProviderCandidate,
    TopologySnapshotCandidate,
    publish_topology_snapshots,
)


SYMBOL_COUNT = 31_000
RELATIONSHIP_COUNT = 65_000


def _workspace(root: Path) -> Path:
    source = root / "sources" / "scale"
    source.mkdir(parents=True)
    source.joinpath("tracked.txt").write_text("scale fixture\n", encoding="utf-8")
    config = root / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: scale\n"
        "    path: sources/scale\n",
        encoding="utf-8",
    )
    return source


def _symbol_locator(index: int) -> tuple[str, str]:
    if index < 2:
        return f"src/duplicate-{index}.py", "scale.resolve"
    return f"src/module-{index % 256:03d}.py", f"scale.symbol_{index:05d}"


def _analysis() -> tuple[bytes, bytes, tuple[str, ...]]:
    symbols: list[dict[str, object]] = []
    keys: list[str] = []
    for index in range(SYMBOL_COUNT):
        path, qualified_name = _symbol_locator(index)
        key = canonical_symbol_key(path, qualified_name, "function", "()")
        keys.append(key)
        symbols.append(
            {
                "symbol_key": key,
                "file_path": path,
                "qualified_name": qualified_name,
                "name": qualified_name.rpartition(".")[2],
                "kind": "function",
                "signature": "()",
                "line_start": 1,
                "line_end": 1,
            }
        )

    endpoints = [(index, 4) for index in range(5, SYMBOL_COUNT)]
    endpoints.extend((index, index + 1) for index in range(5, SYMBOL_COUNT - 1))
    endpoints.extend((index, index + 100) for index in range(5, 5 + 3_008))
    endpoints.extend(((0, 1), (1, 2), (2, 3)))
    assert len(endpoints) == RELATIONSHIP_COUNT
    relationships = [
        {
            "kind": "calls",
            "source_key": keys[source],
            "target_key": keys[target],
            "source_name": symbols[source]["qualified_name"],
            "target_name": symbols[target]["qualified_name"],
        }
        for source, target in endpoints
    ]
    counts = {
        "discovered_symbols": SYMBOL_COUNT,
        "emitted_symbols": SYMBOL_COUNT,
        "excluded_symbols": 0,
        "discovered_relationships": RELATIONSHIP_COUNT,
        "emitted_relationships": RELATIONSHIP_COUNT,
        "excluded_relationships": 0,
    }
    document = {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": "/provider/native/scale",
        "provider_status": "complete",
        "complete": True,
        "supported": True,
        "counts": counts,
        "diagnostics": {"unresolved_relationships": []},
        "symbols": symbols,
        "relationships": relationships,
        "call_graph": [],
        "type_hierarchy": [],
        "impact_radius": [],
    }
    summary = {
        "schema_version": 2,
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "provider_status": "complete",
        "complete": True,
        "counts": counts,
        "diagnostics": {"unresolved_relationships": []},
    }
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode(),
        tuple(keys),
    )


def _compact_artifact_graphs(
    root: Path, monkeypatch: pytest.MonkeyPatch, receipt_path: str
) -> tuple[dict[str, object], dict[str, object]]:
    spec_dir = root / "specs" / "001-scale"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text("# Scale\n", encoding="utf-8")
    member = SpecArtifactGraph(
        spec_id="001-scale",
        generator_version="test",
        inputs=(),
        nodes=(
            GraphNode("spec:001-scale", "Spec", {"spec_id": "001-scale"}),
            GraphNode(
                "source:scale",
                "SourceRoot",
                {"source_id": "scale", "path": "sources/scale"},
            ),
            GraphNode(
                f"artifact:001-scale:{receipt_path}",
                "Artifact",
                {"path": receipt_path, "role": "topology-receipt"},
            ),
        ),
        edges=(
            GraphEdge("spec:001-scale", "USES_SOURCE", "source:scale", {}),
            GraphEdge(
                "source:scale",
                "HAS_TOPOLOGY_RECEIPT",
                f"artifact:001-scale:{receipt_path}",
                {},
            ),
        ),
        memory_receipts=(),
    )
    graph_path = spec_dir / "spec-artifact-graph.json"
    graph_path.write_bytes(render_spec_graph(member))
    graph_hash = "sha256:" + hashlib.sha256(graph_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda project_root, selector: SimpleNamespace(
            status="pass",
            graph_hash=graph_hash,
            findings=(),
            to_dict=lambda: {"status": "pass", "graph_hash": graph_hash},
        ),
    )
    return member.to_dict(), build_workspace_graph(root).graph.to_dict()


@pytest.mark.performance
def test_published_topology_scales_without_projecting_provider_graphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from echelon.topology_audit import audit_topology
    from echelon.topology_provider import TopologyNodeResolutionError
    from echelon.topology_registry import load_published_topology, load_topology_index

    source = _workspace(tmp_path)
    fingerprint = fingerprint_source(source, resolve_re_fingerprint_profile(tmp_path))
    analysis, summary, keys = _analysis()
    candidate = TopologySnapshotCandidate(
        source_id="scale",
        source_path="sources/scale",
        source_fingerprint=fingerprint,
        analyzed_commit=fingerprint.git_head,
        provenance={"kind": "re", "run_id": "re-scale"},
        providers=(TopologyProviderCandidate("codegraph", analysis, summary),),
    )

    publication = publish_topology_snapshots(
        tmp_path, (candidate,), owner_id="re-scale", owner_run_dir=None
    )
    audit = audit_topology(tmp_path)
    topology = load_published_topology(tmp_path)
    published_analysis = json.loads(
        (tmp_path / "re/topology/sources/scale/codegraph-analysis.json").read_bytes()
    )

    assert publication.generation == 1
    assert audit.status == "current"
    assert audit.exit_code == 0
    assert published_analysis["counts"]["emitted_symbols"] == SYMBOL_COUNT
    assert published_analysis["counts"]["emitted_relationships"] == RELATIONSHIP_COUNT
    assert sum(isinstance(node, TopologySymbol) for node in topology.nodes_by_id.values()) == SYMBOL_COUNT
    assert sum(relation.provider == "codegraph" for relation in topology.relationships) == RELATIONSHIP_COUNT

    duplicate = topology.search("scale", "scale.resolve", frozenset({"SYMBOL"}), 20)
    bounded = topology.search("scale", "scale.symbol", frozenset({"SYMBOL"}), 20)
    assert [node.path for node in duplicate.nodes] == [
        "src/duplicate-0.py",
        "src/duplicate-1.py",
    ]
    assert not duplicate.truncated
    assert len(bounded.nodes) == 20
    assert bounded.truncated
    assert bounded == topology.search(
        "scale", "scale.symbol", frozenset({"SYMBOL"}), 20
    )

    exact_ids = [
        f"symbol:scale:codegraph:{keys[index][7:]}" for index in range(5)
    ]
    with pytest.raises(TopologyNodeResolutionError) as ambiguous:
        topology.explain("scale", "scale.resolve")
    assert ambiguous.value.candidates == tuple(sorted(exact_ids[:2]))
    assert topology.explain("scale", exact_ids[0]).node.path == "src/duplicate-0.py"
    assert topology.explain("scale", exact_ids[1]).node.path == "src/duplicate-1.py"

    neighbors = topology.neighbors(
        "scale", exact_ids[4], "in", frozenset({"CALLS"}), 20
    )
    assert len(neighbors.steps) == 20
    assert neighbors.truncated
    assert neighbors == topology.neighbors(
        "scale", exact_ids[4], "in", frozenset({"CALLS"}), 20
    )
    impact = topology.impact(
        "scale", exact_ids[3], 3, frozenset({"CALLS"})
    )
    assert [step.depth for step in impact.steps] == [1, 2, 3]
    assert [step.node_id for step in impact.steps] == exact_ids[2::-1]
    assert not impact.truncated
    assert impact == topology.impact(
        "scale", exact_ids[3], 3, frozenset({"CALLS"})
    )

    index = load_topology_index(tmp_path)
    assert index is not None
    receipt_path = index.sources["scale"].receipt.path
    spec_graph, workspace_graph = _compact_artifact_graphs(
        tmp_path, monkeypatch, receipt_path
    )
    for graph in (spec_graph, workspace_graph):
        node_ids = [node["id"] for node in graph["nodes"]]
        assert len(node_ids) < 20
        assert not any(node_id.startswith(("file:", "symbol:")) for node_id in node_ids)
        assert not any(
            edge["type"] in {"CALLS", "DECLARES"} for edge in graph["edges"]
        )
