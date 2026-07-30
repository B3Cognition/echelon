"""Freshness audit for the derived workspace artifact graph."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping

from echelon.spec_graph import GRAPH_SCHEMA_VERSION
from echelon.workspace_graph import (
    WorkspaceArtifactGraph,
    WorkspaceCompositionIssue,
    WorkspaceGraphBuildResult,
    WorkspaceGraphError,
    WorkspaceGraphMember,
    build_workspace_graph,
    load_workspace_graph_document,
    render_workspace_graph,
    workspace_graph_path,
)


WORKSPACE_GRAPH_AUDIT_FILENAME = "workspace-artifact-graph-audit.json"


@dataclass(frozen=True)
class WorkspaceGraphFinding:
    severity: str
    code: str
    message: str
    subject_id: str | None = None

    @property
    def id(self) -> str:
        return f"finding:{self.code}:{self.subject_id or 'workspace'}"

    def to_dict(self) -> dict[str, str]:
        payload = {
            "id": self.id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.subject_id is not None:
            payload["subject_id"] = self.subject_id
        return payload


@dataclass(frozen=True)
class WorkspaceGraphAuditReport:
    schema_version: int
    workspace_name: str
    graph_hash: str | None
    status: str
    members: tuple[WorkspaceGraphMember, ...]
    findings: tuple[WorkspaceGraphFinding, ...]
    recommendations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": "workspace",
            "workspace_name": self.workspace_name,
            "graph_hash": self.graph_hash,
            "status": self.status,
            "members": [member.to_dict() for member in self.members],
            "findings": [finding.to_dict() for finding in self.findings],
            "recommendations": list(self.recommendations),
        }


def audit_workspace_graph(
    project_root: Path,
    candidate: WorkspaceGraphBuildResult | None = None,
) -> WorkspaceGraphAuditReport:
    """Compare a workspace graph snapshot with fresh, read-only composition."""
    root = Path(project_root).resolve()
    reference, reference_issues, graph_hash, load_findings = _reference_graph(
        root, candidate
    )
    try:
        current = build_workspace_graph(root)
    except WorkspaceGraphError as exc:
        code, unavailable = _composition_failure(exc)
        return _report(
            workspace_name=reference.get("workspace_name", root.name),
            graph_hash=graph_hash,
            members=_members_from_document(reference),
            findings=[
                *load_findings,
                *_issue_findings(reference_issues),
                WorkspaceGraphFinding(
                    "error",
                    code,
                    f"canonical workspace composition is unavailable: {exc}",
                ),
            ],
            unavailable=unavailable,
        )

    findings = [*load_findings]
    findings.extend(_issue_findings(reference_issues))
    findings.extend(_compare_graphs(reference, current.graph))
    findings.extend(_issue_findings(current.issues))
    return _report(
        workspace_name=current.graph.workspace_name,
        graph_hash=graph_hash,
        members=current.graph.members,
        findings=findings,
        unavailable=not any(member.included for member in current.graph.members),
    )


def write_workspace_graph_audit(
    report: WorkspaceGraphAuditReport,
    project_root: Path,
) -> Path:
    """Atomically publish a deterministic workspace audit report."""
    path = workspace_graph_path(project_root).with_name(WORKSPACE_GRAPH_AUDIT_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return path


def _reference_graph(
    root: Path,
    candidate: WorkspaceGraphBuildResult | None,
) -> tuple[dict[str, object], tuple[WorkspaceCompositionIssue, ...], str | None, list[WorkspaceGraphFinding]]:
    if candidate is not None:
        return (
            candidate.graph.to_dict(),
            candidate.issues,
            _sha256(render_workspace_graph(candidate.graph)),
            [],
        )
    try:
        document = load_workspace_graph_document(root)
    except WorkspaceGraphError as exc:
        return (
            {},
            (),
            None,
            [WorkspaceGraphFinding("error", _load_code(exc), str(exc))],
        )
    if not _is_workspace_graph_document(document):
        return (
            {},
            (),
            None,
            [
                WorkspaceGraphFinding(
                    "error",
                    "workspace_graph_invalid",
                    "workspace graph document does not satisfy the workspace graph contract",
                )
            ],
        )
    return document, (), _sha256(workspace_graph_path(root).read_bytes()), []


def _load_code(exc: WorkspaceGraphError) -> str:
    return "workspace_graph_missing" if "is missing" in str(exc) else "workspace_graph_invalid"


def _composition_failure(exc: WorkspaceGraphError) -> tuple[str, bool]:
    message = str(exc)
    if "conflicting normalized" in message:
        return "workspace_identity_conflict", False
    if (
        "canonical workspace config" in message
        or "workspace config" in message
        or "workspace source" in message
        or "no canonical spec directories" in message
    ):
        return "workspace_discovery_unavailable", True
    return "workspace_composition_failed", False


def _is_workspace_graph_document(document: Mapping[str, object]) -> bool:
    required_strings = (
        "generator_version",
        "workspace_name",
        "source_set_digest",
        "member_state_digest",
    )
    required_lists = ("members", "inputs", "nodes", "edges")
    return all(isinstance(document.get(key), str) for key in required_strings) and all(
        isinstance(document.get(key), list) for key in required_lists
    )


def _compare_graphs(
    reference: Mapping[str, object],
    current: WorkspaceArtifactGraph,
) -> list[WorkspaceGraphFinding]:
    if not reference:
        return []
    findings: list[WorkspaceGraphFinding] = []
    old_members = _members_by_spec(reference.get("members", []))
    new_members = {member.spec_id: member for member in current.members}
    if (
        reference.get("source_set_digest") != current.source_set_digest
        or old_members.keys() != new_members.keys()
    ):
        findings.append(
            WorkspaceGraphFinding(
                "error",
                "workspace_source_set_stale",
                "workspace source-set digest differs from current canonical inputs",
            )
        )
    if reference.get("member_state_digest") != current.member_state_digest:
        findings.append(
            WorkspaceGraphFinding(
                "error",
                "workspace_member_state_stale",
                "workspace member-state digest differs from current member receipts",
            )
        )
    for spec_id in sorted(new_members.keys() - old_members.keys()):
        findings.append(
            WorkspaceGraphFinding(
                "error",
                "workspace_member_added",
                f"canonical spec was added after workspace graph composition: {spec_id}",
                f"spec:{spec_id}",
            )
        )
    for spec_id in sorted(old_members.keys() - new_members.keys()):
        findings.append(
            WorkspaceGraphFinding(
                "error",
                "workspace_member_removed",
                f"canonical spec was removed after workspace graph composition: {spec_id}",
                f"spec:{spec_id}",
            )
        )
    for spec_id in sorted(old_members.keys() & new_members.keys()):
        old = old_members[spec_id]
        new = new_members[spec_id]
        subject_id = f"spec:{spec_id}"
        if old.get("graph_hash") != new.graph_hash:
            findings.append(
                WorkspaceGraphFinding(
                    "error",
                    "workspace_member_graph_changed",
                    f"member graph bytes changed after workspace graph composition: {spec_id}",
                    subject_id,
                )
            )
        if old.get("audit_hash") != new.audit_hash or old.get("audit_status") != new.audit_status:
            findings.append(
                WorkspaceGraphFinding(
                    "error",
                    "workspace_member_audit_changed",
                    f"live member audit receipt changed after workspace graph composition: {spec_id}",
                    subject_id,
                )
            )
    return findings


def _members_by_spec(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item["spec_id"]): item
        for item in value
        if isinstance(item, dict) and isinstance(item.get("spec_id"), str)
    }


def _members_from_document(document: Mapping[str, object]) -> tuple[WorkspaceGraphMember, ...]:
    members = _members_by_spec(document.get("members", []))
    return tuple(
        WorkspaceGraphMember(
            spec_id=spec_id,
            path=str(member.get("path", "")),
            graph_hash=member.get("graph_hash") if isinstance(member.get("graph_hash"), str) else None,
            audit_hash=str(member.get("audit_hash", "")),
            audit_status=str(member.get("audit_status", "unavailable")),
            included=bool(member.get("included")),
            exclusion_reason=(
                member.get("exclusion_reason")
                if isinstance(member.get("exclusion_reason"), str)
                else None
            ),
        )
        for spec_id, member in sorted(members.items())
    )


def _issue_findings(
    issues: Iterable[WorkspaceCompositionIssue],
) -> list[WorkspaceGraphFinding]:
    return [
        WorkspaceGraphFinding(issue.severity, issue.code, issue.message, issue.subject_id)
        for issue in issues
    ]


def _report(
    *,
    workspace_name: object,
    graph_hash: str | None,
    members: tuple[WorkspaceGraphMember, ...],
    findings: Iterable[WorkspaceGraphFinding],
    unavailable: bool,
) -> WorkspaceGraphAuditReport:
    unique = {(finding.code, finding.subject_id): finding for finding in findings}
    ordered = tuple(sorted(unique.values(), key=lambda finding: finding.id))
    has_excluded_member = any(not member.included for member in members)
    if unavailable:
        status = "unavailable"
    elif has_excluded_member or any(finding.severity == "error" for finding in ordered):
        status = "fail"
    elif ordered:
        status = "warn"
    else:
        status = "pass"
    return WorkspaceGraphAuditReport(
        schema_version=GRAPH_SCHEMA_VERSION,
        workspace_name=str(workspace_name),
        graph_hash=graph_hash,
        status=status,
        members=tuple(sorted(members, key=lambda member: member.spec_id)),
        findings=ordered,
        recommendations=_recommendations(ordered),
    )


def _recommendations(findings: Iterable[WorkspaceGraphFinding]) -> tuple[str, ...]:
    if not tuple(findings):
        return ()
    return ("Run `echelon graph workspace refresh --write` to repair stale workspace state.",)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
