"""Audit-aware services and deterministic renderers for topology CLI reads.

Reads use a bounded double-collect guarantee: an initial live audit is bound to
the loaded publication, then an independent final publication capture is bound
to the last live audit before rendering. No filesystem read follows that audit.
This detects mutation within the command's read window without claiming a
permanent filesystem lock after final validation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping

import yaml

from echelon.topology_audit import (
    TopologyAuditFinding,
    TopologyAuditReport,
    TopologyAuditSnapshot,
    TopologyAuditSource,
    audit_topology,
    snapshot_topology_index,
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
_MAX_CANDIDATE_BYTES = 256
_MAX_CANDIDATES_TOTAL_BYTES = 2048
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
    initial_report, audit_error = _audit_at_boundary(root, source)
    if audit_error is not None:
        return _fatal(
            "audit",
            initial_report,
            str(audit_error),
            request={"source": source},
            as_json=as_json,
            kind="invalid",
        )
    if initial_report.exit_code == 2:
        return _fatal_audit(
            "audit",
            initial_report,
            request={"source": source},
            as_json=as_json,
        )
    if initial_report.exit_code != 2:
        try:
            index = load_topology_index(root)
            if index is None:
                raise TopologyRegistryError("topology index is missing")
            snapshot = snapshot_topology_index(index, source)
            _assert_audit_matches_snapshot(initial_report, snapshot)
            if not _index_has_usable_provider(index, source):
                return _fatal(
                    "audit",
                    initial_report,
                    "canonical topology providers are unavailable",
                    request={"source": source},
                    as_json=as_json,
                    kind="unavailable",
                )
            final_index = load_topology_index(root)
            if final_index is None:
                raise TopologyRegistryError("topology index is missing")
            final_snapshot = snapshot_topology_index(final_index, source)
            if final_snapshot != snapshot:
                raise TopologyRegistryError("topology publication changed during read")
            final_report, audit_error = _audit_at_boundary(root, source)
            if audit_error is not None:
                return _fatal(
                    "audit",
                    final_report,
                    str(audit_error),
                    request={"source": source},
                    as_json=as_json,
                    kind="invalid",
                )
            if final_report.exit_code == 2:
                return _fatal_audit(
                    "audit",
                    final_report,
                    request={"source": source},
                    as_json=as_json,
                )
            _assert_audit_matches_snapshot(final_report, final_snapshot)
            report = _merge_audit_reports(initial_report, final_report)
        except (OSError, TopologyRegistryError, TopologyValidationError, ValueError) as exc:
            return _fatal(
                "audit",
                initial_report,
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
    initial_report, audit_error = _audit_at_boundary(root)
    if audit_error is not None:
        return _fatal(
            "list-sources",
            initial_report,
            str(audit_error),
            as_json=as_json,
            kind="invalid",
        )
    if initial_report.exit_code == 2:
        return _fatal_audit("list-sources", initial_report, as_json=as_json)
    try:
        index = load_topology_index(root)
        if index is None:
            raise TopologyRegistryError("topology index is missing")
        snapshot = snapshot_topology_index(index)
        _assert_audit_matches_snapshot(initial_report, snapshot)
        if not _index_has_usable_provider(index):
            return _fatal(
                "list-sources",
                initial_report,
                "canonical topology providers are unavailable",
                as_json=as_json,
                kind="unavailable",
            )
        final_index = load_topology_index(root)
        if final_index is None:
            raise TopologyRegistryError("topology index is missing")
        final_snapshot = snapshot_topology_index(final_index)
        if final_snapshot != snapshot:
            raise TopologyRegistryError("topology publication changed during read")
        final_report, audit_error = _audit_at_boundary(root)
        if audit_error is not None:
            return _fatal(
                "list-sources",
                final_report,
                str(audit_error),
                as_json=as_json,
                kind="invalid",
            )
        if final_report.exit_code == 2:
            return _fatal_audit("list-sources", final_report, as_json=as_json)
        _assert_audit_matches_snapshot(final_report, final_snapshot)
        report = _merge_audit_reports(initial_report, final_report)
        statuses = _source_statuses(report)
        rows = [
            _source_row(
                source,
                statuses.get(source.source_id, report.status),
                final_index.generation,
            )
            for source in final_index.sources.values()
        ]
    except (OSError, TopologyRegistryError, TopologyValidationError, ValueError) as exc:
        return _fatal(
            "list-sources",
            initial_report,
            str(exc),
            as_json=as_json,
            kind=_error_kind(exc),
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
    initial_report, audit_error = _audit_at_boundary(root, source)
    if audit_error is not None:
        return _fatal(
            command,
            initial_report,
            str(audit_error),
            request=request,
            as_json=as_json,
            kind="invalid",
        )
    if initial_report.exit_code == 2:
        return _fatal_audit(command, initial_report, request=request, as_json=as_json)
    try:
        selected = (source,) if source is not None else ()
        topology = load_published_topology(root, selected)
        source_ids = _read_source_ids(topology, source)
        _assert_topology_matches_audit(topology, initial_report, source_ids)
        binding = _topology_binding(topology, source_ids)
        if not _topology_has_usable_provider(topology, initial_report):
            return _fatal(
                command,
                initial_report,
                "canonical topology providers are unavailable",
                request=request,
                as_json=as_json,
                kind="unavailable",
            )
        result = operation(topology)
        final_topology = load_published_topology(root, selected)
        if _topology_binding(final_topology, source_ids) != binding:
            raise TopologyRegistryError("topology publication changed during read")
        final_report, audit_error = _audit_at_boundary(root, source)
        if audit_error is not None:
            return _fatal(
                command,
                final_report,
                str(audit_error),
                request=request,
                as_json=as_json,
                kind="invalid",
            )
        if final_report.exit_code == 2:
            return _fatal_audit(
                command, final_report, request=request, as_json=as_json
            )
        _assert_topology_matches_audit(final_topology, final_report, source_ids)
        report = _merge_audit_reports(initial_report, final_report)
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
            initial_report,
            str(exc),
            request=request,
            as_json=as_json,
            kind=_error_kind(exc),
            candidates=getattr(exc, "candidates", ()),
            candidate_count=getattr(exc, "candidate_count", None),
            candidates_truncated=getattr(exc, "candidates_truncated", False),
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
    source_paths = _source_paths(report)
    return {
        "provenance": _receipt_payload(result.receipt),
        "results": [
            _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
                source_paths,
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
    source_paths = _source_paths(report)
    status = statuses.get(result.node.source_id, report.status)
    return {
        "provenance": _receipt_payload(result.receipt),
        "node": _node_payload(
            result.node,
            result.receipt,
            status,
            result.truncated,
            source_paths,
        ),
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
    source_paths = _source_paths(report)
    paths = _traversal_paths(root_id, result.steps)
    return {
        "provenance": _receipt_payload(result.receipt),
        "nodes": [
            _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
                source_paths,
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
                source_paths,
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
    source_paths: Mapping[str, str],
) -> dict[str, object]:
    provider = node.provider if isinstance(node, TopologySymbol) else "topology"
    provider_key = _provider_key(receipt, node.source_id, provider)
    artifact_path = _provider_artifact_path(receipt, provider, node.source_id)
    source_relative_path = (
        source_paths.get(node.source_id)
        if isinstance(node, TopologySource)
        else getattr(node, "path", None)
    )
    return {
        "source_id": node.source_id,
        "provider": provider,
        "node_id": node.id,
        "node_type": node.type,
        "path": source_relative_path,
        "source_relative_path": source_relative_path,
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
    target_node = topology.nodes_by_id[relationship.target_id]
    provider_key = _provider_key(receipt, source_node.source_id, relationship.provider)
    source_relative_path = (
        relationship.path
        or getattr(source_node, "path", None)
        or getattr(target_node, "path", None)
    )
    return {
        "source_id": source_node.source_id,
        "provider": relationship.provider,
        "relation": relationship.type,
        "provider_relation": relationship.provider_kind,
        "source_node_id": relationship.source_id,
        "target_node_id": relationship.target_id,
        "path": source_relative_path,
        "source_relative_path": source_relative_path,
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
    source_paths: Mapping[str, str],
) -> dict[str, object]:
    node = topology.nodes_by_id[step.node_id]
    row = _node_payload(
        node,
        receipt,
        statuses.get(node.source_id, "current"),
        truncated,
        source_paths,
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
        "source_relative_path": getattr(source, "source_path"),
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
        "sources": [_audit_source_row(report, source) for source in report.sources],
        "findings": [_finding_payload(finding) for finding in findings],
        "findings_truncated": len(report.findings) > len(findings),
    }


def _audit_source_row(
    report: TopologyAuditReport, source: TopologyAuditSource
) -> dict[str, object]:
    snapshots = (
        {row.source_id: row for row in report.snapshot.sources}
        if report.snapshot is not None
        else {}
    )
    bound = snapshots.get(source.source_id)
    path = bound.source_path if bound is not None else None
    return {
        "source_id": source.source_id,
        "provider": "topology",
        "node_id": f"source:{source.source_id}",
        "path": path,
        "source_relative_path": path,
        "topology_generation": (
            report.snapshot.generation if report.snapshot is not None else None
        ),
        "status": source.status,
        "topology_status": source.status,
        "source_fingerprint": (
            bound.source_fingerprint if bound is not None else None
        ),
        "provider_receipt_hash": (
            bound.receipt_sha256 if bound is not None else None
        ),
        "providers": list(source.providers),
        "truncated": False,
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
            row = _audit_source_row(report, source)
            providers = ",".join(source.providers) or "none"
            lines.append(
                f"- node={row['node_id']} source={row['source_id']} "
                f"provider={row['provider']} path={row['path'] or '-'} "
                f"generation={row['topology_generation'] or '-'} "
                f"status={row['topology_status']} truncated=no providers={providers}"
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
            f"- node={row['node_id']} source={row['source_id']} "
            f"provider={row['provider']} path={row['source_relative_path']} "
            f"generation={row['topology_generation']} status={row['topology_status']} "
            f"truncated={_yes_no(bool(row['truncated']))} providers={providers or 'none'}"
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
        source_paths = _source_paths(report)
        for node in result.nodes:
            row = _node_payload(
                node,
                result.receipt,
                statuses.get(node.source_id, report.status),
                result.truncated,
                source_paths,
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
    source_paths = _source_paths(report)
    lines = [_read_header("explain", report, result.receipt, result.truncated)]
    _append_findings(lines, report)
    lines.append(
        _render_node_row(
            _node_payload(
                result.node,
                result.receipt,
                statuses.get(result.node.source_id, report.status),
                result.truncated,
                source_paths,
            )
        )
    )
    lines.append("Relationships:" if result.relationships else "Relationships: (none)")
    for relationship in result.relationships:
        lines.append(
            _render_relationship_row(
                _relationship_payload(
                    topology,
                    relationship,
                    result.receipt,
                    statuses,
                    result.truncated,
                )
            )
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
    source_paths = _source_paths(report)
    root = topology.nodes_by_id[root_id]
    lines.append("Root:")
    lines.append(
        _render_node_row(
            _node_payload(
                root,
                result.receipt,
                _source_statuses(report).get(root.source_id, report.status),
                result.truncated,
                source_paths,
            )
        )
    )
    lines.append("Steps:" if result.steps else "Steps: (none)")
    paths = _traversal_paths(root_id, result.steps)
    for index, step in enumerate(result.steps):
        row = _step_payload(
            topology,
            step,
            result.receipt,
            _source_statuses(report),
            result.truncated,
            paths[index],
            source_paths,
        )
        lines.append(
            f"- depth={row['depth']} direction={row['direction']} "
            f"relation={row['relation']} source_node={row['source_node_id']} "
            f"target_node={row['target_node_id']} node={row['node_id']} "
            f"source={row['source_id']} provider={row['provider']} "
            f"path={row['source_relative_path'] or '-'} "
            f"generation={row['topology_generation']} status={row['topology_status']} "
            f"truncated={_yes_no(bool(row['truncated']))} "
            f"traversal_path={' -> '.join(row['traversal_path'])}"
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


def _render_relationship_row(row: Mapping[str, object]) -> str:
    return (
        f"- relation={row['relation']} source_node={row['source_node_id']} "
        f"target_node={row['target_node_id']} source={row['source_id']} "
        f"provider={row['provider']} path={row['source_relative_path'] or '-'} "
        f"generation={row['topology_generation']} status={row['topology_status']} "
        f"truncated={_yes_no(bool(row['truncated']))}"
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
    message = (
        report.findings[0].message
        if report.findings
        else "topology audit is invalid"
    )
    payload = {
        "schema_version": 1,
        "command": command,
        "request": dict(request or {}),
        "audit": _audit_payload(report),
        "error": {
            "kind": "invalid",
            "message": _bounded_message(message),
            "candidates": [],
            "candidates_truncated": False,
        },
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
    candidate_count: int | None = None,
    candidates_truncated: bool = False,
) -> TopologyCliResult:
    bounded_candidates, output_truncated = _bounded_candidates(
        candidates,
        candidate_count=candidate_count,
        candidates_truncated=candidates_truncated,
    )
    payload = {
        "schema_version": 1,
        "command": command,
        "request": dict(request or {}),
        "audit": _audit_payload(report),
        "error": {
            "kind": kind,
            "message": _bounded_message(message),
            "candidates": list(bounded_candidates),
            "candidates_truncated": output_truncated,
        },
    }
    if as_json:
        rendered = _json(payload)
    else:
        rendered = f"Topology {command} failed [{kind}]: {_bounded_message(message)}\n"
        for candidate in bounded_candidates:
            rendered += f"- {candidate}\n"
        if output_truncated:
            total = max(len(candidates), candidate_count or 0)
            omitted = max(0, total - len(bounded_candidates))
            if omitted:
                rendered += f"- {omitted} additional candidates omitted\n"
            else:
                rendered += "- candidate output truncated\n"
    return TopologyCliResult(stderr=rendered, exit_code=2)


def _bounded_candidates(
    candidates: tuple[str, ...],
    *,
    candidate_count: int | None,
    candidates_truncated: bool,
) -> tuple[tuple[str, ...], bool]:
    selected = tuple(sorted(str(candidate) for candidate in candidates))[
        :_MAX_DIAGNOSTICS
    ]
    bounded: list[str] = []
    total_bytes = 0
    content_truncated = False
    for candidate in selected:
        value, shortened = _bounded_utf8(candidate, _MAX_CANDIDATE_BYTES)
        remaining = _MAX_CANDIDATES_TOTAL_BYTES - total_bytes
        if remaining <= 0:
            content_truncated = True
            break
        if len(value.encode("utf-8")) > remaining:
            value, shortened_for_total = _bounded_utf8(value, remaining)
            shortened = shortened or shortened_for_total
        if not value:
            content_truncated = True
            break
        bounded.append(value)
        total_bytes += len(value.encode("utf-8"))
        content_truncated = content_truncated or shortened
    known_count = max(len(candidates), candidate_count or 0)
    truncated = (
        candidates_truncated
        or known_count > len(bounded)
        or len(candidates) > len(selected)
        or content_truncated
    )
    return tuple(bounded), truncated


def _bounded_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value, False
    if max_bytes <= 0:
        return "", True
    suffix = b"..."[:max_bytes]
    prefix = raw[: max_bytes - len(suffix)].decode("utf-8", errors="ignore")
    return prefix + suffix.decode("ascii"), True


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


def _read_source_ids(
    topology: PublishedTopology, source_id: str | None
) -> tuple[str, ...]:
    if source_id is not None:
        return (source_id,)
    return tuple(
        sorted(
            node.source_id
            for node in topology.nodes_by_id.values()
            if isinstance(node, TopologySource)
        )
    )


def _topology_binding(
    topology: PublishedTopology, source_ids: tuple[str, ...]
) -> tuple[object, ...]:
    rows: list[tuple[object, ...]] = []
    for source_id in source_ids:
        receipt = topology.receipt(source_id)
        rows.append(
            (
                source_id,
                receipt.source_fingerprint,
                tuple(receipt.provider_receipt_hashes.items()),
                tuple(receipt.provider_artifact_paths),
                tuple(receipt.provider_statuses.items()),
            )
        )
    return (topology.generation, tuple(rows))


def _assert_topology_matches_audit(
    topology: PublishedTopology,
    report: TopologyAuditReport,
    source_ids: tuple[str, ...],
) -> None:
    snapshot = report.snapshot
    if snapshot is None:
        return
    if topology.generation != snapshot.generation:
        raise TopologyRegistryError("topology publication changed during read")
    audited = {source.source_id: source for source in snapshot.sources}
    if set(audited) != set(source_ids):
        raise TopologyRegistryError("topology publication changed during read")
    for source_id in source_ids:
        receipt = topology.receipt(source_id)
        expected = audited[source_id]
        if receipt.source_fingerprint != expected.source_fingerprint:
            raise TopologyRegistryError("topology publication changed during read")
        receipt_hashes = set(receipt.provider_receipt_hashes.values())
        if receipt_hashes and receipt_hashes != {expected.receipt_sha256}:
            raise TopologyRegistryError("topology publication changed during read")


def _assert_audit_matches_snapshot(
    report: TopologyAuditReport, snapshot: TopologyAuditSnapshot
) -> None:
    if report.snapshot is not None and report.snapshot != snapshot:
        raise TopologyRegistryError("topology publication changed during read")


def _merge_audit_reports(
    initial: TopologyAuditReport, final: TopologyAuditReport
) -> TopologyAuditReport:
    priority = {"current": 0, "degraded": 1, "stale": 2, "invalid": 3}
    source_rows: dict[str, TopologyAuditSource] = {}
    for source in (*initial.sources, *final.sources):
        existing = source_rows.get(source.source_id)
        if existing is None or priority[source.status] > priority[existing.status]:
            source_rows[source.source_id] = source
    findings = tuple(
        sorted(
            set((*initial.findings, *final.findings)),
            key=lambda finding: (
                finding.source_id or "",
                finding.provider or "",
                finding.path or "",
                finding.status,
                finding.message,
            ),
        )
    )
    status = max(
        (initial.status, final.status),
        key=lambda value: priority[value],
    )
    return TopologyAuditReport(
        status=status,
        exit_code=0 if status == "current" else 2 if status == "invalid" else 1,
        sources=tuple(source_rows[source_id] for source_id in sorted(source_rows)),
        findings=findings,
        snapshot=final.snapshot,
    )


def _audit_at_boundary(
    root: Path, source_id: str | None = None
) -> tuple[TopologyAuditReport, BaseException | None]:
    try:
        return audit_topology(root, source_id=source_id), None
    except (
        OSError,
        TopologyProviderError,
        TopologyRegistryError,
        TopologyValidationError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        message = _bounded_message(f"workspace config or topology audit failed: {exc}")
        return (
            TopologyAuditReport(
                status="invalid",
                exit_code=2,
                sources=(),
                findings=(
                    TopologyAuditFinding(
                        "invalid",
                        message,
                        source_id=source_id,
                    ),
                ),
            ),
            ValueError(message),
        )


def _source_statuses(report: TopologyAuditReport) -> dict[str, str]:
    return {source.source_id: source.status for source in report.sources}


def _source_paths(report: TopologyAuditReport) -> dict[str, str]:
    if report.snapshot is None:
        return {}
    return {
        source.source_id: source.source_path
        for source in report.snapshot.sources
    }


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
