from __future__ import annotations

import hashlib
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
    write_workspace_graph_bytes,
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
    artifact_properties: dict[str, object] | None = None,
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
                {
                    "path": artifact_path,
                    "role": artifact_role,
                    **(artifact_properties or {}),
                },
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


def _pass_audit(
    spec_id: str,
    status: str = "pass",
    graph_hash: str | None = None,
    finding_codes: tuple[str, ...] = (),
) -> SimpleNamespace:
    findings = tuple(
        SimpleNamespace(code=code)
        for code in finding_codes
    )
    return SimpleNamespace(
        spec_id=spec_id,
        status=status,
        graph_hash=graph_hash,
        findings=findings,
        to_dict=lambda: {
            "schema_version": 1,
            "spec_id": spec_id,
            "graph_hash": graph_hash,
            "status": status,
            "findings": [{"code": code} for code in finding_codes],
        },
    )


def _audit_for_current_graph(
    spec_dir: Path,
    status: str = "pass",
    finding_codes: tuple[str, ...] = (),
) -> SimpleNamespace:
    return _pass_audit(
        spec_dir.name,
        status,
        "sha256:" + hashlib.sha256(spec_dir.joinpath("spec-artifact-graph.json").read_bytes()).hexdigest(),
        finding_codes,
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
@pytest.mark.parametrize("target_inside_workspace", [True, False])
def test_discovery_rejects_symlinked_spec_file(
    tmp_path: Path,
    target_inside_workspace: bool,
) -> None:
    root = tmp_path / "workspace"
    _write_config(root)
    spec_dir = _spec_dir(root, "001-alpha")
    target = (
        root / "shared-spec.md"
        if target_inside_workspace
        else tmp_path / "outside-spec.md"
    )
    target.write_text("# linked specification\n", encoding="utf-8")
    spec_dir.joinpath("spec.md").unlink()
    spec_dir.joinpath("spec.md").symlink_to(target)

    assert discover_canonical_spec_dirs(root) == ()


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
@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (
            [{"id": "app", "path": "app-a"}, {"id": "app", "path": "app-b"}],
            "duplicate workspace source id: app",
        ),
        ([{"id": "missing", "path": "missing"}], "workspace source path does not exist"),
        ([{"id": "outside", "path": "../outside"}], "workspace source path escapes project root"),
    ],
)
def test_build_rejects_invalid_configured_source_roots(
    tmp_path: Path,
    sources: list[dict[str, str]],
    message: str,
) -> None:
    _spec_dir(tmp_path, "001-alpha")
    (tmp_path / "app-a").mkdir()
    (tmp_path / "app-b").mkdir()
    _write_config(tmp_path, sources=sources)

    with pytest.raises(WorkspaceGraphError, match=message):
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
        lambda root, selector: _audit_for_current_graph(Path(selector)),
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
        lambda root, selector: _audit_for_current_graph(
            Path(selector),
            statuses[Path(selector).name],
            (
                ("graph_source_set_stale",)
                if Path(selector).name == "002-beta"
                else ()
            ),
        ),
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
        "member_specs": ["002-beta"],
    }
    assert [member.included for member in result.graph.members] == [True, False]
    assert result.issues[0].subject_id == "spec:002-beta"


@pytest.mark.unit
def test_current_member_with_coherence_failure_is_unhealthy_not_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(
            Path(selector),
            "fail",
            ("requirement_verification_missing",),
        ),
    )

    result = build_workspace_graph(tmp_path)
    member = result.graph.members[0]
    spec_node = next(node for node in result.graph.nodes if node.type == "Spec")

    assert member.exclusion_reason == "member_graph_unhealthy"
    assert spec_node.properties["exclusion_reason"] == "member_graph_unhealthy"
    assert result.issues[0].code == "member_graph_unhealthy"


@pytest.mark.unit
def test_member_receipts_preserve_graph_and_per_spec_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    member_graph = _member_graph("001-alpha")
    _write_member_graph(alpha, member_graph)
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    result = build_workspace_graph(tmp_path)
    member = result.graph.members[0]

    assert member.graph_path == "specs/001-alpha/spec-artifact-graph.json"
    assert member.member_source_set_digest == member_graph.source_set_digest
    assert member.member_memory_state_digest == member_graph.memory_state_digest
    assert {
        (item.path, item.role)
        for item in result.graph.inputs
    } == {
        (".echelon/config.yml", "workspace_config"),
        ("specs", "canonical_spec_set"),
        ("specs/001-alpha/spec-artifact-graph.json", "member_graph"),
        ("specs/001-alpha/spec.md", "workspace_spec"),
    }


