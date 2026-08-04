from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from echelon.spec_graph import (
    GraphEdge,
    GraphInput,
    GraphNode,
    SpecArtifactGraph,
    render_spec_graph,
)
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
    member_source_set_digest: str | None = "sha256:member-source",
    member_memory_state_digest: str | None = "sha256:member-memory",
    audit_hash: str = "sha256:audit",
    audit_status: str = "pass",
    included: bool = True,
    exclusion_reason: str = "member_graph_stale",
    inputs: tuple[GraphInput, ...] = (),
    issues: tuple[WorkspaceCompositionIssue, ...] = (),
) -> WorkspaceGraphBuildResult:
    member = WorkspaceGraphMember(
        spec_id=spec_id,
        graph_path=f"specs/{spec_id}/spec-artifact-graph.json",
        graph_hash=graph_hash,
        member_source_set_digest=member_source_set_digest,
        member_memory_state_digest=member_memory_state_digest,
        audit_hash=audit_hash,
        audit_status=audit_status,
        included=included,
        exclusion_reason=None if included else exclusion_reason,
    )
    graph = WorkspaceArtifactGraph(
        workspace_name="workspace",
        generator_version="test",
        members=(member,),
        inputs=inputs,
        nodes=(
            GraphNode("workspace:current", "Workspace", {"workspace_name": "workspace"}),
            GraphNode(
                f"spec:{spec_id}",
                "Spec",
                {
                    "spec_id": spec_id,
                    "composition_status": "included" if included else "excluded",
                    "member_audit_status": audit_status,
                    **({} if included else {"exclusion_reason": exclusion_reason}),
                },
            ),
        ),
        edges=(
            GraphEdge("workspace:current", "CONTAINS_SPEC", f"spec:{spec_id}", {}),
        ),
    )
    return WorkspaceGraphBuildResult(graph=graph, issues=issues)


def _write_real_workspace(root: Path) -> Path:
    source = root / "apps" / "app"
    source.mkdir(parents=True)
    config_path = root / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace": {"git_role": "orchestration"},
                "sources": [{"id": "app", "path": "apps/app"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec_dir = root / "specs" / "001-alpha"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "---\nsupersedes: 000-old\n---\n# alpha\n",
        encoding="utf-8",
    )
    spec_dir.joinpath("targets.yml").write_text(
        "targets:\n  - id: app\n    path: apps/app\n",
        encoding="utf-8",
    )
    graph = SpecArtifactGraph(
        spec_id="001-alpha",
        generator_version="test",
        inputs=(),
        nodes=(GraphNode("spec:001-alpha", "Spec", {"spec_id": "001-alpha"}),),
        edges=(),
        memory_receipts=(),
    )
    spec_dir.joinpath("spec-artifact-graph.json").write_bytes(render_spec_graph(graph))
    return spec_dir


def _current_member_audit(spec_dir: Path) -> SimpleNamespace:
    graph_bytes = spec_dir.joinpath("spec-artifact-graph.json").read_bytes()
    graph_hash = f"sha256:{hashlib.sha256(graph_bytes).hexdigest()}"
    return SimpleNamespace(
        status="pass",
        graph_hash=graph_hash,
        to_dict=lambda: {"schema_version": 1, "status": "pass", "graph_hash": graph_hash},
    )


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
def test_unhealthy_member_recommends_spec_repair_without_futile_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unhealthy = _candidate(
        audit_status="fail",
        included=False,
        exclusion_reason="member_graph_unhealthy",
        issues=(
            WorkspaceCompositionIssue(
                "error",
                "member_graph_unhealthy",
                "spec member is excluded from workspace composition: 001-alpha",
                "spec:001-alpha",
            ),
        ),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: unhealthy,
    )

    report = audit_workspace_graph(tmp_path, candidate=unhealthy)

    assert report.status == "unavailable"
    assert report.recommendations == (
        "Inspect affected specs with `echelon graph audit <spec> --json` and repair "
        "the reported findings.",
    )


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
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["nodes"].append(dict(payload["nodes"][0])),
        lambda payload: payload["edges"].append(
            {
                "source": "missing",
                "type": "BROKEN",
                "target": "spec:001-alpha",
                "properties": {},
            }
        ),
        lambda payload: payload.update({"members": [{"spec_id": "001-alpha"}]}),
    ],
)
def test_audit_rejects_invalid_persisted_graph_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    current = _candidate()
    write_workspace_graph(current.graph, tmp_path)
    path = workspace_graph_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert report.status == "fail"
    assert [finding.code for finding in report.findings] == ["workspace_graph_invalid"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"source_set_digest": "sha256:tampered"}),
        lambda payload: payload["members"][0].update({"graph_hash": None}),
        lambda payload: payload["nodes"].pop(),
        lambda payload: payload["nodes"][0].update({"id": "workspace:other"}),
    ],
)
def test_audit_rejects_tampered_persisted_receipts_and_workspace_coherence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    current = _candidate()
    write_workspace_graph(current.graph, tmp_path)
    path = workspace_graph_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert report.status == "fail"
    assert [finding.code for finding in report.findings] == ["workspace_graph_invalid"]


