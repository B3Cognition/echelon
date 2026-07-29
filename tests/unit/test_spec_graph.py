from __future__ import annotations

from pathlib import Path
import hashlib
import json
from types import SimpleNamespace

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


@pytest.mark.unit
def test_build_spec_graph_uses_native_planner_and_audit_for_drawers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import echelon.mempalace_audit  # noqa: F401

    spec_dir = _canonical_spec(tmp_path)
    support = spec_dir / "fulfillment-gaps.md"
    support.write_text("# Gaps\n\nFR-001 has no gap.\n", encoding="utf-8")

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return [
                SimpleNamespace(
                    drawer_id="drawer-fr-001",
                    requirement_id="FR-001",
                    room="functional-requirements",
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="spec-hash",
                    requirement_content_sha256="content-hash",
                )
            ]

        def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
            return [
                SimpleNamespace(
                    drawer_id="drawer-gap-001",
                    requirement_id="CTX-fulfillment-gaps-001",
                    room="spec-fulfillment-evidence",
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="support-hash",
                    requirement_content_sha256="support-content-hash",
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector: SimpleNamespace(
            schema_version=1,
            wing="demo-wing",
            status="pass",
            expected_count=2,
            present_current_count=2,
            missing=[],
            stale=[],
            wrong_wing=[],
            wrong_room=[],
            duplicate=[],
            non_canonical=[],
            lifecycle_excluded=[],
            errors=[],
        ),
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    nodes = {item["id"]: item for item in payload["nodes"]}
    edges = {
        (item["source"], item["type"], item["target"]): item
        for item in payload["edges"]
    }

    assert nodes["drawer:001-demo:drawer-fr-001"]["properties"]["presence"] == "present"
    assert nodes["drawer:001-demo:drawer-gap-001"]["properties"]["room"] == (
        "spec-fulfillment-evidence"
    )
    support_id = "artifact:001-demo:specs/001-demo/fulfillment-gaps.md"
    assert support_id in nodes
    assert (
        support_id,
        "STORED_AS",
        "drawer:001-demo:drawer-gap-001",
    ) in edges
    assert (
        "req:001-demo:FR-001",
        "STORED_AS",
        "drawer:001-demo:drawer-fr-001",
    ) in edges
    memory_inputs = [
        item for item in payload["inputs"] if item["role"] == "memory_audit_report"
    ]
    assert memory_inputs == [
        {
            "path": "mempalace://canonical-spec/001-demo/audit",
            "hash": memory_inputs[0]["hash"],
            "role": "memory_audit_report",
            "required": True,
            "source_set_digest": memory_inputs[0]["source_set_digest"],
            "status": "pass",
        }
    ]


@pytest.mark.unit
def test_build_spec_graph_retains_expected_drawers_when_memory_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import echelon.mempalace_audit  # noqa: F401

    spec_dir = _canonical_spec(tmp_path)

    class FakeAdapter:
        wing = "demo-wing"

        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return [
                SimpleNamespace(
                    drawer_id="drawer-fr-001",
                    requirement_id="FR-001",
                    room="functional-requirements",
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="spec-hash",
                    requirement_content_sha256="content-hash",
                )
            ]

        def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
            return []

    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector: SimpleNamespace(
            schema_version=1,
            wing="demo-wing",
            status="unavailable",
            expected_count=1,
            present_current_count=0,
            missing=[],
            stale=[],
            wrong_wing=[],
            wrong_room=[],
            duplicate=[],
            non_canonical=[],
            lifecycle_excluded=[],
            errors=["ConnectionError"],
        ),
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    drawer = next(
        item for item in payload["nodes"] if item["id"] == "drawer:001-demo:drawer-fr-001"
    )

    assert drawer["properties"]["presence"] == "unavailable"
    assert drawer["properties"]["reconciliation_status"] == "unavailable"


@pytest.mark.unit
def test_build_spec_graph_reconciles_applicable_evidence_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    evidence = spec_dir / "fulfillment-report.md"
    evidence.write_text("# Fulfillment\n\nFR-001 is implemented.\n", encoding="utf-8")

    class FakeAdapter:
        wing = "demo-wing"

        def plan_spec_evidence_artifact_rows(
            self,
            content,
            *,
            source,
            artifact_metadata,
        ):
            return [
                SimpleNamespace(
                    drawer_id="drawer-evidence-001",
                    requirement_id="EVID-001",
                    room=artifact_metadata["room"],
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="evidence-hash",
                    requirement_content_sha256="evidence-content-hash",
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.create_spec_evidence_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.audit_spec_evidence_memory",
        lambda project_root, selector: SimpleNamespace(
            schema_version=1,
            wing="demo-wing",
            status="pass",
            artifact_count=1,
            expected_count=1,
            present_current_count=1,
            missing=[],
            stale=[],
            wrong_wing=[],
            wrong_room=[],
            duplicate=[],
            non_canonical=[],
            lifecycle_excluded=[],
            errors=[],
        ),
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    nodes = {item["id"]: item for item in payload["nodes"]}
    edges = {
        (item["source"], item["type"], item["target"])
        for item in payload["edges"]
    }

    artifact_id = "artifact:001-demo:specs/001-demo/fulfillment-report.md"
    drawer_id = "drawer:001-demo:drawer-evidence-001"
    assert nodes[drawer_id]["properties"]["artifact_kind"] == "spec-evidence"
    assert (artifact_id, "STORED_AS", drawer_id) in edges
    assert any(
        item["path"] == "mempalace://spec-evidence/001-demo/audit"
        and item["status"] == "pass"
        for item in payload["inputs"]
    )


@pytest.mark.unit
def test_build_spec_graph_limits_re_memory_to_canonical_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    linked = tmp_path / "re" / "workspace" / "overview.md"
    linked.parent.mkdir(parents=True)
    linked.write_text("# Linked RE\n", encoding="utf-8")
    unrelated = tmp_path / "re" / "workspace" / "relationships.md"
    unrelated.write_text("# Unrelated RE\n", encoding="utf-8")
    _write_json(
        spec_dir / "re-context.json",
        {
            "schema_version": 1,
            "status": "attached",
            "generation": 2,
            "artifacts": [
                {
                    "path": "re/workspace/overview.md",
                    "hash": (
                        "sha256:"
                        + hashlib.sha256(linked.read_bytes()).hexdigest()
                    ),
                }
            ],
        },
    )

    class FakeAdapter:
        wing = "demo-wing"

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            return [
                SimpleNamespace(
                    drawer_id=f"drawer-{Path(source).stem}",
                    requirement_id=f"RE-{Path(source).stem.upper()}",
                    room=artifact_metadata["room"],
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="re-hash",
                    requirement_content_sha256="re-content-hash",
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    monkeypatch.setattr(
        "echelon.mempalace_re.audit_re_memory",
        lambda project_root: SimpleNamespace(
            schema_version=1,
            wing="demo-wing",
            status="pass",
            artifact_count=2,
            expected_count=2,
            present_current_count=2,
            missing=[],
            stale=[],
            wrong_wing=[],
            wrong_room=[],
            duplicate=[],
            non_canonical=[],
            lifecycle_excluded=[],
            errors=[],
        ),
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    nodes = {item["id"]: item for item in payload["nodes"]}

    assert "drawer:001-demo:drawer-overview" in nodes
    assert "drawer:001-demo:drawer-relationships" not in nodes
    assert "artifact:001-demo:re/workspace/overview.md" in nodes
    assert "artifact:001-demo:re/workspace/relationships.md" not in nodes
