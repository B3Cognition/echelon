from __future__ import annotations

import copy
import re

import pytest

from echelon.graph_vis_network import (
    VIS_MAX_EDGES,
    VIS_MAX_NODES,
    load_vis_network_source,
    render_vis_graph_html,
)
from echelon.graph_visualization import GraphViewPayload


def _payload(
    *,
    nodes: tuple[dict[str, object], ...] | None = None,
    edges: tuple[dict[str, object], ...] | None = None,
) -> GraphViewPayload:
    return GraphViewPayload(
        scope="workspace",
        title="Workspace </script> \u2028 & overview",
        audit={
            "status": "fail",
            "findings": [
                {
                    "severity": "error",
                    "code": "missing_trace",
                    "message": "Unsafe </script><script>alert(1)</script> finding",
                    "subject_id": "req:demo:FR-001",
                }
            ],
        },
        lenses=("all", "exceptions", "traceability", "memory", "delivery", "portfolio"),
        initial_lens="traceability",
        nodes=nodes
        if nodes is not None
        else (
            {
                "id": "req:demo:FR-001",
                "type": "Requirement",
                "properties": {"requirement_id": "FR-001", "summary": "A & B < C"},
                "label": "Requirement: FR-001",
                "searchable_label": "requirement fr-001 a & b < c",
                "degree": 2,
                "member_specs": ("001-demo",),
                "exception": True,
                "lenses": ("all", "exceptions", "traceability"),
            },
            {
                "id": "task:demo:T-001",
                "type": "Task",
                "properties": {"task_id": "T-001"},
                "label": "Task: T-001",
                "searchable_label": "task t-001",
                "degree": 1,
                "member_specs": ("001-demo",),
                "exception": False,
                "lenses": ("all", "delivery"),
            },
        ),
        edges=edges
        if edges is not None
        else (
            {
                "source": "task:demo:T-001",
                "type": "IMPLEMENTS",
                "target": "req:demo:FR-001",
                "properties": {},
                "lenses": ("all", "delivery"),
            },
        ),
    )


def _node(index: int) -> dict[str, object]:
    node_id = f"node:{index:05d}"
    return {
        "id": node_id,
        "type": "Artifact",
        "properties": {"path": f"artifacts/{index:05d}.json"},
        "label": f"Artifact: {index:05d}",
        "searchable_label": f"artifact {index:05d}",
        "degree": 1,
        "member_specs": (),
        "exception": False,
        "lenses": ("all",),
    }


def _edge(index: int) -> dict[str, object]:
    return {
        "source": "node:00000",
        "type": f"LINK_{index:05d}",
        "target": "node:00001",
        "properties": {},
        "lenses": ("all",),
    }


@pytest.mark.unit
def test_packaged_vis_network_standalone_bundle_is_available_offline() -> None:
    source = load_vis_network_source()

    assert "vis-network" in source[:1_000].lower()
    assert "Network" in source
    assert "DataSet" in source
    assert len(source) > 500_000


@pytest.mark.unit
def test_html_is_self_contained_script_safe_deterministic_and_read_only() -> None:
    payload = _payload()
    before = copy.deepcopy(payload.to_dict())
    source = "window.vis = {Network: function Network() {}, DataSet: function DataSet() {}};"

    first = render_vis_graph_html(payload, source)
    second = render_vis_graph_html(payload, source)

    assert first == second
    assert payload.to_dict() == before
    assert source in first
    assert not re.search(r"<script\s+[^>]*src=", first, flags=re.IGNORECASE)
    assert not re.search(r"<link\s+[^>]*stylesheet", first, flags=re.IGNORECASE)
    assert '<script id="graph-data" type="application/json">' in first
    assert "</script><script>alert(1)</script>" not in first
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e" in first
    assert "\\u0026" in first
    assert "\\u2028" in first
    assert "localStorage" not in first
    assert "sessionStorage" not in first
    assert "indexedDB" not in first
    assert "fetch(" not in first


