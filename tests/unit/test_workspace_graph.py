from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from echelon.spec_graph import GraphEdge, GraphNode, SpecArtifactGraph, render_spec_graph
from echelon.workspace_graph import (
    WorkspaceGraphError,
    build_workspace_graph,
    discover_canonical_spec_dirs,
    load_workspace_graph_document,
    render_workspace_graph,
    workspace_graph_path,
    write_workspace_graph,
)


def _write_config(root: Path, *, sources: object = None) -> None:
    config = root / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        yaml.safe_dump(
            {
                "workspace": {"git_role": "orchestration"},
                "sources": [] if sources is None else sources,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _spec_dir(root: Path, spec_id: str, *, targets: object = None) -> Path:
    spec_dir = root / "specs" / spec_id
    spec_dir.mkdir(parents=True)
    target_frontmatter = ""
    if targets is not None:
        target_frontmatter = yaml.safe_dump({"targets": targets}, sort_keys=False)
    spec_dir.joinpath("spec.md").write_text(
        f"---\n{target_frontmatter}---\n# {spec_id}\n",
        encoding="utf-8",
    )
    return spec_dir


def _member_graph(
    spec_id: str,
    *,
    artifact_path: str = "re/workspace/overview.md",
    drawer_id: str = "shared-re-drawer",
    artifact_role: str = "published-re",
    extra_nodes: tuple[GraphNode, ...] = (),
    extra_edges: tuple[GraphEdge, ...] = (),
) -> SpecArtifactGraph:
    artifact_id = f"artifact:{spec_id}:{artifact_path}"
    drawer_node_id = f"drawer:{spec_id}:{drawer_id}"
    return SpecArtifactGraph(
        spec_id=spec_id,
        generator_version="test",
        inputs=(),
        nodes=(
            GraphNode(
                f"spec:{spec_id}",
                "Spec",
                {"spec_id": spec_id, "path": f"specs/{spec_id}"},
            ),
            GraphNode(
                artifact_id,
                "Artifact",
                {"path": artifact_path, "role": artifact_role},
            ),
            GraphNode(
                drawer_node_id,
                "MemPalaceDrawer",
                {"drawer_id": drawer_id, "room": "published-re"},
            ),
            *extra_nodes,
        ),
        edges=(
            GraphEdge(artifact_id, "STORED_AS", drawer_node_id, {}),
            *extra_edges,
        ),
        memory_receipts=(),
    )


def _write_member_graph(spec_dir: Path, graph: SpecArtifactGraph) -> None:
    spec_dir.joinpath("spec-artifact-graph.json").write_bytes(render_spec_graph(graph))


def _pass_audit(spec_id: str, status: str = "pass") -> SimpleNamespace:
    return SimpleNamespace(
        spec_id=spec_id,
        status=status,
        to_dict=lambda: {"schema_version": 1, "spec_id": spec_id, "status": status},
    )


@pytest.mark.unit
def test_discovery_is_direct_sorted_and_ignores_symlinks(tmp_path: Path) -> None:
    _write_config(tmp_path)
    beta = _spec_dir(tmp_path, "002-beta")
    alpha = _spec_dir(tmp_path, "001-alpha")
    _spec_dir(alpha, "runs/003-run-local")
    link = tmp_path / "specs" / "003-link"
    link.symlink_to(beta, target_is_directory=True)

    assert [path.name for path in discover_canonical_spec_dirs(tmp_path)] == [
        "001-alpha",
        "002-beta",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "canonical workspace config is missing"),
        ("[not-an-object]", "canonical workspace config must be an object"),
        ("workspace: {}\nsources: invalid\n", "workspace sources must be a list"),
    ],
)
def test_discovery_requires_valid_canonical_config(
    tmp_path: Path,
    config: str | None,
    message: str,
) -> None:
    _spec_dir(tmp_path, "001-alpha")
    if config is not None:
        path = tmp_path / ".echelon" / "config.yml"
        path.parent.mkdir(parents=True)
        path.write_text(config, encoding="utf-8")

    with pytest.raises(WorkspaceGraphError, match=message):
        build_workspace_graph(tmp_path)


@pytest.mark.unit
def test_build_rejects_empty_canonical_spec_set(tmp_path: Path) -> None:
    _write_config(tmp_path)

    with pytest.raises(WorkspaceGraphError, match="no canonical spec directories"):
        build_workspace_graph(tmp_path)


