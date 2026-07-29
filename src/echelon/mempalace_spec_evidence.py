from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from echelon.context_metadata import artifact_hash
from echelon.mempalace_requirements import (
    SpecMemoryError,
    _read_int,
    _read_mempalace_wing,
    _read_str_list,
    resolve_spec_dir,
)
from echelon.mempalace_memory_audit import audit_artifact_memory


@dataclass(frozen=True)
class SpecEvidenceArtifactSnapshot:
    spec_id: str
    spec_dir: Path
    artifact_file: Path
    content: bytes
    source: str
    artifact_metadata: dict[str, Any]


@dataclass(frozen=True)
class SpecEvidenceMemoryMineReport:
    schema_version: int
    spec_id: str
    spec_dir: str
    wing: str | None
    palace_path: str | None
    status: str
    artifact_count: int
    expected_count: int
    written_count: int
    adopted_count: int
    skipped_count: int
    failed_count: int
    drifted_count: int
    unavailable_count: int = 0
    drawer_ids: list[str] = field(default_factory=list)
    expected_drawer_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "status": self.status,
            "artifact_count": self.artifact_count,
            "expected_count": self.expected_count,
            "written_count": self.written_count,
            "adopted_count": self.adopted_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "drifted_count": self.drifted_count,
            "unavailable_count": self.unavailable_count,
            "drawer_ids": list(self.drawer_ids),
            "expected_drawer_ids": list(self.expected_drawer_ids),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class SpecEvidenceMemoryAuditReport:
    schema_version: int
    spec_id: str
    spec_dir: str
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
            "spec_id": self.spec_id,
            "spec_dir": self.spec_dir,
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


CANONICAL_SPEC_EVIDENCE_ARTIFACTS = {
    "docs-verification-report.md",
    "documentation-impact-report.md",
    "evidence-grades.md",
    "evidence-inventory.json",
    "evidence-resolution.md",
    "fulfillment-report.md",
    "implementability-report.md",
    "plan-conformance.json",
    "plan-conformance.md",
    "verified-fulfillment-ledger.json",
}

def _room_for_evidence_artifact(name: str) -> str:
    if name in {
        "fulfillment-report.md",
        "verified-fulfillment-ledger.json",
        "fulfillment-report.fallback.md",
    }:
        return "spec-fulfillment-evidence"
    if name in {"implementation-map.md", "codegraph-evidence-map.md"}:
        return "spec-implementation-evidence"
    if name.startswith("docs-") or name.startswith("documentation-"):
        return "spec-documentation-evidence"
    if name in {
        "judgment-prepass.json",
        "judgment-prepass.md",
        "progress-integrity.json",
        "progress-integrity.md",
        "requirement-audit.md",
    }:
        return "spec-verification-evidence"
    return "spec-evidence-context"


def _snapshot_for_artifact(
    project_root: Path,
    spec_dir: Path,
    artifact: Path,
) -> SpecEvidenceArtifactSnapshot:
    spec_id = spec_dir.name
    source = artifact.resolve().relative_to(project_root.resolve()).as_posix()
    digest = artifact_hash(artifact)
    return SpecEvidenceArtifactSnapshot(
        spec_id=spec_id,
        spec_dir=spec_dir,
        artifact_file=artifact,
        content=artifact.read_bytes(),
        source=source,
        artifact_metadata={
            "scope": "spec-evidence",
            "canonical": True,
            "artifact_kind": "spec-evidence",
            "artifact_path": source,
            "artifact_hash": digest,
            "source_file": source,
            "lifecycle_status": "active",
            "provenance_type": "spec_evidence_mine",
            "added_by": "echelon",
            "phase": "VERIFY",
            "room": _room_for_evidence_artifact(artifact.name),
            "spec_id": spec_id,
        },
    )


