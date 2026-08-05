from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest

from echelon.spec_graph import GraphNode, SpecArtifactGraph, render_spec_graph
from echelon.spec_graph_audit import (
    GRAPH_AUDIT_FILENAME,
    GraphFinding,
    SpecGraphAuditReport,
)
from echelon.spec_retarget_graph import (
    RetargetGraphError,
    RetargetGraphReceipt,
    _unlink_outputs,
    finalize_retarget_graphs,
    invalidate_retarget_graphs,
    invalidate_retarget_graphs_from_recovered_baseline,
)
from echelon.workspace_graph import (
    build_workspace_graph,
    workspace_graph_path,
    write_workspace_graph,
)
from echelon.workspace_graph_audit import (
    WORKSPACE_GRAPH_AUDIT_FILENAME,
    WorkspaceGraphAuditReport,
    WorkspaceGraphFinding,
    audit_workspace_graph,
    write_workspace_graph_audit,
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _graph(spec_id: str) -> SpecArtifactGraph:
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
        ),
        edges=(),
        memory_receipts=(),
    )


def _live_audit(_root: Path, selector: str | Path) -> SpecGraphAuditReport:
    spec_dir = Path(selector)
    graph_bytes = spec_dir.joinpath("spec-artifact-graph.json").read_bytes()
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id=spec_dir.name,
        graph_hash=_sha256(graph_bytes),
        status="pass",
        findings=(),
    )


@dataclass(frozen=True)
class GraphWorkspace:
    root: Path
    selected_spec: Path
    other_spec: Path | None


def _workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    two_specs: bool,
) -> GraphWorkspace:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    selected = tmp_path / "specs" / "001-demo"
    selected.mkdir(parents=True)
    selected.joinpath("spec.md").write_text("# Selected\n", encoding="utf-8")
    selected.joinpath("spec-artifact-graph.json").write_bytes(
        render_spec_graph(_graph(selected.name))
    )
    selected.joinpath(GRAPH_AUDIT_FILENAME).write_bytes(b"selected-audit-before\n")
    other: Path | None = None
    if two_specs:
        other = tmp_path / "specs" / "002-other"
        other.mkdir(parents=True)
        other.joinpath("spec.md").write_text("# Other\n", encoding="utf-8")
        other.joinpath("spec-artifact-graph.json").write_bytes(
            render_spec_graph(_graph(other.name))
        )
        other.joinpath(GRAPH_AUDIT_FILENAME).write_bytes(b"other-audit-before\n")
    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", _live_audit)
    built = build_workspace_graph(tmp_path)
    write_workspace_graph(built.graph, tmp_path)
    write_workspace_graph_audit(audit_workspace_graph(tmp_path, built), tmp_path)
    return GraphWorkspace(tmp_path, selected, other)


@pytest.mark.unit
def test_single_spec_invalidation_removes_workspace_graph_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=False)
    workspace.selected_spec.joinpath("spec.md").unlink()

    receipt = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)

    assert receipt == RetargetGraphReceipt(
        spec_id="001-demo",
        spec_status="invalidated",
        spec_graph_hash=None,
        workspace_status="not_applicable_empty_workspace",
        workspace_graph_hash=None,
        workspace_finding_codes=(),
    )
    assert not workspace.selected_spec.joinpath("spec-artifact-graph.json").exists()
    assert not workspace.selected_spec.joinpath(GRAPH_AUDIT_FILENAME).exists()
    assert not workspace_graph_path(workspace.root).exists()
    assert not workspace_graph_path(workspace.root).with_name(
        WORKSPACE_GRAPH_AUDIT_FILENAME
    ).exists()


@pytest.mark.unit
def test_multi_spec_invalidation_composes_only_from_other_persisted_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    assert workspace.other_spec is not None
    other_graph_before = workspace.other_spec.joinpath(
        "spec-artifact-graph.json"
    ).read_bytes()
    other_audit_before = workspace.other_spec.joinpath(GRAPH_AUDIT_FILENAME).read_bytes()
    workspace.selected_spec.joinpath("spec.md").unlink()

    receipt = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)

    document = json.loads(workspace_graph_path(workspace.root).read_bytes())
    assert [member["spec_id"] for member in document["members"]] == ["002-other"]
    assert workspace.other_spec.joinpath("spec-artifact-graph.json").read_bytes() == (
        other_graph_before
    )
    assert workspace.other_spec.joinpath(GRAPH_AUDIT_FILENAME).read_bytes() == (
        other_audit_before
    )
    assert receipt.spec_status == "invalidated"
    assert receipt.workspace_status == "pass"
    assert receipt.workspace_graph_hash == _sha256(
        workspace_graph_path(workspace.root).read_bytes()
    )


