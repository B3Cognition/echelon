"""Audit-aware services and deterministic renderers for topology CLI reads."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping

from echelon.topology_audit import (
    TopologyAuditFinding,
    TopologyAuditReport,
    audit_topology,
)
from echelon.topology_model import (
    TopologyExplainResult,
    TopologyFile,
    TopologyReceipt,
    TopologyRelationship,
    TopologySearchResult,
    TopologySource,
    TopologySymbol,
    TopologyTraversalResult,
    TopologyTraversalStep,
    TopologyValidationError,
)
from echelon.topology_provider import (
    PublishedTopology,
    TopologyNodeResolutionError,
    TopologyProviderError,
)
from echelon.topology_registry import (
    TopologyIndex,
    TopologyRegistryError,
    load_published_topology,
    load_topology_index,
)


_MAX_DIAGNOSTICS = 10
_MAX_MESSAGE_LENGTH = 500
_Node = TopologySource | TopologyFile | TopologySymbol


@dataclass(frozen=True, slots=True)
class TopologyCliResult:
    """One fully rendered command result with process-style stream policy."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def audit_command(
    project_root: Path,
    *,
    source: str | None = None,
    as_json: bool = False,
) -> TopologyCliResult:
    """Audit canonical topology without loading or mutating alternate state."""
    root = Path(project_root)
    report = audit_topology(root, source_id=source)
    if report.exit_code != 2:
        try:
            index = load_topology_index(root)
            if index is None:
                raise TopologyRegistryError("topology index is missing")
            if not _index_has_usable_provider(index, source):
                return _fatal(
                    "audit",
                    report,
                    "canonical topology providers are unavailable",
                    request={"source": source},
                    as_json=as_json,
                    kind="unavailable",
                )
        except (OSError, TopologyRegistryError, TopologyValidationError, ValueError) as exc:
            return _fatal(
                "audit",
                report,
                str(exc),
                request={"source": source},
                as_json=as_json,
                kind=_error_kind(exc),
            )
    payload = {
        "schema_version": 1,
        "command": "audit",
        "request": {"source": source},
        "audit": _audit_payload(report),
    }
    rendered = _json(payload) if as_json else _render_audit(report)
    if report.exit_code == 2:
        return TopologyCliResult(stderr=rendered, exit_code=2)
    return TopologyCliResult(stdout=rendered, exit_code=report.exit_code)


def list_sources_command(
    project_root: Path,
    *,
    as_json: bool = False,
) -> TopologyCliResult:
    """List canonical source rows with provider and freshness receipts."""
    root = Path(project_root)
    report = audit_topology(root)
    if report.exit_code == 2:
        return _fatal_audit("list-sources", report, as_json=as_json)
    try:
        index = load_topology_index(root)
        if index is None:
            raise TopologyRegistryError("topology index is missing")
        if not _index_has_usable_provider(index):
            return _fatal(
                "list-sources",
                report,
                "canonical topology providers are unavailable",
                as_json=as_json,
                kind="unavailable",
            )
        statuses = _source_statuses(report)
        rows = [
            _source_row(
                source,
                statuses.get(source.source_id, report.status),
                index.generation,
            )
            for source in index.sources.values()
        ]
    except (OSError, TopologyRegistryError, TopologyValidationError, ValueError) as exc:
        return _fatal(
            "list-sources", report, str(exc), as_json=as_json, kind=_error_kind(exc)
        )
    payload = {
        "schema_version": 1,
        "command": "list-sources",
        "audit": _audit_payload(report),
        "sources": rows,
    }
    rendered = _json(payload) if as_json else _render_source_rows(report, rows)
    return TopologyCliResult(stdout=rendered, exit_code=report.exit_code)


def search_command(
    project_root: Path,
    query: str,
    *,
    source: str | None = None,
    node_types: tuple[str, ...] = (),
    limit: int = 50,
    as_json: bool = False,
) -> TopologyCliResult:
    """Search selected canonical provider topology with deterministic output."""
    types = _normalized_filters(node_types)

    def read(topology: PublishedTopology) -> TopologySearchResult:
        return topology.search(source, query, frozenset(types), limit)

    return _run_read(
        Path(project_root),
        "search",
        source,
        {
            "query": query,
            "source": source,
            "types": list(types),
            "limit": limit,
        },
        read,
        lambda topology, report, result: _search_payload(topology, report, result),
        lambda topology, report, result: _render_search(topology, report, result),
        as_json=as_json,
    )


