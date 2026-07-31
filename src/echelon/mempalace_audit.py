from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from echelon.context_reconciliation import reconcile_drawers
from echelon.mempalace_requirements import (
    SpecMemoryError,
    PlannedRequirementDrawer,
    create_requirement_memory_adapter,
    load_canonical_spec_snapshot,
    load_supporting_artifact_snapshots,
    resolve_spec_dir,
)

MAX_AUDIT_SCAN_ROWS = 1_000


@dataclass(frozen=True)
class _CollectionDrawer:
    drawer_id: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _ParsedCollectionRows:
    rows: dict[str, tuple[str, dict[str, Any]]]
    malformed: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class SpecMemoryAuditReport:
    schema_version: int
    spec_id: str
    spec_dir: str
    wing: str | None
    palace_path: str | None
    status: str
    expected_count: int
    present_current_count: int
    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    wrong_wing: list[str] = field(default_factory=list)
    wrong_room: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    non_canonical: list[str] = field(default_factory=list)
    lifecycle_excluded: list[str] = field(default_factory=list)
    retrieval_probe: dict[str, Any] | None = None
    recommendations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "status": self.status,
            "expected_count": self.expected_count,
            "present_current_count": self.present_current_count,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "wrong_wing": list(self.wrong_wing),
            "wrong_room": list(self.wrong_room),
            "duplicate": list(self.duplicate),
            "non_canonical": list(self.non_canonical),
            "lifecycle_excluded": list(self.lifecycle_excluded),
            "retrieval_probe": self.retrieval_probe,
            "recommendations": list(self.recommendations),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class SpecMemoryCleanupReport:
    schema_version: int
    spec_id: str
    spec_dir: str
    wing: str | None
    palace_path: str | None
    deleted_count: int
    deleted_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "deleted_count": self.deleted_count,
            "deleted_ids": list(self.deleted_ids),
        }


def _collection_from_adapter(adapter: object) -> object:
    opener = getattr(adapter, "open_collection_read_only", None)
    if callable(opener):
        return opener()
    raise SpecMemoryError("MemPalace collection is unavailable")


def _as_collection_rows(raw: object) -> _ParsedCollectionRows:
    if type(raw) is not dict:
        raise SpecMemoryError("invalid MemPalace collection response")
    ids = raw.get("ids")
    documents = raw.get("documents")
    metadatas = raw.get("metadatas")
    if type(ids) is not list or type(documents) is not list or type(metadatas) is not list:
        raise SpecMemoryError("invalid MemPalace collection response")
    if len(ids) != len(documents) or len(ids) != len(metadatas):
        raise SpecMemoryError("invalid MemPalace collection response")
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    malformed: dict[str, tuple[str, ...]] = {}
    for drawer_id, document, metadata in zip(ids, documents, metadatas):
        if type(drawer_id) is not str or not drawer_id:
            raise SpecMemoryError("invalid MemPalace collection response")
        reasons: list[str] = []
        if type(document) is not str:
            reasons.append("invalid_document")
        if type(metadata) is not dict:
            reasons.append("invalid_metadata")
        if drawer_id in result or drawer_id in malformed:
            reasons.append("duplicate_response_id")
        if reasons:
            malformed[drawer_id] = tuple(reasons)
            result.pop(drawer_id, None)
        else:
            result[drawer_id] = (document, metadata)
    return _ParsedCollectionRows(rows=result, malformed=malformed)


def _unavailable_report(
    *,
    snapshot: object,
    adapter: object | None,
    expected: list[object],
    error: Exception | SystemExit,
) -> SpecMemoryAuditReport:
    return SpecMemoryAuditReport(
        schema_version=1,
        spec_id=getattr(snapshot, "spec_id"),
        spec_dir=str(getattr(snapshot, "spec_dir")),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status="unavailable",
        expected_count=len(expected),
        present_current_count=0,
        errors=[type(error).__name__],
    )


def _failure_report(
    *,
    snapshot: object,
    adapter: object | None,
    error: Exception | SystemExit,
    expected_count: int = 0,
    recommendations: list[str] | None = None,
) -> SpecMemoryAuditReport:
    return SpecMemoryAuditReport(
        schema_version=1,
        spec_id=getattr(snapshot, "spec_id"),
        spec_dir=str(getattr(snapshot, "spec_dir")),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status="fail",
        expected_count=expected_count,
        present_current_count=0,
        recommendations=list(recommendations or []),
        errors=[type(error).__name__],
    )


