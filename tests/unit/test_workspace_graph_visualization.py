from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from echelon.graph_visualization import (
    GraphViewPayload,
    GraphVisualizationError,
    build_graph_view_payload,
    filter_graph,
    load_graph_document,
    render_graph_dot,
    render_graph_html,
)
from echelon.workspace_graph import WorkspaceGraphMember
from echelon.workspace_graph_audit import (
    WorkspaceGraphAuditReport,
    WorkspaceGraphFinding,
)


def _workspace_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generator_version": "test",
        "scope": "workspace",
        "workspace_name": "delivery-board",
        "source_set_digest": "sha256:sources",
        "member_state_digest": "sha256:members",
        "members": [],
        "inputs": [],
        "nodes": [
            {
                "id": "artifact:shared/ledger.json",
                "type": "Artifact",
                "properties": {"path": "shared/ledger.json"},
            },
            {
                "id": "req:001-alpha:FR-001",
                "type": "Requirement",
                "properties": {
                    "requirement_id": "FR-001",
                    "summary": "</script><script>alert(1)</script>",
                },
            },
            {
                "id": "source:service-api",
                "type": "SourceRoot",
                "properties": {"source_id": "service-api", "path": "services/api"},
            },
            {
                "id": "spec:001-alpha",
                "type": "Spec",
                "properties": {
                    "spec_id": "001-alpha",
                    "composition_status": "included",
                    "member_audit_status": "pass",
                },
            },
            {
                "id": "spec:002-beta",
                "type": "Spec",
                "properties": {
                    "spec_id": "002-beta",
                    "composition_status": "excluded",
                    "member_audit_status": "fail",
                },
            },
            {
                "id": "workspace:current",
                "type": "Workspace",
                "properties": {"workspace_name": "delivery-board"},
            },
        ],
        "edges": [
            {
                "source": "req:001-alpha:FR-001",
                "type": "DERIVED_FROM",
                "target": "artifact:shared/ledger.json",
                "properties": {},
            },
            {
                "source": "spec:001-alpha",
                "type": "HAS_REQUIREMENT",
                "target": "req:001-alpha:FR-001",
                "properties": {},
            },
            {
                "source": "spec:001-alpha",
                "type": "SUPERSEDES",
                "target": "spec:002-beta",
                "properties": {},
            },
            {
                "source": "spec:001-alpha",
                "type": "TARGETS",
                "target": "source:service-api",
                "properties": {},
            },
            {
                "source": "workspace:current",
                "type": "CONTAINS_SPEC",
                "target": "spec:001-alpha",
                "properties": {},
            },
            {
                "source": "workspace:current",
                "type": "CONTAINS_SPEC",
                "target": "spec:002-beta",
                "properties": {},
            },
        ],
    }


def _audit(status: str = "fail") -> WorkspaceGraphAuditReport:
    return WorkspaceGraphAuditReport(
        schema_version=1,
        workspace_name="delivery-board",
        graph_hash="sha256:graph",
        status=status,
        members=(
            WorkspaceGraphMember(
                spec_id="001-alpha",
                graph_path="specs/001-alpha/spec-artifact-graph.json",
                graph_hash="sha256:alpha",
                member_source_set_digest="sha256:alpha-sources",
                member_memory_state_digest="sha256:alpha-memory",
                audit_hash="sha256:alpha-audit",
                audit_status="pass",
                included=True,
            ),
        ),
        findings=(
            WorkspaceGraphFinding(
                "error",
                "workspace_member_excluded",
                "Spec 002-beta has no current member graph",
                "spec:002-beta",
            ),
        )
        if status == "fail"
        else (),
    )


def _isolated_workspace_document() -> dict[str, object]:
    document = _workspace_document()
    document["nodes"] = [
        {
            "id": "source:isolated-a",
            "type": "SourceRoot",
            "properties": {"source_id": "isolated-a", "path": "services/isolated-a"},
        },
        {
            "id": "source:isolated-b",
            "type": "SourceRoot",
            "properties": {"source_id": "isolated-b", "path": "services/isolated-b"},
        },
        {
            "id": "spec:003-isolated",
            "type": "Spec",
            "properties": {"spec_id": "003-isolated"},
        },
        {
            "id": "workspace:current",
            "type": "Workspace",
            "properties": {"workspace_name": "delivery-board"},
        },
    ]
    document["edges"] = []
    return document


def _viewer_payload(html: str) -> dict[str, object]:
    return json.loads(
        html.split("window.ECHELON_GRAPH = ", 1)[1].split(";\n    (() =>", 1)[0]
    )