@pytest.mark.unit
def test_workspace_composition_preserves_requirement_projection_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(
        alpha,
        _member_graph(
            "001-alpha",
            extra_nodes=(
                GraphNode(
                    "req:001-alpha:FR-001",
                    "Requirement",
                    {
                        "requirement_id": "FR-001",
                        "category": "functional",
                        "source_line": 3,
                        "source_path": "specs/001-alpha/spec.md",
                        "source_text": "- **FR-001**: Build the report.",
                    },
                ),
                GraphNode(
                    "task:001-alpha:T-001",
                    "Task",
                    {"task_id": "T-001", "status": "PENDING"},
                ),
            ),
            extra_edges=(
                GraphEdge(
                    "spec:001-alpha",
                    "HAS_REQUIREMENT",
                    "req:001-alpha:FR-001",
                    {},
                ),
                GraphEdge(
                    "task:001-alpha:T-001",
                    "IMPLEMENTS",
                    "req:001-alpha:FR-001",
                    {},
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    result = build_workspace_graph(tmp_path)
    spec = next(node for node in result.graph.nodes if node.id == "spec:001-alpha")
    requirement = next(node for node in result.graph.nodes if node.id == "req:001-alpha:FR-001")
    task = next(node for node in result.graph.nodes if node.id == "task:001-alpha:T-001")

    assert spec.properties["member_specs"] == ["001-alpha"]
    assert requirement.properties == {
        "requirement_id": "FR-001",
        "category": "functional",
        "source_line": 3,
        "source_path": "specs/001-alpha/spec.md",
        "source_text": "- **FR-001**: Build the report.",
        "member_specs": ["001-alpha"],
    }
    assert task.properties == {
        "task_id": "T-001",
        "status": "PENDING",
        "member_specs": ["001-alpha"],
    }


@pytest.mark.unit
def test_source_receipts_change_for_workspace_spec_and_targets_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "apps" / "app").mkdir(parents=True)
    _write_config(tmp_path, sources=[{"id": "app", "path": "apps/app"}])
    alpha = _spec_dir(tmp_path, "001-alpha")
    alpha.joinpath("spec.md").write_text(
        "---\nsupersedes: 000-old\n---\n# alpha\n",
        encoding="utf-8",
    )
    alpha.joinpath("targets.yml").write_text(
        "targets:\n  - id: app\n    path: apps/app\n",
        encoding="utf-8",
    )
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    initial = build_workspace_graph(tmp_path).graph
    alpha.joinpath("spec.md").write_text(
        "---\nsupersedes: 001-alpha\n---\n# alpha\n",
        encoding="utf-8",
    )
    spec_changed = build_workspace_graph(tmp_path).graph
    alpha.joinpath("targets.yml").write_text(
        "targets:\n  - id: missing\n    path: missing\n",
        encoding="utf-8",
    )
    targets_changed = build_workspace_graph(tmp_path).graph

    assert initial.source_set_digest != spec_changed.source_set_digest
    assert spec_changed.source_set_digest != targets_changed.source_set_digest
    assert ("specs/001-alpha/targets.yml", "workspace_targets") in {
        (item.path, item.role) for item in targets_changed.inputs
    }


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
            "member_specs": ["001-alpha"],
        },
    )
    assert result.issues[0].subject_id == "spec:001-alpha"


@pytest.mark.unit
def test_missing_member_graph_becomes_placeholder_after_live_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    calls: list[str] = []

    def audit(root: Path, selector: Path) -> SimpleNamespace:
        calls.append("audit")
        return _pass_audit("001-alpha", "unavailable")

    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", audit)

    result = build_workspace_graph(tmp_path)

    assert calls == ["audit"]
    assert result.graph.members[0].graph_hash is None
    assert result.graph.members[0].exclusion_reason == "member_graph_invalid"
    assert result.issues[0].code == "member_graph_invalid"


@pytest.mark.unit
def test_excludes_member_when_live_audit_observes_replaced_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(alpha, _member_graph("001-alpha"))
    graph_path = alpha / "spec-artifact-graph.json"
    replacement = render_spec_graph(
        _member_graph("001-alpha", artifact_path="re/workspace/replaced.md")
    )

    def audit(root: Path, selector: Path) -> SimpleNamespace:
        graph_path.write_bytes(replacement)
        return _pass_audit(
            "001-alpha",
            graph_hash="sha256:" + hashlib.sha256(replacement).hexdigest(),
        )

    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", audit)

    result = build_workspace_graph(tmp_path)

    assert result.graph.members[0].included is False
    assert result.graph.members[0].exclusion_reason == "member_graph_changed"
    assert result.issues[0].code == "member_graph_changed"


@pytest.mark.unit
def test_merges_shared_identity_and_adds_workspace_relationships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "apps" / "app").mkdir(parents=True)
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
        lambda root, selector: _audit_for_current_graph(Path(selector)),
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
    assert nodes["source:app"].type == "SourceRoot"
    shared_edge = edges[("artifact:re/workspace/overview.md", "STORED_AS", "drawer:shared-re-drawer")]
    assert shared_edge.properties["member_specs"] == ["001-alpha", "002-beta"]
    assert ("workspace:current", "CONTAINS_SPEC", "spec:001-alpha") in edges
    assert ("workspace:current", "CONTAINS_SPEC", "spec:002-beta") in edges
    assert ("spec:001-alpha", "TARGETS", "source:app") in edges
    assert ("spec:002-beta", "TARGETS", "source:app") in edges
    assert ("spec:002-beta", "SUPERSEDES", "spec:001-alpha") in edges


