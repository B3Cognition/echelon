"""Deterministic presentation adapters for read-only graph consumption."""

from __future__ import annotations

from collections.abc import Mapping

from echelon.graph_read import GraphReadModel
from echelon.graph_traversal import GraphPath, GraphResult, PathStep


def graph_result_payload(
    model: GraphReadModel,
    command: str,
    request: Mapping[str, object],
    result: GraphResult,
) -> dict[str, object]:
    """Return the common JSON envelope without changing persisted mappings."""
    return {
        "schema_version": 1,
        "scope": model.scope,
        "graph_hash": model.graph_hash,
        "audit": model.audit.to_dict(),
        "command": command,
        "request": dict(request),
        "nodes": list(result.nodes),
        "edges": list(result.edges),
        "paths": [_path_payload(path) for path in result.paths],
        "truncated": result.truncated,
    }


def render_graph_result_text(
    model: GraphReadModel,
    command: str,
    result: GraphResult,
) -> str:
    """Render compact, deterministic text without property dictionary reprs."""
    audit = model.audit.to_dict()
    findings = audit.get("findings", [])
    lines = [
        f"Scope: {model.scope}",
        f"Audit: {audit.get('status', 'unknown')} (findings={len(findings)})",
    ]
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        lines.append(
            f"Warning [{finding.get('code', 'unknown')}]: "
            f"{finding.get('message', '')}"
        )
    lines.append(f"Command: {command}")
    _render_nodes(lines, result)
    _render_edges(lines, result)
    _render_paths(lines, result)
    if result.truncated:
        lines.append("Results truncated.")
    return "\n".join(lines)


def _path_payload(path: GraphPath) -> dict[str, object]:
    return {
        "node_ids": list(path.node_ids),
        "steps": [_step_payload(step) for step in path.steps],
    }


def _step_payload(step: PathStep) -> dict[str, object]:
    return {
        "source": step.source,
        "type": step.type,
        "target": step.target,
        "direction": step.direction,
        "properties": step.properties,
    }


def _render_nodes(lines: list[str], result: GraphResult) -> None:
    if not result.nodes:
        lines.append("Nodes: (none)")
        return
    lines.append("Nodes:")
    for node in result.nodes:
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        lines.append(f"- {node_id} [{node_type}]")
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            continue
        source_path = properties.get("source_path")
        source_line = properties.get("source_line")
        if isinstance(source_path, str) and isinstance(source_line, int):
            lines.append(f"  Source: {source_path}:{source_line}")


def _render_edges(lines: list[str], result: GraphResult) -> None:
    if not result.edges:
        lines.append("Edges: (none)")
        return
    lines.append("Edges:")
    for edge in result.edges:
        lines.append(
            f"- {edge.get('source', '')} -[{edge.get('type', '')}]-> "
            f"{edge.get('target', '')}"
        )


def _render_paths(lines: list[str], result: GraphResult) -> None:
    if not result.paths:
        lines.append("Paths: (none)")
        return
    lines.append("Paths:")
    for index, path in enumerate(result.paths, start=1):
        lines.append(f"- Path {index}: {' -> '.join(path.node_ids)}")
        for step in path.steps:
            lines.append(
                f"  {step.source} -[{step.type}]-> {step.target} "
                f"(direction={step.direction})"
            )
