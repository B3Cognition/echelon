from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner


@dataclass(frozen=True)
class _Graph:
    nodes: tuple[object, ...] = ()
    edges: tuple[object, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    graph: _Graph


@dataclass(frozen=True)
class _Report:
    status: str
    findings: tuple[object, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"scope": "workspace", "status": self.status, "findings": []}


@dataclass(frozen=True)
class _RefreshResult:
    candidate: _Candidate
    report: _Report
    outcomes: tuple[object, ...] = ()


@pytest.mark.unit
def test_workspace_graph_help_exposes_lifecycle_commands() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "--help"])

    assert result.exit_code == 0
    assert all(name in result.output for name in ("build", "audit", "refresh", "view", "export"))


@pytest.mark.unit
def test_workspace_build_only_writes_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _Candidate(graph=_Graph())
    writes: list[object] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph.build_workspace_graph", lambda root: candidate
    )
    monkeypatch.setattr(
        "echelon.workspace_graph.write_workspace_graph",
        lambda graph, root: writes.append(graph),
    )
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda *args, **kwargs: pytest.fail("build must not mine memory"),
    )
    from echelon.cli_app import app

    preview = CliRunner().invoke(app, ["graph", "workspace", "build"])
    written = CliRunner().invoke(app, ["graph", "workspace", "build", "--write"])

    assert preview.exit_code == 0
    assert written.exit_code == 0
    assert writes == [candidate.graph]


@pytest.mark.unit
def test_workspace_audit_json_is_only_json_and_maps_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.audit_workspace_graph",
        lambda root: _Report("fail"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.write_workspace_graph_audit",
        lambda report, root: pytest.fail("audit without --write must not persist"),
    )
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda *args, **kwargs: pytest.fail("audit must not mine memory"),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "audit", "--json"])

    assert result.exit_code == 1
    assert result.output == '{\n  "findings": [],\n  "scope": "workspace",\n  "status": "fail"\n}\n'


@pytest.mark.unit
def test_workspace_refresh_uses_service_candidate_audit_and_exit_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    expected = _RefreshResult(_Candidate(_Graph()), _Report("unavailable"))
    seen: list[bool] = []
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.refresh_workspace_graph",
        lambda root, *, write: seen.append(write) or expected,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "refresh"])

    assert result.exit_code == 2
    assert seen == [False]
    assert "Workspace graph audit unavailable" in result.output


def _persisted_workspace_graph(tmp_path: Path) -> Path:
    path = tmp_path / ".echelon" / "runtime" / "graph" / "workspace-artifact-graph.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        """{
  "schema_version": 1,
  "scope": "workspace",
  "workspace_name": "demo",
  "nodes": [
    {"id": "workspace:current", "type": "Workspace", "properties": {}},
    {"id": "spec:001-demo", "type": "Spec", "properties": {"spec_id": "001-demo"}}
  ],
  "edges": [
    {"source": "workspace:current", "type": "CONTAINS_SPEC", "target": "spec:001-demo", "properties": {}}
  ]
}
""",
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_workspace_view_defaults_to_runtime_path_and_portfolio_lens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _persisted_workspace_graph(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.audit_workspace_graph",
        lambda root: _Report("fail"),
    )
    monkeypatch.setattr(
        "webbrowser.open",
        lambda url: pytest.fail("--no-open must keep the browser closed"),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "view", "--no-open"])

    output = tmp_path / ".echelon" / "runtime" / "graph" / "workspace.html"
    assert result.exit_code == 1
    assert output.is_file()
    assert '"initial_lens": "portfolio"' in output.read_text(encoding="utf-8")


@pytest.mark.unit
def test_workspace_export_defaults_to_dot_stdout_and_preserves_audit_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _persisted_workspace_graph(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.audit_workspace_graph",
        lambda root: _Report("warn"),
    )
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda *args, **kwargs: pytest.fail("export must not mine memory"),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "export"])

    assert result.exit_code == 0
    assert result.output.startswith('digraph "demo" {')
    assert '"workspace:current"' in result.output