def _viewer_script(html: str) -> str:
    start = html.index("    window.ECHELON_GRAPH = ")
    end = html.index("\n  </script>", start)
    return html[start:end]


def _rendered_viewer_elements(html: str, tmp_path: Path) -> list[dict[str, object]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    script_path = tmp_path / "workspace-viewer-filter.js"
    script_path.write_text(
        """const elements = {
  "graph-title": {},
  "audit-status": {},
  "graph-lens": { value: "", addEventListener() {} },
  "graph-search": { value: "", addEventListener() {} },
  "selection": {},
  "findings": {},
  "cy": {},
  "one-hop": { addEventListener() {} },
  "two-hop": { addEventListener() {} },
  "fit": { addEventListener() {} },
  "reset": { addEventListener() {} },
};
global.window = {};
global.document = { getElementById(id) { return elements[id]; } };
let rendered;
global.cytoscape = (config) => {
  rendered = config.elements;
  return {
    nodes() { return { length: 0 }; },
    elements() { return { toggleClass() {} }; },
    on() {},
  };
};
"""
        + _viewer_script(html)
        + "\nconsole.log(JSON.stringify(rendered));\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script_path)], capture_output=True)

    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout)


@pytest.mark.unit
def test_workspace_html_embeds_one_filterable_payload_and_portfolio_lens() -> None:
    html = render_graph_html(
        _workspace_document(),
        _audit(),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    )

    assert '"scope": "workspace"' in html
    assert '"title": "delivery-board"' in html
    assert 'value="portfolio"' in html
    assert '"views"' not in html
    assert html.count("window.ECHELON_GRAPH = ") == 1
    payload = _viewer_payload(html)
    assert "portfolio" in next(
        edge["lenses"] for edge in payload["edges"] if edge["type"] == "TARGETS"
    )
    assert "payload.nodes" in html
    assert "</script><script>alert(1)</script>" not in html
    assert r"<\/script><script>alert(1)<\/script>" in html


@pytest.mark.unit
def test_workspace_portfolio_dot_uses_workspace_title_and_relationships() -> None:
    dot = render_graph_dot(_workspace_document(), _audit(), lens="portfolio")

    assert dot.startswith('digraph "delivery-board" {\n')
    assert 'graph [label="delivery-board | audit: fail"' in dot
    assert '"workspace:current" -> "spec:001-alpha"' in dot
    assert 'label="CONTAINS_SPEC"' in dot
    assert 'label="TARGETS"' in dot
    assert 'label="SUPERSEDES"' in dot


@pytest.mark.unit
def test_workspace_exceptions_lens_retains_audited_spec_and_its_neighbors() -> None:
    dot = render_graph_dot(_workspace_document(), _audit(), lens="exceptions")

    assert '"spec:002-beta"' in dot
    assert '"workspace:current"' in dot
    assert 'label="CONTAINS_SPEC"' in dot


@pytest.mark.unit
def test_workspace_viewer_ignores_unknown_exception_subjects() -> None:
    audit = replace(
        _audit(),
        findings=(
            WorkspaceGraphFinding(
                "error",
                "workspace_member_removed",
                "Spec 003-gamma is no longer present",
                "spec:003-gamma",
            ),
        ),
    )
    html = render_graph_html(
        _workspace_document(),
        audit,
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="exceptions",
    )
    payload = _viewer_payload(html)

    assert not any(node["exception"] for node in payload["nodes"])


@pytest.mark.unit
def test_portfolio_lens_keeps_isolated_workspace_spec_and_source_nodes() -> None:
    document = _isolated_workspace_document()
    filtered = filter_graph(document, _audit(status="unavailable"), lens="portfolio")
    dot = render_graph_dot(document, _audit(status="unavailable"), lens="portfolio")

    assert [node["id"] for node in filtered["nodes"]] == [
        "source:isolated-a",
        "source:isolated-b",
        "spec:003-isolated",
        "workspace:current",
    ]
    assert filtered["edges"] == []
    for node_id in (
        "source:isolated-a",
        "source:isolated-b",
        "spec:003-isolated",
        "workspace:current",
    ):
        assert f'"{node_id}"' in dot


@pytest.mark.unit
def test_workspace_payload_exposes_member_specs_and_portfolio_lens_membership() -> None:
    document = _isolated_workspace_document()
    document["nodes"][0]["properties"]["member_specs"] = ["002-beta", "001-alpha"]
    payload = build_graph_view_payload(
        document,
        _audit(status="unavailable"),
        initial_lens="portfolio",
    )

    assert isinstance(payload, GraphViewPayload)
    assert payload.scope == "workspace"
    assert payload.title == "delivery-board"
    assert payload.lenses == (
        "all",
        "exceptions",
        "traceability",
        "memory",
        "delivery",
        "portfolio",
    )
    source = next(node for node in payload.nodes if node["id"] == "source:isolated-a")
    assert source["member_specs"] == ("001-alpha", "002-beta")
    assert source["lenses"] == ("all", "portfolio")


@pytest.mark.unit
def test_workspace_html_portfolio_lens_keeps_isolated_node_types() -> None:
    html = render_graph_html(
        _isolated_workspace_document(),
        _audit(status="unavailable"),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    )
    payload = _viewer_payload(html)

    assert {
        node["id"]
        for node in payload["nodes"]
        if "portfolio" in node["lenses"]
    } == {
        "source:isolated-a",
        "source:isolated-b",
        "spec:003-isolated",
        "workspace:current",
    }


@pytest.mark.unit
def test_workspace_viewer_script_is_syntactically_valid_when_node_is_available(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    html = render_graph_html(
        _isolated_workspace_document(),
        _audit(status="unavailable"),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    )
    script_path = tmp_path / "workspace-viewer.js"
    script_path.write_text(
        _viewer_script(html),
        encoding="utf-8",
    )

    result = subprocess.run([node, "--check", str(script_path)], capture_output=True)

    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.unit
def test_workspace_viewer_filters_portfolio_with_type_seeds_and_closed_edges(
    tmp_path: Path,
) -> None:
    isolated_html = render_graph_html(
        _isolated_workspace_document(),
        _audit(status="unavailable"),
        cytoscape_source="",
        initial_lens="portfolio",
    )
    isolated_elements = _rendered_viewer_elements(isolated_html, tmp_path)
    assert {
        element["data"]["id"]
        for element in isolated_elements
        if element["group"] == "nodes"
    } == {
        "source:isolated-a",
        "source:isolated-b",
        "spec:003-isolated",
        "workspace:current",
    }
    assert [element for element in isolated_elements if element["group"] == "edges"] == []

    connected_html = render_graph_html(
        _workspace_document(),
        _audit(status="unavailable"),
        cytoscape_source="",
        initial_lens="portfolio",
    )
    elements = _rendered_viewer_elements(connected_html, tmp_path)
    node_ids = {
        element["data"]["id"]
        for element in elements
        if element["group"] == "nodes"
    }
    edges = [element for element in elements if element["group"] == "edges"]
    assert node_ids == {
        "source:service-api",
        "spec:001-alpha",
        "spec:002-beta",
        "workspace:current",
    }
    assert {edge["data"]["type"] for edge in edges} == {
        "CONTAINS_SPEC",
        "SUPERSEDES",
        "TARGETS",
    }
    assert all(
        edge["data"]["source"] in node_ids and edge["data"]["target"] in node_ids
        for edge in edges
    )


@pytest.mark.unit
def test_workspace_html_and_dot_are_deterministic_when_document_order_changes() -> None:
    document = _workspace_document()
    reordered = dict(document)
    reordered["nodes"] = list(reversed(document["nodes"]))
    reordered["edges"] = list(reversed(document["edges"]))

    assert render_graph_dot(document, _audit(), lens="portfolio") == render_graph_dot(
        reordered,
        _audit(),
        lens="portfolio",
    )
    assert render_graph_html(
        document,
        _audit(),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    ) == render_graph_html(
        reordered,
        _audit(),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    )


@pytest.mark.unit
def test_workspace_document_loader_rejects_missing_edge_endpoint(tmp_path: Path) -> None:
    document = _workspace_document()
    document["edges"] = [
        {
            "source": "workspace:current",
            "type": "CONTAINS_SPEC",
            "target": "spec:missing",
            "properties": {},
        }
    ]
    path = tmp_path / "workspace-artifact-graph.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(GraphVisualizationError, match="missing endpoint"):
        load_graph_document(path)


@pytest.mark.unit
def test_placeholder_only_unavailable_workspace_viewer_supports_portfolio() -> None:
    document = _workspace_document()
    document["nodes"] = [
        node
        for node in document["nodes"]
        if node["id"]
        in {"workspace:current", "spec:001-alpha", "spec:002-beta"}
    ]
    document["edges"] = [
        edge
        for edge in document["edges"]
        if edge["type"] == "CONTAINS_SPEC"
    ]

    html = render_graph_html(
        document,
        _audit(status="unavailable"),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="portfolio",
    )

    assert '"status": "unavailable"' in html
    assert '"workspace:current"' in html
    assert 'value="portfolio"' in html
