from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Iterable

from echelon.mempalace_requirements import SpecMemoryError

MAX_MEMORY_AUDIT_SCAN_ROWS = 10_000


@dataclass(frozen=True)
class ArtifactMemoryAuditReport:
    schema_version: int
    label: str
    root: str
    wing: str | None
    palace_path: str | None
    status: str
    artifact_count: int
    expected_count: int
    present_current_count: int
    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    wrong_wing: list[str] = field(default_factory=list)
    wrong_room: list[str] = field(default_factory=list)
    non_canonical: list[str] = field(default_factory=list)
    lifecycle_excluded: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": self.label,
            "root": self.root,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "status": self.status,
            "artifact_count": self.artifact_count,
            "expected_count": self.expected_count,
            "present_current_count": self.present_current_count,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "wrong_wing": list(self.wrong_wing),
            "wrong_room": list(self.wrong_room),
            "non_canonical": list(self.non_canonical),
            "lifecycle_excluded": list(self.lifecycle_excluded),
            "duplicate": list(self.duplicate),
            "errors": list(self.errors),
            "recommendations": list(self.recommendations),
        }


@dataclass(frozen=True)
class _CollectionRows:
    rows: dict[str, tuple[str, dict[str, Any]]]
    malformed: dict[str, tuple[str, ...]]


def render_artifact_memory_audit_markdown(report: ArtifactMemoryAuditReport) -> str:
    lines = [
        f"# MemPalace {report.label} Audit",
        "",
        f"- Status: {report.status}",
        f"- Artifacts: {report.artifact_count}",
        f"- Expected drawers: {report.expected_count}",
        f"- Present current drawers: {report.present_current_count}",
        f"- Missing: {len(report.missing)}",
        f"- Stale: {len(report.stale)}",
        f"- Wrong wing: {len(report.wrong_wing)}",
        f"- Wrong room: {len(report.wrong_room)}",
        f"- Non-canonical: {len(report.non_canonical)}",
        f"- Lifecycle excluded: {len(report.lifecycle_excluded)}",
        f"- Duplicate: {len(report.duplicate)}",
    ]
    return "\n".join(lines) + "\n"