@pytest.mark.unit
def test_html_exposes_complete_accessible_operational_renderer_contract() -> None:
    html = render_vis_graph_html(
        _payload(),
        "window.vis = {Network: function Network() {}, DataSet: function DataSet() {}};",
    )

    for element_id in (
        "network",
        "graph-search",
        "graph-lens",
        "group-type",
        "group-spec",
        "legend-filters",
        "selection-details",
        "incoming-neighbors",
        "outgoing-neighbors",
        "fit",
        "reset",
        "physics",
        "audit-status",
        "audit-findings",
    ):
        assert f'id="{element_id}"' in html

    assert 'aria-label="Search graph nodes"' in html
    assert 'aria-label="Graph lens"' in html
    assert 'aria-label="Group nodes by type"' in html
    assert 'aria-label="Group nodes by specification"' in html
    assert 'aria-label="Fit graph to view"' in html
    assert 'title="Fit graph to view"' in html
    assert 'aria-label="Reset graph view and filters"' in html
    assert 'title="Reset graph view and filters"' in html
    assert 'aria-label="Toggle graph physics"' in html
    assert 'title="Toggle graph physics"' in html
    assert 'aria-live="polite"' in html
    assert 'new vis.Network(' in html
    assert 'new vis.DataSet(' in html
    assert "arrows: { to: { enabled: true" in html
    assert "label: edge.type" in html
    assert "stabilization:" in html
    assert "physics:" in html
    assert "node.lenses.includes(activeLens)" in html
    assert "node.member_specs" in html
    assert "incoming" in html and "outgoing" in html
    assert "Math.min(MAX_NODE_SIZE, Math.max(MIN_NODE_SIZE" in html
    assert "const MIN_NODE_SIZE = 18;" in html
    assert "const MAX_NODE_SIZE = 44;" in html
    assert "function colorForGroupKey(key)" in html
    assert "colorForGroupKey(key)" in html
    assert "#network { width: 100%; height: 100%; min-height: 420px;" in html
    assert ".icon-button { width: 36px; height: 34px;" in html
    assert "linear-gradient" not in html


@pytest.mark.unit
def test_exact_graph_limits_initialize_the_full_network() -> None:
    at_node_limit = render_vis_graph_html(
        _payload(nodes=tuple(_node(index) for index in range(VIS_MAX_NODES)), edges=()),
        "window.vis = {};",
    )
    at_edge_limit = render_vis_graph_html(
        _payload(
            nodes=(_node(0), _node(1)),
            edges=tuple(_edge(index) for index in range(VIS_MAX_EDGES)),
        ),
        "window.vis = {};",
    )

    assert "new vis.Network(" in at_node_limit
    assert '"id": "node:04999"' in at_node_limit
    assert "new vis.Network(" in at_edge_limit
    assert '"type": "LINK_09999"' in at_edge_limit


@pytest.mark.unit
@pytest.mark.parametrize(
    ("payload", "node_count", "edge_count", "sentinel"),
    (
        (
            _payload(
                nodes=tuple(_node(index) for index in range(VIS_MAX_NODES + 1)),
                edges=(),
            ),
            VIS_MAX_NODES + 1,
            0,
            "node:05000",
        ),
        (
            _payload(
                nodes=(_node(0), _node(1)),
                edges=tuple(_edge(index) for index in range(VIS_MAX_EDGES + 1)),
            ),
            2,
            VIS_MAX_EDGES + 1,
            "LINK_10000",
        ),
    ),
)
def test_oversized_graph_reports_exact_counts_without_partial_network(
    payload: GraphViewPayload,
    node_count: int,
    edge_count: int,
    sentinel: str,
) -> None:
    html = render_vis_graph_html(payload, "window.vis = {};")

    assert f"{node_count:,} nodes" in html
    assert f"{edge_count:,} edges" in html
    assert "Cytoscape" in html
    assert "new vis.Network" not in html
    assert 'id="graph-data"' not in html
    assert sentinel not in html