@pytest.mark.unit
def test_rendering_is_deterministic_and_workspace_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    beta = _spec_dir(tmp_path, "002-beta")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    _write_member_graph(beta, _member_graph("002-beta"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit(Path(selector).name),
    )

    first = build_workspace_graph(tmp_path)
    second = build_workspace_graph(tmp_path)

    assert render_workspace_graph(first.graph) == render_workspace_graph(second.graph)
    assert first.graph.to_dict()["scope"] == "workspace"
    assert first.graph.to_dict()["nodes"][0]["id"] == "artifact:re/workspace/overview.md"
    assert list(first.graph.to_dict()) == [
        "schema_version",
        "generator_version",
        "scope",
        "workspace_name",
        "source_set_digest",
        "member_state_digest",
        "members",
        "inputs",
        "nodes",
        "edges",
    ]


@pytest.mark.unit
def test_member_audits_control_partial_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    beta = _spec_dir(tmp_path, "002-beta")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    _write_member_graph(beta, _member_graph("002-beta"))
    statuses = {"001-alpha": "warn", "002-beta": "fail"}
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit(Path(selector).name, statuses[Path(selector).name]),
    )

    result = build_workspace_graph(tmp_path)
    nodes = {node.id: node for node in result.graph.nodes}
    included = nodes["spec:001-alpha"]
    excluded = nodes["spec:002-beta"]

    assert included.properties["composition_status"] == "included"
    assert excluded.properties == {
        "spec_id": "002-beta",
        "composition_status": "excluded",
        "member_audit_status": "fail",
        "exclusion_reason": "member_graph_stale",
    }
    assert [member.included for member in result.graph.members] == [True, False]
    assert result.issues[0].subject_id == "spec:002-beta"


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        b"{not-json}",
        json.dumps({"schema_version": 2, "nodes": [], "edges": []}).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "other-spec",
                "nodes": [],
                "edges": [],
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "001-alpha",
                "nodes": [
                    {
                        "id": "spec:001-alpha",
                        "type": "Spec",
                        "properties": {"spec_id": "other-spec"},
                    }
                ],
                "edges": [],
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "001-alpha",
                "nodes": [
                    {
                        "id": "spec:001-alpha",
                        "type": "Spec",
                        "properties": {"spec_id": "001-alpha"},
                    },
                    {
                        "id": "artifact:001-alpha:re/workspace/overview.md",
                        "type": "Artifact",
                        "properties": {"path": "re/workspace/overview.md"},
                    },
                    {
                        "id": "artifact:001-alpha:re/workspace/overview.md",
                        "type": "Artifact",
                        "properties": {"path": "re/workspace/overview.md"},
                    },
                ],
                "edges": [],
            }
        ).encode(),
    ],
)
def test_unhealthy_member_graphs_become_placeholders_without_rebuilding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    alpha.joinpath("spec-artifact-graph.json").write_bytes(payload)
    monkeypatch.setattr(
        "echelon.workspace_graph.build_spec_graph",
        lambda *args: pytest.fail("workspace composition must not rebuild members"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit("001-alpha", "unavailable"),
    )

    result = build_workspace_graph(tmp_path)

    member = result.graph.members[0]
    assert member.included is False
    assert next(node for node in result.graph.nodes if node.id == "spec:001-alpha") == GraphNode(
        "spec:001-alpha",
        "Spec",
        {
            "spec_id": "001-alpha",
            "composition_status": "excluded",
            "member_audit_status": "unavailable",
            "exclusion_reason": "member_graph_invalid",
        },
    )
    assert result.issues[0].subject_id == "spec:001-alpha"


@pytest.mark.unit
def test_merges_shared_identity_and_adds_workspace_relationships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, sources=[{"id": "app", "path": "apps/app"}])
    alpha = _spec_dir(tmp_path, "001-alpha", targets=[{"id": "app", "path": "wrong"}])
    beta = _spec_dir(tmp_path, "002-beta", targets=[{"path": "apps/app"}])
    beta.joinpath("spec.md").write_text(
        "---\n"
        "targets:\n"
        "  - path: apps/app\n"
        "supersedes: 001-alpha\n"
        "---\n"
        "# 002-beta\n",
        encoding="utf-8",
    )
    _write_member_graph(alpha, _member_graph("001-alpha"))
    _write_member_graph(beta, _member_graph("002-beta"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit(Path(selector).name),
    )

    result = build_workspace_graph(tmp_path)
    ids = [node.id for node in result.graph.nodes]
    nodes = {node.id: node for node in result.graph.nodes}
    edges = {(edge.source, edge.type, edge.target): edge for edge in result.graph.edges}

    assert ids.count("artifact:re/workspace/overview.md") == 1
    assert ids.count("drawer:shared-re-drawer") == 1
    assert nodes["artifact:re/workspace/overview.md"].properties["member_specs"] == [
        "001-alpha",
        "002-beta",
    ]
    shared_edge = edges[("artifact:re/workspace/overview.md", "STORED_AS", "drawer:shared-re-drawer")]
    assert shared_edge.properties["member_specs"] == ["001-alpha", "002-beta"]
    assert ("workspace:current", "CONTAINS_SPEC", "spec:001-alpha") in edges
    assert ("workspace:current", "CONTAINS_SPEC", "spec:002-beta") in edges
    assert ("spec:001-alpha", "TARGETS", "source:app") in edges
    assert ("spec:002-beta", "TARGETS", "source:app") in edges
    assert ("spec:002-beta", "SUPERSEDES", "spec:001-alpha") in edges


@pytest.mark.unit
def test_reports_unresolved_workspace_relationships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, sources=[{"id": "app", "path": "apps/app"}])
    alpha = _spec_dir(tmp_path, "001-alpha", targets=[{"id": "missing", "path": "none"}])
    alpha.joinpath("spec.md").write_text(
        "---\ntargets:\n  - id: missing\n    path: none\nsupersedes: 000-old\n---\n# alpha\n",
        encoding="utf-8",
    )
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit("001-alpha"),
    )

    result = build_workspace_graph(tmp_path)

    assert [issue.code for issue in result.issues] == [
        "superseded_spec_missing",
        "target_unresolved",
    ]
    assert all(issue.severity == "warning" for issue in result.issues)


