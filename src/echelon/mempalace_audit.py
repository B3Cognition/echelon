from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any

from echelon.mempalace_requirements import (
    SpecMemoryError,
    create_requirement_memory_adapter,
    load_canonical_spec_snapshot,
    resolve_spec_dir,
)


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


def _collection_from_adapter(adapter: object) -> object:
    collection = getattr(adapter, "collection", None)
    if collection is not None:
        return collection
    miner = getattr(adapter, "miner", None)
    writer = getattr(miner, "_get_writer", lambda: None)()
    getter = getattr(writer, "_get_collection", None)
    if callable(getter):
        return getter()
    raise SpecMemoryError("MemPalace collection is unavailable")


def _as_collection_rows(raw: object) -> dict[str, tuple[str, dict[str, Any]]]:
    if type(raw) is not dict:
        return {}
    ids = raw.get("ids")
    documents = raw.get("documents")
    metadatas = raw.get("metadatas")
    if type(ids) is not list or type(documents) is not list or type(metadatas) is not list:
        return {}
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for drawer_id, document, metadata in zip(ids, documents, metadatas):
        if type(drawer_id) is str and type(document) is str and type(metadata) is dict:
            result[drawer_id] = (document, metadata)
    return result


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
    if report.duplicate or (report.retrieval_probe or {}).get("status") == "warn":
        return "warn"
    return "pass"


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
        expected = adapter.plan_canonical_bytes(
            snapshot.content,
            source=snapshot.source,
            artifact_metadata=snapshot.artifact_metadata,
        )
        collection = _collection_from_adapter(adapter)
        raw = collection.get(ids=expected, include=["documents", "metadatas"])
    except Exception as exc:
        return SpecMemoryAuditReport(
            schema_version=1,
            spec_id=snapshot.spec_id,
            spec_dir=str(snapshot.spec_dir),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
            errors=[type(exc).__name__],
        )
    rows = _as_collection_rows(raw)
    missing = [drawer_id for drawer_id in expected if drawer_id not in rows]
    stale: list[str] = []
    wrong_wing: list[str] = []
    wrong_room: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []
    present = 0
    for drawer_id in expected:
        row = rows.get(drawer_id)
        if row is None:
            continue
        _document, metadata = row
        if metadata.get("wing") != getattr(adapter, "wing", None):
            wrong_wing.append(drawer_id)
        if metadata.get("room") not in {"functional-requirements", "non-functional-requirements", "acceptance-criteria", "user-stories"}:
            wrong_room.append(drawer_id)
        if metadata.get("canonical") is not True:
            non_canonical.append(drawer_id)
        if metadata.get("artifact_hash") != snapshot.artifact_metadata["artifact_hash"]:
            stale.append(drawer_id)
        if metadata.get("lifecycle_status", metadata.get("status", "active")) in {"deprecated", "superseded", "removed", "delivered"}:
            lifecycle_excluded.append(drawer_id)
        if drawer_id not in stale and drawer_id not in wrong_wing and drawer_id not in wrong_room and drawer_id not in non_canonical and drawer_id not in lifecycle_excluded:
            present += 1
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
        stale=stale,
        wrong_wing=wrong_wing,
        wrong_room=wrong_room,
        non_canonical=non_canonical,
        lifecycle_excluded=lifecycle_excluded,
        retrieval_probe={"status": "skipped"} if not probe_retrieval else {"status": "warn", "checked": 0},
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
