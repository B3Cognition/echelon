"""Immutable schema-4 input publication over the shared manifest-last store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    Protocol22ExecutorError,
)
from harness.re_v2.protocol_22.inputs import (
    FaultHook,
    Protocol22InputStoreError,
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
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    load_canonical_object,
)
from harness.re_v2.run_store import ReV2Paths, ReV2RunStoreError, load_run_manifest

from .adoption import ParentAuthorityBundleV2, Protocol25AdoptionError
from .artifacts import AuditEpochV1
from .model import Protocol25SchemaError, RunManifestV4
from .policies import (
    AuditTaxonomyV1,
    SemanticArtifactPolicyCatalogV1,
    SemanticExecutorContractCatalogV1,
)


class Protocol25InputStoreError(Protocol22InputStoreError):
    """Raised when immutable schema-4 inputs are unsafe or inconsistent."""


def _validate_object_mapping(values: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol25InputStoreError("immutable_objects must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        try:
            digest_value(object_hash, "Protocol25InputSet.immutable_objects key")
        except Protocol22SchemaError as exc:
            raise Protocol25InputStoreError(str(exc)) from exc
        if not isinstance(payload, bytes):
            raise Protocol25InputStoreError(
                "Protocol25InputSet immutable object payloads must be bytes"
            )
        if content_digest(payload) != object_hash:
            raise Protocol25InputStoreError(
                f"immutable object hash mismatch: {object_hash}"
            )
        if payload.startswith(TREE_OBJECT_MAGIC):
            raise Protocol25InputStoreError(
                "protocol-2.5 input objects must be blobs, not tree objects"
            )
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class Protocol25InputSet:
    workspace_partition: WorkspacePartitionCatalogV1
    artifact_policy: SemanticArtifactPolicyCatalogV1
    executor_contract: SemanticExecutorContractCatalogV1
    audit_policy: AuditTaxonomyV1
    parent_authority_bundle: ParentAuthorityBundleV2
    immutable_objects: Mapping[str, bytes]
    frozen_audit_epoch: AuditEpochV1 | None
    human_guidance: bytes | None

    def __post_init__(self) -> None:
        expected = (
            (self.workspace_partition, WorkspacePartitionCatalogV1, "workspace_partition"),
            (self.artifact_policy, SemanticArtifactPolicyCatalogV1, "artifact_policy"),
            (
                self.executor_contract,
                SemanticExecutorContractCatalogV1,
                "executor_contract",
            ),
            (self.audit_policy, AuditTaxonomyV1, "audit_policy"),
            (
                self.parent_authority_bundle,
                ParentAuthorityBundleV2,
                "parent_authority_bundle",
            ),
        )
        for value, expected_type, field in expected:
            if not isinstance(value, expected_type):
                raise Protocol25InputStoreError(
                    f"{field} must be {expected_type.__name__}"
                )
        if self.frozen_audit_epoch is not None and not isinstance(
            self.frozen_audit_epoch, AuditEpochV1
        ):
            raise Protocol25InputStoreError(
                "frozen_audit_epoch must be AuditEpochV1 or null"
            )
        if self.human_guidance is not None:
            if not isinstance(self.human_guidance, bytes):
                raise Protocol25InputStoreError("human_guidance must be bytes or null")
            _load_guidance(self.human_guidance)
        object.__setattr__(
            self,
            "immutable_objects",
            _validate_object_mapping(self.immutable_objects),
        )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol25Inputs:
    workspace_partition: WorkspacePartitionCatalogV1
    artifact_policy: SemanticArtifactPolicyCatalogV1
    executor_contract: SemanticExecutorContractCatalogV1
    audit_policy: AuditTaxonomyV1
    parent_authority_bundle: ParentAuthorityBundleV2
    immutable_objects: Mapping[str, bytes]
    frozen_audit_epoch: AuditEpochV1 | None
    human_guidance: bytes | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "immutable_objects",
            MappingProxyType(dict(sorted(self.immutable_objects.items()))),
        )

    @property
    def graph_inputs(self):  # type: ignore[no-untyped-def]
        """Expose graph authority only after all durable inputs authenticate."""
        from .graph import Protocol25GraphInputsV1

        return Protocol25GraphInputsV1(
            workspace_partition=self.workspace_partition,
            artifact_policy=self.artifact_policy,
            executor_contract=self.executor_contract,
            audit_policy=self.audit_policy,
            immutable_objects=self.immutable_objects,
            prior_semantic_object_hashes=(
                self.parent_authority_bundle.semantic_authority.object_ids
            ),
        )


@dataclass(frozen=True, slots=True)
class _PreparedProtocol25Inputs:
    workspace_payload: bytes
    artifact_policy_payload: bytes
    executor_payload: bytes
    audit_policy_payload: bytes
    parent_authority_payload: bytes
    frozen_epoch_payload: bytes | None
    guidance_payload: bytes | None


def create_protocol_25_run_store(
    run_dir: Path,
    manifest: RunManifestV4,
    inputs: Protocol25InputSet,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Publish every schema-4 authority before atomically linking run.json."""
    if not isinstance(manifest, RunManifestV4):
        raise Protocol25InputStoreError(
            "protocol-2.5 input creation requires RunManifestV4"
        )
    if not isinstance(inputs, Protocol25InputSet):
        raise Protocol25InputStoreError(
            "protocol-2.5 input creation requires Protocol25InputSet"
        )
    if manifest.run_id != run_dir.name:
        raise Protocol25InputStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    prepared = _prepare_protocol_25_inputs(manifest, inputs)
    catalogs: list[tuple[str, CatalogReferenceV1, bytes]] = [
        (
            "workspace_partition",
            manifest.workspace_partition_catalog,
            prepared.workspace_payload,
        ),
        ("artifact_policy", manifest.artifact_policy_catalog, prepared.artifact_policy_payload),
        (
            "executor_contract",
            manifest.executor_contract_catalog,
            prepared.executor_payload,
        ),
        ("audit_policy", manifest.audit_policy_catalog, prepared.audit_policy_payload),
        (
            "parent_authority",
            manifest.parent_authority_bundle,
            prepared.parent_authority_payload,
        ),
    ]
    if manifest.frozen_audit_epoch is not None:
        assert prepared.frozen_epoch_payload is not None
        catalogs.append(
            ("frozen_audit_epoch", manifest.frozen_audit_epoch, prepared.frozen_epoch_payload)
        )
    if manifest.human_guidance is not None:
        assert prepared.guidance_payload is not None
        catalogs.append(
            ("human_guidance", manifest.human_guidance, prepared.guidance_payload)
        )
    try:
        return _publish_immutable_run_inputs(
            run_dir,
            manifest,
            inputs.immutable_objects,
            tuple(catalogs),
            fault_hook,
            protocol_label="protocol-2.5",
        )
    except Protocol25InputStoreError:
        raise
    except Protocol22InputStoreError as exc:
        raise Protocol25InputStoreError(str(exc)) from exc


