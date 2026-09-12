"""Pure graph contribution from captured memory sources, plans and observations.

The caller owns acquisition and observation authentication. This projection does
not plan, audit storage, establish current evidence, or produce a complete graph.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

from echelon.mempalace_requirements import PlannedRequirementDrawer
from echelon.spec_memory_miner import CanonicalRequirementDrawerPlan
from echelon.spec_graph import (
    GraphEdge, GraphInput, GraphNode, MemoryReceipt, SpecGraphError, _canonical_digest,
)
from echelon.spec_graph_structure import (
    _add_artifact_record, _artifact_required, _validate_scope,
)
from harness.squad_source_snapshot import _source_path


@dataclass(frozen=True, slots=True)
class GraphMemorySource:
    path: str
    content: bytes
    artifact_kind: str
    room: str


@dataclass(frozen=True, slots=True)
class GraphMemoryAudit:
    origin: str
    schema_version: int
    wing: str | None
    status: str
    artifact_count: int
    expected_count: int
    present_current_count: int
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    wrong_wing: tuple[str, ...]
    wrong_room: tuple[str, ...]
    duplicate: tuple[str, ...]
    non_canonical: tuple[str, ...]
    lifecycle_excluded: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryGraphContribution:
    spec_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    receipt: MemoryReceipt


_ISSUE_FIELDS = (
    "missing", "stale", "wrong_wing", "wrong_room", "duplicate",
    "non_canonical", "lifecycle_excluded", "errors",
)
_ROW_FIELDS = (
    "drawer_id", "requirement_id", "room", "source", "artifact_hash",
    "canonical_spec_sha256", "requirement_content_sha256",
)


def _text(value: object, *, nonempty: bool = False) -> None:
    if type(value) is not str or (nonempty and not value):
        raise ValueError("invalid text")
    value.encode("utf-8")


def _audit_report(audit: GraphMemoryAudit) -> object:
    if type(audit) is not GraphMemoryAudit:
        raise ValueError("invalid audit")
    if type(audit.origin) is not str or audit.origin not in {"returned", "exception"}:
        raise ValueError("invalid audit origin")
    values = {}
    for field in ("schema_version", "artifact_count", "expected_count", "present_current_count"):
        value = getattr(audit, field)
        if type(value) is not int or value < 0:
            raise ValueError("invalid counter")
        values[field] = value
    if audit.wing is not None:
        _text(audit.wing)
    _text(audit.status, nonempty=True)
    values.update(wing=audit.wing, status=audit.status)
    for field in _ISSUE_FIELDS:
        items = getattr(audit, field)
        if type(items) is not tuple:
            raise ValueError("invalid issue collection")
        for item in items:
            _text(item)
        # Legacy drawer interpretation is deliberately list-only.
        values[field] = list(items)
    if audit.origin == "exception" and (
        audit.schema_version != 1 or audit.wing is not None or audit.status != "unavailable"
        or any(values[field] != 0 for field in (
            "artifact_count", "expected_count", "present_current_count",
        ))
        or any(values[field] for field in _ISSUE_FIELDS if field != "errors")
        or len(audit.errors) != 1 or not audit.errors[0]
    ):
        raise ValueError("invalid exception observation")
    return SimpleNamespace(**values)


def build_memory_graph_contribution(
    *, spec_id: str, lifecycle: str, domain: str,
    sources: tuple[GraphMemorySource, ...],
    planned_rows: tuple[PlannedRequirementDrawer | CanonicalRequirementDrawerPlan, ...],
    audit: GraphMemoryAudit,
    known_node_ids: tuple[str, ...],
) -> MemoryGraphContribution:
    """Project detached supplied values; ordinary failures never expose inputs."""
    try:
        return _build_memory_graph_contribution(
            spec_id=spec_id, lifecycle=lifecycle, domain=domain, sources=sources,
            planned_rows=planned_rows, audit=audit, known_node_ids=known_node_ids,
        )
    except Exception:
        pass
    # Raising outside the handler avoids retaining source-bearing exceptions.
    raise SpecGraphError("invalid captured memory graph contribution")


def _build_memory_graph_contribution(
    *, spec_id: str, lifecycle: str, domain: str,
    sources: tuple[GraphMemorySource, ...],
    planned_rows: tuple[PlannedRequirementDrawer | CanonicalRequirementDrawerPlan, ...],
    audit: GraphMemoryAudit,
    known_node_ids: tuple[str, ...],
) -> MemoryGraphContribution:
    spec_path = _validate_scope(spec_id, lifecycle)
    if type(domain) is not str or domain not in {"canonical-spec", "spec-evidence", "published-re"}:
        raise ValueError("invalid memory domain")
    if any(type(items) is not tuple for items in (sources, planned_rows, known_node_ids)):
        raise ValueError("invalid collection")
    for node_id in known_node_ids:
        _text(node_id, nonempty=True)
    if len(set(known_node_ids)) != len(known_node_ids):
        raise ValueError("duplicate node ID")
    report = _audit_report(audit)
    source_root = PurePosixPath("re") if domain == "published-re" else spec_path
    by_path = {}
    source_records = []
    for source in sources:
        if type(source) is not GraphMemorySource or type(source.content) is not bytes:
            raise ValueError("invalid source")
        path = PurePosixPath(_source_path(source.path).as_posix())
        if path.as_posix() != source.path or source_root not in path.parents:
            raise ValueError("invalid source path")
        if source.path in by_path:
            raise ValueError("duplicate source")
        _text(source.artifact_kind, nonempty=True)
        _text(source.room)
        digest = hashlib.sha256(source.content).hexdigest()
        by_path[source.path] = (source, digest)
        source_records.append({
            "path": source.path, "hash": "sha256:" + digest,
            "artifact_kind": source.artifact_kind, "room": source.room,
        })
    drawer_ids = set()
    for row in planned_rows:
        if type(row) not in (PlannedRequirementDrawer, CanonicalRequirementDrawerPlan):
            raise ValueError("invalid planned row")
        for field in _ROW_FIELDS:
            _text(getattr(row, field), nonempty=True)
        for field in ("canonical_spec_sha256", "requirement_content_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", getattr(row, field)) is None:
                raise ValueError("invalid SHA256")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", row.artifact_hash) is None:
            raise ValueError("invalid artifact hash")
        if row.source not in by_path:
            raise ValueError("missing planned source")
        digest = by_path[row.source][1]
        if row.artifact_hash != "sha256:" + digest or row.canonical_spec_sha256 != digest:
            raise ValueError("incoherent planned source")
        if row.drawer_id in drawer_ids:
            raise ValueError("duplicate drawer ID")
        drawer_ids.add(row.drawer_id)
    if domain == "published-re" and audit.origin == "returned":
        report = _project_memory_audit(report, drawer_ids)
    virtual_path = (
        "mempalace://published-re/audit" if domain == "published-re"
        else f"mempalace://{domain}/{spec_id}/audit"
    )
    receipt, audit_input = _memory_receipt_records(
        domain=domain, virtual_path=virtual_path,
        source_set_digest=_source_records_digest(source_records),
        report=report, required=domain == "canonical-spec",
    )
    nodes: dict[str, GraphNode] = {}
    inputs: dict[str, GraphInput] = {}
    edges: list[GraphEdge] = []
    role = {
        "canonical-spec": "supporting-context",
        "spec-evidence": "verification-evidence",
        "published-re": "reverse-engineering",
    }[domain]
    for source, digest in by_path.values():
        path = PurePosixPath(source.path)
        if domain == "canonical-spec" and path == spec_path / "spec.md":
            continue
        _add_artifact_record(
            spec_id, source.path, path.name, "sha256:" + digest, role,
            _artifact_required(spec_path, path, lifecycle), nodes, inputs,
        )
    inputs[virtual_path] = audit_input
    for record in _drawer_records(
        spec_id, planned_rows, report, (*known_node_ids, *nodes),
        source_artifact_kind={source.path: source.artifact_kind for source in sources},
    ):
        if isinstance(record, GraphNode):
            nodes[record.id] = record
        else:
            edges.append(record)
    return MemoryGraphContribution(
        spec_id, tuple(inputs.values()), deepcopy(tuple(nodes.values())),
        deepcopy(tuple(edges)), receipt,
    )


def _source_records_digest(records: list[dict[str, str]]) -> str:
    return _canonical_digest(sorted(records, key=lambda item: item["path"]))


def _memory_receipt_records(
    *, domain: str, virtual_path: str, source_set_digest: str,
    report: object, required: bool,
) -> tuple[MemoryReceipt, GraphInput]:
    audit_hash = _canonical_digest(_normalized_memory_audit(report))
    status = str(getattr(report, "status", "unavailable"))
    return (
        MemoryReceipt(domain, source_set_digest, audit_hash, status),
        GraphInput(virtual_path, audit_hash, "memory_audit_report", required,
                   status, source_set_digest),
    )


def _project_memory_audit(report: object, drawer_ids: set[str]) -> object:
    projected: dict[str, list[str]] = {}
    fail_fields = (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "non_canonical",
        "lifecycle_excluded",
    )
    for field in (*fail_fields, "duplicate"):
        projected[field] = sorted(
            value
            for value in getattr(report, field, [])
            if value in drawer_ids
        )
    projected["errors"] = sorted(
        value
        for value in getattr(report, "errors", [])
        if any(str(value).startswith(drawer_id) for drawer_id in drawer_ids)
    )
    if str(getattr(report, "status", "")) == "unavailable":
        status = "unavailable"
    elif any(projected[field] for field in fail_fields):
        status = "fail"
    elif projected["duplicate"] or projected["errors"]:
        status = "warn"
    else:
        status = "pass"
    return _ProjectedMemoryReport(
        report=report,
        status=status,
        expected_count=len(drawer_ids),
        issues=projected,
    )


class _ProjectedMemoryReport:
    def __init__(
        self,
        *,
        report: object,
        status: str,
        expected_count: int,
        issues: Mapping[str, list[str]],
    ) -> None:
        self.schema_version = int(getattr(report, "schema_version", 1))
        self.wing = getattr(report, "wing", None)
        self.status = status
        self.artifact_count = 0
        self.expected_count = expected_count
        failed_ids: set[str] = set()
        for field in (
            "missing",
            "stale",
            "wrong_wing",
            "wrong_room",
            "non_canonical",
            "lifecycle_excluded",
        ):
            failed_ids.update(issues[field])
        self.present_current_count = expected_count - len(failed_ids)
        for field, values in issues.items():
            setattr(self, field, values)


def _drawer_records(
    spec_id: str,
    planned_rows: Iterable[object],
    report: object,
    known_node_ids: Iterable[str],
    *,
    source_artifact_kind: Mapping[str, str],
) -> Iterator[GraphNode | GraphEdge]:
    """Yield records in legacy update order, including before endpoint failures."""
    available = set(known_node_ids)
    issue_fields = (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "non_canonical",
        "lifecycle_excluded",
        "duplicate",
    )
    issues_by_id: dict[str, list[str]] = {}
    for field in issue_fields:
        values = getattr(report, field, [])
        if not isinstance(values, list):
            continue
        for drawer_id in values:
            if isinstance(drawer_id, str):
                issues_by_id.setdefault(drawer_id, []).append(field)
    status = str(getattr(report, "status", "unavailable"))

    for row in planned_rows:
        drawer_id = str(getattr(row, "drawer_id"))
        source = str(getattr(row, "source"))
        requirement_id = str(getattr(row, "requirement_id", ""))
        issue_codes = sorted(issues_by_id.get(drawer_id, []))
        if status == "unavailable":
            presence = "unavailable"
            reconciliation_status = "unavailable"
        elif "missing" in issue_codes:
            presence = "missing"
            reconciliation_status = "fail"
        elif issue_codes:
            presence = "invalid"
            reconciliation_status = "fail"
        else:
            presence = "present"
            reconciliation_status = "pass"

        node_id = f"drawer:{spec_id}:{drawer_id}"
        available.add(node_id)
        yield GraphNode(
            node_id,
            "MemPalaceDrawer",
            {
                "drawer_id": drawer_id,
                "source_path": source,
                "room": str(getattr(row, "room", "")),
                "artifact_kind": source_artifact_kind.get(source, "unknown"),
                "artifact_hash": str(getattr(row, "artifact_hash", "")),
                "content_hash": str(
                    getattr(row, "requirement_content_sha256", "")
                ),
                "presence": presence,
                "reconciliation_status": reconciliation_status,
                "issue_codes": issue_codes,
            },
        )
        requirement_node = f"req:{spec_id}:{requirement_id}"
        artifact_node = f"artifact:{spec_id}:{source}"
        source_node = (
            requirement_node
            if requirement_node in available and source_artifact_kind.get(source) == "requirement"
            else artifact_node
        )
        if source_node not in available:
            raise SpecGraphError(
                f"memory planner source has no Artifact node: {source}"
            )
        yield GraphEdge(
            source_node,
            "STORED_AS",
            node_id,
            {
                "presence": presence,
                "reconciliation_status": reconciliation_status,
            },
        )


def _normalized_memory_audit(report: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": int(getattr(report, "schema_version", 1)),
        "wing": getattr(report, "wing", None),
        "status": str(getattr(report, "status", "unavailable")),
        "artifact_count": int(getattr(report, "artifact_count", 0)),
        "expected_count": int(getattr(report, "expected_count", 0)),
        "present_current_count": int(
            getattr(report, "present_current_count", 0)
        ),
    }
    for field in (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "duplicate",
        "non_canonical",
        "lifecycle_excluded",
        "errors",
    ):
        values = getattr(report, field, [])
        payload[field] = sorted(str(value) for value in values)
    return payload