def explain_command(
    project_root: Path,
    node: str,
    *,
    source: str | None = None,
    as_json: bool = False,
) -> TopologyCliResult:
    """Explain one exact or unambiguous topology node."""
    return _run_read(
        Path(project_root),
        "explain",
        source,
        {"node": node, "source": source},
        lambda topology: topology.explain(source, node),
        lambda topology, report, result: _explain_payload(topology, report, result),
        lambda topology, report, result: _render_explain(topology, report, result),
        as_json=as_json,
    )


def neighbors_command(
    project_root: Path,
    node: str,
    *,
    source: str | None = None,
    direction: str = "both",
    relations: tuple[str, ...] = (),
    limit: int = 50,
    as_json: bool = False,
) -> TopologyCliResult:
    """Read deterministic direct topology neighbors."""
    relation_types = _normalized_filters(relations)

    def read(
        topology: PublishedTopology,
    ) -> tuple[TopologyTraversalResult, str]:
        selected = topology.explain(source, node).node.id
        return (
            topology.neighbors(
                source,
                selected,
                direction,
                frozenset(relation_types),
                limit,
            ),
            selected,
        )

    return _run_read(
        Path(project_root),
        "neighbors",
        source,
        {
            "node": node,
            "source": source,
            "direction": direction,
            "relations": list(relation_types),
            "limit": limit,
        },
        read,
        lambda topology, report, value: _traversal_payload(
            "neighbors", topology, report, value[0], value[1]
        ),
        lambda topology, report, value: _render_traversal(
            "neighbors", topology, report, value[0], value[1]
        ),
        as_json=as_json,
    )


def impact_command(
    project_root: Path,
    node: str,
    *,
    source: str | None = None,
    max_depth: int = 3,
    relations: tuple[str, ...] = (),
    as_json: bool = False,
) -> TopologyCliResult:
    """Read bounded deterministic impact paths from canonical topology."""
    relation_types = _normalized_filters(relations)

    def read(
        topology: PublishedTopology,
    ) -> tuple[TopologyTraversalResult, str]:
        selected = topology.explain(source, node).node.id
        return (
            topology.impact(
                source,
                selected,
                max_depth,
                frozenset(relation_types),
            ),
            selected,
        )

    return _run_read(
        Path(project_root),
        "impact",
        source,
        {
            "node": node,
            "source": source,
            "max_depth": max_depth,
            "relations": list(relation_types),
        },
        read,
        lambda topology, report, value: _traversal_payload(
            "impact", topology, report, value[0], value[1]
        ),
        lambda topology, report, value: _render_traversal(
            "impact", topology, report, value[0], value[1]
        ),
        as_json=as_json,
    )


def _run_read(
    root: Path,
    command: str,
    source: str | None,
    request: Mapping[str, object],
    operation: Callable[[PublishedTopology], object],
    payload_builder: Callable[[PublishedTopology, TopologyAuditReport, object], dict[str, object]],
    text_builder: Callable[[PublishedTopology, TopologyAuditReport, object], str],
    *,
    as_json: bool,
) -> TopologyCliResult:
    report = audit_topology(root, source_id=source)
    if report.exit_code == 2:
        return _fatal_audit(command, report, request=request, as_json=as_json)
    try:
        selected = (source,) if source is not None else ()
        topology = load_published_topology(root, selected)
        if not _topology_has_usable_provider(topology, report):
            return _fatal(
                command,
                report,
                "canonical topology providers are unavailable",
                request=request,
                as_json=as_json,
                kind="unavailable",
            )
        result = operation(topology)
    except (
        OSError,
        TopologyNodeResolutionError,
        TopologyProviderError,
        TopologyRegistryError,
        TopologyValidationError,
        ValueError,
    ) as exc:
        return _fatal(
            command,
            report,
            str(exc),
            request=request,
            as_json=as_json,
            kind=_error_kind(exc),
            candidates=getattr(exc, "candidates", ()),
        )
    if as_json:
        payload = {
            "schema_version": 1,
            "command": command,
            "request": dict(request),
            "audit": _audit_payload(report),
            **payload_builder(topology, report, result),
        }
        rendered = _json(payload)
    else:
        rendered = text_builder(topology, report, result)
    return TopologyCliResult(stdout=rendered, exit_code=report.exit_code)