def load_protocol_25_inputs(
    paths: ReV2Paths,
    manifest: RunManifestV4,
) -> ValidatedProtocol25Inputs:
    """Authenticate every schema-4 input without consulting parent state."""
    if not isinstance(paths, ReV2Paths):
        raise Protocol25InputStoreError("paths must be ReV2Paths")
    if not isinstance(manifest, RunManifestV4):
        raise Protocol25InputStoreError("manifest must be RunManifestV4")
    canonical_paths = ReV2Paths.for_run(paths.root.parent)
    if paths != canonical_paths or manifest.run_id != paths.root.parent.name:
        raise Protocol25InputStoreError(
            "input paths do not match the protocol-2.5 manifest run"
        )
    try:
        authoritative = load_run_manifest(paths.root.parent)
    except ReV2RunStoreError as exc:
        raise Protocol25InputStoreError(
            f"cannot load authoritative manifest: {exc}"
        ) from exc
    if authoritative != manifest:
        raise Protocol25InputStoreError(
            "manifest argument does not equal the authoritative manifest"
        )
    if paths.inputs.is_symlink() or not paths.inputs.is_dir():
        raise Protocol25InputStoreError(
            f"protocol-2.5 input directory is unsafe or missing: {paths.inputs}"
        )
    if paths.objects.is_symlink() or not paths.objects.is_dir():
        raise Protocol25InputStoreError(
            f"protocol-2.5 object directory is unsafe or missing: {paths.objects}"
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
        artifact_policy = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.artifact_policy_catalog,
                "artifact policy",
            ),
            SemanticArtifactPolicyCatalogV1.from_json_dict,
        )
        executor = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.executor_contract_catalog,
                "executor contract",
            ),
            SemanticExecutorContractCatalogV1.from_json_dict,
        )
        audit_policy = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.audit_policy_catalog,
                "audit policy",
            ),
            AuditTaxonomyV1.from_json_dict,
        )
        parent = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.parent_authority_bundle,
                "parent authority",
            ),
            ParentAuthorityBundleV2.from_json_dict,
        )
        epoch = (
            None
            if manifest.frozen_audit_epoch is None
            else load_canonical_object(
                _read_reference(
                    paths.inputs,
                    manifest.frozen_audit_epoch,
                    "frozen audit epoch",
                ),
                AuditEpochV1.from_json_dict,
            )
        )
        guidance = (
            None
            if manifest.human_guidance is None
            else _read_reference(
                paths.inputs,
                manifest.human_guidance,
                "human guidance",
            )
        )
        if guidance is not None:
            _load_guidance(guidance)
    except (
        Protocol22InputStoreError,
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22ExecutorError,
        Protocol25SchemaError,
        Protocol25AdoptionError,
    ) as exc:
        raise Protocol25InputStoreError(
            f"invalid immutable protocol-2.5 input: {exc}"
        ) from exc

    _validate_bindings(
        manifest,
        workspace,
        artifact_policy,
        audit_policy,
        parent,
        epoch,
        guidance,
    )
    roles = _semantic_executor_roles(executor)
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
            raise Protocol25InputStoreError(str(exc)) from exc
        if content_digest(payload) != object_hash:
            raise Protocol25InputStoreError(
                f"immutable object hash mismatch: {object_hash}"
            )
        if object_hash in roles:
            try:
                _validate_referenced_object(payload, roles[object_hash], object_hash)
            except Protocol22InputStoreError as exc:
                raise Protocol25InputStoreError(str(exc)) from exc
        objects[object_hash] = payload
    return ValidatedProtocol25Inputs(
        workspace_partition=workspace,
        artifact_policy=artifact_policy,
        executor_contract=executor,
        audit_policy=audit_policy,
        parent_authority_bundle=parent,
        immutable_objects=objects,
        frozen_audit_epoch=epoch,
        human_guidance=guidance,
    )


