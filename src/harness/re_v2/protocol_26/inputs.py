"""Self-contained, manifest-last protocol-2.6 input publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.inputs import (
    FaultHook,
    Protocol22InputSet,
    Protocol22InputStoreError,
    ValidatedProtocol22Inputs,
    _fault,
    _fsync_tree_directories,
    _prepare_input_destination,
    _prepare_inputs,
    _publish_manifest_last,
    _read_reference,
    _write_new_file,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1, RunManifestV2
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    load_canonical_object,
)
from harness.re_v2.protocol_24.inputs import (
    Protocol24InputSet,
    Protocol24InputStoreError,
    ValidatedProtocol24Inputs,
    _prepare_protocol_24_inputs,
    load_protocol_24_inputs,
)
from harness.re_v2.protocol_24.model import RunManifestV3
from harness.re_v2.protocol_25.inputs import (
    Protocol25InputSet,
    Protocol25InputStoreError,
    ValidatedProtocol25Inputs,
    _prepare_protocol_25_inputs,
    load_protocol_25_inputs,
)
from harness.re_v2.protocol_25.model import RunManifestV4
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
    staged_v2_run_store,
)

from .model import (
    CheckpointSelectionBundleV1,
    LayerExecutionContractV1,
    RunManifestV5,
)


LayerInputSetV1 = Protocol22InputSet | Protocol24InputSet | Protocol25InputSet
ValidatedLayerInputsV1 = (
    ValidatedProtocol22Inputs | ValidatedProtocol24Inputs | ValidatedProtocol25Inputs
)


class Protocol26InputStoreError(Protocol22InputStoreError):
    """Raised when schema-5 authority is unsafe, incomplete, or inconsistent."""


def _validated_object_mapping(
    values: Mapping[str, bytes],
    *,
    label: str,
) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol26InputStoreError(f"{label} must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        try:
            digest_value(object_hash, f"{label} key")
        except Protocol22SchemaError as exc:
            raise Protocol26InputStoreError(str(exc)) from exc
        if not isinstance(payload, bytes):
            raise Protocol26InputStoreError(f"{label} payloads must be bytes")
        if content_digest(payload) != object_hash:
            raise Protocol26InputStoreError(f"{label} hash mismatch: {object_hash}")
        if payload.startswith(TREE_OBJECT_MAGIC):
            raise Protocol26InputStoreError(f"{label} must contain blobs")
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class Protocol26InputSet:
    manifest: RunManifestV5
    layer_execution_contract: LayerExecutionContractV1
    layer_inputs: LayerInputSetV1
    checkpoint_selection: CheckpointSelectionBundleV1
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, RunManifestV5):
            raise Protocol26InputStoreError("manifest must be RunManifestV5")
        if not isinstance(self.layer_execution_contract, LayerExecutionContractV1):
            raise Protocol26InputStoreError(
                "layer_execution_contract must be LayerExecutionContractV1"
            )
        if not isinstance(self.checkpoint_selection, CheckpointSelectionBundleV1):
            raise Protocol26InputStoreError(
                "checkpoint_selection must be CheckpointSelectionBundleV1"
            )
        authority = _validated_object_mapping(
            self.authority_objects,
            label="authority_objects",
        )
        object.__setattr__(self, "authority_objects", authority)
        _validate_bindings(
            self.manifest,
            self.layer_execution_contract,
            self.layer_inputs,
            self.checkpoint_selection,
            authority,
        )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol26Inputs:
    manifest: RunManifestV5
    layer_execution_contract: LayerExecutionContractV1
    layer_inputs: ValidatedLayerInputsV1
    checkpoint_selection: CheckpointSelectionBundleV1
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authority_objects",
            MappingProxyType(dict(sorted(self.authority_objects.items()))),
        )


def create_protocol_26_run_store(
    run_dir: Path,
    manifest: RunManifestV5,
    inputs: Protocol26InputSet,
    *,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Stage and validate one self-contained schema-5 run before publication."""
    if not isinstance(manifest, RunManifestV5):
        raise Protocol26InputStoreError(
            "protocol-2.6 input creation requires RunManifestV5"
        )
    if not isinstance(inputs, Protocol26InputSet) or inputs.manifest != manifest:
        raise Protocol26InputStoreError(
            "protocol-2.6 input creation requires the exact Protocol26InputSet"
        )
    if manifest.run_id != run_dir.name:
        raise Protocol26InputStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    catalogs, layer_objects = _prepare_layer_inputs(
        inputs.layer_execution_contract.layer_manifest,
        inputs.layer_inputs,
    )
    contract_payload = canonical_json_bytes(
        inputs.layer_execution_contract.to_json_dict()
    )
    selection_payload = canonical_json_bytes(inputs.checkpoint_selection.to_json_dict())
    merged_objects = _merge_objects(layer_objects, inputs.authority_objects)
    try:
        with staged_v2_run_store(run_dir) as staged:
            staged.inputs.mkdir(mode=0o700)
            object_store = ObjectStore(staged.objects)
            for object_hash, payload in sorted(layer_objects.items()):
                if object_store.put_blob(payload) != object_hash:
                    raise Protocol26InputStoreError(
                        f"layer object publication changed identity: {object_hash}"
                    )
            for object_hash, payload in sorted(inputs.authority_objects.items()):
                if object_store.put_blob(payload) != object_hash:
                    raise Protocol26InputStoreError(
                        f"authority object publication changed identity: {object_hash}"
                    )
                _fault(fault_hook, "authority_object_written")

            for _name, reference, payload in catalogs:
                _write_catalog(staged, reference, payload)
            _fault(fault_hook, "catalogs_written")
            _write_catalog(
                staged,
                manifest.layer_execution_contract,
                contract_payload,
            )
            _write_catalog(
                staged,
                manifest.checkpoint_selection,
                selection_payload,
            )
            _fault(fault_hook, "selection_written")
            _fsync_tree_directories(staged.inputs)
            _validate_staged_bytes(
                staged,
                (
                    *catalogs,
                    (
                        "layer_execution_contract",
                        manifest.layer_execution_contract,
                        contract_payload,
                    ),
                    (
                        "checkpoint_selection",
                        manifest.checkpoint_selection,
                        selection_payload,
                    ),
                ),
                merged_objects,
            )
            _fault(fault_hook, "before_manifest_publish")
            _publish_manifest_last(staged, manifest, None)
            loaded = load_protocol_26_inputs(staged, manifest)
            if (
                loaded.layer_execution_contract != inputs.layer_execution_contract
                or loaded.checkpoint_selection != inputs.checkpoint_selection
                or loaded.authority_objects != inputs.authority_objects
            ):
                raise Protocol26InputStoreError(
                    "staged protocol-2.6 authority changed during validation"
                )
    except Protocol26InputStoreError:
        raise
    except (Protocol22InputStoreError, ReV2RunStoreError, ReV2LedgerError) as exc:
        raise Protocol26InputStoreError(str(exc)) from exc
    _fault(fault_hook, "manifest_published")
    return ReV2Paths.for_run(run_dir)


