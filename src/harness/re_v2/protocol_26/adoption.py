"""Shared typed acceptance import and frozen workspace-checkpoint adoption."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactCertificationAssessmentV2,
)
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_25.artifacts import SemanticCertificationReceiptV1
from harness.re_v2.protocol_25.ledger import Protocol25Ledger

from .inputs import ValidatedProtocol26Inputs
from .model import CheckpointSelectionEntryV1


CertificationAuthorityV1 = CertificationReceiptV2 | SemanticCertificationReceiptV1


class Protocol26AdoptionError(RuntimeError):
    """Raised when frozen checkpoint authority cannot be imported exactly."""


def _freeze_required_objects(values: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol26AdoptionError("required_objects must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        if (
            not isinstance(object_hash, str)
            or not isinstance(payload, bytes)
            or content_digest(payload) != object_hash
            or payload.startswith(TREE_OBJECT_MAGIC)
        ):
            raise Protocol26AdoptionError("required object authority is invalid")
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class FrozenAcceptancePackageV1:
    work_item: WorkItemV2
    certification: CertificationAuthorityV1
    candidate_assessment: CandidateAssessmentReceiptV1 | None
    acceptance: ArtifactAcceptanceReceiptV2
    required_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.work_item, WorkItemV2):
            raise Protocol26AdoptionError("frozen acceptance work item is invalid")
        if not isinstance(
            self.certification,
            (CertificationReceiptV2, SemanticCertificationReceiptV1),
        ):
            raise Protocol26AdoptionError("frozen certification is invalid")
        if self.candidate_assessment is not None and not isinstance(
            self.candidate_assessment, CandidateAssessmentReceiptV1
        ):
            raise Protocol26AdoptionError("frozen candidate assessment is invalid")
        if not isinstance(self.acceptance, ArtifactAcceptanceReceiptV2):
            raise Protocol26AdoptionError("frozen acceptance receipt is invalid")
        objects = _freeze_required_objects(self.required_objects)
        object.__setattr__(self, "required_objects", objects)
        certification = self.certification
        if isinstance(certification, CertificationReceiptV2):
            key = certification.certification_key
            bound = (
                key.artifact_key == self.work_item.output_key
                and key.verifier_id == self.work_item.verifier_id
                and key.verifier_version == self.work_item.verifier_version
                and key.verifier_implementation_digest
                == self.work_item.verifier_implementation_digest
            )
            artifact_hash = key.artifact_hash
            artifact_key_id = key.artifact_key.identity
        else:
            bound = certification.artifact_key_id == self.work_item.output_key.identity
            artifact_hash = certification.artifact_hash
            artifact_key_id = certification.artifact_key_id
        if (
            certification.verdict != "accepted"
            or not bound
            or self.acceptance.certification_receipt_id != certification.identity
            or self.acceptance.artifact_key != self.work_item.output_key
            or self.acceptance.artifact_key.identity != artifact_key_id
            or self.acceptance.artifact_hash != artifact_hash
            or artifact_hash not in objects
        ):
            raise Protocol26AdoptionError(
                "frozen acceptance package is not exactly cross-bound"
            )
        candidate = self.candidate_assessment
        if isinstance(certification, CertificationReceiptV2):
            requires_candidate = isinstance(
                certification.assessment,
                CompactCertificationAssessmentV2,
            )
            if requires_candidate != (candidate is not None):
                raise Protocol26AdoptionError(
                    "frozen candidate presence disagrees with certification kind"
                )
        if candidate is not None:
            required_candidate_objects = {candidate.execution_capture_hash}
            if candidate.normalized_authorial_payload_hash is not None:
                required_candidate_objects.add(
                    candidate.normalized_authorial_payload_hash
                )
            if (
                candidate.outcome != "certified"
                or candidate.work_item_id != self.work_item.work_item_id
                or candidate.artifact_hash != artifact_hash
                or candidate.certification_receipt_id != certification.identity
                or not required_candidate_objects <= set(objects)
            ):
                raise Protocol26AdoptionError(
                    "frozen candidate assessment is not exactly cross-bound"
                )
        elif isinstance(certification, SemanticCertificationReceiptV1):
            raise Protocol26AdoptionError(
                "semantic frozen acceptance requires candidate authority"
            )


@dataclass(frozen=True, slots=True)
class ImportedAcceptanceV1:
    artifact_key_id: str
    work_item_id: str
    receipt_ids: tuple[str, ...]
    object_ids: tuple[str, ...]

    @classmethod
    def from_package(
        cls,
        package: FrozenAcceptancePackageV1,
    ) -> "ImportedAcceptanceV1":
        receipts = {package.certification.identity, package.acceptance.identity}
        if package.candidate_assessment is not None:
            receipts.add(package.candidate_assessment.identity)
        return cls(
            artifact_key_id=package.acceptance.artifact_key.identity,
            work_item_id=package.work_item.work_item_id,
            receipt_ids=tuple(sorted(receipts)),
            object_ids=tuple(sorted(package.required_objects)),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_key_id": self.artifact_key_id,
            "work_item_id": self.work_item_id,
            "receipt_ids": list(self.receipt_ids),
            "object_ids": list(self.object_ids),
        }


@dataclass(frozen=True, slots=True)
class CheckpointAdoptionReportV1:
    imports: tuple[ImportedAcceptanceV1, ...]

    def __post_init__(self) -> None:
        values = tuple(self.imports)
        if any(not isinstance(item, ImportedAcceptanceV1) for item in values):
            raise Protocol26AdoptionError("checkpoint adoption report is invalid")
        keys = tuple(item.artifact_key_id for item in values)
        if len(keys) != len(set(keys)):
            raise Protocol26AdoptionError(
                "checkpoint adoption report contains duplicate artifact keys"
            )
        object.__setattr__(self, "imports", values)

    @property
    def artifact_key_ids(self) -> tuple[str, ...]:
        return tuple(item.artifact_key_id for item in self.imports)

    @property
    def work_item_ids(self) -> tuple[str, ...]:
        return tuple(item.work_item_id for item in self.imports)

    @property
    def receipt_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for item in self.imports for value in item.receipt_ids})
        )

    @property
    def object_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for item in self.imports for value in item.object_ids})
        )

    def to_json_dict(self) -> dict[str, object]:
        return {"imports": [item.to_json_dict() for item in self.imports]}


def import_typed_acceptance(
    package: FrozenAcceptancePackageV1,
    destination_objects: ObjectStore,
    destination_ledger: Protocol22Ledger,
) -> ImportedAcceptanceV1:
    """Import one exact receipt package in the established ledger order."""
    if not isinstance(package, FrozenAcceptancePackageV1):
        raise Protocol26AdoptionError("typed acceptance package is invalid")
    if not isinstance(destination_objects, ObjectStore) or not isinstance(
        destination_ledger, Protocol22Ledger
    ):
        raise Protocol26AdoptionError(
            "typed acceptance requires object-store and ledger facades"
        )
    try:
        for object_hash, payload in package.required_objects.items():
            if destination_objects.put_blob(payload) != object_hash:
                raise Protocol26AdoptionError(
                    f"copied object changed identity: {object_hash}"
                )
        if isinstance(package.certification, SemanticCertificationReceiptV1):
            if not isinstance(destination_ledger, Protocol25Ledger):
                raise Protocol26AdoptionError(
                    "semantic acceptance requires a protocol-2.5 ledger"
                )
            destination_ledger.record_semantic_certification(package.certification)
        else:
            destination_ledger.record_certification(
                package.certification,
                package.work_item,
            )
        if package.candidate_assessment is not None:
            destination_ledger.record_candidate_assessment(package.candidate_assessment)
        destination_ledger.record_artifact_acceptance(package.acceptance)
        _verify_imported_acceptance(package, destination_ledger)
    except Protocol26AdoptionError:
        raise
    except ReV2LedgerError as exc:
        raise Protocol26AdoptionError(
            f"typed acceptance import conflict: {exc}"
        ) from exc
    return ImportedAcceptanceV1.from_package(package)


def import_frozen_checkpoint_closure(
    inputs: ValidatedProtocol26Inputs,
    objects: ObjectStore,
    ledger: Protocol22Ledger,
) -> CheckpointAdoptionReportV1:
    """Import workspace checkpoints from the child's frozen local authority."""
    if not isinstance(inputs, ValidatedProtocol26Inputs):
        raise Protocol26AdoptionError(
            "checkpoint import requires ValidatedProtocol26Inputs"
        )
    imported: list[ImportedAcceptanceV1] = []
    for selection in inputs.checkpoint_selection.selected:
        if selection.source_kind != "workspace_checkpoint":
            continue
        try:
            package = _frozen_package(inputs, selection)
            imported.append(import_typed_acceptance(package, objects, ledger))
        except Protocol26AdoptionError:
            raise
        except (KeyError, ReV2LedgerError, ValueError) as exc:
            raise Protocol26AdoptionError(
                f"frozen checkpoint authority is incomplete: {exc}"
            ) from exc
    return CheckpointAdoptionReportV1(tuple(imported))


