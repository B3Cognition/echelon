"""Self-contained, read-only vis-network rendering for graph view payloads."""

from __future__ import annotations

from importlib.resources import files
import json

from echelon.graph_visualization import GraphViewPayload, GraphVisualizationError


VIS_NETWORK_ASSET = "assets/vis-network-10.1.0.min.js"
VIS_MAX_NODES = 5_000
VIS_MAX_EDGES = 10_000


def load_vis_network_source() -> str:
    """Load the packaged standalone vis-network bundle without network access."""
    try:
        return files("echelon").joinpath(VIS_NETWORK_ASSET).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise GraphVisualizationError(
            f"packaged vis-network asset is missing: {VIS_NETWORK_ASSET}"
        ) from exc


def render_vis_graph_html(
    payload: GraphViewPayload,
    vis_network_source: str,
) -> str:
    """Render a deterministic offline viewer without changing the payload."""
    node_count = len(payload.nodes)
    edge_count = len(payload.edges)
    if node_count > VIS_MAX_NODES or edge_count > VIS_MAX_EDGES:
        return (
            _LIMIT_TEMPLATE.replace("__NODE_COUNT__", f"{node_count:,}")
            .replace("__EDGE_COUNT__", f"{edge_count:,}")
        )

    payload_json = _script_safe_json(payload.to_dict())
    return (
        _HTML_TEMPLATE.replace("__VIS_NETWORK_SOURCE__", vis_network_source)
        .replace("__GRAPH_PAYLOAD__", payload_json)
    )