def _search_payload(
    topology: PublishedTopology,
    report: TopologyAuditReport,
    value: object,
) -> dict[str, object]:
    result = _expect(value, TopologySearchResult)
    statuses = _source_statuses(report)
    return {
        "provenance": _receipt_payload(result.receipt),
        "results": [
            _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
            )
            for node in result.nodes
        ],
        "truncated": result.truncated,
    }


def _explain_payload(
    topology: PublishedTopology,
    report: TopologyAuditReport,
    value: object,
) -> dict[str, object]:
    result = _expect(value, TopologyExplainResult)
    statuses = _source_statuses(report)
    status = statuses.get(result.node.source_id, report.status)
    return {
        "provenance": _receipt_payload(result.receipt),
        "node": _node_payload(result.node, result.receipt, status, result.truncated),
        "relationships": [
            _relationship_payload(
                topology, relationship, result.receipt, statuses, result.truncated
            )
            for relationship in result.relationships
        ],
        "truncated": result.truncated,
    }


def _traversal_payload(
    command: str,
    topology: PublishedTopology,
    report: TopologyAuditReport,
    result: TopologyTraversalResult,
    root_id: str,
) -> dict[str, object]:
    statuses = _source_statuses(report)
    paths = _traversal_paths(root_id, result.steps)
    return {
        "provenance": _receipt_payload(result.receipt),
        "nodes": [
            _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
            )
            for node in result.nodes
        ],
        "relationships": [
            _relationship_payload(
                topology, relationship, result.receipt, statuses, result.truncated
            )
            for relationship in result.relationships
        ],
        "steps": [
            _step_payload(
                topology,
                step,
                result.receipt,
                statuses,
                result.truncated,
                paths[index],
            )
            for index, step in enumerate(result.steps)
        ],
        "truncated": result.truncated,
    }


def _node_payload(
    node: _Node,
    receipt: TopologyReceipt,
    topology_status: str,
    truncated: bool,
) -> dict[str, object]:
    provider = node.provider if isinstance(node, TopologySymbol) else "topology"
    provider_key = _provider_key(receipt, node.source_id, provider)
    artifact_path = _provider_artifact_path(receipt, provider, node.source_id)
    return {
        "source_id": node.source_id,
        "provider": provider,
        "node_id": node.id,
        "node_type": node.type,
        "path": getattr(node, "path", None),
        "source_relative_path": getattr(node, "path", None),
        "name": getattr(node, "name", ""),
        "qualified_name": getattr(node, "qualified_name", ""),
        "kind": getattr(node, "kind", ""),
        "line_start": getattr(node, "line_start", None),
        "line_end": getattr(node, "line_end", None),
        "topology_generation": receipt.generation,
        "topology_status": topology_status,
        "provider_status": receipt.provider_statuses.get(provider_key),
        "provider_receipt_hash": receipt.provider_receipt_hashes.get(provider_key),
        "provider_artifact_path": artifact_path,
        "truncated": truncated,
    }


def _relationship_payload(
    topology: PublishedTopology,
    relationship: TopologyRelationship,
    receipt: TopologyReceipt,
    statuses: Mapping[str, str],
    truncated: bool,
) -> dict[str, object]:
    source_node = topology.nodes_by_id[relationship.source_id]
    provider_key = _provider_key(receipt, source_node.source_id, relationship.provider)
    return {
        "source_id": source_node.source_id,
        "provider": relationship.provider,
        "relation": relationship.type,
        "provider_relation": relationship.provider_kind,
        "source_node_id": relationship.source_id,
        "target_node_id": relationship.target_id,
        "path": relationship.path,
        "source_relative_path": relationship.path,
        "line_start": relationship.line_start,
        "topology_generation": receipt.generation,
        "topology_status": statuses.get(source_node.source_id, "current"),
        "provider_status": receipt.provider_statuses.get(provider_key),
        "provider_receipt_hash": receipt.provider_receipt_hashes.get(provider_key),
        "provider_artifact_path": _provider_artifact_path(
            receipt, relationship.provider, source_node.source_id
        ),
        "truncated": truncated,
    }


