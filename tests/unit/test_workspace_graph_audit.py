from __future__ import annotations

from pathlib import Path

import pytest

from echelon.spec_graph import GraphInput, GraphNode
from echelon.workspace_graph import (
    WorkspaceArtifactGraph,
    WorkspaceGraphBuildResult,
    WorkspaceGraphError,
    WorkspaceGraphMember,
    WorkspaceCompositionIssue,
    workspace_graph_path,
    write_workspace_graph,
)
from echelon.workspace_graph_audit import (
    WORKSPACE_GRAPH_AUDIT_FILENAME,
    audit_workspace_graph,
    write_workspace_graph_audit,
)


def _candidate(
    *,
    spec_id: str = "001-alpha",
    graph_hash: str | None = "sha256:member",
    audit_hash: str = "sha256:audit",
    audit_status: str = "pass",
    included: bool = True,
    inputs: tuple[GraphInput, ...] = (),
    issues: tuple[WorkspaceCompositionIssue, ...] = (),
) -> WorkspaceGraphBuildResult:
    member = WorkspaceGraphMember(
        spec_id=spec_id,
        path=f"specs/{spec_id}",
        graph_hash=graph_hash,
        audit_hash=audit_hash,
        audit_status=audit_status,
        included=included,
        exclusion_reason=None if included else "member_graph_stale",
    )
    graph = WorkspaceArtifactGraph(
        workspace_name="workspace",
        generator_version="test",
        members=(member,),
        inputs=inputs,
        nodes=(GraphNode(f"spec:{spec_id}", "Spec", {"spec_id": spec_id}),),
        edges=(),
    )
    return WorkspaceGraphBuildResult(graph=graph, issues=issues)


@pytest.mark.unit
def test_candidate_audit_passes_without_touching_upstream_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: candidate,
    )

    report = audit_workspace_graph(tmp_path, candidate=candidate)

    assert report.status == "pass"
    assert report.to_dict()["scope"] == "workspace"
    assert report.findings == ()


@pytest.mark.unit
def test_audit_orders_findings_and_maps_warning_failure_and_unavailable_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = _candidate(
        issues=(
            WorkspaceCompositionIssue(
                "warning", "target_unresolved", "target is not configured", "spec:001-alpha"
            ),
        )
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: warning
    )

    report = audit_workspace_graph(tmp_path, candidate=warning)

    assert report.status == "warn"
    assert [row["id"] for row in report.to_dict()["findings"]] == sorted(
        row["id"] for row in report.to_dict()["findings"]
    )

    failed = _candidate(included=False)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: failed
    )
    assert audit_workspace_graph(tmp_path, candidate=failed).status == "unavailable"


@pytest.mark.unit
def test_audit_reports_missing_or_malformed_persisted_workspace_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _candidate()
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    missing = audit_workspace_graph(tmp_path)
    assert missing.status == "fail"
    assert [finding.code for finding in missing.findings] == ["workspace_graph_missing"]

    path = workspace_graph_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    malformed = audit_workspace_graph(tmp_path)
    assert malformed.status == "fail"
    assert [finding.code for finding in malformed.findings] == ["workspace_graph_invalid"]

    path.write_text('{"schema_version": 1, "scope": "workspace"}\n', encoding="utf-8")
    incomplete = audit_workspace_graph(tmp_path)
    assert incomplete.status == "fail"
    assert [finding.code for finding in incomplete.findings] == ["workspace_graph_invalid"]


@pytest.mark.unit
def test_audit_reports_member_add_remove_and_graph_receipt_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _candidate()
    write_workspace_graph(stored.graph, tmp_path)
    current = _candidate(spec_id="002-beta", graph_hash="sha256:changed")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert {finding.code for finding in report.findings} == {
        "workspace_member_added",
        "workspace_member_removed",
        "workspace_member_state_stale",
        "workspace_source_set_stale",
    }


@pytest.mark.unit
def test_audit_reports_changed_member_graph_and_live_audit_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _candidate()
    write_workspace_graph(stored.graph, tmp_path)
    current = _candidate(graph_hash="sha256:new-member", audit_hash="sha256:new-audit")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert {finding.code for finding in report.findings} == {
        "workspace_member_graph_changed",
        "workspace_member_audit_changed",
        "workspace_member_state_stale",
    }


@pytest.mark.unit
def test_audit_reports_workspace_source_set_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _candidate(
        inputs=(GraphInput(".echelon/config.yml", "sha256:old", "workspace_config", True),)
    )
    write_workspace_graph(stored.graph, tmp_path)
    current = _candidate(
        inputs=(GraphInput(".echelon/config.yml", "sha256:new", "workspace_config", True),)
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert {finding.code for finding in report.findings} == {"workspace_source_set_stale"}


@pytest.mark.unit
def test_candidate_issues_are_included_once_and_never_read_old_workspace_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _candidate()
    write_workspace_graph(stale.graph, tmp_path)
    candidate = _candidate(
        issues=(
            WorkspaceCompositionIssue(
                "warning", "superseded_spec_missing", "missing superseded spec", "spec:001-alpha"
            ),
        )
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: candidate
    )

    report = audit_workspace_graph(tmp_path, candidate=candidate)

    assert report.status == "warn"
    assert [(finding.code, finding.subject_id) for finding in report.findings] == [
        ("superseded_spec_missing", "spec:001-alpha")
    ]


@pytest.mark.unit
def test_structural_composition_failure_is_not_reported_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: (_ for _ in ()).throw(
            WorkspaceGraphError("conflicting normalized node properties: artifact:shared")
        ),
    )

    report = audit_workspace_graph(tmp_path, candidate=candidate)

    assert report.status == "fail"
    assert [finding.code for finding in report.findings] == ["workspace_identity_conflict"]


@pytest.mark.unit
def test_write_workspace_audit_is_atomic_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _candidate(
        issues=(
            WorkspaceCompositionIssue(
                "warning", "target_unresolved", "target is not configured", "spec:001-alpha"
            ),
        )
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )
    report = audit_workspace_graph(tmp_path, candidate=current)
    replaced: list[tuple[Path, Path]] = []
    real_replace = __import__("os").replace

    def observe_replace(source: Path, target: Path) -> None:
        replaced.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr("echelon.workspace_graph_audit.os.replace", observe_replace)

    path = write_workspace_graph_audit(report, tmp_path)

    assert path.name == WORKSPACE_GRAPH_AUDIT_FILENAME
    assert path.read_bytes().endswith(b"\n")
    assert replaced and replaced[0][1] == path
