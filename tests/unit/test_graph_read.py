from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from echelon.spec_graph import GRAPH_FILENAME
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport
from echelon.workspace_graph_audit import (
    WorkspaceGraphAuditReport,
    WorkspaceGraphFinding,
)


def _document(*, scope: str = "spec") -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "generator_version": "test",
        "nodes": [
            {"id": "task:905:T-002", "type": "Task", "properties": {"task_id": "T-002"}},
            {
                "id": "artifact:905:output",
                "type": "Artifact",
                "properties": {"path": "out.json", "publication_id": "PUBLISHED-001"},
            },
            {"id": "req:905:FR-012", "type": "Requirement", "properties": {"requirement_id": "FR-012"}},
            {"id": "spec:905", "type": "Spec", "properties": {"spec_id": "905"}},
            {"id": "task:905:T-001", "type": "Task", "properties": {"task_id": "T-001"}},
            {"id": "artifact:905:input", "type": "Artifact", "properties": {"path": "in.json"}},
        ],
        "edges": [
            {"source": "task:905:T-002", "type": "IMPLEMENTS", "target": "req:905:FR-012", "properties": {}},
            {"source": "req:905:FR-012", "type": "DERIVED_FROM", "target": "artifact:905:input", "properties": {}},
            {"source": "spec:905", "type": "HAS_REQUIREMENT", "target": "req:905:FR-012", "properties": {}},
            {"source": "req:905:FR-012", "type": "VERIFIED_BY", "target": "artifact:905:output", "properties": {}},
            {"source": "task:905:T-001", "type": "IMPLEMENTS", "target": "req:905:FR-012", "properties": {}},
        ],
    }
    if scope == "workspace":
        document.update({"scope": "workspace", "workspace_name": "demo"})
    else:
        document["spec_id"] = "905-demo"
    return document


