"""Self-contained, manifest-last protocol-2.8 input publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from types import MappingProxyType
from typing import Mapping

from echelon.atomic_install import atomic_rename_no_replace
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_activation import (
    ReviewedDiscoveryCatalogV1, validate_reviewed_discovery_catalog,
)
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
    ReviewedParentAuthorityBundleV3,
)
from harness.re_v2.protocol_28.evidence import (
    SnapshotEvidenceCatalogV1,
    read_staged_shard_bytes,
)
from harness.re_v2.protocol_28.executors import L4ExecutorCatalogV1
from harness.re_v2.protocol_28.graph import (
    AcceptedExhaustiveSliceV1,
    ExhaustiveVerificationReceiptV1,
    L4RunRootV1,
    L4TargetRootV1,
)
from harness.re_v2.protocol_28.model import (
    ExhaustiveRequestV1, SafeExhaustiveRequestV1, ReviewedExhaustiveRequestV1,
    ExhaustiveRunManifestV7,
    L4ClosureRunManifestV7,
    SafeExhaustiveRunManifestV7,
    ReviewedExhaustiveRunManifestV7,
)
from harness.re_v2.protocol_28.safe_evidence import (
    Protocol28SafeEvidenceError,
    SafeLowerAuthorityCatalogV1,
    SafeSnapshotEvidenceCatalogV1,
    validate_safe_lower_authority_catalog,
    validate_safe_snapshot_evidence_catalog,
)
from harness.re_v2.protocol_28.planning import (
    ExhaustivePlanV1,
    ExhaustiveSubjectCatalogV1,
    Protocol28PlanningError,
    validate_exhaustive_plan_coverage,
)
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1, ExhaustivePolicyV2
from harness.re_v2.protocol_25.debt import (
    Protocol25DebtError,
    ResidualDebtAcceptanceV1,
)
from harness.re_v2.run_store import ReV2Paths, ReV2RunStoreError, load_run_manifest


_RAW_EVIDENCE_MAGIC = b"re-v2-l4-raw-v1\x00"
_INPUT_FILES = {
    "parent_authority_bundle": "parent-authority-bundle.json",
    "l3_projection_catalog": "l3-target-projections.json",
    "snapshot_evidence_catalog": "snapshot-evidence-catalog.json",
    "safe_snapshot_evidence_catalog": "safe-snapshot-evidence-catalog.json",
    "safe_lower_authority_catalog": "safe-lower-authority-catalog.json",
    "reviewed_discovery_catalog": "reviewed-discovery-catalog.json",
    "exhaustive_subject_catalog": "exhaustive-subject-catalog.json",
    "exhaustive_policy": "exhaustive-policy.json",
    "executor_catalog": "l4-executor-catalog.json",
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
    executor_catalog: L4ExecutorCatalogV1
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
            (self.executor_catalog, L4ExecutorCatalogV1, "executor catalog"),
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
        protocol_28_residual_debt_acceptance(self)


@dataclass(frozen=True, slots=True)
class ValidatedProtocol28Inputs:
    manifest: ExhaustiveRunManifestV7
    parent_authority_bundle: ParentAuthorityBundleV3
    l3_projection_catalog: L3TargetProjectionCatalogV1
    snapshot_evidence_catalog: SnapshotEvidenceCatalogV1
    exhaustive_subject_catalog: ExhaustiveSubjectCatalogV1
    exhaustive_policy: ExhaustivePolicyV1
    executor_catalog: L4ExecutorCatalogV1
    exhaustive_plan: ExhaustivePlanV1
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        _validate_input_subtype(self)
        object.__setattr__(
            self, "authority_objects", MappingProxyType(dict(sorted(self.authority_objects.items())))
        )


@dataclass(frozen=True, slots=True)
class SafeProtocol28CreationInputs(Protocol28CreationInputs):
    """Creation-input subtype that requires an authenticated safe evidence view."""

    safe_snapshot_evidence_catalog: SafeSnapshotEvidenceCatalogV1
    safe_lower_authority_catalog: SafeLowerAuthorityCatalogV1

    def __post_init__(self) -> None:
        super(SafeProtocol28CreationInputs, self).__post_init__()
        if not isinstance(self.manifest, SafeExhaustiveRunManifestV7):
            raise Protocol28InputError("safe creation manifest has invalid type")
        try:
            validate_safe_snapshot_evidence_catalog(
                self.safe_snapshot_evidence_catalog,
                self.snapshot_evidence_catalog,
            )
        except Protocol28SafeEvidenceError as exc:
            raise Protocol28InputError(f"invalid safe snapshot evidence: {exc}") from exc
        if (
            self.manifest.safe_snapshot_evidence_catalog_id
            != self.safe_snapshot_evidence_catalog.identity
            or self.manifest.safe_lower_authority_catalog_id
            != self.safe_lower_authority_catalog.identity
        ):
            raise Protocol28InputError("safe authority manifest binding does not match")
        try:
            validate_safe_lower_authority_catalog(
                self.safe_lower_authority_catalog,
                self.authority_objects,
                _slice_lower_authority_ids(self.exhaustive_plan),
            )
        except Protocol28SafeEvidenceError as exc:
            raise Protocol28InputError(f"invalid safe lower authority: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ValidatedSafeProtocol28Inputs(ValidatedProtocol28Inputs):
    """Loaded, self-contained safe protocol-2.8 exhaustive inputs."""

    safe_snapshot_evidence_catalog: SafeSnapshotEvidenceCatalogV1
    safe_lower_authority_catalog: SafeLowerAuthorityCatalogV1

    def __post_init__(self) -> None:
        super(ValidatedSafeProtocol28Inputs, self).__post_init__()
        if not isinstance(self.manifest, SafeExhaustiveRunManifestV7):
            raise Protocol28InputError("safe loaded manifest has invalid type")
        try:
            validate_safe_snapshot_evidence_catalog(
                self.safe_snapshot_evidence_catalog,
                self.snapshot_evidence_catalog,
            )
        except Protocol28SafeEvidenceError as exc:
            raise Protocol28InputError(f"invalid safe snapshot evidence: {exc}") from exc
        if (
            self.manifest.safe_snapshot_evidence_catalog_id
            != self.safe_snapshot_evidence_catalog.identity
            or self.manifest.safe_lower_authority_catalog_id
            != self.safe_lower_authority_catalog.identity
        ):
            raise Protocol28InputError("safe authority manifest binding does not match")
        try:
            validate_safe_lower_authority_catalog(
                self.safe_lower_authority_catalog,
                self.authority_objects,
                _slice_lower_authority_ids(self.exhaustive_plan),
            )
        except Protocol28SafeEvidenceError as exc:
            raise Protocol28InputError(
                f"invalid safe lower authority: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class _PreliminarySafeProtocol28Inputs:
    """Parsed Safe authority used only before the opaque closure is loaded."""

    manifest: SafeExhaustiveRunManifestV7
    parent_authority_bundle: ParentAuthorityBundleV3
    l3_projection_catalog: L3TargetProjectionCatalogV1
    snapshot_evidence_catalog: SnapshotEvidenceCatalogV1
    exhaustive_subject_catalog: ExhaustiveSubjectCatalogV1
    exhaustive_policy: ExhaustivePolicyV1
    executor_catalog: L4ExecutorCatalogV1
    exhaustive_plan: ExhaustivePlanV1
    safe_snapshot_evidence_catalog: SafeSnapshotEvidenceCatalogV1
    safe_lower_authority_catalog: SafeLowerAuthorityCatalogV1


@dataclass(frozen=True, slots=True)
class ReviewedProtocol28CreationInputs(SafeProtocol28CreationInputs):
    reviewed_discovery_catalog: ReviewedDiscoveryCatalogV1


@dataclass(frozen=True, slots=True)
class ValidatedReviewedProtocol28Inputs(ValidatedSafeProtocol28Inputs):
    reviewed_discovery_catalog: ReviewedDiscoveryCatalogV1

    def __post_init__(self):
        super(ValidatedReviewedProtocol28Inputs, self).__post_init__()
        _validate_bindings(self)


@dataclass(frozen=True, slots=True)
class _PreliminaryReviewedProtocol28Inputs(_PreliminarySafeProtocol28Inputs):
    reviewed_discovery_catalog: ReviewedDiscoveryCatalogV1
    authority_objects: Mapping[str, bytes]


def _validate_input_subtype(inputs):
    """Manifest and request authority cannot be downgraded through a parent class."""
    compatible = {
        Protocol28CreationInputs: (ExhaustiveRunManifestV7, ExhaustiveRequestV1),
        ValidatedProtocol28Inputs: (ExhaustiveRunManifestV7, ExhaustiveRequestV1),
        SafeProtocol28CreationInputs: (SafeExhaustiveRunManifestV7, SafeExhaustiveRequestV1),
        ValidatedSafeProtocol28Inputs: (SafeExhaustiveRunManifestV7, SafeExhaustiveRequestV1),
        _PreliminarySafeProtocol28Inputs: (SafeExhaustiveRunManifestV7, SafeExhaustiveRequestV1),
        ReviewedProtocol28CreationInputs: (ReviewedExhaustiveRunManifestV7, ReviewedExhaustiveRequestV1),
        ValidatedReviewedProtocol28Inputs: (ReviewedExhaustiveRunManifestV7, ReviewedExhaustiveRequestV1),
        _PreliminaryReviewedProtocol28Inputs: (ReviewedExhaustiveRunManifestV7, ReviewedExhaustiveRequestV1),
    }
    expected = compatible.get(type(inputs))
    if (expected is None or type(inputs.manifest) is not expected[0]
            or type(inputs.manifest.exhaustive_request) is not expected[1]):
        raise Protocol28InputError('input subtype does not match manifest/request authority')


def residual_debt_acceptance_from_objects(
    authority_objects: Mapping[str, bytes],
) -> ResidualDebtAcceptanceV1 | None:
    """Decode the unique exact residual-debt object in an authority closure."""
    candidates: list[tuple[str, ResidualDebtAcceptanceV1]] = []
    for object_hash, payload in authority_objects.items():
        try:
            raw = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or raw.get("acceptance_policy_id") != (
            "re-v2-banzai-residual-debt-v1"
        ):
            continue
        try:
            acceptance = load_canonical_object(
                payload, ResidualDebtAcceptanceV1.from_json_dict
            )
        except (Protocol22SchemaError, Protocol25DebtError, ValueError) as exc:
            raise Protocol28InputError(
                f"invalid residual-debt acceptance authority: {object_hash}"
            ) from exc
        if acceptance.identity != object_hash:
            raise Protocol28InputError("residual-debt acceptance identity mismatch")
        candidates.append((object_hash, acceptance))
    if not candidates:
        return None
    if len(candidates) != 1:
        raise Protocol28InputError("L4 inputs contain multiple residual-debt acceptances")
    return candidates[0][1]


def protocol_28_residual_debt_acceptance(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> ResidualDebtAcceptanceV1 | None:
    """Return and authenticate the exact residual debt carried into L4, if any."""
    if not isinstance(inputs, (Protocol28CreationInputs, ValidatedProtocol28Inputs)):
        raise Protocol28InputError("protocol-2.8 debt authority input is invalid")
    acceptance = residual_debt_acceptance_from_objects(inputs.authority_objects)
    parent = inputs.parent_authority_bundle
    selected_unresolved = {
        finding_id
        for projection in inputs.l3_projection_catalog.projections
        for finding_id in projection.unresolved_finding_ids
    }
    reviewed = isinstance(inputs.manifest, ReviewedExhaustiveRunManifestV7)
    if reviewed:
        required_id = _reviewed_residual_debt_id(parent, inputs.l3_projection_catalog)
        if required_id != (acceptance.identity if acceptance else None):
            raise Protocol28InputError("residual-debt acceptance differs from authenticated Reviewed parent")
        deeper = set(parent.unresolved_deeper_finding_ids)
        accepted = set(acceptance.unresolved_finding_ids) & selected_unresolved if acceptance else set()
        if deeper & accepted or deeper | accepted != selected_unresolved:
            raise Protocol28InputError("Reviewed parent unresolved findings lack exact debt or deeper-work authority")
        selected_unresolved = accepted
    if acceptance is None:
        return None
    acceptance_hash = acceptance.identity
    if (
        acceptance.run_manifest_hash != parent.l3_manifest_hash
        or acceptance.terminal_event_hash != parent.l3_terminal_event_hash
        or acceptance.audit_epoch_id != parent.frozen_epoch_id
        or acceptance.source_snapshot_id != parent.source_snapshot_id
    ):
        raise Protocol28InputError("residual-debt acceptance does not bind the L3 parent")
    if not selected_unresolved or not set(selected_unresolved).issubset(
        acceptance.unresolved_finding_ids
    ):
        raise Protocol28InputError(
            "residual-debt acceptance does not cover selected unresolved findings"
        )
    debt_sources = {
        finding_id: group.source_id
        for group in acceptance.unresolved_by_source_and_class
        for finding_id in group.finding_ids
    }
    if any(
        debt_sources.get(finding_id) != projection.source_id
        for projection in inputs.l3_projection_catalog.projections
        for finding_id in projection.unresolved_finding_ids
        if finding_id in selected_unresolved
    ):
        raise Protocol28InputError(
            "residual-debt acceptance source ownership differs from L3 projections"
        )
    plan_entries = tuple(
        entry
        for target in inputs.exhaustive_plan.target_plans
        for entry in target.entries
    )
    if any(
        acceptance_hash not in entry.required_lower_authority_ids
        for entry in plan_entries
    ):
        raise Protocol28InputError(
            "every L4 slice must authenticate the residual-debt acceptance"
        )
    return acceptance


def protocol_28_input_quality(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> str:
    """Classify L4 inputs without allowing exhaustive evidence to erase L3 debt."""
    return (
        "partial"
        if protocol_28_residual_debt_acceptance(inputs) is not None
        else "complete"
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


def _validate_bindings(
    inputs: (
        Protocol28CreationInputs
        | ValidatedProtocol28Inputs
        | _PreliminarySafeProtocol28Inputs
    ),
) -> None:
    _validate_input_subtype(inputs)
    manifest = inputs.manifest
    parent = inputs.parent_authority_bundle
    l3 = inputs.l3_projection_catalog
    evidence = inputs.snapshot_evidence_catalog
    subjects = inputs.exhaustive_subject_catalog
    policy = inputs.exhaustive_policy
    executors = inputs.executor_catalog
    plan = inputs.exhaustive_plan
    reviewed_inputs = isinstance(inputs, (ReviewedProtocol28CreationInputs,
        ValidatedReviewedProtocol28Inputs, _PreliminaryReviewedProtocol28Inputs))
    if reviewed_inputs != isinstance(manifest, ReviewedExhaustiveRunManifestV7):
        raise Protocol28InputError('reviewed input subtype does not match manifest')
    reviewed = None
    if reviewed_inputs:
        if (inputs.reviewed_discovery_catalog.identity != manifest.reviewed_discovery_catalog_id
                or manifest.exhaustive_request.reviewed_discovery_catalog_id != manifest.reviewed_discovery_catalog_id):
            raise Protocol28InputError('reviewed authority binding mismatch')
        if not isinstance(inputs, _PreliminaryReviewedProtocol28Inputs):
            try:
                reviewed = validate_reviewed_discovery_catalog(inputs.reviewed_discovery_catalog,
                    inputs.authority_objects, l3, evidence, subjects)
            except ValueError as exc:
                raise Protocol28InputError('invalid reviewed discovery closure') from exc
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
        (manifest.executor_catalog_id, executors.identity),
        (manifest.exhaustive_plan_id, plan.identity),
        (plan.parent_authority_bundle_id, parent.identity),
        (plan.l3_projection_catalog_id, l3.identity),
        (plan.evidence_catalog_id, evidence.identity),
        (plan.subject_catalog_id, subjects.identity),
        (plan.policy_id, policy.identity),
        (policy.producer_contract_hash, executors.entry("producer").agent_contract_hash),
        (policy.verifier_contract_hash, executors.entry("verifier").agent_contract_hash),
        (l3.source_snapshot_id, parent.source_snapshot_id),
        (l3.partition_manifest_id, parent.partition_manifest_id),
        (l3.selection_id, parent.selection_id),
        (evidence.source_snapshot_id, parent.source_snapshot_id),
        (evidence.partition_catalog_id, parent.workspace_partition_catalog_id),
        (evidence.selection_id, parent.selection_id),
    )
    if any(left != right for left, right in expected):
        raise Protocol28InputError("protocol-2.8 input authority bindings do not match")
    safe_inputs = isinstance(
        inputs,
        (
            SafeProtocol28CreationInputs,
            ValidatedSafeProtocol28Inputs,
            _PreliminarySafeProtocol28Inputs,
        ),
    )
    safe_manifest = isinstance(manifest, SafeExhaustiveRunManifestV7)
    if safe_inputs != safe_manifest:
        raise Protocol28InputError("protocol-2.8 safe input subtype does not match manifest")
    if safe_inputs:
        safe_catalog = inputs.safe_snapshot_evidence_catalog
        safe_lower_catalog = inputs.safe_lower_authority_catalog
        if (
            manifest.safe_snapshot_evidence_catalog_id != safe_catalog.identity
            or manifest.exhaustive_request.safe_snapshot_evidence_catalog_id
            != safe_catalog.identity
            or manifest.safe_lower_authority_catalog_id
            != safe_lower_catalog.identity
            or manifest.exhaustive_request.safe_lower_authority_catalog_id
            != safe_lower_catalog.identity
        ):
            raise Protocol28InputError("protocol-2.8 safe authority bindings do not match")
        required_lower = _slice_lower_authority_ids(plan)
        if safe_lower_catalog.raw_authority_ids != required_lower:
            raise Protocol28InputError(
                "required lower authority does not match the safe catalogue"
            )
        if set(required_lower) - _required_opaque_ids(inputs):
            raise Protocol28InputError(
                "required lower authority is outside the authenticated opaque closure"
            )
    request = manifest.exhaustive_request
    if (
        request.parent_authority_bundle_id != parent.identity
        or request.l3_target_projection_catalog_id != l3.identity
        or request.snapshot_evidence_catalog_id != evidence.identity
        or request.exhaustive_policy_catalog_id != policy.identity
        or request.executor_catalog_id != executors.identity
        or request.exhaustive_plan_id not in {None, plan.identity}
        or (
            isinstance(inputs, Protocol28CreationInputs)
            and request.exhaustive_plan_id is None
        )
    ):
        raise Protocol28InputError("exhaustive request does not authenticate staged inputs")
    try:
        if not isinstance(inputs, _PreliminaryReviewedProtocol28Inputs):
            validate_exhaustive_plan_coverage(plan, subjects, evidence, policy, reviewed=reviewed)
    except Protocol28PlanningError as exc:
        raise Protocol28InputError(f"invalid repaired coverage: {exc}") from exc
    if isinstance(policy, ExhaustivePolicyV2):
        _validate_repaired_parent_obligations(inputs)


def _validate_repaired_parent_obligations(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> None:
    """Authenticate obligations independently of the plan's own coverage ledger."""
    parent, l3 = inputs.parent_authority_bundle, inputs.l3_projection_catalog
    plan, subjects = inputs.exhaustive_plan, inputs.exhaustive_subject_catalog
    if (
        parent.l3_projection_catalog_id != l3.identity
        or set(parent.selected_projection_ids) != {item.identity for item in l3.projections}
        or set(parent.selected_epoch_membership_ids) != {item.identity for item in l3.memberships}
        or subjects.l3_projection_catalog_id != l3.identity
        or subjects.source_snapshot_id != parent.source_snapshot_id
        or subjects.partition_manifest_id != parent.partition_manifest_id
        or plan.source_snapshot_id != parent.source_snapshot_id
        or plan.partition_manifest_id != parent.partition_manifest_id
        or plan.selection_id != parent.selection_id
    ):
        raise Protocol28InputError("repaired target authority differs from the selected parent")
    projections = {(p.source_id, p.target_kind, p.target_id): p for p in l3.projections}
    if {target.sort_key for target in plan.target_plans} != set(projections):
        raise Protocol28InputError("repaired plan omits or adds a selected L3 target")
    if any((s.source_id, s.target_kind, s.target_id) not in projections for s in subjects.subjects):
        raise Protocol28InputError("repaired subject references an unselected L3 target")
    assigned = []
    for target in plan.target_plans:
        projection = projections[target.sort_key]
        if (target.l3_projection_id != projection.identity
                or target.target_content_id != projection.target_content_id):
            raise Protocol28InputError("repaired target differs from its accepted L3 projection")
        for entry in target.entries:
            if not set(entry.assigned_finding_ids).issubset(projection.finding_ids):
                raise Protocol28InputError("repaired finding assigned outside its L3 target")
            assigned.extend(entry.assigned_finding_ids)
    if sorted(assigned) != list(parent.unresolved_deeper_finding_ids):
        raise Protocol28InputError("repaired plan does not cover required parent findings exactly once")