def _prepare_protocol_25_inputs(
    manifest: RunManifestV4,
    inputs: Protocol25InputSet,
) -> _PreparedProtocol25Inputs:
    _validate_reference_layout(manifest)
    try:
        workspace_payload = canonical_json_bytes(
            inputs.workspace_partition.to_json_dict()
        )
        workspace = load_canonical_object(
            workspace_payload, WorkspacePartitionCatalogV1.from_json_dict
        )
        artifact_policy_payload = canonical_json_bytes(
            inputs.artifact_policy.to_json_dict()
        )
        artifact_policy = load_canonical_object(
            artifact_policy_payload,
            SemanticArtifactPolicyCatalogV1.from_json_dict,
        )
        executor_payload = canonical_json_bytes(inputs.executor_contract.to_json_dict())
        executor = load_canonical_object(
            executor_payload,
            SemanticExecutorContractCatalogV1.from_json_dict,
        )
        audit_policy_payload = canonical_json_bytes(inputs.audit_policy.to_json_dict())
        audit_policy = load_canonical_object(
            audit_policy_payload, AuditTaxonomyV1.from_json_dict
        )
        parent_authority_payload = canonical_json_bytes(
            inputs.parent_authority_bundle.to_json_dict()
        )
        parent = load_canonical_object(
            parent_authority_payload, ParentAuthorityBundleV2.from_json_dict
        )
        frozen_epoch_payload = (
            None
            if inputs.frozen_audit_epoch is None
            else canonical_json_bytes(inputs.frozen_audit_epoch.to_json_dict())
        )
        epoch = (
            None
            if frozen_epoch_payload is None
            else load_canonical_object(frozen_epoch_payload, AuditEpochV1.from_json_dict)
        )
        guidance_payload = inputs.human_guidance
        if guidance_payload is not None:
            _load_guidance(guidance_payload)
    except (
        TypeError,
        ValueError,
        UnicodeError,
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22ExecutorError,
        Protocol25SchemaError,
        Protocol25AdoptionError,
    ) as exc:
        raise Protocol25InputStoreError(
            f"invalid protocol-2.5 immutable input: {exc}"
        ) from exc
    if (
        workspace != inputs.workspace_partition
        or artifact_policy != inputs.artifact_policy
        or executor != inputs.executor_contract
        or audit_policy != inputs.audit_policy
        or parent != inputs.parent_authority_bundle
        or epoch != inputs.frozen_audit_epoch
    ):
        raise Protocol25InputStoreError(
            "typed protocol-2.5 inputs do not round-trip canonically"
        )
    expected = [
        (
            "workspace partition",
            manifest.workspace_partition_catalog,
            workspace_payload,
        ),
        ("artifact policy", manifest.artifact_policy_catalog, artifact_policy_payload),
        ("executor contract", manifest.executor_contract_catalog, executor_payload),
        ("audit policy", manifest.audit_policy_catalog, audit_policy_payload),
        (
            "parent authority",
            manifest.parent_authority_bundle,
            parent_authority_payload,
        ),
    ]
    if manifest.frozen_audit_epoch is not None and frozen_epoch_payload is not None:
        expected.append(
            ("frozen audit epoch", manifest.frozen_audit_epoch, frozen_epoch_payload)
        )
    if manifest.human_guidance is not None and guidance_payload is not None:
        expected.append(("human guidance", manifest.human_guidance, guidance_payload))
    for label, reference, payload in expected:
        if content_digest(payload) != reference.object_hash:
            raise Protocol25InputStoreError(f"{label} catalog hash mismatch")
    _validate_bindings(
        manifest,
        workspace,
        artifact_policy,
        audit_policy,
        parent,
        epoch,
        guidance_payload,
    )
    roles = _semantic_executor_roles(executor)
    required = set(roles) | _parent_object_hashes(parent)
    supplied = set(inputs.immutable_objects)
    if supplied != required:
        raise Protocol25InputStoreError(
            "immutable object set must exactly equal executor and parent references; "
            f"missing={sorted(required - supplied)}, extra={sorted(supplied - required)}"
        )
    for object_hash, payload in inputs.immutable_objects.items():
        if object_hash in roles:
            try:
                _validate_referenced_object(payload, roles[object_hash], object_hash)
            except Protocol22InputStoreError as exc:
                raise Protocol25InputStoreError(str(exc)) from exc
    return _PreparedProtocol25Inputs(
        workspace_payload,
        artifact_policy_payload,
        executor_payload,
        audit_policy_payload,
        parent_authority_payload,
        frozen_epoch_payload,
        guidance_payload,
    )


