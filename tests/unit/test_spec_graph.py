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
    write_spec_graph,
)
from echelon.spec_graph_audit import write_spec_graph_audit
from harness.re_registry import ReRegistryError


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


@pytest.mark.unit
def test_write_spec_graph_is_atomic_and_preserves_previous_bytes_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "spec-artifact-graph.json"
    path.write_bytes(b"previous\n")

    def failed_replace(source: Path, target: Path) -> None:
        raise OSError("publication failed")

    monkeypatch.setattr("os.replace", failed_replace)

    with pytest.raises(OSError, match="publication failed"):
        write_spec_graph(_graph(), tmp_path)

    assert path.read_bytes() == b"previous\n"
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize("target_kind", ["symlink", "directory"])
def test_write_spec_graph_rejects_nonregular_targets(
    tmp_path: Path,
    target_kind: str,
) -> None:
    path = tmp_path / "spec-artifact-graph.json"
    referent = tmp_path / "referent.json"
    if target_kind == "symlink":
        referent.write_bytes(b"referent\n")
        path.symlink_to(referent)
    else:
        path.mkdir()

    with pytest.raises(OSError, match="regular file"):
        write_spec_graph(_graph(), tmp_path)

    if target_kind == "symlink":
        assert path.is_symlink()
        assert referent.read_bytes() == b"referent\n"


@pytest.mark.unit
def test_write_spec_graph_audit_is_atomic_and_preserves_previous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "spec-artifact-graph-audit.json"
    path.write_bytes(b"previous-audit\n")
    report = SimpleNamespace(to_dict=lambda: {"schema_version": 1, "status": "pass"})

    def failed_replace(source: Path, target: Path) -> None:
        raise OSError("audit publication failed")

    monkeypatch.setattr("os.replace", failed_replace)

    with pytest.raises(OSError, match="audit publication failed"):
        write_spec_graph_audit(report, tmp_path)

    assert path.read_bytes() == b"previous-audit\n"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _re_descriptor(
    root: Path,
    relative_path: str,
    *,
    kind: str,
    scope: str,
    source_id: str | None = None,
) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "kind": kind,
        "path": relative_path,
        "sha256": "sha256:"
        + hashlib.sha256((root / relative_path).read_bytes()).hexdigest(),
        "scope": scope,
    }
    if source_id is not None:
        descriptor["source_id"] = source_id
    return descriptor


def _write_re_index(
    root: Path,
    *,
    typed: bool,
    include_source: bool = True,
) -> None:
    workspace_root = root / "re" / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    manifest_path = workspace_root / "manifest.json"
    if not manifest_path.exists():
        _write_json(manifest_path, {"schema_version": 1})
    for name in ("overview.md", "relationships.md", "contracts.md"):
        path = workspace_root / name
        if not path.exists():
            path.write_text(f"# {name}\n", encoding="utf-8")

    source_entry: dict[str, object] = {
        "path": ".",
        "published_path": "re/sources/api",
        "fingerprint": "source-fingerprint",
        "profile_hash": "profile-hash",
        "status": "complete",
        "manifest": "re/sources/api/manifest.json",
    }
    workspace_entry: dict[str, object] = {
        "manifest": "re/workspace/manifest.json",
        "overview": "re/workspace/overview.md",
        "relationships": "re/workspace/relationships.md",
        "contracts": "re/workspace/contracts.md",
    }
    if typed and include_source:
        source_entry["manifest_artifact"] = _re_descriptor(
            root,
            "re/sources/api/manifest.json",
            kind="re-source-manifest",
            scope="source",
            source_id="api",
        )
        workspace_entry["manifest_artifact"] = _re_descriptor(
            root,
            "re/workspace/manifest.json",
            kind="re-workspace-manifest",
            scope="workspace",
        )
    _write_json(
        root / "re" / "index.json",
        {
            "schema_version": 1,
            "generation": 2,
            "publication_status": "complete",
            "published_at": "2026-08-04T12:00:00Z",
            "published_from_run": "re-graph-test",
            "sources": {"api": source_entry} if include_source else {},
            "workspace": workspace_entry,
            "warnings": [],
        },
    )


