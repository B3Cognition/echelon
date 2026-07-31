"""Read-only, audit-aware access to persisted artifact graph documents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from echelon.mempalace_requirements import resolve_spec_dir
from echelon.spec_graph import GRAPH_FILENAME, GRAPH_SCHEMA_VERSION
from echelon.spec_graph_audit import SpecGraphAuditReport, audit_spec_graph
from echelon.workspace_graph import workspace_graph_path
from echelon.workspace_graph_audit import WorkspaceGraphAuditReport, audit_workspace_graph


class GraphReadError(RuntimeError):
    """Raised when a persisted graph cannot be read safely."""


class NodeResolutionError(GraphReadError):
    """Raised when a graph node selector is absent or ambiguous."""


@dataclass(frozen=True)
class GraphReadModel:
    scope: str
    graph_hash: str
    document: Mapping[str, object]
    audit: SpecGraphAuditReport | WorkspaceGraphAuditReport
    nodes_by_id: Mapping[str, Mapping[str, object]]
    outgoing: Mapping[str, tuple[Mapping[str, object], ...]]
    incoming: Mapping[str, tuple[Mapping[str, object], ...]]


def read_graph_document(path: Path) -> dict[str, object]:
    """Read and validate one persisted schema-1 graph document."""
    document, _ = _read_graph_document_bytes(path)
    _indexes(document)
    return document


def load_graph(project_root: Path, spec_selector: str | None = None) -> GraphReadModel:
    """Load a persisted graph plus its live, read-only audit."""
    root = Path(project_root)
    if spec_selector is None:
        graph_path = workspace_graph_path(root)
        document, graph_bytes = _read_graph_document_bytes(graph_path)
        audit = audit_workspace_graph(root)
        invalid_finding_code = "workspace_graph_invalid"
    else:
        spec_dir = resolve_spec_dir(root, spec_selector)
        graph_path = spec_dir / GRAPH_FILENAME
        document, graph_bytes = _read_graph_document_bytes(graph_path)
        audit = audit_spec_graph(root, spec_selector)
        invalid_finding_code = "graph_invalid"

    _reject_contract_invalid_audit(audit, invalid_finding_code)
    nodes_by_id, outgoing, incoming = _indexes(document)
    return GraphReadModel(
        scope=_graph_scope(document),
        graph_hash=_sha256(graph_bytes),
        document=document,
        audit=audit,
        nodes_by_id=nodes_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )


def resolve_node_id(model: GraphReadModel, selector: str) -> str:
    """Resolve an exact node ID or one unambiguous human-scale identifier."""
    if not isinstance(selector, str) or not (value := selector.strip()):
        raise NodeResolutionError("graph node selector must not be blank")
    if value in model.nodes_by_id:
        return value

    normalized = value.casefold()
    candidates = {
        node_id
        for node_id, node in model.nodes_by_id.items()
        if _matches_selector(node_id, node, normalized)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates:
        raise NodeResolutionError(f"unknown graph node selector: {value}")
    raise NodeResolutionError(
        f"ambiguous graph node selector {value!r}: {_format_candidates(candidates)}"
    )


def graph_read_exit_code(model: GraphReadModel) -> int:
    """Return success only for a clean passing live audit."""
    return 0 if model.audit.status == "pass" and not model.audit.findings else 1


def _read_graph_document_bytes(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        graph_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise GraphReadError(f"graph artifact is missing: {path}") from exc
    except OSError as exc:
        raise GraphReadError(f"graph artifact is unreadable: {path}") from exc
    try:
        document = json.loads(graph_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GraphReadError(f"graph artifact is unreadable: {path}") from exc
    if not isinstance(document, dict):
        raise GraphReadError("graph document must be an object")
    if document.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise GraphReadError("unsupported graph schema version")
    scope = _graph_scope(document)
    if scope == "spec" and (
        not isinstance(document.get("spec_id"), str) or not document["spec_id"]
    ):
        raise GraphReadError("graph spec_id must be a non-empty string")
    if scope == "workspace" and (
        not isinstance(document.get("workspace_name"), str)
        or not document["workspace_name"]
    ):
        raise GraphReadError("graph workspace_name must be a non-empty string")
    return document, graph_bytes


def _reject_contract_invalid_audit(
    audit: SpecGraphAuditReport | WorkspaceGraphAuditReport,
    finding_code: str,
) -> None:
    if any(finding.code == finding_code for finding in audit.findings):
        raise GraphReadError(
            f"persisted graph failed live contract audit: {finding_code}"
        )


def _indexes(
    document: Mapping[str, object],
) -> tuple[
    Mapping[str, Mapping[str, object]],
    Mapping[str, tuple[Mapping[str, object], ...]],
    Mapping[str, tuple[Mapping[str, object], ...]],
]:
    raw_nodes = document.get("nodes")
    raw_edges = document.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise GraphReadError("graph nodes and edges must be lists")

    nodes: dict[str, Mapping[str, object]] = {}
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise GraphReadError("graph node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise GraphReadError("graph node id must be a non-empty string")
        if node_id in nodes:
            raise GraphReadError(f"duplicate graph node id: {node_id}")
        if not isinstance(node.get("type"), str):
            raise GraphReadError(f"graph node type is invalid: {node_id}")
        if not isinstance(node.get("properties"), dict):
            raise GraphReadError(f"graph node properties are invalid: {node_id}")
        nodes[node_id] = node

    edges: list[Mapping[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise GraphReadError("graph edge must be an object")
        source = edge.get("source")
        edge_type = edge.get("type")
        target = edge.get("target")
        if not all(isinstance(item, str) and item for item in (source, edge_type, target)):
            raise GraphReadError("graph edge identity is invalid")
        identity = (source, edge_type, target)
        if identity in identities:
            raise GraphReadError(f"duplicate graph edge: {source} {edge_type} {target}")
        if source not in nodes or target not in nodes:
            raise GraphReadError(
                f"graph edge has missing endpoint: {source} {edge_type} {target}"
            )
        if not isinstance(edge.get("properties"), dict):
            raise GraphReadError(
                f"graph edge properties are invalid: {source} {edge_type} {target}"
            )
        identities.add(identity)
        edges.append(edge)

    ordered_nodes = {node_id: nodes[node_id] for node_id in sorted(nodes)}
    outgoing = {node_id: [] for node_id in ordered_nodes}
    incoming = {node_id: [] for node_id in ordered_nodes}
    for edge in sorted(edges, key=lambda item: (str(item["type"]), str(item["source"]), str(item["target"]))):
        outgoing[str(edge["source"])].append(edge)
        incoming[str(edge["target"])].append(edge)
    return (
        MappingProxyType(ordered_nodes),
        MappingProxyType({node_id: tuple(edges) for node_id, edges in outgoing.items()}),
        MappingProxyType({node_id: tuple(edges) for node_id, edges in incoming.items()}),
    )


def _graph_scope(document: Mapping[str, object]) -> str:
    scope = document.get("scope")
    if scope in {None, "spec"}:
        return "spec"
    if scope == "workspace":
        return "workspace"
    raise GraphReadError(f"unsupported graph scope: {scope!r}")


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _matches_selector(node_id: str, node: Mapping[str, object], selector: str) -> bool:
    if node_id.rpartition(":")[2].casefold() == selector:
        return True
    properties = node["properties"]
    if not isinstance(properties, Mapping):
        return False
    return any(
        key.endswith("_id")
        and isinstance(identity, (str, int, float, bool))
        and str(identity).casefold() == selector
        for key, identity in properties.items()
    )


def _format_candidates(candidates: set[str]) -> str:
    ordered = sorted(candidates)
    shown = ordered[:10]
    remaining = len(ordered) - len(shown)
    suffix = f", ... (+{remaining} more)" if remaining else ""
    return ", ".join(shown) + suffix