@pytest.mark.unit
def test_audit_rejects_tampered_persisted_member_state_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _candidate()
    write_workspace_graph(current.graph, tmp_path)
    path = workspace_graph_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["member_state_digest"] = "sha256:tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert report.status == "fail"
    assert [finding.code for finding in report.findings] == ["workspace_graph_invalid"]


@pytest.mark.unit
def test_audit_reports_tampered_persisted_workspace_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _candidate()
    write_workspace_graph(current.graph, tmp_path)
    path = workspace_graph_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["workspace_name"] = "tampered-workspace"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert [finding.code for finding in report.findings] == ["workspace_identity_stale"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["nodes"][0]["properties"].update({"title": "tampered"}),
        lambda payload: payload["edges"][0]["properties"].update({"title": "tampered"}),
    ],
)
def test_audit_reports_valid_but_stale_workspace_graph_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    current = _candidate()
    write_workspace_graph(current.graph, tmp_path)
    path = workspace_graph_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert [finding.code for finding in report.findings] == ["workspace_graph_body_stale"]


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
        "workspace_graph_body_stale",
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
def test_audit_reports_member_source_and_memory_receipt_staleness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _candidate()
    write_workspace_graph(stored.graph, tmp_path)
    current = _candidate(
        member_source_set_digest="sha256:new-source",
        member_memory_state_digest="sha256:new-memory",
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert {finding.code for finding in report.findings} == {
        "workspace_member_source_set_stale",
        "workspace_member_memory_state_stale",
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
@pytest.mark.parametrize(
    "path",
    ["specs/001-alpha/spec.md", "specs/001-alpha/targets.yml"],
)
def test_audit_reports_workspace_metadata_source_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    stored = _candidate(
        inputs=(GraphInput(path, "sha256:old", "workspace_metadata", True),)
    )
    write_workspace_graph(stored.graph, tmp_path)
    current = _candidate(
        inputs=(GraphInput(path, "sha256:new", "workspace_metadata", True),)
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: current
    )

    report = audit_workspace_graph(tmp_path)

    assert [finding.code for finding in report.findings] == ["workspace_source_set_stale"]


@pytest.mark.unit
def test_audit_detects_real_spec_and_targets_relationship_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_dir = _write_real_workspace(tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph.audit_spec_graph",
        lambda root, selector: _current_member_audit(Path(selector)),
    )
    from echelon.workspace_graph import build_workspace_graph

    write_workspace_graph(build_workspace_graph(tmp_path).graph, tmp_path)
    original_member_bytes = spec_dir.joinpath("spec-artifact-graph.json").read_bytes()
    original_config_bytes = (tmp_path / ".echelon" / "config.yml").read_bytes()

    spec_dir.joinpath("spec.md").write_text(
        "---\nsupersedes: 001-alpha\n---\n# alpha\n",
        encoding="utf-8",
    )
    spec_report = audit_workspace_graph(tmp_path)
    write_workspace_graph(build_workspace_graph(tmp_path).graph, tmp_path)
    spec_dir.joinpath("targets.yml").write_text(
        "targets:\n  - id: missing\n    path: missing\n",
        encoding="utf-8",
    )
    targets_report = audit_workspace_graph(tmp_path)

    assert "workspace_source_set_stale" in {
        finding.code for finding in spec_report.findings
    }
    assert "workspace_source_set_stale" in {
        finding.code for finding in targets_report.findings
    }
    assert spec_dir.joinpath("spec-artifact-graph.json").read_bytes() == original_member_bytes
    assert (tmp_path / ".echelon" / "config.yml").read_bytes() == original_config_bytes


@pytest.mark.unit
def test_included_warn_member_produces_workspace_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = _candidate(audit_status="warn", audit_hash="sha256:warning")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: warning
    )

    report = audit_workspace_graph(tmp_path, candidate=warning)

    assert report.status == "warn"
    assert [(finding.code, finding.subject_id) for finding in report.findings] == [
        ("workspace_member_audit_warning", "spec:001-alpha")
    ]


@pytest.mark.unit
def test_candidate_audit_hash_and_comparison_use_one_rendered_byte_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    rendered = candidate.graph.to_dict()
    rendered["nodes"][0]["properties"]["title"] = "captured"
    captured_bytes = (json.dumps(rendered, indent=2, sort_keys=True) + "\n").encode("utf-8")
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.render_workspace_graph",
        lambda graph: captured_bytes,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph", lambda project_root: candidate
    )

    report = audit_workspace_graph(tmp_path, candidate=candidate)

    assert report.graph_hash == f"sha256:{hashlib.sha256(captured_bytes).hexdigest()}"
    assert [finding.code for finding in report.findings] == ["workspace_graph_body_stale"]


