from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import GraphNode, SpecArtifactGraph, write_spec_graph
from echelon.spec_graph_audit import SpecGraphAuditReport


def _graph(spec_id: str, *, changed: bool = False) -> SpecArtifactGraph:
    nodes = [
        GraphNode(
            f"spec:{spec_id}",
            "Spec",
            {
                "spec_id": spec_id,
                "path": f"specs/{spec_id}",
                "lifecycle": "phase_a",
            },
        )
    ]
    if changed:
        nodes.append(
            GraphNode(
                f"artifact:{spec_id}/changed.md",
                "Artifact",
                {"path": f"{spec_id}/changed.md"},
            )
        )
    return SpecArtifactGraph(
        spec_id=spec_id,
        generator_version="test",
        inputs=(),
        nodes=tuple(nodes),
        edges=(),
        memory_receipts=(),
    )


def _live_audit(project_root: Path, selector: str | Path) -> SpecGraphAuditReport:
    spec_dir = Path(selector)
    if not spec_dir.is_absolute():
        spec_dir = project_root / "specs" / spec_dir
    graph_bytes = (spec_dir / "spec-artifact-graph.json").read_bytes()
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id=spec_dir.name,
        graph_hash=f"sha256:{hashlib.sha256(graph_bytes).hexdigest()}",
        status="pass",
        findings=(),
    )


@pytest.mark.integration
def test_workspace_graph_cli_refresh_audit_view_and_export_report_stale_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sources" / "application"
    source_root.mkdir(parents=True)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources:\n"
        "  - id: application\n    path: sources/application\n",
        encoding="utf-8",
    )
    spec_dirs = [
        tmp_path / "specs" / f"{index:03d}-{label}"
        for index, label in enumerate(("alpha", "beta"), start=1)
    ]
    for spec_dir in spec_dirs:
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Synthetic spec\n", encoding="utf-8")
        write_spec_graph(_graph(spec_dir.name), spec_dir)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", _live_audit)
    monkeypatch.setattr("echelon.workspace_graph_refresh.audit_spec_graph", _live_audit)
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory",
        lambda root: type("Report", (), {"status": "pass"})(),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory",
        lambda root, selector: type("Report", (), {"status": "pass"})(),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh._evidence_is_applicable",
        lambda root, spec_dir: False,
    )

    from echelon.cli_app import app

    runner = CliRunner()
    refreshed = runner.invoke(app, ["graph", "workspace", "refresh", "--write"])
    audit = runner.invoke(app, ["graph", "workspace", "audit", "--json"])
    viewer = runner.invoke(app, ["graph", "workspace", "view", "--no-open"])
    dot_path = tmp_path / "workspace.dot"
    exported = runner.invoke(
        app,
        ["graph", "workspace", "export", "--format", "dot", "--output", str(dot_path)],
    )

    assert refreshed.exit_code == audit.exit_code == viewer.exit_code == exported.exit_code == 0
    assert json.loads(audit.output)["status"] == "pass"
    assert (tmp_path / ".echelon" / "runtime" / "graph" / "workspace.html").is_file()
    assert dot_path.read_text(encoding="utf-8").startswith("digraph")

    stale_dir = spec_dirs[0]
    write_spec_graph(_graph(stale_dir.name, changed=True), stale_dir)

    stale_audit = runner.invoke(app, ["graph", "workspace", "audit", "--json"])
    stale_view = runner.invoke(
        app,
        ["graph", "workspace", "view", "--no-open", "--output", "stale.html"],
    )
    stale_dot_path = tmp_path / "stale.dot"
    stale_export = runner.invoke(
        app,
        ["graph", "workspace", "export", "--output", str(stale_dot_path)],
    )

    assert stale_audit.exit_code == stale_view.exit_code == stale_export.exit_code == 1
    findings = json.loads(stale_audit.output)["findings"]
    assert any(
        finding["code"] == "workspace_member_graph_changed"
        and finding["subject_id"] == f"spec:{stale_dir.name}"
        for finding in findings
    )
    assert (tmp_path / "stale.html").is_file()
    assert stale_dot_path.read_text(encoding="utf-8").startswith("digraph")
