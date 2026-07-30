"""Freshness audit for the derived workspace artifact graph."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping

from echelon.spec_graph import (
    GRAPH_SCHEMA_VERSION,
    GraphEdge,
    GraphInput,
    GraphNode,
    SpecGraphError,
    _validate_graph,
)
from echelon.workspace_graph import (
    WorkspaceArtifactGraph,
    WorkspaceCompositionIssue,
    WorkspaceGraphBuildResult,
    WorkspaceGraphError,
    WorkspaceGraphMember,
    build_workspace_graph,
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
        members = _members_from_document(reference)
        return _report(
            workspace_name=reference.get("workspace_name", root.name),
            graph_hash=graph_hash,
            members=members,
            findings=[
                *load_findings,
                *_issue_findings(reference_issues),
                *(
                    _removed_member_findings(members)
                    if _canonical_members_were_removed(exc)
                    else []
                ),
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
    findings.extend(_member_audit_findings(current.graph.members))
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
) -> tuple[
    dict[str, object],
    tuple[WorkspaceCompositionIssue, ...],
    str | None,
    list[WorkspaceGraphFinding],
]:
    if candidate is not None:
        graph_bytes = render_workspace_graph(candidate.graph)
        document, _ = _parse_workspace_graph_document(graph_bytes)
        return (
            document,
            candidate.issues,
            _sha256(graph_bytes),
            [],
        )
    path = workspace_graph_path(root)
    try:
        graph_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        return (
            {},
            (),
            None,
            [
                WorkspaceGraphFinding(
                    "error",
                    "workspace_graph_missing",
                    f"workspace graph artifact is missing: {path}",
                )
            ],
        )
    except OSError as exc:
        return (
            {},
            (),
            None,
            [
                WorkspaceGraphFinding(
                    "error",
                    "workspace_graph_invalid",
                    f"workspace graph artifact is unreadable: {path}",
                )
            ],
        )
    try:
        document, _ = _parse_workspace_graph_document(graph_bytes)
    except WorkspaceGraphError:
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
    return document, (), _sha256(graph_bytes), []


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


def _canonical_members_were_removed(exc: WorkspaceGraphError) -> bool:
    return "no canonical spec directories" in str(exc)


def _parse_workspace_graph_document(
    graph_bytes: bytes,
) -> tuple[dict[str, object], WorkspaceArtifactGraph]:
    try:
        document = json.loads(graph_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceGraphError("workspace graph JSON is malformed") from exc
    if not isinstance(document, dict) or not _is_workspace_graph_document(document):
        raise WorkspaceGraphError("workspace graph document is invalid")
    try:
        nodes = tuple(_parse_node(item) for item in document["nodes"])
        edges = tuple(_parse_edge(item) for item in document["edges"])
        _validate_graph(nodes, edges)
        inputs = _parse_inputs(document["inputs"])
        members = _parse_members(document["members"])
        graph = WorkspaceArtifactGraph(
            workspace_name=document["workspace_name"],
            generator_version=document["generator_version"],
            members=members,
            inputs=inputs,
            nodes=nodes,
            edges=edges,
        )
        if document["source_set_digest"] != graph.source_set_digest:
            raise ValueError("workspace source-set digest")
        if document["member_state_digest"] != graph.member_state_digest:
            raise ValueError("workspace member-state digest")
        _validate_workspace_node_coherence(graph)
    except (KeyError, TypeError, ValueError, SpecGraphError) as exc:
        raise WorkspaceGraphError("workspace graph document is invalid") from exc
    return document, graph


def _is_workspace_graph_document(document: Mapping[str, object]) -> bool:
    required_strings = (
        "generator_version",
        "workspace_name",
        "source_set_digest",
        "member_state_digest",
    )
    required_lists = ("members", "inputs", "nodes", "edges")
    return (
        document.get("schema_version") == GRAPH_SCHEMA_VERSION
        and document.get("scope") == "workspace"
        and all(isinstance(document.get(key), str) for key in required_strings)
        and all(
            isinstance(document.get(key), list) for key in required_lists
        )
    )


def _parse_node(value: object) -> GraphNode:
    if not isinstance(value, dict):
        raise ValueError("workspace node")
    node_id = value.get("id")
    node_type = value.get("type")
    properties = value.get("properties")
    if (
        not isinstance(node_id, str)
        or not isinstance(node_type, str)
        or not isinstance(properties, dict)
    ):
        raise ValueError("workspace node")
    return GraphNode(node_id, node_type, properties)


def _parse_edge(value: object) -> GraphEdge:
    if not isinstance(value, dict):
        raise ValueError("workspace edge")
    source = value.get("source")
    edge_type = value.get("type")
    target = value.get("target")
    properties = value.get("properties")
    if not all(
        isinstance(item, str) for item in (source, edge_type, target)
    ) or not isinstance(properties, dict):
        raise ValueError("workspace edge")
    return GraphEdge(source, edge_type, target, properties)


def _parse_inputs(value: object) -> tuple[GraphInput, ...]:
    if not isinstance(value, list):
        raise ValueError("workspace inputs")
    inputs: list[GraphInput] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("workspace input")
        path = item.get("path")
        digest = item.get("hash")
        role = item.get("role")
        required = item.get("required")
        if not all(
            isinstance(field, str) for field in (path, digest, role)
        ) or not isinstance(required, bool):
            raise ValueError("workspace input")
        status = item.get("status")
        source_set_digest = item.get("source_set_digest")
        if status is not None and not isinstance(status, str):
            raise ValueError("workspace input")
        if source_set_digest is not None and not isinstance(source_set_digest, str):
            raise ValueError("workspace input")
        inputs.append(GraphInput(path, digest, role, required, status, source_set_digest))
    identities = [(item.role, item.path) for item in inputs]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate workspace input")
    return tuple(inputs)


def _parse_members(value: object) -> tuple[WorkspaceGraphMember, ...]:
    if not isinstance(value, list):
        raise ValueError("workspace members")
    spec_ids: set[str] = set()
    graph_paths: set[str] = set()
    members: list[WorkspaceGraphMember] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("workspace member")
        spec_id = item.get("spec_id")
        graph_path = item.get("graph_path")
        graph_hash = item.get("graph_hash")
        source_set_digest = item.get("member_source_set_digest")
        memory_state_digest = item.get("member_memory_state_digest")
        audit_hash = item.get("audit_hash")
        audit_status = item.get("audit_status")
        included = item.get("included")
        if (
            not isinstance(spec_id, str)
            or not spec_id
            or not isinstance(graph_path, str)
            or not graph_path
            or (graph_hash is not None and not isinstance(graph_hash, str))
            or (
                source_set_digest is not None
                and not isinstance(source_set_digest, str)
            )
            or (
                memory_state_digest is not None
                and not isinstance(memory_state_digest, str)
            )
            or not isinstance(audit_hash, str)
            or not isinstance(audit_status, str)
            or audit_status not in {"pass", "warn", "fail", "unavailable"}
            or not isinstance(included, bool)
        ):
            raise ValueError("workspace member")
        exclusion_reason = item.get("exclusion_reason")
        if exclusion_reason is not None and not isinstance(exclusion_reason, str):
            raise ValueError("workspace member")
        if included:
            if (
                not isinstance(graph_hash, str)
                or not isinstance(source_set_digest, str)
                or not isinstance(memory_state_digest, str)
                or audit_status not in {"pass", "warn"}
                or exclusion_reason is not None
            ):
                raise ValueError("included workspace member")
        elif not isinstance(exclusion_reason, str) or not exclusion_reason:
            raise ValueError("excluded workspace member")
        if spec_id in spec_ids or graph_path in graph_paths:
            raise ValueError("duplicate workspace member")
        spec_ids.add(spec_id)
        graph_paths.add(graph_path)
        members.append(
            WorkspaceGraphMember(
                spec_id=spec_id,
                graph_path=graph_path,
                graph_hash=graph_hash,
                member_source_set_digest=source_set_digest,
                member_memory_state_digest=memory_state_digest,
                audit_hash=audit_hash,
                audit_status=audit_status,
                included=included,
                exclusion_reason=exclusion_reason,
            )
        )
    return tuple(members)


def _validate_workspace_node_coherence(graph: WorkspaceArtifactGraph) -> None:
    workspace_nodes = [node for node in graph.nodes if node.id == "workspace:current"]
    if len(workspace_nodes) != 1 or workspace_nodes[0].type != "Workspace":
        raise ValueError("workspace root node")
    members_by_spec = {member.spec_id: member for member in graph.members}
    spec_nodes = [node for node in graph.nodes if node.type == "Spec"]
    if len(spec_nodes) != len(members_by_spec):
        raise ValueError("workspace spec node count")
    for node in spec_nodes:
        spec_id = node.properties.get("spec_id")
        if not isinstance(spec_id, str) or node.id != f"spec:{spec_id}":
            raise ValueError("workspace spec node identity")
        member = members_by_spec.get(spec_id)
        if member is None:
            raise ValueError("undeclared workspace spec node")
        expected_status = "included" if member.included else "excluded"
        if node.properties.get("composition_status") != expected_status:
            raise ValueError("workspace spec composition status")
        if node.properties.get("member_audit_status") != member.audit_status:
            raise ValueError("workspace spec audit status")


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
    current_document = current.to_dict()
    if (
        reference.get("nodes") != current_document["nodes"]
        or reference.get("edges") != current_document["edges"]
    ):
        findings.append(
            WorkspaceGraphFinding(
                "error",
                "workspace_graph_body_stale",
                "workspace graph nodes or edges differ from fresh composition",
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
        if old.get("member_source_set_digest") != new.member_source_set_digest:
            findings.append(
                WorkspaceGraphFinding(
                    "error",
                    "workspace_member_source_set_stale",
                    f"member source-set digest differs from fresh receipt: {spec_id}",
                    subject_id,
                )
            )
        if old.get("member_memory_state_digest") != new.member_memory_state_digest:
            findings.append(
                WorkspaceGraphFinding(
                    "error",
                    "workspace_member_memory_state_stale",
                    f"member memory-state digest differs from fresh receipt: {spec_id}",
                    subject_id,
                )
            )
    return findings


def _member_audit_findings(
    members: Iterable[WorkspaceGraphMember],
) -> list[WorkspaceGraphFinding]:
    return [
        WorkspaceGraphFinding(
            "warning",
            "workspace_member_audit_warning",
            f"live member audit has warnings: {member.spec_id}",
            f"spec:{member.spec_id}",
        )
        for member in members
        if member.included and member.audit_status == "warn"
    ]


def _removed_member_findings(
    members: Iterable[WorkspaceGraphMember],
) -> list[WorkspaceGraphFinding]:
    return [
        WorkspaceGraphFinding(
            "error",
            "workspace_member_removed",
            f"canonical spec was removed after workspace graph composition: {member.spec_id}",
            f"spec:{member.spec_id}",
        )
        for member in members
    ]


def _members_by_spec(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item["spec_id"]): item
        for item in value
        if isinstance(item, dict) and isinstance(item.get("spec_id"), str)
    }


def _members_from_document(document: Mapping[str, object]) -> tuple[WorkspaceGraphMember, ...]:
    return _parse_members(document.get("members", []))


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