def load_spec_evidence_artifact_snapshots(
    project_root: Path,
    spec_selector: str | Path,
) -> list[SpecEvidenceArtifactSnapshot]:
    root = project_root.resolve()
    spec_dir = resolve_spec_dir(root, spec_selector)
    artifacts: list[Path] = []
    for name in sorted(CANONICAL_SPEC_EVIDENCE_ARTIFACTS):
        artifact = spec_dir / name
        if artifact.is_file():
            artifacts.append(artifact)
    return [_snapshot_for_artifact(root, spec_dir, artifact) for artifact in sorted(artifacts)]


class SpecEvidenceMemoryAdapter:
    def __init__(self, project_root: Path, run_id: str) -> None:
        from codegen.memory.context import MemPalaceContext
        from echelon.spec_memory_miner import SpecMemoryMiner

        wing = _read_mempalace_wing(project_root)
        self.context = MemPalaceContext.from_wing(wing, run_id=run_id)
        self.miner = SpecMemoryMiner(self.context, project_dir=project_root)
        self.wing = self.context.wing
        self.palace_path = self.context.palace_path

    def mine_spec_evidence_artifact_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> object:
        return self.miner.mine_spec_evidence_artifact_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )

    def plan_spec_evidence_artifact_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[object]:
        return self.miner.plan_spec_evidence_artifact_rows(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )

    def open_collection_read_only(self) -> object:
        opener = getattr(self.miner, "open_collection_read_only", None)
        if not callable(opener):
            raise SpecMemoryError(
                "installed MemPalace does not support read-only collection access"
            )
        return opener()


def create_spec_evidence_memory_adapter(
    project_root: Path,
    run_id: str,
) -> SpecEvidenceMemoryAdapter:
    return SpecEvidenceMemoryAdapter(project_root, run_id)


def audit_spec_evidence_memory(
    project_root: Path,
    spec_selector: str | Path,
) -> SpecEvidenceMemoryAuditReport:
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    snapshots = load_spec_evidence_artifact_snapshots(project_root, spec_selector)
    try:
        adapter = create_spec_evidence_memory_adapter(project_root, run_id="audit")
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        return SpecEvidenceMemoryAuditReport(
            schema_version=1,
            label="Spec Evidence",
            root=str(spec_dir),
            wing=None,
            palace_path=None,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=0,
            present_current_count=0,
            errors=[type(exc).__name__],
        )
    generic = audit_artifact_memory(
        label="Spec Evidence",
        root=spec_dir,
        snapshots=snapshots,
        adapter=adapter,
        artifact_kind="spec-evidence",
        scope="spec-evidence",
        spec_id=spec_dir.name,
        planner_name="plan_spec_evidence_artifact_rows",
    )
    return SpecEvidenceMemoryAuditReport(
        schema_version=generic.schema_version,
        spec_id=spec_dir.name,
        spec_dir=generic.root,
        wing=generic.wing,
        palace_path=generic.palace_path,
        status=generic.status,
        artifact_count=generic.artifact_count,
        expected_count=generic.expected_count,
        present_current_count=generic.present_current_count,
        missing=generic.missing,
        stale=generic.stale,
        wrong_wing=generic.wrong_wing,
        wrong_room=generic.wrong_room,
        non_canonical=generic.non_canonical,
        lifecycle_excluded=generic.lifecycle_excluded,
        duplicate=generic.duplicate,
        errors=generic.errors,
        recommendations=generic.recommendations,
    )


