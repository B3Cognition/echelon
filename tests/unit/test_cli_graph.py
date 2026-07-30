from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import GraphNode, SpecArtifactGraph
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport


def _graph() -> SpecArtifactGraph:
    return SpecArtifactGraph(
        spec_id="001-demo",
        generator_version="test",
        inputs=(),
        nodes=(
            GraphNode(
                "spec:001-demo",
                "Spec",
                {
                    "spec_id": "001-demo",
                    "path": "specs/001-demo",
                    "lifecycle": "phase_a",
                },
            ),
        ),
        edges=(),
        memory_receipts=(),
    )


def _workspace(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001\n", encoding="utf-8")
    return spec_dir


@pytest.mark.unit
def test_graph_help_exposes_build_audit_and_refresh() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "--help"])

    assert result.exit_code == 0
    assert "build" in result.output
    assert "audit" in result.output
    assert "refresh" in result.output


@pytest.mark.unit
def test_spec_graph_route_is_not_available() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "graph", "--help"])

    assert result.exit_code != 0
    assert "No such command 'graph'" in result.output


@pytest.mark.unit
def test_graph_build_does_not_write_without_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda project_root, selector: _graph(),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "build", "001-demo"])

    assert result.exit_code == 0
    assert "nodes=1" in result.output
    assert not (spec_dir / "spec-artifact-graph.json").exists()


@pytest.mark.unit
def test_graph_build_writes_with_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda project_root, selector: _graph(),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["graph", "build", "001-demo", "--write"],
    )

    assert result.exit_code == 0
    payload = json.loads(
        (spec_dir / "spec-artifact-graph.json").read_text(encoding="utf-8")
    )
    assert payload["spec_id"] == "001-demo"


@pytest.mark.unit
def test_graph_audit_json_is_machine_readable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = SpecGraphAuditReport(
        schema_version=1,
        spec_id="001-demo",
        graph_hash="sha256:graph",
        status="warn",
        findings=(
            GraphFinding(
                "warning",
                "requirement_task_missing",
                "active requirement has no mapped task",
                "req:001-demo:FR-001",
            ),
        ),
    )
    monkeypatch.setattr(
        "echelon.spec_graph_audit.audit_spec_graph",
        lambda project_root, selector: report,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["graph", "audit", "001-demo", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "warn"


@pytest.mark.unit
def test_graph_audit_maps_fail_and_unavailable_exit_codes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    statuses = iter(("fail", "unavailable"))
    monkeypatch.setattr(
        "echelon.spec_graph_audit.audit_spec_graph",
        lambda project_root, selector: SpecGraphAuditReport(
            schema_version=1,
            spec_id="001-demo",
            graph_hash=None,
            status=next(statuses),
            findings=(),
        ),
    )
    from echelon.cli_app import app

    failed = CliRunner().invoke(app, ["graph", "audit", "001-demo"])
    unavailable = CliRunner().invoke(app, ["graph", "audit", "001-demo"])

    assert failed.exit_code == 1
    assert unavailable.exit_code == 2


@pytest.mark.unit
def test_graph_refresh_writes_graph_then_audit_without_mining(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda project_root, selector: calls.append("build") or _graph(),
    )
    monkeypatch.setattr(
        "echelon.spec_graph_audit.audit_spec_graph",
        lambda project_root, selector: calls.append("audit")
        or SpecGraphAuditReport(
            schema_version=1,
            spec_id="001-demo",
            graph_hash="sha256:graph",
            status="pass",
            findings=(),
        ),
    )
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda *args, **kwargs: pytest.fail("refresh must not mine memory"),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["graph", "refresh", "001-demo", "--write"],
    )

    assert result.exit_code == 0
    assert calls == ["build", "audit"]
    assert (spec_dir / "spec-artifact-graph.json").is_file()
    assert (spec_dir / "spec-artifact-graph-audit.json").is_file()