@pytest.mark.unit
def test_invalidation_refuses_until_selected_spec_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    selected_graph_before = workspace.selected_spec.joinpath(
        "spec-artifact-graph.json"
    ).read_bytes()
    workspace_graph_before = workspace_graph_path(workspace.root).read_bytes()

    with pytest.raises(RetargetGraphError, match="spec.md must already be absent"):
        invalidate_retarget_graphs(workspace.root, workspace.selected_spec)

    assert workspace.selected_spec.joinpath("spec-artifact-graph.json").read_bytes() == (
        selected_graph_before
    )
    assert workspace_graph_path(workspace.root).read_bytes() == workspace_graph_before


@pytest.mark.unit
def test_recovery_invalidation_temporarily_hides_and_restores_canonical_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=False)
    before = workspace.selected_spec.joinpath("spec.md").read_bytes()

    receipt = invalidate_retarget_graphs_from_recovered_baseline(
        workspace.root,
        workspace.selected_spec,
    )

    assert receipt.spec_status == "invalidated"
    assert workspace.selected_spec.joinpath("spec.md").read_bytes() == before
    assert not workspace.selected_spec.joinpath(
        ".spec.md.retarget-recovery"
    ).exists()


@pytest.mark.unit
def test_recovery_invalidation_restores_canonical_spec_after_graph_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=False)
    before = workspace.selected_spec.joinpath("spec.md").read_bytes()
    monkeypatch.setattr(
        "echelon.spec_retarget_graph.invalidate_retarget_graphs",
        lambda *_args: (_ for _ in ()).throw(RetargetGraphError("injected")),
    )

    with pytest.raises(RetargetGraphError, match="injected"):
        invalidate_retarget_graphs_from_recovered_baseline(
            workspace.root,
            workspace.selected_spec,
        )

    assert workspace.selected_spec.joinpath("spec.md").read_bytes() == before
    assert not workspace.selected_spec.joinpath(
        ".spec.md.retarget-recovery"
    ).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {key: item for key, item in value.items() if key != "spec_id"},
        lambda value: {**value, "extra": "rejected"},
        lambda value: {**value, "spec_id": True},
        lambda value: {**value, "spec_id": "demo"},
        lambda value: {**value, "spec_status": "complete"},
        lambda value: {**value, "spec_graph_hash": "sha256:nope"},
        lambda value: {**value, "workspace_status": 1},
        lambda value: {**value, "workspace_graph_hash": False},
        lambda value: {**value, "workspace_finding_codes": "finding"},
        lambda value: {**value, "workspace_finding_codes": [1]},
        lambda value: {
            **value,
            "workspace_finding_codes": [
                "workspace_member_audit_warning:002-other",
                "workspace_member_audit_warning:002-other",
            ],
        },
        lambda value: {
            **value,
            "workspace_finding_codes": [
                "workspace_member_audit_warning:002-other",
                "target_unresolved:001-demo",
            ],
        },
        lambda value: {**value, "workspace_finding_codes": ["not stable"]},
    ],
)
def test_retarget_graph_receipt_rejects_malformed_types_and_values(mutation) -> None:
    valid = {
        "spec_id": "001-demo",
        "spec_status": "invalidated",
        "spec_graph_hash": None,
        "workspace_status": "pass",
        "workspace_graph_hash": "sha256:" + "a" * 64,
        "workspace_finding_codes": [
            "workspace_member_audit_warning:002-other"
        ],
    }

    with pytest.raises(RetargetGraphError):
        RetargetGraphReceipt.from_dict(mutation(valid))


@pytest.mark.unit
def test_retarget_graph_receipt_round_trips_exact_valid_contract() -> None:
    receipt = RetargetGraphReceipt(
        spec_id="001-demo",
        spec_status="invalidated",
        spec_graph_hash=None,
        workspace_status="warn",
        workspace_graph_hash="sha256:" + "b" * 64,
        workspace_finding_codes=(
            "workspace_member_audit_warning:002-other",
        ),
    )

    assert RetargetGraphReceipt.from_dict(receipt.to_dict()) == receipt


