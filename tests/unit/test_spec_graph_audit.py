from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from echelon.spec_graph import (
    GraphEdge,
    GraphInput,
    GraphNode,
    MemoryReceipt,
    SpecArtifactGraph,
    write_spec_graph,
)
from echelon.spec_graph_audit import (
    GraphFinding,
    REBUILDABLE_GRAPH_FINDING_CODES,
    SpecGraphAuditReport,
    audit_spec_graph,
    classify_spec_graph_audit,
    write_spec_graph_audit,
)


def _graph(
    *,
    lifecycle: str = "phase_a",
    inputs: tuple[GraphInput, ...] = (),
    receipts: tuple[MemoryReceipt, ...] = (),
    include_task: bool = True,
    include_verification: bool = False,
) -> SpecArtifactGraph:
    nodes = [
        GraphNode(
            "spec:001-demo",
            "Spec",
            {
                "spec_id": "001-demo",
                "path": "specs/001-demo",
                "lifecycle": lifecycle,
            },
        ),
        GraphNode(
            "req:001-demo:FR-001",
            "Requirement",
            {
                "requirement_id": "FR-001",
                "category": "functional",
                "source_line": 3,
                "source_path": "specs/001-demo/spec.md",
                "source_text": "- **FR-001**: Build the report.",
            },
        ),
    ]
    edges = [
        GraphEdge(
            "spec:001-demo",
            "HAS_REQUIREMENT",
            "req:001-demo:FR-001",
            {},
        )
    ]
    if include_task:
        nodes.append(
            GraphNode(
                "task:001-demo:T-001",
                "Task",
                {
                    "task_id": "T-001",
                    "status": "PENDING",
                    "phase": "build",
                    "target": None,
                    "unresolved_requirement_ids": [],
                },
            )
        )
        edges.append(
            GraphEdge(
                "task:001-demo:T-001",
                "IMPLEMENTS",
                "req:001-demo:FR-001",
                {},
            )
        )
    if include_verification:
        nodes.append(
            GraphNode(
                "artifact:001-demo:specs/001-demo/verified-fulfillment-ledger.json",
                "Artifact",
                {
                    "path": "specs/001-demo/verified-fulfillment-ledger.json",
                    "role": "verification-evidence",
                    "hash": "sha256:ledger",
                    "mining_status": "mined",
                },
            )
        )
        edges.append(
            GraphEdge(
                "req:001-demo:FR-001",
                "VERIFIED_BY",
                "artifact:001-demo:specs/001-demo/verified-fulfillment-ledger.json",
                {"complete": True},
            )
        )
    return SpecArtifactGraph(
        spec_id="001-demo",
        generator_version="test",
        inputs=inputs,
        nodes=tuple(nodes),
        edges=tuple(edges),
        memory_receipts=receipts,
    )


@pytest.mark.unit
@pytest.mark.parametrize("code", sorted(REBUILDABLE_GRAPH_FINDING_CODES))
def test_classify_every_rebuildable_graph_finding_as_stale(code: str) -> None:
    report = SpecGraphAuditReport(
        schema_version=1,
        spec_id="001-demo",
        graph_hash="sha256:graph",
        status="fail",
        findings=(GraphFinding("error", code, f"finding {code}"),),
    )

    assert classify_spec_graph_audit(report) == "stale"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "codes", "expected"),
    [
        ("pass", (), "current"),
        ("warn", ("mempalace_reconciliation_unavailable",), "current"),
        ("fail", ("graph_source_set_stale",), "stale"),
        ("fail", ("graph_memory_state_stale",), "stale"),
        ("unavailable", ("graph_missing",), "stale"),
        ("fail", ("graph_invalid",), "stale"),
        ("unavailable", ("graph_source_unavailable",), "unavailable"),
        ("fail", ("requirement_verification_missing",), "unhealthy"),
        ("fail", ("future_coherence_finding",), "unhealthy"),
    ],
)
def test_classify_spec_graph_audit(
    status: str,
    codes: tuple[str, ...],
    expected: str,
) -> None:
    report = SpecGraphAuditReport(
        schema_version=1,
        spec_id="001-demo",
        graph_hash="sha256:graph",
        status=status,
        findings=tuple(
            GraphFinding("error", code, f"finding {code}")
            for code in codes
        ),
    )

    assert classify_spec_graph_audit(report) == expected


