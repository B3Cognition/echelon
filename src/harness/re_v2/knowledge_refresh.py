"""Pure freshness and invalidation planning for ordinary RE refresh actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from pathlib import PurePosixPath
from typing import Literal

from echelon.re_cli_options import KnowledgeDepth, resolve_knowledge_depth
from harness.re_registry import PublishedReIndex
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class KnowledgeRefreshError(ValueError):
    """Raised when immutable refresh inputs do not form one closed selection."""


@dataclass(frozen=True, slots=True)
class CurrentSourceSnapshotV1:
    schema_version: int
    workspace_snapshot_id: str
    source_id: str
    source_content_id: str
    source_path: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise KnowledgeRefreshError("invalid current source snapshot version")
        if not self.source_id or not isinstance(self.source_id, str):
            raise KnowledgeRefreshError("invalid current source ID")
        for value in (self.workspace_snapshot_id, self.source_content_id):
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise KnowledgeRefreshError("invalid current source snapshot identity")
        path = PurePosixPath(self.source_path)
        if (
            not self.source_path
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != self.source_path
        ):
            raise KnowledgeRefreshError("invalid current source path")

    @property
    def identity(self) -> str:
        return content_digest(asdict(self))


RefreshDisposition = Literal["reanalyze", "reuse", "not-checked"]
RefreshReason = Literal[
    "new-source",
    "source-changed",
    "depth-changed",
    "source-path-changed",
    "missing-depth-authority",
    "published-authority-unusable",
    "current",
    "not-selected",
]


@dataclass(frozen=True, slots=True)
class KnowledgeRefreshSourceV1:
    schema_version: int
    source_id: str
    disposition: RefreshDisposition
    reason: RefreshReason
    depth: KnowledgeDepth
    current_content_id: str | None
    published_content_id: str | None
    published_depth: str | None
    current_source_path: str | None
    published_source_path: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeRefreshPlanV1:
    schema_version: int
    workspace_snapshot_id: str
    publication_generation: int
    selected_source_ids: tuple[str, ...]
    sources: tuple[KnowledgeRefreshSourceV1, ...]
    reanalyze_source_ids: tuple[str, ...]
    reusable_source_ids: tuple[str, ...]
    retained_source_ids: tuple[str, ...]
    missing_retained_source_ids: tuple[str, ...]
    not_checked_source_ids: tuple[str, ...]
    removed_source_ids: tuple[str, ...]
    invalidated_source_output_ids: tuple[str, ...]
    invalidates_workspace_outputs: bool
    no_op: bool
    needs_attention: bool
    reason_code: str | None

    @property
    def identity(self) -> str:
        return content_digest(asdict(self))


def snapshots_from_partition(
    partition: WorkspacePartitionCatalogV1,
) -> tuple[CurrentSourceSnapshotV1, ...]:
    """Project authenticated partition authority into refresh-only identities."""

    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise KnowledgeRefreshError("refresh requires workspace partition authority")
    return tuple(
        CurrentSourceSnapshotV1(
            schema_version=1,
            workspace_snapshot_id=partition.snapshot_id,
            source_id=source.source_id,
            source_content_id=source.source_content_id,
            source_path=source.workspace_relative_path,
        )
        for source in partition.sources
    )


def plan_knowledge_refresh(
    *,
    declared_source_ids: tuple[str, ...],
    selected_snapshots: tuple[CurrentSourceSnapshotV1, ...],
    selected_source_ids: tuple[str, ...] | None,
    published: PublishedReIndex | None,
    explicit_depth: str | None,
    workspace_default: str | None,
) -> KnowledgeRefreshPlanV1:
    """Compare a frozen selected snapshot with durable publication metadata."""

    declared = _canonical_source_ids(declared_source_ids, "declared sources")
    selected = (
        declared
        if selected_source_ids is None
        else _canonical_source_ids(selected_source_ids, "selected sources")
    )
    if not set(selected).issubset(declared):
        raise KnowledgeRefreshError("selected sources must be declared")
    if any(not isinstance(item, CurrentSourceSnapshotV1) for item in selected_snapshots):
        raise KnowledgeRefreshError("refresh requires current source snapshots")
    current = {item.source_id: item for item in selected_snapshots}
    if len(current) != len(selected_snapshots) or set(current) != set(selected):
        raise KnowledgeRefreshError(
            "selected snapshot scope must exactly match selected sources"
        )
    snapshot_ids = {item.workspace_snapshot_id for item in selected_snapshots}
    if len(snapshot_ids) != 1:
        raise KnowledgeRefreshError("selected sources must share one workspace snapshot")
    workspace_snapshot_id = next(iter(snapshot_ids))

    published_sources = published.sources if published is not None else {}
    not_checked = tuple(sorted(set(declared) - set(selected)))
    removed = tuple(sorted(set(published_sources) - set(declared)))
    rows: list[KnowledgeRefreshSourceV1] = []
    reanalyze: list[str] = []
    reusable: list[str] = []

    for source_id in declared:
        prior = published_sources.get(source_id)
        depth = resolve_knowledge_depth(
            explicit=explicit_depth,
            published=prior.depth if prior is not None else None,
            workspace_default=workspace_default,
        )
        if source_id not in current:
            rows.append(
                KnowledgeRefreshSourceV1(
                    1,
                    source_id,
                    "not-checked",
                    "not-selected",
                    depth,
                    None,
                    prior.fingerprint if prior is not None else None,
                    prior.depth if prior is not None else None,
                    None,
                    prior.source_path if prior is not None else None,
                )
            )
            continue

        snapshot = current[source_id]
        if prior is None:
            disposition, reason = "reanalyze", "new-source"
        elif prior.depth is None:
            disposition, reason = "reanalyze", "missing-depth-authority"
        elif prior.status not in {"complete", "partial"}:
            disposition, reason = "reanalyze", "published-authority-unusable"
        elif prior.source_path != snapshot.source_path:
            disposition, reason = "reanalyze", "source-path-changed"
        elif prior.fingerprint != snapshot.source_content_id:
            disposition, reason = "reanalyze", "source-changed"
        elif prior.depth != depth:
            disposition, reason = "reanalyze", "depth-changed"
        else:
            disposition, reason = "reuse", "current"
        if disposition == "reanalyze":
            reanalyze.append(source_id)
        else:
            reusable.append(source_id)
        rows.append(
            KnowledgeRefreshSourceV1(
                1,
                source_id,
                disposition,  # type: ignore[arg-type]
                reason,  # type: ignore[arg-type]
                depth,
                snapshot.source_content_id,
                prior.fingerprint if prior is not None else None,
                prior.depth if prior is not None else None,
                snapshot.source_path,
                prior.source_path if prior is not None else None,
            )
        )

    invalidated = tuple(sorted({*reanalyze, *removed}))
    retained = tuple(
        source_id for source_id in not_checked if source_id in published_sources
    )
    missing_retained = tuple(
        source_id for source_id in not_checked if source_id not in published_sources
    )
    return KnowledgeRefreshPlanV1(
        schema_version=1,
        workspace_snapshot_id=workspace_snapshot_id,
        publication_generation=published.generation if published is not None else 0,
        selected_source_ids=selected,
        sources=tuple(rows),
        reanalyze_source_ids=tuple(reanalyze),
        reusable_source_ids=tuple(reusable),
        retained_source_ids=retained,
        missing_retained_source_ids=missing_retained,
        not_checked_source_ids=not_checked,
        removed_source_ids=removed,
        invalidated_source_output_ids=invalidated,
        invalidates_workspace_outputs=bool(invalidated or missing_retained),
        no_op=not invalidated and not missing_retained,
        needs_attention=bool(missing_retained),
        reason_code=(
            "unselected-source-has-no-published-authority"
            if missing_retained
            else None
        ),
    )


def _canonical_source_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise KnowledgeRefreshError(f"{label} must be non-empty source IDs")
    if len(set(values)) != len(values):
        raise KnowledgeRefreshError(f"{label} must be unique")
    return tuple(sorted(values))


__all__ = (
    "CurrentSourceSnapshotV1",
    "KnowledgeRefreshError",
    "KnowledgeRefreshPlanV1",
    "KnowledgeRefreshSourceV1",
    "plan_knowledge_refresh",
    "snapshots_from_partition",
)