def _attach_re_context(spec_dir: Path, root: Path, paths: list[str]) -> None:
    _write_json(
        spec_dir / "re-context.json",
        {
            "schema_version": 1,
            "status": "attached",
            "generation": 2,
            "artifacts": [
                {
                    "path": path,
                    "hash": "sha256:"
                    + hashlib.sha256((root / path).read_bytes()).hexdigest(),
                }
                for path in paths
            ],
        },
    )


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
@pytest.mark.parametrize(
    "context_case",
    ["absent", "ignored", "empty", "hash-rejected"],
)
def test_build_spec_graph_skips_malformed_re_index_without_admitted_artifacts(
    tmp_path: Path,
    context_case: str,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    index = tmp_path / "re" / "index.json"
    index.parent.mkdir(parents=True)
    index.write_text("{malformed\n", encoding="utf-8")

    if context_case == "ignored":
        _write_json(
            spec_dir / "re-context.json",
            {"schema_version": 1, "status": "ignored", "artifacts": []},
        )
    elif context_case == "empty":
        _write_json(
            spec_dir / "re-context.json",
            {"schema_version": 1, "status": "attached", "artifacts": []},
        )
    elif context_case == "hash-rejected":
        artifact = tmp_path / "re" / "workspace" / "overview.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Current bytes\n", encoding="utf-8")
        _write_json(
            spec_dir / "re-context.json",
            {
                "schema_version": 1,
                "status": "attached",
                "artifacts": [
                    {
                        "path": "re/workspace/overview.md",
                        "hash": "sha256:" + "0" * 64,
                    }
                ],
            },
        )

    graph = build_spec_graph(tmp_path, spec_dir)

    assert all(
        node.type not in {"ReverseEngineeringSource", "Decision"}
        for node in graph.nodes
    )


