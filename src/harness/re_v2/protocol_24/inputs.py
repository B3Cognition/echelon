"""Immutable schema-3 input publication over the shared manifest-last store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
)
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    Protocol22ExecutorError,
)
from harness.re_v2.protocol_22.inputs import (
    FaultHook,
    Protocol22InputSet,
    Protocol22InputStoreError,
    ValidatedProtocol22Inputs,
    _executor_catalog_payload,
    _object_relative_path,
    _publish_immutable_run_inputs,
    _read_reference,
    _read_regular_beneath,
    _referenced_object_roles,
    _validate_referenced_object,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_22.partition import (
    Protocol22PartitionError,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    Protocol22PolicyError,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    load_canonical_object,
)

from .model import ParentAuthorityBundleV1, RunManifestV3


class Protocol24InputStoreError(Protocol22InputStoreError):
    """Raised when immutable schema-3 inputs are unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class Protocol24InputSet(Protocol22InputSet):
    parent_authority_bundle: ParentAuthorityBundleV1

    def __post_init__(self) -> None:
        Protocol22InputSet.__post_init__(self)
        if not isinstance(self.parent_authority_bundle, ParentAuthorityBundleV1):
            raise Protocol24InputStoreError(
                "parent_authority_bundle must be ParentAuthorityBundleV1"
            )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol24Inputs(ValidatedProtocol22Inputs):
    parent_authority_bundle: ParentAuthorityBundleV1

    def __post_init__(self) -> None:
        ValidatedProtocol22Inputs.__post_init__(self)
        if not isinstance(self.parent_authority_bundle, ParentAuthorityBundleV1):
            raise Protocol24InputStoreError(
                "parent_authority_bundle must be ParentAuthorityBundleV1"
            )


@dataclass(frozen=True, slots=True)
class _PreparedProtocol24Inputs:
    workspace_payload: bytes
    artifact_policy_payload: bytes
    executor_payload: bytes
    parent_authority_payload: bytes


