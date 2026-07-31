from __future__ import annotations

import copy
import json
import re
import subprocess

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
    initial_lens: str = "traceability",
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
        initial_lens=initial_lens,
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


def _run_runtime(html: str, actions: str) -> dict[str, object]:
    data_match = re.search(
        r'<script id="graph-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    scripts = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, flags=re.DOTALL)
    assert data_match is not None
    assert scripts
    harness = f"""
const graphData = {json.dumps(data_match.group(1))};
const runtimeSource = {json.dumps(scripts[-1])};

class FakeElement {{
  constructor(id = "", tagName = "div") {{
    this.id = id;
    this.tagName = tagName;
    this.textContent = "";
    this.className = "";
    this.value = "";
    this.checked = false;
    this.type = "";
    this.name = "";
    this.style = {{}};
    this.children = [];
    this.listeners = {{}};
    this.attributes = {{}};
  }}
  get firstChild() {{ return this.children[0] || null; }}
  append(...children) {{
    children.forEach((child) => {{ child.parent = this; this.children.push(child); }});
  }}
  removeChild(child) {{
    this.children = this.children.filter((candidate) => candidate !== child);
  }}
  addEventListener(name, listener) {{ this.listeners[name] = listener; }}
  setAttribute(name, value) {{ this.attributes[name] = String(value); }}
  querySelectorAll(selector) {{
    const descendants = [];
    const visit = (element) => {{
      element.children.forEach((child) => {{ descendants.push(child); visit(child); }});
    }};
    visit(this);
    if (selector === 'input[type="checkbox"]') {{
      return descendants.filter((element) => element.tagName === "input" && element.type === "checkbox");
    }}
    return [];
  }}
}}

const elementIds = [
  "graph-data", "graph-search", "graph-lens", "legend-filters", "graph-summary",
  "selection-details", "incoming-neighbors", "outgoing-neighbors", "render-state",
  "physics", "graph-title", "audit-status", "audit-findings", "network", "fit",
  "reset", "group-type", "group-spec"
];
const elements = new Map(elementIds.map((id) => [id, new FakeElement(id)]));
elements.get("graph-data").textContent = graphData;
elements.get("group-type").name = "grouping";
elements.get("group-type").value = "type";
elements.get("group-spec").name = "grouping";
elements.get("group-spec").value = "spec";

globalThis.document = {{
  getElementById(id) {{ return elements.get(id); }},
  createElement(tagName) {{ return new FakeElement("", tagName); }},
  querySelectorAll(selector) {{
    if (selector === 'input[name="grouping"]') {{
      return [elements.get("group-type"), elements.get("group-spec")];
    }}
    return [];
  }}
}};

class FakeDataSet {{
  constructor(items) {{ this.items = items; }}
}}
class FakeNetwork {{
  constructor(container, data, options) {{
    this.container = container;
    this.data = data;
    this.options = options;
    this.handlers = {{}};
    globalThis.runtimeNetwork = this;
  }}
  on(name, handler) {{ this.handlers[name] = handler; }}
  setOptions(options) {{ this.lastOptions = options; }}
  setData(data) {{ this.data = data; }}
  selectNodes(nodeIds) {{ this.selectedNodeIds = nodeIds; }}
  stopSimulation() {{}}
  startSimulation() {{}}
  fit() {{}}
}}
globalThis.vis = {{ DataSet: FakeDataSet, Network: FakeNetwork }};
eval(runtimeSource);
{actions}
"""
    completed = subprocess.run(
        ["node"],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


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
    assert "function colorForGroupKey(key)" in html
    assert "colorForGroupKey(key)" in html
    assert "#network { width: 100%; height: 100%; min-height: 420px;" in html
    assert ".icon-button { width: 36px; height: 34px;" in html
    assert "linear-gradient" not in html


@pytest.mark.unit
def test_degree_sizing_changes_effective_size_for_every_supported_node_type() -> None:
    supported_types = (
        "Spec",
        "Requirement",
        "Task",
        "Artifact",
        "MemPalaceDrawer",
        "Amendment",
        "Deferral",
    )
    nodes = tuple(
        {
            "id": f"{node_type}:{degree}",
            "type": node_type,
            "properties": {},
            "label": f"{node_type}: {degree}",
            "searchable_label": f"{node_type} {degree}",
            "degree": degree,
            "member_specs": (),
            "exception": False,
            "lenses": ("all",),
        }
        for node_type in supported_types
        for degree in (0, 100)
    )
    html = render_vis_graph_html(
        _payload(nodes=nodes, edges=(), initial_lens="all"),
        "",
    )

    result = _run_runtime(
        html,
        """
const emitted = Object.fromEntries(
  runtimeNetwork.data.nodes.items.map((node) => [node.id, { shape: node.shape, size: node.size }])
);
process.stdout.write(JSON.stringify(emitted));
""",
    )

    size_honoring_shapes = {
        "diamond",
        "dot",
        "hexagon",
        "square",
        "star",
        "triangle",
        "triangleDown",
    }
    emitted_shapes = set()
    for node_type in supported_types:
        low = result[f"{node_type}:0"]
        high = result[f"{node_type}:100"]
        assert low["shape"] in size_honoring_shapes
        assert high["shape"] == low["shape"]
        assert 18 <= low["size"] < high["size"] <= 44
        emitted_shapes.add(low["shape"])
    assert len(emitted_shapes) == len(supported_types)


@pytest.mark.unit
def test_details_follow_lens_legend_and_search_visible_graph() -> None:
    nodes = (
        {
            "id": "spec:demo",
            "type": "Spec",
            "properties": {"spec_id": "demo"},
            "label": "Spec: demo",
            "searchable_label": "spec demo",
            "degree": 1,
            "member_specs": (),
            "exception": False,
            "lenses": ("all", "traceability"),
        },
        {
            "id": "req:demo:FR-001",
            "type": "Requirement",
            "properties": {"requirement_id": "FR-001"},
            "label": "Requirement: FR-001",
            "searchable_label": "requirement fr-001",
            "degree": 2,
            "member_specs": ("demo",),
            "exception": False,
            "lenses": ("all", "traceability", "delivery"),
        },
        {
            "id": "task:demo:T-001",
            "type": "Task",
            "properties": {"task_id": "T-001"},
            "label": "Task: T-001",
            "searchable_label": "task t-001",
            "degree": 1,
            "member_specs": ("demo",),
            "exception": False,
            "lenses": ("all", "delivery"),
        },
    )
    edges = (
        {
            "source": "spec:demo",
            "type": "HAS_REQUIREMENT",
            "target": "req:demo:FR-001",
            "properties": {},
            "lenses": ("all", "traceability"),
        },
        {
            "source": "task:demo:T-001",
            "type": "IMPLEMENTS",
            "target": "req:demo:FR-001",
            "properties": {},
            "lenses": ("all", "delivery"),
        },
    )
    html = render_vis_graph_html(
        _payload(nodes=nodes, edges=edges, initial_lens="traceability"),
        "",
    )

    result = _run_runtime(
        html,
        """
const incomingText = () => elements.get("incoming-neighbors").children.map((item) => item.textContent);
runtimeNetwork.handlers.selectNode({ nodes: ["req:demo:FR-001"] });
const traceability = incomingText();

elements.get("graph-lens").value = "delivery";
elements.get("graph-lens").listeners.change();
const delivery = incomingText();

elements.get("graph-search").value = "requirement";
elements.get("graph-search").listeners.input();
const searchFiltered = incomingText();
elements.get("graph-search").value = "";
elements.get("graph-search").listeners.input();

const taskLegend = elements.get("legend-filters").children
  .map((label) => label.children[0])
  .find((input) => input.value === "Task");
taskLegend.checked = false;
taskLegend.listeners.change();
const legendFiltered = incomingText();

process.stdout.write(JSON.stringify({ traceability, delivery, searchFiltered, legendFiltered }));
""",
    )

    assert result == {
        "traceability": ["HAS_REQUIREMENT: Spec: demo"],
        "delivery": ["IMPLEMENTS: Task: T-001"],
        "searchFiltered": ["None"],
        "legendFiltered": ["None"],
    }


@pytest.mark.unit
def test_exact_graph_limits_initialize_populated_datasets() -> None:
    at_node_limit = render_vis_graph_html(
        _payload(
            nodes=tuple(_node(index) for index in range(VIS_MAX_NODES)),
            edges=(),
            initial_lens="all",
        ),
        "",
    )
    at_edge_limit = render_vis_graph_html(
        _payload(
            nodes=(_node(0), _node(1)),
            edges=tuple(_edge(index) for index in range(VIS_MAX_EDGES)),
            initial_lens="all",
        ),
        "",
    )

    node_result = _run_runtime(
        at_node_limit,
        """
process.stdout.write(JSON.stringify({
  nodes: runtimeNetwork.data.nodes.items.length,
  edges: runtimeNetwork.data.edges.items.length,
  lastNode: runtimeNetwork.data.nodes.items.some((node) => node.id === "node:04999")
}));
""",
    )
    edge_result = _run_runtime(
        at_edge_limit,
        """
process.stdout.write(JSON.stringify({
  nodes: runtimeNetwork.data.nodes.items.length,
  edges: runtimeNetwork.data.edges.items.length,
  lastEdge: runtimeNetwork.data.edges.items.some((edge) => edge.label === "LINK_09999")
}));
""",
    )

    assert node_result == {"nodes": VIS_MAX_NODES, "edges": 0, "lastNode": True}
    assert edge_result == {"nodes": 2, "edges": VIS_MAX_EDGES, "lastEdge": True}


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