@pytest.mark.unit
def test_build_spec_graph_validates_re_index_for_admitted_artifact(
    tmp_path: Path,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    artifact = tmp_path / "re" / "workspace" / "overview.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Attached bytes\n", encoding="utf-8")
    _attach_re_context(
        spec_dir,
        tmp_path,
        ["re/workspace/overview.md"],
    )
    index = tmp_path / "re" / "index.json"
    index.write_text("{malformed\n", encoding="utf-8")

    with pytest.raises(ReRegistryError, match="cannot read RE index"):
        build_spec_graph(tmp_path, spec_dir)


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

    assert payload["node_projection_version"] == 2
    assert nodes["spec:001-demo"]["properties"]["lifecycle"] == "phase_a"
    assert nodes["req:001-demo:FR-001"]["properties"] == {
        "category": "functional",
        "requirement_id": "FR-001",
        "source_line": 3,
        "source_path": "specs/001-demo/spec.md",
        "source_text": "- **FR-001**: Build the report.",
    }
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
def test_build_spec_graph_aggregates_multiple_product_inputs_per_requirement(
    tmp_path: Path,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    _write_json(
        spec_dir / "inputs" / "traceability.json",
        {
            "schema_version": 1,
            "requirements": [
                {
                    "input_unit_id": "IN-REQ-002",
                    "disposition": "included",
                    "spec_ids": ["FR-001"],
                    "task_ids": ["T-001"],
                    "targets": [],
                },
                {
                    "input_unit_id": "IN-REQ-001",
                    "disposition": "included",
                    "spec_ids": ["FR-001"],
                    "task_ids": ["T-001"],
                    "targets": [],
                },
            ],
        },
    )

    payload = build_spec_graph(tmp_path, spec_dir).to_dict()
    derived = [
        edge
        for edge in payload["edges"]
        if edge["source"] == "req:001-demo:FR-001"
        and edge["type"] == "DERIVED_FROM"
    ]

    assert len(derived) == 1
    assert derived[0]["properties"] == {
        "input_unit_ids": ["IN-REQ-001", "IN-REQ-002"]
    }


@pytest.mark.unit
def test_build_spec_graph_accepts_infrastructure_task_scope(
    tmp_path: Path,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=foundation "
        "req=INFRA depends=none\n",
        encoding="utf-8",
    )

    graph = build_spec_graph(tmp_path, spec_dir)
    task = next(node for node in graph.nodes if node.type == "Task")

    assert task.properties["unresolved_requirement_ids"] == []


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


@pytest.mark.unit
def test_build_spec_graph_uses_typed_descriptor_kinds_for_re_topology(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    source_root = tmp_path / "re" / "sources" / "api"
    workspace_root = tmp_path / "re" / "workspace"
    source_artifacts = {
        "notes/alpha.md": ("re-architecture", "# Typed architecture\n"),
        "notes/bravo.md": ("re-contracts", "# Typed contracts\n"),
        "notes/charlie.md": ("re-components", "# Typed components\n"),
        "notes/delta.md": ("re-decision", "# Typed source decision\n"),
        "evidence/echo.json": (
            "re-codegraph-summary",
            '{"summary":"source"}\n',
        ),
    }
    source_descriptors = []
    for relative_path, (kind, content) in source_artifacts.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        source_descriptors.append(
            _re_descriptor(
                tmp_path,
                f"re/sources/api/{relative_path}",
                kind=kind,
                scope="source",
                source_id="api",
            )
        )
    uncataloged = source_root / "contracts.md"
    uncataloged.write_text("# Uncataloged filename bait\n", encoding="utf-8")
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "publication_status": "complete",
            "source_fingerprint": "source-fingerprint",
            "artifacts": sorted(
                source_descriptors,
                key=lambda descriptor: str(descriptor["path"]),
            ),
        },
    )

    workspace_decision = workspace_root / "notes" / "foxtrot.md"
    workspace_decision.parent.mkdir(parents=True, exist_ok=True)
    workspace_decision.write_text("# Typed workspace decision\n", encoding="utf-8")
    _write_json(
        workspace_root / "manifest.json",
        {
            "schema_version": 1,
            "artifacts": [
                _re_descriptor(
                    tmp_path,
                    "re/workspace/notes/foxtrot.md",
                    kind="re-decision",
                    scope="workspace",
                )
            ],
        },
    )
    _write_re_index(tmp_path, typed=True)
    attached_paths = [
        "re/sources/api/manifest.json",
        *[
            f"re/sources/api/{relative_path}"
            for relative_path in source_artifacts
        ],
        "re/sources/api/contracts.md",
        "re/workspace/notes/foxtrot.md",
    ]
    _attach_re_context(spec_dir, tmp_path, attached_paths)

    class FakeAdapter:
        wing = "demo-wing"

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            if source != "re/sources/api/notes/alpha.md":
                return []
            return [
                SimpleNamespace(
                    drawer_id="drawer-re-architecture",
                    requirement_id="RE-ARCH-001",
                    room=artifact_metadata["room"],
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="re-architecture-hash",
                    requirement_content_sha256="re-architecture-content-hash",
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
            artifact_count=len(attached_paths),
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

    source_id = "re-source:api"
    architecture_id = "artifact:001-demo:re/sources/api/notes/alpha.md"
    contracts_id = "artifact:001-demo:re/sources/api/notes/bravo.md"
    components_id = "artifact:001-demo:re/sources/api/notes/charlie.md"
    source_decision_artifact_id = (
        "artifact:001-demo:re/sources/api/notes/delta.md"
    )
    source_decision_id = "decision:api:notes/delta.md"
    codegraph_id = "artifact:001-demo:re/sources/api/evidence/echo.json"
    workspace_decision_artifact_id = (
        "artifact:001-demo:re/workspace/notes/foxtrot.md"
    )
    workspace_decision_id = "decision:workspace:notes/foxtrot.md"
    uncataloged_id = "artifact:001-demo:re/sources/api/contracts.md"
    drawer_id = "drawer:001-demo:drawer-re-architecture"

    assert nodes[source_id]["properties"]["publication_status"] == "complete"
    assert nodes[architecture_id]["properties"]["re_artifact_kind"] == (
        "re-architecture"
    )
    assert nodes[architecture_id]["properties"]["re_scope"] == "source"
    assert nodes[architecture_id]["properties"]["re_source_id"] == "api"
    assert nodes[workspace_decision_artifact_id]["properties"][
        "re_artifact_kind"
    ] == "re-decision"
    assert nodes[workspace_decision_artifact_id]["properties"]["re_scope"] == (
        "workspace"
    )
    assert (source_id, "DESCRIBED_BY", architecture_id) in edges
    assert (source_id, "DECLARES_CONTRACTS_IN", contracts_id) in edges
    assert (source_id, "CATALOGS_COMPONENTS_IN", components_id) in edges
    assert (source_id, "SUMMARIZED_BY", codegraph_id) in edges
    assert (source_id, "HAS_DECISION", source_decision_id) in edges
    assert (
        source_decision_id,
        "DOCUMENTED_BY",
        source_decision_artifact_id,
    ) in edges
    assert (
        "spec:001-demo",
        "INFORMED_BY_DECISION",
        workspace_decision_id,
    ) in edges
    assert (
        workspace_decision_id,
        "DOCUMENTED_BY",
        workspace_decision_artifact_id,
    ) in edges
    assert (architecture_id, "STORED_AS", drawer_id) in edges
    assert "re_artifact_kind" not in nodes[uncataloged_id]["properties"]
    assert "re_scope" not in nodes[uncataloged_id]["properties"]
    assert not any(
        source == source_id and target == uncataloged_id
        for source, _, target in edges
    )


@pytest.mark.unit
def test_build_spec_graph_models_linked_re_source_topology(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    source_root = tmp_path / "re" / "sources" / "api"
    source_root.mkdir(parents=True)
    artifacts = {
        "manifest.json": json.dumps(
            {
                "schema_version": 1,
                "source_id": "api",
                "publication_status": "complete",
                "source_fingerprint": "source-fingerprint",
                "overview": "re/sources/api/overview.md",
                "specs": [],
                "architecture": "re/sources/api/architecture.md",
                "contracts": "re/sources/api/contracts.md",
                "components": "re/sources/api/components.md",
                "codegraph_summary": (
                    "re/sources/api/codegraph-summary.json"
                ),
            }
        )
        + "\n",
        "overview.md": "# API Overview\n",
        "architecture.md": "# API Architecture\n",
        "contracts.md": "# API Contracts\n",
        "components.md": "# API Components\n",
        "adrs/ADR-001-boundary.md": "Decision text without a heading.\n",
        "codegraph-summary.json": '{"unknown_schema":{"entities":12}}\n',
    }
    context_rows = []
    for relative, content in artifacts.items():
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        context_rows.append(
            {
                "path": f"re/sources/api/{relative}",
                "hash": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    _write_re_index(tmp_path, typed=False)
    _write_json(
        spec_dir / "re-context.json",
        {
            "schema_version": 1,
            "status": "attached",
            "generation": 2,
            "artifacts": context_rows,
        },
    )

    class FakeAdapter:
        wing = "demo-wing"

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            if source != "re/sources/api/architecture.md":
                return []
            return [
                SimpleNamespace(
                    drawer_id="drawer-re-architecture",
                    requirement_id="RE-ARCH-001",
                    room=artifact_metadata["room"],
                    source=source,
                    artifact_hash=artifact_metadata["artifact_hash"],
                    canonical_spec_sha256="re-architecture-hash",
                    requirement_content_sha256="re-architecture-content-hash",
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
            artifact_count=len(artifacts),
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

    source_id = "re-source:api"
    decision_id = "decision:api:adrs/ADR-001-boundary.md"
    architecture_id = "artifact:001-demo:re/sources/api/architecture.md"
    contracts_id = "artifact:001-demo:re/sources/api/contracts.md"
    components_id = "artifact:001-demo:re/sources/api/components.md"
    adr_id = "artifact:001-demo:re/sources/api/adrs/ADR-001-boundary.md"
    codegraph_id = "artifact:001-demo:re/sources/api/codegraph-summary.json"

    assert nodes[source_id]["type"] == "ReverseEngineeringSource"
    assert nodes[source_id]["properties"]["publication_status"] == "complete"
    assert nodes[decision_id]["type"] == "Decision"
    assert nodes[decision_id]["properties"]["title"] == "ADR-001-boundary"
    assert nodes[architecture_id]["properties"]["re_artifact_kind"] == (
        "re-architecture"
    )
    assert nodes[architecture_id]["properties"]["re_scope"] == "source"
    assert nodes[architecture_id]["properties"]["re_source_id"] == "api"
    assert nodes[architecture_id]["properties"]["mining_status"] == "mined"
    assert nodes[codegraph_id]["properties"]["mining_status"] == "eligible"
    drawer_id = "drawer:001-demo:drawer-re-architecture"
    assert nodes[drawer_id]["properties"]["artifact_kind"] == "re-architecture"
    assert ("spec:001-demo", "USES_RE_SOURCE", source_id) in edges
    assert (source_id, "DESCRIBED_BY", architecture_id) in edges
    assert (source_id, "DECLARES_CONTRACTS_IN", contracts_id) in edges
    assert (source_id, "CATALOGS_COMPONENTS_IN", components_id) in edges
    assert (source_id, "SUMMARIZED_BY", codegraph_id) in edges
    assert (source_id, "HAS_DECISION", decision_id) in edges
    assert (decision_id, "DOCUMENTED_BY", adr_id) in edges
    assert (architecture_id, "STORED_AS", drawer_id) in edges


@pytest.mark.unit
def test_build_spec_graph_models_linked_workspace_re_decision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = _canonical_spec(tmp_path)
    adr = tmp_path / "re" / "workspace" / "strategy" / "adrs" / "ADR-001-platform.md"
    adr.parent.mkdir(parents=True)
    adr.write_text("# Platform Boundary\n\nKeep services independent.\n", encoding="utf-8")
    _write_re_index(tmp_path, typed=False, include_source=False)
    _write_json(
        spec_dir / "re-context.json",
        {
            "schema_version": 1,
            "status": "attached",
            "generation": 2,
            "artifacts": [
                {
                    "path": "re/workspace/strategy/adrs/ADR-001-platform.md",
                    "hash": "sha256:" + hashlib.sha256(adr.read_bytes()).hexdigest(),
                }
            ],
        },
    )

    class FakeAdapter:
        wing = "demo-wing"

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            return []

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
            artifact_count=1,
            expected_count=0,
            present_current_count=0,
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
    artifact_id = (
        "artifact:001-demo:re/workspace/strategy/adrs/ADR-001-platform.md"
    )
    decision_id = "decision:workspace:strategy/adrs/ADR-001-platform.md"

    assert nodes[artifact_id]["properties"]["re_artifact_kind"] == "re-decision"
    assert nodes[artifact_id]["properties"]["re_scope"] == "workspace"
    assert nodes[decision_id]["type"] == "Decision"
    assert nodes[decision_id]["properties"]["title"] == "Platform Boundary"
    assert ("spec:001-demo", "INFORMED_BY_DECISION", decision_id) in edges
    assert (decision_id, "DOCUMENTED_BY", artifact_id) in edges
