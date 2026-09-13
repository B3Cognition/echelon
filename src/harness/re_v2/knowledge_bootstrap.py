"""Snapshot-backed compatibility authority for fresh reviewed RE analysis.

The repaired knowledge path does not need legacy L2/L3 semantic output before
discovery.  Protocol 2.8 still consumes its historical target-authority shape,
so this module builds that shape exclusively from authenticated snapshot and
partition facts.  Its receipts assert inventory identity only; they never claim
that behavior was analyzed, reviewed, or found complete.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import digest_value, safe_id
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3TargetV1,
)
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    ReV2SnapshotError,
    load_snapshot_manifest,
    validate_source_snapshot,
)


class KnowledgeBootstrapError(ValueError):
    """Closed fresh-analysis bootstrap diagnostic."""


@dataclass(frozen=True, slots=True)
class SnapshotBootstrapResultV1:
    parent: ValidatedL3ParentV1
    selection: SelectionScopeV1
    partition_manifest_id: str
    bootstrap_authority_id: str
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.parent, ValidatedL3ParentV1):
            raise KnowledgeBootstrapError("invalid-bootstrap-parent")
        if not isinstance(self.selection, SelectionScopeV1):
            raise KnowledgeBootstrapError("invalid-bootstrap-selection")
        for value in (self.partition_manifest_id, self.bootstrap_authority_id):
            try:
                digest_value(value, "bootstrap-authority")
            except ValueError:
                raise KnowledgeBootstrapError("invalid-bootstrap-authority") from None
        copied = dict(self.authority_objects)
        if any(
            not isinstance(payload, bytes) or content_digest(payload) != object_id
            for object_id, payload in copied.items()
        ):
            raise KnowledgeBootstrapError("invalid-bootstrap-object-closure")
        object.__setattr__(
            self, "authority_objects", MappingProxyType(dict(sorted(copied.items())))
        )


def partition_manifest_authority_bytes(snapshot: CapturedSnapshot) -> bytes:
    """Return the canonical composite-source manifest used by RE protocols."""

    manifest = load_snapshot_manifest(snapshot)
    if manifest.components is None:
        raise KnowledgeBootstrapError("snapshot-has-no-composite-authority")
    return canonical_json_bytes(
        {
            "partition_protocol": "re-v2-partition-v2",
            "source_snapshot_id": manifest.snapshot_id,
            "sources": [
                {
                    "git_role": item.git_role,
                    "id": item.source_id,
                    "path": item.workspace_path,
                }
                for item in manifest.components
            ],
        }
    )


def _put(objects: dict[str, bytes], value: object) -> str:
    payload = canonical_json_bytes(value)
    object_id = content_digest(payload)
    objects[object_id] = payload
    return object_id


def _selected_sources(
    partition: WorkspacePartitionCatalogV1, selection: SelectionScopeV1
) -> tuple[object, ...]:
    declared = {source.source_id for source in partition.sources}
    selected_ids = declared if selection.all_sources else set(selection.source_ids)
    if not selected_ids or not selected_ids.issubset(declared):
        raise KnowledgeBootstrapError("selection-source-mismatch")
    selected = tuple(
        source for source in partition.sources if source.source_id in selected_ids
    )
    if len(selected) != len(selected_ids):
        raise KnowledgeBootstrapError("selection-source-mismatch")
    if selection.domain_keys:
        domains = {domain.domain_key for source in selected for domain in source.domains}
        if not set(selection.domain_keys).issubset(domains):
            raise KnowledgeBootstrapError("selection-domain-mismatch")
    return selected


def build_snapshot_bootstrap(
    run_id: str,
    snapshot: CapturedSnapshot,
    partition: WorkspacePartitionCatalogV1,
    selection: SelectionScopeV1,
) -> SnapshotBootstrapResultV1:
    """Build exact inventory authority for fresh reviewed discovery.

    The returned ``ValidatedL3ParentV1`` is a compatibility projection consumed
    only by existing protocol-2.8 preparation.  Empty finding and overlay sets
    are intentional: the receipts certify target identity, not prior analysis.
    """

    try:
        safe_id(run_id, "bootstrap-run")
        validate_source_snapshot(snapshot)
    except (ValueError, OSError, ReV2SnapshotError):
        raise KnowledgeBootstrapError("invalid-bootstrap-input") from None
    if not isinstance(partition, WorkspacePartitionCatalogV1) or not isinstance(
        selection, SelectionScopeV1
    ):
        raise KnowledgeBootstrapError("invalid-bootstrap-input")
    if partition.snapshot_id != snapshot.snapshot_id:
        raise KnowledgeBootstrapError("snapshot-partition-mismatch")

    selected = _selected_sources(partition, selection)
    objects: dict[str, bytes] = {}
    partition_bytes = partition_manifest_authority_bytes(snapshot)
    partition_manifest_id = content_digest(partition_bytes)
    objects[partition_manifest_id] = partition_bytes
    partition_id = _put(objects, partition.to_json_dict())
    if partition_id != partition.identity:
        raise KnowledgeBootstrapError("partition-identity-mismatch")

    policy_ids = {
        name: _put(
            objects,
            {
                "schema_version": 1,
                "kind": "reviewed_snapshot_bootstrap_policy",
                "policy": name,
                "version": "1",
            },
        )
        for name in ("artifact", "audit", "executor")
    }
    target_rows: list[tuple[str, str, str, str]] = []
    for source in selected:
        target_rows.append(
            ("source", source.source_id, source.source_content_id, source.source_id)
        )
        for domain in source.domains:
            if selection.domain_keys and domain.domain_key not in selection.domain_keys:
                continue
            target_rows.append(
                (
                    "domain",
                    domain.domain_key,
                    domain.domain_content_id,
                    source.source_id,
                )
            )
    target_rows.sort(key=lambda row: (row[3], row[0], row[1]))
    target_receipts: list[tuple[tuple[str, str, str, str], str]] = []
    for target_kind, target_id, target_content_id, source_id in target_rows:
        receipt_id = _put(
            objects,
            {
                "schema_version": 1,
                "kind": "reviewed_snapshot_target",
                "source_snapshot_id": snapshot.snapshot_id,
                "workspace_partition_catalog_id": partition.identity,
                "selection_id": selection.identity,
                "source_id": source_id,
                "target_kind": target_kind,
                "target_id": target_id,
                "target_content_id": target_content_id,
            },
        )
        target_receipts.append(
            ((target_kind, target_id, target_content_id, source_id), receipt_id)
        )

    bootstrap_authority_id = _put(
        objects,
        {
            "schema_version": 1,
            "kind": "reviewed_snapshot_bootstrap",
            "run_id": run_id,
            "source_snapshot_id": snapshot.snapshot_id,
            "partition_manifest_id": partition_manifest_id,
            "workspace_partition_catalog_id": partition.identity,
            "selection_id": selection.identity,
            "policy_ids": dict(sorted(policy_ids.items())),
            "target_receipt_ids": sorted(receipt for _row, receipt in target_receipts),
            "semantic_analysis_state": "not-started",
        },
    )
    closure_id = _put(
        objects,
        {
            "schema_version": 1,
            "kind": "reviewed_snapshot_bootstrap_closed",
            "bootstrap_authority_id": bootstrap_authority_id,
            "target_receipt_ids": sorted(receipt for _row, receipt in target_receipts),
        },
    )
    targets = []
    for (target_kind, target_id, target_content_id, source_id), receipt_id in target_receipts:
        targets.append(
            ValidatedL3TargetV1(
                1,
                target_kind,  # type: ignore[arg-type]
                source_id,
                target_id,
                target_content_id,
                receipt_id,
                (),
                (),
                (),
                (),
                "complete",
                (receipt_id,),
                policy_ids["audit"],
                policy_ids["executor"],
                bootstrap_authority_id,
                receipt_id,
            )
        )
    parent = ValidatedL3ParentV1(
        1,
        run_id,
        bootstrap_authority_id,
        closure_id,
        snapshot.snapshot_id,
        partition_manifest_id,
        selection.identity,
        bootstrap_authority_id,
        "complete",
        (),
        partition.identity,
        policy_ids["artifact"],
        (bootstrap_authority_id,),
        tuple(sorted(targets, key=lambda target: target.sort_key)),
    )
    return SnapshotBootstrapResultV1(
        parent,
        selection,
        partition_manifest_id,
        bootstrap_authority_id,
        objects,
    )


__all__ = (
    "KnowledgeBootstrapError",
    "SnapshotBootstrapResultV1",
    "build_snapshot_bootstrap",
    "partition_manifest_authority_bytes",
)
