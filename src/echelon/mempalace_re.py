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
)


@dataclass(frozen=True)
class ReArtifactSnapshot:
    re_root: Path
    artifact_file: Path
    content: bytes
    source: str
    artifact_metadata: dict[str, Any]


@dataclass(frozen=True)
class ReMemoryMineReport:
    schema_version: int
    re_root: str
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
            "re_root": self.re_root,
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


ROOT_RE_ARTIFACTS = {
    "index.json",
    "re-analysis-manifest.json",
    "re-source-index.json",
    "re-workspace-inputs.json",
    "repos-manifest.json",
    "workspace-manifest.json",
}

SOURCE_RE_ARTIFACTS = {
    "configs.json",
    "dependencies.json",
    "domain-manifest.json",
    "manifest.json",
    "overview.md",
    "supporting-artifacts.md",
}

WORKSPACE_RE_JSON_ARTIFACTS = {
    "architecture-map.json",
    "manifest.json",
}

QUALITY_RE_ARTIFACTS = {
    "semantic-quality-review.json",
}


def resolve_re_root(project_root: Path) -> Path:
    root = project_root.resolve()
    direct = root / "re"
    if direct.is_dir() and _contains_curated_re_artifacts(direct):
        return direct
    raise SpecMemoryError(
        "published RE artifacts not found; run 'echelon re publish <run-id>' first"
    )


def _contains_curated_re_artifacts(re_root: Path) -> bool:
    for artifact in re_root.rglob("*"):
        if artifact.is_file() and _is_curated_re_artifact(artifact.relative_to(re_root)):
            return True
    return False


def _room_for_re_path(relative_to_re: Path) -> str:
    parts = relative_to_re.parts
    if not parts:
        return "re-workspace-context"
    if parts[0] == "quality":
        return "re-quality-review"
    if parts[0] == "sources":
        if "specs" in parts:
            return "re-generated-specs"
        return "re-source-context"
    if parts[0] == "workspace":
        if len(parts) > 1 and parts[1] == "strategy":
            return "re-strategy"
        if len(parts) > 1 and parts[1] == "domains":
            return "re-domain-context"
        return "re-workspace-context"
    return "re-workspace-context"


def _is_curated_re_artifact(relative_to_re: Path) -> bool:
    parts = relative_to_re.parts
    if (
        not parts
        or any(part in {".cache", "__pycache__"} for part in parts)
        or relative_to_re.suffix.lower() not in {".md", ".txt", ".json"}
    ):
        return False
    name = relative_to_re.name
    if len(parts) == 1:
        return name in ROOT_RE_ARTIFACTS
    if parts[0] == "workspace":
        return (
            relative_to_re.suffix.lower() == ".md"
            or name in WORKSPACE_RE_JSON_ARTIFACTS
        )
    if parts[0] == "sources":
        if "specs" in parts:
            return name in {"spec.md", "checklist.md"}
        return name in SOURCE_RE_ARTIFACTS
    if parts[0] == "quality":
        return name in QUALITY_RE_ARTIFACTS or (
            len(parts) == 3 and parts[1] == "sources" and relative_to_re.suffix == ".json"
        )
    return False


def load_re_artifact_snapshots(project_root: Path) -> list[ReArtifactSnapshot]:
    root = project_root.resolve()
    re_root = resolve_re_root(root)
    snapshots: list[ReArtifactSnapshot] = []
    for artifact in sorted(re_root.rglob("*")):
        if not artifact.is_file():
            continue
        relative_to_re = artifact.relative_to(re_root)
        if not _is_curated_re_artifact(relative_to_re):
            continue
        try:
            source = artifact.resolve().relative_to(root).as_posix()
        except ValueError:
            source = f"re/{relative_to_re.as_posix()}"
        digest = artifact_hash(artifact)
        room = _room_for_re_path(relative_to_re)
        snapshots.append(
            ReArtifactSnapshot(
                re_root=re_root,
                artifact_file=artifact,
                content=artifact.read_bytes(),
                source=source,
                artifact_metadata={
                    "scope": "reverse-engineering",
                    "canonical": True,
                    "artifact_kind": "reverse-engineering",
                    "artifact_path": source,
                    "artifact_hash": digest,
                    "source_file": source,
                    "lifecycle_status": "active",
                    "provenance_type": "reverse_engineering_mine",
                    "added_by": "echelon",
                    "phase": "RE",
                    "room": room,
                },
            )
        )
    return snapshots


class ReMemoryAdapter:
    def __init__(self, project_root: Path, run_id: str) -> None:
        from codegen.memory.context import MemPalaceContext
        from echelon.spec_memory_miner import SpecMemoryMiner

        wing = _read_mempalace_wing(project_root)
        self.context = MemPalaceContext.from_wing(wing, run_id=run_id)
        self.miner = SpecMemoryMiner(self.context, project_dir=project_root)
        self.wing = self.context.wing
        self.palace_path = self.context.palace_path

    def mine_re_artifact_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> object:
        return self.miner.mine_re_artifact_bytes(
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


def create_re_memory_adapter(project_root: Path, run_id: str) -> ReMemoryAdapter:
    return ReMemoryAdapter(project_root, run_id)


def _cleanup_existing_re_drawers(adapter: object) -> list[str]:
    try:
        opener = getattr(adapter, "open_collection_read_only", None)
        if not callable(opener):
            return ["re_memory_cleanup_unavailable"]
        collection = opener()
        rows = collection.get(  # type: ignore[attr-defined]
            where={"wing": {"$eq": getattr(adapter, "wing", "")}},
            include=["metadatas"],
        )
        ids = rows.get("ids") if isinstance(rows, dict) else None
        metadatas = rows.get("metadatas") if isinstance(rows, dict) else None
        if not isinstance(ids, list) or not isinstance(metadatas, list):
            return ["re_memory_cleanup_invalid_response"]
        delete_ids = [
            drawer_id
            for drawer_id, metadata in zip(ids, metadatas)
            if isinstance(drawer_id, str)
            and isinstance(metadata, dict)
            and metadata.get("artifact_kind") == "reverse-engineering"
            and metadata.get("wing") == getattr(adapter, "wing", "")
        ]
        if delete_ids:
            collection.delete(ids=delete_ids)  # type: ignore[attr-defined]
    except (Exception, SystemExit) as exc:
        return [f"re_memory_cleanup_skipped:{type(exc).__name__}"]
    return []


def mine_re_memory(project_root: Path, *, run_id: str) -> ReMemoryMineReport:
    snapshots = load_re_artifact_snapshots(project_root)
    re_root = snapshots[0].re_root if snapshots else resolve_re_root(project_root)
    try:
        adapter = create_re_memory_adapter(project_root, run_id)
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        return ReMemoryMineReport(
            schema_version=1,
            re_root=str(re_root),
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
    cleanup_errors = _cleanup_existing_re_drawers(adapter)
    try:
        results = [
            adapter.mine_re_artifact_bytes(
                snapshot.content,
                source=snapshot.source,
                artifact_metadata=snapshot.artifact_metadata,
            )
            for snapshot in snapshots
        ]
    except ValueError as exc:
        return ReMemoryMineReport(
            schema_version=1,
            re_root=str(re_root),
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
        return ReMemoryMineReport(
            schema_version=1,
            re_root=str(re_root),
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
    return ReMemoryMineReport(
        schema_version=1,
        re_root=str(re_root),
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