@pytest.mark.unit
def test_rejects_conflicting_normalized_properties_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    beta = _spec_dir(tmp_path, "002-beta")
    _write_member_graph(alpha, _member_graph("001-alpha", artifact_role="published-re"))
    _write_member_graph(beta, _member_graph("002-beta", artifact_role="other"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit(Path(selector).name),
    )

    with pytest.raises(WorkspaceGraphError, match="conflicting normalized node properties"):
        build_workspace_graph(tmp_path)


@pytest.mark.unit
def test_write_is_atomic_and_preserves_previous_bytes_on_structural_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit("001-alpha"),
    )
    graph = build_workspace_graph(tmp_path).graph
    path = write_workspace_graph(graph, tmp_path)
    previous = path.read_bytes()
    replaced: list[tuple[Path, Path]] = []
    real_replace = __import__("os").replace

    def observe_replace(source: Path, target: Path) -> None:
        replaced.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr("echelon.workspace_graph.os.replace", observe_replace)
    write_workspace_graph(graph, tmp_path)
    assert replaced and replaced[0][1] == workspace_graph_path(tmp_path)

    beta = _spec_dir(tmp_path, "002-beta")
    _write_member_graph(beta, _member_graph("002-beta", artifact_role="conflict"))
    with pytest.raises(WorkspaceGraphError):
        build_workspace_graph(tmp_path)
    assert path.read_bytes() == previous
    assert load_workspace_graph_document(tmp_path)["scope"] == "workspace"


@pytest.mark.unit
def test_write_preserves_the_publication_failure_when_temp_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _pass_audit("001-alpha"),
    )
    graph = build_workspace_graph(tmp_path).graph
    cleanup_attempted: list[Path] = []

    def failed_replace(source: Path, target: Path) -> None:
        raise OSError("publication failed")

    def failed_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        cleanup_attempted.append(path)
        raise OSError("cleanup failed")

    monkeypatch.setattr("echelon.workspace_graph.os.replace", failed_replace)
    monkeypatch.setattr(Path, "unlink", failed_cleanup)

    with pytest.raises(OSError, match="publication failed"):
        write_workspace_graph(graph, tmp_path)
    assert cleanup_attempted
