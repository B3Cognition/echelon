"""Aggregate-safe bounded context construction for protocol-2.7 synthesis.

Version 1 bounded every excerpt independently but did not reserve space for the
sum of excerpts.  Workspace roots can reference scores of valid artifacts, so
this version deterministically finds the largest common excerpt size whose
fully serialized context fits the already-pinned total byte ceiling.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore

from .context import (
    Protocol27ContextError,
    SynthesisAuthorizedObjectV1,
    SynthesisContextPolicyV1,
    SynthesisContextV1,
    SynthesisDependencyArtifactV1,
    SynthesisPublicContractV1,
    _classify_non_artifact,
    _excerpt,
    _load_context_policy,
    _read_authority_object,
    _source_ids_for_scope,
    _validate_work_item_shape,
)
from .model import SynthesisWorkItemV1
from .schemas import required_section_ids


def fit_excerpt_limit(
    payloads: Sequence[bytes],
    *,
    max_excerpt_bytes: int,
    max_context_bytes: int,
    serialized_size: Callable[[tuple[str, ...]], int],
) -> int:
    """Return the largest shared UTF-8 prefix limit fitting a serialized body."""
    if max_excerpt_bytes <= 0 or max_context_bytes <= 0:
        raise Protocol27ContextError("excerpt fitting limits must be positive")

    def excerpts(limit: int) -> tuple[str, ...]:
        return tuple(_excerpt(payload, limit)[0] for payload in payloads)

    if serialized_size(excerpts(0)) > max_context_bytes:
        raise Protocol27ContextError(
            "synthesis context metadata exceeds its byte ceiling"
        )
    low, high = 0, max_excerpt_bytes
    while low < high:
        candidate = (low + high + 1) // 2
        if serialized_size(excerpts(candidate)) <= max_context_bytes:
            low = candidate
        else:
            high = candidate - 1
    return low


def build_synthesis_context_v2(
    inputs,  # ValidatedProtocol27Inputs; lazy to avoid an inputs/context cycle.
    work_item: SynthesisWorkItemV1,
    *,
    policy: SynthesisContextPolicyV1 | None = None,
    aggregate_byte_limit: int | None = None,
) -> SynthesisContextV1:
    """Build a context whose aggregate canonical size is guaranteed to fit."""
    from .inputs import ValidatedProtocol27Inputs

    if not isinstance(inputs, ValidatedProtocol27Inputs):
        raise Protocol27ContextError("synthesis context requires validated child inputs")
    if not isinstance(work_item, SynthesisWorkItemV1):
        raise Protocol27ContextError("synthesis context requires a synthesis work item")
    selected_policy = policy or _load_context_policy(inputs)
    if selected_policy.identity != work_item.output_key.context_policy_hash:
        raise Protocol27ContextError("synthesis context policy authority mismatch")
    target_bytes = min(
        selected_policy.max_canonical_json_bytes,
        (
            selected_policy.max_canonical_json_bytes
            if aggregate_byte_limit is None
            else aggregate_byte_limit
        ),
    )
    if target_bytes <= 0:
        raise Protocol27ContextError("aggregate synthesis context limit is invalid")
    node = inputs.graph.node_for_work_item(work_item)
    _validate_work_item_shape(inputs, work_item, node)
    source_ids = _source_ids_for_scope(inputs, work_item.output_key.scope)
    store = ObjectStore(inputs.paths.objects)
    overview_sources = {
        item.identity: item.source_id
        for item in inputs.source_overview_catalog.projections
    }
    outcomes_by_id = {
        item.source_id: item for item in inputs.parent_authority.accepted_sources
    }
    outcomes = tuple(outcomes_by_id[source_id] for source_id in source_ids)

    dependency_rows = tuple(
        (
            dependency,
            _read_authority_object(store, dependency.artifact_hash),
            (
                (overview_sources[dependency.artifact_key_id],)
                if dependency.artifact_key_id in overview_sources
                else source_ids
            ),
        )
        for dependency in work_item.output_key.artifact_dependencies
    )
    authorized_rows = []
    for object_hash in work_item.output_key.non_artifact_dependency_hashes:
        role, object_sources = _classify_non_artifact(inputs, object_hash, source_ids)
        authorized_rows.append(
            (object_hash, role, object_sources, _read_authority_object(store, object_hash))
        )
    for debt_hash in work_item.output_key.debt_manifest_hashes:
        debt_sources = tuple(
            item.source_id for item in outcomes if item.debt_manifest_hash == debt_hash
        )
        if not debt_sources:
            raise Protocol27ContextError("debt authority is outside context sources")
        authorized_rows.append(
            (
                debt_hash,
                "debt-manifest",
                debt_sources,
                _read_authority_object(store, debt_hash),
            )
        )
    authorized_rows.sort(key=lambda row: row[0])
    if len(authorized_rows) + len(dependency_rows) > selected_policy.max_objects:
        raise Protocol27ContextError("synthesis context exceeds its object ceiling")

    contract = SynthesisPublicContractV1(
        public_path=node.public_path,
        required_section_ids=required_section_ids(node.artifact_kind),
    )

    def assemble(limit: int) -> SynthesisContextV1:
        dependencies = tuple(
            sorted(
                (
                    SynthesisDependencyArtifactV1(
                        dependency.artifact_key_id,
                        dependency.artifact_hash,
                        dependency_sources,
                        *_excerpt(payload, limit),
                    )
                    for dependency, payload, dependency_sources in dependency_rows
                ),
                key=lambda item: item.artifact_key_id,
            )
        )
        authorized = tuple(
            SynthesisAuthorizedObjectV1(
                object_hash,
                role,
                object_sources,
                *_excerpt(payload, limit),
            )
            for object_hash, role, object_sources, payload in authorized_rows
        )
        return SynthesisContextV1(
            schema_version=1,
            work_item_id=work_item.work_item_id,
            artifact_key_id=work_item.output_key.artifact_key_id,
            artifact_kind=work_item.output_key.artifact_kind,
            scope=work_item.output_key.scope,
            source_ids=source_ids,
            authorized_objects=authorized,
            dependency_artifacts=dependencies,
            source_outcomes=outcomes,
            debt_refs=work_item.output_key.debt_manifest_hashes,
            input_quality=(
                "partial" if work_item.output_key.debt_manifest_hashes else "complete"
            ),
            public_contract=contract,
            response_schema_hash=work_item.output_key.response_schema_hash,
            context_policy_hash=work_item.output_key.context_policy_hash,
            max_canonical_json_bytes=selected_policy.max_canonical_json_bytes,
        )

    payloads = tuple(row[1] for row in dependency_rows) + tuple(
        row[3] for row in authorized_rows
    )

    def serialized_size(excerpts: tuple[str, ...]) -> int:
        dependency_count = len(dependency_rows)
        dependency_excerpts = excerpts[:dependency_count]
        authorized_excerpts = excerpts[dependency_count:]
        dependencies = tuple(
            sorted(
                (
                    SynthesisDependencyArtifactV1(
                        dependency.artifact_key_id,
                        dependency.artifact_hash,
                        dependency_sources,
                        excerpt,
                        len(payload) > len(excerpt.encode("utf-8")),
                    )
                    for (dependency, payload, dependency_sources), excerpt in zip(
                        dependency_rows, dependency_excerpts, strict=True
                    )
                ),
                key=lambda item: item.artifact_key_id,
            )
        )
        authorized = tuple(
            SynthesisAuthorizedObjectV1(
                object_hash,
                role,
                object_sources,
                excerpt,
                len(payload) > len(excerpt.encode("utf-8")),
            )
            for (object_hash, role, object_sources, payload), excerpt in zip(
                authorized_rows, authorized_excerpts, strict=True
            )
        )
        value = {
            "schema_version": 1,
            "work_item_id": work_item.work_item_id,
            "artifact_key_id": work_item.output_key.artifact_key_id,
            "artifact_kind": work_item.output_key.artifact_kind,
            "scope": work_item.output_key.scope.to_json_dict(),
            "source_ids": list(source_ids),
            "authorized_objects": [item.to_json_dict() for item in authorized],
            "dependency_artifacts": [item.to_json_dict() for item in dependencies],
            "source_outcomes": [item.to_json_dict() for item in outcomes],
            "debt_refs": list(work_item.output_key.debt_manifest_hashes),
            "input_quality": (
                "partial" if work_item.output_key.debt_manifest_hashes else "complete"
            ),
            "public_contract": contract.to_json_dict(),
            "response_schema_hash": work_item.output_key.response_schema_hash,
            "context_policy_hash": work_item.output_key.context_policy_hash,
            "max_canonical_json_bytes": selected_policy.max_canonical_json_bytes,
        }
        return len(canonical_json_bytes(value))

    excerpt_limit = fit_excerpt_limit(
        payloads,
        max_excerpt_bytes=selected_policy.max_object_excerpt_bytes,
        max_context_bytes=target_bytes,
        serialized_size=serialized_size,
    )
    return assemble(excerpt_limit)


__all__ = ("build_synthesis_context_v2", "fit_excerpt_limit")