def audit_artifact_memory(
    *,
    label: str,
    root: Path,
    snapshots: list[object],
    adapter: object,
    artifact_kind: str,
    scope: str,
    spec_id: str | None = None,
    planner_name: str,
) -> ArtifactMemoryAuditReport:
    try:
        expected_rows = _plan_expected_rows(
            snapshots=snapshots,
            adapter=adapter,
            planner_name=planner_name,
        )
    except (Exception, SystemExit) as exc:
        return _report(
            label=label,
            root=root,
            adapter=adapter,
            status="fail",
            artifact_count=len(snapshots),
            expected_count=0,
            errors=[type(exc).__name__],
        )

    expected_ids = [row.drawer_id for row in expected_rows]
    try:
        collection = _collection_from_adapter(adapter)
        raw = (
            collection.get(
                ids=expected_ids,
                include=["documents", "metadatas"],
            )
            if expected_ids
            else {"ids": [], "documents": [], "metadatas": []}
        )
        parsed = _as_collection_rows(raw)
    except (Exception, SystemExit) as exc:
        return _report(
            label=label,
            root=root,
            adapter=adapter,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=len(expected_ids),
            errors=[type(exc).__name__],
        )

    present = 0
    missing: list[str] = []
    stale: list[str] = []
    wrong_wing: list[str] = []
    wrong_room: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    duplicate: list[str] = []
    errors: list[str] = []

    rows = parsed.rows
    for drawer_id, reasons in parsed.malformed.items():
        errors.extend(f"{drawer_id}:{reason}" for reason in reasons)
        _append_unique(non_canonical, drawer_id)

    expected_by_id = {row.drawer_id: row for row in expected_rows}
    for drawer_id in expected_ids:
        planned = expected_by_id[drawer_id]
        row = rows.get(drawer_id)
        if row is None:
            if drawer_id not in parsed.malformed:
                missing.append(drawer_id)
            continue
        document, metadata = row
        if metadata.get("wing") != getattr(adapter, "wing", None):
            _append_unique(wrong_wing, drawer_id)
        if metadata.get("room") != planned.room:
            _append_unique(wrong_room, drawer_id)
        if _is_lifecycle_excluded(metadata):
            _append_unique(lifecycle_excluded, drawer_id)
        if not _has_expected_identity(
            metadata,
            planned=planned,
            artifact_kind=artifact_kind,
            scope=scope,
            spec_id=spec_id,
        ):
            _append_unique(non_canonical, drawer_id)
        if not _has_expected_hashes(document, metadata, planned=planned):
            _append_unique(stale, drawer_id)
        if any(
            drawer_id in values
            for values in (
                stale,
                wrong_wing,
                wrong_room,
                non_canonical,
                lifecycle_excluded,
            )
        ):
            continue
        present += 1

    try:
        extra_stale, extra_non_canonical, extra_lifecycle, extra_duplicate = _scan_extras(
            collection=collection,
            adapter=adapter,
            expected_rows=expected_rows,
            artifact_kind=artifact_kind,
            spec_id=spec_id,
        )
    except (Exception, SystemExit) as exc:
        return _report(
            label=label,
            root=root,
            adapter=adapter,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=len(expected_ids),
            errors=[type(exc).__name__],
        )
    for value in extra_stale:
        _append_unique(stale, value)
    for value in extra_non_canonical:
        _append_unique(non_canonical, value)
    for value in extra_lifecycle:
        _append_unique(lifecycle_excluded, value)
    for value in extra_duplicate:
        _append_unique(duplicate, value)

    status = "pass"
    if any((missing, stale, wrong_wing, wrong_room, non_canonical, lifecycle_excluded)):
        status = "fail"
    elif duplicate or errors:
        status = "warn"
    return _report(
        label=label,
        root=root,
        adapter=adapter,
        status=status,
        artifact_count=len(snapshots),
        expected_count=len(expected_ids),
        present_current_count=present,
        missing=missing,
        stale=stale,
        wrong_wing=wrong_wing,
        wrong_room=wrong_room,
        non_canonical=non_canonical,
        lifecycle_excluded=lifecycle_excluded,
        duplicate=duplicate,
        errors=errors,
    )


def _plan_expected_rows(
    *,
    snapshots: list[object],
    adapter: object,
    planner_name: str,
) -> list[object]:
    planner = getattr(adapter, planner_name)
    expected: list[object] = []
    for snapshot in snapshots:
        expected.extend(
            planner(
                getattr(snapshot, "content"),
                source=getattr(snapshot, "source"),
                artifact_metadata=getattr(snapshot, "artifact_metadata"),
            )
        )
    return expected


def _collection_from_adapter(adapter: object) -> object:
    opener = getattr(adapter, "open_collection_read_only", None)
    if callable(opener):
        return opener()
    raise SpecMemoryError("MemPalace collection is unavailable")


def _as_collection_rows(raw: object) -> _CollectionRows:
    if not isinstance(raw, dict):
        raise SpecMemoryError("invalid MemPalace collection response")
    ids = raw.get("ids")
    documents = raw.get("documents")
    metadatas = raw.get("metadatas")
    if not isinstance(ids, list) or not isinstance(documents, list) or not isinstance(metadatas, list):
        raise SpecMemoryError("invalid MemPalace collection response")
    if len(ids) != len(documents) or len(ids) != len(metadatas):
        raise SpecMemoryError("invalid MemPalace collection response")
    rows: dict[str, tuple[str, dict[str, Any]]] = {}
    malformed: dict[str, tuple[str, ...]] = {}
    for drawer_id, document, metadata in zip(ids, documents, metadatas):
        if not isinstance(drawer_id, str) or not drawer_id:
            raise SpecMemoryError("invalid MemPalace collection response")
        reasons: list[str] = []
        if not isinstance(document, str):
            reasons.append("invalid_document")
        if not isinstance(metadata, dict):
            reasons.append("invalid_metadata")
        if drawer_id in rows or drawer_id in malformed:
            reasons.append("duplicate_response_id")
        if reasons:
            malformed[drawer_id] = tuple(reasons)
            rows.pop(drawer_id, None)
        else:
            rows[drawer_id] = (document, metadata)
    return _CollectionRows(rows=rows, malformed=malformed)