def _restore_selected_for_finalization(
    workspace: GraphWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace.selected_spec.joinpath("spec.md").write_text(
        "# Replacement\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "echelon.spec_retarget_graph.build_spec_graph",
        lambda root, selector: _graph(Path(selector).name),
    )
    monkeypatch.setattr(
        "echelon.spec_retarget_graph.audit_spec_graph",
        _live_audit,
    )


@pytest.mark.unit
def test_finalization_requires_selected_current_and_tolerates_old_other_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)

    def audit_with_other_warning(
        root: Path, selector: str | Path
    ) -> SpecGraphAuditReport:
        report = _live_audit(root, selector)
        if Path(selector).name != "002-other":
            return report
        return SpecGraphAuditReport(
            schema_version=1,
            spec_id=report.spec_id,
            graph_hash=report.graph_hash,
            status="warn",
            findings=(
                GraphFinding(
                    "warning",
                    "requirement_task_missing",
                    "pre-existing warning",
                    "req:002-other:FR-001",
                ),
            ),
        )

    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph", audit_with_other_warning
    )
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    assert baseline.workspace_finding_codes == (
        "workspace_member_audit_warning:002-other",
    )
    _restore_selected_for_finalization(workspace, monkeypatch)

    receipt = finalize_retarget_graphs(
        workspace.root,
        workspace.selected_spec,
        baseline,
    )

    assert receipt.spec_status == "pass"
    assert receipt.workspace_status == "warn"
    members = json.loads(workspace_graph_path(workspace.root).read_bytes())["members"]
    assert any(
        member["spec_id"] == "001-demo" and member["included"]
        for member in members
    )


@pytest.mark.unit
def test_finalization_rejects_new_selected_spec_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=False)
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    _restore_selected_for_finalization(workspace, monkeypatch)

    def failing_audit(root: Path, selector: str | Path) -> SpecGraphAuditReport:
        report = _live_audit(root, selector)
        return SpecGraphAuditReport(
            schema_version=1,
            spec_id=report.spec_id,
            graph_hash=report.graph_hash,
            status="fail",
            findings=(
                GraphFinding(
                    "error",
                    "graph_source_set_stale",
                    "selected graph is stale",
                ),
            ),
        )

    monkeypatch.setattr(
        "echelon.spec_retarget_graph.audit_spec_graph", failing_audit
    )

    with pytest.raises(RetargetGraphError, match="selected spec graph audit failed"):
        finalize_retarget_graphs(
            workspace.root,
            workspace.selected_spec,
            baseline,
        )
    assert workspace.selected_spec.joinpath("spec-artifact-graph.json").is_file()
    assert workspace.selected_spec.joinpath(GRAPH_AUDIT_FILENAME).is_file()


@pytest.mark.unit
def test_finalization_rejects_selected_member_that_is_not_current_and_included(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    _restore_selected_for_finalization(workspace, monkeypatch)

    def stale_selected(root: Path, selector: str | Path) -> SpecGraphAuditReport:
        report = _live_audit(root, selector)
        if Path(selector).name != "001-demo":
            return report
        return SpecGraphAuditReport(
            schema_version=1,
            spec_id=report.spec_id,
            graph_hash=report.graph_hash,
            status="fail",
            findings=(
                GraphFinding(
                    "error",
                    "graph_source_set_stale",
                    "selected member stale",
                ),
            ),
        )

    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", stale_selected)

    with pytest.raises(
        RetargetGraphError,
        match="selected spec is not a current included workspace member",
    ):
        finalize_retarget_graphs(
            workspace.root,
            workspace.selected_spec,
            baseline,
        )


@pytest.mark.unit
def test_finalization_rejects_new_workspace_error_without_selected_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    _restore_selected_for_finalization(workspace, monkeypatch)
    real_audit = audit_workspace_graph

    def new_workspace_error(root: Path, candidate) -> WorkspaceGraphAuditReport:
        report = real_audit(root, candidate)
        return WorkspaceGraphAuditReport(
            schema_version=report.schema_version,
            workspace_name=report.workspace_name,
            graph_hash=report.graph_hash,
            status="fail",
            members=report.members,
            findings=(
                *report.findings,
                WorkspaceGraphFinding(
                    "error",
                    "workspace_identity_stale",
                    "new workspace error",
                ),
            ),
        )

    monkeypatch.setattr(
        "echelon.spec_retarget_graph.audit_workspace_graph", new_workspace_error
    )

    with pytest.raises(RetargetGraphError, match="new workspace graph error"):
        finalize_retarget_graphs(
            workspace.root,
            workspace.selected_spec,
            baseline,
        )
    assert workspace_graph_path(workspace.root).is_file()
    assert workspace_graph_path(workspace.root).with_name(
        WORKSPACE_GRAPH_AUDIT_FILENAME
    ).is_file()


@pytest.mark.unit
def test_finalization_tolerates_unchanged_error_attributed_to_other_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)

    def other_unhealthy(root: Path, selector: str | Path) -> SpecGraphAuditReport:
        report = _live_audit(root, selector)
        if Path(selector).name != "002-other":
            return report
        return SpecGraphAuditReport(
            schema_version=1,
            spec_id=report.spec_id,
            graph_hash=report.graph_hash,
            status="fail",
            findings=(
                GraphFinding(
                    "error",
                    "requirement_verification_missing",
                    "pre-existing other-spec error",
                ),
            ),
        )

    monkeypatch.setattr("echelon.workspace_graph.audit_spec_graph", other_unhealthy)
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    assert baseline.workspace_status == "unavailable"
    assert baseline.workspace_finding_codes == ("member_graph_unhealthy:002-other",)
    _restore_selected_for_finalization(workspace, monkeypatch)

    receipt = finalize_retarget_graphs(
        workspace.root,
        workspace.selected_spec,
        baseline,
    )

    assert receipt.workspace_status == "fail"
    assert receipt.workspace_finding_codes == baseline.workspace_finding_codes