def _write_current_graph(tmp_path: Path, graph: SpecArtifactGraph) -> Path:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001\n", encoding="utf-8")
    write_spec_graph(graph, spec_dir)
    return spec_dir


@pytest.mark.unit
def test_audit_passes_for_matching_current_graph(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = _graph(
        inputs=(
            GraphInput(
                "specs/001-demo/spec.md",
                "sha256:spec",
                "requirements_source",
                True,
            ),
        ),
    )
    spec_dir = _write_current_graph(tmp_path, graph)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )

    report = audit_spec_graph(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.findings == ()
    assert classify_spec_graph_audit(report) == "current"
    assert report.graph_hash == (
        "sha256:"
        + hashlib.sha256(
            (spec_dir / "spec-artifact-graph.json").read_bytes()
        ).hexdigest()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate_payload", "expected_message"),
    [
        (
            lambda payload, requirement: payload.pop("node_projection_version"),
            "graph projection version 1 is stale",
        ),
        (
            lambda payload, requirement: requirement["properties"].pop("source_text"),
            "graph requirement projection is stale",
        ),
        (
            lambda payload, requirement: requirement["properties"].__setitem__("source_line", True),
            "graph requirement projection is stale",
        ),
    ],
)
def test_audit_reports_stale_requirement_projection(
    tmp_path: Path,
    monkeypatch,
    mutate_payload,
    expected_message: str,
) -> None:
    graph = _graph(
        inputs=(
            GraphInput(
                "specs/001-demo/spec.md",
                "sha256:spec",
                "requirements_source",
                True,
            ),
        ),
    )
    spec_dir = _write_current_graph(tmp_path, graph)
    payload = json.loads((spec_dir / "spec-artifact-graph.json").read_text(encoding="utf-8"))
    requirement = next(node for node in payload["nodes"] if node["type"] == "Requirement")
    mutate_payload(payload, requirement)
    (spec_dir / "spec-artifact-graph.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )

    report = audit_spec_graph(tmp_path, spec_dir)
    stale_findings = [
        finding for finding in report.findings if finding.code == "graph_projection_stale"
    ]

    assert report.status == "fail"
    assert len(stale_findings) == 1
    assert stale_findings[0].message == expected_message
    assert classify_spec_graph_audit(report) == "stale"


@pytest.mark.unit
def test_audit_distinguishes_graph_staleness_from_current_memory_health(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old = _graph(
        inputs=(
            GraphInput("specs/001-demo/spec.md", "sha256:old", "requirements_source", True),
            GraphInput(
                "mempalace://canonical-spec/001-demo/audit",
                "sha256:old-audit",
                "memory_audit_report",
                True,
                status="fail",
                source_set_digest="sha256:old-source",
            ),
        ),
        receipts=(
            MemoryReceipt(
                "canonical-spec",
                "sha256:old-source",
                "sha256:old-audit",
                "fail",
            ),
        ),
    )
    current = _graph(
        inputs=(
            GraphInput("specs/001-demo/spec.md", "sha256:new", "requirements_source", True),
            GraphInput(
                "mempalace://canonical-spec/001-demo/audit",
                "sha256:new-audit",
                "memory_audit_report",
                True,
                status="pass",
                source_set_digest="sha256:new-source",
            ),
        ),
        receipts=(
            MemoryReceipt(
                "canonical-spec",
                "sha256:new-source",
                "sha256:new-audit",
                "pass",
            ),
        ),
    )
    spec_dir = _write_current_graph(tmp_path, old)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: current,
    )

    report = audit_spec_graph(tmp_path, spec_dir)
    codes = {finding.code for finding in report.findings}

    assert report.status == "fail"
    assert "graph_source_set_stale" in codes
    assert "graph_memory_state_stale" in codes
    assert "mempalace_reconciliation_failed" not in codes


@pytest.mark.unit
def test_audit_reports_required_memory_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = _graph(
        inputs=(
            GraphInput(
                "mempalace://canonical-spec/001-demo/audit",
                "sha256:audit",
                "memory_audit_report",
                True,
                status="unavailable",
                source_set_digest="sha256:sources",
            ),
        ),
        receipts=(
            MemoryReceipt(
                "canonical-spec",
                "sha256:sources",
                "sha256:audit",
                "unavailable",
            ),
        ),
    )
    spec_dir = _write_current_graph(tmp_path, graph)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )

    report = audit_spec_graph(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert {finding.code for finding in report.findings} == {
        "mempalace_reconciliation_unavailable"
    }


@pytest.mark.unit
def test_audit_enforces_lifecycle_coverage_with_stable_finding_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = _graph(lifecycle="verified", include_task=False)
    spec_dir = _write_current_graph(tmp_path, graph)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )

    report = audit_spec_graph(tmp_path, spec_dir)
    findings = {finding.code: finding for finding in report.findings}

    assert report.status == "fail"
    assert findings["requirement_task_missing"].id == (
        "finding:requirement_task_missing:req:001-demo:FR-001"
    )
    assert findings["requirement_verification_missing"].severity == "error"


@pytest.mark.unit
def test_audit_does_not_require_tasks_for_acceptance_criteria(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = _graph(lifecycle="build", include_task=False)
    graph = SpecArtifactGraph(
        spec_id=graph.spec_id,
        generator_version=graph.generator_version,
        inputs=graph.inputs,
        nodes=tuple(
            GraphNode(
                node.id,
                node.type,
                {
                    **node.properties,
                    "requirement_id": "AC-001",
                    "category": "acceptance",
                },
            )
            if node.type == "Requirement"
            else node
            for node in graph.nodes
        ),
        edges=graph.edges,
        memory_receipts=graph.memory_receipts,
    )
    spec_dir = _write_current_graph(tmp_path, graph)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )

    report = audit_spec_graph(tmp_path, spec_dir)

    assert "requirement_task_missing" not in {
        finding.code for finding in report.findings
    }


@pytest.mark.unit
def test_write_graph_audit_uses_deterministic_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graph = _graph()
    spec_dir = _write_current_graph(tmp_path, graph)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: graph,
    )
    report = audit_spec_graph(tmp_path, spec_dir)

    path = write_spec_graph_audit(report, spec_dir)

    assert path.name == "spec-artifact-graph-audit.json"
    assert path.read_bytes().endswith(b"\n")


@pytest.mark.unit
def test_audit_reports_missing_graph_as_unavailable(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001\n", encoding="utf-8")

    report = audit_spec_graph(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert report.findings[0].code == "graph_missing"


@pytest.mark.unit
def test_audit_reports_malformed_graph_without_traceback(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001\n", encoding="utf-8")
    (spec_dir / "spec-artifact-graph.json").write_text("{broken", encoding="utf-8")

    report = audit_spec_graph(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.findings[0].code == "graph_invalid"
    assert "malformed" in report.findings[0].message


@pytest.mark.unit
def test_audit_reports_added_input_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old = _graph()
    current = _graph(
        inputs=(
            GraphInput(
                "specs/001-demo/tasks.md",
                "sha256:tasks",
                "task_source",
                False,
            ),
        ),
    )
    spec_dir = _write_current_graph(tmp_path, old)
    monkeypatch.setattr(
        "echelon.spec_graph_audit.build_spec_graph",
        lambda project_root, selector: current,
    )

    report = audit_spec_graph(tmp_path, spec_dir)

    assert "graph_input_added" in {finding.code for finding in report.findings}