def _semantic_executor_roles(
    executor: SemanticExecutorContractCatalogV1,
) -> Mapping[str, frozenset[str]]:
    combined = ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(
            sorted(
                executor.inherited_catalog.entries + executor.semantic_entries,
                key=lambda entry: entry.producer_family,
            )
        ),
    )
    return _referenced_object_roles(combined)


def _parent_object_hashes(parent: ParentAuthorityBundleV2) -> set[str]:
    lower = parent.lower_authority_bundle
    return {
        lower.source_manifest_hash,
        lower.source_event_chain_hash,
        lower.source_ledger_chain_hash,
        *lower.ancestor_bundle_hashes,
        *parent.semantic_authority.object_ids,
    }


def _validate_bindings(
    manifest: RunManifestV4,
    workspace: WorkspacePartitionCatalogV1,
    artifact_policy: SemanticArtifactPolicyCatalogV1,
    audit_policy: AuditTaxonomyV1,
    parent: ParentAuthorityBundleV2,
    epoch: AuditEpochV1 | None,
    guidance: bytes | None,
) -> None:
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol25InputStoreError(
            "workspace partition snapshot does not match the run manifest"
        )
    if artifact_policy.audit_taxonomy != audit_policy:
        raise Protocol25InputStoreError(
            "artifact and audit policy catalogs disagree on taxonomy"
        )
    lineage = manifest.parent_lineage
    lower = parent.lower_authority_bundle
    if (
        lower.direct_parent_run_id != lineage.direct_parent_run_id
        or lower.source_manifest_hash != lineage.direct_parent_manifest_hash
        or lower.source_terminal_event_hash
        != lineage.direct_parent_terminal_event_hash
        or lower.lineage_root_run_id != lineage.lineage_root_run_id
    ):
        raise Protocol25InputStoreError(
            "parent authority bundle does not match manifest lineage"
        )
    if parent.source_snapshot_id != manifest.source_snapshot_id:
        raise Protocol25InputStoreError(
            "parent source snapshot does not match manifest"
        )
    if parent.selection_id != manifest.selection.identity:
        raise Protocol25InputStoreError("parent selection does not match manifest")

    semantic = parent.semantic_authority
    if manifest.run_mode == "new-audit-epoch":
        eligible = (
            parent.parent_layer in {"L1", "L2"}
            and parent.parent_state == "complete"
            and semantic.is_empty
        ) or (
            parent.parent_layer == "L3"
            and parent.parent_state in {"complete", "next_epoch_required"}
            and semantic.audit_epoch_id is not None
            and not semantic.unresolved_finding_ids
            and (
                parent.parent_state != "next_epoch_required"
                or bool(semantic.deferred_observation_ids)
            )
        )
        if not eligible or epoch is not None or guidance is not None:
            raise Protocol25InputStoreError(
                "new audit epoch inputs do not match eligible parent or optional authority"
            )
    elif manifest.run_mode == "audit-successor":
        if (
            parent.parent_layer != "L3"
            or parent.parent_state != "blocked_incomplete"
            or semantic.audit_epoch_id is not None
            or not semantic.accepted_audit_candidate_hashes
            or not semantic.unresolved_audit_target_ids
            or epoch is not None
            or guidance is None
        ):
            raise Protocol25InputStoreError(
                "audit successor inputs require retained candidates, missing targets, and guidance"
            )
    else:
        if (
            parent.parent_layer != "L3"
            or parent.parent_state != "blocked_plateau"
            or semantic.audit_epoch_id is None
            or semantic.closure_root_hash is None
            or not semantic.unresolved_finding_ids
            or epoch is None
            or epoch.identity != semantic.audit_epoch_id
            or epoch.selection_id != manifest.selection.identity
            or epoch.audit_policy_hash != audit_policy.identity
            or guidance is None
        ):
            raise Protocol25InputStoreError(
                "closure successor inputs require the exact frozen epoch, open findings, and guidance"
            )


