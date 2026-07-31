"""Freshness and coherence audit for spec artifact graphs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from echelon.mempalace_requirements import resolve_spec_dir
from echelon.spec_graph import (
    GRAPH_FILENAME,
    GRAPH_SCHEMA_VERSION,
    NODE_PROJECTION_VERSION,
    GraphEdge,
    GraphNode,
    SpecArtifactGraph,
    SpecGraphError,
    _validate_graph,
    build_spec_graph,
)


GRAPH_AUDIT_FILENAME = "spec-artifact-graph-audit.json"
REBUILDABLE_GRAPH_FINDING_CODES = frozenset(
    {
        "graph_missing",
        "graph_invalid",
        "graph_inputs_invalid",
        "graph_projection_stale",
        "graph_source_set_stale",
        "graph_memory_state_stale",
        "graph_input_added",
        "graph_input_removed",
        "graph_input_changed",
        "graph_body_stale",
    }
)


@dataclass(frozen=True)
class GraphFinding:
    severity: str
    code: str
    message: str
    subject_id: str | None = None

    @property
    def id(self) -> str:
        return f"finding:{self.code}:{self.subject_id or 'graph'}"

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
class SpecGraphAuditReport:
    schema_version: int
    spec_id: str
    graph_hash: str | None
    status: str
    findings: tuple[GraphFinding, ...]
    recommendations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "graph_hash": self.graph_hash,
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "recommendations": list(self.recommendations),
        }


def classify_spec_graph_audit(report: object) -> str:
    """Classify whether a live graph audit is current, stale, or unhealthy."""
    status = getattr(report, "status", None)
    if status in {"pass", "warn"}:
        return "current"
    finding_codes = {
        getattr(finding, "code", None)
        for finding in getattr(report, "findings", ())
    }
    if finding_codes & REBUILDABLE_GRAPH_FINDING_CODES:
        return "stale"
    if status == "unavailable" or "graph_source_unavailable" in finding_codes:
        return "unavailable"
    return "unhealthy"


def audit_spec_graph(
    project_root: Path,
    selector: str | Path,
) -> SpecGraphAuditReport:
    spec_dir = resolve_spec_dir(project_root, selector)
    graph_path = spec_dir / GRAPH_FILENAME
    if not graph_path.is_file():
        finding = GraphFinding(
            "error",
            "graph_missing",
            f"graph artifact is missing: {graph_path}",
        )
        return _report(
            spec_id=spec_dir.name,
            graph_hash=None,
            findings=[finding],
            unavailable=True,
        )

    graph_bytes = graph_path.read_bytes()
    graph_hash = f"sha256:{hashlib.sha256(graph_bytes).hexdigest()}"
    try:
        stored = _read_graph_payload(graph_bytes)
    except SpecGraphError as exc:
        return _report(
            spec_id=spec_dir.name,
            graph_hash=graph_hash,
            findings=[
                GraphFinding("error", "graph_invalid", str(exc))
            ],
        )

    findings = _projection_findings(stored)
    try:
        current = build_spec_graph(project_root, spec_dir)
    except Exception as exc:
        return _report(
            spec_id=spec_dir.name,
            graph_hash=graph_hash,
            findings=[
                *findings,
                GraphFinding(
                    "error",
                    "graph_source_unavailable",
                    f"current graph sources are unavailable: {type(exc).__name__}",
                )
            ],
            unavailable=True,
        )

    if stored.get("source_set_digest") != current.source_set_digest:
        findings.append(
            GraphFinding(
                "error",
                "graph_source_set_stale",
                "graph source-set digest differs from current canonical inputs",
            )
        )
    if stored.get("memory_state_digest") != current.memory_state_digest:
        findings.append(
            GraphFinding(
                "error",
                "graph_memory_state_stale",
                "graph memory-state digest differs from current MemPalace receipts",
            )
        )

    findings.extend(_input_findings(stored, current))
    current_document = current.to_dict()
    if (
        stored.get("nodes") != current_document["nodes"]
        or stored.get("edges") != current_document["edges"]
    ):
        findings.append(
            GraphFinding(
                "error",
                "graph_body_stale",
                "graph nodes or edges differ from the current build",
            )
        )
    memory_findings, required_memory_unavailable = _memory_findings(current)
    findings.extend(memory_findings)
    findings.extend(_coherence_findings(current))
    return _report(
        spec_id=spec_dir.name,
        graph_hash=graph_hash,
        findings=findings,
        unavailable=required_memory_unavailable,
    )


def write_spec_graph_audit(
    report: SpecGraphAuditReport,
    spec_dir: Path,
) -> Path:
    path = spec_dir / GRAPH_AUDIT_FILENAME
    path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read_graph_payload(graph_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(graph_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecGraphError("graph JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise SpecGraphError("graph JSON must be an object")
    if payload.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise SpecGraphError("unsupported graph schema version")
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise SpecGraphError("graph nodes and edges must be lists")
    try:
        nodes = tuple(
            GraphNode(
                id=str(item["id"]),
                type=str(item["type"]),
                properties=_mapping(item["properties"]),
            )
            for item in raw_nodes
            if isinstance(item, dict)
        )
        edges = tuple(
            GraphEdge(
                source=str(item["source"]),
                type=str(item["type"]),
                target=str(item["target"]),
                properties=_mapping(item["properties"]),
            )
            for item in raw_edges
            if isinstance(item, dict)
        )
    except (KeyError, TypeError) as exc:
        raise SpecGraphError("graph node or edge contract is invalid") from exc
    if len(nodes) != len(raw_nodes) or len(edges) != len(raw_edges):
        raise SpecGraphError("graph node or edge must be an object")
    _validate_graph(nodes, edges)
    return payload


def _projection_findings(stored: Mapping[str, object]) -> list[GraphFinding]:
    projection_version = stored.get("node_projection_version", 1)
    if (
        type(projection_version) is not int
        or projection_version != NODE_PROJECTION_VERSION
    ):
        return [
            GraphFinding(
                "error",
                "graph_projection_stale",
                f"graph projection version {projection_version} is stale",
            )
        ]

    for item in stored.get("nodes", []):
        if not isinstance(item, Mapping) or item.get("type") != "Requirement":
            continue
        properties = item.get("properties")
        if not isinstance(properties, Mapping):
            break
        source_text = properties.get("source_text")
        source_path = properties.get("source_path")
        source_line = properties.get("source_line")
        if (
            not isinstance(source_text, str)
            or not source_text
            or not isinstance(source_path, str)
            or not source_path
            or type(source_line) is not int
            or source_line <= 0
        ):
            break
    else:
        return []

    return [
        GraphFinding(
            "error",
            "graph_projection_stale",
            "graph requirement projection is stale",
        )
    ]


def _input_findings(
    stored: Mapping[str, object],
    current: SpecArtifactGraph,
) -> list[GraphFinding]:
    raw_inputs = stored.get("inputs", [])
    if not isinstance(raw_inputs, list):
        return [
            GraphFinding("error", "graph_inputs_invalid", "graph inputs must be a list")
        ]
    stored_by_path = {
        str(item.get("path")): item
        for item in raw_inputs
        if isinstance(item, dict) and item.get("path")
    }
    current_by_path = {item.path: item.to_dict() for item in current.inputs}
    findings: list[GraphFinding] = []
    for path in sorted(current_by_path.keys() - stored_by_path.keys()):
        findings.append(
            GraphFinding(
                "error",
                "graph_input_added",
                f"input was added after graph build: {path}",
                path,
            )
        )
    for path in sorted(stored_by_path.keys() - current_by_path.keys()):
        findings.append(
            GraphFinding(
                "error",
                "graph_input_removed",
                f"input was removed after graph build: {path}",
                path,
            )
        )
    for path in sorted(stored_by_path.keys() & current_by_path.keys()):
        old = stored_by_path[path]
        new = current_by_path[path]
        if (
            old.get("hash") != new.get("hash")
            or old.get("required") != new.get("required")
            or old.get("role") != new.get("role")
            or old.get("source_set_digest") != new.get("source_set_digest")
        ):
            findings.append(
                GraphFinding(
                    "error",
                    "graph_input_changed",
                    f"input changed after graph build: {path}",
                    path,
                )
            )
    return findings


def _memory_findings(
    graph: SpecArtifactGraph,
) -> tuple[list[GraphFinding], bool]:
    findings: list[GraphFinding] = []
    required_unavailable = False
    for item in sorted(graph.inputs, key=lambda value: value.path):
        if item.role != "memory_audit_report" or item.status == "pass":
            continue
        if item.status == "unavailable":
            severity = "error" if item.required else "warning"
            code = "mempalace_reconciliation_unavailable"
            required_unavailable = required_unavailable or item.required
        elif item.status == "warn":
            severity = "warning"
            code = "mempalace_reconciliation_warning"
        else:
            severity = "error"
            code = "mempalace_reconciliation_failed"
        findings.append(
            GraphFinding(
                severity,
                code,
                f"native memory audit is {item.status}: {item.path}",
                item.path,
            )
        )
    return findings, required_unavailable


def _coherence_findings(graph: SpecArtifactGraph) -> list[GraphFinding]:
    nodes = {node.id: node for node in graph.nodes}
    outgoing: dict[tuple[str, str], list[GraphEdge]] = {}
    for edge in graph.edges:
        outgoing.setdefault((edge.source, edge.type), []).append(edge)
    spec = next((node for node in graph.nodes if node.type == "Spec"), None)
    lifecycle = str((spec.properties if spec else {}).get("lifecycle") or "phase_a")
    findings: list[GraphFinding] = []

    for node in sorted(graph.nodes, key=lambda value: value.id):
        if node.type == "Task":
            unresolved = node.properties.get("unresolved_requirement_ids", [])
            if isinstance(unresolved, list):
                for requirement_id in sorted(str(value) for value in unresolved):
                    findings.append(
                        GraphFinding(
                            "error",
                            "task_requirement_unknown",
                            f"task references requirement absent from spec.md: {requirement_id}",
                            node.id,
                        )
                    )
        if node.type != "Requirement":
            continue
        deferred = bool(outgoing.get((node.id, "DEFERRED_BY")))
        implemented = any(
            edge.type == "IMPLEMENTS" and edge.target == node.id
            for edge in graph.edges
        )
        task_addressable = node.properties.get("category") in {
            "functional",
            "non_functional",
        }
        if task_addressable and not implemented and not deferred:
            severity = (
                "error"
                if lifecycle in {"build", "verified", "landed"}
                else "warning"
            )
            findings.append(
                GraphFinding(
                    severity,
                    "requirement_task_missing",
                    "active requirement has no mapped task",
                    node.id,
                )
            )
        verified = any(
            edge.type == "VERIFIED_BY"
            and edge.source == node.id
            and edge.properties.get("complete") is True
            for edge in graph.edges
        )
        if lifecycle in {"verified", "landed"} and not verified and not deferred:
            findings.append(
                GraphFinding(
                    "error",
                    "requirement_verification_missing",
                    "active requirement has no complete verification evidence",
                    node.id,
                )
            )

    for node in sorted(graph.nodes, key=lambda value: value.id):
        if node.type != "Deferral":
            continue
        selected = node.properties.get("selected_ids", [])
        derived = node.properties.get("derived_task_ids", [])
        selected_values = selected if isinstance(selected, list) else []
        derived_values = derived if isinstance(derived, list) else []
        expected_ids = [
            _scope_node_id(graph.spec_id, str(value))
            for value in [*selected_values, *derived_values]
        ]
        for expected in sorted(set(expected_ids)):
            if expected not in nodes:
                findings.append(
                    GraphFinding(
                        "error",
                        "deferral_subject_unknown",
                        f"deferral references unknown graph subject: {expected}",
                        node.id,
                    )
                )
    return findings


def _report(
    *,
    spec_id: str,
    graph_hash: str | None,
    findings: Iterable[GraphFinding],
    unavailable: bool = False,
) -> SpecGraphAuditReport:
    merged = {
        (finding.code, finding.subject_id): finding
        for finding in findings
    }
    ordered = tuple(sorted(merged.values(), key=lambda finding: finding.id))
    if unavailable:
        status = "unavailable"
    elif any(finding.severity == "error" for finding in ordered):
        status = "fail"
    elif ordered:
        status = "warn"
    else:
        status = "pass"
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id=spec_id,
        graph_hash=graph_hash,
        status=status,
        findings=ordered,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError("properties must be an object")
    return value


def _scope_node_id(spec_id: str, item_id: str) -> str:
    if item_id.startswith("T-"):
        return f"task:{spec_id}:{item_id}"
    return f"req:{spec_id}:{item_id}"
