from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class _Report:
    status: str


@dataclass(frozen=True)
class _MineReport:
    status: str


@dataclass(frozen=True)
class _Candidate:
    graph: object


@pytest.mark.unit
def test_write_refresh_mines_shared_re_once_and_skips_current_domains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import refresh_workspace_graph

    specs = (tmp_path / "specs" / "001-alpha", tmp_path / "specs" / "002-beta")
    for spec_dir in specs:
        spec_dir.mkdir(parents=True)
    calls: list[str] = []

    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.discover_canonical_spec_dirs",
        lambda root: specs,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory",
        lambda root: calls.append("audit-re") or _Report("fail"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_re_memory",
        lambda root, *, run_id: calls.append("mine-re") or _MineReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory",
        lambda root, selector: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_evidence_memory",
        lambda root, selector, *, allow_unlanded=False: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh._evidence_is_applicable",
        lambda root, spec_dir: True,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_graph",
        lambda root, selector: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_workspace_graph",
        lambda root: _Candidate(graph=object()),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_workspace_graph",
        lambda root, candidate: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph",
        lambda graph, root: calls.append("write-workspace"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph_audit",
        lambda report, root: calls.append("write-audit"),
    )

    result = refresh_workspace_graph(tmp_path, write=True)

    assert calls == ["audit-re", "mine-re", "audit-re", "write-workspace", "write-audit"]
    assert [(item.subject_id, item.domain, item.action) for item in result.outcomes] == [
        ("workspace", "re_memory", "refreshed"),
        ("001-alpha", "evidence_memory", "skipped"),
        ("001-alpha", "requirements_memory", "skipped"),
        ("001-alpha", "spec_graph", "skipped"),
        ("002-beta", "evidence_memory", "skipped"),
        ("002-beta", "requirements_memory", "skipped"),
        ("002-beta", "spec_graph", "skipped"),
    ]


@pytest.mark.unit
def test_write_refresh_continues_after_member_failure_and_uses_final_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import refresh_workspace_graph

    specs = (tmp_path / "specs" / "001-alpha", tmp_path / "specs" / "002-beta")
    for spec_dir in specs:
        spec_dir.mkdir(parents=True)
    candidate = _Candidate(graph=object())
    audited: list[object] = []
    built: list[str] = []
    composed_bytes: list[bytes] = []

    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.discover_canonical_spec_dirs",
        lambda root: specs,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory",
        lambda root: (_ for _ in ()).throw(RuntimeError("no RE")),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory",
        lambda root, selector: _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh._evidence_is_applicable",
        lambda root, spec_dir: False,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_graph",
        lambda root, selector: _Report("fail"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_spec_graph",
        lambda root, selector: (
            (_ for _ in ()).throw(RuntimeError("broken alpha"))
            if str(selector) == "001-alpha"
            else built.append(str(selector)) or b"fresh-beta"
        ),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_spec_graph",
        lambda graph, spec_dir: (spec_dir / "spec-artifact-graph.json").write_bytes(graph),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_spec_graph_audit",
        lambda report, spec_dir: None,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_workspace_graph",
        lambda root: composed_bytes.append(
            (specs[1] / "spec-artifact-graph.json").read_bytes()
        ) or candidate,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph",
        lambda graph, root: None,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_workspace_graph",
        lambda root, candidate: audited.append(candidate) or _Report("fail"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph_audit",
        lambda report, root: None,
    )

    result = refresh_workspace_graph(tmp_path, write=True)

    assert built == ["002-beta"]
    assert composed_bytes == [b"fresh-beta"]
    assert audited == [candidate]
    assert result.report.status == "fail"
    assert any(
        outcome.subject_id == "001-alpha" and outcome.domain == "spec_graph" and outcome.action == "failed"
        for outcome in result.outcomes
    )


@pytest.mark.unit
def test_second_write_refresh_is_a_no_op_for_current_upstream_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import refresh_workspace_graph

    spec_dir = tmp_path / "specs" / "001-alpha"
    spec_dir.mkdir(parents=True)
    calls: list[str] = []
    re_statuses = iter(("fail", "pass", "pass"))
    requirements_statuses = iter(("fail", "pass", "pass"))
    graph_statuses = iter(("fail", "pass", "pass"))
    candidate = _Candidate(graph=object())

    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.discover_canonical_spec_dirs",
        lambda root: (spec_dir,),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory",
        lambda root: calls.append("audit-re") or _Report(next(re_statuses)),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_re_memory",
        lambda root, *, run_id: calls.append("mine-re") or _MineReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory",
        lambda root, selector: calls.append("audit-requirements")
        or _Report(next(requirements_statuses)),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_spec_requirements",
        lambda root, selector, *, run_id: calls.append("mine-requirements") or _MineReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.cleanup_stale_spec_memory",
        lambda root, selector: calls.append("cleanup"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh._evidence_is_applicable",
        lambda root, spec_dir: True,
    )
    evidence_statuses = iter(("fail", "pass", "pass"))
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_evidence_memory",
        lambda root, selector, *, allow_unlanded=False: calls.append("audit-evidence")
        or _Report(next(evidence_statuses)),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_spec_evidence_memory",
        lambda root, selector, *, run_id, allow_unlanded=False: calls.append("mine-evidence")
        or _MineReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_graph",
        lambda root, selector: calls.append("audit-graph")
        or _Report(next(graph_statuses)),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_spec_graph",
        lambda root, selector: calls.append("build-graph") or object(),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_spec_graph",
        lambda graph, spec_dir: calls.append("write-graph"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_spec_graph_audit",
        lambda report, spec_dir: calls.append("write-graph-audit"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_workspace_graph",
        lambda root: calls.append("compose") or candidate,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph",
        lambda graph, root: calls.append("write-workspace"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_workspace_graph",
        lambda root, candidate: calls.append("audit-workspace") or _Report("pass"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.write_workspace_graph_audit",
        lambda report, root: calls.append("write-workspace-audit"),
    )

    refresh_workspace_graph(tmp_path, write=True)
    refresh_workspace_graph(tmp_path, write=True)

    assert calls == [
        "audit-re",
        "mine-re",
        "audit-re",
        "audit-requirements",
        "mine-requirements",
        "cleanup",
        "audit-requirements",
        "audit-evidence",
        "mine-evidence",
        "audit-evidence",
        "audit-graph",
        "build-graph",
        "write-graph",
        "audit-graph",
        "write-graph-audit",
        "compose",
        "write-workspace",
        "audit-workspace",
        "write-workspace-audit",
        "audit-re",
        "audit-requirements",
        "audit-evidence",
        "audit-graph",
        "compose",
        "write-workspace",
        "audit-workspace",
        "write-workspace-audit",
    ]


@pytest.mark.unit
def test_requirements_cleanup_failure_still_reaudits_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import _refresh_requirements_memory

    reports = iter((_Report("fail"), _Report("pass")))
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_spec_memory",
        lambda root, selector: next(reports),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_spec_requirements",
        lambda root, selector, *, run_id: _MineReport("complete"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.cleanup_stale_spec_memory",
        lambda root, selector: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    outcome = _refresh_requirements_memory(tmp_path, "001-alpha")

    assert outcome.action == "refreshed"
    assert outcome.status == "pass"
    assert outcome.detail == "cleanup_skipped:RuntimeError"


@pytest.mark.unit
def test_evidence_is_not_applicable_to_unlanded_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import _evidence_is_applicable

    spec_dir = tmp_path / "specs" / "001-alpha"
    spec_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.read_frontmatter",
        lambda spec_dir: {"status": "phase_a"},
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.load_spec_evidence_artifact_snapshots",
        lambda root, selector: pytest.fail("unlanded specs must not inspect evidence"),
    )

    assert _evidence_is_applicable(tmp_path, spec_dir) is False


@pytest.mark.unit
def test_missing_published_re_is_a_skipped_shared_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.workspace_graph_refresh import _refresh_re_memory

    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_re_memory",
        lambda root: (_ for _ in ()).throw(
            SpecMemoryError("published RE artifacts not found; publish first")
        ),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.mine_re_memory",
        lambda *args, **kwargs: pytest.fail("missing published RE must not mine"),
    )

    outcome = _refresh_re_memory(tmp_path)

    assert (outcome.action, outcome.status) == ("skipped", "not_applicable")


@pytest.mark.unit
def test_dry_refresh_has_no_upstream_or_persisted_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.workspace_graph_refresh import refresh_workspace_graph

    candidate = object()
    for target in (
        "mine_spec_requirements",
        "mine_re_memory",
        "mine_spec_evidence_memory",
        "build_spec_graph",
    ):
        monkeypatch.setattr(
            f"echelon.workspace_graph_refresh.{target}",
            lambda *args, **kwargs: pytest.fail(f"dry refresh invoked {target}"),
        )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.discover_canonical_spec_dirs",
        lambda root: pytest.fail("dry refresh must not discover refresh members"),
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.build_workspace_graph",
        lambda root: candidate,
    )
    monkeypatch.setattr(
        "echelon.workspace_graph_refresh.audit_workspace_graph",
        lambda root, candidate: _Report("warn"),
    )

    result = refresh_workspace_graph(tmp_path, write=False)

    assert result.candidate is candidate
    assert result.report.status == "warn"
    assert result.outcomes == ()
