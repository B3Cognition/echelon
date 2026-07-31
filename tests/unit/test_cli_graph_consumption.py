from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable

import pytest
from typer.testing import CliRunner

from echelon.graph_read import GraphReadError, GraphReadModel
from echelon.graph_traversal import GraphResult
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport


REQ = "req:905-import-prose:FR-012"
ARTIFACT = "artifact:specs/905-import-prose/spec.md"
TASK = "task:905-import-prose:T-001"


def _model(
    *, status: str = "pass", findings: tuple[GraphFinding, ...] = ()
) -> GraphReadModel:
    nodes = {
        node_id: {"id": node_id, "type": "TestNode", "properties": {}}
        for node_id in (REQ, ARTIFACT, TASK)
    }
    return GraphReadModel(
        scope="workspace",
        graph_hash="sha256:persisted",
        document={},
        audit=SpecGraphAuditReport(
            schema_version=1,
            spec_id="905-import-prose",
            graph_hash="sha256:live",
            status=status,
            findings=findings,
        ),
        nodes_by_id=MappingProxyType(nodes),
        outgoing=MappingProxyType({node_id: () for node_id in nodes}),
        incoming=MappingProxyType({node_id: () for node_id in nodes}),
    )


def _result() -> GraphResult:
    return GraphResult((), (), ())


def _ambiguous_model() -> GraphReadModel:
    model = _model()
    nodes = dict(model.nodes_by_id)
    nodes["req:other:FR-012"] = {
        "id": "req:other:FR-012",
        "type": "TestNode",
        "properties": {},
    }
    return GraphReadModel(
        scope=model.scope,
        graph_hash=model.graph_hash,
        document=model.document,
        audit=model.audit,
        nodes_by_id=MappingProxyType(nodes),
        outgoing=MappingProxyType({node_id: () for node_id in nodes}),
        incoming=MappingProxyType({node_id: () for node_id in nodes}),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "entrypoint", "expected"),
    [
        (
            ["query", "which requirements depend on import validation?", "--json"],
            "query_graph",
            ("which requirements depend on import validation?", None, 2, 20),
        ),
        (["explain", REQ, "--json"], "explain_node", (REQ, 50)),
        (["path", REQ, ARTIFACT, "--json"], "shortest_path", (REQ, ARTIFACT, 8)),
        (["neighbors", TASK, "--json"], "neighbors", (TASK, "both", None, 50)),
        (["impact", REQ, "--json"], "impact", (REQ, 4, False)),
    ],
)
def test_graph_consumption_commands_forward_defaults_and_emit_json(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    entrypoint: str,
    expected: tuple[object, ...],
) -> None:
    import echelon.graph_read as graph_read
    import echelon.graph_traversal as graph_traversal
    from echelon.cli_app import app

    model = _model()
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(graph_read, "load_graph", lambda root, spec=None: model)

    def traversal(*args: object, **kwargs: object) -> GraphResult:
        calls.append((*args[1:], *kwargs.values()))
        return _result()

    monkeypatch.setattr(graph_traversal, entrypoint, traversal)

    response = CliRunner().invoke(app, ["graph", *argv])

    assert response.exit_code == 0
    assert calls == [expected]
    assert json.loads(response.output)["command"] == argv[0]


@pytest.mark.unit
def test_graph_consumption_loads_default_workspace_or_requested_spec_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read
    import echelon.graph_traversal as graph_traversal
    from echelon.cli_app import app

    model = _model()
    loaded: list[tuple[Path, str | None]] = []
    monkeypatch.setattr(
        graph_read,
        "load_graph",
        lambda root, spec=None: loaded.append((root, spec)) or model,
    )
    monkeypatch.setattr(graph_traversal, "query_graph", lambda *args, **kwargs: _result())

    runner = CliRunner()
    default = runner.invoke(app, ["graph", "query", "imports", "--json"])
    selected = runner.invoke(
        app,
        ["graph", "query", "imports", "--spec", "905-import-prose", "--json"],
    )

    assert default.exit_code == 0
    assert selected.exit_code == 0
    assert loaded == [(Path.cwd(), None), (Path.cwd(), "905-import-prose")]


@pytest.mark.unit
def test_graph_consumption_empty_healthy_result_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read
    import echelon.graph_traversal as graph_traversal
    from echelon.cli_app import app

    monkeypatch.setattr(graph_read, "load_graph", lambda *args, **kwargs: _model())
    monkeypatch.setattr(graph_traversal, "query_graph", lambda *args, **kwargs: _result())

    response = CliRunner().invoke(app, ["graph", "query", "missing", "--json"])

    assert response.exit_code == 0
    assert json.loads(response.output)["nodes"] == []


