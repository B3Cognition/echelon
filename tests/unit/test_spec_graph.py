from __future__ import annotations

from pathlib import Path
import json

import pytest

from echelon.spec_graph import (
    GraphEdge,
    GraphInput,
    GraphNode,
    SpecArtifactGraph,
    SpecGraphError,
    build_spec_graph,
    render_spec_graph,
)


def _graph(
    *,
    inputs: tuple[GraphInput, ...] = (),
    nodes: tuple[GraphNode, ...] = (),
    edges: tuple[GraphEdge, ...] = (),
) -> SpecArtifactGraph:
    return SpecArtifactGraph(
        spec_id="001-demo",
        generator_version="test",
        inputs=inputs,
        nodes=nodes,
        edges=edges,
        memory_receipts=(),
    )


@pytest.mark.unit
def test_graph_rendering_is_deterministic_and_sorted() -> None:
    spec = GraphNode("spec:001-demo", "Spec", {"path": "specs/001-demo"})
    requirement = GraphNode(
        "req:001-demo:FR-001",
        "Requirement",
        {"requirement_id": "FR-001"},
    )
    graph = _graph(
        inputs=(
            GraphInput("specs/001-demo/tasks.md", "sha256:bbb", "task_source", True),
            GraphInput("specs/001-demo/spec.md", "sha256:aaa", "requirements_source", True),
        ),
        nodes=(requirement, spec),
        edges=(
            GraphEdge(
                "spec:001-demo",
                "HAS_REQUIREMENT",
                "req:001-demo:FR-001",
                {},
            ),
        ),
    )

    payload = graph.to_dict()

    assert [item["path"] for item in payload["inputs"]] == [
        "specs/001-demo/spec.md",
        "specs/001-demo/tasks.md",
    ]
    assert [item["id"] for item in payload["nodes"]] == [
        "req:001-demo:FR-001",
        "spec:001-demo",
    ]
    assert payload["source_set_digest"].startswith("sha256:")
    assert payload["memory_state_digest"].startswith("sha256:")
    assert render_spec_graph(graph) == render_spec_graph(graph)
    assert render_spec_graph(graph).endswith(b"\n")


@pytest.mark.unit
def test_source_set_digest_changes_with_input_identity_and_content() -> None:
    first = _graph(
        inputs=(GraphInput("spec.md", "sha256:aaa", "requirements_source", True),),
    )
    changed = _graph(
        inputs=(GraphInput("spec.md", "sha256:bbb", "requirements_source", True),),
    )
    added = _graph(
        inputs=(
            GraphInput("spec.md", "sha256:aaa", "requirements_source", True),
            GraphInput("tasks.md", "sha256:ccc", "task_source", False),
        ),
    )

    assert first.source_set_digest != changed.source_set_digest
    assert first.source_set_digest != added.source_set_digest


@pytest.mark.unit
@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        (
            (
                GraphNode("spec:001-demo", "Spec", {}),
                GraphNode("spec:001-demo", "Spec", {}),
            ),
            (),
            "duplicate node id",
        ),
        (
            (GraphNode("spec:001-demo", "Spec", {}),),
            (
                GraphEdge(
                    "spec:001-demo",
                    "HAS_REQUIREMENT",
                    "req:001-demo:FR-001",
                    {},
                ),
            ),
            "missing edge endpoint",
        ),
    ],
)
def test_graph_rejects_invalid_identity(
    nodes: tuple[GraphNode, ...],
    edges: tuple[GraphEdge, ...],
    message: str,
) -> None:
    with pytest.raises(SpecGraphError, match=message):
        _graph(nodes=nodes, edges=edges).to_dict()


@pytest.mark.unit
def test_graph_rejects_duplicate_edge_identity() -> None:
    nodes = (
        GraphNode("spec:001-demo", "Spec", {}),
        GraphNode("req:001-demo:FR-001", "Requirement", {}),
    )
    edge = GraphEdge(
        "spec:001-demo",
        "HAS_REQUIREMENT",
        "req:001-demo:FR-001",
        {},
    )

    with pytest.raises(SpecGraphError, match="duplicate edge"):
        _graph(nodes=nodes, edges=(edge, edge)).to_dict()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _canonical_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "# Demo\n\n"
        "- **FR-001**: Build the report.\n"
        "- **FR-002**: Export the report.\n"
        "- **AC-001**: Export is machine readable.\n",
        encoding="utf-8",
    )
    (spec_dir / "plan.md").write_text(
        "The plan mentions NFR-999 but cannot define it.\n",
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001,AC-001 depends=none\n"
        "- [x] T-002 complexity=standard phase=verify req=FR-002,NFR-999 depends=T-001\n"
        "  **Status:** DONE\n",
        encoding="utf-8",
    )
    _write_json(spec_dir / "inputs" / "manifest.json", {"schema_version": 1})
    _write_json(
        spec_dir / "inputs" / "catalog.json",
        {"schema_version": 1, "units": [{"id": "IN-REQ-001"}]},
    )
    _write_json(
        spec_dir / "inputs" / "traceability.json",
        {
            "schema_version": 1,
            "requirements": [
                {
                    "input_unit_id": "IN-REQ-001",
                    "disposition": "included",
                    "spec_ids": ["FR-001"],
                    "task_ids": ["T-001"],
                    "targets": [],
                }
            ],
        },
    )
    return spec_dir