def create_protocol_24_run_store(
    run_dir: Path,
    manifest: RunManifestV3,
    inputs: Protocol24InputSet,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Publish all schema-3 authority before linking the manifest."""
    if not isinstance(manifest, RunManifestV3):
        raise Protocol24InputStoreError(
            "protocol-2.4 input creation requires RunManifestV3"
        )
    if not isinstance(inputs, Protocol24InputSet):
        raise Protocol24InputStoreError(
            "protocol-2.4 input creation requires Protocol24InputSet"
        )
    if manifest.run_id != run_dir.name:
        raise Protocol24InputStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    prepared = _prepare_protocol_24_inputs(manifest, inputs)
    try:
        return _publish_immutable_run_inputs(
            run_dir,
            manifest,
            inputs.immutable_objects,
            (
                (
                    "workspace_partition",
                    manifest.workspace_partition_catalog,
                    prepared.workspace_payload,
                ),
                (
                    "artifact_policy",
                    manifest.artifact_policy_catalog,
                    prepared.artifact_policy_payload,
                ),
                (
                    "executor_contract",
                    manifest.executor_contract_catalog,
                    prepared.executor_payload,
                ),
                (
                    "parent_authority",
                    manifest.parent_authority_bundle,
                    prepared.parent_authority_payload,
                ),
            ),
            fault_hook,
            protocol_label="protocol-2.4",
        )
    except Protocol24InputStoreError:
        raise
    except Protocol22InputStoreError as exc:
        raise Protocol24InputStoreError(str(exc)) from exc


def load_protocol_24_inputs(
    paths: ReV2Paths,
    manifest: RunManifestV3,
    *,
    _embedded_in_outer_manifest: bool = False,
) -> ValidatedProtocol24Inputs:
    """Authenticate the four schema-3 inputs and their referenced blobs."""
    if not isinstance(paths, ReV2Paths):
        raise Protocol24InputStoreError("paths must be ReV2Paths")
    if not isinstance(manifest, RunManifestV3):
        raise Protocol24InputStoreError("manifest must be RunManifestV3")
    canonical_paths = ReV2Paths.for_run(paths.root.parent)
    if paths != canonical_paths or manifest.run_id != paths.root.parent.name:
        raise Protocol24InputStoreError(
            "input paths do not match the protocol-2.4 manifest run"
        )
    if not _embedded_in_outer_manifest:
        try:
            authoritative = load_run_manifest(paths.root.parent)
        except ReV2RunStoreError as exc:
            raise Protocol24InputStoreError(
                f"cannot load authoritative manifest: {exc}"
            ) from exc
        if authoritative != manifest:
            raise Protocol24InputStoreError(
                "manifest argument does not equal the authoritative manifest"
            )
    if paths.inputs.is_symlink() or not paths.inputs.is_dir():
        raise Protocol24InputStoreError(
            f"protocol-2.4 input directory is unsafe or missing: {paths.inputs}"
        )
    if paths.objects.is_symlink() or not paths.objects.is_dir():
        raise Protocol24InputStoreError(
            f"protocol-2.4 object directory is unsafe or missing: {paths.objects}"
        )
    _validate_reference_layout(manifest)
    try:
        workspace = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.workspace_partition_catalog,
                "workspace partition",
            ),
            WorkspacePartitionCatalogV1.from_json_dict,
        )
        policy = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.artifact_policy_catalog,
                "artifact policy",
            ),
            ArtifactPolicyCatalogV1.from_json_dict,
        )
        executor = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.executor_contract_catalog,
                "executor contract",
            ),
            ExecutorContractCatalogV1.from_json_dict,
        )
        parent = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.parent_authority_bundle,
                "parent authority",
            ),
            ParentAuthorityBundleV1.from_json_dict,
        )
    except (
        Protocol22InputStoreError,
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22PolicyError,
        Protocol22ExecutorError,
    ) as exc:
        raise Protocol24InputStoreError(
            f"invalid immutable protocol-2.4 input: {exc}"
        ) from exc
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol24InputStoreError(
            "workspace partition snapshot does not match the run manifest"
        )
    _validate_parent_binding(manifest, parent)

    roles = _referenced_object_roles(executor)
    required = set(roles) | _parent_object_hashes(parent)
    objects: dict[str, bytes] = {}
    for object_hash in sorted(required):
        try:
            payload = _read_regular_beneath(
                paths.objects,
                _object_relative_path(object_hash),
                f"immutable object {object_hash}",
            )
        except Protocol22InputStoreError as exc:
            raise Protocol24InputStoreError(str(exc)) from exc
        if content_digest(payload) != object_hash:
            raise Protocol24InputStoreError(
                f"immutable object hash mismatch: {object_hash}"
            )
        if object_hash in roles:
            try:
                _validate_referenced_object(payload, roles[object_hash], object_hash)
            except Protocol22InputStoreError as exc:
                raise Protocol24InputStoreError(str(exc)) from exc
        objects[object_hash] = payload
    return ValidatedProtocol24Inputs(
        workspace_partition=workspace,
        artifact_policy=policy,
        executor_contract=executor,
        immutable_objects=objects,
        parent_authority_bundle=parent,
    )


def _prepare_protocol_24_inputs(
    manifest: RunManifestV3,
    inputs: Protocol24InputSet,
) -> _PreparedProtocol24Inputs:
    _validate_reference_layout(manifest)
    try:
        workspace_payload = canonical_json_bytes(
            inputs.workspace_partition.to_json_dict()
        )
        workspace = load_canonical_object(
            workspace_payload,
            WorkspacePartitionCatalogV1.from_json_dict,
        )
        policy_payload = canonical_json_bytes(inputs.artifact_policy.to_json_dict())
        policy = load_canonical_object(
            policy_payload,
            ArtifactPolicyCatalogV1.from_json_dict,
        )
        executor_payload, executor = _executor_catalog_payload(
            inputs.executor_contract
        )
        parent_payload = canonical_json_bytes(
            inputs.parent_authority_bundle.to_json_dict()
        )
        parent = load_canonical_object(
            parent_payload,
            ParentAuthorityBundleV1.from_json_dict,
        )
    except (
        TypeError,
        ValueError,
        UnicodeError,
        Protocol22InputStoreError,
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22PolicyError,
        Protocol22ExecutorError,
    ) as exc:
        raise Protocol24InputStoreError(
            f"invalid protocol-2.4 immutable input: {exc}"
        ) from exc
    if (
        workspace != inputs.workspace_partition
        or policy != inputs.artifact_policy
        or parent != inputs.parent_authority_bundle
    ):
        raise Protocol24InputStoreError(
            "typed protocol-2.4 inputs do not round-trip canonically"
        )
    expected = (
        ("workspace partition", manifest.workspace_partition_catalog, workspace_payload),
        ("artifact policy", manifest.artifact_policy_catalog, policy_payload),
        ("executor contract", manifest.executor_contract_catalog, executor_payload),
        ("parent authority", manifest.parent_authority_bundle, parent_payload),
    )
    for label, reference, payload in expected:
        if content_digest(payload) != reference.object_hash:
            raise Protocol24InputStoreError(f"{label} catalog hash mismatch")
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol24InputStoreError(
            "workspace partition snapshot does not match manifest source_snapshot_id"
        )
    _validate_parent_binding(manifest, parent)
    roles = _referenced_object_roles(executor)
    required = set(roles) | _parent_object_hashes(parent)
    supplied = set(inputs.immutable_objects)
    if supplied != required:
        raise Protocol24InputStoreError(
            "immutable object set must exactly equal executor and parent references; "
            f"missing={sorted(required - supplied)}, extra={sorted(supplied - required)}"
        )
    for object_hash, payload in inputs.immutable_objects.items():
        if content_digest(payload) != object_hash:
            raise Protocol24InputStoreError(
                f"immutable object hash mismatch: {object_hash}"
            )
        if object_hash in roles:
            try:
                _validate_referenced_object(payload, roles[object_hash], object_hash)
            except Protocol22InputStoreError as exc:
                raise Protocol24InputStoreError(str(exc)) from exc
    return _PreparedProtocol24Inputs(
        workspace_payload=workspace_payload,
        artifact_policy_payload=policy_payload,
        executor_payload=executor_payload,
        parent_authority_payload=parent_payload,
    )


def _parent_object_hashes(parent: ParentAuthorityBundleV1) -> set[str]:
    return {
        parent.source_manifest_hash,
        parent.source_event_chain_hash,
        parent.source_ledger_chain_hash,
        *parent.ancestor_bundle_hashes,
    }


def _validate_parent_binding(
    manifest: RunManifestV3,
    parent: ParentAuthorityBundleV1,
) -> None:
    lineage = manifest.parent_lineage
    if (
        parent.direct_parent_run_id != lineage.direct_parent_run_id
        or parent.source_manifest_hash != lineage.direct_parent_manifest_hash
        or parent.source_terminal_event_hash
        != lineage.direct_parent_terminal_event_hash
        or parent.lineage_root_run_id != lineage.lineage_root_run_id
    ):
        raise Protocol24InputStoreError(
            "parent authority bundle does not match manifest lineage"
        )


def _validate_reference_layout(manifest: RunManifestV3) -> None:
    references = (
        manifest.workspace_partition_catalog,
        manifest.artifact_policy_catalog,
        manifest.executor_contract_catalog,
        manifest.parent_authority_bundle,
    )
    if any(not isinstance(reference, CatalogReferenceV1) for reference in references):
        raise Protocol24InputStoreError(
            "protocol-2.4 manifest has invalid catalog references"
        )
    paths = [PurePosixPath(reference.relative_path).parts for reference in references]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if (
                first == second
                or first == second[: len(first)]
                or second == first[: len(second)]
            ):
                raise Protocol24InputStoreError(
                    "protocol-2.4 catalog references alias or overlap"
                )


__all__ = (
    "Protocol24InputSet",
    "Protocol24InputStoreError",
    "ValidatedProtocol24Inputs",
    "create_protocol_24_run_store",
    "load_protocol_24_inputs",
)