def _step_payload(
    topology: PublishedTopology,
    step: TopologyTraversalStep,
    receipt: TopologyReceipt,
    statuses: Mapping[str, str],
    truncated: bool,
    traversal_path: tuple[str, ...],
) -> dict[str, object]:
    node = topology.nodes_by_id[step.node_id]
    row = _node_payload(
        node,
        receipt,
        statuses.get(node.source_id, "current"),
        truncated,
    )
    relationship = step.relationship
    row.update(
        {
            "direction": step.direction,
            "depth": step.depth,
            "relation": relationship.type,
            "provider": relationship.provider,
            "provider_relation": relationship.provider_kind,
            "source_node_id": relationship.source_id,
            "target_node_id": relationship.target_id,
            "relationship_path": relationship.path,
            "relationship_line_start": relationship.line_start,
            "traversal_path": list(traversal_path),
        }
    )
    provider_key = _provider_key(receipt, node.source_id, relationship.provider)
    row["provider_status"] = receipt.provider_statuses.get(provider_key)
    row["provider_receipt_hash"] = receipt.provider_receipt_hashes.get(provider_key)
    row["provider_artifact_path"] = _provider_artifact_path(
        receipt, relationship.provider, node.source_id
    )
    return row


def _source_row(
    source: object, topology_status: str, topology_generation: int
) -> dict[str, object]:
    providers = getattr(source, "providers")
    return {
        "source_id": getattr(source, "source_id"),
        "provider": "topology",
        "node_id": f"source:{getattr(source, 'source_id')}",
        "path": getattr(source, "source_path"),
        "source_fingerprint": getattr(source, "source_fingerprint").value,
        "source_generation": getattr(source, "generation"),
        "topology_generation": topology_generation,
        "topology_status": topology_status,
        "providers": [
            {
                "provider": provider,
                "status": receipt.status,
                "complete": receipt.complete,
            }
            for provider, receipt in providers.items()
        ],
        "truncated": False,
    }


def _receipt_payload(receipt: TopologyReceipt) -> dict[str, object]:
    return {
        "topology_generation": receipt.generation,
        "source_id": receipt.source_id,
        "source_fingerprint": receipt.source_fingerprint,
        "source_fingerprints": dict(receipt.source_fingerprints),
        "provider_receipt_hashes": dict(receipt.provider_receipt_hashes),
        "provider_artifact_paths": list(receipt.provider_artifact_paths),
        "provider_statuses": dict(receipt.provider_statuses),
    }


def _audit_payload(report: TopologyAuditReport) -> dict[str, object]:
    findings = report.findings[:_MAX_DIAGNOSTICS]
    return {
        "status": report.status,
        "exit_code": report.exit_code,
        "sources": [
            {
                "source_id": source.source_id,
                "status": source.status,
                "providers": list(source.providers),
            }
            for source in report.sources
        ],
        "findings": [_finding_payload(finding) for finding in findings],
        "findings_truncated": len(report.findings) > len(findings),
    }


def _finding_payload(finding: TopologyAuditFinding) -> dict[str, object]:
    return {
        "status": finding.status,
        "message": _bounded_message(finding.message),
        "source_id": finding.source_id,
        "provider": finding.provider,
        "path": finding.path,
    }


def _render_audit(report: TopologyAuditReport) -> str:
    lines = [f"Topology audit: {report.status} (exit={report.exit_code})"]
    if report.sources:
        lines.append("Sources:")
        for source in report.sources:
            providers = ",".join(source.providers) or "none"
            lines.append(
                f"- {source.source_id} status={source.status} providers={providers}"
            )
    _append_findings(lines, report)
    return "\n".join(lines) + "\n"