def _load_guidance(payload: bytes) -> Mapping[str, object]:
    def decode(value: object) -> Mapping[str, object]:
        if not isinstance(value, dict) or not value:
            raise Protocol25InputStoreError(
                "human guidance must be a nonempty canonical JSON object"
            )
        return MappingProxyType(dict(value))

    try:
        return load_canonical_object(payload, decode)
    except Protocol22SchemaError as exc:
        raise Protocol25InputStoreError(f"invalid human guidance: {exc}") from exc


def _validate_reference_layout(manifest: RunManifestV4) -> None:
    references = [
        manifest.workspace_partition_catalog,
        manifest.artifact_policy_catalog,
        manifest.executor_contract_catalog,
        manifest.audit_policy_catalog,
        manifest.parent_authority_bundle,
    ]
    references.extend(
        item
        for item in (manifest.frozen_audit_epoch, manifest.human_guidance)
        if item is not None
    )
    if any(not isinstance(reference, CatalogReferenceV1) for reference in references):
        raise Protocol25InputStoreError(
            "protocol-2.5 manifest has invalid catalog references"
        )
    paths = [PurePosixPath(reference.relative_path).parts for reference in references]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if (
                first == second
                or first == second[: len(first)]
                or second == first[: len(second)]
            ):
                raise Protocol25InputStoreError(
                    "protocol-2.5 catalog references alias or overlap"
                )


__all__ = (
    "Protocol25InputSet",
    "Protocol25InputStoreError",
    "ValidatedProtocol25Inputs",
    "create_protocol_25_run_store",
    "load_protocol_25_inputs",
)
