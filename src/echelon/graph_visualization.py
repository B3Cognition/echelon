"""Offline visualization and deterministic export for persisted artifact graphs."""

from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
from typing import Mapping, Protocol

from echelon.spec_graph import GRAPH_SCHEMA_VERSION


GRAPH_LENSES = ("all", "exceptions", "traceability", "memory", "delivery")
CYTOSCAPE_ASSET = "assets/cytoscape-3.34.0.min.js"

_LENS_EDGE_TYPES = {
    "traceability": {"HAS_REQUIREMENT", "DERIVED_FROM"},
    "memory": {"STORED_AS"},
    "delivery": {"IMPLEMENTS", "VERIFIED_BY", "DEFERRED_BY"},
    "portfolio": {"CONTAINS_SPEC", "TARGETS", "SUPERSEDES"},
}

_LENS_NODE_TYPES = {
    "portfolio": {"Workspace", "Spec", "Source"},
}

_NODE_STYLE = {
    "Spec": ("#1d4ed8", "box"),
    "Requirement": ("#0f766e", "box"),
    "Task": ("#7c3aed", "box"),
    "Artifact": ("#b45309", "rectangle"),
    "MemPalaceDrawer": ("#be123c", "barrel"),
    "Amendment": ("#475569", "diamond"),
    "Deferral": ("#64748b", "hexagon"),
}


class GraphVisualizationError(RuntimeError):
    """Raised when a persisted graph cannot be rendered safely."""


class GraphAuditReport(Protocol):
    """Structural audit contract shared by spec and workspace graph views."""

    status: str
    findings: object

    def to_dict(self) -> dict[str, object]: ...