def _render_source_rows(
    report: TopologyAuditReport, rows: list[dict[str, object]]
) -> str:
    lines = [f"Topology sources: {report.status} (count={len(rows)})"]
    _append_findings(lines, report)
    for row in rows:
        providers = ",".join(
            f"{provider['provider']}:{provider['status']}"
            for provider in row["providers"]  # type: ignore[union-attr]
        )
        lines.append(
            f"- {row['source_id']} path={row['path']} generation={row['topology_generation']} "
            f"status={row['topology_status']} providers={providers or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _render_search(
    topology: PublishedTopology,
    report: TopologyAuditReport,
    value: object,
) -> str:
    result = _expect(value, TopologySearchResult)
    lines = [_read_header("search", report, result.receipt, result.truncated)]
    _append_findings(lines, report)
    if not result.nodes:
        lines.append("Results: (none)")
    else:
        lines.append("Results:")
        statuses = _source_statuses(report)
        for node in result.nodes:
            row = _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
            )
            lines.append(_render_node_row(row))
    return "\n".join(lines) + "\n"


def _render_explain(
    topology: PublishedTopology,
    report: TopologyAuditReport,
    value: object,
) -> str:
    result = _expect(value, TopologyExplainResult)
    statuses = _source_statuses(report)
    lines = [_read_header("explain", report, result.receipt, result.truncated)]
    _append_findings(lines, report)
    lines.append(
        _render_node_row(
            _node_payload(
                result.node,
                result.receipt,
                statuses.get(result.node.source_id, report.status),
                result.truncated,
            )
        )
    )
    lines.append("Relationships:" if result.relationships else "Relationships: (none)")
    for relationship in result.relationships:
        lines.append(
            f"- {relationship.source_id} -[{relationship.type}]-> "
            f"{relationship.target_id} provider={relationship.provider} "
            f"path={relationship.path or '-'}"
        )
    return "\n".join(lines) + "\n"


def _render_traversal(
    command: str,
    topology: PublishedTopology,
    report: TopologyAuditReport,
    result: TopologyTraversalResult,
    root_id: str,
) -> str:
    lines = [_read_header(command, report, result.receipt, result.truncated)]
    _append_findings(lines, report)
    lines.append("Steps:" if result.steps else "Steps: (none)")
    paths = _traversal_paths(root_id, result.steps)
    for index, step in enumerate(result.steps):
        node = topology.nodes_by_id[step.node_id]
        lines.append(
            f"- depth={step.depth} direction={step.direction} relation={step.relationship.type} "
            f"node={step.node_id} source={node.source_id} "
            f"provider={step.relationship.provider} path={getattr(node, 'path', None) or '-'} "
            f"traversal_path={' -> '.join(paths[index])}"
        )
    return "\n".join(lines) + "\n"


def _render_node_row(row: Mapping[str, object]) -> str:
    label = row.get("qualified_name") or row.get("name") or row["node_id"]
    return (
        f"- {row['node_id']} [{row['node_type']}] name={label} "
        f"source={row['source_id']} provider={row['provider']} "
        f"path={row['path'] or '-'} generation={row['topology_generation']} "
        f"status={row['topology_status']} truncated={_yes_no(bool(row['truncated']))}"
    )


def _read_header(
    command: str,
    report: TopologyAuditReport,
    receipt: TopologyReceipt,
    truncated: bool,
) -> str:
    return (
        f"Topology {command}: {report.status} "
        f"(generation={receipt.generation}, truncated={_yes_no(truncated)})"
    )


def _append_findings(lines: list[str], report: TopologyAuditReport) -> None:
    for finding in report.findings[:_MAX_DIAGNOSTICS]:
        scope = "/".join(
            value for value in (finding.source_id, finding.provider) if value
        )
        prefix = f" {scope}" if scope else ""
        lines.append(
            f"Warning [{finding.status}]{prefix}: {_bounded_message(finding.message)}"
        )
    if len(report.findings) > _MAX_DIAGNOSTICS:
        lines.append(
            f"Warning: {len(report.findings) - _MAX_DIAGNOSTICS} additional findings omitted."
        )


def _fatal_audit(
    command: str,
    report: TopologyAuditReport,
    *,
    request: Mapping[str, object] | None = None,
    as_json: bool,
) -> TopologyCliResult:
    payload = {
        "schema_version": 1,
        "command": command,
        "request": dict(request or {}),
        "audit": _audit_payload(report),
    }
    rendered = _json(payload) if as_json else _render_audit(report)
    return TopologyCliResult(stderr=rendered, exit_code=2)