def load_protocol_26_inputs(
    paths: ReV2Paths,
    manifest: RunManifestV5,
) -> ValidatedProtocol26Inputs:
    """Authenticate schema-5 inputs using only the published child store."""
    if not isinstance(paths, ReV2Paths) or not isinstance(manifest, RunManifestV5):
        raise Protocol26InputStoreError(
            "protocol-2.6 loading requires canonical paths and RunManifestV5"
        )
    canonical = ReV2Paths.for_run(paths.root.parent)
    if paths != canonical or manifest.run_id != paths.root.parent.name:
        raise Protocol26InputStoreError(
            "input paths do not match the protocol-2.6 manifest run"
        )
    try:
        authoritative = load_run_manifest(paths.root.parent)
    except ReV2RunStoreError as exc:
        raise Protocol26InputStoreError(
            f"cannot load authoritative manifest: {exc}"
        ) from exc
    if authoritative != manifest:
        raise Protocol26InputStoreError(
            "manifest argument does not equal the authoritative manifest"
        )
    _validate_reference_layout(manifest, None)
    try:
        contract = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.layer_execution_contract,
                "layer execution contract",
            ),
            LayerExecutionContractV1.from_json_dict,
        )
        selection = load_canonical_object(
            _read_reference(
                paths.inputs,
                manifest.checkpoint_selection,
                "checkpoint selection",
            ),
            CheckpointSelectionBundleV1.from_json_dict,
        )
        layer_inputs = _load_layer_inputs(
            paths,
            contract.layer_manifest,
        )
        objects = ObjectStore(paths.objects)
        authority = {
            object_hash: objects.read_blob(object_hash)
            for object_hash in selection.copied_object_ids
        }
    except (
        Protocol22InputStoreError,
        Protocol22SchemaError,
        ReV2LedgerError,
    ) as exc:
        raise Protocol26InputStoreError(
            f"invalid immutable protocol-2.6 input: {exc}"
        ) from exc
    _validate_bindings(manifest, contract, layer_inputs, selection, authority)
    return ValidatedProtocol26Inputs(
        manifest,
        contract,
        layer_inputs,
        selection,
        authority,
    )