def _status_for_failures(report: SpecMemoryAuditReport) -> str:
    fail_lists = (
        report.missing,
        report.stale,
        report.wrong_wing,
        report.wrong_room,
        report.non_canonical,
        report.lifecycle_excluded,
    )
    if any(fail_lists):
        return "fail"
    if (
        report.duplicate
        or report.recommendations
        or (report.retrieval_probe or {}).get("status") == "warn"
    ):
        return "warn"
    return "pass"


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _points_to_spec(metadata: dict[str, Any], snapshot: object) -> bool:
    raw_path = metadata.get("artifact_path") or metadata.get("source_file")
    if not isinstance(raw_path, str):
        return False
    normalized = raw_path.replace("\\", "/").lstrip("./")
    marker = f"specs/{getattr(snapshot, 'spec_id')}/"
    return marker in normalized


def _scan_spec_extras(
    collection: object,
    *,
    adapter: object,
    snapshot: object,
    expected_rows: list[PlannedRequirementDrawer],
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    try:
        raw = collection.get(  # type: ignore[attr-defined]
            where={"wing": getattr(adapter, "wing")},
            include=["documents", "metadatas"],
            limit=MAX_AUDIT_SCAN_ROWS,
        )
    except TypeError:
        return [], [], [], [], [], ["bounded_extra_scan_unsupported"]
    parsed = _as_collection_rows(raw)
    expected_ids = {row.drawer_id for row in expected_rows}
    expected_requirement_ids = {
        row.requirement_id for row in expected_rows
    }
    stale: list[str] = []
    duplicate: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    errors: list[str] = []
    for drawer_id, reasons in parsed.malformed.items():
        if drawer_id in expected_ids:
            continue
        errors.extend(f"{drawer_id}:{reason}" for reason in reasons)
    for drawer_id, (_document, metadata) in parsed.rows.items():
        if drawer_id in expected_ids or not _points_to_spec(metadata, snapshot):
            continue
        if (
            metadata.get("scope") == "spec-evidence"
            and metadata.get("artifact_kind") == "spec-evidence"
        ):
            continue
        artifact_path = metadata.get("artifact_path") or metadata.get(
            "source_file"
        )
        current_hash = getattr(snapshot, "artifact_metadata")["artifact_hash"]
        status = metadata.get(
            "lifecycle_status",
            metadata.get("status", "active"),
        )
        if status in {"deprecated", "superseded", "removed", "delivered"}:
            _append_unique(lifecycle_excluded, drawer_id)
        if (
            metadata.get("canonical") is not True
            or artifact_path != getattr(snapshot, "source")
        ):
            _append_unique(non_canonical, drawer_id)
        if metadata.get("artifact_hash") != current_hash:
            _append_unique(stale, drawer_id)
        requirement_id = metadata.get("requirement_id")
        if (
            requirement_id in expected_requirement_ids
            and drawer_id not in stale
            and drawer_id not in non_canonical
            and drawer_id not in lifecycle_excluded
        ):
            _append_unique(duplicate, drawer_id)
        elif requirement_id not in expected_requirement_ids:
            _append_unique(stale, drawer_id)
    return (
        stale,
        duplicate,
        non_canonical,
        lifecycle_excluded,
        errors,
        [],
    )


def _plan_expected_spec_memory_rows(
    *,
    project_root: Path,
    spec_dir: Path,
    snapshot: object,
    adapter: object,
) -> list[PlannedRequirementDrawer]:
    expected_rows = adapter.plan_canonical_rows(
        getattr(snapshot, "content"),
        source=getattr(snapshot, "source"),
        artifact_metadata=getattr(snapshot, "artifact_metadata"),
    )
    for support_snapshot in load_supporting_artifact_snapshots(
        project_root,
        spec_dir,
    ):
        expected_rows.extend(
            adapter.plan_canonical_support_rows(
                support_snapshot.content,
                source=support_snapshot.source,
                artifact_metadata=support_snapshot.artifact_metadata,
            )
        )
    return expected_rows


def cleanup_stale_spec_memory(
    project_root: Path,
    spec_selector: str | Path,
) -> SpecMemoryCleanupReport:
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    snapshot = load_canonical_spec_snapshot(project_root, spec_dir)
    adapter = create_requirement_memory_adapter(project_root, run_id="cleanup")
    expected_rows = _plan_expected_spec_memory_rows(
        project_root=project_root,
        spec_dir=spec_dir,
        snapshot=snapshot,
        adapter=adapter,
    )
    source_paths = {row.source for row in expected_rows}
    expected_ids = {row.drawer_id for row in expected_rows}
    collection = _collection_from_adapter(adapter)
    raw = collection.get(  # type: ignore[attr-defined]
        where={"wing": getattr(adapter, "wing")},
        include=["documents", "metadatas"],
        limit=MAX_AUDIT_SCAN_ROWS,
    )
    parsed = _as_collection_rows(raw)
    deleted_ids = sorted(
        drawer_id
        for drawer_id, (_document, metadata) in parsed.rows.items()
        if drawer_id not in expected_ids
        and metadata.get("canonical") is True
        and (metadata.get("artifact_path") or metadata.get("source_file"))
        in source_paths
    )
    if deleted_ids:
        collection.delete(ids=deleted_ids)  # type: ignore[attr-defined]
    return SpecMemoryCleanupReport(
        schema_version=1,
        spec_id=snapshot.spec_id,
        spec_dir=str(snapshot.spec_dir),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
    )


def audit_spec_memory(
    project_root: Path,
    spec_selector: str | Path,
    *,
    probe_retrieval: bool = False,
) -> SpecMemoryAuditReport:
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    snapshot = load_canonical_spec_snapshot(project_root, spec_dir)
    try:
        adapter = create_requirement_memory_adapter(project_root, run_id="audit")
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        return _unavailable_report(snapshot=snapshot, adapter=None, expected=[], error=exc)
    try:
        expected_rows = _plan_expected_spec_memory_rows(
            project_root=project_root,
            spec_dir=spec_dir,
            snapshot=snapshot,
            adapter=adapter,
        )
    except (Exception, SystemExit) as exc:
        return _failure_report(snapshot=snapshot, adapter=adapter, error=exc)
    expected = [row.drawer_id for row in expected_rows]
    try:
        collection = _collection_from_adapter(adapter)
        raw = (
            collection.get(
                ids=expected,
                include=["documents", "metadatas"],
            )
            if expected
            else {"ids": [], "documents": [], "metadatas": []}
        )
        parsed = _as_collection_rows(raw)
    except (Exception, SystemExit) as exc:
        return _unavailable_report(snapshot=snapshot, adapter=adapter, expected=expected, error=exc)
    rows = parsed.rows
    missing = [
        drawer_id
        for drawer_id in expected
        if drawer_id not in rows and drawer_id not in parsed.malformed
    ]
    stale: list[str] = []
    wrong_wing: list[str] = []
    wrong_room: list[str] = []
    duplicate: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    errors: list[str] = []
    recommendations: list[str] = []
    for drawer_id, reasons in parsed.malformed.items():
        errors.extend(f"{drawer_id}:{reason}" for reason in reasons)
        if "invalid_document" in reasons:
            _append_unique(stale, drawer_id)
        if "invalid_metadata" in reasons or "duplicate_response_id" in reasons:
            _append_unique(non_canonical, drawer_id)
    present = 0
    drawers = [
        _CollectionDrawer(drawer_id=drawer_id, content=document, metadata=metadata)
        for drawer_id, (document, metadata) in rows.items()
    ]
    try:
        reconciliation = reconcile_drawers(drawers, project_root)
    except (Exception, SystemExit) as exc:
        return _failure_report(
            snapshot=snapshot,
            adapter=adapter,
            error=exc,
            expected_count=len(expected),
            recommendations=["reconciliation_failed"],
        )
    accepted_ids = {drawer.drawer_id for drawer in reconciliation.accepted}
    rejected_reasons = {
        rejection["drawer_id"]: rejection["reason"]
        for rejection in reconciliation.rejected
    }
    expected_by_id = {row.drawer_id: row for row in expected_rows}
    for drawer_id in expected:
        planned = expected_by_id[drawer_id]
        row = rows.get(drawer_id)
        if row is None:
            continue
        document, metadata = row
        rejection_reason = rejected_reasons.get(drawer_id)
        if rejection_reason == "lifecycle_excluded":
            lifecycle_excluded.append(drawer_id)
        elif rejection_reason == "hash_mismatch":
            stale.append(drawer_id)
        elif rejection_reason is not None or drawer_id not in accepted_ids:
            _append_unique(non_canonical, drawer_id)
        if metadata.get("wing") != getattr(adapter, "wing", None):
            _append_unique(wrong_wing, drawer_id)
        if metadata.get("room") != planned.room:
            _append_unique(wrong_room, drawer_id)
        expected_scope = (
            "canonical-support"
            if planned.requirement_id.startswith("CTX-")
            else "canonical"
        )
        if metadata.get("scope") != expected_scope or metadata.get("canonical") is not True:
            _append_unique(non_canonical, drawer_id)
        if (
            planned.requirement_id.startswith("CTX-")
            and metadata.get("artifact_kind") != "supporting-context"
        ):
            _append_unique(non_canonical, drawer_id)
        if (
            metadata.get("artifact_hash") != planned.artifact_hash
            and drawer_id not in stale
        ):
            _append_unique(stale, drawer_id)
        if metadata.get("lifecycle_status", metadata.get("status", "active")) in {"deprecated", "superseded", "removed", "delivered"}:
            if drawer_id not in lifecycle_excluded:
                _append_unique(lifecycle_excluded, drawer_id)
        if metadata.get("artifact_path") != planned.source and drawer_id not in non_canonical:
            _append_unique(non_canonical, drawer_id)
        if (
            metadata.get("deterministic_identity_schema_version") != 1
            or metadata.get("requirement_id") != planned.requirement_id
        ):
            _append_unique(non_canonical, drawer_id)
        if (
            metadata.get("canonical_spec_sha256")
            != planned.canonical_spec_sha256
            or metadata.get("requirement_content_sha256")
            != planned.requirement_content_sha256
            or hashlib.sha256(document.encode("utf-8")).hexdigest()
            != planned.requirement_content_sha256
        ):
            _append_unique(stale, drawer_id)
        if drawer_id in stale or drawer_id in wrong_wing or drawer_id in wrong_room or drawer_id in non_canonical or drawer_id in lifecycle_excluded:
            continue
        present += 1
    try:
        (
            extra_stale,
            duplicate,
            extra_non_canonical,
            extra_lifecycle,
            scan_errors,
            scan_recommendations,
        ) = _scan_spec_extras(
            collection,
            adapter=adapter,
            snapshot=snapshot,
            expected_rows=expected_rows,
        )
    except (Exception, SystemExit) as exc:
        return _unavailable_report(
            snapshot=snapshot,
            adapter=adapter,
            expected=expected,
            error=exc,
        )
    for value in extra_stale:
        _append_unique(stale, value)
    for value in extra_non_canonical:
        _append_unique(non_canonical, value)
    for value in extra_lifecycle:
        _append_unique(lifecycle_excluded, value)
    errors.extend(scan_errors)
    recommendations.extend(scan_recommendations)
    report = SpecMemoryAuditReport(
        schema_version=1,
        spec_id=snapshot.spec_id,
        spec_dir=str(snapshot.spec_dir),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status="pass",
        expected_count=len(expected),
        present_current_count=present,
        missing=missing,
        stale=sorted(stale),
        wrong_wing=sorted(wrong_wing),
        wrong_room=sorted(wrong_room),
        duplicate=sorted(duplicate),
        non_canonical=sorted(non_canonical),
        lifecycle_excluded=sorted(lifecycle_excluded),
        retrieval_probe={"status": "skipped"} if not probe_retrieval else {"status": "warn", "checked": 0},
        recommendations=sorted(set(recommendations)),
        errors=sorted(set(errors)),
    )
    return SpecMemoryAuditReport(**{**report.to_dict(), "status": _status_for_failures(report)})


def render_audit_markdown(report: SpecMemoryAuditReport) -> str:
    lines = [
        f"# MemPalace Audit: {report.spec_id}",
        "",
        f"- Status: {report.status}",
        f"- Expected drawers: {report.expected_count}",
        f"- Present current drawers: {report.present_current_count}",
        f"- Missing: {len(report.missing)}",
        f"- Stale: {len(report.stale)}",
        f"- Wrong wing: {len(report.wrong_wing)}",
    ]
    return "\n".join(lines) + "\n"


def write_audit_reports(report: SpecMemoryAuditReport, spec_dir: Path) -> tuple[Path, Path]:
    json_path = spec_dir / "mempalace-audit.json"
    md_path = spec_dir / "mempalace-audit.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_audit_markdown(report), encoding="utf-8")
    return json_path, md_path
