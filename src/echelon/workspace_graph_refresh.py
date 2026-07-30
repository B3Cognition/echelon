"""Bounded refresh orchestration for persisted workspace artifact graphs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.spec_frontmatter import read_frontmatter

from echelon.mempalace_audit import audit_spec_memory, cleanup_stale_spec_memory
from echelon.mempalace_re import audit_re_memory, mine_re_memory
from echelon.mempalace_requirements import SpecMemoryError, mine_spec_requirements
from echelon.mempalace_spec_evidence import (
    audit_spec_evidence_memory,
    load_spec_evidence_artifact_snapshots,
    mine_spec_evidence_memory,
)
from echelon.spec_graph import build_spec_graph, write_spec_graph
from echelon.spec_graph_audit import (
    audit_spec_graph,
    classify_spec_graph_audit,
    write_spec_graph_audit,
)
from echelon.workspace_graph import (
    WorkspaceGraphBuildResult,
    build_workspace_graph,
    discover_canonical_spec_dirs,
    write_workspace_graph,
)
from echelon.workspace_graph_audit import (
    WorkspaceGraphAuditReport,
    audit_workspace_graph,
    write_workspace_graph_audit,
)


_CURRENT_STATUSES = frozenset({"pass", "warn"})
_DOMAIN_ORDER = {
    "re_memory": 0,
    "evidence_memory": 1,
    "requirements_memory": 2,
    "spec_graph": 3,
}


@dataclass(frozen=True)
class WorkspaceGraphRefreshOutcome:
    """One deterministic member/domain refresh decision."""

    subject_id: str
    domain: str
    action: str
    status: str | None
    detail: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "subject_id": self.subject_id,
            "domain": self.domain,
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class WorkspaceGraphRefreshResult:
    candidate: WorkspaceGraphBuildResult
    report: WorkspaceGraphAuditReport
    outcomes: tuple[WorkspaceGraphRefreshOutcome, ...]


def refresh_workspace_graph(
    project_root: Path,
    *,
    write: bool,
) -> WorkspaceGraphRefreshResult:
    """Refresh stale upstream members only for an explicit write request."""
    root = Path(project_root).resolve()
    if not write:
        candidate = build_workspace_graph(root)
        return WorkspaceGraphRefreshResult(
            candidate=candidate,
            report=audit_workspace_graph(root, candidate),
            outcomes=(),
        )

    outcomes: list[WorkspaceGraphRefreshOutcome] = [_refresh_re_memory(root)]
    for spec_dir in discover_canonical_spec_dirs(root):
        spec_id = spec_dir.name
        outcomes.append(_refresh_requirements_memory(root, spec_id))
        outcomes.append(_refresh_evidence_memory(root, spec_dir))
        outcomes.append(_refresh_spec_graph(root, spec_dir))

    # Compose after per-spec writes so this candidate is derived from their exact bytes.
    candidate = build_workspace_graph(root)
    write_workspace_graph(candidate.graph, root)
    report = audit_workspace_graph(root, candidate)
    write_workspace_graph_audit(report, root)
    return WorkspaceGraphRefreshResult(
        candidate=candidate,
        report=report,
        outcomes=tuple(sorted(outcomes, key=_outcome_sort_key)),
    )


def _refresh_re_memory(root: Path) -> WorkspaceGraphRefreshOutcome:
    try:
        report = audit_re_memory(root)
    except SpecMemoryError as exc:
        if "published RE artifacts not found" in str(exc):
            return _outcome("workspace", "re_memory", "skipped", "not_applicable")
        return _failed("workspace", "re_memory", exc)
    except Exception as exc:
        return _failed("workspace", "re_memory", exc)
    if _is_current(report):
        return _outcome("workspace", "re_memory", "skipped", _status(report))
    try:
        mine_re_memory(root, run_id="workspace-graph-refresh")
        refreshed = audit_re_memory(root)
    except Exception as exc:
        return _failed("workspace", "re_memory", exc)
    return _outcome("workspace", "re_memory", "refreshed", _status(refreshed))


def _refresh_requirements_memory(root: Path, spec_id: str) -> WorkspaceGraphRefreshOutcome:
    try:
        report = audit_spec_memory(root, spec_id)
    except Exception as exc:
        return _failed(spec_id, "requirements_memory", exc)
    if _is_current(report):
        return _outcome(spec_id, "requirements_memory", "skipped", _status(report))
    cleanup_detail: str | None = None
    try:
        mine_report = mine_spec_requirements(
            root, spec_id, run_id="workspace-graph-refresh"
        )
        if _status(mine_report) == "complete":
            try:
                cleanup_stale_spec_memory(root, spec_id)
            except Exception as exc:
                cleanup_detail = f"cleanup_skipped:{type(exc).__name__}"
        refreshed = audit_spec_memory(root, spec_id)
    except Exception as exc:
        return _failed(spec_id, "requirements_memory", exc)
    return _outcome(
        spec_id,
        "requirements_memory",
        "refreshed",
        _status(refreshed),
        cleanup_detail,
    )


def _refresh_evidence_memory(
    root: Path,
    spec_dir: Path,
) -> WorkspaceGraphRefreshOutcome:
    spec_id = spec_dir.name
    try:
        applicable = _evidence_is_applicable(root, spec_dir)
    except Exception as exc:
        return _failed(spec_id, "evidence_memory", exc)
    if not applicable:
        return _outcome(spec_id, "evidence_memory", "skipped", "not_applicable")
    try:
        report = audit_spec_evidence_memory(root, spec_id, allow_unlanded=False)
    except Exception as exc:
        return _failed(spec_id, "evidence_memory", exc)
    if _is_current(report):
        return _outcome(spec_id, "evidence_memory", "skipped", _status(report))
    try:
        mine_spec_evidence_memory(
            root,
            spec_id,
            run_id="workspace-graph-refresh",
            allow_unlanded=False,
        )
        refreshed = audit_spec_evidence_memory(root, spec_id, allow_unlanded=False)
    except Exception as exc:
        return _failed(spec_id, "evidence_memory", exc)
    return _outcome(spec_id, "evidence_memory", "refreshed", _status(refreshed))


def _refresh_spec_graph(root: Path, spec_dir: Path) -> WorkspaceGraphRefreshOutcome:
    spec_id = spec_dir.name
    try:
        report = audit_spec_graph(root, spec_id)
    except Exception as exc:
        return _failed(spec_id, "spec_graph", exc)
    classification = classify_spec_graph_audit(report)
    if classification == "current":
        return _outcome(spec_id, "spec_graph", "skipped", _status(report))
    if classification != "stale":
        return _outcome(
            spec_id,
            "spec_graph",
            "skipped",
            _status(report),
            (
                "source_unavailable"
                if classification == "unavailable"
                else "non_rebuildable"
            ),
        )
    try:
        graph = build_spec_graph(root, spec_id)
        write_spec_graph(graph, spec_dir)
        refreshed = audit_spec_graph(root, spec_id)
        write_spec_graph_audit(refreshed, spec_dir)
    except Exception as exc:
        return _failed(spec_id, "spec_graph", exc)
    return _outcome(spec_id, "spec_graph", "refreshed", _status(refreshed))


def _evidence_is_applicable(root: Path, spec_dir: Path) -> bool:
    """Evidence belongs only to landed specs with canonical published inputs."""
    status = str(read_frontmatter(spec_dir).get("status") or "").strip().lower()
    if status != "landed":
        return False
    return bool(load_spec_evidence_artifact_snapshots(root, spec_dir.name))


def _is_current(report: object) -> bool:
    return _status(report) in _CURRENT_STATUSES


def _status(report: object) -> str | None:
    value = getattr(report, "status", None)
    return value if isinstance(value, str) else None


def _outcome(
    subject_id: str,
    domain: str,
    action: str,
    status: str | None,
    detail: str | None = None,
) -> WorkspaceGraphRefreshOutcome:
    return WorkspaceGraphRefreshOutcome(subject_id, domain, action, status, detail)


def _failed(subject_id: str, domain: str, exc: Exception) -> WorkspaceGraphRefreshOutcome:
    return _outcome(subject_id, domain, "failed", None, type(exc).__name__)


def _outcome_sort_key(outcome: WorkspaceGraphRefreshOutcome) -> tuple[int, str, int]:
    return (
        0 if outcome.subject_id == "workspace" else 1,
        outcome.subject_id,
        _DOMAIN_ORDER[outcome.domain],
    )