def _required_opaque_ids(
    inputs: (
        Protocol28CreationInputs
        | ValidatedProtocol28Inputs
        | _PreliminarySafeProtocol28Inputs
    ),
) -> set[str]:
    return set(
        protocol_28_required_authority_ids(
            inputs.manifest,
            inputs.parent_authority_bundle,
            inputs.l3_projection_catalog,
            inputs.snapshot_evidence_catalog,
            inputs.exhaustive_subject_catalog,
            inputs.executor_catalog,
            reviewed_discovery=getattr(inputs, 'reviewed_discovery_catalog', None),
        )
    )


def _reviewed_residual_debt_id(parent, l3) -> str | None:
    """Derive required debt from the immutable parent before reading its blobs."""
    if type(parent) is not ReviewedParentAuthorityBundleV3:
        raise Protocol28InputError("Reviewed inputs require explicit Reviewed parent authority")
    selected = {key for projection in l3.projections for key in projection.unresolved_finding_ids}
    deeper = set(parent.unresolved_deeper_finding_ids)
    if not deeper.issubset(selected) or (parent.residual_debt_acceptance_id is None and deeper != selected):
        raise Protocol28InputError("Reviewed parent unresolved findings require inherited debt authority")
    return parent.residual_debt_acceptance_id


def _slice_lower_authority_ids(plan: ExhaustivePlanV1) -> tuple[str, ...]:
    """Return the exact lower-authority closure serialized by any plan slice."""
    return tuple(
        sorted(
            {
                object_id
                for target in plan.target_plans
                for entry in target.entries
                for object_id in entry.required_lower_authority_ids
            }
        )
    )


