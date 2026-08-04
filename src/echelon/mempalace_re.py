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
from echelon.mempalace_memory_audit import audit_artifact_memory
from harness.re_artifacts import SUPPORTED_RE_ARTIFACT_KINDS, ReArtifactDescriptor
from harness.re_registry import (
    canonical_re_artifact_descriptors,
    load_published_index,
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


@dataclass(frozen=True)
class ReMemoryAuditReport:
    schema_version: int
    re_root: str
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
            "re_root": self.re_root,
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


ROOT_RE_ARTIFACTS = {
    "index.json",
    "re-analysis-manifest.json",
    "re-source-index.json",
    "re-workspace-inputs.json",
    "repos-manifest.json",
    "workspace-manifest.json",
}

SOURCE_RE_ARTIFACTS = {
    "architecture.md",
    "codegraph-summary.json",
    "components.md",
    "configs.json",
    "contracts.md",
    "dependencies.json",
    "domain-manifest.json",
    "manifest.json",
    "overview.md",
    "supporting-artifacts.md",
}

WORKSPACE_RE_JSON_ARTIFACTS = {
    "architecture-map.json",
    "codegraph-summary.json",
    "manifest.json",
}

MINED_RE_ARTIFACT_KINDS = frozenset(
    {
        "re-source-manifest",
        "re-workspace-manifest",
        "re-overview",
        "re-architecture",
        "re-contracts",
        "re-components",
        "re-decision",
        "re-codegraph-summary",
        "re-domain-manifest",
        "re-generated-spec",
        "re-generated-checklist",
        "re-supporting-artifacts",
        "re-architecture-map",
        "re-relationships",
        "re-domain",
        "re-strategy",
        "re-workspace-checklist",
        "re-quality-report",
    }
)

RE_ARTIFACT_ROOMS = {
    **{(kind, "source"): "re-source-context" for kind in MINED_RE_ARTIFACT_KINDS},
    **{
        (kind, "workspace"): "re-workspace-context"
        for kind in MINED_RE_ARTIFACT_KINDS
    },
    ("re-architecture", "source"): "re-source-architecture",
    ("re-contracts", "source"): "re-source-contracts",
    ("re-components", "source"): "re-source-components",
    ("re-decision", "source"): "re-source-decisions",
    ("re-decision", "workspace"): "re-workspace-decisions",
    ("re-codegraph-summary", "source"): "re-source-codegraph",
    ("re-codegraph-summary", "workspace"): "re-workspace-codegraph",
    ("re-generated-spec", "source"): "re-generated-specs",
    ("re-generated-checklist", "source"): "re-generated-specs",
    ("re-domain", "workspace"): "re-domain-context",
    ("re-strategy", "workspace"): "re-strategy",
    ("re-quality-report", "source"): "re-quality-review",
    ("re-quality-report", "workspace"): "re-quality-review",
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


def _re_artifact_classification(relative_to_re: Path) -> tuple[str, str]:
    """Return deterministic artifact kind and MemPalace room for a curated path."""
    parts = relative_to_re.parts
    name = relative_to_re.name
    if parts and parts[0] == "sources":
        if len(parts) >= 4 and parts[2] == "adrs" and relative_to_re.suffix == ".md":
            return "re-decision", "re-source-decisions"
        source_kinds = {
            "architecture.md": ("re-architecture", "re-source-architecture"),
            "contracts.md": ("re-contracts", "re-source-contracts"),
            "components.md": ("re-components", "re-source-components"),
            "codegraph-summary.json": (
                "re-codegraph-summary",
                "re-source-codegraph",
            ),
        }
        if name in source_kinds:
            return source_kinds[name]
    if parts and parts[0] == "workspace" and name == "codegraph-summary.json":
        return "re-codegraph-summary", "re-workspace-codegraph"
    if (
        len(parts) >= 4
        and parts[:3] == ("workspace", "strategy", "adrs")
        and relative_to_re.suffix.lower() == ".md"
    ):
        return "re-decision", "re-workspace-decisions"
    return "reverse-engineering", _room_for_re_path(relative_to_re)


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
        if len(parts) >= 4 and parts[2] == "adrs":
            return relative_to_re.suffix.lower() == ".md"
        return name in SOURCE_RE_ARTIFACTS
    if parts[0] == "quality":
        return name in QUALITY_RE_ARTIFACTS or (
            len(parts) == 3 and parts[1] == "sources" and relative_to_re.suffix == ".json"
        )
    return False


def load_re_artifact_snapshots(project_root: Path) -> list[ReArtifactSnapshot]:
    root = project_root.resolve()
    index = load_published_index(root)
    if index is not None:
        return _load_descriptor_re_artifact_snapshots(
            root,
            canonical_re_artifact_descriptors(root, index),
        )
    return _load_legacy_re_artifact_snapshots(root)


def _load_descriptor_re_artifact_snapshots(
    root: Path,
    descriptors: tuple[ReArtifactDescriptor, ...],
) -> list[ReArtifactSnapshot]:
    re_root = root / "re"
    snapshots: list[ReArtifactSnapshot] = []
    for descriptor in descriptors:
        room = RE_ARTIFACT_ROOMS.get((descriptor.kind, descriptor.scope))
        if descriptor.kind not in MINED_RE_ARTIFACT_KINDS or room is None:
            continue
        artifact = (root / descriptor.path).resolve()
        snapshots.append(
            ReArtifactSnapshot(
                re_root=re_root,
                artifact_file=artifact,
                content=artifact.read_bytes(),
                source=descriptor.path,
                artifact_metadata={
                    "scope": "reverse-engineering",
                    "canonical": True,
                    "artifact_kind": descriptor.kind,
                    "artifact_path": descriptor.path,
                    "artifact_hash": descriptor.sha256,
                    "source_file": descriptor.path,
                    "lifecycle_status": "active",
                    "provenance_type": "reverse_engineering_mine",
                    "added_by": "echelon",
                    "phase": "RE",
                    "room": room,
                    "re_artifact_scope": descriptor.scope,
                    **(
                        {"re_source_id": descriptor.source_id}
                        if descriptor.source_id is not None
                        else {}
                    ),
                },
            )
        )
    return snapshots


def _load_legacy_re_artifact_snapshots(root: Path) -> list[ReArtifactSnapshot]:
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
        artifact_kind, room = _re_artifact_classification(relative_to_re)
        snapshots.append(
            ReArtifactSnapshot(
                re_root=re_root,
                artifact_file=artifact,
                content=artifact.read_bytes(),
                source=source,
                artifact_metadata={
                    "scope": "reverse-engineering",
                    "canonical": True,
                    "artifact_kind": artifact_kind,
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

    def plan_re_artifact_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[object]:
        return self.miner.plan_re_artifact_rows(
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


def audit_re_memory(project_root: Path) -> ReMemoryAuditReport:
    snapshots = load_re_artifact_snapshots(project_root)
    re_root = snapshots[0].re_root if snapshots else resolve_re_root(project_root)
    try:
        adapter = create_re_memory_adapter(project_root, run_id="audit")
    except SpecMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        return ReMemoryAuditReport(
            schema_version=1,
            label="RE",
            root=str(re_root),
            wing=None,
            palace_path=None,
            status="unavailable",
            artifact_count=len(snapshots),
            expected_count=0,
            present_current_count=0,
            errors=[type(exc).__name__],
        )
    generic = audit_artifact_memory(
        label="RE",
        root=re_root,
        snapshots=snapshots,
        adapter=adapter,
        artifact_kind="reverse-engineering",
        artifact_kinds_by_source={
            snapshot.source: str(snapshot.artifact_metadata["artifact_kind"])
            for snapshot in snapshots
        },
        scope="reverse-engineering",
        planner_name="plan_re_artifact_rows",
    )
    return ReMemoryAuditReport(
        schema_version=generic.schema_version,
        re_root=generic.root,
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
            and _is_re_owned_memory(metadata)
            and metadata.get("wing") == getattr(adapter, "wing", "")
        ]
        if delete_ids:
            collection.delete(ids=delete_ids)  # type: ignore[attr-defined]
    except (Exception, SystemExit) as exc:
        return [f"re_memory_cleanup_skipped:{type(exc).__name__}"]
    return []


def _is_re_owned_memory(metadata: dict[str, Any]) -> bool:
    artifact_kind = metadata.get("artifact_kind")
    return (
        artifact_kind == "reverse-engineering"
        or (
            isinstance(artifact_kind, str)
            and artifact_kind in SUPPORTED_RE_ARTIFACT_KINDS
        )
        or metadata.get("scope") == "reverse-engineering"
        or metadata.get("provenance_type") == "reverse_engineering_mine"
    )


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