@pytest.mark.unit
def test_build_spec_graph_uses_only_canonical_spec_requirements(
    tmp_path: Path,
) -> None:
    _canonical_spec(tmp_path)

    payload = build_spec_graph(tmp_path, "001-demo").to_dict()
    nodes = {item["id"]: item for item in payload["nodes"]}
    edges = {
        (item["source"], item["type"], item["target"]): item
        for item in payload["edges"]
    }

    assert nodes["spec:001-demo"]["properties"]["lifecycle"] == "phase_a"
    assert nodes["req:001-demo:FR-001"]["properties"]["category"] == "functional"
    assert nodes["req:001-demo:AC-001"]["properties"]["category"] == "acceptance"
    assert "req:001-demo:NFR-999" not in nodes
    assert nodes["task:001-demo:T-001"]["properties"]["status"] == "PENDING"
    assert nodes["task:001-demo:T-002"]["properties"]["status"] == "DONE"
    assert (
        "task:001-demo:T-001",
        "IMPLEMENTS",
        "req:001-demo:FR-001",
    ) in edges
    assert (
        "req:001-demo:FR-001",
        "DERIVED_FROM",
        "artifact:001-demo:specs/001-demo/inputs/catalog.json",
    ) in edges
    assert nodes["task:001-demo:T-002"]["properties"]["unresolved_requirement_ids"] == [
        "NFR-999"
    ]


@pytest.mark.unit
def test_build_spec_graph_includes_deferrals_amendments_and_verified_ledger(
    tmp_path: Path,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    _write_json(
        spec_dir / "deferred-scope.json",
        {
            "schema_version": 1,
            "entries": [
                {
                    "entry_id": "defer-001",
                    "status": "deferred",
                    "selected_ids": ["FR-002"],
                    "derived_task_ids": ["T-002"],
                    "prior_task_statuses": {"T-002": "PENDING"},
                    "reason": "Later release",
                    "deferred_at": "2026-07-29T10:00:00Z",
                    "planned_at": None,
                }
            ],
        },
    )
    amendment = spec_dir / "amendments" / "001"
    amendment.mkdir(parents=True)
    (amendment / "change-request.md").write_text("# Change\n", encoding="utf-8")
    (amendment / "impact.md").write_text("# Impact\n", encoding="utf-8")
    _write_json(
        spec_dir / "verified-fulfillment-ledger.json",
        {
            "schema_version": 1,
            "rows": [
                {
                    "requirement_id": "FR-001",
                    "status": "IMPLEMENTED",
                    "evidence_refs": ["tests/test_report.py"],
                    "verified_commit": "abc123",
                    "verify_scope": "full",
                },
                {
                    "requirement_id": "AC-001",
                    "status": "UNVERIFIED",
                    "evidence_refs": [],
                    "verified_commit": "abc123",
                    "verify_scope": "full",
                },
            ],
        },
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    nodes = {item["id"]: item for item in payload["nodes"]}
    edges = {
        (item["source"], item["type"], item["target"]): item
        for item in payload["edges"]
    }

    assert nodes["amendment:001-demo:001"]["properties"]["status"] == "promoted"
    assert nodes["deferral:001-demo:defer-001"]["properties"]["reason"] == "Later release"
    assert (
        "spec:001-demo",
        "AMENDED_BY",
        "amendment:001-demo:001",
    ) in edges
    assert (
        "req:001-demo:FR-002",
        "DEFERRED_BY",
        "deferral:001-demo:defer-001",
    ) in edges
    assert (
        "task:001-demo:T-002",
        "DEFERRED_BY",
        "deferral:001-demo:defer-001",
    ) in edges
    assert edges[
        (
            "req:001-demo:FR-001",
            "VERIFIED_BY",
            "artifact:001-demo:specs/001-demo/verified-fulfillment-ledger.json",
        )
    ]["properties"]["complete"] is True
    assert edges[
        (
            "req:001-demo:AC-001",
            "VERIFIED_BY",
            "artifact:001-demo:specs/001-demo/verified-fulfillment-ledger.json",
        )
    ]["properties"]["complete"] is False