@pytest.mark.unit
def test_finalization_workspace_audit_failure_is_retryable_after_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    assert workspace.other_spec is not None
    other_graph_before = workspace.other_spec.joinpath(
        "spec-artifact-graph.json"
    ).read_bytes()
    other_audit_before = workspace.other_spec.joinpath(GRAPH_AUDIT_FILENAME).read_bytes()
    workspace.selected_spec.joinpath("spec.md").unlink()
    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    _restore_selected_for_finalization(workspace, monkeypatch)
    real_writer = write_workspace_graph_audit
    attempts = 0

    def fail_once(report: WorkspaceGraphAuditReport, root: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("workspace audit publication failed")
        return real_writer(report, root)

    monkeypatch.setattr(
        "echelon.spec_retarget_graph.write_workspace_graph_audit", fail_once
    )

    with pytest.raises(RetargetGraphError, match="workspace audit publication failed"):
        finalize_retarget_graphs(
            workspace.root,
            workspace.selected_spec,
            baseline,
        )
    assert workspace_graph_path(workspace.root).is_file()
    assert not workspace_graph_path(workspace.root).with_name(
        WORKSPACE_GRAPH_AUDIT_FILENAME
    ).exists()

    receipt = finalize_retarget_graphs(
        workspace.root,
        workspace.selected_spec,
        baseline,
    )

    assert attempts == 2
    assert receipt.workspace_status == "pass"
    assert workspace.other_spec.joinpath("spec-artifact-graph.json").read_bytes() == (
        other_graph_before
    )
    assert workspace.other_spec.joinpath(GRAPH_AUDIT_FILENAME).read_bytes() == (
        other_audit_before
    )


@pytest.mark.unit
@pytest.mark.parametrize("target_name", ["spec-artifact-graph.json", GRAPH_AUDIT_FILENAME])
def test_invalidation_rejects_symlinked_selected_graph_targets_without_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    target = workspace.selected_spec / target_name
    target.unlink()
    referent = tmp_path / f"outside-{target_name}"
    referent.write_bytes(b"outside-bytes\n")
    target.symlink_to(referent)
    workspace.selected_spec.joinpath("spec.md").unlink()
    workspace_before = workspace_graph_path(workspace.root).read_bytes()

    with pytest.raises(RetargetGraphError, match="regular file"):
        invalidate_retarget_graphs(workspace.root, workspace.selected_spec)

    assert target.is_symlink()
    assert referent.read_bytes() == b"outside-bytes\n"
    assert workspace_graph_path(workspace.root).read_bytes() == workspace_before


@pytest.mark.unit
def test_invalidation_rejects_symlinked_workspace_target_before_selected_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    selected_graph_before = workspace.selected_spec.joinpath(
        "spec-artifact-graph.json"
    ).read_bytes()
    workspace_target = workspace_graph_path(workspace.root)
    workspace_target.unlink()
    referent = tmp_path / "outside-workspace-graph.json"
    referent.write_bytes(b"outside-workspace\n")
    workspace_target.symlink_to(referent)
    workspace.selected_spec.joinpath("spec.md").unlink()

    with pytest.raises(RetargetGraphError, match="regular file"):
        invalidate_retarget_graphs(workspace.root, workspace.selected_spec)

    assert workspace.selected_spec.joinpath("spec-artifact-graph.json").read_bytes() == (
        selected_graph_before
    )
    assert workspace_target.is_symlink()
    assert referent.read_bytes() == b"outside-workspace\n"


@pytest.mark.unit
def test_retarget_graph_orchestration_never_invokes_broad_workspace_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.refresh_workspace_graph",
        lambda *args, **kwargs: pytest.fail("retarget graph called broad refresh"),
    )
    workspace.selected_spec.joinpath("spec.md").unlink()

    baseline = invalidate_retarget_graphs(workspace.root, workspace.selected_spec)
    _restore_selected_for_finalization(workspace, monkeypatch)
    receipt = finalize_retarget_graphs(
        workspace.root,
        workspace.selected_spec,
        baseline,
    )

    assert receipt.spec_status == "pass"
    assert receipt.workspace_status == "pass"


