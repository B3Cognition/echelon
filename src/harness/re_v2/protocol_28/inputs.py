"""Self-contained, manifest-last protocol-2.8 input publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from types import MappingProxyType
from typing import Mapping

from echelon.atomic_install import atomic_rename_no_replace
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.inputs import (
    FaultHook,
    Protocol22InputStoreError,
    _fsync_tree_directories,
    _publish_manifest_last,
    _read_regular_beneath,
    _write_new_file,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
)
from harness.re_v2.protocol_28.authority import (
    L3TargetProjectionCatalogV1,
    L4ClosureParentBundleV1,
    ParentAuthorityBundleV3,
)
from harness.re_v2.protocol_28.evidence import (
    SnapshotEvidenceCatalogV1,
    read_staged_shard_bytes,
)
from harness.re_v2.protocol_28.graph import (
    AcceptedExhaustiveSliceV1,
    ExhaustiveVerificationReceiptV1,
    L4RunRootV1,
    L4TargetRootV1,
)
from harness.re_v2.protocol_28.model import (
    ExhaustiveRunManifestV7,
    L4ClosureRunManifestV7,
)
from harness.re_v2.protocol_28.planning import (
    ExhaustivePlanV1,
    ExhaustiveSubjectCatalogV1,
)
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1
from harness.re_v2.run_store import ReV2Paths, ReV2RunStoreError, load_run_manifest


_RAW_EVIDENCE_MAGIC = b"re-v2-l4-raw-v1\x00"
_INPUT_FILES = {
    "parent_authority_bundle": "parent-authority-bundle.json",
    "l3_projection_catalog": "l3-target-projections.json",
    "snapshot_evidence_catalog": "snapshot-evidence-catalog.json",
    "exhaustive_subject_catalog": "exhaustive-subject-catalog.json",
    "exhaustive_policy": "exhaustive-policy.json",
    "exhaustive_plan": "exhaustive-plan.json",
    "exhaustive_request": "exhaustive-request.json",
    "closure_parent_bundle": "closure-parent-bundle.json",
    "l4_run_root": "l4-run-root.json",
    "target_roots": "l4-target-roots.json",
    "accepted_slices": "accepted-exhaustive-slices.json",
    "verification_receipts": "exhaustive-verification-receipts.json",
    "closure_request": "l4-closure-request.json",
}


class Protocol28InputError(Protocol22InputStoreError):
    """Raised when L4 inputs are incomplete, unsafe, or not self-contained."""


def _validated_objects(values: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol28InputError("authority_objects must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        try:
            digest_value(object_hash, "authority object hash")
        except Protocol22SchemaError as exc:
            raise Protocol28InputError(str(exc)) from exc
        if not isinstance(payload, bytes) or content_digest(payload) != object_hash:
            raise Protocol28InputError(f"authority object hash mismatch: {object_hash}")
        if payload.startswith(TREE_OBJECT_MAGIC):
            raise Protocol28InputError("authority objects must be immutable blobs")
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class Protocol28CreationInputs:
    manifest: ExhaustiveRunManifestV7
    parent_authority_bundle: ParentAuthorityBundleV3
    l3_projection_catalog: L3TargetProjectionCatalogV1
    snapshot_evidence_catalog: SnapshotEvidenceCatalogV1
    exhaustive_subject_catalog: ExhaustiveSubjectCatalogV1
    exhaustive_policy: ExhaustivePolicyV1
    exhaustive_plan: ExhaustivePlanV1
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        typed = (
            (self.manifest, ExhaustiveRunManifestV7, "manifest"),
            (self.parent_authority_bundle, ParentAuthorityBundleV3, "parent authority"),
            (self.l3_projection_catalog, L3TargetProjectionCatalogV1, "L3 projection catalog"),
            (self.snapshot_evidence_catalog, SnapshotEvidenceCatalogV1, "snapshot evidence"),
            (self.exhaustive_subject_catalog, ExhaustiveSubjectCatalogV1, "subject catalog"),
            (self.exhaustive_policy, ExhaustivePolicyV1, "exhaustive policy"),
            (self.exhaustive_plan, ExhaustivePlanV1, "exhaustive plan"),
        )
        for value, expected, label in typed:
            if not isinstance(value, expected):
                raise Protocol28InputError(f"{label} has invalid type")
        objects = _validated_objects(self.authority_objects)
        object.__setattr__(self, "authority_objects", objects)
        _validate_bindings(self)
        missing = _required_opaque_ids(self) - set(objects)
        if missing:
            raise Protocol28InputError(
                "required authority object is missing: " + ",".join(sorted(missing))
            )
        extra = set(objects) - _required_opaque_ids(self)
        if extra:
            raise Protocol28InputError(
                "unbound authority object is forbidden: " + ",".join(sorted(extra))
            )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol28Inputs:
    manifest: ExhaustiveRunManifestV7
    parent_authority_bundle: ParentAuthorityBundleV3
    l3_projection_catalog: L3TargetProjectionCatalogV1
    snapshot_evidence_catalog: SnapshotEvidenceCatalogV1
    exhaustive_subject_catalog: ExhaustiveSubjectCatalogV1
    exhaustive_policy: ExhaustivePolicyV1
    exhaustive_plan: ExhaustivePlanV1
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authority_objects", MappingProxyType(dict(sorted(self.authority_objects.items())))
        )


@dataclass(frozen=True, slots=True)
class Protocol28ClosureInputs:
    manifest: L4ClosureRunManifestV7
    closure_parent_bundle: L4ClosureParentBundleV1
    l4_run_root: L4RunRootV1
    target_roots: tuple[L4TargetRootV1, ...]
    accepted_slices: tuple[AcceptedExhaustiveSliceV1, ...]
    verification_receipts: tuple[ExhaustiveVerificationReceiptV1, ...]
    closure_policy_bytes: bytes
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, L4ClosureRunManifestV7):
            raise Protocol28InputError("closure manifest has invalid type")
        if not isinstance(self.closure_parent_bundle, L4ClosureParentBundleV1):
            raise Protocol28InputError("closure parent bundle has invalid type")
        if not isinstance(self.l4_run_root, L4RunRootV1):
            raise Protocol28InputError("L4 run root has invalid type")
        for values, expected, label in (
            (self.target_roots, L4TargetRootV1, "target roots"),
            (self.accepted_slices, AcceptedExhaustiveSliceV1, "accepted slices"),
            (self.verification_receipts, ExhaustiveVerificationReceiptV1, "verification receipts"),
        ):
            if not isinstance(values, (list, tuple)) or any(not isinstance(item, expected) for item in values):
                raise Protocol28InputError(f"{label} have invalid types")
        if not isinstance(self.closure_policy_bytes, bytes) or content_digest(self.closure_policy_bytes) != self.manifest.closure_policy_id:
            raise Protocol28InputError("closure policy bytes do not match manifest")
        objects = _validated_objects(self.authority_objects)
        object.__setattr__(self, "authority_objects", objects)
        _validate_closure_bindings(self)
        missing = set(self.closure_parent_bundle.immutable_object_ids) - set(objects)
        if missing:
            raise Protocol28InputError("closure authority object is missing: " + ",".join(sorted(missing)))


@dataclass(frozen=True, slots=True)
class ValidatedProtocol28ClosureInputs:
    manifest: L4ClosureRunManifestV7
    closure_parent_bundle: L4ClosureParentBundleV1
    l4_run_root: L4RunRootV1
    target_roots: tuple[L4TargetRootV1, ...]
    accepted_slices: tuple[AcceptedExhaustiveSliceV1, ...]
    verification_receipts: tuple[ExhaustiveVerificationReceiptV1, ...]
    closure_policy_bytes: bytes
    authority_objects: Mapping[str, bytes]


def _validate_closure_bindings(
    inputs: Protocol28ClosureInputs | ValidatedProtocol28ClosureInputs,
) -> None:
    manifest = inputs.manifest
    parent = inputs.closure_parent_bundle
    request = manifest.closure_request
    target_ids = tuple(sorted(item.identity for item in inputs.target_roots))
    accepted_ids = tuple(sorted(item.identity for item in inputs.accepted_slices))
    receipt_ids = tuple(sorted(item.identity for item in inputs.verification_receipts))
    if (
        manifest.closure_parent_bundle_id != parent.identity
        or manifest.l4_run_root_id != inputs.l4_run_root.identity
        or request.l4_run_root_id != inputs.l4_run_root.identity
        or request.l4_target_root_ids != target_ids
        or request.verification_receipt_ids != receipt_ids
        or parent.l4_run_root_id != inputs.l4_run_root.identity
        or parent.target_root_ids != target_ids
        or parent.accepted_slice_ids != accepted_ids
        or parent.verification_receipt_ids != receipt_ids
        or parent.selection_id != manifest.selection.identity
        or parent.source_snapshot_id != manifest.source_snapshot_id
        or parent.partition_manifest_id != manifest.partition_manifest_id
    ):
        raise Protocol28InputError("protocol-2.8 closure input authority bindings do not match")


def _validate_bindings(inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs) -> None:
    manifest = inputs.manifest
    parent = inputs.parent_authority_bundle
    l3 = inputs.l3_projection_catalog
    evidence = inputs.snapshot_evidence_catalog
    subjects = inputs.exhaustive_subject_catalog
    policy = inputs.exhaustive_policy
    plan = inputs.exhaustive_plan
    expected = (
        (manifest.source_snapshot_id, parent.source_snapshot_id),
        (manifest.partition_manifest_id, parent.partition_manifest_id),
        (manifest.selection.identity, parent.selection_id),
        (manifest.workspace_partition_catalog_id, parent.workspace_partition_catalog_id),
        (manifest.inherited_artifact_policy_catalog_id, parent.inherited_artifact_policy_catalog_id),
        (manifest.parent_authority_bundle_id, parent.identity),
        (manifest.l3_target_projection_catalog_id, l3.identity),
        (manifest.snapshot_evidence_catalog_id, evidence.identity),
        (manifest.exhaustive_policy_catalog_id, policy.identity),
        (manifest.exhaustive_plan_id, plan.identity),
        (plan.parent_authority_bundle_id, parent.identity),
        (plan.l3_projection_catalog_id, l3.identity),
        (plan.evidence_catalog_id, evidence.identity),
        (plan.subject_catalog_id, subjects.identity),
        (plan.policy_id, policy.identity),
        (l3.source_snapshot_id, parent.source_snapshot_id),
        (l3.partition_manifest_id, parent.partition_manifest_id),
        (l3.selection_id, parent.selection_id),
        (evidence.source_snapshot_id, parent.source_snapshot_id),
        (evidence.partition_catalog_id, parent.workspace_partition_catalog_id),
        (evidence.selection_id, parent.selection_id),
    )
    if any(left != right for left, right in expected):
        raise Protocol28InputError("protocol-2.8 input authority bindings do not match")
    request = manifest.exhaustive_request
    if (
        request.parent_authority_bundle_id != parent.identity
        or request.l3_target_projection_catalog_id != l3.identity
        or request.snapshot_evidence_catalog_id != evidence.identity
        or request.exhaustive_policy_catalog_id != policy.identity
    ):
        raise Protocol28InputError("exhaustive request does not authenticate staged inputs")


def _required_opaque_ids(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> set[str]:
    manifest = inputs.manifest
    parent = inputs.parent_authority_bundle
    required = {
        manifest.workspace_partition_catalog_id,
        manifest.inherited_artifact_policy_catalog_id,
        manifest.executor_catalog_id,
        manifest.attempt_policy_id,
        manifest.partition_manifest_id,
        manifest.lineage.lineage_root_manifest_hash,
        parent.l3_manifest_hash,
        parent.l3_terminal_event_hash,
        parent.frozen_epoch_id,
        *parent.lower_l0_l2_authority_ids,
    }
    for projection in inputs.l3_projection_catalog.projections:
        required.update(
            {
                projection.candidate_authority_hash,
                projection.audit_policy_id,
                projection.executor_policy_id,
                *projection.finding_ids,
                *projection.resolution_overlay_ids,
                *projection.closure_receipt_ids,
                *projection.relevant_l2_root_ids,
            }
        )
    required.update(
        item.epoch_target_entry_hash for item in inputs.l3_projection_catalog.memberships
    )
    required.add(inputs.snapshot_evidence_catalog.policy_id)
    for projection in inputs.snapshot_evidence_catalog.projections:
        required.add(projection.target_partition_id)
        required.update(projection.membership_proof_ids)
    required.update(
        item.file_record_hash
        for item in (
            *inputs.snapshot_evidence_catalog.shards,
            *inputs.snapshot_evidence_catalog.empty_receipts,
            *inputs.snapshot_evidence_catalog.nontext_dispositions,
        )
    )
    required.update(
        lower_id
        for subject in inputs.exhaustive_subject_catalog.subjects
        for lower_id in subject.lower_authority_ids
    )
    return required


def _canonical_authorities(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> tuple[tuple[str, object], ...]:
    result: list[tuple[str, object]] = [
        (inputs.parent_authority_bundle.identity, inputs.parent_authority_bundle),
        (inputs.l3_projection_catalog.identity, inputs.l3_projection_catalog),
        (inputs.snapshot_evidence_catalog.identity, inputs.snapshot_evidence_catalog),
        (inputs.exhaustive_subject_catalog.identity, inputs.exhaustive_subject_catalog),
        (inputs.exhaustive_policy.identity, inputs.exhaustive_policy),
        (inputs.exhaustive_plan.identity, inputs.exhaustive_plan),
        (inputs.manifest.exhaustive_request.identity, inputs.manifest.exhaustive_request),
        (inputs.manifest.selection.identity, inputs.manifest.selection),
        (inputs.manifest.lineage.identity, inputs.manifest.lineage),
        (inputs.manifest.budget_policy.identity, inputs.manifest.budget_policy),
    ]
    result.extend((item.identity, item) for item in inputs.l3_projection_catalog.projections)
    result.extend((item.identity, item) for item in inputs.l3_projection_catalog.memberships)
    result.extend((item.identity, item) for item in inputs.snapshot_evidence_catalog.shards)
    result.extend((item.identity, item) for item in inputs.snapshot_evidence_catalog.empty_receipts)
    result.extend((item.identity, item) for item in inputs.snapshot_evidence_catalog.nontext_dispositions)
    result.extend((item.identity, item) for item in inputs.snapshot_evidence_catalog.projections)
    result.extend((item.identity, item) for item in inputs.exhaustive_subject_catalog.subjects)
    for target in inputs.exhaustive_plan.target_plans:
        result.append((target.identity, target))
        result.append((target.coverage_ledger.identity, target.coverage_ledger))
        result.extend((item.identity, item) for item in target.entries)
        result.extend((item.identity, item) for item in target.vacancy_receipts)
    return tuple(sorted(result, key=lambda item: item[0]))


def stage_exhaustive_inputs(
    private_stage: Path,
    inputs: Protocol28CreationInputs,
    *,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Write and authenticate every L4 input in a private, non-visible run."""
    if not isinstance(inputs, Protocol28CreationInputs):
        raise Protocol28InputError("staging requires Protocol28CreationInputs")
    stage = Path(private_stage)
    if stage.exists() or stage.is_symlink():
        raise Protocol28InputError(f"private stage already exists: {stage}")
    try:
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.mkdir(mode=0o700)
        paths = ReV2Paths.for_run(stage)
        paths.root.mkdir(mode=0o700)
        paths.inputs.mkdir(mode=0o700)
        store = ObjectStore(paths.objects)
        for object_hash, payload in inputs.authority_objects.items():
            if store.put_blob(payload) != object_hash:
                raise Protocol28InputError(f"authority object identity changed: {object_hash}")
        if fault_hook is not None:
            fault_hook("authority_objects_staged")
        for expected_id, authority in _canonical_authorities(inputs):
            payload = canonical_json_bytes(authority.to_json_dict())  # type: ignore[attr-defined]
            if store.put_blob(payload) != expected_id:
                raise Protocol28InputError(f"canonical authority identity changed: {expected_id}")
        if fault_hook is not None:
            fault_hook("canonical_authorities_staged")
        for shard in inputs.snapshot_evidence_catalog.shards:
            if store.put_blob(_RAW_EVIDENCE_MAGIC + shard.raw_bytes) != shard.raw_object_hash:
                raise Protocol28InputError("snapshot evidence raw object identity changed")
        if fault_hook is not None:
            fault_hook("snapshot_evidence_staged")
        input_values = {
            "parent_authority_bundle": inputs.parent_authority_bundle,
            "l3_projection_catalog": inputs.l3_projection_catalog,
            "snapshot_evidence_catalog": inputs.snapshot_evidence_catalog,
            "exhaustive_subject_catalog": inputs.exhaustive_subject_catalog,
            "exhaustive_policy": inputs.exhaustive_policy,
            "exhaustive_plan": inputs.exhaustive_plan,
            "exhaustive_request": inputs.manifest.exhaustive_request,
        }
        for label, value in input_values.items():
            _write_new_file(
                paths.inputs / _INPUT_FILES[label],
                canonical_json_bytes(value.to_json_dict()),  # type: ignore[attr-defined]
                mode=0o400,
            )
        _fsync_tree_directories(paths.inputs)
        _fsync_tree_directories(paths.objects)
        if fault_hook is not None:
            fault_hook("inputs_fsynced")
        _load_staged(paths, inputs.manifest)
        if fault_hook is not None:
            fault_hook("before_manifest_publish")
        return paths
    except Protocol28InputError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except (OSError, Protocol22InputStoreError, ReV2LedgerError, ReV2RunStoreError) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise Protocol28InputError(str(exc)) from exc
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def stage_closure_inputs(
    private_stage: Path,
    inputs: Protocol28ClosureInputs,
    *,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Stage a zero-provider closure successor without exhaustive authority."""
    if not isinstance(inputs, Protocol28ClosureInputs):
        raise Protocol28InputError("closure staging requires Protocol28ClosureInputs")
    stage = Path(private_stage)
    if stage.exists() or stage.is_symlink():
        raise Protocol28InputError(f"private stage already exists: {stage}")
    try:
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.mkdir(mode=0o700)
        paths = ReV2Paths.for_run(stage)
        paths.root.mkdir(mode=0o700)
        paths.inputs.mkdir(mode=0o700)
        store = ObjectStore(paths.objects)
        for object_hash, payload in inputs.authority_objects.items():
            if store.put_blob(payload) != object_hash:
                raise Protocol28InputError(f"closure authority identity changed: {object_hash}")
        if fault_hook is not None:
            fault_hook("authority_objects_staged")
        authorities = (
            (inputs.closure_parent_bundle.identity, inputs.closure_parent_bundle),
            (inputs.l4_run_root.identity, inputs.l4_run_root),
            (inputs.manifest.closure_request.identity, inputs.manifest.closure_request),
            *((item.identity, item) for item in inputs.target_roots),
            *((item.identity, item) for item in inputs.accepted_slices),
            *((item.identity, item) for item in inputs.verification_receipts),
        )
        for expected_id, authority in sorted(authorities, key=lambda item: item[0]):
            if store.put_blob(canonical_json_bytes(authority.to_json_dict())) != expected_id:
                raise Protocol28InputError(f"closure canonical authority changed: {expected_id}")
        if fault_hook is not None:
            fault_hook("canonical_authorities_staged")
        if store.put_blob(inputs.closure_policy_bytes) != inputs.manifest.closure_policy_id:
            raise Protocol28InputError("closure policy identity changed")
        singleton_values = {
            "closure_parent_bundle": inputs.closure_parent_bundle.to_json_dict(),
            "l4_run_root": inputs.l4_run_root.to_json_dict(),
            "closure_request": inputs.manifest.closure_request.to_json_dict(),
        }
        collection_values = {
            "target_roots": {"items": [item.to_json_dict() for item in inputs.target_roots]},
            "accepted_slices": {"items": [item.to_json_dict() for item in inputs.accepted_slices]},
            "verification_receipts": {"items": [item.to_json_dict() for item in inputs.verification_receipts]},
        }
        for label, value in {**singleton_values, **collection_values}.items():
            _write_new_file(
                paths.inputs / _INPUT_FILES[label], canonical_json_bytes(value), mode=0o400
            )
        _fsync_tree_directories(paths.inputs)
        _fsync_tree_directories(paths.objects)
        if fault_hook is not None:
            fault_hook("inputs_fsynced")
        _load_staged_closure(paths, inputs.manifest)
        if fault_hook is not None:
            fault_hook("before_manifest_publish")
        return paths
    except Protocol28InputError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except (OSError, Protocol22InputStoreError, ReV2LedgerError, ReV2RunStoreError) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise Protocol28InputError(str(exc)) from exc
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def publish_protocol_28_run(
    private_stage: Path,
    final_run_dir: Path,
    manifest: ExhaustiveRunManifestV7 | L4ClosureRunManifestV7,
) -> ReV2Paths:
    """Publish an authenticated private run atomically, with its manifest last."""
    stage = Path(private_stage)
    final = Path(final_run_dir)
    if not isinstance(manifest, (ExhaustiveRunManifestV7, L4ClosureRunManifestV7)):
        raise Protocol28InputError("publication requires a protocol-2.8 manifest")
    if manifest.run_id != final.name:
        raise Protocol28InputError("manifest run_id does not match final run directory")
    if stage.parent.resolve() != final.parent.resolve():
        raise Protocol28InputError("private stage and final run must be siblings")
    if final.exists() or final.is_symlink():
        raise Protocol28InputError(f"final run already exists: {final}")
    paths = ReV2Paths.for_run(stage)
    try:
        if isinstance(manifest, ExhaustiveRunManifestV7):
            _load_staged(paths, manifest)
        else:
            _load_staged_closure(paths, manifest)
        _publish_manifest_last(paths, manifest, None)
        atomic_rename_no_replace(stage, final)
    except FileExistsError as exc:
        raise Protocol28InputError(f"final run already exists: {final}") from exc
    except (OSError, ValueError, Protocol22InputStoreError, ReV2LedgerError, ReV2RunStoreError) as exc:
        raise Protocol28InputError(str(exc)) from exc
    published = ReV2Paths.for_run(final)
    load_protocol_28_inputs(final)
    return published


def load_protocol_28_inputs(
    run_dir: Path,
) -> ValidatedProtocol28Inputs | ValidatedProtocol28ClosureInputs:
    """Load schema-7 exhaustive inputs using only the published child store."""
    try:
        manifest = load_run_manifest(Path(run_dir))
    except ReV2RunStoreError as exc:
        raise Protocol28InputError(f"cannot load authoritative manifest: {exc}") from exc
    paths = ReV2Paths.for_run(Path(run_dir))
    if isinstance(manifest, ExhaustiveRunManifestV7):
        return _load_staged(paths, manifest)
    if isinstance(manifest, L4ClosureRunManifestV7):
        return _load_staged_closure(paths, manifest)
    raise Protocol28InputError("published run is not a protocol-2.8 mode")


def _read_input(paths: ReV2Paths, label: str, decoder):  # type: ignore[no-untyped-def]
    try:
        payload = _read_regular_beneath(paths.inputs, _INPUT_FILES[label], label)
        return load_canonical_object(payload, decoder)
    except (Protocol22InputStoreError, Protocol22SchemaError, ValueError) as exc:
        raise Protocol28InputError(f"invalid {label.replace('_', ' ')}: {exc}") from exc


def _load_staged(
    paths: ReV2Paths,
    manifest: ExhaustiveRunManifestV7,
) -> ValidatedProtocol28Inputs:
    if paths.root.is_symlink() or not paths.root.is_dir():
        raise Protocol28InputError("protocol-2.8 staged root is unsafe or missing")
    if paths.inputs.is_symlink() or not paths.inputs.is_dir():
        raise Protocol28InputError("protocol-2.8 input directory is unsafe or missing")
    if paths.objects.is_symlink() or not paths.objects.is_dir():
        raise Protocol28InputError("protocol-2.8 object directory is unsafe or missing")
    parent = _read_input(paths, "parent_authority_bundle", ParentAuthorityBundleV3.from_json_dict)
    l3 = _read_input(paths, "l3_projection_catalog", L3TargetProjectionCatalogV1.from_json_dict)
    evidence = _read_input(paths, "snapshot_evidence_catalog", SnapshotEvidenceCatalogV1.from_json_dict)
    subjects = _read_input(paths, "exhaustive_subject_catalog", ExhaustiveSubjectCatalogV1.from_json_dict)
    policy = _read_input(paths, "exhaustive_policy", ExhaustivePolicyV1.from_json_dict)
    plan = _read_input(paths, "exhaustive_plan", ExhaustivePlanV1.from_json_dict)
    request = _read_input(paths, "exhaustive_request", type(manifest.exhaustive_request).from_json_dict)
    if request != manifest.exhaustive_request:
        raise Protocol28InputError("staged exhaustive request differs from manifest")
    store = ObjectStore(paths.objects)
    preliminary = ValidatedProtocol28Inputs(
        manifest, parent, l3, evidence, subjects, policy, plan, {}
    )
    for object_hash, _authority in _canonical_authorities(preliminary):
        try:
            store.verify(object_hash)
        except ReV2LedgerError as exc:
            label = "exhaustive plan" if object_hash == plan.identity else "canonical authority"
            raise Protocol28InputError(f"invalid {label} object: {exc}") from exc
    _validate_bindings(preliminary)
    opaque: dict[str, bytes] = {}
    for object_hash in sorted(_required_opaque_ids(preliminary)):
        try:
            opaque[object_hash] = store.read_blob(object_hash)
        except ReV2LedgerError as exc:
            raise Protocol28InputError(f"required authority object is unavailable: {exc}") from exc
    for shard in evidence.shards:
        try:
            read_staged_shard_bytes(store, shard)
        except (ReV2LedgerError, Protocol22SchemaError) as exc:
            raise Protocol28InputError(f"invalid snapshot evidence object: {exc}") from exc
    return ValidatedProtocol28Inputs(
        manifest, parent, l3, evidence, subjects, policy, plan, opaque
    )


def _read_collection(paths: ReV2Paths, label: str, decoder):  # type: ignore[no-untyped-def]
    def decode(raw: object):  # type: ignore[no-untyped-def]
        value = exact_object(raw, frozenset({"items"}), label)
        items = value["items"]
        if not isinstance(items, list):
            raise Protocol22SchemaError(f"{label}.items must be an array")
        return tuple(decoder(item) for item in items)

    try:
        payload = _read_regular_beneath(paths.inputs, _INPUT_FILES[label], label)
        return load_canonical_object(payload, decode)
    except (Protocol22InputStoreError, Protocol22SchemaError, ValueError) as exc:
        raise Protocol28InputError(f"invalid {label.replace('_', ' ')}: {exc}") from exc


def _load_staged_closure(
    paths: ReV2Paths,
    manifest: L4ClosureRunManifestV7,
) -> ValidatedProtocol28ClosureInputs:
    if paths.root.is_symlink() or not paths.root.is_dir():
        raise Protocol28InputError("protocol-2.8 closure root is unsafe or missing")
    if paths.inputs.is_symlink() or not paths.inputs.is_dir():
        raise Protocol28InputError("protocol-2.8 closure inputs are unsafe or missing")
    if paths.objects.is_symlink() or not paths.objects.is_dir():
        raise Protocol28InputError("protocol-2.8 closure objects are unsafe or missing")
    parent = _read_input(paths, "closure_parent_bundle", L4ClosureParentBundleV1.from_json_dict)
    run_root = _read_input(paths, "l4_run_root", L4RunRootV1.from_json_dict)
    request = _read_input(paths, "closure_request", type(manifest.closure_request).from_json_dict)
    if request != manifest.closure_request:
        raise Protocol28InputError("staged closure request differs from manifest")
    target_roots = _read_collection(paths, "target_roots", L4TargetRootV1.from_json_dict)
    accepted = _read_collection(paths, "accepted_slices", AcceptedExhaustiveSliceV1.from_json_dict)
    receipts = _read_collection(
        paths, "verification_receipts", ExhaustiveVerificationReceiptV1.from_json_dict
    )
    store = ObjectStore(paths.objects)
    typed = (
        (parent.identity, "closure parent bundle"),
        (run_root.identity, "L4 run root"),
        (request.identity, "closure request"),
        *((item.identity, "L4 target root") for item in target_roots),
        *((item.identity, "accepted exhaustive slice") for item in accepted),
        *((item.identity, "verification receipt") for item in receipts),
    )
    for object_hash, label in typed:
        try:
            store.verify(object_hash)
        except ReV2LedgerError as exc:
            raise Protocol28InputError(f"invalid {label} object: {exc}") from exc
    try:
        closure_policy = store.read_blob(manifest.closure_policy_id)
    except ReV2LedgerError as exc:
        raise Protocol28InputError(f"closure policy is unavailable: {exc}") from exc
    opaque: dict[str, bytes] = {}
    for object_hash in parent.immutable_object_ids:
        try:
            opaque[object_hash] = store.read_blob(object_hash)
        except ReV2LedgerError as exc:
            raise Protocol28InputError(f"closure authority object is unavailable: {exc}") from exc
    loaded = ValidatedProtocol28ClosureInputs(
        manifest, parent, run_root, target_roots, accepted, receipts, closure_policy, opaque
    )
    _validate_closure_bindings(loaded)
    return loaded


__all__ = (
    "Protocol28ClosureInputs",
    "Protocol28CreationInputs",
    "Protocol28InputError",
    "ValidatedProtocol28ClosureInputs",
    "ValidatedProtocol28Inputs",
    "load_protocol_28_inputs",
    "publish_protocol_28_run",
    "stage_closure_inputs",
    "stage_exhaustive_inputs",
)