def protocol_28_required_authority_ids(
    manifest: ExhaustiveRunManifestV7,
    parent: ParentAuthorityBundleV3,
    l3: L3TargetProjectionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
    subjects: ExhaustiveSubjectCatalogV1,
    executors: L4ExecutorCatalogV1,
    *, reviewed_discovery: ReviewedDiscoveryCatalogV1 | None = None,
    reviewed_residual_debt_id: str | None = None,
) -> frozenset[str]:
    """Return the exact opaque object closure before constructing input authority."""
    required = {
        manifest.workspace_partition_catalog_id,
        manifest.inherited_artifact_policy_catalog_id,
        manifest.attempt_policy_id,
        manifest.partition_manifest_id,
        manifest.lineage.lineage_root_manifest_hash,
        parent.l3_manifest_hash,
        parent.l3_terminal_event_hash,
        parent.frozen_epoch_id,
        *parent.lower_l0_l2_authority_ids,
    }
    for projection in l3.projections:
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
        item.epoch_target_entry_hash for item in l3.memberships
    )
    required.add(evidence.policy_id)
    for executor in executors.entries:
        required.update(
            {
                executor.inherited_executor_contract_hash,
                executor.agent_contract_hash,
                executor.response_schema_hash,
            }
        )
    for projection in evidence.projections:
        required.add(projection.target_partition_id)
        required.update(projection.membership_proof_ids)
    required.update(
        item.file_record_hash
        for item in (
            *evidence.shards,
            *evidence.empty_receipts,
            *evidence.nontext_dispositions,
        )
    )
    required.update(
        lower_id
        for subject in subjects.subjects
        for lower_id in subject.lower_authority_ids
    )
    if isinstance(manifest, ReviewedExhaustiveRunManifestV7):
        if reviewed_discovery is None or reviewed_discovery.identity != manifest.reviewed_discovery_catalog_id:
            raise Protocol28InputError('reviewed authority catalogue is required')
        required.update(reviewed_discovery.object_ids)
        residual_id = _reviewed_residual_debt_id(parent, l3)
        if reviewed_residual_debt_id is not None and reviewed_residual_debt_id != residual_id:
            raise Protocol28InputError('caller residual debt differs from authenticated Reviewed parent')
        if residual_id is not None:
            required.add(residual_id)
    elif reviewed_discovery is not None:
        raise Protocol28InputError('unexpected reviewed authority catalogue')
    return frozenset(required)


