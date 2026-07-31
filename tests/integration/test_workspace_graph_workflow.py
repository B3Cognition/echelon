from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import GraphNode, SpecArtifactGraph, write_spec_graph
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport
from tests.unit.test_re_publication import write_valid_re_run
from tests.unit.test_spec_publish import _create_spec_branch, _git, _init_repo


@dataclass(frozen=True)
class _StatusReport:
    status: str


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _graph(spec_id: str, *, marker: str | None = None) -> SpecArtifactGraph:
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
    if marker is not None:
        nodes.append(
            GraphNode(
                f"artifact:{spec_id}/{marker}.md",
                "Artifact",
                {"path": f"{spec_id}/{marker}.md"},
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
        graph_hash=_sha256(graph_bytes),
        status="pass",
        findings=(),
    )


def _write_synthetic_spec(spec_dir: Path, *, landed: bool) -> None:
    spec_dir.mkdir(parents=True)
    frontmatter = "---\nstatus: landed\n---\n" if landed else ""
    (spec_dir / "spec.md").write_text(
        f"{frontmatter}# Synthetic spec\n",
        encoding="utf-8",
    )
    write_spec_graph(_graph(spec_dir.name), spec_dir)


class _MemoryCollection:
    """Minimal in-memory stand-in for the external MemPalace collection."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, object]]] = {}

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
        include: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, list[object]]:
        rows = self.rows.items()
        if ids is not None:
            rows = ((drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows)
        elif where is not None:
            rows = (
                (drawer_id, row)
                for drawer_id, row in rows
                if all(
                    row[1].get(key)
                    == (expected.get("$eq") if isinstance(expected, dict) else expected)
                    for key, expected in where.items()
                )
            )
        selected = list(rows)
        if limit is not None:
            selected = selected[:limit]
        return {
            "ids": [drawer_id for drawer_id, _row in selected],
            "documents": [document for _drawer_id, (document, _metadata) in selected],
            "metadatas": [metadata for _drawer_id, (_document, metadata) in selected],
        }

    def delete(self, ids: list[str]) -> None:
        for drawer_id in ids:
            self.rows.pop(drawer_id, None)


class _MemoryWriter:
    """External storage boundary used by the real Echelon mining adapters."""

    def __init__(self, collection: _MemoryCollection, wing: str) -> None:
        self.collection = collection
        self.wing = wing

    def get_collection_read_only(self) -> _MemoryCollection:
        return self.collection

    def write_exact(
        self,
        *,
        room: str,
        content: str,
        phase: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
        provenance_type: str,
        source_file: str,
        extra_metadata: dict[str, object] | None,
    ) -> SimpleNamespace:
        metadata = dict(extra_metadata or {})
        metadata.update(
            {
                "artifact_path": metadata.get("artifact_path", source_file),
                "canonical": True,
                "canonical_spec_sha256": spec_sha256,
                "deterministic_identity_schema_version": 1,
                "lifecycle_status": metadata.get("lifecycle_status", "active"),
                "phase": phase,
                "provenance_type": provenance_type,
                "requirement_content_sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
                "requirement_id": requirement_id,
                "room": room,
                "source_file": source_file,
                "wing": self.wing,
            }
        )
        existing = self.collection.rows.get(drawer_id)
        if existing == (content, metadata):
            return SimpleNamespace(outcome="already_present", drawer_id=drawer_id)
        self.collection.rows[drawer_id] = (content, metadata)
        return SimpleNamespace(outcome="written", drawer_id=drawer_id)

    def verify_exact(
        self,
        *,
        room: str,
        content: str,
        drawer_id: str,
        spec_sha256: str,
        requirement_id: str,
    ) -> SimpleNamespace:
        row = self.collection.rows.get(drawer_id)
        if row is None:
            return SimpleNamespace(outcome="drift", drawer_id=None)
        document, metadata = row
        if (
            document == content
            and metadata.get("room") == room
            and metadata.get("canonical_spec_sha256") == spec_sha256
            and metadata.get("requirement_id") == requirement_id
        ):
            return SimpleNamespace(outcome="already_present", drawer_id=drawer_id)
        return SimpleNamespace(outcome="drift", drawer_id=None)


def _write_verify_evidence(root: Path, spec_id: str) -> Path:
    verify_dir = root / "runs" / f"verify-{spec_id}" / "verify-spec" / spec_id
    verify_dir.mkdir(parents=True)
    (verify_dir / "state.json").write_text('{"status": "complete"}\n', encoding="utf-8")
    (verify_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\nFixture evidence for the published specification.\n",
        encoding="utf-8",
    )
    return verify_dir


def _publish_fixture_workspace(root: Path) -> str:
    (root / ".echelon").mkdir()
    (root / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: fixture-workspace\nworkspace:\n  git_role: orchestration\n"
        "sources:\n  - id: fixture-source\n    path: sources/fixture-source\n",
        encoding="utf-8",
    )
    _git(root, "add", ".echelon/config.yml")
    _git(root, "commit", "-m", "chore: configure fixture workspace")

    spec_id = "001-fixture"
    _create_spec_branch(
        root,
        spec_id,
        "---\nstatus: landed\n---\n# Fixture specification\n\n"
        "- **FR-001**: Validate fixture import records.\n",
        extra_files={
            f"specs/{spec_id}/tasks.md": (
                "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
            ),
            f"specs/{spec_id}/inputs/manifest.json": '{"schema_version": 1}\n',
            f"specs/{spec_id}/inputs/catalog.json": (
                '{"schema_version": 1, "units": [{"id": "IN-REQ-001"}]}\n'
            ),
            f"specs/{spec_id}/inputs/traceability.json": (
                '{"schema_version": 1, "requirements": [{"input_unit_id": '
                '"IN-REQ-001", "disposition": "included", "spec_ids": '
                '["FR-001"], "task_ids": ["T-001"], "targets": []}]}\n'
            ),
            f"specs/{spec_id}/verified-fulfillment-ledger.json": (
                '{"schema_version": 1, "rows": [{"requirement_id": "FR-001", '
                '"status": "IMPLEMENTED", "evidence_refs": ["fixture"], '
                '"verified_commit": "fixture", "verify_scope": "full"}]}\n'
            ),
        },
    )

    from echelon.spec_publish import publish_specs
    from harness.re_publication import publish_re_run

    spec_publication = publish_specs(root, identity=spec_id)
    assert spec_publication.created_commit is True
    published_spec_id = spec_publication.published[0].spec_id

    re_publication = publish_re_run(
        root,
        write_valid_re_run(root, ("fixture-source",), run_id="fixture-re"),
    )
    assert re_publication.generation == 1

    from echelon.mempalace_spec_evidence import publish_spec_evidence_package

    evidence_publication = publish_spec_evidence_package(
        root,
        published_spec_id,
        run_id=_write_verify_evidence(root, published_spec_id).parents[1].name,
    )
    assert evidence_publication.status == "published"
    return published_spec_id


@pytest.mark.integration
def test_workspace_graph_cli_repairs_stale_domains_and_keeps_failure_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "sources" / "source").mkdir(parents=True)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources:\n"
        "  - id: source\n    path: sources/source\n",
        encoding="utf-8",
    )
    memory_spec = tmp_path / "specs" / "001-alpha"
    graph_spec = tmp_path / "specs" / "002-beta"
    _write_synthetic_spec(memory_spec, landed=True)
    _write_synthetic_spec(graph_spec, landed=False)

    re_audits = 0
    re_mines: list[str] = []
    requirement_audits: Counter[str] = Counter()
    requirement_mines: list[str] = []
    evidence_audits: Counter[str] = Counter()
    evidence_mines: list[str] = []
    snapshot_requests: list[str] = []
    graph_audits: Counter[str] = Counter()
    rebuilt_graphs: list[str] = []
    repaired_marker = "repaired"

    def audit_re_memory(root: Path) -> _StatusReport:
        nonlocal re_audits
        re_audits += 1
        return _StatusReport("fail" if re_audits == 1 else "pass")

    def audit_requirements(root: Path, selector: str) -> _StatusReport:
        requirement_audits[selector] += 1
        stale = selector == memory_spec.name and requirement_audits[selector] == 1
        return _StatusReport("fail" if stale else "pass")

    def audit_evidence(
        root: Path,
        selector: str,
        *,
        allow_unlanded: bool = False,
    ) -> _StatusReport:
        evidence_audits[selector] += 1
        stale = selector == memory_spec.name and evidence_audits[selector] == 1
        return _StatusReport("fail" if stale else "pass")

    def audit_member_graph(root: Path, selector: str) -> SpecGraphAuditReport:
        graph_audits[selector] += 1
        if selector == graph_spec.name and graph_audits[selector] == 1:
            return SpecGraphAuditReport(
                schema_version=1,
                spec_id=selector,
                graph_hash=None,
                status="fail",
                findings=(
                    GraphFinding(
                        "error",
                        "graph_missing",
                        "member graph is missing",
                    ),
                ),
            )
        return _live_audit(root, selector)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", _live_audit)
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory", audit_re_memory
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_re_memory",
        lambda root, *, run_id: re_mines.append(run_id)
        or _StatusReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory", audit_requirements
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_spec_requirements",
        lambda root, selector, *, run_id: requirement_mines.append(selector)
        or _StatusReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.cleanup_stale_spec_memory",
        lambda root, selector: None,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.load_spec_evidence_artifact_snapshots",
        lambda root, selector: snapshot_requests.append(selector)
        or ((object(),) if selector == memory_spec.name else ()),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_evidence_memory", audit_evidence
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_spec_evidence_memory",
        lambda root, selector, *, run_id, allow_unlanded=False: evidence_mines.append(
            selector
        )
        or _StatusReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_graph", audit_member_graph
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_spec_graph",
        lambda root, selector: rebuilt_graphs.append(str(selector))
        or _graph(str(selector), marker=repaired_marker),
    )

    from echelon.cli_app import app

    runner = CliRunner()
    refreshed = runner.invoke(app, ["graph", "workspace", "refresh", "--write"])

    assert refreshed.exit_code == 0, refreshed.output
    assert re_audits == 2
    assert re_mines == ["workspace-graph-refresh"]
    assert requirement_audits == Counter(
        {memory_spec.name: 2, graph_spec.name: 1}
    )
    assert requirement_mines == [memory_spec.name]
    assert evidence_audits == Counter({memory_spec.name: 2})
    assert evidence_mines == [memory_spec.name]
    assert snapshot_requests == [memory_spec.name]
    assert graph_audits == Counter({memory_spec.name: 1, graph_spec.name: 2})
    assert rebuilt_graphs == [graph_spec.name]
    rebuilt_bytes = (graph_spec / "spec-artifact-graph.json").read_bytes()
    rebuilt_document = json.loads(rebuilt_bytes)
    repaired_node_id = f"artifact:{graph_spec.name}/{repaired_marker}.md"
    assert repaired_marker.encode("utf-8") in rebuilt_bytes
    assert any(node["id"] == repaired_node_id for node in rebuilt_document["nodes"])
    assert "Workspace refresh refreshed: workspace re_memory (pass)" in refreshed.output
    assert (
        f"Workspace refresh refreshed: {memory_spec.name} requirements_memory (pass)"
        in refreshed.output
    )
    assert (
        f"Workspace refresh refreshed: {memory_spec.name} evidence_memory (pass)"
        in refreshed.output
    )
    assert (
        f"Workspace refresh skipped: {graph_spec.name} requirements_memory (pass)"
        in refreshed.output
    )
    assert (
        f"Workspace refresh refreshed: {graph_spec.name} spec_graph (pass)"
        in refreshed.output
    )

    graph_path = (
        tmp_path
        / ".echelon"
        / "runtime"
        / "graph"
        / "workspace-artifact-graph.json"
    )
    audit_path = graph_path.with_name("workspace-artifact-graph-audit.json")
    workspace_graph_bytes = graph_path.read_bytes()
    workspace_graph = json.loads(workspace_graph_bytes)
    workspace_audit = json.loads(audit_path.read_bytes())
    members = workspace_graph["members"]
    assert members and all(member["included"] for member in members)
    for member in members:
        assert member["graph_hash"] == _sha256(
            (tmp_path / member["graph_path"]).read_bytes()
        )
    assert workspace_audit["graph_hash"] == _sha256(workspace_graph_bytes)

    write_spec_graph(
        _graph(graph_spec.name, marker="changed-after-refresh"), graph_spec
    )

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
        and finding["subject_id"] == f"spec:{graph_spec.name}"
        for finding in findings
    )
    html = (tmp_path / "stale.html").read_text(encoding="utf-8")
    assert html
    assert "<!doctype html>" in html
    assert "<title>Echelon Graph</title>" in html
    assert "</html>" in html
    assert '"scope": "workspace"' in html
    assert f'"title": "{tmp_path.name}"' in html
    assert graph_spec.name in html
    dot = stale_dot_path.read_text(encoding="utf-8")
    assert dot.startswith('digraph "')
    assert dot.endswith("}\n")
    assert '"workspace:current"' in dot
    assert f'"spec:{graph_spec.name}"' in dot
    assert "CONTAINS_SPEC" in dot


@pytest.mark.integration
def test_workspace_graph_cli_runs_the_published_workspace_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _init_repo(tmp_path)
    spec_id = _publish_fixture_workspace(root)
    collection = _MemoryCollection()
    writer = _MemoryWriter(collection, "fixture-workspace")

    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "echelon.spec_memory_miner.SpecMemoryMiner._get_writer",
        lambda _miner: writer,
    )
    monkeypatch.setattr(
        "echelon.spec_memory_miner.check_wing_collision",
        lambda *args: [],
    )

    from echelon.cli_app import app

    runner = CliRunner()
    refreshed = runner.invoke(app, ["graph", "workspace", "refresh", "--write"])

    assert refreshed.exit_code == 0, refreshed.output
    assert "requirements_memory (pass)" in refreshed.output
    assert "evidence_memory (pass)" in refreshed.output
    assert "re_memory (pass)" in refreshed.output
    assert "spec_graph (pass)" in refreshed.output

    graph_path = (
        root
        / ".echelon"
        / "runtime"
        / "graph"
        / "workspace-artifact-graph.json"
    )
    workspace_graph_bytes = graph_path.read_bytes()
    workspace_graph = json.loads(workspace_graph_bytes)
    members = workspace_graph["members"]
    assert members and all(member["included"] for member in members)
    assert {member["spec_id"] for member in members} == {spec_id}
    assert all((root / member["graph_path"]).is_file() for member in members)

    requirement = next(
        node for node in workspace_graph["nodes"] if node["type"] == "Requirement"
    )
    requirement_id = requirement["id"]
    requirement_phrase = requirement["properties"]["source_text"].partition(":")[2].strip()
    linked_edges = [
        edge
        for edge in workspace_graph["edges"]
        if edge["source"] == requirement_id or edge["target"] == requirement_id
    ]
    artifact_id = next(
        edge["target"]
        for edge in linked_edges
        if edge["source"] == requirement_id and edge["type"] == "DERIVED_FROM"
    )
    task_id = next(
        edge["source"]
        for edge in linked_edges
        if edge["target"] == requirement_id and edge["type"] == "IMPLEMENTS"
    )

    query = runner.invoke(app, ["graph", "query", requirement_phrase, "--json"])
    assert query.exit_code == 0, query.output
    query_payload = json.loads(query.output)
    queried_requirement = next(
        node for node in query_payload["nodes"] if node["id"] == requirement_id
    )

    explain = runner.invoke(
        app, ["graph", "explain", queried_requirement["id"], "--json"]
    )
    assert explain.exit_code == 0, explain.output
    explain_payload = json.loads(explain.output)
    explained_requirement = next(
        node for node in explain_payload["nodes"] if node["id"] == requirement_id
    )
    assert explained_requirement["properties"]
    assert explained_requirement["properties"] == requirement["properties"]
    assert explain_payload["edges"]
    assert any(
        edge["source"] == requirement_id or edge["target"] == requirement_id
        for edge in explain_payload["edges"]
    )

    path = runner.invoke(
        app, ["graph", "path", requirement_id, artifact_id, "--json"]
    )
    assert path.exit_code == 0, path.output
    path_payload = json.loads(path.output)
    assert path_payload["paths"]
    selected_path = path_payload["paths"][0]
    assert selected_path["node_ids"][0] == requirement_id
    assert selected_path["node_ids"][-1] == artifact_id
    assert selected_path["steps"]
    assert selected_path["steps"][0]["source"] == requirement_id
    assert selected_path["steps"][-1]["target"] == artifact_id

    neighbors = runner.invoke(app, ["graph", "neighbors", task_id, "--json"])
    impact = runner.invoke(app, ["graph", "impact", requirement_id, "--json"])
    assert neighbors.exit_code == impact.exit_code == 0
    assert any(node["id"] == requirement_id for node in json.loads(neighbors.output)["nodes"])
    assert any(node["id"] == task_id for node in json.loads(impact.output)["nodes"])

    cytoscape_view = runner.invoke(
        app,
        [
            "graph",
            "workspace",
            "view",
            "--renderer",
            "cytoscape",
            "--no-open",
        ],
    )
    vis_view = runner.invoke(
        app,
        ["graph", "workspace", "view", "--renderer", "vis", "--no-open"],
    )
    assert cytoscape_view.exit_code == vis_view.exit_code == 0
    assert (graph_path.parent / "workspace.html").is_file()
    assert (graph_path.parent / "workspace-vis.html").is_file()

    member_graph_bytes = {
        member["graph_path"]: (root / member["graph_path"]).read_bytes()
        for member in members
    }
    repeated_refresh = runner.invoke(
        app, ["graph", "workspace", "refresh", "--write"]
    )
    assert repeated_refresh.exit_code == 0, repeated_refresh.output
    assert graph_path.read_bytes() == workspace_graph_bytes
    assert {
        path: (root / path).read_bytes() for path in member_graph_bytes
    } == member_graph_bytes
