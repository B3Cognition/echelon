from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import (
    GraphEdge,
    GraphNode,
    SpecArtifactGraph,
    write_spec_graph,
)
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport


@dataclass(frozen=True)
class _StatusReport:
    status: str


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _graph(spec_id: str, *, marker: str | None = None) -> SpecArtifactGraph:
    artifact_id = f"artifact:specs/{spec_id}/fixture-input.md"
    requirement_id = f"req:{spec_id}:FR-fixture"
    task_id = f"task:{spec_id}:T-fixture"
    nodes = [
        GraphNode(
            f"spec:{spec_id}",
            "Spec",
            {
                "spec_id": spec_id,
                "path": f"specs/{spec_id}",
                "lifecycle": "phase_a",
            },
        ),
        GraphNode(
            artifact_id,
            "Artifact",
            {"path": f"specs/{spec_id}/fixture-input.md"},
        ),
        GraphNode(
            requirement_id,
            "Requirement",
            {
                "requirement_id": "FR-fixture",
                "summary": "fixture import validation",
            },
        ),
        GraphNode(
            task_id,
            "Task",
            {"task_id": "T-fixture"},
        ),
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
        edges=(
            GraphEdge(f"spec:{spec_id}", "HAS_REQUIREMENT", requirement_id, {}),
            GraphEdge(task_id, "IMPLEMENTS", requirement_id, {}),
            GraphEdge(requirement_id, "VERIFIED_BY", artifact_id, {}),
        ),
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
        lambda root, *, run_id: re_mines.append(run_id) or _StatusReport("complete"),
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
        lambda root, selector, *, run_id, allow_unlanded=False: evidence_mines.append(selector)
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

    assert refreshed.exit_code == 0
    assert re_audits == 2
    assert re_mines == ["workspace-graph-refresh"]
    assert requirement_audits == Counter({memory_spec.name: 2, graph_spec.name: 1})
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
    assert f"Workspace refresh refreshed: workspace re_memory (pass)" in refreshed.output
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

    requirement = next(
        node for node in workspace_graph["nodes"] if node["type"] == "Requirement"
    )
    requirement_id = requirement["id"]
    requirement_summary = requirement["properties"]["summary"]
    requirement_edges = [
        edge
        for edge in workspace_graph["edges"]
        if edge["source"] == requirement_id or edge["target"] == requirement_id
    ]
    artifact_id = next(
        edge["target"]
        for edge in requirement_edges
        if edge["type"] == "VERIFIED_BY" and edge["source"] == requirement_id
    )
    task_id = next(
        edge["source"]
        for edge in requirement_edges
        if edge["type"] == "IMPLEMENTS" and edge["target"] == requirement_id
    )

    query = runner.invoke(app, ["graph", "query", requirement_summary, "--json"])
    assert query.exit_code == 0
    query_payload = json.loads(query.output)
    queried_requirement = next(
        node for node in query_payload["nodes"] if node["id"] == requirement_id
    )

    explain = runner.invoke(
        app, ["graph", "explain", queried_requirement["id"], "--json"]
    )
    path = runner.invoke(
        app, ["graph", "path", queried_requirement["id"], artifact_id, "--json"]
    )
    neighbors = runner.invoke(app, ["graph", "neighbors", task_id, "--json"])
    impact = runner.invoke(
        app, ["graph", "impact", queried_requirement["id"], "--json"]
    )

    assert (
        explain.exit_code == path.exit_code == neighbors.exit_code == impact.exit_code == 0
    )
    assert any(node["id"] == artifact_id for node in json.loads(path.output)["nodes"])
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
        member["graph_path"]: (tmp_path / member["graph_path"]).read_bytes()
        for member in members
    }
    repeated_refresh = runner.invoke(
        app, ["graph", "workspace", "refresh", "--write"]
    )
    assert repeated_refresh.exit_code == 0
    assert graph_path.read_bytes() == workspace_graph_bytes
    assert {
        path: (tmp_path / path).read_bytes() for path in member_graph_bytes
    } == member_graph_bytes

    write_spec_graph(_graph(graph_spec.name, marker="changed-after-refresh"), graph_spec)

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