def required_protocol_28_authority_ids(
    inputs: Protocol28CreationInputs | ValidatedProtocol28Inputs,
) -> frozenset[str]:
    """Expose the exact opaque closure needed by a self-contained L4 child."""
    if not isinstance(inputs, (Protocol28CreationInputs, ValidatedProtocol28Inputs)):
        raise Protocol28InputError("protocol-2.8 authority closure input is invalid")
    return frozenset(_required_opaque_ids(inputs))


def _canonical_authorities(
    inputs: (
        Protocol28CreationInputs
        | ValidatedProtocol28Inputs
        | _PreliminarySafeProtocol28Inputs
    ),
) -> tuple[tuple[str, object], ...]:
    result: list[tuple[str, object]] = [
        (inputs.parent_authority_bundle.identity, inputs.parent_authority_bundle),
        (inputs.l3_projection_catalog.identity, inputs.l3_projection_catalog),
        (inputs.snapshot_evidence_catalog.identity, inputs.snapshot_evidence_catalog),
        (inputs.exhaustive_subject_catalog.identity, inputs.exhaustive_subject_catalog),
        (inputs.exhaustive_policy.identity, inputs.exhaustive_policy),
        (inputs.executor_catalog.identity, inputs.executor_catalog),
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
    if isinstance(
        inputs,
        (
            SafeProtocol28CreationInputs,
            ValidatedSafeProtocol28Inputs,
            _PreliminarySafeProtocol28Inputs,
        ),
    ):
        result.append(
            (
                inputs.safe_snapshot_evidence_catalog.identity,
                inputs.safe_snapshot_evidence_catalog,
            )
        )
        result.extend(
            (item.identity, item)
            for item in inputs.safe_snapshot_evidence_catalog.objects
        )
        result.append(
            (
                inputs.safe_lower_authority_catalog.identity,
                inputs.safe_lower_authority_catalog,
            )
        )
        result.extend(
            (item.identity, item)
            for item in inputs.safe_lower_authority_catalog.objects
        )
    result.extend((item.identity, item) for item in inputs.exhaustive_subject_catalog.subjects)
    if isinstance(inputs, (ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs, _PreliminaryReviewedProtocol28Inputs)):
        result.append((inputs.reviewed_discovery_catalog.identity, inputs.reviewed_discovery_catalog))
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
            "executor_catalog": inputs.executor_catalog,
            "exhaustive_plan": inputs.exhaustive_plan,
            "exhaustive_request": inputs.manifest.exhaustive_request,
        }
        if isinstance(inputs, SafeProtocol28CreationInputs):
            input_values["safe_snapshot_evidence_catalog"] = (
                inputs.safe_snapshot_evidence_catalog
            )
            input_values["safe_lower_authority_catalog"] = (
                inputs.safe_lower_authority_catalog
            )
        if isinstance(inputs, ReviewedProtocol28CreationInputs):
            input_values['reviewed_discovery_catalog'] = inputs.reviewed_discovery_catalog
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
    parent_type = ReviewedParentAuthorityBundleV3 if isinstance(
        manifest, ReviewedExhaustiveRunManifestV7) else ParentAuthorityBundleV3
    parent = _read_input(paths, "parent_authority_bundle", parent_type.from_json_dict)
    l3 = _read_input(paths, "l3_projection_catalog", L3TargetProjectionCatalogV1.from_json_dict)
    evidence = _read_input(paths, "snapshot_evidence_catalog", SnapshotEvidenceCatalogV1.from_json_dict)
    safe_evidence = (
        _read_input(
            paths,
            "safe_snapshot_evidence_catalog",
            SafeSnapshotEvidenceCatalogV1.from_json_dict,
        )
        if isinstance(manifest, SafeExhaustiveRunManifestV7)
        else None
    )
    safe_lower_authority = (
        _read_input(
            paths,
            "safe_lower_authority_catalog",
            SafeLowerAuthorityCatalogV1.from_json_dict,
        )
        if isinstance(manifest, SafeExhaustiveRunManifestV7)
        else None
    )
    subjects = _read_input(paths, "exhaustive_subject_catalog", ExhaustiveSubjectCatalogV1.from_json_dict)
    reviewed_catalog = (_read_input(paths, 'reviewed_discovery_catalog', ReviewedDiscoveryCatalogV1.from_json_dict)
                        if isinstance(manifest, ReviewedExhaustiveRunManifestV7) else None)
    policy = _read_input(paths, "exhaustive_policy", ExhaustivePolicyV1.from_json_dict)
    executors = _read_input(
        paths, "executor_catalog", L4ExecutorCatalogV1.from_json_dict
    )
    plan = _read_input(paths, "exhaustive_plan", ExhaustivePlanV1.from_json_dict)
    request = _read_input(paths, "exhaustive_request", type(manifest.exhaustive_request).from_json_dict)
    if request != manifest.exhaustive_request:
        raise Protocol28InputError("staged exhaustive request differs from manifest")
    store = ObjectStore(paths.objects)
    if safe_evidence is None:
        preliminary: ValidatedProtocol28Inputs = ValidatedProtocol28Inputs(
            manifest, parent, l3, evidence, subjects, policy, executors, plan, {}
        )
    else:
        preliminary_type = _PreliminaryReviewedProtocol28Inputs if reviewed_catalog is not None else _PreliminarySafeProtocol28Inputs
        preliminary = preliminary_type(
            manifest,
            parent,
            l3,
            evidence,
            subjects,
            policy,
            executors,
            plan,
            safe_evidence,
            safe_lower_authority,
            **({'reviewed_discovery_catalog': reviewed_catalog,
                'authority_objects': {key: store.read_blob(key) for key in safe_lower_authority.raw_authority_ids}}
                if reviewed_catalog is not None else {}),
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
    if safe_evidence is None:
        loaded: ValidatedProtocol28Inputs = ValidatedProtocol28Inputs(
            manifest, parent, l3, evidence, subjects, policy, executors, plan, opaque
        )
    else:
        loaded_type = ValidatedReviewedProtocol28Inputs if reviewed_catalog is not None else ValidatedSafeProtocol28Inputs
        loaded = loaded_type(
            manifest,
            parent,
            l3,
            evidence,
            subjects,
            policy,
            executors,
            plan,
            opaque,
            safe_evidence,
            safe_lower_authority,
            **({'reviewed_discovery_catalog': reviewed_catalog} if reviewed_catalog is not None else {}),
        )
    protocol_28_residual_debt_acceptance(loaded)
    return loaded


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
    "SafeProtocol28CreationInputs",
    "ValidatedProtocol28ClosureInputs",
    "ValidatedProtocol28Inputs",
    "ValidatedSafeProtocol28Inputs",
    "load_protocol_28_inputs",
    "protocol_28_input_quality",
    "protocol_28_residual_debt_acceptance",
    "publish_protocol_28_run",
    "residual_debt_acceptance_from_objects",
    "stage_closure_inputs",
    "stage_exhaustive_inputs",
)