def _validate_bindings(
    manifest: RunManifestV5,
    contract: LayerExecutionContractV1,
    layer_inputs: LayerInputSetV1 | ValidatedLayerInputsV1,
    selection: CheckpointSelectionBundleV1,
    authority_objects: Mapping[str, bytes],
) -> None:
    inner = contract.layer_manifest
    expected_layer_types = {
        "L1": (RunManifestV2, (Protocol22InputSet, ValidatedProtocol22Inputs)),
        "L2": (RunManifestV3, (Protocol24InputSet, ValidatedProtocol24Inputs)),
        "L3": (RunManifestV4, (Protocol25InputSet, ValidatedProtocol25Inputs)),
    }
    manifest_type, input_types = expected_layer_types[manifest.target_layer]
    if type(inner) is not manifest_type or type(layer_inputs) not in input_types:
        raise Protocol26InputStoreError(
            "layer input type does not match the schema-5 target layer"
        )
    if (
        contract.target_layer != manifest.target_layer
        or inner.run_id != manifest.run_id
        or inner.created_at != manifest.created_at
        or inner.source_snapshot_id != manifest.source_snapshot_id
        or inner.source_snapshot_kind != manifest.source_snapshot_kind
        or inner.partition_manifest_id != manifest.partition_manifest_id
        or contract.identity != manifest.layer_execution_contract.object_hash
        or selection.identity != manifest.checkpoint_selection.object_hash
        or selection.source_snapshot_id != manifest.source_snapshot_id
        or selection.partition_manifest_id != manifest.partition_manifest_id
        or selection.target_layer != manifest.target_layer
        or (
            hasattr(inner, "selection")
            and selection.target_selection_id != inner.selection.identity
        )
    ):
        raise Protocol26InputStoreError(
            "schema-5 manifest, layer contract, and checkpoint selection disagree"
        )
    _validate_reference_layout(manifest, _layer_references(inner))
    selected_objects = set(selection.copied_object_ids)
    supplied_objects = set(authority_objects)
    if supplied_objects != selected_objects:
        raise Protocol26InputStoreError(
            "authority_objects must exactly equal every selected object; "
            f"missing={sorted(selected_objects - supplied_objects)}, "
            f"extra={sorted(supplied_objects - selected_objects)}"
        )
    if not set(selection.copied_receipt_ids) <= supplied_objects:
        raise Protocol26InputStoreError("selected receipt object is missing")
    if not set(selection.copied_work_item_ids) <= supplied_objects:
        raise Protocol26InputStoreError("selected work item object is missing")
    origin_evidence = {
        *selection.origin_manifest_hashes,
        *selection.origin_event_prefix_hashes,
        *selection.origin_ledger_prefix_hashes,
    }
    if not origin_evidence <= supplied_objects:
        raise Protocol26InputStoreError("selected origin evidence object is missing")
    byte_counts = {key: len(payload) for key, payload in authority_objects.items()}
    if sum(byte_counts.values()) != selection.copied_byte_count:
        raise Protocol26InputStoreError("selected copied byte count is inconsistent")
    for entry in selection.selected:
        if (
            sum(byte_counts[key] for key in entry.copied_object_ids)
            != entry.copied_byte_count
        ):
            raise Protocol26InputStoreError(
                "selected entry copied byte count is inconsistent"
            )


