"""Pure freshness and invalidation planning for ordinary RE refresh actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from pathlib import PurePosixPath
from typing import Literal, Mapping

from echelon.re_cli_options import KnowledgeDepth, resolve_knowledge_depth
from harness.re_registry import PublishedReIndex
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_27.authority import (
    ResolvedSynthesisParentV1,
    freeze_accepted_source_overviews,
    frozen_overview_payloads,
)
from harness.re_v2.protocol_27.model import AcceptedSourceOverviewCatalogV1


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


@dataclass(frozen=True, slots=True)
class KnowledgeRefreshMergeAuthorityV1:
    """Content-addressed authority for one fresh/retained source union."""

    schema_version: int
    refresh_plan_id: str
    publication_generation: int
    published_run_id: str
    published_parent_manifest_hash: str
    fresh_run_id: str
    fresh_parent_manifest_hash: str
    accepted_source_outcome_ids: tuple[str, ...]
    source_dispositions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise KnowledgeRefreshError("invalid refresh merge authority version")
        for value in (
            self.refresh_plan_id,
            self.published_parent_manifest_hash,
            self.fresh_parent_manifest_hash,
            *self.accepted_source_outcome_ids,
        ):
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise KnowledgeRefreshError("invalid refresh merge authority identity")
        if self.publication_generation < 1:
            raise KnowledgeRefreshError("refresh merge requires a published generation")
        if not self.published_run_id or not self.fresh_run_id:
            raise KnowledgeRefreshError("refresh merge requires source run identities")
        if self.accepted_source_outcome_ids != tuple(
            sorted(set(self.accepted_source_outcome_ids))
        ):
            raise KnowledgeRefreshError(
                "refresh merge source outcomes must be sorted and unique"
            )
        source_ids = tuple(source_id for source_id, _ in self.source_dispositions)
        if source_ids != tuple(sorted(set(source_ids))) or any(
            disposition not in {"reanalyzed", "reused", "not_checked"}
            for _, disposition in self.source_dispositions
        ):
            raise KnowledgeRefreshError("invalid refresh merge dispositions")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "refresh_plan_id": self.refresh_plan_id,
            "publication_generation": self.publication_generation,
            "published_run_id": self.published_run_id,
            "published_parent_manifest_hash": self.published_parent_manifest_hash,
            "fresh_run_id": self.fresh_run_id,
            "fresh_parent_manifest_hash": self.fresh_parent_manifest_hash,
            "accepted_source_outcome_ids": list(self.accepted_source_outcome_ids),
            "source_dispositions": [list(item) for item in self.source_dispositions],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "KnowledgeRefreshMergeAuthorityV1":
        fields = {
            "schema_version",
            "refresh_plan_id",
            "publication_generation",
            "published_run_id",
            "published_parent_manifest_hash",
            "fresh_run_id",
            "fresh_parent_manifest_hash",
            "accepted_source_outcome_ids",
            "source_dispositions",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise KnowledgeRefreshError("invalid refresh merge authority object")
        outcomes = value["accepted_source_outcome_ids"]
        dispositions = value["source_dispositions"]
        if not isinstance(outcomes, (list, tuple)) or not isinstance(
            dispositions, (list, tuple)
        ):
            raise KnowledgeRefreshError("invalid refresh merge authority arrays")
        rows: list[tuple[str, str]] = []
        for item in dispositions:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or not all(isinstance(part, str) for part in item)
            ):
                raise KnowledgeRefreshError("invalid refresh merge disposition row")
            rows.append((item[0], item[1]))
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            refresh_plan_id=value["refresh_plan_id"],  # type: ignore[arg-type]
            publication_generation=value["publication_generation"],  # type: ignore[arg-type]
            published_run_id=value["published_run_id"],  # type: ignore[arg-type]
            published_parent_manifest_hash=value["published_parent_manifest_hash"],  # type: ignore[arg-type]
            fresh_run_id=value["fresh_run_id"],  # type: ignore[arg-type]
            fresh_parent_manifest_hash=value["fresh_parent_manifest_hash"],  # type: ignore[arg-type]
            accepted_source_outcome_ids=tuple(outcomes),  # type: ignore[arg-type]
            source_dispositions=tuple(rows),
        )


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


def merge_refresh_synthesis_parent(
    *,
    plan: KnowledgeRefreshPlanV1,
    fresh_parent: ResolvedSynthesisParentV1,
    published_parent: ResolvedSynthesisParentV1,
    published: PublishedReIndex,
) -> ResolvedSynthesisParentV1:
    """Authenticate and merge fresh reviewed authority with a published parent."""

    if not isinstance(plan, KnowledgeRefreshPlanV1):
        raise KnowledgeRefreshError("refresh merge requires an immutable plan")
    if plan.no_op or plan.needs_attention:
        raise KnowledgeRefreshError("refresh merge requires executable changed work")
    if not isinstance(fresh_parent, ResolvedSynthesisParentV1) or not isinstance(
        published_parent, ResolvedSynthesisParentV1
    ):
        raise KnowledgeRefreshError("refresh merge requires resolved synthesis parents")
    if not isinstance(published, PublishedReIndex):
        raise KnowledgeRefreshError("refresh merge requires published authority")
    if published.generation != plan.publication_generation:
        raise KnowledgeRefreshError("publication generation changed during refresh")
    if published.published_from_run != published_parent.parent_run_id:
        raise KnowledgeRefreshError("published run differs from retained authority")

    fresh_by_source = {item.source_id: item for item in fresh_parent.accepted_sources}
    if set(fresh_by_source) != set(plan.reanalyze_source_ids):
        raise KnowledgeRefreshError("fresh source coverage differs from refresh plan")
    prior_by_source = {
        item.source_id: item for item in published_parent.accepted_sources
    }
    retained_ids = set(plan.reusable_source_ids) | set(plan.retained_source_ids)
    if not retained_ids <= set(prior_by_source):
        raise KnowledgeRefreshError("retained source authority is incomplete")
    if not retained_ids <= set(published.sources):
        raise KnowledgeRefreshError("retained source publication is incomplete")
    required_ids = {row.source_id for row in plan.sources}
    if required_ids != set(fresh_by_source) | retained_ids:
        raise KnowledgeRefreshError("refresh merge does not cover declared sources")

    outcomes = tuple(
        sorted(
            (*fresh_by_source.values(), *(prior_by_source[item] for item in retained_ids)),
            key=lambda item: item.source_id,
        )
    )
    fresh_catalog = freeze_accepted_source_overviews(fresh_parent)
    prior_catalog = freeze_accepted_source_overviews(published_parent)
    fresh_projections = {item.source_id: item for item in fresh_catalog.projections}
    prior_projections = {item.source_id: item for item in prior_catalog.projections}
    projections = tuple(
        fresh_projections[source_id]
        if source_id in fresh_by_source
        else prior_projections[source_id]
        for source_id in sorted(required_ids)
    )
    payloads = _merge_payloads(
        frozen_overview_payloads(published_parent),
        frozen_overview_payloads(fresh_parent),
        label="source overview",
    )
    objects = _merge_payloads(
        published_parent.authority_objects,
        fresh_parent.authority_objects,
        label="source authority",
    )
    required_objects = {
        value
        for source in outcomes
        for value in (
            source.source_root_hash,
            source.debt_manifest_hash,
            *source.lower_authority_ids,
        )
        if value is not None
    }
    if not required_objects <= set(objects):
        raise KnowledgeRefreshError("refresh source authority closure is incomplete")
    objects = {object_id: objects[object_id] for object_id in sorted(required_objects)}
    dispositions = {
        source_id: (
            "reanalyzed"
            if source_id in fresh_by_source
            else "not_checked"
            if source_id in plan.not_checked_source_ids
            else "reused"
        )
        for source_id in sorted(required_ids)
    }
    authority = KnowledgeRefreshMergeAuthorityV1(
        schema_version=1,
        refresh_plan_id=plan.identity,
        publication_generation=published.generation,
        published_run_id=published_parent.parent_run_id,
        published_parent_manifest_hash=published_parent.parent_manifest_hash,
        fresh_run_id=fresh_parent.parent_run_id,
        fresh_parent_manifest_hash=fresh_parent.parent_manifest_hash,
        accepted_source_outcome_ids=tuple(sorted(item.identity for item in outcomes)),
        source_dispositions=tuple(dispositions.items()),
    )
    authority_bytes = canonical_json_bytes(authority.to_json_dict())
    if content_digest(authority_bytes) != authority.identity:
        raise KnowledgeRefreshError("refresh merge authority identity changed")
    objects[authority.identity] = authority_bytes
    snapshot_id = content_digest(
        {"kind": "refresh-workspace-snapshot-v1", "refresh_merge_id": authority.identity}
    )
    partition_id = content_digest(
        {"kind": "refresh-workspace-partition-v1", "refresh_merge_id": authority.identity}
    )
    return ResolvedSynthesisParentV1(
        parent_run_id=fresh_parent.parent_run_id,
        parent_manifest_hash=authority.identity,
        source_snapshot_id=snapshot_id,
        partition_manifest_id=partition_id,
        selected_layers={item.source_id: "reviewed" for item in outcomes},
        accepted_sources=outcomes,
        authority_objects=objects,
        debt_summary_hashes={
            **published_parent.debt_summary_hashes,
            **fresh_parent.debt_summary_hashes,
        },
        _overview_catalog=AcceptedSourceOverviewCatalogV1(1, projections),
        _overview_payloads=dict(payloads),
        _overview_authorities={
            item.source_id: (item.source_root_key_id, item.content_hash)
            for item in projections
        },
        _context=fresh_parent._context,
        _refresh_dispositions=dispositions,
        _checkpoint_origin_run_id=published_parent.parent_run_id,
        _refresh_authority=authority,
    )


def _merge_payloads(
    first: Mapping[str, bytes],
    second: Mapping[str, bytes],
    *,
    label: str,
) -> dict[str, bytes]:
    merged = dict(first)
    for object_id, payload in second.items():
        existing = merged.get(object_id)
        if existing is not None and existing != payload:
            raise KnowledgeRefreshError(f"conflicting {label} object: {object_id}")
        merged[object_id] = payload
    return dict(sorted(merged.items()))


def _canonical_source_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise KnowledgeRefreshError(f"{label} must be non-empty source IDs")
    if len(set(values)) != len(values):
        raise KnowledgeRefreshError(f"{label} must be unique")
    return tuple(sorted(values))


__all__ = (
    "CurrentSourceSnapshotV1",
    "KnowledgeRefreshError",
    "KnowledgeRefreshMergeAuthorityV1",
    "KnowledgeRefreshPlanV1",
    "KnowledgeRefreshSourceV1",
    "merge_refresh_synthesis_parent",
    "plan_knowledge_refresh",
    "snapshots_from_partition",
)