@pytest.mark.unit
def test_workspace_graph_deduplicates_re_source_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    beta = _spec_dir(tmp_path, "002-beta")
    artifact_path = "re/sources/api/adrs/ADR-001-boundary.md"
    decision_id = "decision:api:adrs/ADR-001-boundary.md"
    source_node = GraphNode(
        "re-source:api",
        "ReverseEngineeringSource",
        {"source_id": "api", "publication_status": "complete"},
    )
    decision_node = GraphNode(
        decision_id,
        "Decision",
        {
            "source_id": "api",
            "path": artifact_path,
            "title": "API Boundary",
        },
    )
    for spec_dir in (alpha, beta):
        spec_id = spec_dir.name
        artifact_id = f"artifact:{spec_id}:{artifact_path}"
        _write_member_graph(
            spec_dir,
            _member_graph(
                spec_id,
                artifact_path=artifact_path,
                artifact_properties={
                    "re_artifact_kind": "re-decision",
                    "re_scope": "source",
                    "re_source_id": "api",
                },
                extra_nodes=(source_node, decision_node),
                extra_edges=(
                    GraphEdge(f"spec:{spec_id}", "USES_RE_SOURCE", "re-source:api", {}),
                    GraphEdge("re-source:api", "HAS_DECISION", decision_id, {}),
                    GraphEdge(decision_id, "DOCUMENTED_BY", artifact_id, {}),
                ),
            ),
        )
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    result = build_workspace_graph(tmp_path)
    nodes = {node.id: node for node in result.graph.nodes}
    edges = {(edge.source, edge.type, edge.target): edge for edge in result.graph.edges}

    normalized_artifact_id = f"artifact:{artifact_path}"
    assert nodes[normalized_artifact_id].properties["re_artifact_kind"] == (
        "re-decision"
    )
    assert nodes[normalized_artifact_id].properties["re_scope"] == "source"
    assert nodes[normalized_artifact_id].properties["member_specs"] == [
        "001-alpha",
        "002-beta",
    ]
    assert nodes["re-source:api"].properties["member_specs"] == [
        "001-alpha",
        "002-beta",
    ]
    assert nodes[decision_id].properties["member_specs"] == [
        "001-alpha",
        "002-beta",
    ]
    assert edges[("re-source:api", "HAS_DECISION", decision_id)].properties[
        "member_specs"
    ] == ["001-alpha", "002-beta"]
    assert edges[(decision_id, "DOCUMENTED_BY", normalized_artifact_id)].properties[
        "member_specs"
    ] == ["001-alpha", "002-beta"]
    assert edges[
        (normalized_artifact_id, "STORED_AS", "drawer:shared-re-drawer")
    ].properties["member_specs"] == ["001-alpha", "002-beta"]