def _prepare_layer_inputs(
    manifest: RunManifestV2 | RunManifestV3 | RunManifestV4,
    inputs: LayerInputSetV1,
) -> tuple[tuple[tuple[str, CatalogReferenceV1, bytes], ...], Mapping[str, bytes]]:
    try:
        if type(manifest) is RunManifestV2 and type(inputs) is Protocol22InputSet:
            prepared = _prepare_inputs(manifest, inputs)
            catalogs = (
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
            )
        elif type(manifest) is RunManifestV3 and type(inputs) is Protocol24InputSet:
            prepared24 = _prepare_protocol_24_inputs(manifest, inputs)
            catalogs = (
                (
                    "workspace_partition",
                    manifest.workspace_partition_catalog,
                    prepared24.workspace_payload,
                ),
                (
                    "artifact_policy",
                    manifest.artifact_policy_catalog,
                    prepared24.artifact_policy_payload,
                ),
                (
                    "executor_contract",
                    manifest.executor_contract_catalog,
                    prepared24.executor_payload,
                ),
                (
                    "parent_authority",
                    manifest.parent_authority_bundle,
                    prepared24.parent_authority_payload,
                ),
            )
        elif type(manifest) is RunManifestV4 and type(inputs) is Protocol25InputSet:
            prepared25 = _prepare_protocol_25_inputs(manifest, inputs)
            values: list[tuple[str, CatalogReferenceV1, bytes]] = [
                (
                    "workspace_partition",
                    manifest.workspace_partition_catalog,
                    prepared25.workspace_payload,
                ),
                (
                    "artifact_policy",
                    manifest.artifact_policy_catalog,
                    prepared25.artifact_policy_payload,
                ),
                (
                    "executor_contract",
                    manifest.executor_contract_catalog,
                    prepared25.executor_payload,
                ),
                (
                    "audit_policy",
                    manifest.audit_policy_catalog,
                    prepared25.audit_policy_payload,
                ),
                (
                    "parent_authority",
                    manifest.parent_authority_bundle,
                    prepared25.parent_authority_payload,
                ),
            ]
            if manifest.frozen_audit_epoch is not None:
                assert prepared25.frozen_epoch_payload is not None
                values.append(
                    (
                        "frozen_audit_epoch",
                        manifest.frozen_audit_epoch,
                        prepared25.frozen_epoch_payload,
                    )
                )
            if manifest.human_guidance is not None:
                assert prepared25.guidance_payload is not None
                values.append(
                    (
                        "human_guidance",
                        manifest.human_guidance,
                        prepared25.guidance_payload,
                    )
                )
            catalogs = tuple(values)
        else:
            raise Protocol26InputStoreError(
                "layer inputs do not match the embedded layer manifest"
            )
    except (
        Protocol22InputStoreError,
        Protocol24InputStoreError,
        Protocol25InputStoreError,
    ) as exc:
        raise Protocol26InputStoreError(str(exc)) from exc
    _validate_reference_layout(None, tuple(reference for _, reference, _ in catalogs))
    return catalogs, inputs.immutable_objects