def _script_safe_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (
        serialized.replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


_LIMIT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Echelon Graph</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #172033; background: #f5f7fa; }
    main { min-height: 100vh; display: grid; place-items: center; padding: 32px; }
    .message { max-width: 680px; border-left: 4px solid #b45309; padding: 4px 0 4px 18px; }
    h1 { margin: 0 0 10px; font-size: 20px; letter-spacing: 0; }
    p { margin: 6px 0; color: #475569; line-height: 1.5; }
    strong { color: #172033; }
  </style>
</head>
<body>
  <main>
    <div class="message" role="status" aria-live="polite">
      <h1>Graph exceeds the vis-network rendering limit</h1>
      <p><strong>__NODE_COUNT__ nodes</strong> and <strong>__EDGE_COUNT__ edges</strong> were found.</p>
      <p>No partial network was rendered. Use the Cytoscape renderer for this graph size.</p>
    </div>
  </main>
</body>
</html>
"""


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
    button, input, select { font: inherit; letter-spacing: 0; }
    button:focus-visible, input:focus-visible, select:focus-visible {
      outline: 2px solid #2563eb; outline-offset: 2px;
    }
    header { height: 58px; display: flex; align-items: center; gap: 12px; padding: 0 18px;
      border-bottom: 1px solid #d6dce5; background: #fff; }
    h1 { min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      font-size: 16px; font-weight: 700; letter-spacing: 0; }
    .status { flex: 0 0 auto; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .status-pass { color: #166534; background: #dcfce7; }
    .status-warn { color: #854d0e; background: #fef9c3; }
    .status-fail, .status-unavailable { color: #991b1b; background: #fee2e2; }
    .header-actions { margin-left: auto; display: flex; align-items: center; gap: 6px; }
    .icon-button { width: 36px; height: 34px; display: inline-grid; place-items: center; padding: 0;
      border: 1px solid #bcc5d2; border-radius: 4px; background: #fff; color: #172033;
      cursor: pointer; font-size: 18px; line-height: 1; }
    .icon-button:hover, .icon-button[aria-pressed="true"] { background: #eef2f7; }
    .controls { height: 48px; display: flex; align-items: center; gap: 8px; padding: 7px 18px;
      border-bottom: 1px solid #d6dce5; background: #f8fafc; overflow-x: auto; }
    .controls input[type="search"], .controls select { height: 34px; flex: 0 0 auto;
      border: 1px solid #bcc5d2; border-radius: 4px; background: #fff; color: #172033; }
    .controls input[type="search"] { width: 240px; padding: 0 10px; }
    .controls select { width: 148px; padding: 0 28px 0 9px; }
    .segment { width: 144px; height: 34px; flex: 0 0 144px; display: grid; grid-template-columns: 1fr 1fr;
      border: 1px solid #bcc5d2; border-radius: 4px; overflow: hidden; background: #fff; }
    .segment input { position: absolute; opacity: 0; pointer-events: none; }
    .segment label { display: grid; place-items: center; cursor: pointer; font-size: 12px; }
    .segment label + input + label { border-left: 1px solid #bcc5d2; }
    .segment input:checked + label { color: #fff; background: #334155; }
    .segment input:focus-visible + label { outline: 2px solid #2563eb; outline-offset: -2px; }
    .summary { flex: 0 0 auto; color: #64748b; font-size: 12px; white-space: nowrap; }
    main { height: calc(100vh - 106px); min-height: 420px; display: grid;
      grid-template-columns: minmax(0, 1fr) 340px; }
    .graph-pane { min-width: 0; min-height: 0; position: relative; background: #fff; overflow: hidden; }
    #network { width: 100%; height: 100%; min-height: 420px; }
    .render-state { position: absolute; left: 12px; bottom: 10px; max-width: calc(100% - 24px);
      padding: 3px 7px; border: 1px solid #d6dce5; border-radius: 4px; background: #fff;
      color: #475569; font-size: 11px; pointer-events: none; }
    aside { min-width: 0; overflow: auto; border-left: 1px solid #d6dce5; background: #f8fafc; }
    section { padding: 14px; border-bottom: 1px solid #d6dce5; }
    h2 { margin: 0 0 10px; font-size: 13px; letter-spacing: 0; }
    h3 { margin: 12px 0 6px; font-size: 12px; letter-spacing: 0; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere;
      font: 12px/1.45 ui-monospace, SFMono-Regular, monospace; }
    ul { margin: 0; padding-left: 18px; }
    li { margin: 3px 0; overflow-wrap: anywhere; font-size: 12px; line-height: 1.4; }
    .legend-list { display: grid; gap: 7px; }
    .legend-item { min-height: 22px; display: flex; align-items: center; gap: 8px; font-size: 12px; }
    .legend-item input { width: 16px; height: 16px; margin: 0; accent-color: #334155; }
    .swatch { width: 12px; height: 12px; flex: 0 0 12px; border-radius: 2px; }
    .finding { padding: 8px 0; border-top: 1px solid #e2e8f0; font-size: 12px; line-height: 1.4; }
    .finding:first-child { border-top: 0; padding-top: 0; }
    .finding strong { display: block; color: #991b1b; }
    .empty { color: #64748b; font-size: 12px; }
    @media (max-width: 860px) {
      header { padding: 0 10px; }
      .controls { height: auto; min-height: 48px; flex-wrap: wrap;
        padding: 7px 10px; overflow-x: hidden; }
      .controls input[type="search"] { width: auto; min-width: 0; flex: 1 1 210px; }
      .controls select { width: auto; min-width: 0; flex: 1 1 140px; }
      .segment { width: auto; flex: 1 1 144px; }
      .summary { margin-left: auto; }
      main { height: auto; min-height: calc(100vh - 106px); grid-template-columns: 1fr;
        grid-template-rows: minmax(420px, 62vh) minmax(260px, auto); }
      aside { border-left: 0; border-top: 1px solid #d6dce5; }
    }
  </style>
  <script>__VIS_NETWORK_SOURCE__</script>
</head>
<body>
  <header>
    <h1 id="graph-title"></h1>
    <span id="audit-status" class="status" aria-live="polite"></span>
    <div class="header-actions">
      <button id="fit" class="icon-button" type="button" aria-label="Fit graph to view"
        title="Fit graph to view">&#9633;</button>
      <button id="reset" class="icon-button" type="button" aria-label="Reset graph view and filters"
        title="Reset graph view and filters">&#8635;</button>
      <button id="physics" class="icon-button" type="button" aria-label="Toggle graph physics"
        title="Toggle graph physics" aria-pressed="true">&#9889;</button>
    </div>
  </header>
  <div class="controls" role="toolbar" aria-label="Graph controls">
    <input id="graph-search" type="search" placeholder="Search nodes" aria-label="Search graph nodes">
    <select id="graph-lens" aria-label="Graph lens"></select>
    <div class="segment" role="group" aria-label="Node grouping">
      <input id="group-type" name="grouping" type="radio" value="type"
        aria-label="Group nodes by type" checked>
      <label for="group-type">Type</label>
      <input id="group-spec" name="grouping" type="radio" value="spec"
        aria-label="Group nodes by specification">
      <label for="group-spec">Spec</label>
    </div>
    <span id="graph-summary" class="summary" aria-live="polite"></span>
  </div>
  <main>
    <div class="graph-pane">
      <div id="network" role="img" aria-label="Directed artifact graph"></div>
      <div id="render-state" class="render-state" aria-live="polite">Preparing graph</div>
    </div>
    <aside aria-label="Graph inspector">
      <section>
        <h2>Legend filters</h2>
        <div id="legend-filters" class="legend-list"></div>
      </section>
      <section>
        <h2>Selection details</h2>
        <pre id="selection-details" class="empty">No node selected</pre>
        <h3>Incoming neighbors</h3>
        <ul id="incoming-neighbors"><li class="empty">None</li></ul>
        <h3>Outgoing neighbors</h3>
        <ul id="outgoing-neighbors"><li class="empty">None</li></ul>
      </section>
      <section>
        <h2>Audit findings</h2>
        <div id="audit-findings"></div>
      </section>
    </aside>
  </main>
  <script id="graph-data" type="application/json">__GRAPH_PAYLOAD__</script>
  <script>
    (() => {
      "use strict";
      const payload = JSON.parse(document.getElementById("graph-data").textContent);
      const PALETTE = [
        "#2563eb", "#0f766e", "#7c3aed", "#b45309", "#be123c",
        "#0369a1", "#4d7c0f", "#a21caf", "#c2410c", "#475569"
      ];
      const SHAPES = {
        Spec: "dot", Requirement: "diamond", Task: "triangle", Artifact: "square",
        MemPalaceDrawer: "star", Amendment: "triangleDown", Deferral: "hexagon"
      };
      const MIN_NODE_SIZE = 18;
      const MAX_NODE_SIZE = 44;
      const search = document.getElementById("graph-search");
      const lensSelect = document.getElementById("graph-lens");
      const legend = document.getElementById("legend-filters");
      const summary = document.getElementById("graph-summary");
      const selection = document.getElementById("selection-details");
      const incomingList = document.getElementById("incoming-neighbors");
      const outgoingList = document.getElementById("outgoing-neighbors");
      const renderState = document.getElementById("render-state");
      const physicsButton = document.getElementById("physics");
      const nodeTypes = [...new Set(payload.nodes.map((node) => node.type))].sort();
      const enabledTypes = new Set(nodeTypes);
      let grouping = "type";
      let physicsEnabled = true;
      let selectedNodeId = null;
      let currentVisibleGraph = { nodes: [], edges: [] };

      document.getElementById("graph-title").textContent = payload.title;
      const auditStatus = document.getElementById("audit-status");
      const auditState = String(payload.audit.status || "unavailable");
      auditStatus.textContent = `audit: ${auditState}`;
      auditStatus.className = `status status-${auditState}`;

      payload.lenses.forEach((lens) => {
        const option = document.createElement("option");
        option.value = lens;
        option.textContent = lens.charAt(0).toUpperCase() + lens.slice(1);
        lensSelect.append(option);
      });
      lensSelect.value = payload.initial_lens;

      function colorForGroupKey(key) {
        let hash = 2166136261;
        for (let index = 0; index < key.length; index += 1) {
          hash ^= key.charCodeAt(index);
          hash = Math.imul(hash, 16777619);
        }
        return PALETTE[(hash >>> 0) % PALETTE.length];
      }

      const typeColor = new Map(nodeTypes.map((type) => [type, colorForGroupKey(`type:${type}`)]));

      nodeTypes.forEach((type) => {
        const label = document.createElement("label");
        label.className = "legend-item";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = true;
        checkbox.value = type;
        checkbox.setAttribute("aria-label", `Show ${type} nodes`);
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.backgroundColor = typeColor.get(type);
        const text = document.createElement("span");
        text.textContent = type;
        label.append(checkbox, swatch, text);
        legend.append(label);
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) enabledTypes.add(type);
          else enabledTypes.delete(type);
          rebuildData();
        });
      });

      const findings = document.getElementById("audit-findings");
      const auditFindings = Array.isArray(payload.audit.findings) ? payload.audit.findings : [];
      if (auditFindings.length === 0) {
        findings.textContent = "No findings";
        findings.className = "empty";
      } else {
        auditFindings.forEach((finding) => {
          const item = document.createElement("div");
          item.className = "finding";
          const heading = document.createElement("strong");
          heading.textContent = `${finding.code || "unknown"} / ${finding.severity || "unknown"}`;
          const message = document.createElement("span");
          message.textContent = String(finding.message || "");
          item.append(heading, message);
          findings.append(item);
        });
      }

      function groupKey(node) {
        if (grouping === "type") return `type:${node.type}`;
        const specs = Array.isArray(node.member_specs) ? [...node.member_specs].sort() : [];
        return `spec:${specs[0] || "unassigned"}`;
      }

      function groupOptions(nodes) {
        const keys = [...new Set(nodes.map(groupKey))].sort();
        return Object.fromEntries(keys.map((key) => [key, {
          color: {
            background: colorForGroupKey(key),
            border: "#ffffff",
            highlight: { background: colorForGroupKey(key), border: "#111827" }
          }
        }]));
      }

      function nodeSize(node) {
        return Math.min(MAX_NODE_SIZE, Math.max(MIN_NODE_SIZE, 18 + Math.sqrt(node.degree || 0) * 2.6));
      }

      function visibleGraph() {
        const activeLens = lensSelect.value;
        const query = search.value.trim().toLowerCase();
        const nodes = payload.nodes.filter((node) =>
          node.lenses.includes(activeLens) &&
          enabledTypes.has(node.type) &&
          (!query || String(node.searchable_label).toLowerCase().includes(query))
        );
        const visibleIds = new Set(nodes.map((node) => node.id));
        const edges = payload.edges.filter((edge) =>
          edge.lenses.includes(activeLens) &&
          visibleIds.has(edge.source) &&
          visibleIds.has(edge.target)
        );
        return { nodes, edges };
      }

      function networkNode(node) {
        return {
          id: node.id,
          label: node.label,
          group: groupKey(node),
          shape: SHAPES[node.type] || "dot",
          size: nodeSize(node),
          borderWidth: node.exception ? 3 : 1,
          color: node.exception ? { border: "#be123c" } : undefined,
          font: { size: 11, color: "#172033", face: "Inter, system-ui, sans-serif" }
        };
      }

      function networkEdge(edge) {
        return {
          id: `${edge.source}|${edge.type}|${edge.target}`,
          from: edge.source,
          to: edge.target,
          label: edge.type,
          arrows: { to: { enabled: true, scaleFactor: 0.65 } },
          color: { color: "#94a3b8", highlight: "#334155" },
          font: { size: 9, color: "#475569", background: "#ffffff", align: "middle" },
          width: 1.2
        };
      }

      const initial = visibleGraph();
      currentVisibleGraph = initial;
      const data = {
        nodes: new vis.DataSet(initial.nodes.map(networkNode)),
        edges: new vis.DataSet(initial.edges.map(networkEdge))
      };
      const network = new vis.Network(document.getElementById("network"), data, {
        autoResize: true,
        groups: groupOptions(initial.nodes),
        interaction: { hover: true, navigationButtons: false, keyboard: true },
        layout: { improvedLayout: true, randomSeed: 1979 },
        nodes: { chosen: true },
        edges: { smooth: { enabled: true, type: "dynamic" }, chosen: true },
        physics: {
          enabled: true,
          solver: "forceAtlas2Based",
          forceAtlas2Based: {
            gravitationalConstant: -52,
            centralGravity: 0.012,
            springLength: 118,
            springConstant: 0.07,
            damping: 0.5,
            avoidOverlap: 0.45
          },
          stabilization: { enabled: true, iterations: 700, updateInterval: 40, fit: true }
        }
      });

      function clearList(list) {
        while (list.firstChild) list.removeChild(list.firstChild);
      }

      function populateNeighbors(list, neighbors) {
        clearList(list);
        if (neighbors.length === 0) {
          const item = document.createElement("li");
          item.className = "empty";
          item.textContent = "None";
          list.append(item);
          return;
        }
        neighbors.forEach(({ edge, node }) => {
          const item = document.createElement("li");
          item.textContent = `${edge.type}: ${node ? node.label : "Unknown node"}`;
          list.append(item);
        });
      }

      function showSelection(nodeId) {
        selectedNodeId = nodeId;
        const visibleNodeById = new Map(
          currentVisibleGraph.nodes.map((node) => [node.id, node])
        );
        const node = visibleNodeById.get(nodeId);
        if (!node) return;
        selection.className = "";
        selection.textContent = JSON.stringify({
          id: node.id,
          type: node.type,
          degree: node.degree,
          member_specs: node.member_specs,
          properties: node.properties
        }, null, 2);
        const incoming = currentVisibleGraph.edges
          .filter((edge) => edge.target === nodeId)
          .map((edge) => ({ edge, node: visibleNodeById.get(edge.source) }));
        const outgoing = currentVisibleGraph.edges
          .filter((edge) => edge.source === nodeId)
          .map((edge) => ({ edge, node: visibleNodeById.get(edge.target) }));
        populateNeighbors(incomingList, incoming);
        populateNeighbors(outgoingList, outgoing);
      }

      function clearSelection() {
        selectedNodeId = null;
        selection.className = "empty";
        selection.textContent = "No node selected";
        populateNeighbors(incomingList, []);
        populateNeighbors(outgoingList, []);
      }

      function rebuildData() {
        const filtered = visibleGraph();
        currentVisibleGraph = filtered;
        network.setOptions({ groups: groupOptions(filtered.nodes) });
        network.setData({
          nodes: new vis.DataSet(filtered.nodes.map(networkNode)),
          edges: new vis.DataSet(filtered.edges.map(networkEdge))
        });
        network.setOptions({ physics: { enabled: physicsEnabled } });
        summary.textContent = `${filtered.nodes.length} nodes / ${filtered.edges.length} edges`;
        if (selectedNodeId && filtered.nodes.some((node) => node.id === selectedNodeId)) {
          network.selectNodes([selectedNodeId]);
          showSelection(selectedNodeId);
        } else {
          clearSelection();
        }
        renderState.textContent = physicsEnabled ? "Stabilizing layout" : "Physics paused";
      }

      network.on("selectNode", (event) => showSelection(event.nodes[0]));
      network.on("deselectNode", clearSelection);
      network.on("stabilizationProgress", (event) => {
        renderState.textContent = `Stabilizing ${event.iterations}/${event.total}`;
      });
      network.on("stabilizationIterationsDone", () => {
        network.stopSimulation();
        renderState.textContent = "Layout stabilized";
      });

      search.addEventListener("input", rebuildData);
      lensSelect.addEventListener("change", rebuildData);
      document.querySelectorAll('input[name="grouping"]').forEach((input) => {
        input.addEventListener("change", () => {
          grouping = input.value;
          rebuildData();
        });
      });
      document.getElementById("fit").addEventListener("click", () => {
        network.fit({ animation: false });
      });
      physicsButton.addEventListener("click", () => {
        physicsEnabled = !physicsEnabled;
        physicsButton.setAttribute("aria-pressed", String(physicsEnabled));
        network.setOptions({ physics: { enabled: physicsEnabled } });
        renderState.textContent = physicsEnabled ? "Physics running" : "Physics paused";
        if (physicsEnabled) network.startSimulation();
      });
      document.getElementById("reset").addEventListener("click", () => {
        search.value = "";
        lensSelect.value = payload.initial_lens;
        grouping = "type";
        document.getElementById("group-type").checked = true;
        enabledTypes.clear();
        nodeTypes.forEach((type) => enabledTypes.add(type));
        legend.querySelectorAll('input[type="checkbox"]').forEach((input) => {
          input.checked = true;
        });
        physicsEnabled = true;
        physicsButton.setAttribute("aria-pressed", "true");
        clearSelection();
        rebuildData();
        network.fit({ animation: false });
      });

      summary.textContent = `${initial.nodes.length} nodes / ${initial.edges.length} edges`;
      renderState.textContent = physicsEnabled ? "Stabilizing layout" : "Physics paused";
    })();
  </script>
</body>
</html>
"""