@pytest.mark.unit
def test_invalidation_rejects_workspace_publication_that_differs_from_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch, two_specs=True)
    workspace.selected_spec.joinpath("spec.md").unlink()

    def corrupt_writer(graph: object, root: Path) -> Path:
        path = workspace_graph_path(root)
        path.write_bytes(b"corrupt-workspace-graph\n")
        return path

    monkeypatch.setattr(
        "echelon.spec_retarget_graph.write_workspace_graph", corrupt_writer
    )

    with pytest.raises(
        RetargetGraphError,
        match="workspace graph publication does not match audit",
    ):
        invalidate_retarget_graphs(workspace.root, workspace.selected_spec)


@pytest.mark.unit
def test_unlink_outputs_fsyncs_success_before_later_unlink_failure_and_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = tmp_path / "spec-artifact-graph.json"
    audit = tmp_path / GRAPH_AUDIT_FILENAME
    unrelated = tmp_path / "unrelated.json"
    graph.write_bytes(b"graph\n")
    audit.write_bytes(b"audit\n")
    unrelated.write_bytes(b"unrelated\n")
    real_unlink = Path.unlink
    fsynced: list[Path] = []

    def fail_second(path: Path, *args: object, **kwargs: object) -> None:
        if path == audit:
            raise OSError("second unlink failed")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    monkeypatch.setattr(
        "echelon.spec_retarget_graph._fsync_directory",
        lambda path: fsynced.append(path),
    )

    with pytest.raises(OSError, match="second unlink failed"):
        _unlink_outputs((graph, audit))

    assert not graph.exists()
    assert audit.read_bytes() == b"audit\n"
    assert fsynced == [tmp_path, tmp_path]
    assert unrelated.read_bytes() == b"unrelated\n"

    fsynced.clear()
    monkeypatch.setattr(Path, "unlink", real_unlink)
    _unlink_outputs((graph, audit))

    assert fsynced == [tmp_path, tmp_path]
    assert not audit.exists()
    assert unrelated.read_bytes() == b"unrelated\n"


@pytest.mark.unit
def test_unlink_outputs_retries_directory_fsync_when_outputs_are_already_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = tmp_path / "workspace-artifact-graph.json"
    audit = tmp_path / WORKSPACE_GRAPH_AUDIT_FILENAME
    unrelated = tmp_path / "unrelated.json"
    graph.write_bytes(b"graph\n")
    audit.write_bytes(b"audit\n")
    unrelated.write_bytes(b"unrelated\n")
    attempts = 0

    def fail_first_fsync(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("directory fsync failed")

    monkeypatch.setattr(
        "echelon.spec_retarget_graph._fsync_directory", fail_first_fsync
    )

    with pytest.raises(OSError, match="directory fsync failed"):
        _unlink_outputs((graph, audit))

    assert not graph.exists()
    assert audit.read_bytes() == b"audit\n"
    assert unrelated.read_bytes() == b"unrelated\n"

    fsynced: list[Path] = []
    monkeypatch.setattr(
        "echelon.spec_retarget_graph._fsync_directory",
        lambda path: fsynced.append(path),
    )
    _unlink_outputs((graph, audit))

    assert fsynced == [tmp_path, tmp_path]
    assert not audit.exists()
    assert unrelated.read_bytes() == b"unrelated\n"