def _load_layer_inputs(
    paths: ReV2Paths,
    manifest: RunManifestV2 | RunManifestV3 | RunManifestV4,
) -> ValidatedLayerInputsV1:
    try:
        if isinstance(manifest, RunManifestV2):
            return load_protocol_22_inputs(
                paths,
                manifest,
                _embedded_in_outer_manifest=True,
            )
        if isinstance(manifest, RunManifestV3):
            return load_protocol_24_inputs(
                paths,
                manifest,
                _embedded_in_outer_manifest=True,
            )
        return load_protocol_25_inputs(
            paths,
            manifest,
            _embedded_in_outer_manifest=True,
        )
    except (
        Protocol22InputStoreError,
        Protocol24InputStoreError,
        Protocol25InputStoreError,
    ) as exc:
        raise Protocol26InputStoreError(str(exc)) from exc


def _merge_objects(
    layer: Mapping[str, bytes],
    authority: Mapping[str, bytes],
) -> Mapping[str, bytes]:
    merged = dict(layer)
    for object_hash, payload in authority.items():
        existing = merged.get(object_hash)
        if existing is not None and existing != payload:
            raise Protocol26InputStoreError(
                f"layer and checkpoint object conflict: {object_hash}"
            )
        merged[object_hash] = payload
    return MappingProxyType(dict(sorted(merged.items())))


def _write_catalog(
    paths: ReV2Paths,
    reference: CatalogReferenceV1,
    payload: bytes,
) -> None:
    if content_digest(payload) != reference.object_hash:
        raise Protocol26InputStoreError("catalog payload hash mismatch")
    destination = _prepare_input_destination(paths.inputs, reference)
    _write_new_file(destination, payload, mode=0o400)


def _validate_staged_bytes(
    paths: ReV2Paths,
    catalogs: tuple[tuple[str, CatalogReferenceV1, bytes], ...],
    objects: Mapping[str, bytes],
) -> None:
    store = ObjectStore(paths.objects)
    for name, reference, payload in catalogs:
        if _read_reference(paths.inputs, reference, name) != payload:
            raise Protocol26InputStoreError(f"staged catalog changed: {name}")
    for object_hash, payload in objects.items():
        if store.read_blob(object_hash) != payload:
            raise Protocol26InputStoreError(
                f"staged immutable object changed: {object_hash}"
            )


def _validate_reference_layout(
    manifest: RunManifestV5 | None,
    layer_references: tuple[CatalogReferenceV1, ...] | None,
) -> None:
    references = [] if layer_references is None else list(layer_references)
    if manifest is not None:
        references.extend(
            (manifest.layer_execution_contract, manifest.checkpoint_selection)
        )
    if any(not isinstance(reference, CatalogReferenceV1) for reference in references):
        raise Protocol26InputStoreError("protocol-2.6 catalog reference is invalid")
    paths = [PurePosixPath(reference.relative_path).parts for reference in references]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if (
                first == second
                or first == second[: len(first)]
                or second == first[: len(second)]
            ):
                raise Protocol26InputStoreError(
                    "protocol-2.6 catalog references alias or overlap"
                )


def _layer_references(
    manifest: RunManifestV2 | RunManifestV3 | RunManifestV4,
) -> tuple[CatalogReferenceV1, ...]:
    references = [
        manifest.workspace_partition_catalog,
        manifest.artifact_policy_catalog,
        manifest.executor_contract_catalog,
    ]
    if isinstance(manifest, (RunManifestV3, RunManifestV4)):
        references.append(manifest.parent_authority_bundle)
    if isinstance(manifest, RunManifestV4):
        references.append(manifest.audit_policy_catalog)
        references.extend(
            reference
            for reference in (manifest.frozen_audit_epoch, manifest.human_guidance)
            if reference is not None
        )
    return tuple(references)


__all__ = (
    "Protocol26InputSet",
    "Protocol26InputStoreError",
    "ValidatedProtocol26Inputs",
    "create_protocol_26_run_store",
    "load_protocol_26_inputs",
)
