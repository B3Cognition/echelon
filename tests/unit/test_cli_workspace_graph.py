from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import GraphEdge, GraphInput, GraphNode
from echelon.workspace_graph import (
    WorkspaceArtifactGraph,
    WorkspaceGraphMember,
    workspace_graph_path,
    write_workspace_graph,
)


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


def _forbid_upstream_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    for target in (
        "echelon.mempalace_requirements.mine_spec_requirements",
        "echelon.mempalace_re.mine_re_memory",
        "echelon.mempalace_spec_evidence.mine_spec_evidence_memory",
        "echelon.spec_graph.write_spec_graph",
    ):
        def forbidden(*args: object, _target: str = target, **kwargs: object) -> None:
            pytest.fail(f"read-only command invoked {_target}")

        monkeypatch.setattr(
            target,
            forbidden,
        )


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
    _forbid_upstream_mutations(monkeypatch)
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
    _forbid_upstream_mutations(monkeypatch)
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
    graph = WorkspaceArtifactGraph(
        workspace_name="demo",
        generator_version="test",
        members=(
            WorkspaceGraphMember(
                spec_id="001-demo",
                graph_path="specs/001-demo/spec-artifact-graph.json",
                graph_hash="sha256:graph",
                member_source_set_digest="sha256:source",
                member_memory_state_digest="sha256:memory",
                audit_hash="sha256:audit",
                audit_status="pass",
                included=True,
            ),
        ),
        inputs=(
            GraphInput(
                path=".echelon/config.yml",
                hash="sha256:config",
                role="workspace_config",
                required=True,
            ),
        ),
        nodes=(
            GraphNode("workspace:current", "Workspace", {}),
            GraphNode(
                "spec:001-demo",
                "Spec",
                {
                    "spec_id": "001-demo",
                    "composition_status": "included",
                    "member_audit_status": "pass",
                },
            ),
        ),
        edges=(
            GraphEdge(
                "workspace:current",
                "CONTAINS_SPEC",
                "spec:001-demo",
                {},
            ),
        ),
    )
    write_workspace_graph(graph, tmp_path)
    return workspace_graph_path(tmp_path)


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
    _forbid_upstream_mutations(monkeypatch)
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
    _forbid_upstream_mutations(monkeypatch)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "export"])

    assert result.exit_code == 0
    assert result.output.startswith('digraph "demo" {')
    assert '"workspace:current"' in result.output


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.pop("members"),
        lambda payload: payload.pop("inputs"),
        lambda payload: payload.pop("source_set_digest"),
        lambda payload: payload.pop("member_state_digest"),
        lambda payload: payload.update({"members": [{}]}),
        lambda payload: payload.update({"inputs": [{}]}),
        lambda payload: payload.update({"source_set_digest": "sha256:invalid"}),
    ),
)
def test_workspace_view_and_export_reject_invalid_full_contract_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    graph_path = _persisted_workspace_graph(tmp_path)
    payload = __import__("json").loads(graph_path.read_text(encoding="utf-8"))
    mutate(payload)
    graph_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _forbid_upstream_mutations(monkeypatch)
    from echelon.cli_app import app

    view_output = tmp_path / "reports" / "workspace.html"
    export_output = tmp_path / "reports" / "workspace.dot"
    view = CliRunner().invoke(
        app,
        ["graph", "workspace", "view", "--no-open", "--output", str(view_output)],
    )
    exported = CliRunner().invoke(
        app,
        ["graph", "workspace", "export", "--output", str(export_output)],
    )

    assert view.exit_code == 2
    assert exported.exit_code == 2
    assert not view_output.exists()
    assert not export_output.exists()
    assert "digraph" not in exported.output


@pytest.mark.unit
def test_workspace_view_and_export_reject_missing_persisted_graph_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _forbid_upstream_mutations(monkeypatch)
    from echelon.cli_app import app

    view_output = tmp_path / "reports" / "workspace.html"
    export_output = tmp_path / "reports" / "workspace.dot"
    view = CliRunner().invoke(
        app,
        ["graph", "workspace", "view", "--no-open", "--output", str(view_output)],
    )
    exported = CliRunner().invoke(
        app,
        ["graph", "workspace", "export", "--output", str(export_output)],
    )

    assert view.exit_code == 2
    assert exported.exit_code == 2
    assert not view_output.exists()
    assert not export_output.exists()
    assert "digraph" not in exported.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "output_name"),
    (
        (("view", "--no-open"), "workspace.html"),
        (("export",), "workspace.dot"),
    ),
)
def test_workspace_view_and_export_preserve_existing_output_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: tuple[str, ...],
    output_name: str,
) -> None:
    _persisted_workspace_graph(tmp_path)
    output = tmp_path / "reports" / output_name
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.audit_workspace_graph",
        lambda root: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph.os.replace",
        lambda source, target: (_ for _ in ()).throw(OSError("replace failed")),
    )
    _forbid_upstream_mutations(monkeypatch)
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["graph", "workspace", *command, "--output", str(output)],
    )

    assert result.exit_code == 2
    assert output.read_bytes() == b"previous"
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "open_browser",
    (
        lambda url: False,
        lambda url: (_ for _ in ()).throw(__import__("webbrowser").Error("blocked")),
    ),
)
def test_workspace_view_warns_when_browser_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    open_browser,
) -> None:
    _persisted_workspace_graph(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.audit_workspace_graph",
        lambda root: _Report("warn"),
    )
    monkeypatch.setattr("webbrowser.open", open_browser)
    _forbid_upstream_mutations(monkeypatch)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["graph", "workspace", "view"])

    assert result.exit_code == 0
    assert "warning: workspace graph viewer was not opened" in result.stderr