def _has_expected_identity(
    metadata: dict[str, Any],
    *,
    planned: object,
    artifact_kind: str,
    scope: str,
    spec_id: str | None,
) -> bool:
    if metadata.get("artifact_kind") != artifact_kind:
        return False
    if metadata.get("scope") not in {scope, "canonical"}:
        return False
    if metadata.get("canonical") is not True:
        return False
    if metadata.get("artifact_path") != getattr(planned, "source"):
        return False
    if metadata.get("source_file") != getattr(planned, "source"):
        return False
    if metadata.get("requirement_id") != getattr(planned, "requirement_id"):
        return False
    if metadata.get("deterministic_identity_schema_version") != 1:
        return False
    if spec_id is not None and metadata.get("spec_id") != spec_id:
        return False
    return True


def _has_expected_hashes(
    document: str,
    metadata: dict[str, Any],
    *,
    planned: object,
) -> bool:
    return (
        metadata.get("artifact_hash") == getattr(planned, "artifact_hash")
        and metadata.get("canonical_spec_sha256")
        == getattr(planned, "canonical_spec_sha256")
        and metadata.get("requirement_content_sha256")
        == getattr(planned, "requirement_content_sha256")
        and hashlib.sha256(document.encode("utf-8")).hexdigest()
        == getattr(planned, "requirement_content_sha256")
    )


def _scan_extras(
    *,
    collection: object,
    adapter: object,
    expected_rows: list[object],
    artifact_kind: str,
    spec_id: str | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    raw = collection.get(  # type: ignore[attr-defined]
        where={"wing": {"$eq": getattr(adapter, "wing", "")}},
        include=["documents", "metadatas"],
        limit=MAX_MEMORY_AUDIT_SCAN_ROWS,
    )
    parsed = _as_collection_rows(raw)
    expected_ids = {row.drawer_id for row in expected_rows}
    expected_requirement_ids = {row.requirement_id for row in expected_rows}
    stale: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    duplicate: list[str] = []
    for drawer_id, (_document, metadata) in parsed.rows.items():
        if drawer_id in expected_ids:
            continue
        if metadata.get("artifact_kind") != artifact_kind:
            continue
        if spec_id is not None and metadata.get("spec_id") != spec_id:
            continue
        if _is_lifecycle_excluded(metadata):
            _append_unique(lifecycle_excluded, drawer_id)
        if metadata.get("canonical") is not True:
            _append_unique(non_canonical, drawer_id)
        requirement_id = metadata.get("requirement_id")
        if requirement_id in expected_requirement_ids:
            _append_unique(duplicate, drawer_id)
        else:
            _append_unique(stale, drawer_id)
    return stale, non_canonical, lifecycle_excluded, duplicate


def _is_lifecycle_excluded(metadata: dict[str, Any]) -> bool:
    return metadata.get("lifecycle_status", metadata.get("status", "active")) in {
        "deprecated",
        "superseded",
        "removed",
        "delivered",
    }


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _report(
    *,
    label: str,
    root: Path,
    adapter: object | None,
    status: str,
    artifact_count: int,
    expected_count: int,
    present_current_count: int = 0,
    missing: Iterable[str] = (),
    stale: Iterable[str] = (),
    wrong_wing: Iterable[str] = (),
    wrong_room: Iterable[str] = (),
    non_canonical: Iterable[str] = (),
    lifecycle_excluded: Iterable[str] = (),
    duplicate: Iterable[str] = (),
    errors: Iterable[str] = (),
    recommendations: Iterable[str] = (),
) -> ArtifactMemoryAuditReport:
    return ArtifactMemoryAuditReport(
        schema_version=1,
        label=label,
        root=str(root),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status=status,
        artifact_count=artifact_count,
        expected_count=expected_count,
        present_current_count=present_current_count,
        missing=sorted(set(missing)),
        stale=sorted(set(stale)),
        wrong_wing=sorted(set(wrong_wing)),
        wrong_room=sorted(set(wrong_room)),
        non_canonical=sorted(set(non_canonical)),
        lifecycle_excluded=sorted(set(lifecycle_excluded)),
        duplicate=sorted(set(duplicate)),
        errors=sorted(set(errors)),
        recommendations=sorted(set(recommendations)),
    )
