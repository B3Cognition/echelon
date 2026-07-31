from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from echelon.graph_read import GraphReadModel
from echelon.graph_traversal import GraphPath, GraphResult, PathStep
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport


def _model(*, status: str = "pass", findings: tuple[GraphFinding, ...] = ()) -> GraphReadModel:
    node = {
        "id": "req:905-import-prose:FR-012",
        "type": "Requirement",
        "properties": {
            "requirement_id": "FR-012",
            "source_path": "specs/905-import-prose/spec.md",
            "source_line": 12,
            "source_text": "Validate imports before publishing.",
        },
    }
    return GraphReadModel(
        scope="spec",
        graph_hash="sha256:persisted",
        document={},
        audit=SpecGraphAuditReport(
            schema_version=1,
            spec_id="905-import-prose",
            graph_hash="sha256:live",
            status=status,
            findings=findings,
        ),
        nodes_by_id=MappingProxyType({str(node["id"]): node}),
        outgoing=MappingProxyType({str(node["id"]): ()}),
        incoming=MappingProxyType({str(node["id"]): ()}),
    )


@pytest.mark.unit
def test_graph_result_payload_preserves_persisted_mappings_and_path_directions() -> None:
    from echelon.graph_output import graph_result_payload

    model = _model()
    edge = {
        "source": "artifact:spec.md",
        "type": "DERIVED_FROM",
        "target": "req:905-import-prose:FR-012",
        "properties": {"note": "</script><script>alert('nope')</script>"},
    }
    result = GraphResult(
        nodes=(model.nodes_by_id["req:905-import-prose:FR-012"],),
        edges=(edge,),
        paths=(
            GraphPath(
                ("req:905-import-prose:FR-012", "artifact:spec.md"),
                (
                    PathStep(
                        source="artifact:spec.md",
                        type="DERIVED_FROM",
                        target="req:905-import-prose:FR-012",
                        direction="in",
                        properties=edge["properties"],
                    ),
                ),
            ),
        ),
        truncated=True,
    )

    payload = graph_result_payload(
        model,
        "path",
        {"source": "FR-012", "target": "spec.md", "max_hops": 8},
        result,
    )

    assert set(payload) == {
        "schema_version",
        "scope",
        "graph_hash",
        "audit",
        "command",
        "request",
        "nodes",
        "edges",
        "paths",
        "truncated",
    }
    assert payload["nodes"] == [model.nodes_by_id["req:905-import-prose:FR-012"]]
    assert payload["edges"] == [edge]
    assert payload["paths"] == [
        {
            "node_ids": ["req:905-import-prose:FR-012", "artifact:spec.md"],
            "steps": [
                {
                    "source": "artifact:spec.md",
                    "type": "DERIVED_FROM",
                    "target": "req:905-import-prose:FR-012",
                    "direction": "in",
                    "properties": edge["properties"],
                }
            ],
        }
    ]
    assert json.loads(json.dumps(payload))["edges"][0]["properties"]["note"] == (
        "</script><script>alert('nope')</script>"
    )


@pytest.mark.unit
def test_render_graph_result_text_shows_audit_sources_stored_arrows_and_truncation() -> None:
    from echelon.graph_output import render_graph_result_text

    finding = GraphFinding("warning", "stale", "Graph sources changed.")
    model = _model(status="warn", findings=(finding,))
    edge = {
        "source": "artifact:spec.md",
        "type": "DERIVED_FROM",
        "target": "req:905-import-prose:FR-012",
        "properties": {},
    }
    result = GraphResult(
        nodes=(model.nodes_by_id["req:905-import-prose:FR-012"],),
        edges=(edge,),
        paths=(
            GraphPath(
                ("req:905-import-prose:FR-012", "artifact:spec.md"),
                (
                    PathStep(
                        source="artifact:spec.md",
                        type="DERIVED_FROM",
                        target="req:905-import-prose:FR-012",
                        direction="in",
                        properties={},
                    ),
                ),
            ),
        ),
        truncated=True,
    )

    rendered = render_graph_result_text(model, "path", result)

    assert rendered.startswith("Scope: spec\nAudit: warn")
    assert "Warning [stale]: Graph sources changed." in rendered
    assert "Source: specs/905-import-prose/spec.md:12" in rendered
    assert "artifact:spec.md -[DERIVED_FROM]-> req:905-import-prose:FR-012" in rendered
    assert "direction=in" in rendered
    assert "Results truncated." in rendered