def _fatal(
    command: str,
    report: TopologyAuditReport,
    message: str,
    *,
    request: Mapping[str, object] | None = None,
    as_json: bool,
    kind: str,
    candidates: tuple[str, ...] = (),
) -> TopologyCliResult:
    bounded_candidates = tuple(sorted(candidates))[:_MAX_DIAGNOSTICS]
    payload = {
        "schema_version": 1,
        "command": command,
        "request": dict(request or {}),
        "audit": _audit_payload(report),
        "error": {
            "kind": kind,
            "message": _bounded_message(message),
            "candidates": list(bounded_candidates),
            "candidates_truncated": len(candidates) > len(bounded_candidates),
        },
    }
    if as_json:
        rendered = _json(payload)
    else:
        rendered = f"Topology {command} failed [{kind}]: {_bounded_message(message)}\n"
        for candidate in bounded_candidates:
            rendered += f"- {candidate}\n"
        if len(candidates) > len(bounded_candidates):
            omitted = len(candidates) - len(bounded_candidates)
            rendered += f"- {omitted} additional candidates omitted\n"
    return TopologyCliResult(stderr=rendered, exit_code=2)


def _traversal_paths(
    root_id: str, steps: tuple[TopologyTraversalStep, ...]
) -> tuple[tuple[str, ...], ...]:
    known: dict[str, tuple[str, ...]] = {root_id: (root_id,)}
    observed: list[tuple[str, ...]] = []
    for step in steps:
        current = (
            step.relationship.source_id
            if step.direction == "out"
            else step.relationship.target_id
        )
        base = known.get(current, (root_id,))
        path = (*base, step.node_id)
        observed.append(path)
        known.setdefault(step.node_id, path)
    return tuple(observed)


def _source_statuses(report: TopologyAuditReport) -> dict[str, str]:
    return {source.source_id: source.status for source in report.sources}


def _topology_has_usable_provider(
    topology: PublishedTopology, report: TopologyAuditReport
) -> bool:
    source_ids = tuple(source.source_id for source in report.sources)
    if not source_ids:
        source_ids = tuple(
            node.source_id
            for node in topology.nodes_by_id.values()
            if isinstance(node, TopologySource)
        )
    statuses = [
        status
        for source_id in source_ids
        for status in topology.receipt(source_id).provider_statuses.values()
    ]
    return bool(statuses) and any(status != "unavailable" for status in statuses)


def _index_has_usable_provider(
    index: TopologyIndex, source_id: str | None = None
) -> bool:
    sources = (
        (index.sources[source_id],)
        if source_id is not None and source_id in index.sources
        else index.sources.values()
    )
    statuses = [
        receipt.status
        for source in sources
        for receipt in source.providers.values()
    ]
    return bool(statuses) and any(status != "unavailable" for status in statuses)


def _provider_key(
    receipt: TopologyReceipt, source_id: str, provider: str
) -> str:
    qualified = f"{source_id}:{provider}"
    if qualified in receipt.provider_statuses or qualified in receipt.provider_receipt_hashes:
        return qualified
    return provider


def _provider_artifact_path(
    receipt: TopologyReceipt, provider: str, source_id: str
) -> str | None:
    marker = f"/sources/{source_id}/{provider}-analysis.json"
    matches = [path for path in receipt.provider_artifact_paths if path.endswith(marker)]
    return matches[0] if len(matches) == 1 else None


def _normalized_filters(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value.upper() for value in values}))


def _error_kind(exc: BaseException) -> str:
    if isinstance(exc, TopologyNodeResolutionError) and getattr(exc, "candidates", ()):
        return "ambiguous"
    message = str(exc).casefold()
    if "unavailable" in message or "missing" in message:
        return "unavailable"
    if "unsafe" in message or "absolute" in message or "traverse" in message:
        return "unsafe"
    return "invalid"


def _bounded_message(message: str) -> str:
    value = " ".join(str(message).split())
    if len(value) <= _MAX_MESSAGE_LENGTH:
        return value
    return value[: _MAX_MESSAGE_LENGTH - 3] + "..."


def _expect(value: object, expected: type[object]):
    if not isinstance(value, expected):
        raise TypeError(f"unexpected topology result: {type(value).__name__}")
    return value


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"
