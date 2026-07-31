from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.graph_visualization import (
    GraphVisualizationError,
    filter_graph,
    load_cytoscape_source,
    load_graph_document,
    render_graph_dot,
    render_graph_html,
)
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport


def _document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generator_version": "test",
        "spec_id": "001-demo",
        "source_set_digest": "sha256:sources",
        "memory_state_digest": "sha256:memory",
        "inputs": [],
        "nodes": [
            {
                "id": "artifact:001-demo:input",
                "type": "Artifact",
                "properties": {"path": "inputs/catalog.json"},
            },
            {
                "id": "artifact:001-demo:ledger",
                "type": "Artifact",
                "properties": {"path": "verified-fulfillment-ledger.json"},
            },
            {
                "id": "drawer:001-demo:FR-001",
                "type": "MemPalaceDrawer",
                "properties": {
                    "presence": "missing",
                    "reconciliation_status": "fail",
                },
            },
            {
                "id": "req:001-demo:FR-001",
                "type": "Requirement",
                "properties": {
                    "requirement_id": "FR-001",
                    "summary": "</script><script>alert(1)</script>",
                },
            },
            {
                "id": "spec:001-demo",
                "type": "Spec",
                "properties": {"spec_id": "001-demo"},
            },
            {
                "id": "task:001-demo:T-001",
                "type": "Task",
                "properties": {"task_id": "T-001", "status": "PENDING"},
            },
        ],
        "edges": [
            {
                "source": "req:001-demo:FR-001",
                "type": "DERIVED_FROM",
                "target": "artifact:001-demo:input",
                "properties": {},
            },
            {
                "source": "req:001-demo:FR-001",
                "type": "STORED_AS",
                "target": "drawer:001-demo:FR-001",
                "properties": {"reconciliation_status": "fail"},
            },
            {
                "source": "req:001-demo:FR-001",
                "type": "VERIFIED_BY",
                "target": "artifact:001-demo:ledger",
                "properties": {"complete": True},
            },
            {
                "source": "spec:001-demo",
                "type": "HAS_REQUIREMENT",
                "target": "req:001-demo:FR-001",
                "properties": {},
            },
            {
                "source": "task:001-demo:T-001",
                "type": "IMPLEMENTS",
                "target": "req:001-demo:FR-001",
                "properties": {},
            },
        ],
    }


def _audit(status: str = "fail") -> SpecGraphAuditReport:
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id="001-demo",
        graph_hash="sha256:graph",
        status=status,
        findings=(
            GraphFinding(
                "error",
                "requirement_task_missing",
                "Requirement \"FR-001\" has no mapped task",
                "req:001-demo:FR-001",
            ),
        )
        if status == "fail"
        else (),
    )


@pytest.mark.unit
def test_load_graph_document_rejects_missing_edge_endpoint(tmp_path: Path) -> None:
    document = _document()
    document["nodes"] = [
        node
        for node in document["nodes"]
        if node["id"] != "artifact:001-demo:input"
    ]
    path = tmp_path / "spec-artifact-graph.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(GraphVisualizationError, match="missing endpoint"):
        load_graph_document(path)


@pytest.mark.unit
def test_load_graph_document_delegates_to_graph_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_visualization as graph_visualization

    document = _document()
    path = tmp_path / "spec-artifact-graph.json"
    monkeypatch.setattr(graph_visualization, "read_graph_document", lambda received: document)

    assert load_graph_document(path) is document


@pytest.mark.unit
def test_delivery_lens_retains_only_delivery_edges_and_their_endpoints() -> None:
    filtered = filter_graph(_document(), _audit(), lens="delivery")

    assert {edge["type"] for edge in filtered["edges"]} == {
        "IMPLEMENTS",
        "VERIFIED_BY",
    }
    assert [node["id"] for node in filtered["nodes"]] == [
        "artifact:001-demo:ledger",
        "req:001-demo:FR-001",
        "task:001-demo:T-001",
    ]


@pytest.mark.unit
def test_exceptions_lens_includes_audited_subject_and_failed_memory_neighbor() -> None:
    filtered = filter_graph(_document(), _audit(), lens="exceptions")

    assert [node["id"] for node in filtered["nodes"]] == [
        "artifact:001-demo:input",
        "artifact:001-demo:ledger",
        "drawer:001-demo:FR-001",
        "req:001-demo:FR-001",
        "spec:001-demo",
        "task:001-demo:T-001",
    ]
    assert {edge["type"] for edge in filtered["edges"]} == {
        "DERIVED_FROM",
        "HAS_REQUIREMENT",
        "IMPLEMENTS",
        "STORED_AS",
        "VERIFIED_BY",
    }


@pytest.mark.unit
def test_dot_export_is_deterministic_directed_and_escaped() -> None:
    first = render_graph_dot(_document(), _audit(), lens="delivery")
    second = render_graph_dot(_document(), _audit(), lens="delivery")

    assert first == second
    assert first.startswith('digraph "001-demo" {\n')
    assert 'graph [label="001-demo | audit: fail"' in first
    assert '"task:001-demo:T-001" -> "req:001-demo:FR-001"' in first
    assert 'label="IMPLEMENTS"' in first
    assert 'shape="round-rectangle"' not in first
    assert 'shape="box"' in first
    assert '\\"FR-001\\"' not in first
    assert first.endswith("}\n")


@pytest.mark.unit
def test_html_viewer_is_offline_searchable_and_script_safe() -> None:
    html = render_graph_html(
        _document(),
        _audit(),
        cytoscape_source="window.cytoscape = function () {};",
        initial_lens="exceptions",
    )

    assert "window.cytoscape = function () {};" in html
    assert "https://" not in html
    assert 'id="graph-search"' in html
    assert 'id="graph-lens"' in html
    for lens in ("all", "exceptions", "traceability", "memory", "delivery"):
        assert f'value="{lens}"' in html
    assert 'value="portfolio"' not in html
    assert '"initial_lens": "exceptions"' in html
    assert '"label": ""' in html
    assert 'selector: ".labelled"' in html
    assert 'cy.on("zoom", updateLabels)' in html
    assert "maxZoom: 2" in html
    assert "</script><script>alert(1)</script>" not in html
    assert r"<\/script><script>alert(1)<\/script>" in html


@pytest.mark.unit
def test_packaged_cytoscape_bundle_is_available_offline() -> None:
    source = load_cytoscape_source()

    assert "The Cytoscape Consortium" in source[:500]
    assert '.version="3.34.0"' in source
    assert len(source) > 100_000