@pytest.mark.unit
def test_reports_unresolved_workspace_relationships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "apps" / "app").mkdir(parents=True)
    _write_config(tmp_path, sources=[{"id": "app", "path": "apps/app"}])
    alpha = _spec_dir(tmp_path, "001-alpha", targets=[{"id": "missing", "path": "none"}])
    alpha.joinpath("spec.md").write_text(
        "---\ntargets:\n  - id: missing\n    path: none\nsupersedes: 000-old\n---\n# alpha\n",
        encoding="utf-8",
    )
    _write_member_graph(alpha, _member_graph("001-alpha"))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    result = build_workspace_graph(tmp_path)

    assert [issue.code for issue in result.issues] == [
        "superseded_spec_missing",
        "target_unresolved",
    ]
    assert all(issue.severity == "warning" for issue in result.issues)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("node", "sources"),
    [
        (GraphNode("workspace:current", "Workspace", {}), []),
        (GraphNode("source:app", "SourceRoot", {}), [{"id": "app", "path": "app"}]),
    ],
)
def test_rejects_reserved_workspace_node_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node: GraphNode,
    sources: list[dict[str, str]],
) -> None:
    if sources:
        (tmp_path / "app").mkdir()
    _write_config(tmp_path, sources=sources)
    alpha = _spec_dir(tmp_path, "001-alpha")
    _write_member_graph(alpha, _member_graph("001-alpha", extra_nodes=(node,)))
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    with pytest.raises(WorkspaceGraphError, match="reserved workspace node identity"):
        build_workspace_graph(tmp_path)


@pytest.mark.unit
def test_rejects_reserved_workspace_edge_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    alpha = _spec_dir(tmp_path, "001-alpha")
    alpha.joinpath("spec.md").write_text(
        "---\nsupersedes: 001-alpha\n---\n# 001-alpha\n",
        encoding="utf-8",
    )
    _write_member_graph(
        alpha,
        _member_graph(
            "001-alpha",
            extra_edges=(GraphEdge("spec:001-alpha", "SUPERSEDES", "spec:001-alpha", {}),),
        ),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _audit_for_current_graph(Path(selector)),
    )

    with pytest.raises(WorkspaceGraphError, match="reserved workspace edge identity"):
        build_workspace_graph(tmp_path)


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
        lambda root, selector: _audit_for_current_graph(Path(selector)),
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
        lambda root, selector: _audit_for_current_graph(Path(selector)),
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
def test_write_workspace_graph_bytes_is_atomic_and_preserves_previous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / ".echelon" / "runtime" / "graph" / "workspace.html"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous")
    replaced: list[tuple[Path, Path]] = []

    def failed_replace(source: Path, target: Path) -> None:
        replaced.append((Path(source), Path(target)))
        raise OSError("replace failed")

    monkeypatch.setattr("echelon.workspace_graph.os.replace", failed_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_workspace_graph_bytes(output, b"replacement")

    assert output.read_bytes() == b"previous"
    assert replaced and replaced[0][1] == output
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize("target_kind", ["symlink", "directory"])
def test_write_workspace_graph_bytes_rejects_nonregular_targets(
    tmp_path: Path,
    target_kind: str,
) -> None:
    output = tmp_path / ".echelon" / "runtime" / "graph" / "workspace.json"
    output.parent.mkdir(parents=True)
    referent = tmp_path / "outside-workspace.json"
    if target_kind == "symlink":
        referent.write_bytes(b"outside\n")
        output.symlink_to(referent)
    else:
        output.mkdir()

    with pytest.raises(OSError, match="regular file"):
        write_workspace_graph_bytes(output, b"replacement\n")

    if target_kind == "symlink":
        assert output.is_symlink()
        assert referent.read_bytes() == b"outside\n"


@pytest.mark.unit
def test_write_workspace_graph_bytes_rejects_earlier_symlinked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside_control = tmp_path / "outside-control"
    outside_graph = outside_control / "runtime" / "graph"
    outside_graph.mkdir(parents=True)
    root.joinpath(".echelon").symlink_to(
        outside_control,
        target_is_directory=True,
    )
    output = root / ".echelon" / "runtime" / "graph" / "workspace.json"
    external_target = outside_graph / "workspace.json"
    external_target.write_bytes(b"external-before\n")
    temp_calls: list[object] = []

    def unexpected_temp(*args: object, **kwargs: object) -> object:
        temp_calls.append((args, kwargs))
        raise AssertionError("temporary creation must not run")

    monkeypatch.setattr(
        "echelon.workspace_graph.tempfile.NamedTemporaryFile",
        unexpected_temp,
    )

    with pytest.raises(OSError, match="ancestor must be a real directory"):
        write_workspace_graph_bytes(output, b"replacement\n")

    assert temp_calls == []
    assert external_target.read_bytes() == b"external-before\n"


@pytest.mark.unit
def test_workspace_graph_path_uses_canonical_runtime_directory(tmp_path: Path) -> None:
    assert workspace_graph_path(tmp_path) == (
        tmp_path / ".echelon" / "runtime" / "graph" / "workspace-artifact-graph.json"
    )


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
        lambda root, selector: _audit_for_current_graph(Path(selector)),
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