@pytest.mark.unit
def test_graph_consumption_prints_usable_audit_warning_before_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read
    import echelon.graph_traversal as graph_traversal
    from echelon.cli_app import app

    finding = GraphFinding("warning", "stale", "Graph sources changed.")
    monkeypatch.setattr(
        graph_read,
        "load_graph",
        lambda *args, **kwargs: _model(status="warn", findings=(finding,)),
    )
    monkeypatch.setattr(graph_traversal, "query_graph", lambda *args, **kwargs: _result())

    response = CliRunner().invoke(app, ["graph", "query", "imports"])

    assert response.exit_code == 1
    assert "Warning [stale]: Graph sources changed." in response.output
    assert "Nodes:" in response.output


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["query", "imports"],
        ["neighbors", "unknown"],
        ["neighbors", TASK, "--direction", "sideways"],
        ["query", "imports", "--limit", "0"],
    ],
)
def test_graph_consumption_errors_exit_two_without_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    import echelon.graph_read as graph_read
    from echelon.cli_app import app

    if argv == ["query", "imports"]:
        monkeypatch.setattr(
            graph_read,
            "load_graph",
            lambda *args, **kwargs: (_ for _ in ()).throw(GraphReadError("graph missing")),
        )
    else:
        monkeypatch.setattr(graph_read, "load_graph", lambda *args, **kwargs: _model())

    response = CliRunner().invoke(app, ["graph", *argv])

    assert response.exit_code == 2
    assert '"schema_version"' not in response.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "entrypoint"),
    [
        (["query", "imports", "--json"], "query_graph"),
        (["explain", REQ, "--json"], "explain_node"),
        (["path", REQ, ARTIFACT, "--json"], "shortest_path"),
        (["neighbors", TASK, "--json"], "neighbors"),
        (["impact", REQ, "--json"], "impact"),
    ],
)
def test_graph_consumption_never_builds_refreshes_mines_or_writes(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    entrypoint: str,
) -> None:
    import echelon.graph_read as graph_read
    import echelon.graph_traversal as graph_traversal
    import echelon.mempalace_requirements as mempalace_requirements
    import echelon.spec_graph as spec_graph
    import echelon.spec_graph_audit as spec_graph_audit
    import echelon.workspace_graph as workspace_graph
    import echelon.workspace_graph_audit as workspace_graph_audit
    import echelon.workspace_graph_refresh as workspace_graph_refresh
    from echelon.cli_app import app

    def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail("graph consumption command performed a forbidden side effect")

    for module, names in (
        (spec_graph, ("build_spec_graph", "write_spec_graph")),
        (spec_graph_audit, ("write_spec_graph_audit",)),
        (workspace_graph, ("build_workspace_graph", "write_workspace_graph", "write_workspace_graph_bytes")),
        (workspace_graph_audit, ("write_workspace_graph_audit",)),
        (workspace_graph_refresh, ("refresh_workspace_graph",)),
        (mempalace_requirements, ("mine_spec_requirements",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(graph_read, "load_graph", lambda *args, **kwargs: _model())
    monkeypatch.setattr(graph_traversal, entrypoint, lambda *args, **kwargs: _result())

    response = CliRunner().invoke(app, ["graph", *argv])

    assert response.exit_code == 0
    assert json.loads(response.output)["command"] == argv[0]


@pytest.mark.unit
def test_graph_consumption_rejects_ambiguous_node_without_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read
    from echelon.cli_app import app

    monkeypatch.setattr(graph_read, "load_graph", lambda *args, **kwargs: _ambiguous_model())

    response = CliRunner().invoke(app, ["graph", "explain", "FR-012", "--json"])

    assert response.exit_code == 2
    assert "ambiguous graph node selector" in response.output
    assert '"schema_version"' not in response.output


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["query", "imports", "--depth", "0"],
        ["query", "imports", "--limit", "0"],
        ["explain", REQ, "--limit", "0"],
        ["path", REQ, ARTIFACT, "--max-hops", "0"],
        ["neighbors", TASK, "--limit", "0"],
        ["impact", REQ, "--max-depth", "0"],
    ],
)
def test_graph_consumption_rejects_nonpositive_bounds_without_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    import echelon.graph_read as graph_read
    from echelon.cli_app import app

    monkeypatch.setattr(graph_read, "load_graph", lambda *args, **kwargs: _model())

    response = CliRunner().invoke(app, ["graph", *argv])

    assert response.exit_code == 2
    assert '"schema_version"' not in response.output