@pytest.mark.unit
def test_final_member_removal_is_unavailable_and_keeps_member_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _candidate()
    write_workspace_graph(stored.graph, tmp_path)
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: (_ for _ in ()).throw(
            WorkspaceGraphError("no canonical spec directories were found")
        ),
    )

    report = audit_workspace_graph(tmp_path)

    assert report.status == "unavailable"
    assert {finding.code for finding in report.findings} == {
        "workspace_discovery_unavailable",
        "workspace_member_removed",
    }


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


@pytest.mark.unit
def test_repeated_audit_and_failed_audit_write_preserve_deterministic_bytes(
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
    first = audit_workspace_graph(tmp_path, candidate=current)
    second = audit_workspace_graph(tmp_path, candidate=current)
    path = write_workspace_graph_audit(first, tmp_path)
    previous = path.read_bytes()

    monkeypatch.setattr(
        "echelon.workspace_graph_audit.os.replace",
        lambda source, target: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        write_workspace_graph_audit(second, tmp_path)

    assert first.to_dict() == second.to_dict()
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


@pytest.mark.unit
def test_write_workspace_audit_rejects_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _candidate()
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: current,
    )
    report = audit_workspace_graph(tmp_path, candidate=current)
    path = workspace_graph_path(tmp_path).with_name(WORKSPACE_GRAPH_AUDIT_FILENAME)
    path.parent.mkdir(parents=True)
    referent = tmp_path / "outside-audit.json"
    referent.write_bytes(b"outside\n")
    path.symlink_to(referent)

    with pytest.raises(OSError, match="regular file"):
        write_workspace_graph_audit(report, tmp_path)

    assert path.is_symlink()
    assert referent.read_bytes() == b"outside\n"


@pytest.mark.unit
def test_write_workspace_audit_rejects_earlier_symlinked_ancestor(
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
    current = _candidate()
    monkeypatch.setattr(
        "echelon.workspace_graph_audit.build_workspace_graph",
        lambda project_root: current,
    )
    report = audit_workspace_graph(root, candidate=current)
    external_target = outside_graph / WORKSPACE_GRAPH_AUDIT_FILENAME
    external_target.write_bytes(b"external-before\n")
    temp_calls: list[object] = []

    def unexpected_temp(*args: object, **kwargs: object) -> object:
        temp_calls.append((args, kwargs))
        raise AssertionError("temporary creation must not run")

    monkeypatch.setattr(
        "echelon.workspace_graph_audit.tempfile.NamedTemporaryFile",
        unexpected_temp,
    )

    with pytest.raises(OSError, match="ancestor must be a real directory"):
        write_workspace_graph_audit(report, root)

    assert temp_calls == []
    assert external_target.read_bytes() == b"external-before\n"
