from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from echelon.graph_visualization import (
    GraphVisualizationError,
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
    assert html.count('"elements"') == 1
    payload = json.loads(
        html.split("window.ECHELON_GRAPH = ", 1)[1].split(";\n    (() =>", 1)[0]
    )
    assert payload["lens_edge_types"]["portfolio"] == [
        "CONTAINS_SPEC",
        "SUPERSEDES",
        "TARGETS",
    ]
    assert "payload.elements" in html
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
    payload = json.loads(
        html.split("window.ECHELON_GRAPH = ", 1)[1].split(";\n    (() =>", 1)[0]
    )

    assert payload["exception_subject_ids"] == []


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