def checkpoint_adoption_report(
    inputs: ValidatedProtocol26Inputs,
    ledger: Protocol22Ledger,
) -> CheckpointAdoptionReportV1:
    """Prove every frozen workspace checkpoint already exists in the target ledger."""
    if not isinstance(inputs, ValidatedProtocol26Inputs) or not isinstance(
        ledger, Protocol22Ledger
    ):
        raise Protocol26AdoptionError(
            "checkpoint report requires validated inputs and a typed ledger"
        )
    imports: list[ImportedAcceptanceV1] = []
    try:
        for selection in inputs.checkpoint_selection.selected:
            if selection.source_kind != "workspace_checkpoint":
                continue
            package = _frozen_package(inputs, selection)
            _verify_imported_acceptance(package, ledger)
            imports.append(ImportedAcceptanceV1.from_package(package))
    except Protocol26AdoptionError:
        raise
    except (KeyError, ReV2LedgerError, ValueError) as exc:
        raise Protocol26AdoptionError(
            f"checkpoint ledger import is incomplete: {exc}"
        ) from exc
    return CheckpointAdoptionReportV1(tuple(imports))


def initialize_protocol_26_run(
    context: object,
    *,
    fault_hook: Callable[[str], None] | None = None,
) -> CheckpointAdoptionReportV1:
    """Complete the schema-5 creation transaction before normal planning."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_22.recovery import (
        Protocol22RunContext,
        protocol_22_run_lock,
    )
    if not isinstance(context, Protocol22RunContext):
        raise Protocol26AdoptionError(
            "checkpoint initialization requires a shared RE v2 run context"
        )
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol26AdoptionError("checkpoint fault hook must be callable or null")
    if not isinstance(context.event_store, EventStore):
        raise Protocol26AdoptionError("checkpoint initialization has no event store")

    with protocol_22_run_lock(context.paths):
        return _initialize_protocol_26_components(
            context.paths,
            context.event_store,
            context.object_store,
            context.ledger,
            context.clock,
            fault_hook,
        )


def initialize_protocol_26_run_store(
    run_dir: Path,
    *,
    fault_hook: Callable[[str], None] | None = None,
) -> CheckpointAdoptionReportV1:
    """Initialize frozen checkpoint authority without constructing a runtime."""
    from datetime import datetime, timezone

    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    paths = ReV2Paths.for_run(run_dir)
    manifest = load_run_manifest(run_dir)
    if not isinstance(manifest, RunManifestV5):
        raise Protocol26AdoptionError(
            "checkpoint initialization requires schema-5 protocol 2.6"
        )
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    events = EventStore(paths, protocol=protocol_26_events_for(manifest.target_layer))
    clock = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with protocol_22_run_lock(paths):
        return _initialize_protocol_26_components(
            paths,
            events,
            objects,
            ledger,
            clock,
            fault_hook,
        )


def _initialize_protocol_26_components(
    paths: object,
    event_store: object,
    object_store: object,
    ledger: object,
    clock: Callable[[], str],
    fault_hook: Callable[[str], None] | None,
) -> CheckpointAdoptionReportV1:
    """Apply one idempotent checkpoint transaction to authenticated stores."""
    from harness.re_v2.protocol_26.events import append_missing_checkpoint_events
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import load_run_manifest

    manifest = load_run_manifest(paths.root.parent)
    if not isinstance(manifest, RunManifestV5):
        raise Protocol26AdoptionError(
            "checkpoint initialization requires schema-5 protocol 2.6"
        )
    inputs = load_protocol_26_inputs(paths, manifest)
    events = event_store.replay()
    if not events:
        event_store.append(
            "run_created",
            {"run_manifest_id": manifest.run_manifest_id},
            occurred_at=manifest.created_at,
        )
        _adoption_fault(fault_hook, "run_created")
        events = event_store.replay()
    if (
        events[0].type != "run_created"
        or events[0].payload.get("run_manifest_id") != manifest.run_manifest_id
    ):
        raise Protocol26AdoptionError(
            "checkpoint run_created disagrees with outer manifest authority"
        )

    report = import_frozen_checkpoint_closure(inputs, object_store, ledger)
    _adoption_fault(fault_hook, "checkpoint_receipts_imported")
    appended = append_missing_checkpoint_events(
        inputs,
        event_store,
        ledger,
        clock,
    )
    _adoption_fault(fault_hook, "checkpoint_events_appended")
    if appended != report:
        raise Protocol26AdoptionError(
            "checkpoint receipt and event adoption reports disagree"
        )
    return report


def _adoption_fault(
    hook: Callable[[str], None] | None,
    boundary: str,
) -> None:
    if hook is not None:
        hook(boundary)


def _frozen_package(
    inputs: ValidatedProtocol26Inputs,
    selection: CheckpointSelectionEntryV1,
) -> FrozenAcceptancePackageV1:
    work_item = load_canonical_object(
        inputs.authority_objects[selection.expected_work_item_id],
        WorkItemV2.from_json_dict,
    )
    authority = selection.adopted_artifact_authority
    certification = _load_certification(
        inputs.authority_objects[authority.certification_receipt_id]
    )
    candidate = (
        None
        if authority.candidate_assessment_id is None
        else load_canonical_object(
            inputs.authority_objects[authority.candidate_assessment_id],
            CandidateAssessmentReceiptV1.from_json_dict,
        )
    )
    acceptance = load_canonical_object(
        inputs.authority_objects[authority.artifact_acceptance_receipt_id],
        ArtifactAcceptanceReceiptV2.from_json_dict,
    )
    required = {
        object_hash: inputs.authority_objects[object_hash]
        for object_hash in selection.copied_object_ids
    }
    return FrozenAcceptancePackageV1(
        work_item,
        certification,
        candidate,
        acceptance,
        required,
    )


def _load_certification(payload: bytes) -> CertificationAuthorityV1:
    try:
        return load_canonical_object(payload, CertificationReceiptV2.from_json_dict)
    except Exception:
        try:
            return load_canonical_object(
                payload,
                SemanticCertificationReceiptV1.from_json_dict,
            )
        except Exception as semantic_error:
            raise Protocol26AdoptionError(
                "frozen certification object is invalid"
            ) from semantic_error


def _verify_imported_acceptance(
    package: FrozenAcceptancePackageV1,
    ledger: Protocol22Ledger,
) -> None:
    replayed = ledger.replay()
    certification = package.certification
    if isinstance(certification, SemanticCertificationReceiptV1):
        certifications = getattr(replayed, "semantic_certifications", {})
        certification_matches = (
            certifications.get(certification.identity) == certification
        )
    else:
        certification_matches = (
            replayed.certifications.get(certification.identity) == certification
            and replayed.certification_work_items.get(certification.identity)
            == package.work_item
        )
    candidate = package.candidate_assessment
    if (
        not certification_matches
        or replayed.accepted_artifacts.get(package.acceptance.artifact_key.identity)
        != package.acceptance
        or (
            candidate is not None
            and replayed.candidate_assessments.get(candidate.identity) != candidate
        )
    ):
        raise Protocol26AdoptionError(
            "imported ledger does not equal frozen acceptance authority"
        )


__all__ = (
    "CheckpointAdoptionReportV1",
    "FrozenAcceptancePackageV1",
    "ImportedAcceptanceV1",
    "Protocol26AdoptionError",
    "checkpoint_adoption_report",
    "initialize_protocol_26_run",
    "import_frozen_checkpoint_closure",
    "import_typed_acceptance",
)
