from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.spec_graph import GraphNode, SpecArtifactGraph, write_spec_graph
from echelon.spec_graph_audit import SpecGraphAuditReport


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
                findings=(),
            )
        return _live_audit(root, selector)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", _live_audit)
    monkeypatch.setattr("echelon.workspace_graph_refresh.audit_re_memory", audit_re_memory)
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
        or _graph(str(selector), marker="repaired"),
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
    assert f"Workspace refresh refreshed: workspace re_memory (pass)" in refreshed.output
    assert (
        f"Workspace refresh refreshed: {memory_spec.name} requirements_memory (pass)"
        in refreshed.output
    )
    assert (
        f"Workspace refresh refreshed: {memory_spec.name} evidence_memory (pass)"
        in refreshed.output
    )
    assert f"Workspace refresh skipped: {graph_spec.name} requirements_memory (pass)" in refreshed.output
    assert f"Workspace refresh refreshed: {graph_spec.name} spec_graph (pass)" in refreshed.output

    graph_path = tmp_path / ".echelon" / "runtime" / "graph" / "workspace-artifact-graph.json"
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
    assert stale_dot_path.read_text(encoding="utf-8").startswith('digraph "')
