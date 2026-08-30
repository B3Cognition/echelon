"""Exact compatibility, certified ranking, and dependency-closed selection."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.baseline import CompactCertificationAssessmentV2
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_26.model import (
    CheckpointDispositionV1,
    CheckpointManifestV1,
    CheckpointRankV1,
    CheckpointSelectionBundleV1,
    CheckpointSelectionEntryV1,
)


RankExtractor = Callable[[CheckpointManifestV1], CheckpointRankV1]

DETERMINISTIC_RANK_POLICY_ID = "deterministic-pass-v1"
DETERMINISTIC_RANK_POLICY_HASH = content_digest(
    {
        "policy_id": DETERMINISTIC_RANK_POLICY_ID,
        "schema_version": 1,
        "vector": [1],
    }
)
COMPACT_RANK_POLICY_ID = "compact-established-coverage-v1"
COMPACT_RANK_POLICY_HASH = content_digest(
    {
        "components": [
            "observed_required_surface_count",
            "required_surface_claim_count",
            "combined_referenced_file_count",
            "combined_selected_file_count",
        ],
        "ordering": "larger-is-better",
        "policy_id": COMPACT_RANK_POLICY_ID,
        "schema_version": 1,
    }
)
SEMANTIC_RANK_POLICY_ID = "semantic-certified-pass-v1"
SEMANTIC_RANK_POLICY_HASH = content_digest(
    {
        "components": ["accepted_semantic_certification"],
        "ordering": "larger-is-better",
        "policy_id": SEMANTIC_RANK_POLICY_ID,
        "schema_version": 1,
    }
)


class CheckpointSelectionError(RuntimeError):
    """Raised when target graph authority cannot be selected deterministically."""


@dataclass(frozen=True, slots=True)
class RankPolicyRegistryV1:
    extractors: Mapping[tuple[str, str], RankExtractor]

    def __post_init__(self) -> None:
        copied: dict[tuple[str, str], RankExtractor] = {}
        for key, extractor in self.extractors.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not all(isinstance(value, str) and value for value in key)
                or not callable(extractor)
            ):
                raise CheckpointSelectionError("rank policy registration is invalid")
            copied[key] = extractor
        object.__setattr__(
            self,
            "extractors",
            MappingProxyType(dict(sorted(copied.items()))),
        )

    def extract(self, candidate: CheckpointManifestV1) -> CheckpointRankV1:
        key = (
            candidate.work_item.output_key.layer,
            candidate.work_item.output_key.artifact_kind,
        )
        extractor = self.extractors.get(key)
        if extractor is None:
            raise CheckpointSelectionError(
                f"no checkpoint rank policy is registered for {key!r}"
            )
        rank = extractor(candidate)
        if not isinstance(rank, CheckpointRankV1):
            raise CheckpointSelectionError("checkpoint rank extractor returned no rank")
        return rank


def _deterministic_rank(_candidate: CheckpointManifestV1) -> CheckpointRankV1:
    return CheckpointRankV1(
        1,
        DETERMINISTIC_RANK_POLICY_ID,
        DETERMINISTIC_RANK_POLICY_HASH,
        (1,),
    )


def _compact_rank(candidate: CheckpointManifestV1) -> CheckpointRankV1:
    assessment = getattr(candidate.certification_receipt, "assessment", None)
    if not isinstance(assessment, CompactCertificationAssessmentV2):
        raise CheckpointSelectionError("compact checkpoint has no compact assessment")
    observed = tuple(
        item for item in assessment.required_surfaces if item.status == "observed"
    )
    combined = assessment.coverage.combined
    return CheckpointRankV1(
        1,
        COMPACT_RANK_POLICY_ID,
        COMPACT_RANK_POLICY_HASH,
        (
            len(observed),
            sum(item.claim_count for item in observed),
            combined.referenced_file_count,
            combined.selected_file_count,
        ),
    )


def _semantic_rank(candidate: CheckpointManifestV1) -> CheckpointRankV1:
    certification = candidate.certification_receipt
    if (
        not hasattr(certification, "audit_target_id")
        or certification.verdict != "accepted"
    ):
        raise CheckpointSelectionError(
            "semantic checkpoint has no accepted semantic certification"
        )
    return CheckpointRankV1(
        1,
        SEMANTIC_RANK_POLICY_ID,
        SEMANTIC_RANK_POLICY_HASH,
        (1,),
    )


def _built_in_rank_policies() -> RankPolicyRegistryV1:
    deterministic = {
        ("L0", "source-inventory"),
        ("L0", "source-partition"),
        ("L0", "domain-inventory"),
        ("L0", "source-evidence-pack"),
        ("L0", "domain-evidence-pack"),
        ("L1", "domain-context-bundle"),
        ("L1", "source-overview-context-bundle"),
        ("L1", "source-baseline-root"),
        ("L2", "domain-evidence-pack"),
        ("L2", "domain-context-bundle"),
        ("L2", "source-overview-context-bundle"),
        ("L2", "source-baseline-root"),
    }
    compact = {
        ("L1", "domain-baseline"),
        ("L1", "source-overview"),
        ("L2", "domain-baseline"),
        ("L2", "source-overview"),
    }
    semantic = {
        ("L3", "semantic-audit-findings"),
        ("L3", "semantic-resolution-overlay"),
        ("L3", "target-closure-assessment"),
        ("L3", "source-composition-assessment"),
    }
    return RankPolicyRegistryV1(
        {
            **{key: _deterministic_rank for key in deterministic},
            **{key: _compact_rank for key in compact},
            **{key: _semantic_rank for key in semantic},
        }
    )


RANK_POLICIES = _built_in_rank_policies()


def compatibility_mismatches(
    expected: WorkItemV2,
    candidate: CheckpointManifestV1 | WorkItemV2,
) -> Sequence[str]:
    """Return exact field names whose canonical work authority differs."""
    if not isinstance(expected, WorkItemV2):
        raise CheckpointSelectionError("expected work must be WorkItemV2")
    observed = candidate.work_item if isinstance(candidate, CheckpointManifestV1) else candidate
    if not isinstance(observed, WorkItemV2):
        raise CheckpointSelectionError("candidate work must be WorkItemV2")
    mismatches: list[str] = []
    for field in WorkItemV2.FIELDS:
        expected_value = getattr(expected, field)
        observed_value = getattr(observed, field)
        if field == "output_key":
            for key_field in expected.output_key.FIELDS:
                if getattr(expected.output_key, key_field) != getattr(
                    observed.output_key, key_field
                ):
                    mismatches.append(f"output_key.{key_field}")
        elif expected_value != observed_value:
            mismatches.append(field)
    return tuple(mismatches)


def select_checkpoints(
    graph: object,
    candidates: Iterable[CheckpointManifestV1],
    direct_parent: Iterable[CheckpointManifestV1],
    *,
    rank_registry: RankPolicyRegistryV1 | None = None,
) -> CheckpointSelectionBundleV1:
    """Select a maximal exact, dependency-closed checkpoint set."""
    registry = RANK_POLICIES if rank_registry is None else rank_registry
    workspace = tuple(sorted(candidates, key=lambda item: item.identity))
    parents = tuple(sorted(direct_parent, key=lambda item: item.identity))
    if any(not isinstance(item, CheckpointManifestV1) for item in (*workspace, *parents)):
        raise CheckpointSelectionError("checkpoint candidates must be manifests")
    expected_by_key = _expected_work_items(graph, (*workspace, *parents))
    expected_epoch = _expected_audit_epoch(graph)

    compatible: dict[str, list[CheckpointManifestV1]] = {}
    rejected: list[CheckpointDispositionV1] = []
    quarantined: list[CheckpointDispositionV1] = []
    for candidate in workspace:
        expected = expected_by_key.get(candidate.artifact_key_id)
        expected_id = (
            candidate.work_item.work_item_id
            if expected is None
            else expected.work_item_id
        )
        if (
            expected is None
            or compatibility_mismatches(expected, candidate)
            or (
                candidate.work_item.output_key.layer == "L3"
                and expected_epoch is not None
                and candidate.audit_epoch_id != expected_epoch
            )
        ):
            rejected.append(_disposition(candidate, expected_id, "rejected", "checkpoint_incompatible"))
            continue
        try:
            extracted = registry.extract(candidate)
        except Exception:
            quarantined.append(
                _disposition(
                    candidate,
                    expected_id,
                    "quarantined",
                    "checkpoint_rank_invalid",
                )
            )
            continue
        if extracted != candidate.rank or candidate.rank_policy_hash != extracted.policy_hash:
            quarantined.append(
                _disposition(
                    candidate,
                    expected_id,
                    "quarantined",
                    "checkpoint_rank_invalid",
                )
            )
            continue
        compatible.setdefault(candidate.artifact_key_id, []).append(candidate)

    parent_by_key: dict[str, CheckpointManifestV1] = {}
    for parent in parents:
        expected = expected_by_key.get(parent.artifact_key_id)
        if (
            expected is None
            or compatibility_mismatches(expected, parent)
            or (
                parent.work_item.output_key.layer == "L3"
                and expected_epoch is not None
                and parent.audit_epoch_id != expected_epoch
            )
        ):
            continue
        existing = parent_by_key.get(parent.artifact_key_id)
        if existing is None or parent.artifact_hash < existing.artifact_hash:
            parent_by_key[parent.artifact_key_id] = parent

    discovery_rejected = list(rejected)
    choices: dict[str, list[CheckpointManifestV1]] = {}
    selection_reasons: dict[str, str] = {}
    selected: dict[str, tuple[CheckpointManifestV1, str]] = {
        key: (parent, "direct_parent") for key, parent in parent_by_key.items()
    }
    for key, values in sorted(compatible.items()):
        expected_id = expected_by_key[key].work_item_id
        ordered = sorted(values, key=_winner_key)
        if key in parent_by_key:
            choices[key] = ordered
            continue
        choices[key] = ordered
        selected[key] = (ordered[0], "workspace_checkpoint")
        top_vector = ordered[0].rank.vector
        tied = [item for item in ordered if item.rank.vector == top_vector]
        selection_reasons[key] = (
            "checkpoint_rank_hash_tiebreak"
            if len(tied) > 1
            else "checkpoint_rank_winner"
        )
    selected, removed = _prune_selection(selected, choices)
    origin_ids = sorted(
        {
            item.origin_run_id
            for values in choices.values()
            for item in values
        }
    )
    for origin_id in origin_ids:
        coherent = {
            key: value
            for key, value in selected.items()
            if value[1] == "direct_parent"
        }
        for key, ordered in sorted(choices.items()):
            if key in coherent:
                continue
            candidate = next(
                (item for item in ordered if item.origin_run_id == origin_id),
                None,
            )
            if candidate is not None:
                coherent[key] = (candidate, "workspace_checkpoint")
        coherent, coherent_removed = _prune_selection(coherent, choices)
        if len(coherent) > len(selected):
            selected = coherent
            removed = coherent_removed

    alternatives: list[CheckpointDispositionV1] = []
    rejected = discovery_rejected
    for key, ordered in sorted(choices.items()):
        expected_id = expected_by_key[key].work_item_id
        chosen = selected.get(key)
        if key in parent_by_key:
            alternatives.extend(
                _disposition(
                    item,
                    expected_id,
                    "not_selected",
                    "direct_parent_precedence",
                )
                for item in ordered
            )
            continue
        if chosen is None:
            reason = removed.get(key, "checkpoint_dependency_missing")
            rejected.extend(
                _disposition(item, expected_id, "rejected", reason)
                for item in ordered
            )
            continue
        winner = chosen[0]
        if winner is not ordered[0]:
            selection_reasons[key] = "checkpoint_dependency_closure"
        for candidate in ordered:
            if candidate.identity == winner.identity:
                continue
            if not _dependencies_satisfied(candidate, selected):
                rejected.append(
                    _disposition(
                        candidate,
                        expected_id,
                        "rejected",
                        "checkpoint_dependency_missing",
                    )
                )
                continue
            reason = (
                "checkpoint_rank_hash_tiebreak"
                if candidate.rank.vector == winner.rank.vector
                else "checkpoint_rank_winner"
            )
            alternatives.append(
                _disposition(candidate, expected_id, "not_selected", reason)
            )

    ordered_keys = _topological_keys(selected)
    selected_entries = tuple(
        _selection_entry(
            selected[key][0],
            source_kind=selected[key][1],
            selection_reason=(
                "direct_parent_precedence"
                if selected[key][1] == "direct_parent"
                else selection_reasons[key]
            ),
        )
        for key in ordered_keys
    )
    selected_manifests = tuple(selected[key][0] for key in ordered_keys)
    copied_sizes: dict[str, int] = {}
    for candidate in selected_manifests:
        for object_hash, byte_count in candidate.immutable_object_byte_counts.items():
            existing = copied_sizes.get(object_hash)
            if existing is not None and existing != byte_count:
                raise CheckpointSelectionError(
                    "selected checkpoint object byte counts conflict"
                )
            copied_sizes[object_hash] = byte_count
    receipt_ids = {
        receipt_id
        for item in selected_manifests
        for receipt_id in (
            item.certification_receipt.identity,
            item.artifact_acceptance_receipt.identity,
            *(
                ()
                if item.candidate_assessment is None
                else (item.candidate_assessment.identity,)
            ),
        )
    }
    return CheckpointSelectionBundleV1(
        schema_version=1,
        source_snapshot_id=_graph_digest(graph, "source_snapshot_id"),
        partition_manifest_id=_graph_digest(graph, "partition_manifest_id"),
        target_layer=_graph_target_layer(graph),
        target_selection_id=_graph_digest(graph, "target_selection_id"),
        target_graph_id=_graph_digest(graph, "target_graph_id"),
        cache_generation_id=content_digest(
            {
                "candidate_manifest_ids": [item.identity for item in workspace],
                "direct_parent_manifest_ids": [item.identity for item in parents],
                "schema_version": 1,
            }
        ),
        selected=selected_entries,
        origin_manifest_hashes=tuple(
            sorted({item.origin_manifest_hash for item in selected_manifests})
        ),
        origin_event_prefix_hashes=tuple(
            sorted({item.origin_event_prefix_hash for item in selected_manifests})
        ),
        origin_ledger_prefix_hashes=tuple(
            sorted({item.origin_ledger_prefix_hash for item in selected_manifests})
        ),
        copied_receipt_ids=tuple(sorted(receipt_ids)),
        copied_work_item_ids=tuple(
            sorted(item.work_item.work_item_id for item in selected_manifests)
        ),
        copied_object_ids=tuple(sorted(copied_sizes)),
        copied_byte_count=sum(copied_sizes.values()),
        alternatives=_sorted_dispositions(alternatives),
        rejected=_sorted_dispositions(rejected),
        quarantined=_sorted_dispositions(quarantined),
    )


def _winner_key(candidate: CheckpointManifestV1) -> tuple[tuple[int, ...], str]:
    return tuple(-value for value in candidate.rank.vector), candidate.artifact_hash


def _expected_work_items(
    graph: object,
    candidates: tuple[CheckpointManifestV1, ...],
) -> dict[str, WorkItemV2]:
    explicit = getattr(graph, "expected_work_items", None)
    if explicit is not None:
        items = tuple(explicit)
        if any(not isinstance(item, WorkItemV2) for item in items):
            raise CheckpointSelectionError("graph expected_work_items are invalid")
        return {item.output_key.identity: item for item in items}
    templates = tuple(getattr(graph, "templates", ()))
    result: dict[str, WorkItemV2] = {}
    by_template = {getattr(item, "template_id", None): item for item in templates}
    for candidate in candidates:
        item = candidate.work_item
        template = by_template.get(item.template_id)
        if template is None or any(
            getattr(template, field) != getattr(item, field)
            for field in item.COPIED_TEMPLATE_FIELDS
        ):
            continue
        key = item.output_key
        if (
            template.scope != key.scope
            or template.artifact_kind != key.artifact_kind
            or template.layer != key.layer
            or template.producer_protocol_version != key.producer_protocol_version
            or template.layer_policy_hash != key.layer_policy_hash
        ):
            continue
        result[key.identity] = item
    return result


def _expected_audit_epoch(graph: object) -> str | None:
    explicit = getattr(graph, "audit_epoch_id", None)
    if explicit is not None:
        return explicit
    manifest = getattr(graph, "manifest", None)
    reference = None if manifest is None else getattr(manifest, "frozen_audit_epoch", None)
    return None if reference is None else reference.object_hash


def _dependencies_satisfied(
    candidate: CheckpointManifestV1,
    selected: Mapping[str, tuple[CheckpointManifestV1, str]],
) -> bool:
    for dependency in candidate.accepted_artifact_dependencies:
        chosen = selected.get(dependency.artifact_key_id)
        if chosen is None or chosen[0].artifact_hash != dependency.artifact_hash:
            return False
    return all(
        object_hash in candidate.immutable_object_byte_counts
        for object_hash in candidate.non_artifact_dependency_hashes
    )


def _prune_selection(
    initial: Mapping[str, tuple[CheckpointManifestV1, str]],
    choices: Mapping[str, Sequence[CheckpointManifestV1]],
) -> tuple[
    dict[str, tuple[CheckpointManifestV1, str]],
    dict[str, str],
]:
    """Close one deterministic candidate set, trying valid same-key fallbacks."""
    selected = dict(initial)
    removed: dict[str, str] = {}
    while True:
        changed = False
        cyclic = _cyclic_selected_keys(selected)
        if cyclic:
            for key in sorted(cyclic):
                removed[key] = "checkpoint_cycle_detected"
                selected.pop(key, None)
            changed = True
        for key in sorted(tuple(selected)):
            candidate, source_kind = selected[key]
            if _dependencies_satisfied(candidate, selected):
                continue
            if source_kind == "workspace_checkpoint":
                replacement = next(
                    (
                        item
                        for item in choices.get(key, ())
                        if item.identity != candidate.identity
                        and _dependencies_satisfied(item, selected)
                    ),
                    None,
                )
                if replacement is not None:
                    selected[key] = (replacement, source_kind)
                    changed = True
                    continue
            removed[key] = "checkpoint_dependency_missing"
            selected.pop(key, None)
            changed = True
        if not changed:
            return selected, removed


def _cyclic_selected_keys(
    selected: Mapping[str, tuple[CheckpointManifestV1, str]],
) -> frozenset[str]:
    edges = {
        key: tuple(
            dependency.artifact_key_id
            for dependency in value[0].accepted_artifact_dependencies
            if dependency.artifact_key_id in selected
        )
        for key, value in selected.items()
    }
    active: list[str] = []
    visited: set[str] = set()
    cyclic: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            cyclic.update(active[active.index(key) :])
            return
        if key in visited:
            return
        active.append(key)
        for dependency in sorted(edges[key]):
            visit(dependency)
        active.pop()
        visited.add(key)

    for key in sorted(edges):
        visit(key)
    return frozenset(cyclic)


def _topological_keys(
    selected: Mapping[str, tuple[CheckpointManifestV1, str]],
) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(key: str) -> None:
        if key in seen:
            return
        for dependency in sorted(
            item.artifact_key_id
            for item in selected[key][0].accepted_artifact_dependencies
            if item.artifact_key_id in selected
        ):
            visit(dependency)
        seen.add(key)
        ordered.append(key)

    for key in sorted(selected):
        visit(key)
    return tuple(ordered)


def _selection_entry(
    candidate: CheckpointManifestV1,
    *,
    source_kind: str,
    selection_reason: str,
) -> CheckpointSelectionEntryV1:
    return CheckpointSelectionEntryV1(
        schema_version=1,
        expected_work_item_id=candidate.work_item.work_item_id,
        source_kind=source_kind,  # type: ignore[arg-type]
        checkpoint_manifest_id=(
            candidate.identity if source_kind == "workspace_checkpoint" else None
        ),
        adopted_artifact_authority=candidate.adopted_artifact_authority,
        dependency_artifact_key_ids=tuple(
            sorted(
                item.artifact_key_id
                for item in candidate.accepted_artifact_dependencies
            )
        ),
        copied_object_ids=candidate.immutable_object_hashes,
        copied_byte_count=sum(candidate.immutable_object_byte_counts.values()),
        rank=(candidate.rank if source_kind == "workspace_checkpoint" else None),
        origin_run_id=candidate.origin_run_id,
        selection_reason=selection_reason,
    )


def _disposition(
    candidate: CheckpointManifestV1,
    expected_work_item_id: str,
    disposition: str,
    reason: str,
) -> CheckpointDispositionV1:
    return CheckpointDispositionV1(
        1,
        candidate.identity,
        expected_work_item_id,
        disposition,  # type: ignore[arg-type]
        reason,
        candidate.rank,
    )


def _sorted_dispositions(
    values: Iterable[CheckpointDispositionV1],
) -> tuple[CheckpointDispositionV1, ...]:
    by_identity = {item.identity: item for item in values}
    return tuple(by_identity[key] for key in sorted(by_identity))


def _graph_digest(graph: object, field: str) -> str:
    value = getattr(graph, field, None)
    if isinstance(value, str):
        return value
    if field == "source_snapshot_id":
        inputs = getattr(graph, "inputs", getattr(graph, "_inputs", None))
        partition = None if inputs is None else getattr(inputs, "workspace_partition", None)
        value = None if partition is None else getattr(partition, "snapshot_id", None)
    elif field == "partition_manifest_id":
        inputs = getattr(graph, "inputs", getattr(graph, "_inputs", None))
        partition = None if inputs is None else getattr(inputs, "workspace_partition", None)
        value = None if partition is None else getattr(partition, "identity", None)
    if not isinstance(value, str):
        value = content_digest(
            {
                "field": field,
                "template_ids": sorted(
                    getattr(item, "template_id", "")
                    for item in getattr(graph, "templates", ())
                ),
            }
        )
    return value


def _graph_target_layer(graph: object) -> str:
    explicit = getattr(graph, "target_layer", None)
    if explicit in {"L1", "L2", "L3"}:
        return explicit
    layers = {getattr(item, "layer", None) for item in getattr(graph, "templates", ())}
    for layer in ("L3", "L2", "L1"):
        if layer in layers:
            return layer
    raise CheckpointSelectionError("target graph has no L1/L2/L3 layer")


__all__ = (
    "DETERMINISTIC_RANK_POLICY_HASH",
    "DETERMINISTIC_RANK_POLICY_ID",
    "RANK_POLICIES",
    "RankPolicyRegistryV1",
    "compatibility_mismatches",
    "select_checkpoints",
)