def load_graph_document(path: Path) -> dict[str, object]:
    """Read and validate the persisted graph document used by view/export."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GraphVisualizationError(f"graph artifact is missing: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GraphVisualizationError(f"graph artifact is unreadable: {path}") from exc
    if not isinstance(document, dict):
        raise GraphVisualizationError("graph document must be an object")
    if document.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise GraphVisualizationError("unsupported graph schema version")
    scope = _graph_scope(document)
    if scope == "spec" and (
        not isinstance(document.get("spec_id"), str) or not document["spec_id"]
    ):
        raise GraphVisualizationError("graph spec_id must be a non-empty string")
    if scope == "workspace" and (
        not isinstance(document.get("workspace_name"), str)
        or not document["workspace_name"]
    ):
        raise GraphVisualizationError("graph workspace_name must be a non-empty string")
    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphVisualizationError("graph nodes and edges must be lists")

    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphVisualizationError("graph node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise GraphVisualizationError("graph node id must be a non-empty string")
        if node_id in node_ids:
            raise GraphVisualizationError(f"duplicate graph node id: {node_id}")
        if not isinstance(node.get("type"), str):
            raise GraphVisualizationError(f"graph node type is invalid: {node_id}")
        if not isinstance(node.get("properties"), dict):
            raise GraphVisualizationError(f"graph node properties are invalid: {node_id}")
        node_ids.add(node_id)

    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise GraphVisualizationError("graph edge must be an object")
        source = edge.get("source")
        edge_type = edge.get("type")
        target = edge.get("target")
        if not all(isinstance(value, str) and value for value in (source, edge_type, target)):
            raise GraphVisualizationError("graph edge identity is invalid")
        identity = (source, edge_type, target)
        if identity in seen_edges:
            raise GraphVisualizationError(
                f"duplicate graph edge: {source} {edge_type} {target}"
            )
        if source not in node_ids or target not in node_ids:
            raise GraphVisualizationError(
                f"graph edge has missing endpoint: {source} {edge_type} {target}"
            )
        if not isinstance(edge.get("properties"), dict):
            raise GraphVisualizationError(
                f"graph edge properties are invalid: {source} {edge_type} {target}"
            )
        seen_edges.add(identity)
    return document


def filter_graph(
    document: Mapping[str, object],
    audit: GraphAuditReport,
    *,
    lens: str,
) -> dict[str, list[dict[str, object]]]:
    """Return a deterministic graph slice while preserving edge endpoints."""
    lenses = _available_lenses(document)
    if lens not in lenses:
        raise GraphVisualizationError(
            f"unknown graph lens {lens!r}; expected one of {', '.join(lenses)}"
        )
    nodes = {
        str(node["id"]): node
        for node in _objects(document.get("nodes"), "nodes")
    }
    edges = _objects(document.get("edges"), "edges")
    if lens == "all":
        selected_edges = edges
        selected_ids = set(nodes)
    elif lens == "exceptions":
        selected_ids = {
            str(subject_id)
            for finding in _audit_findings(audit)
            if (subject_id := getattr(finding, "subject_id", None)) in nodes
        }
        selected_ids.update(
            node_id
            for node_id, node in nodes.items()
            if _node_is_exception(node)
        )
        selected_edges = [
            edge
            for edge in edges
            if edge.get("source") in selected_ids or edge.get("target") in selected_ids
        ]
        for edge in selected_edges:
            selected_ids.add(str(edge["source"]))
            selected_ids.add(str(edge["target"]))
        if not selected_ids:
            selected_ids.update(
                node_id
                for node_id, node in nodes.items()
                if node.get("type") == "Spec"
            )
    else:
        edge_types = _LENS_EDGE_TYPES[lens]
        selected_edges = [
            edge for edge in edges if edge.get("type") in edge_types
        ]
        selected_ids = {
            str(endpoint)
            for edge in selected_edges
            for endpoint in (edge["source"], edge["target"])
        }
        selected_ids.update(
            node_id
            for node_id, node in nodes.items()
            if node.get("type") in _LENS_NODE_TYPES.get(lens, set())
        )

    return {
        "nodes": [
            dict(nodes[node_id])
            for node_id in sorted(selected_ids)
            if node_id in nodes
        ],
        "edges": [
            dict(edge)
            for edge in sorted(
                selected_edges,
                key=lambda item: (
                    str(item.get("source")),
                    str(item.get("type")),
                    str(item.get("target")),
                ),
            )
            if edge.get("source") in selected_ids
            and edge.get("target") in selected_ids
        ],
    }


def render_graph_dot(
    document: Mapping[str, object],
    audit: GraphAuditReport,
    *,
    lens: str,
) -> str:
    """Render a deterministic directed DOT document for one graph lens."""
    filtered = filter_graph(document, audit, lens=lens)
    title = _graph_title(document)
    lines = [
        f'digraph "{_dot_escape(title)}" {{',
        (
            f'  graph [label="{_dot_escape(title)} | audit: '
            f'{_dot_escape(audit.status)}", labelloc="t", rankdir="LR"];'
        ),
        '  node [fontname="Helvetica", fontsize="10", style="filled"];',
        '  edge [fontname="Helvetica", fontsize="9", color="#64748b"];',
    ]
    for node in filtered["nodes"]:
        node_id = str(node["id"])
        node_type = str(node.get("type") or "Unknown")
        color, shape = _NODE_STYLE.get(node_type, ("#64748b", "ellipse"))
        label = _node_label(node)
        lines.append(
            f'  "{_dot_escape(node_id)}" '
            f'[label="{_dot_escape(label)}", shape="{shape}", '
            f'fillcolor="{color}", fontcolor="white"];'
        )
    for edge in filtered["edges"]:
        lines.append(
            f'  "{_dot_escape(str(edge["source"]))}" -> '
            f'"{_dot_escape(str(edge["target"]))}" '
            f'[label="{_dot_escape(str(edge["type"]))}"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_cytoscape_source() -> str:
    """Load the packaged browser bundle without network access."""
    try:
        return files("echelon").joinpath(CYTOSCAPE_ASSET).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise GraphVisualizationError(
            f"packaged Cytoscape asset is missing: {CYTOSCAPE_ASSET}"
        ) from exc


def render_graph_html(
    document: Mapping[str, object],
    audit: GraphAuditReport,
    *,
    cytoscape_source: str,
    initial_lens: str,
) -> str:
    """Render one self-contained interactive HTML graph viewer."""
    lenses = _available_lenses(document)
    if initial_lens not in lenses:
        raise GraphVisualizationError(f"unknown graph lens: {initial_lens}")
    elements = _cytoscape_elements(filter_graph(document, audit, lens="all"))
    node_ids = {
        str(element["data"]["id"])
        for element in elements
        if element["group"] == "nodes"
    }
    payload = {
        "scope": _graph_scope(document),
        "title": _graph_title(document),
        "audit": audit.to_dict(),
        "initial_lens": initial_lens,
        "lenses": lenses,
        "lens_edge_types": {
            lens: sorted(_LENS_EDGE_TYPES[lens])
            for lens in lenses
            if lens in _LENS_EDGE_TYPES
        },
        "lens_node_types": {
            lens: sorted(_LENS_NODE_TYPES[lens])
            for lens in lenses
            if lens in _LENS_NODE_TYPES
        },
        "exception_subject_ids": sorted(
            str(subject_id)
            for finding in _audit_findings(audit)
            if (subject_id := getattr(finding, "subject_id", None)) in node_ids
        ),
        "elements": elements,
    }
    payload_json = json.dumps(payload, indent=2, sort_keys=True).replace("</", r"<\/")
    return (
        _HTML_TEMPLATE.replace("__CYTOSCAPE_SOURCE__", cytoscape_source)
        .replace("__GRAPH_PAYLOAD__", payload_json)
        .replace(
            "__PORTFOLIO_OPTION__",
            '<option value="portfolio">Portfolio</option>'
            if "portfolio" in lenses
            else "",
        )
    )


def _graph_scope(document: Mapping[str, object]) -> str:
    scope = document.get("scope")
    if scope in {None, "spec"}:
        return "spec"
    if scope == "workspace":
        return "workspace"
    raise GraphVisualizationError(f"unsupported graph scope: {scope!r}")


def _available_lenses(document: Mapping[str, object]) -> tuple[str, ...]:
    if _graph_scope(document) == "workspace":
        return (*GRAPH_LENSES, "portfolio")
    return GRAPH_LENSES


def _graph_title(document: Mapping[str, object]) -> str:
    key = "workspace_name" if _graph_scope(document) == "workspace" else "spec_id"
    value = document.get(key)
    if isinstance(value, str) and value:
        return value
    return "Echelon graph"


def _audit_findings(audit: GraphAuditReport) -> tuple[object, ...]:
    try:
        return tuple(audit.findings)
    except TypeError:
        return ()


def _objects(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise GraphVisualizationError(f"graph {label} must be a list of objects")
    return value


def _node_is_exception(node: Mapping[str, object]) -> bool:
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return False
    presence = properties.get("presence")
    reconciliation = properties.get("reconciliation_status")
    return (
        presence not in {None, "present"}
        or reconciliation not in {None, "pass"}
    )


def _node_label(node: Mapping[str, object]) -> str:
    properties = node.get("properties")
    values = properties if isinstance(properties, dict) else {}
    for key in ("requirement_id", "task_id", "spec_id", "path", "drawer_id"):
        value = values.get(key)
        if value:
            return f"{node.get('type')}: {value}"
    return f"{node.get('type')}: {node.get('id')}"


def _dot_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _cytoscape_elements(
    filtered: Mapping[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    elements: list[dict[str, object]] = []
    for node in filtered["nodes"]:
        elements.append(
            {
                "group": "nodes",
                "data": {
                    "id": str(node["id"]),
                    "type": str(node.get("type") or "Unknown"),
                    "label": _node_label(node),
                    "properties": node.get("properties", {}),
                },
            }
        )
    for edge in filtered["edges"]:
        source = str(edge["source"])
        edge_type = str(edge["type"])
        target = str(edge["target"])
        elements.append(
            {
                "group": "edges",
                "data": {
                    "id": f"{source}|{edge_type}|{target}",
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    "label": edge_type,
                    "properties": edge.get("properties", {}),
                },
            }
        )
    return elements


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Echelon Graph</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #172033; background: #f5f7fa; }
    header { height: 58px; display: flex; align-items: center; gap: 16px; padding: 0 18px;
      border-bottom: 1px solid #d6dce5; background: #fff; }
    h1 { margin: 0; font-size: 16px; font-weight: 700; }
    .status { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .status-pass { color: #166534; background: #dcfce7; }
    .status-warn { color: #854d0e; background: #fef9c3; }
    .status-fail, .status-unavailable { color: #991b1b; background: #fee2e2; }
    .toolbar { margin-left: auto; display: flex; align-items: center; gap: 8px; }
    input, select, button { height: 34px; border: 1px solid #bcc5d2; border-radius: 4px;
      background: #fff; color: #172033; font: inherit; }
    input { width: 240px; padding: 0 10px; }
    select { padding: 0 30px 0 9px; }
    button { padding: 0 10px; cursor: pointer; }
    button:hover { background: #eef2f7; }
    main { height: calc(100vh - 58px); display: grid; grid-template-columns: minmax(0, 1fr) 330px; }
    #cy { min-width: 0; background: #fff; }
    aside { overflow: auto; border-left: 1px solid #d6dce5; background: #f8fafc; }
    section { padding: 14px; border-bottom: 1px solid #d6dce5; }
    h2 { margin: 0 0 10px; font-size: 13px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.45 ui-monospace, monospace; }
    .finding { padding: 8px 0; border-top: 1px solid #e2e8f0; font-size: 12px; line-height: 1.4; }
    .finding:first-child { border-top: 0; }
    .finding strong { display: block; color: #991b1b; }
    .empty { color: #64748b; font-size: 12px; }
    @media (max-width: 800px) {
      header { height: auto; min-height: 58px; flex-wrap: wrap; padding: 10px; }
      .toolbar { width: 100%; margin: 0; flex-wrap: wrap; }
      input { width: min(100%, 260px); }
      main { height: calc(100vh - 112px); grid-template-columns: 1fr; grid-template-rows: minmax(320px, 1fr) 240px; }
      aside { border-left: 0; border-top: 1px solid #d6dce5; }
    }
  </style>
  <script>__CYTOSCAPE_SOURCE__</script>
</head>
<body>
  <header>
    <h1 id="graph-title"></h1>
    <span id="audit-status" class="status"></span>
    <div class="toolbar">
      <input id="graph-search" type="search" placeholder="Search nodes" aria-label="Search nodes">
      <select id="graph-lens" aria-label="Graph lens">
        <option value="all">All</option>
        <option value="exceptions">Exceptions</option>
        <option value="traceability">Traceability</option>
        <option value="memory">Memory</option>
        <option value="delivery">Delivery</option>
        __PORTFOLIO_OPTION__
      </select>
      <button id="one-hop" type="button">1 hop</button>
      <button id="two-hop" type="button">2 hops</button>
      <button id="fit" type="button">Fit</button>
      <button id="reset" type="button">Reset</button>
    </div>
  </header>
  <main>
    <div id="cy"></div>
    <aside>
      <section><h2>Selection</h2><pre id="selection" class="empty">No node selected</pre></section>
      <section><h2>Audit findings</h2><div id="findings"></div></section>
    </aside>
  </main>
  <script>
    window.ECHELON_GRAPH = __GRAPH_PAYLOAD__;
    (() => {
      const payload = window.ECHELON_GRAPH;
      const lensSelect = document.getElementById("graph-lens");
      const search = document.getElementById("graph-search");
      const selection = document.getElementById("selection");
      const findings = document.getElementById("findings");
      let selectedNode = null;
      let cy = null;

      document.getElementById("graph-title").textContent = payload.title;
      const status = document.getElementById("audit-status");
      status.textContent = `audit: ${payload.audit.status}`;
      status.className = `status status-${payload.audit.status}`;
      lensSelect.value = payload.initial_lens;

      if (payload.audit.findings.length === 0) {
        findings.textContent = "No findings";
        findings.className = "empty";
      } else {
        payload.audit.findings.forEach((finding) => {
          const item = document.createElement("div");
          item.className = "finding";
          const title = document.createElement("strong");
          title.textContent = `${finding.code} · ${finding.severity}`;
          const message = document.createElement("span");
          message.textContent = finding.message;
          item.append(title, message);
          findings.append(item);
        });
      }

      const styles = [
        { selector: "node", style: {
          "background-color": "#64748b", "label": "", "color": "#172033",
          "font-size": 10, "text-wrap": "wrap", "text-max-width": 150,
          "text-valign": "bottom", "text-margin-y": 7, "width": 22, "height": 22
        }},
        { selector: "node[type = 'Spec']", style: { "background-color": "#1d4ed8", "shape": "round-rectangle" }},
        { selector: "node[type = 'Requirement']", style: { "background-color": "#0f766e", "shape": "round-rectangle" }},
        { selector: "node[type = 'Task']", style: { "background-color": "#7c3aed", "shape": "round-rectangle" }},
        { selector: "node[type = 'Artifact']", style: { "background-color": "#b45309", "shape": "rectangle" }},
        { selector: "node[type = 'MemPalaceDrawer']", style: { "background-color": "#be123c", "shape": "barrel" }},
        { selector: "edge", style: {
          "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": .75,
          "line-color": "#94a3b8", "target-arrow-color": "#94a3b8",
          "label": "", "font-size": 8, "color": "#475569",
          "text-background-color": "#fff", "text-background-opacity": .85,
          "text-background-padding": 2, "width": 1.2
        }},
        { selector: ".labelled", style: { "label": "data(label)" }},
        { selector: "node:selected", style: {
          "label": "data(label)", "border-width": 3, "border-color": "#111827"
        }},
        { selector: "edge:selected", style: {
          "label": "data(label)", "line-color": "#111827", "target-arrow-color": "#111827"
        }},
        { selector: ".faded", style: { "opacity": .12, "text-opacity": 0 }}
      ];

      function layoutName() {
        return lensSelect.value === "all" ? "cose" : "breadthfirst";
      }

      function isException(node) {
        const properties = node.data.properties || {};
        return (
          (properties.presence != null && properties.presence !== "present") ||
          (properties.reconciliation_status != null && properties.reconciliation_status !== "pass")
        );
      }

      function lensElements() {
        const nodes = payload.elements.filter((element) => element.group === "nodes");
        const edges = payload.elements.filter((element) => element.group === "edges");
        const lens = lensSelect.value;
        if (lens === "all") return payload.elements;

        let selectedEdges;
        const selectedIds = new Set();
        if (lens === "exceptions") {
          payload.exception_subject_ids.forEach((id) => selectedIds.add(id));
          nodes.filter(isException).forEach((node) => selectedIds.add(node.data.id));
          selectedEdges = edges.filter((edge) =>
            selectedIds.has(edge.data.source) || selectedIds.has(edge.data.target)
          );
          selectedEdges.forEach((edge) => {
            selectedIds.add(edge.data.source);
            selectedIds.add(edge.data.target);
          });
          if (selectedIds.size === 0) {
            nodes
              .filter((node) => node.data.type === "Spec")
              .forEach((node) => selectedIds.add(node.data.id));
          }
        } else {
          const edgeTypes = new Set(payload.lens_edge_types[lens] || []);
          const nodeTypes = new Set(payload.lens_node_types[lens] || []);
          selectedEdges = edges.filter((edge) => edgeTypes.has(edge.data.type));
          nodes
            .filter((node) => nodeTypes.has(node.data.type))
            .forEach((node) => selectedIds.add(node.data.id));
          selectedEdges.forEach((edge) => {
            selectedIds.add(edge.data.source);
            selectedIds.add(edge.data.target);
          });
        }
        return [
          ...nodes.filter((node) => selectedIds.has(node.data.id)),
          ...selectedEdges.filter((edge) =>
            selectedIds.has(edge.data.source) && selectedIds.has(edge.data.target)
          ),
        ];
      }

      function updateLabels() {
        const showAll = cy.nodes().length <= 30 || cy.zoom() >= 1.2;
        cy.elements().toggleClass("labelled", showAll);
      }

      function loadLens() {
        if (cy) cy.destroy();
        cy = cytoscape({
          container: document.getElementById("cy"),
          elements: lensElements(),
          style: styles,
          maxZoom: 2,
          layout: { name: layoutName(), directed: true, padding: 36, animate: false }
        });
        cy.on("zoom", updateLabels);
        updateLabels();
        selectedNode = null;
        selection.textContent = "No node selected";
        selection.className = "empty";
        cy.on("tap", "node", (event) => {
          selectedNode = event.target;
          selection.className = "";
          selection.textContent = JSON.stringify(selectedNode.data(), null, 2);
        });
      }

      function showHops(depth) {
        if (!selectedNode) return;
        let visible = selectedNode;
        let frontier = selectedNode;
        for (let index = 0; index < depth; index += 1) {
          frontier = frontier.closedNeighborhood();
          visible = visible.union(frontier);
        }
        cy.elements().addClass("faded");
        visible.removeClass("faded");
      }

      search.addEventListener("input", () => {
        const query = search.value.trim().toLowerCase();
        cy.nodes().removeClass("faded search-match");
        if (!query) {
          updateLabels();
          return;
        }
        cy.nodes().forEach((node) => {
          if (!JSON.stringify(node.data()).toLowerCase().includes(query)) {
            node.addClass("faded");
          } else {
            node.addClass("labelled search-match");
          }
        });
      });
      lensSelect.addEventListener("change", loadLens);
      document.getElementById("one-hop").addEventListener("click", () => showHops(1));
      document.getElementById("two-hop").addEventListener("click", () => showHops(2));
      document.getElementById("fit").addEventListener("click", () => cy.fit(undefined, 32));
      document.getElementById("reset").addEventListener("click", () => {
        search.value = "";
        cy.elements().removeClass("faded search-match");
        cy.elements().unselect();
        cy.fit(undefined, 32);
        updateLabels();
      });
      loadLens();
    })();
  </script>
</body>
</html>
"""