def _cleanup_existing_spec_evidence_drawers(adapter: object, spec_id: str) -> list[str]:
    try:
        opener = getattr(adapter, "open_collection_read_only", None)
        if not callable(opener):
            return ["spec_evidence_cleanup_unavailable"]
        collection = opener()
        rows = collection.get(  # type: ignore[attr-defined]
            where={"wing": {"$eq": getattr(adapter, "wing", "")}},
            include=["metadatas"],
        )
        ids = rows.get("ids") if isinstance(rows, dict) else None
        metadatas = rows.get("metadatas") if isinstance(rows, dict) else None
        if not isinstance(ids, list) or not isinstance(metadatas, list):
            return ["spec_evidence_cleanup_invalid_response"]
        delete_ids = [
            drawer_id
            for drawer_id, metadata in zip(ids, metadatas)
            if isinstance(drawer_id, str)
            and isinstance(metadata, dict)
            and metadata.get("artifact_kind") == "spec-evidence"
            and metadata.get("spec_id") == spec_id
            and metadata.get("wing") == getattr(adapter, "wing", "")
        ]
        if delete_ids:
            collection.delete(ids=delete_ids)  # type: ignore[attr-defined]
    except (Exception, SystemExit) as exc:
        return [f"spec_evidence_cleanup_skipped:{type(exc).__name__}"]
    return []


def mine_spec_evidence_memory(
    project_root: Path,
    spec_selector: str | Path,
    *,
    run_id: str,
) -> SpecEvidenceMemoryMineReport:
    snapshots = load_spec_evidence_artifact_snapshots(project_root, spec_selector)
    spec_dir = resolve_spec_dir(project_root, spec_selector)
    try:
        adapter = create_spec_evidence_memory_adapter(project_root, run_id)
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        return SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id=spec_dir.name,
            spec_dir=str(spec_dir),
            wing=None,
            palace_path=None,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    cleanup_errors = _cleanup_existing_spec_evidence_drawers(adapter, spec_dir.name)
    try:
        results = [
            adapter.mine_spec_evidence_artifact_bytes(
                snapshot.content,
                source=snapshot.source,
                artifact_metadata=snapshot.artifact_metadata,
            )
            for snapshot in snapshots
        ]
    except ValueError as exc:
        return SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id=spec_dir.name,
            spec_dir=str(spec_dir),
            wing=str(getattr(adapter, "wing", "")) or None,
            palace_path=str(getattr(adapter, "palace_path", "")) or None,
            status="partial",
            artifact_count=len(snapshots),
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=1,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    except (ImportError, OSError, RuntimeError, SpecMemoryError, SystemExit) as exc:
        return SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id=spec_dir.name,
            spec_dir=str(spec_dir),
            wing=str(getattr(adapter, "wing", "")) or None,
            palace_path=str(getattr(adapter, "palace_path", "")) or None,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=0,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
            errors=[type(exc).__name__],
        )
    expected = sorted(
        {
            drawer_id
            for item in results
            for drawer_id in _read_str_list(item, "expected_drawer_ids")
        }
    )
    drawer_ids = sorted(
        {
            drawer_id
            for item in results
            for drawer_id in _read_str_list(item, "drawer_ids")
        }
    )
    written = sum(_read_int(item, "written") for item in results)
    adopted = sum(_read_int(item, "already_present") for item in results)
    skipped = sum(_read_int(item, "skipped") for item in results)
    failed = sum(_read_int(item, "failed") for item in results)
    drifted = sum(_read_int(item, "drifted") for item in results)
    unavailable = sum(_read_int(item, "unavailable") for item in results)
    status = "complete"
    if unavailable:
        status = "unavailable"
    elif failed or drifted:
        status = "partial"
    return SpecEvidenceMemoryMineReport(
        schema_version=1,
        spec_id=spec_dir.name,
        spec_dir=str(spec_dir),
        wing=str(getattr(adapter, "wing", "")) or None,
        palace_path=str(getattr(adapter, "palace_path", "")) or None,
        status=status,
        artifact_count=len(snapshots),
        expected_count=len(expected),
        written_count=written,
        adopted_count=adopted,
        skipped_count=skipped,
        failed_count=failed,
        drifted_count=drifted,
        unavailable_count=unavailable,
        drawer_ids=drawer_ids,
        expected_drawer_ids=expected,
        errors=[
            *cleanup_errors,
            *[
                str(error)
                for item in results
                for error in getattr(item, "errors", [])
                if isinstance(error, str)
            ],
        ],
    )