def _write_graph(path: Path, document: dict[str, object]) -> bytes:
    data = (json.dumps(document, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _spec_audit(*, status: str = "pass", graph_hash: str = "sha256:live") -> SpecGraphAuditReport:
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id="905-demo",
        graph_hash=graph_hash,
        status=status,
        findings=(
            GraphFinding("warning", "stale", "The audit is deliberately live.")
        )
        if status != "pass"
        else (),
    )


def _workspace_audit(
    *, status: str = "warn", graph_hash: str = "sha256:live"
) -> WorkspaceGraphAuditReport:
    return WorkspaceGraphAuditReport(
        schema_version=1,
        workspace_name="demo",
        graph_hash=graph_hash,
        status=status,
        members=(),
        findings=(
            WorkspaceGraphFinding("warning", "stale", "The audit is deliberately live.")
        ),
    )


def _forbidden_side_effect(name: str):
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"graph reader called forbidden side effect: {name}")

    return fail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda document: document["nodes"].append(dict(document["nodes"][0])), "duplicate graph node id"),
        (lambda document: document["edges"].append(dict(document["edges"][0])), "duplicate graph edge"),
        (lambda document: document["nodes"][0].update(properties=[]), "node properties are invalid"),
        (lambda document: document["edges"][0].update(target="missing"), "missing endpoint"),
    ],
)
def test_read_graph_document_rejects_invalid_graph_structure(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    from echelon.graph_read import GraphReadError, read_graph_document

    document = _document()
    mutate(document)  # type: ignore[operator]
    path = tmp_path / GRAPH_FILENAME
    _write_graph(path, document)

    with pytest.raises(GraphReadError, match=message):
        read_graph_document(path)


@pytest.mark.unit
def test_load_graph_builds_deterministic_immutable_edge_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read

    spec_dir = tmp_path / "specs" / "905-demo"
    graph_path = spec_dir / GRAPH_FILENAME
    _write_graph(graph_path, _document())
    monkeypatch.setattr(graph_read, "resolve_spec_dir", lambda root, selector: spec_dir)
    monkeypatch.setattr(graph_read, "audit_spec_graph", lambda root, selector: _spec_audit())

    model = graph_read.load_graph(tmp_path, "905")

    assert list(model.nodes_by_id) == [
        "artifact:905:input",
        "artifact:905:output",
        "req:905:FR-012",
        "spec:905",
        "task:905:T-001",
        "task:905:T-002",
    ]
    assert [edge["type"] for edge in model.outgoing["req:905:FR-012"]] == [
        "DERIVED_FROM",
        "VERIFIED_BY",
    ]
    assert [edge["source"] for edge in model.incoming["req:905:FR-012"]] == [
        "spec:905",
        "task:905:T-001",
        "task:905:T-002",
    ]
    assert isinstance(model.outgoing["req:905:FR-012"], tuple)
    with pytest.raises(TypeError):
        model.outgoing["req:905:FR-012"] += ()


@pytest.mark.unit
def test_load_graph_uses_persisted_workspace_graph_and_live_workspace_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read

    graph_path = tmp_path / ".echelon" / "runtime" / "graph" / "workspace-artifact-graph.json"
    data = _write_graph(graph_path, _document(scope="workspace"))
    audit = _workspace_audit()
    calls: list[Path] = []
    monkeypatch.setattr(graph_read, "workspace_graph_path", lambda root: graph_path)
    monkeypatch.setattr(
        graph_read,
        "audit_workspace_graph",
        lambda root: calls.append(root) or audit,
    )

    model = graph_read.load_graph(tmp_path)

    assert calls == [tmp_path]
    assert model.scope == "workspace"
    assert model.audit is audit
    assert model.graph_hash == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert model.graph_hash != audit.graph_hash


@pytest.mark.unit
def test_load_graph_uses_canonical_spec_graph_and_live_spec_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read

    spec_dir = tmp_path / "specs" / "905-demo"
    data = _write_graph(spec_dir / GRAPH_FILENAME, _document())
    audit = _spec_audit(status="warn")
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(graph_read, "resolve_spec_dir", lambda root, selector: spec_dir)
    monkeypatch.setattr(
        graph_read,
        "audit_spec_graph",
        lambda root, selector: calls.append((root, selector)) or audit,
    )

    model = graph_read.load_graph(tmp_path, "905")

    assert calls == [(tmp_path, "905")]
    assert model.scope == "spec"
    assert model.audit is audit
    assert model.graph_hash == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert model.graph_hash != audit.graph_hash


@pytest.mark.unit
def test_load_graph_never_builds_refreshes_mines_or_writes_persisted_graphs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read
    import echelon.mempalace_requirements as mempalace_requirements
    import echelon.spec_graph as spec_graph
    import echelon.spec_graph_audit as spec_graph_audit
    import echelon.workspace_graph as workspace_graph
    import echelon.workspace_graph_audit as workspace_graph_audit
    import echelon.workspace_graph_refresh as workspace_graph_refresh

    spec_dir = tmp_path / "specs" / "905-demo"
    workspace_path = (
        tmp_path
        / ".echelon"
        / "runtime"
        / "graph"
        / "workspace-artifact-graph.json"
    )
    _write_graph(spec_dir / GRAPH_FILENAME, _document())
    _write_graph(workspace_path, _document(scope="workspace"))

    forbidden = (
        (spec_graph, "build_spec_graph"),
        (spec_graph, "write_spec_graph"),
        (workspace_graph, "build_workspace_graph"),
        (workspace_graph, "write_workspace_graph"),
        (workspace_graph, "write_workspace_graph_bytes"),
        (workspace_graph_refresh, "refresh_workspace_graph"),
        (mempalace_requirements, "mine_spec_requirements"),
        (spec_graph_audit, "write_spec_graph_audit"),
        (workspace_graph_audit, "write_workspace_graph_audit"),
    )
    for module, name in forbidden:
        sentinel = _forbidden_side_effect(f"{module.__name__}.{name}")
        monkeypatch.setattr(module, name, sentinel)
        monkeypatch.setattr(graph_read, name, sentinel, raising=False)

    monkeypatch.setattr(graph_read, "workspace_graph_path", lambda root: workspace_path)
    monkeypatch.setattr(graph_read, "resolve_spec_dir", lambda root, selector: spec_dir)
    monkeypatch.setattr(graph_read, "audit_workspace_graph", lambda root: _workspace_audit())
    monkeypatch.setattr(graph_read, "audit_spec_graph", lambda root, selector: _spec_audit())

    workspace_model = graph_read.load_graph(tmp_path)
    spec_model = graph_read.load_graph(tmp_path, "905")

    assert workspace_model.scope == "workspace"
    assert spec_model.scope == "spec"


@pytest.mark.unit
def test_graph_read_exit_code_requires_clean_passing_audit() -> None:
    from echelon.graph_read import GraphReadModel, graph_read_exit_code

    passing = GraphReadModel("spec", "sha256:test", {}, _spec_audit(), {}, {}, {})
    passing_with_finding = GraphReadModel(
        "spec",
        "sha256:test",
        {},
        SpecGraphAuditReport(
            schema_version=1,
            spec_id="905-demo",
            graph_hash="sha256:live",
            status="pass",
            findings=(GraphFinding("warning", "live", "Still not clean."),),
        ),
        {},
        {},
        {},
    )
    warning = GraphReadModel(
        "spec", "sha256:test", {}, _spec_audit(status="warn"), {}, {}, {}
    )

    assert graph_read_exit_code(passing) == 0
    assert graph_read_exit_code(passing_with_finding) == 1
    assert graph_read_exit_code(warning) == 1


@pytest.mark.unit
def test_resolve_node_id_supports_exact_shorthand_and_identity_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read

    spec_dir = tmp_path / "specs" / "905-demo"
    _write_graph(spec_dir / GRAPH_FILENAME, _document())
    monkeypatch.setattr(graph_read, "resolve_spec_dir", lambda root, selector: spec_dir)
    monkeypatch.setattr(graph_read, "audit_spec_graph", lambda root, selector: _spec_audit())
    model = graph_read.load_graph(tmp_path, "905")

    assert graph_read.resolve_node_id(model, "req:905:FR-012") == "req:905:FR-012"
    assert graph_read.resolve_node_id(model, "fr-012") == "req:905:FR-012"
    assert graph_read.resolve_node_id(model, "t-001") == "task:905:T-001"
    assert graph_read.resolve_node_id(model, "published-001") == "artifact:905:output"


@pytest.mark.unit
def test_resolve_node_id_rejects_unknown_blank_and_ambiguous_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.graph_read as graph_read

    document = _document(scope="workspace")
    document["nodes"].append(
        {"id": "req:906:FR-012", "type": "Requirement", "properties": {"requirement_id": "FR-012"}}
    )
    _write_graph(
        tmp_path / ".echelon" / "runtime" / "graph" / "workspace-artifact-graph.json",
        document,
    )
    monkeypatch.setattr(graph_read, "audit_workspace_graph", lambda root: _workspace_audit())
    model = graph_read.load_graph(tmp_path)

    assert graph_read.resolve_node_id(model, "req:905:FR-012") == "req:905:FR-012"
    with pytest.raises(graph_read.NodeResolutionError, match="selector must not be blank"):
        graph_read.resolve_node_id(model, "  ")
    with pytest.raises(graph_read.NodeResolutionError, match="unknown graph node selector: NOPE"):
        graph_read.resolve_node_id(model, "NOPE")
    with pytest.raises(
        graph_read.NodeResolutionError,
        match=r"ambiguous graph node selector 'FR-012': req:905:FR-012, req:906:FR-012",
    ):
        graph_read.resolve_node_id(model, "FR-012")


@pytest.mark.unit
def test_resolve_node_id_caps_ambiguous_candidate_list() -> None:
    from echelon.graph_read import GraphReadModel, NodeResolutionError, resolve_node_id

    nodes_by_id = {
        f"req:{number:03d}:FR-012": {
            "id": f"req:{number:03d}:FR-012",
            "type": "Requirement",
            "properties": {},
        }
        for number in range(12)
    }
    model = GraphReadModel("workspace", "sha256:test", {}, _workspace_audit(), nodes_by_id, {}, {})

    with pytest.raises(NodeResolutionError) as exc_info:
        resolve_node_id(model, "FR-012")

    assert str(exc_info.value).endswith(
        "req:000:FR-012, req:001:FR-012, req:002:FR-012, req:003:FR-012, "
        "req:004:FR-012, req:005:FR-012, req:006:FR-012, req:007:FR-012, "
        "req:008:FR-012, req:009:FR-012, ... (+2 more)"
    )
